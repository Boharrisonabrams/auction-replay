"""Exploratory 2025 core-offense price experiment; never accepted full-scoring inputs.

Fixed-starter mode preserves the best fixed starting lineup's season projection
times 16/17, with no bench utility. Joint-weekly mode bounds complete rosters with
scheduled bye coverage. Both freeze recommendations before the separate outcome
evaluation, which uses neutral preseason ordering and known byes for all policies.
K/DEF production is excluded, with their roster places and future $1 costs kept.
"""

import csv
import hashlib
import json
import re
import argparse
import time
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from . import replay_auction as replay

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RESEARCH = ROOT / "docs" / "research"
SOURCE = ROOT / "data/local/2025/sources"
OFFENSE = ("QB", "RB", "WR", "TE")
PRICE_FACTORS = (Decimal("0.8"), Decimal(1), Decimal("1.2"))
JOINT_OBJECTIVE = "weekly-core-offense/v1: complete rosters, scheduled byes, uniform projection per 17 NFL games"
ALIASES = {"hollywoodbrown": "marquisebrown", "joshuapalmer": "joshpalmer"}
FORECAST_FIELDS = {
    "QB": {6: "passing_yards", 7: "passing_tds", 8: "passing_interceptions", 10: "rushing_yards", 11: "rushing_tds"},
    "RB": {5: "rushing_yards", 6: "rushing_tds", 7: "receptions", 8: "receiving_yards", 9: "receiving_tds"},
    "WR": {4: "receptions", 5: "receiving_yards", 6: "receiving_tds", 8: "rushing_yards", 9: "rushing_tds"},
    "TE": {4: "receptions", 5: "receiving_yards", 6: "receiving_tds"},
}
ACTUAL_FULL = dict(passing_yards=".04", passing_tds="4", passing_interceptions="-1", rushing_yards=".1", rushing_tds="6",
                   receptions=".5", receiving_yards=".1", receiving_tds="6",
                   fumbles_lost_total="-2", passing_2pt_conversions="2", rushing_2pt_conversions="2",
                   receiving_2pt_conversions="2", special_teams_tds="6", fumble_recovery_tds="6")
ACTUAL_CORE = {pos: {field: ACTUAL_FULL[field] for field in fields.values()} for pos, fields in FORECAST_FIELDS.items()}
# Outcome-only exceptions, documented in the report; never remove their forecasts.
NONPARTICIPANTS = {"00-0033897", "00-0036261", "00-0031544"}


def name_key(name):
    name = re.sub(r"\s+(?:Jr\.?|Sr\.?|II|III|IV)$", "", name, flags=re.I)
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return ALIASES.get(key, key)


def core_projection(position, cells):
    return sum((replay._decimal(cells[index].replace(",", ""), "projection component") * Decimal(ACTUAL_FULL[field])
                for index, field in FORECAST_FIELDS[position].items()), Decimal(0))


