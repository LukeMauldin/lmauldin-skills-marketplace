#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""List Cloud Run service and job revisions deployed during a time period.

Helps correlate cost changes with deployment activity.

Usage:
    uv run cloud_run_revisions.py --start 2026-01-01 --end 2026-01-11
    uv run cloud_run_revisions.py --start 2026-01-01 --end 2026-01-11 --project ksu-live
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

DEFAULT_PROJECT = "ksu-live"
DEFAULT_REGION = "us-central1"
PROJECTS = ["ksu-live", "kidstrong-at-home", "kidstrong-infra"]


class GcloudError(Exception):
    """Error executing gcloud command."""


@dataclass
class Revision:
    """A Cloud Run revision."""

    name: str
    service: str
    creation_time: datetime
    project: str
    region: str
    config: dict[str, str | None]

    @property
    def creation_str(self) -> str:
        return self.creation_time.strftime("%Y-%m-%d %H:%M:%S")


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
    )
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v, -vv)")
    parser.add_argument("--start", "-s", required=True,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", "-e", required=True,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--project", "-p", default=DEFAULT_PROJECT,
                        choices=PROJECTS, help=f"GCP project (default: {DEFAULT_PROJECT})")
    parser.add_argument("--region", "-r", default=DEFAULT_REGION,
                        help=f"GCP region (default: {DEFAULT_REGION})")
    parser.add_argument("--all-projects", action="store_true",
                        help="Query all known projects")
    parser.add_argument("--limit", "-l", type=int, default=50,
                        help="Max revisions to show (default: 50)")
    parser.add_argument("--skip-job-executions", action="store_true",
                        help="Skip job execution counts (faster)")
    parser.add_argument("--skip-config-diff", action="store_true",
                        help="Skip config change summary")
    parser.add_argument("--job-execution-limit", type=int, default=20,
                        help="Max jobs to show in execution summary (default: 20)")

    return parser.parse_args(argv)


