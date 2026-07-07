#!/usr/bin/env python3
"""Fetch comments for a ClickUp task.

Lightweight script for fetching just comments without full task data.
Useful when you already have task information and only need comments.

Usage:
    # Get comments as JSON
    python fetch_comments.py 868abc123

    # Multiple tasks
    python fetch_comments.py 868abc1 868abc2

    # Fetch multiple comment pages
    python fetch_comments.py 868abc123 --pages 3

    # Quiet mode (JSON only)
    python fetch_comments.py 868abc123 --quiet

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Output (JSON format):
    {
        "task_id": "868abc123",
        "comments": [...],
        "count": 5
    }
"""
from __future__ import annotations

import argparse
import json
from clickup_auth import resolve_token
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

BASE_URL = "https://api.clickup.com/api/v2"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch comments for ClickUp task(s)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "task_ids",
        nargs="+",
        metavar="TASK_ID",
        help="Task ID(s) to fetch comments for",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress stderr messages",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Compact JSON output",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of comment pages to fetch (default: 1)",
    )

    args = parser.parse_args(argv)

    token = resolve_token()
    if not token:
        if not args.quiet:
            print("Error: No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt", file=sys.stderr)
        return 1

    results = []
    for task_id in args.task_ids:
        if not args.quiet:
            print(f"Fetching comments for {task_id}...", file=sys.stderr)

        comments = fetch_comments(task_id, token, max_pages=args.pages)
        results.append({
            "task_id": task_id,
            "comments": comments,
            "count": len(comments),
        })

    # Output
    indent = None if args.compact else 2
    if len(results) == 1:
        print(json.dumps(results[0], indent=indent))
    else:
        print(json.dumps({"results": results}, indent=indent))

    return 0


def fetch_comments(task_id: str, token: str, max_pages: int = 1) -> list[dict[str, Any]]:
    """Fetch comments for a task with pagination."""
    if max_pages <= 0:
        return []

    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }

    comments: list[dict[str, Any]] = []
    start: str | None = None
    start_id: str | None = None

    for _ in range(max_pages):
        params: dict[str, str] = {}
        if start and start_id:
            params["start"] = start
            params["start_id"] = start_id

        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{BASE_URL}/task/{task_id}/comment{query}"

        try:
            request = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            break

        page_comments = data.get("comments", [])
        if not page_comments:
            break

        comments.extend(page_comments)
        last = page_comments[-1]
        start = str(last.get("date", ""))
        start_id = str(last.get("id", ""))

        if not start or not start_id:
            break

    return comments


if __name__ == "__main__":
    sys.exit(main())
