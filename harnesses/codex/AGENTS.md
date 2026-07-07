**User Profile**

- Assume the user is a senior software engineer with substantial production experience.
- Default to concise, high-signal responses.
- Skip beginner explanations unless the user asks for them.
- Prefer tradeoffs, constraints, failure modes, and implementation details over tutorials.
- Treat vague proposals as hypotheses to test, not instructions to accept blindly.
- Simplify the explanation when helpful, but do not simplify away the technical content.

**Applicability**

- Apply defaults, CLI bias, behavioral guardrails, documentation style, version-control (jj) habits, and non-destructive engineering habits by default.
- Apply Python, Gcloud, and PR-publishing guidance only when the task explicitly involves those areas. Version-control guidance (Jujutsu / jj) applies whenever a task makes changes in a git repo; skip it only for read-only work.
- For analysis-only, prompt-writing, personal-document, or read-only codebase tasks, skip environment and PR preflight unless needed.

**Defaults**

- Primary languages: Go, Rust
- Secondary languages: Python, TypeScript
- Environment: macOS 26.3; interactive shell `fish`; use `zsh` 5.9 for new scripts unless the repo says otherwise; maintain `bash` 3.2 compatibility when needed.
- Tooling: assume latest stable via Homebrew (`brew`) or `mise`. In Node.js/TypeScript project directories, run `mise use` when a `.mise.toml` or `.tool-versions` file is present.

**CLI Bias**

- Preferred tools: `jq` (JSON), `gh-jb`/`gh-ks` for account-specific GitHub CLI, `gh` only when the target account is irrelevant, `gcloud` (Google Cloud), `python3.14`, `markdownlint-cli2` (Markdown linting).
- Available modern tools often include `rg`, `fd`, `bat`, `eza`, `sd`, `ast-grep`, `jq`, `gron`, `xh`, and `difft`. Use them when they materially improve speed, accuracy, or readability; otherwise use the simplest non-interactive command for the task. For file reads, use `rg` for search, `bat --line-range` when line-focused output is useful, and `sed -n`/`cat` when they are simpler. Do not use `bat`, `eza`, or fallback chains like `bat ... || cat ...` solely for style.
- `rg` already respects `.gitignore`; do not add `--include` flags unless excluding a tracked path.
- For text substitutions, prefer `sd` over `sed` when the pattern is a literal or simple regex replace — fewer escaping bugs.
- For code-shape searches (regex alternations spanning language constructs), prefer `ast-grep` over `rg` to avoid false positives in strings and comments.
- JSON: `jq` for structured queries; `gron` to flatten when the schema is unknown. HTTP: `xh` for JSON endpoints; `curl -sS` (keep stderr) as fallback.
- Structural code diffs: `difft`. Line diffs already go through `delta` via git config.
- Avoid `cd <dir> && <cmd>` for one-shot commands — pass the path to the command (`rg foo <dir>`, `pnpm -C <dir> test`).
- For shell commands, write POSIX-compatible `sh`/`zsh`/`bash` syntax unless a tool call explicitly selects another shell. The interactive shell may be `fish`, but Codex command execution does not understand fish syntax by default. Use `for x in …; do …; done` and `if …; then …; fi`; never fish's `for…end` / `if…else…end`. Don't assign zsh read-only names (`status`, etc.).
- If a tool is unavailable, suggest installation (e.g., `brew install fd`) or a POSIX fallback.

**Account-Specific Tooling**

- This machine has isolated JB and KidStrong profiles. Do not assume default Cursor, GitHub CLI, or GitHub SSH state is correct.
- JB repos live under `/Users/lukemauldin/code/github.com/jb-web-dev`; use `gh-jb` for GitHub CLI and SSH remotes with `github.com-jb`.
- KidStrong repos live under `/Users/lukemauldin/code/github.com/KidStrong`; use `gh-ks` for GitHub CLI and SSH remotes with `github.com-ks`.
- For Cursor session inspection, use `cursor-session-inspector` with `--cursor-profile jb` or `--cursor-profile ks` when the profile is not inferable from the repo path. Ask which profile to inspect if ambiguous.

**Behavioral Guardrails**

- Do not default to agreement. Treat user proposals as hypotheses and challenge them when they are underspecified, risky, or likely incorrect.
- Prioritize correctness over tone alignment. If a request is plausible but weakly justified, surface what is uncertain and what evidence is needed.
- When a request is likely suboptimal, call it out directly with concise alternatives.
- Prefer counter-check phrasing for design and implementation decisions: "This works if X/Y assumptions hold; if not, breakage occurs because ...".
- In final responses, if intent is unclear, choose clarification and scope narrowing over silent acceptance.

