"""Package the frozen 2025 pilot into a private, offline decision explorer."""

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import historical_price_pilot as pilot
from . import replay_auction as replay

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TEMPLATES = ROOT / "templates"
DEFAULT_INPUT = ROOT / "data/local/2025/price-pilot-companion/recommendations.json"
JOINT_INPUT = ROOT / "data/local/2025/joint-roster-pilot/recommendations.json"
OUTPUT = ROOT / "data/local/companion/auction-replay.html"
FACTORS = ("0.8", "1", "1.2")


def sale_row(sale):
    return dict(
        pick=sale.pick,
        player_id=sale.player_id,
        name=sale.name,
        position=sale.position,
        price=sale.salary,
        buyer=sale.team,
    )


def room_snapshot(state, rules):
    return [
        dict(
            name=t.name,
            budget=t.budget,
            open_slots=rules.roster_size - len(t.roster),
            cash_cap=max(0, t.budget - (rules.roster_size - len(t.roster) - 1))
            if len(t.roster) < rules.roster_size
            else 0,
            roster=list(t.roster),
        )
        for t in state.teams
    ]


def compact_bound(bound, budget, fixed, candidates, prices, players, rules):
    if bound["status"] == "infeasible":
        if any(bound[k] is not None for k in ("lower", "upper", "roster", "cost")):
            raise replay.InputError("infeasible bound contains a recommendation")
        return None
    score = replay._decimal(bound["lower"], "roster score")
    roster = bound["roster"]
    cost = replay._integer(bound["cost"], "completion cost", 0, budget)
    if (
        bound["status"] != "optimal"
        or score != replay._decimal(bound["upper"], "upper bound")
        or not isinstance(roster, list)
        or len(roster) != rules.roster_size
        or len(set(roster)) != len(roster)
        or not fixed.issubset(roster)
        or not set(roster).issubset(fixed | candidates)
        or replay.missing_starters(roster, players, rules)
        or cost != sum(prices[p] for p in roster if p not in fixed)
    ):
        raise replay.InputError("invalid frozen roster frontier")
    return dict(score=float(score), cost=cost, roster=roster)


def build_legacy_payload(picks, rules, players, frozen):
    metadata = frozen["metadata"]
    digest = hashlib.sha256(replay.canonical_bytes(picks)).hexdigest()
    if metadata["auction_transactions_sha256"] != digest:
        raise replay.InputError("recommendations belong to a different auction")
    expected = (
        "data/local/2025/sources/candidate-forecast-rows.json",
        "data/local/2025/sources/player-ids.csv",
        "data/local/2025/rules.json",
        "src/auction_replay/historical_price_pilot.py",
    )
    if set(metadata["source_hashes"]) != set(expected):
        raise replay.InputError("unexpected recommendation source paths")
    for path in expected:
        if replay._file_hash(ROOT / path) != metadata["source_hashes"][path]:
            raise replay.InputError(f"stale recommendation source: {path}")
    records = defaultdict(list)
    for record in frozen["records"]:
        records[record["pick"]].append(record)
    decisions = []
    for nomination in replay.replay_states(picks, rules):
        state, pid = nomination.state, nomination.player_id
        team = state.team(metadata["team"])
        room = room_snapshot(state, rules)
        own = next(t for t in room if t["name"] == team.name)
        rows = records.pop(nomination.pick, [])
        if not rows or any(
            r["player_id"] != pid
            or r["budget"] != team.budget
            or r["held_roster"] != list(team.roster)
            for r in rows
        ):
            raise replay.InputError(f"frozen state mismatch at pick {nomination.pick}")
        available = set(players) - state.owned
        capacity, reason = replay.legal_capacity(team, pid, players, available, rules)
        blocked = reason or (
            "specialist excluded from pilot" if players[pid].position not in pilot.OFFENSE else None
        )
        cases = {}
        if blocked:
            if len(rows) != 1 or rows[0]["disposition"] != blocked:
                raise replay.InputError("frozen exclusion mismatch")
        else:
            neutral = [r for r in rows if r.get("scenario") == "neutral"]
            if len(neutral) != 3 or {r["price_factor"] for r in neutral} != set(FACTORS):
                raise replay.InputError("missing or duplicate future-price scenario")
            for row in neutral:
                if row["disposition"] != "evaluated" or row["capacity"] != capacity:
                    raise replay.InputError("invalid recommendation capacity")
                prices = {
                    p: replay._integer(v, "future price", 1)
                    for p, v in row["future_prices"].items()
                }
                if set(prices) != available or len(row["buy"]) != team.budget + 1:
                    raise replay.InputError("incomplete frozen price pool or frontier")
                candidates, fixed = available - {pid}, set(team.roster)
                passing = compact_bound(
                    row["passing"], team.budget, fixed, candidates, prices, players, rules
                )
                changes, previous = [], object()
                for budget, bound in enumerate(row["buy"]):
                    current = compact_bound(
                        bound, budget, fixed | {pid}, candidates, prices, players, rules
                    )
                    if current != previous:
                        changes.append([budget, current])
                        previous = current
                ceiling = row["roster_ceiling"]
                if ceiling is not None:
                    replay._integer(ceiling, "model ceiling", 0, capacity)
                cases[row["price_factor"]] = dict(
                    ceiling=ceiling, market_price=prices[pid], passing=passing, buy=changes
                )
        decisions.append(
            dict(
                pick=nomination.pick,
                player_id=pid,
                budget=team.budget,
                cash_cap=own["cash_cap"],
                room=room,
                cases=cases,
                blocked=blocked,
                history_count=len(state.sales),
            )
        )
    if records:
        raise replay.InputError("recommendations contain unknown auction picks")
    return dict(
        team=metadata["team"],
        season=rules.season,
        budget=rules.budget,
        roster_size=rules.roster_size,
        auction_hash=digest,
        decisions=decisions,
        players={p: dict(name=v.name, position=v.position) for p, v in players.items()},
        keepers=[sale_row(p) for p in picks if p.keeper],
        sales=[sale_row(p) for p in picks if not p.keeper],
        final_cash=sum(t.budget for t in replay.final_state(picks, rules).teams),
        preparation=dict(
            season=2026,
            teams=14,
            budget=200,
            keeper="Caleb Williams",
            keeper_cost=1,
            cash=199,
            open_slots=13,
            actionable=False,
        ),
    )


