# Mauldin Skills

Canonical source of truth for personal agent skills.

## Layout

- `skills/` contains one directory per skill, each with a `SKILL.md`.
- `manifests/all-skills.txt` lists the canonical deployed skill set.
- `scripts/audit-skills` compares deployed agent skill roots against this repo.
- `scripts/link-skills` replaces deployed non-system skill directories with symlinks.
- `upstreams/README.md` records upstream precedence and source commits.

## Policy

- Agent-owned `.system` skills are not managed here.
- Copilot skills are out of scope.
- Same-name skills from `jb-web-dev/llm-skills` are mirrored from that upstream.
- Same-name skills from `pocock-skills` are mirrored from that upstream after JB upstream precedence.
- Local extras are dropped when an approved upstream has the same skill name.

## Deployment

Run audits before linking:

```sh
zsh scripts/audit-skills
zsh scripts/link-skills --dry-run
```

Deploy with:

```sh
zsh scripts/link-skills
```
