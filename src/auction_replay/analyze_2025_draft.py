"""Validate the Yahoo snapshot and summarize historical spending and production."""

import csv
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

SOURCE = Path(__file__).resolve().parents[2] / "docs" / "research" / "2025-discount-double-check-auction.csv"


def read_rows():
    with SOURCE.open() as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        row["pick"] = int(row["pick"])
        row["salary"] = int(row["salary"])
        row["points"] = Decimal(row["points"])
        assert row["keeper"] in {"true", "false"}
        row["keeper"] = row["keeper"] == "true"
        row["games"] = int(row["games"]) if row["games"] else None
        assert row["points"].is_finite()
        assert row["salary"] >= 1
        assert row["position"] in {"QB", "RB", "WR", "TE", "K", "DEF"}
    assert [row["pick"] for row in rows] == list(range(1, 197))
    assert len({row["id"] for row in rows}) == 196
    assert set(Counter(row["team"] for row in rows).values()) == {14}
    assert len({row["team"] for row in rows}) == 14
    # Independent totals captured from the browser before saving the CSV.
    assert sum(row["salary"] for row in rows) == 2774
    assert sum(row["points"] for row in rows) == Decimal("28061.16")
    assert sum(row["pick"] * row["points"] for row in rows) == Decimal("2595795.66")
    assert sum(row["keeper"] for row in rows) == 14
    assert sum(row["salary"] for row in rows if row["keeper"]) == 231
    for team in {row["team"] for row in rows}:
        assert sum(row["salary"] for row in rows if row["team"] == team) <= 200
    return rows


def price_bands(rows):
    result = []
    for position in ("WR", "RB", "TE", "QB"):
        for low, high in ((1, 9), (10, 29), (30, 49), (50, 200)):
            group = [row for row in rows if row["position"] == position
                     and not row["keeper"] and low <= row["salary"] <= high]
            if group:
                result.append({"position": position, "band": f"${low}–${high}",
                               "players": len(group),
                               "mean_salary": round(mean(row["salary"] for row in group), 2),
                               "mean_points": round(mean(row["points"] for row in group), 2),
                               "median_points": round(median(row["points"] for row in group), 2)})
    return result


if __name__ == "__main__":
    rows = read_rows()
    print(json.dumps({"checks": "passed", "selections": len(rows),
                      "nonkeeper_price_bands": price_bands(rows)}, indent=2, default=str))
