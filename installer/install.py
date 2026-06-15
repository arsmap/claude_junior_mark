#!/usr/bin/env python3
"""Junior Mark installer"""
import json
import re
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
    ok("directories created")

    # 2. copy scripts
    src = BASE_DIR / 'scripts'
    dst = TARGET_DIR / 'scripts'
    count = 0
    for f in src.glob('*.py'):
        shutil.copy2(f, dst / f.name)
        count += 1
    ok(f"scripts/ copied ({count} files)")

    # 3. copy root files (jm_rules.md, README.md, README_KO.md,LICENSE)
    for fname in ('jm_rules.md', 'README.md', 'README_KO.md', 'LICENSE'):
        src_file = BASE_DIR / fname
        if src_file.exists():
            shutil.copy2(src_file, TARGET_DIR / fname)
    ok("jm_rules.md, README.md, README_KO.md, LICENSE copied")

    # 4. merge hooks into settings.json
    settings_path = CLAUDE_DIR / 'settings.json'
    if settings_path.exists():
        shutil.copy2(settings_path, str(settings_path) + '.bak')
        text = settings_path.read_text(encoding='utf-8')
        text = re.sub(r',\s*([}\]])', r'\1', text)  # strip trailing commas
        settings = json.loads(text)
    else:
        settings = {}

    hooks_file = INSTALLER_DIR / 'adding to settings.json'
    if not hooks_file.exists():
        err("installer/adding to settings.json not found")
    adding = json.loads('{' + hooks_file.read_text(encoding='utf-8') + '}')

    # merge hooks
    if 'hooks' in adding:
        if 'hooks' not in settings:
            settings['hooks'] = {}
        for event, new_entries in adding['hooks'].items():
            existing = settings['hooks'].get(event, [])
            kept = [e for e in existing if not any('junior_mark' in h.get('command', '') for h in e.get('hooks', []))]
            settings['hooks'][event] = kept + new_entries

    # copy non-hooks top-level keys (e.g. statusLine)
    for key, value in adding.items():
        if key != 'hooks':
            settings[key] = value

    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    ok("settings.json merged (hooks + statusLine)")

    # 5. add @include lines to CLAUDE.md (idempotent)
    claude_md = CLAUDE_DIR / 'CLAUDE.md'
    if claude_md.exists():
        shutil.copy2(claude_md, str(claude_md) + '.bak')
    content = claude_md.read_text(encoding='utf-8-sig') if claude_md.exists() else ''
    def _norm(s):
        return re.sub(r'\\(.)', r'\1', s.strip())
    jm_norm = {_norm(l) for l in CLAUDE_MD_LINES}
    seen_jm = set()
    deduped = []
    for line in content.splitlines():
        if _norm(line) in jm_norm:
            if _norm(line) not in seen_jm:
                deduped.append(line)
                seen_jm.add(_norm(line))
        else:
            deduped.append(line)
    missing = [l for l in CLAUDE_MD_LINES if _norm(l) not in seen_jm]
    new_content = '\n'.join(deduped)
    if missing:
        new_content += '\n' + '\n'.join(missing) + '\n'
    claude_md.write_text(new_content, encoding='utf-8')
    if missing:
        ok("CLAUDE.md @include added")
    elif len(deduped) < len(content.splitlines()):
        ok("CLAUDE.md duplicate @include removed")
    else:
        info("CLAUDE.md @include already present (skipped)")

    print("\nDone! Restart CC to activate the foreman.")


if __name__ == '__main__':
    try:
        install()
    except SystemExit:
        pass
    input("\nPress Enter to exit...")
