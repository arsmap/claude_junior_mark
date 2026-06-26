#!/usr/bin/env python3
"""statusLine hook — outputs JM status bar for TUI footer"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, CONTEXT_TOKENS_FALLBACK, CONTEXT_WINDOW_OVERHEAD, WARN, THRESHOLD, find_cc_pid, recover_data_dir_by_cc_pid, turn_threshold
except Exception:
    sys.exit(0)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        data = {}

    try:
        sid = data.get('session_id', '')
        DATA_DIR = get_data_dir(hook_cwd=data.get('cwd'), session_id=sid)
        if not sid:  # session_id absent → session_map bypassed; recover via cc_pid (cold path, rarely taken)
            DATA_DIR = recover_data_dir_by_cc_pid(DATA_DIR, find_cc_pid())
        P = get_jm_paths(DATA_DIR)
    except Exception:
        print("⚫ [░░░░░░░░░░░░░░░░░░░░] --% | JM")
        sys.stdout.flush()
        return

    # token count: prefer CC stdin, fallback to token_usage.txt
    cw = data.get('context_window', {})
    tokens = cw.get('total_input_tokens', 0)
    if not tokens:
        try:
            token_file = P.get('token_usage', DATA_DIR / 'token_usage.txt')
            if Path(token_file).exists():
                tokens = int(Path(token_file).read_text(encoding='utf-8').strip() or 0)
        except Exception:
            pass

    # context window: prefer CC stdin, fallback to dynamic read
    ctx_size = cw.get('context_window_size', 0)
    if ctx_size:
        # persist the live raw window size so other hooks (no access to CC stdin context_window)
        # can use it instead of the stale .claude.json cache
        try:
            P.get('ctx_window_live', DATA_DIR / 'ctx_window_live.txt').write_text(str(ctx_size), encoding='utf-8')
        except Exception:
            pass
        ctx_window = max(ctx_size - CONTEXT_WINDOW_OVERHEAD, 1)
    else:
        ctx_window = CONTEXT_TOKENS_FALLBACK
        try:
            cj_path = Path.home() / '.claude.json'
            if cj_path.exists():
                tw = json.loads(cj_path.read_text(encoding='utf-8')).get(
                    'cachedGrowthBookFeatures', {}).get('tengu_hawthorn_window')
                if tw:
                    ctx_window = int(tw)
        except Exception:
            pass
        ctx_window = max(ctx_window - CONTEXT_WINDOW_OVERHEAD, 1)

    pct = round(tokens / ctx_window * 100, 1) if ctx_window and tokens else 0.0

    # turn count: read pre-computed value from handoff.json (avoids relay.jsonl full scan)
    turns = 0
    try:
        handoff_file = P.get('handoff', DATA_DIR / 'handoff.json')
        if Path(handoff_file).exists():
            turns = json.loads(Path(handoff_file).read_text(encoding='utf-8')).get('metrics', {}).get('total_turns', 0)
    except Exception:
        pass

    # foreman pid (process existence check)
    foreman_alive = False
    foreman_pid_str = "----"
    try:
        pid_file = P.get('pid', DATA_DIR / 'foreman.pid')
        if Path(pid_file).exists():
            pid = Path(pid_file).read_text(encoding='utf-8').strip()
            if pid:
                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                    capture_output=True, check=False
                )
                out = r.stdout.decode(errors='replace')
                if pid in out and "python" in out.lower():
                    foreman_alive = True
                    foreman_pid_str = pid
    except Exception:
        pass

    dot = "🔴" if pct >= THRESHOLD else ("🟡" if pct >= WARN else "🟢")
    if not foreman_alive:
        # Detect new session startup by comparing session IDs
        current_sid = data.get('session_id', '')
        stored_sid = ''
        try:
            sid_path = Path(P.get('session_id', DATA_DIR / 'current_session_id.txt'))
            if sid_path.exists():
                stored_sid = sid_path.read_text(encoding='utf-8').strip()
        except Exception:
            pass

        if current_sid and current_sid != stored_sid:
            # New session: IDs differ → show 0 before session_start.py runs
            tokens = 0
            turns = 0
            pct = 0.0
            dot = "⚪"
            foreman_pid_str = "..."
        elif turns == 0:
            dot = "⚪"  # same session, foreman not yet ready
            try:
                pid_file_path = P.get('pid', DATA_DIR / 'foreman.pid')
                if Path(pid_file_path).exists():
                    raw = Path(pid_file_path).read_text(encoding='utf-8').strip()
                    if raw:
                        foreman_pid_str = raw
                else:
                    foreman_pid_str = "..."
            except Exception:
                foreman_pid_str = "..."
        else:
            dot = "⚫"  # mid-session foreman death — show last known values

    # fresh start in the same window (/clear or new session): session_id differs from the stored one.
    # Show a clean "session just started" bar (⚪ 0.0% | 0/win | 0/T | PID:...) for this one render,
    # so /clear looks like a fresh session instead of carrying the cleared context's token usage.
    # The next prompt restores live values from CC stdin. statusline stdin has no 'source' field, so
    # detect via session_id mismatch; skip guest sessions so their bar is untouched.
    try:
        fresh_sid = data.get('session_id', '')
        fresh_stored = ''
        fresh_sid_path = Path(P.get('session_id', DATA_DIR / 'current_session_id.txt'))
        if fresh_sid_path.exists():
            fresh_stored = fresh_sid_path.read_text(encoding='utf-8').strip()
        fresh_guest = Path(P.get('is_guest_flag', DATA_DIR / 'is_guest.flag'))
        if fresh_sid and fresh_sid != fresh_stored and not fresh_guest.exists():
            tokens = 0
            pct = 0.0
            dot = "⚪"
            turns = 0
            foreman_pid_str = "..."
    except Exception:
        pass

    filled = max(0, min(20, round(pct / 100 * 20)))
    bar = "█" * filled + "░" * (20 - filled)
    k_tok = str(tokens // 1000) if tokens >= 1000 else str(tokens)
    k_win = f"{ctx_window // 1000}K"

    print(f"{dot} [{bar}] {pct}% | {k_tok}/{k_win} | {turns}/{turn_threshold(ctx_window)}T | PID:{foreman_pid_str}")
    sys.stdout.flush()


if __name__ == '__main__':
    main()
