#!/usr/bin/env python3
"""foreman.py — background daemon. monitor relay.jsonl + write handoff/context_warn"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# [1] load bootstrap (paths / constants / stream init)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, JM_BASE, CONTEXT_TOKENS_FALLBACK, CONTEXT_WINDOW_OVERHEAD, WARN, THRESHOLD, TURN_THRESHOLD, CHAR_THRESHOLD, register_session, lookup_session
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


# [2] settings and threshold definitions (TURN/CHAR_THRESHOLD are shared bootstrap constants)
CHECK_INTERVAL      = 5
INACTIVITY_TIMEOUT  = 5 * 60    # auto-exit after this many seconds of inactivity

# background daemon — follow JM_DATA_DIR env var or current_data_dir.txt from paths.py. no CLI args needed.
DATA_DIR = get_data_dir()
# JM_DATA_DIR env var takes priority automatically; use P["handoff"] throughout instead of HANDOFF_FILE
P = get_jm_paths(DATA_DIR)


def is_cc_alive(pid):
    """Check if CC process is alive via Windows API. Returns True (conservative) if check fails."""
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle: return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    except Exception:
        return True


def log(msg):
    try:
        with open(P["log"], "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def atomic_write(file_path, content):
    try:
        # write to .tmp first, then replace (atomic write)
        temp_file = file_path.with_suffix('.tmp')
        temp_file.write_text(content, encoding='utf-8')
        # overwrite by rename (safe on Windows with os.replace)
        os.replace(str(temp_file), str(file_path))
    except Exception as e:
        log(f"handoff write error: {e}")


def read_relay():
    if not P["relay"].exists(): return []
    entries = []
    try:
        for line in P["relay"].read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except: pass
    except: pass
    return entries


def read_token_usage():
    try:
        f = P.get("token_usage") or DATA_DIR / "token_usage.txt"
        if Path(f).exists():
            return int(Path(f).read_text(encoding='utf-8').strip())
    except Exception: pass
    return 0


def compute_metrics(entries):
    total_turns = sum(1 for e in entries if e.get("role") == "assistant")
    total_chars = sum(e.get("chars", 0) for e in entries)
    turn_pct    = min(round(total_turns / TURN_THRESHOLD * 100), 999)
    char_pct    = min(round(total_chars / CHAR_THRESHOLD * 100), 999)

    context_tokens = read_token_usage()
    try:
        # prefer the live window size statusline.py recorded from CC stdin (foreman has no direct access to it)
        live_file = P.get("ctx_window_live") or DATA_DIR / "ctx_window_live.txt"
        context_window = int(Path(live_file).read_text(encoding='utf-8').strip())
    except Exception:
        try:
            claude_json = json.loads((Path.home() / '.claude.json').read_text(encoding='utf-8'))
            context_window = int(claude_json.get('cachedGrowthBookFeatures', {}).get('tengu_hawthorn_window', CONTEXT_TOKENS_FALLBACK))
        except Exception:
            context_window = CONTEXT_TOKENS_FALLBACK
    context_window = max(context_window - CONTEXT_WINDOW_OVERHEAD, 1)
    token_pct = min(round(context_tokens / context_window * 100), 999) if context_tokens > 0 else 0

    return {
        "total_turns":    total_turns,
        "total_chars":    total_chars,
        "turn_pct":       turn_pct,
        "char_pct":       char_pct,
        "context_tokens": context_tokens,
        "token_pct":      token_pct,
    }


def write_handoff(entries, metrics):
    recent = [{"role": e["role"], "text": e.get("text", "")[:80]} for e in entries[-6:]]
    last_prompt = ""
    try:
        if P["last_prompt"].exists():
            last_prompt = P["last_prompt"].read_text(encoding="utf-8").strip()[:200]
    except: pass

    pct = metrics.get("token_pct", 0)
    handoff = {
        "metrics": metrics,
        "relationship": {"mood": "focused", "recent_jokes": []},
        "work": {
            "project": DATA_DIR.name,
            "status":  f"{metrics['total_turns']} turns / {metrics['total_chars']:,} chars",
            "decided": [],
            "pending": [],
        },
        "recent_turns": recent,
        "handoff_message": (
            f"Context {pct}% reached — new session recommended. (last: {last_prompt[:30]}...)"
            if pct >= WARN else
            (f"{metrics['total_turns']} turns in progress ({pct}%, last: {last_prompt[:30]}...)"
             if last_prompt else f"{metrics['total_turns']} turns in progress ({pct}%)")
        ),
    }
    atomic_write(P["handoff"], json.dumps(handoff, ensure_ascii=False, indent=2))


def write_context_warn(metrics):
    pct = metrics.get("token_pct", 0)
    tokens = metrics.get("context_tokens", 0)
    msg = f"Context {pct}% reached ({tokens:,} tokens) — consider starting a new session."
    try:
        P["context_warn"].write_text(msg, encoding="utf-8")
    except Exception as e:
        log(f"context_warn.flag write error: {e}")


def write_context_threshold(metrics):
    pct = metrics.get("token_pct", 0)
    tokens = metrics.get("context_tokens", 0)
    msg = f"Context {pct}% exceeded ({tokens:,} tokens) — run move~ (do NOT /compact, it will fail at this level)"
    try:
        P["context_threshold"].write_text(msg, encoding="utf-8")
    except Exception as e:
        log(f"context_threshold.flag write error: {e}")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    P["pid"].write_text(str(os.getpid()), encoding="utf-8")

    # record script hash (used by session_start for staleness check)
    def _file_hash(p):
        try: return hashlib.md5(p.read_bytes()).hexdigest()
        except: return ''
    current_hash = _file_hash(Path(__file__))
    P["hash"].write_text(current_hash, encoding="utf-8")

    # CC process PID file path (written by session_start.py, re-read each loop)
    cc_pid_file = Path(P.get("cc_pid") or DATA_DIR / "cc_pid.txt")

    def read_cc_pid():
        try:
            if cc_pid_file.exists():
                val = cc_pid_file.read_text(encoding='utf-8').strip()
                if val.isdigit():
                    return int(val)
        except Exception:
            pass
        return None

    cc_pid = read_cc_pid()
    if cc_pid:
        log(f"foreman started (PID={os.getpid()}, CC_PID={cc_pid} watch mode)")
    else:
        log(f"foreman started (PID={os.getpid()}, inactivity fallback mode, INACTIVITY={INACTIVITY_TIMEOUT}s)")

    while True:
        try:
            # re-read cc_pid.txt each loop — detect PID change or new entry
            new_cc_pid = read_cc_pid()
            if new_cc_pid != cc_pid:
                if new_cc_pid:
                    log(f"CC_PID updated: {cc_pid} → {new_cc_pid} (switching to watch mode)")
                else:
                    log(f"CC_PID gone: {cc_pid} → None (switching to fallback mode)")
                cc_pid = new_cc_pid

            # monitor CC process — if PID is set, check liveness first
            if cc_pid is not None:
                if not is_cc_alive(cc_pid):
                    log(f"CC process (PID={cc_pid}) exit detected — shutting down")
                    try:
                        P["foreman_exit"].write_text("foreman stopped — CC process exit detected.", encoding="utf-8")
                    except: pass
                    break
            else:
                # fallback: inactivity timeout (used when CC PID detection fails)
                last_activity = 0.0
                for f in (P["relay"], P["last_prompt"]):
                    try:
                        last_activity = max(last_activity, f.stat().st_mtime)
                    except FileNotFoundError:
                        pass
                if last_activity > 0:
                    idle = time.time() - last_activity
                    if idle >= INACTIVITY_TIMEOUT:
                        log(f"idle {idle:.0f}s elapsed — auto-exit (fallback)")
                        try:
                            P["foreman_exit"].write_text("foreman stopped — auto-exit after inactivity timeout.", encoding="utf-8")
                        except: pass
                        break

            # clean up guest CC PIDs — auto-remove terminated guest processes
            guest_file = P.get("guest_session_id", DATA_DIR / "guest_session_id.txt")
            if guest_file.exists():
                try:
                    lines = [l.strip() for l in guest_file.read_text(encoding='utf-8').splitlines() if l.strip()]
                    surviving = []
                    removed = []
                    for line in lines:
                        parts = line.split(':')
                        if len(parts) >= 2 and parts[1].isdigit():
                            guest_cc_pid = int(parts[1])
                            if is_cc_alive(guest_cc_pid):
                                surviving.append(line)
                            else:
                                removed.append(line)
                        else:
                            surviving.append(line)
                    if removed:
                        if surviving:
                            guest_file.write_text('\n'.join(surviving) + '\n', encoding='utf-8')
                        else:
                            guest_file.unlink(missing_ok=True)
                        for r in removed:
                            log(f"guest CC exit detected — removing from guest_session_id: {r}")
                except Exception as e:
                    log(f"guest CC PID cleanup error: {e}")

            entries = read_relay()
            if entries:
                metrics = compute_metrics(entries)

                # relay_writer updates handoff every turn, so foreman only manages warning flags
                # (also always updates as backup in case relay_writer doesn't run)
                write_handoff(entries, metrics)

                # CWD pollution detection → update session_map (first safety layer)
                try:
                    latest = next((e for e in reversed(entries) if e.get('cwd')), None)
                    latest_cwd = latest.get('cwd', '') if latest else ''
                    latest_sid = latest.get('session_id', '') if latest else ''
                    cwd_restore_file = P.get("cwd_restore", DATA_DIR / "cwd_restore.flag")
                    cwd_restored_file = P.get("cwd_restored", DATA_DIR / "cwd_restored.flag")
                    if latest_cwd and latest_sid:
                        cwd_str = str(latest_cwd).replace('\\', '/')
                        cwd_slug = re.sub(r'^([A-Za-z]):', r'\1', cwd_str).replace('/', '--').lstrip('-')
                        correct_drive = DATA_DIR.name[0]
                        correct_rest = DATA_DIR.name[1:].replace('--', '\\')
                        correct_path = f"{correct_drive}:{correct_rest}"
                        if cwd_slug != DATA_DIR.name:
                            current_mapping = lookup_session(latest_sid)
                            if current_mapping != DATA_DIR:
                                register_session(latest_sid, DATA_DIR)
                                log(f"CWD pollution detected — session_map updated: {cwd_slug} → {DATA_DIR.name}")
                            # create restore request flag (signal_checker → passes to Claude)
                            cwd_restore_file.write_text(correct_path, encoding='utf-8')
                        else:
                            # CWD normal — check if recovery is complete
                            if cwd_restore_file.exists():
                                cwd_restore_file.unlink(missing_ok=True)
                                cwd_restored_file.write_text(correct_path, encoding='utf-8')
                                log("CWD recovery confirmed — cwd_restored.flag created")
                except Exception as e:
                    log(f"CWD pollution detection error: {e}")

                # issue warning flags on threshold breach (updated every check cycle)
                # suppress for first 3 turns — token_pct inherits from previous session right after move~
                # preventing false warning on first response
                pct = metrics.get("token_pct", 0)

                if metrics.get("total_turns", 0) >= 3:
                    if pct >= THRESHOLD:
                        write_context_threshold(metrics)
                        log(f"threshold exceeded: {pct}%")
                    elif pct >= WARN:
                        write_context_warn(metrics)
                        log(f"warn issued: {pct}%")

        except Exception as e: log(f"loop error: {e}")
        time.sleep(CHECK_INTERVAL)

    # ── cleanup after loop exit ──
    log(f"foreman exited (PID={os.getpid()}, auto-exit)")
    session_id_file = P.get("session_id", DATA_DIR / "current_session_id.txt")
    reset_flag_file = P.get("reset_flag", DATA_DIR / "foreman_reset.flag")

    try:
        if session_id_file.exists():
            session_id_file.unlink()
            log("cleanup: current_session_id.txt deleted")
    except Exception as e:
        log(f"cleanup error (session_id): {e}")

    try:
        reset_flag_file.write_text("forced", encoding="utf-8")
        log("cleanup: foreman_reset.flag created (forced — CC force-closed)")
    except Exception as e:
        log(f"cleanup error (reset_flag): {e}")

    try:
        P["pid"].unlink(missing_ok=True)
        log("cleanup: foreman.pid deleted")
    except Exception as e:
        log(f"cleanup error (pid): {e}")

    try:
        relay_file = P.get("relay", DATA_DIR / "relay.jsonl")
        if relay_file.exists():
            relay_file.unlink()
            log("cleanup: relay.jsonl deleted")
    except Exception as e:
        log(f"cleanup error (relay): {e}")

    # stale cc_pid.txt can cause PID reuse to map another session to this DATA_DIR by mistake
    try:
        cc_pid_cleanup = P.get("cc_pid", DATA_DIR / "cc_pid.txt")
        if cc_pid_cleanup.exists():
            cc_pid_cleanup.unlink()
            log("cleanup: cc_pid.txt deleted")
    except Exception as e:
        log(f"cleanup error (cc_pid): {e}")


if __name__ == "__main__":
    main()
