#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
"""Estimate Anthropic API token costs from Claude Code session logs.

Queries the session-inspector SQLite cache under ``~/.claude/inspector/`` to
estimate what the recorded usage would have cost at current documented Anthropic
API standard pricing.  The cache must already exist — run
``uv run scripts/inspect_session.py refresh`` first.

Claude Code reports disjoint token categories per API request:
  input_tokens      — uncached base input (billed at base input rate)
  cache_read        — prompt-cache hits  (billed at 0.1× base input rate)
  cache_create      — prompt-cache writes, split by TTL under usage.cache_creation:
                        5-minute writes billed at 1.25× base input,
                        1-hour   writes billed at 2×    base input
  output_tokens     — all output including extended-thinking tokens

Server-side tools (``advisor``, ``web_search``, ``code_execution``) run extra
sub-requests against an Anthropic-hosted model.  Their tokens appear in
``usage.iterations[]`` on the parent assistant message under entries whose
``type`` ends with ``_message`` (e.g. ``advisor_message``).  The parent's
``input_tokens`` / ``output_tokens`` totals are aggregated from the
non-``*_message`` iterations only, so the server-tool iteration tokens are
**additive** and must be billed separately.  This script reads them from
``server_tool_calls.iteration_*`` and rolls them into model totals.

Pricing catalog sources, checked 2026-04-16:
  https://docs.anthropic.com/en/docs/about-claude/models
  https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
"""

import argparse
import importlib.util
import json
import logging
import sqlite3
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, tzinfo
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCRIPT_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)
USD_PRECISION = Decimal("0.000001")
USD_DISPLAY_PRECISION = Decimal("0.01")
PRICE_CATALOG_AS_OF = "2026-06-09"
SOURCE_URLS = [
    "https://docs.anthropic.com/en/docs/about-claude/models",
    "https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching",
]


# ---------------------------------------------------------------------------
# Support-module loader
# ---------------------------------------------------------------------------

def _load_support_module(module_name: str, filename: str) -> Any:
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    module_path = SCRIPT_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load support module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


DB = _load_support_module("claude_session_inspector_db", "db.py")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class PriceInfo:
    model_id: str
    input_per_million: Decimal
    cache_read_per_million: Decimal
    # Prompt-cache writes are billed per TTL: 5-minute at 1.25x base input,
    # 1-hour at 2x base input.  Claude Code uses both; current logs record the
    # split under usage.cache_creation.
    cache_write_5m_per_million: Decimal
    cache_write_1h_per_million: Decimal
    output_per_million: Decimal


@dataclass(slots=True, frozen=True)
class TokenUsage:
    input_tokens: int
    cache_read_tokens: int
    cache_write_5m_tokens: int
    cache_write_1h_tokens: int
    output_tokens: int

    @property
    def cache_write_tokens(self) -> int:
        return self.cache_write_5m_tokens + self.cache_write_1h_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens + self.output_tokens


@dataclass(slots=True, frozen=True)
class ModelResolution:
    raw_model: str | None
    pricing_model: str | None
    estimated: bool
    resolution_reason: str | None


@dataclass(slots=True, frozen=True)
class UsageEvent:
    session_id: str
    slug: str | None
    custom_title: str | None
    project: str | None
    is_subagent: bool
    timestamp: datetime
    local_day: str
    raw_model: str | None
    pricing_model: str | None
    estimated_model: bool
    resolution_reason: str | None
    token_usage: TokenUsage
    cost_usd: Decimal | None
    # "turn" for normal assistant turn usage; "server_tool" for additive
    # Anthropic-hosted server-tool iterations (advisor / web_search / code_execution).
    source: str = "turn"
    # When source == "server_tool", names the tool (e.g., "advisor").
    server_tool_name: str | None = None
    # True when this turn (or its parent turn, for server-tool iterations) ran in
    # Claude Code fast mode and was priced at the fast-mode rate.
    is_fast: bool = False


# ---------------------------------------------------------------------------
# Price catalog — Anthropic standard pricing as of 2026-06-09
#
# Cache read     = 0.1×  base input rate
# Cache write 5m = 1.25× base input rate (5-minute TTL)
# Cache write 1h = 2×    base input rate (1-hour TTL)
#   Current Claude Code logs record the per-TTL split under
#   usage.cache_creation.{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens};
#   the importer reconciles it into cache_create_5m / cache_create_1h columns.
# Output rate includes extended-thinking tokens (no separate surcharge).
# No long-context surcharge — Fable 5, Mythos 5, Opus 4.8, Opus 4.7,
# Opus/Sonnet 4.6 include 1M context at standard rates.
# ---------------------------------------------------------------------------

def _price(
    model_id: str,
    input_rate: str,
    output_rate: str,
) -> PriceInfo:
    base = Decimal(input_rate)
    return PriceInfo(
        model_id=model_id,
        input_per_million=base,
        cache_read_per_million=(base * Decimal("0.1")).quantize(USD_PRECISION),
        cache_write_5m_per_million=(base * Decimal("1.25")).quantize(USD_PRECISION),
        cache_write_1h_per_million=(base * Decimal("2")).quantize(USD_PRECISION),
        output_per_million=Decimal(output_rate),
    )


