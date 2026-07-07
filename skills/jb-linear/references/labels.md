# JB Web Linear Labels

Canonical reference for the labels this skill applies and how to approach work under each.

**Two sources of truth, split by role.** Linear owns label *existence and naming* — resolve the live set with `list_issue_labels` before any mutation, and trust it over this file if a name has drifted. This file owns **which groups the skill may apply** and the **engineering approach** each Dev Type implies — content Linear does not carry.

`list_issue_labels` returns every label Linear knows — the Dev Type and Dev Area groups, the standalone Security label, and many PM, workflow, and client groups the skill does not touch. Only the groups documented below are in scope.

## Apply Policy

Apply labels only from these groups; if the right one is even slightly ambiguous, leave it unset rather than guess:

- **Dev Type** — the primary nature of the work.
- **Dev Area** — marks where the work lands.
- **Security** — standalone; add it *in addition* to the Dev Type and/or Dev Area when the issue touches security.

Do not apply any other label — not the PM/workflow/client groups (Who, Source, Tier/Severity/Effort, Client Engagement, Review Type, JB Client List, Cancelled Issue Type, Site Hardening Work Type), and not any ungrouped or team-specific label — unless the user explicitly asks. Those are not engineering classification.

## Dev Type

The kind of work. Pick the one that names the issue's dominant intent.

| Label | When | Approach |
|-------|------|----------|
| **Bug** | Something works incorrectly | Reproduce → minimize → hypothesize → fix. Resist patching before you have a reliable repro and a root-cause hypothesis. Record the root cause in the resolution, not just the patch. |
| **Feature** | New functionality or capability | Brainstorm the design space first. Slice vertically — ship the thinnest valuable cut, then iterate. Separate load-bearing from nice-to-have before committing. |
| **Improvement** | Enhancement to an existing feature | Identify what changes and what stays; don't break existing flows. Read the call sites — an improvement that changes a contract is a migration, not an improvement. |
| **Tech Debt** | Refactor, cleanup, architecture | Audit, propose, scope. High-impact, low-risk first. Understand callers before refactoring — blast radius is the bug source. |
| **Dedupe** | Collapse duplicated code | Quantify the duplication before refactoring — ad-hoc reads overestimate it. Collapse only when the variation is genuinely incidental; three similar lines often beat a premature helper. |
| **Performance** | Make something faster or lighter | Measure first. Establish a baseline, profile to find the *actual* bottleneck, optimize the dominant cost, then re-measure against the same baseline to prove the gain and confirm no correctness regression. |
| **Maintenance** | Dependency updates, routine upkeep | Verify before updating: read changelogs for breaking changes, run tests after, check transitive dependencies. Routine ≠ low-risk. |
| **Testing** | Test additions or improvements | Test at the right level. Integration tests beat mocked unit tests when you can run the real thing. Test behavior, not implementation. |
| **QoL** | Small quality-of-life fix | Find the actual annoyance and make the smallest fix that resolves it. Don't gold-plate — these are meant to be cheap. |
| **Spike** | Timeboxed investigation | Reduce uncertainty, don't ship product code. The output is knowledge — a recommendation, a proof-of-concept, a decision. Close with the findings so the follow-up work is well-scoped. |

## Dev Area

Where the work lands. Orthogonal to Dev Type, but single-select within itself — apply one when it adds signal; skip when the area is obvious or the work spans everything.

| Label | Scope |
|-------|-------|
| **Frontend** | Frontend-specific work |
| **Backend** | Backend-specific work |
| **Infra** | Infrastructure, deployment, environments |
| **API-Contracts** | OpenAPI / interface-contract changes |
| **Docs** | Documentation. Capture the *why* and the constraints, not the *what*; be audience-aware (internal docs assume context, external don't); don't restate what well-named identifiers already say |
| **IA** | Information architecture — site/content structure |

## Security

Standalone label, applied alongside the Dev Type (and Dev Area, if set). When present, threats and mitigations come first. Validate inputs at trust boundaries. Do not disable a safety check to make something work.

## Cross-cutting

- **Docs shipped with a change**: when an issue is both a Dev Type and touches documentation, ship the doc with the change, not after.
