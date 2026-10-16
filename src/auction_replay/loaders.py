"""Load the league rules, the auction CSV, and the normalized source files.

Each source file must match its JSON manifest before any value is used. The replay_auction
module docstring describes the file and manifest schema.
"""

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .inputs import POSITIONS, AuctionPick, InputError, LeagueRules, Player
from .inputs import decimal as _decimal
from .inputs import integer as _integer
from .inputs import json_object as _json
from .inputs import rows as _rows
from .inputs import text as _text
from .inputs import timestamp as _timestamp


def load_rules(path, require_scoring=True):
    """Require an explicitly captured complete rule set; never infer scoring.

    JSON uses every LeagueRules field plus scoring_complete=true. Scoring is a
    mapping of all enabled Yahoo scoring categories to decimal coefficients.
    Collection must verify completeness against the league settings; this loader
    validates the declaration and exact downstream scoring agreement.
    With require_scoring=False, incomplete scoring becomes an empty tuple and
    only structural reconstruction is permitted; no coefficients are invented.
    """
    data = _json(path)
    required = set(LeagueRules.__dataclass_fields__) | {"scoring_complete"}
    if required - data.keys():
        raise InputError(f"missing league rules: {sorted(required - data.keys())}")
    complete = (
        data["scoring_complete"] is True
        and isinstance(data["scoring"], dict)
        and bool(data["scoring"])
    )
    if require_scoring and not complete:
        raise InputError("complete scoring rules are unavailable")
    values = {
        key: _integer(data[key], key, 1)
        for key in ("season", "teams", "budget", "roster_size", "first_week", "last_week")
    }
    _timestamp(data["draft_at"], "draft_at")
    if _timestamp(data["draft_at"], "draft_at").year != values["season"]:
        raise InputError("draft year does not match season")
    starters = data["starters"]
    if (
        not isinstance(starters, list)
        or not starters
        or any(slot not in POSITIONS | {"FLEX"} for slot in starters)
        or len(starters) > values["roster_size"]
        or values["budget"] < values["roster_size"]
        or not 1 <= values["first_week"] <= values["last_week"] <= 17
    ):
        raise InputError("incompatible roster, budget, or week rules")
    scoring = (
        tuple(
            sorted(
                (_text(key, "scoring category"), _decimal(value, key))
                for key, value in data["scoring"].items()
            )
        )
        if complete
        else ()
    )
    return LeagueRules(
        **values, draft_at=data["draft_at"], starters=tuple(starters), scoring=scoring
    )


def scoring_hash(rules):
    content = json.dumps(
        [(key, str(value.normalize())) for key, value in sorted(rules.scoring)],
        separators=(",", ":"),
    )
    return hashlib.sha256(content.encode()).hexdigest()


def load_auction(path, rules=LeagueRules()):
    """Whitelist auction facts; outcome columns are never read or validated."""
    rows = _rows(path, "pick id name position salary team keeper".split())
    picks = []
    seen = set()
    for row in rows:
        player_id = _text(row["id"], "player ID")
        if player_id in seen:
            raise InputError(f"duplicate player ID: {player_id}")
        seen.add(player_id)
        if row["keeper"] not in {"true", "false"}:
            raise InputError(f"invalid keeper flag for {player_id}")
        keeper = row["keeper"] == "true"
        position = _text(row["position"], "position")
        if position not in POSITIONS:
            raise InputError(f"unknown position for {player_id}: {position}")
        picks.append(
            AuctionPick(
                _integer(row["pick"], "pick", 1),
                player_id,
                _text(row["name"], "name"),
                position,
                _integer(row["salary"], "salary", 0 if keeper else 1, rules.budget),
                _text(row["team"], "fantasy team"),
                keeper,
            )
        )
    if [p.pick for p in picks] != list(range(1, len(picks) + 1)):
        raise InputError("auction pick sequence must be contiguous and ordered")
    counts = Counter(p.team for p in picks)
    if len(counts) != rules.teams or set(counts.values()) != {rules.roster_size}:
        raise InputError("auction team count or roster size does not match league rules")
    for team in counts:
        if sum(p.salary for p in picks if p.team == team) > rules.budget:
            raise InputError(f"auction budget exceeded for {team}")
    return tuple(picks)


