#!/usr/bin/env python3
"""Retrieve detailed information about a ClickUp task by ID.

Designed for LLM consumption - outputs structured JSON by default with all
relevant task information including custom fields, assignees, and optionally
comments. By default, includes markdown_description for rich text formatting.

Usage:
    # Get task details as JSON (default, with markdown description)
    python get_task.py 868abc123

    # Get human-readable summary
    python get_task.py 868abc123 --format summary

    # Include comments in output
    python get_task.py 868abc123 --include-comments

    # Disable markdown description (plain text only)
    python get_task.py 868abc123 --no-markdown

    # Quiet mode (JSON only, no stderr messages)
    python get_task.py 868abc123 --quiet

    # Multiple tasks
    python get_task.py 868abc1 868abc2 868abc3

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Output (JSON format):
    {
        "task": {
            "markdown_description": "...",  # Markdown-formatted (default)
            "description": "...",           # Plain text fallback
            ...
        },
        "comments": [ ... ],       # Optional, if --include-comments
        "metadata": {
            "fetched_at": "...",
            "task_id": "..."
        }
    }
"""
from __future__ import annotations

import argparse
import json
import logging
from clickup_auth import resolve_token
import sys
import urllib.error
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


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns exit code."""
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
    """Parse command line arguments."""
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
        help="Task ID(s) to retrieve (e.g., 868abc123)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for info, -vv for debug)",
    )

    # Output options
    output_group = parser.add_argument_group("output options")
    output_group.add_argument(
        "--format", "-f",
        choices=["json", "summary"],
        default="json",
        help="Output format (default: json)",
    )
    output_group.add_argument(
        "--quiet", "-q",
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

    # Content options
    content_group = parser.add_argument_group("content options")
    content_group.add_argument(
        "--include-comments", "-c",
        action="store_true",
        help="Fetch and include task comments",
    )
    content_group.add_argument(
        "--include-subtasks", "-s",
        action="store_true",
        help="Include subtask information (already in task data)",
    )
    content_group.add_argument(
        "--no-markdown",
        action="store_true",
        help="Disable markdown description (returns plain text description)",
    )

    return parser.parse_args(argv)


def configure_logging(verbosity: int, quiet: bool) -> None:
    """Configure logging based on verbosity level."""
    if quiet:
        level = logging.CRITICAL + 1  # Suppress all logging
    else:
        level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(levelname)s: %(message)s",
    )


def run(args: argparse.Namespace) -> int:
    """Execute the task retrieval."""
    token = resolve_token()
    if not token:
        logger.error("No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt")
        return 1

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for task_id in args.task_ids:
        logger.info("Fetching task %s...", task_id)
        try:
            result = fetch_task_data(
                task_id,
                token,
                include_comments=args.include_comments,
                include_markdown=not args.no_markdown,
            )
            results.append(result)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                errors.append(f"Task {task_id} not found")
                logger.warning("Task %s not found", task_id)
            else:
                raise

    if not results:
        logger.error("No tasks found")
        return 1

    # Output
    if args.format == "json":
        output_json(results, args)
    else:
        output_summary(results)

    return 0 if not errors else 1


def fetch_task_data(
    task_id: str,
    token: str,
    *,
    include_comments: bool,
    include_markdown: bool = True,
) -> dict[str, Any]:
    """Fetch task data with optional comments and markdown description."""
    query_params = []
    if include_markdown:
        query_params.append("include_markdown_description=true")
    query_string = f"?{'&'.join(query_params)}" if query_params else ""
    task = api_request("GET", f"/task/{task_id}{query_string}", token)

    result: dict[str, Any] = {
        "task": task,
        "metadata": {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
        },
    }

    if include_comments:
        comments = fetch_comments(task_id, token)
        result["comments"] = comments
        result["metadata"]["comment_count"] = len(comments)

    return result


def api_request(
    method: str,
    endpoint: str,
    token: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make an API request to ClickUp."""
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


