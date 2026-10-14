"""Run the focused replay checks with Python's standard library."""

import csv
import hashlib
import io
import json
import tempfile
from contextlib import redirect_stderr
from dataclasses import replace
from collections import Counter
from decimal import Decimal
from itertools import combinations, permutations
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

# Run from a checkout without installing: put src/ on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auction_replay import replay_auction as replay  # noqa: E402

AUCTION_CSV = Path(__file__).resolve().parents[1] / "docs" / "research" / "2025-discount-double-check-auction.csv"


def fails(fragment, operation):
    try:
        operation()
    except replay.InputError as error:
        assert fragment in str(error), str(error)
    else:
        raise AssertionError(f"Expected input error containing {fragment!r}")


def write_csv(path, fields, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def input_checks():
    rules = replay.LeagueRules()
    real = replay.load_auction(AUCTION_CSV, rules)
    assert len(real) == 196 and sum(p.salary for p in real) == 2774
    assert sum(p.salary for p in real if p.keeper) == 231
    assert any(p.team == "n/a" for p in real)
    assert any(p.player_id == "denver" for p in real)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        auction = root / "auction.csv"
        fields = "pick,id,name,position,salary,team,keeper".split(",")
        rows = [dict(zip(fields, [p.pick, p.player_id, p.name, p.position, p.salary,
                                 p.team, str(p.keeper).lower()])) for p in real]
        write_csv(auction, fields, rows)
        assert replay.load_auction(auction, rules) == real
        polluted = [dict(row, points="not a number", games="future outcome") for row in rows]
        write_csv(auction, fields + ["points", "games"], polluted)
        assert replay.load_auction(auction, rules) == real
        rows[1]["id"] = rows[0]["id"]
        write_csv(auction, fields, rows)
        fails("duplicate player", lambda: replay.load_auction(auction, rules))
        auction.write_bytes(b"pick,id,name,position,salary,team,keeper\n\xff")
        fails(str(auction), lambda: replay.load_auction(auction, rules))
        auction.write_text("pick,id,name,position,salary,team,keeper\n1," + "x" * (csv.field_size_limit() + 1))
        fails(str(auction), lambda: replay.load_auction(auction, rules))

        forecasts = root / "forecasts.csv"
        forecast_fields = "provider_id,name,position,nfl_team,bye,projected_points".split(",")
        forecast_rows = [dict(zip(forecast_fields, row)) for row in [
            ["a", "Player A", "WR", "CIN", 10, "180.25"],
            ["b", "Player B", "DEF", "DEN", 12, "70"],
            ["c", "Undrafted C", "RB", "NYJ", 9, "80"]]]
        write_csv(forecasts, forecast_fields, forecast_rows)
        scored_rules = replace(rules, scoring=(("receptions", Decimal("0.5")),))
        manifest = {"url": "https://example.org/preseason", "season": 2025,
                    "published_at": "2025-08-31", "retrieved_at": "2026-09-05T12:00:00+00:00",
                    "sha256": hashlib.sha256(forecasts.read_bytes()).hexdigest(),
                    "scoring_coverage": ["receptions"], "scoring_hash": replay.scoring_hash(scored_rules),
                    "identity_mappings": [{"provider_id": key, "player_id": value}
                                          for key, value in [("a", "01"), ("b", "denver"), ("c", "03")]],
                    "local_use": "Local research only; redistribution unverified", "includes_undrafted": True}
        players = replay.load_forecasts(forecasts, manifest, scored_rules, {"01", "denver"})
        assert players["01"].projected_points == Decimal("180.25")
        assert players["denver"].position == "DEF"
        for field, value, error in [("published_at", "2025-09-04", "post-draft"),
                                    ("published_at", "", "publication"),
                                    ("season", 2026, "season"),
                                    ("scoring_coverage", [], "scoring coverage"),
                                    ("sha256", "0" * 64, "hash"),
                                    ("includes_undrafted", False, "undrafted")]:
            fails(error, lambda f=field, v=value: replay.load_forecasts(
                forecasts, dict(manifest, **{f: v}), scored_rules, {"01", "denver"}))
        ambiguous = manifest["identity_mappings"] + [{"provider_id": "a", "player_id": "other"}]
        fails("ambiguous", lambda: replay.load_forecasts(
            forecasts, dict(manifest, identity_mappings=ambiguous), scored_rules, {"01", "denver"}))
        fails("missing drafted", lambda: replay.load_forecasts(forecasts, manifest, scored_rules, {"absent"}))
        fails("scoring", lambda: replay.load_forecasts(forecasts, manifest, rules, {"01", "denver"}))
        rules_data = {"season": 2025, "draft_at": rules.draft_at, "teams": 14, "budget": 200,
                      "roster_size": 14, "starters": list(rules.starters), "first_week": 1,
                      "last_week": 17, "scoring": {"receptions": "0.5"}, "scoring_complete": True}
        assert replay.load_rules(rules_data) == scored_rules
        fails("scoring", lambda: replay.load_rules(dict(rules_data, scoring_complete=False)))
        fails("missing league rules", lambda: replay.load_rules({"season": 2025}))
        reference = root / "reference.csv"
        write_csv(reference, ["provider_id", "reference_value"],
                  [{"provider_id": "a", "reference_value": "29.5"}])
        reference_manifest = dict(manifest, sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                                  scoring_coverage=[], scoring_hash="different-provider-scoring",
                                  source_scoring="Half PPR with provider default scoring",
                                  source_format="12 teams, $200 budget, 18 roster slots")
        assert replay.load_reference_values(reference, reference_manifest, scored_rules, {"01"}) == {
            "01": Decimal("29.5")}
        fails("scoring description", lambda: replay.load_reference_values(
            reference, dict(reference_manifest, source_scoring=""), scored_rules, {"01"}))
        fails("missing reference", lambda: replay.load_reference_values(
            reference, reference_manifest, scored_rules, players))

        weekly = root / "weekly.csv"
        write_csv(weekly, ["player_id", "week", "points", "status"], [
            {"player_id": "01", "week": 1, "points": "0", "status": "verified"},
            {"player_id": "01", "week": 2, "points": "", "status": "missing"},
            {"player_id": "01", "week": 18, "points": "999", "status": "verified"}])
        outcome_manifest = dict(manifest, sha256=hashlib.sha256(weekly.read_bytes()).hexdigest(),
                                published_at="2026-01-10", identity_mappings=[
                                    {"provider_id": "01", "player_id": "01"}])
        outcomes = replay.load_weekly_outcomes(weekly, outcome_manifest, scored_rules, {"01"})
        assert outcomes[("01", 1)] == Decimal("0")
        assert outcomes[("01", 2)] is None and outcomes[("01", 3)] is None
        assert ("01", 18) not in outcomes
        assert replay.weekly_gaps(outcomes) == [("01", week) for week in range(2, 18)]
        print("Input checks passed: 196 auction rows, source gates, identity coverage, outcome isolation.")


def state_checks():
    rules = replay.LeagueRules()
    real = replay.load_auction(AUCTION_CSV, rules)
    moments = tuple(replay.replay_states(real, rules))
    assert len(moments) == 182
    assert sum(rules.budget - t.budget for t in moments[0].state.teams) == 231
    keepers = {p.player_id for p in real if p.keeper}
    assert moments[0].state.owned == keepers
    assert not hasattr(moments[0], "salary") and not hasattr(moments[0], "team")
    final = replay.final_state(real, rules)
    assert sum(t.budget for t in final.teams) == 26
    assert all(len(t.roster) == 14 for t in final.teams)
    assert all(set(t.roster) == {p.player_id for p in real if p.team == t.name} for t in final.teams)
    bo = final.team("Team Bo")
    positions = {p.player_id: p for p in real}
    assert replay.missing_starters(bo.roster, positions, rules) == ("K",)
    assert bo.budget == 2

    small = replace(rules, teams=2, budget=12, roster_size=3, starters=("QB", "FLEX"))
    players = {key: replay.Player(key, key, position, "NFL", 8, Decimal(100))
               for key, position in [("a", "QB"), ("b", "WR"), ("c", "RB"),
                                     ("d", "QB"), ("e", "TE"), ("f", "WR"),
                                     ("z", "QB"), ("y", "RB")]}
    picks = tuple(replay.AuctionPick(i, key, key, players[key].position, salary, team, keeper)
                  for i, (key, salary, team, keeper) in enumerate([
                      ("b", 4, "A", False), ("d", 3, "B", False),
                      ("e", 2, "B", False), ("f", 1, "A", False),
                      ("a", 2, "A", True), ("c", 2, "B", True)], 1))
    refs = {key: Decimal(value) for key, value in zip(players, [8, 7, 6, 5, 4, 3, 2, 1])}
    markets = tuple(replay.replay_markets(picks, players, refs, small))
    fails("missing auction players", lambda: next(replay.replay_markets(
        picks, {key: value for key, value in players.items() if key != "b"}, refs, small)))
    fails("position mismatch", lambda: next(replay.replay_markets(
        picks, dict(players, b=replace(players["b"], position="QB")), refs, small)))
    first = markets[0]
    initial_pool = replay.reference_pool(first.nomination.state, players, refs, small, include_owned=True)
    assert set(initial_pool) >= {"a", "c"} and len(initial_pool) == 6
    assert sum(dict(first.static)[key] for key in initial_pool) == Decimal(24)
    assert first.prior_ratios == ()
    assert replay.market_adjustment(()) == 1
    assert replay.market_adjustment((Decimal(2),)) == 1 + Decimal(1) / 21
    changed = tuple(replace(p, salary=5 if p.player_id == "b" else p.salary) for p in picks)
    changed_markets = tuple(replay.replay_markets(changed, players, refs, small))
    assert markets[0] == changed_markets[0]
    assert markets[1].inflation != changed_markets[1].inflation
    prediction = replay.future_prices(dict(first.inflation), first.prior_ratios)["b"]
    assert markets[1].prior_ratios == (Decimal(4) / prediction,)
    changed_late = tuple(replace(p, salary=4, team="A") if p.player_id == "e" else p for p in picks)
    assert next(replay.replay_markets(changed_late, players, refs, small)) == first
    future = replay.future_prices({"b": Decimal("2.1")}, (), Decimal("0.8"))
    assert future["b"] == 2
    assert replay.future_prices({"b": Decimal("0")}, ())["b"] == 1
    assert replay.legal_capacity(first.nomination.state.team("A"), "b", players,
                                 set(players) - first.nomination.state.owned, small) == (9, None)
    for policy in (dict(first.static), dict(first.inflation)):
        assert replay.baseline_ceiling(policy, first.nomination.state.team("A"), "b", players,
                                       set(players) - first.nomination.state.owned, small)[0] <= 9
    poor = replay.TeamState("A", ("a",), 1)
    assert replay.legal_capacity(poor, "b", players, {"b", "e"}, small) == (0, "insufficient reserve")
    full = replay.TeamState("A", ("a", "b", "e"), 10)
    assert replay.legal_capacity(full, "d", players, {"d"}, small) == (0, "full roster")
    impossible = replay.TeamState("B", ("b", "e"), 10)
    assert replay.legal_capacity(impossible, "f", players, {"f", "d"}, small) == (0, "positional infeasibility")
    assert replay.missing_starters(("b",), players, replace(small, starters=("WR", "FLEX"))) == ("FLEX",)
    zeros = tuple(replay.replay_markets(picks, players, {key: Decimal(1) for key in players}, small))
    assert set(dict(zeros[0].static).values()) == {Decimal(1)}
    assert set(dict(zeros[0].inflation).values()) == {Decimal(1)}
    assert any("zero discretionary denominator" in warning for warning in zeros[0].warnings)
    # Expensive quarterbacks cannot crowd out the two distinct FLEX starters.
    crowded = {key: Decimal(100 if p.position == "QB" else 1) for key, p in players.items()}
    pool = replay.reference_pool(first.nomination.state, players, crowded, small, include_owned=True)
    assert len([key for key in pool if players[key].position in {"RB", "WR", "TE"}]) >= 2
    stranded = replay.AuctionState((replay.TeamState("A", ("a",), 8),
                                    replay.TeamState("B", ("b", "e", "f"), 10)))
    prices, warnings = replay.inflation_prices(stranded, players, dict(first.static), small)
    pool = replay.reference_pool(stranded, players, dict(first.static), small)
    assert abs(sum(prices[key] for key in pool) - 8) < Decimal("1e-24")
    assert any("B: historical starter coverage impossible" in warning for warning in warnings)
    # An impossible open roster also leaves valid decisions for the other team.
    tighter = replace(small, starters=("QB", "RB", "FLEX"))
    bad_open = replay.AuctionState((replay.TeamState("A", ("a",), 8),
                                    replay.TeamState("B", ("b", "e"), 10)))
    prices, warnings = replay.inflation_prices(bad_open, players, dict(first.static), tighter)
    assert prices and warnings
    assert replay.legal_capacity(bad_open.team("A"), "c", players,
                                 set(players) - bad_open.owned, tighter)[0] == 7
    # Exercise the real market-to-comparison chain without outcome data or mocks.
    scenarios = replay.nominee_scenarios(first, "A", players, small, work_limit=10000)
    assert len(scenarios) == 9
    for scenario in scenarios:
        for bound in scenario.comparison.buy.bounds:
            if bound.roster:
                assert {"a", "b"} <= set(bound.roster) and "c" not in bound.roster
    print("State checks passed: keeper-first timeline, budgets, prefix isolation, baselines, reserves, positions.")


def oracle_score(roster, players, rules, nominee=None, forecast_factor=Decimal(1), absent_weeks=()):
    """Enumerate distinct legal weekly assignments, independently of the optimizer."""
    total = Decimal(0)
    for week in range(rules.first_week, rules.last_week + 1):
        active = [key for key in roster if players[key].bye != week and
                  not (key == nominee and week in absent_weeks)]
        # Separate dummy players permit any vacant slot to score zero.
        choices = active + [None] * len(rules.starters)
        best = Decimal(0)
        for lineup in permutations(choices, len(rules.starters)):
            if all(key is None or (players[key].position in {"RB", "WR", "TE"}
                                  if slot == "FLEX" else players[key].position == slot)
                   for slot, key in zip(rules.starters, lineup)):
                score = sum((players[key].projected_points *
                             (forecast_factor if key == nominee else 1)
                             for key in lineup if key is not None), Decimal(0))
                best = max(best, score)
        total += best
    return total / 17


def oracle_frontier(fixed, candidates, prices, players, rules, max_budget, **sensitivity):
    frontier = [None] * (max_budget + 1)
    for addition in combinations(sorted(candidates), rules.roster_size - len(fixed)):
        roster = tuple(fixed) + addition
        # Structural coverage is independently checked by distinct assignments.
        legal = any(all(players[key].position in {"RB", "WR", "TE"} if slot == "FLEX"
                        else players[key].position == slot
                        for slot, key in zip(rules.starters, assignment))
                    for assignment in permutations(roster, len(rules.starters)))
        cost = sum(prices[key] for key in addition)
        if not legal or cost > max_budget:
            continue
        score = oracle_score(roster, players, rules, **sensitivity)
        for budget in range(cost, max_budget + 1):
            frontier[budget] = score if frontier[budget] is None else max(frontier[budget], score)
    return frontier


def absent_flex_checks():
    from auction_replay import historical_price_pilot as pilot

    rules = replace(replay.LeagueRules(), teams=1, roster_size=2, budget=4, starters=("QB", "FLEX"))
    prices = {"q1": 1, "q2": 1, "flex": 3}
    for position in ("RB", "WR", "TE"):
        players = {key: replay.Player(key, key, pos, "NFL", 18, Decimal(points))
                   for key, pos, points in [("q1", "QB", 170), ("q2", "QB", 153), ("flex", position, 136)]}
        for fixed in ((), ("q2",)):
            candidates = set(players) - set(fixed)
            expected = oracle_frontier(fixed, candidates, prices, players, rules, 4)
            raw = replay.positional_frontier(fixed, candidates, prices, players, rules, 4)
            assert raw.complete
            assert [Decimal(e[0]) / 1000000 if e else None for e in raw.entries] == expected
            for function, scale in ((replay.completion_frontier, Decimal(1)),
                                    (pilot.season_frontier, Decimal(16) / 17)):
                result = function(fixed, candidates, prices, players, rules, 4)
                for budget, (bound, optimum) in enumerate(zip(result.bounds, expected)):
                    if optimum is None:
                        assert bound.status == "infeasible" and bound.roster is None
                    else:
                        assert bound.lower == bound.upper == optimum * scale
                        assert not replay.missing_starters(bound.roster, players, rules)
                        assert set(fixed) <= set(bound.roster)
                        assert bound.cost == sum(prices[k] for k in bound.roster if k not in fixed) <= budget
    print("Absent FLEX checks passed: every eligible category, mandatory holdings, joint and fixed-starter frontiers.")


def relaxation_checks():
    # A cheaper starting-core replacement unlocks a different-bye backup. The
    # weekly optimum exceeds every fixed-starter 16/17 score at this budget.
    rules = replace(replay.LeagueRules(), teams=1, roster_size=2, budget=5, starters=("WR",))
    players = {key: replay.Player(key, key, "WR", "NFL", bye, Decimal(points))
               for key, bye, points in [("a", 1, 170), ("b", 1, 169), ("c", 2, 168), ("d", 1, 1)]}
    prices = dict(zip(players, [4, 3, 2, 1]))
    weekly = oracle_frontier((), players, prices, players, rules, 5)
    no_byes = {key: replace(player, bye=18) for key, player in players.items()}
    raw_oracle = oracle_frontier((), players, prices, no_byes, rules, 5)
    assert weekly[5] > raw_oracle[5] * 16 / 17
    raw = replay.positional_frontier((), players, prices, players, rules, 5)
    assert raw.complete and raw.fallback is None and raw.transitions > 0
    assert [Decimal(v[0]) / 1000000 if v else None for v in raw.entries] == raw_oracle
    limited = replay.completion_frontier((), players, prices, players, rules, 5, work_limit=1)
    assert limited.bounds[4].upper <= raw_oracle[4]  # Bound applies to pending nodes too.
    assert limited.bounds[5].lower >= replay.projected_total(raw.entries[5][2], players, rules)
    assert limited.relaxation_complete and limited.relaxation_transitions == raw.transitions
    complete = replay.completion_frontier((), players, prices, players, rules, 5, work_limit=10000)
    assert complete.bounds[5].roster == ("b", "c") and complete.bounds[5].lower == weekly[5]
    for search_limit in (1, 3, 10000):
        for transition_limit in (0, 1, 10, 100000):
            result = replay.completion_frontier((), players, prices, players, rules, 5,
                work_limit=search_limit, relaxation_limit=transition_limit)
            assert result.relaxation_transitions <= transition_limit
            assert result.relaxation_limit == transition_limit
            for budget, (bound, optimum) in enumerate(zip(result.bounds, weekly)):
                if optimum is not None:
                    assert bound.upper >= optimum and (bound.lower is None or bound.lower <= optimum)
                if bound.upper is None:
                    assert optimum is None
                if bound.roster is not None:
                    assert bound.lower == oracle_score(bound.roster, players, rules)
                    assert bound.cost == sum(prices[k] for k in bound.roster) <= budget
                if search_limit == 10000:
                    assert bound.lower == bound.upper == optimum
            if transition_limit == 0:
                assert not result.relaxation_complete and "limit" in result.relaxation_fallback
    # Unsupported relaxation shapes must preserve the generic exact search,
    # including nonpositive forecasts and paid specialist roster places.
    shape = {key: replay.Player(key, key, pos, "NFL", bye, Decimal(points)) for key, pos, bye, points in [
        ("held", "QB", 1, "-1"), ("wr", "WR", 2, "51.1234567"), ("rb", "RB", 3, "45"),
        ("te", "TE", 1, "40"), ("k", "K", 2, "0"), ("def", "DEF", 3, "0")]}
    shape_prices = {k: 1 for k in shape if k != "held"}
    for slots in (("QB", "FLEX", "K", "DEF"), ("QB", "FLEX", "FLEX")):
        if slots.count("FLEX") == 2:
            shape = dict(shape, wr=replace(shape["wr"], projected_points=Decimal(51)))
        variant = replace(rules, roster_size=5, starters=slots, last_week=2)
        oracle = oracle_frontier(("held",), set(shape) - {"held"}, shape_prices, shape, variant, 5)
        for limit in (1, 10000):
            result = replay.completion_frontier(("held",), set(shape) - {"held"}, shape_prices,
                                                shape, variant, 5, work_limit=limit)
            expected_fallback = "one FLEX" if slots.count("FLEX") == 2 else "six decimal"
            assert not result.relaxation_complete and expected_fallback in result.relaxation_fallback
            for budget, (bound, optimum) in enumerate(zip(result.bounds, oracle)):
                if optimum is not None:
                    assert bound.upper >= optimum and (bound.lower is None or bound.lower <= optimum)
                if bound.roster:
                    assert "held" in bound.roster and bound.cost == 4
                if limit == 10000:
                    assert bound.lower == bound.upper == optimum
    # A partial positional pass must never mark an affordable completion impossible.
    partial = replay.positional_frontier((), players, prices, players, rules, 5, transition_limit=1)
    assert not partial.complete and partial.transitions == 1 and "limit" in partial.fallback
    # Reordering equal-score input does not change the proof or witness.
    ties = {k: replace(p, projected_points=Decimal(100)) for k, p in players.items()}
    first = replay.completion_frontier((), ties, prices, ties, rules, 5, work_limit=10000)
    second = replay.completion_frontier((), reversed(ties), prices, dict(reversed(list(ties.items()))),
                                        rules, 5, work_limit=10000)
    assert first == second
    timings = {}
    measured = replay.completion_frontier((), ties, prices, ties, rules, 5, work_limit=10000, timings=timings)
    assert measured == first and set(timings) == {"preprocessing_seconds", "search_seconds", "total_seconds"}
    assert all(value >= 0 for value in timings.values())
    assert abs(timings["preprocessing_seconds"] + timings["search_seconds"] - timings["total_seconds"]) < 1e-9
    # Nominee-only precision fallback must not change the cached pass branch.
    precision = dict(players, a=replace(players["a"], projected_points=Decimal("170.000001")))
    nomination = replay.Nomination(1, "a", replay.AuctionState((replay.TeamState("A", (), 5),)))
    moment = replay.MarketMoment(nomination, tuple(prices.items()), tuple(prices.items()), (), ())
    for case in replay.nominee_scenarios(moment, "A", precision, rules):
        direct = replay.compare_nominee(nomination, "A", precision,
            replay.future_prices(prices, (), case.price_factor), rules,
            forecast_factor=case.forecast_factor, absent_weeks=case.absent_weeks)
        assert case.comparison == direct
    # The raw frontier is exact with nonpositive fixed ownership, fractional
    # forecasts, and each feasible FLEX assignment; weekly scoring only lowers it.
    small_rules = replace(rules, roster_size=4, starters=("QB", "WR", "FLEX"), last_week=3)
    small = {k: replay.Player(k, k, pos, "NFL", bye, Decimal(value)) for k, pos, bye, value in [
        ("q", "QB", 2, "-3"), ("q2", "QB", 1, "85.123456"), ("w", "WR", 1, "51.2"),
        ("w2", "WR", 2, "44.3"), ("r", "RB", 3, "49.9"), ("t", "TE", 1, "48") ]}
    small_prices = dict(zip(small, (1, 4, 3, 1, 2, 2)))
    for fixed in ((), ("q",), ("q", "q2")):
        candidates = set(small) - set(fixed)
        raw = replay.positional_frontier(fixed, candidates, small_prices, small, small_rules, 8)
        raw_players = {key: replace(player, bye=18) for key, player in small.items()}
        raw_rules = replace(small_rules, last_week=17)
        raw_expected = oracle_frontier(fixed, candidates, small_prices, raw_players, raw_rules, 8)
        assert raw.complete
        assert [Decimal(v[0]) / 1000000 if v else None for v in raw.entries] == raw_expected
        for absent in ((), (2, 3)):
            expected = oracle_frontier(fixed, candidates, small_prices, small, small_rules, 8,
                                       nominee="w", forecast_factor=Decimal(".8"), absent_weeks=absent)
            for cap in (1, 10000):
                frontier = replay.completion_frontier(fixed, candidates, small_prices, small, small_rules, 8,
                    work_limit=cap, nominee="w", forecast_factor=Decimal(".8"), absent_weeks=absent)
                for bound, optimum in zip(frontier.bounds, expected):
                    if optimum is not None:
                        assert bound.upper >= optimum and (bound.lower is None or bound.lower <= optimum)
                    if cap == 10000:
                        assert bound.lower == bound.upper == optimum
    print("Relaxation checks passed: raw no-bye oracle, budget bounds, weekly seeds, caps, fallback, deterministic witnesses.")


def optimizer_checks():
    rules = replace(replay.LeagueRules(), teams=1, budget=13, roster_size=3, starters=("QB", "WR"))
    players = {key: replay.Player(key, key, position, "NFL", 18, Decimal(points))
               for key, position, points in [("n", "WR", 170), ("q", "QB", 170),
                                              ("q2", "QB", 17), ("w", "WR", 136), ("w2", "WR", 34)]}
    prices = {"n": 2, "q": 6, "q2": 1, "w": 3, "w2": 1}
    candidates = set(players) - {"n"}
    pass_oracle = oracle_frontier((), candidates, prices, players, rules, 13)
    buy_oracle = oracle_frontier(("n",), candidates, prices, players, rules, 13)
    expected = [price for price in range(1, 12) if buy_oracle[13 - price] > pass_oracle[13]]
    assert pass_oracle[13] == 306 and buy_oracle[7] == 340 and expected == list(range(1, 7))
    print("Tiny exhaustive oracle established: pass 306, buy 340 through $6; reference $2 is synthetic.")
    state = replay.AuctionState((replay.TeamState("A", (), 13),))
    nomination = replay.Nomination(1, "n", state)
    result = replay.compare_nominee(nomination, "A", players, prices, rules, work_limit=10000)
    assert result.capacity == 11 and result.reason is None
    assert result.supported_ceiling == 6 and result.possible_ceiling == 6
    assert [row.price for row in result.prices if row.decision == "buy"] == expected
    for frontier, oracle in [(result.buy, buy_oracle), (result.passing, pass_oracle)]:
        for budget, (bound, expected_score) in enumerate(zip(frontier.bounds, oracle)):
            assert bound.lower == bound.upper == expected_score, (budget, bound, expected_score)
            assert bound.status == ("infeasible" if expected_score is None else "optimal")
            if bound.roster is not None:
                assert len(bound.roster) == rules.roster_size == len(set(bound.roster))
                assert bound.cost <= budget
        assert frontier.work_limit == 10000 and not frontier.exhausted
    assert all("n" not in bound.roster for bound in result.passing.bounds if bound.roster)
    assert all("n" in bound.roster for bound in result.buy.bounds if bound.roster)
    cheaper = replay.compare_nominee(nomination, "A", players,
                                     replay.future_prices(prices, (), Decimal("0.8")), rules)
    dearer = replay.compare_nominee(nomination, "A", players,
                                    replay.future_prices(prices, (), Decimal("1.2")), rules)
    stressed = replay.compare_nominee(nomination, "A", players, prices, rules, forecast_factor=Decimal("0.8"))
    assert cheaper.supported_ceiling == 7 and dearer.supported_ceiling == 3
    assert stressed.supported_ceiling == 0 and all(row.decision == "pass" for row in stressed.prices)
    assert stressed.prices[0].buy.lower == stressed.prices[0].passing.lower == 306
    # The future nominee price cannot leak into either branch's completion bill.
    assert replay.compare_nominee(nomination, "A", players,
                                  {key: value for key, value in prices.items() if key != "n"},
                                  rules, work_limit=10000) == result
    assert replay.compare_nominee(nomination, "A", dict(reversed(list(players.items()))),
                                  prices, rules, work_limit=10000) == result
    for limit in (1, 2, 4, 7, 12):
        limited = replay.compare_nominee(nomination, "A", players, prices, rules, work_limit=limit)
        for frontier, oracle in [(limited.buy, buy_oracle), (limited.passing, pass_oracle)]:
            assert frontier.nodes <= limit and frontier.work_limit == limit
            for budget, (bound, optimum) in enumerate(zip(frontier.bounds, oracle)):
                if optimum is not None:
                    assert bound.upper is not None and bound.upper >= optimum, (limit, budget, bound)
                    assert bound.lower is None or bound.lower <= optimum
                if bound.status == "infeasible":
                    assert optimum is None
                if bound.roster:
                    assert bound.lower == oracle_score(bound.roster, players, rules)
                    assert bound.cost <= budget
        for row in limited.prices:
            if row.decision == "buy":
                assert buy_oracle[13 - row.price] > pass_oracle[13]
        if limit == 1:
            # The exact no-bye relaxation now resolves this no-bye fixture.
            assert limited.buy.complete and limited.passing.complete
    unseeded = replay.compare_nominee(nomination, "A", players, prices, rules,
                                      work_limit=1, relaxation_limit=0)
    assert unseeded.buy.exhausted and not unseeded.buy.complete
    assert any(row.decision == "unresolved" for row in unseeded.prices)
    no_cheap_qb = candidates - {"q2"}
    interrupted = replay.completion_frontier(("n",), no_cheap_qb, prices, players, rules, 13,
                                             work_limit=1, relaxation_limit=0)
    assert interrupted.bounds[4].lower is None and interrupted.bounds[4].upper is not None
    assert interrupted.bounds[4].status == "unresolved" and "no feasible incumbent" in interrupted.bounds[4].reason
    finished = replay.completion_frontier(("n",), no_cheap_qb, prices, players, rules, 13, work_limit=10000)
    assert finished.bounds[4].status == "infeasible"  # Only completed proof can reject it.

    moment = replay.MarketMoment(nomination, tuple(prices.items()), tuple(prices.items()), (), ())
    scenarios = replay.nominee_scenarios(moment, "A", players, rules, work_limit=10000)
    assert len(scenarios) == 9
    assert {case.price_factor for case in scenarios} == {Decimal("0.8"), Decimal(1), Decimal("1.2")}
    for case in scenarios:
        assert case.absent_weeks == ((1, 2) if case.name == "two_non_bye_absences" else ())
        modeled_prices = replay.future_prices(prices, (), case.price_factor)
        expected_buy = oracle_frontier(("n",), candidates, modeled_prices, players, rules, 13,
                                      nominee="n", forecast_factor=case.forecast_factor, absent_weeks=case.absent_weeks)
        expected_pass = oracle_frontier((), candidates, modeled_prices, players, rules, 13)
        assert [bound.lower for bound in case.comparison.buy.bounds] == expected_buy
        assert [bound.lower for bound in case.comparison.passing.bounds] == expected_pass

    # Cached scenarios must match nine independent direct runs, including caps.
    for limit in (1, 4, 10000):
        with patch.object(replay, "completion_frontier", wraps=replay.completion_frontier) as searched:
            shared = replay.nominee_scenarios(moment, "A", players, rules, work_limit=limit)
        assert searched.call_count == 12, searched.call_count
        for case in shared:
            direct = replay.compare_nominee(nomination, "A", players,
                replay.future_prices(prices, (), case.price_factor), rules, limit,
                case.forecast_factor, case.absent_weeks)
            assert case.comparison == direct
        for offset in (0, 3, 6):
            assert all(case.comparison.passing is shared[offset].comparison.passing
                       for case in shared[offset:offset + 3])

    capped_rules = replace(rules, budget=8, starters=("WR", "QB"))
    capped_players = {str(i): replay.Player(str(i), str(i), position, "NFL", 18, Decimal(points))
                      for i, (position, points) in enumerate([
                          ("WR", 38), ("QB", 17), ("TE", 96), ("WR", 81), ("TE", 60), ("QB", 25)])}
    capped_prices = dict(zip(capped_players, (4, 2, 2, 5, 4, 4)))
    capped_nomination = replay.Nomination(1, "0", replay.AuctionState((replay.TeamState("A", (), 8),)))
    capped = replay.compare_nominee(capped_nomination, "A", capped_players, capped_prices, capped_rules,
                                     4, relaxation_limit=0).prices[4]
    assert capped.buy.upper is None and capped.passing.upper is not None and capped.passing.lower is None
    assert capped.decision == "unresolved" and "pass feasibility unresolved" in capped.reason
    exhaustive = replay.compare_nominee(capped_nomination, "A", capped_players, capped_prices, capped_rules, 10000).prices[4]
    assert exhaustive.buy.upper is exhaustive.passing.upper is None and exhaustive.decision == "infeasible"

    flex_rules = replace(rules, roster_size=3, starters=("FLEX", "WR"))
    flex = {key: replay.Player(key, key, pos, "NFL", 18, Decimal(points))
            for key, pos, points in [("wr", "WR", 170), ("rb", "RB", 153), ("te", "TE", 136)]}
    assert replay.projected_lineup(tuple(flex), flex, flex_rules, 1) == ("rb", "wr")
    assert replay.projected_total(tuple(flex), flex, flex_rules) == oracle_score(tuple(flex), flex, flex_rules) == 323
    bye_rules = replace(rules, roster_size=2, starters=("QB",))
    backups = {"starter": replay.Player("starter", "starter", "QB", "NFL", 1, Decimal(170)),
               "backup": replay.Player("backup", "backup", "QB", "NFL", 1, Decimal(153))}
    assert replay.projected_total(tuple(backups), backups, bye_rules) == 160
    backups["backup"] = replace(backups["backup"], bye=2)
    assert replay.projected_total(tuple(backups), backups, bye_rules) == oracle_score(tuple(backups), backups, bye_rules) == 169
    assert replay.projected_total(("n", "q"), players, rules, "n", absent_weeks=(1, 2)) == 320
    fails("non-bye", lambda: replay.projected_total(tuple(backups), backups, bye_rules, "starter", absent_weeks=(1, 2)))
    fails("non-finite", lambda: replay.projected_total(("n",), dict(players, n=replace(players["n"], projected_points=Decimal("NaN"))), rules))
    fails("missing future prices", lambda: replay.compare_nominee(nomination, "A", players, {}, rules))
    fails("future price", lambda: replay.compare_nominee(nomination, "A", players, dict(prices, q=0), rules))
    fails("overlapping", lambda: replay.completion_frontier(("n",), ("n",), prices, players, rules, 13))
    fails("search work limit", lambda: replay.compare_nominee(nomination, "A", players, prices, rules, work_limit=0))

    # A full default roster pays for all nine starters and all five bench places.
    normal = replay.LeagueRules()
    positions = ("QB", "WR", "WR", "RB", "RB", "TE", "K", "DEF", "WR") + ("QB",) * 5
    whole = {str(i): replay.Player(str(i), str(i), position, "NFL", 18, Decimal(100))
             for i, position in enumerate(positions)}
    held = tuple(str(i) for i in range(8))
    six = replay.Nomination(1, "8", replay.AuctionState((replay.TeamState("A", held, 6),)))
    whole_prices = {key: 1 for key in whole}
    completed = replay.compare_nominee(six, "A", whole, whole_prices, normal)
    assert completed.capacity == 1 and completed.prices[0].decision == "buy"
    assert len(completed.prices[0].buy.roster) == 14 and completed.prices[0].buy.cost == 5
    assert completed.prices[0].passing.status == "infeasible"
    expensive_bench = replay.compare_nominee(six, "A", whole, dict(whole_prices, **{"9": 2}), normal)
    assert expensive_bench.prices[0].buy.status == "infeasible"
    poor = replace(six, state=replay.AuctionState((replay.TeamState("A", held, 5),)))
    assert replay.compare_nominee(poor, "A", whole, whole_prices, normal).reason == "insufficient reserve"
    assert six.state.team("A").roster == held  # Hypotheticals never mutate history.

    # Representative synthetic shape: seed a usable 14-slot roster even at one node.
    broad = {f"{pos}{i:02}": replay.Player(f"{pos}{i:02}", f"{pos}{i:02}", pos, "NFL", i % 18 + 1,
                                         Decimal(400 - i if pos == "QB" else 200 - i))
             for pos in sorted(replay.POSITIONS) for i in range(25)}
    seed = replay.completion_frontier((), set(broad), {key: 1 for key in broad}, broad, normal, 200, work_limit=1)
    assert seed.bounds[200].roster is not None and len(seed.bounds[200].roster) == 14
    assert not replay.missing_starters(seed.bounds[200].roster, broad, normal)
    # Cross-check byes, fractional projections, fixed ownership, and three slots
    # against an independent oracle, including several interrupted traversals.
    varied_rules = replace(rules, roster_size=4, starters=("WR", "FLEX", "QB"), last_week=3)
    varied = {key: replay.Player(key, key, position, "NFL", bye, Decimal(points))
              for key, position, bye, points in [("held", "QB", 2, "217.45"), ("n", "WR", 3, "170.15"),
                                                  ("a", "WR", 1, "110.4"), ("b", "RB", 2, "139.6"),
                                                  ("c", "TE", 3, "125"), ("d", "QB", 1, "102"),
                                                  ("e", "RB", 4, "65.99")]}
    varied_nomination = replay.Nomination(1, "n", replay.AuctionState((replay.TeamState("A", ("held",), 9),)))
    for multiplier in (Decimal("0.8"), Decimal(1), Decimal("1.2")):
        varied_prices = replay.future_prices(dict(zip(varied, [1, 2, 1, 3, 4, 2, 1])), (), multiplier)
        for limit in (1, 5, 10000):
            comparison = replay.compare_nominee(varied_nomination, "A", varied, varied_prices,
                                                varied_rules, work_limit=limit)
            for frontier, fixed in [(comparison.buy, ("held", "n")), (comparison.passing, ("held",))]:
                expected = oracle_frontier(fixed, set(varied) - {"held", "n"}, varied_prices, varied,
                                           varied_rules, 9)
                for bound, optimum in zip(frontier.bounds, expected):
                    if optimum is not None:
                        assert bound.upper >= optimum and (bound.lower is None or bound.lower <= optimum)
                    else:
                        assert bound.lower is None
                    if limit == 10000:
                        assert bound.lower == bound.upper == optimum
    print("Optimizer checks passed: exhaustive frontiers, price breakpoints, FLEX, byes, reserves, stresses, capped bounds.")


def export_checks():
    rules = replace(replay.LeagueRules(), teams=1, budget=2, roster_size=1, starters=("WR",))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        rules_data = {key: getattr(rules, key) for key in replay.LeagueRules.__dataclass_fields__}
        rules_data.update(scoring={}, scoring_complete=False)
        (root / "rules.json").write_text(json.dumps(rules_data))
        for text in ("=1+1", "+1+1", "-1+1", "@SUM(1,1)", "\x01\t=1+1", "\u200b+1+1", "Normal Name"):
            auction, report, decisions = (root / name for name in ("auction.csv", "report.md", "decisions.csv"))
            write_csv(auction, "pick id name position salary team keeper".split(), [
                dict(pick=1, id=text, name=text, position="WR", salary=1, team=text, keeper="false")])
            picks = replay.load_auction(auction, rules)
            raw = next(replay.decision_rows(picks, rules))
            assert all(raw[key] == text for key in ("player_id", "player_name", "team"))
            replay.run_benchmark(auction, root, report, decisions, 1)
            with decisions.open() as source:
                row = next(csv.DictReader(source))
            expected = text if text == "Normal Name" else "'" + text
            assert all(row[key] == expected for key in ("player_id", "player_name", "team")), row
            assert json.loads(row["room_state"])["teams"][0]["name"] == text
            assert row["budget"] == "2" and row["price"] == ""
    assert replay._cell(Decimal("-12.5"), "buy_lower") == "-12.5"
    assert replay._cell("-12.5", "buy_lower") == "-12.5"
    assert replay._cell("Normal = Name", "player_name") == "Normal = Name"
    print("Export checks passed: formula-leading imported text, controls, raw identities, numeric negatives.")


def benchmark_checks():
    rules = replace(replay.LeagueRules(), teams=1, budget=13, roster_size=3, starters=("QB", "WR"))
    players = {key: replay.Player(key, key, position, "NFL", 18, Decimal(points))
               for key, position, points in [("n", "WR", 170), ("q", "QB", 170),
                                              ("q2", "QB", 17), ("w", "WR", 136), ("w2", "WR", 34)]}
    picks = tuple(replay.AuctionPick(i, key, key, players[key].position, 1, "A", False)
                  for i, key in enumerate(("n", "q", "w"), 1))
    prices = dict(zip(players, map(Decimal, (2, 6, 1, 3, 1))))
    rows = list(replay.decision_rows(picks, rules, players, prices, work_limit=10000))
    first = [row for row in rows if row["pick"] == 1]
    assert len(first) == 11 * 9
    assert any(row["scenario_disagreement"] for row in first)
    assert all(row["buy_total_cost"] == row["buy_future_cost"] + row["price"]
               for row in rows if row.get("buy_future_cost") is not None)
    for row in rows:
        if row["roster_action"] == "supported":
            assert row["buy_roster"] and (row["pass_upper"] is None or row["buy_lower"] > row["pass_upper"])
        for policy in ("static", "inflation"):
            if row[policy + "_action"] == "supported":
                assert row["buy_roster"]
    # A ceiling alone never confirms a buy with an unresolved feasibility search.
    bound = replay.RosterBound(None, Decimal(100), None, None, "unresolved", "no feasible incumbent")
    feasible = replay.RosterBound(Decimal(50), Decimal(100), ("n", "q", "w"), 3, "unresolved", "limit")
    assert replay.policy_action(1, 5, bound, feasible)[0] == "search-unresolved"
    assert replay.policy_action(1, 5, feasible, bound)[0] == "supported"
    assert replay.policy_action(6, 5, feasible, bound)[0] == "search-unresolved"

    weekly = {(key, week): Decimal(2 if key == "q" else 20) for key in players for week in range(1, 19)}
    score = replay.evaluate_roster(("n", "q", "q2"), players, rules, weekly)
    assert score["fixed_preseason_total"] == 374 and score["optimistic_hindsight_total"] == 680
    assert score["fixed_preseason_total"] != score["optimistic_hindsight_total"]
    assert replay.evaluate_roster(("n", "q", "q2"), players, rules,
                                  {key: value for key, value in weekly.items() if key[1] != 18}) == score
    missing_bench = dict(weekly)
    missing_bench[("q2", 1)] = None
    scored = replay.evaluate_roster(("n", "q", "q2"), players, rules, missing_bench)
    assert scored["fixed_preseason_total"] == 374 and scored["optimistic_hindsight_total"] is None
    missing_selected = dict(weekly)
    missing_selected[("q", 1)] = None
    scored = replay.evaluate_roster(("n", "q", "q2"), players, rules, missing_selected)
    assert scored["fixed_preseason_total"] is None and scored["missing_selected"] == (("q", 1),)
    missing_selected[("q", 1)] = Decimal(0)
    assert replay.evaluate_roster(("n", "q", "q2"), players, rules, missing_selected)["fixed_preseason_total"] == 372
    bye_players = dict(players, q=replace(players["q"], bye=1))
    assert replay.evaluate_roster(("n", "q"), bye_players, rules,
                                  {key: val for key, val in weekly.items() if key != ("q", 1)})["fixed_preseason_total"] == 372

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        report, decisions = root / "report.md", root / "decisions.csv"
        auction = root / "auction.csv"
        write_csv(auction, "pick id name position salary team keeper points".split(), [
            dict(pick=p.pick, id=p.player_id, name=p.name, position=p.position, salary=p.salary,
                 team=p.team, keeper="false", points="future") for p in picks])
        rules_data = {key: getattr(rules, key) for key in replay.LeagueRules.__dataclass_fields__}
        rules_data.update(scoring={"receptions": "0.5"}, scoring_complete=True)
        (root / "rules.json").write_text(json.dumps(rules_data))
        fails("cannot overwrite input", lambda: replay.run_benchmark(auction, root, report, auction))
        scored_rules = replay.load_rules(root / "rules.json")
        write_csv(root / "forecasts.csv", "provider_id name position nfl_team bye projected_points".split(), [
            dict(provider_id=key, name=p.name, position=p.position, nfl_team=p.nfl_team,
                 bye=p.bye, projected_points=p.projected_points) for key, p in players.items()])
        write_csv(root / "reference.csv", ["provider_id", "reference_value"], [
            dict(provider_id=key, reference_value=value) for key, value in prices.items()])
        manifests = {}
        for name in ("forecasts", "reference", "weekly"):
            manifests[name] = dict(url="https://example.org/" + name, season=2025,
                published_at="2026-01-10" if name == "weekly" else "2025-08-31",
                retrieved_at="2026-09-05T12:00:00+00:00", includes_undrafted=True,
                scoring_coverage=["receptions"], scoring_hash=replay.scoring_hash(scored_rules),
                identity_mappings=[dict(provider_id=key, player_id=key) for key in players],
                source_scoring="Synthetic", source_format="Synthetic", local_use="Synthetic test")
        def save_manifest(name):
            manifests[name]["sha256"] = hashlib.sha256((root / (name + ".csv")).read_bytes()).hexdigest()
            (root / (name + ".manifest.json")).write_text(json.dumps(manifests[name]))
        for name in ("forecasts", "reference"):
            save_manifest(name)
        def run(values):
            write_csv(root / "weekly.csv", ["player_id", "week", "points", "status"], [
                dict(player_id=key, week=week, points=value, status="verified")
                for (key, week), value in sorted(values.items())])
            save_manifest("weekly")
            result = replay.run_benchmark(auction, root, report, decisions, work_limit=10000)
            output = list(csv.DictReader(decisions.open()))
            recommendation_bytes = replay.canonical_bytes([
                {key: value for key, value in row.items() if key not in replay.EVALUATION_FIELDS}
                for row in output])
            return result, recommendation_bytes, decisions.read_bytes(), report.read_bytes()
        original, recommendations, csv_bytes, report_bytes = run(weekly)
        assert original["benchmark_complete"] and original["pair_count"] == 3
        assert original["csv_sha256"] == hashlib.sha256(csv_bytes).hexdigest()
        assert original["csv_sha256"].encode() in report_bytes
        assert str(report).encode() in report_bytes and str(decisions).encode() in report_bytes
        assert replay.main(["--auction", str(auction), "--input-dir", str(root), "--report", str(report),
                            "--csv", str(decisions), "--work-limit", "10000"]) == 0
        repeated, rec2, csv2, md2 = run(weekly)
        assert repeated == original and rec2 == recommendations and csv2 == csv_bytes and md2 == report_bytes
        assert b"Scenario disagreement" in report_bytes
        permuted = {key: Decimal(20 if key[0] == "q" else 2) for key in weekly}
        changed, rec3, csv3, _ = run(permuted)
        assert rec3 == recommendations and changed["recommendation_sha256"] == original["recommendation_sha256"]
        assert csv3 != csv_bytes
        # Outcome columns in the original auction are outside the policy hash too.
        auction.write_text(auction.read_text().replace("future", "987654321"))
        changed_auction, rec4, _, _ = run(weekly)
        assert rec4 == recommendations and changed_auction["recommendation_sha256"] == original["recommendation_sha256"]
        more_week18 = dict(weekly)
        more_week18[("q", 18)] = Decimal(99999)
        _, rec5, csv5, _ = run(more_week18)
        assert rec5 == recommendations and csv5 == csv_bytes
        incomplete_weekly = dict(weekly)
        del incomplete_weekly[("q", 1)]
        missing_run, same_recommendations, _, _ = run(incomplete_weekly)
        assert not missing_run["benchmark_complete"] and same_recommendations == recommendations
        assert missing_run["unknown_evaluation_branch_rows"]["fixed_preseason"] > 0
        # A failed rerun must preserve the previously complete artifact pair.
        _, _, complete_csv, complete_report = run(weekly)
        good_forecast = (root / "forecasts.csv").read_bytes()
        (root / "forecasts.csv").write_text(good_forecast.decode().replace("q,q,QB", "q,q,WR"))
        save_manifest("forecasts")
        (root / "input-gaps.json").write_text("{malformed")
        fails("unreadable list", lambda: replay.run_benchmark(auction, root, report, decisions, 10000))
        assert decisions.read_bytes() == complete_csv and report.read_bytes() == complete_report
        (root / "input-gaps.json").write_text("[]")
        rejected, _, rejected_csv, rejected_report = run(weekly)
        assert not rejected["benchmark_complete"] and rejected["pair_dispositions"] == {"missing-data": 3}
        assert b"position mismatch: q" in rejected_csv and b"position mismatch: q" in rejected_report
        assert b"Actual-roster outcome scores are unavailable" in rejected_report
        assert b"| Actual team roster |" not in rejected_report
        assert b"Accepted forecasts:" not in rejected_report
        assert b"Accepted normalized files pass" not in rejected_report
        direct_bad = dict(players, q=replace(players["q"], position="WR"))
        assert all(row["roster_action"] == "missing-data" and "position mismatch: q" in row["reason"]
                   for row in replay.decision_rows(picks, rules, direct_bad, prices))
        (root / "forecasts.csv").write_bytes(good_forecast)
        save_manifest("forecasts")
        _, _, complete_csv, complete_report = run(weekly)
        good_auction = auction.read_bytes()
        auction.write_bytes(b"pick,id,name,position,salary,team,keeper\n\xff")
        error_output = io.StringIO()
        with redirect_stderr(error_output):
            try:
                replay.main(["--auction", str(auction), "--input-dir", str(root),
                             "--report", str(report), "--csv", str(decisions)])
            except SystemExit as error:
                assert error.code == 2
            else:
                raise AssertionError("Malformed CSV encoding must exit 2")
        assert str(auction) in error_output.getvalue() and "Replay input/output error" in error_output.getvalue()
        assert decisions.read_bytes() == complete_csv and report.read_bytes() == complete_report
        auction.write_bytes(good_auction)
        assert sorted(path.name for path in root.iterdir()) == [
            "auction.csv", "decisions.csv", "forecasts.csv", "forecasts.manifest.json", "input-gaps.json",
            "reference.csv", "reference.manifest.json", "report.md", "rules.json", "weekly.csv", "weekly.manifest.json"]
        # Real auction coverage uses an isolated missing-input bundle; later
        # normalized real inputs must never trigger a full search during tests.
        partial_dir = root / "partial"
        partial_dir.mkdir()
        partial_rules = {key: getattr(replay.LeagueRules(), key)
                         for key in replay.LeagueRules.__dataclass_fields__}
        partial_rules.update(scoring={}, scoring_complete=False)
        (partial_dir / "rules.json").write_text(json.dumps(partial_rules))
        partial = replay.run_benchmark(AUCTION_CSV,
                                        partial_dir, report, decisions, work_limit=1)
        assert partial["benchmark_complete"] is False and partial["pair_count"] == 2548
        assert partial["evaluated_pair_count"] == 0 and "none are run" in report.read_text()
        assert partial["pair_dispositions"] == {"infeasible": 385, "missing-data": 2163}
        real_rows = list(csv.DictReader(decisions.open()))
        assert len(real_rows) == 2548 and all(row["price"] == "" for row in real_rows)
        assert Counter(row["reason"] for row in real_rows)["full roster"] == 312
        assert "Team Bo" in report.read_text() and "missing K" in report.read_text()
    print("Benchmark checks passed: complete price/scenario grid, frozen recommendation hashes, fixed versus hindsight, missing weeks, real 2,548-pair coverage.")


class ReplayAuctionChecks(unittest.TestCase):
    """unittest entry points for the assertion-based checks above."""

    def test_inputs(self):
        input_checks()

    def test_states(self):
        state_checks()

    def test_absent_flex(self):
        absent_flex_checks()

    def test_relaxation(self):
        relaxation_checks()

    def test_optimizer(self):
        optimizer_checks()

    def test_export(self):
        export_checks()

    def test_benchmark_and_no_leakage(self):
        # Includes the invariant that the recommendation SHA-256 is unchanged when outcome columns change.
        benchmark_checks()


if __name__ == "__main__":
    input_checks()
    state_checks()
    absent_flex_checks()
    relaxation_checks()
    optimizer_checks()
    export_checks()
    benchmark_checks()