PRICE_CATALOG: dict[str, PriceInfo] = {
    # Current models
    "claude-fable-5":    _price("claude-fable-5",   "10.00",  "50.00"),
    "claude-mythos-5":   _price("claude-mythos-5",  "10.00",  "50.00"),
    "claude-opus-4-8":   _price("claude-opus-4-8",   "5.00",  "25.00"),
    "claude-opus-4-7":   _price("claude-opus-4-7",   "5.00",  "25.00"),
    "claude-opus-4-6":   _price("claude-opus-4-6",   "5.00",  "25.00"),
    "claude-sonnet-4-6": _price("claude-sonnet-4-6", "3.00",  "15.00"),
    "claude-haiku-4-5":  _price("claude-haiku-4-5",  "1.00",   "5.00"),
    "claude-opus-4-5":   _price("claude-opus-4-5",   "5.00",  "25.00"),
    "claude-sonnet-4-5": _price("claude-sonnet-4-5", "3.00",  "15.00"),
    # Deprecated / retiring — best-effort pricing
    "claude-opus-4-1":   _price("claude-opus-4-1",  "15.00",  "75.00"),
    "claude-opus-4-0":   _price("claude-opus-4-0",  "15.00",  "75.00"),
    "claude-sonnet-4-0": _price("claude-sonnet-4-0",  "3.00", "15.00"),
    "claude-haiku-3-5":  _price("claude-haiku-3-5",   "0.80",  "4.00"),
}

# Fast mode price catalog — Claude Code "fast mode" (research preview) prices
# Opus at a higher per-token rate for ~2.5x lower latency.  Same model, same
# quality; only the rate differs.  Source: https://code.claude.com/docs/en/fast-mode
# (checked 2026-05-28).
#
# The multiplier is per-model, NOT global:
#   Opus 4.8            -> $10 / $50  MTok (2x standard)
#   Opus 4.7, Opus 4.6  -> $30 / $150 MTok (6x standard)
# Fast mode is Opus-only — Sonnet/Haiku have no fast entry and always price at
# standard rates.
#
# ASSUMPTION: the docs publish only the input/output fast rates.  We derive the
# fast cache rates with the same ratios used for standard pricing — 0.1x (read),
# 1.25x (5m write), 2x (1h write) — off the fast input rate; Anthropic does not
# document fast-mode cache rates, and the docs note fast pricing is "flat across
# the full 1M token context window".
FAST_PRICE_CATALOG: dict[str, PriceInfo] = {
    "claude-opus-4-8": _price("claude-opus-4-8", "10.00",  "50.00"),
    "claude-opus-4-7": _price("claude-opus-4-7", "30.00", "150.00"),
    "claude-opus-4-6": _price("claude-opus-4-6", "30.00", "150.00"),
}

# usage.speed value (Claude Code session JSONL) that indicates fast mode was
# active for a turn.  Standard turns carry "standard"; absent/empty is treated
# as standard.  Any other non-standard value is counted as an unknown speed and
# priced at standard rates (see usage_event_from_turn_row) rather than guessed.
FAST_SPEED_VALUE = "fast"
STANDARD_SPEED_VALUES = frozenset({"standard", ""})

# Model IDs that can appear with a YYYYMMDD date suffix stripped.
SNAPSHOT_ALIASES: set[str] = set(PRICE_CATALOG.keys())

# Map internal / variant model IDs to the closest public model.
CLOSEST_FAMILY_MAP: dict[str, str] = {
    "claude-3-5-sonnet":  "claude-sonnet-4-0",
    "claude-3-5-haiku":   "claude-haiku-3-5",
    "claude-3-opus":      "claude-opus-4-0",
    "claude-3-haiku":     "claude-haiku-3-5",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate Anthropic API token costs from Claude Code session logs.",
        suggest_on_error=True,
    )
    parser.add_argument("--begin", required=True, help="Inclusive start date or datetime.")
    parser.add_argument("--end", required=True, help="Inclusive end date or datetime.")
    parser.add_argument(
        "--claude-home",
        type=Path,
        default=None,
        help="Override ~/.claude home directory.",
    )
    parser.add_argument(
        "--exclude-subagents",
        action="store_true",
        help="Exclude subagent turns from the report.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Filter to sessions whose project or cwd contains this substring "
        "(case-insensitive).",
    )
    parser.add_argument(
        "--timezone",
        default=None,
        help="IANA timezone for date-only parsing and day grouping. Defaults to local.",
    )
    parser.add_argument(
        "--unknown-model-policy",
        choices=("closest-family", "strict", "exclude"),
        default="closest-family",
        help="How to handle unknown Claude model ids.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of plain text.",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    return parser.parse_args(argv)


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(levelname)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        tz = resolve_timezone(args.timezone)
        begin_at, end_at = parse_time_range(args.begin, args.end, tz)
        report = build_report(
            claude_home=args.claude_home,
            begin_at=begin_at,
            end_at=end_at,
            display_timezone=tz,
            exclude_subagents=args.exclude_subagents,
            unknown_model_policy=args.unknown_model_policy,
            project=args.project,
        )
        emit(report, as_json=args.json)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        logger.exception("Unexpected error")
        return 1


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def resolve_timezone(value: str | None) -> tzinfo:
    if value is None:
        local = datetime.now().astimezone().tzinfo
        if local is None:
            raise ValueError("could not resolve local timezone")
        return local
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {value}") from exc


def parse_time_range(
    begin_value: str,
    end_value: str,
    display_timezone: tzinfo,
) -> tuple[datetime, datetime]:
    begin_at = parse_cli_datetime(begin_value, display_timezone, end_of_range=False)
    end_at = parse_cli_datetime(end_value, display_timezone, end_of_range=True)
    if end_at < begin_at:
        raise ValueError("--end must be on or after --begin")
    return begin_at.astimezone(UTC), end_at.astimezone(UTC)


def parse_cli_datetime(
    value: str,
    display_timezone: tzinfo,
    *,
    end_of_range: bool,
) -> datetime:
    if "T" not in value and " " not in value:
        parsed_date = date.fromisoformat(value)
        return datetime.combine(
            parsed_date,
            time.max if end_of_range else time.min,
            tzinfo=display_timezone,
        )
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=display_timezone)
    return parsed


