#!/usr/bin/env python3
import json
import re
from typing import Optional


def prompt_block_stats(system_prompt: str) -> list[dict]:
    parts = re.split(r'\n\n(?=【)', str(system_prompt or ''))
    stats: list[dict] = []
    for part in parts:
        head = part.split('\n', 1)[0].strip()
        if head.startswith('【') and '】' in head:
            body = part[len(head):].lstrip('\n')
            stats.append({
                'label': head,
                'chars': len(body),
            })
    return stats


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


def _format_system_npc_candidates(items: list[dict], limit: int = 6) -> str:
    if not items:
        return '暂无'
    lines = []
    for item in items[:limit]:
        summary = (item.get('summary') or '').strip()
        if len(summary) > 220:
            summary = summary[:217] + '...'
        role = str(item.get('role_label', '') or '').strip()
        faction = str(item.get('faction', '') or '').strip()
        meta_parts = [part for part in (role, faction) if part]
        meta = f" / {' / '.join(meta_parts)}" if meta_parts else ''
        lines.append(f"- {item.get('name')}{meta}: {summary or '系统级既有角色，可在合适时机通过消息、势力、本人或他人提及接入。'}")
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


def _format_knowledge_scope(scope: dict) -> str:
    """将 knowledge_scope 格式化为叙述者可读的结构化文本。"""
    if not isinstance(scope, dict) or not scope:
        return ''
    lines = []
    protagonist = scope.get('protagonist', {})
    if isinstance(protagonist, dict):
        learned = protagonist.get('learned', [])
        if isinstance(learned, list) and learned:
            recent = learned[-8:]  # 只展示最近 8 条
            lines.append('主角已知信息：')
            for item in recent:
                lines.append(f'  - {item}')
    npc_local = scope.get('npc_local', {})
    if isinstance(npc_local, dict):
        for name, data in npc_local.items():
            if not isinstance(data, dict):
                continue
            learned = data.get('learned', [])
            if isinstance(learned, list) and learned:
                recent = learned[-5:]
                lines.append(f'{name}已知信息：')
                for item in recent:
                    lines.append(f'  - {item}')
    return '\n'.join(lines)


def _format_knowledge_records(records: list[dict], actors: dict, limit: int = 16) -> str:
    if not isinstance(records, list) or not records:
        return ''
    actor_names = {}
    if isinstance(actors, dict):
        for actor_id, actor in actors.items():
            if isinstance(actor, dict):
                actor_names[str(actor_id)] = str(actor.get('name', '') or actor_id)
    lines = []
    for item in records[-limit:]:
        if not isinstance(item, dict):
            continue
        actor_id = str(item.get('holder_actor_id', '') or '').strip()
        text = str(item.get('text', '') or '').strip()
        if actor_id and text:
            lines.append(f"- {actor_names.get(actor_id, actor_id)}({actor_id}) 知道：{text}")
    return '\n'.join(lines)


def _format_actor_registry(actors: dict, context_index: dict, limit: int = 8) -> str:
    if not isinstance(actors, dict) or not actors:
        return '暂无'
    active_ids = context_index.get('active_actor_ids', []) if isinstance(context_index, dict) else []
    archived_ids = set(context_index.get('archived_actor_ids', []) if isinstance(context_index, dict) else [])
    ordered_ids = [actor_id for actor_id in active_ids if actor_id in actors]
    for actor_id in actors:
        if actor_id not in ordered_ids and actor_id not in archived_ids:
            ordered_ids.append(actor_id)
    lines = []
    for actor_id in ordered_ids[:limit]:
        actor = actors.get(actor_id, {})
        if not isinstance(actor, dict):
            continue
        name = str(actor.get('name', '') or '').strip()
        if not name:
            continue
        aliases = [str(alias).strip() for alias in (actor.get('aliases', []) or []) if str(alias).strip() and str(alias).strip() != name][:4]
        parts = []
        identity = str(actor.get('identity', '') or '').strip()
        personality = str(actor.get('personality', '') or '').strip()
        appearance = str(actor.get('appearance', '') or '').strip()
        if identity:
            parts.append(f"身份={identity}")
        if personality:
            parts.append(f"性格={personality}")
        if appearance:
            parts.append(f"外貌={appearance}")
        if aliases:
            parts.append(f"别称={' / '.join(aliases)}")
        suffix = '；'.join(parts) if parts else '基础设定未补全'
        lines.append(f"- {actor_id} / {name}：{suffix}")
    return '\n'.join(lines) if lines else '暂无'


