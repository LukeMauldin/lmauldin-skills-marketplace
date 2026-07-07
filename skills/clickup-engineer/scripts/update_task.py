#!/usr/bin/env python3
"""
Update a single ClickUp task via API (when MCP tools unavailable).

Supports updating status, priority, assignees, description, custom fields,
and adding comments - all in a single call or separately.

Usage:
    # Update status
    python update_task.py 868abc123 --status "Closed"

    # Add a comment
    python update_task.py 868abc123 --comment "Closing as stale - no longer relevant"

    # Update multiple fields
    python update_task.py 868abc123 --status "in progress" --priority high --assignee me

    # Update description
    python update_task.py 868abc123 --description "Updated description here"

    # Set custom field (Apps = Server)
    python update_task.py 868abc123 --custom-field "039b4b60-e29b-4edc-a126-f465908feded=90ca02d6-0a54-4e1b-92ff-5463c56ba501"

    # View current task state (dry run)
    python update_task.py 868abc123 --dry-run

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Common Status Values:
    Open, backlog, in progress, Closed

Priority Values:
    urgent (1), high (2), normal (3), low (4), none (null)
"""

import argparse
import json
from clickup_auth import resolve_token
import sys
import urllib.request
import urllib.error
from typing import Optional, Any

BASE_URL = "https://api.clickup.com/api/v2"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)

# Common team members for quick assignment (name -> user ID)
TEAM_MEMBERS = {
    "luke": "75349906",
    "bob": "57214468",
    "joshua": "38252373",
    "josh": "38252373",
    "rachel": "38527352",
}

# Cached current user (populated on first call to get_current_user)
_current_user: Optional[dict] = None

PRIORITY_MAP = {
    "urgent": 1,
    "high": 2,
    "normal": 3,
    "low": 4,
    "none": None,
}


def api_request(method: str, endpoint: str, token: str, data: Optional[dict] = None) -> dict:
    """Make an API request to ClickUp."""
    url = f"{BASE_URL}{endpoint}"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    body = json.dumps(data).encode("utf-8") if data else None
    request = urllib.request.Request(url, headers=headers, method=method, data=body)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"API Error {e.code}: {error_body}", file=sys.stderr)
        raise


def get_task(task_id: str, token: str) -> dict:
    """Get task details."""
    return api_request("GET", f"/task/{task_id}", token)


def update_task(task_id: str, token: str, updates: dict) -> dict:
    """Update task fields."""
    return api_request("PUT", f"/task/{task_id}", token, updates)


def add_comment(task_id: str, token: str, comment_text: str, notify_all: bool = False) -> dict:
    """Add a comment to a task."""
    data = {
        "comment_text": comment_text,
        "notify_all": notify_all
    }
    return api_request("POST", f"/task/{task_id}/comment", token, data)


def set_custom_field(task_id: str, field_id: str, value: Any, token: str) -> dict:
    """Set a custom field value."""
    data = {"value": value}
    return api_request("POST", f"/task/{task_id}/field/{field_id}", token, data)


def get_current_user(token: str) -> dict:
    """Get the current authenticated user from the API token.

    Returns cached result on subsequent calls.
    """
    global _current_user
    if _current_user is None:
        response = api_request("GET", "/user", token)
        _current_user = response.get("user", {})
    return _current_user


def resolve_assignee(name: str, token: Optional[str] = None) -> Optional[str]:
    """Resolve assignee name to user ID.

    Args:
        name: Assignee name ('me', team member name, or numeric user ID)
        token: API token (required if name is 'me')

    Returns:
        User ID as string, or None if unresolvable.
    """
    name_lower = name.lower()

    # Handle 'me' - requires API call to get current user
    if name_lower == "me":
        if token is None:
            print("Warning: Cannot resolve 'me' without API token", file=sys.stderr)
            return None
        user = get_current_user(token)
        user_id = user.get("id")
        return str(user_id) if user_id else None

    # Check team members
    if name_lower in TEAM_MEMBERS:
        return TEAM_MEMBERS[name_lower]

    # Try as direct user ID
    if name.isdigit():
        return name

    # Fall back to a live workspace member lookup for names not in the static map
    if token is not None:
        try:
            from resolve_members import resolve_member_id
            member_id = resolve_member_id(name, token)
            if member_id is not None:
                return str(member_id)
        except Exception as e:
            print(f"Warning: live member lookup failed for '{name}': {e}", file=sys.stderr)

    return None


def extract_assignee_ids(assignees: list[object]) -> list[int]:
    """Extract numeric assignee IDs from API responses."""
    ids: list[int] = []
    for assignee in assignees:
        if isinstance(assignee, dict):
            raw_id = assignee.get("id")
            if isinstance(raw_id, int):
                ids.append(raw_id)
            elif isinstance(raw_id, str) and raw_id.isdigit():
                ids.append(int(raw_id))
        elif isinstance(assignee, int):
            ids.append(assignee)
        elif isinstance(assignee, str) and assignee.isdigit():
            ids.append(int(assignee))
    return ids


def format_assignees(assignees: list[object]) -> str:
    """Format assignees for display, supporting ID-only responses."""
    names: list[str] = []
    for assignee in assignees:
        if isinstance(assignee, dict):
            name = assignee.get("username") or assignee.get("email") or assignee.get("id")
            if name is not None:
                names.append(str(name))
        else:
            names.append(str(assignee))
    return ", ".join(names) if names else "None"