def parse_iso_timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

def resolve_pricing_model(
    raw_model: str | None,
    *,
    unknown_model_policy: str,
) -> ModelResolution:
    if raw_model is None:
        return ModelResolution(
            raw_model=None,
            pricing_model=None,
            estimated=False,
            resolution_reason="missing-model",
        )

    if raw_model in PRICE_CATALOG:
        return ModelResolution(
            raw_model=raw_model,
            pricing_model=raw_model,
            estimated=False,
            resolution_reason="exact",
        )

    base_model = strip_claude_snapshot_suffix(raw_model)
    if base_model in PRICE_CATALOG and base_model in SNAPSHOT_ALIASES:
        return ModelResolution(
            raw_model=raw_model,
            pricing_model=base_model,
            estimated=False,
            resolution_reason="snapshot-alias",
        )

    if unknown_model_policy == "closest-family":
        mapped = CLOSEST_FAMILY_MAP.get(raw_model)
        if mapped is None:
            mapped = CLOSEST_FAMILY_MAP.get(base_model)
        if mapped is not None:
            return ModelResolution(
                raw_model=raw_model,
                pricing_model=mapped,
                estimated=True,
                resolution_reason=f"closest-family:{mapped}",
            )

    return ModelResolution(
        raw_model=raw_model,
        pricing_model=None,
        estimated=False,
        resolution_reason="unknown-claude-model",
    )


def strip_claude_snapshot_suffix(model_id: str) -> str:
    """Strip a YYYYMMDD date suffix from a Claude model ID.

    Claude snapshot IDs look like ``claude-haiku-4-5-20251001`` where the last
    segment is an 8-digit date.  This differs from OpenAI's ``YYYY-MM-DD``
    format.
    """
    parts = model_id.rsplit("-", 1)
    if len(parts) != 2:
        return model_id
    suffix = parts[1]
    if len(suffix) != 8 or not suffix.isdigit():
        return model_id
    try:
        datetime.strptime(suffix, "%Y%m%d")
    except ValueError:
        return model_id
    return parts[0]


# ---------------------------------------------------------------------------
# Cost computation
# ---------------------------------------------------------------------------

def compute_cost(*, pricing_model: str, token_usage: TokenUsage, fast: bool = False) -> Decimal:
    if fast and pricing_model in FAST_PRICE_CATALOG:
        price = FAST_PRICE_CATALOG[pricing_model]
    else:
        price = PRICE_CATALOG[pricing_model]
    input_cost = token_cost(token_usage.input_tokens, price.input_per_million)
    cache_read_cost = token_cost(token_usage.cache_read_tokens, price.cache_read_per_million)
    cache_write_cost = (
        token_cost(token_usage.cache_write_5m_tokens, price.cache_write_5m_per_million)
        + token_cost(token_usage.cache_write_1h_tokens, price.cache_write_1h_per_million)
    )
    output_cost = token_cost(token_usage.output_tokens, price.output_per_million)
    return (input_cost + cache_read_cost + cache_write_cost + output_cost).quantize(
        USD_PRECISION,
        rounding=ROUND_HALF_UP,
    )


def token_cost(tokens: int, per_million: Decimal) -> Decimal:
    return (Decimal(tokens) / Decimal(1_000_000)) * per_million


def classify_speed(speed: str | None) -> str:
    """Classify a turn's ``usage.speed`` value for pricing.

    Returns one of ``"standard"``, ``"fast"``, or ``"unknown"``.  ``None`` and
    empty values are treated as standard (older sessions / non-Opus turns do not
    carry the field).  Anything that is neither the known standard nor fast
    value is ``"unknown"`` so the caller can price it at standard rates and
    surface a counter rather than silently mispricing it.
    """
    if speed is None:
        return "standard"
    normalized = speed.strip().lower()
    if normalized in STANDARD_SPEED_VALUES:
        return "standard"
    if normalized == FAST_SPEED_VALUE:
        return "fast"
    return "unknown"


# ---------------------------------------------------------------------------
# SQLite data loading
# ---------------------------------------------------------------------------

def build_report(
    *,
    claude_home: Path | None,
    begin_at: datetime,
    end_at: datetime,
    display_timezone: tzinfo,
    exclude_subagents: bool,
    unknown_model_policy: str,
    project: str | None = None,
) -> dict[str, Any]:
    home = claude_home or Path.home() / ".claude"
    db_path = DB.default_db_path(home)
    if not db_path.exists():
        raise RuntimeError(
            f"SQLite cache not found at {db_path}. Run "
            "`uv run scripts/inspect_session.py refresh` first."
        )

    event_counter: Counter[str] = Counter()
    unpriced_counter: Counter[str] = Counter()
    events: list[UsageEvent] = []

    with closing(DB.open_db(db_path)) as conn:
        session_count = count_sessions(
            conn, exclude_subagents=exclude_subagents, project=project
        )
        for row in fetch_turn_rows(
            conn,
            begin_at=begin_at,
            end_at=end_at,
            exclude_subagents=exclude_subagents,
            project=project,
        ):
            event = usage_event_from_row(
                row,
                display_timezone=display_timezone,
                unknown_model_policy=unknown_model_policy,
                event_counter=event_counter,
                unpriced_counter=unpriced_counter,
            )
            if event is not None:
                events.append(event)

        if server_tool_iterations_supported(conn):
            for row in fetch_server_tool_iteration_rows(
                conn,
                begin_at=begin_at,
                end_at=end_at,
                exclude_subagents=exclude_subagents,
                project=project,
            ):
                event = usage_event_from_server_tool_row(
                    row,
                    display_timezone=display_timezone,
                    unknown_model_policy=unknown_model_policy,
                    event_counter=event_counter,
                    unpriced_counter=unpriced_counter,
                )
                if event is not None:
                    events.append(event)

    return summarize_events(
        events,
        begin_at=begin_at,
        end_at=end_at,
        display_timezone=display_timezone,
        db_path=db_path,
        session_count=session_count,
        event_counter=event_counter,
        unpriced_counter=unpriced_counter,
        unknown_model_policy=unknown_model_policy,
        exclude_subagents=exclude_subagents,
        project=project,
    )


