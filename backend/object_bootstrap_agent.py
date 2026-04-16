#!/usr/bin/env python3
"""物品抽取 bootstrap：启发式提候选 → LLM 判定/分类/去重 → merge 到 object_index。"""
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
        # 去掉首行 ```json 或 ```
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

# 物件动作动词（转移/持有类）
_TRANSFER_VERBS = (
    '拿出|掏出|摸出|亮出|举起|握住|递给|交给|塞给|丢给|扔给|'
    '放下|收起|塞回|挂回|插回|收入|放入|解下|摘下|拔出|抽出|'
    '系上|捡起|接过|取出|取下|藏入|掖入'
)

# 物件名词模式（常见 RP 物件关键词）
_OBJECT_NOUNS_LIST = [n for n in (
    '刀|剑|枪|弓|箭|盾|甲|斧|锤|戟|鞭|匕首|暗器|弩|弹弓|短刀|长剑|宝剑|柴刀|'
    '信|纸|书|卷|册|帛|笺|契约|文书|地图|图纸|令牌|腰牌|木牌|铜牌|铁牌|石碑|'
    '药|丸|散|膏|瓶|壶|罐|囊|袋|盒|箱|匣|笼|锁|钥匙牌|钥匙|'
    '玉|珠|环|簪|钗|镯|佩|坠|戒|冠|笠|面具|'
    '灯|烛|火折子|火折|绳|索|钩|铁链|风灯|油灯|灯笼|'
    '银两|碎银|金锭|铜钱|银票|铜板|'
    '纸条|包裹|包袱|竹筒|托盘|木盆|酒壶|茶壶|'
    '长衫|外袍|披风|斗篷|面纱|头巾|布巾'
).split('|') if n]
# 按长度降序排列，保证长词优先匹配
_OBJECT_NOUNS_LIST.sort(key=len, reverse=True)
_OBJECT_NOUNS = '|'.join(_OBJECT_NOUNS_LIST)

# 策略1：动作动词 + 量词 + 已知物件名词
_VERB_NOUN_PATTERN = re.compile(
    rf'(?:{_TRANSFER_VERBS})\s*(?:了|来|去)?\s*'
    rf'(?:[那这其一两]?[把柄只个张枚块包袋瓶壶件副条卷串份封面])?'
    rf'[\u4e00-\u9fff]{{0,2}}?({_OBJECT_NOUNS})',
    re.UNICODE
)

# 策略2：动作动词 + 短名词（2-4字，不含的/了/着等虚词）
_VERB_SHORT_PATTERN = re.compile(
    rf'(?:{_TRANSFER_VERBS})\s*(?:了|来|去)?\s*'
    rf'(?:[那这其一两]?[把柄只个张枚块包袋瓶壶件副条卷串份封面])?\s*'
    rf'([\u4e00-\u9fff]{{2,4}})',
    re.UNICODE
)

# 策略3：量词 + 已知物件名词（无需动词前缀）
_QUANT_NOUN_PATTERN = re.compile(
    r'[一二三四五六七八九十两几数那这]'
    r'[把柄只个张枚块包袋瓶壶件副条卷串份封面盏柄截]'
    rf'[\u4e00-\u9fff]{{0,2}}?({_OBJECT_NOUNS})',
    re.UNICODE
)

# 策略4：直接匹配已知多字物件名词（≥2字，无需前缀）
_DIRECT_NOUN_PATTERN = re.compile(
    rf'({"|".join(n for n in _OBJECT_NOUNS_LIST if len(n) >= 2)})',
    re.UNICODE
)

# 虚词/动词/方位词 — 不应出现在物件名里
_JUNK_CHARS = set('的了着过来去在到从把被给让叫使得很太更也都还就只才又又已将要会能可应该是有没不无')
_JUNK_SUFFIXES = {'时候', '时', '之后', '之前', '上面', '下面', '里面', '外面', '旁边', '过来', '过去', '起来', '上去', '下去', '上来', '下来', '声道', '低声', '冷笑', '一笑'}
# 不是便携物件的词
_NOT_OBJECTS = {
    '抽屉', '柜子', '桌子', '椅子', '门', '窗', '墙', '地面', '屋顶', '台阶', '楼梯',
    '眼底', '手心', '手背', '脸上', '身上', '头上', '肩上', '腰间', '怀中', '掌心',
    '小二', '掌柜', '老板', '伙计', '客人', '侍女', '丫鬟', '老者', '少年', '青年',
    '院子', '厨房', '柴房', '大堂', '客房', '天井', '走廊', '门口', '巷口', '街道',
}


def _registry_path(session_id: str):
    return session_paths(session_id)['memory_dir'] / 'object_registry.json'


def load_object_registry(session_id: str) -> dict:
    path = _registry_path(session_id)
    if not path.exists():
        return {'version': 1, 'processed_pairs': 0, 'objects': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error('物品 registry 加载失败 (%s): %s', session_id, e)
        data = {}
    data.setdefault('version', 1)
    data.setdefault('processed_pairs', 0)
    data.setdefault('objects', [])
    return data


def save_object_registry(session_id: str, registry: dict) -> None:
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


def _is_valid_object_label(label: str) -> bool:
    """检查候选标签是否像物件名。"""
    if not label or len(label) < 2 or len(label) > 6:
        return False
    if label in _NOT_OBJECTS:
        return False
    # 含虚词/动词字符 → 不是物件
    if any(c in _JUNK_CHARS for c in label):
        return False
    # 以方位/时间后缀结尾 → 不是物件
    for suffix in _JUNK_SUFFIXES:
        if label.endswith(suffix):
            return False
    return True


def _heuristic_extract_objects(window_pairs: list[tuple[dict, dict]]) -> list[dict]:
    """启发式从对话窗口中提取物件候选。双策略：已知名词优先，短名词兜底。"""
    candidates = []
    seen_labels: set[str] = set()

    def _add(label: str, text: str, match_pos: int, source: str):
        # 去除量词前缀（如 "一角碎银" → "碎银"，"几枚铜钱" → "铜钱"）
        label = re.sub(r'^[一二三四五六七八九十两几数半]?[把柄只个张枚块袋瓶壶件副条卷串份封角坛]', '', label)
        if len(label) < 2:
            return
        normalized = sanitize_runtime_name(label)
        if not normalized or normalized in seen_labels:
            return
        if not _is_valid_object_label(normalized):
            return
        candidates.append({
            'label': normalized,
            'holder': '',
            'source': source,
        })
        seen_labels.add(normalized)

    for _user_item, assistant_item in window_pairs:
        text = str(assistant_item.get('content', '') or '')
        # 策略1：动词 + 已知物件名词（高置信度）
        for match in _VERB_NOUN_PATTERN.finditer(text):
            _add(match.group(1), text, match.start(), 'known_noun')
        # 策略2：动词 + 短名词（需过滤）
        for match in _VERB_SHORT_PATTERN.finditer(text):
            _add(match.group(1), text, match.start(), 'short_noun')
        # 策略3：量词 + 已知物件名词（无需动词）
        for match in _QUANT_NOUN_PATTERN.finditer(text):
            _add(match.group(1), text, match.start(), 'quant_noun')
        # 策略4：直接匹配已知多字物件名词
        for match in _DIRECT_NOUN_PATTERN.finditer(text):
            _add(match.group(1), text, match.start(), 'direct_noun')
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
            payload = json.loads(_strip_code_fences(reply))
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
