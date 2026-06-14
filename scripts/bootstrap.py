#!/usr/bin/env python3
"""junior_mark common initialization module.

Add to the top of each script:
    sys.path.insert(0, str(Path(__file__).parent))
    from bootstrap import get_data_dir, get_jm_paths, JM_BASE, CONTEXT_TOKENS_FALLBACK, WARN, THRESHOLD
"""
import inspect
import io
import sys
from datetime import datetime
from pathlib import Path

# ── system constants ─────────────────────────────────────────────
# context window fallback (used when live token limit is unavailable). measured baseline: 200K.
# effective CC limit ≈ 178K (200K minus ~22K overhead).
# prior bug (167K fallback) reproduced: WARN=87%×167K≈145K, THRESHOLD=97%×167K≈162K
# → converted to 200K basis: 145K/200K=72%, 162K/200K=81%
CONTEXT_TOKENS_FALLBACK = 200_000
TURN_THRESHOLD = 30
CHAR_THRESHOLD = 50_000
WARN      = 72   # 144K tokens → CC ~19% remaining
THRESHOLD = 81   # 162K tokens → CC  ~9% remaining

# ── track caller filename ───────────────────────────────────────
_stack = inspect.stack()
_caller_file = _stack[1].filename if len(_stack) > 1 else __file__

# ── load paths.py ────────────────────────────────────────────────
try:
    from paths import get_data_dir, get_jm_paths, JM_BASE, register_session, lookup_session
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
        "usage":             d / "transcript_usage.txt",
        "token_usage":       d / "token_usage.txt",
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
    }

# ── stream setup ─────────────────────────────────────────────────
sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding="utf-8")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
