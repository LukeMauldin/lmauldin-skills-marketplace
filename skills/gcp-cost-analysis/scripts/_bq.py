"""Shared utilities for BigQuery billing analysis.

This module provides common functionality for scripts that query GCP billing data,
including BigQuery command execution, date handling, and output formatting.

Important scope distinction:
- The billing export tables are hosted in the BigQuery dataset
  ``ksu-live.tech_billing_data``.
- Those tables contain cost rows for multiple GCP projects via ``project.id``.
- ``--bq-project`` selects which project runs the BigQuery job and has dataset
  access. It does not limit billed cost scope.
- Cost scope stays "all exported projects" unless a script adds a
  ``project.id = ...`` filter.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Billing export dataset is hosted in ksu-live, but contains rows for many
# billed GCP projects via project.id.
BILLING_DATASET_PROJECT = "ksu-live"
BILLING_TABLE_STANDARD = (
    "ksu-live.tech_billing_data.gcp_billing_export_v1_01F770_268BC9_B9A577"
)
BILLING_TABLE_RESOURCE = (
    "ksu-live.tech_billing_data.gcp_billing_export_resource_v1_01F770_268BC9_B9A577"
)

# Common billed projects present in the export.
EXPORTED_PROJECTS = ["ksu-live", "kidstrong-at-home", "kidstrong-infra", "kidstrongtv"]

# Backward-compatible constant name used by the scripts for the project that
# runs BigQuery queries.
DEFAULT_PROJECT = BILLING_DATASET_PROJECT


class BQError(Exception):
    """Error executing BigQuery command."""


@dataclass
class DateRange:
    """A date range for billing analysis."""

    start: date
    end: date
    label: str

    @property
    def start_str(self) -> str:
        return self.start.strftime("%Y-%m-%d")

    @property
    def end_str(self) -> str:
        return self.end.strftime("%Y-%m-%d")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def end_exclusive(self) -> date:
        return self.end + timedelta(days=1)

    @property
    def end_exclusive_str(self) -> str:
        return self.end_exclusive.strftime("%Y-%m-%d")

    def __str__(self) -> str:
        return f"{self.label}: {self.start_str} to {self.end_str} ({self.days} days)"


def parse_date(date_str: str) -> date:
    """Parse a date string in YYYY-MM-DD format."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def end_exclusive_str(date_str: str) -> str:
    """Return an exclusive end date (YYYY-MM-DD) for a given inclusive date."""
    return (parse_date(date_str) + timedelta(days=1)).strftime("%Y-%m-%d")


def validate_date_range(start: date, end: date, label: str) -> None:
    """Validate that start <= end."""
    if start > end:
        raise ValueError(f"{label} start date {start} is after end date {end}")


def date_range_from_args(
    target_start: str,
    target_end: str,
    reference_start: str | None = None,
    reference_end: str | None = None,
) -> tuple[DateRange, DateRange]:
    """Create target and reference date ranges from CLI arguments.

    Args:
        target_start: Target period start date (YYYY-MM-DD).
        target_end: Target period end date (YYYY-MM-DD).
        reference_start: Reference period start date (optional).
        reference_end: Reference period end date (optional).

    Returns:
        Tuple of (target_range, reference_range).
    """
    target = DateRange(
        start=parse_date(target_start),
        end=parse_date(target_end),
        label="target",
    )
    validate_date_range(target.start, target.end, "Target")

    if (reference_start and not reference_end) or (reference_end and not reference_start):
        raise ValueError("Reference start and end must be provided together.")

    if reference_start and reference_end:
        reference = DateRange(
            start=parse_date(reference_start),
            end=parse_date(reference_end),
            label="reference",
        )
    else:
        # Default: same duration period immediately before target
        duration = target.days
        ref_end = target.start - timedelta(days=1)
        ref_start = ref_end - timedelta(days=duration - 1)
        reference = DateRange(start=ref_start, end=ref_end, label="reference")

    validate_date_range(reference.start, reference.end, "Reference")

    return target, reference


