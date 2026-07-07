#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Show error timeline by day for Cloud Run resources.

Usage:
    uv run timeline.py [--project PROJECT] [--days DAYS] [--service SERVICE] [--job JOB]

Examples:
    uv run timeline.py --project ksu-live --days 14
    uv run timeline.py --service kidstrong-task-handler --days 7
    uv run timeline.py --job kidstrong-firestore-integrity-checker-job
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
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
    parser.add_argument("--service", "-s", help="Filter to specific service")
    parser.add_argument("--job", "-j", help="Filter to specific job")
    parser.add_argument("--limit", "-l", type=int, default=20000,
                        help="Max log entries to fetch (default: 20000)")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    """Execute the timeline analysis."""
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00Z")

    # Build query
    if args.service:
        query = f'resource.type="cloud_run_revision" AND resource.labels.service_name="{args.service}" AND severity>=ERROR AND timestamp>="{since}"'
    elif args.job:
        query = f'resource.type="cloud_run_job" AND resource.labels.job_name="{args.job}" AND severity>=ERROR AND timestamp>="{since}"'
    else:
        query = f'(resource.type="cloud_run_revision" OR resource.type="cloud_run_job") AND severity>=ERROR AND timestamp>="{since}"'

    entries = run_gcloud_logging(query, args.project, args.limit)

    # Group by date and resource
    by_date: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    for entry in entries:
        # Parse timestamp to get date
        timestamp = entry.get("timestamp", "")
        if timestamp:
            date = timestamp[:10]  # Extract YYYY-MM-DD
        else:
            continue

        # Get resource name (service or job)
        name = get_nested(entry, "resource", "labels", "service_name")
        if not name:
            name = get_nested(entry, "resource", "labels", "job_name", default="unknown")
        by_date[date][name] += 1

    # Print results
    resource_filter = args.service or args.job or "all resources"
    print(f"\n{'='*70}")
    print(f"Error Timeline: {args.project} - {resource_filter} (last {args.days} days)")
    print(f"{'='*70}\n")

    if not by_date:
        print("No errors found.")
        return

    all_dates = sorted(by_date.keys())

    if args.service or args.job:
        # Simple view for single resource
        print(f"{'Date':<12} {'Count':>8}")
        print(f"{'-'*12} {'-'*8}")
        for date in all_dates:
            total = sum(by_date[date].values())
            bar = "#" * min(total // 10, 40)
            print(f"{date:<12} {total:>8}  {bar}")
    else:
        # Detailed view with top resources per day
        for date in all_dates:
            total = sum(by_date[date].values())
            print(f"\n{date} (total: {total})")
            print("-" * 40)
            sorted_resources = sorted(by_date[date].items(), key=lambda x: -x[1])[:5]
            for name, count in sorted_resources:
                print(f"  {count:>6}  {name}")

    print(f"\n{'Total':>12}: {sum(sum(d.values()) for d in by_date.values())} errors")


if __name__ == "__main__":
    sys.exit(main())
