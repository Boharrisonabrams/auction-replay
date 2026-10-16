"""Replay the observed auction: team budgets and rosters before each nomination.

Keepers are charged first, then each sale is applied in order. A nomination sees only the
sales before it. legal_capacity gives the highest bid a team can legally make.
"""

from collections import Counter
from dataclasses import dataclass

from .inputs import InputError


@dataclass(frozen=True)
class TeamState:
    name: str
    roster: tuple
    budget: int


@dataclass(frozen=True)
class AuctionState:
    teams: tuple
    sales: tuple = ()

    @property
    def owned(self):
        return frozenset(player_id for team in self.teams for player_id in team.roster)

    def team(self, name):
        return next(team for team in self.teams if team.name == name)


@dataclass(frozen=True)
class Nomination:
    pick: int
    player_id: str
    state: AuctionState


@dataclass(frozen=True)
class MarketMoment:
    nomination: Nomination
    static: tuple
    inflation: tuple
    prior_ratios: tuple
    warnings: tuple


def apply_sale(state, sale, rules):
    """Record an observed purchase without repairing historical position errors."""
    team = state.team(sale.team)
    if sale.player_id in state.owned:
        raise InputError(f"player already owned: {sale.player_id}")
    if len(team.roster) >= rules.roster_size or sale.salary > team.budget:
        raise InputError(f"observed purchase exceeds roster or budget: {sale.pick}")
    updated = TeamState(team.name, team.roster + (sale.player_id,), team.budget - sale.salary)
    return AuctionState(
        tuple(updated if t.name == team.name else t for t in state.teams),
        state.sales if sale.keeper else state.sales + (sale,),
    )


def initial_state(picks, rules):
    state = AuctionState(
        tuple(TeamState(name, (), rules.budget) for name in sorted({p.team for p in picks}))
    )
    for keeper in sorted((p for p in picks if p.keeper), key=lambda p: p.player_id):
        state = apply_sale(state, keeper, rules)
    return state


def replay_states(picks, rules):
    """Expose only known keepers and completed sales, then apply each observed sale."""
    state = initial_state(picks, rules)
    for sale in picks:
        if not sale.keeper:
            yield Nomination(sale.pick, sale.player_id, state)
            state = apply_sale(state, sale, rules)


def final_state(picks, rules):
    state = initial_state(picks, rules)
    for sale in picks:
        if not sale.keeper:
            state = apply_sale(state, sale, rules)
    return state


def missing_starters(roster, players, rules):
    """Fill fixed slots before FLEX; each owned player can fill only one slot."""
    counts = Counter(players[player_id].position for player_id in roster)
    missing = []
    for slot in rules.starters:
        if slot != "FLEX":
            if counts[slot]:
                counts[slot] -= 1
            else:
                missing.append(slot)
    flex_needed = rules.starters.count("FLEX")
    missing.extend(["FLEX"] * max(0, flex_needed - sum(counts[p] for p in ("RB", "WR", "TE"))))
    return tuple(missing)


def _covers(positions, needs):
    counts = Counter(positions)
    for slot in needs:
        if slot != "FLEX":
            if not counts[slot]:
                return False
            counts[slot] -= 1
    return sum(counts[p] for p in ("RB", "WR", "TE")) >= needs.count("FLEX")


def legal_capacity(team, nominee, players, available, rules):
    """Return the shared maximum legal bid and a distinct structural rejection."""
    slots = rules.roster_size - len(team.roster)
    if slots <= 0:
        return 0, "full roster"
    if nominee not in available or nominee in team.roster:
        return 0, "player unavailable"
    capacity = team.budget - (slots - 1)
    if capacity < 1:
        return 0, "insufficient reserve"
    remaining = set(available) - {nominee}
    needs = missing_starters(team.roster + (nominee,), players, rules)
    if (
        len(needs) > slots - 1
        or len(remaining) < slots - 1
        or not _covers((players[key].position for key in remaining), needs)
    ):
        return 0, "positional infeasibility"
    return capacity, None