def load_pilot():
    """Use forecasts and identities only; the auction loader discards outcome fields."""
    rules = replay.load_rules(ROOT / "data/local/2025/rules.json")
    picks = replay.load_auction(RESEARCH / "2025-discount-double-check-auction.csv", rules)
    inventory = json.loads((SOURCE / "source-inventory.json").read_text())
    for item in inventory:
        if item["name"].startswith("weekly-"):
            continue  # Outcome bytes are not inspected at the policy boundary.
        path = SOURCE / item["file"]
        if replay._file_hash(path) != item["sha256"]:
            raise replay.InputError(f"source hash mismatch: {path.name}")
        if item.get("publisher_date"):
            date = datetime.strptime(item["publisher_date"], "%m/%d/%Y" if len(item["publisher_date"].split("/")[-1]) == 4 else "%m/%d/%y")
            if date.date() >= datetime.fromisoformat(rules.draft_at).date():
                raise replay.InputError("non-preseason source date")
    draft_keys = {(name_key(p.name), p.position): p.player_id for p in picks if p.position != "DEF"}
    defenses = {p.name: p.player_id for p in picks if p.position == "DEF"}
    with (SOURCE / "player-ids.csv").open() as f:
        identities = list(csv.DictReader(f))
    by_name = defaultdict(set)
    for row in identities:
        if row["gsis_id"] not in {"", "NA"}:
            by_name[name_key(row["name"]), row["position"]].add(row["gsis_id"])
    players, gsis, keys = {}, {}, set()
    candidates = json.loads((SOURCE / "candidate-forecast-rows.json").read_text())
    for row in candidates:
        pos, name, cells = row["position"], row["name"], row["cells"]
        key = (name_key(name), pos)
        if key in keys:
            raise replay.InputError(f"ambiguous forecast name: {key}")
        keys.add(key)
        if pos == "DEF":
            matches = [pid for nickname, pid in defenses.items() if name.endswith(" " + nickname)]
            if len(matches) > 1:
                raise replay.InputError("ambiguous defense")
            pid = matches[0] if matches else "fftoday:def:" + name_key(name)
            team, bye, points = name, cells[2], Decimal(0)
        else:
            provider = re.search(r"/players/(\d+)/", row["provider_url"])
            if provider is None:
                raise replay.InputError("missing forecast source identity")
            pid = draft_keys.get(key, "fftoday:" + provider[1])
            team, bye = cells[2:4]
            points = core_projection(pos, cells) if pos in OFFENSE else Decimal(0)
        if pid in players:
            raise replay.InputError(f"duplicate player identity: {pid}")
        players[pid] = replay.Player(pid, name, pos, team, replay._integer(bye, "bye", 1, 18), points)
        matches = by_name.get(key, set())
        # Patriots 2025 round 3/pick 69, unlike the 2010 Arizona State namesake.
        if key == ("kylewilliams", "WR") and team == "NE":
            matches = matches & {"00-0040131"}
        gsis[pid] = next(iter(matches)) if len(matches) == 1 else None
    replay._validate_auction_forecasts(picks, players)
    # Value above positional replacement. These ranks are declared assumptions:
    # 14 QBs, 28 RBs, 28 WRs, 14 TEs, plus seven RB and seven WR FLEX starters.
    replacement_ranks = {"QB": 14, "RB": 35, "WR": 35, "TE": 14}
    weights, baselines = {}, {}
    for pos, rank in replacement_ranks.items():
        group = sorted((p for p in players.values() if p.position == pos), key=lambda p: (-p.projected_points, p.player_id))
        baseline = group[rank].projected_points  # first player beyond starter demand
        baselines[pos] = baseline
        weights.update({p.player_id: Decimal(1) + max(Decimal(0), p.projected_points - baseline) for p in group})
    weights.update({p.player_id: Decimal(1) for p in players.values() if p.position not in OFFENSE})
    return picks, rules, players, weights, gsis, baselines


def season_frontier(fixed, candidates, prices, players, rules, max_budget,
                    nominee=None, forecast_factor=Decimal(1), bench_credit=Decimal(0)):
    """Preserve the historical pilot's exact fixed-starter 16/17 objective."""
    raw = replay.positional_frontier(fixed, candidates, prices, players, rules, max_budget,
                                    nominee, forecast_factor, bench_credit)
    if not raw.complete:
        raise replay.InputError(raw.fallback)
    bounds = tuple(replay.RosterBound(Decimal(v[0]) * 16 / 17000000, Decimal(v[0]) * 16 / 17000000,
                                     v[2], v[1], "optimal", None)
                   if v else replay.RosterBound(None, None, None, None, "infeasible", "no complete roster")
                   for v in raw.entries)
    return replay.BudgetFrontier(bounds, 0, 0, False, relaxation_transitions=raw.transitions,
                                 relaxation_complete=True)


