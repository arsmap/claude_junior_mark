#!/usr/bin/env python3
"""Junior Mark uninstaller"""
import json
import shutil
from pathlib import Path

CLAUDE_DIR = Path.home() / '.claude'
TARGET_DIR = CLAUDE_DIR / 'plugins' / 'junior_mark'

HOOK_KEYS = ['SessionStart', 'UserPromptSubmit', 'Stop', 'PreCompact']
CLAUDE_MD_LINES = [
    '@~/.claude/plugins/junior_mark/jm_rules.md',
]

def ok(msg):   print(f"  [ok] {msg}")
def info(msg): print(f"  [--] {msg}")


def uninstall():
    print("Uninstalling Junior Mark...\n")

    # 1. remove scripts/
    scripts_dir = TARGET_DIR / 'scripts'
    if scripts_dir.exists():
        shutil.rmtree(scripts_dir)
        ok("scripts/ removed")
    else:
        info("scripts/ not found (skipped)")

    # 2. remove debug/
    debug_dir = TARGET_DIR / 'debug'
    if debug_dir.exists():
        shutil.rmtree(debug_dir)
        ok("debug/ removed")
    else:
        info("debug/ not found (skipped)")

    # 3. remove jm_rules.md
    for name in ['jm_rules.md']:
        f = TARGET_DIR / name
        if f.exists():
            f.unlink()
            ok(f"{name} removed")
        else:
            info(f"{name} not found (skipped)")

    # 4. remove commands/
    cmd_dir = CLAUDE_DIR / 'commands'
    installer_cmds = ['foreman.md', 'token.md']
    removed_cmds = []
    for name in installer_cmds:
        f = cmd_dir / name
        if f.exists():
            f.unlink()
            removed_cmds.append(name)
    if removed_cmds:
        ok(f"commands/ removed ({', '.join(removed_cmds)})")
    else:
        info("no commands to remove (skipped)")

    # 5. remove hooks from settings.json
    settings_path = CLAUDE_DIR / 'settings.json'
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding='utf-8'))
        shutil.copy2(settings_path, str(settings_path) + '.bak')
        hooks = settings.get('hooks', {})
        removed = [k for k in HOOK_KEYS if k in hooks]
        for k in HOOK_KEYS:
            hooks.pop(k, None)
        if not hooks:
            settings.pop('hooks', None)
        settings_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        if removed:
            ok(f"settings.json hooks removed ({', '.join(removed)})")
        else:
            info("no hooks to remove in settings.json (skipped)")

    # 6. remove @include lines from CLAUDE.md
    claude_md = CLAUDE_DIR / 'CLAUDE.md'
    if claude_md.exists():
        lines = claude_md.read_text(encoding='utf-8').splitlines(keepends=True)
        filtered = [l for l in lines if l.rstrip('\n\r') not in CLAUDE_MD_LINES]
        if len(filtered) < len(lines):
            claude_md.write_text(''.join(filtered), encoding='utf-8')
            ok("CLAUDE.md @include lines removed")
        else:
            info("no @include lines to remove in CLAUDE.md (skipped)")

    print("\nDone! The data/ folder was kept. Remove it manually if needed:")
    print(f"  {TARGET_DIR / 'data'}")


if __name__ == '__main__':
    uninstall()
