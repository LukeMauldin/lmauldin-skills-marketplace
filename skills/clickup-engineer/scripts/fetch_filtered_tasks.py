#!/usr/bin/env python3
"""
Fetch ClickUp tasks with custom field filtering.

Works around MCP tool limitations by using the ClickUp API directly.
Supports filtering by custom fields, pagination, and various output formats.

Usage:
    # Fetch Server Backlog tasks
    python fetch_filtered_tasks.py --list-id 900600273627 \
        --custom-field "039b4b60-e29b-4edc-a126-f465908feded=90ca02d6-0a54-4e1b-92ff-5463c56ba501" \
        --output server_backlog.json

    # Fetch Q1 tasks
    python fetch_filtered_tasks.py --list-id 900600273627 \
        --custom-field "c59a97ae-1ecc-44d4-9d7d-ca2009aaaf8b=c5fc228a-ce9f-44cd-b7b3-68e87d1f2857"

    # Multiple filters
    python fetch_filtered_tasks.py --list-id 900600273627 \
        --custom-field "FIELD_ID=OPTION_ID" \
        --custom-field "FIELD_ID2=OPTION_ID2"

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Common Filter Presets:
    Server Backlog: --preset server
    KS Coach:       --preset coach
    KSTV:           --preset kstv
"""

import argparse
import json
from clickup_auth import resolve_token
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Any

# Configuration
BASE_URL = "https://api.clickup.com/api/v2"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)
TEAM_ID = "12606327"
DEFAULT_LIST_ID = "900600273627"  # Product Roadmap

# Preset filters for common queries
PRESETS = {
    "server": {
        "list_id": "900600273627",
        "custom_fields": [
            {"field_id": "039b4b60-e29b-4edc-a126-f465908feded", "operator": "=", "value": "90ca02d6-0a54-4e1b-92ff-5463c56ba501"}
        ],
        "description": "Server Backlog (Apps = Server)"
    },
    "coach": {
        "list_id": "900600273627",
        "custom_fields": [
            {"field_id": "039b4b60-e29b-4edc-a126-f465908feded", "operator": "=", "value": "fa89f94a-c15d-424c-a22c-1fd4280ee13a"}
        ],
        "description": "KS Coach Backlog (Apps = KS Coach)"
    },
    "kstv": {
        "list_id": "900600273627",
        "custom_fields": [
            {"field_id": "039b4b60-e29b-4edc-a126-f465908feded", "operator": "=", "value": "8d274314-9b65-4503-a60a-f692fe0c36b4"}
        ],
        "description": "KSTV Backlog (Apps = KSTV)"
    },
    "lighthouse": {
        "list_id": "900600273627",
        "custom_fields": [
            {"field_id": "039b4b60-e29b-4edc-a126-f465908feded", "operator": "=", "value": "e9774825-fad0-474d-81b4-3d6c9326d045"}
        ],
        "description": "Lighthouse Backlog (Apps = Lighthouse)"
    },
}


def fetch_tasks_page(
    token: str,
    list_id: str,
    custom_fields: list[dict[str, str]],
    page: int = 0,
    include_closed: bool = True,
) -> dict[str, Any]:
    """Fetch a single page of tasks from ClickUp API."""
    params = {
        "page": str(page),
        "list_ids[]": list_id,
        "include_closed": str(include_closed).lower(),
        "subtasks": "true",
    }

    if custom_fields:
        params["custom_fields"] = json.dumps(custom_fields)

    query_string = urllib.parse.urlencode(params, safe="[]")
    url = f"{BASE_URL}/team/{TEAM_ID}/task?{query_string}"

    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    request = urllib.request.Request(url, headers=headers, method="GET")

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all_tasks(
    token: str,
    list_id: str,
    custom_fields: list[dict[str, str]],
    include_closed: bool = True,
) -> list[dict[str, Any]]:
    """Fetch all tasks, handling pagination."""
    all_tasks = []
    page = 0

    while True:
        print(f"Fetching page {page}...", file=sys.stderr)
        response = fetch_tasks_page(token, list_id, custom_fields, page, include_closed)
        tasks = response.get("tasks", [])

        if not tasks:
            break

        all_tasks.extend(tasks)
        print(f"  Got {len(tasks)} tasks (total: {len(all_tasks)})", file=sys.stderr)

        if len(tasks) < 100:
            break

        page += 1

    return all_tasks


def parse_custom_field_arg(arg: str) -> dict[str, str]:
    """Parse a custom field argument in format 'field_id=value'."""
    if "=" not in arg:
        raise ValueError(f"Invalid custom field format: {arg}. Expected 'field_id=value'")

    field_id, value = arg.split("=", 1)
    return {
        "field_id": field_id.strip(),
        "operator": "=",
        "value": value.strip()
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch ClickUp tasks with custom field filtering",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        suggest_on_error=True,
    )

    parser.add_argument(
        "--list-id",
        default=DEFAULT_LIST_ID,
        help=f"ClickUp list ID (default: {DEFAULT_LIST_ID} - Product Roadmap)"
    )
    parser.add_argument(
        "--custom-field",
        action="append",
        dest="custom_fields",
        metavar="FIELD_ID=VALUE",
        help="Custom field filter in format 'field_id=option_id'. Can be repeated."
    )
    parser.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        help="Use a preset filter configuration"
    )
    parser.add_argument(
        "--include-closed",
        action="store_true",
        default=True,
        help="Include closed tasks (default: True)"
    )
    parser.add_argument(
        "--exclude-closed",
        action="store_true",
        help="Exclude closed tasks"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "summary"],
        default="json",
        help="Output format (default: json)"
    )

    args = parser.parse_args()

    # Get token
    token = resolve_token()
    if not token:
        print("Error: No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt", file=sys.stderr)
        print("Get your token from: ClickUp Settings > Apps > API Token", file=sys.stderr)
        sys.exit(1)

    # Determine list ID and custom fields
    list_id = args.list_id
    custom_fields = []

    if args.preset:
        preset = PRESETS[args.preset]
        list_id = preset["list_id"]
        custom_fields = preset["custom_fields"]
        print(f"Using preset: {args.preset} - {preset['description']}", file=sys.stderr)

    if args.custom_fields:
        for cf_arg in args.custom_fields:
            custom_fields.append(parse_custom_field_arg(cf_arg))

    include_closed = not args.exclude_closed

    # Fetch tasks
    print(f"Fetching tasks from list {list_id}...", file=sys.stderr)
    if custom_fields:
        print(f"Custom field filters: {len(custom_fields)}", file=sys.stderr)

    tasks = fetch_all_tasks(token, list_id, custom_fields, include_closed)

    print(f"\nFetched {len(tasks)} tasks", file=sys.stderr)

    # Build output
    if args.format == "json":
        output = {
            "metadata": {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "team_id": TEAM_ID,
                "list_id": list_id,
                "custom_field_filters": custom_fields,
                "include_closed": include_closed,
                "total_tasks": len(tasks)
            },
            "tasks": tasks
        }
        output_str = json.dumps(output, indent=2)
    else:
        # Summary format
        lines = [f"Total tasks: {len(tasks)}", ""]
        for task in tasks:
            task_id = task.get("id", "?")
            name = task.get("name", "Untitled")[:60]
            status = task.get("status", {}).get("status", "?")
            lines.append(f"[{task_id}] {name} ({status})")
        output_str = "\n".join(lines)

    # Write output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"Written to: {args.output}", file=sys.stderr)
    else:
        print(output_str)

    return 0


if __name__ == "__main__":
    sys.exit(main())
