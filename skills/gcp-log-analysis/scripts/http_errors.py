#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Show HTTP error breakdown (4xx/5xx) by service.

Usage:
    uv run http_errors.py [--project PROJECT] [--days DAYS] [--status STATUS]

Examples:
    uv run http_errors.py --project ksu-live --days 7
    uv run http_errors.py --status 500 --days 1
    uv run http_errors.py --status 429  # Rate limit errors
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
    parser.add_argument("--status", "-s", type=int,
                        help="Filter to specific HTTP status code")
    parser.add_argument("--limit", "-l", type=int, default=10000,
                        help="Max log entries to fetch (default: 10000)")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    """Execute the HTTP errors analysis."""
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00Z")

    # Build query
    if args.status:
        status_filter = f"httpRequest.status={args.status}"
    else:
        status_filter = "httpRequest.status>=400"

    query = f'resource.type="cloud_run_revision" AND {status_filter} AND timestamp>="{since}"'

    entries = run_gcloud_logging(query, args.project, args.limit)

    # Count by service and status
    by_service_status: Counter[tuple[str, int]] = Counter()
    for entry in entries:
        service = get_nested(entry, "resource", "labels", "service_name", default="unknown")
        status = get_nested(entry, "httpRequest", "status", default=0)
        if service and status:
            by_service_status[(service, status)] += 1

    # Print results
    status_desc = f"HTTP {args.status}" if args.status else "HTTP 4xx/5xx"
    print(f"\n{'='*60}")
    print(f"{status_desc} Errors: {args.project} (last {args.days} days)")
    print(f"{'='*60}\n")

    if not by_service_status:
        print("No HTTP errors found.")
        return

    print(f"{'Count':>8}  {'Status':>6}  Service")
    print(f"{'-'*8}  {'-'*6}  {'-'*40}")

    for (service, status), count in by_service_status.most_common():
        print(f"{count:>8}  {status:>6}  {service}")

    # Summary by status code
    print(f"\n{'-'*60}")
    print("Summary by Status Code:")
    status_totals: Counter[int] = Counter()
    for (_, status), count in by_service_status.items():
        status_totals[status] += count
    for status, count in sorted(status_totals.items()):
        print(f"  HTTP {status}: {count}")

    print(f"\n{'Total':>8}: {sum(by_service_status.values())} errors")


if __name__ == "__main__":
    sys.exit(main())
