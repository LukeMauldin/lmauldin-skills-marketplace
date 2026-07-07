# Upstreams

This repo is a curated mirror, not the original authoring location for every skill.

## Precedence

1. Excluded skills are omitted even if present upstream.
2. `~/code/github.com/jb-web-dev/llm-skills` wins for same-name skills.
3. `~/code/playground/pocock-skills` wins for same-name skills not owned by `llm-skills`.
4. Remaining skills come from local Claude/Codex/Pi/Cursor deployments by manual selection.

## Source Revisions

- `~/code/github.com/jb-web-dev/llm-skills`: `b3d2eb8`
- `~/code/playground/pocock-skills`: `16a2a5c`

## Excluded

- `caveman`
- `diagnose`
- `sentry-cli`
- `write-a-skill`
- `zoom-out`
- `linear-team-setup`
- `tavily-extract`
- `tavily-research`
- Copilot-only skills

## Manual Local Choices

- `clickup-engineer`: majority local copy from Claude/Codex/Pi/Cursor KS; Qwen was missing scripts and coverage docs.
- `glofox-api`: Codex local skill with Claude's newer `references/openapi.yml`.
- `jj-colocated`: Codex/Claude local copy with jj 0.42 guidance and Codex sandbox reference.
