#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from model_client import call_model
from model_config import resolve_provider_model
from paths import clear_active_character_override, normalize_session_id, set_active_character_override
from runtime_store import load_history, load_state, session_paths


CANDIDATE_PATTERNS = [
    r'[\u4e00-\u9fff]{1,4}之人',
    r'[\u4e00-\u9fff]{1,4}身影',
    r'[\u4e00-\u9fff]{1,4}人',
    r'掌柜',
    r'皂衣人',
    r'毡笠人',
    r'瘦削之人',
    r'木匣',
    r'账册',
    r'三处私盐',
    r'沈砚青',
    r'沈大人',
]


JUDGE_SYSTEM = """你是中文 RP runtime 的实体候选判定器。

你不会自由抽取新实体，只会判断脚本提取出的候选是否真的是“当前应该保留为人物实体”的名字。

只输出 JSON。
格式：
{
  "accepted": [{"candidate": str, "canonical": str, "reason": str}],
  "rejected": [{"candidate": str, "reason": str}]
}

判定规则：
1. 只有“人物称呼 / 人物别称 / 明确指向单个角色的标签”才接受。
2. 情报短语、地点、物件、数量片段、句子碎片、动作碎片，一律拒绝。
3. 如果候选只是某个人物称呼的残片（例如截断掉前缀或后缀），也拒绝。
4. 如果两个候选明显是同一人物的描述性别称，accepted 里只保留更完整、更自然的称呼；另一个放 rejected 并说明是别称碎片或较弱别称。
5. 不要把“木匣 / 账册 / 私盐道 / 军仓 / 车 / 天牢 / 司里”之类非人物词当成人物。
6. 宁可少收，也不要误收。
"""


def _recent_assistant_excerpt(history: list[dict], *, limit: int = 6) -> str:
    blocks = [
        str(item.get('content', '') or '')
        for item in history[-12:]
        if item.get('role') == 'assistant'
    ]
    return '\n\n'.join(blocks[-limit:])


def _baseline_outputs(state: dict) -> dict:
    return {
        'relevant_npcs': state.get('relevant_npcs', []),
        'scene_entities': [
            item.get('primary_label')
            for item in (state.get('scene_entities', []) or [])
            if isinstance(item, dict) and item.get('primary_label')
        ],
        'important_npcs': [
            item.get('primary_label')
            for item in (state.get('important_npcs', []) or [])
            if isinstance(item, dict) and item.get('primary_label')
        ],
        'thread_actors': sorted({
            actor
            for item in (state.get('active_threads', []) or [])
            if isinstance(item, dict)
            for actor in (item.get('actors', []) or [])
            if actor
        }),
    }


def _script_candidates(assistant_excerpt: str, baseline: dict) -> list[str]:
    candidates: list[str] = []
    for pattern in CANDIDATE_PATTERNS:
        for match in re.findall(pattern, assistant_excerpt):
            if match not in candidates:
                candidates.append(match)
    for pool in baseline.values():
        for item in pool:
            if item and item not in candidates:
                candidates.append(item)
    return candidates


def _judge_candidates(assistant_excerpt: str, candidates: list[str], baseline: dict, *, model_id: str) -> tuple[dict, dict]:
    system_prompt = JUDGE_SYSTEM
    user_prompt = json.dumps({
        'assistant_excerpt': assistant_excerpt,
        'script_candidates': candidates,
        'current_bad_outputs': baseline,
    }, ensure_ascii=False, indent=2)
    cfg = resolve_provider_model('narrator')
    cfg['model'] = {'id': model_id}
    cfg['temperature'] = 0.0
    cfg['max_output_tokens'] = 1200
    cfg['stream'] = False
    try:
        reply, usage = call_model(cfg, system_prompt, user_prompt)
    except AttributeError:
        # Some providers return usage=null; retry with a fallback judge model rather than
        # modifying the main client path in this sidecar experiment.
        cfg['model'] = {'id': 'gemini-3-flash-preview'}
        reply, usage = call_model(cfg, system_prompt, user_prompt)
    reply_text = reply.strip()
    if '```json' in reply_text:
        start = reply_text.index('```json') + 7
        end = reply_text.index('```', start) if '```' in reply_text[start:] else len(reply_text)
        reply_text = reply_text[start:end].strip()
    elif reply_text.startswith('```'):
        start = reply_text.find('\n')
        end = reply_text.rfind('```')
        if start != -1 and end > start:
            reply_text = reply_text[start:end].strip()
    payload = json.loads(reply_text)
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault('accepted', [])
    payload.setdefault('rejected', [])
    return payload, {
        'model': usage.get('model'),
        'input_tokens': usage.get('input_tokens'),
        'output_tokens': usage.get('output_tokens'),
        'finish_reason': usage.get('finish_reason'),
    }


def run_experiment(session_id: str, *, judge_model: str) -> dict:
    state = load_state(session_id)
    history = load_history(session_id)
    assistant_excerpt = _recent_assistant_excerpt(history)
    baseline = _baseline_outputs(state)
    candidates = _script_candidates(assistant_excerpt, baseline)
    judged, usage = _judge_candidates(assistant_excerpt, candidates, baseline, model_id=judge_model)
    return {
        'session_id': session_id,
        'baseline': baseline,
        'script_candidates': candidates,
        'assistant_excerpt': assistant_excerpt,
        'judge_model': judge_model,
        'judge_usage': usage,
        'judge_result': judged,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Run a sidecar entity extraction experiment: script candidates + LLM judge')
    parser.add_argument('--session', required=True, help='Target session id')
    parser.add_argument('--character-id', help='Optional active character override')
    parser.add_argument('--judge-model', default='qwen3.6-plus', help='Model id used only for candidate judging')
    args = parser.parse_args()

    session_id = normalize_session_id(args.session)
    set_active_character_override(args.character_id)
    try:
        report = run_experiment(session_id, judge_model=args.judge_model)
    finally:
        clear_active_character_override()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
