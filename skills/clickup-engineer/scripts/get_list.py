#!/usr/bin/env python3
"""Retrieve ClickUp list details by ID.

Usage:
    # Get list details as JSON (default)
    python get_list.py 90100118193

    # Get human-readable summary
    python get_list.py 90100118193 --format summary

    # Quiet mode (JSON only, no stderr messages)
    python get_list.py 90100118193 --quiet

    # Multiple lists
    python get_list.py 90100118193 900600273627

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Output (JSON format):
    {
        "list": {
            "id": "90100118193",
            "name": "Sprint 78 (12/29 - 1/11)",
            "folder": { "name": "Server Sprints" },
            ...
        },
        "metadata": {
            "fetched_at": "...",
            "list_id": "90100118193"
        }
    }
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from clickup_auth import resolve_token
import sys
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

BASE_URL = "https://api.clickup.com/api/v2"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose, args.quiet)

    try:
        return run(args)
    except KeyboardInterrupt:
        return 130
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8")
        logger.error("API error %d: %s", exc.code, error_body)
        return 1
    except urllib.error.URLError as exc:
        logger.error("Network error: %s", exc.reason)
        return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        suggest_on_error=True,
    )
    parser.add_argument(
        "list_ids",
        nargs="+",
        metavar="LIST_ID",
        help="List ID(s) to retrieve (e.g., 90100118193)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for info, -vv for debug)",
    )

    output_group = parser.add_argument_group("output options")
    output_group.add_argument(
        "--format",
        "-f",
        choices=["json", "summary"],
        default="json",
        help="Output format (default: json)",
    )
    output_group.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress stderr messages (only output result)",
    )
    output_group.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: True)",
    )
    output_group.add_argument(
        "--compact",
        action="store_true",
        help="Compact JSON output (no indentation)",
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


def run(args: argparse.Namespace) -> int:
    token = resolve_token()
    if not token:
        logger.error("No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt")
        return 1

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for list_id in args.list_ids:
        logger.info("Fetching list %s...", list_id)
        try:
            list_data = fetch_list_data(list_id, token)
            results.append(
                {
                    "list": list_data,
                    "metadata": {
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "list_id": list_id,
                    },
                }
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                errors.append(f"List {list_id} not found")
                logger.warning("List %s not found", list_id)
            else:
                raise

    if not results:
        logger.error("No lists found")
        return 1

    if args.format == "json":
        output_json(results, args)
    else:
        output_summary(results)

    return 0 if not errors else 1


def fetch_list_data(list_id: str, token: str) -> dict[str, Any]:
    return api_request("GET", f"/list/{list_id}", token)


def api_request(
    method: str,
    endpoint: str,
    token: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{BASE_URL}{endpoint}"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode("utf-8") if data else None
    request = urllib.request.Request(url, headers=headers, method=method, data=body)

    logger.debug("API %s %s", method, endpoint)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def output_json(results: list[dict[str, Any]], args: argparse.Namespace) -> None:
    indent = None if args.compact else 2

    if len(results) == 1:
        print(json.dumps(results[0], indent=indent))
    else:
        print(json.dumps({"lists": results, "count": len(results)}, indent=indent))


def output_summary(results: list[dict[str, Any]]) -> None:
    for result in results:
        list_data = result.get("list", {})
        list_id = list_data.get("id", "?")
        name = list_data.get("name", "Untitled")
        space = list_data.get("space", {}).get("name", "Unknown")
        folder = list_data.get("folder", {}).get("name", "Unknown")
        status = list_data.get("status", {}).get("status", "Unknown")
        archived = list_data.get("archived", False)

        print(f"\n{name}")
        print(f"{'=' * min(len(name), 60)}")
        print(f"ID:       {list_id}")
        print(f"Space:    {space}")
        print(f"Folder:   {folder}")
        print(f"Status:   {status}")
        print(f"Archived: {archived}")


if __name__ == "__main__":
    sys.exit(main())
