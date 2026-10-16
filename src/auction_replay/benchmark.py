"""Run the full benchmark and write its decision CSV and report.

run_benchmark hashes the recommendations before it opens any weekly outcome file.
main is the command-line entry point that replay_auction runs.
"""

import argparse
import csv
import hashlib
import json
import shlex
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryFile
from unicodedata import category

from .decisions import (
    DECISION_FIELDS,
    EVALUATION_FIELDS,
    canonical_bytes,
    decision_rows,
    evaluate_roster,
)
from .inputs import InputError
from .inputs import integer as _integer
from .inputs import json_object as _json
from .loaders import (
    load_auction,
    load_forecasts,
    load_reference_values,
    load_rules,
    load_weekly_outcomes,
    scoring_hash,
)
from .pricing import _validate_auction_forecasts
from .state import final_state, missing_starters


def _cell(value, field=None):
    if field in {"team", "player_id", "player_name"} and isinstance(value, str):
        first = next(
            (char for char in value if not char.isspace() and category(char) not in {"Cc", "Cf"}),
            "",
        )
        if first in {"=", "+", "-", "@"}:
            return "'" + value
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, bool)):
        return canonical_bytes(value).decode()
    return str(value)


def _file_hash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _json_list(path):
    try:
        result = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise InputError(f"unreadable list {path}: {error}") from None
    if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
        raise InputError(f"expected a list of objects: {path}")
    return result


