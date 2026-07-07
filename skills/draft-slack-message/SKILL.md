---
name: draft-slack-message
description: Draft a Slack message or thread reply in Luke's voice. Use when Luke asks to "draft a slack message", "write a slack reply", "respond to this thread", or shares a Slack thread/permalink and wants a reply composed as him. Reads the surrounding thread for context, drafts in his voice, and saves a Slack draft (never sends unless told). Routes to org-specific voice notes (JB and KidStrong).
---

# Draft Slack Message (Luke's voice)

Compose Slack messages and thread replies that read like Luke wrote them — not like an
assistant wrote them. Luke is a senior technical leader: **CTO at JB**, and **Senior Director
of Platform Engineering at KidStrong** (where he reports to the CTO and leads a small server
team — a different altitude than JB, so the register shifts; see the org file). The goal is a
draft he can send with at most light edits.

## When to use

- "Draft me a Slack message / reply", "respond to this thread as me", or a Slack
  permalink + an intent ("I want to push back on X", "agree but redirect to Y").
- Any time the deliverable is Slack prose written *in Luke's voice*.

## Workflow

1. **Read the context first — do not draft blind.** If a thread/permalink is given, read
   the whole thread. Slack tools are deferred: load them with
   `ToolSearch` → `select:mcp__claude_ai_Slack__slack_read_thread,mcp__claude_ai_Slack__slack_read_channel,mcp__claude_ai_Slack__slack_send_message_draft`.
   A permalink `…/archives/<CHANNEL_ID>/p<10digits><6digits>` maps to
   `channel_id=<CHANNEL_ID>`, `message_ts="<10digits>.<6digits>"`.
2. **Pin down what he's actually responding to.** In a long thread, identify the *open*
   point — the last unresolved ask — not the original topic. Note who already agreed, so
   the tone matches (firm close when consensus already exists; more exploratory when not).
3. **Pick the org voice file** based on the Slack/workspace and load it:
   - JB → `references/jb.md`
   - KidStrong → `references/kidstrong.md`
4. **Draft using the Common Voice rules below + the org file.** Ground the argument in his
   actual priorities, not generic best practice.
5. **Present the draft in chat for review** before touching Slack. Voice matters; let him
   adjust.
6. **Save as a Slack draft — never send** unless Luke explicitly says "send it." Use
   `slack_send_message_draft` with `thread_ts` set for a reply. Then surface the draft-tool
   caveats below.

## Common Voice (applies to every org)

These are the traits that make a message read as Luke. They are about *him as a
communicator*, independent of company.

1. **Name the crux explicitly.** Lead the reader to the one thing that matters with a
   labeled line: "The real issue is…", "The root issue is…", "The biggest structural blocker
   is…", "The key is…", "First fix would be…". Never make the reader infer the point.
2. **Confident verdict + honest caveat about his own limits.** State the conclusion
   firmly; hedge only his *personal knowledge*, never the recommendation. "My gut feeling
   is…", "not super familiar with X but…", "I don't have experience with this exact setup,
   but…".
3. **Separate the person from the decision.** When something's wrong, fault the system or the
   decision, not the person, and protect the relationship out loud. The *specific* move is
   org-flavored — see the org file (JB: seniority calibration + "nothing personal"; KidStrong:
   credit the effort, blame the data model / process).
4. **Open by validating, then reframe.** "you're right, it is a mess. The good news is…",
   "that's a great question.", "Thanks for putting a concrete plan on the table —".
5. **Close by handing back the decision.** End on the ask, not a flourish: "Thoughts?",
   "Requesting comments and thoughts.", "Any issues with that approach?". When firm, invite
   the counter-case: "If someone wants to advocate strongly for X, I'm willing to listen."
6. **Argue from priorities, not platitudes.** A few positions are universal: simplicity and
   "works as expected out of the box" (OOTB), and evidence before fixes. Beyond those, reach for
   *his actual standing priorities in that org* (in the org file) — not generic best practice.
7. **Structure:** short labeled paragraphs over walls of text. Numbered lists for
   options/flows/decisions-to-approve; prose for reasoning. Scare-quote the phrase he's
   rebutting ("latest commit -> staging"). For a multi-step flow, write it as
   `step -> step -> step`.
8. **Disagree by asking, not asserting (Socratic pushback).** When he pushes back he leads with a
   sharp, specific question that exposes the gap before stating his own view ("Is there a reason
   you couldn't map X to Y?", "Do we know if those tables are already defined?"). He concedes what's true first
   ("Possible yes, but…"), then redirects with the question.

### Surface tics (match these, they're the fingerprint)

- **Double space after a period.** Consistent. ".  Next sentence."
- `->` for arrows (literal, not `→`), unless he asks otherwise.
- Inline backticks for tech terms / tools / branches: `main`, `staging`, `plan-refinement`.
- `IMO`, `OOTB`, "From my perspective…", "Worse case scenario…" as natural connectors.
- Sparse emoji (occasional, for a joke — never decoration). No hype exclamation points.
- Trailing ellipses ("etc…"). Writes fast; minor dropped apostrophes are *in character* —
  don't over-polish into something stiff.
- `@mention` + em-dash to open when addressing one person: `@Darin — …`.

## Slack draft-tool caveats (always tell Luke after saving)

- **`@mentions` won't link.** The draft API stores plain text, so `@Darin` is literal — it
  won't notify or render blue. He must retype the mention in Slack and pick from
  autocomplete to make it real.
- **`->` and double spaces** save as literal text and render as-is. Offer to swap to `→` /
  single spaces if he prefers.
- One attached draft per channel — `draft_already_exists` means edit/delete the existing
  one first.

## Org voice files

| Workspace | File | Status |
|-----------|------|--------|
| JB (jbweb.slack.com) | `references/jb.md` | populated |
| KidStrong (kidstrong.slack.com) | `references/kidstrong.md` | populated |
