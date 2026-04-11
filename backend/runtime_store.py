#!/usr/bin/env python3
import json
import re
from pathlib import Path

try:
    from .persona_runtime import infer_persona_traits
    from .name_sanitizer import sanitize_runtime_name
    from .paths import APP_ROOT, SHARED_ROOT, character_npcs_root, character_runtime_persona_root, character_source_root, current_sessions_root, resolve_layered_source, resolve_session_dir, shared_path
except ImportError:
    from persona_runtime import infer_persona_traits
    from name_sanitizer import sanitize_runtime_name
    from paths import APP_ROOT, SHARED_ROOT, character_npcs_root, character_runtime_persona_root, character_source_root, current_sessions_root, resolve_layered_source, resolve_session_dir, shared_path

ROOT = SHARED_ROOT
RUNTIME_WEB = APP_ROOT
SESSIONS_DIR = current_sessions_root()
CONFIG = RUNTIME_WEB / 'config' / 'runtime.json'


def character_data_path() -> Path:
    layered = character_source_root() / 'character-data.json'
    if layered.exists():
        return layered
    return shared_path('character', 'character-data.json')


def root_persona_dir() -> Path:
    layered = character_runtime_persona_root()
    if layered.exists():
        return layered
    return shared_path('runtime', 'persona-seeds')


def character_npc_profiles_dir() -> Path:
    layered = character_npcs_root()
    if layered.exists():
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


def resolve_character_cover_path() -> Path | None:
    small_cover = RUNTIME_WEB / 'frontend' / 'character-cover-small.png'
    if small_cover.exists():
        return small_cover
    data = _read_json_file(character_data_path())
    notes = str(data.get('notes', '') or '')
    match = re.search(r'character/imported/([^.]+)\.raw-card\.json', notes)
    candidates: list[Path] = []
    if match:
        stem = match.group(1)
        for ext in ('.png', '.jpg', '.jpeg', '.webp'):
            candidates.append(shared_path('角色卡', f'{stem}{ext}'))
    role_cards = shared_path('角色卡')
    candidates.extend(sorted(role_cards.glob('*')) if role_cards.exists() else [])
    for path in candidates:
        if path.is_file() and path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
            return path
    return None


def load_character_card_meta() -> dict:
    data = _read_json_file(character_data_path())
    core = data.get('coreDescription', {}) if isinstance(data.get('coreDescription', {}), dict) else {}
    cover_path = resolve_character_cover_path()
    return {
        'name': str(data.get('name', '') or core.get('title', '') or '未命名角色卡').strip(),
        'title': str(core.get('title', '') or data.get('name', '') or '未命名角色卡').strip(),
        'subtitle': str(core.get('tagline', '') or data.get('role', '') or '').strip(),
        'summary': str(core.get('summary', '') or '').strip(),
        'cover_url': '/character-cover' if cover_path else None,
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
        'context': session_dir / 'context.json',
        'meta': session_dir / 'meta.json',
    }


def load_history(session_id: str) -> list:
    path = session_paths(session_id)['history']
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            items.append(json.loads(s))
        except Exception:
            continue
    return items


def is_complete_assistant_item(item: dict) -> bool:
    if item.get('role') != 'assistant':
        return True
    return item.get('completion_status', 'complete') == 'complete'


def append_history(session_id: str, item: dict) -> None:
    path = session_paths(session_id)['history']
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(item, ensure_ascii=False) + '\n')


def save_history(session_id: str, items: list[dict]) -> None:
    path = session_paths(session_id)['history']
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


def load_state(session_id: str) -> dict:
    path = session_paths(session_id)['state']
    if not path.exists():
        return {
            'time': '待确认',
            'location': '待确认',
            'main_event': '待确认',
            'scene_core': '待确认',
            'onstage_npcs': [],
            'relevant_npcs': [],
            'immediate_goal': '待确认',
            'immediate_risks': [],
            'carryover_clues': [],
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


def save_continuity_hints(session_id: str, items: list[dict]) -> None:
    path = session_paths(session_id)['continuity_hints']
    payload = {'entries': items}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_summary(session_id: str) -> str:
    path = session_paths(session_id)['summary']
    return path.read_text(encoding='utf-8') if path.exists() else '# Summary\n\n## 最近阶段摘要\n- 暂无\n'


def save_summary(session_id: str, text: str) -> None:
    path = session_paths(session_id)['summary']
    path.write_text(text, encoding='utf-8')


def load_canon(session_id: str) -> str:
    path = session_paths(session_id)['canon']
    return path.read_text(encoding='utf-8') if path.exists() else '# Canon\n\n## 世界长期事实\n- 待确认\n'


def save_canon(session_id: str, text: str) -> None:
    path = session_paths(session_id)['canon']
    path.write_text(text, encoding='utf-8')


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
    path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def save_state(session_id: str, state: dict) -> None:
    path = session_paths(session_id)['state']
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def trace_path(session_id: str, turn_id: str) -> Path:
    paths = session_paths(session_id)
    trace_dir = paths['trace_dir']
    trace_dir.mkdir(parents=True, exist_ok=True)
    safe_turn_id = str(turn_id or 'turn-unknown').strip() or 'turn-unknown'
    return trace_dir / f'{safe_turn_id}.json'


def save_turn_trace(session_id: str, turn_id: str, trace: dict) -> Path:
    path = trace_path(session_id, turn_id)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def load_turn_trace(session_id: str, turn_id: str) -> dict:
    path = trace_path(session_id, turn_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def build_state_snapshot(state: dict) -> dict:
    scene_entities = state.get('scene_entities', []) if isinstance(state.get('scene_entities', []), list) else []
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
        'scene_core': state.get('scene_core', '待确认'),
        'scene_entities': scene_entities,
        'onstage_entities': build_named_entities(state.get('onstage_npcs', [])),
        'relevant_entities': build_named_entities(state.get('relevant_npcs', [])),
        'active_threads': state.get('active_threads', []),
        'important_npcs': state.get('important_npcs', []),
        'onstage_npcs': state.get('onstage_npcs', []),
        'relevant_npcs': state.get('relevant_npcs', []),
        'immediate_goal': state.get('immediate_goal', '待确认'),
        'immediate_risks': state.get('immediate_risks', []),
        'carryover_clues': state.get('carryover_clues', []),
        'tracked_objects': state.get('tracked_objects', []),
        'possession_state': state.get('possession_state', []),
        'object_visibility': state.get('object_visibility', []),
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
            (directory / filename).write_text(json.dumps(seed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


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
    path.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
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
    for entity in scene_entities:
        primary = sanitize_runtime_name(entity.get('primary_label', ''))
        if not primary:
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
        'scene_core': '待确认',
        'onstage_npcs': [],
        'relevant_npcs': [],
        'immediate_goal': '待确认',
        'immediate_risks': [],
        'carryover_clues': [],
        'tracked_objects': [],
        'possession_state': [],
        'object_visibility': [],
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


def save_meta(session_id: str, meta: dict) -> None:
    path = session_paths(session_id)['meta']
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
