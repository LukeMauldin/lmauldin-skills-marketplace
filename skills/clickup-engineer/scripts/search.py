#!/usr/bin/env python3
"""Keyword search across ClickUp tasks and doc titles (clickup_search equivalent).

LIMITATION (read this): ClickUp's public API has NO free-text search endpoint.
MCP's clickup_search wraps an internal, ranked, cross-entity index (~20 hits).
This script approximates it with a CLIENT-SIDE substring scan:
    * Tasks  - paginated GET /team/{team_id}/task, matched on task name
               (and description with --include-description).
    * Docs   - paginated v3 GET /workspaces/{ws}/docs, matched on doc TITLE only.
It does NOT do server-side relevance ranking, does NOT search comments, and does
NOT read doc bodies. For exhaustive custom-field filtering use fetch_filtered_tasks.py.

Because an unscoped scan walks the whole workspace, results are bounded by --limit
and --max-pages, with a 0.15s delay between pages and 429 backoff. Scope the search
with --list/--space/--folder to make it fast and cheap.

Usage:
    # Search the whole workspace (bounded)
    uv run --python 3.14 scripts/search.py "rate limiting"

    # Scope to a list (fast)
    uv run --python 3.14 scripts/search.py "auth" --list 900600273627

    # Also match task descriptions, include closed tasks, skip docs
    uv run --python 3.14 scripts/search.py "redis" --include-description --include-closed --no-docs

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Output (JSON):
    { "query": "...", "tasks": [...], "docs": [...],
      "counts": {"tasks": N, "docs": M},
      "truncated": {"tasks": bool, "docs": bool}, "limitation": "..." }
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

BASE_URL_V2 = "https://api.clickup.com/api/v2"
BASE_URL_V3 = "https://api.clickup.com/api/v3"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)

TEAM_ID = "12606327"
WORKSPACE_ID = "12606327"
RATE_LIMIT_DELAY = 0.15  # Seconds between API calls
MAX_RETRIES = 3

LIMITATION = (
    "client-side substring scan (task names + doc titles); "
    "no server-side relevance ranking, no comment search, doc bodies not searched"
)


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
    parser.add_argument("query", help="Keyword/substring to search for (case-insensitive)")
    parser.add_argument("--team-id", default=TEAM_ID, help=f"Workspace/team ID (default: {TEAM_ID})")

    scope = parser.add_argument_group("scope (default: whole workspace)")
    scope.add_argument("--list", action="append", dest="list_ids", help="Limit to list ID(s). Repeatable.")
    scope.add_argument("--space", action="append", dest="space_ids", help="Limit to space ID(s). Repeatable.")
    scope.add_argument("--folder", action="append", dest="folder_ids", help="Limit to folder ID(s). Repeatable.")

    parser.add_argument("--include-closed", action="store_true", help="Include closed tasks")
    parser.add_argument("--include-description", action="store_true",
                        help="Also match against task descriptions (heavier)")
    parser.add_argument("--no-docs", action="store_true", help="Skip the doc-title search")
    parser.add_argument("--limit", type=int, default=50, help="Max results per type (default: 50)")
    parser.add_argument("--max-pages", type=int, default=20,
                        help="Safety cap on pages scanned per type (default: 20; 100 tasks/page)")
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

    if not (args.list_ids or args.space_ids or args.folder_ids):
        logger.warning("No scope given; scanning the whole workspace (bounded by --max-pages=%d)",
                       args.max_pages)

    tasks, tasks_truncated = search_tasks(args, token)
    logger.info("Matched %d task(s)%s", len(tasks), " (truncated)" if tasks_truncated else "")

    docs: list[dict[str, Any]] = []
    docs_truncated = False
    if not args.no_docs:
        docs, docs_truncated = search_docs(args, token)
        logger.info("Matched %d doc(s)%s", len(docs), " (truncated)" if docs_truncated else "")

    output = {
        "query": args.query,
        "tasks": tasks,
        "docs": docs,
        "counts": {"tasks": len(tasks), "docs": len(docs)},
        "truncated": {"tasks": tasks_truncated, "docs": docs_truncated},
        "limitation": LIMITATION,
    }

    if args.format == "summary":
        render_summary(output)
    else:
        print(json.dumps(output, indent=None if args.compact else 2))

    return 0


def search_tasks(args: argparse.Namespace, token: str) -> tuple[list[dict[str, Any]], bool]:
    q = args.query.lower()
    matches: list[dict[str, Any]] = []
    scope: dict[str, Any] = {}
    if args.list_ids:
        scope["list_ids[]"] = args.list_ids
    if args.space_ids:
        scope["space_ids[]"] = args.space_ids
    if args.folder_ids:
        scope["project_ids[]"] = args.folder_ids  # ClickUp calls folders "projects"

    for page in range(args.max_pages):
        params: dict[str, Any] = {
            "page": page,
            "include_closed": args.include_closed,
        }
        if args.include_description:
            params["include_markdown_description"] = True
        params.update(scope)

        resp = api_request("GET", f"/team/{args.team_id}/task", token,
                           params=params, base_url=BASE_URL_V2)
        tasks = resp.get("tasks", [])
        for t in tasks:
            haystack = (t.get("name") or "").lower()
            if args.include_description:
                haystack += " " + (t.get("markdown_description") or t.get("description") or "").lower()
            if q in haystack:
                matches.append(trim_task(t))
                if len(matches) >= args.limit:
                    return matches, True

        if resp.get("last_page") or not tasks:
            return matches, False
        time.sleep(RATE_LIMIT_DELAY)

    return matches, True  # hit max_pages without exhausting


def search_docs(args: argparse.Namespace, token: str) -> tuple[list[dict[str, Any]], bool]:
    q = args.query.lower()
    matches: list[dict[str, Any]] = []
    cursor: str | None = None

    for _ in range(args.max_pages):
        params: dict[str, Any] = {"limit": 50}
        if cursor:
            params["next_cursor"] = cursor
        resp = api_request("GET", f"/workspaces/{WORKSPACE_ID}/docs", token,
                           params=params, base_url=BASE_URL_V3)
        docs = resp.get("docs", []) if isinstance(resp, dict) else []
        for d in docs:
            if q in (d.get("name") or "").lower():
                doc_id = d.get("id")
                matches.append({
                    "id": doc_id,
                    "name": d.get("name"),
                    "url": f"https://app.clickup.com/{WORKSPACE_ID}/v/dc/{doc_id}",
                })
                if len(matches) >= args.limit:
                    return matches, True

        cursor = resp.get("next_cursor") if isinstance(resp, dict) else None
        if not cursor or not docs:
            return matches, False
        time.sleep(RATE_LIMIT_DELAY)

    return matches, True


def trim_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "name": task.get("name"),
        "status": task.get("status", {}).get("status") if task.get("status") else None,
        "url": task.get("url"),
        "list": task.get("list", {}).get("name") if task.get("list") else None,
        "space": task.get("space", {}).get("id") if task.get("space") else None,
        "folder": task.get("folder", {}).get("name") if task.get("folder") else None,
    }


def render_summary(output: dict[str, Any]) -> None:
    print(f"Query: {output['query']}")
    print(f"\nTasks ({output['counts']['tasks']}{' truncated' if output['truncated']['tasks'] else ''}):")
    for t in output["tasks"]:
        print(f"  [{t['id']}] {t['name']} ({t['status']}) — {t['list']}")
    print(f"\nDocs ({output['counts']['docs']}{' truncated' if output['truncated']['docs'] else ''}):")
    for d in output["docs"]:
        print(f"  [{d['id']}] {d['name']}")
    print(f"\nNote: {output['limitation']}")


def api_request(
    method: str,
    endpoint: str,
    token: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    base_url: str = BASE_URL_V2,
) -> Any:
    """Make an API request to ClickUp (empty-body safe, 429 backoff). base_url selects v2/v3."""
    url = f"{base_url}{endpoint}"
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
