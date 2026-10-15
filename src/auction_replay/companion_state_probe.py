"""Offline evidence: accepted purchases can fail the optimizer's roster policy.

Run from the repository root: PYTHONPATH=src python3 -B -m auction_replay.companion_state_probe
No API calls or provider values. Outputs a reproducible JSON evidence receipt.
"""

import hashlib
import json
from pathlib import Path

from . import replay_auction as replay


if __name__ == "__main__":
    auction = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "research"
        / "2025-discount-double-check-auction.csv"
    )
    rules = replay.LeagueRules()
    picks = replay.load_auction(auction, rules)
    players = {p.player_id: p for p in picks}
    moments = tuple(replay.replay_states(picks, rules))
    final = replay.final_state(picks, rules)
    keeper_cost = sum(p.salary for p in picks if p.keeper)
    exceptions = []
    for moment in moments:
        state = moment.state
        assert (
            sum(t.budget for t in state.teams)
            + keeper_cost
            + sum(sale.salary for sale in state.sales)
            == rules.teams * rules.budget
        )
        sale = players[moment.player_id]
        if sale.team != "Team Bo":
            continue
        team = state.team(sale.team)
        slots = rules.roster_size - len(team.roster)
        cash_cap = team.budget - (slots - 1)
        model_cap, reason = replay.legal_capacity(
            team, sale.player_id, players, set(players) - state.owned, rules
        )
        if reason == "positional infeasibility" and sale.salary <= cash_cap:
            exceptions.append(
                dict(
                    pick=sale.pick,
                    player=sale.name,
                    actual_cost=sale.salary,
                    budget=team.budget,
                    open_slots=slots,
                    cash_reserve_cap=cash_cap,
                    optimizer_cap=model_cap,
                    optimizer_reason=reason,
                )
            )
    assert len(moments) == 182 and keeper_cost == 231
    assert sum(t.budget for t in final.teams) == 26
    assert [(row["pick"], row["cash_reserve_cap"], row["optimizer_cap"]) for row in exceptions] == [
        (129, 8, 0),
        (138, 3, 0),
    ]
    print(
        json.dumps(
            dict(
                evidence="Offline 2025 observed sales; no live platform-cap verification",
                inputs_sha256={
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (auction, Path(replay.__file__), Path(__file__))
                },
                sale_states_checked=len(moments),
                keeper_cost=keeper_cost,
                final_league_cash=sum(t.budget for t in final.teams),
                cash_conservation="passed at every pre-sale state",
                accepted_purchases_rejected_by_completion_policy=exceptions,
                consequence="Do not use optimizer legal_capacity as a Yahoo opponent lockout. "
                "It includes a complete-starters policy beyond the cash reserve cap.",
            ),
            indent=2,
        )
    )