def _project_clause(project: str | None, *, alias: str) -> tuple[str, list[str]]:
    """Build a case-insensitive project/cwd LIKE clause and its bind params."""
    if not project:
        return "", []
    like = f"%{project.lower()}%"
    col_project = f"{alias}.project" if alias else "project"
    col_cwd = f"{alias}.cwd" if alias else "cwd"
    clause = f"AND (LOWER(COALESCE({col_project}, '')) LIKE ? OR LOWER(COALESCE({col_cwd}, '')) LIKE ?)"
    return clause, [like, like]


def count_sessions(
    conn: sqlite3.Connection,
    *,
    exclude_subagents: bool,
    project: str | None = None,
) -> int:
    clauses: list[str] = []
    params: list[str] = []
    if exclude_subagents:
        clauses.append("is_subagent = 0")
    project_clause, project_params = _project_clause(project, alias="")
    if project_clause:
        clauses.append(project_clause.removeprefix("AND "))
        params.extend(project_params)
    query = "SELECT COUNT(*) AS count FROM sessions"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    row = conn.execute(query, params).fetchone()
    return int(row["count"]) if row else 0


def fetch_turn_rows(
    conn: sqlite3.Connection,
    *,
    begin_at: datetime,
    end_at: datetime,
    exclude_subagents: bool,
    project: str | None = None,
) -> Iterable[sqlite3.Row]:
    subagent_clause = "AND s.is_subagent = 0" if exclude_subagents else ""
    project_clause, project_params = _project_clause(project, alias="s")
    query = f"""
        SELECT
            t.session_id,
            s.slug,
            s.custom_title,
            s.project,
            s.is_subagent,
            COALESCE(t.timestamp, s.start_timestamp) AS effective_timestamp,
            COALESCE(t.model, s.model)                AS effective_model,
            t.speed,
            t.input_tokens,
            t.output_tokens,
            t.cache_read,
            t.cache_create,
            t.cache_create_5m,
            t.cache_create_1h
        FROM turns t
        JOIN sessions s ON s.session_id = t.session_id
        WHERE COALESCE(t.timestamp, s.start_timestamp) >= ?
          AND COALESCE(t.timestamp, s.start_timestamp) <= ?
          {subagent_clause}
          {project_clause}
        ORDER BY effective_timestamp, t.id
    """
    return conn.execute(query, [begin_at.isoformat(), end_at.isoformat(), *project_params])


def server_tool_iterations_supported(conn: sqlite3.Connection) -> bool:
    """Return True if the cache schema has the server_tool_calls table."""
    row = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name = 'server_tool_calls'"
    ).fetchone()
    return row is not None


def fetch_server_tool_iteration_rows(
    conn: sqlite3.Connection,
    *,
    begin_at: datetime,
    end_at: datetime,
    exclude_subagents: bool,
    project: str | None = None,
) -> Iterable[sqlite3.Row]:
    """Yield priced server-tool iteration rows from server_tool_calls.

    Filters out aborted calls (no tokens recorded) and rows whose iteration
    contributed no tokens.  Time-range is keyed on the parent turn timestamp
    so the report stays consistent with the turn-level query.
    """
    subagent_clause = "AND s.is_subagent = 0" if exclude_subagents else ""
    project_clause, project_params = _project_clause(project, alias="s")
    query = f"""
        SELECT
            stc.session_id,
            s.slug,
            s.custom_title,
            s.project,
            s.is_subagent,
            COALESCE(t.timestamp, s.start_timestamp) AS effective_timestamp,
            t.speed,
            stc.tool_name,
            stc.iteration_model,
            stc.iteration_input_tokens,
            stc.iteration_output_tokens,
            stc.iteration_cache_read,
            stc.iteration_cache_create,
            stc.iteration_cache_create_5m,
            stc.iteration_cache_create_1h,
            stc.is_aborted
        FROM server_tool_calls stc
        JOIN turns t    ON t.id = stc.turn_id
        JOIN sessions s ON s.session_id = stc.session_id
        WHERE COALESCE(t.timestamp, s.start_timestamp) >= ?
          AND COALESCE(t.timestamp, s.start_timestamp) <= ?
          AND COALESCE(stc.is_aborted, 0) = 0
          {subagent_clause}
          {project_clause}
        ORDER BY effective_timestamp, stc.id
    """
    return conn.execute(query, [begin_at.isoformat(), end_at.isoformat(), *project_params])


