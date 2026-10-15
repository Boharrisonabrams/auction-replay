"""Run with python3 -B tests/test_draft_companion.py (requires Node.js)."""

import json
import re
import subprocess
from dataclasses import replace
from decimal import Decimal
from copy import deepcopy
import shutil
import tempfile
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

# Run from a checkout without installing: put src/ on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auction_replay import build_draft_companion as companion  # noqa: E402
from auction_replay import historical_price_pilot as pilot  # noqa: E402
from auction_replay import replay_auction as replay  # noqa: E402


def synthetic_fixture():
    """Portable, real engine snapshot; callers may render it without provider caches."""
    rules = replace(
        replay.LeagueRules(), teams=2, budget=14, roster_size=4, starters=("QB", "WR", "FLEX")
    )
    players = {
        key: replay.Player(key, key, pos, "NFL", bye, Decimal(points))
        for key, pos, bye, points in [
            ("a", "QB", 7, "100"),
            ("b", "QB", 8, "80"),
            ("c", "WR", 7, "120"),
            ("d", "WR", 8, "60"),
            ("e", "RB", 9, "95"),
            ("f", "K", 10, "0"),
            ("g", "RB", 11, "20"),
            ("h", "WR", 12, "10"),
            ("i", "WR", 8, "59.999999999"),
            ("j", "RB", 10, "50"),
        ]
    }
    picks = tuple(
        replay.AuctionPick(i, key, key, players[key].position, cost, team, keeper)
        for i, (key, cost, team, keeper) in enumerate(
            [
                ("c", 6, "A", False),
                ("d", 3, "B", False),
                ("e", 3, "A", False),
                ("f", 2, "B", False),
                ("g", 1, "B", False),
                ("h", 1, "A", False),
                ("a", 3, "A", True),
                ("b", 2, "B", True),
            ],
            1,
        )
    )
    weights = {k: v.projected_points + 1 for k, v in players.items()}
    selection = pilot.joint_selection(picks, rules, players, weights, "A", "probes")
    metadata = pilot.make_joint_metadata(
        picks, rules, players, weights, "A", selection, 12, 20000, {}
    )
    records = pilot.recommend_joint(picks, rules, players, weights, "A", selection, 12, 20000)
    frozen = json.loads(replay.canonical_bytes(dict(metadata=metadata, records=records)))
    return picks, rules, players, weights, frozen


def reclassify(row):
    def bound(b):
        return replay.RosterBound(
            *(Decimal(b[k]) if b[k] is not None else None for k in ("lower", "upper")),
            tuple(b["roster"]) if b["roster"] is not None else None,
            b["cost"],
            b["status"],
            b["reason"],
        )

    comparison = replay._compare_frontiers(
        row["capacity"],
        row["budget"],
        replay.BudgetFrontier(tuple(bound(b) for b in row["buy"]), **row["buy_effort"]),
        replay.BudgetFrontier((bound(row["passing"]),) * (row["budget"] + 1), **row["pass_effort"]),
    )
    row["prices"] = pilot.decision_grid(comparison, row["static_ceiling"], row["inflation_ceiling"])
    row["supported_ceiling"], row["possible_ceiling"] = (
        comparison.supported_ceiling,
        comparison.possible_ceiling,
    )


