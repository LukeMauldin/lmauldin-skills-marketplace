#!/usr/bin/env python3
"""
Generate markdown documentation from ClickUp task JSON.

Converts task JSON (from fetch_filtered_tasks.py) into reviewable markdown:
- INDEX.md: Summary table of all tickets
- Individual {task_id}.md files with full details
- Optional legacy tech flagging

Usage:
    # Basic usage
    python generate_ticket_docs.py tasks.json --output-dir ./tickets

    # With legacy tech flagging
    python generate_ticket_docs.py tasks.json --output-dir ./tickets --flag-legacy

    # Fetch comments for each task (slower, requires API token)
    python generate_ticket_docs.py tasks.json --output-dir ./tickets --fetch-comments

    # Exclude closed tasks
    python generate_ticket_docs.py tasks.json --output-dir ./tickets --exclude-closed

Environment:
    CLICKUP_API_TOKEN - needed only for --fetch-comments; from env or ~/.agents/clickup_key.txt
"""

import argparse
import json
from clickup_auth import resolve_token
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_URL = "https://api.clickup.com/api/v2"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)

# Legacy/deprecated technology patterns
LEGACY_PATTERNS = {
    "KSP": ["ksp", "kidstrong parent", "parent gateway", "ksp gateway"],
    "Flamelink/Hygraph": ["flamelink", "hygraph legacy", "hygraph remove"],
    "TypeScript": ["typescript port", "typescript replace", "cloud function port"],
    "Cloud Functions": ["cloud function migrate", "cloud function replace", "cloud function remove"],
    "ZenPlanner": ["zenplanner", "zen planner"],
    "Daxko": ["daxko"],
}


def timestamp_to_date(ts: Optional[str]) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "—"


def timestamp_to_datetime(ts: Optional[str]) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return "—"


def get_custom_field_value(task: dict, field_name: str) -> str:
    for cf in task.get("custom_fields", []):
        cf_name = cf.get("name", "").lower().replace("👥 ", "").replace("🛠 ", "")
        if cf_name == field_name.lower():
            value = cf.get("value")
            if value is None:
                return "—"
            options = cf.get("type_config", {}).get("options", [])
            for opt in options:
                if opt.get("orderindex") == value or str(opt.get("orderindex")) == str(value):
                    return opt.get("name", str(value))
            return str(value) if value else "—"
    return "—"


def check_legacy_tech(task: dict) -> list[str]:
    """Check if task relates to deprecated/legacy tech."""
    name = task.get("name", "").lower()
    desc = (task.get("text_content") or task.get("description") or "").lower()
    tags = [t.get("name", "").lower() for t in task.get("tags", [])]
    text = f"{name} {desc} {' '.join(tags)}"

    matches = []
    for tech, patterns in LEGACY_PATTERNS.items():
        for pattern in patterns:
            if pattern in text:
                matches.append(tech)
                break
    return matches


def fetch_comments(task_id: str, token: str) -> list[dict]:
    """Fetch comments for a task."""
    url = f"{BASE_URL}/task/{task_id}/comment"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("comments", [])
    except Exception as e:
        print(f"  Warning: Failed to fetch comments for {task_id}: {e}", file=sys.stderr)
        return []


def format_comment(comment: dict) -> str:
    user = comment.get("user", {})
    username = user.get("username", "Unknown")
    date = timestamp_to_datetime(comment.get("date"))
    text = comment.get("comment_text", "").strip()
    if not text:
        return ""
    if len(text) > 1000:
        text = text[:1000] + "... [truncated]"
    return f"**{username}** ({date}):\n> {text}\n"


