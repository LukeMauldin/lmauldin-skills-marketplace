#!/usr/bin/env python3
"""Resolve ClickUp workspace members by name, email, or ID (live lookup).

MCP equivalent: clickup_resolve_assignees / clickup_find_member_by_name /
clickup_get_workspace_members.

IMPORTANT — endpoint note: ClickUp has NO working `GET /team/{team_id}/member`
endpoint (it returns HTTP 404). The authoritative live source of workspace members
is `GET /team`, whose response contains `teams[].members[]`, each shaped as
`{"user": {"id", "username", "email", "initials", "role", ...}}`. This script
filters that response to the KidStrong workspace (team 12606327) and matches.

The static name->ID map in create_task.py / update_task.py stays the fast path;
those scripts fall back to `resolve_member_id()` here for any name not in the map.

Usage:
    # Resolve a single member (name substring, email, or numeric ID)
    uv run --python 3.14 scripts/resolve_members.py luke
    uv run --python 3.14 scripts/resolve_members.py luke.mauldin@kidstrong.com
    uv run --python 3.14 scripts/resolve_members.py 75349906

    # List all workspace members
    uv run --python 3.14 scripts/resolve_members.py --list

    # Human-readable summary
    uv run --python 3.14 scripts/resolve_members.py luke --format summary

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Output (resolve, JSON):
    { "query": "luke", "user": { "id": 75349906, "username": "Luke Mauldin", ... } }

Output (--list, JSON):
    { "members": [ { "id": ..., "username": ..., "email": ... } ], "count": N }

Limitation: `GET /team` returns up to ~100 members; this covers all named team
members. There is no separate paginated member endpoint to fall back to.
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

TEAM_ID = "12606327"
RATE_LIMIT_DELAY = 0.15  # Seconds between API calls
MAX_RETRIES = 3

# Cached members (populated on first fetch_members call)
_members_cache: list[dict[str, Any]] | None = None


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
        "query",
        nargs="?",
        help="Name substring, email, or numeric user ID to resolve",
    )
    parser.add_argument(
        "--list",
        dest="list_all",
        action="store_true",
        help="List all workspace members instead of resolving a query",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for info, -vv for debug)",
    )

    output_group = parser.add_argument_group("output options")
    output_group.add_argument(
        "--format",
        "-f",
        choices=["json", "summary"],
        default="json",
        help="Output format (default: json)",
    )
    output_group.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress stderr messages (only output result)",
    )
    output_group.add_argument(
        "--compact",
        action="store_true",
        help="Compact JSON output (no indentation)",
    )

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

    indent = None if args.compact else 2

    if args.list_all:
        members = fetch_members(token)
        users = [m.get("user", {}) for m in members]
        if args.format == "summary":
            for u in users:
                print(f"{u.get('id')}\t{u.get('username')}\t{u.get('email')}")
        else:
            print(json.dumps({"members": users, "count": len(users)}, indent=indent))
        return 0

    if not args.query:
        logger.error("Provide a query (name/email/ID) or use --list")
        return 1

    logger.info("Resolving member '%s'...", args.query)
    user = resolve_member(args.query, token)
    # When there's no unique match, surface the substring candidates so the
    # caller can disambiguate instead of getting a bare null.
    candidates = [] if user else member_candidates(args.query, token)

    if args.format == "summary":
        if user:
            print(f"{user.get('id')}\t{user.get('username')}\t{user.get('email')}")
        elif candidates:
            print(f"Ambiguous '{args.query}' — candidates:")
            for u in candidates:
                print(f"  {u.get('id')}\t{u.get('username')}\t{u.get('email')}")
        else:
            print(f"No member matched '{args.query}'")
    else:
        payload: dict[str, Any] = {"query": args.query, "user": user}
        if candidates:
            payload["candidates"] = candidates
        print(json.dumps(payload, indent=indent))

    return 0 if user else 1


def fetch_members(token: str) -> list[dict[str, Any]]:
    """Fetch workspace members via GET /team (cached). Returns the raw members list."""
    global _members_cache
    if _members_cache is not None:
        return _members_cache

    response = api_request("GET", "/team", token)
    teams = response.get("teams", [])
    members: list[dict[str, Any]] = []
    for team in teams:
        if str(team.get("id")) == TEAM_ID:
            members = team.get("members", [])
            break
    else:
        # No exact team match; fall back to the first team if present.
        if teams:
            logger.warning("Team %s not found in /team response; using first team", TEAM_ID)
            members = teams[0].get("members", [])

    _members_cache = members
    return members


def resolve_member(query: str, token: str) -> dict[str, Any] | None:
    """Resolve a name/email/ID to a member's `user` dict, or None.

    Match order: numeric ID exact -> email exact -> username exact ->
    username substring (only if unambiguous).
    """
    members = fetch_members(token)
    users = [m.get("user", {}) for m in members]
    q = query.strip().lower()

    if q.isdigit():
        for u in users:
            if str(u.get("id")) == q:
                return u

    for u in users:
        if (u.get("email") or "").lower() == q:
            return u

    for u in users:
        if (u.get("username") or "").lower() == q:
            return u

    substring = [u for u in users if q in (u.get("username") or "").lower()]
    if len(substring) == 1:
        return substring[0]
    if len(substring) > 1:
        names = ", ".join(str(u.get("username")) for u in substring)
        logger.warning("Ambiguous query '%s' matched %d members: %s", query, len(substring), names)
        return None

    return None


def member_candidates(query: str, token: str) -> list[dict[str, Any]]:
    """Return all members whose username contains the query (substring, case-insensitive)."""
    q = query.strip().lower()
    users = [m.get("user", {}) for m in fetch_members(token)]
    return [u for u in users if q in (u.get("username") or "").lower()]


def resolve_member_id(query: str, token: str) -> int | None:
    """Resolve a name/email/ID to a numeric user ID, or None.

    Used as a fallback by create_task.py and update_task.py when a name is not
    present in their static TEAM_MEMBERS map.
    """
    user = resolve_member(query, token)
    if not user:
        return None
    uid = user.get("id")
    return int(uid) if uid is not None else None


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