def fetch_comments(task_id: str, token: str) -> list[dict[str, Any]]:
    """Fetch comments for a task."""
    try:
        response = api_request("GET", f"/task/{task_id}/comment", token)
        return response.get("comments", [])
    except urllib.error.HTTPError as e:
        logger.warning("Failed to fetch comments for %s: %s", task_id, e)
        return []


def output_json(results: list[dict[str, Any]], args: argparse.Namespace) -> None:
    """Output results as JSON."""
    indent = None if args.compact else 2

    if len(results) == 1:
        # Single task - output directly
        print(json.dumps(results[0], indent=indent))
    else:
        # Multiple tasks - wrap in array
        print(json.dumps({"tasks": results, "count": len(results)}, indent=indent))


def output_summary(results: list[dict[str, Any]]) -> None:
    """Output human-readable summary."""
    for result in results:
        task = result["task"]
        print_task_summary(task, result.get("comments"))
        if len(results) > 1:
            print("-" * 60)


def print_task_summary(task: dict[str, Any], comments: list[dict[str, Any]] | None) -> None:
    """Print a human-readable task summary."""
    task_id = task.get("id", "?")
    name = task.get("name", "Untitled")
    url = task.get("url", f"https://app.clickup.com/t/{task_id}")

    status = task.get("status", {}).get("status", "Unknown")
    priority_data = task.get("priority")
    priority = priority_data.get("priority", "None") if priority_data else "None"

    assignees = [a.get("username", "Unknown") for a in task.get("assignees", [])]
    assignees_str = ", ".join(assignees) if assignees else "Unassigned"

    creator = task.get("creator", {}).get("username", "Unknown")
    date_created = format_timestamp(task.get("date_created"))
    date_updated = format_timestamp(task.get("date_updated"))

    # Custom fields
    custom_fields = extract_custom_fields(task)

    print(f"\n{name}")
    print(f"{'=' * min(len(name), 60)}")
    print(f"ID:        {task_id}")
    print(f"URL:       {url}")
    print(f"Status:    {status}")
    print(f"Priority:  {priority}")
    print(f"Assignees: {assignees_str}")
    print(f"Creator:   {creator}")
    print(f"Created:   {date_created}")
    print(f"Updated:   {date_updated}")

    if custom_fields:
        print("\nCustom Fields:")
        for field_name, field_value in custom_fields.items():
            print(f"  {field_name}: {field_value}")

    # Description (prefer markdown_description if available)
    description = (
        task.get("markdown_description")
        or task.get("text_content")
        or task.get("description")
        or ""
    )
    if description:
        print("\nDescription:")
        # Truncate long descriptions
        if len(description) > 500:
            description = description[:500] + "... [truncated]"
        for line in description.split("\n"):
            print(f"  {line}")

    # Comments
    if comments:
        print(f"\nComments ({len(comments)}):")
        for comment in comments[:5]:
            user = comment.get("user", {}).get("username", "Unknown")
            date = format_timestamp(comment.get("date"))
            text = comment.get("comment_text", "")[:100]
            if len(comment.get("comment_text", "")) > 100:
                text += "..."
            print(f"  [{user} @ {date}]: {text}")
        if len(comments) > 5:
            print(f"  ... and {len(comments) - 5} more comments")

    print()


def extract_custom_fields(task: dict[str, Any]) -> dict[str, str]:
    """Extract custom fields from task data."""
    fields: dict[str, str] = {}

    for cf in task.get("custom_fields", []):
        name = cf.get("name", "").replace("👥 ", "").replace("🛠 ", "")
        value = cf.get("value")

        if value is None:
            continue

        # Handle dropdown/label fields
        type_config = cf.get("type_config", {})
        options = type_config.get("options", [])

        if options:
            # Find matching option
            for opt in options:
                if opt.get("orderindex") == value or str(opt.get("orderindex")) == str(value):
                    fields[name] = opt.get("name", str(value))
                    break
            else:
                fields[name] = str(value)
        else:
            fields[name] = str(value)

    return fields


def format_timestamp(ts: str | None) -> str:
    """Format a timestamp for display."""
    if not ts:
        return "—"
    try:
        dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return "—"


if __name__ == "__main__":
    sys.exit(main())
