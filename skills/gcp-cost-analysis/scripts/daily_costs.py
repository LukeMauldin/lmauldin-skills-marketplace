#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Analyze daily GCP costs to identify spending trends and anomalies.

Shows day-by-day cost breakdown with optional service filtering.

Usage:
    uv run daily_costs.py --start 2025-12-22 --end 2026-01-11
    uv run daily_costs.py --start 2025-12-22 --end 2026-01-11 --service "Cloud Logging"
"""
from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from _bq import (
    BILLING_TABLE_STANDARD,
    BQError,
    DEFAULT_PROJECT,
    build_cost_type_clause,
    configure_logging,
    describe_project_scope,
    end_exclusive_str,
    format_currency,
    print_table,
    run_bq_query,
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
    except BQError as e:
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
    )
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v, -vv)")
    parser.add_argument("--start", "-s", required=True,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", "-e", required=True,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--service", help="Filter by service name")
    parser.add_argument("--project", "-p",
                        help="Filter billed costs to a specific project.id in the export")
    parser.add_argument("--bq-project", default=DEFAULT_PROJECT,
                        help=(
                            "GCP project that runs the BigQuery query and hosts the billing "
                            f"dataset access (default: {DEFAULT_PROJECT}); not a cost filter"
                        ))
    parser.add_argument("--show-services", action="store_true",
                        help="Show breakdown by service for each day")
    parser.add_argument("--cost-type", action="append", dest="cost_types",
                        help="Include only specific cost_type (repeatable)")
    parser.add_argument("--exclude-cost-type", action="append", dest="exclude_cost_types",
                        help="Exclude specific cost_type (repeatable)")
    parser.add_argument("--exclude-tax-adjustments", action="store_true",
                        help="Exclude tax and adjustment cost types")

    return parser.parse_args(argv)


def query_daily_totals(
    start: str,
    end: str,
    service: str | None,
    project: str | None,
    cost_type_clause: str,
    *,
    bq_project: str,
) -> list[dict]:
    """Query daily cost totals."""
    end_exclusive = end_exclusive_str(end)
    where_clauses = [
        f'usage_start_time >= TIMESTAMP("{start}")',
        f'usage_start_time < TIMESTAMP("{end_exclusive}")',
    ]
    if service:
        where_clauses.append(f'service.description = "{service}"')
    if project:
        where_clauses.append(f'project.id = "{project}"')
    where = " AND ".join(where_clauses)
    if cost_type_clause:
        where = f"{where} {cost_type_clause}"

    query = f"""
