#!/usr/bin/env python3
from __future__ import annotations

import json
import re

try:
    from .llm_manager import call_role_llm
    from .local_model_client import parse_json_response
    from .runtime_store import is_complete_assistant_item, load_history, load_summary_chunks, save_summary_chunks
    from .name_sanitizer import looks_like_bad_entity_fragment, protagonist_names
    from .event_ledger import extract_time_location_anchor
except ImportError:
    from llm_manager import call_role_llm
    from local_model_client import parse_json_response
    from runtime_store import is_complete_assistant_item, load_history, load_summary_chunks, save_summary_chunks
    from name_sanitizer import looks_like_bad_entity_fragment, protagonist_names
    from event_ledger import extract_time_location_anchor


SUMMARY_CHUNK_SIZE = 12


SUMMARY_CHUNK_SYSTEM = """你是 RP 历史分段整理器。

只输出 JSON，不要解释。

你要把固定 12 轮对话整理成 dense summary chunk。要求尽量保留事件细节，不要写成高度抽象的一句话。

输出格式：
{
  "dense_summary": ["按时间顺序，每轮或每个连续动作一条，保留地点、人物、物品、台词要点、发现、误会、未解问题"],
  "time_start": "本段开始时的叙事时间锚点，如无则空字符串",
  "time_end": "本段结束时的叙事时间锚点，如无则空字符串",
  "key_events": ["这一段最关键的事件事实"],
  "unresolved": ["这一段结束后仍未解决的问题"],
  "locations": ["出现过的地点"],
  "actors_mentioned": ["出现过的人物称呼"],
  "objects_mentioned": ["出现过的物品"],
  "keywords": ["用于后续检索的结构化短关键词，优先人物/地点/事件线/关系线/物件"]
}

规则：
1. 只总结输入窗口，不要续写。
2. dense_summary 尽量细，8-18 条，每条 50-140 中文字。
3. key_events 3-10 条。
4. unresolved 0-10 条。
5. 不维护 NPC 性格设定；人物设定由 actor registry 管。
6. 不维护物品主账本或谁知道什么；这些由 keeper 管。
7. 保留台词里的关键信息，但不要整段抄 prose。
8. keywords 不要输出随机中文碎片、断句或泛词；优先输出 2-12 字的稳定检索键，如完整人物名、地点名、关键物件、事件短语、关系线（例：新人训练、带队教官、场地考核、回答提问、手环异常）。
"""


GENERIC_KEYWORD_TOKENS = {
    '当前', '自己', '一个', '一些', '没有', '已经', '开始', '继续', '只是', '不是', '可能', '觉得',
    '时候', '地方', '位置', '周围', '对方', '什么', '起来', '下来', '过去', '出来', '进去',
}

WEAK_KEYWORD_EDGES = tuple('在把被将和与及向从对给为于的了着过里中上下前后时')

BAD_KEYWORD_SUBSTRINGS = (
    '发现', '站在', '看着', '想着', '抓住', '触到', '落进', '没有', '前往', '位于',
    '朝着', '仍朝', '疑似', '暗示', '打算', '声音', '一触', '那截', '缝里',
    '角色在', '人影朝', '再次观察', '墙上的', '返回', '正跟', '画占', '朝灵田',
    '贴了', '内容是',
)

KEYWORD_ENTITY_PATTERNS = (
    r'(?:青布短衫人|灰袍散修|灰袍人|提灯人|脚夫|伙计|掌柜|教官)',
    r'(?:苍梧城|苍梧岭|城主府|茶肆|客栈|灵田|松林|灌木丛|凹地|旧摊|西市)',
    r'(?:吸灵螺|螺旋壳|病壳|大壳|管壁|短剑|须子|脚印|黑影|泥坑|泥地|榜文|图册|飞行符|隐灵符|镇魂符)',
)


