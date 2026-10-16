"""Replay a fantasy football auction and compare buy-versus-pass complete rosters.

Standard library only. Run modules with ``python3 -m auction_replay.<module>`` from a checkout
(``PYTHONPATH=src``) or after ``python3 -m pip install -e .``.

The names in ``__all__`` are the replay engine's public API, for example
``from auction_replay import load_rules, replay_markets, compare_nominee``. The engine
modules, in reading order, are inputs, loaders, state, pricing, search, decisions, and
benchmark. The replay_auction module re-exports the same names for older imports and is
the command-line entry point, so this package does not import it.
"""

from .benchmark import run_benchmark
from .decisions import (
    DECISION_FIELDS,
    EVALUATION_FIELDS,
    canonical_bytes,
    decision_rows,
    evaluate_roster,
    policy_action,
)
from .inputs import (
    POSITIONS,
    AuctionPick,
    InputError,
    LeagueRules,
    Player,
    decimal,
    integer,
    json_object,
    rows,
    text,
    timestamp,
)
from .loaders import (
    load_auction,
    load_forecasts,
    load_reference_values,
    load_rules,
    load_weekly_outcomes,
    scoring_hash,
    validate_manifest,
    weekly_gaps,
)
from .pricing import (
    baseline_ceiling,
    future_prices,
    inflation_prices,
    market_adjustment,
    rebase_reference,
    reference_pool,
    replay_markets,
)
from .search import (
    DEFAULT_RELAXATION_LIMIT,
    BudgetFrontier,
    NomineeComparison,
    NomineeScenario,
    PositionalFrontier,
    PriceComparison,
    RosterBound,
    compare_nominee,
    completion_frontier,
    nominee_scenarios,
    positional_frontier,
    projected_lineup,
    projected_total,
)
from .state import (
    AuctionState,
    MarketMoment,
    Nomination,
    TeamState,
    apply_sale,
    final_state,
    initial_state,
    legal_capacity,
    missing_starters,
    replay_states,
)

__all__ = [
    # inputs: shared records, the input error, and checked parsing helpers
    "POSITIONS",
    "AuctionPick",
    "InputError",
    "LeagueRules",
    "Player",
    "decimal",
    "integer",
    "json_object",
    "rows",
    "text",
    "timestamp",
    # loaders: rules, the auction CSV, and manifest-checked source files
    "load_auction",
    "load_forecasts",
    "load_reference_values",
    "load_rules",
    "load_weekly_outcomes",
    "scoring_hash",
    "validate_manifest",
    "weekly_gaps",
    # state: the observed auction, one sale at a time
    "AuctionState",
    "MarketMoment",
    "Nomination",
    "TeamState",
    "apply_sale",
    "final_state",
    "initial_state",
    "legal_capacity",
    "missing_starters",
    "replay_states",
    # pricing: estimates from earlier sales only
    "baseline_ceiling",
    "future_prices",
    "inflation_prices",
    "market_adjustment",
    "rebase_reference",
    "reference_pool",
    "replay_markets",
    # search: roster bounds and the buy-versus-pass comparison
    "DEFAULT_RELAXATION_LIMIT",
    "BudgetFrontier",
    "NomineeComparison",
    "NomineeScenario",
    "PositionalFrontier",
    "PriceComparison",
    "RosterBound",
    "compare_nominee",
    "completion_frontier",
    "nominee_scenarios",
    "positional_frontier",
    "projected_lineup",
    "projected_total",
    # decisions: one row per legal price and scenario, and roster evaluation
    "DECISION_FIELDS",
    "EVALUATION_FIELDS",
    "canonical_bytes",
    "decision_rows",
    "evaluate_roster",
    "policy_action",
    # benchmark: the full frozen-then-evaluated run
    "run_benchmark",
]
