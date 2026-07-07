#!/usr/bin/env python3
"""Create a new ClickUp task with server team defaults.

Defaults (unless overridden):
    - List: Current server team sprint
    - Status: Open
    - Assignee: Current user (from API token)
    - Description format: Objective / Business Justification / Technical Details

Usage:
    # Basic creation with name only (uses all defaults)
    python create_task.py "Implement user auth caching"

    # With description sections
    python create_task.py "Implement user auth caching" \
        --objective "Add Redis caching for user authentication tokens" \
        --justification "Reduce database load and improve response times" \
        --details "Use Redis with 15-minute TTL. Update auth middleware."

    # Override defaults
    python create_task.py "Fix login bug" --status "in progress" --assignee bob

    # Add to Product Roadmap instead of sprint
    python create_task.py "New feature idea" --list roadmap

    # Set custom fields
    python create_task.py "Server enhancement" --apps Server --quarter Q1

    # Dry run (show what would be created)
    python create_task.py "Test task" --dry-run

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Available Statuses (Server Sprint):
    Open, in progress, in review, testing, blocked, pending live, completed, Closed
"""
from __future__ import annotations

import argparse
import json
import logging
from clickup_auth import resolve_token
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import TYPE_CHECKING, Any

from get_current_sprint import resolve_current_sprint_list_id

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

BASE_URL = "https://api.clickup.com/api/v2"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)

# Default values
DEFAULT_STATUS = "Open"
SERVER_SPRINT_FOLDER_ID = "90100118193"

# List presets
LIST_PRESETS: dict[str, str] = {
    "roadmap": "900600273627",  # Product Roadmap
}

# Team member ClickUp user IDs (from: GET /team/{team_id}/member)
# These IDs are stable and don't change when display names change.
TEAM_MEMBERS: dict[str, int] = {
    "luke": 75349906,      # Luke Mauldin
    "bob": 57214468,       # Bob D'Ercole
    "joshua": 38252373,    # Joshua Gasaway
    "josh": 38252373,      # Joshua Gasaway (alias)
    "rachel": 38527352,    # Rachel Vale
}

# Cached current user (populated on first call to get_current_user)
_current_user: dict[str, Any] | None = None

# Custom field IDs
CUSTOM_FIELD_IDS: dict[str, str] = {
    "apps": "039b4b60-e29b-4edc-a126-f465908feded",
    "quarter": "c59a97ae-1ecc-44d4-9d7d-ca2009aaaf8b",
    "stage": "9a960487-3a1f-42e3-9578-91d9d66d158f",
    "year": "5482e720-7597-47cd-a56a-bb507afd67cb",
}

# Custom field option mappings
APPS_OPTIONS: dict[str, str] = {
    "server": "90ca02d6-0a54-4e1b-92ff-5463c56ba501",
    "coach": "fa89f94a-c15d-424c-a22c-1fd4280ee13a",
    "ks coach": "fa89f94a-c15d-424c-a22c-1fd4280ee13a",
    "kstv": "8d274314-9b65-4503-a60a-f692fe0c36b4",
    "tv": "8d274314-9b65-4503-a60a-f692fe0c36b4",
    "lighthouse": "e9774825-fad0-474d-81b4-3d6c9326d045",
    "parent": "a5c027e8-17dd-46ef-8599-6aa8d4db2f61",
    "ks parent": "a5c027e8-17dd-46ef-8599-6aa8d4db2f61",
}

QUARTER_OPTIONS: dict[str, str] = {
    "q1": "c5fc228a-ce9f-44cd-b7b3-68e87d1f2857",
    "q2": "46dfcda3-b13c-4fa7-b2a0-f684921a96e9",
    "q3": "81e38530-a3e5-4606-8cca-e6137ce4c67d",
    "q4": "40ff1541-da0b-47f6-ac0f-09767ba6734a",
    "quarter 1": "c5fc228a-ce9f-44cd-b7b3-68e87d1f2857",
    "quarter 2": "46dfcda3-b13c-4fa7-b2a0-f684921a96e9",
    "quarter 3": "81e38530-a3e5-4606-8cca-e6137ce4c67d",
    "quarter 4": "40ff1541-da0b-47f6-ac0f-09767ba6734a",
}

STAGE_OPTIONS: dict[str, str] = {
    "planning": "473b00a4-3f02-490c-9ea9-c44f117c620c",
    "design": "02f67bf1-e65a-4736-85ff-1c0871da17fe",
    "picked up": "f1fb1f59-42e8-4db2-90ae-4cf2bf4fdd0c",
    "engineering": "3533e01a-ad8b-4d48-9a4e-3c54fe492b7e",
    "qa": "b201b0ae-f562-4d67-9dc5-8743b8247147",
    "pending release": "4091209a-30d1-4c8e-9392-4e01473f329e",
    "released": "fe2a1cdf-c4ef-4bba-acd1-19781a196a24",
}

