from __future__ import annotations

from pathlib import Path

BIDI_CODEPOINTS = {
    *(range(0x202A, 0x202F)),
    *(range(0x2066, 0x206A)),
    0x200E,
    0x200F,
    0x061C,
}


def scan_files() -> list[tuple[Path, int, str]]:
    root = Path(__file__).resolve().parents[1]
    findings: list[tuple[Path, int, str]] = []
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix not in {'.py', '.html'}:
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(content.splitlines(), start=1):
            for ch in line:
                if ord(ch) in BIDI_CODEPOINTS:
                    findings.append((path.relative_to(root), line_no, f'U+{ord(ch):04X}'))
                    break
    return findings


def main() -> int:
    findings = scan_files()
    if findings:
        print('Bidi control characters detected:')
        for path, line_no, cp in findings:
            print(f' - {path}:{line_no} ({cp})')
        return 1
    print('No bidi control characters found in .py/.html files.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