def run_benchmark(auction_path, input_dir, report_path, csv_path, work_limit=2000):
    """Freeze recommendations, load outcomes, and generate both files before publishing."""
    input_dir, report_path, csv_path = Path(input_dir), Path(report_path), Path(csv_path)
    work_limit = _integer(work_limit, "search work limit", 1)
    input_paths = {
        Path(auction_path).resolve(),
        (input_dir / "rules.json").resolve(),
        Path(__file__).resolve(),
    }
    input_paths.update(
        (input_dir / (name + suffix)).resolve()
        for name in ("forecasts", "reference", "weekly")
        for suffix in (".csv", ".manifest.json")
    )
    if (
        report_path.resolve() == csv_path.resolve()
        or {report_path.resolve(), csv_path.resolve()} & input_paths
    ):
        raise InputError("output paths must be distinct and cannot overwrite input files")
    rules = load_rules(input_dir / "rules.json", require_scoring=False)
    picks = load_auction(auction_path, rules)
    gaps, provenance = [], {}
    players = references = None
    try:
        scored_rules = load_rules(input_dir / "rules.json")
        forecast_manifest = _json(input_dir / "forecasts.manifest.json")
        forecasts = load_forecasts(
            input_dir / "forecasts.csv",
            forecast_manifest,
            scored_rules,
            {pick.player_id for pick in picks},
        )
        _validate_auction_forecasts(picks, forecasts)
        players = forecasts
        provenance["forecasts"] = forecast_manifest
        reference_manifest = _json(input_dir / "reference.manifest.json")
        references = load_reference_values(
            input_dir / "reference.csv", reference_manifest, scored_rules, players
        )
        provenance["reference"] = reference_manifest
    except InputError as error:
        gaps.append(str(error))
    metadata = dict(
        rules=asdict(rules),
        auction=[asdict(pick) for pick in picks],
        preseason_sources=provenance,
        work_limit=work_limit,
        implementation_sha256=_file_hash(__file__),
        policy_input_gaps=gaps,
    )
    recommendation_hash = hashlib.sha256(canonical_bytes(metadata) + b"\n")
    row_counts: dict[str, Counter[str]]
    pair_summaries, row_counts = (
        {},
        {policy: Counter() for policy in ("static", "inflation", "roster")},
    )
    reason_counts: Counter[str] = Counter()
    evaluated_unknown = {"fixed_preseason": 0, "optimistic_hindsight": 0}
    final = final_state(picks, rules)
    frozen_actual = tuple((team.name, tuple(team.roster)) for team in final.teams)
    with TemporaryFile(mode="w+t", encoding="utf-8") as frozen, ExitStack() as pending:
        for row in decision_rows(picks, rules, players, references, gaps, work_limit):
            payload = canonical_bytes(row)
            recommendation_hash.update(payload + b"\n")
            frozen.write(payload.decode() + "\n")
            pair = (row["pick"], row["team"])
            if pair not in pair_summaries:
                pair_summaries[pair] = {
                    key: value
                    for key, value in row.items()
                    if key
                    in {
                        "pick",
                        "player_id",
                        "player_name",
                        "team",
                        "budget",
                        "reason",
                        "neutral_supported_ceiling",
                        "neutral_possible_ceiling",
                        "scenario_supported_min",
                        "scenario_supported_max",
                        "scenario_possible_min",
                        "scenario_possible_max",
                        "scenario_disagreement",
                    }
                }
                pair_summaries[pair]["actions"] = set()
                reason_counts[row["reason"]] += 1
            pair_summaries[pair]["actions"].add(row["roster_action"])
            for policy, counts in row_counts.items():
                counts[row[policy + "_action"]] += 1
        # No weekly file, manifest, or realized-point hash is read before this boundary.
        frozen.flush()
        frozen.seek(0)
        digest = recommendation_hash.hexdigest()
        outcomes, outcome_gap, outcome_source = {}, None, None
        if players is not None and rules.scoring:
            try:
                outcome_source = _json(input_dir / "weekly.manifest.json")
                outcomes = load_weekly_outcomes(
                    input_dir / "weekly.csv", outcome_source, rules, players
                )
            except InputError as error:
                outcome_gap = str(error)
        else:
            outcome_gap = (
                "accepted forecasts are unavailable for weekly evaluation"
                if rules.scoring
                else "complete league scoring and accepted forecasts are unavailable for weekly evaluation"
            )

        @lru_cache(maxsize=512)
        def evaluated(roster):
            return evaluate_roster(roster, players, rules, outcomes)

        for path in (report_path, csv_path):
            path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=csv_path.parent,
            prefix=f".{csv_path.name}.",
            delete=False,
        ) as target:
            staged_csv = Path(target.name)
            pending.callback(staged_csv.unlink, missing_ok=True)
            writer = csv.DictWriter(target, fieldnames=DECISION_FIELDS + EVALUATION_FIELDS)
            writer.writeheader()
            for line in frozen:
                row = json.loads(line)
                for branch in ("buy", "pass"):
                    roster = row.get(branch + "_roster")
                    if roster is not None:
                        evaluation = evaluated(tuple(roster))
                        row[branch + "_evaluation"] = evaluation
                        for method in evaluated_unknown:
                            if evaluation[method + "_total"] is None:
                                evaluated_unknown[method] += 1
                writer.writerow({key: _cell(value, key) for key, value in row.items()})
        actual_evaluations = (
            {name: evaluated(roster) for name, roster in frozen_actual} if players else {}
        )
        pair_counts: Counter[str] = Counter()
        for pair in pair_summaries.values():
            actions = pair["actions"]
            # A mixed grid remains inspectable in row counts and CSV. This hierarchy
            # labels each pair once and never treats prices as independent seasons.
            pair["disposition"] = next(
                action
                for action in (
                    "missing-data",
                    "search-unresolved",
                    "supported",
                    "pass",
                    "infeasible",
                )
                if action in actions
            )
            pair_counts[pair["disposition"]] += 1
        actual_unknown = sum(
            value["fixed_preseason_total"] is None or value["optimistic_hindsight_total"] is None
            for value in actual_evaluations.values()
        )
        complete = (
            not gaps
            and outcome_gap is None
            and not any(
                counts["missing-data"] or counts["search-unresolved"]
                for counts in row_counts.values()
            )
            and not any(evaluated_unknown.values())
            and not actual_unknown
        )
        summary = dict(
            benchmark_complete=complete,
            pair_count=len(pair_summaries),
            evaluated_pair_count=sum(
                "neutral_supported_ceiling" in pair for pair in pair_summaries.values()
            ),
            pair_dispositions=dict(sorted(pair_counts.items())),
            row_dispositions={
                key: dict(sorted(value.items())) for key, value in row_counts.items()
            },
            recommendation_sha256=digest,
            csv_sha256=_file_hash(staged_csv),
            work_limit=work_limit,
            scenario_disagreement_pairs=sum(
                bool(pair.get("scenario_disagreement")) for pair in pair_summaries.values()
            ),
            unknown_evaluation_branch_rows=evaluated_unknown,
        )
        report = _render_report(
            report_path,
            csv_path,
            input_dir,
            auction_path,
            picks,
            rules,
            final,
            summary,
            pair_summaries,
            reason_counts,
            gaps,
            provenance,
            outcome_gap,
            outcome_source,
            actual_evaluations,
        )
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=report_path.parent,
            prefix=f".{report_path.name}.",
            delete=False,
        ) as target:
            staged_report = Path(target.name)
            pending.callback(staged_report.unlink, missing_ok=True)
            target.write(report)
        staged_csv.replace(csv_path)
        staged_report.replace(report_path)
        return summary


