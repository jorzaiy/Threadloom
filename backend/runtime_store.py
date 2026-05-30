#!/usr/bin/env python3
import copy
import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

try:
    from atomic_io import atomic_write_json, atomic_write_text
    from .character_assets import resolve_character_cover_path
    from .persona_runtime import infer_persona_traits
    from .name_sanitizer import sanitize_runtime_name, looks_like_bad_entity_fragment
    from .paths import APP_ROOT, SHARED_ROOT, active_character_id, active_user_label, character_npcs_root, character_runtime_persona_root, character_source_root, is_character_override_active, is_multi_user_request_context, normalize_turn_id, resolve_layered_source, resolve_session_dir, shared_path
except ImportError:
    from atomic_io import atomic_write_json, atomic_write_text
    from character_assets import resolve_character_cover_path
    from persona_runtime import infer_persona_traits
    from name_sanitizer import sanitize_runtime_name, looks_like_bad_entity_fragment
    from paths import APP_ROOT, SHARED_ROOT, active_character_id, active_user_label, character_npcs_root, character_runtime_persona_root, character_source_root, is_character_override_active, is_multi_user_request_context, normalize_turn_id, resolve_layered_source, resolve_session_dir, shared_path

ROOT = SHARED_ROOT
RUNTIME_WEB = APP_ROOT
CONFIG = RUNTIME_WEB / 'config' / 'runtime.json'
HISTORY_SHARD_SIZE = 24

logger = logging.getLogger(__name__)

# Single process-wide lock guarding the in-memory history cache and the
# read-modify-write store helpers (history, event summaries, meta, shards).
# Mirrors player_profile.PLAYER_PROFILE_LOCK. Reentrant so nested calls such as
# append_history -> save_history -> invalidate_history_cache don't self-deadlock.
_STORE_LOCK = threading.RLock()


def _backup_corrupt_json(path: Path) -> None:
    """Move a corrupt JSON file aside to ``<name>.corrupt`` so the bad bytes are
    preserved for diagnosis instead of being silently overwritten by the next
    save."""
    backup = path.with_name(path.name + '.corrupt')
    try:
        os.replace(path, backup)
        logger.warning('moved corrupt json aside: %s -> %s', path, backup.name)
    except OSError:
        logger.exception('failed to move corrupt json aside: %s', path)


def _load_json(path: Path, default, *, backup_corrupt: bool = True):
    """Load JSON from ``path``.

    Returns a deep copy of ``default`` when the file is absent. When the file
    exists but cannot be parsed, the failure is logged and (unless
    ``backup_corrupt`` is False) the corrupt file is moved aside before the
    default is returned -- so a corrupt file is never silently mistaken for a
    missing one. Pass ``backup_corrupt=False`` for user-authored files (e.g.
    config) that should be fixed in place rather than relocated.
    """
    if not path.exists():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        logger.exception('failed to parse json: %s', path)
        if backup_corrupt:
            _backup_corrupt_json(path)
        return copy.deepcopy(default)


# ---------------------------------------------------------------------------
# 原子写入：先写临时文件再 rename，防止中途中断导致文件损坏
# ---------------------------------------------------------------------------
def _atomic_write_text(path: Path, content: str, encoding: str = 'utf-8') -> None:
    atomic_write_text(path, content, encoding=encoding)


def _atomic_write_json(path: Path, data, *, indent: int = 2) -> None:
    atomic_write_json(path, data, indent=indent)

_history_cache: dict[str, tuple[float, list]] = {}


def _history_cache_key(path: Path) -> str:
    return str(path.resolve(strict=False))


def invalidate_history_cache(session_id: str | None = None) -> None:
    """Clear cached history. Call after appending to history."""
    with _STORE_LOCK:
        if session_id:
            path = session_paths(session_id)['history']
            _history_cache.pop(_history_cache_key(path), None)
        else:
            _history_cache.clear()


def character_data_path() -> Path:
    layered = character_source_root() / 'character-data.json'
    if layered.exists():
        return layered
    if is_multi_user_request_context() or is_character_override_active():
        return layered
    return shared_path('character', 'character-data.json')


def root_persona_dir() -> Path:
    layered = character_runtime_persona_root()
    if layered.exists():
        return layered
    return layered


def character_npc_profiles_dir() -> Path:
    layered = character_npcs_root()
    if layered.exists():
        return layered
    if is_multi_user_request_context() or is_character_override_active():
        return layered
    return shared_path('memory', 'npcs')


def load_runtime_web_config() -> dict:
    # User-authored config: log on corruption but never relocate the file, so
    # the operator can fix it in place.
    return _load_json(CONFIG, {}, backup_corrupt=False)


def _read_json_file(path: Path) -> dict:
    return _load_json(path, {}, backup_corrupt=False)


