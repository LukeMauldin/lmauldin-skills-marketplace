#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Compare GCP costs between target and reference periods by service and SKU.

Identifies top cost changes between two time periods to pinpoint spending anomalies.

Usage:
    uv run cost_breakdown.py --target-start 2026-01-05 --target-end 2026-01-11
    uv run cost_breakdown.py --target-start 2026-01-05 --target-end 2026-01-11 \\
        --reference-start 2025-12-22 --reference-end 2025-12-28
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
    date_range_from_args,
    describe_project_scope,
    expand_reference_periods,
    format_currency,
    format_delta,
    format_percent,
    print_table,
    run_bq_query,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from _bq import DateRange


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    args = parse_args(argv)
    configure_logging(args.verbose)

    try:
        target, reference = date_range_from_args(
            args.target_start,
            args.target_end,
            args.reference_start,
            args.reference_end,
        )
        run(target, reference, args)
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

    # Target period (required)
    parser.add_argument("--target-start", "-ts", required=True,
                        help="Target period start date (YYYY-MM-DD)")
    parser.add_argument("--target-end", "-te", required=True,
                        help="Target period end date (YYYY-MM-DD)")

    # Reference period (optional - defaults to period before target)
    parser.add_argument("--reference-start", "-rs",
                        help="Reference period start date (YYYY-MM-DD)")
    parser.add_argument("--reference-end", "-re",
                        help="Reference period end date (YYYY-MM-DD)")

    # Output options
    parser.add_argument("--by", choices=["service", "sku", "project"],
                        default="service", help="Group by dimension (default: service)")
    parser.add_argument("--limit", "-l", type=int, default=20,
                        help="Max rows to show (default: 20)")
    parser.add_argument("--baseline-periods", type=int, default=1,
                        help="Number of prior periods to average for reference (default: 1)")
    parser.add_argument("--normalize-per-day", action="store_true",
                        help="Normalize costs by days in period")
    parser.add_argument("--cost-type", action="append", dest="cost_types",
                        help="Include only specific cost_type (repeatable)")
    parser.add_argument("--exclude-cost-type", action="append", dest="exclude_cost_types",
                        help="Exclude specific cost_type (repeatable)")
    parser.add_argument("--exclude-tax-adjustments", action="store_true",
                        help="Exclude tax and adjustment cost types")
    parser.add_argument("--show-decreases", action="store_true",
                        help="Show cost decreases as well as increases")
    parser.add_argument("--increases-only", action="store_true",
                        help="Show only cost increases (overrides default for --by project)")
    parser.add_argument("--project-filter", "-p",
                        help="Filter billed costs to a specific project.id in the export")
    parser.add_argument("--bq-project", default=DEFAULT_PROJECT,
                        help=(
                            "GCP project that runs the BigQuery query and hosts the billing "
                            f"dataset access (default: {DEFAULT_PROJECT}); not a cost filter"
                        ))

    return parser.parse_args(argv)


def build_period_case(reference_periods: list[DateRange], target: DateRange) -> str:
    """Build SQL CASE statement for period labeling."""
    cases = []
    for idx, period in enumerate(reference_periods, start=1):
        cases.append(
            f'WHEN usage_start_time >= TIMESTAMP("{period.start_str}") '
            f'AND usage_start_time < TIMESTAMP("{period.end_exclusive_str}") '
            f'THEN "reference_{idx}"'
        )
    cases.append(
        f'WHEN usage_start_time >= TIMESTAMP("{target.start_str}") '
        f'AND usage_start_time < TIMESTAMP("{target.end_exclusive_str}") '
        f'THEN "target"'
    )
    return "CASE " + " ".join(cases) + " END AS period"


def overall_start(reference_periods: list[DateRange]) -> str:
    """Get the earliest start date across reference periods."""
    return min(p.start for p in reference_periods).strftime("%Y-%m-%d")


