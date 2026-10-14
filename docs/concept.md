# Fantasy Football Auction Value: concept

Captured from Bo's dictated description and clarification on September 5, 2026. This is a working concept, not an agreed implementation plan.

## The problem

During Yahoo fantasy football auctions, Bo uses tools that suggest player values and adjust as the draft progresses. He has found that waiting for players priced below those values can leave him without elite players, followed by paying more for the remaining second- or third-tier options.

The central problem is pricing relative to the actual league. A player can cost more than a tool's reference value and still be the better purchase when the players left after passing are likely to cost disproportionately more for less useful production. The assistant should calculate when that premium is justified by the league's scoring, keeper supply, remaining budgets, player alternatives, and starting-lineup constraints.

The primary product hypothesis is a better league-specific valuation calculation. Complete-roster comparisons explain its recommendations. A fixed premium for all stars would not capture the conditional advantage Bo describes.

## First evidence: the 2025 league

Bo asks to compare his draft with players' production across the league. The [2025 Discount Double Check analysis](research/2025-discount-double-check-analysis.md) matches all 196 selections, including 14 keepers, to Yahoo's league-scored season totals.

His Ridley, Odunze, Hunter, and Jeudy purchases cost $53 and produced 308.40 season points combined; Puka Nacua cost $49 and produced 310.50 from one roster slot. The same draft also contains expensive disappointments and productive cheap players. These results establish a concrete case to investigate, while the premium that would have been justified on draft night still requires contemporaneous projections, available alternatives, and uncertain opponent responses.

## The product direction

Explore a companion to the fantasy platform that combines current player information, league rules, historical auction prices, manager behavior, remaining budgets, and live draft state to guide bidding and adapt a roster strategy as the room changes.

The desired first platform is Yahoo. Login management and letting friends connect their own leagues are part of the intended usable product. ESPN matters as further coverage. Monetization is a possible later direction; it is not yet a paid-launch requirement.

## Research to guide the first version

- Use the actual 2025 draft as the first benchmark for league-relative value and the cost of waiting; separate observed outcomes from advice supportable on draft night.
- Compare existing tools' valuation behavior, roster construction, dynamic pricing, inflation, and auction synchronization capabilities.
- Verify supported platform access, historical fields, live event availability, and data-use permissions.
- Test whether league and manager history adds predictive value beyond a baseline, while accounting for sparse data and changing league membership.
- Compare complete roster outcomes and decision quality, rather than rewarding individual bargains alone.
- Explore how shared use affects private strategy, recommendations, and competition within a league.

## Inputs still to establish

The 2025 league, settings, draft prices, keeper markers, and full-season player totals are verified through Yahoo's website. Original tool values and projections, weekly results through the league's Week 17 finish, the upcoming draft deadline and venue, approved API access, and initial success criteria remain open. The currently linked 2026 league lists an offline draft; the intended upcoming draft experience is not yet established.
