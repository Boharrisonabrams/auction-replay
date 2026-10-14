"""Study affordable bye coverage using frozen, forecast-only roster seeds."""
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from . import build_draft_companion as companion
from . import historical_price_pilot as pilot
from . import replay_auction as replay

OUTPUT = pilot.ROOT / "data/local/2025/bench-coverage"


def improve_bench(seed, fixed, candidates, prices, players, rules, budget):
    """Improve a feasible roster; return a lower bound, never an optimal bid."""
    budget = replay._integer(budget, "completion budget", 0)
    roster, fixed, candidates = tuple(sorted(seed)), set(fixed), set(candidates)
    if (len(roster) != rules.roster_size or len(set(roster)) != len(roster)
            or not fixed <= set(roster) or fixed & candidates
            or (fixed | candidates) - players.keys()
            or not set(roster) <= fixed | candidates):
        raise replay.InputError("invalid seed, fixed players, or candidate pool")
    prices = {p: replay._integer(prices.get(p), "candidate price", 1) for p in candidates}
    if replay.missing_starters(roster, players, rules):
        raise replay.InputError("seed cannot fill starters")
    cost = sum(prices[p] for p in roster if p not in fixed)
    if cost > budget:
        raise replay.InputError("seed exceeds completion budget")
    weights, _ = replay._forecast_weights(players, rules, None, Decimal(1), ())
    # Week 0 selects the no-bye starting core; validated player byes are 1..18.
    protected = fixed | set(replay._projected_lineup(roster, players, weights, rules, 0, None, ()))
    protected.discard(None)

    def score(keys):
        return replay._projected_total(keys, players, weights, rules, None, ())

    points, swaps = score(roster), []
    # ponytail: three greedy bench swaps; use a stronger solver if bounds are needed.
    for _ in range(3):
        best = None
        best_points = points
        roster_set = set(roster)
        incoming_keys = sorted(candidates - roster_set)
        for outgoing in sorted(roster_set - protected):
            for incoming in incoming_keys:
                next_cost = cost - prices[outgoing] + prices[incoming]
                if next_cost > budget:
                    continue
                trial = tuple(sorted((roster_set - {outgoing}) | {incoming}))
                if replay.missing_starters(trial, players, rules):
                    continue
                trial_points = score(trial)
                if trial_points > best_points:
                    best_points = trial_points
                    best = trial, next_cost, outgoing, incoming
        if best is None:
            break
        roster, cost, outgoing, incoming = best
        swaps.append(dict(outgoing=outgoing, incoming=incoming, projected_gain=best_points - points))
        points = best_points
    return dict(roster=list(roster), cost=cost, projected_points=points,
                protected=sorted(protected), swaps=swaps, status="feasible_lower_bound")


def study(frozen, players, rules):
    """Use each frozen room-price estimate, never the nominee's closing price."""
    records = []
    for row in frozen["records"]:
        if row["disposition"] != "evaluated":
            records.append({k: row[k] for k in ("pick", "player_id", "disposition")})
            continue
        if row["scenario"] != "neutral":
            continue
        price = row["future_prices"][row["player_id"]]
        result = dict(pick=row["pick"], player_id=row["player_id"],
                      price_factor=row["price_factor"], probe_price=price,
                      capacity=row["capacity"], disposition="evaluated")
        records.append(result)
        if price > row["capacity"]:
            result["disposition"] = "room_price_exceeds_legal_capacity"
            continue
        buy = row["buy"][row["budget"] - price]
        if buy["roster"] is None or row["passing"]["roster"] is None:
            result["disposition"] = "no_feasible_seed_at_room_price"
            continue
        pool = set(row["future_prices"]) - {row["player_id"]}
        for label, seed, fixed, budget in (
            ("buy", buy, set(row["held_roster"]) | {row["player_id"]}, row["budget"] - price),
            ("pass", row["passing"], set(row["held_roster"]), row["budget"]),
        ):
            result[label] = dict(
                seed=dict(roster=seed["roster"], cost=seed["cost"],
                          projected_points=replay.projected_total(seed["roster"], players, rules)),
                repaired=improve_bench(seed["roster"], fixed, pool, row["future_prices"],
                                       players, rules, budget))
        # A difference between feasible solutions is descriptive, not a decision bound.
        result["comparison_status"] = "unresolved_no_optimality_bounds"
        if row["price_factor"] == "1.2":
            print(f"Bench study frozen through pick {row['pick']}", flush=True)
    return records


def evaluate(records, players, rules, gsis):
    core, full, coverage = pilot.load_outcomes(players, gsis)
    offense_rules = replace(rules, starters=tuple(p for p in rules.starters if p in (*pilot.OFFENSE, "FLEX")))
    cache, rows = {}, []
    for row in records:
        if row["disposition"] != "evaluated":
            continue
        result = {k: row[k] for k in ("pick", "player_id", "price_factor", "probe_price")}
        for branch in ("buy", "pass"):
            result[branch] = {}
            for version in ("seed", "repaired"):
                roster = tuple(sorted(row[branch][version]["roster"]))
                if roster not in cache:
                    cache[roster] = {}
                    for label, outcomes in (("core", core), ("full_offense", full)):
                        scored = replay.evaluate_roster(roster, players, offense_rules, outcomes)
                        cache[roster][label] = dict(points=scored["fixed_preseason_total"],
                                                    missing=scored["missing_selected"])
                result[branch][version] = cache[roster]
        rows.append(result)
    return rows, coverage


def main(output_dir=OUTPUT):
    picks, rules, players, _, gsis, _ = pilot.load_pilot()
    frozen = json.loads(companion.DEFAULT_INPUT.read_text())
    # Reuse the companion's full source, state, money, and roster validation.
    companion.build_payload(picks, rules, players, frozen)
    inputs = (companion.DEFAULT_INPUT, Path(__file__), Path(replay.__file__),
              Path(pilot.__file__), Path(companion.__file__))
    metadata = dict(
        team=frozen["metadata"]["team"], full_benchmark_complete=False,
        objective="Weeks 1-17 core-offense starters with scheduled bye coverage",
        method="Preserve held players and the seed starting core; at most three positive bench swaps",
        probe="Frozen neutral room price under each future-price factor, before actual closing price",
        status="Feasible roster improvements only; no optimal bid or demonstrated advantage",
        source_hashes={str(p.relative_to(pilot.ROOT)): replay._file_hash(p) for p in inputs},
        seed_metadata=frozen["metadata"])
    records = study(frozen, players, rules)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "rosters.json"
    pilot.save_json(path, dict(metadata=metadata, records=records))
    digest = replay._file_hash(path)
    rows, coverage = evaluate(records, players, rules, gsis)
    if replay._file_hash(path) != digest:
        raise replay.InputError("frozen bench rosters changed during evaluation")
    pilot.save_json(output_dir / "evaluation.json", dict(roster_sha256=digest, coverage=coverage, rows=rows))
    print(f"Saved {len(records)} coverage records and {len(rows)} paired probes to {output_dir}")


if __name__ == "__main__":
    main()