def generate_ticket_markdown(task: dict, comments: list[dict]) -> str:
    task_id = task.get("id", "unknown")
    name = task.get("name", "Untitled")
    url = task.get("url", f"https://app.clickup.com/t/{task_id}")

    status = task.get("status", {}).get("status", "Unknown")
    priority_data = task.get("priority")
    priority = priority_data.get("priority", "None") if priority_data else "None"

    date_created = timestamp_to_date(task.get("date_created"))
    date_updated = timestamp_to_date(task.get("date_updated"))

    creator = task.get("creator", {}).get("username", "Unknown")
    assignees = [a.get("username", "Unknown") for a in task.get("assignees", [])]
    assignees_str = ", ".join(assignees) if assignees else "Unassigned"

    tags = [t.get("name", "") for t in task.get("tags", [])]
    tags_str = ", ".join(f"`{t}`" for t in tags) if tags else "None"

    apps = get_custom_field_value(task, "Apps")
    quarter = get_custom_field_value(task, "Quarter")
    stage = get_custom_field_value(task, "Stage")
    year = get_custom_field_value(task, "Year")

    description = task.get("text_content") or task.get("description") or ""
    if len(description) > 5000:
        description = description[:5000] + "\n\n... [truncated]"

    points = task.get("points")
    points_str = str(points) if points else "—"

    try:
        created_ts = int(task.get("date_created", 0)) / 1000
        age_days = (datetime.now(timezone.utc).timestamp() - created_ts) / 86400
        age_str = f"{int(age_days)} days"
    except Exception:
        age_str = "—"

    md = f"""# {name}

> **ClickUp**: [{task_id}]({url})

## Quick Info

| Field | Value |
|-------|-------|
| **Status** | {status} |
| **Priority** | {priority.capitalize() if priority else 'None'} |
| **Assignees** | {assignees_str} |
| **Points** | {points_str} |
| **Tags** | {tags_str} |
| **Created** | {date_created} ({age_str} ago) |
| **Updated** | {date_updated} |
| **Creator** | {creator} |

## Custom Fields

| Field | Value |
|-------|-------|
| **Apps** | {apps} |
| **Quarter** | {quarter} |
| **Year** | {year} |
| **Stage** | {stage} |

## Description

{description if description.strip() else "_No description provided._"}

"""

    if comments:
        md += "## Comments\n\n"
        for comment in comments[:10]:
            formatted = format_comment(comment)
            if formatted:
                md += formatted + "\n"
        if len(comments) > 10:
            md += f"\n_... and {len(comments) - 10} more comments._\n"

    md += """
---

## Grooming Notes

**Action**: [ ] Keep as-is  [ ] Update  [ ] Close  [ ] Needs Discussion

**Notes**:

"""
    return md


