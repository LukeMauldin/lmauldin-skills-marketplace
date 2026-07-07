#!/usr/bin/env python3
"""Find the current sprint list for a sprint folder based on date.

Usage:
    # Current server sprint (today)
    python scripts/get_current_sprint.py --team server

    # Specify date (ISO-8601)
    python scripts/get_current_sprint.py --team server --date 2026-01-02

    # Output only the list ID
    python scripts/get_current_sprint.py --team server --format id

    # Fallback to latest sprint if no date match
    python scripts/get_current_sprint.py --team server --fallback latest

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Output (JSON format, default):
    {
        "list_id": "901234567890",
        "list_name": "Sprint 78 (12/29 - 1/11)",
        "folder_id": "90100118193",
        "board_url": "https://app.clickup.com/...",
        "date_range": { "start": "2025-12-29", "end": "2026-01-11" }
    }

Output (--format id):
    901234567890
"""
from __future__ import annotations

import argparse
import json
import logging
from clickup_auth import resolve_token
import re
import sys
import urllib.error
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from get_folder import get_folder_lists

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

BASE_URL = "https://api.clickup.com/api/v2"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)

WORKSPACE_ID = "12606327"
SPACE_ID = "16581563"
BOARD_URL_TEMPLATE = "https://app.clickup.com/12606327/v/b/li/{list_id}?pr=16581563"

FOLDER_PRESETS: dict[str, str] = {
    "server": "90100118193",
    "coach": "90100118119",
    "tv": "90100118129",
}

SPRINT_RE = re.compile(r"Sprint\s+(?P<number>\d+)", re.IGNORECASE)
DATE_RANGE_RE = re.compile(
    r"(?P<start>\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*-\s*"
    r"(?P<end>\d{1,2}/\d{1,2}(?:/\d{2,4})?)"
)
DATE_PARTS_RE = re.compile(r"^(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>\d{2,4}))?$")


@dataclass(frozen=True)
class SprintList:
    list_id: str
    name: str
    sprint_number: int | None
    start_date: date | None
    end_date: date | None
    raw_range: str | None


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose, args.quiet)

    try:
        return run(args)
    except KeyboardInterrupt:
        return 130
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        logger.error("API error %d: %s", e.code, error_body)
        return 1
    except urllib.error.URLError as e:
        logger.error("Network error: %s", e.reason)
        return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser_kwargs: dict[str, Any] = {
        "description": __doc__.splitlines()[0],
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": __doc__,
    }
    if sys.version_info >= (3, 14):
        parser_kwargs["suggest_on_error"] = True
    parser = argparse.ArgumentParser(**parser_kwargs)
    parser.add_argument(
        "--date",
        dest="target_date",
        type=parse_iso_date,
        help="Target date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "summary", "id"],
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived lists in the folder query.",
    )
    parser.add_argument(
        "--include-candidates",
        action="store_true",
        help="Include parsed sprint candidates in JSON output.",
    )
    parser.add_argument(
        "--fallback",
        choices=["none", "latest"],
        default="none",
        help="Fallback behavior if no sprint covers the date (default: none).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for info, -vv for debug).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stderr messages (only output result).",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--team",
        choices=sorted(FOLDER_PRESETS.keys()),
        help="Team preset (default: server).",
    )
    group.add_argument(
        "--folder-id",
        help="ClickUp folder ID for the sprint lists.",
    )

    return parser.parse_args(argv)


def configure_logging(verbosity: int, quiet: bool) -> None:
    if quiet:
        level = logging.CRITICAL + 1
    else:
        level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(levelname)s: %(message)s",
    )


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc


