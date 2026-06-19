#!/usr/bin/env python3
"""SessionStart hook -- launch foreman in background + load previous session handoff.json"""

import hashlib
import json
import os
import sys
import subprocess
import time
import datetime
from pathlib import Path

# [1] load bootstrap (paths / constants / stream init)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, JM_BASE, CONTEXT_TOKENS_FALLBACK, CONTEXT_WINDOW_OVERHEAD, TURN_THRESHOLD, register_session
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


SYSTEM_NAME    = os.environ.get('DODAM_SYSTEM_NAME', '')
NICKNAME       = os.environ.get('DODAM_NICKNAME', '') or SYSTEM_NAME


def read_token_pct_from_transcript(transcript_path_str):
    """Read token usage from the last entry in the transcript JSONL and return as %"""
    if not transcript_path_str:
        return 0
    try:
        p = Path(transcript_path_str)
        if not p.exists():
            return 0
        last_tokens = 0
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    # usage is nested inside message.usage, not at the top level (same parsing as signal_checker)
                    msg = entry.get('message', {})
                    usage = msg.get('usage', {}) if isinstance(msg, dict) else {}
                    if usage:
                        tokens = (usage.get('input_tokens', 0) +
                                  usage.get('cache_read_input_tokens', 0) +
                                  usage.get('cache_creation_input_tokens', 0))
                        if tokens > 0:
                            last_tokens = tokens
                except Exception:
                    continue
        try:
            # prefer the live window size statusline.py recorded from CC stdin (SessionStart has no direct access to it)
            live_file = P.get("ctx_window_live") or DATA_DIR / "ctx_window_live.txt"
            eff_window = max(int(Path(live_file).read_text(encoding='utf-8').strip()) - CONTEXT_WINDOW_OVERHEAD, 1)
        except Exception:
            try:
                cj = json.loads((Path.home() / '.claude.json').read_text(encoding='utf-8'))
                eff_window = max(int(cj.get('cachedGrowthBookFeatures', {}).get('tengu_hawthorn_window', CONTEXT_TOKENS_FALLBACK)) - CONTEXT_WINDOW_OVERHEAD, 1)
            except Exception:
                eff_window = CONTEXT_TOKENS_FALLBACK - CONTEXT_WINDOW_OVERHEAD
        return min(round(last_tokens / eff_window * 100), 999) if last_tokens else 0
    except Exception:
        return 0

SCRIPTS_DIR = Path(__file__).parent

# 
DETACHED = subprocess.DETACHED_PROCESS | 0x08000000  # CREATE_NO_WINDOW


def _file_hash(p):
    try:
        return hashlib.md5(p.read_bytes()).hexdigest()
    except Exception:
        return ''


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
            children_count = {}
            for _, (par, _) in pid_map.items():
                children_count[par] = children_count.get(par, 0) + 1
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


def is_foreman_stale():
    try:
        # hash file lives in the data folder (P)
        if not P["hash"].exists(): return True
        saved = P["hash"].read_text().strip()

        # compute hash from the actual source file in SCRIPTS_DIR
        current = _file_hash(SCRIPTS_DIR / "foreman.py")
        return saved != current
    except Exception:
        return False        


def kill_foreman():
    try:
        pid = int(P["pid"].read_text().strip())
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    except:
        pass

        
def is_foreman_alive():
    if not P["pid"].exists(): return False
    try:
        pid = int(P["pid"].read_text().strip())
        # verify it's actually a python process, not just a matching PID
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                           capture_output=True, text=True, check=False)
        return str(pid) in r.stdout and "python" in r.stdout.lower()
    except: return False


def is_pid_alive(pid):
    """Check if an arbitrary PID is alive via Windows API. Returns True if uncertain (conservative)."""
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