def recommend(picks, rules, players, weights, team_name, progress=None):
    records = []
    for moment in replay.replay_markets(picks, players, weights, rules):
        n = moment.nomination
        team = n.state.team(team_name)
        available = set(players) - n.state.owned
        cap, reason = replay.legal_capacity(team, n.player_id, players, available, rules)
        common = dict(pick=n.pick, player_id=n.player_id, player=players[n.player_id].name,
                      budget=team.budget, held_roster=team.roster, capacity=cap)
        if reason or players[n.player_id].position not in OFFENSE:
            records.append(dict(common, disposition=reason or "specialist excluded from pilot"))
            continue
        static, _ = replay.baseline_ceiling(dict(moment.static), team, n.player_id, players, available, rules)
        inflation, _ = replay.baseline_ceiling(dict(moment.inflation), team, n.player_id, players, available, rules)
        for factor in (Decimal(".8"), Decimal(1), Decimal("1.2")):
            prices = replay.future_prices(dict(moment.inflation), moment.prior_ratios, factor)
            prices.update({k: 1 for k in prices if players[k].position not in OFFENSE})
            candidates = available - {n.player_id}
            passing = season_frontier(team.roster, candidates, prices, players, rules, team.budget)
            for label, forecast_factor, bench_credit in (("neutral", Decimal(1), Decimal(0)),
                    ("forecast_minus_20_percent", Decimal(".8"), Decimal(0)),
                    ("two_absences_equivalent", Decimal(".875"), Decimal(0)),
                    ("backup_credit_12.5_percent", Decimal(1), Decimal(".125")),
                    ("backup_credit_25_percent", Decimal(1), Decimal(".25"))):
                pass_case = (season_frontier(team.roster, candidates, prices, players, rules, team.budget,
                                            bench_credit=bench_credit) if bench_credit else passing)
                buy = season_frontier(team.roster + (n.player_id,), candidates, prices, players, rules,
                                      team.budget, n.player_id, forecast_factor, bench_credit)
                comparison = replay._compare_frontiers(cap, team.budget, buy, pass_case)
                records.append(dict(common, disposition="evaluated", price_factor=str(factor), scenario=label,
                                    static_ceiling=static, inflation_ceiling=inflation,
                                    roster_ceiling=comparison.supported_ceiling,
                                    future_prices=prices, prior_ratios=moment.prior_ratios,
                                    buy=[asdict(bound) for bound in buy.bounds],
                                    passing=asdict(pass_case.bounds[team.budget])))
        if progress:
            progress(n.pick, common["player"], len(records))
    return records


def performance_cases(player, rules):
    weeks = tuple(w for w in range(rules.first_week, rules.last_week + 1) if w != player.bye)[:2]
    if len(weeks) != 2:
        raise replay.InputError("two non-bye sensitivity weeks are unavailable")
    return (("neutral", Decimal(1), ()), ("forecast_minus_20_percent", Decimal("0.8"), ()),
            ("two_non_bye_absences", Decimal(1), weeks))