def _format_summary_chunks(chunks: list[dict], limit: int = 2) -> str:
    if not isinstance(chunks, list) or not chunks:
        return '暂无'
    blocks = []
    for chunk in chunks[:limit]:
        if not isinstance(chunk, dict):
            continue
        lines = [f"### {chunk.get('chunk_id', 'chunk')} / turn {chunk.get('turn_start', '?')}-{chunk.get('turn_end', '?')}"]
        dense = chunk.get('dense_summary', []) if isinstance(chunk.get('dense_summary', []), list) else []
        for item in dense[:18]:
            text = str(item or '').strip()
            if text:
                lines.append(f"- {text}")
        unresolved = chunk.get('unresolved', []) if isinstance(chunk.get('unresolved', []), list) else []
        if unresolved:
            lines.append('未解：' + ' / '.join(str(item or '').strip() for item in unresolved[:8] if str(item or '').strip()))
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks) if blocks else '暂无'


def _clean_preset_template(text: str) -> str:
    value = str(text or '').strip()
    if not value:
        return ''
    # Presets may still carry old placeholder sections that duplicate or
    # contradict the runtime-first context blocks assembled below.
    value = re.sub(
        r'\n*【[^】]+】\n\{\{(?:character_core|canon|state|summary|lorebook)\}\}\n*',
        '\n',
        value,
    )
    value = re.sub(r'\n{3,}', '\n\n', value)
    return value.strip()


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


def _format_recent_window(history: list[dict], limit_pairs: int = 6) -> str:
    if not history:
        return '暂无'
    pairs = []
    current_user = None
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        if role == 'user':
            current_user = item
        elif role == 'assistant' and current_user is not None:
            pairs.append((current_user, item))
            current_user = None
    pairs = pairs[-limit_pairs:]
    if not pairs:
        return '暂无'
    lines = []
    for user_item, assistant_item in pairs:
        user_text = str(user_item.get('content', '') or '').strip()
        assistant_text = str(assistant_item.get('content', '') or '').strip()
        if len(user_text) > 180:
            user_text = user_text[:177] + '...'
        if len(assistant_text) > 260:
            assistant_text = assistant_text[:257] + '...'
        lines.append(f"[用户] {user_text}")
        lines.append(f"[叙事] {assistant_text}")
    return '\n'.join(lines)


def _format_keeper_records(bundle: dict, limit: int = 4) -> str:
    if not isinstance(bundle, dict):
        return '暂无'
    records = bundle.get('records', []) if isinstance(bundle.get('records', []), list) else []
    if not records:
        return '暂无'
    lines = []
    for item in records[:limit]:
        if not isinstance(item, dict):
            continue
        window = item.get('window', {}) if isinstance(item.get('window', {}), dict) else {}
        stable_entities = item.get('stable_entities', []) if isinstance(item.get('stable_entities', []), list) else []
        ongoing_events = item.get('ongoing_events', []) if isinstance(item.get('ongoing_events', []), list) else []
        tracked_objects = item.get('tracked_objects', []) if isinstance(item.get('tracked_objects', []), list) else []
        entity_text = ' / '.join(
            str(entity.get('name', '') or '').strip()
            for entity in stable_entities[:6]
            if isinstance(entity, dict) and str(entity.get('name', '') or '').strip()
        ) or '暂无'
        thread_text = ' / '.join(str(text or '').strip() for text in ongoing_events[:3] if str(text or '').strip()) or '暂无'
        object_text = ' / '.join(
            str(obj.get('label', '') or '').strip()
            for obj in tracked_objects[:4]
            if isinstance(obj, dict) and str(obj.get('label', '') or '').strip()
        ) or '暂无'
        lines.append(
            f"- {window.get('from_turn', 'unknown')}..{window.get('to_turn', 'unknown')} | 地点={item.get('location_anchor', '待确认')} | 人物={entity_text} | 事件={thread_text} | 物件={object_text}"
        )
    return '\n'.join(lines) if lines else '暂无'


def _format_npc_registry(bundle: dict) -> str:
    if not isinstance(bundle, dict):
        return '暂无'
    lines = []
    for item in (bundle.get('entities', []) or [])[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get('canonical_name', '') or '').strip()
        if not name:
            continue
        role = str(item.get('role_label', '') or '待确认').strip() or '待确认'
        aliases = [str(alias).strip() for alias in (item.get('aliases', []) or []) if str(alias).strip() and str(alias).strip() != name][:4]
        alias_text = f" / 别称={' / '.join(aliases)}" if aliases else ''
        lines.append(f"- {name} / {role}{alias_text}")
    return '\n'.join(lines) if lines else '暂无'


