#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from bootstrap_session import load_runtime_config, read_text, resolve_source_from_config
from paths import current_session_owner_context, normalize_session_id, reset_active_character_override, resolve_session_dir, set_active_character_override
from runtime_store import append_history, build_state_snapshot, save_canon, save_context, save_meta, save_state, save_summary, seed_default_state, session_paths
from state_bridge import parse_root_state_markdown


ROOT = Path(__file__).resolve().parents[1]
HTML_COMMENT_RE = re.compile(r'<!--.*?-->', re.S)
USER_INPUT_BLOCK_RE = re.compile(r'<本轮用户输入>\s*(.*?)\s*</本轮用户输入>', re.S)
CONTENT_BLOCK_RE = re.compile(r'<content>\s*(.*?)\s*</content>', re.S | re.I)
RECALL_TAG_RE = re.compile(r'<recall>.*?</recall>', re.S | re.I)
XML_TAG_RE = re.compile(r'</?[^>\n]+>')
TERMINAL_BLOCK_RE = re.compile(r'^\s*【[^】]{0,20}(?:终端|状态栏)[^】]*】.*?(?:\n\s*\*{4,}.*?){0,1}', re.S)
INLINE_TERMINAL_HEADER_RE = re.compile(r'^\s*[\u4e00-\u9fffA-Za-z·0-9\-]+(?:终端|状态栏)?·\d{1,2}:\d{2}\s*(?:AM|PM)?\s*$', re.M)


def _slug(text: str) -> str:
    value = str(text or '').strip()
    if not value:
        return 'imported-chat'
    value = re.sub(r'[\\/:\s]+', '-', value)
    value = re.sub(r'[^0-9A-Za-z_\-\u4e00-\u9fff·]+', '', value)
    return value.strip('-') or 'imported-chat'


def _parse_send_date(value: str | None, fallback_ms: int) -> int:
    text = str(value or '').strip()
    if not text:
        return fallback_ms
    iso_candidate = text.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(iso_candidate)
    except Exception:
        dt = None
    if dt is None:
        for pattern in (
            '%B %d, %Y %I:%M%p',
            '%B %d, %Y %I:%M %p',
            '%b %d, %Y %I:%M%p',
            '%b %d, %Y %I:%M %p',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
        ):
            try:
                dt = datetime.strptime(text, pattern)
                break
            except Exception:
                continue
    if dt is None:
        return fallback_ms
    return int(dt.timestamp() * 1000)


def _strip_status_panel(text: str) -> str:
    lines = str(text or '').splitlines()
    if not lines:
        return ''
    start_idx = None
    end_idx = None
    for idx, line in enumerate(lines[:20]):
        if line.strip() == '******':
            if start_idx is None:
                start_idx = idx
            else:
                end_idx = idx
                break
    if start_idx is not None and end_idx is not None and end_idx > start_idx:
        head = '\n'.join(lines[:start_idx]).strip()
        tail = '\n'.join(lines[end_idx + 1:]).strip()
        if head and tail:
            return f'{head}\n\n{tail}'.strip()
        return tail or head
    return '\n'.join(lines).strip()


def _normalize_user_content(text: str) -> str:
    value = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    match = USER_INPUT_BLOCK_RE.search(value)
    if match:
        value = match.group(1)
    value = RECALL_TAG_RE.sub('', value)
    value = re.sub(r'^\s*以下是用户的本轮输入：\s*$', '', value, flags=re.M)
    value = re.sub(r'^\s*<本轮用户输入>\s*$', '', value, flags=re.M)
    value = re.sub(r'^\s*</本轮用户输入>\s*$', '', value, flags=re.M)
    value = HTML_COMMENT_RE.sub('', value)
    value = XML_TAG_RE.sub('', value)
    value = re.sub(r'\n{3,}', '\n\n', value)
    return value.strip()


def _normalize_assistant_content(text: str) -> str:
    value = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    match = CONTENT_BLOCK_RE.search(value)
    if match:
        value = match.group(1)
    value = HTML_COMMENT_RE.sub('', value)
    value = re.sub(r'^\s*[A-Za-z\u4e00-\u9fff]+>\s*$', '', value, flags=re.M)
    value = re.sub(r'^\s*</?think>\s*$', '', value, flags=re.M | re.I)
    value = re.sub(r'^\s*</?content>\s*$', '', value, flags=re.M | re.I)
    value = re.sub(r'^\s*</?Amily2Edit>\s*$', '', value, flags=re.M | re.I)
    value = TERMINAL_BLOCK_RE.sub('', value)
    value = INLINE_TERMINAL_HEADER_RE.sub('', value)
    value = _strip_status_panel(value)
    value = XML_TAG_RE.sub('', value)
    value = re.sub(r'\n{3,}', '\n\n', value)
    return value.strip()


def _normalize_content(text: str, *, is_user: bool) -> str:
    if is_user:
        return _normalize_user_content(text)
    return _normalize_assistant_content(text)


def _looks_like_setup_prompt(text: str) -> bool:
    value = str(text or '').strip()
    if '请设定您的初始资料' in value:
        return True
    required = ('姓名：', '性别：', '身份', '地点', '初始人际')
    return sum(1 for token in required if token in value) >= 4


