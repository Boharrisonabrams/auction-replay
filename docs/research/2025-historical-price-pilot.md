# Historical price experiment: 2025

**Result: this first model does not demonstrate better pricing than room-adjusted values.** Under the central assumptions, its action differs from the inflation baseline at 13 tested decisions. Its chosen roster later scores better in 4 and worse in 9. It still declines Puka Nacua and Jaxon Smith-Njigba at the tested prices. This is useful negative evidence before investing in live integration.

This report is an **exploratory core-offense pilot for Team Bo**, not the completed [full league benchmark](2025-auction-replay.md). It uses the actual room's 14 teams, keepers, budgets, and sale order, but calculates counterfactuals for one manager. It neither simulates a new auction nor estimates championship odds.

## What ran

- Reconstructed all 196 selections, including 14 keepers and 182 auction sales.
- Accounted for every nomination for your team: **95 eligible offensive decisions**, 44 after your roster filled, 27 purchases that could not leave enough starting-position slots, and 16 specialist nominations outside this pilot's objective.
- Evaluated the 95 decisions under **15 combinations of assumptions**, producing 1,425 scenario records. Each retains every legal price comparison's budget frontier, complete roster, and future cost.
- Froze recommendations before loading weekly outcomes or using closing prices to select evaluation probes.
- Evaluated **5,340 affordable probes** across observed closing price, closing price plus $1, plus $5, and plus $10. A probe requires both a feasible buy and pass completion. These are conditional purchase-price scenarios, not claims that those bids would have won.
- Reconciled **all 173 drafted offensive players** to Yahoo's full regular-season totals. Week 18 enters this source check only; the roster evaluation stops after Week 17.

## Central comparison

The central case uses the neutral forecast and future-price estimate, no projected bench credit, and a tested purchase price of **observed closing price plus $1**. There are 92 comparable decisions with affordable, feasible buy and pass alternatives and complete selected-lineup outcomes.

| Policy | Buy decisions | Pass decisions | Mean paired points versus inflation policy |
| --- | ---: | ---: | ---: |
| Static value-based ceiling | 34 | 58 | -6.68 |
| Room-adjusted inflation ceiling | 47 | 45 | 0.00 |
| Roster-based ceiling | 36 | 56 | -6.69 |

For each decision, both policies use the same two completed rosters and the same lineup rule. The paired difference is the later Weeks 1–17 offensive score of the roster chosen by one policy minus the roster chosen by inflation. Equal actions contribute zero. The table averages these differences across 92 decisions.

**These averages are not team-season gains or independent observations.** Decisions share players and historical states. Do not sum them into an imagined season or use this one auction to claim statistical significance. Core-only outcome scoring and full offensive scoring are both retained; the table uses full offensive scoring.

## Decisions that explain the result

Ceilings are whole-dollar limits under the central case. Outcome differences compare the frozen buy and pass rosters at the tested price, with full offensive scoring and preseason lineup ordering.

| Nominee | Static ceiling | Inflation ceiling | Roster ceiling | Tested price | Roster action | Later buy-minus-pass points |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Christian McCaffrey | $71 | $85 | $82 | $64 | Buy | +422.14 |
| Puka Nacua | $34 | $43 | $40 | $50 | Pass | +134.54 |
| Drake London | $25 | $33 | $33 | $51 | Pass | -288.60 |
| James Conner | $37 | $51 | $52 | $52 | Buy | -228.80 |
| Calvin Ridley | $15 | $20 | $20 | $15 | Buy | -150.44 |
| Jaxon Smith-Njigba | $21 | $29 | $29 | $40 | Pass | +118.10 |
| Rome Odunze | $3 | $4 | $3 | $15 | Pass | -25.96 |
| George Pickens | $6 | $7 | $4 | $19 | Pass | +273.80 |

The cases include successful and failed expensive purchases. They illustrate the complete decision set; they did not select the forecast universe or tune the model.

The room adjustment already explains much of the increase over static prices. The roster calculation often stays near it, and sometimes lowers the ceiling. At Conner's tested price, only about **0.09 projected points** separate buy and pass in the simplified objective. That is a mathematical breakpoint, not a practically reliable edge.

