# Wiki Operating Rules

Global rules for the JM wiki (`~/.claude/plugins/junior_mark/wiki/`). Loaded via
CLAUDE.md `@include`, same as jm_rules.md. Session-lifecycle rules (foreman, handoff,
end procedures) stay in jm_rules.md; everything wiki-global lives here.

## 1. Wiki Anchor — Read Side (session start)

**Every main session, before handoff (`IS_GUEST=false`):**
When SessionStart shows `IS_GUEST=false`, first read the last entry of the wiki log
(`~/.claude/plugins/junior_mark/wiki/log.md`) — it carries the in-progress work and
the next item to pick up. Applies to every main session (new **or** continuing/move),
regardless of how specific the user's prompt is. The wiki is independent of the handoff
path, so a purged handoff (e.g. after /clear) no longer drops the work thread. Guests
are excluded automatically (they emit only `IS_GUEST=true`, never `IS_GUEST=false`).
Note: currently includes move sessions (IS_GUEST=false). May later narrow to
`IS_GUEST=false & IS_NEW_SESSION=true` to exclude move sessions.

Read the anchor with the Read tool (jm_rules "File Read Rule") — never shell commands.

## 2. Wiki Anchor — Output Message

Reading the wiki anchor has its own label — do not borrow the handoff label. When the
wiki anchor is the only start-context read (handoff is skipped, i.e.
`IS_NEW_SESSION=true` or `IS_GUEST=true`), output exactly `Reading wiki anchor.`
(do not expose path or details). In a continuing session that also reads handoff, the
single `Reading handoff.` line covers it — do not add a second line.

## 3. Wiki Anchor — Write Side (before ending a session)

Before `/clear` or move~ (or any session break during wiki work), confirm that any
in-progress decision, policy, or next-pickup item is written into the **last entry of
`log.md`**. The read anchor above only carries what was actually written there — a
decision made mid-session but left only in chat/snapshot (snapshots are not auto-read)
is lost on `/clear`. Rule of thumb: "did this decision make it into the anchor?"
This also covers **completing** an item a prior entry marked pending/next-pickup: flip
it to done in the anchor (not only in-progress items). Write the completion entry
**before** the terminal sync/commit so it rides in the commit payload — a chat
completion report is **not** durable (`/clear` purges it) and never substitutes for the
anchor.

**Append incrementally, don't batch at end.** Jot each decision into the anchor as it
lands during the session, not all at once when the user says end~/move~ — batching makes
the session-end procedure slow (backup → read → long edit) and risks losing a decision if
end is abrupt. At end-time the anchor should already be current, so the closing entry is
short and **next-pickup-focused** (details already live in commits/memory — do not
re-summarize them into the anchor).

## 4. Write Eligibility — one recorder per work thread

Only a session that actually edited wiki content (pages/ingest) during its run writes
the anchor. A session that merely assisted — tests run in another folder, non-wiki
project work — must NOT write log.md; it reports results back to the owning session,
and that session records them.
Rationale: these rules are global, so every folder's main session inherits the farewell
anchor step; without this condition a late-closing helper session appends a stale entry
at the bottom, and the anchor contract "last entry = next pickup" makes last-writer-wins
poisonous (2026-07-05 near-miss: a workplace_webpage session tried to append 1-hour-stale
test results at end~; only an Edit staleness error stopped it).

## 5. Anchor Freshness at Session End (pre-menu step)

Anchor freshness is a pre-menu step, not a per-branch action. A session-end menu
appearing means work is wrapping up, so the wiki `log.md` last entry must already carry
the current in-progress work + next-pickup (§3, flip completed items to done) **before**
the choices are shown — regardless of which option (move~/end~/clear) the user picks.
Confirm/update the anchor first; the end-procedure branches (jm_rules Rule 5) assume it
is current.
**This step applies only to sessions that edited wiki content** (§4). A session that did
no wiki editing skips anchor writing entirely and goes straight to the choices — do not
append a session summary to log.md.

## 6. Ingest Compresses, but Must Not Discard the Process

When ingesting, do not take "keep only the conclusion / the essence" as the goal. That
framing auto-sorts the back-and-forth — wrong turns, reversals, getting stuck, being
corrected by the user — into "not the essence = filler," and it drops out. But in this
wiki's methodology and Dodam-self-cognition pages, **the messy process IS the substance**:
if only the conclusion survives, the next session's Dodam never learns the process and
repeats the same habit (e.g. a "gate won" summary that erases the three reversals teaches
nothing). The compression test is not "how short" but **"could someone who wasn't there
reconstruct what actually happened?"** In particular, when erasing a fact unflattering to
Dodam leaves a satisfying "just the essence remains" feeling, treat that satisfaction
itself as a bias signal. Review for substance (is the process alive?), not only form
(closing/links). This is **not** license to invent failures that didn't happen — keep the
process that actually occurred, balanced. → [[gap-filling-habit]] applied to ingest ·
[[purpose]] "distilled honest knowledge".
