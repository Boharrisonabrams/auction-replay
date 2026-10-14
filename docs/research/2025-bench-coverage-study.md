# 2025 bench coverage study

Date: September 6, 2026. Scope: Discount Double Check, Team Bo

This is the preserved bench-only experiment. The later [joint roster comparison](2025-joint-roster-pilot.md) supersedes its companion-state and next-step notes. To rerun this historical objective after a code update, first regenerate its legacy input with `PYTHONPATH=src python3 -B -m auction_replay.historical_price_pilot --mode fixed-starter --output-dir data/local/2025/price-pilot-companion`; the builder rejects stale source hashes.

Including useful bench players changes the relative value of complete rosters. Under the central future-price assumption, affordable bye coverage changes the buy/pass roster ranking in **30 of 82 paired comparisons**. This exposes a limitation in the earlier pilot; it does not establish an optimal bid or an advantage over room-adjusted prices.

## What changed

The study starts from the existing frozen pilot's complete buy/pass rosters. It preserves held players, the nominee in the buy branch, and the original starting core. It replaces up to three bench players when an affordable, legal replacement increases projected starter points over Weeks 1–17. Both the seed and improved roster use the same weekly objective: preseason projections divided across 17 NFL games, with scheduled byes and fixed preseason lineup rankings. Bench points count only when a player enters a starting slot.

Each probe uses the frozen room-price estimate under its future-price scenario. It does not use that nominee's closing price. The study writes every roster before loading actual weekly outcomes. Reconstructed future prices and availability remain assumptions; the study does not simulate opponents' reactions to a different purchase.

## Complete coverage

All 182 non-keeper nominations remain accounted for. The original 87 exclusions comprise 44 full-roster states, 27 positional infeasibilities, and 16 specialist nominations. The remaining 95 nominations produce 285 scenario probes: 247 paired comparisons and 38 exclusions because the forecast room price exceeds the legal bidding capacity.

| Future-price factor | Paired probes | Buy: improved projected total | Buy: median projected gain | Pass: improved projected total | Pass: median projected gain | Roster ranking changed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.8 | 86 | 71 | 16.69 | 86 | 18.15 | 35 |
| 1.0 | 82 | 78 | 17.24 | 82 | 20.69 | 30 |
| 1.2 | 79 | 24 | 0.00 | 24 | 0.00 | 21 |

Gains are projected core-offense points over Weeks 1–17, relative to the same seed roster scored with bye coverage. Ranking changes include transitions to or from a tie. The higher-price scenario often leaves no affordable improving single replacement; a zero gain is not proof that a better roster is impossible.

## Example: Puka Nacua at a forecast price of $41

| Roster comparison | Buy | Pass | Buy minus pass |
| --- | ---: | ---: | ---: |
| Seed rosters, scored with byes | 1,368.68 | 1,331.57 | +37.11 |
| After bench replacements | 1,379.29 | 1,379.86 | −0.57 |

Improving the pass roster closes the apparent advantage of buying. These are feasible roster totals, not upper bounds. The study therefore labels the comparison **unresolved** and does not turn the −0.57 difference into a bidding instruction. The companion still displays the earlier season-only pilot, with a prominent warning about this limitation.

## Actual outcomes, evaluated after the roster freeze

| Future-price factor | Buy: higher / lower actual total | Buy: median actual gain | Pass: higher / lower actual total | Pass: median actual gain |
| --- | ---: | ---: | ---: | ---: |
| 0.8 | 70 / 1 | 21.12 | 85 / 1 | 39.30 |
| 1.0 | 75 / 3 | 32.20 | 82 / 0 | 43.00 |
| 1.2 | 24 / 0 | 0.00 | 24 / 0 | 0.00 |

Unlisted cases are ties. All 247 pairs have selected-player weekly outcome coverage. The outcome loader reconciles all 173 drafted offensive season totals; its existing explicit zero-week and nonparticipant assumptions still apply. Evaluation fixes each lineup using preseason forecasts and known byes, without hindsight lineup changes, injury substitutions, or waivers.

These comparisons reuse overlapping rosters from one repeatedly studied season. Do not sum them into a season gain, treat them as independent samples, or interpret the counts as win rates. This improves an intentionally weak bench baseline; it does not show that the strategy beats FantasyPros, Draft Sharks, or the league's bidding market. Forecast pages were retrieved in 2026 with claimed preseason 2025 publication dates, not independent archived snapshots.

## Validation and next development step

The new runnable check covers bye coverage, fixed holdings, FLEX, cash limits, deterministic selection, invalid inputs, missing actual outcomes, and the freeze-before-evaluation boundary. All four existing research checks also pass, including the companion's 21,243 browser-calculation comparisons. An independent artifact check re-scores all 494 improved rosters and verifies source hashes, roster sizes, starter feasibility, protected players, and nonnegative projected gains. No lint or typecheck is configured.

Compound Engineering simplification completed all three reviews: reuse and quality required no changes; efficiency removed repeated set construction and sorting. **Code review: skipped (ce-code-review unavailable).** The actual invocation terminated because the ce-code-review skill owns a scope rule (in its references/scope.md) stating, “Untracked paths are out of scope unless staged.” Direct source inspection and calculation checks completed; formal review remains outstanding before publication. No Git staging or publishing occurred.

Keep this as a model study until a joint starter-and-bench search supplies useful optimality bounds. The three-swap search preserves the starting core and can miss improvements that require multiple coordinated replacements. Kicker and defense points, full scoring, and prospective injury behavior remain outside this pilot. The 2026 account check was blocked by the Mac lock; opponent keeper inputs and scoring still need verification before actionable 2026 prices. Caleb Williams at $1 remains the confirmed keeper input.

## Reproduce locally

From the repository directory, run `python3 -B tests/test_bench_coverage.py`, then `PYTHONPATH=src python3 -B -m auction_replay.bench_coverage`. The study uses the ignored source cache and validates the existing companion snapshot before computing.

- Frozen rosters and source hashes (`data/local/2025/bench-coverage/rosters.json`, private and not included)
- Separate actual-outcome evaluation (`data/local/2025/bench-coverage/evaluation.json`, private and not included)
- Local validation record (`data/local/2025/bench-coverage/validation.json`, private and not included)
- [Study implementation](../../src/auction_replay/bench_coverage.py)
- [Accepted replay plan](../plans/2026-09-05-1630-feat-league-specific-auction-replay-plan.md)
