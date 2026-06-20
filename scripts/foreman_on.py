#!/usr/bin/env python3
"""foreman on — atomically claim session lock + start a new foreman
Shared logic called by both /foreman on skill and start~ hook."""

import json
import os
import subprocess
import sys
from pathlib import Path

# [1] load bootstrap (paths / constants / stream init)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, read_transcript_tokens
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



def _session_id_from_relay(relay_file):
    """Extract session_id from the last user entry in relay.jsonl"""
    if not relay_file.exists():
        return None
    try:
        last_sid = None
        for line in relay_file.read_text(encoding='utf-8').splitlines():
            try:
                entry = json.loads(line)
                if entry.get('role') == 'user' and entry.get('session_id'):
                    last_sid = entry['session_id']
            except Exception:
                pass
        return last_sid
    except Exception:
        return None


def run(data_dir=None, session_id=None, transcript_path=None, cc_pid=None):
    DATA_DIR = get_data_dir(forced_path=data_dir) if data_dir else get_data_dir()
    P = get_jm_paths(DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    result = {
        "claimed": False,
        "already_active": False,
        "session_id": session_id,
        "pid": None,
        "error": None,
    }

    # if session_id missing, extract from last user entry in relay.jsonl
    if not session_id:
        session_id = _session_id_from_relay(P["relay"])
        result["session_id"] = session_id

    # 1. check current session lock
    sid_file = P["session_id"]
    if sid_file.exists():
        existing = sid_file.read_text(encoding='utf-8').strip()
        if existing == session_id:
            result["already_active"] = True  # already this session — just restart foreman
        else:
            result["error"] = f"another session is already active ({existing[:8]}...)"
            return result

    # 2. claim session lock
    if not result["already_active"]:
        if not session_id:
            result["error"] = "no session_id (not found in relay.jsonl either)"
            return result
        sid_file.write_text(session_id, encoding='utf-8')
        result["claimed"] = True

    # 3. record token usage
    tokens = read_transcript_tokens(transcript_path)
    if tokens:
        P["token_usage"].write_text(str(tokens), encoding='utf-8')

    # 4. stop existing foreman
    if P["pid"].exists():
        pid_str = P["pid"].read_text(encoding='utf-8').strip()
        if pid_str:
            subprocess.run(
                ["taskkill", "/F", "/PID", pid_str],
                capture_output=True, check=False
            )
        P["pid"].unlink(missing_ok=True)

    # 5. clean up stale files (remove context warning flags, clear reset_flag/retire_flag)
    for key in ("context_warn", "context_threshold", "reset_flag", "retire_flag", "foreman_exit"):
        p = P.get(key)
        if p and p.exists():
            p.unlink(missing_ok=True)

    # 5-1. restore CC PID — prevents fallback mode if cc_pid.txt was deleted by cleanup
    if cc_pid and P.get("cc_pid"):
        try:
            P["cc_pid"].write_text(str(cc_pid), encoding='utf-8')
        except Exception:
            pass

    # 6. start new foreman (with explicit JM_DATA_DIR)
    foreman_py = Path(__file__).parent / "foreman.py"
    env = os.environ.copy()
    env['JM_DATA_DIR'] = str(DATA_DIR)
    proc = subprocess.Popen(
        [sys.executable, str(foreman_py)],
        env=env,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    result["pid"] = proc.pid

    # 7. update session_foreman.json
    sf_file = P["session_foreman"]
    sf_data = {}
    if sf_file.exists():
        try:
            sf_data = json.loads(sf_file.read_text(encoding='utf-8'))
        except Exception:
            pass
    if session_id:
        sf_data[session_id] = result["pid"]  # store as int, same as session_start
    sf_file.write_text(json.dumps(sf_data, ensure_ascii=False), encoding='utf-8')

    return result


if __name__ == "__main__":
    # CLI: python foreman_on.py <data_dir> [session_id] [transcript_path]
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    session_id = sys.argv[2] if len(sys.argv) > 2 else None
    transcript_path = sys.argv[3] if len(sys.argv) > 3 else None
    cc_pid_arg = sys.argv[4] if len(sys.argv) > 4 else None
    cc_pid = int(cc_pid_arg) if cc_pid_arg and cc_pid_arg.isdigit() else None

    r = run(data_dir, session_id, transcript_path, cc_pid)

    if r.get("error"):
        print(f"[foreman on] ❌ {r['error']}")
    elif r.get("already_active"):
        print(f"[foreman on] ✓ already active session — foreman restarted PID {r['pid']}")
    else:
        print(f"[foreman on] ✓ claimed | PID {r['pid']}")
