#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import tempfile
from urllib.parse import quote
from base64 import b64decode
from pathlib import Path

from card_hints import invalidate_card_hints_cache
from card_importer import extract_card_json, import_card_to_target, load_raw_card
from lorebook_distiller import rebuild_lorebook_distillation
from player_profile import build_player_profile_override_draft, load_base_player_profile
from paths import APP_ROOT, active_character_id, active_user_id, active_user_label, character_root, normalize_session_id, read_json_file, slugify, user_root
from runtime_store import invalidate_history_cache


MAX_CHARACTER_IMPORT_BYTES = 16 * 1024 * 1024


def _slug(text: str, fallback: str = 'character') -> str:
    return slugify(text, fallback)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return read_json_file(path)
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def current_user_character_root() -> Path:
    return user_root() / 'characters'


def active_character_file() -> Path:
    return user_root() / 'config' / 'active-character.json'


def _character_cover_url(character_id: str) -> str | None:
    encoded_id = quote(character_id)
    character_root = current_user_character_root() / character_id
    asset_root = character_root / 'source' / 'assets'
    for stem in ('cover-small', 'cover', 'cover-original'):
        for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
            candidate = asset_root / f'{stem}{ext}'
            if candidate.exists():
                return f'/character-cover?character_id={encoded_id}&variant={stem}'
    imported_root = character_root / 'source' / 'imported'
    for candidate in sorted(imported_root.glob('*.original.*')):
        if candidate.is_file():
            return f'/character-cover?character_id={encoded_id}'
    return None


def list_character_cards() -> list[dict]:
    root = current_user_character_root()
    items: list[dict] = []
    active_id = get_active_character_id()
    if not root.exists():
        return items
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.is_dir():
            continue
        source = path / 'source'
        core_path = source / 'character-data.json'
        data = _read_json(core_path) if core_path.exists() else {}
        core = data.get('coreDescription', {}) if isinstance(data.get('coreDescription', {}), dict) else {}
        items.append({
            'user_id': active_user_label(),
            'character_id': path.name,
            'name': str(data.get('name', '') or core.get('title', '') or path.name).strip() or path.name,
            'subtitle': str(core.get('tagline', '') or data.get('role', '') or '').strip(),
            'summary': str(data.get('displaySummary', '') or core.get('summary', '') or '').strip(),
            'cover_url': _character_cover_url(path.name),
            'has_source': source.exists(),
            'active': path.name == active_id,
        })
    return items


def get_active_character_id() -> str:
    stored = _read_json(active_character_file())
    value = str(stored.get('character_id', '') or '').strip()
    if value:
        candidate = current_user_character_root() / value
        if candidate.exists():
            return value
    return active_character_id()


def set_active_character(character_id: str) -> dict:
    value = _slug(character_id)
    target = current_user_character_root() / value
    if not target.exists():
        raise ValueError('character not found')
    _write_json(active_character_file(), {'character_id': value})
    invalidate_card_hints_cache()
    invalidate_history_cache()
    return {
        'user_id': active_user_label(),
        'character_id': value,
        'characters': list_character_cards(),
    }


def delete_character_card(character_id: str) -> dict:
    value = _slug(character_id)
    target = current_user_character_root() / value
    if not target.exists():
        raise ValueError('character not found')
    if target.resolve() == current_user_character_root().resolve():
        raise ValueError('invalid character target')
    shutil.rmtree(target)

    remaining = list_character_cards()
    active_id = get_active_character_id()
    if active_id == value:
        next_id = remaining[0]['character_id'] if remaining else ''
        _write_json(active_character_file(), {'character_id': next_id})
    invalidate_card_hints_cache()
    invalidate_history_cache()
    return {
        'ok': True,
        'deleted_character_id': value,
        'active_character_id': get_active_character_id() if remaining else '',
        'characters': list_character_cards(),
    }


def rebuild_character_lorebook(character_id: str) -> dict:
    value = _slug(character_id)
    target = current_user_character_root() / value
    source = target / 'source'
    if not target.exists() or not source.exists():
        raise ValueError('character not found')
    if not (source / 'lorebook.json').exists():
        raise ValueError('lorebook not found')
    report = rebuild_lorebook_distillation(source)
    invalidate_card_hints_cache()
    invalidate_history_cache()
    return {
        'ok': True,
        'character_id': value,
        'lorebook_distillation': report,
        'characters': list_character_cards(),
    }


def import_character_card_upload(filename: str, file_bytes: bytes, *, target_name: str = '', set_active: bool = True) -> dict:
    suffix = Path(filename or '').suffix.lower()
    if suffix not in {'.png', '.json'}:
        raise ValueError('import file must be a .png or .json raw card')

    if suffix == '.png':
        card_json = extract_card_json(file_bytes)
    else:
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False, dir='/tmp') as temp:
            temp.write(file_bytes)
            temp_path = Path(temp.name)
        try:
            card_json = load_raw_card(temp_path)
        finally:
            try:
                temp_path.unlink()
            except Exception:
                pass
    payload = card_json.get('data', {}) if isinstance(card_json.get('data'), dict) else card_json
    card_name = str(payload.get('name') or card_json.get('name') or '').strip()

    target_character_id = _slug(target_name or card_name or Path(filename).stem)
    target_root = character_root(character_id=target_character_id, user_id=active_user_id()) / 'source'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir='/tmp') as temp:
        temp.write(file_bytes)
        temp_path = Path(temp.name)
    try:
        report = import_card_to_target(temp_path, target_source_root=target_root)
    finally:
        try:
            temp_path.unlink()
        except Exception:
            pass

    if set_active:
        set_active_character(target_character_id)

    report = dict(report)
    report['user_id'] = active_user_label()
    report['character_id'] = target_character_id
    report['characters'] = list_character_cards()
    report['player_profile_override_draft'] = build_player_profile_override_draft(payload if isinstance(payload, dict) else {}, base_profile=load_base_player_profile())
    return report


def import_character_card_base64(filename: str, content_base64: str, *, target_name: str = '', set_active: bool = True) -> dict:
    try:
        file_bytes = b64decode(content_base64.encode('utf-8'), validate=True)
    except Exception as err:
        raise ValueError('invalid base64 file payload') from err
    if len(file_bytes) > MAX_CHARACTER_IMPORT_BYTES:
        raise ValueError('import file is too large')
    return import_character_card_upload(filename, file_bytes, target_name=target_name, set_active=set_active)