def compute_metrics(
    rows: list[dict],
    baseline_periods: int,
    reference_days: int,
    target_days: int,
    normalize_per_day: bool,
) -> list[dict]:
    """Compute net costs, deltas, and percentages from raw query rows."""
    computed = []
    for r in rows:
        ref_gross_total = float(r.get("reference_gross_total", 0) or 0)
        ref_credits_total = float(r.get("reference_credits_total", 0) or 0)
        target_gross = float(r.get("target_gross", 0) or 0)
        target_credits = float(r.get("target_credits", 0) or 0)

        ref_gross = ref_gross_total / baseline_periods
        ref_credits = ref_credits_total / baseline_periods
        ref_net = ref_gross + ref_credits
        tgt_net = target_gross + target_credits

        if normalize_per_day:
            ref_gross /= reference_days
            ref_credits /= reference_days
            ref_net /= reference_days
            target_gross /= target_days
            target_credits /= target_days
            tgt_net /= target_days

        if abs(ref_net) < 0.01 and abs(tgt_net) < 0.01:
            continue

        delta = tgt_net - ref_net
        pct_change = (delta / ref_net * 100) if ref_net > 0 else None

        computed.append({
            **r,
            "reference_gross": ref_gross,
            "reference_credits": ref_credits,
            "reference_net": ref_net,
            "target_gross": target_gross,
            "target_credits": target_credits,
            "target_net": tgt_net,
            "delta": delta,
            "pct_change": pct_change,
            "credits_delta": target_credits - ref_credits,
        })

    return computed


def query_by_service(
    target: DateRange,
    reference_periods: list[DateRange],
    project_filter: str | None,
    cost_type_clause: str,
    *,
    bq_project: str,
) -> list[dict]:
    """Query costs grouped by service."""
    project_clause = f'AND project.id = "{project_filter}"' if project_filter else ""
    period_case = build_period_case(reference_periods, target)
    start_date = overall_start(reference_periods)

    query = f"""
WITH period_costs AS (
  SELECT
    service.description AS dimension,
    {period_case},
    SUM(cost) AS gross_cost,
    SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits
  FROM `{BILLING_TABLE_STANDARD}`
  WHERE usage_start_time >= TIMESTAMP("{start_date}")
    AND usage_start_time < TIMESTAMP("{target.end_exclusive_str}")
    {project_clause}
    {cost_type_clause}
  GROUP BY dimension, period
  HAVING period IS NOT NULL
),
pivoted AS (
  SELECT
    dimension,
    SUM(CASE WHEN period LIKE "reference_%" THEN gross_cost ELSE 0 END) AS reference_gross_total,
    SUM(CASE WHEN period LIKE "reference_%" THEN credits ELSE 0 END) AS reference_credits_total,
    SUM(CASE WHEN period = "target" THEN gross_cost ELSE 0 END) AS target_gross,
    SUM(CASE WHEN period = "target" THEN credits ELSE 0 END) AS target_credits
  FROM period_costs
  GROUP BY dimension
)
SELECT
  dimension,
  reference_gross_total,
  reference_credits_total,
  target_gross,
  target_credits
FROM pivoted
"""
    return run_bq_query(query, project_id=bq_project)


def query_by_sku(
    target: DateRange,
    reference_periods: list[DateRange],
    project_filter: str | None,
    cost_type_clause: str,
    *,
    bq_project: str,
) -> list[dict]:
    """Query costs grouped by service and SKU."""
    project_clause = f'AND project.id = "{project_filter}"' if project_filter else ""
    period_case = build_period_case(reference_periods, target)
    start_date = overall_start(reference_periods)

    query = f"""
WITH period_costs AS (
  SELECT
    service.description AS service,
    sku.description AS sku,
    {period_case},
    SUM(cost) AS gross_cost,
    SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits
  FROM `{BILLING_TABLE_STANDARD}`
  WHERE usage_start_time >= TIMESTAMP("{start_date}")
    AND usage_start_time < TIMESTAMP("{target.end_exclusive_str}")
    {project_clause}
    {cost_type_clause}
  GROUP BY service, sku, period
  HAVING period IS NOT NULL
),
pivoted AS (
  SELECT
    service,
    sku,
    SUM(CASE WHEN period LIKE "reference_%" THEN gross_cost ELSE 0 END) AS reference_gross_total,
    SUM(CASE WHEN period LIKE "reference_%" THEN credits ELSE 0 END) AS reference_credits_total,
    SUM(CASE WHEN period = "target" THEN gross_cost ELSE 0 END) AS target_gross,
    SUM(CASE WHEN period = "target" THEN credits ELSE 0 END) AS target_credits
  FROM period_costs
  GROUP BY service, sku
)
SELECT
  service,
  sku,
  reference_gross_total,
  reference_credits_total,
  target_gross,
  target_credits
FROM pivoted
"""
    return run_bq_query(query, project_id=bq_project)


