#!/usr/bin/env python3
"""Junior Mark installer"""
import json
import shutil
from pathlib import Path

INSTALLER_DIR = Path(__file__).parent
BASE_DIR = INSTALLER_DIR.parent
CLAUDE_DIR = Path.home() / '.claude'
TARGET_DIR = CLAUDE_DIR / 'plugins' / 'junior_mark'

CLAUDE_MD_LINES = [
    '@~/.claude/plugins/junior_mark/jm_rules.md',
]

def ok(msg):   print(f"  [ok] {msg}")
def info(msg): print(f"  [--] {msg}")
def err(msg):  print(f"  [!!] {msg}"); raise SystemExit(1)


def install():
    print("Installing Junior Mark...\n")

    # 1. create directories
    (TARGET_DIR / 'scripts').mkdir(parents=True, exist_ok=True)
    (TARGET_DIR / 'debug').mkdir(parents=True, exist_ok=True)
    (CLAUDE_DIR / 'commands').mkdir(parents=True, exist_ok=True)
    ok("directories created")

    # 2. copy scripts
    src = BASE_DIR / 'scripts'
    dst = TARGET_DIR / 'scripts'
    count = 0
    for f in src.glob('*.py'):
        shutil.copy2(f, dst / f.name)
        count += 1
    ok(f"scripts/ copied ({count} files)")

    # 3. copy root files (jm_rules.md, README.md, LICENSE)
    for fname in ('jm_rules.md', 'README.md', 'LICENSE'):
        src_file = BASE_DIR / fname
        if src_file.exists():
            shutil.copy2(src_file, TARGET_DIR / fname)
    ok("jm_rules.md, README.md, LICENSE copied")

    # 4. copy commands/
    src_cmds = INSTALLER_DIR / 'commands'
    count = 0
    for f in src_cmds.glob('*.md'):
        shutil.copy2(f, CLAUDE_DIR / 'commands' / f.name)
        count += 1
    ok(f"commands/ copied ({count} files)")

    # 5. merge hooks into settings.json
    settings_path = CLAUDE_DIR / 'settings.json'
    if settings_path.exists():
        shutil.copy2(settings_path, str(settings_path) + '.bak')
        settings = json.loads(settings_path.read_text(encoding='utf-8'))
    else:
        settings = {}

    hooks_file = INSTALLER_DIR / 'adding to settings.json'
    if not hooks_file.exists():
        err("installer/adding to settings.json not found")
    new_hooks = json.loads('{' + hooks_file.read_text(encoding='utf-8') + '}')['hooks']

    if 'hooks' not in settings:
        settings['hooks'] = {}
    for event, new_entries in new_hooks.items():
        existing = settings['hooks'].get(event, [])
        kept = [e for e in existing if not any('junior_mark' in h.get('command', '') for h in e.get('hooks', []))]
        settings['hooks'][event] = kept + new_entries
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    ok("settings.json hooks merged")

    # 6. add @include lines to CLAUDE.md (idempotent)
    claude_md = CLAUDE_DIR / 'CLAUDE.md'
    if claude_md.exists():
        shutil.copy2(claude_md, str(claude_md) + '.bak')
    content = claude_md.read_text(encoding='utf-8-sig') if claude_md.exists() else ''
    existing = {l.strip() for l in content.splitlines()}
    missing = [l for l in CLAUDE_MD_LINES if l.strip() not in existing]
    if missing:
        with claude_md.open('a', encoding='utf-8') as f:
            f.write('\n' + '\n'.join(missing) + '\n')
        ok("CLAUDE.md @include added")
    else:
        info("CLAUDE.md @include already present (skipped)")

    print("\nDone! Restart CC to activate the foreman.")


if __name__ == '__main__':
    install()
