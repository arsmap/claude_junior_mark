#!/usr/bin/env python3
"""foreman off — release session lock + stop foreman
Shared logic called by both /foreman off skill and end~ hook."""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# [1] load bootstrap (paths / constants / stream init)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, JM_BASE, CONTEXT_TOKENS_FALLBACK, WARN, THRESHOLD
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



def run(data_dir=None):
    DATA_DIR = get_data_dir(forced_path=data_dir) if data_dir else get_data_dir()
    P = get_jm_paths(DATA_DIR)
    result = {"killed_pid": None, "lock_released": False, "files_deleted": []}

    # 1. stop foreman
    if P["pid"].exists():
        pid_str = P["pid"].read_text(encoding="utf-8").strip()
        if pid_str:
            try:
                log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] foreman stopped (PID={pid_str}, foreman_off)\n"
                with open(P["log"], "a", encoding="utf-8") as f:
                    f.write(log_entry)
            except Exception:
                pass
            subprocess.run(
                ["taskkill", "/F", "/PID", pid_str],
                capture_output=True, check=False
            )
            result["killed_pid"] = pid_str
        P["pid"].unlink(missing_ok=True)
        result["files_deleted"].append("foreman.pid")

    # 2. release session lock — allow other sessions to become candidates
    if P["session_id"].exists():
        P["session_id"].unlink(missing_ok=True)
        result["lock_released"] = True
        result["files_deleted"].append("current_session_id.txt")

    # 3. clean up files (keep cc_pid — new foreman launched via start~ needs it to monitor CC in the same session)
    for key in ["token_usage", "retire_flag"]:
        p = P.get(key)
        if p and p.exists():
            p.unlink(missing_ok=True)
            result["files_deleted"].append(p.name)

    # 4. create reset_flag (signals handoff reset on next session start)
    P["reset_flag"].touch()

    # 5. create snapshot inline from relay.jsonl (same format as foreman_retire)
    try:
        entries = []
        if P["relay"].exists():
            for line in P["relay"].read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
        total_turns = sum(1 for e in entries if e.get('role') == 'assistant')
        total_chars = sum(e.get('chars', 0) for e in entries)
        now = datetime.now()
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
            snap_lines.append(f"  [{role}] {e.get('text', '')[:120]}")
        snap_lines.append('=' * 60)
        snapshots_dir = DATA_DIR / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        snap_file = snapshots_dir / f"off_{now.strftime('%Y%m%d_%H%M')}.txt"
        snap_file.write_text('\n'.join(snap_lines), encoding='utf-8')
        result["snapshot"] = snap_file.name
    except Exception:
        result["snapshot"] = False

    # 6. reset handoff.json — prevent sessions opened after end~ from reading stale context
    if P["handoff"].exists():
        try:
            empty_handoff = {
                "metrics": {"total_turns": 0, "total_chars": 0, "turn_pct": 0, "char_pct": 0, "context_tokens": 0, "token_pct": 0},
                "relationship": {"mood": "", "recent_jokes": []},
                "work": {"project": "", "status": "", "decided": [], "pending": []},
                "recent_turns": [],
                "handoff_message": "Session ended — type start~ to begin a new session."
            }
            P["handoff"].write_text(json.dumps(empty_handoff, ensure_ascii=False, indent=2), encoding="utf-8")
            result["handoff_reset"] = True
        except Exception:
            result["handoff_reset"] = False

    return result


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    r = run(data_dir)
    pid_msg = f"PID {r['killed_pid']} killed" if r["killed_pid"] else "no foreman (already stopped)"
    lock_msg = "session lock released" if r["lock_released"] else "no lock file"
    print(f"[foreman off] {pid_msg} / {lock_msg}")
