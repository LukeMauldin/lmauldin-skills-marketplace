#!/usr/bin/env python3
"""Retrieve ClickUp folder details by ID (MCP clickup_get_folder equivalent).

Returns the raw folder object from GET /folder/{folder_id}, which includes the
folder's name, space, task_count, and its `lists` array. Also exposes a reusable
`get_folder_lists()` helper (GET /folder/{folder_id}/list) shared with
get_current_sprint.py.

Usage:
    # Get folder details as JSON (default)
    uv run --python 3.14 scripts/get_folder.py 90100118193

    # Human-readable summary
    uv run --python 3.14 scripts/get_folder.py 90100118193 --format summary

    # Multiple folders, compact JSON, no stderr noise
    uv run --python 3.14 scripts/get_folder.py 90100118193 90100118119 --compact --quiet

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Output (JSON format):
    {
        "folder": {
            "id": "90100118193",
            "name": "Server Sprints",
            "space": { "id": "16581563", "name": "Tech" },
            "task_count": "...",
            "lists": [ { "id": "...", "name": "..." } ]
        },
        "metadata": { "fetched_at": "...", "folder_id": "90100118193" }
    }

Parity note: the MCP envelope for clickup_get_folder is not observable, so this
returns the raw API JSON under a thin `folder`/`metadata` wrapper.
"""
from __future__ import annotations

import argparse
import json
import logging
from clickup_auth import resolve_token
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
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

RATE_LIMIT_DELAY = 0.15  # Seconds between API calls
MAX_RETRIES = 3


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
        "folder_ids",
        nargs="+",
        metavar="FOLDER_ID",
        help="Folder ID(s) to retrieve (e.g., 90100118193)",
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

    for folder_id in args.folder_ids:
        logger.info("Fetching folder %s...", folder_id)
        try:
            folder = get_folder(folder_id, token)
            results.append(
                {
                    "folder": folder,
                    "metadata": {
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "folder_id": folder_id,
                    },
                }
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                errors.append(f"Folder {folder_id} not found")
                logger.warning("Folder %s not found", folder_id)
            else:
                raise

    if not results:
        logger.error("No folders found")
        return 1

    if args.format == "json":
        output_json(results, args)
    else:
        output_summary(results)

    return 0 if not errors else 1


def get_folder(folder_id: str, token: str) -> dict[str, Any]:
    """Fetch a folder's details (GET /folder/{folder_id})."""
    return api_request("GET", f"/folder/{folder_id}", token)


def get_folder_lists(
    folder_id: str,
    token: str,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Fetch the lists inside a folder (GET /folder/{folder_id}/list).

    Shared with get_current_sprint.py. Preserves the original archived semantics:
    archived=true when include_archived is truthy, archived=false otherwise.
    """
    params = {"archived": "true" if include_archived else "false"}
    response = api_request("GET", f"/folder/{folder_id}/list", token, params=params)
    return response.get("lists", [])


def api_request(
    method: str,
    endpoint: str,
    token: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """Make an API request to ClickUp.

    Handles empty/204 response bodies (returns {}) and retries on HTTP 429 with
    Retry-After-aware backoff.
    """
    url = f"{BASE_URL}{endpoint}"
    if params:
        url = f"{url}?{build_query(params)}"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(url, headers=headers, method=method, data=body)

    logger.debug("API %s %s", method, endpoint)
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < MAX_RETRIES:
                delay = retry_delay(exc, attempt)
                logger.warning("Rate limited (429); retrying in %.1fs", delay)
                time.sleep(delay)
                attempt += 1
                continue
            raise


def build_query(params: dict[str, Any]) -> str:
    """Build a query string; list values become repeated key=value pairs.

    Brackets in keys (e.g. 'list_ids[]') are left unencoded.
    """
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                pairs.append((key, str(item)))
        elif isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
        else:
            pairs.append((key, str(value)))
    return urllib.parse.urlencode(pairs, safe="[]")


def retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
    """Compute backoff delay for a 429, honoring Retry-After when present."""
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after and retry_after.strip().isdigit():
        return float(retry_after.strip())
    return (attempt + 1) * 2.0


def output_json(results: list[dict[str, Any]], args: argparse.Namespace) -> None:
    indent = None if args.compact else 2
    if len(results) == 1:
        print(json.dumps(results[0], indent=indent))
    else:
        print(json.dumps({"folders": results, "count": len(results)}, indent=indent))


def output_summary(results: list[dict[str, Any]]) -> None:
    for result in results:
        folder = result.get("folder", {})
        folder_id = folder.get("id", "?")
        name = folder.get("name", "Untitled")
        space = folder.get("space", {}).get("name", "Unknown")
        task_count = folder.get("task_count", "?")
        lists = folder.get("lists", [])

        print(f"\n{name}")
        print(f"{'=' * min(len(name), 60)}")
        print(f"ID:         {folder_id}")
        print(f"Space:      {space}")
        print(f"Task count: {task_count}")
        print(f"Lists:      {len(lists)}")
        for lst in lists:
            print(f"  - [{lst.get('id')}] {lst.get('name')}")


if __name__ == "__main__":
    sys.exit(main())
