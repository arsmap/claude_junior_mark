#!/usr/bin/env python3
"""foreman_retire.py — session retire: write session_warn + create snapshot + print completion message"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# [1] load bootstrap (paths / constants / stream init)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, CHAR_THRESHOLD, turn_threshold, read_eff_window
except Exception:
    try:
        from pathlib import Path as _P; from datetime import datetime as _dt; import traceback as _tb
        _dbg = _P.home() / '.claude' / 'plugins' / 'junior_mark' / 'debug' / 'bootstrap_import_error.txt'
        _dbg.parent.mkdir(parents=True, exist_ok=True)
        _dbg.write_text(
            f"[{_dt.now():%Y-%m-%d %H:%M:%S}] bootstrap import failed in {_P(__file__).name}\n"
            f"{_tb.format_exc()}",
            encoding='utf-8'
        )
    except Exception:
        pass
    raise



def main():
    # pass CLI arg if provided; None falls through to shared path logic
    forced_arg = sys.argv[1] if len(sys.argv) > 1 else None
    DATA_DIR = get_data_dir(forced_path=forced_arg)

    P = get_jm_paths(DATA_DIR)

    # 1. write session_warn.txt
    warn_msg = f"Session move requested at {datetime.now().strftime('%H:%M')}. Review previous context before continuing."
               # "⚠️ This session has retired — continue in a new session. (/foreman restart to reactivate)",
    try:
        P["session_warn"].write_text(warn_msg, encoding="utf-8")
    except Exception as e:
        print(f"Error writing session_warn: {e}")

    # 2. create snapshot (use DATA_DIR directly — avoids snapshot.py PWD dependency)
    entries = []
    if P["relay"].exists():
        try:
            for line in P["relay"].read_text(encoding="utf-8").splitlines():
                if line.strip(): entries.append(json.loads(line))
        except: pass

    total_turns = sum(1 for e in entries if e.get('role') == 'assistant')
    total_chars = sum(e.get('chars', 0) for e in entries)

    handoff = {}
    try:
        if P["handoff"].exists():
            handoff = json.loads(P["handoff"].read_text(encoding='utf-8'))
    except: pass

    # collect extra metrics
    transcript_bytes = P["relay"].stat().st_size if P["relay"].exists() else 0

    context_tokens = 0
    try:
        if P["token_usage"].exists():
            context_tokens = int(P["token_usage"].read_text(encoding='utf-8').strip())
    except: pass

    metrics = handoff.get('metrics', {})
    turn_pct = metrics.get('turn_pct', 0)
    token_pct = metrics.get('token_pct', 0)
    if not context_tokens:
        context_tokens = metrics.get('context_tokens', 0)

    now = datetime.now()
    ts  = now.strftime('%Y%m%d_%H%M')

    snap_lines = [
        '=' * 60,
        f"  Session snapshot — {now.strftime('%Y-%m-%d %H:%M')}  ({DATA_DIR.name})",
        '=' * 60,
        '',
        f"  total turns : {total_turns}",
        f"  total chars : {total_chars:,}",
        '',
        '  recent turns (last 10):',
    ]
    for e in entries[-10:]:
        role = 'user' if e.get('role') == 'user' else 'asst'
        text = e.get('text', '')[:120]
        snap_lines.append(f"  [{role}] {text}")

    if handoff.get('handoff_message'):
        snap_lines += ['', f"  handoff: {handoff['handoff_message']}"]
    snap_lines.append('=' * 60)

    snapshots_dir = DATA_DIR / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snap_file = snapshots_dir / f"retire_{ts}.txt"

    # 3. print completion message (signal_checker → systemMessage / skill → Claude output)
    try:
        snap_file.write_text('\n'.join(snap_lines), encoding='utf-8')

        # merge decided + latest_snapshot from pre_retire_summary.json into handoff.json
        decided = []
        pre_summary_to_delete = None
        pre_summary = P.get("pre_retire_summary", DATA_DIR / "pre_retire_summary.json")
        try:
            if pre_summary.exists():
                pre_data = json.loads(pre_summary.read_text(encoding='utf-8'))
                decided = pre_data.get('decided', [])
                pre_summary_to_delete = pre_summary  # delete after retire_data.json written successfully
        except: pass

        decided_count = len(decided)
        try:
            retire_data_file = P.get("retire_data", DATA_DIR / "retire_data.json")
            retire_data_file.write_text(
                json.dumps({
                    "decided": decided,
                    "latest_snapshot": str(snap_file),
                    "stats": {
                        "turns": total_turns,
                        "turn_pct": turn_pct,
                        "transcript_bytes": transcript_bytes,
                        "context_tokens": context_tokens,
                        "token_pct": token_pct,
                    }
                }, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            if pre_summary_to_delete:
                pre_summary_to_delete.unlink(missing_ok=True)
        except: pass

        # flag to prevent duplicate move~ execution
        try: P["retire_flag"].touch()
        except: pass

        # collect foreman status
        pid_val = None
        foreman_alive = "dead"
        try:
            if P["pid"].exists():
                pid_val = P["pid"].read_text(encoding='utf-8').strip()
                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid_val}", "/NH", "/FO", "CSV"],
                    capture_output=True, text=True
                )
                if pid_val in r.stdout:
                    foreman_alive = "alive"
        except: pass

        pid_display = f"{pid_val} ✓" if foreman_alive == "alive" else f"{pid_val or '?'} ✗"
        ctx_warn_status = "yes" if P.get("context_warn", DATA_DIR / "context_warn.flag").exists() else "none"
        eff_window = read_eff_window(P, DATA_DIR)
        turn_pct_f  = round(total_turns / turn_threshold(eff_window) * 100, 1)
        token_pct_f = round(context_tokens / eff_window * 100, 1) if context_tokens else 0.0

        msg = (
            f"    - foreman    : {foreman_alive}\n"
            f"    - PID        : {pid_display}\n"
            f"    - turns      : {total_turns} / {turn_threshold(eff_window)} ({turn_pct_f}%)\n"
            f"    - transcript : {transcript_bytes:,} / {CHAR_THRESHOLD:,} byte\n"
            f"    - token      : {context_tokens:,} ({token_pct_f}%)\n"
            f"    - ctx_warn   : {ctx_warn_status}\n"
            f"    ---------------------------------\n"
            f"    - retired session !\n"
            f"    - snapshot  : {snap_file.name}\n"
            f"    - decided   : {decided_count}"
        )
        print(f'[Junior Mark] {msg}')
        sys.stdout.flush()
    except Exception as e:
        print(f'[Junior Mark] snapshot save error: {e}')


if __name__ == '__main__':
    main()