def load_character_card_meta() -> dict:
    data = _read_json_file(character_data_path())
    core = data.get('coreDescription', {}) if isinstance(data.get('coreDescription', {}), dict) else {}
    cover_path = resolve_character_cover_path()
    character_id = active_character_id()
    return {
        'user_id': active_user_label(),
        'character_id': character_id,
        'name': str(data.get('name', '') or core.get('title', '') or '未命名角色卡').strip(),
        'title': str(core.get('title', '') or data.get('name', '') or '未命名角色卡').strip(),
        'subtitle': str(core.get('tagline', '') or data.get('role', '') or '').strip(),
        'summary': str(core.get('summary', '') or '').strip(),
        'cover_url': f'/character-cover?character_id={quote(character_id)}&variant=cover-small' if cover_path else None,
        'has_cover': bool(cover_path),
    }


def ensure_session_dirs(session_id: str) -> Path:
    session_dir = resolve_session_dir(session_id, create=True)
    (session_dir / 'memory').mkdir(parents=True, exist_ok=True)
    (session_dir / 'persona' / 'scene').mkdir(parents=True, exist_ok=True)
    (session_dir / 'persona' / 'archive').mkdir(parents=True, exist_ok=True)
    (session_dir / 'persona' / 'longterm').mkdir(parents=True, exist_ok=True)
    return session_dir


def session_paths(session_id: str) -> dict:
    session_dir = ensure_session_dirs(session_id)
    memory_dir = session_dir / 'memory'
    persona_dir = session_dir / 'persona'
    trace_dir = session_dir / 'turn-trace'
    return {
        'session_dir': session_dir,
        'memory_dir': memory_dir,
        'persona_dir': persona_dir,
        'persona_scene_dir': persona_dir / 'scene',
        'persona_archive_dir': persona_dir / 'archive',
        'persona_longterm_dir': persona_dir / 'longterm',
        'trace_dir': trace_dir,
        'history': memory_dir / 'history.jsonl',
        'history_manifest': memory_dir / 'history_manifest.json',
        'history_shards_dir': memory_dir / 'history_shards',
        'state': memory_dir / 'state.json',
        'continuity_hints': memory_dir / 'continuity_hints.json',
        'canon': memory_dir / 'canon.md',
        'summary': memory_dir / 'summary.md',
        'event_summaries': memory_dir / 'event_summaries.json',
        'summary_chunks': memory_dir / 'summary_chunks.json',
        'keeper_archive': memory_dir / 'keeper_record_archive.json',
        'context': session_dir / 'context.json',
        'meta': session_dir / 'meta.json',
    }


