"""Price the players still available at each nomination, from earlier sales only.

Reference values are rebased to the league's budget and roster pool, then rescaled to the
cash that is left. replay_markets freezes these estimates before each closing price.
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from statistics import median

from .inputs import InputError
from .inputs import decimal as _decimal
from .state import (
    MarketMoment,
    _covers,
    initial_state,
    legal_capacity,
    missing_starters,
    replay_states,
)


def reference_pool(state, players, values, rules, include_owned=False):
    """Select the highest-valued remaining pool with distinct starter coverage.

    Known keepers count toward each team's fixed slots before residual FLEX
    needs. Already-full historical rosters need no further pool allocation;
    callers still report any unfilled starters on those rosters separately. If
    an observed team has too few slots to complete starters, its remaining slots
    count as unrestricted demand. Its infeasibility must not erase other teams'
    decision coverage; both baselines attach an explicit warning for this case.
    """
    missing = set(players) - values.keys()
    if missing or state.owned - players.keys():
        raise InputError(
            f"reference universe coverage missing: {sorted(missing | (state.owned - players.keys()))}"
        )
    needs = []
    slots = 0
    for team in state.teams:
        open_slots = rules.roster_size - len(team.roster)
        required = missing_starters(team.roster, players, rules)
        if open_slots and len(required) <= open_slots:
            needs.extend(required)
        slots += open_slots
    candidates = sorted(set(players) - state.owned, key=lambda key: (-values[key], key))
    if len(candidates) < slots or not _covers((players[key].position for key in candidates), needs):
        raise InputError("reference pool has insufficient roster or starter coverage")
    selected = set()
    # Position quotas are disjoint; only FLEX can share a position category.
    for slot in [slot for slot in needs if slot != "FLEX"] + ["FLEX"] * needs.count("FLEX"):
        selected.add(
            next(
                key
                for key in candidates
                if key not in selected
                and (
                    players[key].position in {"RB", "WR", "TE"}
                    if slot == "FLEX"
                    else players[key].position == slot
                )
            )
        )
    for key in candidates:
        if len(selected) >= slots:
            break
        selected.add(key)
    if include_owned:
        selected.update(state.owned)
    return tuple(sorted(selected))


def _rescale(values, available, pool, discretionary):
    excess = {key: max(Decimal(0), values[key] - 1) for key in available}
    denominator = sum((excess[key] for key in pool), Decimal(0))
    if denominator == 0:
        return {key: Decimal(1) for key in sorted(available)}, (
            "zero discretionary denominator; $1-only estimate",
        )
    scale = Decimal(max(0, discretionary)) / denominator
    return {key: Decimal(1) + excess[key] * scale for key in sorted(available)}, ()


def _pool_warnings(state, players, rules):
    return tuple(
        f"{team.name}: historical starter coverage impossible; remaining market slots unrestricted"
        for team in state.teams
        if len(missing_starters(team.roster, players, rules)) > rules.roster_size - len(team.roster)
    )


def rebase_reference(state, players, source_values, rules):
    pool = reference_pool(state, players, source_values, rules, include_owned=True)
    estimates, warnings = _rescale(
        source_values, set(players), pool, rules.teams * (rules.budget - rules.roster_size)
    )
    return estimates, warnings + _pool_warnings(state, players, rules)


def inflation_prices(state, players, static_values, rules):
    """Rescale spendable cash: full-roster teams cannot contribute further bids."""
    pool = reference_pool(state, players, static_values, rules)
    slots = sum(rules.roster_size - len(team.roster) for team in state.teams)
    discretionary = (
        sum(team.budget for team in state.teams if len(team.roster) < rules.roster_size) - slots
    )
    if discretionary < 0:
        raise InputError("league cannot reserve $1 per remaining roster place")
    estimates, warnings = _rescale(static_values, set(players) - state.owned, pool, discretionary)
    return estimates, warnings + _pool_warnings(state, players, rules)


def baseline_ceiling(values, team, nominee, players, available, rules):
    capacity, reason = legal_capacity(team, nominee, players, available, rules)
    if reason:
        return 0, reason
    if nominee not in values:
        raise InputError(f"missing baseline estimate: {nominee}")
    return min(capacity, max(1, int(values[nominee].to_integral_value(rounding=ROUND_FLOOR)))), None


def market_adjustment(prior_ratios):
    if any(ratio is None for ratio in prior_ratios):
        raise InputError("prior market estimate unavailable; pooled adjustment unresolved")
    count = len(prior_ratios)
    return (
        Decimal(1)
        if not count
        else Decimal(1) + Decimal(count) / (count + 20) * (median(prior_ratios) - 1)
    )


def future_prices(inflation, prior_ratios, multiplier=Decimal(1)):
    multiplier = _decimal(multiplier, "future-price multiplier")
    if multiplier <= 0:
        raise InputError("future-price multiplier must be positive")
    adjustment = market_adjustment(prior_ratios)
    return {
        key: max(
            1, int((value * adjustment * multiplier).to_integral_value(rounding=ROUND_CEILING))
        )
        for key, value in sorted(inflation.items())
    }


def _validate_auction_forecasts(picks, players):
    missing = {pick.player_id for pick in picks} - players.keys()
    if missing:
        raise InputError(f"missing auction players from forecast universe: {sorted(missing)}")
    for pick in picks:
        if pick.position != players[pick.player_id].position:
            raise InputError(f"auction/forecast position mismatch: {pick.player_id}")


def replay_markets(picks, players, source_values, rules):
    """Freeze uncapped market predictions before revealing each closing price.

    Empty inflation estimates and named warnings preserve a failed pool as a
    visible gap. A missing previous prediction also blocks the pooled forecast;
    no sale is silently dropped from its history.
    """
    _validate_auction_forecasts(picks, players)
    static, static_warnings = rebase_reference(
        initial_state(picks, rules), players, source_values, rules
    )
    prior_ratios = ()
    previous_prediction = None
    for nomination in replay_states(picks, rules):
        if nomination.state.sales:
            actual = nomination.state.sales[-1].salary
            prior_ratios += (
                None if previous_prediction is None else Decimal(actual) / previous_prediction,
            )
        warnings = static_warnings
        try:
            inflation, pool_warnings = inflation_prices(nomination.state, players, static, rules)
            warnings += pool_warnings
        except InputError as error:
            inflation = {}
            warnings += (str(error),)
        previous_prediction = None
        if inflation:
            try:
                previous_prediction = future_prices(inflation, prior_ratios)[nomination.player_id]
            except InputError as error:
                warnings += (str(error),)
        yield MarketMoment(
            nomination,
            tuple(sorted(static.items())),
            tuple(sorted(inflation.items())),
            prior_ratios,
            warnings,
        )
