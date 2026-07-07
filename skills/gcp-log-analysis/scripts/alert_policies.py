#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""List Cloud Monitoring alert policies.

Usage:
    uv run alert_policies.py [--project PROJECT] [--filter FILTER]

Examples:
    uv run alert_policies.py --project ksu-live
    uv run alert_policies.py --filter "HTTP"
    uv run alert_policies.py --filter "Latency"
"""
from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from _gcloud import (
    DEFAULT_PROJECT,
    PROJECTS,
    GcloudError,
    configure_logging,
    run_gcloud_command,
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
    parser.add_argument("--filter", "-f", help="Filter policies by name (case-insensitive)")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    """Execute the alert policies listing."""
    cmd = [
        "gcloud", "alpha", "monitoring", "policies", "list",
        f"--project={args.project}",
        "--format=table(displayName,enabled,conditions.displayName)",
    ]
    output = run_gcloud_command(cmd)

    print(f"\n{'='*80}")
    print(f"Alert Policies: {args.project}")
    print(f"{'='*80}\n")

    if args.filter:
        filter_lower = args.filter.lower()
        lines = output.strip().split("\n")
        # Keep header
        if lines:
            print(lines[0])
        # Filter remaining lines
        for line in lines[1:]:
            if filter_lower in line.lower():
                print(line)
    else:
        print(output)


if __name__ == "__main__":
    sys.exit(main())
