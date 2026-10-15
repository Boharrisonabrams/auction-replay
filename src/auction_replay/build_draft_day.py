"""Build a private, offline roster worksheet from two user-exported Draft Sharks CSVs."""

import argparse
import csv
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parents[1] / "templates"


def load(path, required):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows or not set(required) <= set(rows[0]):
        raise ValueError(f"{path.name}: missing required columns")
    if len(rows[0]) != len(set(rows[0])):
        raise ValueError("Duplicate columns")
    if any(len(r) != len(rows[0]) for r in rows[1:]):
        raise ValueError("Malformed CSV row width")
    result = [dict(zip(rows[0], r)) for r in rows[1:]]
    if len({r["Player"] for r in result}) != len(result):
        raise ValueError("Ambiguous player names")
    return result


def build(projections, market, output):
    rows = load(projections, ["Player", "Pos", "DS Proj"])
    refs = {r["Player"]: r for r in load(market, ["Player", "Pos", "Market $"])}
    players = {}
    for r in rows:
        if r["Pos"] not in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            continue
        points = float(r["DS Proj"])
        if not math.isfinite(points):
            raise ValueError("Invalid projection")
        ref = refs.get(r["Player"])
        price = None
        if ref and ref["Pos"] == r["Pos"] and re.fullmatch(r"\$\d+", ref["Market $"]):
            price = int(ref["Market $"][1:])
        players[r["Player"]] = dict(pos=r["Pos"], points=points, market=price)
    names = [
        "Caleb Williams",
        "Jahmyr Gibbs",
        "D'Andre Swift",
        "Tee Higgins",
        "Jaylen Waddle",
        "Travis Kelce",
        "Rhamondre Stevenson",
    ]
    bench: list[str] = []
    for pos in ["K", "DEF", "RB", "RB", "WR", "WR", "QB"]:
        bench.append(
            next(
                n
                for n, p in players.items()
                if p["pos"] == pos and p["market"] == 1 and n not in bench + names
            )
        )
    names += bench
    first = [dict(name=n, cost=players[n]["market"] + 1, owned=i == 0) for i, n in enumerate(names)]
    first[0]["cost"] = 1
    first[1]["cost"] = 78
    second = [dict(r) for r in first]
    for i, n in [(1, "Kenneth Walker III"), (3, "Nico Collins"), (5, "Colston Loveland")]:
        second[i] = dict(name=n, cost=players[n]["market"] + 1, owned=False)
    source = hashlib.sha256(projections.read_bytes() + market.read_bytes()).hexdigest()
    data: dict[str, Any] = dict(
        players=players,
        source=source,
        captured=datetime.fromtimestamp(projections.stat().st_mtime, UTC).isoformat(),
        initial=dict(
            version=1,
            source=source,
            budget=200,
            target=1,
            stress=1,
            owned=[True] + [False] * 13,
            plans=[first, second],
            unavailable=[],
            confirmed=False,
            quote="",
        ),
    )
    style = re.search(  # type: ignore[index]  # the template has a style block
        r"<style>(.*?)</style>", (TEMPLATES / "draft-companion.html").read_text(), re.S
    )[1]
    html = (
        (TEMPLATES / "draft-day.html")
        .read_text()
        .replace("<!--STYLE-->", style)
        .replace(
            "<!--PAYLOAD-->",
            json.dumps(data, ensure_ascii=True)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026"),
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".html.tmp")
    temporary.write_text(html)
    temporary.replace(output)
    print(
        json.dumps(
            dict(
                path=str(output),
                players=len(players),
                source=source,
                plan_costs=[sum(r["cost"] for r in p) for p in data["initial"]["plans"]],
                scope="Unconfirmed rehearsal worksheet; manual future prices; no live feed",
            )
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=HERE.parents[1] / "data/local/companion/draft-day.html"
    )
    args = parser.parse_args(argv)
    build(args.projections, args.market, args.output)


if __name__ == "__main__":
    main()
