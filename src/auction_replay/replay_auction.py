"""Local auction replay inputs, kept separate from realized player production.

Normalized forecasts: provider_id,name,position,nfl_team,bye,projected_points.
Points cover the NFL's 17 scheduled games, scored using the explicit league rules.
Reference values: provider_id,reference_value (original whole or fractional dollars).
Weekly outcomes: player_id,week,points,status; status is verified or missing.

Each normalized source has a JSON manifest: url, season, published_at,
retrieved_at, sha256 (normalized file bytes), scoring_coverage (rule keys),
scoring_hash, identity_mappings ([{provider_id, player_id}]), and local_use.
Preseason manifests also declare includes_undrafted=true. Reference manifests
record source_scoring and source_format descriptions instead of league scoring
coverage/hash, because their original values are rebased later. Publisher dates and
coverage are source claims, not proof that a historical page was never revised.
Keep original snapshots and their hashes with collection notes in data/local/.
"""

import argparse
import csv
import hashlib
import json
import shlex
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from functools import lru_cache
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from statistics import median
from time import perf_counter
from tempfile import NamedTemporaryFile, TemporaryFile
from unicodedata import category
from urllib.parse import urlparse

POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DEF"})
DEFAULT_RELAXATION_LIMIT = 2000000


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


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"missing {field}")
    return value.strip()


def _integer(value, field, minimum=0, maximum=None):
    if isinstance(value, bool) or not str(value).isdigit():
        raise InputError(f"invalid integer {field}: {value!r}")
    number = int(value)
    if number < minimum or (maximum is not None and number > maximum):
        raise InputError(f"out-of-range {field}: {number}")
    return number


def _decimal(value, field):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise InputError(f"missing or invalid {field}: {value!r}") from None
    if not result.is_finite():
        raise InputError(f"non-finite {field}")
    return result


