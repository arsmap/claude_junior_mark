#!/usr/bin/env python3
"""Stop hook — log assistant response to relay + update handoff.json"""

import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# [1] load bootstrap (paths / constants / stream init)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, JM_BASE, CONTEXT_TOKENS_FALLBACK, WARN, THRESHOLD, TURN_THRESHOLD, CHAR_THRESHOLD
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


# [3] debug config
#DEBUG_FILE = Path.home() / '.claude' / 'junior_mark' / 'relay_writer_debug.txt'
DEBUG_FILE = JM_BASE / "debug" / "relay_writer_debug.txt"

def dbg(msg):
    try:
        DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# [5] atomic write (prevent data loss)
def atomic_write(file_path, content):
    try:
        # write to .tmp first, then replace (atomic write)
        temp_file = file_path.with_suffix('.tmp')
        temp_file.write_text(content, encoding='utf-8')
        # overwrite by rename (safe on Windows with os.replace)
        os.replace(str(temp_file), str(file_path))
    except Exception as e:
        dbg(f"atomic_write error ({file_path.name}): {e}")


def extract_text(data):
    # new format: last_assistant_message (string)
    lam = data.get("last_assistant_message")
    if lam and isinstance(lam, str):
        return lam
    # legacy format: message.content[].text
    msg = data.get("message", {})
    if not isinstance(msg, dict):
        return ""
    text = ""
    for block in msg.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")
    return text


# [6] relay file reader
def read_relay(relay_file):
    if not relay_file.exists():
        return []
    entries = []
    try:
        for line in relay_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except: pass
    except: pass
    return entries


# [7] update handoff and metrics (takes path map P as argument)
def update_handoff(DATA_DIR, P, last_prompt_file):
    entries = read_relay(P["relay"])
    total_turns = sum(1 for e in entries if e.get("role") == "assistant")
    total_chars = sum(e.get("chars", 0) for e in entries)
    turn_pct    = min(round(total_turns / TURN_THRESHOLD * 100), 999)
    char_pct    = min(round(total_chars / CHAR_THRESHOLD * 100), 999)

    context_tokens = 0
    try:
        token_file = P.get("token_usage") or DATA_DIR / "token_usage.txt"
        if Path(token_file).exists():
            context_tokens = int(Path(token_file).read_text(encoding='utf-8').strip())
    except Exception: pass
    context_window = CONTEXT_TOKENS_FALLBACK
    try:
        claude_json = json.loads((Path.home() / '.claude.json').read_text(encoding='utf-8'))
        context_window = int(claude_json.get('cachedGrowthBookFeatures', {}).get('tengu_hawthorn_window', CONTEXT_TOKENS_FALLBACK))
    except Exception:
        pass
    token_pct = min(round(context_tokens / context_window * 100), 999) if context_tokens > 0 else 0

    pct = token_pct

    recent = [
        {"role": e["role"], "text": e.get("text", "")[:80]}
        for e in entries[-6:]
    ]

    last_prompt = ""
    try:
        if last_prompt_file.exists():
            last_prompt = last_prompt_file.read_text(encoding="utf-8").strip()[:30]
    except: pass

    handoff = {
        "metrics": {
            "total_turns":    total_turns,
            "total_chars":    total_chars,
            "turn_pct":       turn_pct,
            "char_pct":       char_pct,
            "context_tokens": context_tokens,
            "token_pct":      token_pct,
        },
        "relationship": {"mood": "focused", "recent_jokes": []},
        "work": {
            "project": DATA_DIR.name,
            "status":  f"{total_turns} turns / {total_chars:,} chars",
            "decided": [],
            "pending": [],
        },
        "recent_turns":    recent,
        "handoff_message": (
            f"Context {pct}% reached — consider starting a new session."
            if pct >= WARN else
                f"{total_turns} turns in progress ({pct}%)"
        ),
    }

    atomic_write(P["handoff"], json.dumps(handoff, ensure_ascii=False, indent=2))

    return total_turns


def main():
    raw = ""  # pre-initialize raw
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception as e:
        dbg(f"stdin parse error: {e} | raw[:100]={raw[:100]!r}")
        data = {}

    my_session_id = data.get('session_id', '')
    DATA_DIR = get_data_dir(hook_cwd=data.get('cwd'), ignore_cur_file=True, session_id=my_session_id)
    P = get_jm_paths(DATA_DIR)

    text = extract_text(data)
    dbg(f"slug={DATA_DIR.name} text_len={len(text)}")

    # stale session check — skip relay.jsonl write if session_id differs
    if my_session_id and P.get('session_id') and P['session_id'].exists():
        current_id = P['session_id'].read_text(encoding='utf-8').strip()
        if current_id and my_session_id != current_id:
            dbg(f"stale session detected — skipping relay write ({my_session_id[:8]})")
            return

    entry = {
        "role": "assistant",
        "session_id": my_session_id,
        "cwd": data.get('cwd', ''),
        "text": text[:200],
        "chars": len(text),
        "ts": datetime.now().isoformat()
    }

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # use P["relay"] to avoid NameError
        with open(P["relay"], "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # skip handoff update if reset_flag exists (prevents Stop hook from overwriting handoff right after foreman_off)
        if P.get("reset_flag") and P["reset_flag"].exists():
            dbg("reset_flag detected — skipping handoff update")
            return

        # update token_usage.txt immediately at Stop hook time
        # signal_checker (UserPromptSubmit) updates at next turn start → 2-turn delay on large jumps
        # updating at Stop hook reduces delay to 1 turn (foreman detects within 5-second poll)
        transcript_path = data.get('transcript_path')
        if transcript_path and os.path.exists(str(transcript_path)):
            try:
                last_usage = None
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
                if last_usage:
                    total_tokens = (last_usage.get('input_tokens', 0) +
                                    last_usage.get('cache_read_input_tokens', 0) +
                                    last_usage.get('cache_creation_input_tokens', 0))
                    P["token_usage"].write_text(str(total_tokens), encoding='utf-8')
                    dbg(f"Stop hook token_usage updated: {total_tokens:,}")
            except Exception as e:
                dbg(f"Stop hook token_usage update error: {e}")

        # update handoff and signal
        turns = update_handoff(DATA_DIR, P, P["last_prompt"])
        dbg(f"handoff update done: {turns} turns")

    except Exception as e:
        dbg(f"handoff update failed: {e}")
        return


if __name__ == "__main__":
    main()
