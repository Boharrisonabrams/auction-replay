"""Turn each team and nomination into one decision row per legal price and scenario.

decision_rows yields the rows that run_benchmark freezes and hashes. evaluate_roster
scores a frozen roster against weekly outcomes after that freeze.
"""

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal

from .inputs import InputError
from .inputs import integer as _integer
from .pricing import _validate_auction_forecasts, baseline_ceiling, rebase_reference, replay_markets
from .search import _forecast_weights, _projected_lineup, nominee_scenarios
from .state import MarketMoment, initial_state, missing_starters, replay_states

# Outcome columns are appended only after the recommendation spool is frozen.
EVALUATION_FIELDS = ("buy_evaluation", "pass_evaluation")


DECISION_FIELDS = tuple(
    "pick player_id player_name team budget held_roster room_state state_sha256 price scenario "
    "price_factor forecast_factor absent_weeks capacity source_reference static_estimate inflation_estimate "
    "static_ceiling inflation_ceiling static_action inflation_action roster_action static_reason inflation_reason reason "
    "neutral_supported_ceiling neutral_possible_ceiling scenario_supported_min scenario_supported_max "
    "scenario_possible_min scenario_possible_max scenario_disagreement price_disagreement "
    "scenario_supported_ceiling scenario_possible_ceiling prior_ratios warnings work_limit "
    "buy_lower buy_upper buy_roster buy_future_cost buy_total_cost buy_status buy_reason buy_nodes buy_exhausted "
    "pass_lower pass_upper pass_roster pass_future_cost pass_total_cost pass_status pass_reason pass_nodes pass_exhausted "
    "buy_relaxation_transitions buy_relaxation_limit buy_relaxation_complete buy_relaxation_fallback "
    "pass_relaxation_transitions pass_relaxation_limit pass_relaxation_complete pass_relaxation_fallback".split()
)


def canonical_bytes(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=lambda item: str(item) if isinstance(item, Decimal) else asdict(item),
    ).encode()


def policy_action(price, ceiling, bought, passed):
    """Keep price-policy intent separate from a witnessed executable completion."""
    chosen = bought if price <= ceiling else passed
    action = "supported" if price <= ceiling else "pass"
    if chosen.roster is not None:
        return (
            action,
            "price within ceiling; feasible buy incumbent"
            if action == "supported"
            else "price exceeds ceiling; feasible pass incumbent",
        )
    if chosen.upper is not None:
        return "search-unresolved", "chosen branch has no feasible incumbent within search limit"
    if action == "supported" and passed.roster is not None:
        return "pass", "buy completion infeasible; feasible pass incumbent"
    if action == "supported" and passed.upper is not None:
        return "search-unresolved", "buy completion infeasible; pass feasibility unresolved"
    return "infeasible", "price policy has no executable completion"


def _structural_rejection(team, nominee, positions, rules):
    """Prove rejection from observed holdings, without inventing a future pool."""
    slots = rules.roster_size - len(team.roster)
    if slots <= 0:
        return "full roster"
    if team.budget < slots:
        return "insufficient reserve"
    if len(missing_starters(team.roster + (nominee,), positions, rules)) > slots - 1:
        return "insufficient starter slots after purchase"
    return None


