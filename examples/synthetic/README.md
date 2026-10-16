# Synthetic quickstart league

This folder holds a made-up league that is small enough to replay in a few seconds. Every player, team, and source in it is invented. It contains no real league, no real person, and no Yahoo or Draft Sharks data. Use it to see the replay work before you supply your own inputs.

To replay it, run `sh scripts/quickstart.sh` from the repository root.

## The league

- Four teams: Team Red, Team Blue, Team Green, and Team Gold. Each has a $30 budget and a 5-player roster.
- The starters are one QB, one RB, one WR, and one FLEX (RB, WR, or TE). The fifth place is a bench place.
- Each team keeps two players before the auction. Then 12 players sell in order, so 20 of the 25 players are drafted.
- The letter in a player's name shows the position group: A is QB, B is RB, C is WR, and D is TE. A lower number means a higher projection.
- The season runs from Week 1 to Week 17. Byes fall in Weeks 6 to 11. NFL team codes such as `AAA` are placeholders.

## Files

| File | What it holds |
| --- | --- |
| `auction.csv` | The 20 picks in order, 12 auction sales and then 8 keepers, with transaction fields only and no outcome columns. |
| `rules.json` | The league rules: season, draft time, team count, budget, roster size, starters, weeks, and a complete made-up scoring table. |
| `forecasts.csv` | Preseason projections for all 25 players, including the 5 that nobody drafts, with position, team code, bye week, and projected season points. |
| `forecasts.manifest.json` | The source record for `forecasts.csv`: a placeholder URL, dates before the draft, the CSV's SHA-256, the scoring coverage and hash, and the player ID mappings. |
| `reference.csv` | Made-up preseason dollar values from an imaginary 10-team league, which the replay rebases to this league's budgets and rosters. |
| `reference.manifest.json` | The source record for `reference.csv`, which describes the source's own format instead of this league's scoring. |
| `weekly.csv` | Made-up points for every player in every week, which the replay opens only after it freezes and hashes its recommendations. |
| `weekly.manifest.json` | The source record for `weekly.csv`, dated after the season. |
| `.gitattributes` | A setting that stops Git from changing CSV line endings, because a changed byte breaks the manifest hashes. |

## How the numbers were made

- Projections and reference values were picked by hand to spread from star to replacement level.
- Each weekly score is the player's projection divided by 17, times a fixed multiplier from 0.6 to 1.4 that shifts by week and player, rounded to one decimal place. A bye week scores 0.
- Salaries were picked by hand so that every team fills all 5 places within its $30 budget.

## What to look for

These results use the neutral scenario at the 1.0 future-price factor, as the quickstart tables do. The "Scenarios" column in the first table shows how far the proven ceiling moves across all nine scenarios.

- Player B1, the top RB, sells first for $12. For the winner, Team Blue, buying is proven better than passing at every bid up to $14.
- Player A1, the top QB, sells for $9. For the winner, Team Red, buying is proven only up to $7, so passing wins at the price paid.
- Player D1, the top TE, sells for $10. For the winner, Team Gold, passing wins at every legal bid.

## If you edit a file

The replay rejects a CSV whose bytes do not match the `sha256` in its manifest. After you edit a CSV, recompute its hash with `shasum -a 256` (or `sha256sum` on Linux) and update the manifest. If you change the scoring in `rules.json`, also update `scoring_coverage` and `scoring_hash` in the forecast and weekly manifests. To print the new scoring hash, run this command from the repository root:

```sh
PYTHONPATH=src python3 -B -c 'from auction_replay.replay_auction import load_rules, scoring_hash; print(scoring_hash(load_rules("examples/synthetic/rules.json")))'
```

The auction must still give every team exactly 5 players within its budget, and every drafted player must appear in `forecasts.csv` and `reference.csv`.