def validated_bound(
    bound, budget, fixed, candidates, prices, players, rules, nominee=None, factor=1, absences=()
):
    """Validate a feasible witness independently; absence of one is not infeasibility."""
    if set(bound) != {"lower", "upper", "roster", "cost", "status", "reason"}:
        raise replay.InputError("invalid bound fields; regenerate snapshot")
    lower = None if bound["lower"] is None else replay._decimal(bound["lower"], "lower bound")
    upper = None if bound["upper"] is None else replay._decimal(bound["upper"], "upper bound")
    status, roster, cost = bound["status"], bound["roster"], bound["cost"]
    if status == "infeasible":
        if any(v is not None for v in (lower, upper, roster, cost)):
            raise replay.InputError("infeasible bound contains a witness or score")
    elif status not in {"optimal", "unresolved"} or upper is None or upper < 0:
        raise replay.InputError("invalid bound status or upper bound")
    elif lower is None:
        if status != "unresolved" or roster is not None or cost is not None:
            raise replay.InputError("missing lower bound must have no witness")
    else:
        if lower < 0 or lower > upper or (status == "optimal") != (lower == upper):
            raise replay.InputError("inconsistent bound interval or proof status")
        if (
            not isinstance(roster, list)
            or len(roster) != rules.roster_size
            or any(not isinstance(p, str) for p in roster)
            or len(set(roster)) != len(roster)
            or not fixed <= set(roster)
            or not set(roster) <= fixed | candidates
            or replay.missing_starters(roster, players, rules)
        ):
            raise replay.InputError("invalid frozen roster membership or positions")
        cost = replay._integer(cost, "completion cost", 0, budget)
        if cost != sum(prices[p] for p in roster if p not in fixed):
            raise replay.InputError("frozen completion cost mismatch")
        if replay.projected_total(roster, players, rules, nominee, factor, absences) != lower:
            raise replay.InputError("weekly witness score mismatch; regenerate snapshot")
    if bound["reason"] is not None and not isinstance(bound["reason"], str):
        raise replay.InputError("invalid bound reason")
    return replay.RosterBound(
        lower, upper, tuple(roster) if roster is not None else None, cost, status, bound["reason"]
    )


def display_bound(bound):
    result = asdict(bound)
    for key in ("lower", "upper"):
        result[key] = str(result[key]) if result[key] is not None else None
    return result


def validate_effort(effort, config):
    if set(effort) != {
        "nodes",
        "work_limit",
        "exhausted",
        "relaxation_transitions",
        "relaxation_limit",
        "relaxation_complete",
        "relaxation_fallback",
    }:
        raise replay.InputError("invalid search effort fields")
    replay._integer(effort["nodes"], "search nodes", 0, config["work_limit"])
    replay._integer(
        effort["relaxation_transitions"], "relaxation transitions", 0, config["relaxation_limit"]
    )
    if (
        effort["work_limit"] != config["work_limit"]
        or effort["relaxation_limit"] != config["relaxation_limit"]
        or type(effort["exhausted"]) is not bool
        or type(effort["relaxation_complete"]) is not bool
        or effort["relaxation_fallback"] is not None
        and not isinstance(effort["relaxation_fallback"], str)
    ):
        raise replay.InputError("incompatible search effort")


