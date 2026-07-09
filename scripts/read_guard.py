#!/usr/bin/env python3
"""PreToolUse guard for the Bash and PowerShell tools.

Denies bare file-read commands (cat/tail/head, Get-Content/gc/type,
[System.IO.File]::ReadAll*) and points to the Read tool instead.
Shell file reads break UTF-8 Korean under the cp949 console (PowerShell
5.1 reads BOM-less UTF-8 as ANSI) and non-allowlisted variants trigger
permission prompts; the Read tool has neither problem.

Conservative by design -- zero false positives first:
- only a *bare* read is denied; a command that pipes the content into
  further processing (`|`) is allowed
- redirects/heredocs (`>`, `<`, `<<`) are writes or input feeds -> allowed
- `tail -f` / `tail -F` (follow mode, which Read cannot do) is allowed
- .NET ReadAll* is denied even in compound statements (that is exactly
  the encoding-workaround pattern this guard targets), unless the same
  command also writes (WriteAll*/Set-Content/Out-File/Add-Content)

Fail-open: registered with `|| true`; if this script crashes, the
command simply runs unguarded.
"""
import json
import re
import sys

# Bash tool: a single simple command -- cat/tail/head + args, no pipe,
# no redirect, no chaining, whole-command match.
BASH_BARE_READ = re.compile(r"^\s*(cat|tail|head)\s+[^|<>;&]+$")
TAIL_FOLLOW = re.compile(r"^\s*tail\s+[^|<>;&]*-[a-zA-Z]*[fF]")

# PowerShell tool: bare Get-Content/gc/type/cat, no pipe/chain/redirect.
PS_BARE_READ = re.compile(r"^\s*(Get-Content|gc|type|cat)\s+[^|<>;&]+$", re.IGNORECASE)
# .NET file read -- the encoding-workaround pattern; caught even when chained.
PS_DOTNET_READ = re.compile(r"\[(?:System\.)?IO\.File\]::ReadAll\w*", re.IGNORECASE)
PS_WRITE_HINT = re.compile(
    r"WriteAll\w*|Set-Content|Out-File|Add-Content|>", re.IGNORECASE)

REASON = (
    "Bare shell file-read detected. Shell reads break UTF-8 Korean under the "
    "cp949 console (PowerShell reads BOM-less UTF-8 as ANSI) and non-allowlisted "
    "variants trigger permission prompts. Use the Read tool instead (offset/limit "
    "for partial reads). Piped processing, redirects/heredocs, and `tail -f` are allowed."
)


def is_bare_read(tool_name, command):
    if tool_name == "Bash":
        if TAIL_FOLLOW.match(command):
            return False
        return bool(BASH_BARE_READ.match(command))
    if tool_name == "PowerShell":
        if PS_BARE_READ.match(command):
            return True
        if PS_DOTNET_READ.search(command) and not PS_WRITE_HINT.search(command):
            return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # can't parse -> stay out of the way

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Bash", "PowerShell"):
        return

    command = data.get("tool_input", {}).get("command", "")
    if not command or not is_bare_read(tool_name, command):
        return

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
