#!/usr/bin/env python3
"""UserPromptSubmit hook — log user prompt + detect and forward context_warn.flag"""

import ctypes
import io
import json
import os
import re
import subprocess
import sys
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

# [1] load bootstrap (paths / constants / stream init)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bootstrap import get_data_dir, get_jm_paths, JM_BASE
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



def find_cc_pid():
    """Walk up the process tree and return the claude process PID. Returns None if not found."""
    try:
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
                last_orphan_pid = parent_pid
                break
            _, parent_name = parent_info
            if 'claude' in parent_name:
                return parent_pid
            pid = parent_pid
        # fallback 1: query parent not in snapshot directly via OpenProcess
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
        # fallback 2: scan entire snapshot for claude.exe
        claude_pids = [p for p, (_, nm) in pid_map.items() if 'claude' in nm]
        if len(claude_pids) == 1:
            return claude_pids[0]
        elif len(claude_pids) > 1:
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


RETIRE_KEYWORDS   = ["move~"]
START_KEYWORDS    = ["start~"]
ON_KEYWORDS       = ["on~"]
OFF_KEYWORDS      = ["off~"]
RESTART_KEYWORDS  = ["restart~"]
FAREWELL_KEYWORDS = ['goodbye', 'goodnight', 'seeyou', 'seeyalater', 'gottago',
                     'wrappingup', 'callingitaday', 'thatsitfortoday', 'alldone',
                     'donefortoday', 'signingoff', 'imout', 'talklaterdone', 'byebye']

#DEBUG_FILE    = Path.home() / '.claude' / 'junior_mark' / 'signal_checker_debug.txt'
DEBUG_FILE    = JM_BASE / "debug" / "signal_checker_debug.txt"

_HOME          = Path.home()
_CLAUDE_DIR    = _HOME / '.claude'


