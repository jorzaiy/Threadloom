#!/usr/bin/env python3
"""情报抽取 bootstrap：启发式提候选 → LLM 判定/分类/去重 → merge 到 clue_registry。"""
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


CLUE_CLASSIFY_SYSTEM = """你是 RP 情报整理器。

任务：
- 对候选情报列表做判定：哪些是值得持续追踪的剧情线索
- 排除：日常闲聊、环境描写、重复信息
- 情报类型：暗线（hidden）、传闻（rumor）、实证（evidence）、情报（intel）

只输出 JSON：
{
  "clues": [
    {
      "summary": "一句话概括（≤30字）",
      "type": "hidden|rumor|evidence|intel",
      "confidence": "low|medium|high",
      "related_entities": ["相关人名或势力"],
      "notes": "补充说明"
    }
  ]
}
"""

# 情报/线索触发模式
_CLUE_PATTERNS = [
    # 直接信息传递
    re.compile(r'(?:听说|据说|有人说|传闻|消息|情报|密报|线报|风声|流言)'),
    # 发现/揭示
    re.compile(r'(?:发现|注意到|察觉|看出|认出|觉察|感应到|嗅到|闻到)'),
    # 秘密/隐藏
    re.compile(r'(?:秘密|暗中|偷偷|悄悄|隐藏|掩饰|隐瞒|不为人知|背后)'),
    # 证据/痕迹
    re.compile(r'(?:痕迹|证据|线索|蛛丝马迹|端倪|疑点|破绽|异常|可疑)'),
    # 信件/文件
    re.compile(r'(?:信中|书中|纸上|卷宗|记录|写着|记载|提到|载有)'),
    # 关系/阴谋
    re.compile(r'(?:勾结|串通|联手|密谋|图谋|阴谋|暗算|设局|布局)'),
    # 组织/势力
    re.compile(r'(?:镇北司|六扇门|丐帮|武当|少林|暗卫|锦衣|东厂|西厂)'),
]


def _registry_path(session_id: str):
    return session_paths(session_id)['memory_dir'] / 'clue_registry.json'