def print_task_summary(task: dict):
    """Print a summary of task state."""
    print(f"\nTask: {task.get('name')}")
    print(f"  ID: {task.get('id')}")
    print(f"  Status: {task.get('status', {}).get('status')}")
    print(f"  Priority: {task.get('priority', {}).get('priority') if task.get('priority') else 'None'}")
    print(f"  Assignees: {format_assignees(task.get('assignees', []))}")
    print(f"  URL: {task.get('url')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update a ClickUp task via API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        suggest_on_error=True,
    )
    parser.add_argument("task_id", help="Task ID to update (e.g., 868abc123)")
    parser.add_argument("--status", "-s", help="Set status (e.g., 'Closed', 'in progress')")
    parser.add_argument("--priority", "-p", choices=list(PRIORITY_MAP.keys()), help="Set priority")
    parser.add_argument("--assignee", "-a", action="append", dest="assignees",
                        help="Set assignee: 'me' (current user), team name, or ID. Can repeat.")
    parser.add_argument("--add-assignee", action="append", dest="add_assignees",
                        help="Add assignee without removing existing. Can repeat.")
    parser.add_argument("--remove-assignee", action="append", dest="remove_assignees",
                        help="Remove specific assignee. Can repeat.")
    parser.add_argument("--description", "-d", help="Set description (markdown supported)")
    parser.add_argument("--name", "-n", help="Set task name")
    parser.add_argument("--comment", "-c", help="Add a comment to the task")
    parser.add_argument("--comment-notify", action="store_true", help="Notify assignees of comment")
    parser.add_argument("--custom-field", action="append", dest="custom_fields",
                        metavar="FIELD_ID=VALUE", help="Set custom field. Can repeat.")
    parser.add_argument("--due-date", help="Set due date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Show current state, don't update")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output")

    args = parser.parse_args()

    token = resolve_token()
    if not token:
        print("Error: No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt", file=sys.stderr)
        sys.exit(1)

    # Get current task state
    if not args.quiet:
        print(f"Fetching task {args.task_id}...", file=sys.stderr)

    try:
        task = get_task(args.task_id, token)
    except Exception as e:
        print(f"Error fetching task: {e}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print_task_summary(task)
        print("\n(Dry run - no changes made)")
        return 0

    # Build updates
    updates = {}
    made_changes = False

    if args.status:
        updates["status"] = args.status
        made_changes = True

    if args.priority:
        updates["priority"] = PRIORITY_MAP[args.priority]
        made_changes = True

    if args.assignees:
        user_ids = []
        for a in args.assignees:
            uid = resolve_assignee(a, token)
            if uid:
                user_ids.append(int(uid))
            else:
                print(f"Warning: Could not resolve assignee '{a}'", file=sys.stderr)
        if user_ids:
            updates["assignees"] = {
                "add": user_ids,
                "rem": extract_assignee_ids(task.get("assignees", [])),
            }
            made_changes = True

    if args.add_assignees:
        add_ids = []
        for a in args.add_assignees:
            uid = resolve_assignee(a, token)
            if uid:
                add_ids.append(int(uid))
        if add_ids:
            updates["assignees"] = updates.get("assignees", {})
            updates["assignees"]["add"] = updates["assignees"].get("add", []) + add_ids
            made_changes = True

    if args.remove_assignees:
        rem_ids = []
        for a in args.remove_assignees:
            uid = resolve_assignee(a, token)
            if uid:
                rem_ids.append(int(uid))
        if rem_ids:
            updates["assignees"] = updates.get("assignees", {})
            updates["assignees"]["rem"] = updates["assignees"].get("rem", []) + rem_ids
            made_changes = True

    if args.description:
        updates["markdown_description"] = args.description
        made_changes = True

    if args.name:
        updates["name"] = args.name
        made_changes = True

    if args.due_date:
        # Convert YYYY-MM-DD to timestamp
        from datetime import datetime
        try:
            dt = datetime.strptime(args.due_date, "%Y-%m-%d")
            updates["due_date"] = int(dt.timestamp() * 1000)
            made_changes = True
        except ValueError:
            print(f"Error: Invalid date format '{args.due_date}', use YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)

    # Apply main updates
    if updates:
        if not args.quiet:
            print(f"Updating task with: {json.dumps(updates, indent=2)}", file=sys.stderr)
        try:
            result = update_task(args.task_id, token, updates)
            if not args.quiet:
                print("Task updated successfully", file=sys.stderr)
        except Exception as e:
            print(f"Error updating task: {e}", file=sys.stderr)
            sys.exit(1)

    # Handle custom fields separately
    if args.custom_fields:
        for cf_arg in args.custom_fields:
            if "=" not in cf_arg:
                print(f"Error: Invalid custom field format '{cf_arg}', use FIELD_ID=VALUE", file=sys.stderr)
                continue
            field_id, value = cf_arg.split("=", 1)
            try:
                if not args.quiet:
                    print(f"Setting custom field {field_id}...", file=sys.stderr)
                set_custom_field(args.task_id, field_id.strip(), value.strip(), token)
                made_changes = True
            except Exception as e:
                print(f"Error setting custom field: {e}", file=sys.stderr)

    # Add comment
    if args.comment:
        try:
            if not args.quiet:
                print("Adding comment...", file=sys.stderr)
            add_comment(args.task_id, token, args.comment, args.comment_notify)
            made_changes = True
            if not args.quiet:
                print("Comment added", file=sys.stderr)
        except Exception as e:
            print(f"Error adding comment: {e}", file=sys.stderr)

    if not made_changes:
        print("No changes specified. Use --help to see options.", file=sys.stderr)
        print_task_summary(task)
        return 0

    # Show final state
    if not args.quiet:
        updated_task = get_task(args.task_id, token)
        print_task_summary(updated_task)

    return 0


if __name__ == "__main__":
    sys.exit(main())
