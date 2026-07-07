#!/usr/bin/env python3
"""Delete ClickUp task(s) (clickup_delete_task) — DESTRUCTIVE.

Safety model:
    * Dry-run by DEFAULT. Without --yes, nothing is deleted; the script prints the
      task name(s) it WOULD delete and exits.
    * --yes is REQUIRED to actually delete. The script refuses to delete without it.
    * The task name is fetched and printed before each deletion.

Task IDs are accepted with or without the `CU-` display prefix. Deletion is
permanent (DELETE /task/{task_id}).

Usage:
    # Dry run (default) — shows what would be deleted, deletes nothing
    uv run --python 3.14 scripts/delete_task.py 868abc123

    # Actually delete (explicit confirmation required)
    uv run --python 3.14 scripts/delete_task.py 868abc123 --yes

    # Multiple tasks
    uv run --python 3.14 scripts/delete_task.py 868abc123 868def456 --yes

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset
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
        "task_ids",
        nargs="+",
        metavar="TASK_ID",
        help="Task ID(s) to delete (with or without CU- prefix)",
    )
    parser.add_argument("--yes", action="store_true",
                        help="Confirm deletion. REQUIRED to actually delete (default is dry-run).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Explicitly preview only (same as omitting --yes)")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v info, -vv debug)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress stderr messages")
    parser.add_argument("--compact", action="store_true", help="Compact JSON output")

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


def normalize_task_id(raw: str) -> str:
    """Strip a leading CU- display prefix; standard IDs are passed through as-is."""
    cleaned = raw.strip()
    if cleaned[:3].upper() == "CU-":
        return cleaned[3:]
    return cleaned


def run(args: argparse.Namespace) -> int:
    token = resolve_token()
    if not token:
        logger.error("No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt")
        return 1

    # Without --yes (or with explicit --dry-run), refuse to delete.
    execute = args.yes and not args.dry_run

    results: list[dict[str, Any]] = []
    exit_code = 0

    for i, raw_id in enumerate(args.task_ids):
        task_id = normalize_task_id(raw_id)
        name = None
        try:
            task = api_request("GET", f"/task/{task_id}", token)
            name = task.get("name")
        except urllib.error.HTTPError as exc:
            # A missing task returns 404 — or 401/OAUTH_023 in this workspace. Either way,
            # skip this id and keep processing the rest of the batch.
            reason = "not_found" if exc.code == 404 else f"http_{exc.code}"
            logger.warning("Could not fetch task %s (HTTP %d); skipping", task_id, exc.code)
            results.append({"task_id": task_id, "name": None, "deleted": False, "error": reason})
            exit_code = 1
            continue

        if not execute:
            logger.warning("DRY RUN: would DELETE task %s (%r). Re-run with --yes to delete.",
                           task_id, name)
            results.append({"task_id": task_id, "name": name, "deleted": False, "dry_run": True})
            continue

        logger.info("Deleting task %s (%r)...", task_id, name)
        api_request("DELETE", f"/task/{task_id}", token)
        results.append({"task_id": task_id, "name": name, "deleted": True})
        if i < len(args.task_ids) - 1:
            time.sleep(RATE_LIMIT_DELAY)

    payload = {"executed": execute, "results": results, "count": len(results)}
    print(json.dumps(payload, indent=None if args.compact else 2))
    return exit_code


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
