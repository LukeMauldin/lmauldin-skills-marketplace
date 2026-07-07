#!/usr/bin/env python3
"""List the custom fields accessible from a ClickUp list (clickup_get_custom_fields).

GET /list/{list_id}/field returns the field definitions, including each field's
`id`, `name`, `type`, and `type_config.options[]` (option UUIDs). Those option
UUIDs are exactly what create_task.py / update_task.py / bulk_update_tasks.py need
when WRITING dropdown custom fields (reads return orderindex; writes need UUIDs).

Usage:
    # Custom fields for a list as JSON (default)
    uv run --python 3.14 scripts/get_custom_fields.py 900600273627

    # Human-readable summary (field -> options with UUIDs)
    uv run --python 3.14 scripts/get_custom_fields.py 900600273627 --format summary

    # Multiple lists
    uv run --python 3.14 scripts/get_custom_fields.py 900600273627 90100118193

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Output (JSON format):
    {
        "list_id": "900600273627",
        "fields": [
            { "id": "...", "name": "Apps", "type": "drop_down",
              "type_config": { "options": [ { "id": "...", "name"/"label": "Server" } ] } }
        ],
        "count": N
    }
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
        "list_ids",
        nargs="+",
        metavar="LIST_ID",
        help="List ID(s) whose custom fields to retrieve",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v info, -vv debug)")

    output_group = parser.add_argument_group("output options")
    output_group.add_argument("--format", "-f", choices=["json", "summary"], default="json",
                              help="Output format (default: json)")
    output_group.add_argument("--quiet", "-q", action="store_true",
                              help="Suppress stderr messages (only output result)")
    output_group.add_argument("--compact", action="store_true", help="Compact JSON output")

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
        logger.info("Fetching custom fields for list %s...", list_id)
        try:
            fields = get_custom_fields(list_id, token)
            results.append({"list_id": list_id, "fields": fields, "count": len(fields)})
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                errors.append(f"List {list_id} not found")
                logger.warning("List %s not found", list_id)
            else:
                raise

    if not results:
        logger.error("No custom fields found")
        return 1

    indent = None if args.compact else 2
    if args.format == "summary":
        output_summary(results)
    elif len(results) == 1:
        print(json.dumps(results[0], indent=indent))
    else:
        print(json.dumps({"results": results, "count": len(results)}, indent=indent))

    return 0 if not errors else 1


def get_custom_fields(list_id: str, token: str) -> list[dict[str, Any]]:
    """Fetch a list's accessible custom fields (GET /list/{list_id}/field)."""
    response = api_request("GET", f"/list/{list_id}/field", token)
    return response.get("fields", [])


def output_summary(results: list[dict[str, Any]]) -> None:
    for result in results:
        print(f"\nList {result['list_id']} — {result['count']} field(s)")
        for field in result["fields"]:
            print(f"  [{field.get('id')}] {field.get('name')} ({field.get('type')})")
            options = field.get("type_config", {}).get("options", [])
            for opt in options:
                label = opt.get("name") or opt.get("label")
                print(f"      - {label}: {opt.get('id')}")


def api_request(
    method: str,
    endpoint: str,
    token: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """Make an API request to ClickUp (empty-body safe, 429 backoff)."""
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
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after and retry_after.strip().isdigit():
        return float(retry_after.strip())
    return (attempt + 1) * 2.0


if __name__ == "__main__":
    sys.exit(main())