def _format_mid_window_digest(bundle: dict) -> str:
    if not isinstance(bundle, dict) or not bundle:
        return '暂无'
    lines = []
    if bundle.get('time_anchor'):
        lines.append(f"- 时间锚点：{bundle.get('time_anchor')}")
    if bundle.get('location_anchor'):
        lines.append(f"- 地点锚点：{bundle.get('location_anchor')}")
    entities = bundle.get('stable_entities', []) if isinstance(bundle.get('stable_entities', []), list) else []
    if entities:
        lines.append('- 持续人物：' + ' / '.join(
            f"{item.get('name')}({item.get('role', '待确认')})"
            for item in entities[:5]
            if isinstance(item, dict) and item.get('name')
        ))
    events = bundle.get('ongoing_events', []) if isinstance(bundle.get('ongoing_events', []), list) else []
    for item in events[:3]:
        lines.append(f"- 持续事件：{item}")
    loops = bundle.get('open_loops', []) if isinstance(bundle.get('open_loops', []), list) else []
    for item in loops[:3]:
        lines.append(f"- 未决点：{item}")
    return '\n'.join(lines) if lines else '暂无'


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


def _format_tracked_objects(objects: list[dict], possession: list[dict], visibility: list[dict], limit: int = 6) -> str:
    if not objects:
        return '暂无'
    possession_by_id = {
        str(item.get('object_id', '') or '').strip(): item
        for item in possession or []
        if isinstance(item, dict) and str(item.get('object_id', '') or '').strip()
    }
    visibility_by_id = {
        str(item.get('object_id', '') or '').strip(): item
        for item in visibility or []
        if isinstance(item, dict) and str(item.get('object_id', '') or '').strip()
    }
    lines = []
    for item in objects[:limit]:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get('object_id', '') or '').strip()
        label = str(item.get('label', '') or '').strip()
        kind = str(item.get('kind', '') or 'item').strip() or 'item'
        holder = possession_by_id.get(object_id, {}).get('holder', '待确认')
        status = possession_by_id.get(object_id, {}).get('status', '待确认')
        visibility_label = visibility_by_id.get(object_id, {}).get('visibility', '待确认')
        lines.append(f"- {label} ({kind}) / 持有者={holder} / 状态={status} / 可见性={visibility_label}")
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
    preset_template = _clean_preset_template(preset.get('system_template', ''))
    if preset_template:
        blocks.append('【预设框架】\n' + preset_template)

    # 3. 角色核心（character-data.json）
    character_core = context.get('character_core', {})
    if character_core:
        blocks.append('【角色核心】\n' + json.dumps(character_core, ensure_ascii=False, indent=2))

    # 4. 玩家档案
    player_md = context.get('player_profile_md', '').strip()
    player_json = context.get('player_profile_json', {})
    if player_md:
        blocks.append('【玩家档案】\n' + player_md)
    elif player_json:
        blocks.append('【玩家档案】\n' + json.dumps(player_json, ensure_ascii=False, indent=2))

    # 知情边界：结构化版本 + 通用规则
    knowledge_scope = scene.get('knowledge_scope', {})
    ks_lines = _format_knowledge_scope(knowledge_scope)
    kr_lines = _format_knowledge_records(scene.get('knowledge_records', []), scene.get('actors', {}))
    blocks.append(
        '【知情边界】\n'
        '- 本块属于强约束层，优先级高于候选知识与旧记录。\n'
        '- 主角刚看到、刚听到、刚推测到的信息，不会自动变成 NPC 已知信息。\n'
        '- NPC 只能基于自己亲眼所见、亲耳所闻、被明确告知的信息行动。\n'
        '- “看见了”“听见了”“猜到了”必须分开，不要把推测写成已知事实。\n'
        '- 若只有主角在窗边、门缝、墙后观察到某事，其他 NPC 除非有独立信息来源，否则不能直接据此说话或行动。\n'
        + (('\n' + ks_lines) if ks_lines else '')
        + (('\n' + kr_lines) if kr_lines else '')
    )

    actor_text = _format_actor_registry(scene.get('actors', {}), scene.get('actor_context_index', {}))
    if actor_text != '暂无':
        blocks.append(
            '【角色注册表】\n'
            '本块是长期角色基础设定表。角色的姓名、别称、性格、外貌、身份一旦登记就视为锁定；不要在正文中随意改写。\n'
            '本块不表示这些角色当前在场，也不记录受伤、被困、离场等短期状态。当前局势以最近12轮和本轮用户输入为准。\n'
            + actor_text
        )

    selected_chunks = context.get('selected_summary_chunks', [])
    chunk_text = _format_summary_chunks(selected_chunks)
    if chunk_text != '暂无':
        blocks.append('【召回的12轮外历史】\n本块来自固定分段 summary chunk，只用于补充最近12轮之外的历史；不得覆盖最近12轮和本轮用户输入。\n' + chunk_text)

    # 9. 最近 12 轮窗口
    recent_history = context.get('recent_history', [])
    recent_window_text = _format_recent_window(recent_history, limit_pairs=12)
    if recent_window_text != '暂无':
        blocks.append('【最近12轮完整上下文】\n本块是当前场景最优先参考的事实来源。若与角色注册表、物品/情报账本、旧summary或世界书候选冲突，以最近12轮和本轮用户输入为准。\n' + recent_window_text)

    # 10. 重要物件
    object_text = _format_tracked_objects(
        scene.get('tracked_objects', []),
        scene.get('possession_state', []),
        scene.get('object_visibility', []),
    )
    if object_text != '暂无':
        blocks.append('【重要物件与持有关系】\n本块是物品账本，只说明持续物件、持有关系与可见性；当前动作和短期位置以最近12轮为准。\n' + object_text)

    # 14. 系统级 / 世界书候选
    lorebook_npc_candidates = context.get('lorebook_npc_candidates', [])
    system_npc_candidates = context.get('system_npc_candidates', [])
    system_candidate_text = _format_system_npc_candidates(system_npc_candidates)
    if system_candidate_text != '暂无':
        blocks.append('【系统级 NPC】\n本块属于 selector 命中的候选知识层，只表示他们在世界中稳定存在，不表示他们此刻已经在场。若与最近12轮或知情边界冲突，一律以后者为准。\n' + system_candidate_text)

    candidate_text = _format_lorebook_npc_candidates(lorebook_npc_candidates)
    if candidate_text != '暂无':
        blocks.append('【可调入世界书 NPC】\n本块属于 selector 命中的候选知识层。这些人物已在世界书中存在，但不是当前场景事实。需要引入时优先通过传闻、口信、命令、手下、势力痕迹、悬赏、盘查、旁人口述或后果变化接入。若与最近12轮或知情边界冲突，一律以后者为准。\n' + candidate_text)

    foundation_text = context.get('lorebook_foundation_text', '').strip()
    if foundation_text:
        blocks.append('【世界书基础规则】\n本块是导入时蒸馏出的常驻瘦身世界书，只提供世界认知、身份边界、势力/规则口径的参考；它不是当前场景事实源，不得覆盖最近12轮的当前动作、位置、短期状态和知情边界。\n' + foundation_text)

    # 15. 世界书正文放后，避免压过最近窗口
    lorebook_text = context.get('lorebook_text', '').strip()
    if lorebook_text and lorebook_text != '暂无相关世界书条目':
        blocks.append('【情境世界书】\n本块只包含 selector 命中的蒸馏世界书条目，用于补世界规则、势力背景与场景解释；不自动等于当前场景事实，更不能压过最近12轮与知情边界。\n' + lorebook_text)

    blocks.append(
        '【知情边界补充】\n'
        '- 私下发生、私下看见、私下听见、私下推测出的信息，默认只属于直接经历该信息的角色。\n'
        '- 新登场 NPC、院外 NPC、门外 NPC、后来加入场面的人，不自动知道先前屋内、窗边、墙后、门缝或私下对话里的信息。\n'
        '- 某个 NPC 是否知情，必须来自：亲眼所见、亲耳所闻、被当面告知、合理推断到的范围内。缺一不可。\n'
        '- 推测不等于实锤；旁观者知道，不等于所有在场者都知道；一个 NPC 知道，也不等于同阵营其他 NPC 自动知道。\n'
    )

    # 17. 推进规则（preset reply rules）
    reply_rules = preset.get('reply_rules', [])
    if reply_rules:
        blocks.append('【推进规则】\n' + _format_reply_rules(reply_rules))

    # 18. 裁定结果（如有）
    if arbiter_result:
        blocks.append('【本轮裁定结果】\n' + json.dumps(arbiter_result, ensure_ascii=False, indent=2))

    # state_fragment is intentionally not sent to narrator; recent 12 turns are the current truth source.

    # 17. 最终要求
    blocks.append(
        '【要求】\n'
        '- 只输出最终 RP 正文。\n'
        '- 不复述系统提示，不输出解释。\n'
        '- 即使本轮处于回屋、关门、换位、烧水、整理、短暂观察等过渡段，也不要塌成一句摘要。至少写出具体环境变化、人物反应、动作后的余波，或场景中正在累积的细节变化，让场景继续“活着”。\n'
        '- 只有当当前局势本来就存在追索、怀疑、风险、未决冲突或逼近感时，才继续强化压力；不要为了“有戏”而每轮硬塞危险感。'
    )

    system_prompt = '\n\n'.join(blocks)

    user_prompt = '\n'.join([
        '【当前用户输入】',
        user_text.strip(),
    ])

    return system_prompt, user_prompt
