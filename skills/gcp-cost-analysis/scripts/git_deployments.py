#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Analyze git commits during a time period to identify deployment-related changes.

Helps correlate code changes with cost fluctuations.

Usage:
    uv run git_deployments.py --start 2026-01-01 --end 2026-01-11 --repo /path/to/repo
    uv run git_deployments.py --start 2026-01-01 --end 2026-01-11 --repo . --filter terraform
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Error executing git command."""


@dataclass
class Commit:
    """A git commit."""

    hash: str
    short_hash: str
    author: str
    date: datetime
    subject: str
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    args = parse_args(argv)
    configure_logging(args.verbose)

    try:
        run(args)
        return 0
    except KeyboardInterrupt:
        return 130
    except GitError as e:
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
    parser.add_argument("--repo", "-r", type=Path, default=Path("."),
                        help="Path to git repository (default: current directory)")
    parser.add_argument("--filter", "-f", help="Filter commits by keyword in message or files")
    parser.add_argument("--show-files", action="store_true",
                        help="Show files changed in each commit")
    parser.add_argument("--limit", "-l", type=int, default=100,
                        help="Max commits to show (default: 100)")
    parser.add_argument("--branch", "-b", default="main",
                        help="Branch to analyze (default: main)")

    return parser.parse_args(argv)


def configure_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level."""
    level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(levelname)s: %(message)s",
    )


def run_git(args: list[str], cwd: Path) -> str:
    """Execute git command and return stdout."""
    cmd = ["git"] + args
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=60)
    if result.returncode != 0:
        raise GitError(f"git error: {result.stderr.strip()}")
    return result.stdout


def get_commits(
    repo: Path,
    start: str,
    end: str,
    branch: str,
    limit: int,
) -> list[Commit]:
    """Get commits in date range."""
    # Format: hash|short_hash|author|date|subject
    format_str = "%H|%h|%an|%aI|%s"

    output = run_git([
        "log",
        branch,
        f"--since={start}",
        f"--until={end} 23:59:59",
        f"--format={format_str}",
        f"-n{limit}",
        "--no-merges",
    ], repo)

    commits = []
    for line in output.strip().split("\n"):
        if not line:
            continue
        try:
            parts = line.split("|", 4)
            if len(parts) < 5:
                continue

            commit = Commit(
                hash=parts[0],
                short_hash=parts[1],
                author=parts[2],
                date=datetime.fromisoformat(parts[3]),
                subject=parts[4],
            )
            commits.append(commit)
        except (ValueError, IndexError) as e:
            logger.debug("Failed to parse commit line: %s - %s", line, e)

    return commits


def get_commit_stats(repo: Path, commit_hash: str) -> tuple[int, int, int]:
    """Get file stats for a commit."""
    try:
        output = run_git([
            "show",
            commit_hash,
            "--stat",
            "--format=",
        ], repo)

        # Parse summary line like "5 files changed, 100 insertions(+), 50 deletions(-)"
        lines = output.strip().split("\n")
        if lines:
            summary = lines[-1]
            files = 0
            insertions = 0
            deletions = 0

            if "file" in summary:
                parts = summary.split(",")
                for part in parts:
                    part = part.strip()
                    if "file" in part:
                        files = int(part.split()[0])
                    elif "insertion" in part:
                        insertions = int(part.split()[0])
                    elif "deletion" in part:
                        deletions = int(part.split()[0])

            return files, insertions, deletions
    except (GitError, ValueError):
        pass

    return 0, 0, 0


def get_changed_files(repo: Path, commit_hash: str) -> list[str]:
    """Get list of files changed in a commit."""
    output = run_git([
        "show",
        commit_hash,
        "--name-only",
        "--format=",
    ], repo)
    return [f for f in output.strip().split("\n") if f]


