#!/usr/bin/env python3
from __future__ import annotations

import json

try:
    from .persona_runtime import build_persona_seed
    from .runtime_store import load_history, load_persona_index, load_state, save_persona_seed, session_paths
except ImportError:
    from persona_runtime import build_persona_seed
    from runtime_store import load_history, load_persona_index, load_state, save_persona_seed, session_paths


SERVICE_ROLE_TOKENS = (
    '掌柜', '伙计', '小二', '老板', '船夫', '艄公', '跑堂', '脚夫', '商贩', '店伙计', '店小二', '掌舵'
)

SCENE_SEED_MIN_STREAK = 5
LONGTERM_SEED_MIN_STREAK = 7

COMMON_SURNAME_PREFIXES = set(
    '赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕张孔曹严华金魏陶姜'
    '戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐'
    '费廉岑薛雷贺倪汤滕殷罗毕郝安常乐于时傅皮卞齐康伍余元卜顾孟平黄'
    '和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董'
    '梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡'
    '凌霍虞万支柯管卢莫房裴陆沙风漠月血刑关白柳顾韩沈秦谢宋苏萧裴'
)


def _load_local_layer(directory) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not directory.exists():
        return out
    for path in sorted(directory.glob('*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        name = data.get('display_name') or data.get('npc_id') or path.stem
        if name:
            out[name] = data
    return out


def _persona_name_tokens(seed: dict) -> set[str]:
    tokens: set[str] = set()
    display = str(seed.get('display_name') or seed.get('npc_id') or '').strip()
    if display:
        tokens.add(display)
    return tokens


def _match_existing_persona(entity: dict, previous_pool: dict[str, dict]) -> tuple[str, dict] | None:
    primary = str(entity.get('primary_label', '') or '').strip()
    role_label = str(entity.get('role_label', '') or '').strip()
    aliases = {str(alias).strip() for alias in (entity.get('aliases') or []) if str(alias).strip()}
    if primary:
        aliases.add(primary)

    best_name = None
    best_seed = None
    best_score = 0.0
    for name, seed in previous_pool.items():
        seed_names = _persona_name_tokens(seed)
        score = 0.0
        if seed_names & aliases:
            score += 1.0
        seed_role = str(seed.get('identity', {}).get('role_label', '') or '').strip()
        if role_label and seed_role and role_label == seed_role:
            score += 0.5
        if score > best_score:
            best_name = name
            best_seed = seed
            best_score = score
    if best_seed and best_score >= 0.5:
        return best_name, best_seed
    return None


def _clear_local_layers(paths: dict) -> None:
    for key in ['persona_scene_dir', 'persona_archive_dir', 'persona_longterm_dir']:
        directory = paths[key]
        if not directory.exists():
            continue
        for path in directory.glob('*.json'):
            path.unlink()


def _infer_lore_identity(name: str, lorebook_candidates: list[dict]) -> dict:
    for item in lorebook_candidates or []:
        if item.get('name') != name:
            continue
        summary = (item.get('summary') or '').strip()
        title = (item.get('title') or '').strip()
        return {
            'faction': '世界书既有 NPC',
            'base_region': '待确认',
            'role_label': title.split('NPC：', 1)[1].strip() if title.startswith('NPC：') else '待确认',
            'summary': summary,
        }
    return {}


def _turn_pairs(history: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    current_user = None
    for item in history:
        role = item.get('role')
        content = item.get('content', '') or ''
        if role == 'user':
            current_user = content
        elif role == 'assistant':
            pairs.append((current_user or '', content))
            current_user = None
    return pairs


def _count_observed_turns(history: list[dict], name: str, aliases: list[str] | None = None) -> int:
    tokens = [name] + list(aliases or [])
    seen = 0
    for user_text, assistant_text in _turn_pairs(history):
        if any(token and (token in assistant_text or token in user_text) for token in tokens):
            seen += 1
    return seen


def _count_consecutive_observed_turns(history: list[dict], name: str, aliases: list[str] | None = None) -> int:
    tokens = [name] + list(aliases or [])
    streak = 0
    for user_text, assistant_text in reversed(_turn_pairs(history)):
        if any(token and (token in assistant_text or token in user_text) for token in tokens):
            streak += 1
            continue
        break
    return streak


def _count_recent_user_mentions(history: list[dict], name: str, aliases: list[str] | None = None, limit_turns: int = 6) -> int:
    tokens = [name] + list(aliases or [])
    mentions = 0
    recent_pairs = _turn_pairs(history)[-limit_turns:]
    for user_text, _assistant_text in recent_pairs:
        if any(token and token in user_text for token in tokens):
            mentions += 1
    return mentions


def _count_recent_turn_presence(history: list[dict], name: str, aliases: list[str] | None = None, limit_turns: int = 3) -> int:
    tokens = [name] + list(aliases or [])
    mentions = 0
    recent_pairs = _turn_pairs(history)[-limit_turns:]
    for user_text, assistant_text in recent_pairs:
        if any(token and (token in user_text or token in assistant_text) for token in tokens):
            mentions += 1
    return mentions


def _count_consecutive_quiet_turns(history: list[dict], name: str, aliases: list[str] | None = None) -> int:
    tokens = [name] + list(aliases or [])
    quiet = 0
    for user_text, assistant_text in reversed(_turn_pairs(history)):
        if any(token and (token in user_text or token in assistant_text) for token in tokens):
            break
        quiet += 1
    return quiet


def _is_service_npc(name: str, role_label: str) -> bool:
    combined = f'{name} {role_label}'
    return any(token in combined for token in SERVICE_ROLE_TOKENS)


def _has_proper_name(name: str) -> bool:
    cleaned = (name or '').strip()
    if not cleaned:
        return False
    if cleaned.startswith('阿') and 2 <= len(cleaned) <= 4:
        return True
    if cleaned[0] in COMMON_SURNAME_PREFIXES and 2 <= len(cleaned) <= 4:
        return True
    for token in SERVICE_ROLE_TOKENS:
        if token in cleaned and cleaned != token:
            prefix = cleaned.split(token, 1)[0].strip()
            if prefix and (prefix[0] in COMMON_SURNAME_PREFIXES or prefix.startswith('阿')):
                return True
    return False


def _is_worldbook_priority(name: str, lorebook_candidates: list[dict], previous: dict) -> bool:
    if any((item.get('name') or '').strip() == name for item in (lorebook_candidates or [])):
        return True
    return previous.get('identity', {}).get('faction') == '世界书既有 NPC'


def _is_clue_bearer(entity: dict, state: dict, history: list[dict]) -> bool:
    name = (entity.get('primary_label') or '').strip()
    aliases = entity.get('aliases', []) or []
    tokens = [name] + aliases
    scene_text_parts = [
        state.get('main_event', ''),
        state.get('scene_core', ''),
        ' '.join(state.get('immediate_risks', []) or []),
        ' '.join(state.get('carryover_clues', []) or []),
        entity.get('role_label', ''),
        entity.get('possible_link', '') or '',
    ]
    recent_pairs = _turn_pairs(history)[-3:]
    for user_text, assistant_text in recent_pairs:
        scene_text_parts.append(user_text)
        scene_text_parts.append(assistant_text)
    haystack = '\n'.join(part for part in scene_text_parts if part)
    clue_keywords = (
        '线索', '可疑', '当事人', '后院', '房间', '空出来', '押钱', '走得急', '门闩', '钥匙',
        '盘查', '巡街', '监视', '盯', '人影', '搜查', '追索', '命令', '口信', '痕迹'
    )
    has_entity_presence = any(token and token in haystack for token in tokens)
    has_clue_signal = any(keyword in haystack for keyword in clue_keywords)
    return has_entity_presence and has_clue_signal


def update_persona(session_id: str, lorebook_candidates: list[dict] | None = None) -> dict:
    state = load_state(session_id)
    history = load_history(session_id)
    paths = session_paths(session_id)
    inherited = load_persona_index(session_id)
    current_scene_signature = f"{state.get('location', '')}||{state.get('main_event', '')}"

    local_scene = _load_local_layer(paths['persona_scene_dir'])
    local_archive = _load_local_layer(paths['persona_archive_dir'])
    local_longterm = _load_local_layer(paths['persona_longterm_dir'])
    local_existing = {**local_archive, **local_scene, **local_longterm}

    onstage_names = list(state.get('onstage_npcs', []) or [])
    relevant_names = list(state.get('relevant_npcs', []) or [])
    entities = list(state.get('scene_entities', []) or [])
    important_names = {
        str(item.get('primary_label', '') or '').strip()
        for item in (state.get('important_npcs', []) or [])
        if isinstance(item, dict) and item.get('locked')
    }
    known_names = {(entity.get('primary_label') or '').strip() for entity in entities}

    for name in onstage_names + relevant_names:
        if not name or name in known_names:
            continue
        inherited_seed = inherited.get(name, {})
        lore_identity = _infer_lore_identity(name, lorebook_candidates or [])
        entities.append({
            'primary_label': name,
            'aliases': [name],
            'role_label': inherited_seed.get('identity', {}).get('role_label') or lore_identity.get('role_label') or '待确认',
            'onstage': name in onstage_names,
            'possible_link': None,
        })

    next_layers = {'scene': {}, 'archive': {}, 'longterm': {}}
    active_names: set[str] = set()

    for entity in entities:
        name = (entity.get('primary_label') or '').strip()
        if not name:
            continue
        matched = _match_existing_persona(entity, {**local_existing, **inherited})
        if matched is not None:
            matched_name, matched_seed = matched
            if matched_name != name:
                name = matched_name
                entity['primary_label'] = matched_name
        active_names.add(name)
        role_label = (entity.get('role_label') or '待确认').strip()
        previous = local_existing.get(name) or inherited.get(name) or {}
        prev_turns = int(previous.get('importance', {}).get('appearance_turns', 0) or 0)
        prev_dormant = int(previous.get('importance', {}).get('dormant_turns', 0) or 0)
        is_onstage = bool(entity.get('onstage')) or name in onstage_names
        is_relevant = is_onstage or name in relevant_names
        observed_turns = _count_observed_turns(history, name, entity.get('aliases', []))
        consecutive_turns = _count_consecutive_observed_turns(history, name, entity.get('aliases', []))
        recent_user_focus = _count_recent_user_mentions(history, name, entity.get('aliases', []))
        recent_turn_presence = _count_recent_turn_presence(history, name, entity.get('aliases', []))
        quiet_turns = _count_consecutive_quiet_turns(history, name, entity.get('aliases', []))
        turns = max(prev_turns, observed_turns, consecutive_turns, 1)
        dormant_turns = 0 if is_relevant else prev_dormant + 1
        lore_identity = _infer_lore_identity(name, lorebook_candidates or [])
        generic_service_npc = _is_service_npc(name, role_label) and not _has_proper_name(name)
        worldbook_priority = _is_worldbook_priority(name, lorebook_candidates or [], previous)
        important_lock = name in important_names
        clue_bearer = _is_clue_bearer(entity, state, history)
        user_focus_priority = recent_user_focus >= 2
        previous_scene_signature = previous.get('source_window', {}).get('scene_signature', '')
        scene_changed = bool(previous_scene_signature) and previous_scene_signature != current_scene_signature
        retention_grace = bool(previous) and not is_onstage and recent_turn_presence >= 1 and quiet_turns <= 1
        interaction_grace = bool(previous) and is_relevant and (recent_user_focus >= 1 or recent_turn_presence >= 2 or retention_grace)
        early_seed_reason = None
        if user_focus_priority:
            early_seed_reason = '用户已连续多轮主动关注该人物，提前保留 scene 骨架。'
        elif worldbook_priority and is_relevant:
            early_seed_reason = '该人物来自世界书既有重要人物层，且已进入当前局势。'
        elif clue_bearer and is_relevant:
            early_seed_reason = '该人物正在承载当前场景的可疑点或线索链，提前保留 scene 骨架。'
        elif interaction_grace:
            early_seed_reason = '该人物虽未必仍是主线索承载者，但当前仍与用户或场景持续互动，暂时保留 scene 骨架。'
        exceptional_seed = bool(early_seed_reason)

        should_seed = False
        if important_lock and not generic_service_npc:
            should_seed = True
        elif (previous.get('seed_layer') == 'longterm' or name in local_longterm) and not generic_service_npc:
            should_seed = True
        elif consecutive_turns >= SCENE_SEED_MIN_STREAK:
            should_seed = True
        elif exceptional_seed:
            should_seed = True
        if generic_service_npc and not exceptional_seed:
            should_seed = False
        if not should_seed:
            if previous and scene_changed and quiet_turns >= 2 and not is_onstage and not generic_service_npc:
                next_layers['archive'][name] = build_persona_seed(
                    name,
                    role_label,
                    layer='archive',
                    previous=previous,
                    appearance_turns=turns,
                    dormant_turns=max(dormant_turns, 1),
                    onstage=False,
                    relevant=False,
                    identity_overrides={
                        'faction': lore_identity.get('faction'),
                        'base_region': lore_identity.get('base_region'),
                    },
                    scene_signature=current_scene_signature,
                    reason_suffix=f'场景已切换，且已连续 {quiet_turns} 轮无互动，降为 archive。',
                )
            continue

        if important_lock and not generic_service_npc:
            layer = 'longterm' if is_relevant or is_onstage else 'scene'
        elif (previous.get('seed_layer') == 'longterm' or name in local_longterm) and not generic_service_npc:
            layer = 'longterm' if is_relevant else 'archive'
        elif consecutive_turns >= LONGTERM_SEED_MIN_STREAK:
            layer = 'longterm' if is_relevant else 'archive'
        elif is_relevant:
            layer = 'scene'
        else:
            layer = 'archive'

        if not is_relevant and dormant_turns >= 4 and previous.get('seed_layer') == 'archive':
            continue

        next_layers[layer][name] = build_persona_seed(
            name,
            role_label,
            layer=layer,
            previous=previous,
            appearance_turns=turns,
            dormant_turns=dormant_turns,
            onstage=is_onstage,
            relevant=is_relevant,
            identity_overrides={
                'faction': lore_identity.get('faction'),
                'base_region': lore_identity.get('base_region'),
            },
            scene_signature=current_scene_signature,
            reason_suffix=early_seed_reason or '当前由 Threadloom session-local persona 流转维护。',
        )

    for name, previous in local_existing.items():
        if name in active_names:
            continue
        role_label = previous.get('identity', {}).get('role_label', '待确认')
        turns = int(previous.get('importance', {}).get('appearance_turns', 1) or 1)
        dormant_turns = int(previous.get('importance', {}).get('dormant_turns', 0) or 0) + 1
        if dormant_turns >= 4 and previous.get('seed_layer') == 'archive':
            continue
        next_layers['archive'][name] = build_persona_seed(
            name,
            role_label,
            layer='archive',
            previous=previous,
            appearance_turns=turns,
            dormant_turns=dormant_turns,
            onstage=False,
            relevant=False,
            scene_signature=current_scene_signature,
            reason_suffix='本轮未继续在场或 relevant，转入 archive。',
        )

    _clear_local_layers(paths)
    counts = {}
    for layer, items in next_layers.items():
        counts[layer] = len(items)
        for seed in items.values():
            save_persona_seed(session_id, layer, seed)
    return counts