def _render_report(
    report_path,
    csv_path,
    input_dir,
    auction_path,
    picks,
    rules,
    final,
    summary,
    pairs,
    reasons,
    gaps,
    provenance,
    outcome_gap,
    outcome_source,
    actual_evaluations,
):
    def table(headers, rows):
        clean = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
        return [
            "| " + " | ".join(map(clean, headers)) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ] + ["| " + " | ".join(map(clean, row)) + " |" for row in rows]

    project = Path(__file__).resolve().parents[2]

    def shown(path):
        # Paths inside the checkout stay repository-relative, so reports carry no machine paths.
        path = Path(path).resolve()
        return str(path.relative_to(project)) if path.is_relative_to(project) else str(path)

    command = (
        f"PYTHONPATH=src python3 -B -m auction_replay.replay_auction "
        f"--auction {shlex.quote(shown(auction_path))} --input-dir {shlex.quote(shown(input_dir))} "
        f"--report {shlex.quote(shown(report_path))} --csv {shlex.quote(shown(csv_path))} "
        f"--work-limit {summary['work_limit']}"
    )
    lines = [
        f"# {rules.season} auction replay",
        "",
        f"**Benchmark {'COMPLETE' if summary['benchmark_complete'] else 'INCOMPLETE'}**: `benchmark_complete: {str(summary['benchmark_complete']).lower()}`.",
        "",
        "This local report separates observed auction facts, conditional draft-time recommendations, and later evaluation. "
        "A partial report or a synthetic calculation proof cannot establish a premium strategy for this league.",
        "",
        "## Reproduce the report",
        "",
        f"To regenerate these artifacts, run `{command}` from the repository root. Exit 0 means complete, 1 means a generated incomplete benchmark, and 2 means an input/output error.",
        "",
        "To run the calculation checks, use `python3 -B tests/test_replay_auction.py` from the repository root.",
        "",
        f"The machine-readable CSV is `{csv_path.name}` under `{shown(csv_path.parent)}`. It contains every team/nomination pair: "
        "one row per legal price and scenario when inputs are valid, or one blank-price row for a blocked pair.",
        "",
        "## Coverage and observed auction",
        "",
        f"{len(picks)} selections; {sum(not pick.keeper for pick in picks)} auction nominations; {rules.teams} teams; "
        f"{summary['pair_count']} team/nomination pairs. Total spend ${sum(p.salary for p in picks):,}; "
        f"keeper commitments ${sum(p.salary for p in picks if p.keeper):,}; remaining cash ${sum(t.budget for t in final.teams):,}.",
        "",
    ]
    rule_source = _json(input_dir / "rules.json")
    lines += [
        (
            f"The captured league rules declare {len(rules.scoring)} enabled scoring categories; "
            f"scoring SHA-256 `{scoring_hash(rules)}`."
            if rules.scoring
            else "Only structural rules are accepted; complete scoring is unavailable."
        ),
        "",
    ]
    if rule_source.get("source_url"):
        lines += [
            f"[League settings]({rule_source['source_url']}); captured {rule_source.get('source_captured_at', 'date unavailable')}; "
            f"source SHA-256 `{rule_source.get('source_sha256', 'unavailable')}`.",
            "",
        ]
    dispositions = ("supported", "pass", "infeasible", "missing-data", "search-unresolved")
    lines += table(
        ("Disposition", "Pairs", "Static rows", "Inflation rows", "Roster rows"),
        [
            (
                name,
                summary["pair_dispositions"].get(name, 0),
                *(
                    summary["row_dispositions"][policy].get(name, 0)
                    for policy in ("static", "inflation", "roster")
                ),
            )
            for name in dispositions
        ],
    )
    lines += [
        "",
        "Each pair receives one summary label: missing-data, then search-unresolved, supported, pass, or infeasible. "
        "The CSV retains mixed actions across prices. Rows and overlapping branches are not independent samples or additive seasons.",
        "",
    ]
    if reasons.get("full roster") or reasons.get("insufficient starter slots after purchase"):
        lines += [
            f"Structural rejection: {reasons['full roster']} pairs have a full roster; "
            f"{reasons['insufficient starter slots after purchase']} purchases leave too few starter slots. "
            "These proofs use observed holdings only. Missing forecasts never shrink the unknown eligible future universe.",
            "",
        ]
    positions = {pick.player_id: pick for pick in picks}
    lines += table(
        ("Team", "Spent", "Roster", "Unfilled starting positions", "Pair dispositions"),
        [
            (
                team.name,
                f"${rules.budget - team.budget}",
                len(team.roster),
                "missing " + ", ".join(missing_starters(team.roster, positions, rules))
                if missing_starters(team.roster, positions, rules)
                else "none",
                ", ".join(
                    f"{key}: {value}"
                    for key, value in sorted(
                        Counter(
                            pair["disposition"]
                            for pair in pairs.values()
                            if pair["team"] == team.name
                        ).items()
                    )
                ),
            )
            for team in final.teams
        ],
    )
    lines += [
        "",
        "Actual holdings remain unchanged, including missing starters. The evaluator adds no replacement player, refund, waiver, or injury substitution.",
        "",
        "## Evidence blockers",
        "",
    ]
    for gap in gaps:
        lines += [f"- Policy input: {gap}"]
    if outcome_gap:
        lines += [f"- Weekly evaluation: {outcome_gap}"]
    notes_path = input_dir / "input-gaps.json"
    if notes_path.exists():
        lines += [
            "",
            "Collection notes below record source research. Current loader failures appear above; these notes may be stale "
            "after you supply accepted normalized files and do not override their validation results.",
            "",
        ]
        for note in _json_list(notes_path):
            lines += [
                f"- **{note.get('code', 'source gap')}** ({note.get('affects', 'coverage')}): {note.get('details', '')} "
                f"[Required source]({note.get('source', '')})."
            ]
    if not gaps and not outcome_gap:
        lines += [
            "Accepted normalized files pass season, pre-draft date, hash, scoring-coverage, coefficient, identity, and undrafted-universe gates. "
            "Source declarations still require collection review; they do not establish untouched historical archives."
        ]
    lines += [
        "",
        "## Policies, scenarios, and search bounds",
        "",
        "Static values rebase source excess dollars above $1 to the league's budget and roster pool. Inflation rescales remaining "
        "discretionary dollars. Future prices use only earlier auction sales, with a median sale-to-prediction ratio shrunk toward 1 by n/(n+20). "
        "The original advice tool remains unidentified; these public-reference policies do not measure that tool's performance.",
        "",
        "All three policies share the captured state, legal integer price grid, future pool, paid roster completion, and branch frontiers. "
        "The CSV distinguishes source values, raw estimates, legally capped policy ceilings, and executable actions. Baseline 'supported' means "
        "within its ceiling with a feasible buy incumbent; it does not prove that buying beats passing. A baseline cannot confirm a buy without a feasible roster.",
        "",
        "The roster policy supports buying only if its feasible buy lower bound exceeds the pass upper bound, or passing is proven infeasible. "
        "Equality passes. Overlapping bounds remain search-unresolved. Buy future cost excludes the nominee; buy total cost adds the tested nominee price. "
        "Both exclude previously paid holdings. Every row records exact Decimal bounds, roster IDs, costs, state, node counts, and reasons.",
        "",
        f"Each branch has a deterministic {summary['work_limit']:,}-node limit. Frontiers are reused across prices; "
        "the pass frontier is also shared across nominee-only stresses at the same future prices. "
        "The subset search can leave realistic pools unresolved; no runtime or resolution rate is promised. A limit is never proof of infeasibility.",
        "",
        "The nine defined scenarios cross future-price factors 0.8, 1.0, and 1.2 with neutral forecasts, a 20% nominee forecast reduction, and two "
        "nominee absences in the first two non-bye evaluation weeks. Season forecasts are distributed over 17 scheduled games and scored in Weeks 1–17. "
        "Byes drive bench coverage. Scenarios are stress assumptions, not calibrated probabilities.",
        "",
        (
            f"Scenario execution: all nine scenarios run for each of {summary['evaluated_pair_count']} evaluated pairs."
            if summary["evaluated_pair_count"]
            else "Scenario execution: no price grid is evaluated; all nine scenarios are defined but none are run."
        ),
        "",
        f"**Scenario disagreement:** {summary['scenario_disagreement_pairs']} evaluated pairs change action across scenarios. "
        "Zero disagreements with no evaluated grid means missing evidence, not robustness. The CSV repeats each pair's neutral supported/possible "
        "ceiling and scenario ranges, plus disagreement at the tested price.",
        "",
    ]
    examples = [
        pair
        for pair in pairs.values()
        if any(
            name in pair["player_name"] for name in ("Nacua", "Ridley", "Odunze", "Hunter", "Jeudy")
        )
    ]
    if not examples:
        examples = [
            pair
            for pair in pairs.values()
            if pair["pick"] == min(pick.pick for pick in picks if not pick.keeper)
        ]
    lines += [
        "## Named decision examples within full coverage",
        "",
        "These nomination examples preserve all teams at each named moment. No observed season points choose a favorable branch. "
        "Read the complete CSV for every other nomination. Blank ceilings indicate blocked inputs, not a $0 valuation.",
        "",
    ]
    lines += table(
        (
            "Pick",
            "Nominee",
            "Team",
            "Disposition",
            "Neutral supported / possible",
            "Scenario supported range",
            "Possible range",
            "Disagrees",
        ),
        [
            (
                pair["pick"],
                pair["player_name"],
                pair["team"],
                pair["disposition"],
                f"{pair['neutral_supported_ceiling']} / {pair['neutral_possible_ceiling']}"
                if "neutral_supported_ceiling" in pair
                else "unavailable",
                f"{pair['scenario_supported_min']}–{pair['scenario_supported_max']}"
                if "scenario_supported_min" in pair
                else "unavailable",
                f"{pair['scenario_possible_min']}–{pair['scenario_possible_max']}"
                if "scenario_possible_min" in pair
                else "unavailable",
                str(pair.get("scenario_disagreement", "unavailable")).lower(),
            )
            for pair in examples
        ],
    )
    lines += [
        "",
        "## Separate realized evaluation",
        "",
        "All completed roster alternatives and the recommendation payload freeze before weekly outcomes load. Fixed-preseason lineups use the "
        "base forecast ordering, stable ID ties, and known byes, even when the purchase scenario stressed a forecast. A selected player's missing "
        "week makes its score unknown; verified nonparticipation can be zero. Known byes and unfilled positions contribute zero. Week 18 is excluded.",
        "",
        "The separately labeled optimistic hindsight lineup selects the best legal weekly lineup over the same frozen roster. Any missing active "
        "eligible player's outcome makes that week's optimistic bound unknown. Empty slots may score zero. Neither method models roster transactions. "
        "No overlapping alternative is summed into a simulated team season, and 2025 remains exploratory because its outcomes have already informed the question.",
        "",
        f"Unknown evaluation branch rows: fixed-preseason {summary['unknown_evaluation_branch_rows']['fixed_preseason']}; "
        f"optimistic hindsight {summary['unknown_evaluation_branch_rows']['optimistic_hindsight']}. "
        "These are coverage counts, not independent observations. With no completed alternatives, zero counts mean evaluation was unavailable.",
        "",
    ]
    if actual_evaluations:
        lines += table(
            (
                "Actual team roster",
                "Fixed-preseason points",
                "Optimistic hindsight points",
                "Missing selected weeks",
                "Missing hindsight player-weeks",
            ),
            [
                (
                    team,
                    value["fixed_preseason_total"]
                    if value["fixed_preseason_total"] is not None
                    else "unknown",
                    value["optimistic_hindsight_total"]
                    if value["optimistic_hindsight_total"] is not None
                    else "unknown",
                    len(value["missing_selected"]),
                    len(value["missing_hindsight"]),
                )
                for team, value in actual_evaluations.items()
            ],
        )
    else:
        lines += [
            "Actual-roster outcome scores are unavailable because accepted forecast and weekly outcome inputs are unavailable."
        ]
    lines += [
        "",
        "## Reproducibility and source provenance",
        "",
        f"- Recommendation SHA-256: `{summary['recommendation_sha256']}`.",
        f"- Decision CSV SHA-256 (includes evaluation): `{summary['csv_sha256']}`.",
        f"- Raw auction file SHA-256 (descriptive only; may include outcome columns): `{_file_hash(auction_path)}`.",
        "- Recommendation hashing includes only whitelisted auction facts, structural/scoring rules, accepted preseason manifests, "
        "search settings, implementation bytes, and frozen policy rows. Raw outcome columns and weekly source hashes cannot alter it.",
        "",
    ]
    for name, manifest in provenance.items():
        lines += [
            f"- Accepted {name}: [source]({manifest['url']}), season {manifest['season']}, published {manifest['published_at']}, "
            f"retrieved {manifest['retrieved_at']}, normalized SHA-256 `{manifest['sha256']}`; "
            f"{len(manifest['identity_mappings'])} explicit mappings. {manifest['local_use']}."
        ]
    if outcome_source:
        lines += [
            f"- Separate weekly source (evaluation only): [source]({outcome_source.get('url', '')}), "
            f"normalized SHA-256 `{outcome_source.get('sha256', 'unavailable')}`. Acceptance: {'failed' if outcome_gap else 'passed'}."
        ]
    inventory = input_dir / "sources/source-inventory.json"
    if inventory.exists():
        lines += [
            "",
            "Cached raw sources below are candidates, not accepted normalized policy inputs. Hash checks establish current cache reproducibility; "
            "publisher dates do not prove historical immutability. Raw reconciliation that includes Week 18 is diagnostic only.",
            "",
        ]
        source_rows = []
        for source in _json_list(inventory):
            path = inventory.parent / source.get("file", "")
            valid = path.is_file() and _file_hash(path) == source.get("sha256")
            source_rows.append(
                (
                    f"[{source.get('name')}]({source.get('url')})",
                    source.get("season"),
                    source.get("publisher_date") or "unknown",
                    source.get("retrieved_at"),
                    "matches" if valid else "MISSING/MISMATCH",
                    source.get("sha256"),
                )
            )
        matched = sum(row[4] == "matches" for row in source_rows)
        lines += [
            f"**Raw cache verification: {matched}/{len(source_rows)} hashes match; {len(source_rows) - matched} missing or mismatched.** "
            "This check is separate from normalized-input acceptance.",
            "",
        ]
        lines += table(
            ("Raw source", "Season", "Publisher date", "Retrieved", "Cache hash", "SHA-256"),
            source_rows,
        )
    lines += [
        "",
        "This report does not establish generalization, championship probability, other managers' maximum bids, or a causal alternate auction. "
        "For an incomplete benchmark, resolve the current input failures. Review calculation and source evidence before sharing a strategy conclusion.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Generate a local auction replay; missing evidence produces an incomplete report."
    )
    parser.add_argument(
        "--auction",
        type=Path,
        default=root / "docs/research/2025-discount-double-check-auction.csv",
    )
    parser.add_argument("--input-dir", type=Path, default=root / "data/local/2025")
    parser.add_argument(
        "--report", type=Path, default=root / "docs/research/2025-auction-replay.md"
    )
    parser.add_argument("--csv", type=Path, default=root / "data/local/2025/replay-decisions.csv")
    parser.add_argument("--work-limit", type=int, default=2000)
    args = parser.parse_args(argv)
    try:
        summary = run_benchmark(
            args.auction, args.input_dir, args.report, args.csv, args.work_limit
        )
    except (InputError, OSError) as error:
        parser.exit(2, f"Replay input/output error: {error}\n")
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["benchmark_complete"] else 1