**Documentation Style**

- Tone: use a clear, formal, and structured tone suitable for engineers, PMs, and QA. Avoid jargon unless defined.
- Structure: produce well-structured Markdown with sections appropriate to the document type, such as Overview, Requirements, Design, Plan, and Risks.
- Content principles:
  - Focus on the why over the what.
  - Make content reusable and shareable; include examples, glossaries, or references when they improve clarity.
  - State reasoning and assumptions when they materially affect the document.
- Requirements docs: emphasize clarity, specificity, and testability. Use SHALL, SHOULD, and MAY where appropriate.
- Design and plan docs: emphasize modularity, scalability, and alignment with project goals. Include Mermaid diagrams when they materially clarify a workflow or architecture.

**Conditional Guidance**

- For Python implementation, environment setup, dependency installation, or interpreter mismatch diagnosis, use the `python-engineer` skill.
- Skill-specific guidance in this global profile is personal-profile guidance. Do not copy it into repository-level `AGENTS.md` files unless the skill is available and intended for that repo.

**Codex Enforcement Surfaces**

- Keep `AGENTS.md` for durable judgment, workflow preferences, repository conventions, and verification expectations.
- For mechanical command policy, prefer Codex rules under `~/.codex/rules/` or a project `.codex/rules/` directory: use rules to allow, prompt, or forbid specific command prefixes outside the sandbox.
- For lifecycle automation or checks that need to inspect prompts, tool calls, approval requests, compaction, subagent starts/stops, or turn completion, prefer Codex hooks in `hooks.json` or `[hooks]` config. Keep hooks narrow and expect changed non-managed hooks to require trust review.
- Use `codex execpolicy check --pretty --rules <file> -- <command>` to test rules before relying on them.

**Gcloud**

- Prefer `gcloud`, `bq`, and `gsutil` directly.
- If path resolution fails, verify with:
  - `command -v gcloud`
  - `command -v bq`
  - `command -v gsutil`
- If a direct path is needed on this machine, use:
  - `/Users/lukemauldin/google-cloud-sdk/bin/gcloud`
  - `/Users/lukemauldin/google-cloud-sdk/bin/bq`
  - `/Users/lukemauldin/google-cloud-sdk/bin/gsutil`
- If SDK shell setup is needed explicitly, source:
  - `/Users/lukemauldin/google-cloud-sdk/path.zsh.inc`

**Version Control — Jujutsu (jj), colocated mode**

- Default VCS for owned work repos is Jujutsu (`jj`) in colocated mode (`.jj/` alongside `.git/`). Drive version-control *mutations* through jj; use git only for read-only inspection, and `gh-jb`/`gh-ks` for PRs/CI. `jj git push` uses the existing git remote, so the account-specific SSH host alias (`github.com-jb` / `github.com-ks`) is respected automatically.
- Auto-setup: before making changes in an owned work git repo that lacks `.jj/`, run `jj git init --colocate` at the repo root, then `jj git fetch`. Skip for read-only tasks and do not colocate third-party, vendor, temp, or ambiguous-ownership repos without asking. After colocation, git is in detached HEAD — normal for jj, do not "fix" it.
- In a colocated repo, route commits, rebases/restacks, undo, and stack maintenance through jj. **Load the `jj-colocated` skill before any jj operation beyond a plain `jj commit`/`jj describe`** — rebase, integrating an advanced `main`, reconciling a stack, parallel workspaces, or recovery — **including mid-conversation when a jj need arises after non-jj work**. Don't improvise multi-commit jj topology from memory.
- In Codex `workspace-write`, repo metadata such as `.git/`, `.jj/`, `.agents/`, and `.codex/` may be protected even when the working tree is writable. For colocated jj, run metadata-mutating jj commands with `sandbox_permissions = "require_escalated"` on the first attempt so `approvals_reviewer = "auto_review"` can review them before the sandbox blocks metadata writes. Read-only jj inspection stays sandboxed when the working tree is clean.
- After file edits, even `jj st`, `jj diff`, or `jj log` may snapshot the working copy and write metadata. This is acceptable when needed because jj snapshots are inspectable and recoverable with `jj undo`; use `--no-integrate-operation` only when avoiding metadata writes is more important than snapshotting current edits.
- To work on top of an existing bookmark: `jj new <bookmark>` — **not `jj edit <bookmark>`** (immutable error on pushed tips).
- To put your branch on top of an advanced `main` (base PR merged, *or a sibling PR merged while your base is still unmerged*): `jj git fetch && jj rebase -b @ --onto 'trunk()' --skip-emptied`. **Never merge to catch up** (`jj new @ main@origin` / `git merge main`) — forces painful later linearization (`jj undo` + `jj rebase -s`).
- Before rebasing/rewriting a bookmark you did **not** author, verify ownership (`gh-jb`/`gh-ks pr view <n> --json author`, `git log -1 --format=%ae <tip>`). Pushing the rewrite force-updates shared history.
- Agent-safe jj usage (interactive modes hang the agent):
  - `--no-pager` on output; `-m "..."` for messages — never bare `jj describe`/`jj commit`.
  - Escalate jj metadata mutations up front: `jj git init --colocate`, `jj git fetch`, `jj new`, `jj commit`, `jj rebase`, `jj squash`, `jj abandon`, `jj restore`, `jj op restore`, `jj bookmark ...`, `jj file untrack`, and `jj git push`. These write `.git` or jj operation metadata that `workspace-write` protects; auto-review should make the decision, not a failed first attempt.
  - Never: `jj split`, `jj squash -i`, `jj resolve`, `jj diff -i`. Edit conflict markers directly, then `jj st`.
  - Diffs: `jj --no-pager diff --git`. Reference commits by **change ID**, not SHA — except when `(divergent)` (operate by SHA; see `jj-colocated` skill).
  - Rebase destination: `-o`/`--onto` (canonical); `-d` is a legacy alias (same flag, still works on 0.42). Prefer `--onto`. Selectors: `-b` whole branch, `-s` subtree, `-r` single rev only.
  - After `jj commit -m`, bookmark `@-` not `@` (`jj bookmark move feat --to @-` or `jj bookmark advance feat`).
  - Do not use `jj git push --allow-new` — removed in 0.42. `jj git push --bookmark <name>` suffices.
  - Read-only inspection without WC snapshot: `--no-integrate-operation` (jj ≥ 0.41).