def joint_selection(picks, rules, players, weights, team_name, selection="probes"):
    """Declare the measured nomination set using forecasts and observed prefixes only."""
    if selection not in {"probes", "all"}:
        raise replay.InputError("selection must be probes or all")
    eligible, excluded, all_picks = [], {}, []
    for moment in replay.replay_markets(picks, players, weights, rules):
        n = moment.nomination
        _, reason = replay.legal_capacity(n.state.team(team_name), n.player_id, players,
                                          set(players) - n.state.owned, rules)
        reason = reason or ("specialist excluded from pilot" if players[n.player_id].position not in OFFENSE else None)
        all_picks.append(n.pick)
        if reason:
            excluded[str(n.pick)] = reason
        else:
            eligible.append(n.pick)
    chosen = eligible if selection == "all" else sorted({eligible[i] for i in (0, len(eligible) // 2, -1)}) if eligible else []
    return dict(method=selection, all_picks=all_picks, eligible_picks=eligible,
                selected_picks=chosen, exclusions=excluded)


def joint_config(rules, work_limit, relaxation_limit):
    return dict(objective=JOINT_OBJECTIVE, horizon=[rules.first_week, rules.last_week],
                price_factors=[str(f) for f in PRICE_FACTORS],
                performance_protocol="neutral; forecast x0.8; absent first two non-bye evaluation weeks",
                work_limit=replay._integer(work_limit, "search work limit", 1),
                relaxation_limit=replay._integer(relaxation_limit, "relaxation limit", 0),
                future_specialist_price=1, primary_price_grid="every legal whole-dollar price")


def policy_source_hashes():
    """Hash only policy inputs; outcome inventory entries and bytes remain excluded."""
    inventory = [item for item in json.loads((SOURCE / "source-inventory.json").read_text())
                 if not item["name"].startswith("weekly-")]
    hashes = {"policy_inventory": hashlib.sha256(replay.canonical_bytes(inventory)).hexdigest()}
    paths = [SOURCE / item["file"] for item in inventory]
    paths += [SOURCE / "candidate-forecast-rows.json", ROOT / "data/local/2025/rules.json"]
    for path in paths:
        hashes[str(path.relative_to(ROOT))] = replay._file_hash(path)
    return hashes


def make_joint_metadata(picks, rules, players, weights, team_name, selection,
                        work_limit=2000, relaxation_limit=2000000, source_hashes=None):
    return dict(schema="joint-weekly/v1", snapshot_kind="companion", team=team_name,
                scoring="position-available core offense only; K/DEF scoring excluded", full_benchmark_complete=False,
                config=joint_config(rules, work_limit, relaxation_limit), selection=selection,
                auction_transactions_sha256=hashlib.sha256(replay.canonical_bytes(picks)).hexdigest(),
                inputs_sha256=hashlib.sha256(replay.canonical_bytes(dict(rules=rules, players=players, weights=weights))).hexdigest(),
                code_hashes={p.name: replay._file_hash(p) for p in (Path(__file__), Path(replay.__file__))},
                source_hashes=policy_source_hashes() if source_hashes is None else source_hashes)


def decision_grid(comparison, static, inflation):
    """Freeze exact Decimal proof classifications, including infeasible and unresolved."""
    rows = []
    for c in comparison.prices:
        row = dict(price=c.price, roster_action=c.decision, reason=c.reason)
        for policy, ceiling in (("static", static), ("inflation", inflation)):
            action, reason = replay.policy_action(c.price, ceiling, c.buy, c.passing)
            row[policy + "_action"] = "buy" if action == "supported" else action
            row[policy + "_reason"] = reason
        rows.append(row)
    return rows


def recommend_joint(picks, rules, players, weights, team_name, selection,
                    work_limit=2000, relaxation_limit=2000000, progress=None, timings=None):
    if selection != joint_selection(picks, rules, players, weights, team_name, selection["method"]):
        raise replay.InputError("selection does not match forecast-only eligibility")
    joint_config(rules, work_limit, relaxation_limit)
    records = []
    for moment in replay.replay_markets(picks, players, weights, rules):
        n = moment.nomination
        team, available = n.state.team(team_name), set(players) - n.state.owned
        cap, reason = replay.legal_capacity(team, n.player_id, players, available, rules)
        common = dict(pick=n.pick, player_id=n.player_id, player=players[n.player_id].name,
                      budget=team.budget, held_roster=list(team.roster), capacity=cap)
        blocked = selection["exclusions"].get(str(n.pick))
        if blocked or n.pick not in selection["selected_picks"]:
            records.append(dict(common, disposition="excluded" if blocked else "unrun",
                                reason=blocked or "outside predeclared measured nomination set"))
            continue
        static, _ = replay.baseline_ceiling(dict(moment.static), team, n.player_id, players, available, rules)
        inflation, _ = replay.baseline_ceiling(dict(moment.inflation), team, n.player_id, players, available, rules)
        for price_factor in PRICE_FACTORS:
            prices = replay.future_prices(dict(moment.inflation), moment.prior_ratios, price_factor)
            prices.update({pid: 1 for pid in prices if players[pid].position not in OFFENSE})

            def frontier(fixed, label, factor=Decimal(1), absences=()):
                timing = {}
                result = replay.completion_frontier(fixed, available - {n.player_id}, prices, players, rules,
                    team.budget, work_limit, n.player_id, factor, absences, relaxation_limit, timing)
                if timings is not None:
                    timings.append(dict(pick=n.pick, price_factor=str(price_factor), branch=label, **timing))
                return result

            passing = frontier(team.roster, "pass")
            for label, factor, absences in performance_cases(players[n.player_id], rules):
                buy = frontier(team.roster + (n.player_id,), label, factor, absences)
                comparison = replay._compare_frontiers(cap, team.budget, buy, passing)
                effort = lambda f: {k: v for k, v in asdict(f).items() if k != "bounds"}
                records.append(dict(common, disposition="evaluated", price_factor=str(price_factor), scenario=label,
                    forecast_factor=str(factor), absent_weeks=list(absences),
                    static_ceiling=static, inflation_ceiling=inflation,
                    supported_ceiling=comparison.supported_ceiling, possible_ceiling=comparison.possible_ceiling,
                    future_prices=dict(sorted(prices.items())), prior_ratios=moment.prior_ratios,
                    buy=[asdict(b) for b in buy.bounds], passing=asdict(passing.bounds[team.budget]),
                    buy_effort=effort(buy), pass_effort=effort(passing),
                    prices=decision_grid(comparison, static, inflation)))
        if progress:
            progress(n.pick, common["player"], len(records))
    return records


def evaluate_joint(records, players, rules, gsis, picks):
    """Paired policy outcomes on the frozen whole-dollar grid; never sum branches."""
    cases = defaultdict(list)
    for record in records:
        if record['disposition'] == 'evaluated':
            cases[record['pick']].append(record)
    core, full, coverage = load_outcomes(players, gsis)
    offense_rules = replace(rules, starters=tuple(s for s in rules.starters if s not in {"K", "DEF"}))
    cache, rows = {}, []
    sales = {p.pick: p.salary for p in picks if not p.keeper}

    def score(bound):
        if bound["roster"] is None:
            return None
        key = tuple(sorted(bound["roster"]))
        if key not in cache:
            result = {}
            for label, actuals in (("core", core), ("full_offense", full)):
                evaluated = replay.evaluate_roster(key, players, offense_rules, actuals)
                result[label] = evaluated["fixed_preseason_total"]
                result[label + "_hindsight"] = evaluated["optimistic_hindsight_total"]
                result[label + "_missing"] = evaluated["missing_selected"]
            cache[key] = result
        return cache[key]

    for record in records:
        if record["disposition"] != "evaluated":
            rows.append({k: record[k] for k in ("pick", "player_id", "disposition", "reason")})
            continue
        passed = score(record["passing"])
        grid = cases[record['pick']]
        same_prices = [r for r in grid if r['price_factor'] == record['price_factor']]
        neutral = next(r for r in same_prices if r['scenario'] == 'neutral')
        for decision in record["prices"]:
            price = decision["price"]
            buy_bound = record["buy"][record["budget"] - price]
            bought = score(buy_bound)
            row = dict(pick=record["pick"], player_id=record["player_id"], disposition="evaluated",
                       price_factor=record["price_factor"], scenario=record["scenario"], **decision,
                       forecast_factor=record['forecast_factor'], absent_weeks=record['absent_weeks'],
                       scenario_disagreement=len({r['prices'][price - 1]['roster_action'] for r in grid}) > 1,
                       supported_ceiling=record['supported_ceiling'], possible_ceiling=record['possible_ceiling'],
                       neutral_supported_ceiling=neutral['supported_ceiling'], neutral_possible_ceiling=neutral['possible_ceiling'],
                       supported_min=min(r['supported_ceiling'] for r in same_prices),
                       supported_max=max(r['supported_ceiling'] for r in same_prices),
                       possible_min=min(r['possible_ceiling'] for r in same_prices),
                       possible_max=max(r['possible_ceiling'] for r in same_prices),
                       buy_evaluation=bought, pass_evaluation=passed,
                       closing_price_plus=price - sales[record["pick"]] if price - sales[record["pick"]] in (0, 1, 5, 10) else None)
            for branch, bound in (('buy', buy_bound), ('pass', record['passing'])):
                for key in ('lower', 'upper', 'status', 'cost'):
                    row[branch + '_' + key] = bound[key]
                row[branch + '_interval_width'] = (None if bound['lower'] is None or bound['upper'] is None else
                                                   Decimal(bound['upper']) - Decimal(bound['lower']))
                row.update({branch + '_' + key: value for key, value in record[branch + '_effort'].items()})
            selected = {p: bought if decision[p + "_action"] == "buy" else passed
                        if decision[p + "_action"] == "pass" else None for p in ("roster", "static", "inflation")}
            for baseline in ("static", "inflation"):
                pair = (selected["roster"], selected[baseline])
                for label in ("core", "full_offense"):
                    reason = ("policy unresolved or no feasible selected witness" if any(v is None for v in pair)
                              else "missing selected weekly outcomes" if any(v[label] is None for v in pair) else None)
                    row[f"{baseline}_{label}_delta"] = None if reason else pair[0][label] - pair[1][label]
                    row[f"{baseline}_{label}_unmatched"] = reason
            rows.append(row)
    coverage = dict(coverage, accounting=dict(Counter(r["disposition"] for r in records)),
                    nomination_accounting=dict(Counter({r['pick']: r['disposition'] for r in records}.values())),
                    primary="matched forecast-covered components; every legal whole-dollar price",
                    sensitivity="full offense; actual closing price plus 0/1/5/10 is secondary",
                    interpretation="Overlapping branches are neither season totals nor independent samples")
    return rows, coverage


def load_outcomes(players, gsis):
    """Outcome-only boundary, called after the recommendation file is frozen.

    A known season participant's absent weekly row is a zero-stat assumption,
    supported by complete team-game coverage and drafted season reconciliation.
    Never infer a season-long nonparticipant from absence alone.
    """
    for item in json.loads((SOURCE / "source-inventory.json").read_text()):
        if item["name"].startswith("weekly-") and replay._file_hash(SOURCE / item["file"]) != item["sha256"]:
            raise replay.InputError("outcome source hash mismatch")
    with (SOURCE / "weekly-team-stats.csv").open() as f:
        team_rows = [r for r in csv.DictReader(f) if r["season_type"] == "REG"]
    if (len(team_rows) != 544 or set(Counter(r["team"] for r in team_rows).values()) != {17}
            or len({(r["game_id"], r["team"]) for r in team_rows}) != 544
            or set(Counter(r["game_id"] for r in team_rows).values()) != {2}
            or any(r["season"] != "2025" for r in team_rows)):
        raise replay.InputError("incomplete regular-season team coverage")
    with (SOURCE / "weekly-player-stats.csv").open() as f:
        rows = [r for r in csv.DictReader(f) if r["season_type"] == "REG"]
    stats = {}
    for row in rows:
        if row["season"] != "2025":
            raise replay.InputError("wrong outcome season")
        key = row["player_id"], replay._integer(row["week"], "outcome week", 1, 18)
        if key in stats:
            raise replay.InputError("duplicate weekly player")
        stats[key] = row
    participants = {key[0] for key in stats}
    core, full = {}, {}
    for pid, player in players.items():
        if player.position not in OFFENSE:
            continue
        identity = gsis[pid]
        for week in range(1, 19):
            row = stats.get((identity, week))
            for target, coefficients in ((core, ACTUAL_CORE[player.position]), (full, ACTUAL_FULL)):
                target[pid, week] = (sum((replay._decimal(row[key], key) * Decimal(weight)
                                         for key, weight in coefficients.items()), Decimal(0)) if row else
                                     Decimal(0) if identity in participants | NONPARTICIPANTS else None)
    # Reconcile full-season sums only for source validation, never optimization.
    with (RESEARCH / "2025-discount-double-check-auction.csv").open() as f:
        auction = list(csv.DictReader(f))
    verified, gaps = 0, []
    for row in auction:
        if row["position"] not in OFFENSE:
            continue
        values = [full.get((row["id"], week)) for week in range(1, 19)]
        if any(v is None for v in values):
            gaps.append(row["name"])
        elif sum(values, Decimal(0)) != Decimal(row["points"]):
            raise replay.InputError(f"Yahoo outcome reconciliation mismatch: {row['name']}")
        else:
            verified += 1
    return core, full, {"drafted_offense_reconciled": verified, "unreconciled": gaps,
                        "zero_week_assumption": "Known season participant without a weekly stat row has zero recorded stats",
                        "explicit_nonparticipant_gsis": sorted(NONPARTICIPANTS)}


def evaluate(records, players, rules, gsis):
    core, full, coverage = load_outcomes(players, gsis)
    offense_rules = replace(rules, starters=tuple(s for s in rules.starters if s not in {"K", "DEF"}))
    with (RESEARCH / "2025-discount-double-check-auction.csv").open() as f:
        sales = {int(r["pick"]): int(r["salary"]) for r in csv.DictReader(f)}
    cache = {}

    def score(roster):
        key = tuple(sorted(roster))
        if key not in cache:
            result = {}
            for label, actuals in (("core", core), ("full_offense", full)):
                e = replay.evaluate_roster(key, players, offense_rules, actuals)
                result[label] = e["fixed_preseason_total"]
                result[label + "_hindsight"] = e["optimistic_hindsight_total"]
                result[label + "_missing"] = len(e["missing_selected"])
            cache[key] = result
        return cache[key]

    evaluations = []
    for row in records:
        if row["disposition"] != "evaluated":
            continue
        passed = row["passing"]
        for extra in (0, 1, 5, 10):
            price = sales[row["pick"]] + extra
            if price > row["capacity"]:
                continue
            bought = row["buy"][row["budget"] - price]
            if not bought["roster"] or not passed["roster"]:
                continue
            buy_score, pass_score = score(bought["roster"]), score(passed["roster"])
            evaluations.append(dict(pick=row["pick"], player=row["player"], price_factor=row["price_factor"],
                                    scenario=row["scenario"], price=price, closing_price_plus=extra,
                                    static_action="buy" if price <= row["static_ceiling"] else "pass",
                                    inflation_action="buy" if price <= row["inflation_ceiling"] else "pass",
                                    roster_action="buy" if price <= row["roster_ceiling"] else "pass",
                                    projected_delta=bought["lower"] - passed["lower"],
                                    buy_roster=bought["roster"], pass_roster=passed["roster"],
                                    buy_cost=bought["cost"] + price, pass_cost=passed["cost"],
                                    buy_evaluation=buy_score, pass_evaluation=pass_score,
                                    **{label + "_delta": buy_score[label] - pass_score[label]
                                       if buy_score[label] is not None and pass_score[label] is not None else None
                                       for label in ("core", "full_offense")}))
    return evaluations, coverage


def save_json(path, data):
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", delete=False) as f:
        temporary = Path(f.name)
        try:
            json.dump(data, f, indent=2, default=str, allow_nan=False)
            f.write("\n")
            f.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--team", default="Team Bo")
    parser.add_argument("--mode", choices=("fixed-starter", "joint-weekly"), default="fixed-starter")
    parser.add_argument("--selection", choices=("probes", "all"), default="probes")
    parser.add_argument("--work-limit", type=int, default=2000)
    parser.add_argument("--relaxation-limit", type=int, default=2000000)
    args = parser.parse_args()
    if args.output_dir is None:
        args.output_dir = ROOT / 'data/local/2025' / ('joint-roster-pilot' if args.mode == 'joint-weekly' else 'price-pilot')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    picks, rules, players, weights, gsis, baselines = load_pilot()
    if args.mode == "joint-weekly":
        selection = joint_selection(picks, rules, players, weights, args.team, args.selection)
        metadata = make_joint_metadata(picks, rules, players, weights, args.team, selection,
                                      args.work_limit, args.relaxation_limit)
        save_json(args.output_dir / "selection.json", metadata)
        timings = []
        records = recommend_joint(picks, rules, players, weights, args.team, selection,
            args.work_limit, args.relaxation_limit,
            lambda pick, name, count: print(f"Frozen through pick {pick}: {name}; {count} records", flush=True), timings)
        path = args.output_dir / "recommendations.json"
        save_json(path, dict(metadata=metadata, records=records))
        digest = replay._file_hash(path)
        save_json(args.output_dir / "timings.json", dict(recommendation_sha256=digest, rows=timings))
        rows, coverage = evaluate_joint(records, players, rules, gsis, picks)
        if replay._file_hash(path) != digest:
            raise replay.InputError("frozen recommendations changed during evaluation")
        save_json(args.output_dir / "evaluation.json", dict(recommendation_sha256=digest, coverage=coverage, rows=rows))
        fields = ["pick", "player_id", "disposition", "reason", "price_factor", "scenario", "price", "closing_price_plus",
                  "roster_action", "static_action", "inflation_action", "static_reason", "inflation_reason",
                  "forecast_factor", "absent_weeks", "scenario_disagreement", "supported_ceiling", "possible_ceiling",
                  "neutral_supported_ceiling", "neutral_possible_ceiling", "supported_min", "supported_max", "possible_min", "possible_max"]
        fields += [f'{branch}_{key}' for branch in ('buy', 'pass') for key in
                   ('lower', 'upper', 'status', 'cost', 'interval_width', 'nodes', 'work_limit', 'exhausted',
                    'relaxation_transitions', 'relaxation_limit', 'relaxation_complete', 'relaxation_fallback')]
        fields += [f"{p}_{label}_{suffix}" for p in ("static", "inflation")
                   for label in ("core", "full_offense") for suffix in ("delta", "unmatched")]
        context = dict(recommendation_sha256=digest, inputs_sha256=metadata['inputs_sha256'],
                       objective=metadata['config']['objective'], horizon=metadata['config']['horizon'],
                       selection=selection['method'])
        fields += list(context)
        temporary = args.output_dir / "decisions.csv.tmp"
        try:
            with temporary.open("w", newline="") as f:
                writer = csv.DictWriter(f, fields)
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: replay._cell((row | context).get(key), key) for key in fields})
            temporary.replace(args.output_dir / "decisions.csv")
        finally:
            temporary.unlink(missing_ok=True)
        print(json.dumps(dict(records=len(records), price_rows=len(rows), coverage=coverage,
                              elapsed_seconds=round(time.monotonic() - start, 2)), default=str))
        return
    records = recommend(picks, rules, players, weights, args.team,
                        lambda pick, name, count: print(f"Frozen through pick {pick}: {name}; {count} records", flush=True))
    inputs = [SOURCE / "candidate-forecast-rows.json", SOURCE / "player-ids.csv",
              ROOT / "data/local/2025/rules.json", Path(__file__)]
    metadata = dict(team=args.team, scoring="position-available core offense only", full_benchmark_complete=False,
                    objective="fixed season starters; no projected bench or bye utility; multiplied by 16/17",
                    replacement_baselines=baselines, players=len(players),
                    auction_transactions_sha256=hashlib.sha256(replay.canonical_bytes(picks)).hexdigest(),
                    source_hashes={str(p.relative_to(ROOT)): replay._file_hash(p) for p in inputs})
    recommendation_path = args.output_dir / "recommendations.json"
    save_json(recommendation_path, dict(metadata=metadata, records=records))
    frozen_hash = replay._file_hash(recommendation_path)
    evaluations, coverage = evaluate(records, players, rules, gsis)
    if replay._file_hash(recommendation_path) != frozen_hash:
        raise replay.InputError("frozen recommendations changed during evaluation")
    save_json(args.output_dir / "evaluation.json", dict(recommendation_sha256=frozen_hash,
                                                       coverage=coverage, rows=evaluations))
    print(json.dumps(dict(records=len(records), evaluated_probes=len(evaluations), coverage=coverage,
                          elapsed_seconds=round(time.monotonic() - start, 2)), default=str))


if __name__ == "__main__":
    main()
