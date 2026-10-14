"""Run with python3 -B tests/test_import_yahoo_snapshot.py.

Synthetic Yahoo-shaped responses test parsing, not authenticated API access.
"""

import copy
import csv
import json
import tempfile
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

# Run from a checkout without installing: put src/ on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auction_replay.import_yahoo_snapshot import InputError, import_snapshot, main, reconcile  # noqa: E402


def sample():
    metadata = {"league_key": "999.l.123", "league_id": "123", "game_code": "nfl",
                "season": "2025", "num_teams": 2, "draft_status": "postdraft"}
    settings = {"is_auction_draft": "1", "scoring_type": "headpoint",
                "roster_positions": [{"roster_position": {"position": "QB", "count": 1}},
                                     {"roster_position": {"position": "BN", "count": "1"}}],
                "stat_categories": {"stats": [{"stat": {"stat_id": 4, "name": "Passing Touchdowns", "enabled": "1"}}]},
                "stat_modifiers": {"stats": [{"stat": {"stat_id": 4, "value": "6"}}]}}
    rows = [{"pick": 1, "round": 1, "player_key": "999.p.10", "team_key": "999.l.123.t.1", "cost": "70"},
            {"pick": 2, "round": 1, "player_key": "999.p.11", "team_key": "999.l.123.t.2", "cost": "0"}]
    draft = {str(i): {"draft_result": row} for i, row in enumerate(rows)}
    draft["count"] = 2
    return ({"fantasy_content": {"league": [copy.deepcopy(metadata), {"settings": [settings]}]}},
            {"fantasy_content": {"league": [copy.deepcopy(metadata), {"draft_results": draft}]}})


def parse(settings, draft):
    return import_snapshot(settings, draft, league_key="999.l.123", season=2025, source_kind="sample")


def rejected(change, fragment):
    settings, draft = sample()
    change(settings, draft)
    try:
        parse(settings, draft)
    except InputError as error:
        assert fragment in str(error), (fragment, str(error))
    else:
        raise AssertionError("invalid input was accepted")


def run():
    settings, draft = sample()
    # Metadata outside the import allowlist must not leak into a derived report.
    settings["fantasy_content"]["league"][0]["irrelevant_private_field"] = "DO_NOT_EXPORT"
    result = parse(settings, draft)
    assert result["source_kind"] == "sample" and result["authenticated_access_verified"] is False
    assert result["replay_ready"] is False
    assert result["draft"][0]["player_key"] == "999.p.10"
    assert result["draft"][0]["cost"] == 70
    assert result["draft"][1]["cost"] == 0 and result["draft"][1]["keeper"] is None
    assert result["settings"]["scoring"][0]["value"] == "6"
    assert result["summary"]["known_spend"] == 70 and "DO_NOT_EXPORT" not in json.dumps(result)
    del draft["fantasy_content"]["league"][1]["draft_results"]["0"]["draft_result"]["cost"]
    result = parse(settings, draft)
    assert result["draft"][0]["cost"] is None and result["summary"]["missing_costs"] == 1
    rejected(lambda s, d: d["fantasy_content"]["league"][0].update(league_key="999.l.456"), "league identity")
    rejected(lambda s, d: d["fantasy_content"]["league"][0].update(season="2024"), "season")
    rejected(lambda s, d: s["fantasy_content"]["league"][0].update(game_code="nhl"), "NFL")
    rejected(lambda s, d: d["fantasy_content"]["league"][1]["draft_results"].update(count=3), "count")
    rejected(lambda s, d: d["fantasy_content"]["league"][1]["draft_results"]["1"]["draft_result"].update(player_key="999.p.10"), "duplicate player")
    rejected(lambda s, d: d["fantasy_content"]["league"][1]["draft_results"]["1"]["draft_result"].update(team_key="999.l.456.t.2"), "team key")
    rejected(lambda s, d: d["fantasy_content"]["league"][1]["draft_results"]["1"]["draft_result"].update(player_key="998.p.11"), "player key")
    rejected(lambda s, d: d["fantasy_content"]["league"][1]["draft_results"]["0"]["draft_result"].update(cost=-1), "cost")
    rejected(lambda s, d: s["fantasy_content"]["league"][1]["settings"][0]["stat_modifiers"]["stats"][0]["stat"].update(value="NaN"), "finite")
    rejected(lambda s, d: s["fantasy_content"]["league"][1]["settings"][0]["stat_modifiers"]["stats"][0]["stat"].update(stat_id=99), "stat category")
    settings, draft = sample()
    for response in [settings, draft]:
        response["fantasy_content"]["league"][0]["num_teams"] = 1
    try:
        parse(settings, draft)
    except InputError as error:
        assert "more teams" in str(error)
    else:
        raise AssertionError("excess draft teams were accepted")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        expected = root / "auction.csv"
        with expected.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "pick", "salary", "points"])
            writer.writeheader()
            writer.writerows([{"id": "10", "pick": "1", "salary": "70", "points": "9999"},
                              {"id": "11", "pick": "2", "salary": "0", "points": "0"}])
        settings, draft = sample()
        result = parse(settings, draft)
        comparison = reconcile(result["draft"], expected)
        assert comparison["prices_and_order_match"] is True
        assert comparison["ownership_verified"] is False and comparison["keepers_verified"] is False
        changed_order = copy.deepcopy(result["draft"])
        changed_order[0]["pick"] = 2
        assert reconcile(changed_order, expected)["differences"][0]["field"] == "pick"
        changed_player = copy.deepcopy(result["draft"])
        changed_player[0]["player_id"] = "99"
        mismatch = reconcile(changed_player, expected)
        assert mismatch["prices_and_order_match"] is False
        assert mismatch["missing_player_ids"] == ["10"] and mismatch["extra_player_ids"] == ["99"]
        result["draft"][0]["cost"] = 71
        assert reconcile(result["draft"], expected)["differences"][0]["field"] == "cost"
        settings_path, draft_path, output_path = root / "settings.json", root / "draft.json", root / "import.json"
        settings_path.write_text(json.dumps(settings))
        draft_path.write_text(json.dumps(draft))
        args = ["--settings", str(settings_path), "--draft", str(draft_path), "--league-key", "999.l.123",
                "--season", "2025", "--source-kind", "sample", "--captured-at", "2026-09-05T00:00:00Z",
                "--output", str(output_path), "--expected-auction", str(expected)]
        assert main(args) == 0
        before = output_path.read_bytes()
        saved = json.loads(before)
        assert len(saved["sources"]["settings"]["sha256"]) == 64
        output_path.write_text("old snapshot")
        with patch("builtins.print", side_effect=BrokenPipeError("status pipe closed")):
            assert main(args) == 0
        assert output_path.read_bytes() == before
        # Duplicate JSON keys must fail before a later value can hide a purchase.
        original_draft = draft_path.read_text()
        draft_path.write_text(original_draft.replace('"cost": "70"', '"cost": "1", "cost": "70"'))
        assert main(args) == 2 and output_path.read_bytes() == before
        draft_path.write_text(original_draft)
        settings_path.write_text("not json")
        assert main(args) == 2 and output_path.read_bytes() == before
    print("Yahoo snapshot checks passed (synthetic data; no Yahoo calls).")


class YahooSnapshotChecks(unittest.TestCase):
    def test_import_snapshot(self):
        run()


if __name__ == "__main__":
    run()
