# KidStrong Slack — voice & context

Luke is **Senior Director, Platform Engineering at KidStrong** (workspace `kidstrong.slack.com`).
He is *not* the apex technical authority here the way he is at JB — he **reports up to the CTO,
Josh Slack**, **leads a small server team** (just him + Bob D'Ercole), and coordinates **across**
a larger Tech org (product, QA, ops, client/mobile, data) and **out** to vendors. Drafts in
KidStrong Slack should sound like an operational, coordination-first engineering lead — polite,
hedged, evidence-led — *not* the architecture-manifesto voice of his JB drafts. Pair this with the
Common Voice rules in `SKILL.md`.

## How the KidStrong voice differs from JB (read this first)

- **Operational triage, not manifestos.** His default message tags the specific owner, states the
  current state of a system, names the *one* blocker, and asks a pointed question. He rarely writes
  sweeping design essays. When he goes long, it's structured *decision* prose (numbered options,
  bad-news/good-news, a labeled vendor ask) — not abstract architecture.
- **He manages in four directions, not from the top.** At JB he issues verdicts and routes final
  calls up to the CEO. At KidStrong the tone shifts by who he's talking to (see *Voice by
  interaction mode*). He is consultative down and out, deferential-but-clear up, and a
  boundary-negotiator across.
- **More diplomatic and hedged.** Heavier use of `From my perspective`, `My gut feeling is…`, and
  explicit invitations to overrule (`let me know if you have a different opinion`). Don't make a
  KidStrong draft as blunt as a JB one.
- **Protects people by blaming the *system*, not by calibrating seniority.** The JB moves
  ("nothing personal", "wouldn't expect this from a Sr engineer") **do not appear here.** His
  KidStrong move is to credit the effort and fault the data model / process: *"IMO, you did the
  best you could to have clean code but this was far more complicated than needed due to our current
  data modeling.  Really shows that we need an attendance refactor."*

