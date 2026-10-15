"""Print a short, readable summary of one quickstart replay run.

Usage: python3 -B scripts/quickstart_summary.py INPUT_DIR OUTPUT_DIR REPLAY_EXIT_CODE

INPUT_DIR holds the league files (examples/synthetic). OUTPUT_DIR holds the replay's
summary.json, report.md, and decisions.csv. The tables show the neutral scenario at
the 1.0 future-price factor, from the view of the team that won each sale. The
closing price appears only as a label here; the replay never sees it before deciding.
Standard library only.
"""

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

DECISION_LABELS = {"supported": "buy", "pass": "pass", "search-unresolved": "unresolved",
                   "infeasible": "infeasible", "missing-data": "missing data"}


def _points(value):
    return "none" if value in ("", None) else f"{Decimal(value):.1f}"


def _dollars(value):
    return "none" if value in ("", None) else f"${value}"


def _shown(path):
    path = Path(path).resolve()
    return str(path.relative_to(Path.cwd())) if path.is_relative_to(Path.cwd()) else str(path)


def _table(headers, rows, right):
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows)]
    lines = []
    for row in (headers, *rows):
        cells = [str(cell).rjust(width) if index in right else str(cell).ljust(width)
                 for index, (cell, width) in enumerate(zip(row, widths))]
        lines.append("  ".join(cells).rstrip())
    return lines


def _heading(text):
    return ["", text, "-" * len(text)]


def summarize(input_dir, output_dir, status):
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    rules = json.loads((input_dir / "rules.json").read_text())
    with (input_dir / "auction.csv").open(newline="", encoding="utf-8") as source:
        picks = list(csv.DictReader(source))
    summary = json.loads((output_dir / "summary.json").read_text())
    sales = {pick["pick"]: pick for pick in picks if pick["keeper"] == "false"}
    keepers = len(picks) - len(sales)

    # Keep one row per sale: the winning team's neutral row at the price it paid,
    # or its blank-price row when the replay rejects the pair before pricing.
    chosen = {}
    with (output_dir / "decisions.csv").open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            sale = sales.get(row["pick"])
            if sale is None or row["team"] != sale["team"]:
                continue
            if row["price"] == "" or (row["scenario"] == "neutral" and row["price_factor"] == "1"
                                      and row["price"] == sale["salary"]):
                chosen[row["pick"]] = row

    roster = summary["row_dispositions"]["roster"]
    pairs = summary["pair_count"]
    evaluated = summary["evaluated_pair_count"]
    lines = ["Auction replay quickstart", "=========================",
             f"Synthetic league from {_shown(input_dir)}: {rules['teams']} teams, ${rules['budget']} budgets, "
             f"{rules['roster_size']}-player rosters",
             f"(starters {', '.join(rules['starters'])}). {keepers} keepers count first; "
             f"{len(sales)} sales then replay in order.",
             "Every player and team is made up. No private data is read."]
    lines += _heading("Benchmark summary")
    lines += [f"Benchmark complete: {'yes' if summary['benchmark_complete'] else 'no'} (replay exit code {status})",
              f"Team and nomination pairs: {pairs} ({evaluated} priced, {pairs - evaluated} rejected before pricing)",
              f"Decision rows: {roster.get('supported', 0)} buy, {roster.get('pass', 0)} pass, "
              f"{roster.get('search-unresolved', 0)} unresolved, {roster.get('infeasible', 0)} infeasible, "
              f"{roster.get('missing-data', 0)} missing data",
              "(one row per team, nomination, legal price, and scenario; a rejected pair gets one row)"]

    ceiling_rows, bound_rows = [], []
    for number, sale in sorted(sales.items(), key=lambda item: int(item[0])):
        row = chosen.get(number)
        if row is None or row["price"] == "":
            reason = "no row" if row is None else row["reason"]
            ceiling_rows.append((number, sale["name"], sale["position"], sale["team"], f"${sale['salary']}",
                                 "blocked", "", "", reason))
            continue
        ceiling_rows.append((number, sale["name"], sale["position"], sale["team"], f"${sale['salary']}",
                             _dollars(row["capacity"]), _dollars(row["neutral_supported_ceiling"]),
                             _dollars(row["neutral_possible_ceiling"]),
                             f"${row['scenario_supported_min']} to ${row['scenario_supported_max']}"))
        bound_rows.append((number, sale["name"], f"${sale['salary']}",
                           _points(row["buy_lower"]), _points(row["buy_upper"]),
                           _points(row["pass_lower"]), _points(row["pass_upper"]),
                           DECISION_LABELS.get(row["roster_action"], row["roster_action"])))

    lines += _heading("Bid ceilings for the team that won each sale (neutral scenario)")
    lines += ["Max bid keeps $1 for every other open place. Proven is the highest bid at which buying",
              "is proven better than passing; possible is the highest bid not yet ruled out. Scenarios",
              "gives the proven range across all nine stress scenarios. $0 means no bid is proven.", ""]
    lines += _table(("Pick", "Nominee", "Pos", "Winner", "Paid", "Max bid", "Proven", "Possible", "Scenarios"),
                    ceiling_rows, {0, 4, 5, 6, 7})
    lines += _heading("Buy versus pass bounds at the price paid (projected season points)")
    lines += _table(("Pick", "Nominee", "Paid", "Buy lower", "Buy upper", "Pass lower", "Pass upper",
                     "Decision"), bound_rows, {0, 2, 3, 4, 5, 6})
    lines += ["",
              "Buy is proven when its lower bound beats the pass upper bound. Pass is proven when its",
              "lower bound meets or beats the buy upper bound. Overlapping bounds stay unresolved."]
    if evaluated and not roster.get("search-unresolved"):
        lines += ["In this small pool the search proves every decision; real 14-team pools often do not."]
    lines += _heading("Files")
    lines += [f"Full report: {_shown(output_dir / 'report.md')}",
              f"Every team, price, and scenario: {_shown(output_dir / 'decisions.csv')}"]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        raise SystemExit(__doc__.strip().splitlines()[2])
    print(summarize(argv[0], argv[1], int(argv[2])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