SELECT
  DATE(usage_start_time) AS usage_date,
  ROUND(SUM(cost), 2) AS gross_cost,
  ROUND(SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS credits,
  ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net_cost,
  COUNT(*) AS line_items
FROM `{BILLING_TABLE_STANDARD}`
WHERE {where}
GROUP BY usage_date
ORDER BY usage_date
"""
    return run_bq_query(query, project_id=bq_project)


def query_daily_by_service(
    start: str,
    end: str,
    project: str | None,
    cost_type_clause: str,
    *,
    bq_project: str,
) -> list[dict]:
    """Query daily costs broken down by service."""
    end_exclusive = end_exclusive_str(end)
    where_clauses = [
        f'usage_start_time >= TIMESTAMP("{start}")',
        f'usage_start_time < TIMESTAMP("{end_exclusive}")',
    ]
    if project:
        where_clauses.append(f'project.id = "{project}"')
    where = " AND ".join(where_clauses)
    if cost_type_clause:
        where = f"{where} {cost_type_clause}"

    query = f"""
SELECT
  DATE(usage_start_time) AS usage_date,
  service.description AS service,
  ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net_cost
FROM `{BILLING_TABLE_STANDARD}`
WHERE {where}
GROUP BY usage_date, service
HAVING net_cost > 0.10
ORDER BY usage_date, net_cost DESC
"""
    return run_bq_query(query, project_id=bq_project)


def run(args: argparse.Namespace) -> None:
    """Execute the daily costs analysis."""
    print(f"\n{'='*70}")
    print(f"Daily GCP Costs: {args.start} to {args.end}")
    print(f"{'='*70}")
    if args.service:
        print(f"Service Filter: {args.service}")
    print(f"Project Scope: {describe_project_scope(args.project)}")
    print(f"BQ Host:       {args.bq_project}")
    print()

    cost_type_clause = build_cost_type_clause(
        args.cost_types,
        args.exclude_cost_types,
        args.exclude_tax_adjustments,
    )

    if args.cost_types:
        print(f"Cost Type: Include only {', '.join(args.cost_types)}")
    elif args.exclude_cost_types or args.exclude_tax_adjustments:
        exclude = (args.exclude_cost_types or []) + (
            ["tax", "adjustment"] if args.exclude_tax_adjustments else []
        )
        print(f"Cost Type: Excluding {', '.join(exclude)}")
    print()

    # Query daily totals
    results = query_daily_totals(args.start, args.end, args.service, args.project, cost_type_clause, bq_project=args.bq_project)

    if not results:
        print("No cost data found for the specified period.")
        return

    # Print daily breakdown
    headers = ["Date", "Net Cost", "Gross Cost", "Credits", "Items"]
    alignments = ["l", "r", "r", "r", "r"]
    rows = []

    total_net = 0.0
    total_gross = 0.0
    total_credits = 0.0

    for r in results:
        net = float(r.get("net_cost", 0) or 0)
        gross = float(r.get("gross_cost", 0) or 0)
        credits = float(r.get("credits", 0) or 0)

        total_net += net
        total_gross += gross
        total_credits += credits

        rows.append([
            r.get("usage_date", ""),
            format_currency(net),
            format_currency(gross),
            format_currency(credits),
            str(r.get("line_items", 0)),
        ])

    print_table(headers, rows, alignments)

    # Print totals
    print()
    print(f"Period Totals:")
    print(f"  Net Cost:   {format_currency(total_net)}")
    print(f"  Gross Cost: {format_currency(total_gross)}")
    print(f"  Credits:    {format_currency(total_credits)}")
    print(f"  Avg/Day:    {format_currency(total_net / len(results) if results else 0)}")

    # Identify anomalies (days > 1.5x average)
    if results:
        avg = total_net / len(results)
        anomalies = [r for r in results if float(r.get("net_cost", 0) or 0) > avg * 1.5]
        if anomalies:
            print(f"\nHigh-Cost Days (>1.5x average of {format_currency(avg)}):")
            for a in anomalies:
                print(f"  {a.get('usage_date')}: {format_currency(a.get('net_cost'))}")

    # Detect billing lag / incomplete data
    # GCP billing exports have 24-48 hour lag, so recent days may have incomplete data
    if results:
        avg_items = sum(int(r.get("line_items", 0)) for r in results) / len(results)

        incomplete_days = []
        for r in results:
            net = float(r.get("net_cost", 0) or 0)
            items = int(r.get("line_items", 0))
            date_str = r.get("usage_date", "")

            # Flag days with < 10% of average items or < $1 cost (likely incomplete)
            if items < avg_items * 0.1 or (net < 1.0 and items < 1000):
                incomplete_days.append((date_str, net, items))

        if incomplete_days:
            print(f"\n⚠️  Billing Data Warning:")
            print(f"The following days appear to have incomplete data (billing export lag is 24-48 hours):")
            for date_str, net, items in incomplete_days:
                print(f"  {date_str}: {format_currency(net)} ({items} line items vs ~{int(avg_items)} avg)")
            print(f"Consider excluding these days from analysis or re-running after data is complete.")

    # Show service breakdown if requested
    if args.show_services:
        print(f"\n{'='*70}")
        print("Daily Breakdown by Service")
        print(f"{'='*70}\n")

        service_data = query_daily_by_service(args.start, args.end, args.project, cost_type_clause, bq_project=args.bq_project)

        # Group by date
        by_date: dict[str, list[tuple[str, float]]] = {}
        for r in service_data:
            date = r.get("usage_date", "")
            service = r.get("service", "")
            cost = float(r.get("net_cost", 0) or 0)
            if date not in by_date:
                by_date[date] = []
            by_date[date].append((service, cost))

        for date in sorted(by_date.keys()):
            services = by_date[date]
            print(f"{date}:")
            for service, cost in services[:5]:  # Top 5 services per day
                print(f"  {format_currency(cost):>10}  {service}")
            if len(services) > 5:
                print(f"  ... and {len(services) - 5} more services")
            print()


if __name__ == "__main__":
    sys.exit(main())
