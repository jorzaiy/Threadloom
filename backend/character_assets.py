#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from .paths import APP_ROOT, active_user_id, character_root, character_source_root, is_multi_user_request_context, shared_path
except ImportError:
    from paths import APP_ROOT, active_user_id, character_root, character_source_root, is_multi_user_request_context, shared_path


_CHARACTER_OVERRIDE_ROOT: Path | None = None


def set_character_override_root(root: Path | None) -> None:
    global _CHARACTER_OVERRIDE_ROOT
    _CHARACTER_OVERRIDE_ROOT = root.resolve() if isinstance(root, Path) else None


def clear_character_override_root() -> None:
    set_character_override_root(None)


def character_source_base() -> Path:
    if _CHARACTER_OVERRIDE_ROOT is not None:
        return _CHARACTER_OVERRIDE_ROOT
    return character_source_root()


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def character_assets_root() -> Path:
    return character_source_base() / 'assets'


def imported_card_root() -> Path:
    return character_source_base() / 'imported'


def character_core_path() -> Path:
    return character_source_base() / 'character-data.json'


def lorebook_path() -> Path:
    return character_source_base() / 'lorebook.json'


def openings_path() -> Path:
    return character_source_base() / 'openings.json'


def system_npcs_path() -> Path:
    return character_source_base() / 'system-npcs.json'


def import_manifest_path() -> Path:
    return character_source_base() / 'import-manifest.json'


def load_character_core() -> dict:
    return _read_json(character_core_path())


def load_openings() -> dict:
    path = openings_path()
    if path.exists():
        return _read_json(path)

    core = load_character_core()
    hooks = core.get('openingHooks', []) if isinstance(core.get('openingHooks', []), list) else []
    options = []
    for index, item in enumerate(hooks, start=1):
        text = str(item or '').strip()
        if not text:
            continue
        title = text
        prompt = text
        if '：' in text:
            title, prompt = text.split('：', 1)
        elif ':' in text:
            title, prompt = text.split(':', 1)
        options.append({
            'id': f'opening-{index:02d}',
            'title': title.strip() or text,
            'prompt': prompt.strip() or text,
            'full_text': text,
        })
    return {
        'version': 1,
        'menu_intro': str(core.get('opening', '') or '').strip(),
        'bootstrap': core.get('openingBootstrap') or core.get('openingState') or {},
        'options': options,
    }


def load_system_npcs() -> dict:
    path = system_npcs_path()
    if path.exists():
        data = _read_json(path)
        if 'items' not in data:
            core = data.get('core', []) if isinstance(data.get('core', []), list) else []
            faction_named = data.get('faction_named', []) if isinstance(data.get('faction_named', []), list) else []
            roster = data.get('roster', []) if isinstance(data.get('roster', []), list) else []
            data['items'] = core + faction_named + roster
        return data
    return {'version': 2, 'core': [], 'faction_named': [], 'roster': [], 'items': []}


def load_import_manifest() -> dict:
    return _read_json(import_manifest_path())


def _legacy_imported_stem() -> str:
    core = load_character_core()
    notes = str(core.get('notes', '') or '')
    match = re.search(r'character/imported/([^.]+)\.raw-card\.json', notes)
    if match:
        return match.group(1)
    source = core.get('source', {}) if isinstance(core.get('source', {}), dict) else {}
    raw_rel = str(source.get('raw_card', '') or '').strip()
    match = re.search(r'([0-9a-f]{8,})\.raw-card\.json$', raw_rel)
    if match:
        return match.group(1)
    return ''


def resolve_character_cover_path() -> Path | None:
    asset_root = character_assets_root()
    for stem in ('cover-small', 'cover', 'cover-original'):
        for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
            candidate = asset_root / f'{stem}{ext}'
            if candidate.exists():
                return candidate

    legacy_frontend_cover = APP_ROOT / 'frontend' / 'character-cover-small.png'
    if legacy_frontend_cover.exists() and not is_multi_user_request_context():
        return legacy_frontend_cover

    stem = _legacy_imported_stem()
    if stem:
        imported_root = imported_card_root()
        for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
            candidate = imported_root / f'{stem}.original{ext}'
            if candidate.exists():
                return candidate
        for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
            if is_multi_user_request_context():
                break
            candidate = shared_path('角色卡', f'{stem}{ext}')
            if candidate.exists():
                return candidate

    return None
