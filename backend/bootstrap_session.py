#!/usr/bin/env python3
import json
from pathlib import Path

from runtime_store import ensure_session_dirs, load_canon, load_context, load_state, load_summary, save_canon, save_context, save_state, seed_default_state, session_paths
from state_bridge import parse_root_state_markdown
from paths import APP_ROOT, SHARED_ROOT, resolve_layered_source, resolve_source_key

ROOT = SHARED_ROOT
RUNTIME_WEB = APP_ROOT
CONFIG = RUNTIME_WEB / 'config' / 'runtime.json'


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def load_runtime_config() -> dict:
    return read_json(CONFIG)


def resolve_source(path_str: str) -> Path:
    return resolve_layered_source(path_str)


def resolve_source_from_config(sources: dict, key: str, fallback_source_key: str) -> Path:
    configured = sources.get(key)
    if configured:
        return resolve_source(configured)
    return resolve_source_key(fallback_source_key)


def bootstrap_session(session_id: str) -> dict:
    ensure_session_dirs(session_id)
    cfg = load_runtime_config()
    sources = cfg.get('sources', {})
    existing_context = load_context(session_id)
    paths = session_paths(session_id)

    replay_bootstrap = existing_context.get('replay_bootstrap') if isinstance(existing_context, dict) else None
    if replay_bootstrap in {'empty', 'session'}:
        return {
            'session_id': session_id,
            'bootstrapped': False,
            'context': existing_context,
            'state': load_state(session_id),
            'summary': load_summary(session_id),
        }

    canon = load_canon(session_id)
    existing = bool(existing_context) and paths['canon'].exists() and paths['state'].exists()

    if not existing:
        root_canon = read_text(resolve_source_from_config(sources, 'canon', 'character.canon'))
        base_state_text = read_text(resolve_source_from_config(sources, 'state', 'character.state'))

        save_canon(session_id, root_canon)

        state = parse_root_state_markdown(base_state_text, session_id) if base_state_text.strip() else seed_default_state(session_id)
        if not state.get('main_event') or state.get('main_event') == '待确认':
            state['main_event'] = '开始新的剧情会话。'
        if not state.get('scene_core') or state.get('scene_core') == '待确认':
            state['scene_core'] = '等待第一轮输入来确立当前场景。'
        save_state(session_id, state)

        save_context(session_id, {
            'runtime_rules_path': sources.get('runtime_rules'),
            'character_core_path': sources.get('character_core'),
            'lorebook_path': sources.get('lorebook'),
            'active_preset': sources.get('active_preset'),
            'initialized_from_root_state': bool(base_state_text),
            'bootstrapped_time': state.get('time', '待确认'),
            'bootstrapped_location': state.get('location', '待确认'),
            'bootstrapped_main_event': state.get('main_event', '待确认'),
        })

    return {
        'session_id': session_id,
        'bootstrapped': not existing,
        'context': load_context(session_id),
        'state': load_state(session_id),
        'summary': load_summary(session_id),
    }
