#!/usr/bin/env python3
"""Manage ClickUp task tags, links, and dependencies (MUTATIONS).

Covers four MCP tools via subcommands:
    add-tag             clickup_add_tag_to_task        POST   /task/{id}/tag/{tag_name}
    add-link            clickup_add_task_link          POST   /task/{id}/link/{links_to}
    add-dependency      clickup_add_task_dependency    POST   /task/{id}/dependency
    remove-dependency   clickup_remove_task_dependency DELETE /task/{id}/dependency

Task IDs are accepted with or without the `CU-` display prefix.

Usage:
    # Add an existing tag to a task
    uv run --python 3.14 scripts/task_relations.py add-tag 868abc123 backend

    # Link two tasks (task_id <-> links_to)
    uv run --python 3.14 scripts/task_relations.py add-link 868abc123 868def456

    # Make 868abc123 depend on (wait for) 868def456
    uv run --python 3.14 scripts/task_relations.py add-dependency 868abc123 --depends-on 868def456

    # Make 868def456 a dependency-of 868abc123 (868abc123 waits for 868def456)
    uv run --python 3.14 scripts/task_relations.py add-dependency 868abc123 --dependency-of 868def456

    # Remove a dependency
    uv run --python 3.14 scripts/task_relations.py remove-dependency 868abc123 --depends-on 868def456

    # Preview any operation without sending it
    uv run --python 3.14 scripts/task_relations.py add-tag 868abc123 backend --dry-run

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Dependency direction:
    --depends-on X     => this task waits for X (body: {"depends_on": X})
    --dependency-of Y  => Y waits for this task (body: {"dependency_of": Y})
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

    token = resolve_token()
    if not token:
        logger.error("No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt")
        return 1

    try:
        if args.command == "add-tag":
            return cmd_add_tag(args, token)
        if args.command == "add-link":
            return cmd_add_link(args, token)
        if args.command == "add-dependency":
            return cmd_add_dependency(args, token)
        if args.command == "remove-dependency":
            return cmd_remove_dependency(args, token)
        return 1
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

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("task_id", help="Task ID (with or without CU- prefix)")
    common.add_argument("--dry-run", action="store_true",
                        help="Print the exact request without sending it")
    common.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v info, -vv debug)")
    common.add_argument("--quiet", "-q", action="store_true", help="Suppress stderr messages")
    common.add_argument("--compact", action="store_true", help="Compact JSON output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    tag_parser = subparsers.add_parser("add-tag", parents=[common],
                                       help="Add an existing tag to a task", suggest_on_error=True)
    tag_parser.add_argument("tag_name", help="Existing tag name (case-sensitive)")

    link_parser = subparsers.add_parser("add-link", parents=[common],
                                        help="Link a task to another task", suggest_on_error=True)
    link_parser.add_argument("links_to", help="Target task ID to link to")

    add_dep = subparsers.add_parser("add-dependency", parents=[common],
                                    help="Add a dependency", suggest_on_error=True)
    dep_group = add_dep.add_mutually_exclusive_group(required=True)
    dep_group.add_argument("--depends-on", help="Task this task waits for")
    dep_group.add_argument("--dependency-of", help="Task that waits for this task")

    rm_dep = subparsers.add_parser("remove-dependency", parents=[common],
                                   help="Remove a dependency", suggest_on_error=True)
    rm_dep.add_argument("--depends-on", help="The depends_on task ID of the dependency")
    rm_dep.add_argument("--dependency-of", help="The dependency_of task ID of the dependency")

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


def cmd_add_tag(args: argparse.Namespace, token: str) -> int:
    task_id = normalize_task_id(args.task_id)
    endpoint = f"/task/{task_id}/tag/{urllib.parse.quote(args.tag_name, safe='')}"
    if args.dry_run:
        return emit_dry_run("POST", endpoint, None, None, args)
    resp = api_request("POST", endpoint, token)
    emit_result({"operation": "add-tag", "task_id": task_id, "tag_name": args.tag_name,
                 "response": resp}, args)
    return 0


def cmd_add_link(args: argparse.Namespace, token: str) -> int:
    task_id = normalize_task_id(args.task_id)
    links_to = normalize_task_id(args.links_to)
    endpoint = f"/task/{task_id}/link/{links_to}"
    if args.dry_run:
        return emit_dry_run("POST", endpoint, None, None, args)
    resp = api_request("POST", endpoint, token)
    emit_result({"operation": "add-link", "task_id": task_id, "links_to": links_to,
                 "response": resp}, args)
    return 0


def cmd_add_dependency(args: argparse.Namespace, token: str) -> int:
    task_id = normalize_task_id(args.task_id)
    endpoint = f"/task/{task_id}/dependency"
    if args.depends_on:
        body = {"depends_on": normalize_task_id(args.depends_on)}
    else:
        body = {"dependency_of": normalize_task_id(args.dependency_of)}
    if args.dry_run:
        return emit_dry_run("POST", endpoint, body, None, args)
    resp = api_request("POST", endpoint, token, data=body)
    emit_result({"operation": "add-dependency", "task_id": task_id, "body": body,
                 "response": resp}, args)
    return 0


def cmd_remove_dependency(args: argparse.Namespace, token: str) -> int:
    task_id = normalize_task_id(args.task_id)
    if not args.depends_on and not args.dependency_of:
        logger.error("Provide --depends-on and/or --dependency-of")
        return 1
    endpoint = f"/task/{task_id}/dependency"
    params: dict[str, Any] = {}
    if args.depends_on:
        params["depends_on"] = normalize_task_id(args.depends_on)
    if args.dependency_of:
        params["dependency_of"] = normalize_task_id(args.dependency_of)
    if args.dry_run:
        return emit_dry_run("DELETE", endpoint, None, params, args)
    resp = api_request("DELETE", endpoint, token, params=params)
    emit_result({"operation": "remove-dependency", "task_id": task_id, "params": params,
                 "response": resp}, args)
    return 0


def emit_dry_run(
    method: str,
    endpoint: str,
    data: dict[str, Any] | None,
    params: dict[str, Any] | None,
    args: argparse.Namespace,
) -> int:
    url = f"{BASE_URL}{endpoint}"
    if params:
        url = f"{url}?{build_query(params)}"
    preview = {
        "dry_run": True,
        "method": method,
        "url": url,
        "body": data if data is not None else "(no body)",
    }
    print(json.dumps(preview, indent=None if args.compact else 2))
    return 0


def emit_result(result: dict[str, Any], args: argparse.Namespace) -> None:
    print(json.dumps(result, indent=None if args.compact else 2))


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