def log_to_foreman(msg):
    try:
        with open(P["log"], "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass        

    
def load_handoff():
    if not P["handoff"].exists(): return None
    try:
        data = json.loads(P["handoff"].read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, Exception): # guard against corrupted JSON
        return None    


def ensure_foreman():
    if is_foreman_alive(): return "✓"
    
    script_path = Path(__file__).parent / "foreman.py"
    try:
        # ensure log directory exists
        P["log"].parent.mkdir(parents=True, exist_ok=True)

        # launch detached background process
        env = os.environ.copy()
        env['JM_DATA_DIR'] = str(DATA_DIR)
        subprocess.Popen(
            [sys.executable, str(script_path)],
            env=env,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True
        )
        return "▶"
    except Exception: return "✗"
    
    
def main():    
    # 1. declare globals and load input data
    global DATA_DIR, P
    raw = ""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    # 2. initialize path system
    # read session_id first to prioritize session_map lookup — prevents hook CWD pollution
    session_id = data.get('session_id', '')
    DATA_DIR = get_data_dir(hook_cwd=data.get('cwd'), session_id=session_id)

    # validate DATA_DIR by scanning cc_pid.txt — fallback when session_map is stale
    try:
        cc_pid_val = find_cc_pid()
        if cc_pid_val:
            cc_pid_file = DATA_DIR / 'cc_pid.txt'
            stored_cc = cc_pid_file.read_text(encoding='utf-8').strip() if cc_pid_file.exists() else ''
            if stored_cc != str(cc_pid_val):
                data_root = JM_BASE / 'data'
                for slug_dir in data_root.iterdir():
                    if not slug_dir.is_dir() or slug_dir == DATA_DIR:
                        continue
                    candidate = slug_dir / 'cc_pid.txt'
                    if candidate.exists():
                        try:
                            if candidate.read_text(encoding='utf-8').strip() == str(cc_pid_val):
                                DATA_DIR = slug_dir
                                break
                        except Exception:
                            continue
    except Exception:
        pass

    P = get_jm_paths(DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 3. detect auto-compact re-run — check before any state files are written
    # Case 1: valid session auto-compact (session_id == stored → same session restarted)
    # → exit silently without doing anything
    if session_id and P['session_id'].exists():
        try:
            stored_id = P['session_id'].read_text(encoding='utf-8').strip()
            if stored_id and session_id == stored_id:
                for f_key in ["context_warn", "context_threshold", "token_usage"]:
                    try:
                        if f_key in P: P[f_key].unlink(missing_ok=True)
                    except Exception:
                        pass
                try:
                    P["post_compact"].touch()
                except Exception:
                    pass
                # same session restart (=/compact auto-compact): skip handoff/relay reset
                # but guarantee foreman is alive — if foreman died or went stale at compact time
                # and we don't restart it, foreman stays absent for the rest of the session
                try:
                    if is_foreman_alive():
                        if is_foreman_stale():
                            kill_foreman()
                            try: P["pid"].unlink(missing_ok=True)
                            except Exception: pass
                            ensure_foreman()
                    else:
                        ensure_foreman()
                except Exception:
                    pass
                sys.exit(0)  # Case 1: valid session auto-compact (clear warning flags + ensure foreman)
        except Exception:
            pass

    # 3-2. early handoff.json zero — before any branch logic so StatusLine sees 0/30T immediately
    try:
        existing = {}
        if P["handoff"].exists():
            try:
                existing = json.loads(P["handoff"].read_text(encoding='utf-8'))
            except Exception:
                pass
        existing.setdefault('metrics', {})['total_turns'] = 0
        P["handoff"].write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    try:
        P["token_usage"].write_text("0", encoding='utf-8')
    except Exception:
        pass
    try:
        if P.get("force_retire_mute") and Path(P["force_retire_mute"]).exists():
            Path(P["force_retire_mute"]).unlink(missing_ok=True)
    except Exception:
        pass

    # 3-4. clear old session flag — always remove on new session start
    try:
#        old_flag = Path.home() / '.claude' / 'junior_mark' / 'old_session.flag'
        old_flag = JM_BASE / 'old_session.flag'
        old_flag.unlink(missing_ok=True)
    except Exception:
        pass

    # 3-5. session_id write deferred until main session confirmed (after guest check)

    # 3-6. measure token_pct at session start
    # (write token_usage.txt after branch logic — branches delete it, so write must come after)
    transcript_path = data.get('transcript_path', '')
    start_token_pct = read_token_pct_from_transcript(transcript_path)

    # 4. foreman state management
    retire_data_file = P.get("retire_data", DATA_DIR / "retire_data.json")
    reset_flag = P.get("reset_flag", DATA_DIR / "foreman_reset.flag")
    handoff_prev = P.get("handoff_prev", DATA_DIR / "handoff_prev.json")

    # [ownership check] independent of foreman state — decide GUEST/main based on retire status
    is_guest = False
    if session_id and P['session_id'].exists():
        try:
            stored_id = P['session_id'].read_text(encoding='utf-8').strip()
            if stored_id and stored_id != session_id:
                if not retire_data_file.exists():
                    is_guest = True
                else:
                    # retire_data exists → attempt main session claim.
                    # O_CREAT|O_EXCL is atomic on NTFS — only first session succeeds,
                    # subsequent sessions get OSError → treated as guest.
                    claim_lock = DATA_DIR / "retire_claim.lock"
                    try:
                        fd = os.open(str(claim_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        os.close(fd)
                    except OSError:
                        is_guest = True
        except Exception:
            pass

    if is_guest:
        # [recovery check] promote to main if the previous active session's CC PID is already dead
        try:
            cc_pid_file = P.get("cc_pid", DATA_DIR / "cc_pid.txt")
            if cc_pid_file.exists():
                prev_cc_str = cc_pid_file.read_text(encoding='utf-8').strip()
                if prev_cc_str.isdigit():
                    prev_cc_pid = int(prev_cc_str)
                    if not is_pid_alive(prev_cc_pid):
                        log_to_foreman(f"guest→main promoted: previous CC PID={prev_cc_pid} confirmed dead")
                        try:
                            P['session_id'].unlink(missing_ok=True)
                            log_to_foreman("cleanup: removed current_session_id.txt (promoted)")
                        except Exception as e:
                            log_to_foreman(f"cleanup error (session_id): {e}")
                        try:
                            P['handoff'].unlink(missing_ok=True)
                            log_to_foreman("cleanup: removed handoff.json (promoted)")
                        except Exception as e:
                            log_to_foreman(f"cleanup error (handoff): {e}")
                        try:
                            P['handoff_prev'].unlink(missing_ok=True)
                            log_to_foreman("cleanup: removed handoff_prev.json (promoted → first session after force-close)")
                        except Exception as e:
                            log_to_foreman(f"cleanup error (handoff_prev): {e}")
                        try:
                            P['pre_retire_summary'].unlink(missing_ok=True)
                            log_to_foreman("cleanup: removed pre_retire_summary.json (promoted)")
                        except Exception as e:
                            log_to_foreman(f"cleanup error (pre_retire_summary): {e}")
                        is_guest = False
        except Exception as e:
            log_to_foreman(f"promotion check error: {e}")

    if is_guest:
        try:
            guest_file = P.get("guest_session_id", DATA_DIR / "guest_session_id.txt")
            existing_ids = set()
            if guest_file.exists():
                for line in guest_file.read_text(encoding='utf-8').splitlines():
                    existing_ids.add(line.split(':')[0].strip())
            if session_id not in existing_ids:
                cc_pid_val = find_cc_pid()
                entry = f"{session_id}:{cc_pid_val}" if cc_pid_val else session_id
                with open(guest_file, "a", encoding='utf-8') as gf:
                    gf.write(entry + "\n")
            pid_val = P["pid"].read_text(encoding='utf-8').strip() if P["pid"].exists() else "?"
            try:
                P.get("is_guest_flag", DATA_DIR / "is_guest.flag").write_text("1", encoding='utf-8')
            except Exception:
                pass
            additional_parts = ["IS_GUEST=true"]
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": " | ".join(additional_parts)
                },
                "systemMessage": f"\n[Junior Mark] 👤 GUEST session | Main session in progress (Foreman ID: {pid_val}) | not logged"
            }
            print(json.dumps(output, ensure_ascii=False))
            sys.stdout.flush()
        except Exception:
            pass
        return

    # 4-0. clear previous guest session flag
    try:
        P.get("is_guest_flag", DATA_DIR / "is_guest.flag").unlink(missing_ok=True)
    except Exception:
        pass
    # 4-1. save CC process PID — must be done before ensure_foreman() so foreman monitors the right PID
    try:
        cc_pid_val = find_cc_pid()
        cc_pid_file = P.get("cc_pid", DATA_DIR / "cc_pid.txt")
        if cc_pid_val:
            Path(cc_pid_file).write_text(str(cc_pid_val), encoding='utf-8')
        else:
            try: Path(cc_pid_file).unlink()
            except FileNotFoundError: pass
    except Exception:
        pass

    # read session_warn early — before branches delete it
    session_warn_content = ""
    try:
        if P["session_warn"].exists():
            session_warn_content = P["session_warn"].read_text(encoding="utf-8").strip()
    except: pass

    # [main session] check and manage foreman state
    alive = is_foreman_alive()
    stale = is_foreman_stale() if alive else False
    if alive and stale:
        kill_foreman()
        alive = False

    if alive:
        # [continuing session] kill previous foreman and restart
        try:
            if P["handoff"].exists():
                import shutil
                shutil.copy2(P["handoff"], handoff_prev)
        except Exception:
            pass

        if retire_data_file.exists():
            try:
                rd = json.loads(retire_data_file.read_text(encoding='utf-8'))
                if Path(handoff_prev).exists():
                    _hp = json.loads(Path(handoff_prev).read_text(encoding='utf-8'))
                    if rd.get('decided'):
                        _hp.setdefault('work', {})['decided'] = rd['decided']
                    if rd.get('latest_snapshot'):
                        _hp['latest_snapshot'] = rd['latest_snapshot']
                    Path(handoff_prev).write_text(json.dumps(_hp, ensure_ascii=False, indent=2), encoding='utf-8')
                retire_data_file.unlink()
            except:
                pass

        try: reset_flag.unlink()
        except FileNotFoundError: pass

        (DATA_DIR / "retire_claim.lock").unlink(missing_ok=True)
        for f_key in ["context_warn", "context_threshold", "foreman_exit", "relay", "last_prompt", "session_warn", "token_usage", "retire_flag"]:
            try:
                if f_key in P: P[f_key].unlink()
            except FileNotFoundError:
                pass

        foreman_status = "▶"
        kill_foreman()
        try: P["pid"].unlink(missing_ok=True)
        except: pass
        try:
            existing = {}
            if P["handoff"].exists():
                try:
                    existing = json.loads(P["handoff"].read_text(encoding='utf-8'))
                except Exception:
                    pass
            existing.setdefault('metrics', {})['total_turns'] = 0
            P["handoff"].write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        try:
            P["token_usage"].write_text("0", encoding='utf-8')
        except Exception:
            pass
        ensure_foreman()
        for _ in range(10):
            time.sleep(0.2)
            if is_foreman_alive(): break
        else:
            ensure_foreman()
            for _ in range(10):
                time.sleep(0.2)
                if is_foreman_alive(): break
        foreman_status = "✓" if is_foreman_alive() else "✗"

    else:
        # [new/restart] reset_flag / retire_data / crash branch
        if reset_flag.exists():
            files_to_purge = ["context_warn", "context_threshold", "foreman_exit", "relay", "pid", "last_prompt", "session_warn", "handoff", "handoff_prev", "token_usage", "guest_session_id", "retire_flag"]
            for f_key in files_to_purge:
                try:
                    if f_key in P: P[f_key].unlink()
                except FileNotFoundError: pass
            try: reset_flag.unlink()
            except: pass
            try: retire_data_file.unlink()
            except FileNotFoundError: pass

        elif retire_data_file.exists():
            try:
                rd = json.loads(retire_data_file.read_text(encoding='utf-8'))
                if P["handoff"].exists():
                    import shutil
                    shutil.copy2(P["handoff"], handoff_prev)
                if Path(handoff_prev).exists():
                    _hp = json.loads(Path(handoff_prev).read_text(encoding='utf-8'))
                    if rd.get('decided'):
                        _hp.setdefault('work', {})['decided'] = rd['decided']
                    if rd.get('latest_snapshot'):
                        _hp['latest_snapshot'] = rd['latest_snapshot']
                    Path(handoff_prev).write_text(json.dumps(_hp, ensure_ascii=False, indent=2), encoding='utf-8')
            except:
                pass
            try: P["relay"].unlink()
            except FileNotFoundError: pass
            try: retire_data_file.unlink()
            except FileNotFoundError: pass
            (DATA_DIR / "retire_claim.lock").unlink(missing_ok=True)
            for f_key in ["context_warn", "context_threshold", "foreman_exit", "last_prompt", "session_warn", "token_usage", "retire_flag"]:
                try:
                    if f_key in P: P[f_key].unlink()
                except FileNotFoundError: pass

        else:
            # foreman crash / timeout
            for f_key in ["context_warn", "context_threshold", "foreman_exit", "relay", "last_prompt", "session_warn", "token_usage", "retire_flag"]:
                try:
                    if f_key in P: P[f_key].unlink()
                except FileNotFoundError: pass
            (DATA_DIR / "retire_claim.lock").unlink(missing_ok=True)

        try:
            existing = {}
            if P["handoff"].exists():
                try:
                    existing = json.loads(P["handoff"].read_text(encoding='utf-8'))
                except Exception:
                    pass
            existing.setdefault('metrics', {})['total_turns'] = 0
            P["handoff"].write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        try:
            P["token_usage"].write_text("0", encoding='utf-8')
        except Exception:
            pass
        try: P["pid"].unlink(missing_ok=True)
        except: pass
        foreman_status = "▶"
        ensure_foreman()
        for _ in range(10):
            time.sleep(0.2)
            if is_foreman_alive(): break
        else:
            ensure_foreman()
            for _ in range(10):
                time.sleep(0.2)
                if is_foreman_alive(): break
        foreman_status = "✓" if is_foreman_alive() else "✗"

    # 4-2. write session start token count — must come after branch cleanup (branches delete token_usage)
    try:
        # prefer the live window size statusline.py recorded from CC stdin (SessionStart has no direct access to it)
        live_file = P.get("ctx_window_live") or DATA_DIR / "ctx_window_live.txt"
        eff_window = max(int(Path(live_file).read_text(encoding='utf-8').strip()) - CONTEXT_WINDOW_OVERHEAD, 1)
    except Exception:
        try:
            cj = json.loads((Path.home() / '.claude.json').read_text(encoding='utf-8'))
            eff_window = max(int(cj.get('cachedGrowthBookFeatures', {}).get('tengu_hawthorn_window', CONTEXT_TOKENS_FALLBACK)) - CONTEXT_WINDOW_OVERHEAD, 1)
        except Exception:
            eff_window = CONTEXT_TOKENS_FALLBACK - CONTEXT_WINDOW_OVERHEAD
    if start_token_pct > 0:
        try:
            token_count = round(start_token_pct * eff_window / 100)
            P["token_usage"].write_text(str(token_count), encoding='utf-8')
        except Exception:
            pass

    # main session confirmed — write session_id + register in session map
    try:
        if session_id:
            P["session_id"].write_text(session_id, encoding='utf-8')
            register_session(session_id, DATA_DIR)
    except Exception:
        pass

    # 5-1. save session → foreman PID mapping (used to provide PID info when detecting stale sessions)
    if session_id:
        try:
            pid_val = P["pid"].read_text(encoding='utf-8').strip() if P["pid"].exists() else ""
            if pid_val:
                sf_file = P.get("session_foreman", DATA_DIR / "session_foreman.json")
                sf_data = {}
                if sf_file.exists():
                    try: sf_data = json.loads(sf_file.read_text(encoding='utf-8'))
                    except: pass
                sf_data[session_id] = int(pid_val)
                if len(sf_data) > 10:  # trim old entries
                    sf_data = dict(list(sf_data.items())[-10:])
                sf_file.write_text(json.dumps(sf_data, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    # 6. extract project name and build display message
    slug_parts = DATA_DIR.name.split('--')
    project_name = slug_parts[-1] if slug_parts[-1].lower() != 'administrator' else 'HOME'

    hp_data = None
    try:
        hp_path = Path(handoff_prev)
        if hp_path.exists():
            hp_data = json.loads(hp_path.read_text(encoding='utf-8'))
    except Exception:
        pass

    if hp_data:
        prev_m = hp_data.get('metrics', {})
        prev_work_d = hp_data.get('work', {})
        prev_decided = prev_work_d.get('decided', [])
        prev_pending = prev_work_d.get('pending', [])
        msg = (f"{project_name} turns({prev_m.get('turn_pct', 0)}%) "
               f"token({prev_m.get('token_pct', 0)}%) | "
               f"decided: {len(prev_decided)} | pending: {len(prev_pending)}")
    else:
        msg = f"{project_name} turns(0%) token({start_token_pct}%) | new session"

    # 7. final output — wait up to 1 second for new foreman to write its PID file
    pid_display = "?"
    try:
        for _ in range(5):
            if P["pid"].exists():
                v = P["pid"].read_text(encoding='utf-8').strip()
                if v:
                    pid_display = v
                    break
            time.sleep(0.2)
    except Exception:
        pass
    session_short = session_id.split('-')[0] if session_id else "?"

    is_new = hp_data is None

    line1 = f"[Junior Mark] foreman {foreman_status} | Foreman ID: {pid_display} | Session ID: {session_short}"
    line2 = f"[Junior Mark] {TURN_THRESHOLD} turns {eff_window:,} tokens | {msg}"

    tui_msg = f"\n{line1}\n{line2}"
    if session_warn_content:
        tui_msg += f"\n[Junior Mark] ℹ️ {session_warn_content}"

    additional_parts = ["IS_GUEST=false"]
    additional_parts.append("IS_NEW_SESSION=true" if is_new else "IS_NEW_SESSION=false")
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": " | ".join(additional_parts)
        },
        "systemMessage": tui_msg
    }
    print(json.dumps(output, ensure_ascii=False))
    sys.stdout.flush()

if __name__ == "__main__":
    main()
    
    