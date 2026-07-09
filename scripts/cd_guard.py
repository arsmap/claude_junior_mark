#!/usr/bin/env python3
"""PreToolUse guard for the Bash tool.

Blocks the harmful pattern where `cd <dir>` is used as a launcher for another
chained command (e.g. `cd /some/path && git log`). That pattern changes the
session-global working directory, polluting the CWD for later tool calls, and
also triggers the extra permission prompt for cross-directory execution.

A standalone `cd "path"` (used by the JM CWD_RESTORE recovery, Rule 0-1) is left
alone -- only a `cd` that is chained (via && or ;) into another command is denied.

Suggests `git -C <abs-path>` / absolute paths instead.
"""
import json
import re
import sys

# Match a `cd <arg>` segment that is followed by a chained command (&& or ;).
# Anchored to a segment boundary (start, &&, ;, or pipe) so `abcd` won't match.
CHAINED_CD = re.compile(r"(?:^|&&|;|\|)\s*cd\s+[^&;]*(?:&&|;)")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # can't parse -> stay out of the way

    if data.get("tool_name") != "Bash":
        return

    command = data.get("tool_input", {}).get("command", "")
    if not CHAINED_CD.search(command):
        return

    reason = (
        "Chained `cd` detected. `cd <dir> && <cmd>` pollutes the session-global "
        "working directory for later tool calls. Use an absolute path instead "
        "(e.g. `git -C <abs-path> ...`), or run the command with a full path. "
        "A standalone `cd \"path\"` for CWD restore is allowed."
    )
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