def build_payload(picks, rules, players, frozen, weights=None, source_hashes=None):
    if frozen["metadata"].get("schema") != "joint-weekly/v1":
        if "schema" in frozen["metadata"]:
            raise replay.InputError("unknown snapshot schema; regenerate snapshot")
        return build_legacy_payload(picks, rules, players, frozen)
    metadata = frozen["metadata"]
    if weights is None:
        raise replay.InputError("joint snapshot requires independent reference weights")
    selection = pilot.joint_selection(
        picks, rules, players, weights, metadata["team"], metadata["selection"]["method"]
    )
    expected = pilot.make_joint_metadata(
        picks,
        rules,
        players,
        weights,
        metadata["team"],
        selection,
        metadata["config"]["work_limit"],
        metadata["config"]["relaxation_limit"],
        source_hashes,
    )
    if metadata != expected:
        raise replay.InputError(
            "stale or incompatible snapshot identity; regenerate recommendations"
        )
    records = defaultdict(list)
    for row in frozen["records"]:
        replay._integer(row["pick"], "nomination pick", 1)
        replay._integer(row["budget"], "remaining budget", 0)
        replay._integer(row["capacity"], "purchase capacity", 0)
        common_fields = {
            "pick",
            "player_id",
            "player",
            "budget",
            "held_roster",
            "capacity",
            "disposition",
        }
        case_fields = {
            "price_factor",
            "scenario",
            "forecast_factor",
            "absent_weeks",
            "static_ceiling",
            "inflation_ceiling",
            "supported_ceiling",
            "possible_ceiling",
            "future_prices",
            "prior_ratios",
            "buy",
            "passing",
            "buy_effort",
            "pass_effort",
            "prices",
        }
        if set(row) != common_fields | (
            case_fields if row["disposition"] == "evaluated" else {"reason"}
        ):
            raise replay.InputError("unexpected frozen record fields; regenerate snapshot")
        records[row["pick"]].append(row)
    decisions = []
    for moment in replay.replay_markets(picks, players, weights, rules):
        n = moment.nomination
        state, pid = n.state, n.player_id
        team = state.team(metadata["team"])
        room = room_snapshot(state, rules)
        own = next(t for t in room if t["name"] == team.name)
        available = set(players) - state.owned
        capacity, reason = replay.legal_capacity(team, pid, players, available, rules)
        rows = records.pop(n.pick, [])
        if not rows or any(
            r["player_id"] != pid
            or r["budget"] != team.budget
            or r["capacity"] != capacity
            or r["held_roster"] != list(team.roster)
            or r["player"] != players[pid].name
            for r in rows
        ):
            raise replay.InputError(f"frozen state mismatch at pick {n.pick}")
        blocked = selection["exclusions"].get(str(n.pick))
        disposition = (
            "excluded"
            if blocked
            else "unrun"
            if n.pick not in selection["selected_picks"]
            else "evaluated"
        )
        cases = {}
        if disposition != "evaluated":
            reason = blocked or "outside predeclared measured nomination set"
            if (
                len(rows) != 1
                or rows[0]["disposition"] != disposition
                or rows[0]["reason"] != reason
            ):
                raise replay.InputError("frozen exclusion or unrun state mismatch")
        else:
            expected_cases = {
                (str(f), label)
                for f in pilot.PRICE_FACTORS
                for label, _, _ in pilot.performance_cases(players[pid], rules)
            }
            if (
                len(rows) != 9
                or {(r["price_factor"], r["scenario"]) for r in rows} != expected_cases
            ):
                raise replay.InputError("missing or duplicate scenario; regenerate snapshot")
            static, _ = replay.baseline_ceiling(
                dict(moment.static), team, pid, players, available, rules
            )
            inflation, _ = replay.baseline_ceiling(
                dict(moment.inflation), team, pid, players, available, rules
            )
            for row in rows:
                factor, absences = next(
                    (f, a)
                    for label, f, a in pilot.performance_cases(players[pid], rules)
                    if label == row["scenario"]
                )
                prices = replay.future_prices(
                    dict(moment.inflation),
                    moment.prior_ratios,
                    replay._decimal(row["price_factor"], "future factor"),
                )
                prices.update({p: 1 for p in prices if players[p].position not in pilot.OFFENSE})
                if (
                    row["disposition"] != "evaluated"
                    or row["forecast_factor"] != str(factor)
                    or row["absent_weeks"] != list(absences)
                    or replay.canonical_bytes(row["future_prices"])
                    != replay.canonical_bytes(prices)
                    or replay.canonical_bytes(row["prior_ratios"])
                    != replay.canonical_bytes(moment.prior_ratios)
                    or row["static_ceiling"] != static
                    or row["inflation_ceiling"] != inflation
                    or len(row["buy"]) != team.budget + 1
                ):
                    raise replay.InputError("frozen scenario identity or market mismatch")
                for branch in ("buy", "pass"):
                    validate_effort(row[branch + "_effort"], metadata["config"])
                candidates, fixed = available - {pid}, set(team.roster)
                passing = validated_bound(
                    row["passing"], team.budget, fixed, candidates, prices, players, rules
                )
                buy = tuple(
                    validated_bound(
                        b,
                        budget,
                        fixed | {pid},
                        candidates,
                        prices,
                        players,
                        rules,
                        pid,
                        factor,
                        absences,
                    )
                    for budget, b in enumerate(row["buy"])
                )
                comparison = replay._compare_frontiers(
                    capacity,
                    team.budget,
                    replay.BudgetFrontier(buy, **row["buy_effort"]),
                    replay.BudgetFrontier((passing,) * (team.budget + 1), **row["pass_effort"]),
                )
                grid = pilot.decision_grid(comparison, static, inflation)
                if (
                    row["prices"] != grid
                    or row["supported_ceiling"] != comparison.supported_ceiling
                    or row["possible_ceiling"] != comparison.possible_ceiling
                ):
                    raise replay.InputError("frozen decision proof mismatch")
                changes, previous = [], object()
                for budget, bound in enumerate(buy):
                    current = display_bound(bound)
                    if current != previous:
                        changes.append([budget, current])
                        previous = current
                cases.setdefault(row["price_factor"], {})[row["scenario"]] = dict(
                    supported_ceiling=comparison.supported_ceiling,
                    possible_ceiling=comparison.possible_ceiling,
                    market_price=prices[pid],
                    passing=display_bound(passing),
                    buy=changes,
                    prices=grid,
                    forecast_factor=str(factor),
                    absent_weeks=list(absences),
                    buy_effort=row["buy_effort"],
                    pass_effort=row["pass_effort"],
                )
        decisions.append(
            dict(
                pick=n.pick,
                player_id=pid,
                budget=team.budget,
                cash_cap=own["cash_cap"],
                room=room,
                cases=cases,
                blocked=reason if disposition != "evaluated" else None,
                disposition=disposition,
                history_count=len(state.sales),
            )
        )
    if records:
        raise replay.InputError("unknown auction pick in snapshot")
    return dict(
        team=metadata["team"],
        season=rules.season,
        budget=rules.budget,
        roster_size=rules.roster_size,
        auction_hash=metadata["auction_transactions_sha256"],
        snapshot_hash=hashlib.sha256(replay.canonical_bytes(frozen)).hexdigest(),
        objective=metadata["config"]["objective"],
        config=metadata["config"],
        decisions=decisions,
        players={p: dict(name=v.name, position=v.position) for p, v in players.items()},
        keepers=[sale_row(p) for p in picks if p.keeper],
        sales=[sale_row(p) for p in picks if not p.keeper],
        final_cash=sum(t.budget for t in replay.final_state(picks, rules).teams),
        preparation=dict(
            season=2026,
            teams="14 maximum; final count unresolved",
            budget=200,
            keeper="Caleb Williams",
            keeper_cost=1,
            cash=199,
            open_slots=13,
            actionable=False,
        ),
    )


def render_html(data):
    payload = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    return (TEMPLATES / "draft-companion.html").read_text().replace("<!--PAYLOAD-->", payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=JOINT_INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    temporary = None
    try:
        picks, rules, players, weights, *_ = pilot.load_pilot()
        frozen = json.loads(args.input.read_text())
        if frozen["metadata"].get("schema") != "joint-weekly/v1":
            raise replay.InputError(
                "this view requires joint-weekly recommendations; preserve the historical comparator and regenerate joint input"
            )
        payload = build_payload(picks, rules, players, frozen, weights)
        html = render_html(payload)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=args.output.parent, delete=False
        ) as target:
            temporary = Path(target.name)
            target.write(html)
            target.flush()
        temporary.replace(args.output)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        print(f"Companion not generated: {error}")
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Built {len(payload['decisions'])} decisions: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
