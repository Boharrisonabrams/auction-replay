# Yahoo client evaluation

## Decision

Use the existing `yahoo_fantasy_api` client as the first candidate for authenticated imports. Its raw settings and draft-results methods cover the first data boundary. The new [offline importer](../../src/auction_replay/import_yahoo_snapshot.py) consumes those raw responses without requiring the package to be installed. Keep that boundary independent of the chosen client so changing the transport does not change the replay engine.

This is enough to prepare settings and completed-auction imports. It is not an access workaround or a complete valuation dataset. Yahoo approval, account authorization, and verification against Bo's actual league remain outstanding.

## Sources inspected

Default-branch commits checked on September 5, 2026. Repository activity timestamps include branches other than the default; they are not release dates.

| Client | Source revision | Findings |
| --- | --- | --- |
| [yahoo_fantasy_api](https://github.com/spilchen/yahoo_fantasy_api/tree/c9f4fef444a521022579ba38e4721f0a780f66c6) | `c9f4fef`, April 3, 2026; MIT | `YHandler.get_settings_raw` and `get_draftresults_raw` retain the raw response. The public `League.draft_results()` method documents auction cost and transforms the player key into a numeric player ID. Prefer raw responses to retain the full season-specific key. |
| [YFPY](https://github.com/uberfastman/yfpy/tree/5287b2d68d33d0f03f24eea70c179ae27aedc99c) | `5287b2d`, September 14, 2025; GPL-3.0 | Settings, history, and draft queries exist. `DraftResult` models cost, pick, round, team key, and player key, but has no keeper field. Its serializer emits modeled attributes, so an extra field in the source response can disappear from a saved object. |
| [Node client](https://github.com/whatadewitt/yahoo-fantasy-sports-api/tree/ef2cb692509a37cecfc8e9c8f1c0a0fac32a786f) | `ef2cb69`, April 19, 2024; MIT | Alternative for a future JavaScript application. Source and maintenance metadata inspected; runtime not tested. No reason to change this project's Python implementation for the initial import. |

YFPY remains an option for private use. Its GPL license does not require publishing private modifications, but distribution needs a separate license assessment. The MIT client is a simpler default for possible future distribution. See the [GNU license FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#GPLRequireSourcePostedPublic). No third-party library source was copied into the project implementation, and no dependency was installed.

## Evidence and limits

- **Source support:** The MIT client's [draft method](https://github.com/spilchen/yahoo_fantasy_api/blob/c9f4fef444a521022579ba38e4721f0a780f66c6/yahoo_fantasy_api/league.py#L731) documents completed purchases and their costs. It explicitly excludes the currently nominated player. This is library documentation, not a measured Yahoo live-feed capability.
- **Offline execution:** Loaded the pinned upstream `YHandler` implementation with a synthetic saved-response HTTP session. Its actual settings and draft methods generated the expected URLs, and both responses passed through the new importer. Socket creation was prohibited. Two sample purchases retained costs of $70 and $0; keeper status remained unknown. This tests client-to-parser compatibility, not Yahoo authorization or current response availability.
- **Fixture warning:** The MIT repository's sample draft filename names one league key, but its embedded metadata names a different one. Both downloaded samples are NHL examples. Never infer league identity or NFL compatibility from a filename. Local copies retain only required metadata; the original sample is not treated as Bo's data.
- **YFPY offline mode:** Its cache loader requires previously saved files. Query construction checks consumer credentials before reaching its offline authentication branch. Offline mode cannot recover league data that was never obtained.
- **Current access:** YFPY has open reports of [application authorization failures](https://github.com/uberfastman/yfpy/issues/84) and [continued denial after reported approval](https://github.com/uberfastman/yfpy/issues/85). These are reporter observations, not a diagnosis of Bo's account. Follow [Yahoo's current application process](https://sports.yahoo.com/developer/), then verify a real read.

The source downloads, synthetic samples, and offline execution receipt are under ignored `data/local/yahoo-client-evaluation/`. Do not publish raw account responses or credentials with code.

## Import contract

The importer accepts two raw JSON objects from the settings and draft-results endpoints, each with a `fantasy_content.league` envelope containing metadata. It does not accept YFPY's serialized `Settings` or `DraftResult` objects. If YFPY is selected later, retain raw responses before its model serialization.

- Require the same explicit game/league key, season, team count, NFL game code, and completed-draft status in both responses.
- Validate auction format, roster counts, scoring modifiers, collection count, unique player keys, pick sequence, and team-key namespace.
- Reject duplicate JSON object keys before parsing can silently replace a purchase or setting.
- Preserve missing costs as `null`, distinct from $0. Report the sum of known costs and missing-cost count separately.
- Leave keeper status unknown. Do not infer a keeper from a $0 cost or its location in the draft table.
- Show scoring IDs and coefficients for inspection. Mark bonus-bearing rules and unmapped categories, and keep `scoring_complete: false` until mapping and reconciliation are done.
- Compare player IDs, pick order, and prices with an optional historical CSV. Ownership, keepers, and rule equivalence remain separate checks. Do not read realized points as recommendation inputs.
- Label samples explicitly. `yahoo-cache` is a caller-supplied source label, not proof of authentication. Every snapshot retains `authenticated_access_verified: false` and `replay_ready: false`.
- Hash the exact source bytes parsed, record the supplied capture timestamp, and replace the output only after successful parsing and rendering. A successful exit means the inspection snapshot was written; it does not mean prices match, scoring is accepted, or the benchmark is complete.
- Keep success-status printing outside the failure path: losing the status pipe after saving must not claim that an old snapshot was preserved.

The importer does not create accepted `rules.json`, forecast files, or weekly-outcome files. That prevents a preliminary snapshot from silently entering the valuation engine.

## Run the checks

Run the synthetic parser and file-preservation checks:

```sh
python3 -B tests/test_import_yahoo_snapshot.py
```

Inspect the sample snapshot using the locally prepared example files:

```sh
PYTHONPATH=src python3 -B -m auction_replay.import_yahoo_snapshot --settings data/local/yahoo-client-evaluation/sample-settings.json --draft data/local/yahoo-client-evaluation/sample-draft.json --league-key 999.l.123 --season 2025 --source-kind sample --captured-at 2026-09-05T00:00:00Z --output data/local/yahoo-client-evaluation/sample-import.json
```

These are synthetic IDs and a synthetic timestamp. For real cached responses, use their actual league key, season, capture timestamp, and `--source-kind yahoo-cache`; optionally add `--expected-auction docs/research/2025-discount-double-check-auction.csv`. Keep output under ignored `data/local/`, and create the destination directory first.

## Validation result

Synthetic importer checks and the existing replay checks passed locally. The completed Compound Engineering review (`yahoo-20260905-01`) found two defects in the initial snapshot: duplicate raw JSON keys were silently overwritten, and a failed status print could incorrectly report preservation after saving. Both are fixed, with regression checks that failed before the fixes and passed afterward. Reconciliation mismatch and excess-team checks were also added. `git diff --check` passed.

Seven local review lenses completed. External cross-model corroboration was unavailable because both review-provider routes failed authentication; a local adversarial review and independent finding validation completed instead. This limitation concerns review providers, not Yahoo access. All project changes remain local and uncommitted.

## Next authenticated check

After Yahoo provisions access, configure authorization under a separate security review and obtain one settings response and one completed draft response. Run this importer against the 2025 reference CSV. Resolve discrepancies and verify ownership, keeper deductions, budget, and scoring before promoting any imported data into the replay. Pre-draft projections and weekly outcomes remain separate work even if the Yahoo client supplies every requested field.
