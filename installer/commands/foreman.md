# /foreman

Foreman status check and control.

> **Important**: Always use this `/foreman` skill to check or control foreman status.
> Do not manually assemble PowerShell paths or read `foreman.pid` directly.
> (Direct path assembly can mis-reference the DATA_DIR structure and produce false diagnostics.)

## Usage

```
/foreman          Show status
/foreman status   Show status (same)
/foreman restart  Restart foreman
/foreman on       Claim session lock + start foreman (reactivate after end~)
/foreman retire   Retire this session (save snapshot + warn next session, foreman stays running)
/foreman off      Stop foreman (next session starts fresh)
/foreman log      Show recent log output
```

## ⛔ Step 0: Check for guest / stale session (applies to all commands — highest priority)

**Guest session check**: If `IS_GUEST=true` is present in system-reminder, output the following single line and stop.
Do not execute any PowerShell or Python commands.

```
This command is not available in a guest session.
```

**Stale session check**: If `This session is no longer valid` is present in the conversation context, output the following single line and stop.
Do not execute any PowerShell or Python commands.

```
    - status : ⚠️ stale session — this session's foreman has been replaced. Please open a new session.
```

---

## Status check

Run the PowerShell block below in one call and output the result in the format shown.

> **No automatic action after output**: After printing the 6-line format, do not suggest, guide, or auto-process anything. Only act when the user explicitly issues a command.

```
    - foreman    : alive / dead
    - PID        : N ✓/✗
    - turns      : N / 30 (X%)          ← if N=0: 0 / 30 (0% -> Reset)
    - transcript : N,NNN / 50,000 byte  ← byte count with comma format
    - token      : N (X%)               ← if N=0: 0 (0% -> Reset)
    - signal     : none  / warn / trsd
```

`signal` has two trailing spaces after `none` (`none  `), no spaces after `warn` or `trsd`.

```powershell
$MAX_TURNS = 30; $MAX_TRANSCRIPT = 50000
$jmBase = "$env:USERPROFILE\.claude\plugins\junior_mark"
$cwd = (Get-Location).Path
$drive = $cwd[0]
$rest = $cwd.Substring(2) -replace '[/\\]', '--'
$slug = "$drive$rest"
$data = "$jmBase\data\$slug"
if (-not (Test-Path $data)) {
    Write-Host "DATA_DIR not found: $data"
    exit 1
}
$pidFile = "$data\foreman.pid"
$pidVal = if (Test-Path $pidFile) { (Get-Content $pidFile -Raw).Trim() } else { $null }
$alive = if ($pidVal) { if (Get-Process -Id $pidVal -ErrorAction SilentlyContinue) { "alive" } else { "dead" } } else { "dead" }
$relay = "$data\relay.jsonl"
$turns = 0; $transcriptBytes = 0
if (Test-Path $relay) {
    $transcriptBytes = (Get-Item $relay).Length
    $turns = (Get-Content $relay | Where-Object { $_ -match '"role":\s*"assistant"' }).Count
}
$turnPct = [math]::Round($turns / $MAX_TURNS * 100, 1)
$signal = if (Test-Path "$data\context_threshold.flag") { "trsd" } elseif (Test-Path "$data\context_warn.flag") { "warn" } else { "none" }
$contextWindow = 200000
try {
    $claudeJson = Get-Content "$env:USERPROFILE\.claude.json" -Raw | ConvertFrom-Json
    $tw = $claudeJson.cachedGrowthBookFeatures.tengu_hawthorn_window
    if ($tw) { $contextWindow = [int]$tw }
} catch {}
$tokens = 0; $tokenPct = 0
$tokenFile = "$data\token_usage.txt"
if (Test-Path $tokenFile) {
    $tokens = [int](Get-Content $tokenFile -Raw).Trim()
    $tokenPct = [math]::Round($tokens / $contextWindow * 100, 1)
}
Write-Host "alive=$alive pid=$pidVal"
Write-Host "turns=$turns/$MAX_TURNS/$turnPct"
Write-Host "transcript=$transcriptBytes/$MAX_TRANSCRIPT"
Write-Host "token=$tokens/$tokenPct"
Write-Host "signal=$signal"
```

## restart

1. Read PID from `foreman.pid` and run `taskkill /F /PID <pid>` via PowerShell.
2. Delete `relay.jsonl`, `last_prompt.txt`, `session_warn.txt`, `transcript_usage.txt`, `token_usage.txt`, `context_warn.flag`, `context_threshold.flag`, `foreman_reset.flag`.
3. Run `python ~/.claude/plugins/junior_mark/scripts/foreman.py` in the background.
4. After 2 seconds, run the status check block (PowerShell above) and output in the same 6-line format.

Note: Deleting relay.jsonl resets the turn count to 0, so token_usage.txt is deleted together for consistency. On the next prompt, signal_checker.py parses the transcript JSONL and writes a fresh token_usage.txt.

## retire

Retire this session (foreman stays running):
1. Compute slug from CWD (same method as `$slug` in the `## Status check` PowerShell).
2. Run `python ~/.claude/plugins/junior_mark/scripts/foreman_retire.py`.
3. Output the content after `[Junior Mark]` in the systemMessage **verbatim, without summarizing**. Example:

```
● retire complete.

    - foreman    : alive
    - PID        : N ✓
    - turns      : N / 30 (X%)
    - transcript : N,NNN / 50,000 byte
    - token      : N,NNN (X%)
    - signal     : none
    ---------------------------------
    - retired session !
    - snapshot  : retire_YYYYMMDD_HHMM.txt
    - decided   : N

    See you in the next session!
```

## on

Claim session lock + start a new foreman. Used to make the current session active after `end~`.
`start~` keyword triggers signal_checker hook automatically — this command is for manual override.

1. Compute DATA_DIR from CWD slug (same method as `$data` in the `## Status check` PowerShell).
2. Run `python ~/.claude/plugins/junior_mark/scripts/foreman_on.py {DATA_DIR}`.
   - foreman_on.py auto-extracts session_id from the last user entry in relay.jsonl → claims session lock.
3. After 2 seconds, run the status check block and output in the same 6-line format.

```
● foreman on complete.

    - foreman    : alive
    - PID        : N ✓
    - turns      : N / 30 (X%)
    - transcript : N,NNN / 50,000 byte
    - token      : N (X%)
    - signal     : none
```

Note: On claim failure (`❌ another session is already active`) — output as-is and stop. No further action.

## off

1. Compute slug from CWD (same method as `$slug` in the `## Status check` PowerShell).
2. Run `python ~/.claude/plugins/junior_mark/scripts/foreman_off.py` and output the result in the format below.

```
● foreman off complete.

    - PID        : N killed / no foreman (already stopped)
    - session lock : released / no lock file
    - other sessions : can now activate with /foreman on
```

Note: Releasing the session lock (current_session_id.txt) makes other open sessions candidates. relay.jsonl/handoff.json are kept. foreman_reset.flag is created → handoff resets on next new session start.

## log

Output the last 30 lines of `foreman.log`.
