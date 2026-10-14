"""Import saved Yahoo settings and draft-results JSON without network or credentials.

Accept raw fantasy_content.league responses, available through the MIT
yahoo_fantasy_api client's YHandler. Keep full provider keys and unknown costs.
This produces an inspection snapshot, not accepted replay inputs or bid advice.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from .replay_auction import InputError, _decimal, _integer, _rows, _text, _timestamp


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate JSON object key")
        result[key] = value
    return result


def _object(value, field):
    if not isinstance(value, dict):
        raise InputError(f"{field} must be an object")
    return value


def _wrapped_list(value, key):
    if not isinstance(value, list):
        raise InputError(f"{key} collection must be a list")
    return [_object(_object(row, key).get(key), key) for row in value]


def _league(document, league_key, season):
    content = _object(_object(document, "response").get("fantasy_content"), "fantasy_content")
    league = content.get("league")
    if not isinstance(league, list) or len(league) < 2:
        raise InputError("expected a raw Yahoo league response with metadata and a subresource")
    metadata = _object(league[0], "league metadata")
    if metadata.get("league_key") != league_key or str(metadata.get("league_id")) != league_key.split(".")[-1]:
        raise InputError("league identity does not match requested league")
    if _integer(metadata.get("season"), "season", 2000) != season:
        raise InputError("season does not match requested season")
    if metadata.get("game_code") != "nfl":
        raise InputError("this importer requires an NFL league")
    if metadata.get("draft_status") != "postdraft":
        raise InputError("a completed draft is required for this historical importer")
    combined = {}
    for part in league[1:]:
        part = _object(part, "league subresource")
        if combined.keys() & part.keys():
            raise InputError("duplicate league subresource")
        combined.update(part)
    return metadata, combined


def _settings(raw):
    if not isinstance(raw, list) or not raw:
        raise InputError("settings must be a nonempty list")
    settings = {}
    for part in raw:
        part = _object(part, "settings")
        if settings.keys() & part.keys():
            raise InputError("duplicate settings field")
        settings.update(part)
    if _integer(settings.get("is_auction_draft"), "is_auction_draft", 0, 1) != 1:
        raise InputError("an auction draft is required")
    positions = {}
    for row in _wrapped_list(settings.get("roster_positions"), "roster_position"):
        position = _text(row.get("position"), "roster position")
        if position in positions:
            raise InputError("duplicate roster position")
        positions[position] = _integer(row.get("count"), "roster count")
    if not positions:
        raise InputError("missing roster positions")
    categories = {}
    for row in _wrapped_list(_object(settings.get("stat_categories"), "stat_categories").get("stats"), "stat"):
        stat_id = str(_integer(row.get("stat_id"), "stat_id"))
        if stat_id in categories:
            raise InputError("duplicate stat category")
        categories[stat_id] = row
    scoring, seen = [], set()
    for row in _wrapped_list(_object(settings.get("stat_modifiers"), "stat_modifiers").get("stats"), "stat"):
        stat_id = str(_integer(row.get("stat_id"), "stat_id"))
        if stat_id not in categories or stat_id in seen:
            raise InputError("missing or duplicate stat category for modifier")
        seen.add(stat_id)
        category = categories[stat_id]
        scoring.append({"stat_id": stat_id, "name": _text(category.get("name"), "stat name"),
                        "value": str(_decimal(row.get("value"), "scoring value")),
                        "has_bonuses": bool(row.get("bonuses")),
                        "enabled": None if "enabled" not in category else _integer(category["enabled"], "stat enabled", 0, 1)})
    if not scoring:
        raise InputError("missing scoring modifiers")
    return {"is_auction_draft": True, "scoring_type": _text(settings.get("scoring_type"), "scoring_type"),
            "roster_positions": positions, "scoring": scoring,
            "unmapped_category_ids": sorted(set(categories) - seen),
            "scoring_complete": False}


def import_snapshot(settings_document, draft_document, *, league_key, season, source_kind):
    """Validate one completed NFL auction and retain unknown evidence explicitly."""
    if not isinstance(league_key, str) or not re.fullmatch(r"[0-9]+\.l\.[0-9]+", league_key):
        raise InputError("use an explicit season-specific league key")
    if source_kind not in {"sample", "yahoo-cache"}:
        raise InputError("source_kind must be sample or yahoo-cache")
    metadata, settings_part = _league(settings_document, league_key, season)
    draft_metadata, draft_part = _league(draft_document, league_key, season)
    teams = _integer(metadata.get("num_teams"), "num_teams", 1)
    if _integer(draft_metadata.get("num_teams"), "num_teams", 1) != teams:
        raise InputError("team counts disagree between responses")
    settings = _settings(settings_part.get("settings"))
    raw = _object(draft_part.get("draft_results"), "draft_results")
    count = _integer(raw.get("count"), "draft count", 1)
    if count != len(raw) - 1 or set(raw) != {"count"} | {str(i) for i in range(count)}:
        raise InputError("draft collection count or indexes do not match")
    draft, players, owner_keys = [], set(), set()
    game_key = league_key.split(".")[0]
    player_pattern = re.compile(re.escape(game_key) + r"\.p\.[0-9]+")
    team_pattern = re.compile(re.escape(league_key) + r"\.t\.[1-9][0-9]*")
    for i in range(count):
        row = _object(_object(raw[str(i)], "draft entry").get("draft_result"), "draft_result")
        player_key = _text(row.get("player_key"), "player key")
        team_key = _text(row.get("team_key"), "team key")
        if not player_pattern.fullmatch(player_key):
            raise InputError("player key belongs to another game or is malformed")
        if not team_pattern.fullmatch(team_key):
            raise InputError("team key belongs to another league or is malformed")
        if player_key in players:
            raise InputError("duplicate player in draft results")
        players.add(player_key)
        owner_keys.add(team_key)
        draft.append({"pick": _integer(row.get("pick"), "pick", 1),
                      "player_key": player_key, "player_id": player_key.split(".")[-1],
                      "team_key": team_key,
                      "cost": None if row.get("cost") is None else _integer(row["cost"], "cost"),
                      # Keeper placement and $0 costs cannot establish keeper status.
                      "keeper": None})
    draft.sort(key=lambda row: row["pick"])
    if [row["pick"] for row in draft] != list(range(1, count + 1)):
        raise InputError("draft pick sequence must be contiguous and unique")
    if len(owner_keys) > teams:
        raise InputError("draft includes more teams than league metadata")
    return {"source_kind": source_kind, "authenticated_access_verified": False, "replay_ready": False,
            "league": {"league_key": league_key, "season": season, "game_code": "nfl", "num_teams": teams},
            "settings": settings, "draft": draft,
            "summary": {"selections": count, "known_spend": sum(row["cost"] or 0 for row in draft),
                        "missing_costs": sum(row["cost"] is None for row in draft), "unknown_keepers": count},
            "limitations": ["Local files do not verify current Yahoo access.",
                            "Keeper status, starting budget, and owner identities require separate verification.",
                            "Scoring IDs and bonuses require mapping and reconciliation before replay use.",
                            "Completed purchases do not include losing bids or live nomination state.",
                            "Pre-draft projections and weekly outcomes are separate inputs."]}


def reconcile(draft, auction_path):
    """Compare player IDs, pick order, and costs; never read outcome columns."""
    expected = {}
    for row in _rows(auction_path, ["id", "pick", "salary"]):
        player_id = _text(row["id"], "player ID")
        if player_id in expected:
            raise InputError("duplicate expected player ID")
        expected[player_id] = {"pick": _integer(row["pick"], "expected pick", 1),
                               "cost": _integer(row["salary"], "expected cost")}
    actual = {row["player_id"]: row for row in draft}
    matched = expected.keys() & actual.keys()
    differences = [{"player_id": pid, "field": field, "expected": expected[pid][field], "actual": actual[pid][field]}
                   for pid in sorted(matched) for field in ["pick", "cost"]
                   if expected[pid][field] != actual[pid][field]]
    missing, extra = sorted(expected.keys() - actual.keys()), sorted(actual.keys() - expected.keys())
    return {"prices_and_order_match": not differences and not missing and not extra,
            "ownership_verified": False, "keepers_verified": False,
            "matched_player_ids": len(matched),
            "missing_player_ids": missing, "extra_player_ids": extra, "differences": differences}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["settings", "draft", "league-key", "captured-at", "output"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument("--source-kind", required=True, choices=["sample", "yahoo-cache"])
    parser.add_argument("--expected-auction")
    args = parser.parse_args(argv)
    try:
        _timestamp(args.captured_at, "captured_at")
        output = Path(args.output)
        source_paths = {"settings": Path(args.settings), "draft": Path(args.draft)}
        inputs = list(source_paths.values())
        if args.expected_auction:
            inputs.append(Path(args.expected_auction))
        if output.resolve() in [path.resolve() for path in inputs]:
            raise InputError("output must not overwrite an input")
        documents, sources = [], {}
        for label, path in source_paths.items():
            content = path.read_bytes()
            documents.append(json.loads(content, object_pairs_hook=_unique_object))
            sources[label] = {"sha256": hashlib.sha256(content).hexdigest(), "captured_at": args.captured_at}
        result = import_snapshot(*documents, league_key=args.league_key, season=args.season, source_kind=args.source_kind)
        result["sources"] = sources
        if args.expected_auction:
            result["reconciliation"] = reconcile(result["draft"], args.expected_auction)
        rendered = json.dumps(result, indent=2, allow_nan=False) + "\n"
        # Finish rendering and validation before replacing a previous snapshot.
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as temp:
            temporary = Path(temp.name)
            try:
                temp.write(rendered)
                temp.flush()
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
    except (InputError, OSError, ValueError, TypeError) as error:
        # Print the error class, not untrusted response bodies or credential data.
        print(f"Snapshot import failed ({type(error).__name__}); previous output preserved.", file=sys.stderr)
        return 2
    # The file is the deliverable; a closed status pipe cannot undo a saved import.
    try:
        print(json.dumps({"imported": result["summary"]["selections"], "source_kind": args.source_kind,
                          "replay_ready": False, "authenticated_access_verified": False}), flush=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