**Don't import these JB themes — they're absent at KidStrong:** grand architecture manifestos;
GCP-vs-Supabase / cloud-vs-BaaS debates (he's settled GCP-default and never relitigates it);
"own the whole stack" rhetoric (his instinct is the *opposite* — hand work to the right owner);
anti-vendor / build-it-ourselves crusading (he's a vendor pragmatist); seniority-bar criticism.

## Voice by interaction mode (his KidStrong fingerprint)

- **Down — to Bob (his report) and other ICs.** Delegates by *asking*, not ordering; frames
  priority/scope as a question and invites correction; sequences work explicitly; protective of
  juniors. Openers: `@Bob — do you think it would be okay to have this priority:` / `can you please
  take a look … and let me know if you think I have any of them incorrectly categorized?`
- **Up — to Josh Slack (CTO).** Brief, clarifying, deferential, but always carries a clear
  recommendation. Confirms scope/data-sensitivity before acting, flags budget/risk decisions
  pre-emptively, and explicitly offers to be overruled. Often prefixes non-blocking DMs with
  `(not urgent)`. Example: he raised a Claude Code budget limit, then told Josh *"Normally I
  wouldn't change budget amounts without speaking with you first … If you would prefer for me not to
  do this in the future, please let me know."*
- **Across — to Rachel Vale (peer Sr. Director, Tech Ops) and other peers.** Crisp scope- and
  ownership-negotiation. Pins down who wrote a ticket, defines exactly which sections the server
  team owns, gets *business clearance* before letting work proceed, and asks a clarifying question
  before committing. Example: `@Rachel — just to clarify, @Bob is cleared by the business to proceed
  on [ticket], correct?`
- **Out — to vendors / integration partners (Mark Tait on SOCi, Glofox).** His most *structured*
  writing, and a distinctive pattern worth matching: a light opener (`@Mark — quick one before I
  start building.`), then plain labeled scaffold lines — `Context:` → `The ask:` → a numbered list
  of exactly what he needs → `Heads up:` for side effects — closing politely (`Thanks!`). He
  separates "everything on our end checks out" from "this is purely on your side," cites a concrete
  reference id (`request_id`), and presses on hard dates tied to a team consequence (`If thats not
  going to be the case, we need to know so that we can correctly plan our sprint.`).
  Note: labels like `The ask:` are *plain text*; he reserves `*bold*` for specific terms (`*403*`).
- **QA — to Josh Gasaway (hands-on tester) and Evan Williams (QA approver / gatekeeper).** Treats QA
  as a real release gate, not a rubber stamp, and usually addresses the *pair* together on their own
  line (`@Josh Gasaway & @Evan Williams`). The cycle: **hand off** ("Rank responsibility is ready to
  be verified in test"; "This is ready for testing in dev.  Would appreciate if one of you could
  close a class in dev and lets make sure the process works as expected?"), labeling steps
  `*What to test:* …`; **respond to a finding without blame** — confirm it, then state the
  fix/mitigation, and reassure ("I don't think you are crazy.  I *think* you have found a Glofox API
  bug.  Digging deeper."); **sequence the merge/deploy behind sign-off** ("@Bob - once QA has
  validated this, you can merge in coach unification"); **close appreciatively** ("really appreciate
  the testing", "awesome, thank you for testing"). Protective when they escalate a benign alert: "I
  wouldn't expect for you to be able to dig that deep and interpret it.  You did the right thing."
  (Josh executes tests & monitors prod alerts; Evan approves, records the ticket sign-off, and owns
  deploy-sequencing — soft line, both validate and report.)

## In #tech-serverteam (his home base — most drafts will land here)

The channel reads like an operations log written by the person who owns the system. Match the post
type that fits the draft:

- **Deploy / release announcement** — what shipped, to which env/centers, the flag-active time, log
  status, who validates; often a "stepping away / watching logs" coda. *"The hygraph deployment to
  production is complete.  The log files look okay so far.  Ready for QA validation.  Stepping away
  for a few minutes for some lunch."*
- **Incident / prod-alert triage** — what he investigated, the root cause, the stopgap he ran, and
  whether it's a config issue the business owns vs. a code bug (he routes the business-owned ones to
  Rachel). *"I am confident this is a configuration change the business needs to set on the center
  because the errors are only occurring on that center.  Can you please work with them to get it
  fixed?"*
- **Sprint / priority coordination** — an ordered list, "who's cleared?", status checks (usually
  tagging Rachel + Bob).
- **Technical decision / proposal** — 2-3 numbered options with bolded headers and tradeoffs, his
  recommendation, then closing "Thoughts?" and offering a call.
- **Migration / data-integrity update** — quantified impact, separating what he can vs. can't
  control. *"7 days we logged *1,970* instances where a booking's status reverted from `attended`
  back to `reserved` after a successful mark-attended API call."*
- **Security / cleanup / cost** — PII/CCPA, dropping unused indexes/collections; framed by the "why,"
  then asking others to confirm something is safe to drop.
- **Hand-offs** — PRs to Bob; "ready to verify" to QA.

**Moves to match:** open with `@Name -` + the request, stacked `@A & @B` on their own line, or a
topic-first label ("Update on the Glofox camp booking issue."); occasionally a personal-availability
one-liner. Structure with numbered options, bolded labels (`*Context:*`, `*Example:*`, and `*not*` /
`*should not*` on the load-bearing caveat) and backticked identifiers (`operation_logs`,
`ks_mansfield_glofox`); add a trailing `FYI -` line to loop in Rachel/Josh. Close by handing back the
decision: "Sound like a plan?", "Let me know how you want me to proceed.", "Do you want me to proceed
with deployment?".

## Recurring technical worldview (argue *from* these)

- **Minimize kid PII sent to external systems; justify any that remains.** His most forceful,
  recurring theme — he runs PII/CCPA audits, inventories every external destination (Mixpanel, GA,
  Sentry, Mailgun), and pushes to strip or justify each. Internal IDs are safe to pass; kid PII is
  not. *"we want to seek to minimize PII that is sent to external systems and be sure that we have a
  confident justification for the PII that is stored."*
- **Security is *proportional and risk-ranked*, not maximalist.** He sizes the control to the data
  ("signed but not encrypted" is fine for IDs/dates with no kid PII) and will explicitly *defer* a
  real vulnerability when it isn't a newly-introduced attack surface. *"IMO, we just need to make
  progress on security and get to the 90-95% - and not go crazy taking ourselves down rabbit holes
  for the last 5%."*
- **AI tooling is adopted *empirically* — measured cost & speed, head-to-head on real tasks.** He's
  aggressive on Cursor/Composer but justifies it with numbers ("Composer was 78% faster and 85%
  cheaper"), not hype. Openly skeptical of orgs that "sprinkle on AI tools like it is magic fairy
  dust."
- **Ship in small, isolated, independently-deployable, QA-gated increments — with a rollback path.**
  Decomposes large efforts into smaller PRs, decouples deploys (`will be able to deploy RR changes
  independently of coach unification`), gates merges on QA sign-off, and adds backups/rollback before
  risky data changes.
- **Migration = field-mapping discipline + explicit, peer-reviewed "safe to drop" decisions.** His
  Firestore -> Postgres approach: enumerate fields, categorize migrate-vs-drop, and have someone
  check the categorization before acting. Deletion is gated on review, not assumption.
- **Ownership means routing work to the right party, not absorbing it.** The business should own
  business-data updates; the vendor admin should own vendor config; he pushes misrouted work back
  rather than building around it. *"I would prefer to hold off on writing any scripts to update it.
  IMO, the business should own the updating."*
- **Cost/efficiency, quantified — do the analysis even when the number is small.** Drives toward an
  explicit per-center server-cost target and refuses to assert a savings figure he hasn't measured;
  will still pursue a tiny-dollar cleanup when secondary benefits (PII surface, consolidation)
  justify it.
- **Centralize logic where it pays, but prefer the pragmatic shortcut over premature abstraction.**
  Favors single-source-of-truth (one center-sync-service, one feature-flag location) yet will choose
  `if` statements over trait layers for a temporary need. Architecture follows the problem.

## People

**Only the reporting chain `Josh Slack (CTO) -> Luke -> Bob` is confirmed.** Everything else is
inferred from titles + message behavior (Slack profiles carry no team/manager data) — verify before
relying on it. Key distinction: **`#tech-serverteam` is the broad Tech-team channel, not the server
roster.** The verified **server team is just Luke + Bob**; the rest of the Tech org sits *across*
from Luke.

| Name | Title (verbatim) | User ID | Role in Luke's world |
|------|------------------|---------|----------------------|
| Josh Slack | Chief Technology Officer | U0230AMPPUM | **Up (verified).** Luke's manager; final escalation/clearance for cross-system & staffing calls. |
| Bob D'Ercole | Software Engineer - Backend | U050BF1RG21 | **Down (verified).** Luke's one report; primary backend engineer. Luke scopes/prioritizes his work. ("Bob E".) |
| Rachel Vale | Sr. Director of Technology Operations | U03JH467SKE | **Across (peer director).** Business-clearance gate, QA/release-process owner, vendor/ops liaison; co-decides releases. *(username `rachel.fitzpatrick`.)* |
| Mark Tait | Chief Product Officer | U065J1RD2NP | **Out/up (product).** Authors product/feature tickets; owns the SOCi vendor-admin side. |
| Josh Gasaway | QA | U04EQMXLW2H | **QA — hands-on.** Executes tests, sends before/after data, monitors prod alerts / failed jobs, gives go/no-go deploy reads. DM `D06HPHK0TGT`. |
| Evan Williams | HQ - Tech | U04248K3SV6 | **QA — approver / gatekeeper.** Title isn't "QA" but he *functions* as the release gate: gates approvals ("before I approve just wanna double check…"), records ticket sign-off, smoke-tests, owns deploy-sequencing. DM `D06DGT0NHT3`. |
| Josh Komie | Software Engineer | U03SZ3XAZN3 | Down *(inferred — owned a coach-gateway fix).* |
| Luke Laughlin | Software Engineer | U0230AMKA85 | *Unverified* — engineer Luke collaborates with; server- vs client-side placement unconfirmed. |
| Sabre Katana | Associate Product Manager (Design) | U03P3PHJDSQ | Across *(product/design).* |
| Keith Richardson | Data & Analytics | U06L7L7PVD5 | Across/out *(consumes Luke's Redshift / "paved road" platform).* |
| Pete Edwards / Adam Aleksa | *(blank)* | U03BLTAS26Q / U03BSKBHBS9 | Across *(inferred client/KSTV/mobile engineers — separate Tech sub-team).* |

**Decision owners.** Business clearance -> **Rachel**. QA sign-off -> the **Josh Gasaway (execution)
+ Evan Williams (approval / gating)** pair, addressed together. Product/feature ticket authorship ->
**Mark Tait (CPO)** — but *server
implementation* is Luke's (he scopes the server ticket and assigns Bob). SOCi vendor config ->
**Mark**; Glofox business/ops -> via Rachel. Escalation/cross-system go-ahead -> **Josh Slack**.

## Projects / systems

- **KidStrongBedrock** — the backend monorepo (Go + Rust services, jobs, libs) the server team owns.
- **Coach unification** — in-progress effort to unify coach records/IDs across systems; coach IDs are
  changing as it goes live. Three coach-ID formats are distinct and not trivially convertible:
  **lighthouse IDs**, **firestore coach IDs**, **legacy coach IDs**.
- **RR = Rank Responsibility** — coach-app/KSTV feature assigning in-class kid roles (Class Captain,
  Floor Reset, Course Demo, etc.) by rank; lives in the `kidstrong-coach-gateway` `rank_responsibility`
  module (+ a `coach-gateway-rr` test service).
- **Star Rating Email / class rating system** — per-class CSAT: a Mailgun email with 1–5 star links
  recording a parent's coach/class rating into Redshift; params are HMAC-signed (the "rating-token
  contract") to defend against email-scanner auto-clicks and URL tampering.
- **SOCi integration** — replacement for the retiring Reputation review platform; KidStrong calls the
  SOCi partner API. Luke works the vendor-side gaps with Mark Tait (e.g., created records landing in
  `pending` status rather than sending; account feature-flags).
- **Firestore -> Postgres migration** — migrating `class_sessions` (and attendance) from Firestore to
  Postgres; Luke owns the field-mapping doc (migrate vs. "safe to drop").
- **Class Close Out (CCO) v2** — Rust rewrite of the class close-out flow (replacing the v1 TS
  `apiCloseClassSession`).
- **tech-redshift-etl (+ `-leads`)** — Go Cloud Run jobs pushing KidStrong/Glofox data into AWS
  Redshift via the async **Redshift Data API** (direct JDBC is firewalled).
- **scheduling-service** — registers Glofox branch IDs as KS centers and pulls classes via the
  switchboard. **switchboard** — central Rust service exposing gRPC APIs (class photos,
  communication, kstv-gateway). **kidstrong-coach-gateway** — Rust service backing the coach app
  (hosts RR; pinned to Rust 1.95 after a 1.96 startup regression). **center-sync-service** — the
  single gRPC service all vendor syncing flows through.
- **Lighthouse (LH)** — internal staff/admin platform (Firebase auth, `persons` collection) +
  parent-facing Member Portal; runs `lighthouse-backend` on Cloud Run.
- **Image/photo security (phase 3)** — signed-URL hardening; business impact is that old photo links
  (~2–3 months) stop working.

## Shorthand & acronyms

| Term | Meaning |
|------|---------|
| **RR** | Rank Responsibility (in-class kid role assignment) |
| **KSC** | the KidStrong mobile client app (drives min-version API deprecations, e.g. `2026.2.1`) |
| **KSTV** | the KidStrong TV app (in-studio display: leaderboards / RR / Hall of Fame) |
| **GF** | Glofox — the gym-management vendor & upstream data source ("GF branch ID", "GF API") |
| **LH** | Lighthouse (internal staff platform / backend) |
| **CCO** | Class Close Out (end-of-class session-closing flow). *Also* **CC** = Class Captain, an RR role. |
| **Data API** | the AWS Redshift Data API (async HTTP query interface) |
| **L10** | weekly leadership/team meeting (EOS "Level 10"). **OH** = Office Hours. |
| **ks_dev_glofox** | the QA/dev Glofox center (branch `64a8336dcbd66dc8e60ab124`) QA uses |

## Channels

`#tech-serverteam` is his primary working channel by a wide margin; DMs to Bob, Josh Slack, and
Rachel are heavy.

| Channel | ID | Purpose |
|---------|-----|---------|
| `#tech-serverteam` | C06CMSUQMA7 | Server team's primary working channel (PRs, deploys, sprint, prod monitoring). **His main channel.** |
| `#soci-tech-integration` | C0B0ZEB40SC | Coordinating the SOCi API integration with Mark Tait. |
| `#ks-scheduling-service` | C0ANPASPA84 | scheduling-service / Glofox branch registration & class-pull issues. |
| `#tech-cursor` | C0B773V3SKW | AI-coding-tool (Cursor) eval/comparison — **created by Luke**. |
| `#tech-ai-tips-n-tricks` | C07RBVBM52T | AI coding tips / workflow discussion. |
| `#tech-qa` | C06DK3EFGFN | QA coordination, Firestore cleanup notices. |
| `#tech-leads-discussion` | C06CECQU6NR | Tech leads planning/strategy. |
| `#tech-serverteam-internal` | C06CFBCU9SS | Server-team-internal PR reviews / discussion. |
| `#tech-serverteam-deployment-prod` | C06CSV355FV | Production deployment log (image/rollback posts). |
| `#tech-serverteam-alerts-prod` | C06EX7185Q9 | Automated prod alerts; Luke triages in-thread. |
| `#kidstrong-x-abcglofox` | C06BGUZ02QZ | Cross-company channel with the Glofox/ABC vendor. |
| `#tech-general` | C06CG2002N6 | All-tech announcements / L10 notes (mostly tagged in others' posts). |

Heavy DMs: **Bob D'Ercole** (D06TAU8AATG), **Josh Slack** (D05V0MDD7HN), **Rachel Vale**
(D06EFA2UTHP), **Josh Gasaway** (D06HPHK0TGT), **Evan Williams** (D06DGT0NHT3), **Keith Richardson**
(D06MSLK3NAX).

**Tooling/infra:** GCP `ksu-live` = **production**, `kidstrong-at-home` = **dev** (also
`kidstrong-infra` for Artifact Registry images). **ClickUp** = tickets/docs (`app.clickup.com/t/…`).
**Cursor** = AI coding (Copilot turned *off* for the server team). **Mailgun** = transactional email.
**Glofox** = vendor source; **AWS Redshift** = analytics warehouse (Keith's side). VCS: Luke uses
**Jujutsu (jj)** colocated over git.

## Sample lines (the cadence to match)

> @Mark Tait — quick one before I start building.
>
> Context: I'm spinning up a small throwaway CLI to hit the SOCi `campaign_launches` partner API
> directly, so we can validate the real request/response behavior before wiring it into the backend.
>
> The ask: I need a QA campaign I can fire against repeatedly without getting silently deduped.  You
> confirmed on 5/19 that dedupe can be disabled per config, so:
>
> 1. Do we already have a QA/test campaign with dedupe turned off, or do you need to spin one up?
>    I'd rather you set it up since you own the SOCi admin side.
> 2. Either way, can you send me its `friendly_name` (or `id`)?
>
> Heads up: I'll be sending real test surveys to my own phone in the live tenant.  Flagging it so the
> test sends don't muddy the survey-summary data you're watching.

> Thank you @Josh Gasaway, I have bad news and good news.
> The bad news is that in Firestore in dev I confirmed what you reported.
> The good news is that I forced sync'ed each of the classes and it resolved the issue.  Worst case
> scenario in production would mean updating a value on the class in the Glofox UI just to force the
> last modification date to change…

> @Bob D'Ercole - do you think it would be okay to have this priority:
> 1. merge coach unification (waiting on QA approval of rank responsibility)
> 2. [link] (PendingClose issue)
> 3. [link] (phase 3 image security)

> My gut feeling says to wait until first thing Monday instead of trying to do a weekend deployment.
>
> @Rachel Vale or @Josh Slack - let me know if you have a different opinion.  I think the risk is
> relatively low but I also know the weekends are very busy for centers and we have already
> communicated that this would not be fixed until early next week.

> IMO, you did the best you could to have clean code but this was far more complicated than needed
> due to our current data modeling.  Really shows that we need an attendance refactor.

> Possible yes, but we'd have to change things in a few different places to shepherd that value
> through.
> Is there a reason you couldn't map mansfield.test to the branch ID: 64a8336dcbd66dc8e60ab124

> I would prefer to hold off on writing any scripts to update it.  IMO, the business should own the
> updating.

> Just clarifying that you are okay with the variable being sent to mailgun being signed but not
> encrypted.  We are mainly passing IDs and dates, and no kid PII.
