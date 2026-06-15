#!/usr/bin/env python3
"""statusLine hook — outputs JM status bar for TUI footer"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, CONTEXT_TOKENS_FALLBACK, CONTEXT_WINDOW_OVERHEAD, WARN, THRESHOLD
except Exception:
    sys.exit(0)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        data = {}

    try:
        DATA_DIR = get_data_dir(hook_cwd=data.get('cwd'))
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

    # turn count
    turns = 0
    try:
        relay = P.get('relay', DATA_DIR / 'relay.jsonl')
        if Path(relay).exists():
            with open(relay, encoding='utf-8') as f:
                for line in f:
                    if '"role": "assistant"' in line or '"role":"assistant"' in line:
                        turns += 1
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
        if turns == 0:
            dot = "⚪"  # new session startup — foreman may not be ready yet
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
            dot = "⚫"
    filled = max(0, min(20, round(pct / 100 * 20)))
    bar = "█" * filled + "░" * (20 - filled)
    k_tok = f"{tokens // 1000}K" if tokens >= 1000 else str(tokens)
    k_win = f"{ctx_window // 1000}K"

    print(f"{dot} [{bar}] {pct}% | {k_tok}/{k_win} | {turns}T/30T | PID:{foreman_pid_str}")
    sys.stdout.flush()


if __name__ == '__main__':
    main()
