#!/usr/bin/env python3
"""
Bulk update multiple ClickUp tasks via API.

Execute batch operations that would be slow with individual MCP calls.
Reads task IDs from file, stdin, or command line arguments.

Usage:
    # Close multiple tasks from a file
    python bulk_update_tasks.py close --ids-file tasks_to_close.txt --comment "Closing as stale"

    # Update status on multiple tasks
    python bulk_update_tasks.py update --ids 868abc1 868abc2 868abc3 --status "backlog"

    # Set quarter on tasks from stdin
    echo "868abc1\n868abc2" | python bulk_update_tasks.py update --ids-stdin --quarter Q1

    # Move tasks to a different list (e.g., from backlog to sprint)
    python bulk_update_tasks.py move --ids-file sprint_tasks.txt --list-id 901112637752

    # Dry run to see what would happen
    python bulk_update_tasks.py close --ids 868abc1 --dry-run

Subcommands:
    close   - Close tasks with optional comment
    update  - Update fields (status, priority, quarter, etc.)
    move    - Move tasks to a different list

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset
"""

import argparse
import json
from clickup_auth import resolve_token
import sys
import time
import urllib.request
import urllib.error
from typing import Optional, Any

BASE_URL = "https://api.clickup.com/api/v2"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)

# Common custom field IDs
CUSTOM_FIELDS = {
    "apps": "039b4b60-e29b-4edc-a126-f465908feded",
    "quarter": "c59a97ae-1ecc-44d4-9d7d-ca2009aaaf8b",
    "stage": "9a960487-3a1f-42e3-9578-91d9d66d158f",
    "year": "5482e720-7597-47cd-a56a-bb507afd67cb",
}

# Quarter option IDs
QUARTER_OPTIONS = {
    "Q1": "c5fc228a-ce9f-44cd-b7b3-68e87d1f2857",
    "Q2": "46dfcda3-b13c-4fa7-b2a0-f684921a96e9",
    "Q3": "81e38530-a3e5-4606-8cca-e6137ce4c67d",
    "Q4": "40ff1541-da0b-47f6-ac0f-09767ba6734a",
}

PRIORITY_MAP = {
    "urgent": 1, "high": 2, "normal": 3, "low": 4, "none": None,
}

RATE_LIMIT_DELAY = 0.15  # Seconds between API calls


