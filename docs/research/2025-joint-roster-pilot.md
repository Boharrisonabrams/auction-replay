# 2025 joint roster comparison

Date: September 6, 2026. Scope: Discount Double Check, Team Bo

The joint search compares the complete roster you can afford after buying a nominee with the complete roster you can afford after passing. It includes scheduled bye coverage and lets every unowned starter or bench player change. A higher individual price is supported only when the buy roster's proven advantage survives the pass branch's remaining uncertainty. This remains an exploratory core-offense comparison, not a demonstrated strategy advantage.

## What the bounds mean

The lower bound is the projected Weeks 1–17 score of a complete, affordable roster the search actually found. The upper bound limits what any completion could score under the same assumptions. Buying is supported when its lower bound exceeds the pass upper bound. Passing is supported when its lower bound meets or exceeds the buy upper bound; ties favor passing. Overlapping bounds remain unresolved. A missing roster after a work limit is different from proof that no feasible roster exists.

The shared optimizer first solves a simpler budget problem that ignores byes, then scores those complete rosters with the weekly objective to obtain useful starting solutions. The raw no-bye score supplies an upper bound. The old pilot's 16/17 conversion cannot supply that bound: a backup on a different bye can lift the weekly score above the best fixed starting lineup. An independent small example verifies this distinction and requires replacing a starting-core player to improve coverage.

The positional calculation and joint search have separate deterministic limits. An interrupted positional calculation supplies no upper-bound or infeasibility proof. The generic search remains available for inputs outside the simpler calculation's supported precision or FLEX shape. The old fixed-starter pilot and its backup-credit variants retain their previous outputs.

## Fixed comparison protocol

The forecast-only eligibility pass identifies 95 nominations for Bo. All 182 auction sales remain accounted for: 16 specialist exclusions, 27 positional infeasibilities, and 44 full-roster states. The initial engineering probes select nominations 1, 63, and 111, the earliest, middle, and latest eligible cases. The main run selects all 95 eligible nominations before loading outcomes.

Each measured nomination crosses future-price factors 0.8, 1.0, and 1.2 with a neutral forecast, a 20% nominee forecast reduction, and two explicitly absent non-bye weeks. It retains the full available pool from 422 forecast players. Only observed holdings and the nominee in the buy branch are fixed. Every other roster place remains a paid choice.

Static, inflation, and roster policies use identical observed prefixes, future-price assumptions, legal whole-dollar bids, and completion alternatives. The primary comparison covers every legal bid. Actual closing-price probes, including $1, $5, and $10 more than the closing price, are secondary descriptions. No current or later closing price enters its own recommendation.

Recommendations freeze before weekly outcomes load. The primary evaluation uses the offensive components covered by the forecasts; full-offensive scoring is a separate sensitivity. Lineups follow preseason projection ordering and scheduled byes. The optimistic hindsight lineup is labeled separately. Missing selected outcomes remain unknown. Repeated prices and overlapping rosters are neither independent observations nor additive season gains.

## Measured result

The completed run covers all 95 eligible nominations and 855 scenario records, with no unrun cases. Its CSV contains 63,729 legal-price comparisons plus 87 exclusion rows. All 173 drafted offensive season totals reconcile against Yahoo. The separately evaluated weekly window remains Weeks 1–17.

| Roster verdict | Price/scenario rows | Share |
| --- | ---: | ---: |
| Buy supported | 3,461 | 5.43% |
| Pass supported | 23,248 | 36.48% |
| Unresolved | 37,020 | 58.09% |

The nine scenarios disagree at one or more prices for 65 of 95 eligible nominations. **No supported buy exceeds either its static or inflation ceiling in this run.** This does not disprove worthwhile premiums: unresolved bounds cover much of the decision space. It means the current search has not established the premium-bidding advantage the project aims to test.

For the neutral forecast, each future-price factor has the same 7,081 legal-price rows. The following table compares the roster policy with inflation pricing on that whole-dollar grid. A matched row requires both policies to choose a branch with known evaluated outcomes.