def query_by_project(
    target: DateRange,
    reference_periods: list[DateRange],
    project_filter: str | None,
    cost_type_clause: str,
    *,
    bq_project: str,
) -> list[dict]:
    """Query costs grouped by project."""
    project_clause = f'AND project.id = "{project_filter}"' if project_filter else ""
    period_case = build_period_case(reference_periods, target)
    start_date = overall_start(reference_periods)

    query = f"""
WITH period_costs AS (
  SELECT
    IFNULL(project.id, "(unassigned)") AS dimension,
    {period_case},
    SUM(cost) AS gross_cost,
    SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits
  FROM `{BILLING_TABLE_STANDARD}`
  WHERE usage_start_time >= TIMESTAMP("{start_date}")
    AND usage_start_time < TIMESTAMP("{target.end_exclusive_str}")
    {project_clause}
    {cost_type_clause}
  GROUP BY dimension, period
  HAVING period IS NOT NULL
),
pivoted AS (
  SELECT
    dimension,
    SUM(CASE WHEN period LIKE "reference_%" THEN gross_cost ELSE 0 END) AS reference_gross_total,
    SUM(CASE WHEN period LIKE "reference_%" THEN credits ELSE 0 END) AS reference_credits_total,
    SUM(CASE WHEN period = "target" THEN gross_cost ELSE 0 END) AS target_gross,
    SUM(CASE WHEN period = "target" THEN credits ELSE 0 END) AS target_credits
  FROM period_costs
  GROUP BY dimension
)
SELECT
  dimension,
  reference_gross_total,
  reference_credits_total,
  target_gross,
  target_credits
FROM pivoted
"""
    return run_bq_query(query, project_id=bq_project)


