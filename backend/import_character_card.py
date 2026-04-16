#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from card_importer import extract_card_json, import_card, import_card_to_target, import_raw_card_file, load_raw_card
from paths import active_user_id, character_source_root, character_root


def _slug(text: str, fallback: str = 'character') -> str:
    value = str(text or '').strip()
    if not value:
        return fallback
    value = re.sub(r'[\\/:\s]+', '-', value)
    value = re.sub(r'[^0-9A-Za-z_\-\u4e00-\u9fff·]+', '', value)
    value = value.strip('-')
    return value or fallback


def main() -> int:
    parser = argparse.ArgumentParser(description='Import a character card into the current character source bundle.')
    parser.add_argument('source', help='Path to a Tavern PNG card or a raw-card.json file')
    parser.add_argument('--target-name', help='Target character directory name. Defaults to card name.')
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f'source not found: {source}')

    if source.suffix.lower() == '.png':
        card_json = extract_card_json(source.read_bytes())
    elif source.suffix.lower() == '.json':
        card_json = load_raw_card(source)
    else:
        raise SystemExit('source must be a .png or .json raw card')

    payload = card_json.get('data', {}) if isinstance(card_json.get('data'), dict) else card_json
    card_name = str(payload.get('name') or card_json.get('name') or '').strip()
    target_name = args.target_name or card_name or source.stem
    target_root = character_root(character_id=_slug(target_name), user_id=active_user_id()) / 'source'
    report = import_card_to_target(source, target_source_root=target_root)
    report['target_source_root'] = str(target_root)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
