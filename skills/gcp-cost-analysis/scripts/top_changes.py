#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Identify top cost drivers between target and reference periods.

Analyzes resource-level billing data to find the specific resources
contributing most to cost changes.

Usage:
    uv run top_changes.py --target-start 2026-01-05 --target-end 2026-01-11
    uv run top_changes.py --target-start 2026-01-05 --target-end 2026-01-11 \\
        --service "Cloud Run" --limit 30
"""
from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from _bq import (
    BILLING_TABLE_RESOURCE,
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

    # Reference period (optional)
    parser.add_argument("--reference-start", "-rs",
                        help="Reference period start date (YYYY-MM-DD)")
    parser.add_argument("--reference-end", "-re",
                        help="Reference period end date (YYYY-MM-DD)")

    # Filters
    parser.add_argument("--service", "-s", help="Filter by service name")
    parser.add_argument("--project", "-p",
                        help="Filter billed costs to a specific project.id in the export")
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
    parser.add_argument("--min-delta", type=float, default=0.50,
                        help="Minimum absolute delta to show (default: $0.50)")
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


def compute_change_rows(
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
        ref_usage_total = float(r.get("reference_usage_total", 0) or 0)
        target_gross = float(r.get("target_gross", 0) or 0)
        target_credits = float(r.get("target_credits", 0) or 0)
        target_usage = float(r.get("target_usage", 0) or 0)

        ref_gross = ref_gross_total / baseline_periods
        ref_credits = ref_credits_total / baseline_periods
        ref_usage = ref_usage_total / baseline_periods
        ref_net = ref_gross + ref_credits
        tgt_net = target_gross + target_credits

        if normalize_per_day:
            ref_gross /= reference_days
            ref_credits /= reference_days
            ref_usage /= reference_days
            ref_net /= reference_days
            target_gross /= target_days
            target_credits /= target_days
            target_usage /= target_days
            tgt_net /= target_days

        if abs(ref_net) < 0.01 and abs(tgt_net) < 0.01:
            continue

        delta = tgt_net - ref_net
        pct_change = (delta / ref_net * 100) if ref_net > 0 else None

        computed.append({
            **r,
            "reference_gross": ref_gross,
            "reference_credits": ref_credits,
            "reference_usage": ref_usage,
            "reference_net": ref_net,
            "target_gross": target_gross,
            "target_credits": target_credits,
            "target_usage": target_usage,
            "target_net": tgt_net,
            "delta": delta,
            "pct_change": pct_change,
            "credits_delta": target_credits - ref_credits,
        })

    return computed


def query_resource_changes(
    target: DateRange,
    reference_periods: list[DateRange],
    service: str | None,
    project: str | None,
    limit: int,
    cost_type_clause: str,
    *,
    bq_project: str,
) -> list[dict]:
    """Query resource-level cost changes."""
    period_case = build_period_case(reference_periods, target)
    start_date = overall_start(reference_periods)
    where_clauses = [
        f'usage_start_time >= TIMESTAMP("{start_date}")',
        f'usage_start_time < TIMESTAMP("{target.end_exclusive_str}")',
    ]
    if service:
        where_clauses.append(f'service.description = "{service}"')
    if project:
        where_clauses.append(f'project.id = "{project}"')
    where = " AND ".join(where_clauses)
    if cost_type_clause:
        where = f"{where} {cost_type_clause}"

    query = f"""
WITH period_costs AS (
  SELECT
    project.id AS project_id,
    service.description AS service,
    sku.description AS sku,
    resource.name AS resource_name,
    {period_case},
    SUM(cost) AS gross_cost,
    SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits,
    SUM(usage.amount) AS usage_amount,
    usage.unit AS usage_unit
  FROM `{BILLING_TABLE_RESOURCE}`
  WHERE {where}
  GROUP BY project_id, service, sku, resource_name, period, usage_unit
  HAVING period IS NOT NULL
),
pivoted AS (
  SELECT
    project_id,
    service,
    sku,
    resource_name,
    usage_unit,
    SUM(CASE WHEN period LIKE "reference_%" THEN gross_cost ELSE 0 END) AS reference_gross_total,
    SUM(CASE WHEN period LIKE "reference_%" THEN credits ELSE 0 END) AS reference_credits_total,
    SUM(CASE WHEN period LIKE "reference_%" THEN usage_amount ELSE 0 END) AS reference_usage_total,
    SUM(CASE WHEN period = "target" THEN gross_cost ELSE 0 END) AS target_gross,
    SUM(CASE WHEN period = "target" THEN credits ELSE 0 END) AS target_credits,
    SUM(CASE WHEN period = "target" THEN usage_amount ELSE 0 END) AS target_usage
  FROM period_costs
  GROUP BY project_id, service, sku, resource_name, usage_unit
)
SELECT
  project_id,
  service,
  sku,
  resource_name,
  usage_unit,
  reference_gross_total,
  reference_credits_total,
  reference_usage_total,
  target_gross,
  target_credits,
  target_usage