def run(target: DateRange, reference: DateRange, args: argparse.Namespace) -> None:
    """Execute the cost breakdown analysis."""
    if args.baseline_periods < 1:
        raise ValueError("--baseline-periods must be >= 1")

    reference_periods = expand_reference_periods(reference, args.baseline_periods)
    cost_type_clause = build_cost_type_clause(
        args.cost_types,
        args.exclude_cost_types,
        args.exclude_tax_adjustments,
    )

    # Determine whether to show decreases:
    # - For --by project, default to showing all changes (decreases are common)
    # - For service/sku, default to increases only
    # - --show-decreases or --increases-only can override these defaults
    if args.increases_only:
        show_decreases = False
    elif args.show_decreases:
        show_decreases = True
    else:
        # Default: project shows all, service/sku shows increases only
        show_decreases = (args.by == "project")

    print(f"\n{'='*70}")
    print(f"GCP Cost Breakdown: {args.by.upper()}")
    print(f"{'='*70}")
    print(f"Target:    {target}")
    if args.baseline_periods > 1:
        print(f"Reference: {reference} (avg of {args.baseline_periods} periods)")
    else:
        print(f"Reference: {reference}")
    print(f"Scope:     {describe_project_scope(args.project_filter)}")
    print(f"BQ Host:   {args.bq_project}")
    if args.normalize_per_day:
        print("Mode:      Per-day normalization enabled")
    if args.cost_types:
        print(f"Cost Type: Include only {', '.join(args.cost_types)}")
    elif args.exclude_cost_types or args.exclude_tax_adjustments:
        exclude = (args.exclude_cost_types or []) + (
            ["tax", "adjustment"] if args.exclude_tax_adjustments else []
        )
        print(f"Cost Type: Excluding {', '.join(exclude)}")
    if not show_decreases:
        print(f"Filter:    Showing cost increases only (use --show-decreases for all)")
    print()

    # Query based on grouping
    if args.by == "service":
        results = query_by_service(target, reference_periods, args.project_filter, cost_type_clause, bq_project=args.bq_project)
    elif args.by == "sku":
        results = query_by_sku(target, reference_periods, args.project_filter, cost_type_clause, bq_project=args.bq_project)
    else:
        results = query_by_project(target, reference_periods, args.project_filter, cost_type_clause, bq_project=args.bq_project)

    if not results:
        print("No cost data found for the specified periods.")
        return

    computed = compute_metrics(
        results,
        baseline_periods=args.baseline_periods,
        reference_days=reference.days,
        target_days=target.days,
        normalize_per_day=args.normalize_per_day,
    )
    if not computed:
        print("No cost data found for the specified periods.")
        return

    computed.sort(key=lambda r: r["delta"], reverse=True)

    # Store original count for messaging
    total_results = len(computed)

    # Filter results based on delta direction
    if not show_decreases:
        computed = [r for r in computed if float(r.get("delta", 0) or 0) >= 0]
        if not computed and total_results > 0:
            print(f"All {total_results} items showed cost decreases.")
            print("Use --show-decreases to see all changes.")
            return

    results = computed[:args.limit]

    # Calculate totals
    total_ref_gross = sum(float(r.get("reference_gross", 0) or 0) for r in results)
    total_ref_credits = sum(float(r.get("reference_credits", 0) or 0) for r in results)
    total_ref_net = sum(float(r.get("reference_net", 0) or 0) for r in results)
    total_target_gross = sum(float(r.get("target_gross", 0) or 0) for r in results)
    total_target_credits = sum(float(r.get("target_credits", 0) or 0) for r in results)
    total_target_net = sum(float(r.get("target_net", 0) or 0) for r in results)
    total_delta = total_target_net - total_ref_net

    # Format and print table
    if args.by == "sku":
        headers = ["Service", "SKU", "Ref Net", "Target Net", "Delta", "% Change", "Credits Δ"]
        alignments = ["l", "l", "r", "r", "r", "r", "r"]
        rows = []
        for r in results:
            rows.append([
                r.get("service", "")[:25],
                r.get("sku", "")[:35],
                format_currency(r.get("reference_net")),
                format_currency(r.get("target_net")),
                format_delta(r.get("delta")),
                format_percent(r.get("pct_change")) if r.get("pct_change") is not None else "N/A",
                format_delta(r.get("credits_delta")),
            ])
    else:
        headers = ["Dimension", "Ref Net", "Target Net", "Delta", "% Change", "Credits Δ"]
        alignments = ["l", "r", "r", "r", "r", "r"]
        rows = []
        for r in results:
            rows.append([
                r.get("dimension", "")[:40],
                format_currency(r.get("reference_net")),
                format_currency(r.get("target_net")),
                format_delta(r.get("delta")),
                format_percent(r.get("pct_change")) if r.get("pct_change") is not None else "N/A",
                format_delta(r.get("credits_delta")),
            ])

    print_table(headers, rows, alignments)

    # Print summary
    print()
    print(f"{'='*70}")
    print(f"Summary (shown rows only):")
    print(f"  Reference Gross: {format_currency(total_ref_gross)}")
    print(f"  Reference Credits: {format_currency(total_ref_credits)}")
    print(f"  Reference Net:   {format_currency(total_ref_net)}")
    print(f"  Target Gross:    {format_currency(total_target_gross)}")
    print(f"  Target Credits:  {format_currency(total_target_credits)}")
    print(f"  Target Net:      {format_currency(total_target_net)}")
    print(f"  Net Change:      {format_delta(total_delta)}")
    if total_ref_net > 0:
        pct = (total_delta / total_ref_net) * 100
        print(f"  % Change:        {format_percent(pct)}")


if __name__ == "__main__":
    sys.exit(main())