def generate_index_markdown(tasks: list[dict], flag_legacy: bool = False) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    by_status = {}
    by_priority = {}
    legacy_tasks = []

    for task in tasks:
        status = task.get("status", {}).get("status", "Unknown")
        by_status[status] = by_status.get(status, 0) + 1

        priority = task.get("priority", {})
        priority_name = priority.get("priority", "none") if priority else "none"
        by_priority[priority_name] = by_priority.get(priority_name, 0) + 1

        if flag_legacy:
            legacy = check_legacy_tech(task)
            if legacy:
                legacy_tasks.append({"task": task, "tech": legacy})

    sorted_tasks = sorted(tasks, key=lambda t: int(t.get("date_created", 0)))

    md = f"""# Ticket Index

**Generated**: {now}
**Total Tickets**: {len(tasks)}

## Summary

### By Status
| Status | Count |
|--------|-------|
"""
    for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
        md += f"| {status} | {count} |\n"

    md += """
### By Priority
| Priority | Count |
|----------|-------|
"""
    for p in ["urgent", "high", "normal", "low", "none"]:
        if p in by_priority:
            md += f"| {p.capitalize()} | {by_priority[p]} |\n"

    if flag_legacy and legacy_tasks:
        md += f"""
---

## ⚠️ Legacy/Deprecated Tech ({len(legacy_tasks)} tickets)

| # | ID | Name | Tech | Status | Age | Detail |
|---|-----|------|------|--------|-----|--------|
"""
        for i, item in enumerate(sorted(legacy_tasks, key=lambda x: int(x["task"].get("date_created", 0))), 1):
            task = item["task"]
            task_id = task.get("id", "?")
            name = task.get("name", "?")[:45]
            if len(task.get("name", "")) > 45:
                name += "..."
            name = name.replace("|", "\\|")
            tech = ", ".join(item["tech"])
            status = task.get("status", {}).get("status", "?")
            try:
                age = int((datetime.now(timezone.utc).timestamp() - int(task.get("date_created", 0)) / 1000) / 86400)
                age_str = f"{age}d"
            except Exception:
                age_str = "—"
            md += f"| {i} | [CU](https://app.clickup.com/t/{task_id}) | {name} | {tech} | {status} | {age_str} | [View](./{task_id}.md) |\n"

    md += """
---

## All Tickets (Oldest First)

| # | ID | Name | Status | Priority | Assignees | Age | Tags | Detail |
|---|-----|------|--------|----------|-----------|-----|------|--------|
"""

    for i, task in enumerate(sorted_tasks, 1):
        task_id = task.get("id", "?")
        name = task.get("name", "?")[:50]
        if len(task.get("name", "")) > 50:
            name += "..."
        name = name.replace("|", "\\|")

        status = task.get("status", {}).get("status", "?")
        priority = task.get("priority", {})
        priority_str = priority.get("priority", "—") if priority else "—"

        assignees = [a.get("username", "").split()[0] for a in task.get("assignees", [])]
        assignees_str = ", ".join(assignees[:2]) or "—"
        if len(assignees) > 2:
            assignees_str += f" +{len(assignees)-2}"

        try:
            age = int((datetime.now(timezone.utc).timestamp() - int(task.get("date_created", 0)) / 1000) / 86400)
            age_str = f"{age}d"
        except Exception:
            age_str = "—"

        tags = [t.get("name", "") for t in task.get("tags", [])]
        tags_str = ", ".join(tags[:2]) or "—"
        if len(tags) > 2:
            tags_str += "..."

        md += f"| {i} | [CU](https://app.clickup.com/t/{task_id}) | {name} | {status} | {priority_str} | {assignees_str} | {age_str} | {tags_str} | [View](./{task_id}.md) |\n"

    return md


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate markdown documentation from ClickUp task JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        suggest_on_error=True,
    )
    parser.add_argument("input", help="Input JSON file (from fetch_filtered_tasks.py)")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory for markdown files")
    parser.add_argument("--flag-legacy", action="store_true", help="Flag legacy/deprecated tech tickets")
    parser.add_argument("--fetch-comments", action="store_true", help="Fetch comments for each task (slower)")
    parser.add_argument("--exclude-closed", action="store_true", help="Exclude closed tasks")

    args = parser.parse_args()

    token = resolve_token() if args.fetch_comments else None
    if args.fetch_comments and not token:
        print("Error: --fetch-comments needs a token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt", file=sys.stderr)
        sys.exit(1)

    # Load tasks
    print(f"Loading tasks from {args.input}...", file=sys.stderr)
    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    tasks = data.get("tasks", [])
    if args.exclude_closed:
        tasks = [t for t in tasks if not t.get("date_closed")]

    print(f"Processing {len(tasks)} tasks...", file=sys.stderr)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate individual ticket files
    for i, task in enumerate(tasks, 1):
        task_id = task.get("id", "unknown")
        task_name = task.get("name", "Untitled")[:40]

        comments = []
        if args.fetch_comments and token:
            print(f"  [{i}/{len(tasks)}] {task_id}: {task_name}...", file=sys.stderr)
            comments = fetch_comments(task_id, token)
            time.sleep(0.1)
        elif i % 20 == 0 or i == len(tasks):
            print(f"  [{i}/{len(tasks)}] Processing...", file=sys.stderr)

        md_content = generate_ticket_markdown(task, comments)
        (output_dir / f"{task_id}.md").write_text(md_content, encoding="utf-8")

    # Generate index
    print("Generating index...", file=sys.stderr)
    index_content = generate_index_markdown(tasks, args.flag_legacy)
    (output_dir / "INDEX.md").write_text(index_content, encoding="utf-8")

    print(f"\nDone! Generated {len(tasks)} ticket files + INDEX.md in {output_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
