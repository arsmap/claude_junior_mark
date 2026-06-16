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
| `foreman ✗` | Foreman failed to start — open a new session |
| `turns(X%) token(X%)` | Token usage this session. Move session at 72%+ |

---

## Features

- Real-time token/turn monitoring via background daemon
- Status bar on every turn: token%, turn count, foreman PID and alive state
- Context threshold alerts (warn at 72%, urgent at 81%)
- Automatic handoff — next session picks up where you left off
- Turn counter reset on `/compact`

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
| `end~` | Full stop — shuts down foreman + ends session | Starts fresh |
| `start~` | Re-activate after `end~` in the same window | — |
| `on~` | Start foreman only (no session state change) | — |
| `off~` | Stop foreman only (no session state change) | — |
| `restart~` | Kill and restart foreman | — |
| `guest-end~` | End a guest session | — |

> **Two groups:**
> - **Session state** (`start~` / `move~` / `end~`): modify session files (retire flag, reset flag, session warn, etc.)
> - **Process control** (`on~` / `off~` / `restart~`): foreman process only — no session state change. Note: `restart~` is NOT a variant of `start~`.

> The `~` suffix is required. Mentioning the word alone in conversation does nothing.

---

## Status bar

Shown automatically on every turn :

```
🟢 [████████░░░░░░░░░░░░] 40.1% | 80K/200K T:26/30 | PID: 3624
```

| Field | Description |
|-------|-------------|
| 🟢 / 🟡 / 🔴 | Foreman alive + context level (normal / warn / threshold) |
| ⚫ | Foreman dead — type `restart~` to restart, or open a new session |
| `X% \| XK/200K` | Token usage |
| `T:N/30` | Turn count this session |
| `PID: N` | Foreman process ID (`----` if dead) |

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
| ⚠ foreman dead detected | Type `restart~` to restart, or open a new session |
| ⚠ Session interrupted by terminal close | Open a new CC window or type `start~` |
| ⚠ Session already ended | Open a new CC window or type `start~` |
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
install.bat
```

Restart Claude Code after installation. The system activates automatically.

| Installed to | Contents |
|-------------|---------|
| `~/.claude/plugins/junior_mark/scripts/` | Hook scripts |
| `~/.claude/settings.json` | Hook registrations |
| `~/.claude/CLAUDE.md` | jm_rules.md registrations |

---

## About the name

Claude Junior Mark / Junior Mark / jm / foreman — all refer to the same system.

---

## Acknowledgements

The idea that Claude Code passes live `context_window` data (token count, window size, usage %) via stdin to a `statusLine` hook was discovered from [claude-context-monitor](https://github.com/fomyio/claude-context-monitor) by fomyio.
The status bar layout, session management, foreman daemon, and handoff system are independently developed.