def categorize_commit(subject: str, files: list[str]) -> list[str]:
    """Categorize a commit based on subject and files."""
    categories = []

    subject_lower = subject.lower()
    all_text = subject_lower + " " + " ".join(files).lower()

    # Infrastructure changes
    if any(k in all_text for k in ["terraform", ".tf", "infra"]):
        categories.append("terraform")
    if any(k in all_text for k in ["dockerfile", "docker", "container"]):
        categories.append("docker")
    if any(k in all_text for k in ["cloud run", "cloudrun", "gcp", "gcloud"]):
        categories.append("gcp")
    if any(k in all_text for k in ["ci", "github/workflows", ".github", "ci/cd"]):
        categories.append("ci/cd")

    # Code changes
    if any(k in all_text for k in [".go", "go.mod", "go.sum"]):
        categories.append("go")
    if any(k in all_text for k in [".rs", "cargo.toml", "cargo.lock"]):
        categories.append("rust")
    if any(k in all_text for k in [".py", "requirements", "pyproject"]):
        categories.append("python")
    if any(k in all_text for k in [".ts", ".js", "package.json"]):
        categories.append("typescript")

    # Feature areas
    if any(k in all_text for k in ["logging", "log", "trace", "tracing"]):
        categories.append("observability")
    if any(k in all_text for k in ["firestore", "database", "sql", "postgres"]):
        categories.append("database")
    if any(k in all_text for k in ["migration", "migrate"]):
        categories.append("migration")
    if any(k in all_text for k in ["batch", "job", "cron", "scheduler"]):
        categories.append("jobs")

    return categories if categories else ["other"]


def run(args: argparse.Namespace) -> None:
    """Execute the git analysis."""
    repo = args.repo.resolve()

    if not (repo / ".git").exists():
        raise GitError(f"Not a git repository: {repo}")

    print(f"\n{'='*70}")
    print(f"Git Commit Analysis: {args.start} to {args.end}")
    print(f"Repository: {repo}")
    print(f"Branch: {args.branch}")
    print(f"{'='*70}\n")

    # Get commits
    commits = get_commits(repo, args.start, args.end, args.branch, args.limit)

    if not commits:
        print("No commits found in the specified date range.")
        return

    # Filter if requested
    if args.filter:
        filter_lower = args.filter.lower()
        filtered = []
        for commit in commits:
            files = get_changed_files(repo, commit.hash)
            all_text = commit.subject.lower() + " " + " ".join(files).lower()
            if filter_lower in all_text:
                filtered.append(commit)
        commits = filtered
        print(f"Filtered to {len(commits)} commits matching '{args.filter}'")

    if not commits:
        print("No commits match the filter criteria.")
        return

    # Categorize and collect stats
    category_counts: dict[str, int] = {}
    total_files = 0
    total_insertions = 0
    total_deletions = 0

    print(f"Found {len(commits)} commits\n")
    print("-" * 70)

    for commit in commits:
        files = get_changed_files(repo, commit.hash) if args.show_files else []
        categories = categorize_commit(commit.subject, files)

        for cat in categories:
            category_counts[cat] = category_counts.get(cat, 0) + 1

        files_changed, insertions, deletions = get_commit_stats(repo, commit.hash)
        total_files += files_changed
        total_insertions += insertions
        total_deletions += deletions

        # Print commit
        date_str = commit.date.strftime("%Y-%m-%d %H:%M")
        cat_str = ", ".join(categories)
        print(f"{commit.short_hash} {date_str} [{cat_str}]")
        print(f"    {commit.subject[:65]}")
        if args.show_files and files:
            for f in files[:5]:
                print(f"      - {f}")
            if len(files) > 5:
                print(f"      ... and {len(files) - 5} more files")
        print()

    # Summary
    print(f"{'='*70}")
    print("Summary")
    print("-" * 70)
    print(f"Total commits: {len(commits)}")
    print(f"Total files changed: {total_files}")
    print(f"Total insertions: +{total_insertions}")
    print(f"Total deletions: -{total_deletions}")
    print()
    print("By category:")
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {count:>3}x  {cat}")

    # Cost-relevant changes
    cost_relevant = ["terraform", "gcp", "docker", "migration", "jobs", "database", "observability"]
    relevant_count = sum(category_counts.get(c, 0) for c in cost_relevant)
    if relevant_count > 0:
        print(f"\nPotentially cost-impacting commits: {relevant_count}")
        print("  Categories: " + ", ".join(c for c in cost_relevant if category_counts.get(c, 0) > 0))


if __name__ == "__main__":
    sys.exit(main())
