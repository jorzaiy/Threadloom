#!/usr/bin/env python3
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

try:
    from .character_assets import resolve_character_cover_path
    from .persona_runtime import infer_persona_traits
    from .name_sanitizer import sanitize_runtime_name, looks_like_bad_entity_fragment
    from .paths import APP_ROOT, SHARED_ROOT, active_character_id, active_user_label, character_npcs_root, character_runtime_persona_root, character_source_root, is_character_override_active, is_multi_user_request_context, normalize_turn_id, resolve_layered_source, resolve_session_dir, shared_path
except ImportError:
    from character_assets import resolve_character_cover_path
    from persona_runtime import infer_persona_traits
    from name_sanitizer import sanitize_runtime_name, looks_like_bad_entity_fragment
    from paths import APP_ROOT, SHARED_ROOT, active_character_id, active_user_label, character_npcs_root, character_runtime_persona_root, character_source_root, is_character_override_active, is_multi_user_request_context, normalize_turn_id, resolve_layered_source, resolve_session_dir, shared_path

ROOT = SHARED_ROOT
RUNTIME_WEB = APP_ROOT
CONFIG = RUNTIME_WEB / 'config' / 'runtime.json'


# ---------------------------------------------------------------------------
# 原子写入：先写临时文件再 rename，防止中途中断导致文件损坏
# ---------------------------------------------------------------------------
def _atomic_write_text(path: Path, content: str, encoding: str = 'utf-8') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, data, *, indent: int = 2) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent) + '\n')

_history_cache: dict[str, tuple[float, list]] = {}


def _history_cache_key(path: Path) -> str:
    return str(path.resolve(strict=False))


def invalidate_history_cache(session_id: str | None = None) -> None:
    """Clear cached history. Call after appending to history."""
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
    if not CONFIG.exists():
        return {}
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


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


def load_history(session_id: str) -> list:
    path = session_paths(session_id)['history']
    if not path.exists():
        return []
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    cache_key = _history_cache_key(path)
    cached = _history_cache.get(cache_key)
    if cached and cached[0] == mtime:
        return list(cached[1])
    items = []
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            items.append(json.loads(s))
        except Exception:
            continue
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
    items = load_history(session_id)
    if isinstance(item, dict) and item.get('role') == 'user':
        while items and isinstance(items[-1], dict) and items[-1].get('role') == 'assistant' and not is_complete_assistant_item(items[-1]):
            items.pop()
            if items and isinstance(items[-1], dict) and items[-1].get('role') == 'user':
                items.pop()
    items.append(item)
    save_history(session_id, items)


def save_history(session_id: str, items: list[dict]) -> None:
    path = session_paths(session_id)['history']
    content = ''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in (items or []))
    _atomic_write_text(path, content)
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
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def load_continuity_hints(session_id: str) -> list:
    path = session_paths(session_id)['continuity_hints']
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return []
    if isinstance(data, dict):
        items = data.get('entries', [])
        return items if isinstance(items, list) else []
    return data if isinstance(data, list) else []


def load_summary_chunks(session_id: str) -> dict:
    path = session_paths(session_id)['summary_chunks']
    if not path.exists():
        return {'version': 1, 'chunks': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {'version': 1, 'chunks': []}
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
    path = session_paths(session_id)['event_summaries']
    if not path.exists():
        return {'version': 1, 'items': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {'version': 1, 'items': []}
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
    payload = load_event_summaries(session_id)
    items = list(payload.get('items', []) or [])
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
    path = session_paths(session_id)['context']
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


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
    path = _trace_file_path(session_id, turn_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


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
        'immediate_goal': state.get('immediate_goal', '待确认'),
        'carryover_signals': state.get('carryover_signals', []),
        'immediate_risks': state.get('immediate_risks', []),
        'carryover_clues': state.get('carryover_clues', []),
        'tracked_objects': state.get('tracked_objects', []),
        'possession_state': state.get('possession_state', []),
        'object_visibility': state.get('object_visibility', []),
        'actors': state.get('actors', {}),
        'actor_context_index': state.get('actor_context_index', {}),
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
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
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
    path = session_paths(session_id)['meta']
    if not path.exists():
        return {'last_turn_id': 0, 'processed_client_turn_ids': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
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
    cache = meta.get('processed_client_turn_ids', {})
    if isinstance(cache, dict) and len(cache) > MAX_IDEMPOTENCY_CACHE:
        sorted_keys = sorted(cache.keys())
        for key in sorted_keys[:len(cache) - MAX_IDEMPOTENCY_CACHE]:
            del cache[key]
    path = session_paths(session_id)['meta']
    _atomic_write_json(path, meta)