| Future-price factor | Matched rows | Unmatched rows | Higher / lower / identical core outcome | Mean paired core points |
| --- | ---: | ---: | --- | ---: |
| 0.8 | 3,751 | 3,330 | 7 / 5 / 3,739 | +0.093 |
| 1.0 | 3,542 | 3,539 | 1 / 0 / 3,541 | +0.004 |
| 1.2 | 1,388 | 5,693 | 1 / 0 / 1,387 | +0.011 |

All unmatched rows in this table are unresolved policy comparisons; none lacks selected weekly outcomes. The mean is per matched price-decision row, not per nomination or season. Higher-budget nominations contribute more rows, and neighboring prices often repeat the same roster. Resolution also selects which rows enter the mean. These tiny descriptive averages do not establish an advantage.

Against static pricing, the same three matched sets each contain one higher core outcome and otherwise identical outcomes. The central differing row is Jordan Addison at a hypothetical $1: the roster policy passes while both baselines buy. Its later core outcome difference is +15.16 points (+13.16 using full-offensive scoring). This is one overlapping roster comparison, not a measured season gain.

For Puka Nacua, the central neutral comparison supports bids through $23, with possible bids through $57. A $50 probe has overlapping buy/pass bounds and stays unresolved. Reducing his forecast by 20% supports passing at $50. Neither the possible $57 ceiling nor his later strong season justifies presenting a precise $50 buy recommendation.

Tighter bounds near realistic auction prices are needed to determine whether the model supports materially different choices.

## Runtime measurement

The first 36-frontier measurement uses 2,000 search nodes and 2,000,000 positional transitions per branch. It takes 38.21 seconds on the local machine, including preprocessing. All twelve early-nomination positional calculations reach their transition limit. The middle and late probes finish that calculation.

| Probe nomination | Twelve frontiers, seconds | Completed positional calculations | Supported buy prices | Supported pass prices | Unresolved prices |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 19.14 | 0 | 0 | 0 | 1,458 |
| 63 | 15.20 | 12 | 88 | 58 | 430 |
| 111 | 3.77 | 12 | 0 | 108 | 0 |

These counts cover nine scenarios per nomination. They diagnose search effort, not strategy quality. A separate forecast-only measurement finishes the early neutral buy/pass positional calculations in 2.28–3.32 million transitions, taking 0.25–0.34 seconds each. The main run therefore fixes a 20,000,000-transition cap and retains 2,000 search nodes before evaluating outcomes. Timings are stored separately from deterministic recommendation hashes.

The final run takes 1,342.86 seconds (22.38 minutes), including preprocessing, serialization, and outcome evaluation. Its 1,140 shared frontiers account for 1,324.28 seconds. Every positional calculation completes under the larger cap; 1,131 joint searches still reach their 2,000-node limit. That does not force every comparison to be unresolved: separate feasible lower and valid upper bounds can prove a decision before either branch is optimized exactly.

| Probe nomination, final limits | Twelve frontiers, seconds | Buy / pass / unresolved price rows | Median buy interval width |
| --- | ---: | --- | ---: |
| 1: Saquon Barkley | 20.55 | 445 / 378 / 635 | 65.33 |
| 63: Kenneth Walker | 15.06 | 88 / 58 / 430 | 42.15 |
| 111: Jordan Addison | 3.68 | 0 / 108 / 0 | 0.00 |

Interval widths are projected core-offense points for witnessed buy branches over the legal grid. The measurements support offline replay; they do not meet a live bidding latency claim.

## Limits that remain

- Forecast pages were retrieved in 2026 with displayed preseason 2025 dates. Their hashes establish current reproducibility, not independent proof of historical immutability.
- Kicker and defense production remains excluded; their future costs are $1. Missing forecast scoring components prevent promotion to the accepted full-scoring benchmark.
- Future prices are conditional estimates based on remaining cash and earlier sales. Winning salaries reveal neither losing bids nor opponents' reactions to a different purchase.
- This season has already informed model choices. A held-out prospective evaluation is still needed before claiming an edge over either baseline or a commercial provider.

The original [historical price pilot](2025-historical-price-pilot.md) and [bench coverage study](2025-bench-coverage-study.md) remain historical evidence under their own objectives and source hashes.

## Software verification

