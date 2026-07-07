#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
# ]
# ///
"""Batch-create Linear labels (project or issue) with grouping support.

Supports CLI list mode and JSON file mode, with optional dry-run and idempotent
behavior (skip labels/groups that already exist in the target scope).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence


logger = logging.getLogger(__name__)

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
DEFAULT_COLOR = "#663399"
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

LabelType = Literal["project", "issue"]


class LinearAPIError(RuntimeError):
    """Raised when the Linear GraphQL API returns errors."""


class ValidationError(ValueError):
    """Raised when user input/configuration is invalid."""


@dataclass(slots=True)
class LinearClient:
    """Small GraphQL client for Linear API."""

    api_key: str
    timeout_seconds: float = 60.0

    def request(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a GraphQL operation and return `data`."""
        payload: dict[str, Any] = {"query": query, "variables": variables or {}}
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(LINEAR_GRAPHQL_URL, headers=headers, json=payload)
        if response.status_code >= 400:
            raise LinearAPIError(
                f"HTTP {response.status_code} from Linear GraphQL: {response.text}"
            )
        parsed = response.json()
        errors = parsed.get("errors")
        if errors:
            raise LinearAPIError(json.dumps(errors, indent=2))
        data = parsed.get("data")
        if data is None:
            raise LinearAPIError("GraphQL response missing `data`.")
        return data


@dataclass(slots=True)
class LabelSpec:
    """Normalized standalone label configuration."""

    name: str
    color: str
    description: str | None = None


@dataclass(slots=True)
class GroupSpec:
    """Normalized grouped label configuration."""

    group_name: str
    color: str
    labels: list[LabelSpec]


@dataclass(slots=True)
class ExistingLabel:
    """Existing label record used for idempotency checks."""

    id: str
    name: str
    color: str | None
    is_group: bool
    parent_id: str | None
    team_id: str | None