def run(args: argparse.Namespace) -> int:
    token = resolve_token()
    if not token:
        logger.error("No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt")
        return 1

    folder_id, folder_label = resolve_folder(args)

    target_date = args.target_date or date.today()
    try:
        matched, match_type, sprints = resolve_current_sprint(
            token=token,
            folder_id=folder_id,
            target_date=target_date,
            include_archived=args.include_archived,
            fallback=args.fallback,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    output = build_output(
        matched=matched,
        match_type=match_type,
        target_date=target_date,
        folder_id=folder_id,
        folder_label=folder_label,
        include_candidates=args.include_candidates,
        candidates=sprints,
    )
    render_output(output, args.format)
    return 0


def resolve_current_sprint(
    token: str,
    folder_id: str,
    target_date: date | None = None,
    include_archived: bool = False,
    fallback: str = "none",
) -> tuple[SprintList, str | None, list[SprintList]]:
    target_date = target_date or date.today()
    lists = fetch_lists(folder_id, token, include_archived=include_archived)
    if not lists:
        raise ValueError(f"No lists found for folder {folder_id}")

    sprints: list[SprintList] = []
    for list_obj in lists:
        sprint = parse_sprint_list(list_obj, target_date)
        if sprint is not None:
            sprints.append(sprint)

    if not sprints:
        raise ValueError(f"No sprint lists found in folder {folder_id}")

    matched = select_current_sprint(sprints, target_date)
    match_type: str | None = None
    if matched is not None:
        match_type = "date_range"
    elif fallback == "latest":
        matched = select_latest_sprint(sprints)
        match_type = "latest"

    if matched is None:
        raise ValueError(
            f"No sprint covers {target_date.isoformat()} in folder {folder_id}. "
            "Use --fallback latest to pick newest."
        )

    return matched, match_type, sprints


def resolve_current_sprint_list_id(
    token: str,
    folder_id: str,
    target_date: date | None = None,
    include_archived: bool = False,
    fallback: str = "none",
) -> tuple[str, str | None]:
    matched, match_type, _ = resolve_current_sprint(
        token=token,
        folder_id=folder_id,
        target_date=target_date,
        include_archived=include_archived,
        fallback=fallback,
    )
    return matched.list_id, match_type


def resolve_folder(args: argparse.Namespace) -> tuple[str, str]:
    if args.folder_id:
        return args.folder_id, "custom"
    team = args.team or "server"
    return FOLDER_PRESETS[team], team


def fetch_lists(folder_id: str, token: str, include_archived: bool) -> list[dict[str, Any]]:
    # Delegates to the shared helper in get_folder.py (GET /folder/{id}/list).
    # Behavior is identical: archived=true when include_archived, else archived=false.
    return get_folder_lists(folder_id, token, include_archived=include_archived)


def parse_sprint_list(list_obj: dict[str, Any], target_date: date) -> SprintList | None:
    name = str(list_obj.get("name", ""))
    sprint_match = SPRINT_RE.search(name)
    if not sprint_match:
        return None

    sprint_number = int(sprint_match.group("number"))
    range_match = DATE_RANGE_RE.search(name)

    start_date = None
    end_date = None
    raw_range = None

    if range_match:
        start_raw = range_match.group("start")
        end_raw = range_match.group("end")
        raw_range = f"{start_raw} - {end_raw}"
        try:
            start_date, end_date = resolve_date_range(start_raw, end_raw, target_date)
        except ValueError as exc:
            logger.debug("Skipping invalid date range '%s' in list '%s': %s", raw_range, name, exc)

    return SprintList(
        list_id=str(list_obj.get("id", "")),
        name=name,
        sprint_number=sprint_number,
        start_date=start_date,
        end_date=end_date,
        raw_range=raw_range,
    )


def resolve_date_range(start_raw: str, end_raw: str, target_date: date) -> tuple[date, date]:
    start_parts = parse_date_parts(start_raw)
    end_parts = parse_date_parts(end_raw)

    start_year = normalize_year(start_parts["year"]) if start_parts["year"] else None
    end_year = normalize_year(end_parts["year"]) if end_parts["year"] else None

    if start_year and end_year:
        return (
            date(start_year, start_parts["month"], start_parts["day"]),
            date(end_year, end_parts["month"], end_parts["day"]),
        )

    if start_year and not end_year:
        end_year = start_year + (1 if (end_parts["month"], end_parts["day"]) < (start_parts["month"], start_parts["day"]) else 0)
        return (
            date(start_year, start_parts["month"], start_parts["day"]),
            date(end_year, end_parts["month"], end_parts["day"]),
        )

    if end_year and not start_year:
        start_year = end_year - (1 if (end_parts["month"], end_parts["day"]) < (start_parts["month"], start_parts["day"]) else 0)
        return (
            date(start_year, start_parts["month"], start_parts["day"]),
            date(end_year, end_parts["month"], end_parts["day"]),
        )

    candidates: list[tuple[date, date]] = []
    for base_year in (target_date.year - 1, target_date.year, target_date.year + 1):
        end_year = base_year + (1 if (end_parts["month"], end_parts["day"]) < (start_parts["month"], start_parts["day"]) else 0)
        start = date(base_year, start_parts["month"], start_parts["day"])
        end = date(end_year, end_parts["month"], end_parts["day"])
        candidates.append((start, end))

    for start, end in candidates:
        if start <= target_date <= end:
            return start, end

    return candidates[1]


def parse_date_parts(value: str) -> dict[str, int | None]:
    match = DATE_PARTS_RE.match(value.strip())
    if not match:
        raise ValueError(f"Unsupported date format: {value}")
    month = int(match.group("month"))
    day = int(match.group("day"))
    year = match.group("year")
    return {
        "month": month,
        "day": day,
        "year": int(year) if year else None,
    }


def normalize_year(value: int) -> int:
    if value < 100:
        return 2000 + value
    return value


def select_current_sprint(sprints: list[SprintList], target_date: date) -> SprintList | None:
    matches = [
        sprint for sprint in sprints
        if sprint.start_date and sprint.end_date and sprint.start_date <= target_date <= sprint.end_date
    ]
    if not matches:
        return None
    return max(
        matches,
        key=lambda sprint: (sprint.start_date, sprint.end_date, sprint.sprint_number or 0),
    )


def select_latest_sprint(sprints: list[SprintList]) -> SprintList:
    with_dates = [s for s in sprints if s.start_date and s.end_date]
    if with_dates:
        return max(with_dates, key=lambda sprint: (sprint.end_date, sprint.start_date))
    return max(sprints, key=lambda sprint: sprint.sprint_number or 0)


def build_output(
    matched: SprintList,
    match_type: str | None,
    target_date: date,
    folder_id: str,
    folder_label: str,
    include_candidates: bool,
    candidates: list[SprintList],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target_date": target_date.isoformat(),
        "folder_id": folder_id,
        "folder_label": folder_label,
        "match_type": match_type,
        "list": {
            "id": matched.list_id,
            "name": matched.name,
            "sprint_number": matched.sprint_number,
            "start_date": matched.start_date.isoformat() if matched.start_date else None,
            "end_date": matched.end_date.isoformat() if matched.end_date else None,
            "board_url": BOARD_URL_TEMPLATE.format(list_id=matched.list_id),
        },
        "metadata": {
            "workspace_id": WORKSPACE_ID,
            "space_id": SPACE_ID,
        },
    }

    if include_candidates:
        payload["candidates"] = [
            {
                "id": sprint.list_id,
                "name": sprint.name,
                "sprint_number": sprint.sprint_number,
                "start_date": sprint.start_date.isoformat() if sprint.start_date else None,
                "end_date": sprint.end_date.isoformat() if sprint.end_date else None,
                "raw_range": sprint.raw_range,
            }
            for sprint in candidates
        ]

    return payload


def render_output(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "id":
        print(payload["list"]["id"])
        return
    if output_format == "summary":
        list_info = payload["list"]
        start = list_info["start_date"] or "unknown"
        end = list_info["end_date"] or "unknown"
        print(f"{list_info['name']} ({start} - {end})")
        print(f"List ID: {list_info['id']}")
        print(f"Board: {list_info['board_url']}")
        print(f"Match: {payload['match_type']} (target date {payload['target_date']})")
        return

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    sys.exit(main())
