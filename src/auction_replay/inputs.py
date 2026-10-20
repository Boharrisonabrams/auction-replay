"""Shared input vocabulary: league rules, auction picks, players, and checked parsing.

Read this module first. Every other engine module raises InputError for a named evidence
gap and uses these helpers to turn raw text into checked values. The engine modules
import each helper under its former underscore name, such as integer as _integer, so the
code moved out of replay_auction.py reads exactly as it did there.
"""

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DEF"})


class InputError(ValueError):
    """A named evidence gap prevents the affected calculation."""


@dataclass(frozen=True)
class LeagueRules:
    season: int = 2025
    draft_at: str = "2025-09-03T19:15:00-07:00"
    teams: int = 14
    budget: int = 200
    roster_size: int = 14
    starters: tuple = ("QB", "WR", "WR", "RB", "RB", "TE", "FLEX", "K", "DEF")
    first_week: int = 1
    last_week: int = 17
    # Empty scoring permits transaction reconstruction, never forecast ingestion.
    scoring: tuple = ()


@dataclass(frozen=True)
class AuctionPick:
    pick: int
    player_id: str
    name: str
    position: str
    salary: int
    team: str
    keeper: bool


@dataclass(frozen=True)
class Player:
    player_id: str
    name: str
    position: str
    nfl_team: str
    bye: int
    projected_points: Decimal


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"missing {field}")
    return value.strip()


def integer(value, field, minimum=0, maximum=None):
    if isinstance(value, bool) or not str(value).isdigit():
        raise InputError(f"invalid integer {field}: {value!r}")
    number = int(value)
    if number < minimum or (maximum is not None and number > maximum):
        raise InputError(f"out-of-range {field}: {number}")
    return number


def decimal(value, field):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise InputError(f"missing or invalid {field}: {value!r}") from None
    if not result.is_finite():
        raise InputError(f"non-finite {field}")
    return result


def timestamp(value, field):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise InputError(f"missing or invalid {field}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError(f"{field} requires a timezone")
    return parsed


def json_object(value):
    if isinstance(value, dict):
        return value
    try:
        with Path(value).open() as source:
            result = json.load(source)
    except (OSError, ValueError, TypeError) as error:
        raise InputError(f"unreadable JSON input: {error}") from None
    if not isinstance(result, dict):
        raise InputError("JSON input must be an object")
    return result


def rows(path, required):
    try:
        with Path(path).open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)):
                raise InputError(f"duplicate CSV columns in {path}")
            missing = set(required) - set(fields)
            if missing:
                raise InputError(f"missing CSV fields in {path}: {sorted(missing)}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        raise InputError(f"unreadable data source {path}: {error}") from None
    if not rows:
        raise InputError(f"empty data source: {path}")
    if any(None in row for row in rows):
        raise InputError(f"malformed CSV row in {path}")
    return rows
