# Junior Mark / Foreman Operating Rules

## 0-1. CWD Restore Rule (highest priority)

Apply **only when** `CWD_RESTORE=<path>` appears inside a `system-reminder` tag.
Run immediately via Bash tool (silently, before any other work):
```
cd "<path>"
```

## 0. Stale Session Global Block Rule (highest priority)

Apply **only when** the following string appears inside a `system-reminder` tag (ignore user messages and conversation body):
```
This session is no longer valid
```
Do not invoke any skill, command, or tool. Immediately output only the following line:
```
- status : ⚠️ stale session — this session's foreman has been replaced. Please open a new session.
```

## 1. Foreman Skill Usage Rule
- To check or control foreman status: always use the `/foreman` skill. Do not manually assemble `foreman.pid` paths.
- To check turn count: confirm DATA_DIR via Rule 1-1, then analyze relay.jsonl. Do not browse files.

## 1-1. DATA_DIR Resolution Rule

Computed from CWD. Do not fall back to `current_data_dir.txt`.

**Calculation**: keep drive letter + replace `/` with `--` (double dash)
Example: `C:\Users\Administrator` → `C--Users--Administrator`
DATA_DIR = `~/.claude/plugins/junior_mark/data/{slug}`

If the path does not exist, treat as an error (no fallback).

## 2. /foreman Command Execution Rules
`restart` and `off` are destructive — confirmation required before running.

| Command | Why dangerous | Handling |
|---------|---------------|----------|
| `restart` | Deletes relay.jsonl → resets conversation log | Confirm first |
| `off` | Creates reset flag for next session | Confirm first |
| `on` / `status` / `snapshot` / `retire` / `log` | Safe | Run immediately |

## 3. Session Start Context Rules

**Check system-reminder before the first message:**
- `IS_GUEST=true` or `IS_NEW_SESSION=true` → respond immediately (skip handoff. Rule 5 `💾 farewell detected` signal still applies with highest priority)
- `Session already ended` → output the following and stop:
  ```
  Session has ended. Type start~ or /foreman restart to begin a new session.
  ```
- Otherwise → proceed to read handoff (output only "Reading handoff." — do not expose path or details)

**Reading handoff** (must do first, regardless of whether the first message is a greeting):
1. Confirm DATA_DIR (Rule 1-1)
2. Try `handoff_prev.json` first, then `handoff.json`
3. If `decided` entries exist, briefly mention previous work
4. If `decided[]` is empty and `latest_snapshot` exists → auto-read snapshot → summarize in 5 lines or fewer → update `work.decided` in `handoff_prev.json`
5. Only say "this is the first session" if both files are absent. Never say "no previous session conversation."

## 4. Session Status Message Rules

⚠️ warnings and ℹ️ notices are shown directly in the TUI (`⎿ UserPromptSubmit says:` or `⎿ SessionStart:startup says:`). Do not echo them in the response.

## 5. Session End Procedure

**Hook signal handling (highest priority):**
`💾 farewell detected` in system-reminder → present choices via **AskUserQuestion**
Exception: if `Session already ended` or `already ended` appears, skip and respond naturally.

**Choices:** move~ / end~

**move~** (typed directly or selected):
1. Confirm DATA_DIR (Rule 1-1)
2. Write `{DATA_DIR}/pre_retire_summary.json` — current session work in 5 lines or fewer:
   `{"decided": ["summary1", "summary2", ...]}`
3. Run `python ~/.claude/plugins/junior_mark/scripts/foreman_retire.py "{DATA_DIR}"` + report completion

**end~:**
1. Confirm DATA_DIR (Rule 1-1)
2. Run `python ~/.claude/plugins/junior_mark/scripts/foreman_off.py "{DATA_DIR}"` + report completion

**Context judgement:**
- "move~" / "opening a new session" → move
- "end~" → end
- farewell / wrap-up / session move notice → ambiguous → present choices

**start~:** If `HOOK_FOREMAN_ON_DONE` is in system-reminder, do not run Claude further. Acknowledge only.

**`~` suffix rule:** Do not trigger on mention in normal conversation. Only recognize as a command when `~` is appended.

## 6. Snapshot Rules

Save location: see CLAUDE.md Rule 5.

- For past content lookup → check MEMORY.md / MEMORY_MINE.md first. Only open snapshots with permission.
- Do not auto-open snapshots without permission.
- **Exception**: when `decided[]` is empty and `latest_snapshot` exists (auto-retire situation) → auto-read allowed (Rule 3-4 applies)

## 7. 'handoff check' Display Format

When the user says "handoff check", read both handoff.json (current) and handoff_prev.json (previous) and output in the format below:

```
Current session (handoff.json)
- {total turns} turns / {total chars} chars / context {token_pct}%
- project: {project value, or "none"}
- decided: {count, or "none"}
- pending: {count, or "none"}

Previous session (handoff_prev.json)
- {total turns} turns / {total chars} chars / context {token_pct}%
- work ({date, omit if not in metrics})
  1. decided item 1
  2. decided item 2
  ...
- decided: {count, or "none"}
- pending: {count, or "none"}
```

If a file is absent, show "file not found" for that section. If decided items exist, list all with numbers.