def decision_rows(picks, rules, players=None, references=None, gaps=(), work_limit=2000):
    """Yield all team/nomination prices; retain at most one pair's nine frontiers."""
    work_limit = _integer(work_limit, "search work limit", 1)
    positions = {pick.player_id: pick for pick in picks}
    if players is None or references is None:
        moments = (
            MarketMoment(nomination, (), (), (), ()) for nomination in replay_states(picks, rules)
        )
    else:
        # Initial pool validation can fail before the generator yields any state.
        try:
            _validate_auction_forecasts(picks, players)
            rebase_reference(initial_state(picks, rules), players, references, rules)
        except InputError as error:
            gaps = tuple(gaps) + (str(error),)
            players = references = None
            moments = (
                MarketMoment(nomination, (), (), (), ())
                for nomination in replay_states(picks, rules)
            )
        else:
            moments = replay_markets(picks, players, references, rules)
    for moment in moments:
        nomination = moment.nomination
        state = nomination.state
        room = dict(
            teams=[asdict(team) for team in state.teams], completed_sale_count=len(state.sales)
        )
        state_hash = hashlib.sha256(canonical_bytes(asdict(state))).hexdigest()
        nominee = nomination.player_id
        if players is not None and references is not None:
            static = dict(moment.static)
            inflation = dict(moment.inflation)
            available = set(players) - state.owned
        for team in state.teams:
            base = dict(
                pick=nomination.pick,
                player_id=nominee,
                player_name=positions[nominee].name,
                team=team.name,
                budget=team.budget,
                held_roster=team.roster,
                room_state=room,
                state_sha256=state_hash,
                work_limit=work_limit,
                prior_ratios=moment.prior_ratios,
                warnings=moment.warnings,
            )
            reason = _structural_rejection(team, nominee, positions, rules)
            action = "infeasible" if reason else "missing-data"
            scenarios = None
            if reason is None and players is not None and references is not None:
                try:
                    static_ceiling, reason = baseline_ceiling(
                        static, team, nominee, players, available, rules
                    )
                    inflation_ceiling, reason2 = baseline_ceiling(
                        inflation, team, nominee, players, available, rules
                    )
                    reason = reason or reason2
                    if reason:
                        action = "infeasible"
                    else:
                        scenarios = nominee_scenarios(moment, team.name, players, rules, work_limit)
                        base.update(
                            source_reference=references[nominee],
                            static_estimate=static[nominee],
                            inflation_estimate=inflation[nominee],
                            static_ceiling=static_ceiling,
                            inflation_ceiling=inflation_ceiling,
                        )
                except InputError as error:
                    reason, action = str(error), "missing-data"
            if scenarios is None:
                reason = (
                    reason
                    or "; ".join(gaps)
                    or "accepted forecast and reference inputs unavailable"
                )
                yield dict(
                    base,
                    price=None,
                    reason=reason,
                    roster_action=action,
                    static_action=action,
                    inflation_action=action,
                )
                continue
            neutral = next(
                case for case in scenarios if case.name == "neutral" and case.price_factor == 1
            )
            supported = [case.comparison.supported_ceiling for case in scenarios]
            possible = [case.comparison.possible_ceiling for case in scenarios]
            price_disagreements = [
                len({case.comparison.prices[i].decision for case in scenarios}) > 1
                for i in range(neutral.comparison.capacity)
            ]
            base.update(
                capacity=neutral.comparison.capacity,
                neutral_supported_ceiling=neutral.comparison.supported_ceiling,
                neutral_possible_ceiling=neutral.comparison.possible_ceiling,
                scenario_supported_min=min(supported),
                scenario_supported_max=max(supported),
                scenario_possible_min=min(possible),
                scenario_possible_max=max(possible),
                scenario_disagreement=any(price_disagreements),
            )
            for scenario in scenarios:
                comparison = scenario.comparison
                for index, price in enumerate(comparison.prices):
                    static_action, static_reason = policy_action(
                        price.price, static_ceiling, price.buy, price.passing
                    )
                    inflation_action, inflation_reason = policy_action(
                        price.price, inflation_ceiling, price.buy, price.passing
                    )
                    row = dict(
                        base,
                        price=price.price,
                        scenario=scenario.name,
                        price_factor=scenario.price_factor,
                        forecast_factor=scenario.forecast_factor,
                        absent_weeks=scenario.absent_weeks,
                        scenario_supported_ceiling=comparison.supported_ceiling,
                        scenario_possible_ceiling=comparison.possible_ceiling,
                        price_disagreement=price_disagreements[index],
                        static_action=static_action,
                        static_reason=static_reason,
                        inflation_action=inflation_action,
                        inflation_reason=inflation_reason,
                        roster_action={"buy": "supported", "unresolved": "search-unresolved"}.get(
                            price.decision, price.decision
                        ),
                        reason=price.reason,
                    )
                    for branch, bound, frontier in (
                        ("buy", price.buy, comparison.buy),
                        ("pass", price.passing, comparison.passing),
                    ):
                        row.update(
                            {
                                branch + "_" + key: value
                                for key, value in asdict(bound).items()
                                if key != "cost"
                            }
                        )
                        row[branch + "_future_cost"] = bound.cost
                        row[branch + "_total_cost"] = (
                            None
                            if bound.cost is None
                            else bound.cost + (price.price if branch == "buy" else 0)
                        )
                        row[branch + "_nodes"] = frontier.nodes
                        row[branch + "_exhausted"] = frontier.exhausted
                        for field in (
                            "relaxation_transitions",
                            "relaxation_limit",
                            "relaxation_complete",
                            "relaxation_fallback",
                        ):
                            row[branch + "_" + field] = getattr(frontier, field)
                    yield row


def evaluate_roster(roster, players, rules, outcomes):
    """Evaluate a frozen roster with base preseason ordering and known byes.

    The optimistic score is unknown if any active eligible player lacks actuals;
    their potential contribution cannot be bounded by treating them as zero.
    Vacant positions stay vacant. No injuries, waiver pickups, or forecast stress
    assumptions alter the preselected lineup ordering during evaluation.
    """
    roster = tuple(roster)
    weights, _ = _forecast_weights(players, rules, None, Decimal(1), ())
    if len(roster) != len(set(roster)) or set(roster) - players.keys():
        raise InputError("duplicate or unknown evaluation roster player")
    fixed_total, hindsight_total = Decimal(0), Decimal(0)
    missing_selected, missing_hindsight, weeks = [], [], []
    for week in range(rules.first_week, rules.last_week + 1):
        lineup = _projected_lineup(roster, players, weights, rules, week, None, ())
        missing = [
            (key, week) for key in lineup if key is not None and outcomes.get((key, week)) is None
        ]
        missing_selected.extend(missing)
        fixed = (
            None
            if missing
            else sum((outcomes[(key, week)] for key in lineup if key is not None), Decimal(0))
        )
        if fixed is not None:
            fixed_total += fixed
        eligible = [
            key
            for key in roster
            if players[key].bye != week
            and any(
                players[key].position in {"RB", "WR", "TE"}
                if slot == "FLEX"
                else players[key].position == slot
                for slot in rules.starters
            )
        ]
        unknown = [(key, week) for key in eligible if outcomes.get((key, week)) is None]
        missing_hindsight.extend(unknown)
        hindsight_lineup, hindsight = None, None
        if not unknown:
            actual = {
                key: outcomes.get((key, week)) if key in eligible else Decimal(0) for key in roster
            }
            hindsight_lineup = _projected_lineup(roster, players, actual, rules, week, None, ())
            hindsight = sum(
                (actual[key] for key in hindsight_lineup if key is not None), Decimal(0)
            )
            hindsight_total += hindsight
        weeks.append(
            dict(
                week=week,
                fixed_preseason_lineup=lineup,
                fixed_preseason_points=fixed,
                optimistic_hindsight_lineup=hindsight_lineup,
                optimistic_hindsight_points=hindsight,
            )
        )
    return dict(
        fixed_preseason_total=None if missing_selected else fixed_total,
        optimistic_hindsight_total=None if missing_hindsight else hindsight_total,
        missing_selected=tuple(missing_selected),
        missing_hindsight=tuple(missing_hindsight),
        missing_starters=missing_starters(roster, players, rules),
        weeks=tuple(weeks),
    )