def configure_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level."""
    level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(levelname)s: %(message)s",
    )


def run_gcloud(cmd: list[str]) -> str:
    """Execute gcloud command and return stdout."""
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise GcloudError(f"gcloud error: {result.stderr.strip()}")
    return result.stdout


# Track permission errors for summary at end (avoid cluttering main output)
_permission_errors: list[tuple[str, str, str]] = []  # (project, resource_type, error_msg)


def list_revisions(project: str, region: str, limit: int) -> list[dict[str, Any]]:
    """List Cloud Run revisions for a project."""
    cmd = [
        "gcloud", "run", "revisions", "list",
        f"--project={project}",
        f"--region={region}",
        f"--limit={limit}",
        "--sort-by=~metadata.creationTimestamp",
        "--format=json",
    ]
    try:
        output = run_gcloud(cmd)
        if not output.strip():
            return []
        return json.loads(output)
    except GcloudError as e:
        error_str = str(e)
        if "Permission" in error_str or "denied" in error_str.lower():
            _permission_errors.append((project, "revisions", error_str))
            logger.debug("Permission denied listing revisions for %s", project)
        else:
            logger.warning("Failed to list revisions for %s: %s", project, e)
        return []


def list_jobs(project: str, region: str) -> list[dict[str, Any]]:
    """List Cloud Run jobs for a project."""
    cmd = [
        "gcloud", "run", "jobs", "list",
        f"--project={project}",
        f"--region={region}",
        "--format=json",
    ]
    try:
        output = run_gcloud(cmd)
        if not output.strip():
            return []
        return json.loads(output)
    except GcloudError as e:
        error_str = str(e)
        if "Permission" in error_str or "denied" in error_str.lower():
            _permission_errors.append((project, "jobs", error_str))
            logger.debug("Permission denied listing jobs for %s", project)
        else:
            logger.warning("Failed to list jobs for %s: %s", project, e)
        return []


def list_job_executions(project: str, region: str, job: str) -> list[dict[str, Any]]:
    """List Cloud Run job executions for a job."""
    cmd = [
        "gcloud", "run", "jobs", "executions", "list",
        f"--project={project}",
        f"--region={region}",
        f"--job={job}",
        "--format=json",
    ]
    try:
        output = run_gcloud(cmd)
        if not output.strip():
            return []
        return json.loads(output)
    except GcloudError as e:
        error_str = str(e)
        if "Permission" in error_str or "denied" in error_str.lower():
            _permission_errors.append((project, "job executions", error_str))
            logger.debug("Permission denied listing executions for %s/%s", project, job)
        else:
            logger.warning("Failed to list executions for %s/%s: %s", project, job, e)
        return []


def parse_timestamp(timestamp: str) -> datetime | None:
    """Parse an ISO timestamp string into a datetime."""
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def date_bounds(start: str, end: str, tzinfo_value: tzinfo | None) -> tuple[datetime, datetime]:
    """Build inclusive datetime bounds for a date range."""
    tz = tzinfo_value or timezone.utc
    start_dt = datetime.strptime(start, "%Y-%m-%d").replace(
        hour=0, minute=0, second=0, tzinfo=tz
    )
    end_dt = datetime.strptime(end, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=tz
    )
    return start_dt, end_dt


def extract_config(data: dict[str, Any]) -> dict[str, str | None]:
    """Extract cost-relevant config from a revision."""
    metadata = data.get("metadata", {})
    annotations = metadata.get("annotations", {}) or {}
    spec = data.get("spec", {}) or {}
    container = (spec.get("containers") or [{}])[0]
    resources = container.get("resources", {}) or {}
    limits = resources.get("limits", {}) or {}

    def to_str(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    return {
        "cpu": to_str(limits.get("cpu")),
        "memory": to_str(limits.get("memory")),
        "concurrency": to_str(spec.get("containerConcurrency")),
        "minScale": annotations.get("autoscaling.knative.dev/minScale"),
        "maxScale": annotations.get("autoscaling.knative.dev/maxScale"),
    }


def compare_configs(
    previous: dict[str, str | None],
    current: dict[str, str | None],
) -> list[tuple[str, str | None, str | None]]:
    """Compare two config maps and return changed keys."""
    changes = []
    for key in sorted(set(previous.keys()) | set(current.keys())):
        if previous.get(key) != current.get(key):
            changes.append((key, previous.get(key), current.get(key)))
    return changes


def parse_revision(data: dict[str, Any], project: str, region: str) -> Revision | None:
    """Parse revision data into Revision object."""
    try:
        metadata = data.get("metadata", {})
        name = metadata.get("name", "")
        labels = metadata.get("labels", {})
        service = labels.get("serving.knative.dev/service", name.rsplit("-", 2)[0] if name else "")

        creation_str = metadata.get("creationTimestamp", "")
        if creation_str:
            # Parse ISO format timestamp
            creation_time = datetime.fromisoformat(creation_str.replace("Z", "+00:00"))
        else:
            return None

        return Revision(
            name=name,
            service=service,
            creation_time=creation_time,
            project=project,
            region=region,
            config=extract_config(data),
        )
    except (KeyError, ValueError) as e:
        logger.debug("Failed to parse revision: %s", e)
        return None


def filter_by_date_range(
    revisions: list[Revision],
    start_dt: datetime,
    end_dt: datetime,
) -> list[Revision]:
    """Filter revisions to those created within date range."""
    return [r for r in revisions if start_dt <= r.creation_time <= end_dt]


def run(args: argparse.Namespace) -> None:
    """Execute the revision listing."""
    # Clear any previous permission errors
    _permission_errors.clear()

    print(f"\n{'='*70}")
    print(f"Cloud Run Revisions: {args.start} to {args.end}")
    print(f"{'='*70}\n")

    projects = PROJECTS if args.all_projects else [args.project]

    all_revisions: list[Revision] = []

    for project in projects:
        print(f"Querying {project}...", end=" ", flush=True)

        # Get revisions
        raw_revisions = list_revisions(project, args.region, args.limit * 2)
        revisions = [
            r for r in (parse_revision(data, project, args.region) for data in raw_revisions)
            if r is not None
        ]
        all_revisions.extend(revisions)
        print(f"found {len(revisions)} revisions")

    if not all_revisions:
        print("\nNo revisions found.")
        return

    # Filter by date range
    tzinfo = all_revisions[0].creation_time.tzinfo
    start_dt, end_dt = date_bounds(args.start, args.end, tzinfo)
    filtered = filter_by_date_range(all_revisions, start_dt, end_dt)

    if not filtered:
        print(f"\nNo revisions deployed between {args.start} and {args.end}.")
        print(f"(Found {len(all_revisions)} total revisions, but none in the specified range)")
        return

    # Sort by creation time (newest first)
    filtered.sort(key=lambda r: r.creation_time, reverse=True)

    # Group by date
    by_date: dict[str, list[Revision]] = {}
    for rev in filtered[:args.limit]:
        date_str = rev.creation_time.strftime("%Y-%m-%d")
        if date_str not in by_date:
            by_date[date_str] = []
        by_date[date_str].append(rev)

    # Print results
    print(f"\nDeployments in range ({len(filtered)} total, showing up to {args.limit}):")
    print("-" * 70)

    for date in sorted(by_date.keys(), reverse=True):
        revisions = by_date[date]
        print(f"\n{date} ({len(revisions)} deployments):")

        # Group by service
        by_service: dict[str, list[Revision]] = {}
        for rev in revisions:
            if rev.service not in by_service:
                by_service[rev.service] = []
            by_service[rev.service].append(rev)

        for service in sorted(by_service.keys()):
            svc_revisions = by_service[service]
            times = ", ".join(r.creation_time.strftime("%H:%M") for r in svc_revisions)
            project = svc_revisions[0].project
            print(f"  {service:<40} ({project}) at {times}")

    # Summary by service
    print(f"\n{'='*70}")
    print("Deployment Summary by Service:")
    print("-" * 70)

    service_counts: dict[str, int] = {}
    for rev in filtered:
        service_counts[rev.service] = service_counts.get(rev.service, 0) + 1

    for service, count in sorted(service_counts.items(), key=lambda x: -x[1]):
        print(f"  {count:>3}x  {service}")

    if not args.skip_config_diff:
        print(f"\n{'='*70}")
        print("Config Changes (prev -> latest in range):")
        print("-" * 70)

        changes = []
        by_service: dict[str, list[Revision]] = {}
        for rev in all_revisions:
            by_service.setdefault(rev.service, []).append(rev)

        for service, revs in by_service.items():
            revs.sort(key=lambda r: r.creation_time)
            in_range = [r for r in revs if start_dt <= r.creation_time <= end_dt]
            if not in_range:
                continue
            latest = max(in_range, key=lambda r: r.creation_time)
            prev = next((r for r in reversed(revs) if r.creation_time < start_dt), None)
            if prev is None:
                changes.append((service, None, None, latest))
                continue
            diffs = compare_configs(prev.config, latest.config)
            if diffs:
                changes.append((service, diffs, prev, latest))

        if not changes:
            print("  No config changes detected.")
        else:
            for service, diffs, prev, latest in changes:
                project = latest.project
                if diffs is None:
                    print(f"  {service} ({project}): no prior revision before range")
                    continue
                print(f"  {service} ({project}):")
                for key, old, new in diffs:
                    old_str = old if old is not None else "(default)"
                    new_str = new if new is not None else "(default)"
                    print(f"    - {key}: {old_str} -> {new_str}")

    # List jobs
    print(f"\n{'='*70}")
    print("Cloud Run Jobs (current):")
    print("-" * 70)

    jobs_by_project: dict[str, list[dict[str, Any]]] = {}
    for project in projects:
        jobs = list_jobs(project, args.region)
        jobs_by_project[project] = jobs
        if jobs:
            print(f"\n{project}:")
            for job in jobs:
                name = job.get("metadata", {}).get("name", "")
                print(f"  - {name}")

    if not args.skip_job_executions:
        print(f"\n{'='*70}")
        print("Job Executions in Range:")
        print("-" * 70)

        job_counts: list[tuple[str, str, int, bool]] = []
        for project, jobs in jobs_by_project.items():
            for job in jobs:
                name = job.get("metadata", {}).get("name", "")
                if not name:
                    continue
                executions = list_job_executions(project, args.region, name)
                count = 0
                oldest_retained: datetime | None = None
                for execution in executions:
                    created = parse_timestamp(
                        execution.get("metadata", {}).get("creationTimestamp", "")
                    )
                    if created:
                        if oldest_retained is None or created < oldest_retained:
                            oldest_retained = created
                        if start_dt <= created <= end_dt:
                            count += 1
                # If the oldest retained execution is after our query start,
                # the count may be incomplete due to GCP's ~1000-record
                # execution retention limit per job.
                possibly_incomplete = (
                    oldest_retained is not None and oldest_retained > start_dt
                )
                if count > 0:
                    job_counts.append((project, name, count, possibly_incomplete))

        if not job_counts:
            print("  No job executions found in range.")
        else:
            job_counts.sort(key=lambda j: j[2], reverse=True)
            has_incomplete = False
            for project, name, count, incomplete in job_counts[:args.job_execution_limit]:
                marker = " *" if incomplete else ""
                print(f"  {count:>3}x  {name} ({project}){marker}")
                if incomplete:
                    has_incomplete = True
            remaining = len(job_counts) - args.job_execution_limit
            if remaining > 0:
                print(f"  ... and {remaining} more jobs")
            if has_incomplete:
                print("\n  * Count may be incomplete — Cloud Run retains ~1000")
                print("    executions per job. Older records outside the retention")
                print("    window are not included in these counts.")

    # Report permission errors at end (compact summary instead of inline warnings)
    if _permission_errors:
        # Group by project
        projects_with_errors = sorted(set(p for p, _, _ in _permission_errors))
        print(f"\n{'='*70}")
        print("⚠️  Skipped projects (permission denied):")
        print("-" * 70)
        for project in projects_with_errors:
            resources = sorted(set(r for p, r, _ in _permission_errors if p == project))
            print(f"  {project}: {', '.join(resources)}")
        print("\nTo access these projects, ensure you have Cloud Run Viewer role.")


if __name__ == "__main__":
    sys.exit(main())
