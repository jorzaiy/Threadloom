#!/usr/bin/env python3
"""Distill a STABLE personality for an NPC from how it behaved in-story — run once,
then locked into the fact-log entity.

Personality here = disposition / temperament / speech-and-action style
(成熟稳重 / 话少 / 飞扬跳脱 / 谨慎). It deliberately EXCLUDES the NPC's attitude
toward the protagonist and any relationship or feeling — those change as the story
advances and are tracked dynamically elsewhere, never frozen here.
"""
from __future__ import annotations

try:
    from .llm_manager import call_role_llm
    from .local_model_client import parse_json_response
except ImportError:
    from llm_manager import call_role_llm
    from local_model_client import parse_json_response

PERSONA_SYSTEM = """你从一个 NPC 在故事里的若干行为片段中，提炼这个角色【稳定的性格气质】。

只输出一句中文（不超过30字），概括他长期稳定的：性格基调 + 说话/做事风格。
示例：「沉默寡言，遇事谨慎，认准的事肯冒险」「成熟稳重，话不多但有主见」「飞扬跳脱，爱开玩笑」。

严格排除（以下都会随剧情变化，不属于性格，绝不能写进来）：
- 对主角或任何人的态度、好恶、信任、戒备、亲疏、关系；
- 当前情绪、当下处境、对具体事件的复述；
- 主角做了什么。

只写这个 NPC「是个怎样的人」，不写「他怎么看待主角」。不要引号、不要解释、不要换行。"""


# keeper-tier models often wrap the answer as JSON ({"content": "..."} or
# {"role":"assistant","content":"..."}); peel it down to the real text.
def _clean_persona_text(reply) -> str:
    text = str(reply or '').strip()
    for _ in range(2):
        if text.startswith('{') or text.startswith('```'):
            obj = parse_json_response(text)
            if isinstance(obj, dict) and obj:
                inner = (obj.get('content') or obj.get('persona') or obj.get('personality')
                         or obj.get('text') or obj.get('result') or '')
                text = str(inner).strip()
                continue
        break
    return text.replace('\n', ' ').strip('"“”「」 ').strip()


# Tokens that betray a prompt echo or leftover JSON rather than a real persona.
_PERSONA_REJECT = ('提炼', '性格气质', '只输出', '示例', 'task_description',
                   'role', 'assistant', 'content', '{', '}', 'NPC')


def distill_persona(name: str, observations: list[str], *, role: str = 'state_keeper_candidate') -> str:
    """Return a clean one-line stable personality, or '' if there isn't enough to go
    on, the call fails, or the model returns a prompt echo / unparsable junk
    (caller then leaves persona empty and retries next consolidation)."""
    obs = [str(o).strip() for o in (observations or []) if str(o).strip()]
    if len(obs) < 2:                       # too little behaviour to characterize
        return ''
    prompt = f'NPC：{name}\n他在故事里的行为片段：\n' + '\n'.join(f'- {o}' for o in obs[:12])
    try:
        reply, _usage = call_role_llm(role, PERSONA_SYSTEM, prompt)
    except Exception:
        return ''
    text = _clean_persona_text(reply)
    if not text or len(text) > 50:                          # empty or suspiciously long
        return ''
    if any(tok in text for tok in _PERSONA_REJECT):         # prompt echo / leftover JSON
        return ''
    return text
