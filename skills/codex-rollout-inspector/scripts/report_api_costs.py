#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
"""Estimate OpenAI API token costs from Codex rollout logs.

Uses the rollout-inspector SQLite cache under `${CODEX_HOME:-~/.codex}`. The
report estimates what the recorded usage would have cost at current documented
OpenAI API standard pricing.

Pricing catalog sources, checked 2026-07-10:
- https://developers.openai.com/api/docs/pricing
- https://developers.openai.com/api/docs/guides/prompt-caching
- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/api/docs/models/gpt-5.6-terra
- https://developers.openai.com/api/docs/models/gpt-5.6-luna
- https://developers.openai.com/api/docs/models/gpt-5.5
- https://developers.openai.com/api/docs/models/gpt-5.5-pro
- https://developers.openai.com/api/docs/models/gpt-5.4
- https://developers.openai.com/api/docs/models/gpt-5.4-mini
- https://developers.openai.com/api/docs/models/gpt-5
- https://developers.openai.com/api/docs/models/gpt-5.1
- https://developers.openai.com/api/docs/models/gpt-5-codex
- https://developers.openai.com/api/docs/models/gpt-5.1-codex
- https://developers.openai.com/api/docs/models/gpt-5.1-codex-max
- https://developers.openai.com/api/docs/models/gpt-5.1-codex-mini
- https://developers.openai.com/api/docs/models/gpt-5.2
- https://developers.openai.com/api/docs/models/gpt-5.2-codex
- https://developers.openai.com/api/docs/models/gpt-5.3-codex
- https://developers.openai.com/api/docs/models/codex-mini-latest
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
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
MICRO_USD = Decimal("0.000001")
USD_PRECISION = Decimal("0.000001")
USD_DISPLAY_PRECISION = Decimal("0.01")
PRICE_CATALOG_AS_OF = "2026-07-10"
SOURCE_URLS = [
    "https://developers.openai.com/api/docs/pricing",
    "https://developers.openai.com/api/docs/guides/prompt-caching",
    "https://developers.openai.com/api/docs/models/gpt-5.6-sol",
    "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
    "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
    "https://developers.openai.com/api/docs/models/gpt-5.5",
    "https://developers.openai.com/api/docs/models/gpt-5.5-pro",
    "https://developers.openai.com/api/docs/models/gpt-5.4",
    "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
    "https://developers.openai.com/api/docs/models/gpt-5",
    "https://developers.openai.com/api/docs/models/gpt-5.1",
    "https://developers.openai.com/api/docs/models/gpt-5-codex",
    "https://developers.openai.com/api/docs/models/gpt-5.1-codex",
    "https://developers.openai.com/api/docs/models/gpt-5.1-codex-max",
    "https://developers.openai.com/api/docs/models/gpt-5.1-codex-mini",
    "https://developers.openai.com/api/docs/models/gpt-5.2",
    "https://developers.openai.com/api/docs/models/gpt-5.2-codex",
    "https://developers.openai.com/api/docs/models/gpt-5.3-codex",
    "https://developers.openai.com/api/docs/models/codex-mini-latest",
]


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

DB = _load_support_module("codex_rollout_inspector_db", "db.py")


@dataclass(slots=True, frozen=True)
class RolloutPaths:
    codex_home: Path
    sessions_dir: Path
    archived_sessions_dir: Path


@dataclass(slots=True, frozen=True)
class PriceInfo:
    model_id: str
    input_per_million: Decimal
    cached_input_per_million: Decimal
    output_per_million: Decimal
    context_window: int
    max_output_tokens: int
    cache_write_per_million: Decimal | None = None
    long_context_threshold: int | None = None
    long_context_input_multiplier: Decimal = Decimal("1")
    long_context_output_multiplier: Decimal = Decimal("1")


@dataclass(slots=True, frozen=True)
class TokenUsage:
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int | None
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int

    @property
    def uncached_input_tokens(self) -> int:
        return max(self.input_tokens - self.cached_input_tokens, 0)

    @property
    def standard_input_tokens(self) -> int:
        cache_write_tokens = self.cache_write_tokens or 0
        return max(self.input_tokens - self.cached_input_tokens - cache_write_tokens, 0)


@dataclass(slots=True, frozen=True)
class CostEstimate:
    lower_usd: Decimal
    upper_usd: Decimal

    @property
    def exact(self) -> bool:
        return self.lower_usd == self.upper_usd


@dataclass(slots=True, frozen=True)
class ModelResolution:
    raw_model: str | None
    pricing_model: str | None
    estimated: bool
    resolution_reason: str | None
    excluded: bool


@dataclass(slots=True, frozen=True)
class UsageEvent:
    session_id: str
    thread_name: str | None
    path: str
    archived: bool
    provider: str | None
    timestamp: datetime
    local_day: str
    raw_model: str | None
    pricing_model: str | None
    estimated_model: bool
    resolution_reason: str | None
    exact_usage_source: str
    usage_is_approximate: bool
    long_context_pricing: bool
    token_usage: TokenUsage
    cost_estimate: CostEstimate | None


@dataclass(slots=True, frozen=True)
class LoadedEventSet:
    events: list[UsageEvent]
    warnings: list[str]
    event_counter: Counter[str]
    unpriced_counter: Counter[str]
    scanned_rollouts: int
    scan_source: str


PRICE_CATALOG: dict[str, PriceInfo] = {
    "gpt-5.6-sol": PriceInfo(
        model_id="gpt-5.6-sol",
        input_per_million=Decimal("5.00"),
        cached_input_per_million=Decimal("0.50"),
        cache_write_per_million=Decimal("6.25"),
        output_per_million=Decimal("30.00"),
        context_window=1_050_000,
        max_output_tokens=128_000,
        long_context_threshold=272_000,
        long_context_input_multiplier=Decimal("2"),
        long_context_output_multiplier=Decimal("1.5"),
    ),
    "gpt-5.6-terra": PriceInfo(
        model_id="gpt-5.6-terra",
        input_per_million=Decimal("2.50"),
        cached_input_per_million=Decimal("0.25"),
        cache_write_per_million=Decimal("3.125"),
        output_per_million=Decimal("15.00"),
        context_window=1_050_000,
        max_output_tokens=128_000,
        long_context_threshold=272_000,
        long_context_input_multiplier=Decimal("2"),
        long_context_output_multiplier=Decimal("1.5"),
    ),
    "gpt-5.6-luna": PriceInfo(
        model_id="gpt-5.6-luna",
        input_per_million=Decimal("1.00"),
        cached_input_per_million=Decimal("0.10"),
        cache_write_per_million=Decimal("1.25"),
        output_per_million=Decimal("6.00"),
        context_window=1_050_000,
        max_output_tokens=128_000,
        long_context_threshold=272_000,
        long_context_input_multiplier=Decimal("2"),
        long_context_output_multiplier=Decimal("1.5"),
    ),
    "gpt-5.5": PriceInfo(
        model_id="gpt-5.5",
        input_per_million=Decimal("5.00"),
        cached_input_per_million=Decimal("0.50"),
        output_per_million=Decimal("30.00"),
        context_window=1_050_000,
        max_output_tokens=128_000,
        long_context_threshold=272_000,
        long_context_input_multiplier=Decimal("2"),
        long_context_output_multiplier=Decimal("1.5"),
    ),
    "gpt-5.5-pro": PriceInfo(
        model_id="gpt-5.5-pro",
        input_per_million=Decimal("30.00"),
        cached_input_per_million=Decimal("30.00"),
        output_per_million=Decimal("180.00"),
        context_window=1_050_000,
        max_output_tokens=128_000,
        long_context_threshold=272_000,
        long_context_input_multiplier=Decimal("2"),
        long_context_output_multiplier=Decimal("1.5"),
    ),
    "gpt-5.4": PriceInfo(
        model_id="gpt-5.4",
        input_per_million=Decimal("2.50"),
        cached_input_per_million=Decimal("0.25"),
        output_per_million=Decimal("15.00"),
        context_window=1_050_000,
        max_output_tokens=128_000,
        long_context_threshold=272_000,
        long_context_input_multiplier=Decimal("2"),
        long_context_output_multiplier=Decimal("1.5"),
    ),
    "gpt-5.4-mini": PriceInfo(
        model_id="gpt-5.4-mini",
        input_per_million=Decimal("0.75"),
        cached_input_per_million=Decimal("0.075"),
        output_per_million=Decimal("4.50"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "gpt-5": PriceInfo(
        model_id="gpt-5",
        input_per_million=Decimal("1.25"),
        cached_input_per_million=Decimal("0.125"),
        output_per_million=Decimal("10.00"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "gpt-5.1": PriceInfo(
        model_id="gpt-5.1",
        input_per_million=Decimal("1.25"),
        cached_input_per_million=Decimal("0.125"),
        output_per_million=Decimal("10.00"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "gpt-5-codex": PriceInfo(
        model_id="gpt-5-codex",
        input_per_million=Decimal("1.25"),
        cached_input_per_million=Decimal("0.125"),
        output_per_million=Decimal("10.00"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "gpt-5.1-codex": PriceInfo(
        model_id="gpt-5.1-codex",
        input_per_million=Decimal("1.25"),
        cached_input_per_million=Decimal("0.125"),
        output_per_million=Decimal("10.00"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "gpt-5.1-codex-max": PriceInfo(
        model_id="gpt-5.1-codex-max",
        input_per_million=Decimal("1.25"),
        cached_input_per_million=Decimal("0.125"),
        output_per_million=Decimal("10.00"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "gpt-5.1-codex-mini": PriceInfo(
        model_id="gpt-5.1-codex-mini",
        input_per_million=Decimal("0.25"),
        cached_input_per_million=Decimal("0.025"),
        output_per_million=Decimal("2.00"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "gpt-5.2": PriceInfo(
        model_id="gpt-5.2",
        input_per_million=Decimal("1.75"),
        cached_input_per_million=Decimal("0.175"),
        output_per_million=Decimal("14.00"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "gpt-5.2-codex": PriceInfo(
        model_id="gpt-5.2-codex",
        input_per_million=Decimal("1.75"),
        cached_input_per_million=Decimal("0.175"),
        output_per_million=Decimal("14.00"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "gpt-5.3-codex": PriceInfo(
        model_id="gpt-5.3-codex",
        input_per_million=Decimal("1.75"),
        cached_input_per_million=Decimal("0.175"),
        output_per_million=Decimal("14.00"),
        context_window=400_000,
        max_output_tokens=128_000,
    ),
    "codex-mini-latest": PriceInfo(
        model_id="codex-mini-latest",
        input_per_million=Decimal("1.50"),
        cached_input_per_million=Decimal("0.375"),
        output_per_million=Decimal("6.00"),
        context_window=200_000,
        max_output_tokens=100_000,
    ),
}

SNAPSHOT_ALIASES = {
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5",
    "gpt-5.1",
    "gpt-5-codex",
    "gpt-5.1-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
    "gpt-5.2",
    "gpt-5.2-codex",
    "gpt-5.3-codex",
}

PUBLIC_MODEL_ALIASES = {
    "gpt-5.6": "gpt-5.6-sol",
}

CLOSEST_PUBLIC_MODEL_MAP = {
    "gpt-5.3-codex-spark": "gpt-5.3-codex",
    "gpt-5-codex-mini": "gpt-5.1-codex-mini",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate OpenAI API token costs from Codex rollout logs.",
        suggest_on_error=True,
    )
    parser.add_argument("--begin", required=True, help="Inclusive start date/time.")
    parser.add_argument("--end", required=True, help="Inclusive end date/time.")
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=None,
        help="Override CODEX_HOME. Defaults to $CODEX_HOME or ~/.codex.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--archived-only",
        action="store_true",
        help="Scan archived rollout files only.",
    )
    group.add_argument(
        "--active-only",
        action="store_true",
        help="Scan active rollout files only.",
    )
    parser.add_argument(
        "--timezone",
        default=None,
        help="IANA timezone for date-only parsing and day grouping. Defaults to local timezone.",
    )
    parser.add_argument(
        "--unknown-model-policy",
        choices=("closest-public", "strict-official", "exclude-unknown"),
        default="closest-public",
        help="How to handle unknown OpenAI model ids.",
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        timezone_value = resolve_timezone(args.timezone)
        begin_at, end_at = parse_time_range(args.begin, args.end, timezone_value)
        report = build_report(
            codex_home=args.codex_home,
            begin_at=begin_at,
            end_at=end_at,
            display_timezone=timezone_value,
            archived_only=args.archived_only,
            active_only=args.active_only,
            unknown_model_policy=args.unknown_model_policy,
        )
        emit(report, as_json=args.json)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        logger.exception("Unexpected error")
        return 1


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


def parse_time_range(begin_value: str, end_value: str, display_timezone: tzinfo) -> tuple[datetime, datetime]:
    begin_at = parse_cli_datetime(begin_value, display_timezone, end_of_range=False)
    end_at = parse_cli_datetime(end_value, display_timezone, end_of_range=True)
    if end_at < begin_at:
        raise ValueError("--end must be on or after --begin")
    return begin_at.astimezone(UTC), end_at.astimezone(UTC)


def parse_cli_datetime(value: str, display_timezone: tzinfo, *, end_of_range: bool) -> datetime:
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


def parse_rollout_timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def build_report(
    *,
    codex_home: Path | None,
    begin_at: datetime,
    end_at: datetime,
    display_timezone: tzinfo,
    archived_only: bool,
    active_only: bool,
    unknown_model_policy: str,
) -> dict[str, Any]:
    paths = resolve_paths(codex_home)
    loaded_event_set = load_usage_events_from_sqlite(
        paths=paths,
        begin_at=begin_at,
        end_at=end_at,
        display_timezone=display_timezone,
        archived_only=archived_only,
        active_only=active_only,
        unknown_model_policy=unknown_model_policy,
    )

    return summarize_events(
        loaded_event_set.events,
        begin_at=begin_at,
        end_at=end_at,
        display_timezone=display_timezone,
        paths=paths,
        scanned_rollouts=loaded_event_set.scanned_rollouts,
        warnings=loaded_event_set.warnings,
        event_counter=loaded_event_set.event_counter,
        unpriced_counter=loaded_event_set.unpriced_counter,
        unknown_model_policy=unknown_model_policy,
        scan_source=loaded_event_set.scan_source,
    )


def resolve_paths(codex_home: Path | None) -> RolloutPaths:
    base = codex_home
    if base is None:
        env_value = os.environ.get("CODEX_HOME")
        base = Path(env_value) if env_value else Path.home() / ".codex"
    base = base.expanduser()
    return RolloutPaths(
        codex_home=base,
        sessions_dir=base / "sessions",
        archived_sessions_dir=base / "archived_sessions",
    )


def load_usage_events_from_sqlite(
    *,
    paths: Any,
    begin_at: datetime,
    end_at: datetime,
    display_timezone: tzinfo,
    archived_only: bool,
    active_only: bool,
    unknown_model_policy: str,
) -> LoadedEventSet:
    db_path = DB.default_db_path(paths.codex_home)
    if not db_path.exists():
        raise RuntimeError(
            f"SQLite cache not found at {db_path}. Run "
            "`uv run --python 3.14 scripts/inspect_rollout.py refresh` first."
        )

    warnings: list[str] = []
    event_counter = Counter()
    unpriced_counter = Counter()
    events: list[UsageEvent] = []
    sessions_with_approximate_usage: set[str] = set()
    sessions_with_missing_cache_writes: set[str] = set()

    try:
        with closing(DB.open_db(db_path)) as conn:
            if not has_token_usage_rows(conn):
                raise RuntimeError(
                    f"SQLite cache at {db_path} has no token usage data. Run "
                    "`uv run --python 3.14 scripts/inspect_rollout.py refresh` first."
                )
            scanned_rollouts = count_sqlite_sessions(
                conn,
                archived_only=archived_only,
                active_only=active_only,
            )
            for row in fetch_sqlite_usage_rows(
                conn,
                begin_at=begin_at,
                end_at=end_at,
                archived_only=archived_only,
                active_only=active_only,
            ):
                event = usage_event_from_sqlite_row(
                    row,
                    display_timezone=display_timezone,
                    unknown_model_policy=unknown_model_policy,
                    event_counter=event_counter,
                    unpriced_counter=unpriced_counter,
                )
                events.append(event)
                if event.usage_is_approximate:
                    sessions_with_approximate_usage.add(event.session_id)
                if (
                    event.cost_estimate is not None
                    and not event.cost_estimate.exact
                ):
                    sessions_with_missing_cache_writes.add(event.session_id)
    except sqlite3.Error as exc:
        raise RuntimeError(f"failed to query SQLite cache at {db_path}: {exc}") from exc

    for session_id in sorted(sessions_with_approximate_usage):
        warnings.append(
            f"{session_id}: some requests used cumulative-token fallback because last_token_usage was absent"
        )
    for session_id in sorted(sessions_with_missing_cache_writes):
        warnings.append(
            f"{session_id}: Codex 0.144.1 did not persist GPT-5.6 cache_write_tokens; "
            "cost is bounded from zero writes to all non-cached input being written"
        )
    return LoadedEventSet(
        events=events,
        warnings=warnings,
        event_counter=event_counter,
        unpriced_counter=unpriced_counter,
        scanned_rollouts=scanned_rollouts,
        scan_source="sqlite",
    )


def has_token_usage_rows(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM token_usage_events LIMIT 1").fetchone()
    return row is not None


def count_sqlite_sessions(
    conn: sqlite3.Connection,
    *,
    archived_only: bool,
    active_only: bool,
) -> int:
    where_clause, params = session_filter_sql(
        archived_only=archived_only,
        active_only=active_only,
    )
    row = conn.execute(
        f"SELECT COUNT(*) AS count FROM sessions s WHERE {where_clause}",
        params,
    ).fetchone()
    return int(row["count"]) if row is not None else 0


def fetch_sqlite_usage_rows(
    conn: sqlite3.Connection,
    *,
    begin_at: datetime,
    end_at: datetime,
    archived_only: bool,
    active_only: bool,
) -> Iterable[sqlite3.Row]:
    session_where_clause, session_params = session_filter_sql(
        archived_only=archived_only,
        active_only=active_only,
    )
    params = [begin_at.isoformat(), end_at.isoformat(), *session_params]
    query = f"""
        SELECT
            tue.session_id,
            s.thread_name,
            s.file_path,
            s.archived,
            tue.model_provider,
            tue.timestamp,
            tue.raw_model,
            tue.usage_source,
            tue.is_approximate,
            tue.input_tokens,
            tue.cached_input_tokens,
            tue.cache_write_tokens,
            tue.output_tokens,
            tue.reasoning_output_tokens,
            tue.total_tokens
        FROM token_usage_events tue
        JOIN sessions s ON s.session_id = tue.session_id
        WHERE tue.timestamp >= ?
          AND tue.timestamp <= ?
          AND {session_where_clause}
        ORDER BY tue.timestamp, tue.id
    """
    return conn.execute(query, params)


def session_filter_sql(
    *,
    archived_only: bool,
    active_only: bool,
) -> tuple[str, list[Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if archived_only:
        clauses.append("s.archived = ?")
        params.append(1)
    elif active_only:
        clauses.append("s.archived = ?")
        params.append(0)
    return " AND ".join(clauses), params


def usage_event_from_sqlite_row(
    row: sqlite3.Row,
    *,
    display_timezone: tzinfo,
    unknown_model_policy: str,
    event_counter: Counter[str],
    unpriced_counter: Counter[str],
) -> UsageEvent:
    provider = string_or_none(row["model_provider"])
    raw_model = string_or_none(row["raw_model"])
    token_usage = TokenUsage(
        input_tokens=max(int_or_zero(row["input_tokens"]), 0),
        cached_input_tokens=max(int_or_zero(row["cached_input_tokens"]), 0),
        cache_write_tokens=(
            max(int_or_zero(row["cache_write_tokens"]), 0)
            if row["cache_write_tokens"] is not None
            else None
        ),
        output_tokens=max(int_or_zero(row["output_tokens"]), 0),
        reasoning_output_tokens=max(int_or_zero(row["reasoning_output_tokens"]), 0),
        total_tokens=max(int_or_zero(row["total_tokens"]), 0),
    )
    timestamp = parse_rollout_timestamp(string_or_none(row["timestamp"]))
    if timestamp is None:
        raise ValueError("token_usage_events row is missing a valid timestamp")
    model_resolution = resolve_pricing_model(
        raw_model,
        provider=provider,
        unknown_model_policy=unknown_model_policy,
    )
    if model_resolution.pricing_model is None:
        unpriced_key = model_resolution.raw_model or provider or "missing-model"
        unpriced_counter[unpriced_key] += 1
        cost_estimate = None
    else:
        cost_estimate = compute_cost_estimate(
            pricing_model=model_resolution.pricing_model,
            token_usage=token_usage,
        )
    long_context = is_long_context_request(model_resolution.pricing_model, token_usage)
    usage_is_approximate = bool(row["is_approximate"])
    event_counter["priced" if cost_estimate is not None else "unpriced"] += 1
    if usage_is_approximate:
        event_counter["approximate_usage"] += 1
    if long_context:
        event_counter["long_context_pricing"] += 1
    if model_resolution.estimated:
        event_counter["estimated_model_mapping"] += 1
    if cost_estimate is not None and not cost_estimate.exact:
        event_counter["missing_cache_write_usage"] += 1
    local_timestamp = timestamp.astimezone(display_timezone)
    return UsageEvent(
        session_id=str(row["session_id"]),
        thread_name=string_or_none(row["thread_name"]),
        path=str(row["file_path"]),
        archived=bool(row["archived"]),
        provider=provider,
        timestamp=timestamp,
        local_day=local_timestamp.date().isoformat(),
        raw_model=raw_model,
        pricing_model=model_resolution.pricing_model,
        estimated_model=model_resolution.estimated,
        resolution_reason=model_resolution.resolution_reason,
        exact_usage_source=str(row["usage_source"]),
        usage_is_approximate=usage_is_approximate,
        long_context_pricing=long_context,
        token_usage=token_usage,
        cost_estimate=cost_estimate,
    )


def resolve_pricing_model(
    raw_model: str | None,
    *,
    provider: str | None,
    unknown_model_policy: str,
) -> ModelResolution:
    if provider not in (None, "", "openai"):
        return ModelResolution(
            raw_model=raw_model,
            pricing_model=None,
            estimated=False,
            resolution_reason=f"provider:{provider}",
            excluded=True,
        )
    if raw_model is None:
        return ModelResolution(
            raw_model=None,
            pricing_model=None,
            estimated=False,
            resolution_reason="missing-model",
            excluded=True,
        )
    canonical_model = PUBLIC_MODEL_ALIASES.get(raw_model, raw_model)
    if canonical_model in PRICE_CATALOG:
        return ModelResolution(
            raw_model=raw_model,
            pricing_model=canonical_model,
            estimated=False,
            resolution_reason=(
                f"public-alias:{canonical_model}"
                if canonical_model != raw_model
                else "exact"
            ),
            excluded=False,
        )

    base_model = strip_snapshot_suffix(raw_model)
    canonical_base_model = PUBLIC_MODEL_ALIASES.get(base_model, base_model)
    if canonical_base_model in PRICE_CATALOG and canonical_base_model in SNAPSHOT_ALIASES:
        return ModelResolution(
            raw_model=raw_model,
            pricing_model=canonical_base_model,
            estimated=False,
            resolution_reason="snapshot-alias",
            excluded=False,
        )

    mapped_model = CLOSEST_PUBLIC_MODEL_MAP.get(raw_model)
    if mapped_model is not None and unknown_model_policy == "closest-public":
        return ModelResolution(
            raw_model=raw_model,
            pricing_model=mapped_model,
            estimated=True,
            resolution_reason=f"closest-public:{mapped_model}",
            excluded=False,
        )

    return ModelResolution(
        raw_model=raw_model,
        pricing_model=None,
        estimated=False,
        resolution_reason="unknown-openai-model",
        excluded=True,
    )


def strip_snapshot_suffix(model_id: str) -> str:
    parts = model_id.rsplit("-", 3)
    if len(parts) != 4:
        return model_id
    tail = "-".join(parts[-3:])
    try:
        date.fromisoformat(tail)
    except ValueError:
        return model_id
    return parts[0]


def compute_cost(*, pricing_model: str, token_usage: TokenUsage) -> Decimal:
    """Return exact cost, rejecting token usage with unknown billable cache writes."""
    estimate = compute_cost_estimate(pricing_model=pricing_model, token_usage=token_usage)
    if not estimate.exact:
        raise ValueError("cache_write_tokens are required for an exact GPT-5.6 cost")
    return estimate.lower_usd


def compute_cost_estimate(*, pricing_model: str, token_usage: TokenUsage) -> CostEstimate:
    price = PRICE_CATALOG[pricing_model]
    long_context = is_long_context_request(pricing_model, token_usage)
    input_rate = price.input_per_million
    cached_rate = price.cached_input_per_million
    cache_write_rate = price.cache_write_per_million
    output_rate = price.output_per_million
    if long_context:
        input_rate *= price.long_context_input_multiplier
        cached_rate *= price.long_context_input_multiplier
        if cache_write_rate is not None:
            cache_write_rate *= price.long_context_input_multiplier
        output_rate *= price.long_context_output_multiplier
    cached_cost = token_cost(token_usage.cached_input_tokens, cached_rate)
    # Reasoning tokens are already included in output_tokens in Codex rollouts.
    output_cost = token_cost(token_usage.output_tokens, output_rate)
    fixed_cost = cached_cost + output_cost

    if cache_write_rate is None:
        exact_cost = fixed_cost + token_cost(token_usage.uncached_input_tokens, input_rate)
        rounded = exact_cost.quantize(USD_PRECISION, rounding=ROUND_HALF_UP)
        return CostEstimate(lower_usd=rounded, upper_usd=rounded)

    if token_usage.cache_write_tokens is not None:
        cache_write_tokens = min(
            token_usage.cache_write_tokens,
            token_usage.uncached_input_tokens,
        )
        exact_cost = (
            fixed_cost
            + token_cost(token_usage.standard_input_tokens, input_rate)
            + token_cost(cache_write_tokens, cache_write_rate)
        )
        rounded = exact_cost.quantize(USD_PRECISION, rounding=ROUND_HALF_UP)
        return CostEstimate(lower_usd=rounded, upper_usd=rounded)

    ordinary_input_cost = token_cost(token_usage.uncached_input_tokens, input_rate)
    all_cache_write_cost = token_cost(token_usage.uncached_input_tokens, cache_write_rate)
    lower = fixed_cost + min(ordinary_input_cost, all_cache_write_cost)
    upper = fixed_cost + max(ordinary_input_cost, all_cache_write_cost)
    return CostEstimate(
        lower_usd=lower.quantize(USD_PRECISION, rounding=ROUND_HALF_UP),
        upper_usd=upper.quantize(USD_PRECISION, rounding=ROUND_HALF_UP),
    )


def is_long_context_request(pricing_model: str | None, token_usage: TokenUsage) -> bool:
    if pricing_model is None:
        return False
    price = PRICE_CATALOG.get(pricing_model)
    if price is None or price.long_context_threshold is None:
        return False
    return token_usage.input_tokens > price.long_context_threshold


def token_cost(tokens: int, per_million: Decimal) -> Decimal:
    return (Decimal(tokens) / Decimal(1_000_000)) * per_million


def summarize_events(
    events: list[UsageEvent],
    *,
    begin_at: datetime,
    end_at: datetime,
    display_timezone: tzinfo,
    paths: Any,
    scanned_rollouts: int,
    warnings: list[str],
    event_counter: Counter[str],
    unpriced_counter: Counter[str],
    unknown_model_policy: str,
    scan_source: str,
) -> dict[str, Any]:
    total_input_tokens = sum(event.token_usage.input_tokens for event in events)
    total_cached_input_tokens = sum(event.token_usage.cached_input_tokens for event in events)
    total_uncached_input_tokens = sum(event.token_usage.uncached_input_tokens for event in events)
    total_cache_write_tokens = sum(
        event.token_usage.cache_write_tokens or 0 for event in events
    )
    total_output_tokens = sum(event.token_usage.output_tokens for event in events)
    total_reasoning_output_tokens = sum(event.token_usage.reasoning_output_tokens for event in events)
    total_cost_lower_usd = sum(
        (event.cost_estimate.lower_usd if event.cost_estimate is not None else Decimal("0"))
        for event in events
    )
    total_cost_upper_usd = sum(
        (event.cost_estimate.upper_usd if event.cost_estimate is not None else Decimal("0"))
        for event in events
    )

    by_day = defaultdict(
        lambda: {
            "events": 0,
            "sessions": set(),
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 0,
            "cache_write_tokens": 0,
            "cache_write_unknown_events": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "cost_lower_usd": Decimal("0"),
            "cost_upper_usd": Decimal("0"),
        }
    )
    by_model = defaultdict(
        lambda: {
            "events": 0,
            "sessions": set(),
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 0,
            "cache_write_tokens": 0,
            "cache_write_unknown_events": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "cost_lower_usd": Decimal("0"),
            "cost_upper_usd": Decimal("0"),
            "estimated_events": 0,
            "long_context_events": 0,
        }
    )
    by_session = defaultdict(
        lambda: {
            "thread_name": None,
            "path": None,
            "archived": False,
            "provider": None,
            "models": Counter(),
            "events": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 0,
            "cache_write_tokens": 0,
            "cache_write_unknown_events": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "cost_lower_usd": Decimal("0"),
            "cost_upper_usd": Decimal("0"),
            "first_timestamp": None,
            "last_timestamp": None,
        }
    )
    estimated_mappings = Counter()

    for event in events:
        day_row = by_day[event.local_day]
        day_row["events"] += 1
        day_row["sessions"].add(event.session_id)
        day_row["input_tokens"] += event.token_usage.input_tokens
        day_row["cached_input_tokens"] += event.token_usage.cached_input_tokens
        day_row["uncached_input_tokens"] += event.token_usage.uncached_input_tokens
        day_row["cache_write_tokens"] += event.token_usage.cache_write_tokens or 0
        day_row["output_tokens"] += event.token_usage.output_tokens
        day_row["reasoning_output_tokens"] += event.token_usage.reasoning_output_tokens
        if event.cost_estimate is not None:
            day_row["cost_lower_usd"] += event.cost_estimate.lower_usd
            day_row["cost_upper_usd"] += event.cost_estimate.upper_usd
            if not event.cost_estimate.exact:
                day_row["cache_write_unknown_events"] += 1

        model_key = event.pricing_model or "unpriced"
        model_row = by_model[model_key]
        model_row["events"] += 1
        model_row["sessions"].add(event.session_id)
        model_row["input_tokens"] += event.token_usage.input_tokens
        model_row["cached_input_tokens"] += event.token_usage.cached_input_tokens
        model_row["uncached_input_tokens"] += event.token_usage.uncached_input_tokens
        model_row["cache_write_tokens"] += event.token_usage.cache_write_tokens or 0
        model_row["output_tokens"] += event.token_usage.output_tokens
        model_row["reasoning_output_tokens"] += event.token_usage.reasoning_output_tokens
        if event.cost_estimate is not None:
            model_row["cost_lower_usd"] += event.cost_estimate.lower_usd
            model_row["cost_upper_usd"] += event.cost_estimate.upper_usd
            if not event.cost_estimate.exact:
                model_row["cache_write_unknown_events"] += 1
        if event.estimated_model:
            model_row["estimated_events"] += 1
            estimated_mappings[f"{event.raw_model} -> {event.pricing_model}"] += 1
        if event.long_context_pricing:
            model_row["long_context_events"] += 1

        session_row = by_session[event.session_id]
        session_row["thread_name"] = event.thread_name
        session_row["path"] = event.path
        session_row["archived"] = event.archived
        session_row["provider"] = event.provider
        session_row["events"] += 1
        session_row["models"][model_key] += 1
        session_row["input_tokens"] += event.token_usage.input_tokens
        session_row["cached_input_tokens"] += event.token_usage.cached_input_tokens
        session_row["uncached_input_tokens"] += event.token_usage.uncached_input_tokens
        session_row["cache_write_tokens"] += event.token_usage.cache_write_tokens or 0
        session_row["output_tokens"] += event.token_usage.output_tokens
        session_row["reasoning_output_tokens"] += event.token_usage.reasoning_output_tokens
        if event.cost_estimate is not None:
            session_row["cost_lower_usd"] += event.cost_estimate.lower_usd
            session_row["cost_upper_usd"] += event.cost_estimate.upper_usd
            if not event.cost_estimate.exact:
                session_row["cache_write_unknown_events"] += 1
        first_ts = session_row["first_timestamp"]
        last_ts = session_row["last_timestamp"]
        session_row["first_timestamp"] = event.timestamp if first_ts is None or event.timestamp < first_ts else first_ts
        session_row["last_timestamp"] = event.timestamp if last_ts is None or event.timestamp > last_ts else last_ts

    summary = {
        "range": {
            "begin_utc": begin_at.isoformat(),
            "end_utc": end_at.isoformat(),
            "timezone": timezone_name(display_timezone),
        },
        "pricing": {
            "pricing_mode": "standard",
            "catalog_as_of": PRICE_CATALOG_AS_OF,
            "unknown_model_policy": unknown_model_policy,
            "reasoning_note": (
                "reasoning_output_tokens are reported separately but not double-counted because "
                "they appear to be included in output_tokens in Codex rollout token_count events"
            ),
            "cache_write_note": (
                "GPT-5.6 cache writes are billed at 1.25x uncached input. Codex 0.144.1 "
                "does not persist cache_write_tokens, so affected events are reported as a "
                "lower/upper bound."
            ),
            "sources": SOURCE_URLS,
        },
        "scan": {
            "source": scan_source,
            "codex_home": str(paths.codex_home),
            "db_path": str(DB.default_db_path(paths.codex_home)),
            "sessions_dir": str(paths.sessions_dir),
            "archived_sessions_dir": str(paths.archived_sessions_dir),
            "rollouts_scanned": scanned_rollouts,
            "usage_events_in_range": len(events),
            "priced_events": event_counter["priced"],
            "unpriced_events": event_counter["unpriced"],
            "approximate_usage_events": event_counter["approximate_usage"],
            "estimated_model_mapping_events": event_counter["estimated_model_mapping"],
            "long_context_pricing_events": event_counter["long_context_pricing"],
            "missing_cache_write_usage_events": event_counter["missing_cache_write_usage"],
        },
        "totals": {
            "session_count": len(by_session),
            "priced_session_count": sum(
                1 for row in by_session.values() if row["cost_upper_usd"] > 0
            ),
            "input_tokens": total_input_tokens,
            "cached_input_tokens": total_cached_input_tokens,
            "uncached_input_tokens": total_uncached_input_tokens,
            "cache_write_tokens": total_cache_write_tokens,
            "cache_write_unknown_events": event_counter["missing_cache_write_usage"],
            "output_tokens": total_output_tokens,
            "reasoning_output_tokens": total_reasoning_output_tokens,
            **cost_summary_fields(total_cost_lower_usd, total_cost_upper_usd),
        },
        "by_day": [
            {
                "day": day,
                "events": row["events"],
                "session_count": len(row["sessions"]),
                "input_tokens": row["input_tokens"],
                "cached_input_tokens": row["cached_input_tokens"],
                "uncached_input_tokens": row["uncached_input_tokens"],
                "cache_write_tokens": row["cache_write_tokens"],
                "cache_write_unknown_events": row["cache_write_unknown_events"],
                "output_tokens": row["output_tokens"],
                "reasoning_output_tokens": row["reasoning_output_tokens"],
                **cost_summary_fields(row["cost_lower_usd"], row["cost_upper_usd"]),
            }
            for day, row in sorted(by_day.items())
        ],
        "by_model": [
            {
                "model": model,
                "events": row["events"],
                "session_count": len(row["sessions"]),
                "input_tokens": row["input_tokens"],
                "cached_input_tokens": row["cached_input_tokens"],
                "uncached_input_tokens": row["uncached_input_tokens"],
                "cache_write_tokens": row["cache_write_tokens"],
                "cache_write_unknown_events": row["cache_write_unknown_events"],
                "output_tokens": row["output_tokens"],
                "reasoning_output_tokens": row["reasoning_output_tokens"],
                **cost_summary_fields(row["cost_lower_usd"], row["cost_upper_usd"]),
                "estimated_mapping_events": row["estimated_events"],
                "long_context_events": row["long_context_events"],
            }
            for model, row in sorted(
                by_model.items(),
                key=lambda item: (item[1]["cost_upper_usd"], item[1]["events"]),
                reverse=True,
            )
        ],
        "by_session": [
            {
                "session_id": session_id,
                "thread_name": row["thread_name"],
                "path": row["path"],
                "archived": row["archived"],
                "provider": row["provider"],
                "models": dict(row["models"]),
                "events": row["events"],
                "input_tokens": row["input_tokens"],
                "cached_input_tokens": row["cached_input_tokens"],
                "uncached_input_tokens": row["uncached_input_tokens"],
                "cache_write_tokens": row["cache_write_tokens"],
                "cache_write_unknown_events": row["cache_write_unknown_events"],
                "output_tokens": row["output_tokens"],
                "reasoning_output_tokens": row["reasoning_output_tokens"],
                **cost_summary_fields(row["cost_lower_usd"], row["cost_upper_usd"]),
                "first_timestamp": row["first_timestamp"].isoformat() if row["first_timestamp"] else None,
                "last_timestamp": row["last_timestamp"].isoformat() if row["last_timestamp"] else None,
            }
            for session_id, row in sorted(
                by_session.items(),
                key=lambda item: (item[1]["cost_upper_usd"], item[1]["events"]),
                reverse=True,
            )
        ],
        "estimated_mappings": [
            {"mapping": mapping, "events": count}
            for mapping, count in estimated_mappings.most_common()
        ],
        "unpriced": [
            {"key": key, "events": count}
            for key, count in unpriced_counter.most_common()
        ],
        "warnings": dedupe_preserve_order(warnings),
    }
    return summary


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def timezone_name(value: tzinfo) -> str:
    key = getattr(value, "key", None)
    if isinstance(key, str):
        return key
    tzname = value.tzname(datetime.now())
    return tzname or str(value)


def cost_summary_fields(lower: Decimal, upper: Decimal) -> dict[str, float | None]:
    exact = lower == upper
    return {
        "estimated_cost_usd": decimal_to_float(lower) if exact else None,
        "estimated_cost_lower_usd": decimal_to_float(lower),
        "estimated_cost_upper_usd": decimal_to_float(upper),
    }


def decimal_to_float(value: Decimal) -> float:
    return float(value.quantize(USD_PRECISION, rounding=ROUND_HALF_UP))


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


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
    lines.append("OpenAI API Cost Estimate")
    lines.append(
        f"Range: {report['range']['begin_utc']} to {report['range']['end_utc']} "
        f"({report['range']['timezone']})"
    )
    lines.append(
        f"Pricing: standard, catalog as of {pricing['catalog_as_of']}, "
        f"unknown-model policy `{pricing['unknown_model_policy']}`"
    )
    lines.append(
        f"Rollouts scanned: {scan['rollouts_scanned']} | events in range: {scan['usage_events_in_range']} | "
        f"priced: {scan['priced_events']} | unpriced: {scan['unpriced_events']}"
    )
    lines.append(f"Estimated cost: {format_report_cost(totals)}")
    lines.append(
        "Tokens: "
        f"input={format_int(totals['input_tokens'])} "
        f"uncached_input={format_int(totals['uncached_input_tokens'])} "
        f"cached_input={format_int(totals['cached_input_tokens'])} "
        f"cache_write_known={format_int(totals['cache_write_tokens'])} "
        f"output={format_int(totals['output_tokens'])} "
        f"reasoning={format_int(totals['reasoning_output_tokens'])}"
    )
    if totals["cache_write_unknown_events"]:
        lines.append(
            "Cache-write accounting: "
            f"{format_int(totals['cache_write_unknown_events'])} GPT-5.6 usage events lack "
            "persisted cache_write_tokens; the displayed cost is a bounded range."
        )
    lines.append(
        "Note: reasoning tokens are surfaced separately but not double-counted in the billed total "
        "because rollout output tokens already appear to include them."
    )

    if report["by_day"]:
        lines.append("")
        lines.append("By Day")
        for row in report["by_day"]:
            lines.append(
                f"{row['day']}: {format_report_cost(row)} | "
                f"events={row['events']} | sessions={row['session_count']} | "
                f"input={format_int(row['input_tokens'])} | output={format_int(row['output_tokens'])}"
            )

    if report["by_model"]:
        lines.append("")
        lines.append("By Model")
        for row in report["by_model"]:
            suffix = ""
            if row["estimated_mapping_events"]:
                suffix += f" | estimated_mappings={row['estimated_mapping_events']}"
            if row["long_context_events"]:
                suffix += f" | long_context={row['long_context_events']}"
            if row["cache_write_unknown_events"]:
                suffix += f" | unknown_cache_writes={row['cache_write_unknown_events']}"
            lines.append(
                f"{row['model']}: {format_report_cost(row)} | "
                f"events={row['events']} | sessions={row['session_count']} | "
                f"input={format_int(row['input_tokens'])} | output={format_int(row['output_tokens'])}{suffix}"
            )

    if report["by_session"]:
        lines.append("")
        lines.append("Top Sessions")
        for row in report["by_session"][:10]:
            model_list = ", ".join(row["models"].keys()) or "unknown"
            title = row["thread_name"] or row["session_id"]
            lines.append(
                f"{title}: {format_report_cost(row)} | "
                f"models={model_list} | events={row['events']} | path={row['path']}"
            )

    if report["estimated_mappings"]:
        lines.append("")
        lines.append("Estimated Mappings")
        for row in report["estimated_mappings"]:
            lines.append(f"{row['mapping']}: {row['events']} events")

    if report["unpriced"]:
        lines.append("")
        lines.append("Unpriced")
        for row in report["unpriced"]:
            lines.append(f"{row['key']}: {row['events']} events")

    if report["warnings"]:
        lines.append("")
        lines.append("Warnings")
        for warning in report["warnings"]:
            lines.append(f"- {warning}")

    lines.append("")
    lines.append("Sources")
    for source in pricing["sources"]:
        lines.append(f"- {source}")
    return "\n".join(lines)


def format_usd(amount: Decimal) -> str:
    return f"${amount.quantize(USD_DISPLAY_PRECISION, rounding=ROUND_HALF_UP):,.2f}"


def format_report_cost(row: dict[str, Any]) -> str:
    exact = row.get("estimated_cost_usd")
    if exact is not None:
        return format_usd(Decimal(str(exact)))
    lower = Decimal(str(row["estimated_cost_lower_usd"]))
    upper = Decimal(str(row["estimated_cost_upper_usd"]))
    lower_display = format_usd(lower)
    upper_display = format_usd(upper)
    if lower_display == upper_display and lower != upper:
        lower_display = f"${lower.quantize(USD_PRECISION, rounding=ROUND_HALF_UP):,.6f}"
        upper_display = f"${upper.quantize(USD_PRECISION, rounding=ROUND_HALF_UP):,.6f}"
    return f"{lower_display}–{upper_display}"


def format_int(value: int) -> str:
    return f"{value:,}"


if __name__ == "__main__":
    sys.exit(main())
