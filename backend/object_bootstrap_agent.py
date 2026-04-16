#!/usr/bin/env python3
"""物品抽取 bootstrap：启发式提候选 → LLM 判定/分类/去重 → merge 到 object_index。"""
from __future__ import annotations

import json
import re
from copy import deepcopy

try:
    from .llm_manager import call_role_llm
    from .runtime_store import session_paths
    from .name_sanitizer import sanitize_runtime_name
except ImportError:
    from llm_manager import call_role_llm
    from runtime_store import session_paths
    from name_sanitizer import sanitize_runtime_name


OBJECT_CLASSIFY_SYSTEM = """你是 RP 物品连续性整理器。

任务：
- 对候选物件列表做判定：哪些是可持续追踪的物件（如武器、信物、书信、地图、药品等）
- 排除：一次性消耗品、货币、抽象概念、动作词残片
- 对有效物件输出标准化信息

只输出 JSON：
{
  "objects": [
    {
      "label": "短标签，2-6字",
      "holder": "持有者名称",
      "state": "佩戴|手持|收纳|放置|其他",
      "notes": "一句话说明"
    }
  ]
}
"""

# 物件动作动词
_ACTION_VERBS = (
    '拿出|掏出|摸出|亮出|举起|握住|握着|提着|背着|佩着|挂着|揣着|'
    '递给|交给|塞给|丢给|扔给|放下|收起|塞回|挂回|插回|收入|放入|'
    '打开|展开|翻开|卷起|合上|解下|摘下|拔出|抽出|系上|捡起|接过|'
    '端着|捧着|抱着|夹着|攥着|拎着|取出|取下|藏入|掖入'
)

# 物件名词模式（常见 RP 物件）
_OBJECT_NOUNS = (
    '刀|剑|枪|弓|箭|盾|甲|斧|锤|戟|鞭|匕首|暗器|弩|弹弓|'
    '信|纸|书|卷|册|帛|笺|契约|文书|地图|图纸|令牌|腰牌|'
    '药|丸|散|膏|瓶|壶|罐|囊|袋|盒|箱|匣|笼|锁|钥匙|'
    '玉|珠|环|簪|钗|镯|佩|坠|戒|冠|笠|面具|'
    '灯|烛|火折|绳|索|钩|铁链|'
    '银两|碎银|金锭|铜钱|银票|'
    '纸条|包裹|竹筒|木牌|铜牌|铁牌|石碑'
)

_ACTION_PATTERN = re.compile(
    rf'(?:{_ACTION_VERBS})\s*(?:了|着|过)?\s*'
    rf'(?:[那这其一]?[把柄只个张枚块包袋瓶壶件副条卷串份封])?\s*'
    rf'([\u4e00-\u9fff]{{2,8}})',
    re.UNICODE
)

_NOUN_PATTERN = re.compile(rf'({_OBJECT_NOUNS})', re.UNICODE)


def _registry_path(session_id: str):
    return session_paths(session_id)['memory_dir'] / 'object_registry.json'


