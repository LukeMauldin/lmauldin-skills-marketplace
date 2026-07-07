#!/usr/bin/env python3
"""Attach local file(s) to a ClickUp task (clickup_attach_task_file equivalent).

Uploads one or more files **from local paths** to a task via ClickUp's native
multipart attachment API. Unlike the MCP tool (which takes inline base64 or a
public URL), this reads bytes straight from disk — no base64 round-trip through
the model's context.

API:
    POST https://api.clickup.com/api/v2/task/{task_id}/attachment
    Content-Type: multipart/form-data (file field name: "attachment", one per request)
    Max 1 GB per file; any file type; cloud-stored files not allowed.

`urllib` has no multipart encoder, so the body is hand-built: a boundary, a
`Content-Disposition`/`Content-Type` part header, the raw file bytes, and the
closing boundary. Files upload sequentially (one request each).

Task IDs are accepted with or without the `CU-` display prefix.

Usage:
    # Attach a single file
    uv run --python 3.14 scripts/attach_file.py 868abc123 ./report.md

    # Attach multiple files (one request each)
    uv run --python 3.14 scripts/attach_file.py 868abc123 ./a.md ./b.png ./c.pdf

    # Custom task IDs (team_id required by the API in this mode)
    uv run --python 3.14 scripts/attach_file.py CUSTOM-123 ./report.md \
      --custom-task-id --team-id 12606327

    # Preview only — prints path, size, mimetype, target; sends nothing
    uv run --python 3.14 scripts/attach_file.py 868abc123 ./report.md --dry-run

Environment:
    CLICKUP_API_TOKEN - ClickUp API token (pk_...); falls back to ~/.agents/clickup_key.txt when unset
"""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from clickup_auth import resolve_token

if TYPE_CHECKING:
    from collections.abc import Sequence

import sys

logger = logging.getLogger(__name__)

BASE_URL = "https://api.clickup.com/api/v2"
MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    version = sys.version.split()[0]
    print(f"Error: Python 3.14+ required; detected {version}.", file=sys.stderr)
    sys.exit(1)

RATE_LIMIT_DELAY = 0.15  # Seconds between API calls
MAX_RETRIES = 3
DEFAULT_MIME = "application/octet-stream"


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
    parser.add_argument("task_id", help="Task ID to attach to (with or without CU- prefix)")
    parser.add_argument(
        "file_paths",
        nargs="+",
        metavar="FILE",
        help="Local file path(s) to upload (one request per file)",
    )
    parser.add_argument("--custom-task-id", action="store_true",
                        help="Treat task_id as a custom task ID (requires --team-id)")
    parser.add_argument("--team-id", help="Workspace/team ID (required with --custom-task-id)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only: print path, size, mimetype, target; send nothing")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v info, -vv debug)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress stderr messages")
    parser.add_argument("--compact", action="store_true", help="Compact JSON output")

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


def guess_mimetype(path: Path) -> str:
    """Best-effort content type; default to a generic binary type."""
    mime, _ = mimetypes.guess_type(path.name)
    return mime or DEFAULT_MIME


def run(args: argparse.Namespace) -> int:
    token = resolve_token()
    if not token:
        logger.error("No ClickUp token: set CLICKUP_API_TOKEN or create ~/.agents/clickup_key.txt")
        return 1

    if args.custom_task_id and not args.team_id:
        logger.error("--custom-task-id requires --team-id")
        return 1

    # Validate every path up front so a bad path fails before any upload.
    files: list[Path] = []
    exit_code = 0
    for raw_path in args.file_paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            logger.error("File not found: %s", raw_path)
            exit_code = 1
        elif not path.is_file():
            logger.error("Not a regular file: %s", raw_path)
            exit_code = 1
        else:
            files.append(path)
    if exit_code:
        return exit_code

    task_id = normalize_task_id(args.task_id)
    params: dict[str, Any] = {}
    if args.custom_task_id:
        params["custom_task_ids"] = True
        params["team_id"] = args.team_id

    results: list[dict[str, Any]] = []
    for i, path in enumerate(files):
        size = path.stat().st_size
        mimetype = guess_mimetype(path)

        if args.dry_run:
            logger.warning(
                "DRY RUN: would upload %s (%d bytes, %s) to task %s. Re-run without --dry-run to send.",
                path, size, mimetype, task_id,
            )
            results.append({
                "file": str(path),
                "size": size,
                "mimetype": mimetype,
                "uploaded": False,
                "dry_run": True,
            })
            continue

        logger.info("Uploading %s (%d bytes, %s) to task %s...", path.name, size, mimetype, task_id)
        try:
            response = upload_attachment(task_id, path, mimetype, token, params)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8")
            logger.error("Failed to upload %s: HTTP %d: %s", path, exc.code, error_body)
            results.append({
                "file": str(path),
                "size": size,
                "mimetype": mimetype,
                "uploaded": False,
                "error": f"http_{exc.code}",
            })
            exit_code = 1
            continue

        results.append({
            "file": str(path),
            "size": size,
            "mimetype": mimetype,
            "uploaded": True,
            "attachment_id": response.get("id"),
            "url": response.get("url"),
            "title": response.get("title"),
        })
        if i < len(files) - 1:
            time.sleep(RATE_LIMIT_DELAY)

    payload = {
        "task_id": task_id,
        "executed": not args.dry_run,
        "results": results,
        "count": len(results),
    }
    print(json.dumps(payload, indent=None if args.compact else 2))
    return exit_code


def encode_multipart(field_name: str, path: Path, mimetype: str) -> tuple[bytes, str]:
    """Hand-build a multipart/form-data body for one file part.

    Returns (body_bytes, boundary). urllib has no multipart encoder, so the body
    is assembled manually: opening boundary, the part headers, the raw file
    bytes, then the closing boundary.
    """
    boundary = uuid.uuid4().hex
    # RFC 2388: escape quotes/backslashes in the filename; ASCII control already excluded.
    filename = path.name.replace("\\", "\\\\").replace('"', '\\"')
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {mimetype}\r\n\r\n"
    ).encode("utf-8")
    trailer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = header + path.read_bytes() + trailer
    return body, boundary


def upload_attachment(
    task_id: str,
    path: Path,
    mimetype: str,
    token: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST one file to the task attachment endpoint (429-aware backoff)."""
    url = f"{BASE_URL}/task/{task_id}/attachment"
    if params:
        url = f"{url}?{build_query(params)}"

    body, boundary = encode_multipart("attachment", path, mimetype)
    headers = {
        "Authorization": token,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    logger.debug("API POST /task/%s/attachment (%d bytes)", task_id, len(body))
    attempt = 0
    while True:
        request = urllib.request.Request(url, headers=headers, method="POST", data=body)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
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
        if isinstance(value, bool):
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
