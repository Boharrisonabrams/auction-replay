"""Runnable check: buy useful bye coverage without changing the starting core."""
from dataclasses import replace
from decimal import Decimal
import json
import tempfile
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

# Run from a checkout without installing: put src/ on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auction_replay import replay_auction as replay  # noqa: E402
from auction_replay import bench_coverage as bench  # noqa: E402


def check():
    rules = replace(replay.LeagueRules(), roster_size=4, starters=("QB", "WR", "FLEX"))
    players = {key: replay.Player(key, key, pos, "NFL", bye, Decimal(points))
               for key, pos, bye, points in [
                   ("q", "QB", 7, 340), ("w", "WR", 8, 170),
                   ("r", "RB", 9, 170), ("filler", "QB", 7, 0),
                   ("backup", "QB", 8, 170), ("same_bye", "QB", 7, 200),
                   ("expensive", "QB", 8, 300), ("flex", "TE", 10, 60)]}
    prices = dict(q=1, w=1, r=1, filler=1, backup=2, same_bye=2, expensive=20, flex=2)
    seed = ("q", "w", "r", "filler")
    fixed = ("q",)
    candidates = set(players) - set(fixed)
    before = replay.projected_total(seed, players, rules)
    with patch.object(bench.pilot, "load_outcomes", side_effect=AssertionError("future outcomes read")):
        got = bench.improve_bench(seed, fixed, candidates, prices, players, rules, 4)
    assert set(got["roster"]) == {"q", "w", "r", "backup"}, got
    assert Decimal(got["projected_points"]) == before + 10
    assert got["cost"] == 4 and len(got["swaps"]) == 1
    assert set(got["protected"]) == {"q", "w", "r"}
    assert got == bench.improve_bench(seed, fixed, reversed(sorted(candidates)), prices, players, rules, 4)
    pair = dict(seed=dict(roster=seed), repaired=got)
    record = dict(pick=1, player_id="w", price_factor="1", probe_price=1,
                  disposition="evaluated", buy=pair, **{"pass": pair})
    actual = {(p, w): Decimal(2) for p in players for w in range(1, 18)}
    with patch.object(bench.pilot, "load_outcomes", return_value=(actual, actual, {})):
        evaluated, _ = bench.evaluate([record], players, rules, {})
    assert evaluated[0]["buy"]["repaired"]["core"]["points"] > evaluated[0]["buy"]["seed"]["core"]["points"]
    actual.pop(("backup", 7))
    with patch.object(bench.pilot, "load_outcomes", return_value=(actual, actual, {})):
        missing, _ = bench.evaluate([record], players, rules, {})
    assert missing[0]["buy"]["repaired"]["core"]["points"] is None
    assert missing[0]["buy"]["repaired"]["core"]["missing"]
    # A kept bench player is immutable; exact cash leaves the original filler.
    assert not bench.improve_bench(seed, seed, (), {}, players, rules, 0)["swaps"]
    assert not bench.improve_bench(seed, fixed, candidates, prices, players, rules, 3)["swaps"]
    # If the quarterback backup is unavailable, a TE can cover RB/WR FLEX byes.
    flex = bench.improve_bench(seed, fixed, candidates - {"backup"}, prices, players, rules, 4)
    assert "flex" in flex["roster"] and Decimal(flex["projected_points"]) > before
    for roster, held, pool, quote, budget in [
        (("q", "w", "r", "r"), fixed, candidates, prices, 4),
        (seed, ("missing",), candidates, prices, 4),
        (seed, fixed, candidates - {"filler"}, prices, 4),
        (seed, fixed, candidates, dict(prices, backup=-1), 4),
        (seed, fixed, candidates, prices, True),
        (seed, fixed, candidates, prices, 2),
    ]:
        try:
            bench.improve_bench(roster, held, pool, quote, players, rules, budget)
        except replay.InputError:
            pass
        else:
            raise AssertionError("invalid repair input accepted")
    # The entrypoint must persist the rosters before touching actual outcomes.
    for mutate in (False, True):
        with tempfile.TemporaryDirectory(dir=bench.pilot.ROOT) as directory:
            root = Path(directory)
            source = root / "seed.json"
            source.write_text(json.dumps(dict(metadata=dict(team="A"))))
            output = root / "output"
            frozen_path = output / "rosters.json"

            def outcomes(*args):
                assert json.loads(frozen_path.read_text())["records"] == []
                if mutate:
                    frozen_path.write_text("changed during evaluation")
                return [], {}

            with patch.object(bench.pilot, "load_pilot", return_value=((), rules, players, {}, {}, {})), \
                 patch.object(bench.companion, "DEFAULT_INPUT", source), \
                 patch.object(bench.companion, "build_payload"), \
                 patch.object(bench, "study", return_value=[]), \
                 patch.object(bench, "evaluate", side_effect=outcomes):
                try:
                    bench.main(output)
                except replay.InputError as error:
                    assert mutate and "frozen bench rosters changed" in str(error)
                else:
                    assert not mutate
                    assert json.loads((output / "evaluation.json").read_text())["roster_sha256"] == replay._file_hash(frozen_path)
                assert (output / "evaluation.json").exists() == (not mutate)
    print("Bench coverage, cash, fixed players, FLEX, determinism, input, and freeze checks passed")


class BenchCoverageChecks(unittest.TestCase):
    def test_bench_coverage(self):
        check()


if __name__ == "__main__":
    check()
