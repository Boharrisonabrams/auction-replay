# Draft-day decision

Use Draft Sharks as the main draft tool. The new local worksheet can check whether a specific premium purchase leaves an affordable complete roster. Freeze the unproven automated bidding model for this draft.

The worksheet is technically tested, but the example plans are not a confirmed draft strategy. Before using them, confirm the $200 budget and 14 paid roster places, enter all shared keepers/purchases, and replace unavailable targets. Caleb Williams at $1 is the only confirmed holding.

## Use it

Open `http://localhost:8766/draft-day.html` beside the actual Draft Sharks board. Choose the Plan A slot, enter a bid, and compare both rosters. Stress other future prices before trusting the available cash. Record your purchase once; it then appears at the actual price in both plans. Mark sold alternatives unavailable and replace them. Download a backup after material changes.

After a computer restart, run this from the repository directory, then reopen the URL:

```sh
python3 -m http.server 8766 --bind localhost --directory data/local/companion
```

The worksheet is also saved in `data/local/companion/draft-day.html`. Testing used the localhost URL; automated navigation to a file URL was blocked by browser policy and was not bypassed. Browser storage and downloaded backups preserve the edited roster. Reload and Undo clear old quotes and readiness confirmation.

## Evidence and limits

- Fresh user-exported Draft Sharks projections contain 1,067 supported-position players. DS Proj comes from Bo's actual league board; example Market $ references come from a separate synthetic rehearsal board. Their combined source hash is `4184e01c59730934e5fd4d4b16f13d3c877f586d95077eb76207af51f12b6ac6`.
- The actual league board displayed 13 teams, snake format, and sync off on September 7. The export had projections but no auction-dollar columns. Final room configuration and opponent keepers remain unconfirmed.
- The example Gibbs-at-$78 plan costs $194; its alternative costs $183. Their starting-offense projections are essentially tied. The $84 budget ceiling falls to $55 with other future prices stressed 20%. These illustrate affordability, not an optimal bid or a proved strategy edge.
- The worksheet has no live feed. It does not infer a current premium from historical outcomes or translate 3D Value into dollars. Its seven-starter projection sum omits weekly lineup decisions, waivers, and win probability; K/DEF projections are excluded because full scoring parity is unverified.

## Verification

Portable checks pass for money/slot arithmetic, position validity, duplicates, unavailable players, malformed exports, shared purchases, and backup adoption. Recovery checks reject invalid candidates before replacing the current state, retain purchases, and clear stale quotes/confirmation. Script syntax checks pass.

Actual browser checks passed for premium-price stress, missing the premium RB, an unexpected shared purchase, invalid-input recovery, downloaded backup restoration, rejected-backup preservation, reload, Undo, owned-field locks, and enabled restore controls after success/rejection. Final browser logs contained no errors or warnings. Removed a pinned summary panel after it obscured action buttons during the expanded-quote test. The final worksheet has only Caleb recorded as owned; synthetic test purchases are cleared.

The [Compound Engineering review](2026-09-07-draft-day-code-review.json) retains four original P2 findings and a verification addendum resolving all four. A local adversarial pass covered the untracked source; no cross-model code transfer occurred. The follow-up verified the final source hashes and found no remaining concrete defects within that scope. This does not establish forecast accuracy or a live provider connection.

Implementation remains local and uncommitted. Private exports/generated data remain ignored; six preexisting research files were preserved. No provider settings, real draft state, GitHub, or Git history changed. Compound learning documentation was skipped because the recovery rules and their verification are recoverable from the final code, tests, and this receipt.
