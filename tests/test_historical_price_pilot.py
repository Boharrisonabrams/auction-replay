"""Small independent oracle and source-boundary checks for the historical pilot."""

from dataclasses import replace
from decimal import Decimal
from itertools import combinations
from unittest.mock import patch
from collections import Counter
import csv
import hashlib
import json
import tempfile
import unittest
import sys
from pathlib import Path

# Run from a checkout without installing: put src/ on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auction_replay import replay_auction as replay  # noqa: E402
from auction_replay import historical_price_pilot as pilot  # noqa: E402


def check():
    rules = replace(
        replay.LeagueRules(), teams=2, roster_size=4, budget=14, starters=("QB", "WR", "FLEX")
    )
    players = {
        key: replay.Player(key, key, pos, "NFL", 7, Decimal(points))
        for key, pos, points in [
            ("a", "QB", 100),
            ("b", "QB", 80),
            ("c", "WR", 120),
            ("d", "WR", 60),
            ("e", "RB", 95),
            ("f", "TE", 50),
            ("g", "RB", 20),
            ("h", "WR", 10),
        ]
    }
    prices = dict(zip(players, [8, 2, 8, 3, 5, 2, 1, 1]))
    for fixed in [(), ("c",), ("b", "h")]:
        candidates = set(players) - set(fixed)
        result = pilot.season_frontier(fixed, candidates, prices, players, rules, 14)
        raw = replay.positional_frontier(fixed, candidates, prices, players, rules, 14)
        assert raw.complete and result.relaxation_complete and raw.transition_limit is None
        assert result.relaxation_transitions == raw.transitions
        for budget in range(15):
            options = []
            for extra in combinations(candidates, rules.roster_size - len(fixed)):
                roster = tuple(fixed) + extra
                if sum(prices[k] for k in extra) > budget or replay.missing_starters(
                    roster, players, rules
                ):
                    continue
                # All players share a bye, so the existing weekly scorer is an
                # independent oracle for the pilot's constant-starter objective.
                options.append(replay.projected_total(roster, players, rules))
            expected = max(options) if options else None
            got = result.bounds[budget]
            entry = raw.entries[budget]
            assert got.lower == (Decimal(entry[0]) * 16 / 17000000 if entry else None)
            assert got.lower == got.upper == expected, (fixed, budget, got, expected)
            if got.roster:
                assert len(got.roster) == 4 and set(fixed) <= set(got.roster)
                assert sum(prices[k] for k in got.roster if k not in fixed) <= budget
    bad = dict(prices, c=-1)
    try:
        pilot.season_frontier((), players, bad, players, rules, 14)
    except replay.InputError:
        pass
    else:
        raise AssertionError("negative price accepted")
    assert pilot.name_key("Luther Burden III") == pilot.name_key("Luther Burden")
    assert pilot.name_key("Hollywood Brown") == pilot.name_key("Marquise Brown")
    assert pilot.core_projection(
        "QB", ["", "A", "NFL", "7", "300", "450", "4000", "30", "10", "50", "200", "2", "0"]
    ) == Decimal(302)
    assert pilot.core_projection(
        "RB", ["", "A", "NFL", "7", "334", "1668", "11", "38", "295", "2", "274.3"]
    ) == Decimal("293.3")
    assert pilot.core_projection(
        "WR", ["", "A", "NFL", "7", "101", "1305", "6", "11", "63", "0", "172.8"]
    ) == Decimal("223.3")
    assert pilot.core_projection(
        "TE", ["", "A", "NFL", "7", "100", "1085", "6", "144.5"]
    ) == Decimal("194.5")
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
    values = {k: p.projected_points + 1 for k, p in players.items()}
    selection = pilot.joint_selection(picks, rules, players, values, "A", "probes")
    assert selection["selected_picks"] and len(selection["all_picks"]) == 6
    with patch.object(
        pilot, "load_outcomes", side_effect=AssertionError("outcomes read before freeze")
    ):
        joint = pilot.recommend_joint(
            picks, rules, players, values, "A", selection, work_limit=20, relaxation_limit=20000
        )
    assert {r["pick"] for r in joint} == set(selection["all_picks"])
    assert all(len(r["prices"]) == r["capacity"] for r in joint if r["disposition"] == "evaluated")
    timings = []
    repeated = pilot.recommend_joint(
        picks, rules, players, values, "A", selection, 20, 20000, timings=timings
    )
    assert replay.canonical_bytes(joint) == replay.canonical_bytes(repeated) and timings
    assert all("seconds" not in key for r in repeated for key in r)
    first_cases = [r for r in joint if r["pick"] == 1]
    assert len(first_cases) == 9
    assert {tuple(r["absent_weeks"]) for r in first_cases} == {(), (1, 2)}
    changed_picks = (replace(picks[0], salary=1),) + picks[1:]
    changed_selection = pilot.joint_selection(changed_picks, rules, players, values, "A", "all")
    changed_joint = pilot.recommend_joint(
        changed_picks, rules, players, values, "A", changed_selection, 20, 20000
    )
    assert first_cases == [r for r in changed_joint if r["pick"] == 1]
    forecast_bytes = replay.canonical_bytes(joint)
    actuals = {(key, week): Decimal(ord(key) + week) for key in players for week in range(1, 19)}
    with patch.object(pilot, "load_outcomes", return_value=(actuals, actuals, {})):
        evaluations, coverage = pilot.evaluate_joint(joint, players, rules, {}, picks)
    with patch.object(
        pilot, "load_outcomes", return_value=({k: v * 2 for k, v in actuals.items()}, actuals, {})
    ):
        altered_evaluations, _ = pilot.evaluate_joint(joint, players, rules, {}, picks)
    assert evaluations != altered_evaluations and replay.canonical_bytes(joint) == forecast_bytes
    assert len(evaluations) == sum(len(r.get("prices", [None])) for r in joint)
    no_week18 = {k: v for k, v in actuals.items() if k[1] != 18}
    with patch.object(pilot, "load_outcomes", return_value=(no_week18, no_week18, {})):
        assert pilot.evaluate_joint(joint, players, rules, {}, picks)[0] == evaluations
    with patch.object(pilot, "load_outcomes", return_value=({}, {}, {})):
        missing, _ = pilot.evaluate_joint(joint, players, rules, {}, picks)
    assert all(
        r["static_core_delta"] is None and r["static_core_unmatched"]
        for r in missing
        if r["disposition"] == "evaluated"
    )
    with patch.object(
        pilot, "load_outcomes", side_effect=AssertionError("outcomes read before freeze")
    ):
        records = pilot.recommend(picks, rules, players, values, "A")
    assert len([r for r in records if r["pick"] == 1]) == 15
    changed = (replace(picks[0], salary=1),) + picks[1:]
    later = pilot.recommend(changed, rules, players, values, "A")
    assert [r for r in records if r["pick"] == 1] == [r for r in later if r["pick"] == 1]
    for row in records:
        if row["disposition"] == "evaluated":
            assert 0 <= row["roster_ceiling"] <= row["capacity"]
    for factor in (Decimal(".8"), Decimal(".875"), Decimal(1)):
        stressed = dict(
            players,
            c=replace(players["c"], projected_points=players["c"].projected_points * factor),
        )
        frontier = pilot.season_frontier(
            ("c",),
            set(players) - {"c"},
            prices,
            players,
            rules,
            14,
            nominee="c",
            forecast_factor=factor,
        )
        for budget in range(15):
            expected = [
                replay.projected_total(("c",) + extra, stressed, rules)
                for extra in combinations(set(players) - {"c"}, 3)
                if sum(prices[k] for k in extra) <= budget
                and not replay.missing_starters(("c",) + extra, players, rules)
            ]
            assert frontier.bounds[budget].lower == (max(expected) if expected else None)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frozen = root / "recommendations.json"
        pilot.save_json(frozen, records)
        before = hashlib.sha256(frozen.read_bytes()).hexdigest()
        with (root / "2025-discount-double-check-auction.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["pick", "salary"])
            writer.writeheader()
            writer.writerows({"pick": p.pick, "salary": p.salary} for p in picks)
        original_records = json.dumps(records, sort_keys=True, default=str)
        actual = {(k, w): Decimal(int(k.encode()[0]) + w) for k in players for w in range(1, 18)}
        with (
            patch.object(pilot, "RESEARCH", root),
            patch.object(pilot, "load_outcomes", return_value=(actual, actual, {})),
        ):
            first, _ = pilot.evaluate(records, players, rules, {})
        changed_actual = {k: v * 3 for k, v in actual.items()}
        with (
            patch.object(pilot, "RESEARCH", root),
            patch.object(pilot, "load_outcomes", return_value=(changed_actual, changed_actual, {})),
        ):
            second, _ = pilot.evaluate(records, players, rules, {})
        assert first != second and original_records == json.dumps(
            records, sort_keys=True, default=str
        )
        assert hashlib.sha256(frozen.read_bytes()).hexdigest() == before
        try:
            pilot.save_json(frozen, {"invalid": float("nan")})
        except ValueError:
            pass
        else:
            raise AssertionError("invalid output serialized")
        assert hashlib.sha256(frozen.read_bytes()).hexdigest() == before
    file_hash = replay._file_hash
    for mutate in (False, True):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            frozen = output / "recommendations.json"

            def evaluate_frozen(*args):
                assert frozen.is_file() and json.loads(frozen.read_text())["records"] == []
                if mutate:
                    frozen.write_text("changed during evaluation")
                return [], {}

            with (
                patch("sys.argv", ["pilot", "--output-dir", directory]),
                patch.object(pilot, "load_pilot", return_value=((), rules, players, {}, {}, {})),
                patch.object(pilot, "recommend", return_value=[]),
                patch.object(pilot, "evaluate", side_effect=evaluate_frozen),
                patch.object(
                    replay,
                    "_file_hash",
                    side_effect=lambda p: file_hash(p) if p == frozen else "synthetic",
                ),
            ):
                try:
                    pilot.main()
                except replay.InputError as error:
                    assert mutate and "frozen recommendations changed" in str(error)
                else:
                    assert not mutate, "main accepted modified recommendations"
                    assert json.loads((output / "evaluation.json").read_text())[
                        "recommendation_sha256"
                    ] == file_hash(frozen)
            assert (output / "evaluation.json").exists() == (not mutate)
    # Independent enumeration includes the extra backup credit and multiple
    # fixed players at one position, exercising cached FLEX table boundaries.
    deeper = replace(rules, roster_size=5)
    for fixed in [(), ("a", "b"), ("c", "d", "h")]:
        for credit in (Decimal(0), Decimal(".125"), Decimal(".25")):
            frontier = pilot.season_frontier(
                fixed, set(players) - set(fixed), prices, players, deeper, 14, bench_credit=credit
            )
            raw = replay.positional_frontier(
                fixed, set(players) - set(fixed), prices, players, deeper, 14, bench_credit=credit
            )
            assert raw.complete
            for budget in range(15):
                entry = raw.entries[budget]
                assert frontier.bounds[budget].lower == (
                    Decimal(entry[0]) * 16 / 17000000 if entry else None
                )
                expected = []
                for extra in combinations(set(players) - set(fixed), 5 - len(fixed)):
                    roster = tuple(fixed) + extra
                    if sum(prices[k] for k in extra) > budget or replay.missing_starters(
                        roster, players, deeper
                    ):
                        continue
                    for flex in ("RB", "WR", "TE"):
                        quota = Counter({"QB": 1, "WR": 1})
                        quota[flex] += 1
                        grouped = {
                            pos: sorted(
                                [
                                    players[k].projected_points
                                    for k in roster
                                    if players[k].position == pos
                                ],
                                reverse=True,
                            )
                            for pos in pilot.OFFENSE
                        }
                        if any(len(grouped[pos]) < n for pos, n in quota.items()):
                            continue
                        value = (
                            sum(
                                (
                                    sum(values[: quota[pos]], Decimal(0))
                                    + (
                                        values[quota[pos]] * credit
                                        if len(values) > quota[pos]
                                        else 0
                                    )
                                    for pos, values in grouped.items()
                                ),
                                Decimal(0),
                            )
                            * 16
                            / 17
                        )
                        expected.append(value)
                assert frontier.bounds[budget].lower == (max(expected) if expected else None), (
                    fixed,
                    credit,
                    budget,
                )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "data/local/2025/sources"
        source.mkdir(parents=True)
        (source.parent / "rules.json").write_text("{}")
        (source / "candidate-forecast-rows.json").write_text("[]")
        (source / "forecast.json").write_text("forecast only")
        inventory = [
            dict(name="forecast", file="forecast.json", sha256="dated"),
            dict(name="weekly-player-stats", file="MISSING.csv", sha256="outcome hash"),
        ]
        inventory_path = source / "source-inventory.json"
        inventory_path.write_text(json.dumps(inventory))
        with patch.object(pilot, "ROOT", root), patch.object(pilot, "SOURCE", source):
            before = pilot.policy_source_hashes()  # Missing outcome file cannot be opened here.
            inventory[1]["sha256"] = "a completely different outcome"
            inventory_path.write_text(json.dumps(inventory))
            assert pilot.policy_source_hashes() == before
            (source / "forecast.json").write_text("changed forecast")
            assert pilot.policy_source_hashes() != before
    for mutate in (False, True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "recommendations.json"
            real_evaluate = pilot.evaluate_joint

            def after_freeze(*args):
                assert frozen.is_file() and (root / "selection.json").is_file()
                assert (
                    json.loads(frozen.read_text())["metadata"]["config"]["objective"]
                    == pilot.JOINT_OBJECTIVE
                )
                assert "seconds" not in frozen.read_text()
                if mutate:
                    frozen.write_text("changed during evaluation")
                return real_evaluate(*args)

            with (
                patch(
                    "sys.argv",
                    [
                        "pilot",
                        "--mode",
                        "joint-weekly",
                        "--output-dir",
                        directory,
                        "--team",
                        "A",
                        "--work-limit",
                        "20",
                        "--relaxation-limit",
                        "20000",
                    ],
                ),
                patch.object(
                    pilot, "load_pilot", return_value=(picks, rules, players, values, {}, {})
                ),
                patch.object(pilot, "policy_source_hashes", return_value={}),
                patch.object(pilot, "load_outcomes", return_value=(actuals, actuals, {})),
                patch.object(pilot, "evaluate_joint", side_effect=after_freeze),
            ):
                try:
                    pilot.main()
                except replay.InputError as error:
                    assert mutate and "frozen recommendations changed" in str(error)
                else:
                    assert not mutate
                    with (root / "decisions.csv").open() as f:
                        exported = list(csv.DictReader(f))
                    assert len(exported) == len(evaluations)
                    assert all(
                        r["recommendation_sha256"] == replay._file_hash(frozen) for r in exported
                    )
                    assert {
                        "scenario_disagreement",
                        "buy_lower",
                        "pass_upper",
                        "buy_relaxation_limit",
                    } <= exported[0].keys()
                    assert json.loads((root / "evaluation.json").read_text())["coverage"][
                        "nomination_accounting"
                    ]
            assert (root / "evaluation.json").exists() is not mutate
    print(
        "Historical pilot checks passed: budget oracle, source separation, deterministic joint grid, matched outcomes, frozen CLI/CSV."
    )


class HistoricalPricePilotChecks(unittest.TestCase):
    def test_pilot(self):
        check()


if __name__ == "__main__":
    check()
