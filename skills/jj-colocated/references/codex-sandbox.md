# Codex Sandbox Guidance for jj

Use this reference only when the active agent harness is Codex.

Codex `workspace-write` intentionally protects repo metadata such as `.git/`,
`.agents/`, and `.codex/` even when the working tree is writable. In a colocated
jj repo, many jj commands update `.git` or jj operation metadata and will fail
under the normal sandbox before succeeding with approval.

Important: "read-only" jj commands are only metadata-read-only when jj does not
need to snapshot the working copy. After file edits, even `jj st`, `jj diff`, or
`jj log` can first snapshot pending changes into `.git/objects`. This is usually
acceptable from a jj-safety perspective because status snapshots are easy to
inspect and recover with `jj undo`, but Codex may block the metadata write before
the status/diff/log output appears.

Keep clean-working-copy inspection sandboxed:

- `jj st`
- `jj --no-pager diff`
- `jj --no-pager log`
- `jj --no-pager show`
- `jj --no-pager bookmark list`

When the working tree may be dirty and the harness cannot or should not write jj
metadata, use non-integrating forms so jj does not snapshot or import/export repo
state:

- `jj --no-pager --no-integrate-operation st`
- `jj --no-pager --no-integrate-operation diff --git`
- `jj --no-pager --no-integrate-operation log`
- `jj --no-pager --no-integrate-operation bookmark list`

Do not combine file edits and jj commands in one shell command in Codex. For
example, avoid:

```bash
git apply patch.diff && jj st
patch -p1 < patch.diff && cargo fmt --all && jj squash
```

If the jj command fails to snapshot after the file edit succeeded, the working
tree is left partially changed and the agent may not be able to inspect or squash
without metadata write approval. Apply/edit files in a separate tool call when
the session has already shown metadata-write problems; otherwise `jj st` after an
edit is a reasonable default because the snapshot is recoverable through jj.

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

Some Codex Granular approval harnesses reject explicit escalation requests before
auto-review, with output like:

```text
you cannot ask for escalated permissions if the approval policy is Granular(...)
```

Treat that as a harness limitation, not a jj failure and not something retrying
with `sandbox_permissions = "require_escalated"` will fix. In that state:

- Stop issuing metadata-writing jj commands from Codex.
- Preserve any applied file edits as patches under a writable temp directory.
- Report the exact current state: current bookmark/parent if known, whether the
  working tree has unsnapshotted edits, and where the patch files are.
- Ask the user to approve jj metadata writes for the session.

If the user grants approval in chat, retry without
`sandbox_permissions = "require_escalated"`; in these Granular harnesses, chat
approval may unlock the default sandbox path while explicit escalation continues
to be rejected. Start with the smallest required jj-only metadata write, then run
`jj --no-pager st`. If plain jj commands still hit `Operation not permitted`, or
permission succeeds intermittently, stop and continue with the handoff path: ask
the user to run the required jj operations locally or restart/adjust the session
with a tool configuration that permits metadata writes.
