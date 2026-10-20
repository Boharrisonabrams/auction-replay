# Auction replay

[![CI](https://github.com/Boharrisonabrams/auction-replay/actions/workflows/ci.yml/badge.svg)](https://github.com/Boharrisonabrams/auction-replay/actions/workflows/ci.yml)

A local research tool that replays a real 14-team fantasy football auction and asks one question at every nomination and every legal price: does buying this player leave a better complete, affordable roster than passing? It uses only the Python standard library, and it reports "unresolved" when it cannot prove an answer.

## The problem

Auction value sheets price players one at a time. Bo Abrams found that waiting for players priced below those values could leave him without elite starters, then paying more for weaker players later. His 2025 league shows the pattern. Four wide receivers he bought for $53 in total scored 308.40 season points across four roster places. Puka Nacua sold earlier for $49 and scored 310.50 from one place.

That hindsight does not prove what he should have bid on draft night. A premium is justified only if, at the moment of the bid, the roster you can still complete after buying beats the roster you can complete after passing. This project builds that comparison and tests it against the actual auction.

## The method

1. **Freeze the room.** The replay charges all 14 keepers first, then processes the 182 auction sales in order. A decision sees earlier sales only. It never sees the current closing price, later prices, or later owners. Hypothetical purchases never rewrite the historical timeline.
2. **Model future prices from the past only.** Reference values are rebased to the league's budget and roster pool, then rescaled to the discretionary cash left after keepers and earlier sales. A pooled adjustment uses the median actual-to-predicted ratio of earlier sales, shrunk toward 1 by n/(n+20). Nine stress scenarios cross future-price factors 0.8, 1.0, and 1.2 with a neutral forecast, a 20% nominee forecast cut, and two nominee absences.
3. **Build buy and pass budget frontiers.** For each remaining budget, the search finds the best complete 14-player roster that fills every starting slot and pays at least $1 for every open place. Only observed holdings, and the nominee in the buy branch, are fixed.
4. **Bound the search.** A deterministic branch-and-bound subset search runs under a fixed node limit. A positional dynamic program over (player count, cost) solves a simpler problem that ignores byes. Its result gives a valid upper bound, and its rosters, rescored with the real weekly bye objective, give feasible lower bounds.
5. **Decide only on proof.** Buying is supported when the buy lower bound exceeds the pass upper bound. Passing is supported when the pass lower bound meets or exceeds the buy upper bound, so ties favor passing. Overlapping bounds stay unresolved, and a work limit is never treated as proof that no roster exists.

The tests validate the optimizer against an independent brute-force oracle. `oracle_score` and `oracle_frontier` in `tests/test_replay_auction.py` enumerate every roster and every legal lineup assignment on small pools. The tests then check that lower bound ≤ true optimum ≤ upper bound at every budget and under several search cutoffs.

## Frozen data and the no-leakage invariant

The 2025 outcomes are already known, so the main risk is hindsight leaking into "draft-time" advice. The code blocks that path in four ways:

- The auction loader accepts only transaction fields. It never reads the points or games columns.
- Source manifests must show a publisher date before the September 3, 2025 draft and a matching content hash.
- Recommendations are written and hashed (SHA-256 over auction facts, rules, accepted source manifests, search settings, implementation bytes, and every decision row) before any weekly outcome file is opened.
- `benchmark_checks` in `tests/test_replay_auction.py` asserts that the recommendation hash stays identical when weekly outcomes are permuted, when the raw auction's outcome columns change, and when Week 18 values change. If that test fails, a recommendation depended on information a manager could not have had.

## Run it

You need Python 3.11 or later. There are no dependencies to install.

To see the replay work on a made-up league, run this command from the repository root:

```sh
sh scripts/quickstart.sh
```

In a few seconds, it replays a synthetic 4-team auction with 12 nominations from [the synthetic example](examples/synthetic/README.md). For each sale, it prints the winning team's bid ceilings and its buy-versus-pass bounds at the price paid. It reads no private data. The full report and decision CSV go to `data/local/quickstart/`, which Git ignores. To use a different interpreter, set `PYTHON`, for example `PYTHON=python3.12 sh scripts/quickstart.sh`.

To run the full test suite, run this command from the repository root:

```sh
python3 -B -m unittest discover -s tests
```

The suite runs 22 tests in about 10 seconds, including one that runs the quickstart. Two tests also need Node.js, because they run the browser-side calculation code; without Node.js, those two tests are skipped. Each test file also runs on its own, for example `python3 -B tests/test_replay_auction.py`.

To run a module, put `src/` on the path:

```sh
PYTHONPATH=src python3 -B -m auction_replay.analyze_2025_draft
PYTHONPATH=src python3 -B -m auction_replay.companion_state_probe
```

Both commands work on a fresh clone. The first audits the 196-row auction CSV and prints salary bands. The second checks cash conservation at all 182 sale states. If you prefer console scripts such as `auction-replay`, run `python3 -m pip install -e .`. The modules resolve `data/local/`, `docs/research/`, and `templates/` relative to the checkout, so use an editable install, not a built wheel.

By default, the full benchmark (`auction_replay.replay_auction`), the pilots, the offline decision explorer (`build_draft_companion`), and the draft-day worksheet (`build_draft_day`) read private inputs under `data/local/`, which this repository does not include. The quickstart points the replay at the synthetic inputs instead. The replay exits 0 for a complete benchmark, 1 for a generated but incomplete benchmark, and 2 for an input or output error.

### With private inputs

If you supply your own league data, the replay's input directory (default `data/local/2025/`) holds `rules.json`, `forecasts.csv`, `reference.csv`, and `weekly.csv`. Each normalized CSV needs a matching `<name>.manifest.json`; the `replay_auction` module docstring describes the schema. Then, from the repository root:

```sh
PYTHONPATH=src python3 -B -m auction_replay.historical_price_pilot --mode joint-weekly --selection all --work-limit 2000 --relaxation-limit 20000000 --output-dir data/local/2025/joint-roster-pilot
PYTHONPATH=src python3 -B -m auction_replay.build_draft_companion --input data/local/2025/joint-roster-pilot/recommendations.json
python3 -m http.server 8766 --bind localhost --directory data/local/companion
```

Then open `http://localhost:8766/auction-replay.html` to step through every sale, test a bid, and inspect the buy and pass roster bounds. The builder rejects stale code or source hashes, incomplete snapshots, and invalid roster witnesses before it replaces the previous HTML. Every output is written to a temporary file first, so a failed run preserves the previous CSV, report, or page. In the replay's decision CSV, team and player text that starts with `=`, `+`, `-`, or `@` gets an apostrophe prefix to block spreadsheet formula injection.

## Results in Bo's league

These results come from the reports in `docs/research/`. They are honest but small: one season, already examined.

- **Full-scoring benchmark: incomplete.** The engine accounts for all 2,548 team and nomination pairs. 385 are structurally infeasible, and 2,163 lack accepted inputs: no complete league-scored forecast set, full reference prices, or verified identity crosswalk passed the source gates. See [2025 auction replay](docs/research/2025-auction-replay.md).
- **Joint roster pilot (exploratory, core offense only).** It covers all 95 of Bo's eligible nominations, nine scenarios each, and 63,729 legal-price comparisons. Buying was supported in 5.43% of price and scenario rows, passing in 36.48%, and 58.09% stayed unresolved. No supported buy exceeded the static or inflation baseline ceiling. The scenarios disagreed for 65 of the 95 nominations. The full run took 22.4 minutes. See [joint roster comparison](docs/research/2025-joint-roster-pilot.md).
- **Puka Nacua at pick 14.** The neutral case supports bids through $23 and allows bids through $57. A $50 bid, close to his actual price, stays unresolved.
- **Earlier fixed-starter pilot.** Against the inflation baseline, the roster policy chose differently at 13 of 92 comparable decisions. Its roster later scored better in 4 and worse in 9. Averaged over all 92 decisions, with matching choices counted as zero, that is -6.69 points per decision. See [historical price pilot](docs/research/2025-historical-price-pilot.md).

The bottom line: this is a tested decision explorer, and it has not shown a bidding edge. Most of the decision space near real auction prices is still unresolved, so it does not disprove premiums either.

For the 2026 draft, the project also produced a manual budget worksheet (`templates/draft-day.html`). The worksheet compares two editable 14-player plans and shows what you can afford for one player while reserving money for every other planned purchase. It is an affordability check, not a bid recommendation.

## What agents built and what Bo decided

Bo set the problem and the product direction. [The concept](docs/concept.md) is a capture of his dictated description. In [the plan](docs/plans/2026-09-05-1630-feat-league-specific-auction-replay-plan.md), his decisions are marked "user-directed" or "user-approved": the complete-roster comparison is the core of the product, and a historical replay comes before any live tool. He provided the league data and a strategy brief, approved each implementation scope and the Yahoo developer application, and confirmed his 2026 keeper.

Coding agents did the rest under that direction, using the Compound Engineering workflow: ideation (`docs/ideation/`), the unified plan with ten key technical decisions, the code, the tests, and the reports. The plan labels agent-selected defaults separately under "Assumptions". [AGENTS.md](AGENTS.md) holds the instructions Bo gave the agents: run the workflow, ask Bo for product decisions, and keep historical evaluation free of future information. Review receipts in `docs/research/*.json` record seven-persona code and document reviews. Cross-model review attempts either failed to authenticate or did not run, so the reports claim no cross-model corroboration.

## Known limitations

- **Private inputs are not included.** `data/local/` held Yahoo exports, cached forecasts, weekly statistics, generated HTML, and vendored third-party Yahoo client libraries. The pilot numbers above cannot be reproduced from a clone; the tests use synthetic fixtures plus the pseudonymized auction CSV.
- **No held-out season.** 2025 informed the model choices, so it cannot also validate them.
- **Forecast provenance is weak.** Forecast pages were retrieved in 2026 with publisher-claimed preseason dates. Nobody archived them before the draft.
- **The pilots simplify scoring.** They exclude kicker and defense points and some offensive scoring components.
- **The code is research-grade.** The replay engine is now split into focused modules, but the pilots, the decision explorer builder, and the bench study still call underscore helpers through `replay_auction`. `build_draft_day.py` packs statements onto single lines and hardcodes Bo's 2026 draft targets. There is no linter, formatter, or CI.
- **Names are pseudonymized.** The 12 named opponent teams are Team A to Team L, Bo's team is Team Bo, and one team keeps the `n/a` label that the Yahoo export recorded. SHA-256 values recorded in the reports describe the original private files.
- **Some outputs can still carry private details.** If you regenerate a report with private inputs, error messages can include absolute paths, and a `rules.json` with a `source_url` prints that league link.

## Repository map

The replay engine is in `src/auction_replay/`. To follow it, start with `inputs.py` and read the engine modules in this order. Each module uses only the modules above it.

| Engine module | What it holds | Start with |
| --- | --- | --- |
| `inputs.py` | League rules, auction pick and player records, `InputError`, and the checked parsing helpers | `LeagueRules` |
| `loaders.py` | Loaders for the rules, the auction CSV, and the normalized sources, each checked against its manifest | `load_auction`, then `validate_manifest` |
| `state.py` | The observed auction, replayed sale by sale: team budgets, rosters, and legal bid capacity | `replay_states`, then `legal_capacity` |
| `pricing.py` | Reference, inflation, and future prices, built from earlier sales only | `replay_markets` |
| `search.py` | Roster bounds for every budget, and the buy-versus-pass comparison at each legal price | `compare_nominee`, then `completion_frontier` |
| `decisions.py` | One decision row per team, nomination, legal price, and scenario, and scoring for frozen rosters | `decision_rows` |
| `benchmark.py` | The full run: freeze and hash the recommendations, evaluate them, and write the CSV and report | `run_benchmark` |
| `replay_auction.py` | The command-line entry point and the original import path, which re-exports every engine name | The module docstring, which describes the input files |

The package's `__all__` lists the engine's public names, so `from auction_replay import compare_nominee` works.

| Other path | Contents |
| --- | --- |
| `src/auction_replay/historical_price_pilot.py` | The exploratory 2025 price pilots, in fixed-starter and joint-weekly modes |
| `src/auction_replay/build_draft_companion.py` | The builder for the offline decision explorer |
| `src/auction_replay/bench_coverage.py` | A study of affordable bye coverage from frozen roster seeds |
| `src/auction_replay/build_draft_day.py` | The builder for the draft-day budget worksheet |
| `src/auction_replay/import_yahoo_snapshot.py` | The offline importer for saved Yahoo settings and draft results |
| `src/auction_replay/analyze_2025_draft.py` | An audit of the 196-row auction CSV that prints salary bands |
| `src/auction_replay/companion_state_probe.py` | A check, at all 182 sale states, of cash conservation and of accepted purchases that the optimizer's roster policy rejects |
| `tests/` | Standard-library checks, including the brute-force oracle and the no-leakage test |
| `templates/` | HTML templates for the decision explorer and the draft-day worksheet |
| `examples/synthetic/` | A made-up 4-team league that the quickstart replays |
| `scripts/` | The quickstart script and the summary it prints |
| `docs/research/` | Reports, the pseudonymized 2025 auction CSV, and review receipts |
| `docs/plans/`, `docs/ideation/`, `docs/concept.md` | Problem statement, ideation, and the unified plan |

This public copy moved code out of `docs/research/` into `src/` and `tests/`, and the Markdown reports point to the new paths. The JSON review receipts keep the original paths as historical records. Three research files stay private because they record signed-in third-party account details.

## License

[MIT](LICENSE), copyright 2026 Bo Abrams.
