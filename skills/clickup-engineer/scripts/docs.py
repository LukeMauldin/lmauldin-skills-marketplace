#!/usr/bin/env python3
"""Read ClickUp Docs via the v3 API (clickup_list_document_pages / clickup_get_document_pages).

Docs are NOT in the v2 OpenAPI spec; they use API v3
(https://api.clickup.com/api/v3). Both endpoints below return BARE JSON ARRAYS
(verified live), so this script prints arrays, not wrapped objects.

Subcommands:
    list-pages  GET /workspaces/{ws}/docs/{doc_id}/pageListing
                -> array of { id, doc_id, workspace_id, name } (page tree)
    get-pages   GET /workspaces/{ws}/docs/{doc_id}/pages?content_format=text/md
                -> array of page objects including a `content` field

Usage:
    # List the pages in a doc
    uv run --python 3.14 scripts/docs.py list-pages --doc-id c0pvq-10131

    # Get all pages' content as markdown (default content-format)
    uv run --python 3.14 scripts/docs.py get-pages --doc-id c0pvq-10131

    # Get specific pages as HTML
    uv run --python 3.14 scripts/docs.py get-pages --doc-id c0pvq-10131 \
        --page-ids c0pvq-4511 --content-format text/html

    # A full doc URL works too (docId is parsed out)
    uv run --python 3.14 scripts/docs.py list-pages \
        --doc-id https://app.clickup.com/12606327/v/dc/c0pvq-10131/c0pvq-4511

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset

Note: Doc WRITE/CREATE (clickup_update_document_page, clickup_create_document)
remain MCP-only; this script covers reads.
"""
from __future__ import annotations

import argparse
import json
import logging
from clickup_auth import resolve_token
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

BASE_URL_V3 = "https://api.clickup.com/api/v3"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)

WORKSPACE_ID = "12606327"
MAX_RETRIES = 3

# Doc URL: https://app.clickup.com/{ws}/v/dc/{docId}/{pageId}
DOC_URL_RE = re.compile(r"/v/dc/(?P<doc_id>[^/?#]+)")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose, args.quiet)

    token = resolve_token()
    if not token:
        logger.error("No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt")
        return 1

    try:
        if args.command == "list-pages":
            return cmd_list_pages(args, token)
        if args.command == "get-pages":
            return cmd_get_pages(args, token)
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
    common.add_argument("--doc-id", required=True, help="Doc ID (e.g., c0pvq-10131) or a full doc URL")
    common.add_argument("--workspace-id", default=WORKSPACE_ID, help=f"Workspace ID (default: {WORKSPACE_ID})")
    common.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v info, -vv debug)")
    common.add_argument("--quiet", "-q", action="store_true", help="Suppress stderr messages")
    common.add_argument("--compact", action="store_true", help="Compact JSON output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list-pages", parents=[common], help="List the page tree of a doc", suggest_on_error=True,
    )
    list_parser.add_argument("--max-page-depth", type=int, default=-1,
                             help="Max nesting depth to return (-1 = all, default)")

    get_parser = subparsers.add_parser(
        "get-pages", parents=[common], help="Get page content of a doc", suggest_on_error=True,
    )
    get_parser.add_argument("--page-ids", nargs="*", default=None,
                            help="Specific page IDs to fetch (default: all pages)")
    get_parser.add_argument("--content-format", choices=["text/md", "text/html"], default="text/md",
                            help="Content format (default: text/md)")

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


def parse_doc_id(raw: str) -> str:
    """Accept a bare doc ID or a full doc URL and return the doc ID."""
    match = DOC_URL_RE.search(raw)
    if match:
        return match.group("doc_id")
    return raw.strip()


def cmd_list_pages(args: argparse.Namespace, token: str) -> int:
    doc_id = parse_doc_id(args.doc_id)
    logger.info("Listing pages for doc %s...", doc_id)
    params: dict[str, Any] = {}
    if args.max_page_depth is not None and args.max_page_depth >= 0:
        params["max_page_depth"] = args.max_page_depth
    pages = api_request(
        "GET",
        f"/workspaces/{args.workspace_id}/docs/{doc_id}/pageListing",
        token,
        params=params or None,
    )
    print(json.dumps(pages, indent=None if args.compact else 2))
    return 0


def cmd_get_pages(args: argparse.Namespace, token: str) -> int:
    doc_id = parse_doc_id(args.doc_id)
    logger.info("Fetching page content for doc %s (%s)...", doc_id, args.content_format)
    params: dict[str, Any] = {"content_format": args.content_format}
    if args.page_ids:
        params["page_ids[]"] = args.page_ids
    pages = api_request(
        "GET",
        f"/workspaces/{args.workspace_id}/docs/{doc_id}/pages",
        token,
        params=params,
    )
    print(json.dumps(pages, indent=None if args.compact else 2))
    return 0


def api_request(
    method: str,
    endpoint: str,
    token: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """Make a v3 API request to ClickUp (empty-body safe, 429 backoff)."""
    url = f"{BASE_URL_V3}{endpoint}"
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