@dataclass(slots=True)
class RunStats:
    """Counters for run summary output."""

    created: int = 0
    skipped_existing: int = 0
    failed: int = 0
    planned: int = 0
    reused_groups: int = 0
    _temp_counter: int = field(default=0, repr=False)

    def next_temp_id(self, prefix: str) -> str:
        self._temp_counter += 1
        return f"{prefix}-temp-{self._temp_counter}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI args."""
    parser_kwargs: dict[str, Any] = {
        "description": __doc__.splitlines()[0],
        "formatter_class": argparse.RawDescriptionHelpFormatter,
    }
    if sys.version_info >= (3, 14):
        parser_kwargs["suggest_on_error"] = True
    parser = argparse.ArgumentParser(**parser_kwargs)
    parser.add_argument(
        "--type",
        required=True,
        choices=["project", "issue"],
        help='Label type: "project" or "issue".',
    )
    parser.add_argument(
        "--list",
        help="Comma-separated label names for CLI mode.",
    )
    parser.add_argument(
        "--group",
        help="Group name (CLI mode only).",
    )
    parser.add_argument(
        "--color",
        default=DEFAULT_COLOR,
        help=f"Hex color code (default: {DEFAULT_COLOR}).",
    )
    parser.add_argument(
        "--team",
        help="Team name/key/UUID for issue labels (optional).",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Path to JSON configuration file.",
    )
    parser.add_argument(
        "--token-env",
        default="LINEAR_API_KEY",
        help="Environment variable containing the Linear API key.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without creating labels.",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase logging verbosity.")
    return parser.parse_args(argv)


def configure_logging(verbosity: int) -> None:
    """Configure logging."""
    level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(level=max(level, logging.DEBUG), format="%(levelname)s: %(message)s")


def load_dotenv_if_present(path: Path) -> None:
    """Load dotenv-style environment variables if file exists.

    Existing process environment values are preserved.
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        idx = line.find("=")
        if idx <= 0:
            continue
        key = line[:idx].strip()
        value = line[idx + 1 :].strip()
        if (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ) and len(value) >= 2:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def format_api_error(api_message: str, context: str) -> str:
    """Attach scope/auth hint for common permission failures."""
    msg = f"{context}: {api_message}"
    if re.search(r"scope.*write|write.*scope|authentication|unauthorized", api_message, re.IGNORECASE):
        msg += (
            "\nHint: LINEAR_API_KEY may not have write permissions. "
            "Create a personal key with write scope in Linear Settings > API."
        )
    return msg


def validate_hex_color(color: str, *, context: str) -> None:
    """Validate #RRGGBB format."""
    if not HEX_COLOR_RE.fullmatch(color):
        raise ValidationError(f"{context}: invalid color '{color}'. Expected format like #3498db.")


def parse_label_list(raw_list: str) -> list[str]:
    """Split comma-separated list while preserving spaces inside names."""
    labels = [item.strip() for item in raw_list.split(",")]
    labels = [item for item in labels if item]
    if not labels:
        raise ValidationError("--list must contain at least one non-empty label name.")
    return labels


def parse_description(value: Any, *, context: str) -> str | None:
    """Normalize optional description field."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{context}: description must be a string when provided.")
    return value


def paginate_connection(
    client: LinearClient,
    query: str,
    variables: dict[str, Any],
    connection_key: str,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Fetch all pages for a top-level connection and return nodes."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page_vars = {**variables, "first": page_size, "after": cursor}
        data = client.request(query, page_vars)
        connection = data[connection_key]
        nodes: list[dict[str, Any]] = connection["nodes"]
        items.extend(nodes)
        page_info = connection["pageInfo"]
        if not page_info["hasNextPage"]:
            return items
        cursor = page_info["endCursor"]


def resolve_team_id(client: LinearClient, team_name_or_id: str) -> str:
    """Resolve team name/key/UUID to a team UUID."""
    if UUID_RE.fullmatch(team_name_or_id):
        return team_name_or_id

    query = """
    query Teams($first: Int!, $after: String) {
      teams(first: $first, after: $after, includeArchived: true) {
        nodes {
          id
          name
          key
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    teams = paginate_connection(client, query, {}, "teams")

    exact = [
        team
        for team in teams
        if team.get("name") == team_name_or_id
        or team.get("key") == team_name_or_id
        or team.get("id") == team_name_or_id
    ]
    if len(exact) == 1:
        return exact[0]["id"]
    if len(exact) > 1:
        raise ValidationError(f"Team reference '{team_name_or_id}' is ambiguous; matched multiple teams.")

    casefold_target = team_name_or_id.casefold()
    casefold_matches = [
        team
        for team in teams
        if (team.get("name") or "").casefold() == casefold_target
        or (team.get("key") or "").casefold() == casefold_target
        or (team.get("id") or "").casefold() == casefold_target
    ]
    if len(casefold_matches) == 1:
        return casefold_matches[0]["id"]
    if len(casefold_matches) > 1:
        raise ValidationError(
            f"Team reference '{team_name_or_id}' is ambiguous (case-insensitive match)."
        )

    raise ValidationError(f"Team not found: {team_name_or_id}")


def list_existing_labels(
    client: LinearClient,
    label_type: LabelType,
    team_id: str | None,
) -> list[ExistingLabel]:
    """List labels in target scope for idempotency checks."""
    if label_type == "project":
        query = """
        query ProjectLabels($first: Int!, $after: String) {
          projectLabels(first: $first, after: $after, includeArchived: true) {
            nodes {
              id
              name
              color
              isGroup
              parent {
                id
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        nodes = paginate_connection(client, query, {}, "projectLabels")
        return [
            ExistingLabel(
                id=node["id"],
                name=node.get("name") or "",
                color=node.get("color"),
                is_group=bool(node.get("isGroup")),
                parent_id=(node.get("parent") or {}).get("id"),
                team_id=None,
            )
            for node in nodes
        ]

    query = """
    query IssueLabels($first: Int!, $after: String) {
      issueLabels(first: $first, after: $after, includeArchived: true) {
        nodes {
          id
          name
          color
          isGroup
          parent {
            id
          }
          team {
            id
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    nodes = paginate_connection(client, query, {}, "issueLabels")
    labels: list[ExistingLabel] = []
    for node in nodes:
        node_team_id = (node.get("team") or {}).get("id")
        if team_id is None and node_team_id is not None:
            continue
        if team_id is not None and node_team_id != team_id:
            continue
        labels.append(
            ExistingLabel(
                id=node["id"],
                name=node.get("name") or "",
                color=node.get("color"),
                is_group=bool(node.get("isGroup")),
                parent_id=(node.get("parent") or {}).get("id"),
                team_id=node_team_id,
            )
        )
    return labels


def build_existing_index(labels: list[ExistingLabel]) -> dict[tuple[str | None, str], list[ExistingLabel]]:
    """Index existing labels by (parent_id, casefold(name))."""
    index: dict[tuple[str | None, str], list[ExistingLabel]] = {}
    for label in labels:
        key = (label.parent_id, label.name.casefold())
        index.setdefault(key, []).append(label)
    return index


def find_existing(
    index: dict[tuple[str | None, str], list[ExistingLabel]],
    parent_id: str | None,
    name: str,
) -> list[ExistingLabel]:
    """Return existing labels matching parent/name."""
    return index.get((parent_id, name.casefold()), [])


def record_existing(
    index: dict[tuple[str | None, str], list[ExistingLabel]],
    label: ExistingLabel,
) -> None:
    """Update index with a newly created/synthetic label."""
    key = (label.parent_id, label.name.casefold())
    index.setdefault(key, []).append(label)


def create_project_label(
    client: LinearClient,
    *,
    name: str,
    color: str,
    description: str | None,
    parent_id: str | None,
    is_group: bool,
) -> ExistingLabel:
    """Create a project label or group label."""
    mutation = """
    mutation CreateProjectLabel(
      $name: String!,
      $color: String!,
      $description: String,
      $parentId: String,
      $isGroup: Boolean
    ) {
      projectLabelCreate(input: {
        name: $name,
        color: $color,
        description: $description,
        parentId: $parentId,
        isGroup: $isGroup
      }) {
        success
        projectLabel {
          id
          name
          color
          isGroup
          parent {
            id
          }
        }
      }
    }
    """
    variables = {
        "name": name,
        "color": color,
        "description": description,
        "parentId": parent_id,
        "isGroup": is_group,
    }
    try:
        data = client.request(mutation, variables)
    except LinearAPIError as exc:
        raise LinearAPIError(
            format_api_error(str(exc), f"Failed to create project label '{name}'")
        ) from exc

    created = data["projectLabelCreate"]["projectLabel"]
    return ExistingLabel(
        id=created["id"],
        name=created.get("name") or name,
        color=created.get("color"),
        is_group=bool(created.get("isGroup")),
        parent_id=(created.get("parent") or {}).get("id"),
        team_id=None,
    )


def create_issue_label(
    client: LinearClient,
    *,
    name: str,
    color: str,
    description: str | None,
    parent_id: str | None,
    is_group: bool,
    team_id: str | None,
) -> ExistingLabel:
    """Create an issue label or group label."""
    mutation = """
    mutation CreateIssueLabel(
      $name: String!,
      $color: String!,
      $description: String,
      $parentId: String,
      $isGroup: Boolean,
      $teamId: String
    ) {
      issueLabelCreate(input: {
        name: $name,
        color: $color,
        description: $description,
        parentId: $parentId,
        isGroup: $isGroup,
        teamId: $teamId
      }) {
        success
        issueLabel {
          id
          name
          color
          isGroup
          parent {
            id
          }
          team {
            id
          }
        }
      }
    }
    """
    variables = {
        "name": name,
        "color": color,
        "description": description,
        "parentId": parent_id,
        "isGroup": is_group,
        "teamId": team_id,
    }
    try:
        data = client.request(mutation, variables)
    except LinearAPIError as exc:
        raise LinearAPIError(
            format_api_error(str(exc), f"Failed to create issue label '{name}'")
        ) from exc

    created = data["issueLabelCreate"]["issueLabel"]
    return ExistingLabel(
        id=created["id"],
        name=created.get("name") or name,
        color=created.get("color"),
        is_group=bool(created.get("isGroup")),
        parent_id=(created.get("parent") or {}).get("id"),
        team_id=(created.get("team") or {}).get("id"),
    )


def create_label(
    client: LinearClient,
    *,
    label_type: LabelType,
    name: str,
    color: str,
    description: str | None,
    parent_id: str | None,
    is_group: bool,
    team_id: str | None,
) -> ExistingLabel:
    """Create label using type-specific mutation."""
    if label_type == "project":
        return create_project_label(
            client,
            name=name,
            color=color,
            description=description,
            parent_id=parent_id,
            is_group=is_group,
        )
    return create_issue_label(
        client,
        name=name,
        color=color,
        description=description,
        parent_id=parent_id,
        is_group=is_group,
        team_id=team_id,
    )


def ensure_group(
    client: LinearClient,
    *,
    label_type: LabelType,
    group_name: str,
    group_color: str,
    team_id: str | None,
    dry_run: bool,
    existing_index: dict[tuple[str | None, str], list[ExistingLabel]],
    stats: RunStats,
) -> str:
    """Get existing group ID or create it (or plan it in dry-run)."""
    matches = find_existing(existing_index, None, group_name)
    groups = [item for item in matches if item.is_group]
    non_groups = [item for item in matches if not item.is_group]

    if groups:
        group = groups[0]
        print(f"SKIP group exists: {group.name} ({group.id})")
        stats.skipped_existing += 1
        stats.reused_groups += 1
        return group.id

    if non_groups:
        raise ValidationError(
            f"Cannot create group '{group_name}': a non-group label with that name already exists in this scope."
        )

    if dry_run:
        group_id = stats.next_temp_id("group")
        print(f"DRY-RUN create group: {group_name} (synthetic id {group_id})")
        stats.planned += 1
        record_existing(
            existing_index,
            ExistingLabel(
                id=group_id,
                name=group_name,
                color=group_color,
                is_group=True,
                parent_id=None,
                team_id=team_id,
            ),
        )
        return group_id

    created = create_label(
        client,
        label_type=label_type,
        name=group_name,
        color=group_color,
        description=None,
        parent_id=None,
        is_group=True,
        team_id=team_id,
    )
    print(f"CREATED group: {created.name} ({created.id})")
    stats.created += 1
    record_existing(existing_index, created)
    return created.id


def create_or_skip_label(
    client: LinearClient,
    *,
    label_type: LabelType,
    spec: LabelSpec,
    parent_id: str | None,
    team_id: str | None,
    dry_run: bool,
    existing_index: dict[tuple[str | None, str], list[ExistingLabel]],
    stats: RunStats,
) -> None:
    """Create a label when missing, otherwise skip as existing."""
    matches = find_existing(existing_index, parent_id, spec.name)
    if matches:
        existing = matches[0]
        print(f"SKIP label exists: {existing.name} ({existing.id})")
        stats.skipped_existing += 1
        return

    if dry_run:
        fake_id = stats.next_temp_id("label")
        parent_desc = parent_id if parent_id is not None else "root"
        print(f"DRY-RUN create label: {spec.name} (parent={parent_desc}, synthetic id {fake_id})")
        stats.planned += 1
        record_existing(
            existing_index,
            ExistingLabel(
                id=fake_id,
                name=spec.name,
                color=spec.color,
                is_group=False,
                parent_id=parent_id,
                team_id=team_id,
            ),
        )
        return

    created = create_label(
        client,
        label_type=label_type,
        name=spec.name,
        color=spec.color,
        description=spec.description,
        parent_id=parent_id,
        is_group=False,
        team_id=team_id,
    )
    print(f"CREATED label: {created.name} ({created.id})")
    stats.created += 1
    record_existing(existing_index, created)


def parse_file_items(
    config: dict[str, Any],
    *,
    default_color: str,
) -> list[LabelSpec | GroupSpec]:
    """Parse and validate file label entries."""
    labels_raw = config.get("labels")
    if not isinstance(labels_raw, list):
        raise ValidationError('JSON file must contain a "labels" array.')

    items: list[LabelSpec | GroupSpec] = []
    for idx, raw in enumerate(labels_raw):
        context = f"labels[{idx}]"
        if not isinstance(raw, dict):
            raise ValidationError(f"{context} must be an object.")

        if "groupName" in raw:
            group_name = raw.get("groupName")
            if not isinstance(group_name, str) or not group_name.strip():
                raise ValidationError(f"{context}.groupName must be a non-empty string.")
            group_name = group_name.strip()

            group_color_raw = raw.get("color") or default_color
            if not isinstance(group_color_raw, str):
                raise ValidationError(f"{context}.color must be a string when provided.")
            validate_hex_color(group_color_raw, context=f"{context}.color")

            child_raw = raw.get("labels")
            if not isinstance(child_raw, list) or len(child_raw) == 0:
                raise ValidationError(f"{context}.labels must be a non-empty array.")

            children: list[LabelSpec] = []
            for child_idx, child in enumerate(child_raw):
                child_context = f"{context}.labels[{child_idx}]"
                if not isinstance(child, dict):
                    raise ValidationError(f"{child_context} must be an object.")
                child_name = child.get("name")
                if not isinstance(child_name, str) or not child_name.strip():
                    raise ValidationError(f"{child_context}.name must be a non-empty string.")
                child_color_raw = child.get("color") or group_color_raw
                if not isinstance(child_color_raw, str):
                    raise ValidationError(f"{child_context}.color must be a string when provided.")
                validate_hex_color(child_color_raw, context=f"{child_context}.color")
                child_description = parse_description(child.get("description"), context=child_context)
                children.append(
                    LabelSpec(
                        name=child_name.strip(),
                        color=child_color_raw,
                        description=child_description,
                    )
                )

            items.append(GroupSpec(group_name=group_name, color=group_color_raw, labels=children))
            continue

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError(f"{context}.name must be a non-empty string.")
        color_raw = raw.get("color") or default_color
        if not isinstance(color_raw, str):
            raise ValidationError(f"{context}.color must be a string when provided.")
        validate_hex_color(color_raw, context=f"{context}.color")
        description = parse_description(raw.get("description"), context=context)
        items.append(LabelSpec(name=name.strip(), color=color_raw, description=description))

    return items


def parse_json_file(path: Path, *, default_color: str) -> tuple[LabelType, str | None, list[LabelSpec | GroupSpec]]:
    """Load, validate, and normalize JSON file mode config."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"Invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValidationError("JSON root must be an object.")

    file_type_raw = payload.get("type")
    if not isinstance(file_type_raw, str):
        raise ValidationError('JSON file must contain a "type" field ("project" or "issue").')
    file_type = file_type_raw.strip().lower()
    if file_type not in {"project", "issue"}:
        raise ValidationError('JSON "type" must be either "project" or "issue".')

    team = payload.get("team")
    if team is not None and not isinstance(team, str):
        raise ValidationError('JSON "team" must be a string when provided.')

    items = parse_file_items(payload, default_color=default_color)
    return file_type, team, items


def process_items(
    client: LinearClient,
    *,
    label_type: LabelType,
    items: list[LabelSpec | GroupSpec],
    team_id: str | None,
    dry_run: bool,
    continue_on_error: bool,
) -> RunStats:
    """Process normalized items with idempotent create behavior."""
    existing_labels = list_existing_labels(client, label_type=label_type, team_id=team_id)
    existing_index = build_existing_index(existing_labels)
    stats = RunStats()

    for item in items:
        try:
            if isinstance(item, GroupSpec):
                group_id = ensure_group(
                    client,
                    label_type=label_type,
                    group_name=item.group_name,
                    group_color=item.color,
                    team_id=team_id,
                    dry_run=dry_run,
                    existing_index=existing_index,
                    stats=stats,
                )
                for child in item.labels:
                    create_or_skip_label(
                        client,
                        label_type=label_type,
                        spec=child,
                        parent_id=group_id,
                        team_id=team_id,
                        dry_run=dry_run,
                        existing_index=existing_index,
                        stats=stats,
                    )
            else:
                create_or_skip_label(
                    client,
                    label_type=label_type,
                    spec=item,
                    parent_id=None,
                    team_id=team_id,
                    dry_run=dry_run,
                    existing_index=existing_index,
                    stats=stats,
                )
        except (LinearAPIError, ValidationError, httpx.HTTPError) as exc:
            stats.failed += 1
            print(f"ERROR: {exc}", file=sys.stderr)
            if not continue_on_error:
                raise

    return stats


def print_summary(
    *,
    label_type: LabelType,
    mode: str,
    team_id: str | None,
    dry_run: bool,
    stats: RunStats,
) -> None:
    """Print deterministic end-of-run summary."""
    scope = team_id or "workspace"
    print("=" * 60)
    print(f"type={label_type} mode={mode} scope={scope} dry_run={str(dry_run).lower()}")
    print(f"created={stats.created}")
    print(f"planned={stats.planned}")
    print(f"skipped_existing={stats.skipped_existing}")
    print(f"reused_groups={stats.reused_groups}")
    print(f"failed={stats.failed}")
    print("=" * 60)


def validate_mode_args(args: argparse.Namespace) -> None:
    """Validate mutually exclusive mode inputs and shared arguments."""
    use_cli = args.list is not None
    use_file = args.file is not None
    if use_cli == use_file:
        raise ValidationError("Provide exactly one input mode: either --list or --file.")

    validate_hex_color(args.color, context="--color")

    if args.group and not use_cli:
        raise ValidationError("--group is only valid with --list mode.")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    args = parse_args(argv)
    configure_logging(args.verbose)

    try:
        validate_mode_args(args)

        script_dir = Path(__file__).resolve().parent
        load_dotenv_if_present(script_dir / ".env")

        api_key = os.getenv(args.token_env)
        if not api_key:
            logger.error("Missing API key env var: %s", args.token_env)
            return 2

        client = LinearClient(api_key=api_key)

        if args.list is not None:
            mode = "cli"
            label_type: LabelType = args.type
            labels = parse_label_list(args.list)

            team_id: str | None = None
            if label_type == "issue" and args.team:
                team_id = resolve_team_id(client, args.team)
            if label_type == "project" and args.team:
                logger.warning("Ignoring --team for project labels.")

            items: list[LabelSpec | GroupSpec]
            if args.group:
                group_name = args.group.strip()
                if not group_name:
                    raise ValidationError("--group must be a non-empty value.")
                items = [
                    GroupSpec(
                        group_name=group_name,
                        color=args.color,
                        labels=[LabelSpec(name=name, color=args.color, description=None) for name in labels],
                    )
                ]
            else:
                items = [LabelSpec(name=name, color=args.color, description=None) for name in labels]

            stats = process_items(
                client,
                label_type=label_type,
                items=items,
                team_id=team_id,
                dry_run=args.dry_run,
                continue_on_error=False,
            )
            print_summary(
                label_type=label_type,
                mode=mode,
                team_id=team_id,
                dry_run=args.dry_run,
                stats=stats,
            )
            return 1 if stats.failed > 0 else 0

        mode = "file"
        label_type_from_file, team_from_file, items = parse_json_file(args.file, default_color=args.color)

        if args.type != label_type_from_file:
            logger.warning(
                "--type=%s differs from file type=%s; using file type.",
                args.type,
                label_type_from_file,
            )

        label_type = label_type_from_file
        team_input = team_from_file if label_type == "issue" else None
        team_id = resolve_team_id(client, team_input) if team_input else None

        if label_type == "project" and team_from_file:
            logger.warning("Ignoring file 'team' value for project labels.")

        stats = process_items(
            client,
            label_type=label_type,
            items=items,
            team_id=team_id,
            dry_run=args.dry_run,
            continue_on_error=True,
        )
        print_summary(
            label_type=label_type,
            mode=mode,
            team_id=team_id,
            dry_run=args.dry_run,
            stats=stats,
        )
        return 1 if stats.failed > 0 else 0

    except KeyboardInterrupt:
        return 130
    except (ValidationError, LinearAPIError, httpx.HTTPError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
