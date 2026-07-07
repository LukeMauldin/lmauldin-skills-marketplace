# Partners Real Estate Initiation

> **DEPRECATED 2026-06-19.** The per-repo `.linear/` model supersedes these central docs, but this project has no code repository to host `.linear/`. It remains here until it acquires a repo or is retired. Keep edits minimal.

## Project Defaults

| Field | Value |
|-------|-------|
| **Primary Team** | Business Development (key: `BIZDEV`) |
| **Project** | Partners Real Estate Initiation |
| **Project ID** | `d88dcc8a-70cd-4eca-8d2e-bff3d27a169a` |
| **Project Slug** | `partners-real-estate-initiation-d04aca766c54` |
| **Client** | Partners Real Estate |
| **Default Assignee Policy** | Ask user; use assignment conventions by task type |
| **Project Lead** | Adam Kecskes (adam@jbweb.com) |
| **Default Priority Policy** | No default priority; this project typically does not use priorities |
| **Default Status** | Backlog |
| **Initiative** | _(none linked to this initiation project)_ |
| **Project State** | Canceled (since 2026-03-02) |
| **Last Verified Snapshot** | 2026-05-24 UTC |

## Primary Team Statuses

| Status | Type |
|--------|------|
| Backlog | backlog |
| Todo | unstarted |
| In Progress | started |
| In Review—Internal | started |
| In Review—Client | started |
| Done | completed |
| Canceled | canceled |
| Duplicate | duplicate |

## Secondary Teams

| Team | When to Use | Notes |
|------|-------------|-------|
| PartnersRE (`PRE`) | Post-signature technical delivery work | PRE order includes `In Review` before `Todo`/`In Progress` in current config; verify current PRE usage at runtime. |

## Label Guidance

This project uses proposal-status labels as secondary workflow indicators.

| Scope | Labels / Rules |
|------|-----------------|
| Workspace (Proposal Status) | `Preparing`, `Pending`, `Requires Client Input`, `Draft sent to Client`, `Docusign sent to Client` |
| Team (`BIZDEV`) | Use BIZDEV statuses plus proposal-status labels for lifecycle clarity |
| Runtime check | Confirm currently used labels with `list_issues` before updating existing issues |

## Repository Mapping

| Repository | Pattern |
|------------|---------|
| N/A | No code repository yet; this is a pre-sales/initiation project. |

## Verification and Refresh

- Snapshot date: 2026-05-24 UTC
- Refresh current issue/state distribution with:
  `list_issues` (`team: "Business Development"`, `project: "d88dcc8a-70cd-4eca-8d2e-bff3d27a169a"`, paginate)
- For delivery-transition checks, also query `team: "PartnersRE"` for the same project ID.

## Project Notes

- Project was Canceled on 2026-03-02. New issue creation here should be confirmed explicitly with the user; default to creating new work in another active project unless the user is intentionally adding historical context.
- Non-engineering project: this is a BIZDEV proposal pipeline, not a software delivery project.
- Uses parent-child issue hierarchy for the proposal lifecycle: parent issue (proposal) with children (draft, review, DocuSign).
- Assignee conventions by task type: PM/review -> Adam Kecskes; technical/content -> Joe Conley; NDA/logistics -> Owen Goode; finance/DocuSign -> pat@jbweb.com.
- External stakeholder: Stuart Showers (SVP Data & Technology at Partners Real Estate).
- Related future project: "Review Agent" (Backlog, led by Joe Conley, on ENG + PRE teams) — the actual technical delivery project.
- Linked resources: Proposal Prep (Google Doc), Initial SOW (Google Doc), [partnersrealestate.com](https://partnersrealestate.com/)
