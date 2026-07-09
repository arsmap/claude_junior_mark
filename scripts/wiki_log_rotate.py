#!/usr/bin/env python3
"""Wiki log.md auto-rotation.

The wiki log (wiki/log.md) is append-only and grows every ingest, so it slowly
becomes too big to read in one page. When it passes a byte threshold, move the
oldest entries (top of the chronological file) into log_archive.md and keep only
the most recent entries in log.md.

log_archive.md is itself bounded: when it grows past a larger (cold-storage) cap,
the whole archive is sealed into an immutable dated shard
(log_archive_<first>_<last>.md) and a fresh archive starts.

Safety rules:
- Cut only at '## ' entry boundaries (never mid-entry).
- Never move the last entry -- it is the session-start anchor (jm_rules Rule 3).
- Do nothing when under threshold; on any error leave both files untouched.

Trigger: called from session_start.py on a main (non-guest) session start.
Can also be run standalone for testing:  python wiki_log_rotate.py
"""
import re
from pathlib import Path

JM_BASE = Path.home() / '.claude' / 'plugins' / 'junior_mark'
WIKI_DIR = JM_BASE / 'wiki'
LOG = WIKI_DIR / 'log.md'
ARCHIVE = WIKI_DIR / 'log_archive.md'
BACKUP = WIKI_DIR / 'log.md.autorotate.bak'

# Keep log.md readable within the Read tool's single-page cap (25,000 tokens).
# Thresholds are expressed in tokens and converted to bytes via the empirical
# ratio measured on this log (175,335 bytes = 85,160 tokens, Korean-heavy content).
READ_PAGE_CAP_TOKENS = 25000   # Read tool single-page cap (harness default)
BYTES_PER_TOKEN = 2.06         # empirical for this log
TRIGGER_TOKENS = 24000         # rotate when log.md approaches the cap
KEEP_TOKENS = 16000            # trim back to ~16K tokens (headroom under the cap)
TRIGGER_BYTES = int(TRIGGER_TOKENS * BYTES_PER_TOKEN)   # ~49 KB
KEEP_BYTES = int(KEEP_TOKENS * BYTES_PER_TOKEN)         # ~32 KB

# log_archive.md is cold storage (never auto-loaded, read via grep/offset), so it
# gets a much larger cap. Past it, the whole archive is sealed into an immutable
# dated shard (log_archive_<first>_<last>.md) and a fresh archive starts.
SEAL_TOKENS = 100000                                   # ~206 KB per shard
SEAL_BYTES = int(SEAL_TOKENS * BYTES_PER_TOKEN)

# breadcrumb pointer kept in log.md's header so a reader knows the older entries
# live in log_archive.md (and up to which date). Refreshed on every rotation.
BREADCRUMB_PREFIX = "> 📦 "

ARCHIVE_HEADER = (
    "# log_archive — archive (not auto-loaded)\n\n"
    "Old ingest entries split out of log.md. Reference only (e.g. reclassification).\n"
    "The anchor reads only the last entry of log.md, so this file never affects runtime.\n"
    "\n---\n"
)


def _entry_date(header_line):
    m = re.search(r'\d{4}-\d{2}-\d{2}', header_line)
    return m.group(0) if m else '?'


def _header_with_breadcrumb(file_header_lines, archive_headers):
    """Return the log.md header with a fresh breadcrumb line pointing to the archive.

    Any previous breadcrumb line is replaced. The breadcrumb is placed just before
    the trailing '---' separator (or appended if there is none).
    """
    cutoff = _entry_date(archive_headers[-1]) if archive_headers else '?'
    crumb = (f"{BREADCRUMB_PREFIX}이 파일 이전의 인제스트 기록 "
             f"{len(archive_headers)}개(~{cutoff})는 log_archive.md 참조.")
    shards = sorted(WIKI_DIR.glob('log_archive_*.md'))
    if shards:
        crumb += f" 더 오래된 봉인본 {len(shards)}개(log_archive_*.md)."
    crumb += "\n"
    cleaned = [ln for ln in file_header_lines if not ln.startswith(BREADCRUMB_PREFIX)]
    out, inserted = [], False
    for ln in cleaned:
        if ln.strip() == '---' and not inserted:
            out.append(crumb)
            out.append('\n')
            inserted = True
        out.append(ln)
    if not inserted:
        out.append(crumb)
    return out