def api_request(method: str, endpoint: str, token: str, data: Optional[dict] = None) -> dict:
    """Make an API request to ClickUp."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data else None
    request = urllib.request.Request(url, headers=headers, method=method, data=body)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise Exception(f"API Error {e.code}: {error_body}")


def update_task(task_id: str, token: str, updates: dict) -> dict:
    return api_request("PUT", f"/task/{task_id}", token, updates)


def add_comment(task_id: str, token: str, comment_text: str, notify_all: bool = False) -> dict:
    return api_request(
        "POST",
        f"/task/{task_id}/comment",
        token,
        {"comment_text": comment_text, "notify_all": notify_all},
    )


def set_custom_field(task_id: str, field_id: str, value: Any, token: str) -> dict:
    return api_request("POST", f"/task/{task_id}/field/{field_id}", token, {"value": value})


def move_task(task_id: str, list_id: str, token: str) -> dict:
    """Move task to a different list."""
    return api_request("POST", f"/list/{list_id}/task/{task_id}", token)


def get_task_ids(args) -> list[str]:
    """Get task IDs from various sources."""
    task_ids = []

    if args.ids:
        task_ids.extend(args.ids)

    if args.ids_file:
        with open(args.ids_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    task_ids.append(line)

    if args.ids_stdin:
        for line in sys.stdin:
            line = line.strip()
            if line and not line.startswith("#"):
                task_ids.append(line)

    return list(dict.fromkeys(task_ids))  # Dedupe while preserving order


def cmd_close(args, token: str):
    """Close multiple tasks."""
    task_ids = get_task_ids(args)
    if not task_ids:
        print("Error: No task IDs provided", file=sys.stderr)
        return 1

    print(f"Closing {len(task_ids)} tasks...", file=sys.stderr)

    success = 0
    failed = 0

    for i, task_id in enumerate(task_ids, 1):
        try:
            if args.dry_run:
                print(f"  [{i}/{len(task_ids)}] Would close: {task_id}")
            else:
                print(f"  [{i}/{len(task_ids)}] Closing: {task_id}...", file=sys.stderr, end="")

                # Update status to Closed
                update_task(task_id, token, {"status": "Closed"})

                # Add comment if provided
                if args.comment:
                    add_comment(task_id, token, args.comment)

                print(" done", file=sys.stderr)
                success += 1
                time.sleep(RATE_LIMIT_DELAY)

        except Exception as e:
            print(f" FAILED: {e}", file=sys.stderr)
            failed += 1

    print(f"\nResults: {success} closed, {failed} failed", file=sys.stderr)
    return 0 if failed == 0 else 1


def cmd_update(args, token: str):
    """Update multiple tasks."""
    task_ids = get_task_ids(args)
    if not task_ids:
        print("Error: No task IDs provided", file=sys.stderr)
        return 1

    # Build updates
    updates = {}
    custom_field_updates = []

    if args.status:
        updates["status"] = args.status
    if args.priority:
        updates["priority"] = PRIORITY_MAP.get(args.priority)

    if args.quarter:
        quarter_key = args.quarter.upper()
        if quarter_key in QUARTER_OPTIONS:
            custom_field_updates.append((CUSTOM_FIELDS["quarter"], QUARTER_OPTIONS[quarter_key]))
        else:
            print(f"Error: Invalid quarter '{args.quarter}', use Q1-Q4", file=sys.stderr)
            return 1

    if not updates and not custom_field_updates:
        print("Error: No updates specified", file=sys.stderr)
        return 1

    print(f"Updating {len(task_ids)} tasks...", file=sys.stderr)
    if updates:
        print(f"  Task updates: {updates}", file=sys.stderr)
    if custom_field_updates:
        print(f"  Custom field updates: {len(custom_field_updates)}", file=sys.stderr)

    success = 0
    failed = 0

    for i, task_id in enumerate(task_ids, 1):
        try:
            if args.dry_run:
                print(f"  [{i}/{len(task_ids)}] Would update: {task_id}")
            else:
                print(f"  [{i}/{len(task_ids)}] Updating: {task_id}...", file=sys.stderr, end="")

                if updates:
                    update_task(task_id, token, updates)

                for field_id, value in custom_field_updates:
                    set_custom_field(task_id, field_id, value, token)

                print(" done", file=sys.stderr)
                success += 1
                time.sleep(RATE_LIMIT_DELAY)

        except Exception as e:
            print(f" FAILED: {e}", file=sys.stderr)
            failed += 1

    print(f"\nResults: {success} updated, {failed} failed", file=sys.stderr)
    return 0 if failed == 0 else 1


def cmd_move(args, token: str):
    """Move multiple tasks to a different list."""
    task_ids = get_task_ids(args)
    if not task_ids:
        print("Error: No task IDs provided", file=sys.stderr)
        return 1

    if not args.list_id:
        print("Error: --list-id required for move operation", file=sys.stderr)
        return 1

    print(f"Moving {len(task_ids)} tasks to list {args.list_id}...", file=sys.stderr)

    success = 0
    failed = 0

    for i, task_id in enumerate(task_ids, 1):
        try:
            if args.dry_run:
                print(f"  [{i}/{len(task_ids)}] Would move: {task_id}")
            else:
                print(f"  [{i}/{len(task_ids)}] Moving: {task_id}...", file=sys.stderr, end="")
                move_task(task_id, args.list_id, token)
                print(" done", file=sys.stderr)
                success += 1
                time.sleep(RATE_LIMIT_DELAY)

        except Exception as e:
            print(f" FAILED: {e}", file=sys.stderr)
            failed += 1

    print(f"\nResults: {success} moved, {failed} failed", file=sys.stderr)
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bulk update ClickUp tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        suggest_on_error=True,
    )

    # Common arguments
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ids", nargs="+", help="Task IDs as arguments")
    common.add_argument("--ids-file", help="File containing task IDs (one per line)")
    common.add_argument("--ids-stdin", action="store_true", help="Read task IDs from stdin")
    common.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Close command
    close_parser = subparsers.add_parser(
        "close",
        parents=[common],
        help="Close multiple tasks",
        suggest_on_error=True,
    )
    close_parser.add_argument("--comment", "-c", help="Comment to add when closing")

    # Update command
    update_parser = subparsers.add_parser(
        "update",
        parents=[common],
        help="Update task fields",
        suggest_on_error=True,
    )
    update_parser.add_argument("--status", "-s", help="Set status")
    update_parser.add_argument("--priority", "-p", choices=list(PRIORITY_MAP.keys()), help="Set priority")
    update_parser.add_argument("--quarter", "-q", help="Set quarter (Q1, Q2, Q3, Q4)")

    # Move command
    move_parser = subparsers.add_parser(
        "move",
        parents=[common],
        help="Move tasks to different list",
        suggest_on_error=True,
    )
    move_parser.add_argument("--list-id", "-l", required=True, help="Target list ID")

    args = parser.parse_args()

    token = resolve_token()
    if not token:
        print("Error: No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt", file=sys.stderr)
        sys.exit(1)

    if args.command == "close":
        return cmd_close(args, token)
    elif args.command == "update":
        return cmd_update(args, token)
    elif args.command == "move":
        return cmd_move(args, token)


if __name__ == "__main__":
    sys.exit(main())
