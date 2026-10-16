"""Run the auction replay benchmark, and keep the engine's original import path working.

The replay engine lives in seven modules. In reading order they are inputs, loaders,
state, pricing, search, decisions, and benchmark. This module re-exports their names,
including the underscore helpers that other modules and the tests use, so existing
imports and the auction-replay console script keep working. To run the benchmark from a
checkout, use: PYTHONPATH=src python3 -B -m auction_replay.replay_auction --help

Local auction replay inputs, kept separate from realized player production.

Normalized forecasts: provider_id,name,position,nfl_team,bye,projected_points.
Points cover the NFL's 17 scheduled games, scored using the explicit league rules.
Reference values: provider_id,reference_value (original whole or fractional dollars).
Weekly outcomes: player_id,week,points,status; status is verified or missing.

Each normalized source has a JSON manifest: url, season, published_at,
retrieved_at, sha256 (normalized file bytes), scoring_coverage (rule keys),
scoring_hash, identity_mappings ([{provider_id, player_id}]), and local_use.
Preseason manifests also declare includes_undrafted=true. Reference manifests
record source_scoring and source_format descriptions instead of league scoring
coverage/hash, because their original values are rebased later. Publisher dates and
coverage are source claims, not proof that a historical page was never revised.
Keep original snapshots and their hashes with collection notes in data/local/.
"""

import sys
from types import ModuleType

from . import benchmark, decisions, inputs, loaders, pricing, search, state
from .benchmark import _cell as _cell
from .benchmark import _file_hash as _file_hash
from .benchmark import _json_list as _json_list
from .benchmark import _render_report as _render_report
from .benchmark import main, run_benchmark
from .decisions import (
    DECISION_FIELDS,
    EVALUATION_FIELDS,
    canonical_bytes,
    decision_rows,
    evaluate_roster,
    policy_action,
)
from .decisions import _structural_rejection as _structural_rejection
from .inputs import POSITIONS, AuctionPick, InputError, LeagueRules, Player
from .loaders import _mapped_id as _mapped_id
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
from .pricing import _pool_warnings as _pool_warnings
from .pricing import _rescale as _rescale
from .pricing import _validate_auction_forecasts as _validate_auction_forecasts
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
from .search import _compare_frontiers as _compare_frontiers
from .search import _forecast_weights as _forecast_weights
from .search import _projected_lineup as _projected_lineup
from .search import _projected_total as _projected_total
from .search import _prune_positional as _prune_positional
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
from .state import _covers as _covers

__all__ = [
    "DECISION_FIELDS",
    "DEFAULT_RELAXATION_LIMIT",
    "EVALUATION_FIELDS",
    "POSITIONS",
    "AuctionPick",
    "AuctionState",
    "BudgetFrontier",
    "InputError",
    "LeagueRules",
    "MarketMoment",
    "Nomination",
    "NomineeComparison",
    "NomineeScenario",
    "Player",
    "PositionalFrontier",
    "PriceComparison",
    "RosterBound",
    "TeamState",
    "apply_sale",
    "baseline_ceiling",
    "canonical_bytes",
    "compare_nominee",
    "completion_frontier",
    "decision_rows",
    "evaluate_roster",
    "final_state",
    "future_prices",
    "inflation_prices",
    "initial_state",
    "legal_capacity",
    "load_auction",
    "load_forecasts",
    "load_reference_values",
    "load_rules",
    "load_weekly_outcomes",
    "main",
    "market_adjustment",
    "missing_starters",
    "nominee_scenarios",
    "policy_action",
    "positional_frontier",
    "projected_lineup",
    "projected_total",
    "rebase_reference",
    "reference_pool",
    "replay_markets",
    "replay_states",
    "run_benchmark",
    "scoring_hash",
    "validate_manifest",
    "weekly_gaps",
]

# The parsing helpers are public in inputs. Other modules and the tests still reach them
# here by their former underscore names.
_text = inputs.text
_integer = inputs.integer
_decimal = inputs.decimal
_timestamp = inputs.timestamp
_json = inputs.json_object
_rows = inputs.rows

_ENGINE_MODULES = (inputs, loaders, state, pricing, search, decisions, benchmark)


class _EngineNames(ModuleType):
    """Copy an assignment to one of this module's names into the engine modules.

    While this file held the whole engine, replacing one of its names, for example with
    unittest.mock.patch.object, changed what every engine function called. Engine
    functions now look names up in their own modules, so an assignment here also
    rebinds each engine module name that holds the object being replaced.
    """

    def __setattr__(self, name, value):
        if not name.startswith("__") and name in vars(self):
            replaced = vars(self)[name]
            for module in _ENGINE_MODULES:
                for key, bound in tuple(vars(module).items()):
                    if bound is replaced:
                        setattr(module, key, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _EngineNames

if __name__ == "__main__":
    raise SystemExit(main())
