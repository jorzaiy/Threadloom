#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import re
from copy import deepcopy


logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """去除 LLM 回复中的 markdown 代码围栏。"""
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```\w*\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()

try:
    from .llm_manager import call_role_llm
    from .runtime_store import session_paths
    from .name_sanitizer import sanitize_runtime_name
except ImportError:
    from llm_manager import call_role_llm
    from runtime_store import session_paths
    from name_sanitizer import sanitize_runtime_name


NPC_BOOTSTRAP_SYSTEM = """你是 RP 人物连续性整理器。

任务：
- 按时间顺序读取一段历史窗口
- 把同一人物的不同称呼收拢为同一个 canonical entity
- 只保留“像人物”的 actor，不要把抽象词、势力词、地点词、机制词当作人物
- 优先输出在当前窗口中反复行动、被追查、被讨论、被观察、与他人发生稳定关系的人

只输出 JSON：
{
  "entities": [
    {
      "canonical_name": "...",
      "aliases": ["..."],
      "role_label": "...",
      "faction": "...",
      "stability": "low|medium|high",
      "notes": "一句非常短的说明"
    }
  ]
}
"""


def _registry_path(session_id: str):
    return session_paths(session_id)['memory_dir'] / 'npc_registry.json'


def load_npc_registry(session_id: str) -> dict:
    path = _registry_path(session_id)
    if not path.exists():
        return {'version': 1, 'processed_pairs': 0, 'entities': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error('NPC registry 加载失败 (%s): %s', session_id, e)
        data = {}
    data.setdefault('version', 1)
    data.setdefault('processed_pairs', 0)
    data.setdefault('entities', [])
    return data


def save_npc_registry(session_id: str, registry: dict) -> None:
    from runtime_store import _atomic_write_json
    path = _registry_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, registry)


def _turn_pairs(items: list[dict]) -> list[tuple[dict, dict]]:
    pairs: list[tuple[dict, dict]] = []
    current_user = None
    for item in items or []:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        if role == 'user':
            current_user = item
        elif role == 'assistant' and current_user is not None:
            pairs.append((current_user, item))
            current_user = None
    return pairs


def _short(text: str, limit: int = 120) -> str:
    value = ' '.join(str(text or '').split()).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + '...'


def _registry_summary(registry: dict) -> list[dict]:
    out = []
    for item in (registry.get('entities', []) or [])[:20]:
        if not isinstance(item, dict):
            continue
        out.append({
            'canonical_name': item.get('canonical_name', ''),
            'aliases': item.get('aliases', []),
            'role_label': item.get('role_label', ''),
            'faction': item.get('faction', ''),
            'stability': item.get('stability', 'low'),
        })
    return out


def _build_user_prompt(registry: dict, window_pairs: list[tuple[dict, dict]], start_idx: int) -> str:
    payload = {
        'current_registry': _registry_summary(registry),
        'window_index': start_idx,
        'history_pairs': [
            {
                'user': str(user_item.get('content', '') or ''),
                'assistant': str(assistant_item.get('content', '') or ''),
            }
            for user_item, assistant_item in window_pairs
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_entities(items) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        canonical = sanitize_runtime_name(item.get('canonical_name', ''))
        if not canonical or canonical in seen:
            continue
        aliases = []
        for alias in (item.get('aliases', []) or []):
            alias_text = sanitize_runtime_name(alias)
            if alias_text and alias_text not in aliases:
                aliases.append(alias_text)
        if canonical not in aliases:
            aliases.insert(0, canonical)
        out.append({
            'canonical_name': canonical,
            'aliases': aliases[:12],
            'role_label': str(item.get('role_label', '') or '待确认').strip() or '待确认',
            'faction': str(item.get('faction', '') or '待确认').strip() or '待确认',
            'stability': str(item.get('stability', '') or 'low').strip() or 'low',
            'notes': _short(item.get('notes', ''), limit=200),
        })
        seen.add(canonical)
    return out


def _merge_registry_entities(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = {str(item.get('canonical_name', '') or '').strip(): deepcopy(item) for item in existing if isinstance(item, dict) and item.get('canonical_name')}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        canonical = str(item.get('canonical_name', '') or '').strip()
        aliases = {sanitize_runtime_name(alias) for alias in (item.get('aliases', []) or []) if sanitize_runtime_name(alias)}
        matched_key = canonical if canonical in merged else ''
        if not matched_key:
            for key, prev in merged.items():
                prev_aliases = {sanitize_runtime_name(alias) for alias in (prev.get('aliases', []) or []) if sanitize_runtime_name(alias)}
                if canonical in prev_aliases or key in aliases or prev_aliases & aliases:
                    matched_key = key
                    break
        if matched_key:
            prev = merged[matched_key]
            all_aliases = {sanitize_runtime_name(alias) for alias in (prev.get('aliases', []) or []) if sanitize_runtime_name(alias)} | aliases | {matched_key, canonical}
            prev['aliases'] = sorted(all_aliases)
            if prev.get('role_label') in {'', '待确认'} and item.get('role_label'):
                prev['role_label'] = item['role_label']
            if prev.get('faction') in {'', '待确认'} and item.get('faction'):
                prev['faction'] = item['faction']
            if item.get('stability') == 'high':
                prev['stability'] = 'high'
            elif item.get('stability') == 'medium' and prev.get('stability') != 'high':
                prev['stability'] = 'medium'
            if not prev.get('notes') and item.get('notes'):
                prev['notes'] = item['notes']
        else:
            merged[canonical] = deepcopy(item)
    return list(merged.values())


def _heuristic_registry(registry: dict, window_pairs: list[tuple[dict, dict]]) -> list[dict]:
    entities = list(registry.get('entities', []) or [])
    existing = {sanitize_runtime_name(item.get('canonical_name', '')) for item in entities if isinstance(item, dict)}
    text = '\n'.join(
        str(assistant_item.get('content', '') or '')
        for _user_item, assistant_item in window_pairs
    )
    patterns = [
        (r'瘦掌柜', '掌柜', '客栈掌柜'),
        (r'掌柜', '掌柜', '客栈掌柜'),
        (r'小二', '小二', '跑堂小二'),
        (r'借宿者', '借宿者', '待确认'),
        (r'深衣青年', '深衣青年', '待确认'),
        (r'高个皂衣人', '高个皂衣人', '镇北司皂衣人'),
        (r'皂衣人', '皂衣人', '镇北司皂衣人'),
    ]
    for pattern, canonical, role_label in patterns:
        if not re.search(pattern, text):
            continue
        if canonical in existing:
            continue
        entities.append({
            'canonical_name': canonical,
            'aliases': [canonical],
            'role_label': role_label,
            'faction': '待确认',
            'stability': 'low',
            'notes': 'heuristic bootstrap',
        })
        existing.add(canonical)
    return entities


def ensure_npc_registry(session_id: str, history: list[dict], *, window_size: int = 10, force: bool = False) -> dict:
    pairs = _turn_pairs(history)
    registry = load_npc_registry(session_id)
    processed_pairs = 0 if force else int(registry.get('processed_pairs', 0) or 0)
    if not force and processed_pairs >= len(pairs):
        return registry

    entities = list(registry.get('entities', []) or []) if not force else []
    for start in range(processed_pairs, len(pairs), window_size):
        window_pairs = pairs[start:start + window_size]
        if not window_pairs:
            continue
        user_prompt = _build_user_prompt({'entities': entities}, window_pairs, start + 1)
        try:
            reply, _usage = call_role_llm('state_keeper_candidate', NPC_BOOTSTRAP_SYSTEM, user_prompt)
            payload = json.loads(_strip_code_fences(reply))
            incoming = _normalize_entities(payload.get('entities', []))
        except Exception:
            incoming = _heuristic_registry({'entities': entities}, window_pairs)
        entities = _merge_registry_entities(entities, incoming)
        processed_pairs = start + len(window_pairs)

    registry = {
        'version': 1,
        'processed_pairs': processed_pairs,
        'entities': entities,
    }
    save_npc_registry(session_id, registry)
    return registry


def canonicalize_name(name: str, registry: dict) -> str:
    text = sanitize_runtime_name(name)
    if not text:
        return ''
    for item in (registry.get('entities', []) or []):
        if not isinstance(item, dict):
            continue
        canonical = sanitize_runtime_name(item.get('canonical_name', ''))
        aliases = {sanitize_runtime_name(alias) for alias in (item.get('aliases', []) or []) if sanitize_runtime_name(alias)}
        if text == canonical or text in aliases:
            return canonical or text
    return text


def registry_summary_lines(registry: dict, limit: int = 6) -> str:
    lines = []
    for item in (registry.get('entities', []) or [])[:limit]:
        if not isinstance(item, dict):
            continue
        name = sanitize_runtime_name(item.get('canonical_name', ''))
        if not name:
            continue
        role = str(item.get('role_label', '') or '待确认').strip() or '待确认'
        lines.append(f"- {name} / {role}")
    return '\n'.join(lines) if lines else '暂无'
