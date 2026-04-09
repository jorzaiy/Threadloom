#!/usr/bin/env python3
import json
from typing import Optional


def _format_persona_lines(persona: list[dict], limit: int = 4) -> str:
    lines = []
    for item in persona[:limit]:
        hooks = item.get('hooks', {})
        lines.append(
            f"- {item.get('name')}: {item.get('archetype', {}).get('value', item.get('archetype'))} / "
            f"{hooks.get('speech_rhythm', '待确认')} / {hooks.get('social_strategy', '待确认')} / {hooks.get('conflict_style', '待确认')}"
        )
    return '\n'.join(lines) if lines else '暂无'


def _format_lorebook_npc_candidates(items: list[dict], limit: int = 6) -> str:
    if not items:
        return '暂无'
    lines = []
    for item in items[:limit]:
        summary = (item.get('summary') or '').strip()
        if len(summary) > 220:
            summary = summary[:217] + '...'
        lines.append(f"- {item.get('name')}: {summary or '世界书已有该 NPC，可在合适时机调入。'}")
    return '\n'.join(lines)


def _format_npc_profiles(npc_profiles: list[dict], limit: int = 4) -> str:
    if not npc_profiles:
        return '暂无'
    parts = []
    for profile in npc_profiles[:limit]:
        name = profile.get('name', '未知')
        content = profile.get('content', '').strip()
        if content:
            # 截断过长内容
            if len(content) > 600:
                content = content[:597] + '...'
            parts.append(f'### {name}\n{content}')
    return '\n\n'.join(parts) if parts else '暂无'


def _format_reply_rules(rules: list[str]) -> str:
    if not rules:
        return ''
    lines = []
    for idx, rule in enumerate(rules, 1):
        lines.append(f'{idx}. {rule}')
    return '\n'.join(lines)


def _format_recent_history(history: list[dict], limit: int = 8) -> str:
    if not history:
        return '暂无'
    items = history[-limit:]
    lines = []
    for item in items:
        role = item.get('role', 'unknown')
        content = item.get('content', '').strip()
        if len(content) > 300:
            content = content[:297] + '...'
        tag = '用户' if role == 'user' else '叙事'
        lines.append(f'[{tag}] {content}')
    return '\n'.join(lines)


def _format_active_threads(items: list[dict], limit: int = 4) -> str:
    if not items:
        return '暂无'
    lines = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('thread_id', 'thread')} / {item.get('kind', 'unknown')} / {item.get('priority', 'secondary')}: "
            f"{item.get('label', '待确认')} | 目标={item.get('goal', '待确认')} | 阻碍={item.get('obstacle', '待确认')}"
        )
    return '\n'.join(lines) if lines else '暂无'


