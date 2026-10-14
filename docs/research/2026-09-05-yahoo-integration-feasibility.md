# Yahoo integration feasibility

Research date: September 5, 2026. Status: documentation checked; authenticated access and response fields remain untested. This note supplements the local replay plan.

## Documented access

Yahoo documents OAuth 2.0, league settings, teams, draft results, and player points in league context. Private league access requires membership; public leagues are accessible. League discovery is documented for the signed-in user. See [Yahoo's API documentation](https://sports.yahoo.com/developer/docs/).

The [current access application](https://sports.yahoo.com/developer/access/) requires Yahoo review and specifies read-only access. New applicants can omit the client ID; Yahoo says access is provisioned after approval. Application approval and user authorization are separate steps.

## Questions for the first authenticated import

- Does this league's historical draft response include auction cost, selection order, and keeper information? Compare returned fields with the existing auction CSV before accepting them.
- Which prior seasons remain accessible?
- Do manager identifiers support reliable matching across accessible leagues? Do not join managers by display name alone.
- Which budget and keeper rules need explicit confirmation because the response omits them?

The documentation describes completed draft results. It does not establish a supported bid-by-bid history or live bid stream. Losing bids, maximum willingness to pay, and nomination behavior remain unverified.

## First integration outcome

Proposed scope: connect Bo's account, select one league and season, and import enough data to validate the existing replay inputs.

1. Establish whether an approved Fantasy API application exists. If it does not, prepare the access application using the product description below and Bo's applicant details.
2. Configure the approved application's OAuth flow. Bo signs in on Yahoo and selects which leagues the assistant imports.
3. Preserve the returned season, league, and provider identities with retrieval timestamps in ignored local data. Keep tokens out of source files, reports, and logs.
4. Compare imported scoring and roster rules against the saved 2025 rules. Reconcile draft selections, salaries, and keepers against the existing 196-row auction data, recording unavailable fields explicitly.
5. Reconcile weekly outcomes under the imported scoring rules. Keep those outcomes separate from information available before the draft.

Success means one authenticated import reconciles with known league data or identifies exact discrepancies. A successful login alone does not establish this outcome. Historical pre-draft projections remain a separate input.

## Submitted application

Bo submitted a personal, noncommercial Yahoo Developer access application on September 5, 2026, after explicitly approving the submission. It requested read-only access to settings, teams, rosters, available historical draft results, and league-scored player statistics for leagues he belongs to, for one initial user. API access remained pending review when this note was written; no credentials or authenticated league import existed. Invited friends or commercial distribution are later scope decisions.

Public copy: the applicant details, form text, and contact information are omitted.

## Modeling and workflow decisions

Use managers' history only from accessible leagues. Before combining seasons or leagues, normalize budget, scoring, roster size, and keeper effects, verify manager matches, and reduce the influence of sparse history. Completed purchases can support spending-pattern estimates; they cannot reveal every bid a manager considered.

Compound Engineering's next implementation stage is `ce-plan` for this import outcome, followed by `ce-work` and security-focused review of authorization and token handling. A new ideation round is unnecessary. The existing replay work can continue while Yahoo access is established.

Bo subsequently authorized evaluating existing clients and preparing the offline importer. The [client evaluation](2026-09-05-yahoo-client-evaluation.md) records the completed source inspection and offline checks. The authenticated portion above remains separate; no credentials or OAuth flow have been configured.

## Gemini brief: integration implications

Reviewed September 5, 2026. These findings refine research assumptions; they do not establish a working extension or change the approved replay implementation scope.

- **An overlay is a viable product form to investigate.** [FantasyPros documents a side assistant](https://support.fantasypros.com/hc/en-us/articles/8280035814683-What-is-the-Browser-Extension-Side-Assistant-and-which-host-sites-support-it) for Yahoo salary-cap drafts. That is evidence for the experience, not proof of our access permissions or its internal ingestion method.
- **Read-only does not establish permission to scrape.** [Yahoo's terms, section 3](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html?ncid=mbr_idnedulnk00000001), require prior permission for automated collection. Verify the permission covering the proposed integration; do not treat the absence of automated bidding as a compliance guarantee.
- **WebSocket capture needs a separate feasibility check.** Chrome [content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts) run in an isolated JavaScript environment. Its [webRequest API](https://developer.chrome.com/docs/extensions/reference/api/webRequest) observes the WebSocket handshake, not individual messages. A DOM observer does not grant socket-frame access. Yahoo's actual transport, available fields, startup order, and reconnection behavior remain uninspected.
- **Separate pre-draft sync from live events.** Approved API access remains the proposed route for settings and history. Reading the currently visible draft cannot supply arbitrary historical leagues. The cited [FantasyFootballAnalyzer README](https://github.com/Krool/FantasyFootballAnalyzer) describes Yahoo OAuth functions and specifically identifies Sleeper for live pick sync; its broad platform list does not prove Yahoo live-auction ingestion.
- **Measure timing and freshness.** [Yahoo's salary-cap guide](https://help.yahoo.com/kb/live-salary-cap%C2%A0draft-sln6530.html) documents a default 20-second offer period and a reset to 10 seconds. Verify the actual room settings. The brief's sub-100-millisecond target is a proposed performance goal, not measured capability. Yahoo [describes throttling](https://sports.yahoo.com/developer/), but that does not establish the brief's exact two-second polling threshold.
- **Keep the sharing decision open.** The existing direction shares the valuation engine with private account context. Gemini's proposal to give friends tracking only is a different product choice. Code delivered in a friend's extension package should be treated as inspectable; compilation does not make that code a secret.

Proposed follow-up: prove one permitted ingestion route, then a small companion that distinguishes expected market price, the roster-based bid ceiling, and legal bid capacity. Keep settled sales separate from active bids; detect duplicates, missed events, corrections, reconnects, and stale state. Suppress recommendations when the state is unreliable and support manual reconciliation. Measure ingestion-to-display latency separately from optimizer runtime; preserve unresolved search bounds when a fast answer is unavailable. An in-room HUD can follow once those behaviors are demonstrated.
