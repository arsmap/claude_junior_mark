[[English]](./README.md) · [[한글]](./README_KO.md)

<h1 align="center">Claude Junior Mark</h1>

<p align="center">
  <b>Session continuity system for Claude Code</b><br>
  Mitigating context saturation and loss via context warnings, cross-session handoff, and a persistent background monitor.
</p><br>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.04.34-blue" alt="Version" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
  <img src="https://img.shields.io/badge/python-≥_3.8-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white" alt="Platform" />
  <img src="https://img.shields.io/badge/Claude_Code-plugin-D97706" alt="Claude Code" />
  <img src="https://img.shields.io/badge/PRs-welcome-purple" alt="PRs Welcome" />
</p>

## Why this exists  
Claude Code sessions end abruptly when the context window fills up.  
You lose your train of thought, and the next session starts cold with no memory of what you were doing.  

Claude Junior Mark (hereafter referred to as jm) solves this by managing your CLI sessions in the background.  
Operating as a background daemon named 'foreman' alongside custom hooks, it continuously monitors session states and seamlessly bridges the context from one session to the next via handoffs.  

| Problem | Solution |
|---------|----------|
| No warning before context overflow | Background foreman monitors token/turn usage and alerts at thresholds |
| Each session starts from scratch | Handoff file carries work context to the next session automatically |
| `/compact` resets turn counter | `PreCompact` hook reinitializes tracking state |  
<br>

## Prerequisites
> | Requirement | Check |
> |-------------|-------|
> | Windows OS | `ver` |
> | Git Bash | `bash --version` |
> | Python 3.8+ | `python --version` |
> | Claude Code | `claude --version` |  
<br>

## Installation
Install via Windows Terminal or Git Bash:  
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
<br>

## Features
Real-time token/turn monitoring via background daemon  
Status bar on every turn: token%, turn count, foreman PID and alive state  
Context threshold alerts (warn at 82%, urgent at 92%)  
Automatic handoff — the next session picks up where you left off  
Turn counter reset on `/compact`  

> **Recommended:** Disable Claude Code's built-in auto-compaction for best results.
> JM manages session transitions manually, and auto-compact can interfere with handoff timing.
>
> Add this to your `~/.claude/settings.json`:
> ```json
> "autoCompact": false
> ```  
<br>

## What you see at session start
```
⎿ SessionStart says:
    [Junior Mark] foreman ✓ | HOME turns(86%) token(73%) | last message preview...
```

| Symbol | Meaning |
|--------|---------|
| `foreman ▶` | Foreman started fresh this session |
| `foreman ✓` | Foreman carried over from previous session |
| `foreman ✗` | Foreman failed to start — open a new session |
| `turns(X%) token(X%)` | Token usage this session. Move session at 82%+ |
<br>


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

<br>

## Guest session
Opening a second Claude Code window on the same project while a session is already
running starts a **guest session** (the status bar shows `👤 GUEST session`). A guest
runs alongside the main session without interfering with it:

- It is **not logged** — its turns/tokens are not recorded, and it does not touch the
  main session's handoff or telemetry.
- Session-ownership / foreman-control keywords are **blocked** so a guest cannot
  disturb the main session's state:

| Blocked in guest | Allowed in guest |
|------------------|------------------|
| `move~` `end~` `start~` `on~` `off~` `restart~` | `guest-end~` (ends the guest) |

Read-only commands (e.g. `/report`) and `/clear` still work — they only affect the
guest's own window.  

<br>

## Status bar
Shown automatically on every turn :

```
🟢 [████████░░░░░░░░░░░░] 40.1% | 80/200K 26/30T | PID:3624
```

| Field | Description |
|-------|-------------|
| 🟢 / 🟡 / 🔴 | Foreman alive + context level (normal / warn / threshold) |
| ⚫ | Foreman dead — type `restart~` to restart, or open a new session |
| `X% | N/200K` | Token usage |
| `N/30T` | Turn count this session |
| `PID:N` | Foreman process ID (`----` if dead) |  

<br>

## Context signals
| signal | Meaning | Action |
|--------|---------|--------|
| `none` | Normal | — |
| `warn` | Token usage > 82% | Wrap up, consider `move~` |
| `trsd` | Token usage > 92% | Run `move~` now |  

<br>

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

<br>

## Session flow
```
[New session starts]
    ↓
Foreman starts → handoff_prev loaded → conversation begins
    ↓
warn (82%) → trsd (92%) → user decides
    ↓
move~                    end~
    ↓                       ↓
retire                   off
snapshot saved           foreman_reset.flag created
next session inherits    next session starts fresh
```
<br>

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
<br>

## Acknowledgments
The output format of the status bar was inspired by fomyio's [claude-context-monitor](https://github.com/fomyio/claude-context-monitor).
Please note that all other core features—including session management, the foreman daemon, and the handoff system—were independently developed.  
<br>

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.  
<br>