FROM pivoted
WHERE ABS((target_gross + target_credits) - (reference_gross_total + reference_credits_total)) > 0.01
ORDER BY (target_gross + target_credits) - (reference_gross_total + reference_credits_total) DESC
LIMIT {limit * 2}
"""
    return run_bq_query(query, project_id=bq_project)


def query_sku_changes(
    target: DateRange,
    reference_periods: list[DateRange],
    service: str | None,
    project: str | None,
    limit: int,
    cost_type_clause: str,
    *,
    bq_project: str,
) -> list[dict]:
    """Query SKU-level cost changes (fallback if resource table unavailable)."""
    period_case = build_period_case(reference_periods, target)
    start_date = overall_start(reference_periods)
    where_clauses = [
        f'usage_start_time >= TIMESTAMP("{start_date}")',
        f'usage_start_time < TIMESTAMP("{target.end_exclusive_str}")',
    ]
    if service:
        where_clauses.append(f'service.description = "{service}"')
    if project:
        where_clauses.append(f'project.id = "{project}"')
    where = " AND ".join(where_clauses)
    if cost_type_clause:
        where = f"{where} {cost_type_clause}"

    query = f"""
WITH period_costs AS (
  SELECT
    project.id AS project_id,
    service.description AS service,
    sku.description AS sku,
    {period_case},
    SUM(cost) AS gross_cost,
    SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits,
    SUM(usage.amount) AS usage_amount,
    usage.unit AS usage_unit
  FROM `{BILLING_TABLE_STANDARD}`
  WHERE {where}
  GROUP BY project_id, service, sku, period, usage_unit
  HAVING period IS NOT NULL
),
pivoted AS (
  SELECT
    project_id,
    service,
    sku,
    usage_unit,
    SUM(CASE WHEN period LIKE "reference_%" THEN gross_cost ELSE 0 END) AS reference_gross_total,
    SUM(CASE WHEN period LIKE "reference_%" THEN credits ELSE 0 END) AS reference_credits_total,
    SUM(CASE WHEN period LIKE "reference_%" THEN usage_amount ELSE 0 END) AS reference_usage_total,
    SUM(CASE WHEN period = "target" THEN gross_cost ELSE 0 END) AS target_gross,
    SUM(CASE WHEN period = "target" THEN credits ELSE 0 END) AS target_credits,
    SUM(CASE WHEN period = "target" THEN usage_amount ELSE 0 END) AS target_usage
  FROM period_costs
  GROUP BY project_id, service, sku, usage_unit
)
SELECT
  project_id,
  service,
  sku,
  usage_unit,
  reference_gross_total,
  reference_credits_total,
  reference_usage_total,
  target_gross,
  target_credits,
  target_usage
