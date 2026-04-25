#!/usr/bin/env python3
from __future__ import annotations

import json

try:
    from .llm_manager import call_role_llm
    from .local_model_client import parse_json_response
    from .model_config import load_runtime_config
    from .name_sanitizer import sanitize_runtime_name
except ImportError:
    from llm_manager import call_role_llm
    from local_model_client import parse_json_response
    from model_config import load_runtime_config
    from name_sanitizer import sanitize_runtime_name


ENTITY_JUDGE_SYSTEM = """你是中文 RP runtime 的实体候选判定器。

你不会自由抽取新实体，只会判断脚本提取出的候选是否真的是“当前应该保留为人物实体”的名字。

只输出 JSON：
{
  "accepted": ["人物名1", "人物名2"],
  "rejected": [{"candidate": "候选", "reason": "拒绝原因"}]
}

规则：
1. 只有“人物称呼 / 人物别称 / 明确指向单个角色的标签”才接受。
2. 情报短语、地点、物件、数量片段、句子碎片、动作碎片，一律拒绝。
3. 如果候选只是某个人物称呼的残片，也拒绝。
4. 如果两个候选明显是同一人物的描述性别称，只保留更完整、更自然的称呼。
5. 不要把容器、文书、地点、机构、交通工具、系统机制、抽象线索之类非人物词当成人物。
6. 宁可少收，也不要误收。
"""


def _judge_config() -> dict:
    cfg = load_runtime_config()
    data = cfg.get('entity_recovery', {}) if isinstance(cfg.get('entity_recovery', {}), dict) else {}
    return {
        'enabled': bool(data.get('use_candidate_judge', False)),
        'judge_role': str(data.get('judge_role', 'state_keeper_candidate') or 'state_keeper_candidate').strip() or 'state_keeper_candidate',
        'max_candidates': max(3, int(data.get('max_candidates', 12) or 12)),
    }


def judge_entity_candidates(candidates: list[str], context_excerpt: str, stable_names: list[str]) -> list[str] | None:
    cfg = _judge_config()
    if not cfg['enabled']:
        return None
    normalized_candidates = []
    for candidate in candidates or []:
        text = sanitize_runtime_name(candidate)
        if text and text not in normalized_candidates:
            normalized_candidates.append(text)
        if len(normalized_candidates) >= cfg['max_candidates']:
            break
    if not normalized_candidates:
        return []

    prompt = json.dumps({
        'context_excerpt': str(context_excerpt or '')[:6000],
        'previous_stable_names': [sanitize_runtime_name(name) for name in stable_names if sanitize_runtime_name(name)][:20],
        'candidates': normalized_candidates,
    }, ensure_ascii=False, indent=2)

    try:
        reply, _usage = call_role_llm(cfg['judge_role'], ENTITY_JUDGE_SYSTEM, prompt)
        payload = parse_json_response(reply)
    except Exception:
        return None

    accepted_raw = payload.get('accepted', []) if isinstance(payload, dict) else []
    accepted: list[str] = []
    for item in accepted_raw if isinstance(accepted_raw, list) else []:
        if isinstance(item, dict):
            text = sanitize_runtime_name(item.get('canonical') or item.get('candidate'))
        else:
            text = sanitize_runtime_name(item)
        if not text or text in accepted:
            continue
        accepted.append(text)
    return accepted
