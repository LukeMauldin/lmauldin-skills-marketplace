#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
# ]
# ///
"""Discover Linear workspace structure via GraphQL and write normalized outputs.

This script queries teams, workflow states, projects, initiatives, labels, users, and
issues, then emits JSON + Markdown summaries for skill maintenance.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence


logger = logging.getLogger(__name__)

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"


class LinearAPIError(RuntimeError):
    """Raised when the Linear GraphQL API returns errors."""


@dataclass(slots=True)
class LinearClient:
    """Small GraphQL client for Linear API."""

    api_key: str
    timeout_seconds: float = 60.0

    def request(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a GraphQL operation and return `data`."""
        payload: dict[str, Any] = {"query": query, "variables": variables or {}}
        headers = {
            # Linear personal API keys are sent directly as the Authorization value.
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


def paginate_connection(
    client: LinearClient,
    query: str,
    variables: dict[str, Any],
    connection_key: str,
    page_size: int = 100,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch all pages for a top-level connection and return concatenated nodes."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page_vars = {**variables, "first": page_size, "after": cursor}
        data = client.request(query, page_vars)
        connection = data[connection_key]
        nodes: list[dict[str, Any]] = connection["nodes"]
        items.extend(nodes)
        if limit is not None and len(items) >= limit:
            return items[:limit]
        page_info = connection["pageInfo"]
        if not page_info["hasNextPage"]:
            return items
        cursor = page_info["endCursor"]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI args."""
    parser_kwargs: dict[str, Any] = {"description": __doc__.splitlines()[0]}
    if sys.version_info >= (3, 14):
        parser_kwargs["suggest_on_error"] = True
    parser = argparse.ArgumentParser(**parser_kwargs)
    parser.add_argument("--token-env", default="LINEAR_API_KEY", help="Env var containing Linear API key.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(".tmp/jb-linear-research"),
        help="Output directory for generated research artifacts.",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=2500,
        help="Max number of issues to fetch for distribution analysis.",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase logging verbosity.")
    return parser.parse_args(argv)


def configure_logging(verbosity: int) -> None:
    """Configure logging."""
    level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(level=max(level, logging.DEBUG), format="%(levelname)s: %(message)s")


def build_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """Produce normalized summary data from raw GraphQL output."""
    teams = raw["teams"]
    projects = raw["projects"]
    workflow_states = raw["workflow_states"]
    labels = raw["issue_labels"]
    users = raw["users"]
    initiatives = raw["initiatives"]
    issues = raw["issues"]

    team_key_by_id = {team["id"]: team.get("key") for team in teams}

    states_by_team_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for state in workflow_states:
        team = state.get("team") or {}
        team_key = team.get("key") or team_key_by_id.get(team.get("id")) or "UNKNOWN"
        states_by_team_key[team_key].append(
            {
                "id": state["id"],
                "name": state["name"],
                "type": state.get("type"),
                "position": state.get("position"),
                "color": state.get("color"),
            }
        )
    for team_key, states in states_by_team_key.items():
        states.sort(key=lambda item: (item.get("position") is None, item.get("position"), item["name"]))
        logger.debug("Team %s has %d workflow states", team_key, len(states))

    labels_by_team_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    workspace_labels: list[dict[str, Any]] = []
    for label in labels:
        team = label.get("team")
        label_entry = {
            "id": label["id"],
            "name": label["name"],
            "color": label.get("color"),
            "description": label.get("description"),
        }
        if team is None:
            workspace_labels.append(label_entry)
            continue
        team_key = team.get("key") or "UNKNOWN"
        labels_by_team_key[team_key].append(label_entry)
    for team_key, team_labels in labels_by_team_key.items():
        team_labels.sort(key=lambda item: item["name"].lower())
    workspace_labels.sort(key=lambda item: item["name"].lower())

    issue_counts_by_team = Counter()
    issue_counts_by_project = Counter()
    issue_counts_by_state = Counter()
    assignee_counts = Counter()
    labels_in_use = Counter()

    for issue in issues:
        team = issue.get("team") or {}
        project = issue.get("project") or {}
        state = issue.get("state") or {}
        assignee = issue.get("assignee") or {}

        team_key = team.get("key", "UNKNOWN")
        project_name = project.get("name", "No Project")
        state_name = state.get("name", "UNKNOWN")

        issue_counts_by_team[team_key] += 1
        issue_counts_by_project[project_name] += 1
        issue_counts_by_state[f"{team_key}:{state_name}"] += 1
        if assignee.get("email"):
            assignee_counts[assignee["email"]] += 1

        issue_labels = issue.get("labels", {}).get("nodes", [])
        for label in issue_labels:
            labels_in_use[label["name"]] += 1

    projects_summary: list[dict[str, Any]] = []
    for project in sorted(projects, key=lambda item: item["name"].lower()):
        project_teams = project.get("teams", {}).get("nodes", [])
        projects_summary.append(
            {
                "id": project["id"],
                "name": project["name"],
                "slugId": project.get("slugId"),
                "state": project.get("state"),
                "description": project.get("description"),
                "url": project.get("url"),
                "startDate": project.get("startDate"),
                "targetDate": project.get("targetDate"),
                "lead": (project.get("lead") or {}).get("email"),
                "teamKeys": [team.get("key") for team in project_teams if team.get("key")],
                "teamNames": [team.get("name") for team in project_teams if team.get("name")],
                "issueCountFromSnapshot": issue_counts_by_project.get(project["name"], 0),
            }
        )

    initiatives_summary = sorted(
        (
            {
                "id": initiative["id"],
                "name": initiative["name"],
                "description": initiative.get("description"),
                "url": initiative.get("url"),
            }
            for initiative in initiatives
        ),
        key=lambda item: item["name"].lower(),
    )

    teams_summary = sorted(
        (
            {
                "id": team["id"],
                "key": team.get("key"),
                "name": team.get("name"),
                "description": team.get("description"),
                "issueCountFromSnapshot": issue_counts_by_team.get(team.get("key", "UNKNOWN"), 0),
                "workflowStates": states_by_team_key.get(team.get("key", "UNKNOWN"), []),
                "teamLabels": labels_by_team_key.get(team.get("key", "UNKNOWN"), []),
            }
            for team in teams
        ),
        key=lambda item: ((item["key"] or "~").lower(), item["name"].lower() if item["name"] else ""),
    )

    return {
        "metadata": raw["metadata"],
        "viewer": raw["viewer"],
        "counts": {
            "teams": len(teams),
            "projects": len(projects),
            "initiatives": len(initiatives),
            "workflowStates": len(workflow_states),
            "issueLabels": len(labels),
            "users": len(users),
            "issuesSnapshot": len(issues),
        },
        "teams": teams_summary,
        "projects": projects_summary,
        "initiatives": initiatives_summary,
        "workspaceLabels": workspace_labels,
        "issueDistributions": {
            "byTeam": dict(issue_counts_by_team.most_common()),
            "byProject": dict(issue_counts_by_project.most_common()),
            "byStateWithinTeam": dict(issue_counts_by_state.most_common()),
            "topAssignees": dict(assignee_counts.most_common(25)),
            "topLabelsInUse": dict(labels_in_use.most_common(50)),
        },
    }


def write_markdown_summary(summary: dict[str, Any], path: Path) -> None:
    """Write a human-readable markdown summary."""
    lines: list[str] = []
    metadata = summary["metadata"]
    counts = summary["counts"]

    lines.append("# Linear Workspace Discovery Summary")
    lines.append("")
    lines.append(f"- Captured at (UTC): `{metadata['capturedAt']}`")
    lines.append(f"- Source endpoint: `{metadata['endpoint']}`")
    lines.append(f"- Viewer email: `{summary['viewer'].get('email', 'unknown')}`")
    lines.append(f"- Teams: `{counts['teams']}`")
    lines.append(f"- Projects: `{counts['projects']}`")
    lines.append(f"- Initiatives: `{counts['initiatives']}`")
    lines.append(f"- Labels: `{counts['issueLabels']}`")
    lines.append(f"- Users: `{counts['users']}`")
    lines.append(f"- Issues in snapshot: `{counts['issuesSnapshot']}`")
    lines.append("")

    lines.append("## Teams")
    lines.append("")
    for team in summary["teams"]:
        key = team["key"] or "NO_KEY"
        lines.append(f"### {team['name']} ({key})")
        lines.append("")
        lines.append(f"- Snapshot issue count: `{team['issueCountFromSnapshot']}`")
        lines.append("- Workflow states:")
        for state in team["workflowStates"]:
            lines.append(f"  - `{state['name']}` ({state.get('type', 'unknown')})")
        if team["teamLabels"]:
            lines.append("- Team labels:")
            for label in team["teamLabels"]:
                lines.append(f"  - `{label['name']}`")
        lines.append("")

    lines.append("## Projects")
    lines.append("")
    for project in summary["projects"]:
        lines.append(f"- `{project['name']}` | teams={project['teamKeys']} | state={project.get('state')} | issues={project['issueCountFromSnapshot']}")
    lines.append("")

    lines.append("## Top Assignees (Issue Snapshot)")
    lines.append("")
    for email, count in summary["issueDistributions"]["topAssignees"].items():
        lines.append(f"- `{email}`: `{count}`")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    args = parse_args(argv)
    configure_logging(args.verbose)

    api_key = os.getenv(args.token_env)
    if not api_key:
        logger.error("Missing API key env var: %s", args.token_env)
        return 2

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    client = LinearClient(api_key=api_key)

    try:
        viewer_query = """
        query Viewer {
          viewer {
            id
            name
            email
          }
        }
        """
        viewer = client.request(viewer_query)["viewer"]

        teams_query = """
        query Teams($first: Int!, $after: String) {
          teams(first: $first, after: $after, includeArchived: true) {
            nodes {
              id
              key
              name
              description
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        teams = paginate_connection(client, teams_query, {}, "teams")

        users_query = """
        query Users($first: Int!, $after: String) {
          users(first: $first, after: $after, includeArchived: true, includeDisabled: true) {
            nodes {
              id
              name
              displayName
              email
              active
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        users = paginate_connection(client, users_query, {}, "users")

        projects_query = """
        query Projects($first: Int!, $after: String) {
          projects(first: $first, after: $after, includeArchived: true) {
            nodes {
              id
              name
              slugId
              description
              state
              startDate
              targetDate
              url
              lead {
                id
                name
                email
              }
              teams(first: 20) {
                nodes {
                  id
                  key
                  name
                }
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        projects = paginate_connection(client, projects_query, {}, "projects")

        initiatives_query = """
        query Initiatives($first: Int!, $after: String) {
          initiatives(first: $first, after: $after, includeArchived: true) {
            nodes {
              id
              name
              description
              url
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        initiatives = paginate_connection(client, initiatives_query, {}, "initiatives")

        labels_query = """
        query IssueLabels($first: Int!, $after: String) {
          issueLabels(first: $first, after: $after, includeArchived: true) {
            nodes {
              id
              name
              color
              description
              team {
                id
                key
                name
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        issue_labels = paginate_connection(client, labels_query, {}, "issueLabels")

        workflow_states_query = """
        query WorkflowStates($first: Int!, $after: String, $teamId: ID!) {
          workflowStates(first: $first, after: $after, includeArchived: true, filter: { team: { id: { eq: $teamId } } }) {
            nodes {
              id
              name
              type
              position
              color
              team {
                id
                key
                name
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """

        workflow_states: list[dict[str, Any]] = []
        for team in teams:
            team_id = team["id"]
            workflow_states.extend(
                paginate_connection(
                    client=client,
                    query=workflow_states_query,
                    variables={"teamId": team_id},
                    connection_key="workflowStates",
                )
            )

        issues_query = """
        query Issues($first: Int!, $after: String) {
          issues(first: $first, after: $after, includeArchived: false) {
            nodes {
              id
              identifier
              title
              state {
                id
                name
                type
              }
              team {
                id
                key
                name
              }
              project {
                id
                name
                slugId
              }
              assignee {
                id
                name
                email
              }
              labels(first: 20) {
                nodes {
                  id
                  name
                }
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        issues = paginate_connection(
            client=client,
            query=issues_query,
            variables={},
            connection_key="issues",
            limit=max(args.max_issues, 1),
        )

        raw_payload = {
            "metadata": {
                "capturedAt": datetime.now(tz=UTC).isoformat(),
                "endpoint": LINEAR_GRAPHQL_URL,
                "maxIssuesRequested": args.max_issues,
            },
            "viewer": viewer,
            "teams": teams,
            "users": users,
            "projects": projects,
            "initiatives": initiatives,
            "issue_labels": issue_labels,
            "workflow_states": workflow_states,
            "issues": issues,
        }
        summary = build_summary(raw_payload)

        raw_path = out_dir / "linear_workspace_raw.json"
        summary_path = out_dir / "linear_workspace_summary.json"
        markdown_path = out_dir / "linear_workspace_summary.md"

        raw_path.write_text(json.dumps(raw_payload, indent=2, sort_keys=True), encoding="utf-8")
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        write_markdown_summary(summary, markdown_path)

        logger.warning("Wrote raw snapshot: %s", raw_path)
        logger.warning("Wrote summary JSON: %s", summary_path)
        logger.warning("Wrote summary Markdown: %s", markdown_path)
        return 0
    except KeyboardInterrupt:
        return 130
    except httpx.HTTPError as exc:
        logger.exception("HTTP error querying Linear API: %s", exc)
        return 1
    except LinearAPIError as exc:
        logger.exception("Linear GraphQL error: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
