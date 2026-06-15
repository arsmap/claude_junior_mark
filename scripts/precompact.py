#!/usr/bin/env python3
"""PreCompact hook — clear stale flags and relay log before compaction"""

import io
import json
import os
import re
import sys
import time
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



def main():
    raw = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    # just before compaction — token count will drop after compact, so existing warning flags are stale → delete
    try:
        DATA_DIR = get_data_dir(hook_cwd=data.get('cwd'), ignore_cur_file=True, session_id=data.get('session_id', ''))
        P = get_jm_paths(DATA_DIR)
        for key in ("context_warn", "context_threshold"):
            f = P.get(key, DATA_DIR / f"{key}.flag")
            if Path(f).exists():
                Path(f).unlink()
        relay = P.get("relay", DATA_DIR / "relay.jsonl")
        if Path(relay).exists():
            Path(relay).unlink()
    except Exception:
        pass

            

if __name__ == "__main__":
    main()