YEAR_OPTIONS: dict[str, str] = {
    "2024": "4fdee6d1-5a0f-4181-af42-9d04a0379c0f",
    "2025": "afab50aa-f9e7-41d8-9a7a-42b5a8443ba5",
    "2026": "97eb520a-5719-4cfe-94e2-fff059b30a4e",
}

PRIORITY_MAP: dict[str, int] = {
    "urgent": 1,
    "high": 2,
    "normal": 3,
    "low": 4,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    args = parse_args(argv)
    configure_logging(args.verbose)

    try:
        return run(args)
    except KeyboardInterrupt:
        return 130
    except ValueError as e:
        logger.error("%s", e)
        return 1
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
    parser.add_argument("name", help="Task name/title")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v for info, -vv for debug)")

    # Description sections
    desc_group = parser.add_argument_group("description sections")
    desc_group.add_argument("--objective", "-o",
                            help="Objective section (2-5 sentences)")
    desc_group.add_argument("--justification", "-j",
                            help="Business justification (2-3 sentences)")
    desc_group.add_argument("--details", "-d",
                            help="Technical details (as long as needed)")
    desc_group.add_argument("--description",
                            help="Raw markdown description (overrides sections)")

    # Task properties
    props_group = parser.add_argument_group("task properties")
    props_group.add_argument("--status", "-s", default=DEFAULT_STATUS,
                             help=f"Status (default: {DEFAULT_STATUS})")
    props_group.add_argument("--assignee", "-a", default="me",
                             help="Assignee: 'me' (current user), team name, or ID (default: me)")
    props_group.add_argument("--list", "-l", dest="list_id", default="sprint",
                             help="List: 'sprint', 'roadmap', or list ID (default: sprint)")
    props_group.add_argument("--priority", "-p", choices=list(PRIORITY_MAP.keys()),
                             help="Task priority")
    props_group.add_argument("--due-date", help="Due date (YYYY-MM-DD)")
    props_group.add_argument("--no-assignee", action="store_true",
                             help="Create without assignee")

    # Custom fields
    cf_group = parser.add_argument_group("custom fields")
    cf_group.add_argument("--apps", help="Apps field (Server, Coach, KSTV, etc.)")
    cf_group.add_argument("--quarter", help="Quarter (Q1, Q2, Q3, Q4)")
    cf_group.add_argument("--stage", help="Stage (Planning, Engineering, etc.)")
    cf_group.add_argument("--year", help="Year (2024, 2025, 2026)")

    # Output control
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be created without creating")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Minimal output (just task ID and URL)")
    parser.add_argument("--json", action="store_true",
                        help="Output full response as JSON")

    return parser.parse_args(argv)


def configure_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level."""
    level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(levelname)s: %(message)s",
    )


def run(args: argparse.Namespace) -> int:
    """Execute the task creation."""
    token = resolve_token()
    if not token:
        logger.error("No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt")
        return 1

    # Resolve list
    list_id = resolve_list(args.list_id, token)
    logger.debug("Resolved list ID: %s", list_id)

    # Build task data
    task_data: dict[str, Any] = {
        "name": args.name,
        "status": args.status,
    }

    # Add description
    description = build_description(
        args.objective,
        args.justification,
        args.details,
        args.description,
    )
    task_data["markdown_description"] = description

    # Add assignee
    if not args.no_assignee:
        assignee_id = resolve_assignee(args.assignee, token)
        if assignee_id:
            task_data["assignees"] = [assignee_id]
            logger.debug("Resolved assignee: %d", assignee_id)
        else:
            logger.warning("Could not resolve assignee '%s'", args.assignee)

    # Add priority
    if args.priority:
        task_data["priority"] = PRIORITY_MAP[args.priority]

    # Add due date
    if args.due_date:
        try:
            dt = datetime.strptime(args.due_date, "%Y-%m-%d")
            task_data["due_date"] = int(dt.timestamp() * 1000)
        except ValueError:
            logger.error("Invalid date format '%s', use YYYY-MM-DD", args.due_date)
            return 1

    # Add custom fields
    custom_fields = build_custom_fields(args)
    if custom_fields:
        task_data["custom_fields"] = custom_fields

    # Dry run
    if args.dry_run:
        print("Would create task:")
        print(f"  List ID: {list_id}")
        print(f"  Name: {task_data['name']}")
        print(f"  Status: {task_data['status']}")
        print(f"  Assignees: {task_data.get('assignees', 'None')}")
        if task_data.get("priority"):
            print(f"  Priority: {args.priority}")
        if custom_fields:
            print(f"  Custom fields: {len(custom_fields)} field(s)")
        print("\nDescription:")
        print("-" * 40)
        print(description)
        print("-" * 40)
        return 0

    # Create task
    logger.info("Creating task in list %s...", list_id)
    result = create_task(list_id, token, task_data)

    # Output
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.quiet:
        print(f"{result['id']} {result['url']}")
    else:
        print(f"\nTask created successfully!")
        print(f"  ID: {result['id']}")
        print(f"  Name: {result['name']}")
        print(f"  Status: {result.get('status', {}).get('status', 'Unknown')}")
        print(f"  URL: {result['url']}")

    return 0


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


def get_current_user(token: str) -> dict[str, Any]:
    """Get the current authenticated user from the API token.

    Returns cached result on subsequent calls.
    """
    global _current_user
    if _current_user is None:
        logger.debug("Fetching current user from API")
        response = api_request("GET", "/user", token)
        _current_user = response.get("user", {})
        logger.debug("Current user: %s (ID: %s)",
                     _current_user.get("username"), _current_user.get("id"))
    return _current_user


def create_task(list_id: str, token: str, task_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new task in the specified list."""
    return api_request("POST", f"/list/{list_id}/task", token, task_data)


