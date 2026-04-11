#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from bootstrap_session import bootstrap_session, load_runtime_config, resolve_source, read_text, resolve_source_from_config
from runtime_store import append_history, build_state_snapshot, save_canon, save_context, save_meta, save_state, save_summary, seed_default_state, session_paths
from state_bridge import parse_root_state_markdown


ROOT = Path(__file__).resolve().parents[1]


def _slug(text: str) -> str:
    value = str(text or '').strip()
    if not value:
        return 'imported-chat'
    value = re.sub(r'[\\/:\s]+', '-', value)
    value = re.sub(r'[^0-9A-Za-z_\-\u4e00-\u9fff]+', '', value)
    return value.strip('-') or 'imported-chat'


def _parse_send_date(value: str | None, fallback_ms: int) -> int:
    text = str(value or '').strip()
    if not text:
        return fallback_ms
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except Exception:
        return fallback_ms
    return int(dt.timestamp() * 1000)


def _normalize_content(text: str) -> str:
    return str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip()


def _load_jsonl(path: Path) -> list[dict]:
    items: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except Exception as err:
            raise RuntimeError(f'invalid json on line {line_no}: {err}') from err
        if not isinstance(item, dict):
            continue
        items.append(item)
    return items


def _split_metadata(items: list[dict]) -> tuple[dict, list[dict]]:
    if not items:
        return {}, []
    first = items[0]
    if 'chat_metadata' in first:
        return first, items[1:]
    return {}, items


def _coerce_history_items(chat_items: list[dict]) -> tuple[list[dict], dict]:
    history: list[dict] = []
    stats = {
        'source_message_count': 0,
        'imported_message_count': 0,
        'user_count': 0,
        'assistant_count': 0,
        'system_count': 0,
        'skipped_empty': 0,
        'assistant_swipe_count': 0,
    }

    base_ts = int(datetime.now().timestamp() * 1000)
    for idx, item in enumerate(chat_items):
        stats['source_message_count'] += 1
        if item.get('is_system'):
            stats['system_count'] += 1
            continue
        content = _normalize_content(item.get('mes', ''))
        if not content:
            stats['skipped_empty'] += 1
            continue
        role = 'user' if item.get('is_user') else 'assistant'
        if role == 'user':
            stats['user_count'] += 1
        else:
            stats['assistant_count'] += 1
        if 'swipe_id' in item:
            stats['assistant_swipe_count'] += 1
        ts = _parse_send_date(item.get('send_date'), base_ts + idx)
        history.append({
            'ts': ts,
            'role': role,
            'content': content,
            'source': 'sillytavern-import',
            'source_name': str(item.get('name', '') or '').strip(),
        })
        stats['imported_message_count'] += 1
    return history, stats


def _pick_name(*values: str | None) -> str | None:
    for value in values:
        text = str(value or '').strip()
        if not text:
            continue
        if text.lower() in {'unused', 'unknown', 'null', 'none'}:
            continue
        return text
    return None


def _infer_chat_names(metadata: dict, chat_items: list[dict]) -> tuple[str | None, str | None]:
    metadata_character = _pick_name(metadata.get('character_name'))
    metadata_user = _pick_name(metadata.get('user_name'))
    first_assistant = None
    first_user = None
    for item in chat_items:
        if 'chat_metadata' in item:
            continue
        name = _pick_name(item.get('name'))
        if item.get('is_user'):
            if name and first_user is None:
                first_user = name
        else:
            if name and first_assistant is None:
                first_assistant = name
        if first_assistant and first_user:
            break
    return metadata_character or first_assistant, metadata_user or first_user


