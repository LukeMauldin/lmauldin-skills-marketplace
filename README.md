# Mauldin Skills

Canonical source of truth for personal agent runtime assets.

## Layout

- `skills/` contains one directory per skill, each with a `SKILL.md`.
- `harnesses/` contains user-level agent instruction files, kept per harness because they intentionally differ.
- `manifests/all-skills.txt` lists the canonical deployed skill set.
- `manifests/default-linked.txt` lists skills linked into every agent.
- `manifests/optional.txt` lists retained skills that are not linked by default.
- `manifests/removed.txt` lists skills that should be removed from runtime roots.
- `scripts/audit-skills` compares deployed agent skill roots against this repo.
- `scripts/link-skills` replaces deployed non-system skill directories with symlinks.
- `scripts/audit-agent-files` compares deployed user-level agent instruction files against this repo.
- `scripts/link-agent-files` replaces deployed user-level agent instruction files with symlinks.
- `upstreams/README.md` records upstream precedence and source commits.

## Policy

- Agent-owned `.system` skills are not managed here.
- Copilot skills are out of scope.
- Only `manifests/default-linked.txt` is linked into runtime agent skill roots.
- Optional skills stay in this repo but are removed from runtime skill roots unless manually linked.
- Removed skills are backed up out of runtime roots and are not retained in `skills/`.
- User-level agent instruction files are managed as per-harness files, not generated from a shared template.
- Project-level `AGENTS.md` and `CLAUDE.md` files are out of scope.
- OpenCode uses `~/.config/opencode/skills` as a symlink to the shared `~/.agents/skills` facade.
- Same-name skills from `jb-web-dev/llm-skills` are mirrored from that upstream.
- Same-name skills from `pocock-skills` are mirrored from that upstream after JB upstream precedence.
- Local extras are dropped when an approved upstream has the same skill name.

## Deployment

Run audits before linking:

```sh
zsh scripts/audit-skills
zsh scripts/link-skills --dry-run
zsh scripts/audit-agent-files
zsh scripts/link-agent-files --dry-run
```

Deploy with:

```sh
zsh scripts/link-skills
zsh scripts/link-agent-files
```