def _seal_archive_if_needed():
    """Seal the active archive into an immutable dated shard when it grows past
    SEAL_BYTES, so a fresh log_archive.md can start. Returns the shard name if
    sealed, else None. (The archive only grows during rotation, so this is checked
    there, before the new batch is appended.)
    """
    if not ARCHIVE.exists() or len(ARCHIVE.read_bytes()) <= SEAL_BYTES:
        return None
    hdrs = [ln for ln in ARCHIVE.read_text(encoding='utf-8').splitlines() if ln.startswith('## ')]
    if not hdrs:
        return None
    first, last = _entry_date(hdrs[0]), _entry_date(hdrs[-1])
    shard = WIKI_DIR / f"log_archive_{first}_{last}.md"
    n = 2
    while shard.exists():
        shard = WIKI_DIR / f"log_archive_{first}_{last}_{n}.md"
        n += 1
    ARCHIVE.rename(shard)
    return shard.name


def rotate_if_needed():
    """Rotate log.md if it exceeds TRIGGER_BYTES.

    Returns a short status string when it rotated, else None.
    """
    if not LOG.exists():
        return None

    text = LOG.read_text(encoding='utf-8')
    if len(text.encode('utf-8')) <= TRIGGER_BYTES:
        return None

    lines = text.splitlines(keepends=True)
    headers = [i for i, ln in enumerate(lines) if ln.startswith('## ')]
    if len(headers) < 2:
        return None  # no safe boundary to split on

    file_header = lines[:headers[0]]  # '# log ...' preamble before the first entry
    starts = headers
    ends = headers[1:] + [len(lines)]
    entries = list(zip(starts, ends))  # (start_line, end_line) per entry

    # walk entries from the bottom, keeping until cumulative bytes reach KEEP_BYTES,
    # but always keep at least the last entry (the anchor)
    keep_bytes = 0
    keep_from = 0
    for idx in range(len(entries) - 1, -1, -1):
        s, e = entries[idx]
        keep_bytes += len(''.join(lines[s:e]).encode('utf-8'))
        keep_from = idx
        if keep_bytes >= KEEP_BYTES and idx != len(entries) - 1:
            break

    if keep_from == 0:
        return None  # everything fits in the keep budget -> nothing to move

    move_lines = lines[entries[0][0]:entries[keep_from][0]]  # oldest entries

    # if the active archive is already too big, seal it into a dated shard first
    # so this batch lands in a fresh archive
    _seal_archive_if_needed()

    # append moved entries to the archive (archive holds older, moved batch is newer)
    if ARCHIVE.exists():
        archive_text = ARCHIVE.read_text(encoding='utf-8')
        if not archive_text.endswith('\n'):
            archive_text += '\n'
        new_archive = archive_text + ''.join(move_lines)
    else:
        new_archive = ARCHIVE_HEADER + '\n' + ''.join(move_lines)

    # refresh the breadcrumb pointer in log.md's header so a reader knows the older
    # entries live in log_archive.md (and up to which date)
    archive_headers = [ln for ln in new_archive.splitlines() if ln.startswith('## ')]
    keep_lines = _header_with_breadcrumb(file_header, archive_headers) + lines[entries[keep_from][0]:]

    try:
        BACKUP.write_text(text, encoding='utf-8')  # backup before overwrite
    except Exception:
        pass

    ARCHIVE.write_text(new_archive, encoding='utf-8')
    LOG.write_text(''.join(keep_lines), encoding='utf-8')

    return f"rotated {keep_from} entries to log_archive.md"


if __name__ == '__main__':
    result = rotate_if_needed()
    print(result if result else "no rotation needed")
