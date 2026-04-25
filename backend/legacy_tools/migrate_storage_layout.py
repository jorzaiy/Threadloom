#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from paths import (
    APP_ROOT,
    active_character_id,
    active_user_id,
    character_npcs_root,
    character_runtime_persona_root,
    character_source_root,
    current_sessions_root,
    legacy_sessions_root,
    user_presets_root,
    user_profile_root,
)


def _copy_file(src: Path, dst: Path) -> bool:
    if not src.exists() or not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_tree(src: Path, dst: Path) -> bool:
    if not src.exists() or not src.is_dir():
        return False
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    return True


def _iter_session_dirs(*, include_archives: bool = False) -> list[Path]:
    root = legacy_sessions_root()
    if not root.exists():
        return []
    out = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        if not include_archives and path.name.startswith('archive-'):
            continue
        out.append(path)
    return sorted(out, key=lambda p: p.name)


def migrate_storage_layout(*, include_sessions: bool = False, include_archives: bool = False, force: bool = False, remove_legacy_sessions: bool = False) -> dict:
    user_id = active_user_id()
    character_id = active_character_id()

    profile_root = user_profile_root()
    presets_root = user_presets_root()
    source_root = character_source_root()
    npcs_root = character_npcs_root()
    persona_root = character_runtime_persona_root()
    sessions_root = current_sessions_root()

    if force:
        for path in (profile_root, presets_root, source_root, sessions_root):
            if path.exists():
                shutil.rmtree(path)

    copied = {
        'user_files': [],
        'preset_dirs': [],
        'character_files': [],
        'session_dirs': [],
        'removed_legacy_session_dirs': [],
    }

    user_files = ['USER.md', 'player-profile.json', 'player-profile.md']
    for name in user_files:
        src = APP_ROOT / name
        dst = profile_root / name
        if _copy_file(src, dst):
            copied['user_files'].append(str(dst))

    preset_src = APP_ROOT / 'character' / 'presets'
    if _copy_tree(preset_src, presets_root):
        copied['preset_dirs'].append(str(presets_root))

    character_files = {
        APP_ROOT / 'character' / 'character-data.json': source_root / 'character-data.json',
        APP_ROOT / 'character' / 'lorebook.json': source_root / 'lorebook.json',
        APP_ROOT / 'memory' / 'canon.md': source_root / 'canon.md',
        APP_ROOT / 'memory' / 'state.md': source_root / 'state.md',
        APP_ROOT / 'memory' / 'summary.md': source_root / 'summary.md',
    }
    for src, dst in character_files.items():
        if _copy_file(src, dst):
            copied['character_files'].append(str(dst))

    _copy_tree(APP_ROOT / 'memory' / 'npcs', npcs_root)
    _copy_tree(APP_ROOT / 'runtime' / 'persona-seeds', persona_root)

    if include_sessions:
        for session_dir in _iter_session_dirs(include_archives=include_archives):
            if not session_dir.exists():
                continue
            target = sessions_root / session_dir.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(session_dir, target)
            copied['session_dirs'].append(str(target))
            if remove_legacy_sessions:
                shutil.rmtree(session_dir)
                copied['removed_legacy_session_dirs'].append(str(session_dir))

    report = {
        'user_id': user_id,
        'character_id': character_id,
        'profile_root': str(profile_root),
        'presets_root': str(presets_root),
        'character_source_root': str(source_root),
        'sessions_root': str(sessions_root),
        'copied': copied,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='Copy current flat storage into the new user/character/session layout')
    parser.add_argument('--include-sessions', action='store_true', help='Also copy existing legacy session directories into the new character session root')
    parser.add_argument('--include-archives', action='store_true', help='When copying sessions, also include archive-* directories')
    parser.add_argument('--force', action='store_true', help='Remove existing migrated targets before copying')
    parser.add_argument('--remove-legacy-sessions', action='store_true', help='After copying sessions into the new root, delete the legacy session directories')
    args = parser.parse_args()

    if args.remove_legacy_sessions and not args.include_sessions:
        raise SystemExit('--remove-legacy-sessions requires --include-sessions')

    report = migrate_storage_layout(
        include_sessions=args.include_sessions,
        include_archives=args.include_archives,
        force=args.force,
        remove_legacy_sessions=args.remove_legacy_sessions,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
