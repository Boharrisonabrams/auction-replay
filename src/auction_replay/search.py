"""Search for the best complete, affordable roster with and without the nominee.

completion_frontier bounds the best roster for every budget. compare_nominee compares
the buy and pass branches at each legal price, and nominee_scenarios repeats that
comparison across the nine stress scenarios.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter

from .inputs import POSITIONS, InputError
from .inputs import decimal as _decimal
from .inputs import integer as _integer
from .pricing import future_prices
from .state import _covers, legal_capacity, missing_starters

DEFAULT_RELAXATION_LIMIT = 2000000


@dataclass(frozen=True)
class RosterBound:
    lower: Decimal | None
    upper: Decimal | None
    roster: tuple | None
    cost: int | None  # Future additions only; fixed ownership is already paid.
    status: str
    reason: str | None


@dataclass(frozen=True)
class BudgetFrontier:
    bounds: tuple  # Index is the budget available for future additions.
    nodes: int
    work_limit: int
    exhausted: bool
    relaxation_transitions: int = 0
    relaxation_limit: int | None = None
    relaxation_complete: bool = False
    relaxation_fallback: str | None = None

    @property
    def complete(self):
        return all(bound.status != "unresolved" for bound in self.bounds)


@dataclass(frozen=True)
class PositionalFrontier:
    entries: tuple  # Budget -> (raw millionth score, future cost, roster), or None.
    transitions: int
    transition_limit: int | None
    complete: bool
    fallback: str | None


@dataclass(frozen=True)
class PriceComparison:
    price: int
    buy: RosterBound
    passing: RosterBound
    decision: str
    reason: str


@dataclass(frozen=True)
class NomineeComparison:
    capacity: int
    reason: str | None
    buy: BudgetFrontier | None
    passing: BudgetFrontier | None
    prices: tuple

    @property
    def supported_ceiling(self):
        return max((row.price for row in self.prices if row.decision == "buy"), default=0)

    @property
    def possible_ceiling(self):
        return max(
            (row.price for row in self.prices if row.decision in {"buy", "unresolved"}), default=0
        )


@dataclass(frozen=True)
class NomineeScenario:
    name: str
    price_factor: Decimal
    forecast_factor: Decimal
    absent_weeks: tuple
    comparison: NomineeComparison


def _forecast_weights(players, rules, nominee, forecast_factor, absent_weeks):
    factor = _decimal(forecast_factor, "nominee forecast factor")
    if factor < 0:
        raise InputError("nominee forecast factor must be nonnegative")
    if nominee is not None and nominee not in players:
        raise InputError(f"unknown nominee: {nominee}")
    if (
        not rules.starters
        or any(slot not in POSITIONS | {"FLEX"} for slot in rules.starters)
        or not 1 <= rules.first_week <= rules.last_week <= 17
        or len(rules.starters) > rules.roster_size
    ):
        raise InputError("incompatible objective roster or week rules")
    weeks = tuple(
        _integer(week, "absence week", rules.first_week, rules.last_week) for week in absent_weeks
    )
    if len(set(weeks)) != len(weeks):
        raise InputError("duplicate absence week")
    if weeks and (nominee is None or players[nominee].bye in weeks):
        raise InputError("nominee absences must name non-bye weeks")
    weights = {}
    for key, player in players.items():
        if key != player.player_id or player.position not in POSITIONS:
            raise InputError(f"invalid forecast identity or position: {key}")
        _integer(player.bye, "forecast bye", 1, 18)
        weights[key] = _decimal(player.projected_points, "projected points") * (
            factor if key == nominee else 1
        )
    return weights, weeks


def _projected_lineup(roster, players, weights, rules, week, nominee, absent_weeks):
    available = sorted(
        (
            key
            for key in roster
            if players[key].bye != week
            and weights[key] > 0
            and not (key == nominee and week in absent_weeks)
        ),
        key=lambda key: (-weights[key], key),
    )
    lineup = [None] * len(rules.starters)
    used = set()
    # Fixed positions are disjoint. Take their best players before assigning FLEX.
    for index in sorted(range(len(rules.starters)), key=lambda i: rules.starters[i] == "FLEX"):
        slot = rules.starters[index]
        key = next(
            (
                key
                for key in available
                if key not in used
                and (
                    players[key].position in {"RB", "WR", "TE"}
                    if slot == "FLEX"
                    else players[key].position == slot
                )
            ),
            None,
        )
        lineup[index] = key
        if key is not None:
            used.add(key)
    return tuple(lineup)


def projected_lineup(
    roster, players, rules, week, nominee=None, forecast_factor=Decimal(1), absent_weeks=()
):
    """Return IDs aligned with starter slots, using only forecasts and known byes.

    Empty slots score zero; a manager may bench a nonpositive forecast. Equal
    forecasts use stable player IDs. A player never occupies two starter slots.
    """
    if len(set(roster)) != len(roster) or set(roster) - players.keys():
        raise InputError("duplicate or unknown roster player")
    week = _integer(week, "lineup week", rules.first_week, rules.last_week)
    weights, weeks = _forecast_weights(players, rules, nominee, forecast_factor, absent_weeks)
    return _projected_lineup(roster, players, weights, rules, week, nominee, weeks)


def _projected_total(roster, players, weights, rules, nominee, absent_weeks):
    # Sum the season-projection numerators before dividing, avoiding 17 repeated
    # divisions. Each scheduled game contributes projection / 17; a bye is zero.
    return (
        sum(
            (
                weights[key]
                for week in range(rules.first_week, rules.last_week + 1)
                for key in _projected_lineup(
                    roster, players, weights, rules, week, nominee, absent_weeks
                )
                if key is not None
            ),
            Decimal(0),
        )
        / 17
    )


def projected_total(
    roster, players, rules, nominee=None, forecast_factor=Decimal(1), absent_weeks=()
):
    if len(set(roster)) != len(roster) or set(roster) - players.keys():
        raise InputError("duplicate or unknown roster player")
    weights, weeks = _forecast_weights(players, rules, nominee, forecast_factor, absent_weeks)
    return _projected_total(roster, players, weights, rules, nominee, weeks)


def _prune_positional(table):
    """For equal roster counts, more cost with no score gain is dominated."""
    best: dict[int, int]
    result, best = {}, {}
    for (count, cost), value in sorted(table.items()):
        if value[0] > best.get(count, -1):
            result[count, cost] = value
            best[count] = value[0]
    return result


def positional_frontier(
    fixed,
    candidates,
    prices,
    players,
    rules,
    max_budget,
    nominee=None,
    forecast_factor=Decimal(1),
    bench_credit=Decimal(0),
    transition_limit=None,
):
    """Return raw millionth scores for the complete-roster no-bye objective.

    With zero bench credit, a completed frontier supplies the maximum possible
    starter numerator at each budget. Partial results are feasible seeds only,
    never upper bounds or infeasibility proofs. Each examined player inclusion
    and positional-table combination counts as one transition, including those
    rejected by cost or count. None leaves the historical pilot uncapped.
    """
    if len(set(fixed)) != len(fixed) or len(set(candidates)) != len(candidates):
        raise InputError("duplicate completion identity")
    fixed, candidates = set(fixed), set(candidates)
    if (
        fixed & candidates
        or (fixed | candidates) - players.keys()
        or len(fixed) > rules.roster_size
    ):
        raise InputError("invalid completion identities")
    max_budget = _integer(max_budget, "budget")
    if set(candidates) - prices.keys():
        raise InputError("missing future prices")
    costs = {k: _integer(prices[k], "future price", 1) for k in candidates}
    costs.update({k: 0 for k in fixed})
    weights, _ = _forecast_weights(players, rules, nominee, forecast_factor, ())
    if bench_credit not in (Decimal(0), Decimal(".125"), Decimal(".25")):
        raise InputError("unsupported bench-credit sensitivity")
    transition_limit = (
        None
        if transition_limit is None
        else _integer(transition_limit, "relaxation transition limit")
    )
    fallback = None
    # Preserve the pilot's integer-millionth and backup-credit arithmetic.
    if any((v * 1000000) != (v * 1000000).to_integral_value() for v in weights.values()):
        fallback = "pilot requires at most six decimal places"
    points = {k: max(0, int(v * 1000000)) for k, v in weights.items()}
    quotas = Counter(slot for slot in rules.starters if slot != "FLEX")
    if rules.starters.count("FLEX") > 1:
        fallback = "pilot supports at most one FLEX"
    if fallback:
        return PositionalFrontier((None,) * (max_budget + 1), 0, transition_limit, False, fallback)
    # An absent FLEX category must still enforce its quota through an empty table.
    positions = sorted(
        {p.position for p in players.values()}
        | set(quotas)
        | ({"RB", "WR", "TE"} if "FLEX" in rules.starters else set())
    )
    best: list[tuple[int, int, tuple[str, ...]] | None] = [None] * (max_budget + 1)
    tables = {}
    flexes = ("RB", "WR", "TE") if "FLEX" in rules.starters else (None,)
    transitions = 0

    class Cutoff(Exception):
        pass

    def transition():
        nonlocal transitions
        if transition_limit is not None and transitions >= transition_limit:
            raise Cutoff
        transitions += 1

    try:
        for flex in flexes:
            required = dict(quotas)
            if flex:
                required[flex] = required.get(flex, 0) + 1
            total: dict[tuple[int, int], tuple[int, tuple[str, ...]]] = {(0, 0): (0, ())}
            for pos in positions:
                quota = required.get(pos, 0)
                if (pos, quota) not in tables:
                    group = sorted(
                        (k for k in fixed | candidates if players[k].position == pos),
                        key=lambda k: (-points[k], k),
                    )
                    # Use base quotas so cached tables remain valid across FLEX assignments.
                    limit = rules.roster_size - sum(
                        max(quotas.get(other, 0), sum(players[k].position == other for k in fixed))
                        for other in positions
                        if other != pos
                    )
                    table: dict[tuple[int, int], tuple[int, tuple[str, ...]]] = {(0, 0): (0, ())}
                    for k in group:
                        next_table = {} if k in fixed else table.copy()
                        for (count, cost), (score, roster) in table.items():
                            transition()
                            new = (count + 1, cost + costs[k])
                            if new[0] > limit or new[1] > max_budget:
                                continue
                            backup = (
                                int(points[k] * bench_credit)
                                if count == quota and pos in {"QB", "RB", "WR", "TE"}
                                else 0
                            )
                            value = (
                                score + (points[k] if count < quota else backup),
                                roster + (k,),
                            )
                            old = next_table.get(new)
                            if (
                                old is None
                                or value[0] > old[0]
                                or (value[0] == old[0] and value[1] < old[1])
                            ):
                                next_table[new] = value
                        table = next_table
                    tables[pos, quota] = _prune_positional(
                        {key: value for key, value in table.items() if key[0] >= quota}
                    )
                next_total: dict[tuple[int, int], tuple[int, tuple[str, ...]]] = {}
                for (n1, c1), (s1, r1) in total.items():
                    for (n2, c2), (s2, r2) in tables[pos, quota].items():
                        transition()
                        key = n1 + n2, c1 + c2
                        if key[0] > rules.roster_size or key[1] > max_budget:
                            continue
                        value = s1 + s2, r1 + r2
                        old = next_total.get(key)
                        if (
                            old is None
                            or value[0] > old[0]
                            or (value[0] == old[0] and value[1] < old[1])
                        ):
                            next_total[key] = value
                total = _prune_positional(next_total)
            for (count, cost), (score, roster) in total.items():
                if count != rules.roster_size:
                    continue
                value = (score, cost, tuple(sorted(roster)))
                old = best[cost]
                if old is None or (-value[0], value[1:]) < (-old[0], old[1:]):
                    best[cost] = value
    except Cutoff:
        fallback = "relaxation transition limit reached; partial frontier is not an upper bound"
    for budget in range(1, max_budget + 1):
        old, new = best[budget - 1], best[budget]
        if old is not None and (new is None or (-old[0], old[1:]) < (-new[0], new[1:])):
            best[budget] = old
    return PositionalFrontier(
        tuple(best), transitions, transition_limit, fallback is None, fallback
    )


def completion_frontier(
    fixed,
    candidates,
    prices,
    players,
    rules,
    max_budget,
    work_limit=2000,
    nominee=None,
    forecast_factor=Decimal(1),
    absent_weeks=(),
    relaxation_limit=DEFAULT_RELAXATION_LIMIT,
    timings=None,
):
    """Bound complete-roster production at every integer completion budget.

    Search nodes and positional-relaxation transitions have separate limits.
    A completed no-bye relaxation seeds weekly incumbents and bounds each budget;
    partial or unsupported relaxation inputs retain the generic search bound.
    Pending nodes retain both bounds and never become infeasible just at cutoff.
    Optional timings are separate diagnostics, excluded from proof equality.
    """
    started = perf_counter() if timings is not None else None
    max_budget = _integer(max_budget, "completion budget")
    work_limit = _integer(work_limit, "search work limit", 1)
    relaxation_limit = _integer(relaxation_limit, "relaxation transition limit")
    fixed, candidates = tuple(fixed), tuple(candidates)
    if (
        len(set(fixed)) != len(fixed)
        or len(set(candidates)) != len(candidates)
        or set(fixed) & set(candidates)
        or (set(fixed) | set(candidates)) - players.keys()
    ):
        raise InputError("duplicate, overlapping, or unknown completion players")
    if len(fixed) > rules.roster_size:
        raise InputError("fixed roster exceeds roster size")
    if set(candidates) - prices.keys():
        raise InputError(f"missing future prices: {sorted(set(candidates) - prices.keys())}")
    costs = {key: _integer(prices[key], f"future price for {key}", 1) for key in candidates}
    weights, weeks = _forecast_weights(players, rules, nominee, forecast_factor, absent_weeks)
    candidates = tuple(sorted(candidates, key=lambda key: (-weights[key], key)))
    lower: list[Decimal | None]
    rosters: list[tuple[str, ...] | None]
    spending: list[int | None]
    lower, rosters, spending = (
        [None] * (max_budget + 1),
        [None] * (max_budget + 1),
        [None] * (max_budget + 1),
    )

    def record(roster, cost):
        score = _projected_total(roster, players, weights, rules, nominee, weeks)
        frozen = tuple(sorted(roster))
        for budget in range(cost, max_budget + 1):
            if (
                lower[budget] is None
                or score > lower[budget]
                or (score == lower[budget] and (cost, frozen) < (spending[budget], rosters[budget]))
            ):
                lower[budget], rosters[budget], spending[budget] = score, frozen, cost

    # Both branches first construct a cheap feasible incumbent. This does not
    # assert optimality; the same capped node search supplies the upper bounds.
    needs = missing_starters(fixed, players, rules)
    cheapest = sorted(candidates, key=lambda key: (costs[key], key))
    seed = list(fixed)
    for slot in sorted(needs, key=lambda slot: slot == "FLEX"):
        key = next(
            (
                key
                for key in cheapest
                if key not in seed
                and (
                    players[key].position in {"RB", "WR", "TE"}
                    if slot == "FLEX"
                    else players[key].position == slot
                )
            ),
            None,
        )
        if key is not None:
            seed.append(key)
    for key in cheapest:
        if len(seed) >= rules.roster_size:
            break
        if key not in seed:
            seed.append(key)
    if len(seed) == rules.roster_size and not missing_starters(seed, players, rules):
        record(tuple(seed), sum(costs[key] for key in seed if key not in fixed))

    initial_upper = _projected_total(fixed + candidates, players, weights, rules, nominee, weeks)
    relaxation_players = {key: players[key] for key in fixed + candidates}
    relaxation = positional_frontier(
        fixed,
        candidates,
        costs,
        relaxation_players,
        rules,
        max_budget,
        nominee if nominee in relaxation_players else None,
        forecast_factor,
        transition_limit=relaxation_limit,
    )
    root_upper = [initial_upper] * (max_budget + 1)
    seen_seeds = set()
    for budget, entry in enumerate(relaxation.entries):
        if entry is not None:
            raw, cost, roster = entry
            if roster not in seen_seeds:
                record(roster, cost)
                seen_seeds.add(roster)
            if relaxation.complete:
                # Every weekly lineup is bounded by the same roster's best
                # no-bye lineup. Do not use the pilot's rounded 16/17 score.
                maximum = Decimal(raw) / 1000000
                root_upper[budget] = min(
                    initial_upper, (rules.last_week - rules.first_week + 1) * maximum / 17
                )
        elif relaxation.complete:
            root_upper[budget] = None  # Only a completed relaxation can prove this.
    search_started = perf_counter() if timings is not None else None
    stack = [(0, fixed, 0, 0, initial_upper)]
    nodes = 0
    # ponytail: exponential subset search with a bounded positional relaxation;
    # add tighter per-node bounds only if measured unresolved rates require them.
    while stack and nodes < work_limit:
        index, roster, cost, _, inherited_upper = stack.pop()
        nodes += 1
        slots = rules.roster_size - len(roster)
        remaining = candidates[index:]
        needs = missing_starters(roster, players, rules)
        if (
            len(remaining) < slots
            or len(needs) > slots
            or not _covers((players[key].position for key in remaining), needs)
        ):
            continue
        minimum = cost + sum(sorted(costs[key] for key in remaining)[:slots])
        if minimum > max_budget:
            continue
        # Owning every remaining player relaxes both cost and roster-size limits.
        upper = min(
            inherited_upper,
            _projected_total(roster + remaining, players, weights, rules, nominee, weeks),
        )
        if all(
            root_upper[budget] is None
            or (lower[budget] is not None and lower[budget] >= min(upper, root_upper[budget]))
            for budget in range(minimum, max_budget + 1)
        ):
            continue
        if not slots:
            record(roster, cost)
            continue
        key = candidates[index]
        # LIFO visits the higher-forecast inclusion first; stable IDs break ties.
        stack.append((index + 1, roster, cost, minimum, upper))
        added_cost = cost + costs[key]
        stack.append(
            (index + 1, roster + (key,), added_cost, max(minimum, added_cost + slots - 1), upper)
        )
    upper = lower.copy()
    for _, _, _, minimum, pending_upper in stack:
        for budget in range(minimum, max_budget + 1):
            if root_upper[budget] is not None:
                bound = min(pending_upper, root_upper[budget])
                upper[budget] = bound if upper[budget] is None else max(upper[budget], bound)
    bounds = []
    for budget, (lo, hi) in enumerate(zip(lower, upper)):
        status = "infeasible" if hi is None else "optimal" if lo == hi else "unresolved"
        reason = (
            "no feasible complete roster"
            if status == "infeasible"
            else "search work limit; no feasible incumbent"
            if lo is None
            else "search work limit; bounds overlap"
            if status == "unresolved"
            else None
        )
        bounds.append(RosterBound(lo, hi, rosters[budget], spending[budget], status, reason))
    if timings is not None:
        finished = perf_counter()
        timings.update(
            # started and search_started are floats whenever timings is not None.
            preprocessing_seconds=search_started - started,  # type: ignore[operator]
            search_seconds=finished - search_started,  # type: ignore[operator]
            total_seconds=finished - started,  # type: ignore[operator]
        )
    return BudgetFrontier(
        tuple(bounds),
        nodes,
        work_limit,
        bool(stack),
        relaxation.transitions,
        relaxation_limit,
        relaxation.complete,
        relaxation.fallback,
    )


def compare_nominee(
    nomination,
    team_name,
    players,
    prices,
    rules,
    work_limit=2000,
    forecast_factor=Decimal(1),
    absent_weeks=(),
    relaxation_limit=DEFAULT_RELAXATION_LIMIT,
):
    """Solve each branch once, then compare all legal purchase prices."""
    state, nominee = nomination.state, nomination.player_id
    if nominee not in players or state.owned - players.keys():
        raise InputError("unknown nominee or owned forecast player")
    team = state.team(team_name)
    available = set(players) - state.owned
    capacity, reason = legal_capacity(team, nominee, players, available, rules)
    if reason:
        return NomineeComparison(capacity, reason, None, None, ())
    candidates = available - {nominee}
    arguments = dict(
        prices=prices,
        players=players,
        rules=rules,
        max_budget=team.budget,
        work_limit=work_limit,
        nominee=nominee,
        forecast_factor=forecast_factor,
        absent_weeks=absent_weeks,
        relaxation_limit=relaxation_limit,
    )
    buy = completion_frontier(team.roster + (nominee,), candidates, **arguments)
    passing = completion_frontier(team.roster, candidates, **arguments)
    return _compare_frontiers(capacity, team.budget, buy, passing)


def _compare_frontiers(capacity, budget, buy, passing):
    rows = []
    for price in range(1, capacity + 1):
        bought, passed = buy.bounds[budget - price], passing.bounds[budget]
        if bought.upper is None:
            decision, why = (
                ("infeasible", "neither branch can complete the roster")
                if passed.upper is None
                else ("pass", "buy branch cannot complete the roster")
                if passed.lower is not None
                else ("unresolved", "buy completion infeasible; pass feasibility unresolved")
            )
        elif bought.lower is not None and (passed.upper is None or bought.lower > passed.upper):
            decision, why = "buy", "buy lower bound exceeds pass upper bound"
        elif passed.lower is not None and bought.upper <= passed.lower:
            decision, why = (
                "pass",
                "buy upper bound does not exceed pass lower bound; equality passes",
            )
        else:
            decision, why = (
                "unresolved",
                "search work limit; comparison bounds overlap or lack a feasible incumbent",
            )
        rows.append(PriceComparison(price, bought, passed, decision, why))
    return NomineeComparison(capacity, None, buy, passing, tuple(rows))


def nominee_scenarios(
    moment, team_name, players, rules, work_limit=2000, relaxation_limit=DEFAULT_RELAXATION_LIMIT
):
    """Cross three performance cases with 0.8/1.0/1.2 future-price stresses.

    The absence protocol predeclares the first two non-bye evaluation weeks.
    These cases are sensitivity assumptions, without injury probabilities.
    """
    nominee = moment.nomination.player_id
    if nominee not in players:
        raise InputError(f"unknown nominee: {nominee}")
    weeks = tuple(
        week
        for week in range(rules.first_week, rules.last_week + 1)
        if week != players[nominee].bye
    )[:2]
    if len(weeks) != 2:
        raise InputError("two non-bye sensitivity weeks are unavailable")
    cases = (
        ("neutral", Decimal(1), ()),
        ("forecast_minus_20_percent", Decimal("0.8"), ()),
        ("two_non_bye_absences", Decimal(1), weeks),
    )
    result = []
    for price_factor in (Decimal("0.8"), Decimal(1), Decimal("1.2")):
        prices = future_prices(dict(moment.inflation), moment.prior_ratios, price_factor)
        neutral = compare_nominee(
            moment.nomination,
            team_name,
            players,
            prices,
            rules,
            work_limit,
            relaxation_limit=relaxation_limit,
        )
        for name, factor, absences in cases:
            comparison = neutral
            if name != "neutral" and neutral.reason is None:
                team = moment.nomination.state.team(team_name)
                candidates = set(players) - moment.nomination.state.owned - {nominee}
                buy = completion_frontier(
                    team.roster + (nominee,),
                    candidates,
                    prices,
                    players,
                    rules,
                    team.budget,
                    work_limit,
                    nominee,
                    factor,
                    absences,
                    relaxation_limit,
                )
                # Passing excludes the nominee; only the price factor changes its frontier.
                comparison = _compare_frontiers(neutral.capacity, team.budget, buy, neutral.passing)
            result.append(NomineeScenario(name, price_factor, factor, absences, comparison))
    return tuple(result)
