#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Aggregate Cloud Run errors by service or job.

Usage:
    uv run error_summary.py [--project PROJECT] [--days DAYS] [--type TYPE]

Examples:
    uv run error_summary.py --project ksu-live --days 7
    uv run error_summary.py --project kidstrong-at-home --type job --days 1
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

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
    parser.add_argument("--type", "-t", choices=["service", "job", "all"], default="all",
                        help="Resource type to query (default: all)")
    parser.add_argument("--limit", "-l", type=int, default=10000,
                        help="Max log entries to fetch (default: 10000)")
    return parser.parse_args(argv)


def query_services(since: str, project: str, limit: int) -> list[dict[str, Any]]:
    """Query Cloud Run service errors."""
    query = f'resource.type="cloud_run_revision" AND severity>=ERROR AND timestamp>="{since}"'
    return run_gcloud_logging(query, project, limit)


def query_jobs(since: str, project: str, limit: int) -> list[dict[str, Any]]:
    """Query Cloud Run job errors."""
    query = f'resource.type="cloud_run_job" AND severity>=ERROR AND timestamp>="{since}"'
    return run_gcloud_logging(query, project, limit)


def run(args: argparse.Namespace) -> None:
    """Execute the error summary analysis."""
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00Z")

    results: Counter[str] = Counter()
    service_entries: list[dict[str, Any]] = []
    job_entries: list[dict[str, Any]] = []

    if args.type == "all":
        # Run both queries in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            service_future = executor.submit(query_services, since, args.project, args.limit)
            job_future = executor.submit(query_jobs, since, args.project, args.limit)
            service_entries = service_future.result()
            job_entries = job_future.result()
    elif args.type == "service":
        service_entries = query_services(since, args.project, args.limit)
    else:
        job_entries = query_jobs(since, args.project, args.limit)

    # Process service entries
    for entry in service_entries:
        name = get_nested(entry, "resource", "labels", "service_name")
        if name:
            results[f"service:{name}"] += 1

    # Process job entries
    for entry in job_entries:
        name = get_nested(entry, "resource", "labels", "job_name")
        if name:
            results[f"job:{name}"] += 1

    # Print results
    print(f"\n{'='*60}")
    print(f"Error Summary: {args.project} (last {args.days} days)")
    print(f"{'='*60}\n")

    if not results:
        print("No errors found.")
        return

    print(f"{'Count':>8}  {'Type':<8}  Resource")
    print(f"{'-'*8}  {'-'*8}  {'-'*40}")

    for name, count in results.most_common():
        rtype, rname = name.split(":", 1)
        print(f"{count:>8}  {rtype:<8}  {rname}")

    print(f"\n{'Total':>8}: {sum(results.values())} errors")


if __name__ == "__main__":
    sys.exit(main())