def dbg(msg):
    try:
        DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def foreman_start(DATA_DIR):
    """Start foreman.py as background process (CREATE_NO_WINDOW). Returns status string."""
    foreman_py = Path(__file__).parent / 'foreman.py'
    try:
        env = os.environ.copy()
        env['JM_DATA_DIR'] = str(DATA_DIR)
        proc = subprocess.Popen(
            [sys.executable, str(foreman_py)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000
        )
        dbg(f"foreman_start: pid={proc.pid}")
        return f"✅ foreman started (PID={proc.pid})"
    except Exception as e:
        return f"❌ foreman start failed: {e}"


def foreman_stop(DATA_DIR, P):
    """Kill foreman process only (no reset flag). Returns status string."""
    try:
        pid_file = P.get('pid', DATA_DIR / 'foreman.pid')
        if Path(pid_file).exists():
            fPid = Path(pid_file).read_text(encoding='utf-8').strip()
            if fPid:
                r = subprocess.run(["taskkill", "/F", "/PID", fPid], capture_output=True)
                if r.returncode == 0:
                    return f"✅ foreman PID {fPid} killed"
                return f"⚠️ foreman PID {fPid} kill failed"
        return "⚠️ no foreman.pid found"
    except Exception as e:
        return f"❌ error: {e}"


def farewell_matches(prompt):
    """Match farewell keywords — skip quoted strings and question-ending prompts (reduce false positives)"""
    text = prompt.strip()
    if text.endswith('?') or text.endswith('？'):
        return []
    # strip quoted content (unmatched/asymmetric quotes fall through to raw text)
    cleaned = re.sub(r"'[^']*'|\"[^\"]*\"", '', text).replace(' ', '').lower()
    return [k for k in FAREWELL_KEYWORDS if k in cleaned]


def main():
    raw = ""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception as e:
        dbg(f"stdin parse error: {e} | raw[:100]={raw[:100]!r}")
        data = {}

    # use cwd + session_id from hook JSON — session_id map takes priority (prevents CWD pollution)
    HOOK_CWD = data.get('cwd')
    my_session_id = data.get('session_id', '')
    DATA_DIR = get_data_dir(hook_cwd=HOOK_CWD, session_id=my_session_id)
    P = get_jm_paths(DATA_DIR)

    relay_file        = DATA_DIR / "relay.jsonl"
    last_prompt_file  = DATA_DIR / "last_prompt.txt"
    foreman_pid_file  = DATA_DIR / "foreman.pid"
    session_warn_file = DATA_DIR / "session_warn.txt"

    prompt = (
        data.get("prompt") or
        data.get("userPrompt") or
        data.get("user_prompt") or
        ""
    )
    dbg(f"slug={DATA_DIR.name} prompt_len={len(prompt)} keys={list(data.keys())}")

    # stale/guest session detection — handle first to avoid polluting token_usage.txt
    is_guest = False
    if my_session_id and P.get('session_id') and P['session_id'].exists():
        try:
            current_id = P['session_id'].read_text(encoding='utf-8').strip()
            if current_id and my_session_id != current_id:

                # handle guest-end~ first — works even without guest_session_id.txt
                _prompt_stripped_early = prompt.strip() if prompt else ""
                if _prompt_stripped_early == "guest-end~":
                    stored_cc_pid = None
                    try:
                        gf = P.get("guest_session_id", DATA_DIR / "guest_session_id.txt")
                        if gf.exists():
                            remaining = []
                            for line in gf.read_text(encoding='utf-8').splitlines():
                                if not line.strip():
                                    continue
                                parts = line.strip().split(':')
                                sid = parts[0]
                                if sid == my_session_id:
                                    if len(parts) > 1 and parts[1].isdigit():
                                        stored_cc_pid = int(parts[1])
                                else:
                                    remaining.append(line.strip())
                            if remaining:
                                gf.write_text('\n'.join(remaining) + '\n', encoding='utf-8')
                            else:
                                gf.unlink(missing_ok=True)
                        dbg(f"guest-end~ — removed from session_id, stored_cc_pid={stored_cc_pid} ({my_session_id[:8]})")
                    except Exception as e:
                        dbg(f"guest-end~ file cleanup error: {e}")
                    cc_pid = stored_cc_pid if stored_cc_pid else find_cc_pid()
                    dbg(f"guest-end~ — taskkill PID={cc_pid}")
                    if cc_pid:
                        subprocess.run(["taskkill", "/F", "/PID", str(cc_pid)], capture_output=True)
                    return

                # check if this is a guest session
                guest_file = P.get("guest_session_id", DATA_DIR / "guest_session_id.txt")
                try:
                    if guest_file.exists():
                        guest_ids = set(line.split(':')[0].strip()
                                        for line in guest_file.read_text(encoding='utf-8').splitlines()
                                        if line.strip())
                        is_guest = my_session_id in guest_ids
                except Exception:
                    pass

                if not is_guest:
                    pid_info = ""
                    try:
                        sf_file = P.get("session_foreman", DATA_DIR / "session_foreman.json")
                        if sf_file.exists():
                            sf_data = json.loads(sf_file.read_text(encoding='utf-8'))
                            my_pid = sf_data.get(my_session_id)
                            cur_pid = P["pid"].read_text(encoding='utf-8').strip() if P["pid"].exists() else "?"
                            if my_pid:
                                pid_info = f" (this session foreman PID {my_pid} → current PID {cur_pid})"
                    except Exception:
                        pass
                    dbg(f"stale session detected ({my_session_id[:8]}){pid_info}")
                    print(json.dumps({"decision": "block", "reason": f"[Junior Mark] ⚠️ This session is no longer valid{pid_info} — please open a new session."}, ensure_ascii=False))
                    sys.stdout.flush()
                    return
                else:
                    dbg(f"guest session detected — skipping relay ({my_session_id[:8]})")
                    # handle guest session commands
                    _GUEST_BLOCKED_EXACT = ["move~", "end~", "start~", "on~", "off~", "restart~"]
                    _prompt_stripped = prompt.strip() if prompt else ""

                    if _prompt_stripped in _GUEST_BLOCKED_EXACT:
                        print(json.dumps({"decision": "block", "reason": "This command is not available in a guest session."}, ensure_ascii=False))
                        sys.stdout.flush()
                        return
        except Exception as e:
            dbg(f"session_id check error: {e}")

    # read last assistant usage from transcript JSONL and record token count (skip for guest sessions)
    # skip on first turn (relay.jsonl empty) — previous session transcript data causes false reads
    _relay_empty_before = not relay_file.exists() or relay_file.stat().st_size == 0
    transcript_path = data.get('transcript_path')

    _post_compact = P.get("post_compact", DATA_DIR / "post_compact.flag")
    if Path(_post_compact).exists():
        try:
            Path(_post_compact).unlink(missing_ok=True)
            dbg("post_compact flag — skip token_usage write (stale pre-compact data)")
        except Exception:
            pass
    elif not is_guest and not _relay_empty_before and transcript_path and os.path.exists(str(transcript_path)):
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
                    except:
                        pass
            if last_usage:
                total_tokens = (last_usage.get('input_tokens', 0) +
                                last_usage.get('cache_read_input_tokens', 0) +
                                last_usage.get('cache_creation_input_tokens', 0))
                P["token_usage"].write_text(str(total_tokens), encoding='utf-8')
                dbg(f"token usage: {total_tokens:,} tokens")
        except Exception as e:
            dbg(f"token read error: {e}")

    # detect foreman_retire.flag — clear it so move~ can run again (allows re-retire after extra turns)
    retire_flag = P.get("retire_flag", DATA_DIR / "foreman_retire.flag")
    if prompt and not is_guest and prompt.strip() in RETIRE_KEYWORDS and Path(retire_flag).exists():
        try:
            Path(retire_flag).unlink(missing_ok=True)
            dbg("retire_flag cleared — allowing re-retire")
        except Exception as e:
            dbg(f"retire_flag clear error: {e}")

    # on~ / off~ / restart~ — pure foreman control (no session state change)
    if prompt and not is_guest:
        _ps = prompt.strip()
        _ctrl_msg = None
        if _ps in ON_KEYWORDS:
            already = False
            if P["pid"].exists():
                try:
                    fPid = P["pid"].read_text(encoding='utf-8').strip()
                    r = subprocess.run(["tasklist", "/FI", f"PID eq {fPid}", "/NH", "/FO", "CSV"], capture_output=True, check=False)
                    already = fPid in r.stdout.decode(errors='replace') and "python" in r.stdout.decode(errors='replace').lower()
                except Exception:
                    pass
            msg = "⚠️ foreman already running — use restart~ to restart" if already else foreman_start(DATA_DIR)
            dbg(f"on~ → {msg}")
            _ctrl_msg = f"on~ — {msg}"
        elif _ps in OFF_KEYWORDS:
            msg = foreman_stop(DATA_DIR, P)
            dbg(f"off~ → {msg}")
            _ctrl_msg = f"off~ — {msg}"
        elif _ps in RESTART_KEYWORDS:
            stop_msg = foreman_stop(DATA_DIR, P)
            start_msg = foreman_start(DATA_DIR)
            dbg(f"restart~ → {stop_msg} / {start_msg}")
            _ctrl_msg = f"restart~ — {stop_msg} → {start_msg}"
        if _ctrl_msg:
            print(json.dumps({
                "systemMessage": f"\n[Junior Mark] {_ctrl_msg}",
                "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "HOOK_FOREMAN_ON_DONE"}
            }, ensure_ascii=False))
            sys.stdout.flush()
            return

    skip_session_warn = False
    start_message = None

    if prompt and not is_guest:
        entry = {
            "role": "user",
            "session_id": data.get('session_id', ''),
            "text": str(prompt)[:200],
            "chars": len(str(prompt)),
            "cwd": HOOK_CWD or "",
            "ts": datetime.now().isoformat()
        }
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(relay_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            dbg("relay write ok")
        except Exception as e:
            dbg(f"relay write error: {e}")

        try:
            last_prompt_file.write_text(str(prompt), encoding="utf-8")
        except Exception as e:
            dbg(f"last_prompt write error: {e}")

        # move keyword detected → write session_warn only (retire handled by Claude on response)
        if prompt.strip() in RETIRE_KEYWORDS and not P["reset_flag"].exists():
            try:
                warn_msg = f"Session move requested at {datetime.now().strftime('%H:%M')}. Review previous context before continuing."
                session_warn_file.write_text(warn_msg, encoding='utf-8')
                dbg("session_warn written (move~ detected, retire handled by Claude)")
            except Exception as e:
                dbg(f"session_warn write error: {e}")
            skip_session_warn = True  # don't show session_warn in this request (reserved for next session)

    # start keyword detected → run foreman_on.py (claim session lock)
    if prompt and not is_guest and prompt.strip() in START_KEYWORDS:
        # un-retire: clear retire_flag + session_warn so move~ can be used again
        try:
            _retire_flag = P.get("retire_flag", DATA_DIR / "foreman_retire.flag")
            _session_warn = P.get("session_warn", DATA_DIR / "session_warn.txt")
            if Path(_retire_flag).exists():
                Path(_retire_flag).unlink(missing_ok=True)
                dbg("retire_flag cleared by start~")
            if Path(_session_warn).exists():
                Path(_session_warn).unlink(missing_ok=True)
                dbg("session_warn cleared by start~")
        except Exception as e:
            dbg(f"un-retire error: {e}")
        try:
            foreman_on_py = Path(__file__).parent / 'foreman_on.py'
            _cc_pid = find_cc_pid()
            result = subprocess.run(
                ["python", str(foreman_on_py), str(DATA_DIR),
                 data.get('session_id', ''), str(data.get('transcript_path', '') or ''),
                 str(_cc_pid) if _cc_pid else ''],
                capture_output=True, text=True, encoding='utf-8', timeout=10
            )
            output = result.stdout.strip()
            dbg(f"foreman_on.py: {output[:80]}")
            if "❌" in output:
                # claim failed — block prompt
                print(json.dumps({"decision": "block", "reason": f"[Junior Mark] {output}"}, ensure_ascii=False))
                sys.stdout.flush()
                return
            # claim succeeded — add to warnings (keep single systemMessage)
            start_message = output.replace("[foreman on] ", "")
        except Exception as e:
            dbg(f"foreman_on.py error: {e}")

    # block guest-only commands in main session
    if prompt and not is_guest and prompt.strip() == "guest-end~":
        print(json.dumps({
            "decision": "block",
            "reason": "[Junior Mark] ⚠️ 'guest-end~' is only available in guest sessions."
        }, ensure_ascii=False))
        sys.stdout.flush()
        return

    # guest farewell detection — handle before is_guest return
    if is_guest and prompt:
        if farewell_matches(prompt):
            print(json.dumps({"systemMessage": "[Junior Mark] 💾 farewell detected (guest session)."}, ensure_ascii=False))
            sys.stdout.flush()

    # collect warnings (priority: stale session > foreman dead > session_warn > reset_flag > signal)
    # merge into single systemMessage — multiple outputs cause TUI display issues
    if is_guest:
        return

    warnings = []
    farewell_detected = False
    force_retire_detected = False
    cwd_restore_path = None

    # farewell detection (only when no reset_flag/retire_flag — skip if session already ended/moved)
    _retire_flag_done = P.get("retire_flag", DATA_DIR / "foreman_retire.flag")
    if prompt and not P["reset_flag"].exists() and not Path(_retire_flag_done).exists():
        matched = farewell_matches(prompt)
        dbg(f"farewell check: matched={matched}")
        if matched:
            warnings.append("[Junior Mark] 💾 farewell detected.")
            farewell_detected = True
            dbg("farewell detected → added to warnings")

    # start keyword claim success message (show first)
    if start_message:
        warnings.append(f"[Junior Mark] ✅ {start_message}")

    # foreman exit detection (pid file exists but process is dead = crash/timeout)
    if P["pid"].exists():
        try:
            pid_str = foreman_pid_file.read_text(encoding="utf-8").strip()
            if pid_str:
                pid = int(pid_str)
                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                    capture_output=True, check=False
                )
                output = r.stdout.decode(errors='replace')
                is_alive = str(pid) in output and "python" in output.lower()
                if not is_alive and not P["context_warn"].exists():
                    warnings.append("[Junior Mark] ⚠️ foreman dead detected — type restart~ to restart, or open a new session.")
                    dbg("foreman dead detected")
        except Exception as e:
            dbg(f"foreman check error: {e}")

    # session_warn detection (skip if retire just processed or already retired — message is for next session)
    retire_data_file = P.get("retire_data", DATA_DIR / "retire_data.json")
    already_retired = retire_data_file.exists()
    if not skip_session_warn and not already_retired and P["session_warn"].exists():
        try:
            content = P["session_warn"].read_text(encoding="utf-8").strip()
            if content:
                warnings.append(f"[Junior Mark] ℹ️ {content}")
            P["session_warn"].unlink(missing_ok=True)
        except: pass

    # foreman_reset.flag detection — source: "forced"=CC force-closed, other=intentional end~
    if P["reset_flag"].exists():
        if prompt and prompt.strip() in ("end~", "move~"):
            print(json.dumps({
                "decision": "block",
                "reason": "[Junior Mark] ⚠️ Session already ended. Type start~ or restart~ to reactivate."
            }, ensure_ascii=False))
            sys.stdout.flush()
            return
        try:
            flag_content = P["reset_flag"].read_text(encoding="utf-8").strip()
        except Exception:
            flag_content = ""
        if flag_content == "forced":
            warnings.append("[Junior Mark] ⚠️ Session interrupted by terminal close. Type start~ or restart~ to continue.")
            dbg("foreman_reset.flag detected → re-entered after CC force-close")
        else:
            warnings.append("[Junior Mark] ⚠️ Session already ended. Type start~ or restart~ to continue.")
            dbg("foreman_reset.flag detected → input after intentional end~")

    # foreman_retire.flag detected → user still typing after move~ (guide to prevent duplicate move)
    if Path(retire_flag).exists() and not P["reset_flag"].exists():
        warnings.append("[Junior Mark] ⚠️ Session move requested in previous session. Open a new session to continue. (stay: /compact then start~ / stop: end~)")
        dbg("foreman_retire.flag detected → input after move~ completed")

    # CWD recovery complete (created by foreman after confirming correct CWD)
    cwd_restored_file = P.get("cwd_restored", DATA_DIR / "cwd_restored.flag")
    if Path(cwd_restored_file).exists():
        try:
            restored_path = Path(cwd_restored_file).read_text(encoding='utf-8').strip()
            Path(cwd_restored_file).unlink(missing_ok=True)
            warnings.insert(0, f"[Junior Mark] ✅ CWD pollution detected - recovery complete: {restored_path}")
            dbg(f"CWD recovery complete: {restored_path}")
        except Exception:
            pass

    # CWD restore request detected (created by foreman on pollution detection)
    cwd_restore_file = P.get("cwd_restore", DATA_DIR / "cwd_restore.flag")
    if Path(cwd_restore_file).exists():
        try:
            cwd_restore_path = Path(cwd_restore_file).read_text(encoding='utf-8').strip()
            contaminated_path = HOOK_CWD or cwd_restore_path
            warnings.append(f"[Junior Mark] ⚠️ CWD pollution detected — restore needed: {contaminated_path}")
            dbg(f"CWD restore request: correct={cwd_restore_path} contaminated={contaminated_path}")
        except Exception:
            pass

    # force_retire.flag detected (written by PostToolUse on context spike ≥ THRESHOLD mid-tool)
    force_retire_f = Path(P.get("force_retire", DATA_DIR / "force_retire.flag"))
    if force_retire_f.exists() and not already_retired and not P["reset_flag"].exists():
        try:
            msg = force_retire_f.read_text(encoding='utf-8').strip()
            force_retire_f.unlink(missing_ok=True)
            warnings.insert(0, f"[Junior Mark] 🚨 {msg}")
            force_retire_detected = True
            dbg(f"force_retire detected: {msg[:80]}")
        except Exception as e:
            dbg(f"force_retire read error: {e}")

    # context_threshold.flag detected (written by foreman when THRESHOLD exceeded)
    ctx_threshold = P.get("context_threshold", DATA_DIR / "context_threshold.flag")
    if Path(ctx_threshold).exists():
        try:
            msg = Path(ctx_threshold).read_text(encoding='utf-8').strip()
            if msg:
                warnings.append(f"[Junior Mark] 🚨 {msg}")
            Path(ctx_threshold).unlink(missing_ok=True)
        except: pass

    # context_warn.flag detected (written by foreman when WARN exceeded)
    ctx_warn = P.get("context_warn", DATA_DIR / "context_warn.flag")
    if Path(ctx_warn).exists():
        try:
            msg = Path(ctx_warn).read_text(encoding='utf-8').strip()
            if msg:
                warnings.append(f"[Junior Mark] ⚠️ {msg}")
            Path(ctx_warn).unlink(missing_ok=True)
        except: pass

    # foreman_exit.flag detected (written on foreman exit — shown once then deleted)
    foreman_exit = P.get("foreman_exit", DATA_DIR / "foreman_exit.flag")
    if Path(foreman_exit).exists():
        try:
            msg = Path(foreman_exit).read_text(encoding='utf-8').strip()
            warnings.append(f"[Junior Mark] ⚠️ {msg}")
            Path(foreman_exit).unlink(missing_ok=True)
        except: pass

    # single output: warnings only (status bar moved to statusLine footer)
    if warnings:
        message = "\n" + "\n".join(warnings)
        dbg(f"systemMessage output: {message!r}")
        out: dict[str, object] = {"systemMessage": message}
        additional_contexts = []
        if force_retire_detected:
            additional_contexts.insert(0, "🚨 force_retire detected — present move~/계속 진행 choices via AskUserQuestion")
            dbg("force_retire additionalContext added")
        if farewell_detected:
            additional_contexts.append("💾 farewell detected — must present choices via AskUserQuestion tool")
            dbg("farewell additionalContext added")
        if start_message:
            additional_contexts.append("HOOK_FOREMAN_ON_DONE")
            dbg("HOOK_FOREMAN_ON_DONE additionalContext added")
        if cwd_restore_path:
            additional_contexts.append(f"CWD_RESTORE={cwd_restore_path}")
            dbg(f"CWD_RESTORE additionalContext added: {cwd_restore_path}")
        if additional_contexts:
            out["hookSpecificOutput"] = {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": " | ".join(additional_contexts)
            }
        print(json.dumps(out, ensure_ascii=False))
        sys.stdout.flush()
    else:
        dbg("no warnings → systemMessage not output")

if __name__ == "__main__":
    main()