- An open PR tracks `<bookmark>@origin`, not local `@` — use `jj bookmark list`, not `git status` alone.
- Recovery: `jj undo`, or `jj op restore <op-id>` (find via `jj --no-pager op log`).
- No `.jj/` + read-only task → git as normal; do not init jj.
- Do not create commits, move bookmarks, push, or open PRs unless explicitly requested. When requested, use jj for local VCS mutations and `gh-jb`/`gh-ks` for PR operations as appropriate.

**Git And PRs**

- Apply this section only when creating a PR, publishing a branch, or managing parallel working copies (jj workspaces).
- Infer the ticket ID from the branch name when possible; ask only when it is missing or ambiguous.
- Ask whether to include all branch commits in the PR description only when the branch contains unrelated commits or the intended PR scope is unclear.
- For stacked/dependent PRs (jj, colocated — preferred): see the jj reconcile step in the Version Control section (`jj git fetch` then `jj rebase -b @ --onto 'trunk()' --skip-emptied`, then `gh-ks pr edit <child-bookmark> --base main`).
- Git fallback (only if a repo is genuinely not colocated): reconcile the dependent with `git rebase --onto origin/main <parent-tip-sha-or-tag> <dep-branch>` — never `git merge origin/main`. After a squash-merge, the squash commit and the rebased copies of the parent's commits are content-equivalent but commit-distinct, so `git merge` produces large duplicate-history conflict piles. When using this fallback, tag the parent tip first (`git tag --force pre-parent-merge/<dep-branch> origin/<parent-branch>`) so the `--onto` reference is one token.
- Parallel working copies use jj workspaces, not `git worktree` (jj does not support git worktrees; mixing them is unsupported and untested). Create with `jj workspace add <path> -r 'trunk()'` — the `-r` is required to base it on trunk, because by default a new workspace shares the *current* `@`'s parents (a sibling of your in-progress work), not your work. Default location when none is specified:
  - `/Users/lukemauldin/code/worktrees/{org_name}/{repo_name}/{workspace_name}_{model_name}_{random_4_digit_id}`
- Before assuming workspace paths, run `jj workspace list`. Caveat: an added workspace has `.jj/` but no `.git/`, so `git` and `gh` do not work inside it — `jj git push`/`jj git fetch` work from the workspace (shared repo backend), but run `gh-jb`/`gh-ks` PR commands from the main colocated workspace. When done, `jj workspace forget <name>` then delete the directory. If a workspace reports a stale working copy, run `jj workspace update-stale`.
- When using GitHub CLI in JB or KidStrong repos, prefer `gh-jb` or `gh-ks` respectively; use plain `gh` only after verifying the active account is intentional.
- When passing multiline text to `gh-jb`, `gh-ks`, or `gh` flags, use ANSI-C quoting instead of `\n` in a normal quoted string.
- Preferred form:
  - `gh-ks pr create --body $'line1\nline2'`
