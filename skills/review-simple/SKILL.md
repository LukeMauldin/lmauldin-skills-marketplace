---
name: review-simple
description: Review a GitHub pull request with a concise, structured code review using `gh` CLI output and local repo context. Use when the user asks for a PR review, code review, review summary, or risk assessment for a GitHub pull request, especially when they provide a PR number or want to choose from currently open PRs.
---

# Review Simple

Review GitHub pull requests by inspecting the PR metadata and diff, then produce a concise but thorough code review. Prefer findings that affect correctness, conventions, performance, testing, or security.

## Workflow

1. Parse the user arguments for a pull request number.
2. If no PR number is present, run `gh pr list` in the current repository.
3. Show the open PRs succinctly and ask the user which PR to review.
4. If a PR number is present, run `gh pr view <number>` to collect title, branch, author, status, and summary context.
5. Run `gh pr diff <number>` to inspect the code changes.
6. If the user provides a plan, spec, handoff, design doc, or phase document, read it early and determine the intended scope of the review:
   - If the document defines phases or milestones, identify which phase the reviewed change is supposed to implement.
   - If the document does not define phases, treat the whole documented scope as the intended scope of the review.
7. Use nearby repo context when needed to verify conventions or behavior, but stay focused on the changed code.
8. Produce the review in the format defined below.

## Review Priorities

Prioritize these areas:

- Code correctness
- Project conventions and style consistency
- Performance implications
- Test coverage and missing validation
- Security considerations

Treat the PR description as a claim, not proof. Verify in the diff whether the implementation actually matches the stated intent.

## Review Method

Read the diff with a reviewer mindset:

- Look for regressions caused by changed control flow, missing validation, incorrect assumptions, and partial updates.
- Check whether naming, structure, and patterns match the surrounding code rather than generic preferences.
- Call out missing tests only when the changed behavior creates risk that is not already covered.
- Note performance concerns only when the diff introduces meaningful extra work, broader queries, repeated allocations, or avoidable I/O.
- Note security concerns only when the diff changes trust boundaries, input handling, auth, secrets, or sensitive data exposure.
- If the user provided a plan/spec/handoff doc, review against the stated scope of the current phase or intended deliverable, not against the full end-state architecture unless the diff claims to deliver that full end state.
- Do not report missing later-phase behavior as a Finding when the plan explicitly defers it. Instead, place it under `Deferred By Design` unless the current change creates immediate incorrect behavior, a misleading public contract, or removes a prerequisite needed by later work.
- For infrastructure, plumbing, and rename-heavy changes, explicitly check for non-blocking review items that are easy to miss:
  - stringly-typed fields that mirror DB enums or CHECK-constrained values and could be modeled as typed enums/newtypes
  - new repositories/resolvers/adapters/ports that lack focused tests for happy path, negative path, and documented ordering or precedence rules
  - stale local variable names, log fields, comments, and helper names that still use old terminology after a public rename

If the diff is large, focus on the highest-risk files first and compress low-signal observations.

## Output Format

Format the response with these sections and bullet points:

- `Overview`
- `Findings`
- `Deferred By Design`
- `Code Quality And Style`
- `Non-Blocking Improvements`
- `Risks`

Within `Findings`, list concrete issues first, ordered by severity. Reference files and lines when possible. If there are no material findings, say so explicitly.

Within `Deferred By Design`, list gaps that are explicitly scheduled for later phases or otherwise intentionally out of scope for the reviewed change.

Within `Non-Blocking Improvements`, list type-safety improvements, focused test additions, naming consistency cleanup, and similar suggestions that would strengthen the code without constituting a bug or regression in the current scope.

Keep the review concise but thorough:

- Prefer short bullets over long prose
- Avoid repeating the PR description
- Distinguish confirmed issues from weaker concerns
- State assumptions briefly when the diff alone is insufficient

## Failure Handling

If `gh` is unavailable, not authenticated, or the PR cannot be read:

- State the blocker directly
- Include the command that failed
- Ask for the missing PR number or repo/auth fix only if needed to proceed

## Example Invocation

Use `$review-simple` to review PR `123`.
