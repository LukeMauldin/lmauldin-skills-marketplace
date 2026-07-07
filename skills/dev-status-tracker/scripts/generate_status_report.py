#!/usr/bin/env python3
"""Generate a unified ClickUp/GitHub/GCP status report for KidStrong."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

GITHUB_ORG = "KidStrong"
DEFAULT_REPOS = ["KidStrongBedrock"]
DEFAULT_REPO_PATH = Path.home() / "code/github.com/KidStrong/KidStrongBedrock"
GCP_DEV_PROJECT = "kidstrong-at-home"
GCP_PROD_PROJECT = "ksu-live"
GCP_REGION = "us-central1"
ACTIVE_STATUSES = {"in progress", "in review", "testing", "pending live"}
CLICKUP_ID_REGEX = re.compile(r"(?<![a-z0-9])cu[-\s]?([a-z0-9]+)\b", re.IGNORECASE)
PR_SEARCH_TERMS = ("CU-", "CU ")

DEFAULT_QA_APPROVAL_REGEX = re.compile(
    r"\bqa\b.*\bapproved\b"
    r"|\bapproved\b.*\bqa\b"
    r"|\bqa\s*pass(?:ed)?\b"
    r"|\bpass(?:ed)?\s*qa\b"
    r"|\bqa\s*ok\b"
    r"|\bqa\b.*\bcomplete\b"
    r"|\bqa\b.*\bsign[-\s]?off\b"
    r"|\bapproved\b.*\bprod(?:uction)?\b"
    r"|\bready\b.*\bprod(?:uction)?\b"
    r"|\btested\b.*\bapproved\b",
    re.IGNORECASE,
)
SPRINT_TEAMS = ("server", "coach", "tv")


@dataclass(frozen=True)
class WorkflowTarget:
    workflow_name: str
    service_name: str
    resource_type: str  # "service" or "job"


@dataclass(frozen=True)
class GcpResourceStatus:
    project: str
    resource_type: str
    service_name: str
    commit_sha: str | None


@dataclass
class DeploymentStatus:
    workflow_name: str
    run_id: int
    run_url: str
    overall_status: str
    build_status: str | None = None
    dev_deploy_status: str | None = None
    prod_deploy_status: str | None = None
    service_name: str | None = None
    resource_type: str | None = None
    gcp_dev: GcpResourceStatus | None = None
    gcp_prod: GcpResourceStatus | None = None


@dataclass
class PRInfo:
    number: int
    title: str
    state: str
    url: str
    merged_at: str | None
    merge_commit: str | None
    head_branch: str | None
    repo: str
    deployments: list[DeploymentStatus] = field(default_factory=list)

    @property
    def is_merged(self) -> bool:
        return self.merged_at is not None

    @property
    def is_open(self) -> bool:
        return self.state.upper() == "OPEN"

    @property
    def is_closed(self) -> bool:
        return self.state.upper() == "CLOSED" and not self.is_merged


@dataclass
class TaskStatus:
    clickup_id: str
    clickup_name: str
    clickup_status: str
    clickup_url: str
    prs: list[PRInfo] = field(default_factory=list)
    qa_approved: bool | None = None
    qa_approval_comment: str | None = None
    expected_status: str | None = None
    discrepancy: str | None = None
    issues: list[str] = field(default_factory=list)


def run_command(
    args: list[str],
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {' '.join(args)}")
    return result


def run_gh_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return run_command(["gh"] + args, check=check)


def run_gcloud_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return run_command(["gcloud"] + args, check=check)


def normalize_repos(values: list[str]) -> list[str]:
    repos: list[str] = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if item:
                repos.append(item)
    return repos or DEFAULT_REPOS


def parse_repo_paths(values: list[str] | None) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    if not values:
        return mapping
    for item in values:
        if "=" not in item:
            raise ValueError(f"Invalid repo path mapping: {item}")
        repo, path = item.split("=", 1)
        mapping[repo.strip()] = Path(path.strip()).expanduser()
    return mapping


def strip_quotes(value: str) -> str:
    value = value.strip()
    if value.startswith("\"") and value.endswith("\""):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def parse_workflow_target(content: str) -> WorkflowTarget | None:
    workflow_name: str | None = None
    service_name: str | None = None
    resource_type: str | None = None

    for line in content.splitlines():
        if workflow_name is None:
            name_match = re.match(r"^name:\s*(.+)$", line)
            if name_match:
                workflow_name = strip_quotes(name_match.group(1))

        service_match = re.match(r"^\s*service-name:\s*(.+)$", line)
        if service_match and service_name is None:
            value = strip_quotes(service_match.group(1))
            if value and "${{" not in value and "inputs" not in value:
                service_name = value

        if "uses:" in line:
            if "deploy-service-dev.yml" in line or "deploy-service-prod.yml" in line:
                resource_type = "service"
            if "deploy-job-dev.yml" in line or "deploy-job-prod.yml" in line:
                resource_type = "job"

    if workflow_name and service_name and resource_type:
        return WorkflowTarget(
            workflow_name=workflow_name,
            service_name=service_name,
            resource_type=resource_type,
        )
    return None


def discover_workflow_targets(repo_path: Path) -> dict[str, WorkflowTarget]:
    workflows_dir = repo_path / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return {}

    targets: dict[str, WorkflowTarget] = {}
    workflow_paths = list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
    for path in workflow_paths:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue

        target = parse_workflow_target(content)
        if target:
            targets[target.workflow_name] = target

    return targets


def list_remote_workflows(repo: str) -> list[str]:
    workflows: list[str] = []
    per_page = 100
    page = 1
    while True:
        endpoint = (
            f"/repos/{GITHUB_ORG}/{repo}/actions/workflows"
            f"?per_page={per_page}&page={page}"
        )
        result = run_gh_command(["api", endpoint], check=False)
        if result.returncode != 0 or not result.stdout.strip():
            break
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            break
        items = data.get("workflows", [])
        if not isinstance(items, list) or not items:
            break
        for item in items:
            path = item.get("path")
            if isinstance(path, str) and path:
                workflows.append(path)
        total_count = data.get("total_count")
        if len(items) < per_page:
            break
        if isinstance(total_count, int) and len(workflows) >= total_count:
            break
        page += 1
    return workflows


def fetch_remote_workflow_content(repo: str, path: str, ref: str | None) -> str | None:
    endpoint = f"/repos/{GITHUB_ORG}/{repo}/contents/{path}"
    if ref:
        endpoint = f"{endpoint}?ref={ref}"
    result = run_gh_command(
        ["api", "-H", "Accept: application/vnd.github.raw", endpoint],
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout


def discover_workflow_targets_remote(repo: str, ref: str | None) -> dict[str, WorkflowTarget]:
    targets: dict[str, WorkflowTarget] = {}
    for path in list_remote_workflows(repo):
        content = fetch_remote_workflow_content(repo, path, ref)
        if not content:
            continue
        target = parse_workflow_target(content)
        if target:
            targets[target.workflow_name] = target
    return targets


def locate_clickup_engineer_script(script_name: str) -> Path | None:
    candidates: list[Path] = []
    override = os.environ.get("CLICKUP_ENGINEER_PATH")
    if override:
        candidates.append(Path(override).expanduser() / "scripts" / script_name)
    try:
        skills_root = Path(__file__).resolve().parents[2]
        candidates.append(skills_root / "clickup-engineer" / "scripts" / script_name)
    except IndexError:
        pass

    candidates.extend(
        [
            Path.home() / ".codex/skills/clickup-engineer/scripts" / script_name,
            Path.home() / ".claude/skills/clickup-engineer/scripts" / script_name,
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def fetch_list_details_via_script(
    token: str,
    list_id: str,
    script_path: Path,
) -> dict[str, Any] | None:
    env = os.environ.copy()
    env["CLICKUP_API_TOKEN"] = token
    result = run_command(
        [sys.executable, str(script_path), list_id, "--format", "json"],
        check=False,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"get_list.py failed: {result.stderr.strip()}"
        )

    if not result.stdout.strip():
        raise RuntimeError("get_list.py returned empty output")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON from get_list.py") from exc

    if isinstance(payload, dict):
        if isinstance(payload.get("list"), dict):
            return payload["list"]
        if isinstance(payload.get("lists"), list):
            for entry in payload["lists"]:
                if isinstance(entry, dict) and isinstance(entry.get("list"), dict):
                    return entry["list"]
    return None


def fetch_tasks_from_list_via_script(
    token: str,
    list_id: str,
    script_path: Path,
) -> list[dict[str, Any]]:
    env = os.environ.copy()
    env["CLICKUP_API_TOKEN"] = token
    result = run_command(
        [
            sys.executable,
            str(script_path),
            "--list-id",
            list_id,
            "--exclude-closed",
            "--format",
            "json",
        ],
        check=False,
        env=env,
    )

    if not result.stdout.strip():
        raise RuntimeError(
            f"fetch_filtered_tasks.py returned empty output: {result.stderr.strip()}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON from fetch_filtered_tasks.py") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        raise RuntimeError("fetch_filtered_tasks.py output missing tasks")

    return payload.get("tasks", [])


def fetch_tasks_by_ids_via_script(
    token: str,
    task_ids: list[str],
    script_path: Path,
) -> list[dict[str, Any]]:
    env = os.environ.copy()
    env["CLICKUP_API_TOKEN"] = token
    result = run_command(
        [sys.executable, str(script_path), *task_ids, "--format", "json"],
        check=False,
        env=env,
    )

    if not result.stdout.strip():
        raise RuntimeError(
            f"get_task.py returned empty output: {result.stderr.strip()}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON from get_task.py") from exc

    tasks: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("task"), dict):
            tasks.append(payload["task"])
        elif isinstance(payload.get("tasks"), list):
            for entry in payload["tasks"]:
                if isinstance(entry, dict) and isinstance(entry.get("task"), dict):
                    tasks.append(entry["task"])

    return tasks


def resolve_current_sprint_via_script(
    token: str,
    sprint_team: str,
    script_path: Path,
) -> tuple[str, str]:
    env = os.environ.copy()
    env["CLICKUP_API_TOKEN"] = token
    result = run_command(
        [
            sys.executable,
            str(script_path),
            "--team",
            sprint_team,
            "--format",
            "json",
            "--fallback",
            "latest",
            "--quiet",
        ],
        check=False,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"get_current_sprint.py failed: {result.stderr.strip()}"
        )

    if not result.stdout.strip():
        raise RuntimeError("get_current_sprint.py returned empty output")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON from get_current_sprint.py") from exc

    list_info = payload.get("list", {}) if isinstance(payload, dict) else {}
    list_id = str(list_info.get("id", "")).strip()
    list_name = list_info.get("name") or "Current Sprint"
    if not list_id:
        raise RuntimeError("get_current_sprint.py missing list id")

    return list_id, list_name


def fetch_task_comments(
    token: str,
    task_id: str,
    max_pages: int,
    script_path: Path | None,
) -> list[dict[str, Any]]:
    if max_pages <= 0:
        return []
    if script_path is None:
        raise RuntimeError("fetch_comments.py path not available")

    env = os.environ.copy()
    env["CLICKUP_API_TOKEN"] = token
    result = run_command(
        [
            sys.executable,
            str(script_path),
            task_id,
            "--quiet",
            "--pages",
            str(max_pages),
        ],
        check=False,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"fetch_comments.py failed for {task_id}: {result.stderr.strip()}"
        )

    if not result.stdout.strip():
        return []

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON from fetch_comments.py") from exc

    if isinstance(payload, dict):
        return payload.get("comments", [])
    return []


def extract_comment_text(comment: dict[str, Any]) -> str:
    if "comment_text" in comment and isinstance(comment["comment_text"], str):
        return comment["comment_text"]
    comment_blocks = comment.get("comment")
    if isinstance(comment_blocks, list):
        return "".join(block.get("text", "") for block in comment_blocks if isinstance(block, dict))
    if isinstance(comment_blocks, str):
        return comment_blocks
    return ""


def find_qa_approval(
    comments: list[dict[str, Any]],
    pattern: re.Pattern[str],
) -> tuple[bool, str | None]:
    for comment in comments:
        text = extract_comment_text(comment)
        if text and pattern.search(text):
            snippet = re.sub(r"\s+", " ", text.strip())
            if len(snippet) > 160:
                snippet = f"{snippet[:157]}..."
            return True, snippet
    return False, None


def run_gh_graphql(
    query: str,
    variables: dict[str, str | None],
    quiet: bool,
) -> dict[str, Any] | None:
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is None:
            continue
        args.extend(["-f", f"{key}={value}"])

    result = run_gh_command(args, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        if not quiet:
            message = result.stderr.strip() or "empty response"
            print(f"Warning: gh api graphql failed: {message}", file=sys.stderr)
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        if not quiet:
            print("Warning: invalid JSON from gh api graphql", file=sys.stderr)
        return None

    if payload.get("errors"):
        if not quiet:
            print(f"Warning: gh api graphql error: {payload['errors']}", file=sys.stderr)
        return None

    return payload


def extract_clickup_ids(title: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for match in CLICKUP_ID_REGEX.finditer(title):
        value = match.group(1).lower()
        if value not in seen:
            seen.add(value)
            ids.append(value)
    return ids


def search_prs_via_graphql(
    repo: str,
    search_query: str,
    quiet: bool,
) -> list[dict[str, Any]]:
    prs: list[dict[str, Any]] = []
    cursor: str | None = None
    query = """
    query($search: String!, $cursor: String) {
      search(query: $search, type: ISSUE, first: 100, after: $cursor) {
        nodes {
          ... on PullRequest {
            number
            title
            state
            url
            mergedAt
            headRefName
            mergeCommit { oid }
            repository { name }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    """

    while True:
        payload = run_gh_graphql(
            query,
            {"search": search_query, "cursor": cursor},
            quiet,
        )
        if not payload:
            break

        search = payload.get("data", {}).get("search", {})
        nodes = search.get("nodes", [])
        if isinstance(nodes, list):
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                repo_name = ""
                repo_data = node.get("repository")
                if isinstance(repo_data, dict):
                    repo_name = repo_data.get("name", "")
                node["_repo"] = repo_name or repo
                prs.append(node)

        page_info = search.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return prs


def fetch_repo_prs(
    repo: str,
    quiet: bool,
    since_date: str | None = None,
) -> list[dict[str, Any]]:
    repo_prs: dict[str, dict[str, Any]] = {}
    for term in PR_SEARCH_TERMS:
        search_query = f'repo:{GITHUB_ORG}/{repo} is:pr in:title "{term}"'
        if since_date:
            search_query = f'{search_query} updated:>={since_date}'
        for pr in search_prs_via_graphql(repo, search_query, quiet):
            key = f"{pr.get('_repo', repo)}#{pr.get('number')}"
            repo_prs[key] = pr
    return list(repo_prs.values())


def build_pr_index(
    repos: list[str],
    quiet: bool,
    since_date: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for repo in repos:
        for pr in fetch_repo_prs(repo, quiet, since_date):
            title = pr.get("title") or ""
            for clickup_id in extract_clickup_ids(title):
                index.setdefault(clickup_id, []).append(pr)
    return index


def get_workflow_runs_for_commit(commit_sha: str, repo: str) -> list[dict[str, Any]]:
    result = run_gh_command(
        [
            "run",
            "list",
            "--repo",
            f"{GITHUB_ORG}/{repo}",
            "--commit",
            commit_sha,
            "--json",
            "databaseId,workflowName,status,conclusion,createdAt,url,event",
            "--limit",
            "100",
        ],
        check=False,
    )

    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    deploy_runs = [r for r in runs if r.get("workflowName", "").startswith("Deploy")]
    return select_latest_runs(deploy_runs)


def select_latest_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        name = run.get("workflowName", "")
        created = run.get("createdAt", "")
        if not name:
            continue
        existing = latest.get(name)
        if not existing or created > existing.get("createdAt", ""):
            latest[name] = run
    return list(latest.values())


def get_workflow_run_details(run_id: int, repo: str) -> dict[str, Any] | None:
    result = run_gh_command(
        [
            "run",
            "view",
            str(run_id),
            "--repo",
            f"{GITHUB_ORG}/{repo}",
            "--json",
            "jobs,status,conclusion,workflowName",
        ],
        check=False,
    )

    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def analyze_deployment_status(run_details: dict[str, Any], run_info: dict[str, Any]) -> DeploymentStatus:
    jobs = run_details.get("jobs", [])

    build_status = None
    dev_status = None
    prod_status = None

    for job in jobs:
        name = job.get("name", "").lower()
        status = job.get("status", "")
        conclusion = job.get("conclusion", "")
        job_status = conclusion if conclusion else status

        if "build" in name:
            build_status = job_status
        if "development" in name or "dev" in name:
            dev_status = job_status
        if "production" in name or "prod" in name:
            prod_status = job_status

    overall = run_details.get("conclusion") or run_details.get("status", "unknown")

    return DeploymentStatus(
        workflow_name=run_info.get("workflowName", "Unknown"),
        run_id=run_info.get("databaseId", 0),
        run_url=run_info.get("url", ""),
        overall_status=overall,
        build_status=build_status,
        dev_deploy_status=dev_status,
        prod_deploy_status=prod_status,
    )


def clickup_id_in_title(title: str, task_id: str) -> bool:
    pattern = re.compile(rf"\bcu[-\s]?{re.escape(task_id)}\b", re.IGNORECASE)
    return bool(pattern.search(title))


def clickup_id_at_end(title: str, task_id: str) -> bool:
    pattern = re.compile(rf"\bcu[-\s]?{re.escape(task_id)}\b\s*$", re.IGNORECASE)
    return bool(pattern.search(title.strip()))


def check_title_format(title: str, task_id: str) -> list[str]:
    issues: list[str] = []
    if clickup_id_at_end(title, task_id):
        return issues
    if clickup_id_in_title(title, task_id):
        issues.append("ClickUp ID not at end of PR title")
    else:
        issues.append("No ClickUp ID found in PR title")
    return issues


def gcloud_commit_label(resource: dict[str, Any]) -> str | None:
    for path in [
        ("metadata", "labels"),
        ("spec", "template", "metadata", "labels"),
    ]:
        node: Any = resource
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, dict) and "commit-sha" in node:
            return node.get("commit-sha")
    return None


def fetch_gcp_resource_status(
    resource_type: str,
    service_name: str,
    project: str,
    region: str,
    cache: dict[tuple[str, str, str], GcpResourceStatus | None],
) -> GcpResourceStatus | None:
    key = (resource_type, service_name, project)
    if key in cache:
        return cache[key]

    if resource_type == "service":
        args = [
            "run",
            "services",
            "describe",
            service_name,
            "--region",
            region,
            "--project",
            project,
            "--format",
            "json",
        ]
    else:
        args = [
            "run",
            "jobs",
            "describe",
            service_name,
            "--region",
            region,
            "--project",
            project,
            "--format",
            "json",
        ]

    result = run_gcloud_command(args, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        cache[key] = None
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        cache[key] = None
        return None

    status = GcpResourceStatus(
        project=project,
        resource_type=resource_type,
        service_name=service_name,
        commit_sha=gcloud_commit_label(data),
    )
    cache[key] = status
    return status


def commits_match(label_sha: str, commit_sha: str) -> bool:
    if not label_sha or not commit_sha:
        return False
    if label_sha == commit_sha:
        return True
    return label_sha.startswith(commit_sha[:7]) or commit_sha.startswith(label_sha[:7])


def gcp_match_status(status: GcpResourceStatus | None, commit_sha: str | None) -> bool | None:
    if not status or not status.commit_sha or not commit_sha:
        return None
    return commits_match(status.commit_sha, commit_sha)


def deployment_prod_ok(dep: DeploymentStatus, commit_sha: str | None) -> bool:
    gcp_match = gcp_match_status(dep.gcp_prod, commit_sha)
    if gcp_match is not None:
        return gcp_match
    if dep.prod_deploy_status:
        return dep.prod_deploy_status == "success"
    return False



def all_prod_deployed(prs: list[PRInfo]) -> bool:
    if not prs:
        return False

    has_deployments = False
    for pr in prs:
        if not pr.deployments:
            return False
        has_deployments = True
        for dep in pr.deployments:
            if not deployment_prod_ok(dep, pr.merge_commit):
                return False
    return has_deployments


def determine_expected_status(
    status: TaskStatus,
    token: str,
    qa_pattern: re.Pattern[str],
    comment_cache: dict[str, tuple[bool, str | None]],
    comment_pages: int,
    fetch_comments_script: Path | None,
) -> str | None:
    if not status.prs:
        return None

    if any(pr.is_open for pr in status.prs):
        return "in review"

    merged_prs = [pr for pr in status.prs if pr.is_merged]
    if not merged_prs:
        return None

    if all_prod_deployed(merged_prs):
        return "completed"

    if comment_pages <= 0:
        status.qa_approved = False
        status.qa_approval_comment = None
        return "testing"

    if status.clickup_id in comment_cache:
        status.qa_approved, status.qa_approval_comment = comment_cache[status.clickup_id]
    else:
        try:
            comments = fetch_task_comments(
                token, status.clickup_id, comment_pages, fetch_comments_script
            )
        except RuntimeError as exc:
            status.issues.append(str(exc))
            status.qa_approved = False
            status.qa_approval_comment = None
            return "testing"
        status.qa_approved, status.qa_approval_comment = find_qa_approval(
            comments, qa_pattern
        )
        comment_cache[status.clickup_id] = (status.qa_approved, status.qa_approval_comment)

    return "pending live" if status.qa_approved else "testing"


def build_task_status(
    task: dict[str, Any],
    pr_index: dict[str, list[dict[str, Any]]],
    workflow_maps: dict[str, dict[str, WorkflowTarget]],
    token: str,
    qa_pattern: re.Pattern[str],
    comment_cache: dict[str, tuple[bool, str | None]],
    comment_pages: int,
    fetch_comments_script: Path | None,
    gcp_enabled: bool,
    gcp_cache: dict[tuple[str, str, str], GcpResourceStatus | None],
    gcp_dev_project: str,
    gcp_prod_project: str,
    gcp_region: str,
) -> TaskStatus:
    task_id = task.get("id", "")
    task_name = task.get("name", "")
    task_status = task.get("status", {}).get("status", "unknown")
    task_url = task.get("url", f"https://app.clickup.com/t/{task_id}")

    status = TaskStatus(
        clickup_id=task_id,
        clickup_name=task_name,
        clickup_status=task_status,
        clickup_url=task_url,
    )

    prs = pr_index.get(str(task_id).lower(), [])
    for pr_data in prs:
        repo = pr_data.get("_repo", "")
        merge_commit = pr_data.get("mergeCommit") or {}
        commit_sha = merge_commit.get("oid") if isinstance(merge_commit, dict) else None

        pr_info = PRInfo(
            number=pr_data.get("number", 0),
            title=pr_data.get("title", ""),
            state=pr_data.get("state", ""),
            url=pr_data.get("url", ""),
            merged_at=pr_data.get("mergedAt"),
            merge_commit=commit_sha,
            head_branch=pr_data.get("headRefName"),
            repo=repo,
        )

        for issue in check_title_format(pr_info.title, task_id):
            status.issues.append(f"PR #{pr_info.number} ({repo}): {issue}")

        if pr_info.is_merged and commit_sha:
            runs = get_workflow_runs_for_commit(commit_sha, repo)
            if not runs:
                status.issues.append(
                    f"PR #{pr_info.number} ({repo}): no deploy workflows found for merge commit"
                )

            for run_info in runs:
                run_id = run_info.get("databaseId", 0)
                run_details = get_workflow_run_details(run_id, repo)
                if not run_details:
                    status.issues.append(
                        f"PR #{pr_info.number} ({repo}): unable to read workflow run {run_id}"
                    )
                    continue

                dep_status = analyze_deployment_status(run_details, run_info)
                target = workflow_maps.get(repo, {}).get(dep_status.workflow_name)
                if target:
                    dep_status.service_name = target.service_name
                    dep_status.resource_type = target.resource_type

                    if gcp_enabled:
                        dep_status.gcp_dev = fetch_gcp_resource_status(
                            target.resource_type,
                            target.service_name,
                            gcp_dev_project,
                            gcp_region,
                            gcp_cache,
                        )
                        dep_status.gcp_prod = fetch_gcp_resource_status(
                            target.resource_type,
                            target.service_name,
                            gcp_prod_project,
                            gcp_region,
                            gcp_cache,
                        )
                elif gcp_enabled:
                    status.issues.append(
                        f"Workflow '{dep_status.workflow_name}' has no service mapping; skipping GCP lookup"
                    )

                pr_info.deployments.append(dep_status)

        status.prs.append(pr_info)

    active_prs = [pr for pr in status.prs if not pr.is_closed]
    if not active_prs and status.clickup_status.lower() in ACTIVE_STATUSES:
        status.issues.append(
            f"No GitHub PR found for task in '{status.clickup_status}' status"
        )

    status.expected_status = determine_expected_status(
        status, token, qa_pattern, comment_cache, comment_pages, fetch_comments_script
    )
    if status.expected_status and status.clickup_status.lower() != status.expected_status.lower():
        status.discrepancy = (
            f"Expected '{status.expected_status}', actual '{status.clickup_status}'"
        )

    return status


def short_sha(value: str | None) -> str:
    if not value:
        return ""
    return value[:7]


def format_gcp_status(status: GcpResourceStatus | None, commit_sha: str | None) -> str:
    match = gcp_match_status(status, commit_sha)
    if match is None:
        return "unknown"
    label = short_sha(status.commit_sha) if status else ""
    return f"{'match' if match else 'mismatch'} ({label})"


def format_deployment_line(dep: DeploymentStatus, commit_sha: str | None) -> list[str]:
    lines = []
    service_info = ""
    if dep.service_name and dep.resource_type:
        service_info = f" ({dep.resource_type}: {dep.service_name})"

    lines.append(f"    - [{dep.workflow_name}]({dep.run_url}){service_info}")
    lines.append(
        f"      - GH: build={dep.build_status or 'n/a'}, "
        f"dev={dep.dev_deploy_status or 'n/a'}, prod={dep.prod_deploy_status or 'n/a'}"
    )
    if dep.gcp_dev or dep.gcp_prod:
        lines.append(
            f"      - GCP: dev={format_gcp_status(dep.gcp_dev, commit_sha)}, "
            f"prod={format_gcp_status(dep.gcp_prod, commit_sha)}"
        )
    return lines


def generate_markdown_report(
    tasks: list[TaskStatus],
    list_name: str,
    repos: list[str],
    gcp_enabled: bool,
    gcp_dev_project: str,
    gcp_prod_project: str,
    gcp_region: str,
) -> str:
    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    discrepancies = [t for t in tasks if t.discrepancy]
    issues = [t for t in tasks if t.issues and not t.discrepancy]

    lines.append("# Development Status Report")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Source:** {list_name}")
    lines.append(f"**Tasks Analyzed:** {len(tasks)}")
    lines.append(f"**GitHub:** {GITHUB_ORG}/{', '.join(repos)}")
    if gcp_enabled:
        lines.append(
            f"**GCP:** dev {gcp_dev_project}, prod {gcp_prod_project} (region {gcp_region})"
        )
    else:
        lines.append("**GCP:** skipped")
    lines.append("")

    if discrepancies:
        lines.append("## Discrepancies")
        lines.append("")
        for task in discrepancies:
            lines.append(
                f"### [{task.clickup_id}]({task.clickup_url}) - {task.clickup_name}"
            )
            lines.append("")
            lines.append(f"**Discrepancy:** {task.discrepancy}")
            if task.qa_approved is not None:
                lines.append(f"**QA Approved:** {'yes' if task.qa_approved else 'no'}")
            if task.qa_approval_comment:
                lines.append(f"**QA Comment:** {task.qa_approval_comment}")
            lines.append("")

            if task.prs:
                lines.append("**PRs:**")
                for pr in task.prs:
                    merged_suffix = (
                        f" (merged {pr.merged_at[:10]})" if pr.is_merged and pr.merged_at else ""
                    )
                    lines.append(
                        f"- **PR #{pr.number} ({pr.repo}):** [{pr.title}]({pr.url}){merged_suffix}"
                    )
                    if pr.deployments:
                        lines.append("  - Deployments:")
                        for dep in pr.deployments:
                            for dep_line in format_deployment_line(dep, pr.merge_commit):
                                lines.append(dep_line)
            if task.issues:
                lines.append("")
                lines.append("**Issues:**")
                for issue in task.issues:
                    lines.append(f"- {issue}")
            lines.append("")

    if issues:
        lines.append("## Issues")
        lines.append("")
        for task in issues:
            lines.append(
                f"### [{task.clickup_id}]({task.clickup_url}) - {task.clickup_name}"
            )
            lines.append("")
            lines.append(f"**Status:** {task.clickup_status}")
            lines.append("")
            lines.append("**Issues:**")
            for issue in task.issues:
                lines.append(f"- {issue}")
            lines.append("")

    lines.append("## Tasks")
    lines.append("")

    for task in tasks:
        lines.append(f"### [{task.clickup_id}]({task.clickup_url}) - {task.clickup_name}")
        lines.append("")
        lines.append(f"- ClickUp: {task.clickup_status}")
        if task.expected_status:
            lines.append(f"- Expected: {task.expected_status}")
        if task.qa_approved is not None:
            lines.append(f"- QA Approved: {'yes' if task.qa_approved else 'no'}")
        if task.prs:
            lines.append("- PRs:")
            for pr in task.prs:
                state = "merged" if pr.is_merged else pr.state.lower()
                lines.append(f"  - PR #{pr.number} ({pr.repo}): {state}")
                if pr.deployments:
                    for dep in pr.deployments:
                        lines.append(
                            f"    - {dep.workflow_name}: "
                            f"build={dep.build_status or 'n/a'}, "
                            f"dev={dep.dev_deploy_status or 'n/a'}, "
                            f"prod={dep.prod_deploy_status or 'n/a'}"
                        )
        if task.issues:
            lines.append("- Issues:")
            for issue in task.issues:
                lines.append(f"  - {issue}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| Discrepancies | {len(discrepancies)} |")
    lines.append(f"| Issues | {len(issues)} |")
    lines.append(f"| OK | {len([t for t in tasks if not t.discrepancy and not t.issues])} |")
    lines.append(f"| **Total** | **{len(tasks)}** |")
    lines.append("")

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser_kwargs: dict[str, Any] = {
        "description": "Generate unified ClickUp/GitHub/GCP status report",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
    }
    if sys.version_info >= (3, 14):
        parser_kwargs["suggest_on_error"] = True

    parser = argparse.ArgumentParser(**parser_kwargs)

    parser.add_argument(
        "--list-id",
        default=None,
        help="ClickUp list ID (default: auto-resolve current sprint list)",
    )
    parser.add_argument(
        "--list-name",
        help="Override list name for report header",
    )
    parser.add_argument(
        "--sprint-folder",
        choices=SPRINT_TEAMS,
        default="server",
        help="Sprint folder to resolve current sprint list (default: server)",
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        default=DEFAULT_REPOS,
        help="GitHub repo names (space or comma separated)",
    )
    parser.add_argument(
        "--repo-path",
        default=str(DEFAULT_REPO_PATH),
        help=f"Local repo path for workflow discovery (default: {DEFAULT_REPO_PATH})",
    )
    parser.add_argument(
        "--repo-paths",
        nargs="*",
        help="Repo-to-path overrides (RepoName=/path/to/repo)",
    )
    parser.add_argument(
        "--workflow-source",
        choices=("auto", "local", "remote"),
        default="auto",
        help="Workflow discovery source (auto, local, or remote)",
    )
    parser.add_argument(
        "--workflow-ref",
        help="Git ref to use when reading remote workflow files",
    )
    parser.add_argument(
        "--task-ids",
        nargs="+",
        metavar="ID",
        help="Specific ClickUp task IDs to check",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of markdown",
    )
    parser.add_argument(
        "--comment-pages",
        type=int,
        default=1,
        help="Number of comment pages to scan for QA approval (default: 1)",
    )
    parser.add_argument(
        "--qa-approval-regex",
        help="Override regex for QA approval detection",
    )
    parser.add_argument(
        "--skip-gcp",
        action="store_true",
        help="Skip GCP lookups (use GitHub Actions only)",
    )
    parser.add_argument(
        "--gcp-dev-project",
        default=GCP_DEV_PROJECT,
        help=f"GCP dev project (default: {GCP_DEV_PROJECT})",
    )
    parser.add_argument(
        "--gcp-prod-project",
        default=GCP_PROD_PROJECT,
        help=f"GCP prod project (default: {GCP_PROD_PROJECT})",
    )
    parser.add_argument(
        "--gcp-region",
        default=GCP_REGION,
        help=f"GCP region (default: {GCP_REGION})",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=90,
        metavar="DAYS",
        help="Only search PRs updated within the last N days (default: 90)",
    )
    parser.add_argument(
        "--no-since",
        action="store_true",
        help="Disable date filtering, search all PRs",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 14):
        print(
            "Error: Python 3.14+ is required. Re-run with: "
            "uv run --python 3.14 scripts/generate_status_report.py",
            file=sys.stderr,
        )
        return 1

    args = parse_args(argv)

    if shutil.which("gh") is None:
        print("Error: gh CLI not found", file=sys.stderr)
        return 1

    if not args.skip_gcp and shutil.which("gcloud") is None:
        print("Warning: gcloud CLI not found; skipping GCP checks", file=sys.stderr)
        args.skip_gcp = True

    token = os.environ.get("CLICKUP_API_TOKEN")
    if not token:
        print("Error: CLICKUP_API_TOKEN environment variable not set", file=sys.stderr)
        return 1

    repos = normalize_repos(args.repos)

    repo_paths = {DEFAULT_REPOS[0]: Path(args.repo_path).expanduser()}
    try:
        repo_paths.update(parse_repo_paths(args.repo_paths))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    workflow_maps: dict[str, dict[str, WorkflowTarget]] = {}
    for repo in repos:
        repo_path = repo_paths.get(repo)
        targets: dict[str, WorkflowTarget] = {}

        if args.workflow_source in ("local", "auto"):
            if repo_path and repo_path.exists():
                targets = discover_workflow_targets(repo_path)
                if targets or args.workflow_source == "local":
                    workflow_maps[repo] = targets
                    if not targets and not args.quiet:
                        print(
                            f"Warning: no workflow targets found in {repo_path}",
                            file=sys.stderr,
                        )
                    continue
            elif args.workflow_source == "local":
                workflow_maps[repo] = {}
                if not args.quiet:
                    print(
                        f"Warning: repo path for {repo} not found; workflow mapping disabled",
                        file=sys.stderr,
                    )
                continue

        if args.workflow_source in ("remote", "auto"):
            targets = discover_workflow_targets_remote(repo, args.workflow_ref)
            workflow_maps[repo] = targets
            if not targets and not args.quiet:
                ref_suffix = f" (ref {args.workflow_ref})" if args.workflow_ref else ""
                print(
                    f"Warning: no workflow targets found for {repo} via remote lookup{ref_suffix}",
                    file=sys.stderr,
                )
            continue

        workflow_maps[repo] = {}

    qa_pattern = (
        re.compile(args.qa_approval_regex, re.IGNORECASE)
        if args.qa_approval_regex
        else DEFAULT_QA_APPROVAL_REGEX
    )

    since_date: str | None = None
    if not args.no_since and args.since > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.since)
        since_date = cutoff.strftime("%Y-%m-%d")

    if not args.quiet:
        date_info = f" (updated since {since_date})" if since_date else " (all time)"
        print(f"Fetching PRs for repos: {', '.join(repos)}{date_info}...", file=sys.stderr)
    pr_index = build_pr_index(repos, args.quiet, since_date)

    list_id = args.list_id
    list_name = args.list_name

    if args.task_ids:
        if not list_name:
            list_name = "Selected Tasks"
    else:
        if not list_id:
            sprint_script = locate_clickup_engineer_script("get_current_sprint.py")
            if not sprint_script:
                print(
                    "Error: clickup-engineer get_current_sprint.py not found",
                    file=sys.stderr,
                )
                return 1
            try:
                resolved_id, resolved_name = resolve_current_sprint_via_script(
                    token, args.sprint_folder, sprint_script
                )
                list_id = resolved_id
                if not list_name:
                    list_name = resolved_name
            except RuntimeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            if not args.quiet and list_name:
                print(
                    f"Resolved current sprint list: {list_name} ({list_id})",
                    file=sys.stderr,
                )
        else:
            list_script = locate_clickup_engineer_script("get_list.py")
            if not list_script:
                print("Error: clickup-engineer get_list.py not found", file=sys.stderr)
                return 1
            try:
                details = fetch_list_details_via_script(token, list_id, list_script)
            except RuntimeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            if not list_name:
                list_name = details.get("name") if details else f"List {list_id}"

    if args.task_ids:
        if not args.quiet:
            print(f"Fetching {len(args.task_ids)} task(s)...", file=sys.stderr)
        get_task_script = locate_clickup_engineer_script("get_task.py")
        if not get_task_script:
            print("Error: clickup-engineer get_task.py not found", file=sys.stderr)
            return 1
        try:
            tasks_data = fetch_tasks_by_ids_via_script(
                token, args.task_ids, get_task_script
            )
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        found_ids = {task.get("id") for task in tasks_data if isinstance(task, dict)}
        for task_id in args.task_ids:
            if task_id not in found_ids:
                print(f"Warning: Task {task_id} not found", file=sys.stderr)
    else:
        if not args.quiet:
            print(f"Fetching tasks from list {list_id}...", file=sys.stderr)
        if not list_id:
            print("Error: ClickUp list ID not resolved", file=sys.stderr)
            return 1
        fetch_tasks_script = locate_clickup_engineer_script("fetch_filtered_tasks.py")
        if not fetch_tasks_script:
            print(
                "Error: clickup-engineer fetch_filtered_tasks.py not found",
                file=sys.stderr,
            )
            return 1
        try:
            tasks_data = fetch_tasks_from_list_via_script(
                token, list_id, fetch_tasks_script
            )
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if not args.quiet:
        print(f"Found {len(tasks_data)} tasks", file=sys.stderr)

    fetch_comments_script: Path | None = None
    if args.comment_pages > 0:
        fetch_comments_script = locate_clickup_engineer_script("fetch_comments.py")
        if not fetch_comments_script:
            print(
                "Error: clickup-engineer fetch_comments.py not found",
                file=sys.stderr,
            )
            return 1

    gcp_cache: dict[tuple[str, str, str], GcpResourceStatus | None] = {}
    comment_cache: dict[str, tuple[bool, str | None]] = {}

    task_statuses: list[TaskStatus] = []
    for index, task in enumerate(tasks_data, 1):
        task_id = task.get("id", "unknown")
        if not args.quiet:
            print(f"[{index}/{len(tasks_data)}] Analyzing {task_id}...", file=sys.stderr)

        status = build_task_status(
            task,
            pr_index,
            workflow_maps,
            token,
            qa_pattern,
            comment_cache,
            args.comment_pages,
            fetch_comments_script,
            not args.skip_gcp,
            gcp_cache,
            args.gcp_dev_project,
            args.gcp_prod_project,
            args.gcp_region,
        )
        task_statuses.append(status)

    if args.json:
        output = json.dumps(
            [
                {
                    "clickup_id": t.clickup_id,
                    "clickup_name": t.clickup_name,
                    "clickup_status": t.clickup_status,
                    "clickup_url": t.clickup_url,
                    "expected_status": t.expected_status,
                    "qa_approved": t.qa_approved,
                    "qa_approval_comment": t.qa_approval_comment,
                    "discrepancy": t.discrepancy,
                    "issues": t.issues,
                    "prs": [
                        {
                            "number": p.number,
                            "title": p.title,
                            "state": p.state,
                            "url": p.url,
                            "repo": p.repo,
                            "is_merged": p.is_merged,
                            "deployments": [
                                {
                                    "workflow": d.workflow_name,
                                    "run_url": d.run_url,
                                    "build": d.build_status,
                                    "dev": d.dev_deploy_status,
                                    "prod": d.prod_deploy_status,
                                    "service": d.service_name,
                                    "resource_type": d.resource_type,
                                    "gcp_dev_commit": d.gcp_dev.commit_sha if d.gcp_dev else None,
                                    "gcp_prod_commit": d.gcp_prod.commit_sha if d.gcp_prod else None,
                                    "gcp_dev_match": gcp_match_status(d.gcp_dev, p.merge_commit),
                                    "gcp_prod_match": gcp_match_status(d.gcp_prod, p.merge_commit),
                                }
                                for d in p.deployments
                            ],
                        }
                        for p in t.prs
                    ],
                }
                for t in task_statuses
            ],
            indent=2,
        )
    else:
        output = generate_markdown_report(
            task_statuses,
            list_name,
            repos,
            not args.skip_gcp,
            args.gcp_dev_project,
            args.gcp_prod_project,
            args.gcp_region,
        )

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if not args.quiet:
            print(f"Report written to: {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
