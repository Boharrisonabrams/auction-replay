# 2025 auction replay

**Benchmark INCOMPLETE**: `benchmark_complete: false`.

This local report separates observed auction facts, conditional draft-time recommendations, and later evaluation. A partial report or a synthetic calculation proof cannot establish a premium strategy for this league.

## Reproduce the report

To regenerate these artifacts, run `PYTHONPATH=src python3 -B -m auction_replay.replay_auction --auction docs/research/2025-discount-double-check-auction.csv --input-dir data/local/2025 --report docs/research/2025-auction-replay.md --csv data/local/2025/replay-decisions.csv --work-limit 2000` from the repository root. Exit 0 means complete, 1 means a generated incomplete benchmark, and 2 means an input/output error.

To run the calculation checks, use `python3 -B tests/test_replay_auction.py` from the repository root.

The machine-readable CSV is `replay-decisions.csv` under `data/local/2025`. It contains every team/nomination pair: one row per legal price and scenario when inputs are valid, or one blank-price row for a blocked pair.

## Coverage and observed auction

196 selections; 182 auction nominations; 14 teams; 2548 team/nomination pairs. Total spend $2,774; keeper commitments $231; remaining cash $26.

The captured league rules declare 30 enabled scoring categories; scoring SHA-256 `3152bfbab64b31c5131fb593daf694ef342d59234c9d48fb8052d7218b7e1a4c`.

League settings (private Yahoo league page; link removed from the public copy); captured 2026-09-05T23:05:21.773Z; source SHA-256 `c4dbd19eb30b0ddbe2dd6886d86dff24d60ad5ed869e99b99b360ca66ebce9e8`.

| Disposition | Pairs | Static rows | Inflation rows | Roster rows |
| --- | --- | --- | --- | --- |
| supported | 0 | 0 | 0 | 0 |
| pass | 0 | 0 | 0 | 0 |
| infeasible | 385 | 385 | 385 | 385 |
| missing-data | 2163 | 2163 | 2163 | 2163 |
| search-unresolved | 0 | 0 | 0 | 0 |

Each pair receives one summary label: missing-data, then search-unresolved, supported, pass, or infeasible. The CSV retains mixed actions across prices. Rows and overlapping branches are not independent samples or additive seasons.

Structural rejection: 312 pairs have a full roster; 73 purchases leave too few starter slots. These proofs use observed holdings only. Missing forecasts never shrink the unknown eligible future universe.

| Team | Spent | Roster | Unfilled starting positions | Pair dispositions |
| --- | --- | --- | --- | --- |
| Team L | $200 | 14 | none | infeasible: 11, missing-data: 171 |
| Team C | $198 | 14 | missing K | infeasible: 27, missing-data: 155 |
| Team K | $200 | 14 | missing DEF | infeasible: 20, missing-data: 162 |
| Team Bo | $198 | 14 | missing K | infeasible: 71, missing-data: 111 |
| Team J | $200 | 14 | none | infeasible: 31, missing-data: 151 |
| Team E | $188 | 14 | none | infeasible: 66, missing-data: 116 |
| Team H | $200 | 14 | none | infeasible: 7, missing-data: 175 |
| Team F | $198 | 14 | missing DEF | infeasible: 36, missing-data: 146 |
| Team G | $196 | 14 | none | infeasible: 29, missing-data: 153 |
| Team I | $200 | 14 | missing K | infeasible: 1, missing-data: 181 |
| Team A | $200 | 14 | none | infeasible: 10, missing-data: 172 |
| Team B | $200 | 14 | none | infeasible: 3, missing-data: 179 |
| Team D | $200 | 14 | none | infeasible: 34, missing-data: 148 |
| n/a | $196 | 14 | none | infeasible: 39, missing-data: 143 |

Actual holdings remain unchanged, including missing starters. The evaluator adds no replacement player, refund, waiver, or injury substitution.

## Evidence blockers

- Policy input: unreadable JSON input: [Errno 2] No such file or directory: 'data/local/2025/forecasts.manifest.json'
- Weekly evaluation: accepted forecasts are unavailable for weekly evaluation