Puka's cached preseason core projection is **223.30 points**; Smith-Njigba's is **197.40**. This forecast set does not make either a sufficiently large upgrade over the modeled alternatives to justify the tested price. Their strong eventual production cannot be fed back into the forecast to make this test succeed.

## Sensitivity results

The following entries are mean paired later points per comparable decision versus the inflation policy, still at closing price plus $1. Each column changes all future offensive purchase-price estimates, not the nominee's tested price. Baseline ceilings remain fixed while their common completion evaluator uses the same scenario as the roster policy.

| Valuation assumption | Future prices ×0.8 | Future prices ×1.0 | Future prices ×1.2 |
| --- | ---: | ---: | ---: |
| Fixed starters, no projected bench utility | +0.76 | -6.69 | +1.08 |
| First backup at each offensive position credited 12.5% | -4.42 | -8.13 | -0.76 |
| First backup credited 25% | -2.06 | -11.11 | -0.76 |
| Nominee forecast reduced 20% | +13.57 | -3.75 | -3.28 |
| Nominee forecast reduced by two of 16 games | +9.60 | +0.50 | -9.15 |

The direction changes across assumptions. Selecting the most favorable cell after seeing outcomes would fit this season rather than validate the strategy. All factors were declared before the first run; none is a calibrated probability.

Across these scenarios, Puka's modeled ceiling ranges from **$11 to $48** and Smith-Njigba's from **$0 to $35**. Neither reaches the central tested purchase price. A $0 ceiling means no tested positive-dollar purchase improves the modeled objective; it does not mean the player has no value.

## Exact model and deliberate simplifications

**Static baseline.** Calculate each player's projected points above positional replacement. Replacement is the first player beyond assumed league-wide starter demand: QB 15, RB 36, WR 36, and TE 15. This splits the league's 14 FLEX places evenly between RB and WR. Rebase positive excess value into the league's discretionary dollars using the existing replay code. These are derived VBD prices, not a recreation of the original advice tool or FFToday's published auction prices. The published table covers only 192 of 357 projected offensive players and omits 14 who were actually drafted.

**Room adjustment.** Reuse the existing keeper-adjusted inflation calculation and pooled prior-sale adjustment. A decision sees earlier sales, not its own closing price or later sales. Future prices vary by 0.8, 1.0, and 1.2. An opponent's actual maximum bid remains unknown.

**Roster ceiling.** For every remaining budget, an exact dynamic program selects a full 14-player roster, respecting already-owned players, remaining dollars, the starting positions, and FLEX. It maximizes the best fixed starting lineup's season projection. The largest bid with a strictly better buy objective than pass is the ceiling; equality passes. Tests compare these frontiers against exhaustive enumeration.

**Depth and specialists.** The primary objective gives the bench no projected utility, which structurally favors concentration. The backup-credit cases expose part of this assumption without claiming to model injuries or waivers. Kicker and defense production is excluded. Their roster slots remain required; future purchases cost $1. Any specialist salary already paid in the actual draft remains paid. No budget is created or refunded.

**Weeks and outcomes.** The optimizer's uniform 16/17 scale is an approximate Week 18 exclusion; it does not model bye coverage or change the optimal selection. Later evaluation uses actual weekly results through Week 17, the known preseason bye, and a fixed preseason projection ordering to fill legal starting slots. It allows bye backups but no injury-aware swaps or waiver pickups. Optimistic hindsight lineup totals are also saved and are not used in the headline comparison.

**Scoring.** Forecasts use the components available in each position's table, with the captured Yahoo coefficients: passing yards/TDs/interceptions, rushing yards/TDs, and receptions/receiving yards/TDs where provided. They omit fumbles, two-point conversions, return scores, and unlisted cross-position statistics. Outcomes are scored both on this same component subset and on full offensive league scoring. The buy-versus-pass outcome sign changes for two central probes between those scoring definitions, which is another reason to retain the distinction. This pilot never writes accepted full-scoring inputs.