def build_narrator_input(context: dict, user_text: str, arbiter_result: Optional[dict] = None) -> tuple[str, str]:
    scene = context.get('scene_facts', {})
    persona = context.get('persona', [])
    preset = context.get('active_preset', {})
    state_fragment = context.get('state_fragment', {}) if isinstance(context.get('state_fragment', {}), dict) else {}

    # --- 构建 system prompt 的各个区块 ---
    blocks = []

    # 1. Runtime rules（长期底板规则）
    runtime_rules = context.get('runtime_rules', '').strip()
    if runtime_rules:
        blocks.append(runtime_rules)

    # 2. 预设系统模板（世界模拟框架 + 推进规则）
    preset_template = preset.get('system_template', '').strip()
    if preset_template:
        blocks.append('【预设框架】\n' + preset_template)

    # 3. 角色核心（character-data.json）
    character_core = context.get('character_core', {})
    if character_core:
        blocks.append('【角色核心】\n' + json.dumps(character_core, ensure_ascii=False, indent=2))

    # 4. 世界书
    lorebook_text = context.get('lorebook_text', '').strip()
    if lorebook_text and lorebook_text != '暂无相关世界书条目':
        blocks.append('【世界书】\n' + lorebook_text)

    # 5. 用户层信息
    user_info = context.get('user_text', '').strip()
    if user_info:
        blocks.append('【用户层信息】\n' + user_info)

    # 6. 玩家档案
    player_md = context.get('player_profile_md', '').strip()
    player_json = context.get('player_profile_json', {})
    if player_md:
        blocks.append('【玩家档案】\n' + player_md)
    elif player_json:
        blocks.append('【玩家档案】\n' + json.dumps(player_json, ensure_ascii=False, indent=2))

    # 7. 长期事实 canon
    canon = context.get('canon', '').strip()
    if canon:
        blocks.append('【长期事实 canon】\n' + canon)

    # 8. 当前状态摘要
    blocks.append('【当前状态摘要】\n' + '\n'.join([
        f"- 时间：{scene.get('time', '待确认')}",
        f"- 地点：{scene.get('location', '待确认')}",
        f"- 主事件：{scene.get('main_event', '待确认')}",
        f"- 局势核心：{scene.get('scene_core', '待确认')}",
        f"- 在场人物：{' / '.join(scene.get('onstage_npcs', [])) or '暂无'}",
        f"- 相关人物：{' / '.join(scene.get('relevant_npcs', [])) or '暂无'}",
        f"- 当前目标：{' / '.join(scene.get('immediate_goal', [])) or '待确认'}",
        f"- 当前风险：{' / '.join(scene.get('immediate_risks', [])) or '暂无'}",
        f"- 延续线索：{' / '.join(scene.get('carryover_clues', [])) or '暂无'}",
    ]))

    # 9. 阶段摘要
    summary = context.get('summary_text', '').strip()
    if summary:
        blocks.append('【阶段摘要】\n' + summary)

    blocks.append(
        '【知情边界】\n'
        '- 主角刚看到、刚听到、刚推测到的信息，不会自动变成 NPC 已知信息。\n'
        '- NPC 只能基于自己亲眼所见、亲耳所闻、被明确告知的信息行动。\n'
        '- “看见了”“听见了”“猜到了”必须分开，不要把推测写成已知事实。\n'
        '- 若只有主角在窗边、门缝、墙后观察到某事，其他 NPC 除非有独立信息来源，否则不能直接据此说话或行动。\n'
    )

    active_threads = scene.get('active_threads', [])
    thread_text = _format_active_threads(active_threads)
    if thread_text != '暂无':
        blocks.append('【活跃线程】\n' + thread_text)

    # 10. NPC 档案内容
    npc_profiles = context.get('npc_profiles', [])
    npc_text = _format_npc_profiles(npc_profiles)
    if npc_text != '暂无':
        blocks.append('【相关 NPC 档案】\n' + npc_text)

    # 11. Onstage Persona
    persona_text = _format_persona_lines(persona)
    blocks.append('【Onstage Persona】\n' + persona_text)

    lorebook_npc_candidates = context.get('lorebook_npc_candidates', [])
    candidate_text = _format_lorebook_npc_candidates(lorebook_npc_candidates)
    if candidate_text != '暂无':
        blocks.append('【可调入世界书 NPC】\n这些人物已在世界书中存在。需要引入新的关键人物、势力接口、消息源、压力来源或旧线回流时，优先从这里选择。\n默认不要让高位或重量级人物突兀肉身进场；更自然的做法是先通过传闻、口信、命令、手下、势力痕迹、悬赏、盘查、旁人口述或后果变化把他们接入当前因果链。\n只有当地点、时机、动机和当前局势都足够合理时，才让人物本人直接出场。\n' + candidate_text)

    # 12. 近期历史
    recent_history = context.get('recent_history', [])
    history_text = _format_recent_history(recent_history)
    if history_text != '暂无':
        blocks.append('【近期历史】\n' + history_text)

    blocks.append(
        '【知情边界补充】\n'
        '- 私下发生、私下看见、私下听见、私下推测出的信息，默认只属于直接经历该信息的角色。\n'
        '- 新登场 NPC、院外 NPC、门外 NPC、后来加入场面的人，不自动知道先前屋内、窗边、墙后、门缝或私下对话里的信息。\n'
        '- 某个 NPC 是否知情，必须来自：亲眼所见、亲耳所闻、被当面告知、合理推断到的范围内。缺一不可。\n'
        '- 推测不等于实锤；旁观者知道，不等于所有在场者都知道；一个 NPC 知道，也不等于同阵营其他 NPC 自动知道。\n'
    )

    # 13. 推进规则（preset reply rules）
    reply_rules = preset.get('reply_rules', [])
    if reply_rules:
        blocks.append('【推进规则】\n' + _format_reply_rules(reply_rules))

    # 14. 裁定结果（如有）
    if arbiter_result:
        blocks.append('【本轮裁定结果】\n' + json.dumps(arbiter_result, ensure_ascii=False, indent=2))

    if state_fragment:
        blocks.append('【结构化状态锚点】\n这不是要输出给用户的内容，而是本轮叙事必须尽量服从的结构化场景锚点。若正文没有明确推翻这些事实，不要主动改写、跳场或清空。\n' + json.dumps(state_fragment, ensure_ascii=False, indent=2))

    # 15. 最终要求
    blocks.append('【要求】\n- 只输出最终 RP 正文。\n- 不复述系统提示，不输出解释。')

    system_prompt = '\n\n'.join(blocks)

    user_prompt = '\n'.join([
        '【当前用户输入】',
        user_text.strip(),
    ])

    return system_prompt, user_prompt