FROM pivoted
WHERE ABS((target_gross + target_credits) - (reference_gross_total + reference_credits_total)) > 0.01
ORDER BY (target_gross + target_credits) - (reference_gross_total + reference_credits_total) DESC
LIMIT {limit}
"""
    return run_bq_query(query, project_id=bq_project)


def run(target: DateRange, reference: DateRange, args: argparse.Namespace) -> None:
    """Execute the top changes analysis."""
    if args.baseline_periods < 1:
        raise ValueError("--baseline-periods must be >= 1")

    reference_periods = expand_reference_periods(reference, args.baseline_periods)
    cost_type_clause = build_cost_type_clause(
        args.cost_types,
        args.exclude_cost_types,
        args.exclude_tax_adjustments,
    )

    print(f"\n{'='*80}")
    print("Top Cost Drivers (Resource-Level Analysis)")
    print(f"{'='*80}")
    print(f"Target:    {target}")
    if args.baseline_periods > 1:
        print(f"Reference: {reference} (avg of {args.baseline_periods} periods)")
    else:
        print(f"Reference: {reference}")
    if args.service:
        print(f"Service:   {args.service}")
    print(f"Scope:     {describe_project_scope(args.project)}")
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
    print()

    # Try resource-level query first
    try:
        results = query_resource_changes(
            target,
            reference_periods,
            args.service,
            args.project,
            args.limit,
            cost_type_clause,
            bq_project=args.bq_project,
        )
    except BQError:
        print("Note: Resource-level billing not available, using SKU-level analysis.")
        results = query_sku_changes(
            target,
            reference_periods,
            args.service,
            args.project,
            args.limit,
            cost_type_clause,
            bq_project=args.bq_project,
        )

    if not results:
        print("No significant cost changes found.")
        return

    computed = compute_change_rows(
        results,
        baseline_periods=args.baseline_periods,
        reference_days=reference.days,
        target_days=target.days,
        normalize_per_day=args.normalize_per_day,
    )

    # Filter by minimum delta
    results = [r for r in computed if abs(float(r.get("delta", 0) or 0)) >= args.min_delta]

    if not results:
        print(f"No cost changes above {format_currency(args.min_delta)} detected.")
        return

    # Split into increases and decreases
    increases = sorted(
        [r for r in results if float(r.get("delta", 0) or 0) > 0],
        key=lambda r: r["delta"],
        reverse=True,
    )[:args.limit]
    decreases = sorted(
        [r for r in results if float(r.get("delta", 0) or 0) < 0],
        key=lambda r: r["delta"],
    )

    # Print increases
    if increases:
        print("COST INCREASES")
        print("-" * 80)

        for r in increases:
            resource = r.get("resource_name", "") or "(aggregate)"
            if len(resource) > 50:
                resource = "..." + resource[-47:]

            print(f"\n{r.get('service', '')} / {r.get('sku', '')}")
            print(f"  Project:   {r.get('project_id', '')}")
            if resource != "(aggregate)":
                print(f"  Resource:  {resource}")
            print(f"  Reference: {format_currency(r.get('reference_net'))}")
            print(f"  Target:    {format_currency(r.get('target_net'))}")
            print(f"  Delta:     {format_delta(r.get('delta'))}", end="")
            if r.get("pct_change"):
                print(f" ({format_percent(r.get('pct_change'))})")
            else:
                print(" (new)")

            if abs(float(r.get("credits_delta", 0) or 0)) >= 0.01:
                print(f"  Credits Δ: {format_delta(r.get('credits_delta'))}")

            # Show usage change if available
            ref_usage = float(r.get("reference_usage", 0) or 0)
            tgt_usage = float(r.get("target_usage", 0) or 0)
            if ref_usage > 0 or tgt_usage > 0:
                unit = r.get("usage_unit", "")
                usage_delta = tgt_usage - ref_usage
                print(f"  Usage:     {ref_usage:,.2f} -> {tgt_usage:,.2f} {unit} ({usage_delta:+,.2f})")

    # Print summary of decreases
    if decreases:
        total_decrease = sum(float(r.get("delta", 0) or 0) for r in decreases)
        print(f"\n{'='*80}")
        print(f"COST DECREASES SUMMARY")
        print(f"-" * 80)
        print(f"  {len(decreases)} items with combined savings of {format_currency(abs(total_decrease))}")

        # Show top 3 decreases
        top_decreases = sorted(decreases, key=lambda x: float(x.get("delta", 0) or 0))[:3]
        for r in top_decreases:
            print(f"  {format_delta(r.get('delta')):>10}  {r.get('service', '')} / {r.get('sku', '')[:40]}")

    # Final summary
    total_increase = sum(float(r.get("delta", 0) or 0) for r in increases)
    total_decrease = sum(float(r.get("delta", 0) or 0) for r in decreases)

    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"  Total Increases: {format_delta(total_increase)}")
    print(f"  Total Decreases: {format_delta(total_decrease)}")
    print(f"  Net Change:      {format_delta(total_increase + total_decrease)}")


if __name__ == "__main__":
    sys.exit(main())