The replay, pilot, companion, bench-study, and Yahoo-importer checks pass from a Git archive with no private source cache. The companion check compares 540 Python/browser price decisions and rejects stale identities, invalid witnesses, missing scenarios, and inconsistent proof states. The separate private-cache integration passes all 182 states, 14 keepers, and $26 final room cash, and the generated real-league view agrees with the frozen Puka result at $50. The unchanged descriptive audit reconciles the 196 original selections. There is no configured lint or typecheck, and no dependency was added.

Review found a missing FLEX-category quota when a candidate pool lacks one eligible position. The shared positional calculation now enforces that quota through an empty table. Regressions cover RB, WR, and TE pools, existing holdings, and both weekly and fixed-starter frontiers; all five suites also pass in a clean clone. The complete league rerun after this fix preserves all 942 recommendation records exactly; only their code identity changes.

Actual browser checks exercise supported buy/pass prices, overlapping bounds, a missing pass incumbent, a future-price reversal, performance selectors, invalid bids, and excluded/unrun states. Changing nominations clears the actual-sale reveal and previous branches. The current template renders without horizontal overflow at a 390-pixel Chrome viewport and at the desktop viewport. The in-app browser records no application console errors; Chrome records one unrelated extension error. These synthetic checks establish interface behavior, not historical strategy results.

A fresh full-scoring engine run still exits 1 with `benchmark_complete: false`: all 2,548 team/nomination pairs remain accounted for, with 385 structurally infeasible pairs and 2,163 missing-data pairs. The exploratory joint pilot does not satisfy those separate source gates.

## Current-season evidence

A read-only Yahoo check on September 6, 2026 verifies the 2026 league settings: half PPR, nine starters, five bench places, two IR places, and 30 enabled scoring categories. The maximum is 14 teams. The draft page currently displays 13 teams and an offline draft, with results unavailable until the commissioner publishes them. The homepage's displayed 2025 standings do not establish current membership or keeper choices.

Caleb Williams at $1 remains Bo's confirmed keeper input. Opponent keeper prices, the final team count, and a correctly configured current-season import remain unresolved. These observations do not enable current-season bidding recommendations. No provider settings changed.

## Analysis validation

**Share with caveats for local research.** Data Analytics validation independently checks nomination/scenario/price uniqueness, contiguous bid grids, all disposition denominators, paired outcome subtraction, and recommendation/CSV identity. It verifies that changing actual outcomes cannot change frozen recommendations through the existing executable tests. The validation notebook (`data/local/2025/joint-roster-pilot/validation-checks.ipynb`, private and not included) preserves the independent checks, and the summary (`data/local/2025/joint-roster-pilot/independent-summary.json`, private and not included) preserves their results; both require the private local outputs.

The available evidence supports the reported calculation behavior and exploratory comparisons. It is insufficient for a better-bidding claim, a commercial-provider comparison, a prospective season gain, or actionable 2026 recommendations. Those are decision blockers; the explicit source and scenario assumptions remain caveats to reading this research result.

- Frozen recommendation SHA-256: `47e336c6b695741285a1ed6882e4234847ae17b22089acc446105797380e1f72`.
- Decision CSV SHA-256: `56716efe070f09daf2c62cea73fcca64141c8fae65a949b93bf08f9860f11b66`.
- Replay source SHA-256: `1b93f830258b6bfecf30749cda7f432b3bf3e291b597709e29c3e6236862190f`.
- Pilot source SHA-256: `f576f20836266d0efd5c6dfef4b8583dfeb0731a6504a74e154dd4d9721bdbb6`.

## Reproduce locally

Run the portable checks from the repository directory:

```sh
python3 -B tests/test_replay_auction.py
python3 -B tests/test_historical_price_pilot.py
python3 -B tests/test_draft_companion.py
```

With the private source cache available, run `PYTHONPATH=src python3 -B -m auction_replay.historical_price_pilot --mode joint-weekly --selection all --work-limit 2000 --relaxation-limit 20000000 --output-dir data/local/2025/joint-roster-pilot`. Use a separate output directory with `--selection probes` for a smaller measurement.

The ignored output directory contains the selection and configuration, frozen recommendations, separate timings, weekly evaluation, and the decision CSV. The companion validates the complete sale accounting, source and code identity, every displayed roster, and every price decision before replacing its HTML. Private source files and generated HTML remain outside Git.
