#!/usr/bin/env python3
"""junior_mark common initialization module.

Add to the top of each script:
    sys.path.insert(0, str(Path(__file__).parent))
    from bootstrap import get_data_dir, get_jm_paths, JM_BASE, CONTEXT_TOKENS_FALLBACK, WARN, THRESHOLD
"""
import inspect
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ── system constants ─────────────────────────────────────────────
# context window fallback (used when live token limit is unavailable). measured baseline: 200K.
# effective CC limit ≈ 178K (200K minus ~22K overhead).
# prior bug (167K fallback) reproduced: WARN=87%×167K≈145K, THRESHOLD=97%×167K≈162K
# → converted to 200K basis: 145K/200K=72%, 162K/200K=81%
CONTEXT_TOKENS_FALLBACK = 200_000
CONTEXT_WINDOW_OVERHEAD = 30_000  # CC compact triggers at ~170K effective window
TURN_THRESHOLD = 30
CHAR_THRESHOLD = 50_000
WARN      = 82   # 164K tokens → CC ~10% remaining
THRESHOLD = 92   # 184K tokens → CC  ~0% remaining

# ── track caller filename ───────────────────────────────────────
_stack = inspect.stack()
_caller_file = _stack[1].filename if len(_stack) > 1 else __file__

# ── load paths.py ────────────────────────────────────────────────
try:
    from paths import get_data_dir, get_jm_paths, JM_BASE, register_session, lookup_session, cwd_to_slug, slug_to_path, recover_data_dir_by_cc_pid
except Exception as _paths_err:
    import traceback as _tb
    _fallback_base = Path.home() / '.claude' / 'plugins' / 'junior_mark'
    _filename = Path(_caller_file).name
    _dbg = _fallback_base / "debug" / "foreman_import_error.txt"
    try:
        _dbg.parent.mkdir(parents=True, exist_ok=True)
        _dbg.write_text(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] paths.py import failed : {_filename}\n"
            f"sys.path[0]: {sys.path[0]}\n"
            f"__file__: {_caller_file}\n"
            f"error: {_tb.format_exc()}\n",
            encoding='utf-8'
        )
    except Exception:
        pass

    JM_BASE = _fallback_base
    def get_data_dir(hook_cwd=None, **kwargs): return _fallback_base / 'data' / 'default'
    def register_session(sid, data_dir): pass
    def lookup_session(sid): return None
    import re as _re
    def cwd_to_slug(cwd): return _re.sub(r'^([A-Za-z]):', r'\1', str(cwd).replace('\\', '/')).replace('/', '--').lstrip('-')
    def slug_to_path(slug): return f"{slug[0]}:{slug[1:].replace('--', chr(92))}"
    def recover_data_dir_by_cc_pid(data_dir, cc_pid): return data_dir
    def get_jm_paths(d): return {
        "relay":             d / "relay.jsonl",
        "handoff":           d / "handoff.json",
        "handoff_prev":      d / "handoff_prev.json",
        "context_warn":      d / "context_warn.flag",
        "context_threshold": d / "context_threshold.flag",
        "pid":               d / "foreman.pid",
        "hash":              d / "foreman_hash.txt",
        "log":               d / "foreman.log",
        "session_warn":      d / "session_warn.txt",
        "last_prompt":       d / "last_prompt.txt",
        "token_usage":       d / "token_usage.txt",
        "ctx_window_live":   d / "ctx_window_live.txt",
        "reset_flag":        d / "foreman_reset.flag",
        "retire_flag":       d / "foreman_retire.flag",
        "retire_data":       d / "retire_data.json",
        "pre_retire_summary": d / "pre_retire_summary.json",
        "session_id":        d / "current_session_id.txt",
        "session_foreman":   d / "session_foreman.json",
        "guest_session_id":  d / "guest_session_id.txt",
        "is_guest_flag":     d / "is_guest.flag",
        "cc_pid":            d / "cc_pid.txt",
        "foreman_exit":      d / "foreman_exit.flag",
        "post_compact":      d / "post_compact.flag",
        "cwd_restore":       d / "cwd_restore.flag",
        "cwd_restored":      d / "cwd_restored.flag",
        "force_retire":      d / "force_retire.flag",
        "force_retire_mute": d / "force_retire_mute.flag",
    }

# ── ensure required base directories exist ───────────────────────
try:
    (JM_BASE / 'debug').mkdir(parents=True, exist_ok=True)
    (JM_BASE / 'data').mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# ── stream setup ─────────────────────────────────────────────────
sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding="utf-8")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


