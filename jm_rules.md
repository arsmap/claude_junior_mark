# Junior Mark / Foreman Operating Rules

## 0-2. Force Retire Rule (highest priority)

Apply **only when** `🚨 force_retire detected` appears inside a `system-reminder` tag.
Present choices via **AskUserQuestion** — do not auto-execute move~.

Choices: move~ / 계속 진행
- move~ selected → execute move~ procedure (Rule 5)
- 계속 진행 selected → write `force_retire_mute.flag` to DATA_DIR, then continue normally
  (mute flag prevents repeated warnings in this session; cleared automatically on next session start)

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

## 1. Foreman Status Rule
- Foreman status is shown automatically in the status bar each turn (`⎿ UserPromptSubmit says:`). It displays PID, token%, and turn count. Do not manually assemble `foreman.pid` paths.
- To check turn count: confirm DATA_DIR via Rule 1-1, then analyze relay.jsonl. Do not browse files.

## 1-1. DATA_DIR Resolution Rule

Computed from CWD. Do not fall back to `current_data_dir.txt`.

**Calculation**: strip the drive letter colon (`:`), then replace each `\` or `/` separator with `--`
Example: `C:\Users\Administrator` → `C--Users--Administrator`, `F:\WorkSpace\foo` → `F--WorkSpace--foo`
DATA_DIR = `~/.claude/plugins/junior_mark/data/{slug}`

If the path does not exist, treat as an error (no fallback).

## 2. Foreman Control Keywords

| Keyword | Action |
|---------|--------|
| `start~` | Claim session lock + start foreman (reactivate after end~) |
| `move~` | Retire session — save snapshot + pass context to next session |
| `end~` | Stop foreman + create reset flag for next session |
| `on~` | Start foreman only (no session lock claim) |
| `off~` | Stop foreman only (no session state change) |
| `restart~` | Stop + restart foreman (pure process control, handled by hook) |

**Session state commands** (`start~` / `move~` / `end~`): modify session files (retire_flag, reset_flag, session_warn, etc.)
**Process control commands** (`on~` / `off~` / `restart~`): foreman process only — no session state change, not affected by retire_flag. Note: `restart~` is NOT a variant of `start~`.

## 3. Session Start Context Rules

**Check system-reminder before the first message:**
- `IS_GUEST=true` or `IS_NEW_SESSION=true` → **respond immediately. Do NOT read any handoff files. Do NOT output "Reading handoff."** (Rule 5 `💾 farewell detected` signal still applies with highest priority)
- `Session already ended` → output the following and stop:
  ```
  Session has ended. Type start~ to begin a new session.
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
3. Run `python ~/.claude/plugins/junior_mark/scripts/foreman_retire.py "{DATA_DIR}"` + output exactly: `retire complete.`

**Close order is safe either way.** Once `retire complete.` is printed, the handoff bundle (`retire_data.json` + snapshot) is on disk in DATA_DIR. The next session recovers it regardless of whether the old session is closed before or after the new one opens — `session_start` merges `retire_data` into `handoff_prev` even when the old session was force-closed first (a `foreman_reset.flag` no longer destroys it). No need to keep the old window open.

**end~:**
1. Confirm DATA_DIR (Rule 1-1)
2. Run `python ~/.claude/plugins/junior_mark/scripts/foreman_off.py "{DATA_DIR}"` + output exactly: `end complete.`

**Context judgement:**
- "move~" / "opening a new session" → move
- "end~" → end
- farewell / wrap-up / session move notice → ambiguous → present choices

**start~:** If `HOOK_FOREMAN_ON_DONE` is in system-reminder, do not run Claude further. Output exactly: `start complete.`

**on~/off~/restart~:** These are handled entirely by the hook (signal_checker.py). If `HOOK_FOREMAN_ON_DONE` is in system-reminder, do NOT run any scripts. Output exactly: `ctrl complete.`

**`~` suffix rule:** Do not trigger on mention in normal conversation. Only recognize as a command when `~` is appended.

## 6. Snapshot Rules

Save location: see CLAUDE.md Rule 5.

- For past content lookup → check MEMORY.md / MEMORY_MINE.md first. Only open snapshots with permission.
- Do not auto-open snapshots without permission.
- **Exception**: when `decided[]` is empty and `latest_snapshot` exists (auto-retire situation) → auto-read allowed (Rule 3-4 applies)

## 8. Foreman Status Verification Rule

- Never infer foreman status from handoff file existence. Absent `handoff.json` / `handoff_prev.json` only means no data written yet (e.g., fresh session or post-reset) — it says nothing about whether the foreman is running.
- To check actual foreman status: read the most recent `⎿ UserPromptSubmit says:` status bar output visible in the conversation. Never state "foreman is not running" or similar without reading the actual status bar or checking the pid file.

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
