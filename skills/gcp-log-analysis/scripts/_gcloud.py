"""Shared utilities for gcloud CLI wrappers.

This module provides common functionality for scripts that wrap gcloud commands,
including structured JSON output parsing, error handling, and logging configuration.
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Common project choices for argument parsers
PROJECTS = ["ksu-live", "kidstrong-at-home"]
DEFAULT_PROJECT = "ksu-live"


class GcloudError(Exception):
    """Error executing gcloud command."""


def run_gcloud_logging(
    query: str,
    project: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Execute gcloud logging read and return parsed JSON entries.

    Args:
        query: Cloud Logging filter query.
        project: GCP project ID.
        limit: Maximum entries to fetch.

    Returns:
        List of log entry dicts with full structure.

    Raises:
        GcloudError: If gcloud command fails.
    """
    cmd = [
        "gcloud", "logging", "read", query,
        f"--project={project}",
        f"--limit={limit}",
        "--format=json",
    ]
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GcloudError(result.stderr.strip())

    if not result.stdout.strip():
        return []
    return json.loads(result.stdout)


def run_gcloud_command(cmd: Sequence[str]) -> str:
    """Execute an arbitrary gcloud command and return stdout.

    Args:
        cmd: Command and arguments to execute.

    Returns:
        Command stdout as string.

    Raises:
        GcloudError: If gcloud command fails.
    """
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(list(cmd), capture_output=True, text=True)
    if result.returncode != 0:
        raise GcloudError(result.stderr.strip())
    return result.stdout


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


def get_nested(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get nested dictionary value.

    Args:
        d: Dictionary to traverse.
        *keys: Sequence of keys to follow.
        default: Value to return if path doesn't exist.

    Returns:
        Value at the nested path, or default if not found.

    Example:
        get_nested(entry, "resource", "labels", "service_name")
    """
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
        if d is default:
            return default
    return d