def _bootstrap_import_session(session_id: str, *, source_path: Path, metadata: dict, character_name: str | None, user_name: str | None) -> dict:
    cfg = load_runtime_config()
    sources = cfg.get('sources', {})
    root_canon = read_text(resolve_source_from_config(sources, 'canon', 'character.canon'))
    root_summary = read_text(resolve_source_from_config(sources, 'summary', 'character.summary'))
    base_state_text = read_text(resolve_source_from_config(sources, 'state', 'character.state'))

    save_canon(session_id, root_canon if root_canon.strip() else '# Canon\n\n## 世界长期事实\n- 待确认\n')
    save_summary(session_id, root_summary if root_summary.strip() else '# Summary\n\n## 最近阶段摘要\n- 暂无\n')

    state = parse_root_state_markdown(base_state_text, session_id) if base_state_text.strip() else seed_default_state(session_id)
    if not state.get('main_event') or state.get('main_event') == '待确认':
        state['main_event'] = '从导入聊天记录继续推进剧情。'
    if not state.get('scene_core') or state.get('scene_core') == '待确认':
        state['scene_core'] = '当前会话由 SillyTavern 聊天记录导入，等待后续重建当前局势。'
    save_state(session_id, state)

    context = {
        'runtime_rules_path': sources.get('runtime_rules'),
        'character_core_path': sources.get('character_core'),
        'lorebook_path': sources.get('lorebook'),
        'active_preset': sources.get('active_preset'),
        'import_source': 'sillytavern-jsonl',
        'imported_chat_path': str(source_path),
        'imported_character_name': character_name,
        'imported_user_name': user_name,
        'replay_bootstrap': 'session',
    }
    save_context(session_id, context)
    save_meta(session_id, {'last_turn_id': 0, 'processed_client_turn_ids': {}})
    return state


def import_sillytavern_jsonl(source_path: Path, *, target_session: str | None = None) -> dict:
    items = _load_jsonl(source_path)
    metadata, chat_items = _split_metadata(items)
    inferred_character_name, inferred_user_name = _infer_chat_names(metadata, chat_items)
    history_items, stats = _coerce_history_items(chat_items)
    if not history_items:
        raise RuntimeError('no importable chat messages found')

    suggested_base = metadata.get('character_name') or source_path.stem
    session_id = target_session or f"import-{_slug(suggested_base)}"
    raw_session_dir = ROOT / 'sessions' / session_id
    if raw_session_dir.exists() and any(raw_session_dir.iterdir()):
        raise RuntimeError(f'target session already exists and is not empty: {session_id}')
    paths = session_paths(session_id)

    initial_state = _bootstrap_import_session(
        session_id,
        source_path=source_path,
        metadata=metadata,
        character_name=inferred_character_name,
        user_name=inferred_user_name,
    )
    for item in history_items:
        append_history(session_id, item)

    import_dir = paths['session_dir'] / 'imports'
    import_dir.mkdir(parents=True, exist_ok=True)
    source_copy_path = import_dir / source_path.name
    source_copy_path.write_bytes(source_path.read_bytes())
    metadata_sidecar_path = import_dir / 'sillytavern-chat-metadata.json'
    metadata_sidecar_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    report = {
        'import_version': 1,
        'source_path': str(source_path),
        'source_copy_path': str(source_copy_path),
        'metadata_sidecar_path': str(metadata_sidecar_path),
        'target_session': session_id,
        'character_name': inferred_character_name,
        'user_name': inferred_user_name,
        'chat_metadata_keys': sorted((metadata.get('chat_metadata') or {}).keys()) if isinstance(metadata.get('chat_metadata'), dict) else [],
        'stats': stats,
        'initial_state_snapshot': build_state_snapshot(initial_state),
    }
    report_path = import_dir / 'sillytavern-import-report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='Import a SillyTavern JSONL chat log into a Threadloom session')
    parser.add_argument('--source', required=True, help='Path to a SillyTavern .jsonl export')
    parser.add_argument('--target-session', help='Optional target session id')
    args = parser.parse_args()

    source_path = Path(args.source)
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    if not source_path.exists():
        raise SystemExit(f'source file not found: {source_path}')

    report = import_sillytavern_jsonl(source_path, target_session=args.target_session)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
