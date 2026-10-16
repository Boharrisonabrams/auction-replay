"""Check what other code relies on from auction_replay.replay_auction.

The other modules, the tests, and the console scripts reach the replay engine through
replay_auction. These checks pin that contract: the names it provides, what patching one
of them does, every console script target, and the decisions for the synthetic league.
They also check that the code hashes cover every module of the engine, not only
replay_auction.py.

Run from the repository root: python3 -B tests/test_replay_compatibility.py
"""

import json
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict
from importlib.metadata import EntryPoint
from io import StringIO
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "examples" / "synthetic"

# Run from a checkout without installing: put src/ on the import path.
sys.path.insert(0, str(ROOT / "src"))

from auction_replay import benchmark  # noqa: E402
from auction_replay import historical_price_pilot as pilot  # noqa: E402
from auction_replay import replay_auction as replay  # noqa: E402

# Every top-level name that replay_auction.py defined when it held the whole engine.
DEFINED_NAMES = frozenset(
    """
    AuctionPick AuctionState BudgetFrontier DECISION_FIELDS DEFAULT_RELAXATION_LIMIT
    EVALUATION_FIELDS InputError LeagueRules MarketMoment Nomination NomineeComparison
    NomineeScenario POSITIONS Player PositionalFrontier PriceComparison RosterBound TeamState
    apply_sale baseline_ceiling canonical_bytes compare_nominee completion_frontier
    decision_rows evaluate_roster final_state future_prices inflation_prices initial_state
    legal_capacity load_auction load_forecasts load_reference_values load_rules
    load_weekly_outcomes main market_adjustment missing_starters nominee_scenarios
    policy_action positional_frontier projected_lineup projected_total rebase_reference
    reference_pool replay_markets replay_states run_benchmark scoring_hash validate_manifest
    weekly_gaps
    _cell _compare_frontiers _covers _decimal _file_hash _forecast_weights _integer _json
    _json_list _mapped_id _pool_warnings _projected_lineup _projected_total _prune_positional
    _render_report _rescale _rows _structural_rejection _text _timestamp
    _validate_auction_forecasts
    """.split()
)

# The synthetic league's benchmark summary. The recommendation hash is left out on
# purpose: it covers the implementation's bytes, so any code edit changes it.
SYNTHETIC_SUMMARY = {
    "benchmark_complete": True,
    "csv_sha256": "a2e3065390d5ac7625477f50dfb6b6ebdb940b105b8a0ad07b3baf0db98635fe",
    "evaluated_pair_count": 36,
    "pair_count": 48,
    "pair_dispositions": {"infeasible": 12, "pass": 3, "supported": 33},
    "row_dispositions": {
        "inflation": {"infeasible": 12, "pass": 1077, "supported": 3009},
        "roster": {"infeasible": 12, "pass": 2240, "supported": 1846},
        "static": {"infeasible": 12, "pass": 1626, "supported": 2460},
    },
    "scenario_disagreement_pairs": 31,
    "unknown_evaluation_branch_rows": {"fixed_preseason": 0, "optimistic_hindsight": 0},
    "work_limit": 2000,
}


def rules_data():
    """Return a complete rules object that load_rules accepts."""
    data = asdict(replay.LeagueRules())
    data.update(starters=list(data["starters"]), scoring={"receptions": "0.5"})
    return dict(data, scoring_complete=True)


class ReplayCompatibilityChecks(unittest.TestCase):
    def test_every_defined_name_is_still_available(self):
        missing = sorted(name for name in DEFINED_NAMES if not hasattr(replay, name))
        self.assertEqual(missing, [])

    def test_patching_a_name_reaches_the_engine_code_that_calls_it(self):
        expected = replay.load_rules(rules_data())
        for name, calls in (("_integer", 6), ("_timestamp", 2), ("_json", 1)):
            with self.subTest(name=name):
                with patch.object(replay, name, wraps=getattr(replay, name)) as helper:
                    self.assertEqual(replay.load_rules(rules_data()), expected)
                self.assertEqual(helper.call_count, calls)
                # The original is back in place once the patch ends.
                self.assertEqual(replay.load_rules(rules_data()), expected)
                self.assertEqual(helper.call_count, calls)

    def test_every_console_script_resolves(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        for name, target in project["scripts"].items():
            with self.subTest(script=name):
                self.assertTrue(callable(EntryPoint(name, target, "console_scripts").load()))
        replay_main = EntryPoint("auction-replay", project["scripts"]["auction-replay"], "")
        self.assertIs(replay_main.load(), replay.main)
        with redirect_stdout(StringIO()) as shown, self.assertRaises(SystemExit) as stopped:
            replay.main(["--help"])
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("--work-limit", shown.getvalue())

    def test_synthetic_benchmark_decisions_are_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            summary = replay.run_benchmark(
                SYNTHETIC / "auction.csv",
                SYNTHETIC,
                output / "report.md",
                output / "decisions.csv",
                2000,
            )
            report = (output / "report.md").read_text()
        recommendation = summary.pop("recommendation_sha256")
        self.assertEqual(json.loads(json.dumps(summary)), SYNTHETIC_SUMMARY)
        self.assertIn(f"Recommendation SHA-256: `{recommendation}`", report)
        self.assertIn(
            f"Decision CSV SHA-256 (includes evaluation): `{summary['csv_sha256']}`", report
        )


class EngineHashChecks(unittest.TestCase):
    def engine_file_names(self):
        modules = (
            value
            for value in vars(replay).values()
            if isinstance(value, ModuleType) and value.__name__.startswith("auction_replay.")
        )
        return {Path(module.__file__ or "").name for module in modules} | {"replay_auction.py"}

    def test_engine_files_list_every_engine_module(self):
        names = [path.name for path in benchmark.ENGINE_FILES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), self.engine_file_names())
        self.assertTrue(all(path.is_file() for path in benchmark.ENGINE_FILES))

    def test_pilot_code_hashes_cover_every_engine_file(self):
        metadata = pilot.make_joint_metadata(
            (), replay.LeagueRules(), {}, {}, "A", {}, source_hashes={}
        )
        expected = {path.name: replay._file_hash(path) for path in benchmark.ENGINE_FILES}
        expected["historical_price_pilot.py"] = replay._file_hash(pilot.__file__)
        self.assertEqual(metadata["code_hashes"], expected)

    def test_implementation_hash_changes_with_any_engine_file(self):
        baseline = benchmark.implementation_hash()
        file_hash = replay._file_hash
        for changed in benchmark.ENGINE_FILES:
            with self.subTest(file=changed.name):
                with patch.object(
                    replay,
                    "_file_hash",
                    side_effect=lambda path, changed=changed: (
                        "0" * 64 if Path(path) == changed else file_hash(path)
                    ),
                ):
                    self.assertNotEqual(benchmark.implementation_hash(), baseline)
        self.assertEqual(benchmark.implementation_hash(), baseline)


if __name__ == "__main__":
    unittest.main()