# ── find Claude Code process PID (shared by hooks) ───────────────
def find_cc_pid():
    """Walk the process tree upward and return the PID of the claude process. Returns None if not found."""
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        k32 = ctypes.windll.kernel32
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snap == -1: return None

        pid_map = {}
        try:
            e = PROCESSENTRY32()
            e.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if k32.Process32First(snap, ctypes.byref(e)):
                while True:
                    name = e.szExeFile.decode('utf-8', errors='replace').lower()
                    pid_map[e.th32ProcessID] = (e.th32ParentProcessID, name)
                    if not k32.Process32Next(snap, ctypes.byref(e)): break
        finally:
            k32.CloseHandle(snap)

        pid = os.getpid()
        last_orphan_pid = None
        for _ in range(15):
            info = pid_map.get(pid)
            if not info: break
            parent_pid, _ = info
            parent_info = pid_map.get(parent_pid)
            if not parent_info:
                last_orphan_pid = parent_pid  # remember parent PID missing from snapshot
                break
            _, parent_name = parent_info
            if 'claude' in parent_name:
                return parent_pid
            pid = parent_pid

        # fallback 1: query the missing parent directly via OpenProcess
        # (handles cases where the hook's bash parent is absent from the snapshot due to MSYS2/Cygwin layer)
        if last_orphan_pid:
            try:
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, last_orphan_pid)
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(260)
                        size = wintypes.DWORD(260)
                        k32.QueryFullProcessImageNameW.argtypes = [
                            wintypes.HANDLE, wintypes.DWORD,
                            ctypes.c_wchar_p, ctypes.POINTER(wintypes.DWORD)
                        ]
                        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
                        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                            if 'claude' in buf.value.lower():
                                return last_orphan_pid
                    finally:
                        k32.CloseHandle(handle)
            except Exception:
                pass

        # fallback 2: scan all claude.exe entries in the snapshot
        # used when ancestor traversal breaks due to MSYS2 PID remapping
        claude_pids = [p for p, (_, nm) in pid_map.items() if 'claude' in nm]
        if len(claude_pids) == 1:
            return claude_pids[0]
        elif len(claude_pids) > 1:
            # pick the claude.exe with the most child processes
            # (the main session has more children due to hook execution)
            def descendant_count(root, depth=0):
                if depth > 6: return 0
                total = 0
                for p, (par, _) in pid_map.items():
                    if par == root:
                        total += 1 + descendant_count(p, depth + 1)
                return total
            return max(claude_pids, key=lambda p: descendant_count(p))

        return None
    except Exception:
        return None


# ── effective context window (raw window - overhead), shared ─────
def read_eff_window(P=None, DATA_DIR=None):
    """Effective context window = raw window - overhead.
    Priority: ctx_window_live.txt (statusline persists CC stdin) -> .claude.json -> FALLBACK."""
    try:
        live_file = (P.get("ctx_window_live") if P else None) or (DATA_DIR / "ctx_window_live.txt" if DATA_DIR is not None else None)
        if live_file is None:
            raise FileNotFoundError
        raw = int(Path(live_file).read_text(encoding='utf-8').strip())
    except Exception:
        try:
            cj = json.loads((Path.home() / '.claude.json').read_text(encoding='utf-8'))
            raw = int(cj.get('cachedGrowthBookFeatures', {}).get('tengu_hawthorn_window', CONTEXT_TOKENS_FALLBACK))
        except Exception:
            raw = CONTEXT_TOKENS_FALLBACK
    return max(raw - CONTEXT_WINDOW_OVERHEAD, 1)


# ── sum tokens from last assistant message in transcript JSONL, shared ─────
def read_transcript_tokens(transcript_path):
    """Sum input + cache_read + cache_creation tokens from the last assistant
    message's usage in the transcript JSONL. Returns int (0 if none/unreadable)."""
    if not transcript_path or not Path(transcript_path).exists():
        return 0
    last_usage = None
    try:
        with open(transcript_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    msg = d.get('message', {})
                    if isinstance(msg, dict) and msg.get('role') == 'assistant':
                        u = msg.get('usage')
                        if u:
                            last_usage = u
                except Exception:
                    pass
    except Exception:
        return 0
    if last_usage:
        return (last_usage.get('input_tokens', 0) +
                last_usage.get('cache_read_input_tokens', 0) +
                last_usage.get('cache_creation_input_tokens', 0))
    return 0


# ── handoff building (shared by foreman daemon + relay_writer Stop hook) ─────
def read_token_usage(P=None, DATA_DIR=None):
    """Read persisted token count from token_usage.txt. Returns int (0 if absent)."""
    try:
        f = (P.get("token_usage") if P else None) or (DATA_DIR / "token_usage.txt" if DATA_DIR is not None else None)
        if f and Path(f).exists():
            return int(Path(f).read_text(encoding='utf-8').strip())
    except Exception:
        pass
    return 0


def compute_handoff_metrics(entries, P=None, DATA_DIR=None):
    """Compute turn/char/token metrics from relay entries + persisted token_usage."""
    total_turns = sum(1 for e in entries if e.get("role") == "assistant")
    total_chars = sum(e.get("chars", 0) for e in entries)
    turn_pct    = min(round(total_turns / TURN_THRESHOLD * 100), 999)
    char_pct    = min(round(total_chars / CHAR_THRESHOLD * 100), 999)
    context_tokens = read_token_usage(P, DATA_DIR)
    context_window = read_eff_window(P, DATA_DIR)
    token_pct = min(round(context_tokens / context_window * 100), 999) if context_tokens > 0 else 0
    return {
        "total_turns":    total_turns,
        "total_chars":    total_chars,
        "turn_pct":       turn_pct,
        "char_pct":       char_pct,
        "context_tokens": context_tokens,
        "token_pct":      token_pct,
    }


def build_handoff(DATA_DIR, metrics, entries, last_prompt=""):
    """Assemble the handoff.json dict (unified message format)."""
    recent = [{"role": e["role"], "text": e.get("text", "")[:80]} for e in entries[-6:]]
    pct = metrics.get("token_pct", 0)
    total_turns = metrics.get("total_turns", 0)
    lp = (last_prompt or "")[:30]
    if pct >= WARN:
        msg = f"Context {pct}% reached — new session recommended. (last: {lp}...)"
    elif lp:
        msg = f"{total_turns} turns in progress ({pct}%, last: {lp}...)"
    else:
        msg = f"{total_turns} turns in progress ({pct}%)"
    return {
        "metrics": metrics,
        "relationship": {"mood": "focused", "recent_jokes": []},
        "work": {
            "project": DATA_DIR.name,
            "status":  f"{metrics['total_turns']} turns / {metrics['total_chars']:,} chars",
            "decided": [],
            "pending": [],
        },
        "recent_turns": recent,
        "handoff_message": msg,
    }
