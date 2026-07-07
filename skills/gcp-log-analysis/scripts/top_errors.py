#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Show top error patterns for a specific Cloud Run service or job.

Usage:
    uv run top_errors.py --service SERVICE [--project PROJECT] [--days DAYS]
    uv run top_errors.py --job JOB [--project PROJECT] [--days DAYS]

Examples:
    uv run top_errors.py --service kidstrong-task-handler --days 7
    uv run top_errors.py --job kidstrong-firestore-integrity-checker-job
    uv run top_errors.py --service center-sync-service --project kidstrong-at-home
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from _gcloud import (
    DEFAULT_PROJECT,
    PROJECTS,
    GcloudError,
    configure_logging,
    get_nested,
    run_gcloud_logging,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    args = parse_args(argv)
    configure_logging(args.verbose)

    try:
        run(args)
        return 0
    except KeyboardInterrupt:
        return 130
    except GcloudError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}", file=sys.stderr)
        return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        suggest_on_error=True,
    )
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v, -vv)")
    parser.add_argument("--project", "-p", default=DEFAULT_PROJECT,
                        choices=PROJECTS,
                        help=f"GCP project (default: {DEFAULT_PROJECT})")
    parser.add_argument("--days", "-d", type=int, default=7,
                        help="Number of days to look back (default: 7)")
    parser.add_argument("--service", "-s", help="Cloud Run service name")
    parser.add_argument("--job", "-j", help="Cloud Run job name")
    parser.add_argument("--limit", "-l", type=int, default=500,
                        help="Max log entries to fetch (default: 500)")
    parser.add_argument("--top", "-n", type=int, default=20,
                        help="Number of top patterns to show (default: 20)")
    args = parser.parse_args(argv)

    if not args.service and not args.job:
        parser.error("Either --service or --job is required")

    return args


def truncate(s: str, max_len: int = 100) -> str:
    """Truncate string to max length."""
    return s[:max_len] + "..." if len(s) > max_len else s


def extract_error_message(entry: dict) -> str:
    """Extract the most relevant error message from a log entry."""
    # Try textPayload first (simple text logs)
    text_payload = entry.get("textPayload")
    if text_payload:
        return text_payload.strip()

    # Try jsonPayload fields
    json_payload = entry.get("jsonPayload", {})
    if json_payload:
        # Common error message fields
        for field in ["message", "error", "msg", "errorMessage", "exception"]:
            value = json_payload.get(field)
            if value:
                if isinstance(value, str):
                    return value.strip()
                elif isinstance(value, dict):
                    # Nested error object
                    return str(value.get("message", value))

        # If no specific field, stringify the whole payload
        return str(json_payload)

    return "<no message>"


def run(args: argparse.Namespace) -> None:
    """Execute the top errors analysis."""
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00Z")

    # Build query
    if args.service:
        query = f'resource.type="cloud_run_revision" AND resource.labels.service_name="{args.service}" AND severity>=ERROR AND timestamp>="{since}"'
        resource_name = args.service
    else:
        query = f'resource.type="cloud_run_job" AND resource.labels.job_name="{args.job}" AND severity>=ERROR AND timestamp>="{since}"'
        resource_name = args.job

    entries = run_gcloud_logging(query, args.project, args.limit)

    # Count error patterns
    patterns: Counter[str] = Counter()
    for entry in entries:
        msg = extract_error_message(entry)
        if msg:
            patterns[msg] += 1

    # Print results
    print(f"\n{'='*80}")
    print(f"Top Error Patterns: {resource_name} (last {args.days} days)")
    print(f"Project: {args.project}")
    print(f"{'='*80}\n")

    if not patterns:
        print("No errors found.")
        return

    print(f"{'Count':>8}  Error Pattern")
    print(f"{'-'*8}  {'-'*70}")

    for msg, count in patterns.most_common(args.top):
        print(f"{count:>8}  {truncate(msg, 70)}")

    total = sum(patterns.values())
    unique = len(patterns)
    print(f"\n{'Total':>8}: {total} errors ({unique} unique patterns)")


if __name__ == "__main__":
    sys.exit(main())