def expand_reference_periods(reference: DateRange, count: int) -> list[DateRange]:
    """Generate additional reference periods before the provided reference range."""
    if count < 1:
        raise ValueError("baseline_periods must be >= 1")
    periods = [reference]
    for idx in range(1, count):
        prev_end = periods[-1].start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=reference.days - 1)
        periods.append(DateRange(start=prev_start, end=prev_end, label=f"reference_{idx + 1}"))
    return periods


def build_cost_type_clause(
    include_types: Sequence[str] | None,
    exclude_types: Sequence[str] | None,
    exclude_tax_adjustments: bool,
) -> str:
    """Build SQL clause for cost_type filtering."""
    include = list(include_types or [])
    exclude = list(exclude_types or [])

    if exclude_tax_adjustments:
        exclude.extend(["tax", "adjustment"])

    if include:
        quoted = ", ".join(f'"{t}"' for t in include)
        return f"AND cost_type IN ({quoted})"
    if exclude:
        quoted = ", ".join(f'"{t}"' for t in exclude)
        return f"AND cost_type NOT IN ({quoted})"
    return ""


def run_bq_query(query: str, *, project_id: str, format_type: str = "prettyjson") -> list[dict[str, Any]]:
    """Execute a BigQuery query and return results as parsed JSON.

    Args:
        query: SQL query to execute.
        project_id: GCP project to run the query in (required).
        format_type: Output format (prettyjson, json, csv).

    Returns:
        List of result rows as dicts.

    Raises:
        BQError: If bq command fails or project_id is not set.
    """
    if not project_id:
        raise BQError("project_id is required but was not set. Pass --bq-project or set a default.")

    cmd = [
        "bq",
        "query",
        "--use_legacy_sql=false",
        f"--project_id={project_id}",
        f"--format={format_type}",
        query,
    ]
    logger.debug("Running: bq query --project_id=%s --use_legacy_sql=false ...", project_id)
    logger.debug("Query:\n%s", query)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        error_detail = result.stderr.strip() or result.stdout.strip()
        raise BQError(f"BigQuery error: {error_detail}")

    if not result.stdout.strip():
        return []

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise BQError(f"Failed to parse BigQuery output: {e}") from e


def describe_project_scope(project_filter: str | None) -> str:
    """Return a human-readable description of billed project scope."""
    if project_filter:
        return project_filter
    return "all exported projects in billing dataset"


def configure_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level.

    Args:
        verbosity: Number of -v flags (0=WARNING, 1=INFO, 2=DEBUG).
    """
    level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(levelname)s: %(message)s",
    )


def format_currency(value: float | str | None) -> str:
    """Format a value as currency."""
    if value is None:
        return "$0.00"
    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


def format_delta(value: float | str | None, show_sign: bool = True) -> str:
    """Format a delta value with sign."""
    if value is None:
        return "$0.00"
    try:
        v = float(value)
        if show_sign and v > 0:
            return f"+${v:,.2f}"
        elif show_sign and v < 0:
            return f"-${abs(v):,.2f}"
        else:
            return f"${v:,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


def format_percent(value: float | str | None) -> str:
    """Format a value as percentage."""
    if value is None:
        return "0.0%"
    try:
        return f"{float(value):.1f}%"
    except (ValueError, TypeError):
        return "0.0%"


def print_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    alignments: Sequence[str] | None = None,
) -> None:
    """Print a formatted table.

    Args:
        headers: Column headers.
        rows: Table rows.
        alignments: Column alignments ('l', 'r', 'c'). Defaults to left.
    """
    if not rows:
        print("No data.")
        return

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))

    if alignments is None:
        alignments = ["l"] * len(headers)

    def format_cell(value: str, width: int, align: str) -> str:
        if align == "r":
            return str(value).rjust(width)
        elif align == "c":
            return str(value).center(width)
        else:
            return str(value).ljust(width)

    # Print header
    header_line = "  ".join(
        format_cell(h, widths[i], alignments[i]) for i, h in enumerate(headers)
    )
    print(header_line)
    print("  ".join("-" * w for w in widths))

    # Print rows
    for row in rows:
        row_line = "  ".join(
            format_cell(str(row[i]) if i < len(row) else "", widths[i], alignments[i])
            for i in range(len(headers))
        )
        print(row_line)
