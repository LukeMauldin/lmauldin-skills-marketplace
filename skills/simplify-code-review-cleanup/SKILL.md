---
name: simplify-code-review-cleanup
description: Use when the user wants a post-change cleanup pass over current edits. This skill reviews changed files for reuse opportunities, code quality issues, and efficiency problems, runs three parallel review agents when delegation is available, fixes worthwhile issues directly, and briefly summarizes what changed.
---

# Simplify Code Review Cleanup

## Overview

Use this skill after implementation work when the user wants a cleanup pass rather than a fresh feature build. The goal is to inspect the current diff, look for reuse, quality, and efficiency issues, fix the worthwhile ones directly, and keep the close-out short.

## Quick Start

1. Identify the review scope from git.
2. Capture one full diff and reuse it for every review pass.
3. Launch three review agents in parallel when delegation is available.
4. Aggregate findings, fix worthwhile issues directly, and skip low-value or false-positive findings without debate.
5. Summarize what was fixed, or state that the code was already clean.

## Workflow

### 1. Identify Changes

- If there are staged changes, inspect `git diff HEAD`.
- Otherwise inspect `git diff`.
- If the git diff is empty, review the most recently modified files the user mentioned or the files you edited earlier in the conversation.
- Keep the review focused on changed files and nearby reusable code, not a broad repo audit.

Practical shell pattern:

```bash
if git diff --cached --quiet; then
  git diff
else
  git diff HEAD
fi
```

### 2. Build the Shared Review Context

- Capture the full diff once and reuse that same diff for all review passes.
- If the diff is large, include the changed file list plus the relevant per-file patches so each review agent still has complete context.
- Add any user-supplied extra focus areas to every review brief.

### 3. Launch Three Review Agents in Parallel

Use `spawn_agent` only when subagent delegation is available and appropriate for the current harness. Launch all three agents concurrently and pass each one the same diff.

If subagents are unavailable, perform the same three reviews locally and continue to the fix phase.

#### Agent 1: Code Reuse Review

Prompt the agent to review the diff for reuse opportunities:

1. Search for existing helpers, utilities, or adjacent patterns that could replace newly written code.
2. Flag any new function that duplicates existing functionality and name the existing function or module to reuse.
3. Flag inline logic that should use an existing utility, especially string manipulation, path handling, environment checks, parsing, validation, and type guards.

#### Agent 2: Code Quality Review

Prompt the agent to review the diff for code quality issues:

1. Redundant state or derived values stored separately
2. Parameter sprawl instead of restructuring an API
3. Copy-paste with slight variation that should become a shared abstraction
4. Leaky abstractions or broken module boundaries
5. Stringly-typed code where constants, enums, or existing types should be used
6. Unnecessary JSX or layout wrappers when component props already solve the problem
7. Unnecessary comments that explain obvious behavior instead of non-obvious constraints

#### Agent 3: Efficiency Review

Prompt the agent to review the diff for efficiency issues:

1. Redundant computation, duplicate reads, duplicate requests, or N+1 work
2. Independent work done sequentially when it could run concurrently
3. Hot-path bloat in startup, request, job-loop, or render paths
4. Recurring no-op updates that should be guarded by change detection
5. Unnecessary existence checks before an operation that already returns a useful error
6. Memory risks such as unbounded collections, leaked listeners, or missing cleanup
7. Overly broad operations such as loading full files or datasets when only part is needed
8. If a meaningful performance improvement would require an API change, interface change, or other contract change, flag it as a deferred recommendation instead of something to implement immediately

### 4. Aggregate Findings

- Wait for all review agents to complete with `wait_agent`.
- Combine their findings into one working list.
- De-duplicate overlapping findings before editing.
- Separate findings into:
  - direct cleanup fixes that can be applied safely now
  - deferred recommendations that would require API, interface, or contract changes
- Treat findings as candidates, not mandates. Fix the worthwhile ones directly. Skip false positives or low-value changes without arguing with the review.

### 5. Fix Issues Directly

- Prefer the smallest defensible fix.
- Reuse existing code instead of introducing new abstractions unless the duplication clearly warrants it.
- Do not implement performance-driven API changes as part of this cleanup pass. Defer those and report them to the user for explicit approval or rejection.
- Preserve unrelated user changes.
- After edits, run the narrowest useful verification for the touched code when practical.

### 6. Close Out

- Briefly summarize what was fixed.
- Call out any deferred performance recommendations that would require API changes, with enough detail for the user to approve or reject them.
- If nothing worthwhile changed, say the reviewed code was already clean.
- Mention any verification you ran, or note if verification was not run.

## Agent Prompt Template

Use this shape for each spawned agent and swap in the role-specific review criteria:

```text
Review the attached diff only for <review area>.

Context:
- Repo: <repo or package>
- Focus: <reuse | quality | efficiency>
- Extra user focus: <optional>

Instructions:
- Use the full diff as the primary review scope.
- Search nearby files and shared utilities when needed to verify reuse opportunities.
- Return only concrete findings worth action.
- If a performance improvement would require an API or contract change, mark it as `deferred` and do not frame it as an immediate cleanup fix.
- For each finding, include:
  - severity: high | medium | low
  - disposition: fix-now | deferred
  - file/path
  - short explanation
  - specific fix suggestion
- If nothing worthwhile is found, say so explicitly.

Diff:
<full diff here>
```

## Codex Harness Notes

- The source prompt may refer to an "Agent tool". In Codex, adapt that to `spawn_agent` plus `wait_agent`.
- Prefer launching all three agents in parallel in a single round.
- Do not wait repeatedly by reflex. Start the agents, do any non-overlapping local work, then collect results when needed.
- If the user includes additional focus text after invoking the skill, append it to each review prompt and honor it in the cleanup pass.