def load_object_registry(session_id: str) -> dict:
    path = _registry_path(session_id)
    if not path.exists():
        return {'version': 1, 'processed_pairs': 0, 'objects': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        data = {}
    data.setdefault('version', 1)
    data.setdefault('processed_pairs', 0)
    data.setdefault('objects', [])
    return data


def save_object_registry(session_id: str, registry: dict) -> None:
    path = _registry_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


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


def _heuristic_extract_objects(window_pairs: list[tuple[dict, dict]]) -> list[dict]:
    """启发式从对话窗口中提取物件候选。"""
    _PRONOUNS = {'你', '我', '他', '她', '它', '其', '某', '那', '这'}
    candidates = []
    seen_labels = set()
    for _user_item, assistant_item in window_pairs:
        text = str(assistant_item.get('content', '') or '')
        for match in _ACTION_PATTERN.finditer(text):
            label = match.group(1).strip()
            # 去除开头代词
            while label and label[0] in _PRONOUNS:
                label = label[1:]
            # 去除常见前缀噪声
            label = re.sub(r'^[一二三四五六七八九十两几数]?[把柄只个张枚块包袋瓶壶件副条卷串份封]', '', label)
            label = re.sub(r'^[怀腰手身背胸腿]中的?', '', label)
            if len(label) < 2 or len(label) > 8:
                continue
            normalized = sanitize_runtime_name(label)
            if not normalized or normalized in seen_labels:
                continue
            # 提取动作前的可能持有者（向前找名字）
            start = max(0, match.start() - 20)
            prefix = text[start:match.start()]
            holder = ''
            name_match = re.search(r'([\u4e00-\u9fff]{2,4})', prefix)
            if name_match:
                holder = name_match.group(1)
            candidates.append({
                'label': normalized,
                'holder': holder,
                'source': 'action_verb',
            })
            seen_labels.add(normalized)
    return candidates


def _build_classify_prompt(existing_objects: list[dict], candidates: list[dict], context_text: str) -> str:
    payload = {
        'existing_objects': [
            {'label': o.get('label', ''), 'holder': o.get('holder', '')}
            for o in existing_objects[:10]
        ],
        'candidates': candidates[:15],
        'context_snippet': context_text[:800],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_objects(items) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        label = sanitize_runtime_name(item.get('label', ''))
        if not label or label in seen or len(label) > 8:
            continue
        out.append({
            'label': label,
            'holder': sanitize_runtime_name(item.get('holder', '')) or '未知',
            'state': str(item.get('state', '') or '收纳').strip() or '收纳',
            'notes': str(item.get('notes', '') or '')[:60],
        })
        seen.add(label)
    return out


def _merge_objects(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = {}
    for item in existing:
        label = sanitize_runtime_name(item.get('label', ''))
        if label:
            merged[label] = deepcopy(item)
    for item in incoming:
        label = sanitize_runtime_name(item.get('label', ''))
        if not label:
            continue
        if label in merged:
            prev = merged[label]
            if item.get('holder') and item['holder'] != '未知':
                prev['holder'] = item['holder']
            if item.get('state') and item['state'] != '收纳':
                prev['state'] = item['state']
            if item.get('notes') and not prev.get('notes'):
                prev['notes'] = item['notes']
        else:
            merged[label] = deepcopy(item)
    return list(merged.values())


def ensure_object_registry(session_id: str, history: list[dict], *, window_size: int = 10, force: bool = False) -> dict:
    pairs = _turn_pairs(history)
    registry = load_object_registry(session_id)
    processed_pairs = 0 if force else int(registry.get('processed_pairs', 0) or 0)
    if not force and processed_pairs >= len(pairs):
        return registry

    objects = list(registry.get('objects', []) or []) if not force else []
    for start in range(processed_pairs, len(pairs), window_size):
        window_pairs = pairs[start:start + window_size]
        if not window_pairs:
            continue
        # 阶段1：启发式提候选
        candidates = _heuristic_extract_objects(window_pairs)
        if not candidates:
            processed_pairs = start + len(window_pairs)
            continue
        # 阶段2：LLM 判定/分类/去重
        context_text = '\n'.join(
            str(a.get('content', '') or '')[:200]
            for _u, a in window_pairs
        )
        user_prompt = _build_classify_prompt(objects, candidates, context_text)
        try:
            reply, _usage = call_role_llm('state_keeper_candidate', OBJECT_CLASSIFY_SYSTEM, user_prompt)
            payload = json.loads(reply)
            incoming = _normalize_objects(payload.get('objects', []))
        except Exception:
            # LLM 失败时使用启发式结果的子集
            incoming = _normalize_objects([
                {'label': c['label'], 'holder': c.get('holder', ''), 'state': '收纳', 'notes': 'heuristic'}
                for c in candidates[:5]
            ])
        # 阶段3：merge
        objects = _merge_objects(objects, incoming)
        processed_pairs = start + len(window_pairs)

    registry = {
        'version': 1,
        'processed_pairs': processed_pairs,
        'objects': objects,
    }
    save_object_registry(session_id, registry)
    return registry


def registry_summary_lines(registry: dict, limit: int = 6) -> str:
    lines = []
    for item in (registry.get('objects', []) or [])[:limit]:
        if not isinstance(item, dict):
            continue
        label = sanitize_runtime_name(item.get('label', ''))
        if not label:
            continue
        holder = str(item.get('holder', '') or '未知').strip()
        state = str(item.get('state', '') or '').strip()
        lines.append(f"- {label} ({holder}, {state})")
    return '\n'.join(lines) if lines else '暂无'