def _looks_like_setup_answer(text: str) -> bool:
    value = str(text or '').strip()
    required = ('姓名：', '性别：', '身份', '地点')
    return sum(1 for token in required if token in value) >= 4


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
        content = _normalize_content(item.get('mes', ''), is_user=bool(item.get('is_user')))
        if not content:
            stats['skipped_empty'] += 1
            continue
        role = 'user' if item.get('is_user') else 'assistant'
        if role == 'assistant' and _looks_like_setup_prompt(content):
            continue
        if role == 'user' and _looks_like_setup_answer(content):
            continue
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
    session_id = normalize_session_id(session_id)
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
    save_state(session_id, state)

    context = {
        **current_session_owner_context(session_id),
        'runtime_rules_path': sources.get('runtime_rules'),
        'character_core_path': sources.get('character_core'),
        'lorebook_path': sources.get('lorebook'),
        'active_preset': sources.get('active_preset'),
        'import_source': 'sillytavern-jsonl',
        'import_metadata_present': bool(metadata),
        'imported_chat_path': str(source_path),
        'imported_character_name': character_name,
        'imported_user_name': user_name,
        'replay_bootstrap': 'session',
    }
    save_context(session_id, context)
    save_meta(session_id, {'last_turn_id': 0, 'processed_client_turn_ids': {}})
    return state


def import_sillytavern_jsonl(source_path: Path, *, target_session: str | None = None, character_id: str | None = None) -> dict:
    token = set_active_character_override(character_id)
    try:
        items = _load_jsonl(source_path)
        metadata, chat_items = _split_metadata(items)
        inferred_character_name, inferred_user_name = _infer_chat_names(metadata, chat_items)
        history_items, stats = _coerce_history_items(chat_items)
        if not history_items:
            raise RuntimeError('no importable chat messages found')

        suggested_base = metadata.get('character_name') or source_path.stem
        session_id = normalize_session_id(target_session or f"import-{_slug(suggested_base)}")
        raw_session_dir = resolve_session_dir(session_id, create=False)
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
            'source_path': source_path.name,
            'source_copy_path': str(source_copy_path.relative_to(paths['session_dir'])),
            'metadata_sidecar_path': str(metadata_sidecar_path.relative_to(paths['session_dir'])),
            'target_session': session_id,
            'character_id': character_id,
            'character_name': inferred_character_name,
            'user_name': inferred_user_name,
            'chat_metadata_keys': sorted((metadata.get('chat_metadata') or {}).keys()) if isinstance(metadata.get('chat_metadata'), dict) else [],
            'stats': stats,
            'initial_state_snapshot': build_state_snapshot(initial_state),
        }
        report_path = import_dir / 'sillytavern-import-report.json'
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

        return report
    finally:
        reset_active_character_override(token)


def main() -> int:
    parser = argparse.ArgumentParser(description='Import a SillyTavern JSONL chat log into a Threadloom session')
    parser.add_argument('--source', required=True, help='Path to a SillyTavern .jsonl export')
    parser.add_argument('--target-session', help='Optional target session id')
    parser.add_argument('--character-id', help='Target character id / directory name')
    args = parser.parse_args()

    source_path = Path(args.source)
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    if not source_path.exists():
        raise SystemExit(f'source file not found: {source_path}')

    report = import_sillytavern_jsonl(source_path, target_session=args.target_session, character_id=args.character_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_jsonl_from_text(text: str) -> list[dict]:
    """从字符串内容解析 JSONL。"""
    items: list[dict] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except Exception as err:
            raise RuntimeError(f'invalid json on line {line_no}: {err}') from err
        if not isinstance(item, dict):
            continue
        items.append(item)
    return items


def preview_chat_import(content: str, *, expected_character_name: str | None = None) -> dict:
    """预览 JSONL 内容：提取角色名和消息统计，不实际导入。"""
    items = _load_jsonl_from_text(content)
    metadata, chat_items = _split_metadata(items)
    character_name, user_name = _infer_chat_names(metadata, chat_items)
    message_count = sum(1 for item in chat_items if 'chat_metadata' not in item)
    match = True
    if expected_character_name and character_name:
        match = character_name == expected_character_name
    elif expected_character_name and not character_name:
        match = False
    return {
        'inferred_character': character_name,
        'expected_character': expected_character_name or '',
        'user_name': user_name,
        'message_count': message_count,
        'has_metadata': bool(metadata),
        'match': match,
    }


def import_sillytavern_from_content(
    content: str,
    filename: str,
    *,
    target_session: str | None = None,
    character_id: str | None = None,
    expected_character_name: str | None = None,
) -> dict:
    """从文本内容导入 SillyTavern 聊天记录，可选验证角色名。"""
    import tempfile
    source_name = str(filename or '').strip()
    items = _load_jsonl_from_text(content)
    metadata, chat_items = _split_metadata(items)
    inferred_character_name, _ = _infer_chat_names(metadata, chat_items)

    # 角色名验证
    if expected_character_name:
        if not inferred_character_name:
            raise RuntimeError('无法从聊天记录中识别角色名，请确认文件格式正确')
        if inferred_character_name != expected_character_name:
            raise RuntimeError(
                f'聊天记录角色名 "{inferred_character_name}" 与当前角色卡 "{expected_character_name}" 不匹配'
            )

    # 写入临时文件，复用现有逻辑
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False, encoding='utf-8') as f:
        f.write(content)
        tmp_path = Path(f.name)
    try:
        report = import_sillytavern_jsonl(tmp_path, target_session=target_session, character_id=character_id)
    finally:
        tmp_path.unlink(missing_ok=True)
    if source_name:
        report['source_filename'] = Path(source_name).name
    return report


if __name__ == '__main__':
    raise SystemExit(main())