def _turn_pairs(history: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    current_user = None
    for item in history or []:
        role = item.get('role')
        content = str(item.get('content', '') or '')
        if role == 'user':
            current_user = content
        elif role == 'assistant' and current_user is not None and is_complete_assistant_item(item):
            pairs.append((current_user, content))
            current_user = None
    return pairs


def _compact(value: str, limit: int = 260) -> str:
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text[:limit]


def _keyword_quality(value: str) -> bool:
    text = _compact(value, 24).strip('，。！？：；、“”‘’[]【】()（） ')
    if not text or text in GENERIC_KEYWORD_TOKENS:
        return False
    if len(text) < 2 or len(text) > 12:
        return False
    if text[0] in WEAK_KEYWORD_EDGES or text[-1] in WEAK_KEYWORD_EDGES:
        return False
    if any(part in text for part in BAD_KEYWORD_SUBSTRINGS):
        return False
    if '陆小环' in text and text != '陆小环':
        return False
    if any(mark in text for mark in ('着', '把', '被', '将', '给', '与')):
        return False
    if any(mark in text for mark in ('，', '。', '！', '？', '：', '；', '“', '”', '…')):
        return False
    if any(mark in text for mark in ('（', '）', '(', ')', '、')):
        return False
    return True


def _extract_keyword_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.findall(r'[《“「『]?([\u4e00-\u9fff]{2,12})(?:[》”」』])', text):
        candidates.append(match)
    for pattern in KEYWORD_ENTITY_PATTERNS:
        candidates.extend(re.findall(pattern, text))
    for phrase in re.findall(r'[\u4e00-\u9fff]{2,8}(?:训练|考核|提问|回答|追问|搜查|线索|风险|异常|转场|冲突|观察|检查|调查|探查|救治|喂食|悬赏|逃离|躲避)[\u4e00-\u9fff]{0,4}', text):
        candidates.append(phrase)
    return candidates


def _dedupe_keywords(candidates: list[str], limit: int = 30) -> list[str]:
    out: list[str] = []
    for raw in candidates:
        text = _compact(raw, 24).strip('，。！？：；、“”‘’[]【】()（） ')
        if not _keyword_quality(text) or text in out:
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _one_char_different(left: str, right: str) -> bool:
    return len(left) == len(right) and sum(1 for a, b in zip(left, right) if a != b) == 1


def _source_protagonist_names(pairs: list[tuple[str, str]]) -> list[str]:
    source_text = '\n'.join(' '.join(pair) for pair in pairs)
    return [name for name in protagonist_names() if name and name in source_text and len(name) >= 2]


def _repair_protagonist_drift(text: str, source_names: list[str]) -> str:
    repaired = str(text or '')
    for name in source_names:
        width = len(name)
        for segment in re.findall(r'[\u4e00-\u9fff]+', repaired):
            for idx in range(0, max(0, len(segment) - width) + 1):
                token = segment[idx:idx + width]
                if _one_char_different(token, name):
                    repaired = repaired.replace(token, name)
    return repaired


def _metadata_keywords(payload: dict, fallback: dict) -> list[str]:
    candidates: list[str] = []
    for field in ('actors_mentioned', 'locations', 'objects_mentioned'):
        for source in (payload, fallback):
            values = source.get(field, []) if isinstance(source.get(field, []), list) else []
            candidates.extend(str(item or '') for item in values)
    return candidates


def _structured_keywords(payload: dict, fallback: dict, pairs: list[tuple[str, str]], limit: int = 30) -> list[str]:
    candidates: list[str] = _metadata_keywords(payload, fallback)
    for field in ('key_events', 'unresolved', 'dense_summary'):
        values = payload.get(field, []) if isinstance(payload.get(field, []), list) else []
        for item in values[:8]:
            candidates.extend(_extract_keyword_candidates(str(item or '')))
    joined = '\n'.join(' '.join(pair) for pair in pairs)
    if len(_dedupe_keywords(candidates, limit=limit)) < 8:
        candidates.extend(_extract_keyword_candidates(joined))
    return _dedupe_keywords(candidates, limit=limit)


def _extract_chunk_metadata(text: str) -> dict[str, list[str]]:
    value = str(text or '')
    locations: list[str] = []
    for header in re.findall(r'【([^】]{2,40})】', value):
        parts = [part.strip() for part in re.split(r'[，,、/｜|]', header) if part.strip()]
        if len(parts) >= 2:
            locations.append(parts[-1])
    return {
        'actors_mentioned': [],
        'locations': locations,
        'objects_mentioned': [],
    }


def _chunk_time_range(pairs: list[tuple[str, str]]) -> tuple[str, str]:
    anchors = []
    for _user_text, assistant_text in pairs or []:
        time_anchor, _location_anchor = extract_time_location_anchor(assistant_text)
        if time_anchor:
            anchors.append(time_anchor)
    if not anchors:
        return '', ''
    return anchors[0], anchors[-1]


def _fallback_chunk(*, chunk_id: str, turn_start: int, turn_end: int, pairs: list[tuple[str, str]], provider: str = 'heuristic') -> dict:
    dense = []
    for idx, (user_text, assistant_text) in enumerate(pairs, start=turn_start):
        dense.append(f'第{idx}轮：用户动作：{_compact(user_text, 90)}；世界反馈：{_compact(assistant_text, 180)}')
    text = '\n'.join(' '.join(pair) for pair in pairs)
    extracted = _extract_chunk_metadata(text)
    time_start, time_end = _chunk_time_range(pairs)
    return {
        'chunk_id': chunk_id,
        'turn_start': turn_start,
        'turn_end': turn_end,
        'time_start': time_start,
        'time_end': time_end,
        'dense_summary': dense[:18],
        'key_events': dense[:6],
        'unresolved': [],
        'locations': extracted['locations'],
        'actors_mentioned': extracted['actors_mentioned'],
        'objects_mentioned': extracted['objects_mentioned'],
        'keywords': _structured_keywords({}, extracted, pairs, limit=30),
        'provider': provider,
    }


def _normalize_chunk(payload: dict, *, chunk_id: str, turn_start: int, turn_end: int, pairs: list[tuple[str, str]], provider: str) -> dict:
    fallback = _fallback_chunk(chunk_id=chunk_id, turn_start=turn_start, turn_end=turn_end, pairs=pairs, provider=provider)
    if not isinstance(payload, dict):
        return fallback
    out = dict(fallback)
    source_protagonist_names = _source_protagonist_names(pairs)
    for field in ('time_start', 'time_end'):
        value = _compact(str(payload.get(field, '') or ''), 40)
        if value:
            out[field] = value
    for field, limit in (
        ('dense_summary', 18),
        ('key_events', 10),
        ('unresolved', 10),
        ('locations', 12),
        ('actors_mentioned', 18),
        ('objects_mentioned', 18),
        ('keywords', 30),
    ):
        values = payload.get(field, [])
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        cleaned = []
        for item in values:
            text = _repair_protagonist_drift(str(item or ''), source_protagonist_names)
            text = _compact(text, 180 if field in {'dense_summary', 'key_events', 'unresolved'} else 40)
            if field == 'actors_mentioned' and looks_like_bad_entity_fragment(text):
                continue
            if text and text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= limit:
                break
        if cleaned:
            out[field] = cleaned
    extracted = _extract_chunk_metadata('\n'.join(' '.join(pair) for pair in pairs))
    for field in ('locations', 'actors_mentioned', 'objects_mentioned'):
        if not out.get(field):
            out[field] = extracted[field]
    out['provider'] = provider
    repaired_payload = dict(payload)
    for field in ('dense_summary', 'key_events', 'unresolved', 'actors_mentioned', 'keywords'):
        values = repaired_payload.get(field, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            repaired_payload[field] = [_repair_protagonist_drift(str(item or ''), source_protagonist_names) for item in values]
    out['keywords'] = _structured_keywords(repaired_payload, out, pairs, limit=30) or out.get('keywords', [])
    return out


def _build_chunk_with_llm(*, chunk_id: str, turn_start: int, turn_end: int, pairs: list[tuple[str, str]]) -> dict:
    prompt = json.dumps({
        'chunk_id': chunk_id,
        'turn_start': turn_start,
        'turn_end': turn_end,
        'turn_pairs': [
            {'turn': turn_start + idx, 'user': user, 'assistant': assistant}
            for idx, (user, assistant) in enumerate(pairs)
        ],
    }, ensure_ascii=False, indent=2)
    try:
        reply, _usage = call_role_llm('state_keeper_candidate', SUMMARY_CHUNK_SYSTEM, prompt)
        payload = parse_json_response(reply)
        return _normalize_chunk(payload, chunk_id=chunk_id, turn_start=turn_start, turn_end=turn_end, pairs=pairs, provider='llm')
    except Exception:
        return _fallback_chunk(chunk_id=chunk_id, turn_start=turn_start, turn_end=turn_end, pairs=pairs, provider='heuristic')


def update_summary_chunks(session_id: str, *, chunk_size: int = SUMMARY_CHUNK_SIZE) -> dict:
    history = load_history(session_id)
    pairs = _turn_pairs(history)
    store = load_summary_chunks(session_id)
    chunks = [item for item in store.get('chunks', []) if isinstance(item, dict)]
    existing_ids = {str(item.get('chunk_id', '') or '') for item in chunks}
    complete_chunks = len(pairs) // chunk_size
    changed = False
    for idx in range(complete_chunks):
        turn_start = idx * chunk_size + 1
        turn_end = (idx + 1) * chunk_size
        chunk_id = f'chunk_{idx + 1:04d}'
        if chunk_id in existing_ids:
            continue
        chunk_pairs = pairs[turn_start - 1:turn_end]
        chunk = _build_chunk_with_llm(chunk_id=chunk_id, turn_start=turn_start, turn_end=turn_end, pairs=chunk_pairs)
        chunks.append(chunk)
        existing_ids.add(chunk_id)
        changed = True
    if changed:
        save_summary_chunks(session_id, {'version': 1, 'chunks': chunks})
    return {'version': 1, 'chunks': chunks, 'created': changed}