def load_clue_registry(session_id: str) -> dict:
    path = _registry_path(session_id)
    if not path.exists():
        return {'version': 1, 'processed_pairs': 0, 'clues': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        data = {}
    data.setdefault('version', 1)
    data.setdefault('processed_pairs', 0)
    data.setdefault('clues', [])
    return data


def save_clue_registry(session_id: str, registry: dict) -> None:
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


def _heuristic_extract_clues(window_pairs: list[tuple[dict, dict]]) -> list[dict]:
    """启发式从对话窗口中提取情报候选。"""
    candidates = []
    for _user_item, assistant_item in window_pairs:
        text = str(assistant_item.get('content', '') or '')
        # 按句分割
        sentences = re.split(r'[。！？\n]', text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 8 or len(sentence) > 200:
                continue
            matched_patterns = sum(1 for p in _CLUE_PATTERNS if p.search(sentence))
            if matched_patterns < 1:
                continue
            # 提取相关实体（简单的中文名提取）
            entities = re.findall(r'([\u4e00-\u9fff]{2,4}(?:司|门|帮|派|卫|营|阁|楼|庄|府|宗))', sentence)
            person_entities = re.findall(r'(?:[\u4e00-\u9fff]{2,4})(?=说|道|提到|表示|透露)', sentence)
            all_entities = list(set(entities + person_entities))
            # 截短作为摘要
            summary = sentence[:30] if len(sentence) > 30 else sentence
            candidates.append({
                'summary': summary,
                'source_sentence': sentence[:100],
                'pattern_count': matched_patterns,
                'related_entities': all_entities[:3],
            })
    # 按匹配模式数量排序取前 8 个
    candidates.sort(key=lambda x: x['pattern_count'], reverse=True)
    return candidates[:8]


def _build_classify_prompt(existing_clues: list[dict], candidates: list[dict], context_text: str) -> str:
    payload = {
        'existing_clues': [
            {'summary': c.get('summary', ''), 'type': c.get('type', '')}
            for c in existing_clues[:8]
        ],
        'candidates': [
            {'summary': c['summary'], 'source_sentence': c.get('source_sentence', '')}
            for c in candidates
        ],
        'context_snippet': context_text[:800],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_clues(items) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    valid_types = {'hidden', 'rumor', 'evidence', 'intel'}
    valid_conf = {'low', 'medium', 'high'}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        summary = str(item.get('summary', '') or '').strip()
        if not summary or len(summary) > 40:
            summary = summary[:40]
        if not summary:
            continue
        key = summary[:15]
        if key in seen:
            continue
        clue_type = str(item.get('type', '') or 'rumor').strip()
        if clue_type not in valid_types:
            clue_type = 'rumor'
        confidence = str(item.get('confidence', '') or 'low').strip()
        if confidence not in valid_conf:
            confidence = 'low'
        related = []
        for e in (item.get('related_entities', []) or []):
            name = sanitize_runtime_name(e)
            if name and name not in related:
                related.append(name)
        out.append({
            'summary': summary,
            'type': clue_type,
            'confidence': confidence,
            'related_entities': related[:4],
            'notes': str(item.get('notes', '') or '')[:60],
        })
        seen.add(key)
    return out


def _merge_clues(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = []
    existing_summaries = set()
    for item in existing:
        s = str(item.get('summary', '') or '').strip()
        if s:
            existing_summaries.add(s[:15])
            merged.append(deepcopy(item))
    for item in incoming:
        s = str(item.get('summary', '') or '').strip()
        if not s:
            continue
        key = s[:15]
        if key in existing_summaries:
            # 更新已有线索的置信度
            for m in merged:
                if str(m.get('summary', '') or '').strip()[:15] == key:
                    if item.get('confidence') == 'high':
                        m['confidence'] = 'high'
                    elif item.get('confidence') == 'medium' and m.get('confidence') != 'high':
                        m['confidence'] = 'medium'
                    break
        else:
            merged.append(deepcopy(item))
            existing_summaries.add(key)
    # 限制总数
    return merged[:20]


def ensure_clue_registry(session_id: str, history: list[dict], *, window_size: int = 10, force: bool = False) -> dict:
    pairs = _turn_pairs(history)
    registry = load_clue_registry(session_id)
    processed_pairs = 0 if force else int(registry.get('processed_pairs', 0) or 0)
    if not force and processed_pairs >= len(pairs):
        return registry

    clues = list(registry.get('clues', []) or []) if not force else []
    for start in range(processed_pairs, len(pairs), window_size):
        window_pairs = pairs[start:start + window_size]
        if not window_pairs:
            continue
        # 阶段1：启发式提候选
        candidates = _heuristic_extract_clues(window_pairs)
        if not candidates:
            processed_pairs = start + len(window_pairs)
            continue
        # 阶段2：LLM 判定/分类
        context_text = '\n'.join(
            str(a.get('content', '') or '')[:200]
            for _u, a in window_pairs
        )
        user_prompt = _build_classify_prompt(clues, candidates, context_text)
        try:
            reply, _usage = call_role_llm('state_keeper_candidate', CLUE_CLASSIFY_SYSTEM, user_prompt)
            payload = json.loads(reply)
            incoming = _normalize_clues(payload.get('clues', []))
        except Exception:
            # LLM 失败时使用启发式结果的子集
            incoming = _normalize_clues([
                {'summary': c['summary'], 'type': 'rumor', 'confidence': 'low',
                 'related_entities': c.get('related_entities', []), 'notes': 'heuristic'}
                for c in candidates[:4]
            ])
        # 阶段3：merge
        clues = _merge_clues(clues, incoming)
        processed_pairs = start + len(window_pairs)

    registry = {
        'version': 1,
        'processed_pairs': processed_pairs,
        'clues': clues,
    }
    save_clue_registry(session_id, registry)
    return registry


def registry_summary_lines(registry: dict, limit: int = 5) -> str:
    lines = []
    for item in (registry.get('clues', []) or [])[:limit]:
        if not isinstance(item, dict):
            continue
        summary = str(item.get('summary', '') or '').strip()
        if not summary:
            continue
        ctype = str(item.get('type', '') or '').strip()
        conf = str(item.get('confidence', '') or '').strip()
        lines.append(f"- [{ctype}/{conf}] {summary}")
    return '\n'.join(lines) if lines else '暂无'
