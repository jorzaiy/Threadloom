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
except ImportError:
    from llm_manager import call_role_llm

PERSONA_SYSTEM = """你从一个 NPC 在故事里的若干行为片段中，提炼这个角色【稳定的性格气质】。

只输出一句中文（不超过30字），概括他长期稳定的：性格基调 + 说话/做事风格。
示例：「沉默寡言，遇事谨慎，认准的事肯冒险」「成熟稳重，话不多但有主见」「飞扬跳脱，爱开玩笑」。

严格排除（以下都会随剧情变化，不属于性格，绝不能写进来）：
- 对主角或任何人的态度、好恶、信任、戒备、亲疏、关系；
- 当前情绪、当下处境、对具体事件的复述；
- 主角做了什么。

只写这个 NPC「是个怎样的人」，不写「他怎么看待主角」。不要引号、不要解释、不要换行。"""


def distill_persona(name: str, observations: list[str], *, role: str = 'state_keeper_candidate') -> str:
    """Return a one-line stable personality, or '' if there isn't enough to go on or
    the model call fails (caller leaves the persona empty and retries next time)."""
    obs = [str(o).strip() for o in (observations or []) if str(o).strip()]
    if len(obs) < 2:                       # too little behaviour to characterize
        return ''
    prompt = f'NPC：{name}\n他在故事里的行为片段：\n' + '\n'.join(f'- {o}' for o in obs[:12])
    try:
        reply, _usage = call_role_llm(role, PERSONA_SYSTEM, prompt)
    except Exception:
        return ''
    text = str(reply or '').strip().replace('\n', ' ').strip('"“”「」 ').strip()
    return text[:60]