def usage_event_from_server_tool_row(
    row: sqlite3.Row,
    *,
    display_timezone: tzinfo,
    unknown_model_policy: str,
    event_counter: Counter[str],
    unpriced_counter: Counter[str],
) -> UsageEvent | None:
    raw_model = string_or_none(row["iteration_model"])
    token_usage = TokenUsage(
        input_tokens=max(int_or_zero(row["iteration_input_tokens"]), 0),
        cache_read_tokens=max(int_or_zero(row["iteration_cache_read"]), 0),
        cache_write_5m_tokens=max(int_or_zero(row["iteration_cache_create_5m"]), 0),
        cache_write_1h_tokens=max(int_or_zero(row["iteration_cache_create_1h"]), 0),
        output_tokens=max(int_or_zero(row["iteration_output_tokens"]), 0),
    )
    if token_usage.total_tokens <= 0:
        event_counter["server_tool_zero_token_skipped"] += 1
        return None

    timestamp = parse_iso_timestamp(string_or_none(row["effective_timestamp"]))
    if timestamp is None:
        event_counter["server_tool_missing_timestamp"] += 1
        return None

    # Server-tool iterations share the parent turn's API configuration, so they
    # are fast-priced whenever the parent turn ran in fast mode.
    speed_class = classify_speed(string_or_none(row["speed"]))
    fast = speed_class == "fast"

    resolution = resolve_pricing_model(raw_model, unknown_model_policy=unknown_model_policy)
    if resolution.pricing_model is None:
        unpriced_key = f"server_tool:{resolution.raw_model or 'missing-model'}"
        unpriced_counter[unpriced_key] += 1
        cost_usd = None
    else:
        if fast and resolution.pricing_model not in FAST_PRICE_CATALOG:
            fast = False
        cost_usd = compute_cost(
            pricing_model=resolution.pricing_model,
            token_usage=token_usage,
            fast=fast,
        )

    event_counter[
        "server_tool_priced" if cost_usd is not None else "server_tool_unpriced"
    ] += 1
    if resolution.estimated:
        event_counter["server_tool_estimated_model_mapping"] += 1

    local_timestamp = timestamp.astimezone(display_timezone)
    tool_name = string_or_none(row["tool_name"]) or "server_tool"

    return UsageEvent(
        session_id=str(row["session_id"]),
        slug=string_or_none(row["slug"]),
        custom_title=string_or_none(row["custom_title"]),
        project=string_or_none(row["project"]),
        is_subagent=bool(row["is_subagent"]),
        timestamp=timestamp,
        local_day=local_timestamp.date().isoformat(),
        raw_model=raw_model,
        pricing_model=resolution.pricing_model,
        estimated_model=resolution.estimated,
        resolution_reason=resolution.resolution_reason,
        token_usage=token_usage,
        cost_usd=cost_usd,
        source="server_tool",
        server_tool_name=tool_name,
        is_fast=fast and cost_usd is not None,
    )


def usage_event_from_row(
    row: sqlite3.Row,
    *,
    display_timezone: tzinfo,
    unknown_model_policy: str,
    event_counter: Counter[str],
    unpriced_counter: Counter[str],
) -> UsageEvent | None:
    raw_model = string_or_none(row["effective_model"])
    token_usage = TokenUsage(
        input_tokens=max(int_or_zero(row["input_tokens"]), 0),
        cache_read_tokens=max(int_or_zero(row["cache_read"]), 0),
        cache_write_5m_tokens=max(int_or_zero(row["cache_create_5m"]), 0),
        cache_write_1h_tokens=max(int_or_zero(row["cache_create_1h"]), 0),
        output_tokens=max(int_or_zero(row["output_tokens"]), 0),
    )
    if token_usage.total_tokens <= 0:
        event_counter["zero_token_turns"] += 1
        return None

    timestamp = parse_iso_timestamp(string_or_none(row["effective_timestamp"]))
    if timestamp is None:
        event_counter["missing_timestamp"] += 1
        return None

    speed_class = classify_speed(string_or_none(row["speed"]))
    if speed_class == "unknown":
        event_counter["unknown_speed_turns"] += 1
    fast = speed_class == "fast"

    resolution = resolve_pricing_model(raw_model, unknown_model_policy=unknown_model_policy)
    if resolution.pricing_model is None:
        unpriced_key = resolution.raw_model or "missing-model"
        unpriced_counter[unpriced_key] += 1
        cost_usd = None
    else:
        if fast and resolution.pricing_model not in FAST_PRICE_CATALOG:
            # Fast mode reported on a model with no fast-rate entry (only Opus
            # supports fast mode).  Fall back to standard pricing and surface it.
            event_counter["fast_speed_without_fast_price"] += 1
            fast = False
        cost_usd = compute_cost(
            pricing_model=resolution.pricing_model,
            token_usage=token_usage,
            fast=fast,
        )

    event_counter["priced" if cost_usd is not None else "unpriced"] += 1
    if fast and cost_usd is not None:
        event_counter["fast_priced"] += 1
    if resolution.estimated:
        event_counter["estimated_model_mapping"] += 1

    local_timestamp = timestamp.astimezone(display_timezone)

    return UsageEvent(
        session_id=str(row["session_id"]),
        slug=string_or_none(row["slug"]),
        custom_title=string_or_none(row["custom_title"]),
        project=string_or_none(row["project"]),
        is_subagent=bool(row["is_subagent"]),
        timestamp=timestamp,
        local_day=local_timestamp.date().isoformat(),
        raw_model=raw_model,
        pricing_model=resolution.pricing_model,
        estimated_model=resolution.estimated,
        resolution_reason=resolution.resolution_reason,
        token_usage=token_usage,
        cost_usd=cost_usd,
        is_fast=fast and cost_usd is not None,
    )


