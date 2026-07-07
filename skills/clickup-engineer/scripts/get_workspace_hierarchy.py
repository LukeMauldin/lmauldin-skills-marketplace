#!/usr/bin/env python3
"""Compose the ClickUp workspace hierarchy tree (clickup_get_workspace_hierarchy equivalent).

Builds spaces > folders > lists (plus folderless lists per space) by walking:
    GET /team/{team_id}/space
    GET /space/{space_id}/folder      (folders include their `lists` array)
    GET /space/{space_id}/list        (folderless lists)

To minimize calls (and rate-limit risk), the lists inside each folder are read
from the embedded `lists` array returned by the folder listing rather than a
separate per-folder request.

Usage:
    # Full workspace tree as JSON (default)
    uv run --python 3.14 scripts/get_workspace_hierarchy.py

    # Limit to one space
    uv run --python 3.14 scripts/get_workspace_hierarchy.py --space-id 16581563

    # Human-readable indented tree
    uv run --python 3.14 scripts/get_workspace_hierarchy.py --format summary

    # Include archived spaces/folders/lists
    uv run --python 3.14 scripts/get_workspace_hierarchy.py --include-archived

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Parity note: the MCP envelope for clickup_get_workspace_hierarchy is not
observable, so this returns a composed tree of {id, name} nodes (raw passthrough
of the relevant fields).
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

TEAM_ID = "12606327"
RATE_LIMIT_DELAY = 0.15  # Seconds between API calls
MAX_RETRIES = 3


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
    parser.add_argument("--team-id", default=TEAM_ID, help=f"Workspace/team ID (default: {TEAM_ID})")
    parser.add_argument("--space-id", help="Limit the tree to a single space ID")
    parser.add_argument("--include-archived", action="store_true",
                        help="Include archived spaces, folders, and lists")
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

    archived = "true" if args.include_archived else "false"

    if args.space_id:
        spaces = [api_request("GET", f"/space/{args.space_id}", token)]
    else:
        logger.info("Fetching spaces for team %s...", args.team_id)
        spaces = api_request(
            "GET", f"/team/{args.team_id}/space", token, params={"archived": archived}
        ).get("spaces", [])

    tree_spaces: list[dict[str, Any]] = []
    for space in spaces:
        space_id = str(space.get("id"))
        logger.info("Fetching folders/lists for space %s (%s)...", space_id, space.get("name"))

        folders_resp = api_request(
            "GET", f"/space/{space_id}/folder", token, params={"archived": archived}
        )
        time.sleep(RATE_LIMIT_DELAY)
        folders = [
            {
                "id": str(f.get("id")),
                "name": f.get("name"),
                "lists": [list_node(lst) for lst in f.get("lists", [])],
            }
            for f in folders_resp.get("folders", [])
        ]

        folderless_resp = api_request(
            "GET", f"/space/{space_id}/list", token, params={"archived": archived}
        )
        time.sleep(RATE_LIMIT_DELAY)
        folderless = [list_node(lst) for lst in folderless_resp.get("lists", [])]

        tree_spaces.append(
            {
                "id": space_id,
                "name": space.get("name"),
                "folders": folders,
                "lists": folderless,
            }
        )

    output = {
        "team_id": args.team_id,
        "spaces": tree_spaces,
        "metadata": {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "space_count": len(tree_spaces),
            "include_archived": args.include_archived,
        },
    }

    if args.format == "summary":
        render_summary(output)
    else:
        print(json.dumps(output, indent=None if args.compact else 2))

    return 0


def list_node(lst: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(lst.get("id")), "name": lst.get("name")}


def render_summary(output: dict[str, Any]) -> None:
    print(f"Workspace {output['team_id']}")
    for space in output["spaces"]:
        print(f"  Space: {space['name']} ({space['id']})")
        for folder in space["folders"]:
            print(f"    Folder: {folder['name']} ({folder['id']})")
            for lst in folder["lists"]:
                print(f"      List: {lst['name']} ({lst['id']})")
        for lst in space["lists"]:
            print(f"    List: {lst['name']} ({lst['id']})  [folderless]")


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