Collection notes below record source research. Current loader failures appear above; these notes may be stale after you supply accepted normalized files and do not override their validation results.

- **forecast_scoring_incomplete** (all roster recommendations): 422 publisher-dated preseason candidate rows cover QB 64, RB 93, WR 131, TE 69, K 33, and DEF 32. No complete league-scored forecast universe is accepted. Offensive lost-fumble, return-TD and offensive fumble-return-TD forecasts are absent; kicker field-goal yardage is absent; DEF season points allowed cannot reconstruct weekly scoring bands. No zero substitutions. [Required source](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=80&Season=2025).
- **reference_coverage_incomplete** (static and inflation baselines): The FFToday table prices 216 players for 12 teams, $200 budgets and 18 roster spots, including only 12 defenses. It does not cover the full 422-player forecast universe. Source differences require rebasing and verified identities; missing prices cannot be assumed to be $1. [Required source](https://www.fftoday.com/rankings/25_av_half_ppr.html).
- **identity_crosswalk_incomplete** (recommendations and outcomes): No approved complete FFToday-to-Yahoo crosswalk exists. A candidate name-and-position diagnostic has 20 alias or defense-name differences. The DynastyProcess direct Yahoo-to-GSIS join lacks 25 drafted offensive rookies. Diagnostic files identify them; no silent fuzzy joins are accepted. [Required source](https://nflreadr.nflverse.com/reference/load_ff_playerids.html).
- **weekly_outcomes_unreconciled** (realized evaluation): Raw 2025 weekly statistics were collected. With the recovered Yahoo offensive coefficients, 145 of 173 drafted offensive season totals match exactly, including Week 18 solely to reconcile the earlier snapshot. The remaining cases are 25 rookie ID gaps and three players without rows. Weekly participation completeness and K/DEF scoring reconciliation remain outstanding. No accepted weekly.csv exists. [Required source](https://nflreadr.nflverse.com/reference/load_player_stats.html).

## Policies, scenarios, and search bounds

Static values rebase source excess dollars above $1 to the league's budget and roster pool. Inflation rescales remaining discretionary dollars. Future prices use only earlier auction sales, with a median sale-to-prediction ratio shrunk toward 1 by n/(n+20). The original advice tool remains unidentified; these public-reference policies do not measure that tool's performance.

All three policies share the captured state, legal integer price grid, future pool, paid roster completion, and branch frontiers. The CSV distinguishes source values, raw estimates, legally capped policy ceilings, and executable actions. Baseline 'supported' means within its ceiling with a feasible buy incumbent; it does not prove that buying beats passing. A baseline cannot confirm a buy without a feasible roster.

The roster policy supports buying only if its feasible buy lower bound exceeds the pass upper bound, or passing is proven infeasible. Equality passes. Overlapping bounds remain search-unresolved. Buy future cost excludes the nominee; buy total cost adds the tested nominee price. Both exclude previously paid holdings. Every row records exact Decimal bounds, roster IDs, costs, state, node counts, and reasons.

Each branch has a deterministic 2,000-node limit. Frontiers are reused across prices; the pass frontier is also shared across nominee-only stresses at the same future prices. The subset search can leave realistic pools unresolved; no runtime or resolution rate is promised. A limit is never proof of infeasibility.

The nine defined scenarios cross future-price factors 0.8, 1.0, and 1.2 with neutral forecasts, a 20% nominee forecast reduction, and two nominee absences in the first two non-bye evaluation weeks. Season forecasts are distributed over 17 scheduled games and scored in Weeks 1–17. Byes drive bench coverage. Scenarios are stress assumptions, not calibrated probabilities.

Scenario execution: no price grid is evaluated; all nine scenarios are defined but none are run.

**Scenario disagreement:** 0 evaluated pairs change action across scenarios. Zero disagreements with no evaluated grid means missing evidence, not robustness. The CSV repeats each pair's neutral supported/possible ceiling and scenario ranges, plus disagreement at the tested price.

## Named decision examples within full coverage

These nomination examples preserve all teams at each named moment. No observed season points choose a favorable branch. Read the complete CSV for every other nomination. Blank ceilings indicate blocked inputs, not a $0 valuation.

| Pick | Nominee | Team | Disposition | Neutral supported / possible | Scenario supported range | Possible range | Disagrees |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 14 | Puka Nacua | Team L | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team C | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team K | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team Bo | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team J | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team E | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team H | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team F | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team G | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team I | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team A | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team B | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | Team D | missing-data | unavailable | unavailable | unavailable | unavailable |
| 14 | Puka Nacua | n/a | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team L | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team C | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team K | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team Bo | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team J | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team E | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team H | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team F | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team G | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team I | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team A | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team B | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | Team D | missing-data | unavailable | unavailable | unavailable | unavailable |
| 49 | Calvin Ridley | n/a | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team L | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team C | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team K | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team Bo | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team J | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team E | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team H | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team F | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team G | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team I | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team A | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team B | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | Team D | missing-data | unavailable | unavailable | unavailable | unavailable |
| 53 | Rome Odunze | n/a | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team L | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team C | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team K | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team Bo | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team J | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team E | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team H | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team F | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team G | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team I | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team A | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team B | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | Team D | missing-data | unavailable | unavailable | unavailable | unavailable |
| 60 | Travis Hunter | n/a | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team L | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team C | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team K | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team Bo | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team J | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team E | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team H | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team F | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team G | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team I | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team A | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team B | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | Team D | missing-data | unavailable | unavailable | unavailable | unavailable |
| 66 | Jerry Jeudy | n/a | missing-data | unavailable | unavailable | unavailable | unavailable |

## Separate realized evaluation

All completed roster alternatives and the recommendation payload freeze before weekly outcomes load. Fixed-preseason lineups use the base forecast ordering, stable ID ties, and known byes, even when the purchase scenario stressed a forecast. A selected player's missing week makes its score unknown; verified nonparticipation can be zero. Known byes and unfilled positions contribute zero. Week 18 is excluded.

The separately labeled optimistic hindsight lineup selects the best legal weekly lineup over the same frozen roster. Any missing active eligible player's outcome makes that week's optimistic bound unknown. Empty slots may score zero. Neither method models roster transactions. No overlapping alternative is summed into a simulated team season, and 2025 remains exploratory because its outcomes have already informed the question.

Unknown evaluation branch rows: fixed-preseason 0; optimistic hindsight 0. These are coverage counts, not independent observations. With no completed alternatives, zero counts mean evaluation was unavailable.

Actual-roster outcome scores are unavailable because accepted forecast and weekly outcome inputs are unavailable.

## Reproducibility and source provenance

- Recommendation SHA-256: `36d205f7862220ddc52ff1ef8ca52f4fb1a54d7931a2f38af926da0244d349ac`.
- Decision CSV SHA-256 (includes evaluation): `0fffcec339f3ca1f688140e19fe2af518f87a52f75f286f5d55b31eddc4b2359`.
- Raw auction file SHA-256 (descriptive only; may include outcome columns): `18ed2d5c1970f573d3fa4ffd43bc5f3898775169e109fe51b83648978407cf43`.
- Recommendation hashing includes only whitelisted auction facts, structural/scoring rules, accepted preseason manifests, search settings, implementation bytes, and frozen policy rows. Raw outcome columns and weekly source hashes cannot alter it.
- Public copy: league team names are pseudonymized (Team A to Team L, plus Team Bo and the source's `n/a` label). The SHA-256 values above describe the original private files, so they do not match the pseudonymized CSV.


Cached raw sources below are candidates, not accepted normalized policy inputs. Hash checks establish current cache reproducibility; publisher dates do not prove historical immutability. Raw reconciliation that includes Week 18 is diagnostic only.

**Raw cache verification: 16/16 hashes match; 0 missing or mismatched.** This check is separate from normalized-input acceptance.

| Raw source | Season | Publisher date | Retrieved | Cache hash | SHA-256 |
| --- | --- | --- | --- | --- | --- |
| [reference](https://www.fftoday.com/rankings/25_av_half_ppr.html) | 2025 | 8/24/25 | 2026-09-05T23:55:53.724283+00:00 | matches | 26f9ced528ce5856738861d4f455b59919ae73277c4b598cb3274216411354fa |
| [QB](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=10&Season=2025) | 2025 | 8/31/2025 | 2026-09-05T23:55:54.067927+00:00 | matches | d550a3d79a1429e6901abf3554c6cd96e0285fbbfc7b97f12d922195a26bff0e |
| [RB](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=20&Season=2025) | 2025 | 8/31/2025 | 2026-09-05T23:55:54.417037+00:00 | matches | 0cca2fc9271981ed7e4c58dd2b953e23b44aa25132c595171419ea3feba889a3 |
| [WR](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=30&Season=2025) | 2025 | 8/31/2025 | 2026-09-05T23:55:54.767759+00:00 | matches | f480199ad1c30c6a2d0c5b49b2e5923bd0750551c3468b07f7466e55303f92b7 |
| [TE](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=40&Season=2025) | 2025 | 8/31/2025 | 2026-09-05T23:55:55.105968+00:00 | matches | 8a4e0ad4d3858960f494274adb789a346c7563e75106b35a57e87688ae92c045 |
| [K](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=80&Season=2025) | 2025 | 8/31/2025 | 2026-09-05T23:55:55.443451+00:00 | matches | 5b7e77b05b980553cddb5b6c36155ce513b9e39eac840a49a23ca33a0183583f |
| [DEF](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=99&Season=2025) | 2025 | 8/31/2025 | 2026-09-05T23:55:55.780765+00:00 | matches | e69c87c8f104dc1a2ad4059b566a60fbd2bb5aebfd08d487932cf965da2e090a |
| [QB-1](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=10&Season=2025&cur_page=1) | 2025 | 8/31/2025 | 2026-09-05T23:56:49.890886+00:00 | matches | f92349e86529f6b110b36611b95dd77d463e3c0b2d45392b82ef54fb19a61081 |
| [RB-1](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=20&Season=2025&cur_page=1) | 2025 | 8/31/2025 | 2026-09-05T23:56:50.236634+00:00 | matches | 7481d8cb510055c6244e6fcd820d5c820665dc3237d724cdab4d50684c5a4061 |
| [WR-1](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=30&Season=2025&cur_page=1) | 2025 | 8/31/2025 | 2026-09-05T23:56:50.584381+00:00 | matches | e560691bf673cec71eec030d86c2be447d070b0e61ac476307318291ef7bb138 |
| [WR-2](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=30&Season=2025&cur_page=2) | 2025 | 8/31/2025 | 2026-09-05T23:56:50.958433+00:00 | matches | 4202bc68314ee1d908a1be8895a890dc29016083a0dd6188961f3a2c114fb237 |
| [TE-1](https://www.fftoday.com/rankings/playerproj.php?LeagueID=1_1&PosID=40&Season=2025&cur_page=1) | 2025 | 8/31/2025 | 2026-09-05T23:56:51.265604+00:00 | matches | 2b73c837bb71c6a09daaadde607a7e39084e40d7423de55cc983b651ef967739 |
| [weekly-player-stats](https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.csv) | 2025 | unknown | 2026-09-05T23:57:41.641501+00:00 | matches | e5e0615b3d96a3eaebfaee91e55afb4a4e7fe0caf057454177bcd7d6ad4bcfc2 |
| [weekly-team-stats](https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2025.csv) | 2025 | unknown | 2026-09-05T23:57:41.987641+00:00 | matches | 91058a59d894855377b2f39f40c4e7bdbeef96d12144289dc68215209a1c93cb |
| [player-ids](https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv) | None | unknown | 2026-09-05T23:57:42.315643+00:00 | matches | a02b7dc2364a8b8de2bd3c91147b1dce46033f627a382161c409b29c5e7defd2 |
| yahoo-2025-settings (private league page; link removed) | 2025 | unknown | 2026-09-05T23:05:21.773Z | matches | c4dbd19eb30b0ddbe2dd6886d86dff24d60ad5ed869e99b99b360ca66ebce9e8 |

This report does not establish generalization, championship probability, other managers' maximum bids, or a causal alternate auction. For an incomplete benchmark, resolve the current input failures. Review calculation and source evidence before sharing a strategy conclusion.