**Coverage assumptions.** A known season participant with no weekly stat row is assigned zero recorded stats, after checking complete regular-season team-game coverage and reconciling drafted season totals. An unknown identity or unexplained season-long absence stays missing. Joe Mixon, Brandon Aiyuk, and Amari Cooper have explicit documented nonparticipation exceptions. No projected player is removed because of later injury or missing outcomes.

## Sources and identity checks

- The original [Yahoo auction and settings analysis](2025-discount-double-check-analysis.md) supplies draft facts. The replay preserves $2,774 spent, including $231 in keeper salaries.
- [FFToday preseason projections](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=10&Season=2025) supply 422 candidates, including 357 offensive players. The cached pages display August 31, 2025, before the September 3 draft. They were retrieved in 2026, **not independently archived before the draft**. Source dates are publisher claims; the snapshot hashes establish reproducibility now.
- [nflverse weekly statistics](https://nflreadr.nflverse.com/reference/load_player_stats.html) supply later outcomes. Source hashes are in the local inventory.
- All 25 rookie ID gaps resolve by unique name and position with explicit suffix normalization. Travis Hunter's outcomes join by GSIS while retaining WR eligibility; filtering his CB-labeled statistical rows would lose production.
- Kyle Williams uses the 2025 Patriots rookie identity, corroborated by the [Patriots' draft announcement](https://www.patriots.com/video/patriots-select-kyle-williams-with-no-69-pick-in-2025-draft), rather than the older WR namesake.
- Outcome-only nonparticipation evidence: [Mixon's missed season](https://www.nfl.com/news/texans-release-rb-joe-mixon-after-foot-injury-wiped-out-entire-2025-season), [Aiyuk's season-ending reserve designation](https://www.nfl.com/_amp/niners-place-brandon-aiyuk-on-reserve-left-squad-list-ending-wr-s-season), and [Cooper's Reserve/Retired transaction](https://www.raiders.com/news/raiders-sign-justin-shorter-active-roster-amari-cooper-reserve-retired-list-2025-nfl-transactions).

## Reproduce and inspect

From the repository root, run the focused checks with `python3 -B tests/test_historical_price_pilot.py`.

From the repository root, run `PYTHONPATH=src python3 -B -m auction_replay.historical_price_pilot --output-dir data/local/2025/price-pilot-verified` to regenerate the machine-readable experiment. It requires the existing ignored source cache, uses Python's standard library, and makes no network calls. `recommendations.json` freezes the full price frontiers; `evaluation.json` links to that file's SHA-256 and retains every evaluated roster and score. The summary above is calculated from those files. A successful pilot exit is not completion of the original full-scoring benchmark.

The 182-nomination summary (`data/local/2025/price-pilot-verified/summary.csv`, private and not included) includes central ceilings, scenario ranges, and reasons for exclusions. The frozen recommendations (`data/local/2025/price-pilot-verified/recommendations.json`, private and not included) and roster evaluations (`data/local/2025/price-pilot-verified/evaluation.json`, private and not included) are larger local files.

The calculation checks cover exhaustive budget/roster oracles, held-player constraints, FLEX and backup credits, invalid prices, and independence from the current closing price. The existing replay suite also passes. The complete rerun finishes in about 168 seconds on this machine; recommendation records and evaluation rows match the first run's semantic SHA-256 hashes exactly after simplification.

Compound Engineering review `price-pilot-09b9d6cc5c` completed six local review lenses with no production-code defects retained. Independent correctness review passed 1,920 randomized small-auction oracle comparisons. The retained command-lifecycle test gap is resolved: the focused suite now invokes the command entry point, checks that recommendations exist before evaluation, verifies the linked output hash, and requires failure if evaluation changes the frozen file. External Claude and Grok review attempts could not authenticate, so there is no cross-model corroboration. These checks support calculation correctness under the declared objective, not predictive superiority.

## Next development decision

Keep historical testing ahead of integration. Preserve this first result rather than tuning a multiplier until 2025 looks favorable. The next useful experiment is to compare independent, dated preseason forecasts and complete weekly bench/bye valuation on earlier league history, then evaluate a frozen choice on another season. The current evidence supports neither a blanket superstar premium nor a claim that the new ceiling beats room inflation.
