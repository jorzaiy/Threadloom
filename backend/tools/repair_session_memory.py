#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from memory_maintenance import repair_memory
from paths import normalize_session_id, reset_active_character_override, set_active_character_override


def main() -> int:
    parser = argparse.ArgumentParser(description='Repair deterministic Threadloom session memory layers')
    parser.add_argument('--session', required=True, help='Session id to inspect or repair')
    parser.add_argument('--character-id', help='Target character id / directory override')
    parser.add_argument('--apply', action='store_true', help='Persist repairs. Default is dry-run only.')
    parser.add_argument('--rebuild-derived', action='store_true', help='Rebuild derived summary chunks and keeper archive where possible')
    parser.add_argument('--no-archive-write', action='store_true', help='Do not write keeper archive even with --apply')
    args = parser.parse_args()

    override_token = set_active_character_override(args.character_id)
    try:
        report = repair_memory(
            normalize_session_id(args.session),
            dry_run=not args.apply,
            rebuild_derived=bool(args.rebuild_derived),
            allow_archive_write=not args.no_archive_write,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        reset_active_character_override(override_token)


if __name__ == '__main__':
    raise SystemExit(main())
