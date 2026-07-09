#!/usr/bin/env python3
"""foreman.py — background daemon. monitor relay.jsonl + write handoff/context_warn"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# [1] load bootstrap (paths / constants / stream init)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, WARN, THRESHOLD, register_session, lookup_session, compute_handoff_metrics, build_handoff, cwd_to_slug, slug_to_path, read_lock_int, clean_lock_text
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


# [2] daemon settings
CHECK_INTERVAL      = 5
INACTIVITY_TIMEOUT  = 5 * 60    # auto-exit after this many seconds of inactivity

# background daemon — DATA_DIR comes from the JM_DATA_DIR env var set by the launcher
# (ensure_foreman / foreman_on / foreman_start). no CLI args needed.
DATA_DIR = get_data_dir()
P = get_jm_paths(DATA_DIR)


def is_cc_alive(pid, recorded_start=None):
    """Check the CC PID is alive AND still our CC — guards against PID reuse.
    Identity is anchored on the process CREATION TIME: immutable across a binary rename
    (CC auto-update renames the running exe to claude.exe.old.<ts>) and distinct for a
    reused PID. The image-name check is only a FALLBACK for when the creation time is
    unavailable (no recorded value / API failure); startswith('claude.exe') tolerates the
    .old rename, still excluding the Desktop WindowsApps bundle. Uses ctypes (not tasklist)
    because this runs every CHECK_INTERVAL. Returns True (conservative) if the check fails."""
    try:
        import ctypes
        from ctypes import wintypes, byref
        k32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle: return False
        try:
            code = ctypes.c_ulong()
            k32.GetExitCodeProcess(handle, ctypes.byref(code))
            if code.value != 259:  # STILL_ACTIVE
                return False
            # primary: creation-time identity (decisive only when both sides are known —
            # a reused PID gets a different creation time; a renamed binary keeps the same)
            if recorded_start is not None:
                class _FT(ctypes.Structure):
                    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]
                c, e, ke, us = _FT(), _FT(), _FT(), _FT()
                if k32.GetProcessTimes(handle, byref(c), byref(e), byref(ke), byref(us)):
                    return ((c.hi << 32) | c.lo) == recorded_start
                # GetProcessTimes failed → fall through to name fallback
            # fallback: image name (startswith 'claude.exe' tolerates the claude.exe.old.<ts>
            # rename; still excludes the Desktop WindowsApps bundle); install-location independent
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            k32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD,
                ctypes.c_wchar_p, ctypes.POINTER(wintypes.DWORD)
            ]
            k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                full = buf.value.lower().replace('\\', '/')
                return full.rsplit('/', 1)[-1].startswith('claude.exe') and 'windowsapps' not in full
            return True  # name query failed → liveness-only fallback (conservative)
        finally:
            k32.CloseHandle(handle)
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


def compute_metrics(entries):
    return compute_handoff_metrics(entries, P, DATA_DIR)


def write_handoff(entries, metrics):
    last_prompt = ""
    try:
        if P["last_prompt"].exists():
            last_prompt = P["last_prompt"].read_text(encoding="utf-8").strip()
    except: pass
    handoff = build_handoff(DATA_DIR, metrics, entries, last_prompt)
    atomic_write(P["handoff"], json.dumps(handoff, ensure_ascii=False, indent=2))


def write_context_warn(metrics):
    pct = metrics.get("token_pct", 0)
    tokens = metrics.get("context_tokens", 0)
    msg = f"Context {pct}% reached ({tokens:,} tokens) — prepare to run move~. Avoid /compact above 80%."
    try:
        P["context_warn"].write_text(msg, encoding="utf-8")
    except Exception as e:
        log(f"context_warn.flag write error: {e}")


def write_context_threshold(metrics):
    pct = metrics.get("token_pct", 0)
    tokens = metrics.get("context_tokens", 0)
    if pct >= 100:
        msg = f"Context {pct}% — move~ / end~ unavailable. /compact only."
    else:
        msg = f"Context {pct}% exceeded ({tokens:,} tokens) — run move~ now. /compact likely to fail at this level."
    try:
        P["context_threshold"].write_text(msg, encoding="utf-8")
    except Exception as e:
        log(f"context_threshold.flag write error: {e}")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write(P["pid"], str(os.getpid()))

    # record script hash (used by session_start for staleness check)
    def _file_hash(p):
        try: return hashlib.md5(p.read_bytes()).hexdigest()
        except: return ''
    current_hash = _file_hash(Path(__file__))
    P["hash"].write_text(current_hash, encoding="utf-8")

    # CC process PID file path (written by session_start.py, re-read each loop)
    cc_pid_file = Path(P.get("cc_pid") or DATA_DIR / "cc_pid.txt")

    cc_start_file = DATA_DIR / "cc_pid_start.txt"

    def read_cc_pid():
        """Return (pid, start_time) — start_time is the recorded process creation time
        (identity anchor, None if absent). cc_pid.txt keeps its plain-pid format; the
        creation time lives in the sibling cc_pid_start.txt (leaves cc_pid.txt readers
        untouched)."""
        pid = read_lock_int(cc_pid_file)
        if pid is not None:
            return pid, read_lock_int(cc_start_file)
        return None, None

    cc_pid, cc_start = read_cc_pid()
    if cc_pid:
        log(f"foreman started (PID={os.getpid()}, CC_PID={cc_pid} watch mode)")
    else:
        log(f"foreman started (PID={os.getpid()}, inactivity fallback mode, INACTIVITY={INACTIVITY_TIMEOUT}s)")

    while True:
        try:
            # re-read cc_pid.txt each loop — detect PID change or new entry
            new_cc_pid, new_cc_start = read_cc_pid()
            if new_cc_pid != cc_pid:
                if new_cc_pid:
                    log(f"CC_PID updated: {cc_pid} → {new_cc_pid} (switching to watch mode)")
                else:
                    log(f"CC_PID gone: {cc_pid} → None (switching to fallback mode)")
                cc_pid = new_cc_pid
            cc_start = new_cc_start  # keep the recorded creation time in sync each loop

            # monitor CC process — if PID is set, check liveness first
            if cc_pid is not None:
                if not is_cc_alive(cc_pid, cc_start):
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
                    lines = [clean_lock_text(l) for l in guest_file.read_text(encoding='utf-8', errors='replace').splitlines()]
                    lines = [l for l in lines if l]
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
                            atomic_write(guest_file, '\n'.join(surviving) + '\n')
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
                        cwd_slug = cwd_to_slug(latest_cwd)
                        correct_path = slug_to_path(DATA_DIR.name)
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

                # auto-clear mute flag when context drops below WARN (compact / new session / any reduction)
                # step01
                force_retire_mute_f = Path(P.get("force_retire_mute", DATA_DIR / "force_retire_mute.flag"))
                if force_retire_mute_f.exists() and pct < WARN:
                    try:
                        force_retire_mute_f.unlink(missing_ok=True)
                        log(f"force_retire_mute cleared — context dropped below WARN ({pct}%)")
                    except Exception as e:
                        log(f"force_retire_mute clear error: {e}")
                # step02
                context_warn_f = Path(P.get("context_warn", DATA_DIR / "context_warn.flag"))
                if context_warn_f.exists() and pct < WARN:
                    try:
                        context_warn_f.unlink(missing_ok=True)
                        log(f"context_warn cleared — context dropped below WARN ({pct}%)")
                    except Exception as e:
                        log(f"context_warn clear error: {e}")
                # step03
                context_threshold_f = Path(P.get("context_threshold", DATA_DIR / "context_threshold.flag"))
                if context_threshold_f.exists() and pct < WARN:
                    try:
                        context_threshold_f.unlink(missing_ok=True)
                        log(f"context_threshold cleared — context dropped below WARN ({pct}%)")
                    except Exception as e:
                        log(f"context_threshold clear error: {e}")
                # step04                        
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
        # the creation-time sidecar shares cc_pid.txt's lifecycle
        cc_start_cleanup = DATA_DIR / "cc_pid_start.txt"
        if cc_start_cleanup.exists():
            cc_start_cleanup.unlink()
            log("cleanup: cc_pid_start.txt deleted")
    except Exception as e:
        log(f"cleanup error (cc_pid): {e}")


if __name__ == "__main__":
    main()
