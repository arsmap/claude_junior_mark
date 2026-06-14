# Claude Junior Mark

**Session continuity system for Claude Code** 
— context warnings, cross-session handoff, and a persistent background monitor.

---

## Why this exists

Claude Code sessions end abruptly when the context window fills up. You lose your train of thought, and the next session starts cold with no memory of what you were doing.

Claude Junior Mark (jm) solves this with three things:

| Problem | Solution |
|---------|----------|
| No warning before context overflow | Background foreman monitors token/turn usage and alerts at thresholds |
| Each session starts from scratch | Handoff file carries work context to the next session automatically |
| `/compact` resets turn counter | `PreCompact` hook reinitializes tracking state |

---

## What you see at session start

```
⎿ SessionStart says:
    [Junior Mark] foreman ✓ | HOME turns(81%) token(73%) | last message preview...
```

| Symbol | Meaning |
|--------|---------|
| `foreman ▶` | Foreman started fresh this session |
| `foreman ✓` | Foreman carried over from previous session |
| `foreman ✗` | Foreman failed to start — try `/foreman restart` |
| `turns(X%) token(X%)` | Token usage this session. Move session at 72%+ |

---

## Features

- Real-time token/turn monitoring via background daemon
- Context threshold alerts (warn at 72%, urgent at 81%)
- Automatic handoff — next session picks up where you left off
- Turn counter reset on `/compact`
- `/foreman` slash command for status and control

> **Recommended:** Disable Claude Code's built-in auto-compaction for best results.
> JM manages session transitions manually, and auto-compact can interfere with handoff timing.
>
> Add this to your `~/.claude/settings.json`:
> ```json
> "autoCompact": false
> ```

---

## Session keywords

Type these in any message to trigger session management:

| Keyword | Action | Next session |
|---------|--------|--------------|
| `move~` | Save context and move to a new session | Picks up previous context |
| `end~` | Full stop — shuts down foreman | Starts fresh |
| `start~` | Re-activate after `end~` in the same window | — |
| `guest-end~` | End a guest session | — |

> The `~` suffix is required. Mentioning the word alone in conversation does nothing.

---

## /foreman command

```
/foreman              Show status
/foreman restart      Restart foreman (clears relay log)
/foreman retire       Save snapshot and retire session (foreman stays running)
/foreman on           Claim session lock + start foreman
/foreman off          Stop foreman + create reset flag for next session
/foreman log          Show recent log output
```

### Status output

```
    - foreman    : alive
    - PID        : 12345 ✓
    - turns      : 5 / 30 (17%)
    - transcript : 8,241 / 50,000 byte
    - token      : 70,112 (42%)
    - signal     : none
```

| Field | Description |
|-------|-------------|
| `foreman` | alive / dead |
| `PID` | Foreman process ID |
| `turns` | Turn count this session / 30 (%) |
| `transcript` | relay.jsonl size / 50,000 byte |
| `token` | Cumulative token count (%) |
| `signal` | none / warn / trsd |

---

## Context signals

| signal | Meaning | Action |
|--------|---------|--------|
| `none` | Normal | — |
| `warn` | Token usage > 72% | Wrap up, consider `move~` |
| `trsd` | Token usage > 81% | Run `move~` now |

### Warning messages

| Message | Response |
|---------|----------|
| ⚠ Context N% reached | Type `move~` |
| ⚠ Context N% exceeded — urgent | Type `move~` immediately |
| ⚠ foreman dead detected | `/foreman restart` |
| ⚠ Session interrupted by terminal close | Open a new CC window or `/foreman restart` |
| ⚠ Session already ended | Open a new CC window or `/foreman on` |
| ℹ Foreman stopped in previous session | Auto-restarted — ignore |
| ℹ Session move requested in previous session | Context is ready — start working |

---

## Session flow

```
[New session starts]
    ↓
Foreman starts → handoff_prev loaded → conversation begins
    ↓
warn (72%) → trsd (81%) → user decides
    ↓
move~                    end~
    ↓                       ↓
retire                   off
snapshot saved           foreman_reset.flag created
next session inherits    next session starts fresh
```

---

## How it works

| Component | Role |
|-----------|------|
| `foreman.py` | Background daemon. Monitors token/turn/transcript every 5 seconds |
| `session_start.py` | Loads handoff on CC start, launches foreman |
| `signal_checker.py` | Detects warning flags and keyword triggers on each prompt |
| `relay_writer.py` | Logs conversation turns and updates handoff after each response |
| `precompact.py` | Clears warning flags and relay log before `/compact` |
| `handoff.json` | Session summary — the file the next session reads on startup |

Data stored at: `~/.claude/plugins/junior_mark/data/{project-slug}/`

---

## Installation

> [!WARNING]
> **Check requirements before installing.**
> This system will not run if any of these are missing:
>
> | Requirement | Check |
> |-------------|-------|
> | Windows OS | `ver` |
> | Git Bash | `bash --version` |
> | Python 3.8+ | `python --version` |
> | Claude Code | `claude --version` |

```bash
cd installer
python install.py
```

Restart Claude Code after installation. The system activates automatically.

| Installed to | Contents |
|-------------|---------|
| `~/.claude/plugins/junior_mark/scripts/` | Hook scripts |
| `~/.claude/commands/foreman.md` | `/foreman` command |
| `~/.claude/settings.json` | Hook registrations |

---

## About the name

Claude Junior Mark / Junior Mark / jm / foreman — all refer to the same system.