def _turn_index_from_id(value: str) -> int:
    match = re.search(r'(\d+)$', str(value or ''))
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def _history_shard_bounds(turn_index: int, shard_size: int = HISTORY_SHARD_SIZE) -> tuple[int, int]:
    if turn_index <= 0:
        return 0, 0
    start = ((turn_index - 1) // shard_size) * shard_size + 1
    return start, start + shard_size - 1


def _history_shard_filename(start: int, end: int) -> str:
    return f'turns-{start:06d}-{end:06d}.jsonl'


def _read_jsonl_items(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items: list[dict] = []
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except Exception:
        return []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except Exception:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def _complete_history_pairs(items: list[dict]) -> list[dict]:
    pairs: list[dict] = []
    current_user = None
    for item in filter_committed_history_items(items):
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        if role == 'user':
            current_user = item
        elif role == 'assistant' and current_user is not None and is_complete_assistant_item(item):
            turn_index = len(pairs) + 1
            pairs.append({
                'turn_index': turn_index,
                'turn_id': f'turn-{turn_index:04d}',
                'user': current_user,
                'assistant': item,
            })
            current_user = None
    return pairs


def _write_history_manifest(session_id: str, shards: list[dict], current_turn_end: int) -> None:
    payload = {
        'version': 1,
        'shard_size': HISTORY_SHARD_SIZE,
        'summary_chunk_size': 12,
        'current_turn_end': current_turn_end,
        'shards': shards,
    }
    _atomic_write_json(session_paths(session_id)['history_manifest'], payload)


def _rebuild_history_shards(session_id: str, items: list[dict]) -> None:
    paths = session_paths(session_id)
    shard_dir = paths['history_shards_dir']
    shard_dir.mkdir(parents=True, exist_ok=True)
    pairs = _complete_history_pairs(items)
    grouped: dict[tuple[int, int], list[dict]] = {}
    for pair in pairs:
        turn_index = int(pair['turn_index'])
        start, end = _history_shard_bounds(turn_index)
        user_item = dict(pair['user'])
        assistant_item = dict(pair['assistant'])
        turn_id = str(pair['turn_id'])
        user_item['turn_id'] = turn_id
        assistant_item['turn_id'] = turn_id
        grouped.setdefault((start, end), []).extend([user_item, assistant_item])
    expected_names = {_history_shard_filename(start, end) for start, end in grouped}
    for path in shard_dir.glob('turns-*.jsonl'):
        if path.name not in expected_names:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
    shards = []
    for start, end in sorted(grouped):
        filename = _history_shard_filename(start, end)
        rel_path = f'history_shards/{filename}'
        content = ''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in grouped[(start, end)])
        _atomic_write_text(shard_dir / filename, content)
        actual_turns = sorted({
            _turn_index_from_id(str(item.get('turn_id', '') or ''))
            for item in grouped[(start, end)]
            if _turn_index_from_id(str(item.get('turn_id', '') or '')) > 0
        })
        turn_end = actual_turns[-1] if actual_turns else start - 1
        first_summary = ((start - 1) // 12) + 1
        last_summary = ((end - 1) // 12) + 1
        shards.append({
            'shard_id': filename[:-6],
            'turn_start': start,
            'turn_end': turn_end,
            'path': rel_path,
            'complete': turn_end >= end,
            'summary_chunks': [f'chunk_{idx:04d}' for idx in range(first_summary, last_summary + 1)],
        })
    _write_history_manifest(session_id, shards, len(pairs))


def load_history_manifest(session_id: str) -> dict:
    default = {'version': 1, 'shard_size': HISTORY_SHARD_SIZE, 'summary_chunk_size': 12, 'current_turn_end': 0, 'shards': []}
    data = _load_json(session_paths(session_id)['history_manifest'], default)
    if not isinstance(data, dict):
        return copy.deepcopy(default)
    data.setdefault('version', 1)
    data.setdefault('shard_size', HISTORY_SHARD_SIZE)
    data.setdefault('summary_chunk_size', 12)
    data.setdefault('current_turn_end', 0)
    data.setdefault('shards', [])
    if not isinstance(data.get('shards'), list):
        data['shards'] = []
    return data


def _history_manifest_needs_rebuild(session_id: str, manifest: dict) -> bool:
    paths = session_paths(session_id)
    history_path = paths['history']
    manifest_path = paths['history_manifest']
    if not history_path.exists():
        return False
    try:
        current_turn_end = int(manifest.get('current_turn_end', 0) or 0)
    except (TypeError, ValueError):
        return True
    if not manifest_path.exists():
        return True
    if not manifest.get('shards'):
        return current_turn_end > 0
    try:
        if history_path.stat().st_mtime > manifest_path.stat().st_mtime:
            return True
    except Exception:
        return True
    shard_dir = paths['history_shards_dir']
    for shard in manifest.get('shards', []) or []:
        if not isinstance(shard, dict):
            return True
        try:
            start = int(shard.get('turn_start', 0) or 0)
        except (TypeError, ValueError):
            return True
        end = start + HISTORY_SHARD_SIZE - 1
        if start <= 0:
            return True
        if not (shard_dir / _history_shard_filename(start, end)).exists():
            return True
    return False


def ensure_history_shards(session_id: str) -> dict:
    with _STORE_LOCK:
        manifest = load_history_manifest(session_id)
        if not _history_manifest_needs_rebuild(session_id, manifest):
            return manifest
        items = load_history(session_id)
        _rebuild_history_shards(session_id, items)
        return load_history_manifest(session_id)


def load_history_pair_count(session_id: str) -> int:
    manifest = ensure_history_shards(session_id)
    try:
        return int(manifest.get('current_turn_end', 0) or 0)
    except (TypeError, ValueError):
        return len(_complete_history_pairs(load_history(session_id)))


def _load_shard_items_for_turn(session_id: str, turn_index: int) -> list[dict]:
    if turn_index <= 0:
        return []
    paths = session_paths(session_id)
    start, end = _history_shard_bounds(turn_index)
    return _read_jsonl_items(paths['history_shards_dir'] / _history_shard_filename(start, end))


def _load_all_history_shard_items(session_id: str) -> list[dict]:
    manifest = load_history_manifest(session_id)
    paths = session_paths(session_id)
    items: list[dict] = []
    shards = [shard for shard in manifest.get('shards', []) or [] if isinstance(shard, dict)]
    shards.sort(key=lambda shard: int(shard.get('turn_start', 0) or 0))
    for shard in shards:
        try:
            start = int(shard.get('turn_start', 0) or 0)
        except (TypeError, ValueError):
            continue
        if start <= 0:
            continue
        _start, end = _history_shard_bounds(start)
        items.extend(_read_jsonl_items(paths['history_shards_dir'] / _history_shard_filename(start, end)))
    return items


def load_history_turn_pair(session_id: str, turn_index: int) -> dict:
    ensure_history_shards(session_id)
    items = _load_shard_items_for_turn(session_id, turn_index)
    turn_id = f'turn-{turn_index:04d}'
    user_item = None
    assistant_item = None
    for item in items:
        if str(item.get('turn_id', '') or '') != turn_id:
            continue
        if item.get('role') == 'user':
            user_item = item
        elif item.get('role') == 'assistant' and is_complete_assistant_item(item):
            assistant_item = item
    if user_item is not None and assistant_item is not None:
        return {'turn_index': turn_index, 'turn_id': turn_id, 'user': user_item, 'assistant': assistant_item}
    for pair in _complete_history_pairs(load_history(session_id)):
        if int(pair.get('turn_index', 0) or 0) == turn_index:
            return pair
    return {}


def load_recent_history(session_id: str, limit_pairs: int) -> list[dict]:
    if limit_pairs <= 0:
        return []
    pair_count = load_history_pair_count(session_id)
    if pair_count <= 0 or pair_count <= limit_pairs:
        return _select_recent_history_window(load_history(session_id), limit_pairs)
    start_turn = max(1, pair_count - limit_pairs + 1)
    needed_bounds = []
    current = start_turn
    while current <= pair_count:
        bounds = _history_shard_bounds(current)
        needed_bounds.append(bounds)
        current = bounds[1] + 1
    items: list[dict] = []
    seen_bounds: set[tuple[int, int]] = set()
    paths = session_paths(session_id)
    for start, end in needed_bounds:
        if (start, end) in seen_bounds:
            continue
        seen_bounds.add((start, end))
        items.extend(_read_jsonl_items(paths['history_shards_dir'] / _history_shard_filename(start, end)))
    if not items:
        return _select_recent_history_window(load_history(session_id), limit_pairs)
    filtered = []
    for item in items:
        turn_index = _turn_index_from_id(str(item.get('turn_id', '') or ''))
        if start_turn <= turn_index <= pair_count:
            filtered.append(item)
    pair_roles: dict[int, set[str]] = {}
    for item in filtered:
        turn_index = _turn_index_from_id(str(item.get('turn_id', '') or ''))
        if turn_index <= 0:
            continue
        role = str(item.get('role', '') or '')
        if role == 'assistant' and not is_complete_assistant_item(item):
            continue
        pair_roles.setdefault(turn_index, set()).add(role)
    expected_turns = set(range(start_turn, pair_count + 1))
    complete_turns = {turn for turn, roles in pair_roles.items() if {'user', 'assistant'} <= roles}
    if not expected_turns <= complete_turns:
        return _select_recent_history_window(load_history(session_id), limit_pairs)
    return filtered or _select_recent_history_window(load_history(session_id), limit_pairs)


def _select_recent_history_window(items: list[dict], limit_pairs: int) -> list[dict]:
    if limit_pairs <= 0:
        return []
    filtered = filter_committed_history_items(items)
    if not filtered:
        return []

    pair_count = 0
    start_index = len(filtered)
    pending_user = False
    for index in range(len(filtered) - 1, -1, -1):
        role = filtered[index].get('role')
        if role == 'assistant':
            pending_user = True
            start_index = index
        elif role == 'user' and pending_user:
            pair_count += 1
            pending_user = False
            start_index = index
            if pair_count >= limit_pairs:
                break
    if pair_count == 0:
        return filtered[-max(1, limit_pairs * 2):]
    return filtered[start_index:]


def load_history(session_id: str) -> list:
    with _STORE_LOCK:
        path = session_paths(session_id)['history']
        if not path.exists():
            return _load_all_history_shard_items(session_id)
        try:
            mtime = path.stat().st_mtime
        except Exception:
            mtime = 0.0
        cache_key = _history_cache_key(path)
        cached = _history_cache.get(cache_key)
        if cached and cached[0] == mtime:
            return list(cached[1])
        items = _read_jsonl_items(path)
        _history_cache[cache_key] = (mtime, items)
        return list(items)


def is_complete_assistant_item(item: dict) -> bool:
    if item.get('role') != 'assistant':
        return True
    return item.get('completion_status', 'complete') == 'complete'


def filter_committed_history_items(items: list[dict]) -> list[dict]:
    committed: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if item.get('role') == 'assistant' and not is_complete_assistant_item(item):
            if committed and isinstance(committed[-1], dict) and committed[-1].get('role') == 'user':
                committed.pop()
            continue
        committed.append(item)
    return committed


def append_history(session_id: str, item: dict) -> None:
    with _STORE_LOCK:
        items = load_history(session_id)
        if isinstance(item, dict) and item.get('role') == 'user':
            while items and isinstance(items[-1], dict) and items[-1].get('role') == 'assistant' and not is_complete_assistant_item(items[-1]):
                items.pop()
                if items and isinstance(items[-1], dict) and items[-1].get('role') == 'user':
                    items.pop()
        items.append(item)
        save_history(session_id, items)


def save_history(session_id: str, items: list[dict]) -> None:
    with _STORE_LOCK:
        path = session_paths(session_id)['history']
        content = ''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in (items or []))
        _atomic_write_text(path, content)
        _rebuild_history_shards(session_id, items)
        invalidate_history_cache(session_id)


def load_state(session_id: str) -> dict:
    path = session_paths(session_id)['state']
    if not path.exists():
        return {
            'time': '待确认',
            'location': '待确认',
            'main_event': '待确认',
            'onstage_npcs': [],
            'relevant_npcs': [],
            'immediate_goal': '待确认',
            'carryover_signals': [],
            'immediate_risks': [],
            'carryover_clues': [],
            'actors': {
                'protagonist': {
                    'actor_id': 'protagonist',
                    'kind': 'protagonist',
                    'name': '主角',
                    'aliases': ['你', '主角'],
                    'personality': '',
                    'appearance': '',
                    'identity': '主角',
                    'created_turn': 1,
                },
            },
            'actor_context_index': {
                'active_actor_ids': ['protagonist'],
                'archived_actor_ids': [],
                'last_mentioned_turn': {'protagonist': 1},
                'archive_after_quiet_turns': 12,
            },
            'knowledge_records': [],
        }
    return _load_json(path, {})


def load_continuity_hints(session_id: str) -> list:
    data = _load_json(session_paths(session_id)['continuity_hints'], [])
    if isinstance(data, dict):
        items = data.get('entries', [])
        return items if isinstance(items, list) else []
    return data if isinstance(data, list) else []


def load_summary_chunks(session_id: str) -> dict:
    data = _load_json(session_paths(session_id)['summary_chunks'], {'version': 1, 'chunks': []})
    chunks = data.get('chunks', []) if isinstance(data, dict) else []
    return {'version': int(data.get('version', 1) or 1) if isinstance(data, dict) else 1, 'chunks': chunks if isinstance(chunks, list) else []}


def save_summary_chunks(session_id: str, chunks: dict) -> None:
    data = chunks if isinstance(chunks, dict) else {'version': 1, 'chunks': []}
    if not isinstance(data.get('chunks', []), list):
        data['chunks'] = []
    data.setdefault('version', 1)
    _atomic_write_json(session_paths(session_id)['summary_chunks'], data)


def save_continuity_hints(session_id: str, items: list[dict]) -> None:
    path = session_paths(session_id)['continuity_hints']
    payload = {'entries': items}
    _atomic_write_json(path, payload)


def load_summary(session_id: str) -> str:
    path = session_paths(session_id)['summary']
    return path.read_text(encoding='utf-8') if path.exists() else '# Summary\n\n## 最近阶段摘要\n- 暂无\n'


def save_summary(session_id: str, text: str) -> None:
    path = session_paths(session_id)['summary']
    _atomic_write_text(path, text)


def load_event_summaries(session_id: str) -> dict:
    data = _load_json(session_paths(session_id)['event_summaries'], {'version': 1, 'items': []})
    if not isinstance(data, dict):
        return {'version': 1, 'items': []}
    items = data.get('items', [])
    return {
        'version': int(data.get('version', 1) or 1),
        'items': items if isinstance(items, list) else [],
    }


def save_event_summaries(session_id: str, payload: dict) -> None:
    path = session_paths(session_id)['event_summaries']
    data = payload if isinstance(payload, dict) else {'version': 1, 'items': []}
    _atomic_write_json(path, data)


def append_event_summary(session_id: str, item: dict) -> None:
    with _STORE_LOCK:
        payload = load_event_summaries(session_id)
        items = list(payload.get('items', []) or [])
        items.append(item)
        payload['items'] = items[-80:]
        save_event_summaries(session_id, payload)


def upsert_event_summary(session_id: str, item: dict) -> None:
    with _STORE_LOCK:
        payload = load_event_summaries(session_id)
        turn_id = str(item.get('turn_id', '') or '').strip() if isinstance(item, dict) else ''
        event_id = str(item.get('event_id', '') or '').strip() if isinstance(item, dict) else ''
        items = []
        replaced = False
        for existing in payload.get('items', []) or []:
            if not isinstance(existing, dict):
                continue
            same_turn = turn_id and str(existing.get('turn_id', '') or '').strip() == turn_id
            same_event = event_id and str(existing.get('event_id', '') or '').strip() == event_id
            if same_turn or same_event:
                if not replaced:
                    items.append(item)
                    replaced = True
                continue
            items.append(existing)
        if not replaced:
            items.append(item)
        payload['items'] = items[-80:]
        save_event_summaries(session_id, payload)


def load_canon(session_id: str) -> str:
    path = session_paths(session_id)['canon']
    return path.read_text(encoding='utf-8') if path.exists() else '# Canon\n\n## 世界长期事实\n- 待确认\n'


def save_canon(session_id: str, text: str) -> None:
    path = session_paths(session_id)['canon']
    _atomic_write_text(path, text)


def load_context(session_id: str) -> dict:
    return _load_json(session_paths(session_id)['context'], {})


def save_context(session_id: str, context: dict) -> None:
    path = session_paths(session_id)['context']
    _atomic_write_json(path, context)


def save_state(session_id: str, state: dict) -> None:
    path = session_paths(session_id)['state']
    _atomic_write_json(path, state)


def trace_path(session_id: str, turn_id: str) -> Path:
    path = _trace_file_path(session_id, turn_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _trace_file_path(session_id: str, turn_id: str) -> Path:
    paths = session_paths(session_id)
    trace_dir = paths['trace_dir']
    safe_turn_id = normalize_turn_id(turn_id)
    return trace_dir / f'{safe_turn_id}.json'


def trace_runtime_settings() -> dict:
    trace = load_runtime_web_config().get('trace', {})
    if not isinstance(trace, dict):
        trace = {}
    try:
        keep_last_turns = int(trace.get('keep_last_turns', 40) or 40)
    except (TypeError, ValueError):
        keep_last_turns = 40
    keep_last_turns = max(1, keep_last_turns)
    return {
        'enabled': bool(trace.get('enabled', True)),
        'keep_last_turns': keep_last_turns,
    }


def _prune_trace_files(trace_dir: Path, keep_last_turns: int) -> None:
    files = sorted(
        [path for path in trace_dir.glob('*.json') if path.is_file()],
        key=lambda path: path.name,
    )
    for path in files[:-keep_last_turns]:
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def save_turn_trace(session_id: str, turn_id: str, trace: dict) -> Path:
    settings = trace_runtime_settings()
    path = _trace_file_path(session_id, turn_id)
    if not settings['enabled']:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, trace)
    _prune_trace_files(path.parent, settings['keep_last_turns'])
    return path


def load_turn_trace(session_id: str, turn_id: str) -> dict:
    return _load_json(_trace_file_path(session_id, turn_id), {})


def build_state_snapshot(state: dict) -> dict:
    raw_scene_entities = state.get('scene_entities', []) if isinstance(state.get('scene_entities', []), list) else []
    scene_entities = [
        item for item in raw_scene_entities
        if isinstance(item, dict)
        and sanitize_runtime_name(item.get('primary_label', ''))
        and not looks_like_bad_entity_fragment(item.get('primary_label', ''))
    ]
    entity_index = {
        sanitize_runtime_name(item.get('primary_label', '')): item
        for item in scene_entities
        if isinstance(item, dict) and sanitize_runtime_name(item.get('primary_label', ''))
    }

    def build_named_entities(names: list[str]) -> list[dict]:
        rows: list[dict] = []
        name_counts: dict[str, int] = {}
        for item in scene_entities:
            if not isinstance(item, dict):
                continue
            label = sanitize_runtime_name(item.get('primary_label', ''))
            if not label:
                continue
            name_counts[label] = name_counts.get(label, 0) + 1
        for name in names or []:
            label = sanitize_runtime_name(name)
            if not label:
                continue
            entity = entity_index.get(label, {}) if name_counts.get(label, 0) == 1 else {}
            rows.append({
                'name': label,
                'entity_id': entity.get('entity_id') if entity else None,
                'role_label': entity.get('role_label') if entity else None,
                'ambiguous': name_counts.get(label, 0) > 1,
            })
        return rows

    return {
        'time': state.get('time', '待确认'),
        'location': state.get('location', '待确认'),
        'main_event': state.get('main_event', '待确认'),
        'scene_entities': scene_entities,
        'onstage_entities': build_named_entities(state.get('onstage_npcs', [])),
        'relevant_entities': build_named_entities(state.get('relevant_npcs', [])),
        'active_threads': state.get('active_threads', []),
        'important_npcs': state.get('important_npcs', []),
        'onstage_npcs': state.get('onstage_npcs', []),
        'relevant_npcs': state.get('relevant_npcs', []),
        'scene_objective': state.get('scene_objective', {}),
        'immediate_goal': state.get('immediate_goal', '待确认'),
        'carryover_signals': state.get('carryover_signals', []),
        'immediate_risks': state.get('immediate_risks', []),
        'carryover_clues': state.get('carryover_clues', []),
        'tracked_objects': state.get('tracked_objects', []),
        'graveyard_objects': state.get('graveyard_objects', []),
        'possession_state': state.get('possession_state', []),
        'object_visibility': state.get('object_visibility', []),
        'actors': state.get('actors', {}),
        'actor_context_index': state.get('actor_context_index', {}),
        'actor_persona_hooks': state.get('actor_persona_hooks', {}),
        'knowledge_records': state.get('knowledge_records', []),
    }


def _persona_filename(display_name: str) -> str:
    safe = (display_name or 'unknown').replace('/', '_').replace('\\', '_').strip()
    return f'{safe}.json'


def _load_persona_dir(directory: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not directory.exists():
        return out
    for path in sorted(directory.glob('*.json')):
        data = _load_json(path, None)
        if not isinstance(data, dict):
            continue
        display = data.get('display_name') or data.get('npc_id') or path.stem
        if display and display not in out:
            out[display] = data
    return out


def load_session_persona_layers(session_id: str) -> dict[str, dict[str, dict]]:
    paths = session_paths(session_id)
    return {
        'scene': _load_persona_dir(paths['persona_scene_dir']),
        'archive': _load_persona_dir(paths['persona_archive_dir']),
        'longterm': _load_persona_dir(paths['persona_longterm_dir']),
    }


def save_session_persona_layers(session_id: str, layers: dict[str, dict[str, dict]] | None) -> None:
    paths = session_paths(session_id)
    normalized = layers if isinstance(layers, dict) else {}
    layer_dirs = {
        'scene': paths['persona_scene_dir'],
        'archive': paths['persona_archive_dir'],
        'longterm': paths['persona_longterm_dir'],
    }
    for layer, directory in layer_dirs.items():
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.glob('*.json'):
            path.unlink()
        layer_items = normalized.get(layer, {})
        if not isinstance(layer_items, dict):
            continue
        for display_name, seed in sorted(layer_items.items()):
            if not isinstance(seed, dict):
                continue
            filename = _persona_filename(str(display_name or seed.get('display_name') or seed.get('npc_id') or 'unknown'))
            _atomic_write_json(directory / filename, seed)


def load_persona_index(session_id: str | None = None) -> dict[str, dict]:
    index: dict[str, dict] = {}
    directories: list[Path] = []
    if session_id:
        paths = session_paths(session_id)
        directories.extend([
            paths['persona_scene_dir'],
            paths['persona_longterm_dir'],
            paths['persona_archive_dir'],
        ])
    directories.extend([
        root_persona_dir() / 'scene',
        root_persona_dir() / 'longterm',
        root_persona_dir() / 'archive',
    ])
    for directory in directories:
        for display, data in _load_persona_dir(directory).items():
            if display not in index:
                index[display] = data
    return index


def save_persona_seed(session_id: str, layer: str, seed: dict) -> Path:
    paths = session_paths(session_id)
    key = f'persona_{layer}_dir'
    target_dir = paths[key]
    display_name = seed.get('display_name') or seed.get('npc_id') or 'unknown'
    path = target_dir / _persona_filename(display_name)
    _atomic_write_json(path, seed)
    return path


def delete_persona_seed(session_id: str, layer: str, display_name: str) -> None:
    paths = session_paths(session_id)
    key = f'persona_{layer}_dir'
    path = paths[key] / _persona_filename(display_name)
    if path.exists():
        path.unlink()


def build_entity_map(state: dict, session_id: str | None = None) -> dict:
    scene_entities = state.get('scene_entities', [])
    onstage = {sanitize_runtime_name(name) for name in (state.get('onstage_npcs', []) or []) if sanitize_runtime_name(name)}
    relevant = {sanitize_runtime_name(name) for name in (state.get('relevant_npcs', []) or []) if sanitize_runtime_name(name)}
    persona_by_name = load_persona_index(session_id)

    def fallback_persona(primary: str, role_label: str) -> dict:
        traits = infer_persona_traits(primary, role_label)
        return {
            'seed_layer': 'derived',
            'seed_confidence_tier': 'low',
            'mbti': traits['mbti'],
            'archetype': traits['archetype'],
            'runtime_hooks': traits['runtime_hooks'],
        }

    out = {}
    for actor_id, actor in (state.get('actors', {}) or {}).items():
        if not isinstance(actor, dict) or actor.get('kind') == 'protagonist':
            continue
        primary = sanitize_runtime_name(actor.get('name', '') or (actor.get('aliases') or [''])[0])
        if not primary or looks_like_bad_entity_fragment(primary):
            continue
        out[actor_id] = {
            'entity_id': actor_id,
            'actor_id': actor_id,
            'primary_label': primary,
            'aliases': actor.get('aliases', []),
            'role_label': actor.get('identity') or 'actor registry',
            'collective': False,
            'count_hint': None,
            'onstage': actor_id in set((state.get('actor_context_index', {}) or {}).get('active_actor_ids', []) or []),
            'relevant': False,
            'possible_links': [],
            'runtime_state': {
                'status': '当前在场并直接牵动局势' if actor_id in set((state.get('actor_context_index', {}) or {}).get('active_actor_ids', []) or []) else '当前未必在场，但仍与局势直接相关',
                'attitude_to_protagonist': '待确认',
                'relation_to_scene': actor.get('personality') or actor.get('appearance') or '长期角色账本中的稳定人物',
            },
            'persona': {
                'seed_layer': 'actor_registry',
                'seed_confidence_tier': 'medium',
                'mbti': '待确认',
                'archetype': actor.get('identity') or '待确认',
                'runtime_hooks': {
                    'decision_style': actor.get('personality') or '待确认',
                    'social_strategy': '待确认',
                    'conflict_style': '待确认',
                    'speech_rhythm': '待确认',
                    'stress_response': '待确认',
                },
            },
            'debug': {
                'source': 'actor_registry',
                'last_updated_at': None,
                'reasons': [],
            },
        }

    for entity in scene_entities:
        primary = sanitize_runtime_name(entity.get('primary_label', ''))
        if not primary or looks_like_bad_entity_fragment(primary):
            continue
        persona = persona_by_name.get(primary, {})
        hooks = persona.get('persona_seed', {}).get('runtime_hooks', {})
        fallback = fallback_persona(primary, entity.get('role_label', '待确认'))
        out[entity.get('entity_id')] = {
            'entity_id': entity.get('entity_id'),
            'primary_label': primary,
            'aliases': entity.get('aliases', []),
            'role_label': entity.get('role_label', '待确认'),
            'collective': bool(entity.get('collective')),
            'count_hint': entity.get('count_hint'),
            'onstage': primary in onstage,
            'relevant': primary in relevant,
            'possible_links': [entity.get('possible_link')] if entity.get('possible_link') else [],
            'runtime_state': {
                'status': '当前在场并直接牵动局势' if primary in onstage else '当前未必在场，但仍与局势直接相关',
                'attitude_to_protagonist': '待确认',
                'relation_to_scene': '当前在场并直接牵动局势' if primary in onstage else '仍可能影响下一轮判断或后续回流',
            },
            'persona': {
                'seed_layer': persona.get('seed_layer', fallback['seed_layer']),
                'seed_confidence_tier': persona.get('seed_confidence_tier', fallback['seed_confidence_tier']),
                'mbti': persona.get('persona_seed', {}).get('mbti', fallback['mbti']),
                'archetype': persona.get('persona_seed', {}).get('archetype', fallback['archetype']),
                'runtime_hooks': {
                    'decision_style': hooks.get('decision_style', {}).get('value', fallback['runtime_hooks']['decision_style']['value']),
                    'social_strategy': hooks.get('social_strategy', {}).get('value', fallback['runtime_hooks']['social_strategy']['value']),
                    'conflict_style': hooks.get('conflict_style', {}).get('value', fallback['runtime_hooks']['conflict_style']['value']),
                    'speech_rhythm': hooks.get('speech_rhythm', {}).get('value', fallback['runtime_hooks']['speech_rhythm']['value']),
                    'stress_response': hooks.get('stress_response', {}).get('value', fallback['runtime_hooks']['stress_response']['value']),
                }
            },
            'debug': {
                'source': persona.get('seed_layer', fallback['seed_layer']),
                'last_updated_at': persona.get('source_window', {}).get('last_evaluated_at'),
                'reasons': persona.get('importance', {}).get('reason', []),
            }
        }
    return out


def seed_default_state(session_id: str) -> dict:
    return {
        'session_id': session_id,
        'time': '待确认',
        'location': '待确认',
        'main_event': '待确认',
        'onstage_npcs': [],
        'relevant_npcs': [],
        'immediate_goal': '待确认',
        'carryover_signals': [],
        'immediate_risks': [],
        'carryover_clues': [],
        'tracked_objects': [],
        'possession_state': [],
        'object_visibility': [],
        'actors': {
            'protagonist': {
                'actor_id': 'protagonist',
                'kind': 'protagonist',
                'name': '主角',
                'aliases': ['你', '主角'],
                'personality': '',
                'appearance': '',
                'identity': '主角',
                'created_turn': 1,
            },
        },
        'actor_context_index': {
            'active_actor_ids': ['protagonist'],
            'archived_actor_ids': [],
            'last_mentioned_turn': {'protagonist': 1},
            'archive_after_quiet_turns': 12,
        },
        'knowledge_records': [],
    }


def load_meta(session_id: str) -> dict:
    data = _load_json(session_paths(session_id)['meta'], {'last_turn_id': 0, 'processed_client_turn_ids': {}})
    if not isinstance(data, dict):
        data = {}
    data.setdefault('last_turn_id', 0)
    data.setdefault('processed_client_turn_ids', {})
    return data


def web_runtime_settings() -> dict:
    web = load_runtime_web_config().get('web', {})
    if not isinstance(web, dict):
        web = {}
    return {
        'default_debug': bool(web.get('default_debug', False)),
        'history_page_size': int(web.get('history_page_size', 80) or 80),
        'show_state_panel': bool(web.get('show_state_panel', True)),
        'show_debug_panel': bool(web.get('show_debug_panel', False)),
    }


MAX_IDEMPOTENCY_CACHE = 50


def save_meta(session_id: str, meta: dict) -> None:
    with _STORE_LOCK:
        cache = meta.get('processed_client_turn_ids', {})
        if isinstance(cache, dict) and len(cache) > MAX_IDEMPOTENCY_CACHE:
            sorted_keys = sorted(cache.keys())
            for key in sorted_keys[:len(cache) - MAX_IDEMPOTENCY_CACHE]:
                del cache[key]
        path = session_paths(session_id)['meta']
        _atomic_write_json(path, meta)
