#!/usr/bin/env python3
"""PostToolUse hook — detect context spike mid-tool and write force_retire.flag"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, CONTEXT_TOKENS_FALLBACK, CONTEXT_WINDOW_OVERHEAD, THRESHOLD, JM_BASE
except Exception:
    sys.exit(0)

DEBUG_FILE = JM_BASE / "debug" / "post_tool_use_jm_debug.txt"

def dbg(msg):
    try:
        DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return

    try:
        DATA_DIR = get_data_dir(hook_cwd=data.get('cwd'), session_id=data.get('session_id', ''))
        P = get_jm_paths(DATA_DIR)
    except Exception:
        return

    # Skip if session already ended or moved
    if P.get('reset_flag', DATA_DIR / 'foreman_reset.flag').exists():
        return
    if P.get('retire_flag', DATA_DIR / 'foreman_retire.flag').exists():
        return

    # Skip if force_retire already pending or muted by user
    force_flag = Path(P.get('force_retire', DATA_DIR / 'force_retire.flag'))
    if force_flag.exists():
        return
    if Path(P.get('force_retire_mute', DATA_DIR / 'force_retire_mute.flag')).exists():
        dbg("force_retire muted — skip")
        return

    # Token count from CC stdin context_window
    cw = data.get('context_window', {})
    tokens = cw.get('total_input_tokens', 0)
    tool = data.get('tool_name', 'unknown')
    dbg(f"tool={tool} cw_keys={list(cw.keys())} tokens={tokens} THRESHOLD={THRESHOLD}")

    if not tokens:
        dbg("no token info — skip")
        return  # No token info — skip

    ctx_size = cw.get('context_window_size', 0) or CONTEXT_TOKENS_FALLBACK
    ctx_window = max(ctx_size - CONTEXT_WINDOW_OVERHEAD, 1)
    pct = round(tokens / ctx_window * 100, 1)
    dbg(f"ctx_size={ctx_size} ctx_window={ctx_window} pct={pct}")

    if pct >= THRESHOLD:
        try:
            msg = (f"Context spike mid-tool ({tool}): {pct}% ({tokens:,}/{ctx_window:,} tokens) "
                   f"— immediate session move required.")
            dbg(f"writing force_retire.flag: {msg[:80]}")
            force_flag.write_text(msg, encoding='utf-8')
        except Exception as e:
            dbg(f"write error: {e}")


if __name__ == '__main__':
    main()
