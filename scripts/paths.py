import json
import os
import re
from pathlib import Path

# base paths
HOME = Path.home()
#JM_BASE = HOME / '.claude' / 'junior_mark'
JM_BASE = HOME / '.claude' / 'plugins' / 'junior_mark'
CLAUDE_DIR = HOME / '.claude'

SESSION_MAP_FILE = JM_BASE / 'session_map.json'

def register_session(session_id, data_dir):
    """Register session_id → DATA_DIR mapping (prevents hook CWD pollution)"""
    if not session_id:
        return
    try:
        SESSION_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        m = {}
        if SESSION_MAP_FILE.exists():
            try:
                m = json.loads(SESSION_MAP_FILE.read_text(encoding='utf-8'))
            except Exception:
                m = {}
        m[session_id] = str(data_dir)
        if len(m) > 50:
            for k in list(m.keys())[:len(m) // 2]:
                del m[k]
        SESSION_MAP_FILE.write_text(json.dumps(m, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass

def lookup_session(session_id):
    """Look up DATA_DIR by session_id. Returns None if not found."""
    if not session_id or not SESSION_MAP_FILE.exists():
        return None
    try:
        m = json.loads(SESSION_MAP_FILE.read_text(encoding='utf-8'))
        p = m.get(session_id)
        if p:
            result = Path(p)
            if result.exists():
                return result
    except Exception:
        pass
    return None

def get_data_dir(*, forced_path=None, hook_cwd=None, session_id=None):
    # """Resolve Junior Mark data directory (unified logic)"""
    # 0. highest priority: explicitly passed path (e.g. from sys.argv)
    if forced_path:
        p = Path(forced_path)
        if p.exists(): return p
        # auto-expand slug form (no path separator but contains '--')
        s = str(forced_path)
        if '--' in s and '\\' not in s and '/' not in s:
            expanded = JM_BASE / 'data' / s
            if expanded.exists(): return expanded

    # 1. environment variable takes priority
    if os.environ.get('JM_DATA_DIR'):
        return Path(os.environ['JM_DATA_DIR'])

    # 2. session_id map lookup (prevents hook CWD pollution — prefers DATA_DIR registered at session start)
    if session_id:
        result = lookup_session(session_id)
        if result:
            return result

    # 3. hook_cwd (path provided by Claude Code)
    cwd = Path(hook_cwd or os.environ.get('PWD', os.getcwd()))

    # fall back to HOME when accessing system folders
    blocked = cwd == CLAUDE_DIR or cwd.parts[:len(CLAUDE_DIR.parts)] == CLAUDE_DIR.parts
    if blocked: cwd = HOME

    cwd_str = str(cwd).replace('\\', '/')
    slug = re.sub(r'^([A-Za-z]):', r'\1', cwd_str).replace('/', '--').lstrip('-')
    return JM_BASE / 'data' / slug

def get_jm_paths(d):
    """Path map for key files in the data directory"""
    return {
        "relay": d / "relay.jsonl", "handoff": d / "handoff.json", 
        "context_warn": d / "context_warn.flag", "pid": d / "foreman.pid",
        "hash": d / "foreman_hash.txt", "log": d / "foreman.log",
        "session_warn": d / "session_warn.txt",
        "last_prompt": d / "last_prompt.txt",
        "token_usage": d / "token_usage.txt",
        "ctx_window_live": d / "ctx_window_live.txt",
        "pre_retire_summary": d / "pre_retire_summary.json",
        "retire_data": d / "retire_data.json",
        "handoff_prev": d / "handoff_prev.json",
        "reset_flag": d / "foreman_reset.flag",
        "retire_flag": d / "foreman_retire.flag",
        "session_id": d / "current_session_id.txt",
        "session_foreman": d / "session_foreman.json",
        "guest_session_id": d / "guest_session_id.txt",
        "is_guest_flag": d / "is_guest.flag",
        "cc_pid": d / "cc_pid.txt",
        "context_threshold": d / "context_threshold.flag",
        "foreman_exit": d / "foreman_exit.flag",
        "post_compact": d / "post_compact.flag",
        "cwd_restore": d / "cwd_restore.flag",
        "cwd_restored": d / "cwd_restored.flag",
    }