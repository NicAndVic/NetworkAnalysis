from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

BLOCKED_EXT = {'.pdf', '.zip', '.xlsx', '.xls', '.xlsm', '.png', '.jpg', '.jpeg', '.gif', '.bmp'}


def _check_tracked_worktree() -> list[tuple[str, str]]:
    files = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()
    bad: list[tuple[str, str]] = []
    for f in files:
        p = Path(f)
        if p.suffix.lower() in BLOCKED_EXT:
            bad.append((f, 'blocked extension (tracked file)'))
            continue
        data = p.read_bytes()[:4096]
        if b'\x00' in data:
            bad.append((f, 'binary signature (tracked file)'))
    return bad


def _check_head_history() -> list[tuple[str, str]]:
    lines = subprocess.check_output(['git', 'rev-list', '--objects', 'HEAD'], text=True).splitlines()
    bad: list[tuple[str, str]] = []
    for line in lines:
        parts = line.split(' ', 1)
        oid = parts[0]
        path = parts[1] if len(parts) > 1 else ''
        if not path:
            continue
        obj_type = subprocess.check_output(['git', 'cat-file', '-t', oid], text=True).strip()
        if obj_type != 'blob':
            continue
        if Path(path).suffix.lower() in BLOCKED_EXT:
            bad.append((path, 'blocked extension in HEAD history'))
            continue
        data = subprocess.check_output(['git', 'cat-file', '-p', oid])[:4096]
        if b'\x00' in data:
            bad.append((path, 'binary signature in HEAD history'))
    # dedupe
    seen = set()
    uniq = []
    for item in bad:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def main() -> int:
    parser = argparse.ArgumentParser(description='Fail if binary artifacts are present in tracked files or branch history.')
    parser.add_argument('--history', action='store_true', help='Also scan HEAD history blobs (recommended for PR branch safety).')
    args = parser.parse_args()

    bad = _check_tracked_worktree()
    if args.history:
        bad.extend(_check_head_history())

    if bad:
        print('BINARY FILES DETECTED:')
        for path, reason in bad:
            print(f' - {path} ({reason})')
        return 1

    scope = 'tracked files + HEAD history' if args.history else 'tracked files'
    print(f'No binary files detected in {scope}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