def resolve_assignee(name: str, token: str | None = None) -> int | None:
    """Resolve assignee name to user ID.

    Args:
        name: Assignee name ('me', team member name, or numeric user ID)
        token: API token (required if name is 'me')

    Returns:
        User ID as int, or None if unresolvable.
    """
    name_lower = name.lower()

    # Handle 'me' - requires API call to get current user
    if name_lower == "me":
        if token is None:
            logger.warning("Cannot resolve 'me' without API token")
            return None
        user = get_current_user(token)
        user_id = user.get("id")
        return int(user_id) if user_id else None

    # Check team members (fast path)
    if name_lower in TEAM_MEMBERS:
        return TEAM_MEMBERS[name_lower]

    # Try as direct user ID
    if name.isdigit():
        return int(name)

    # Fall back to a live workspace member lookup for names not in the static map
    if token is not None:
        try:
            from resolve_members import resolve_member_id
            member_id = resolve_member_id(name, token)
            if member_id is not None:
                logger.debug("Resolved assignee '%s' via live member lookup", name)
                return member_id
        except Exception as exc:  # network/import guard - never block task creation
            logger.debug("Live member lookup failed for '%s': %s", name, exc)

    return None


def resolve_list(name: str, token: str) -> str:
    """Resolve list name to list ID."""
    name_lower = name.lower()
    if name_lower in ("sprint", "current"):
        list_id, match_type = resolve_current_sprint_list_id(
            token=token,
            folder_id=SERVER_SPRINT_FOLDER_ID,
            fallback="latest",
        )
        if match_type == "latest":
            logger.warning("No sprint matched today's date; using latest sprint list %s", list_id)
        return list_id
    if name_lower in LIST_PRESETS:
        return LIST_PRESETS[name_lower]
    return name


def build_description(
    objective: str | None,
    justification: str | None,
    details: str | None,
    raw_description: str | None,
) -> str:
    """Build markdown description from sections or raw input."""
    if raw_description:
        return raw_description

    parts: list[str] = []
    parts.append("## Objective\n")
    if objective:
        parts.append(f"{objective}\n")
    parts.append("\n")

    parts.append("## Business Justification\n")
    if justification:
        parts.append(f"{justification}\n")
    parts.append("\n")

    parts.append("## Technical Details\n")
    if details:
        parts.append(f"{details}\n")

    return "".join(parts)


def build_custom_fields(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Build custom fields array from args."""
    fields: list[dict[str, Any]] = []

    if args.apps:
        option_id = APPS_OPTIONS.get(args.apps.lower())
        if option_id:
            fields.append({"id": CUSTOM_FIELD_IDS["apps"], "value": option_id})
        else:
            logger.warning("Unknown apps value '%s'", args.apps)

    if args.quarter:
        option_id = QUARTER_OPTIONS.get(args.quarter.lower())
        if option_id:
            fields.append({"id": CUSTOM_FIELD_IDS["quarter"], "value": option_id})
        else:
            logger.warning("Unknown quarter value '%s'", args.quarter)

    if args.stage:
        option_id = STAGE_OPTIONS.get(args.stage.lower())
        if option_id:
            fields.append({"id": CUSTOM_FIELD_IDS["stage"], "value": option_id})
        else:
            logger.warning("Unknown stage value '%s'", args.stage)

    if args.year:
        option_id = YEAR_OPTIONS.get(str(args.year))
        if option_id:
            fields.append({"id": CUSTOM_FIELD_IDS["year"], "value": option_id})
        else:
            logger.warning("Unknown year value '%s'", args.year)

    return fields


if __name__ == "__main__":
    sys.exit(main())
