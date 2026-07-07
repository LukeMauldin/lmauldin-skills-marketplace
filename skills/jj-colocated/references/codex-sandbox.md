# Codex Sandbox Guidance for jj

Use this reference only when the active agent harness is Codex.

Codex `workspace-write` intentionally protects repo metadata such as `.git/`,
`.agents/`, and `.codex/` even when the working tree is writable. In a colocated
jj repo, many jj mutations update `.git` or jj operation metadata and will fail
under the normal sandbox before succeeding with approval.

Keep read-only inspection sandboxed:

- `jj st`
- `jj --no-pager diff`
- `jj --no-pager log`
- `jj --no-pager show`
- `jj --no-pager bookmark list`

Escalate metadata mutations on the first attempt with
`sandbox_permissions = "require_escalated"` so
`approvals_reviewer = "auto_review"` can review them before sandbox denial:

- `jj git init --colocate`
- `jj git fetch`
- `jj new`
- `jj commit`
- `jj rebase`
- `jj squash`
- `jj abandon`
- `jj restore`
- `jj op restore`
- `jj bookmark ...`
- `jj file untrack`
- `jj git push`

Use concise justifications and narrow prefix rules, such as:

- `["jj", "commit"]`
- `["jj", "bookmark"]`
- `["jj", "git"]`