def _timestamp(value, field):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise InputError(f"missing or invalid {field}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError(f"{field} requires a timezone")
    return parsed


def _json(value):
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


def _rows(path, required):
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
    crosswalk = {}
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


@dataclass(frozen=True)
class TeamState:
    name: str
    roster: tuple
    budget: int


@dataclass(frozen=True)
class AuctionState:
    teams: tuple
    sales: tuple = ()

    @property
    def owned(self):
        return frozenset(player_id for team in self.teams for player_id in team.roster)

    def team(self, name):
        return next(team for team in self.teams if team.name == name)


@dataclass(frozen=True)
class Nomination:
    pick: int
    player_id: str
    state: AuctionState


@dataclass(frozen=True)
class MarketMoment:
    nomination: Nomination
    static: tuple
    inflation: tuple
    prior_ratios: tuple
    warnings: tuple


def apply_sale(state, sale, rules):
    """Record an observed purchase without repairing historical position errors."""
    team = state.team(sale.team)
    if sale.player_id in state.owned:
        raise InputError(f"player already owned: {sale.player_id}")
    if len(team.roster) >= rules.roster_size or sale.salary > team.budget:
        raise InputError(f"observed purchase exceeds roster or budget: {sale.pick}")
    updated = TeamState(team.name, team.roster + (sale.player_id,), team.budget - sale.salary)
    return AuctionState(
        tuple(updated if t.name == team.name else t for t in state.teams),
        state.sales if sale.keeper else state.sales + (sale,),
    )


def initial_state(picks, rules):
    state = AuctionState(
        tuple(TeamState(name, (), rules.budget) for name in sorted({p.team for p in picks}))
    )
    for keeper in sorted((p for p in picks if p.keeper), key=lambda p: p.player_id):
        state = apply_sale(state, keeper, rules)
    return state


def replay_states(picks, rules):
    """Expose only known keepers and completed sales, then apply each observed sale."""
    state = initial_state(picks, rules)
    for sale in picks:
        if not sale.keeper:
            yield Nomination(sale.pick, sale.player_id, state)
            state = apply_sale(state, sale, rules)


def final_state(picks, rules):
    state = initial_state(picks, rules)
    for sale in picks:
        if not sale.keeper:
            state = apply_sale(state, sale, rules)
    return state


def missing_starters(roster, players, rules):
    """Fill fixed slots before FLEX; each owned player can fill only one slot."""
    counts = Counter(players[player_id].position for player_id in roster)
    missing = []
    for slot in rules.starters:
        if slot != "FLEX":
            if counts[slot]:
                counts[slot] -= 1
            else:
                missing.append(slot)
    flex_needed = rules.starters.count("FLEX")
    missing.extend(["FLEX"] * max(0, flex_needed - sum(counts[p] for p in ("RB", "WR", "TE"))))
    return tuple(missing)


def _covers(positions, needs):
    counts = Counter(positions)
    for slot in needs:
        if slot != "FLEX":
            if not counts[slot]:
                return False
            counts[slot] -= 1
    return sum(counts[p] for p in ("RB", "WR", "TE")) >= needs.count("FLEX")


def legal_capacity(team, nominee, players, available, rules):
    """Return the shared maximum legal bid and a distinct structural rejection."""
    slots = rules.roster_size - len(team.roster)
    if slots <= 0:
        return 0, "full roster"
    if nominee not in available or nominee in team.roster:
        return 0, "player unavailable"
    capacity = team.budget - (slots - 1)
    if capacity < 1:
        return 0, "insufficient reserve"
    remaining = set(available) - {nominee}
    needs = missing_starters(team.roster + (nominee,), players, rules)
    if (
        len(needs) > slots - 1
        or len(remaining) < slots - 1
        or not _covers((players[key].position for key in remaining), needs)
    ):
        return 0, "positional infeasibility"
    return capacity, None


def reference_pool(state, players, values, rules, include_owned=False):
    """Select the highest-valued remaining pool with distinct starter coverage.

    Known keepers count toward each team's fixed slots before residual FLEX
    needs. Already-full historical rosters need no further pool allocation;
    callers still report any unfilled starters on those rosters separately. If
    an observed team has too few slots to complete starters, its remaining slots
    count as unrestricted demand. Its infeasibility must not erase other teams'
    decision coverage; both baselines attach an explicit warning for this case.
    """
    missing = set(players) - values.keys()
    if missing or state.owned - players.keys():
        raise InputError(
            f"reference universe coverage missing: {sorted(missing | (state.owned - players.keys()))}"
        )
    needs = []
    slots = 0
    for team in state.teams:
        open_slots = rules.roster_size - len(team.roster)
        required = missing_starters(team.roster, players, rules)
        if open_slots and len(required) <= open_slots:
            needs.extend(required)
        slots += open_slots
    candidates = sorted(set(players) - state.owned, key=lambda key: (-values[key], key))
    if len(candidates) < slots or not _covers((players[key].position for key in candidates), needs):
        raise InputError("reference pool has insufficient roster or starter coverage")
    selected = set()
    # Position quotas are disjoint; only FLEX can share a position category.
    for slot in [slot for slot in needs if slot != "FLEX"] + ["FLEX"] * needs.count("FLEX"):
        selected.add(
            next(
                key
                for key in candidates
                if key not in selected
                and (
                    players[key].position in {"RB", "WR", "TE"}
                    if slot == "FLEX"
                    else players[key].position == slot
                )
            )
        )
    for key in candidates:
        if len(selected) >= slots:
            break
        selected.add(key)
    if include_owned:
        selected.update(state.owned)
    return tuple(sorted(selected))


def _rescale(values, available, pool, discretionary):
    excess = {key: max(Decimal(0), values[key] - 1) for key in available}
    denominator = sum((excess[key] for key in pool), Decimal(0))
    if denominator == 0:
        return {key: Decimal(1) for key in sorted(available)}, (
            "zero discretionary denominator; $1-only estimate",
        )
    scale = Decimal(max(0, discretionary)) / denominator
    return {key: Decimal(1) + excess[key] * scale for key in sorted(available)}, ()


def _pool_warnings(state, players, rules):
    return tuple(
        f"{team.name}: historical starter coverage impossible; remaining market slots unrestricted"
        for team in state.teams
        if len(missing_starters(team.roster, players, rules)) > rules.roster_size - len(team.roster)
    )


def rebase_reference(state, players, source_values, rules):
    pool = reference_pool(state, players, source_values, rules, include_owned=True)
    estimates, warnings = _rescale(
        source_values, set(players), pool, rules.teams * (rules.budget - rules.roster_size)
    )
    return estimates, warnings + _pool_warnings(state, players, rules)


def inflation_prices(state, players, static_values, rules):
    """Rescale spendable cash: full-roster teams cannot contribute further bids."""
    pool = reference_pool(state, players, static_values, rules)
    slots = sum(rules.roster_size - len(team.roster) for team in state.teams)
    discretionary = (
        sum(team.budget for team in state.teams if len(team.roster) < rules.roster_size) - slots
    )
    if discretionary < 0:
        raise InputError("league cannot reserve $1 per remaining roster place")
    estimates, warnings = _rescale(static_values, set(players) - state.owned, pool, discretionary)
    return estimates, warnings + _pool_warnings(state, players, rules)


def baseline_ceiling(values, team, nominee, players, available, rules):
    capacity, reason = legal_capacity(team, nominee, players, available, rules)
    if reason:
        return 0, reason
    if nominee not in values:
        raise InputError(f"missing baseline estimate: {nominee}")
    return min(capacity, max(1, int(values[nominee].to_integral_value(rounding=ROUND_FLOOR)))), None


def market_adjustment(prior_ratios):
    if any(ratio is None for ratio in prior_ratios):
        raise InputError("prior market estimate unavailable; pooled adjustment unresolved")
    count = len(prior_ratios)
    return (
        Decimal(1)
        if not count
        else Decimal(1) + Decimal(count) / (count + 20) * (median(prior_ratios) - 1)
    )


def future_prices(inflation, prior_ratios, multiplier=Decimal(1)):
    multiplier = _decimal(multiplier, "future-price multiplier")
    if multiplier <= 0:
        raise InputError("future-price multiplier must be positive")
    adjustment = market_adjustment(prior_ratios)
    return {
        key: max(
            1, int((value * adjustment * multiplier).to_integral_value(rounding=ROUND_CEILING))
        )
        for key, value in sorted(inflation.items())
    }


def _validate_auction_forecasts(picks, players):
    missing = {pick.player_id for pick in picks} - players.keys()
    if missing:
        raise InputError(f"missing auction players from forecast universe: {sorted(missing)}")
    for pick in picks:
        if pick.position != players[pick.player_id].position:
            raise InputError(f"auction/forecast position mismatch: {pick.player_id}")


def replay_markets(picks, players, source_values, rules):
    """Freeze uncapped market predictions before revealing each closing price.

    Empty inflation estimates and named warnings preserve a failed pool as a
    visible gap. A missing previous prediction also blocks the pooled forecast;
    no sale is silently dropped from its history.
    """
    _validate_auction_forecasts(picks, players)
    static, static_warnings = rebase_reference(
        initial_state(picks, rules), players, source_values, rules
    )
    prior_ratios = ()
    previous_prediction = None
    for nomination in replay_states(picks, rules):
        if nomination.state.sales:
            actual = nomination.state.sales[-1].salary
            prior_ratios += (
                None if previous_prediction is None else Decimal(actual) / previous_prediction,
            )
        warnings = static_warnings
        try:
            inflation, pool_warnings = inflation_prices(nomination.state, players, static, rules)
            warnings += pool_warnings
        except InputError as error:
            inflation = {}
            warnings += (str(error),)
        previous_prediction = None
        if inflation:
            try:
                previous_prediction = future_prices(inflation, prior_ratios)[nomination.player_id]
            except InputError as error:
                warnings += (str(error),)
        yield MarketMoment(
            nomination,
            tuple(sorted(static.items())),
            tuple(sorted(inflation.items())),
            prior_ratios,
            warnings,
        )


@dataclass(frozen=True)
class RosterBound:
    lower: Decimal | None
    upper: Decimal | None
    roster: tuple | None
    cost: int | None  # Future additions only; fixed ownership is already paid.
    status: str
    reason: str | None


@dataclass(frozen=True)
class BudgetFrontier:
    bounds: tuple  # Index is the budget available for future additions.
    nodes: int
    work_limit: int
    exhausted: bool
    relaxation_transitions: int = 0
    relaxation_limit: int | None = None
    relaxation_complete: bool = False
    relaxation_fallback: str | None = None

    @property
    def complete(self):
        return all(bound.status != "unresolved" for bound in self.bounds)


@dataclass(frozen=True)
class PositionalFrontier:
    entries: tuple  # Budget -> (raw millionth score, future cost, roster), or None.
    transitions: int
    transition_limit: int | None
    complete: bool
    fallback: str | None


@dataclass(frozen=True)
class PriceComparison:
    price: int
    buy: RosterBound
    passing: RosterBound
    decision: str
    reason: str


@dataclass(frozen=True)
class NomineeComparison:
    capacity: int
    reason: str | None
    buy: BudgetFrontier | None
    passing: BudgetFrontier | None
    prices: tuple

    @property
    def supported_ceiling(self):
        return max((row.price for row in self.prices if row.decision == "buy"), default=0)

    @property
    def possible_ceiling(self):
        return max(
            (row.price for row in self.prices if row.decision in {"buy", "unresolved"}), default=0
        )


@dataclass(frozen=True)
class NomineeScenario:
    name: str
    price_factor: Decimal
    forecast_factor: Decimal
    absent_weeks: tuple
    comparison: NomineeComparison


def _forecast_weights(players, rules, nominee, forecast_factor, absent_weeks):
    factor = _decimal(forecast_factor, "nominee forecast factor")
    if factor < 0:
        raise InputError("nominee forecast factor must be nonnegative")
    if nominee is not None and nominee not in players:
        raise InputError(f"unknown nominee: {nominee}")
    if (
        not rules.starters
        or any(slot not in POSITIONS | {"FLEX"} for slot in rules.starters)
        or not 1 <= rules.first_week <= rules.last_week <= 17
        or len(rules.starters) > rules.roster_size
    ):
        raise InputError("incompatible objective roster or week rules")
    weeks = tuple(
        _integer(week, "absence week", rules.first_week, rules.last_week) for week in absent_weeks
    )
    if len(set(weeks)) != len(weeks):
        raise InputError("duplicate absence week")
    if weeks and (nominee is None or players[nominee].bye in weeks):
        raise InputError("nominee absences must name non-bye weeks")
    weights = {}
    for key, player in players.items():
        if key != player.player_id or player.position not in POSITIONS:
            raise InputError(f"invalid forecast identity or position: {key}")
        _integer(player.bye, "forecast bye", 1, 18)
        weights[key] = _decimal(player.projected_points, "projected points") * (
            factor if key == nominee else 1
        )
    return weights, weeks


def _projected_lineup(roster, players, weights, rules, week, nominee, absent_weeks):
    available = sorted(
        (
            key
            for key in roster
            if players[key].bye != week
            and weights[key] > 0
            and not (key == nominee and week in absent_weeks)
        ),
        key=lambda key: (-weights[key], key),
    )
    lineup = [None] * len(rules.starters)
    used = set()
    # Fixed positions are disjoint. Take their best players before assigning FLEX.
    for index in sorted(range(len(rules.starters)), key=lambda i: rules.starters[i] == "FLEX"):
        slot = rules.starters[index]
        key = next(
            (
                key
                for key in available
                if key not in used
                and (
                    players[key].position in {"RB", "WR", "TE"}
                    if slot == "FLEX"
                    else players[key].position == slot
                )
            ),
            None,
        )
        lineup[index] = key
        if key is not None:
            used.add(key)
    return tuple(lineup)


def projected_lineup(
    roster, players, rules, week, nominee=None, forecast_factor=Decimal(1), absent_weeks=()
):
    """Return IDs aligned with starter slots, using only forecasts and known byes.

    Empty slots score zero; a manager may bench a nonpositive forecast. Equal
    forecasts use stable player IDs. A player never occupies two starter slots.
    """
    if len(set(roster)) != len(roster) or set(roster) - players.keys():
        raise InputError("duplicate or unknown roster player")
    week = _integer(week, "lineup week", rules.first_week, rules.last_week)
    weights, weeks = _forecast_weights(players, rules, nominee, forecast_factor, absent_weeks)
    return _projected_lineup(roster, players, weights, rules, week, nominee, weeks)


def _projected_total(roster, players, weights, rules, nominee, absent_weeks):
    # Sum the season-projection numerators before dividing, avoiding 17 repeated
    # divisions. Each scheduled game contributes projection / 17; a bye is zero.
    return (
        sum(
            (
                weights[key]
                for week in range(rules.first_week, rules.last_week + 1)
                for key in _projected_lineup(
                    roster, players, weights, rules, week, nominee, absent_weeks
                )
                if key is not None
            ),
            Decimal(0),
        )
        / 17
    )


def projected_total(
    roster, players, rules, nominee=None, forecast_factor=Decimal(1), absent_weeks=()
):
    if len(set(roster)) != len(roster) or set(roster) - players.keys():
        raise InputError("duplicate or unknown roster player")
    weights, weeks = _forecast_weights(players, rules, nominee, forecast_factor, absent_weeks)
    return _projected_total(roster, players, weights, rules, nominee, weeks)


def _prune_positional(table):
    """For equal roster counts, more cost with no score gain is dominated."""
    result, best = {}, {}
    for (count, cost), value in sorted(table.items()):
        if value[0] > best.get(count, -1):
            result[count, cost] = value
            best[count] = value[0]
    return result


def positional_frontier(
    fixed,
    candidates,
    prices,
    players,
    rules,
    max_budget,
    nominee=None,
    forecast_factor=Decimal(1),
    bench_credit=Decimal(0),
    transition_limit=None,
):
    """Return raw millionth scores for the complete-roster no-bye objective.

    With zero bench credit, a completed frontier supplies the maximum possible
    starter numerator at each budget. Partial results are feasible seeds only,
    never upper bounds or infeasibility proofs. Each examined player inclusion
    and positional-table combination counts as one transition, including those
    rejected by cost or count. None leaves the historical pilot uncapped.
    """
    if len(set(fixed)) != len(fixed) or len(set(candidates)) != len(candidates):
        raise InputError("duplicate completion identity")
    fixed, candidates = set(fixed), set(candidates)
    if (
        fixed & candidates
        or (fixed | candidates) - players.keys()
        or len(fixed) > rules.roster_size
    ):
        raise InputError("invalid completion identities")
    max_budget = _integer(max_budget, "budget")
    if set(candidates) - prices.keys():
        raise InputError("missing future prices")
    costs = {k: _integer(prices[k], "future price", 1) for k in candidates}
    costs.update({k: 0 for k in fixed})
    weights, _ = _forecast_weights(players, rules, nominee, forecast_factor, ())
    if bench_credit not in (Decimal(0), Decimal(".125"), Decimal(".25")):
        raise InputError("unsupported bench-credit sensitivity")
    transition_limit = (
        None
        if transition_limit is None
        else _integer(transition_limit, "relaxation transition limit")
    )
    fallback = None
    # Preserve the pilot's integer-millionth and backup-credit arithmetic.
    if any((v * 1000000) != (v * 1000000).to_integral_value() for v in weights.values()):
        fallback = "pilot requires at most six decimal places"
    points = {k: max(0, int(v * 1000000)) for k, v in weights.items()}
    quotas = Counter(slot for slot in rules.starters if slot != "FLEX")
    if rules.starters.count("FLEX") > 1:
        fallback = "pilot supports at most one FLEX"
    if fallback:
        return PositionalFrontier((None,) * (max_budget + 1), 0, transition_limit, False, fallback)
    # An absent FLEX category must still enforce its quota through an empty table.
    positions = sorted(
        {p.position for p in players.values()}
        | set(quotas)
        | ({"RB", "WR", "TE"} if "FLEX" in rules.starters else set())
    )
    best = [None] * (max_budget + 1)
    tables = {}
    flexes = ("RB", "WR", "TE") if "FLEX" in rules.starters else (None,)
    transitions = 0

    class Cutoff(Exception):
        pass

    def transition():
        nonlocal transitions
        if transition_limit is not None and transitions >= transition_limit:
            raise Cutoff
        transitions += 1

    try:
        for flex in flexes:
            required = dict(quotas)
            if flex:
                required[flex] = required.get(flex, 0) + 1
            total = {(0, 0): (0, ())}
            for pos in positions:
                quota = required.get(pos, 0)
                if (pos, quota) not in tables:
                    group = sorted(
                        (k for k in fixed | candidates if players[k].position == pos),
                        key=lambda k: (-points[k], k),
                    )
                    # Use base quotas so cached tables remain valid across FLEX assignments.
                    limit = rules.roster_size - sum(
                        max(quotas.get(other, 0), sum(players[k].position == other for k in fixed))
                        for other in positions
                        if other != pos
                    )
                    table = {(0, 0): (0, ())}
                    for k in group:
                        next_table = {} if k in fixed else table.copy()
                        for (count, cost), (score, roster) in table.items():
                            transition()
                            new = (count + 1, cost + costs[k])
                            if new[0] > limit or new[1] > max_budget:
                                continue
                            backup = (
                                int(points[k] * bench_credit)
                                if count == quota and pos in {"QB", "RB", "WR", "TE"}
                                else 0
                            )
                            value = (
                                score + (points[k] if count < quota else backup),
                                roster + (k,),
                            )
                            old = next_table.get(new)
                            if (
                                old is None
                                or value[0] > old[0]
                                or (value[0] == old[0] and value[1] < old[1])
                            ):
                                next_table[new] = value
                        table = next_table
                    tables[pos, quota] = _prune_positional(
                        {key: value for key, value in table.items() if key[0] >= quota}
                    )
                next_total = {}
                for (n1, c1), (s1, r1) in total.items():
                    for (n2, c2), (s2, r2) in tables[pos, quota].items():
                        transition()
                        key = n1 + n2, c1 + c2
                        if key[0] > rules.roster_size or key[1] > max_budget:
                            continue
                        value = s1 + s2, r1 + r2
                        old = next_total.get(key)
                        if (
                            old is None
                            or value[0] > old[0]
                            or (value[0] == old[0] and value[1] < old[1])
                        ):
                            next_total[key] = value
                total = _prune_positional(next_total)
            for (count, cost), (score, roster) in total.items():
                if count != rules.roster_size:
                    continue
                value = (score, cost, tuple(sorted(roster)))
                old = best[cost]
                if old is None or (-value[0], value[1:]) < (-old[0], old[1:]):
                    best[cost] = value
    except Cutoff:
        fallback = "relaxation transition limit reached; partial frontier is not an upper bound"
    for budget in range(1, max_budget + 1):
        old, new = best[budget - 1], best[budget]
        if old is not None and (new is None or (-old[0], old[1:]) < (-new[0], new[1:])):
            best[budget] = old
    return PositionalFrontier(
        tuple(best), transitions, transition_limit, fallback is None, fallback
    )


def completion_frontier(
    fixed,
    candidates,
    prices,
    players,
    rules,
    max_budget,
    work_limit=2000,
    nominee=None,
    forecast_factor=Decimal(1),
    absent_weeks=(),
    relaxation_limit=DEFAULT_RELAXATION_LIMIT,
    timings=None,
):
    """Bound complete-roster production at every integer completion budget.

    Search nodes and positional-relaxation transitions have separate limits.
    A completed no-bye relaxation seeds weekly incumbents and bounds each budget;
    partial or unsupported relaxation inputs retain the generic search bound.
    Pending nodes retain both bounds and never become infeasible just at cutoff.
    Optional timings are separate diagnostics, excluded from proof equality.
    """
    started = perf_counter() if timings is not None else None
    max_budget = _integer(max_budget, "completion budget")
    work_limit = _integer(work_limit, "search work limit", 1)
    relaxation_limit = _integer(relaxation_limit, "relaxation transition limit")
    fixed, candidates = tuple(fixed), tuple(candidates)
    if (
        len(set(fixed)) != len(fixed)
        or len(set(candidates)) != len(candidates)
        or set(fixed) & set(candidates)
        or (set(fixed) | set(candidates)) - players.keys()
    ):
        raise InputError("duplicate, overlapping, or unknown completion players")
    if len(fixed) > rules.roster_size:
        raise InputError("fixed roster exceeds roster size")
    if set(candidates) - prices.keys():
        raise InputError(f"missing future prices: {sorted(set(candidates) - prices.keys())}")
    costs = {key: _integer(prices[key], f"future price for {key}", 1) for key in candidates}
    weights, weeks = _forecast_weights(players, rules, nominee, forecast_factor, absent_weeks)
    candidates = tuple(sorted(candidates, key=lambda key: (-weights[key], key)))
    lower, rosters, spending = (
        [None] * (max_budget + 1),
        [None] * (max_budget + 1),
        [None] * (max_budget + 1),
    )

    def record(roster, cost):
        score = _projected_total(roster, players, weights, rules, nominee, weeks)
        frozen = tuple(sorted(roster))
        for budget in range(cost, max_budget + 1):
            if (
                lower[budget] is None
                or score > lower[budget]
                or (score == lower[budget] and (cost, frozen) < (spending[budget], rosters[budget]))
            ):
                lower[budget], rosters[budget], spending[budget] = score, frozen, cost

    # Both branches first construct a cheap feasible incumbent. This does not
    # assert optimality; the same capped node search supplies the upper bounds.
    needs = missing_starters(fixed, players, rules)
    cheapest = sorted(candidates, key=lambda key: (costs[key], key))
    seed = list(fixed)
    for slot in sorted(needs, key=lambda slot: slot == "FLEX"):
        key = next(
            (
                key
                for key in cheapest
                if key not in seed
                and (
                    players[key].position in {"RB", "WR", "TE"}
                    if slot == "FLEX"
                    else players[key].position == slot
                )
            ),
            None,
        )
        if key is not None:
            seed.append(key)
    for key in cheapest:
        if len(seed) >= rules.roster_size:
            break
        if key not in seed:
            seed.append(key)
    if len(seed) == rules.roster_size and not missing_starters(seed, players, rules):
        record(tuple(seed), sum(costs[key] for key in seed if key not in fixed))

    initial_upper = _projected_total(fixed + candidates, players, weights, rules, nominee, weeks)
    relaxation_players = {key: players[key] for key in fixed + candidates}
    relaxation = positional_frontier(
        fixed,
        candidates,
        costs,
        relaxation_players,
        rules,
        max_budget,
        nominee if nominee in relaxation_players else None,
        forecast_factor,
        transition_limit=relaxation_limit,
    )
    root_upper = [initial_upper] * (max_budget + 1)
    seen_seeds = set()
    for budget, entry in enumerate(relaxation.entries):
        if entry is not None:
            raw, cost, roster = entry
            if roster not in seen_seeds:
                record(roster, cost)
                seen_seeds.add(roster)
            if relaxation.complete:
                # Every weekly lineup is bounded by the same roster's best
                # no-bye lineup. Do not use the pilot's rounded 16/17 score.
                maximum = Decimal(raw) / 1000000
                root_upper[budget] = min(
                    initial_upper, (rules.last_week - rules.first_week + 1) * maximum / 17
                )
        elif relaxation.complete:
            root_upper[budget] = None  # Only a completed relaxation can prove this.
    search_started = perf_counter() if timings is not None else None
    stack = [(0, fixed, 0, 0, initial_upper)]
    nodes = 0
    # ponytail: exponential subset search with a bounded positional relaxation;
    # add tighter per-node bounds only if measured unresolved rates require them.
    while stack and nodes < work_limit:
        index, roster, cost, _, inherited_upper = stack.pop()
        nodes += 1
        slots = rules.roster_size - len(roster)
        remaining = candidates[index:]
        needs = missing_starters(roster, players, rules)
        if (
            len(remaining) < slots
            or len(needs) > slots
            or not _covers((players[key].position for key in remaining), needs)
        ):
            continue
        minimum = cost + sum(sorted(costs[key] for key in remaining)[:slots])
        if minimum > max_budget:
            continue
        # Owning every remaining player relaxes both cost and roster-size limits.
        upper = min(
            inherited_upper,
            _projected_total(roster + remaining, players, weights, rules, nominee, weeks),
        )
        if all(
            root_upper[budget] is None
            or (lower[budget] is not None and lower[budget] >= min(upper, root_upper[budget]))
            for budget in range(minimum, max_budget + 1)
        ):
            continue
        if not slots:
            record(roster, cost)
            continue
        key = candidates[index]
        # LIFO visits the higher-forecast inclusion first; stable IDs break ties.
        stack.append((index + 1, roster, cost, minimum, upper))
        added_cost = cost + costs[key]
        stack.append(
            (index + 1, roster + (key,), added_cost, max(minimum, added_cost + slots - 1), upper)
        )
    upper = lower.copy()
    for _, _, _, minimum, pending_upper in stack:
        for budget in range(minimum, max_budget + 1):
            if root_upper[budget] is not None:
                bound = min(pending_upper, root_upper[budget])
                upper[budget] = bound if upper[budget] is None else max(upper[budget], bound)
    bounds = []
    for budget, (lo, hi) in enumerate(zip(lower, upper)):
        status = "infeasible" if hi is None else "optimal" if lo == hi else "unresolved"
        reason = (
            "no feasible complete roster"
            if status == "infeasible"
            else "search work limit; no feasible incumbent"
            if lo is None
            else "search work limit; bounds overlap"
            if status == "unresolved"
            else None
        )
        bounds.append(RosterBound(lo, hi, rosters[budget], spending[budget], status, reason))
    if timings is not None:
        finished = perf_counter()
        timings.update(
            preprocessing_seconds=search_started - started,
            search_seconds=finished - search_started,
            total_seconds=finished - started,
        )
    return BudgetFrontier(
        tuple(bounds),
        nodes,
        work_limit,
        bool(stack),
        relaxation.transitions,
        relaxation_limit,
        relaxation.complete,
        relaxation.fallback,
    )


def compare_nominee(
    nomination,
    team_name,
    players,
    prices,
    rules,
    work_limit=2000,
    forecast_factor=Decimal(1),
    absent_weeks=(),
    relaxation_limit=DEFAULT_RELAXATION_LIMIT,
):
    """Solve each branch once, then compare all legal purchase prices."""
    state, nominee = nomination.state, nomination.player_id
    if nominee not in players or state.owned - players.keys():
        raise InputError("unknown nominee or owned forecast player")
    team = state.team(team_name)
    available = set(players) - state.owned
    capacity, reason = legal_capacity(team, nominee, players, available, rules)
    if reason:
        return NomineeComparison(capacity, reason, None, None, ())
    candidates = available - {nominee}
    arguments = dict(
        prices=prices,
        players=players,
        rules=rules,
        max_budget=team.budget,
        work_limit=work_limit,
        nominee=nominee,
        forecast_factor=forecast_factor,
        absent_weeks=absent_weeks,
        relaxation_limit=relaxation_limit,
    )
    buy = completion_frontier(team.roster + (nominee,), candidates, **arguments)
    passing = completion_frontier(team.roster, candidates, **arguments)
    return _compare_frontiers(capacity, team.budget, buy, passing)


def _compare_frontiers(capacity, budget, buy, passing):
    rows = []
    for price in range(1, capacity + 1):
        bought, passed = buy.bounds[budget - price], passing.bounds[budget]
        if bought.upper is None:
            decision, why = (
                ("infeasible", "neither branch can complete the roster")
                if passed.upper is None
                else ("pass", "buy branch cannot complete the roster")
                if passed.lower is not None
                else ("unresolved", "buy completion infeasible; pass feasibility unresolved")
            )
        elif bought.lower is not None and (passed.upper is None or bought.lower > passed.upper):
            decision, why = "buy", "buy lower bound exceeds pass upper bound"
        elif passed.lower is not None and bought.upper <= passed.lower:
            decision, why = (
                "pass",
                "buy upper bound does not exceed pass lower bound; equality passes",
            )
        else:
            decision, why = (
                "unresolved",
                "search work limit; comparison bounds overlap or lack a feasible incumbent",
            )
        rows.append(PriceComparison(price, bought, passed, decision, why))
    return NomineeComparison(capacity, None, buy, passing, tuple(rows))


def nominee_scenarios(
    moment, team_name, players, rules, work_limit=2000, relaxation_limit=DEFAULT_RELAXATION_LIMIT
):
    """Cross three performance cases with 0.8/1.0/1.2 future-price stresses.

    The absence protocol predeclares the first two non-bye evaluation weeks.
    These cases are sensitivity assumptions, without injury probabilities.
    """
    nominee = moment.nomination.player_id
    if nominee not in players:
        raise InputError(f"unknown nominee: {nominee}")
    weeks = tuple(
        week
        for week in range(rules.first_week, rules.last_week + 1)
        if week != players[nominee].bye
    )[:2]
    if len(weeks) != 2:
        raise InputError("two non-bye sensitivity weeks are unavailable")
    cases = (
        ("neutral", Decimal(1), ()),
        ("forecast_minus_20_percent", Decimal("0.8"), ()),
        ("two_non_bye_absences", Decimal(1), weeks),
    )
    result = []
    for price_factor in (Decimal("0.8"), Decimal(1), Decimal("1.2")):
        prices = future_prices(dict(moment.inflation), moment.prior_ratios, price_factor)
        neutral = compare_nominee(
            moment.nomination,
            team_name,
            players,
            prices,
            rules,
            work_limit,
            relaxation_limit=relaxation_limit,
        )
        for name, factor, absences in cases:
            comparison = neutral
            if name != "neutral" and neutral.reason is None:
                team = moment.nomination.state.team(team_name)
                candidates = set(players) - moment.nomination.state.owned - {nominee}
                buy = completion_frontier(
                    team.roster + (nominee,),
                    candidates,
                    prices,
                    players,
                    rules,
                    team.budget,
                    work_limit,
                    nominee,
                    factor,
                    absences,
                    relaxation_limit,
                )
                # Passing excludes the nominee; only the price factor changes its frontier.
                comparison = _compare_frontiers(neutral.capacity, team.budget, buy, neutral.passing)
            result.append(NomineeScenario(name, price_factor, factor, absences, comparison))
    return tuple(result)


# Outcome columns are appended only after the recommendation spool is frozen.
EVALUATION_FIELDS = ("buy_evaluation", "pass_evaluation")
DECISION_FIELDS = tuple(
    "pick player_id player_name team budget held_roster room_state state_sha256 price scenario "
    "price_factor forecast_factor absent_weeks capacity source_reference static_estimate inflation_estimate "
    "static_ceiling inflation_ceiling static_action inflation_action roster_action static_reason inflation_reason reason "
    "neutral_supported_ceiling neutral_possible_ceiling scenario_supported_min scenario_supported_max "
    "scenario_possible_min scenario_possible_max scenario_disagreement price_disagreement "
    "scenario_supported_ceiling scenario_possible_ceiling prior_ratios warnings work_limit "
    "buy_lower buy_upper buy_roster buy_future_cost buy_total_cost buy_status buy_reason buy_nodes buy_exhausted "
    "pass_lower pass_upper pass_roster pass_future_cost pass_total_cost pass_status pass_reason pass_nodes pass_exhausted "
    "buy_relaxation_transitions buy_relaxation_limit buy_relaxation_complete buy_relaxation_fallback "
    "pass_relaxation_transitions pass_relaxation_limit pass_relaxation_complete pass_relaxation_fallback".split()
)


def canonical_bytes(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=lambda item: str(item) if isinstance(item, Decimal) else asdict(item),
    ).encode()


def policy_action(price, ceiling, bought, passed):
    """Keep price-policy intent separate from a witnessed executable completion."""
    chosen = bought if price <= ceiling else passed
    action = "supported" if price <= ceiling else "pass"
    if chosen.roster is not None:
        return (
            action,
            "price within ceiling; feasible buy incumbent"
            if action == "supported"
            else "price exceeds ceiling; feasible pass incumbent",
        )
    if chosen.upper is not None:
        return "search-unresolved", "chosen branch has no feasible incumbent within search limit"
    if action == "supported" and passed.roster is not None:
        return "pass", "buy completion infeasible; feasible pass incumbent"
    if action == "supported" and passed.upper is not None:
        return "search-unresolved", "buy completion infeasible; pass feasibility unresolved"
    return "infeasible", "price policy has no executable completion"


def _structural_rejection(team, nominee, positions, rules):
    """Prove rejection from observed holdings, without inventing a future pool."""
    slots = rules.roster_size - len(team.roster)
    if slots <= 0:
        return "full roster"
    if team.budget < slots:
        return "insufficient reserve"
    if len(missing_starters(team.roster + (nominee,), positions, rules)) > slots - 1:
        return "insufficient starter slots after purchase"
    return None


def decision_rows(picks, rules, players=None, references=None, gaps=(), work_limit=2000):
    """Yield all team/nomination prices; retain at most one pair's nine frontiers."""
    work_limit = _integer(work_limit, "search work limit", 1)
    positions = {pick.player_id: pick for pick in picks}
    if players is None or references is None:
        moments = (
            MarketMoment(nomination, (), (), (), ()) for nomination in replay_states(picks, rules)
        )
    else:
        # Initial pool validation can fail before the generator yields any state.
        try:
            _validate_auction_forecasts(picks, players)
            rebase_reference(initial_state(picks, rules), players, references, rules)
        except InputError as error:
            gaps = tuple(gaps) + (str(error),)
            players = references = None
            moments = (
                MarketMoment(nomination, (), (), (), ())
                for nomination in replay_states(picks, rules)
            )
        else:
            moments = replay_markets(picks, players, references, rules)
    for moment in moments:
        nomination = moment.nomination
        state = nomination.state
        room = dict(
            teams=[asdict(team) for team in state.teams], completed_sale_count=len(state.sales)
        )
        state_hash = hashlib.sha256(canonical_bytes(asdict(state))).hexdigest()
        nominee = nomination.player_id
        if players is not None and references is not None:
            static = dict(moment.static)
            inflation = dict(moment.inflation)
            available = set(players) - state.owned
        for team in state.teams:
            base = dict(
                pick=nomination.pick,
                player_id=nominee,
                player_name=positions[nominee].name,
                team=team.name,
                budget=team.budget,
                held_roster=team.roster,
                room_state=room,
                state_sha256=state_hash,
                work_limit=work_limit,
                prior_ratios=moment.prior_ratios,
                warnings=moment.warnings,
            )
            reason = _structural_rejection(team, nominee, positions, rules)
            action = "infeasible" if reason else "missing-data"
            scenarios = None
            if reason is None and players is not None and references is not None:
                try:
                    static_ceiling, reason = baseline_ceiling(
                        static, team, nominee, players, available, rules
                    )
                    inflation_ceiling, reason2 = baseline_ceiling(
                        inflation, team, nominee, players, available, rules
                    )
                    reason = reason or reason2
                    if reason:
                        action = "infeasible"
                    else:
                        scenarios = nominee_scenarios(moment, team.name, players, rules, work_limit)
                        base.update(
                            source_reference=references[nominee],
                            static_estimate=static[nominee],
                            inflation_estimate=inflation[nominee],
                            static_ceiling=static_ceiling,
                            inflation_ceiling=inflation_ceiling,
                        )
                except InputError as error:
                    reason, action = str(error), "missing-data"
            if scenarios is None:
                reason = (
                    reason
                    or "; ".join(gaps)
                    or "accepted forecast and reference inputs unavailable"
                )
                yield dict(
                    base,
                    price=None,
                    reason=reason,
                    roster_action=action,
                    static_action=action,
                    inflation_action=action,
                )
                continue
            neutral = next(
                case for case in scenarios if case.name == "neutral" and case.price_factor == 1
            )
            supported = [case.comparison.supported_ceiling for case in scenarios]
            possible = [case.comparison.possible_ceiling for case in scenarios]
            price_disagreements = [
                len({case.comparison.prices[i].decision for case in scenarios}) > 1
                for i in range(neutral.comparison.capacity)
            ]
            base.update(
                capacity=neutral.comparison.capacity,
                neutral_supported_ceiling=neutral.comparison.supported_ceiling,
                neutral_possible_ceiling=neutral.comparison.possible_ceiling,
                scenario_supported_min=min(supported),
                scenario_supported_max=max(supported),
                scenario_possible_min=min(possible),
                scenario_possible_max=max(possible),
                scenario_disagreement=any(price_disagreements),
            )
            for scenario in scenarios:
                comparison = scenario.comparison
                for index, price in enumerate(comparison.prices):
                    static_action, static_reason = policy_action(
                        price.price, static_ceiling, price.buy, price.passing
                    )
                    inflation_action, inflation_reason = policy_action(
                        price.price, inflation_ceiling, price.buy, price.passing
                    )
                    row = dict(
                        base,
                        price=price.price,
                        scenario=scenario.name,
                        price_factor=scenario.price_factor,
                        forecast_factor=scenario.forecast_factor,
                        absent_weeks=scenario.absent_weeks,
                        scenario_supported_ceiling=comparison.supported_ceiling,
                        scenario_possible_ceiling=comparison.possible_ceiling,
                        price_disagreement=price_disagreements[index],
                        static_action=static_action,
                        static_reason=static_reason,
                        inflation_action=inflation_action,
                        inflation_reason=inflation_reason,
                        roster_action={"buy": "supported", "unresolved": "search-unresolved"}.get(
                            price.decision, price.decision
                        ),
                        reason=price.reason,
                    )
                    for branch, bound, frontier in (
                        ("buy", price.buy, comparison.buy),
                        ("pass", price.passing, comparison.passing),
                    ):
                        row.update(
                            {
                                branch + "_" + key: value
                                for key, value in asdict(bound).items()
                                if key != "cost"
                            }
                        )
                        row[branch + "_future_cost"] = bound.cost
                        row[branch + "_total_cost"] = (
                            None
                            if bound.cost is None
                            else bound.cost + (price.price if branch == "buy" else 0)
                        )
                        row[branch + "_nodes"] = frontier.nodes
                        row[branch + "_exhausted"] = frontier.exhausted
                        for field in (
                            "relaxation_transitions",
                            "relaxation_limit",
                            "relaxation_complete",
                            "relaxation_fallback",
                        ):
                            row[branch + "_" + field] = getattr(frontier, field)
                    yield row


def evaluate_roster(roster, players, rules, outcomes):
    """Evaluate a frozen roster with base preseason ordering and known byes.

    The optimistic score is unknown if any active eligible player lacks actuals;
    their potential contribution cannot be bounded by treating them as zero.
    Vacant positions stay vacant. No injuries, waiver pickups, or forecast stress
    assumptions alter the preselected lineup ordering during evaluation.
    """
    roster = tuple(roster)
    weights, _ = _forecast_weights(players, rules, None, Decimal(1), ())
    if len(roster) != len(set(roster)) or set(roster) - players.keys():
        raise InputError("duplicate or unknown evaluation roster player")
    fixed_total, hindsight_total = Decimal(0), Decimal(0)
    missing_selected, missing_hindsight, weeks = [], [], []
    for week in range(rules.first_week, rules.last_week + 1):
        lineup = _projected_lineup(roster, players, weights, rules, week, None, ())
        missing = [
            (key, week) for key in lineup if key is not None and outcomes.get((key, week)) is None
        ]
        missing_selected.extend(missing)
        fixed = (
            None
            if missing
            else sum((outcomes[(key, week)] for key in lineup if key is not None), Decimal(0))
        )
        if fixed is not None:
            fixed_total += fixed
        eligible = [
            key
            for key in roster
            if players[key].bye != week
            and any(
                players[key].position in {"RB", "WR", "TE"}
                if slot == "FLEX"
                else players[key].position == slot
                for slot in rules.starters
            )
        ]
        unknown = [(key, week) for key in eligible if outcomes.get((key, week)) is None]
        missing_hindsight.extend(unknown)
        hindsight_lineup, hindsight = None, None
        if not unknown:
            actual = {
                key: outcomes.get((key, week)) if key in eligible else Decimal(0) for key in roster
            }
            hindsight_lineup = _projected_lineup(roster, players, actual, rules, week, None, ())
            hindsight = sum(
                (actual[key] for key in hindsight_lineup if key is not None), Decimal(0)
            )
            hindsight_total += hindsight
        weeks.append(
            dict(
                week=week,
                fixed_preseason_lineup=lineup,
                fixed_preseason_points=fixed,
                optimistic_hindsight_lineup=hindsight_lineup,
                optimistic_hindsight_points=hindsight,
            )
        )
    return dict(
        fixed_preseason_total=None if missing_selected else fixed_total,
        optimistic_hindsight_total=None if missing_hindsight else hindsight_total,
        missing_selected=tuple(missing_selected),
        missing_hindsight=tuple(missing_hindsight),
        missing_starters=missing_starters(roster, players, rules),
        weeks=tuple(weeks),
    )


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
    pair_summaries, row_counts = (
        {},
        {policy: Counter() for policy in ("static", "inflation", "roster")},
    )
    reason_counts = Counter()
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
        pair_counts = Counter()
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


if __name__ == "__main__":
    raise SystemExit(main())