def validate_manifest(manifest, data_path, rules, preseason=True, require_scoring=True):
    """Validate source metadata and return its one-to-one provider-ID crosswalk."""
    manifest = _json(manifest)
    if type(manifest.get("season")) is not int or manifest["season"] != rules.season:
        raise InputError("source season does not match league season")
    url = urlparse(_text(manifest.get("url"), "source URL"))
    if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password:
        raise InputError("invalid source URL")
    publication = _text(manifest.get("published_at"), "publication date")
    draft = _timestamp(rules.draft_at, "draft_at")
    retrieved = _timestamp(manifest.get("retrieved_at"), "retrieval timestamp")
    if len(publication) == 10:
        try:
            published_date = date.fromisoformat(publication)
        except ValueError:
            raise InputError("invalid publication date") from None
        if preseason and published_date >= draft.date():
            raise InputError("post-draft or ambiguous draft-day publication date")
        if published_date > retrieved.date():
            raise InputError("retrieval precedes publication")
    else:
        published = _timestamp(publication, "publication timestamp")
        if preseason and published >= draft:
            raise InputError("post-draft publication timestamp")
        if published > retrieved:
            raise InputError("retrieval precedes publication")
    try:
        digest = hashlib.sha256(Path(data_path).read_bytes()).hexdigest()
    except OSError as error:
        raise InputError(f"missing normalized source: {error}") from None
    if manifest.get("sha256") != digest:
        raise InputError("normalized source hash mismatch")
    if require_scoring:
        if not rules.scoring:
            raise InputError("league scoring rules are missing")
        coverage = manifest.get("scoring_coverage")
        if (
            not isinstance(coverage, list)
            or any(not isinstance(key, str) for key in coverage)
            or set(coverage) != {key for key, _ in rules.scoring}
        ):
            raise InputError("source scoring coverage does not match complete league rules")
        if manifest.get("scoring_hash") != scoring_hash(rules):
            raise InputError("source scoring coefficients do not match league rules")
    else:
        _text(manifest.get("source_scoring"), "reference source scoring description")
        _text(manifest.get("source_format"), "reference source format")
    _text(manifest.get("local_use"), "permitted local use")
    if preseason and manifest.get("includes_undrafted") is not True:
        raise InputError("preseason universe does not declare undrafted coverage")
    mappings = manifest.get("identity_mappings")
    if not isinstance(mappings, list) or not mappings:
        raise InputError("identity mappings are missing")
    crosswalk: dict[str, str] = {}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise InputError("invalid identity mapping")
        provider_id = _text(mapping.get("provider_id"), "provider ID")
        player_id = _text(mapping.get("player_id"), "Yahoo player ID")
        if provider_id in crosswalk or player_id in crosswalk.values():
            raise InputError(f"ambiguous identity mapping: {provider_id} / {player_id}")
        crosswalk[provider_id] = player_id
    return crosswalk


def _mapped_id(row, crosswalk):
    provider_id = _text(row["provider_id"], "provider ID")
    if provider_id not in crosswalk:
        raise InputError(f"unmatched provider ID: {provider_id}")
    return crosswalk[provider_id]


def load_forecasts(path, manifest, rules, drafted_ids):
    crosswalk = validate_manifest(manifest, path, rules)
    players = {}
    for row in _rows(path, "provider_id name position nfl_team bye projected_points".split()):
        player_id = _mapped_id(row, crosswalk)
        if player_id in players:
            raise InputError(f"duplicate forecast player: {player_id}")
        position = _text(row["position"], "forecast position")
        if position not in POSITIONS:
            raise InputError(f"unknown forecast position: {position}")
        players[player_id] = Player(
            player_id,
            _text(row["name"], "forecast name"),
            position,
            _text(row["nfl_team"], "NFL team"),
            _integer(row["bye"], "bye", 1, 18),
            _decimal(row["projected_points"], "projected points"),
        )
    missing = set(drafted_ids) - players.keys()
    if missing:
        raise InputError(f"missing drafted players from forecast universe: {sorted(missing)}")
    if not players.keys() - set(drafted_ids):
        raise InputError("forecast universe has no undrafted alternatives")
    return players


def load_reference_values(path, manifest, rules, player_ids):
    crosswalk = validate_manifest(manifest, path, rules, require_scoring=False)
    values = {}
    for row in _rows(path, ["provider_id", "reference_value"]):
        player_id = _mapped_id(row, crosswalk)
        if player_id in values:
            raise InputError(f"duplicate reference player: {player_id}")
        value = _decimal(row["reference_value"], "reference value")
        if value < 0:
            raise InputError(f"negative reference value: {player_id}")
        values[player_id] = value
    missing = set(player_ids) - values.keys()
    if missing:
        raise InputError(f"missing reference values: {sorted(missing)}")
    return values


def load_weekly_outcomes(path, manifest, rules, player_ids):
    """Require observed zeros; absent records remain None; exclude Week 18."""
    crosswalk = validate_manifest(manifest, path, rules, preseason=False)
    mapped_ids = set(crosswalk.values())
    outcomes = {
        (player_id, week): None
        for player_id in player_ids
        for week in range(rules.first_week, rules.last_week + 1)
    }
    seen = set()
    for row in _rows(path, ["player_id", "week", "points", "status"]):
        player_id = _text(row["player_id"], "weekly player ID")
        if player_id not in mapped_ids:
            raise InputError(f"unmatched weekly player ID: {player_id}")
        week = _integer(row["week"], "week", 1, 18)
        if not rules.first_week <= week <= rules.last_week:
            continue
        key = (player_id, week)
        if key in seen:
            raise InputError(f"duplicate weekly observation: {player_id}, week {week}")
        seen.add(key)
        if row["status"] not in {"verified", "missing"}:
            raise InputError(f"unknown observation status: {player_id}, week {week}")
        if row["status"] == "missing" and row["points"] not in {"", None}:
            raise InputError(f"missing observation has points: {player_id}, week {week}")
        points = (
            None
            if row["status"] == "missing"
            else _decimal(row["points"], "verified weekly points")
        )
        if key in outcomes:
            outcomes[key] = points
    return outcomes


def weekly_gaps(outcomes):
    return sorted(key for key, points in outcomes.items() if points is None)
