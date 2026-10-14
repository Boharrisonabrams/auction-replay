"""Portable arithmetic and state-contract checks for the draft-day worksheet."""
import re
import shutil
import subprocess
import unittest
from tempfile import TemporaryDirectory
import sys
from pathlib import Path

# Run from a checkout without installing: put src/ on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auction_replay.build_draft_day import load  # noqa: E402

TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'


def check():
    html = (TEMPLATES/'draft-day.html').read_text()
    core = re.search(r'<script id="calculation">(.*?)</script>', html, re.S)[1]
    cases = r'''
const assert = require('node:assert/strict');
const positions=['QB','RB','RB','WR','WR','TE','RB','K','DEF','RB','WR','QB','TE','WR'];
const pool=Object.fromEntries(positions.map((pos,i)=>['p'+i,{pos,points:i<7?100:9999}]));
const rows=positions.map((_,i)=>({name:'p'+i,cost:i===0?1:i===1?78:10,owned:i===0}));
const a=analyze(rows,pool,200,[],1,1);
assert.equal(a.total,199); assert.equal(a.ceiling,79); assert.equal(a.points,700);
assert.equal(a.legalMax,187); assert.equal(a.open,13); assert.equal(a.errors.length,0);
const stressed=analyze(rows,pool,200,[],1,1.2);
assert.equal(stressed.total,223); assert.equal(stressed.ceiling,55);
const bad=structuredClone(rows);bad[2].name='p1';assert.match(analyze(bad,pool,200,[],1,1).errors.join(' '),/Duplicate/);
bad[2].name='p3';assert.match(analyze(bad,pool,200,[],1,1).errors.join(' '),/RB2/);
assert.match(analyze(rows,pool,200,['p1'],1,1).errors.join(' '),/unavailable/);
const negative=structuredClone(rows);negative[4].cost=-1;assert.ok(analyze(negative,pool,200,[],1,1).errors.length);
const missing=structuredClone(rows);missing[4].name='';assert.ok(analyze(missing,pool,200,[],1,1).errors.length);
missing[4].name='__proto__';assert.ok(analyze(missing,pool,200,[],1,1).errors.length);
const invalid=structuredClone(rows);invalid[4].cost=null;assert.ok(analyze(invalid,pool,200,[],1,1).errors.length);
const s={version:1,source:'abc',budget:200,target:1,stress:1,owned:[true,...Array(13).fill(false)],plans:[structuredClone(rows),structuredClone(rows)],unavailable:[],confirmed:false,quote:''};
assert.equal(validState(s,'abc'),true);assert.equal(validState(s,'different'),false);
const unfinished=structuredClone(s);unfinished.plans[0][2].cost=-1.5;assert.equal(validState(unfinished,'abc'),true);assert.ok(analyze(unfinished.plans[0],pool,200,[],1,1).errors.length);
s.plans[1][0].cost=20;syncOwned(s);assert.equal(s.plans[1][0].cost,1);
s.plans[0][1].name='p4';s.plans[0][1].cost=42;s.owned[1]=true;syncOwned(s);
assert.equal(s.plans[1][1].name,'p4');assert.equal(s.plans[1][1].cost,42);
assert.equal(validState({...s,budget:-200},'abc'),false);
assert.equal(validState({...s,stress:Infinity},'abc'),false);
const end=structuredClone(rows).map(r=>({...r,owned:true}));assert.equal(analyze(end,pool,200,[],1,1).legalMax,0);
const saved=structuredClone(s);saved.quote='69';saved.confirmed=true;saved.plans[1][1].cost=999;
const restored=readState(saved,'abc');assert.equal(restored.quote,'');assert.equal(restored.confirmed,false);
assert.equal(restored.plans[1][1].cost,42);assert.equal(restored.plans[1][1].name,'p4');assert.equal(restored.owned[1],true);
assert.equal(saved.quote,'69');assert.equal(saved.plans[1][1].cost,999); // Adoption must not mutate its candidate.
let current=restored;const beforeReject=JSON.stringify(current);
assert.throws(()=>{current=readState({...saved,source:'wrong'},'abc');});assert.equal(JSON.stringify(current),beforeReject);
assert.throws(()=>readState({...saved,plans:[]},'abc'));
restored.quote='90';restored.confirmed=true;const undone=readState(restored,'abc');assert.equal(undone.quote,'');assert.equal(undone.confirmed,false);
console.log('Draft-day calculation and backup checks passed');
'''
    subprocess.run(['node','-e',core+'\n'+cases],check=True)
    with TemporaryDirectory() as directory:
        source=Path(directory)/'source.csv'
        source.write_text('Player,Pos,DS Proj\nExample,RB,200\n')
        assert load(source,['Player','Pos','DS Proj'])[0]['Player']=='Example'
        for content in ['Player,Pos\nExample,RB\n', 'Player,Pos,DS Proj\nExample,RB\n', 'Player,Pos,DS Proj\nExample,RB,200\nExample,RB,201\n']:
            source.write_text(content)
            try: load(source,['Player','Pos','DS Proj'])
            except ValueError: pass
            else: raise AssertionError('Malformed or ambiguous export was accepted')
    print('Draft-day CSV validation checks passed')


class DraftDayChecks(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for the worksheet calculation checks')
    def test_draft_day(self):
        check()


if __name__ == '__main__': check()
