#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from card_importer import _classify_lorebook_entry


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _migrate_entry(entry: dict) -> tuple[dict, bool]:
    title = str(entry.get('title', '') or '').strip()
    content = str(entry.get('content', '') or '').strip()
    keywords = entry.get('keywords', []) if isinstance(entry.get('keywords', []), list) else []
    always_on = bool(entry.get('alwaysOn', False))
    metadata = _classify_lorebook_entry(title, content, keywords, always_on)

    updated = dict(entry)
    changed = False
    for key, value in (
        ('entryType', metadata.get('entryType', 'entry')),
        ('runtimeScope', metadata.get('runtimeScope', 'situational')),
        ('featured', bool(metadata.get('featured', False))),
    ):
        if updated.get(key) != value:
            updated[key] = value
            changed = True
    return updated, changed


def migrate_lorebook_file(path: Path) -> dict:
    payload = _load_json(path)
    entries = payload.get('entries', []) if isinstance(payload.get('entries', []), list) else []
    updated_entries = []
    changed_entries = 0
    for entry in entries:
        if not isinstance(entry, dict):
            updated_entries.append(entry)
            continue
        updated, changed = _migrate_entry(entry)
        updated_entries.append(updated)
        if changed:
            changed_entries += 1
    if changed_entries > 0:
        payload = dict(payload)
        payload['entries'] = updated_entries
        _write_json(path, payload)
    return {
        'path': str(path),
        'entries': len(entries),
        'changed_entries': changed_entries,
        'updated': changed_entries > 0,
    }


def discover_lorebooks() -> list[Path]:
    roots = [Path('/root/Threadloom/character/lorebook.json')]
    roots.extend(sorted(Path('/root/Threadloom/runtime-data/default-user/characters').glob('*/source/lorebook.json')))
    return [path for path in roots if path.exists()]


def main() -> int:
    parser = argparse.ArgumentParser(description='Backfill lorebook metadata for existing character sources.')
    parser.add_argument('paths', nargs='*', help='Optional lorebook.json paths. Defaults to known local character sources.')
    args = parser.parse_args()

    targets = [Path(item).expanduser().resolve() for item in args.paths] if args.paths else discover_lorebooks()
    reports = [migrate_lorebook_file(path) for path in targets]
    print(json.dumps({'reports': reports}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