def check():
    picks, rules, players, weights, frozen = synthetic_fixture()
    build = lambda value: companion.build_payload(picks, rules, players, value, weights, {})
    data = build(frozen)
    assert len(data["decisions"]) == 6 and len(data["keepers"]) == 2
    assert any(d["disposition"] == "unrun" for d in data["decisions"])
    assert any(d["disposition"] == "excluded" for d in data["decisions"])
    assert data == build(json.loads(replay.canonical_bytes(frozen)))
    row_index = next(i for i, r in enumerate(frozen["records"]) if r["disposition"] == "evaluated")
    row = frozen["records"][row_index]
    assert any(b["roster"] for b in row["buy"])
    # Independently rescore the same forecast and explicit absence assumptions.
    for r in frozen["records"]:
        if r["disposition"] == "evaluated":
            for b in r["buy"]:
                if b["roster"]:
                    assert Decimal(b["lower"]) == replay.projected_total(
                        b["roster"],
                        players,
                        rules,
                        r["player_id"],
                        Decimal(r["forecast_factor"]),
                        r["absent_weeks"],
                    )

    def reject(change):
        altered = deepcopy(frozen)
        change(altered)
        try:
            build(altered)
        except (replay.InputError, KeyError, TypeError, ValueError):
            return
        raise AssertionError("invalid snapshot accepted")

    reject(lambda f: f["metadata"]["code_hashes"].update({"replay_auction.py": "0" * 64}))
    reject(lambda f: f["metadata"].update(snapshot_kind="probe"))
    reject(lambda f: f["metadata"].update(inputs_sha256="0" * 64))
    reject(lambda f: f["metadata"]["config"].update(objective="different"))
    reject(lambda f: f["metadata"]["source_hashes"].update({"unexpected": "0" * 64}))
    reject(lambda f: f["records"].pop(row_index))
    reject(lambda f: f["records"].append(deepcopy(f["records"][row_index])))
    reject(lambda f: f["records"][row_index].update(forecast_factor="0.9"))
    reject(lambda f: f["records"][row_index].update(absent_weeks=[3, 4]))
    reject(lambda f: f["records"][row_index].update(actual_price=4))
    witness_index = next(i for i, b in enumerate(row["buy"]) if b["roster"])
    reject(lambda f: f["records"][row_index]["buy"][witness_index].update(lower="NaN"))
    reject(lambda f: f["records"][row_index]["buy"][witness_index].update(upper="0"))
    reject(lambda f: f["records"][row_index]["buy"][witness_index].update(cost=99))
    reject(lambda f: f["records"][row_index]["buy"][witness_index]["roster"].remove("a"))
    reject(
        lambda f: f["records"][row_index]["buy"][witness_index].update(
            lower="1", upper="10000", status="unresolved"
        )
    )
    reject(lambda f: f["records"][row_index]["prices"][0].update(roster_action="invented"))
    # A missing incumbent with a finite bound is valid and remains unresolved.
    missing = deepcopy(frozen)
    changed = missing["records"][row_index]
    changed["passing"].update(
        lower=None, roster=None, cost=None, upper="10000", status="unresolved"
    )
    reclassify(changed)
    missing_data = build(missing)
    case = missing_data["decisions"][0]["cases"][changed["price_factor"]][changed["scenario"]]
    assert case["passing"]["upper"] == "10000" and case["passing"]["roster"] is None
    assert any(p["roster_action"] == "unresolved" for p in case["prices"])
    # A proved infeasible pass branch does not suppress a witnessed buy.
    infeasible = deepcopy(frozen)
    changed = infeasible["records"][row_index]
    changed["passing"].update(lower=None, upper=None, roster=None, cost=None, status="infeasible")
    reclassify(changed)
    infeasible_data = build(infeasible)
    assert any(p["roster_action"] == "buy" for p in changed["prices"])
    both_infeasible = deepcopy(infeasible)
    changed = both_infeasible["records"][row_index]
    for b in changed["buy"]:
        b.update(lower=None, upper=None, roster=None, cost=None, status="infeasible")
    reclassify(changed)
    both_infeasible_data = build(both_infeasible)
    assert all(p["roster_action"] == "infeasible" for p in changed["prices"])
    # Exact tiny Decimal gaps and ties are decided in Python, never rounded JS math.
    low = replay.RosterBound(Decimal("1"), Decimal("1"), ("a",), 0, "optimal", None)
    high = replace(low, lower=Decimal("1.000000000001"), upper=Decimal("1.000000000001"))
    for bought, expected in ((high, "buy"), (low, "pass")):
        c = replay._compare_frontiers(
            1,
            1,
            replay.BudgetFrontier((bought, bought), 0, 1, False),
            replay.BudgetFrontier((low, low), 0, 1, False),
        )
        assert c.prices[0].decision == expected
    html = companion.render_html(dict(data, test_string="</script><script>alert(1)</script>"))
    assert "</script><script>alert(1)</script>" not in html and "\\u003c/script>" in html
    assert "<!--PAYLOAD-->" not in html
    logic = re.search(r'<script id="calculation">(.*?)</script>', html, re.S)[1]
    assertions = r"""
const assert = require('node:assert/strict');
const dataSets = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
let count = 0;
for (const data of dataSets) for (const d of data.decisions) {
  for (const byPerformance of Object.values(d.cases)) for (const c of Object.values(byPerformance)) {
    for (const price of c.prices) {
      const result = assessBid(d,c,String(price.price));
      assert.equal(result.action,price.roster_action);
      assert.equal(result.reason,price.reason);
      if (result.buy.roster) assert.ok(result.buy.cost + price.price <= d.budget);
      count++;
    }
    for (const invalid of ['', ' ', '-1', '0', '1.5', 'Infinity', 'NaN', String(d.cash_cap+1)])
      assert.ok(assessBid(d,c,invalid).error);
  }
  if (!Object.keys(d.cases).length) assert.ok(assessBid(d,undefined,'1').error);
}
const d={cash_cap:1,budget:1}, b={lower:'1',upper:'1',cost:0,roster:['a'],status:'optimal'};
for(const action of ['buy','pass']) {
 const c={buy:[[0,b]],passing:b,prices:[{price:1,roster_action:action,reason:'Decimal proof'}]};
 assert.equal(assessBid(d,c,'1').action,action);
}
console.log(`PASS: ${count} Python/browser proof decisions; invalid bids and missing states`);
"""
    subprocess.run(
        ["node", "-e", logic + assertions],
        input=json.dumps([data, missing_data, infeasible_data, both_infeasible_data]),
        text=True,
        check=True,
    )
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "companion.html"
        target.write_text("previous trusted result")
        source = Path(directory) / "snapshot.json"
        stale = deepcopy(frozen)
        stale["metadata"]["snapshot_kind"] = "probe"
        source.write_text(json.dumps(stale))
        with (
            patch("sys.argv", ["builder", "--input", str(source), "--output", str(target)]),
            patch.object(
                pilot, "load_pilot", return_value=(picks, rules, players, weights, {}, {})
            ),
            patch.object(pilot, "policy_source_hashes", return_value={}),
        ):
            assert companion.main() == 1
        assert target.read_text() == "previous trusted result"
    print(
        "PASS: portable state coverage, source identity, weekly witness validation, null states, atomic preservation"
    )