# ---------------------------------------------------------------------------
# Report summarization
# ---------------------------------------------------------------------------

def summarize_events(
    events: list[UsageEvent],
    *,
    begin_at: datetime,
    end_at: datetime,
    display_timezone: tzinfo,
    db_path: Path,
    session_count: int,
    event_counter: Counter[str],
    unpriced_counter: Counter[str],
    unknown_model_policy: str,
    exclude_subagents: bool,
    project: str | None = None,
) -> dict[str, Any]:
    total_input = sum(e.token_usage.input_tokens for e in events)
    total_cache_read = sum(e.token_usage.cache_read_tokens for e in events)
    total_cache_write = sum(e.token_usage.cache_write_tokens for e in events)
    total_cache_write_5m = sum(e.token_usage.cache_write_5m_tokens for e in events)
    total_cache_write_1h = sum(e.token_usage.cache_write_1h_tokens for e in events)
    total_output = sum(e.token_usage.output_tokens for e in events)
    total_cost = sum((e.cost_usd or Decimal("0")) for e in events)

    fast_events = [e for e in events if e.is_fast]
    fast_cost = sum((e.cost_usd or Decimal("0")) for e in fast_events)
    fast_input = sum(e.token_usage.input_tokens for e in fast_events)
    fast_output = sum(e.token_usage.output_tokens for e in fast_events)

    by_day: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "turns": 0,
            "sessions": set(),
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "cost_usd": Decimal("0"),
        }
    )
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "turns": 0,
            "sessions": set(),
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "cost_usd": Decimal("0"),
            "estimated_turns": 0,
        }
    )
    by_session: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "slug": None,
            "custom_title": None,
            "project": None,
            "is_subagent": False,
            "models": Counter(),
            "turns": 0,
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "cost_usd": Decimal("0"),
            "first_timestamp": None,
            "last_timestamp": None,
        }
    )
    by_server_tool: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "sessions": set(),
            "models": Counter(),
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "cost_usd": Decimal("0"),
        }
    )
    estimated_mappings: Counter[str] = Counter()

    for event in events:
        # Server-tool iteration events share session_id with their parent turn
        # but are not themselves turns.  Roll them into per-day/model/session
        # token + cost totals, but do not double-count "turns".
        is_turn = event.source == "turn"

        day_row = by_day[event.local_day]
        if is_turn:
            day_row["turns"] += 1
        day_row["sessions"].add(event.session_id)
        day_row["input_tokens"] += event.token_usage.input_tokens
        day_row["cache_read_tokens"] += event.token_usage.cache_read_tokens
        day_row["cache_write_tokens"] += event.token_usage.cache_write_tokens
        day_row["output_tokens"] += event.token_usage.output_tokens
        day_row["cost_usd"] += event.cost_usd or Decimal("0")

        model_key = event.pricing_model or "unpriced"
        model_row = by_model[model_key]
        if is_turn:
            model_row["turns"] += 1
        model_row["sessions"].add(event.session_id)
        model_row["input_tokens"] += event.token_usage.input_tokens
        model_row["cache_read_tokens"] += event.token_usage.cache_read_tokens
        model_row["cache_write_tokens"] += event.token_usage.cache_write_tokens
        model_row["output_tokens"] += event.token_usage.output_tokens
        model_row["cost_usd"] += event.cost_usd or Decimal("0")
        if event.estimated_model:
            model_row["estimated_turns"] += 1
            estimated_mappings[f"{event.raw_model} -> {event.pricing_model}"] += 1

        sess = by_session[event.session_id]
        sess["slug"] = event.slug
        sess["custom_title"] = event.custom_title
        sess["project"] = event.project
        sess["is_subagent"] = event.is_subagent
        if is_turn:
            sess["turns"] += 1
        sess["models"][model_key] += 1
        sess["input_tokens"] += event.token_usage.input_tokens
        sess["cache_read_tokens"] += event.token_usage.cache_read_tokens
        sess["cache_write_tokens"] += event.token_usage.cache_write_tokens
        sess["output_tokens"] += event.token_usage.output_tokens
        sess["cost_usd"] += event.cost_usd or Decimal("0")
        first_ts = sess["first_timestamp"]
        last_ts = sess["last_timestamp"]
        sess["first_timestamp"] = event.timestamp if first_ts is None or event.timestamp < first_ts else first_ts
        sess["last_timestamp"] = event.timestamp if last_ts is None or event.timestamp > last_ts else last_ts

        if event.source == "server_tool":
            tool_row = by_server_tool[event.server_tool_name or "server_tool"]
            tool_row["calls"] += 1
            tool_row["sessions"].add(event.session_id)
            tool_row["models"][model_key] += 1
            tool_row["input_tokens"] += event.token_usage.input_tokens
            tool_row["cache_read_tokens"] += event.token_usage.cache_read_tokens
            tool_row["cache_write_tokens"] += event.token_usage.cache_write_tokens
            tool_row["output_tokens"] += event.token_usage.output_tokens
            tool_row["cost_usd"] += event.cost_usd or Decimal("0")

    return {
        "range": {
            "begin_utc": begin_at.isoformat(),
            "end_utc": end_at.isoformat(),
            "timezone": timezone_name(display_timezone),
        },
        "pricing": {
            "pricing_mode": "speed-aware",
            "catalog_as_of": PRICE_CATALOG_AS_OF,
            "unknown_model_policy": unknown_model_policy,
            "fast_mode_note": (
                "Turns are priced per their usage.speed: 'fast' (Claude Code fast "
                "mode, Opus only) bills at the higher fast rate, everything else at "
                "standard. Fast cache rates are derived with the standard 0.1x/1.25x "
                "ratios (Anthropic does not publish fast-mode cache rates). Any "
                "unrecognized speed value is counted under scan.unknown_speed_turns "
                "and priced at standard rates."
            ),
            "cache_write_note": (
                "Cache writes are priced per TTL from usage.cache_creation: 5-minute "
                "writes at 1.25x base input, 1-hour writes at 2x. When the aggregate "
                "cache-write total exceeds the labeled split, the remainder defaults to "
                "the 5-minute rate. Logs without the split (older sessions) price all "
                "cache writes at the 5-minute rate."
            ),
            "thinking_note": (
                "Extended-thinking tokens are included in output_tokens and billed "
                "at the output rate. No separate surcharge."
            ),
            "server_tool_note": (
                "Server-side tool iterations (advisor / web_search / code_execution) "
                "are billed in addition to the parent turn's tokens — their cost is "
                "rolled into per-model totals and broken out under `by_server_tool`. "
                "Web-search per-request surcharges ($10 per 1k searches) are not "
                "included; only the iteration's token cost."
            ),
            "sources": SOURCE_URLS,
        },
        "scan": {
            "source": "sqlite",
            "db_path": str(db_path),
            "sessions_in_db": session_count,
            "turns_in_range": sum(1 for e in events if e.source == "turn"),
            "priced_turns": event_counter["priced"],
            "unpriced_turns": event_counter["unpriced"],
            "fast_turns": event_counter["fast_priced"],
            "unknown_speed_turns": event_counter["unknown_speed_turns"],
            "fast_speed_without_fast_price": event_counter["fast_speed_without_fast_price"],
            "zero_token_turns_skipped": event_counter["zero_token_turns"],
            "missing_timestamp_skipped": event_counter["missing_timestamp"],
            "estimated_model_mapping_turns": event_counter["estimated_model_mapping"],
            "server_tool_iterations_in_range": sum(
                1 for e in events if e.source == "server_tool"
            ),
            "server_tool_priced": event_counter["server_tool_priced"],
            "server_tool_unpriced": event_counter["server_tool_unpriced"],
            "exclude_subagents": exclude_subagents,
            "project_filter": project,
        },
        "totals": {
            "session_count": len(by_session),
            "priced_session_count": sum(1 for s in by_session.values() if s["cost_usd"] > 0),
            "input_tokens": total_input,
            "cache_read_tokens": total_cache_read,
            "cache_write_tokens": total_cache_write,
            "cache_write_5m_tokens": total_cache_write_5m,
            "cache_write_1h_tokens": total_cache_write_1h,
            "output_tokens": total_output,
            "estimated_cost_usd": decimal_to_float(total_cost),
        },
        "fast_mode": {
            "fast_events": len(fast_events),
            "input_tokens": fast_input,
            "output_tokens": fast_output,
            "estimated_cost_usd": decimal_to_float(fast_cost),
        },
        "by_day": [
            {
                "day": day,
                "turns": row["turns"],
                "session_count": len(row["sessions"]),
                "input_tokens": row["input_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "cache_write_tokens": row["cache_write_tokens"],
                "output_tokens": row["output_tokens"],
                "estimated_cost_usd": decimal_to_float(row["cost_usd"]),
            }
            for day, row in sorted(by_day.items())
        ],
        "by_model": [
            {
                "model": model,
                "turns": row["turns"],
                "session_count": len(row["sessions"]),
                "input_tokens": row["input_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "cache_write_tokens": row["cache_write_tokens"],
                "output_tokens": row["output_tokens"],
                "estimated_cost_usd": decimal_to_float(row["cost_usd"]),
                "estimated_mapping_turns": row["estimated_turns"],
            }
            for model, row in sorted(
                by_model.items(),
                key=lambda item: (item[1]["cost_usd"], item[1]["turns"]),
                reverse=True,
            )
        ],
        "by_session": [
            {
                "session_id": sid,
                "slug": row["slug"],
                "custom_title": row["custom_title"],
                "project": row["project"],
                "is_subagent": row["is_subagent"],
                "models": dict(row["models"]),
                "turns": row["turns"],
                "input_tokens": row["input_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "cache_write_tokens": row["cache_write_tokens"],
                "output_tokens": row["output_tokens"],
                "estimated_cost_usd": decimal_to_float(row["cost_usd"]),
                "first_timestamp": row["first_timestamp"].isoformat() if row["first_timestamp"] else None,
                "last_timestamp": row["last_timestamp"].isoformat() if row["last_timestamp"] else None,
            }
            for sid, row in sorted(
                by_session.items(),
                key=lambda item: (item[1]["cost_usd"], item[1]["turns"]),
                reverse=True,
            )
        ],
        "by_server_tool": [
            {
                "tool_name": tool,
                "calls": row["calls"],
                "session_count": len(row["sessions"]),
                "models": dict(row["models"]),
                "input_tokens": row["input_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "cache_write_tokens": row["cache_write_tokens"],
                "output_tokens": row["output_tokens"],
                "estimated_cost_usd": decimal_to_float(row["cost_usd"]),
            }
            for tool, row in sorted(
                by_server_tool.items(),
                key=lambda item: (item[1]["cost_usd"], item[1]["calls"]),
                reverse=True,
            )
        ],
        "estimated_mappings": [
            {"mapping": m, "turns": c}
            for m, c in estimated_mappings.most_common()
        ],
        "unpriced": [
            {"key": k, "turns": c}
            for k, c in unpriced_counter.most_common()
        ],
    }


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

def emit(report: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    print(render_human_report(report))


def render_human_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    totals = report["totals"]
    scan = report["scan"]
    pricing = report["pricing"]

    lines.append("Claude API Cost Estimate")
    lines.append(
        f"Range: {report['range']['begin_utc']} to {report['range']['end_utc']} "
        f"({report['range']['timezone']})"
    )
    lines.append(
        f"Pricing: speed-aware (standard + fast mode), catalog as of {pricing['catalog_as_of']}, "
        f"unknown-model policy `{pricing['unknown_model_policy']}`"
    )
    lines.append(
        f"Sessions in DB: {scan['sessions_in_db']} | turns in range: {scan['turns_in_range']} | "
        f"priced: {scan['priced_turns']} | unpriced: {scan['unpriced_turns']}"
    )
    lines.append(
        f"Estimated cost: {format_usd(Decimal(str(totals['estimated_cost_usd'])))}"
    )
    fast = report.get("fast_mode", {})
    if fast.get("fast_events"):
        lines.append(
            f"Fast mode: {fast['fast_events']} events | "
            f"{format_usd(Decimal(str(fast['estimated_cost_usd'])))} | "
            f"input={format_int(fast['input_tokens'])} | output={format_int(fast['output_tokens'])}"
        )
    if scan.get("unknown_speed_turns"):
        lines.append(
            f"Note: {scan['unknown_speed_turns']} turns had an unrecognized usage.speed "
            "value and were priced at standard rates."
        )
    lines.append(
        "Tokens: "
        f"input={format_int(totals['input_tokens'])} "
        f"cache_read={format_int(totals['cache_read_tokens'])} "
        f"cache_write={format_int(totals['cache_write_tokens'])} "
        f"(5m={format_int(totals['cache_write_5m_tokens'])} "
        f"1h={format_int(totals['cache_write_1h_tokens'])}) "
        f"output={format_int(totals['output_tokens'])}"
    )

    if report["by_day"]:
        lines.append("")
        lines.append("By Day")
        for row in report["by_day"]:
            lines.append(
                f"  {row['day']}: {format_usd(Decimal(str(row['estimated_cost_usd'])))} | "
                f"turns={row['turns']} | sessions={row['session_count']} | "
                f"input={format_int(row['input_tokens'])} | output={format_int(row['output_tokens'])}"
            )

    if report["by_model"]:
        lines.append("")
        lines.append("By Model")
        for row in report["by_model"]:
            suffix = ""
            if row["estimated_mapping_turns"]:
                suffix += f" | estimated_mappings={row['estimated_mapping_turns']}"
            lines.append(
                f"  {row['model']}: {format_usd(Decimal(str(row['estimated_cost_usd'])))} | "
                f"turns={row['turns']} | sessions={row['session_count']} | "
                f"input={format_int(row['input_tokens'])} | output={format_int(row['output_tokens'])}{suffix}"
            )

    if report.get("by_server_tool"):
        lines.append("")
        lines.append("Server-side Tools")
        for row in report["by_server_tool"]:
            model_list = ", ".join(row["models"].keys()) or "unknown"
            lines.append(
                f"  {row['tool_name']}: {format_usd(Decimal(str(row['estimated_cost_usd'])))} | "
                f"calls={row['calls']} | sessions={row['session_count']} | "
                f"models={model_list} | "
                f"input={format_int(row['input_tokens'])} | output={format_int(row['output_tokens'])}"
            )

    if report["by_session"]:
        lines.append("")
        lines.append("Top Sessions")
        for row in report["by_session"][:10]:
            model_list = ", ".join(row["models"].keys()) or "unknown"
            title = row["custom_title"] or row["slug"] or row["session_id"][:12]
            subagent_tag = " [subagent]" if row["is_subagent"] else ""
            lines.append(
                f"  {title}{subagent_tag}: {format_usd(Decimal(str(row['estimated_cost_usd'])))} | "
                f"models={model_list} | turns={row['turns']}"
            )

    if report["estimated_mappings"]:
        lines.append("")
        lines.append("Estimated Mappings")
        for row in report["estimated_mappings"]:
            lines.append(f"  {row['mapping']}: {row['turns']} turns")

    if report["unpriced"]:
        lines.append("")
        lines.append("Unpriced")
        for row in report["unpriced"]:
            lines.append(f"  {row['key']}: {row['turns']} turns")

    lines.append("")
    lines.append("Notes")
    lines.append(f"  - {pricing['cache_write_note']}")
    lines.append(f"  - {pricing['thinking_note']}")
    lines.append(f"  - {pricing['server_tool_note']}")
    lines.append("")
    lines.append("Sources")
    for source in pricing["sources"]:
        lines.append(f"  - {source}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_usd(amount: Decimal) -> str:
    return f"${amount.quantize(USD_DISPLAY_PRECISION, rounding=ROUND_HALF_UP):,.2f}"


def format_int(value: int) -> str:
    return f"{value:,}"


def decimal_to_float(value: Decimal | int) -> float:
    return float(Decimal(value).quantize(USD_PRECISION, rounding=ROUND_HALF_UP))


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def timezone_name(value: tzinfo) -> str:
    key = getattr(value, "key", None)
    if isinstance(key, str):
        return key
    tzname = value.tzname(datetime.now())
    return tzname or str(value)


if __name__ == "__main__":
    sys.exit(main())