def local_cache_check(path=companion.JOINT_INPUT):
    picks, rules, players, weights, *_ = pilot.load_pilot()
    frozen = json.loads(path.read_text())
    data = companion.build_payload(picks, rules, players, frozen, weights)
    assert len(data["decisions"]) == 182 and len(data["keepers"]) == 14 and data["final_cash"] == 26
    puka = next(d for d in data["decisions"] if d["pick"] == 14)
    assert puka["budget"] == 174 and puka["cash_cap"] == 162 and puka["history_count"] == 13
    downs = next(d for d in data["decisions"] if d["pick"] == 129)
    assert downs["cash_cap"] == 8 and downs["disposition"] == "excluded" and not downs["cases"]
    assert all(
        s["pick"] < d["pick"]
        for d in data["decisions"]
        for s in data["sales"][: d["history_count"]]
    )
    assert all("actual_price" not in d and "actual_buyer" not in d for d in data["decisions"])
    assert all("points" not in s for s in data["sales"])
    assert data["preparation"]["actionable"] is False and data["preparation"]["cash"] == 199
    print(
        "PASS: private-cache integration; 182 states, 14 keepers, $26 final cash, current code/source binding"
    )


class DraftCompanionChecks(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("node"), "Node.js is required for the browser-calculation checks"
    )
    def test_companion(self):
        check()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-cache", type=Path, nargs="?", const=companion.JOINT_INPUT)
    args = parser.parse_args()
    check()
    if args.local_cache is not None:
        local_cache_check(args.local_cache)
