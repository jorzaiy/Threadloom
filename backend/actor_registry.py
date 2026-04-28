#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from copy import deepcopy

try:
    from .llm_manager import call_role_llm
    from .local_model_client import parse_json_response
    from .name_sanitizer import sanitize_runtime_name, is_protagonist_name, protagonist_names, looks_like_bad_entity_fragment
except ImportError:
    from llm_manager import call_role_llm
    from local_model_client import parse_json_response
    from name_sanitizer import sanitize_runtime_name, is_protagonist_name, protagonist_names, looks_like_bad_entity_fragment


ARCHIVE_AFTER_QUIET_TURNS = 12


ACTOR_REGISTRY_SYSTEM = """你是 narrator 生成后的角色注册表维护器。

只输出 JSON，不要解释。

你的任务：从本轮 narrator 正文里找出新登场、值得长期保持基础设定一致的人物，并为他们创建不可变 actor 基础设定。

输出格式：
{
  "new_actors": [
    {
      "name": "角色稳定称呼或姓名",
      "aliases": ["正文里的其他称呼"],
      "personality": "只写正文已表现出的稳定性格，未知则空字符串",
      "appearance": "只写正文已明确给出的稳定外貌，未知则空字符串",
      "identity": "只写正文已明确暴露的身份，未知则空字符串"
    }
  ]
}

规则：
1. 只创建新 actor，不修改已有 actor。
2. 已有 actor 的姓名、别称、性格、外貌、身份都视为锁定，不能重写。
3. 不记录是否在场、受伤、被围、昏迷、离开、当前位置等短期状态。
4. 不要把主角、玩家、你、我登记为 NPC。
5. 不要登记背景群体、路人群、势力名、地点、物品、抽象概念。
6. 如果只是“一名差役”“几个皂衣人”这类一次性功能人且没有稳定个体特征，可以不登记。
7. 但如果某个匿名称呼在连续回合承担明确行动链、关系压力或信息承载功能，即使真名未知，也要用正文中的稳定称呼登记，以便后续保持基础称呼、外貌和身份口径一致。
8. 不确定就少输出。
"""


def _clean_text(value: object, limit: int = 120) -> str:
    text = str(value or '').strip()
    text = re.sub(r'\s+', ' ', text)
    return text[:limit]


def _knowledge_tokens(value: str) -> set[str]:
    text = _clean_text(value, 200)
    text = re.sub(r'[，。！？、；：,.!?;:\s"“”‘’（）()【】\[\]]+', '', text)
    for token in ('知道', '得知', '了解到', '了解', '发现', '看出', '获知', '意识到'):
        text = text.replace(token, '')
    tokens = set(re.findall(r'[\u4e00-\u9fff]{2,4}|[A-Za-z][A-Za-z0-9_-]{1,20}', text))
    if not tokens and text:
        tokens = {text[idx:idx + 2] for idx in range(max(0, len(text) - 1))}
    return {token for token in tokens if token}


def _knowledge_bigrams(value: str) -> set[str]:
    text = _clean_text(value, 200)
    text = re.sub(r'[，。！？、；：,.!?;:\s"“”‘’（）()【】\[\]]+', '', text)
    for token in ('知道', '得知', '了解到', '了解', '发现', '看出', '获知', '意识到', '主角'):
        text = text.replace(token, '')
    return {text[idx:idx + 2] for idx in range(max(0, len(text) - 1)) if text[idx:idx + 2]}


def _knowledge_similar(left: str, right: str) -> bool:
    left_text = _clean_text(left, 200)
    right_text = _clean_text(right, 200)
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    if left_text in right_text or right_text in left_text:
        return min(len(left_text), len(right_text)) >= 6
    left_tokens = _knowledge_tokens(left_text)
    right_tokens = _knowledge_tokens(right_text)
    if left_tokens and right_tokens:
        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        if union > 0 and intersection / union >= 0.6:
            return True
    left_bigrams = _knowledge_bigrams(left_text)
    right_bigrams = _knowledge_bigrams(right_text)
    if not left_bigrams or not right_bigrams:
        return False
    intersection = len(left_bigrams & right_bigrams)
    union = len(left_bigrams | right_bigrams)
    return union > 0 and intersection / union >= 0.25


def _actor_name(actor: dict) -> str:
    return sanitize_runtime_name(actor.get('name', ''))


def _actor_aliases(actor: dict) -> list[str]:
    out: list[str] = []
    for item in actor.get('aliases', []) or []:
        name = sanitize_runtime_name(item)
        if name and name not in out:
            out.append(name)
    return out


def _actor_names(actor: dict) -> set[str]:
    names = set(_actor_aliases(actor))
    name = _actor_name(actor)
    if name:
        names.add(name)
    return names


def _ensure_protagonist(actors: dict, player_name: str = '') -> None:
    aliases = ['你', '主角']
    cleaned_player = sanitize_runtime_name(player_name)
    if cleaned_player and cleaned_player not in aliases:
        aliases.append(cleaned_player)
    existing = actors.get('protagonist') if isinstance(actors.get('protagonist'), dict) else {}
    existing_aliases = _actor_aliases(existing)
    for alias in aliases:
        if alias not in existing_aliases:
            existing_aliases.append(alias)
    actors['protagonist'] = {
        'actor_id': 'protagonist',
        'kind': 'protagonist',
        'name': existing.get('name') or cleaned_player or '主角',
        'aliases': existing_aliases or aliases,
        'personality': existing.get('personality', ''),
        'appearance': existing.get('appearance', ''),
        'identity': existing.get('identity') or '主角',
        'created_turn': int(existing.get('created_turn', 1) or 1),
    }


def _next_actor_id(actors: dict) -> str:
    max_idx = 0
    for actor_id in actors:
        if not str(actor_id).startswith('npc_'):
            continue
        try:
            max_idx = max(max_idx, int(str(actor_id).split('_', 1)[1]))
        except Exception:
            continue
    return f'npc_{max_idx + 1:03d}'


def _find_actor_id_by_name(actors: dict, name: str) -> str:
    cleaned = sanitize_runtime_name(name)
    if not cleaned:
        return ''
    if is_protagonist_name(cleaned) or cleaned in protagonist_names():
        return 'protagonist'
    for actor_id, actor in actors.items():
        if isinstance(actor, dict) and cleaned in _actor_names(actor):
            return str(actor_id)
    return ''


def _valid_actor_candidate(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    name = sanitize_runtime_name(item.get('name', ''))
    if not name or is_protagonist_name(name) or looks_like_bad_entity_fragment(name):
        return None
    aliases = []
    for alias in item.get('aliases', []) or []:
        alias_name = sanitize_runtime_name(alias)
        if alias_name and alias_name != name and not is_protagonist_name(alias_name) and alias_name not in aliases:
            aliases.append(alias_name)
    return {
        'name': name,
        'aliases': aliases[:6],
        'personality': _clean_text(item.get('personality', ''), 80),
        'appearance': _clean_text(item.get('appearance', ''), 120),
        'identity': _clean_text(item.get('identity', ''), 80),
    }


def _extract_actor_candidates_with_llm(existing_actors: dict, narrator_reply: str, *, user_text: str = '', recent_pairs: list[tuple[str, str]] | None = None) -> tuple[list[dict], dict | None, dict | None]:
    existing = []
    for actor in existing_actors.values():
        if not isinstance(actor, dict) or actor.get('kind') == 'protagonist':
            continue
        existing.append({
            'actor_id': actor.get('actor_id'),
            'name': actor.get('name'),
            'aliases': actor.get('aliases', []),
        })
    user_prompt = json.dumps({
        'existing_locked_actors': existing[:40],
        'recent_turn_pairs': [
            {'user': user, 'assistant': assistant}
            for user, assistant in (recent_pairs or [])[-3:]
        ],
        'current_turn': {
            'user_text': user_text,
            'narrator_reply': narrator_reply,
        },
    }, ensure_ascii=False, indent=2)
    reply = ''
    usage = None
    try:
        reply, usage = call_role_llm('state_keeper_candidate', ACTOR_REGISTRY_SYSTEM, user_prompt)
    except Exception as err:
        return [], usage if isinstance(usage, dict) else None, {'error': str(err)}
    try:
        payload = parse_json_response(reply)
    except Exception as err:
        raw_reply = str(reply or '')
        return [], usage if isinstance(usage, dict) else None, {
            'error': str(err),
            'raw_reply_empty': not bool(raw_reply.strip()),
            'raw_reply_excerpt': raw_reply[:500],
        }
    raw_items = payload.get('new_actors', []) if isinstance(payload, dict) else []
    candidates = []
    for item in raw_items if isinstance(raw_items, list) else []:
        candidate = _valid_actor_candidate(item)
        if candidate:
            candidates.append(candidate)
    return candidates, usage if isinstance(usage, dict) else {}, None


def _candidate_overlaps_existing_actor(candidate: dict, actors: dict, state: dict) -> bool:
    names = {candidate.get('name', '')} | set(candidate.get('aliases', []) or [])
    names = {sanitize_runtime_name(name) for name in names if sanitize_runtime_name(name)}
    if not names:
        return True
    for actor in actors.values():
        if isinstance(actor, dict) and names & _actor_names(actor):
            return True
    for entity in state.get('scene_entities', []) or []:
        if not isinstance(entity, dict):
            continue
        entity_names = _actor_names({'name': entity.get('primary_label', ''), 'aliases': entity.get('aliases', [])})
        if not names & entity_names:
            continue
        if any(entity_names & _actor_names(actor) for actor in actors.values() if isinstance(actor, dict)):
            return True
    return False


def _fallback_actor_candidates(_state: dict) -> list[dict]:
    return []


def _mentioned_actor_ids(actors: dict, text: str) -> set[str]:
    mentioned: set[str] = set()
    haystack = str(text or '')
    if not haystack:
        return mentioned
    for actor_id, actor in actors.items():
        if not isinstance(actor, dict):
            continue
        if actor_id == 'protagonist':
            mentioned.add('protagonist')
            continue
        if any(name and name in haystack for name in _actor_names(actor)):
            mentioned.add(str(actor_id))
    return mentioned


def _normalize_actor_context_index(state: dict, actors: dict, turn_number: int, mentioned: set[str]) -> dict:
    previous = state.get('actor_context_index', {}) if isinstance(state.get('actor_context_index', {}), dict) else {}
    last = previous.get('last_mentioned_turn', {}) if isinstance(previous.get('last_mentioned_turn', {}), dict) else {}
    last_map: dict[str, int] = {}
    for actor_id in actors:
        if actor_id == 'protagonist':
            last_map[actor_id] = turn_number
            continue
        try:
            previous_turn = int(last.get(actor_id, actors[actor_id].get('created_turn', turn_number)) or turn_number)
        except Exception:
            previous_turn = turn_number
        last_map[actor_id] = turn_number if actor_id in mentioned else previous_turn
    active = ['protagonist']
    archived = []
    for actor_id in sorted(actor_id for actor_id in actors if actor_id != 'protagonist'):
        quiet = max(0, turn_number - int(last_map.get(actor_id, turn_number) or turn_number))
        if quiet >= ARCHIVE_AFTER_QUIET_TURNS:
            archived.append(actor_id)
        else:
            active.append(actor_id)
    return {
        'active_actor_ids': active,
        'archived_actor_ids': archived,
        'last_mentioned_turn': last_map,
        'archive_after_quiet_turns': ARCHIVE_AFTER_QUIET_TURNS,
    }


def _bind_actor_ids(state: dict, actors: dict, *, turn_number: int) -> None:
    for item in state.get('possession_state', []) or []:
        if not isinstance(item, dict):
            continue
        actor_id = _find_actor_id_by_name(actors, item.get('holder', ''))
        if actor_id:
            item['holder_actor_id'] = actor_id
    for item in state.get('object_visibility', []) or []:
        if not isinstance(item, dict):
            continue
        actor_ids = []
        for name in item.get('known_to', []) or []:
            actor_id = _find_actor_id_by_name(actors, name)
            if actor_id and actor_id not in actor_ids:
                actor_ids.append(actor_id)
        if actor_ids:
            item['known_to_actor_ids'] = actor_ids
    scope = state.get('knowledge_scope', {}) if isinstance(state.get('knowledge_scope', {}), dict) else {}
    records = []
    protagonist_scope = scope.get('protagonist', {}) if isinstance(scope.get('protagonist', {}), dict) else {}
    for text in protagonist_scope.get('learned', []) or []:
        value = _clean_text(text, 160)
        if value:
            records.append({'holder_actor_id': 'protagonist', 'text': value})
    npc_local = scope.get('npc_local', {}) if isinstance(scope.get('npc_local', {}), dict) else {}
    for name, data in npc_local.items():
        if not isinstance(data, dict):
            continue
        actor_id = _find_actor_id_by_name(actors, name)
        if not actor_id:
            continue
        for text in data.get('learned', []) or []:
            value = _clean_text(text, 160)
            if value:
                records.append({'holder_actor_id': actor_id, 'text': value})
    if records:
        merged = []
        for item in (state.get('knowledge_records', []) or []) + records:
            if not isinstance(item, dict):
                continue
            key = (item.get('holder_actor_id'), item.get('text'))
            if not key[0] or not key[1]:
                continue
            if any(existing.get('holder_actor_id') == key[0] and _knowledge_similar(existing.get('text', ''), key[1]) for existing in merged):
                continue
            source_turn = item.get('source_turn') or turn_number
            merged.append({'holder_actor_id': key[0], 'text': key[1], 'source_turn': int(source_turn or turn_number)})
        state['knowledge_records'] = merged[-80:]


def update_actor_registry(state: dict, *, narrator_reply: str, turn_number: int, player_name: str = '', user_text: str = '', recent_pairs: list[tuple[str, str]] | None = None, use_llm: bool = True) -> dict:
    current = deepcopy(state or {})
    actors = current.get('actors', {}) if isinstance(current.get('actors', {}), dict) else {}
    actors = {str(actor_id): dict(actor) for actor_id, actor in actors.items() if isinstance(actor, dict)}
    _ensure_protagonist(actors, player_name=player_name)

    diagnostics = {'provider_requested': 'llm' if use_llm else 'fallback', 'created_actor_ids': [], 'fallback_used': False}
    candidates: list[dict] = []
    if use_llm:
        candidates, usage, error = _extract_actor_candidates_with_llm(actors, narrator_reply, user_text=user_text, recent_pairs=recent_pairs)
        diagnostics['model_usage'] = usage
        if isinstance(error, dict):
            diagnostics.update(error)
        else:
            diagnostics['error'] = error
        if error:
            diagnostics['fallback_used'] = True
            candidates = _fallback_actor_candidates(current)
    else:
        candidates = _fallback_actor_candidates(current)

    created_ids = []
    for candidate in candidates:
        if _candidate_overlaps_existing_actor(candidate, actors, current):
            continue
        if _find_actor_id_by_name(actors, candidate['name']):
            continue
        if any(_find_actor_id_by_name(actors, alias) for alias in candidate.get('aliases', [])):
            continue
        actor_id = _next_actor_id(actors)
        actors[actor_id] = {
            'actor_id': actor_id,
            'kind': 'npc',
            'name': candidate['name'],
            'aliases': candidate.get('aliases', [])[:6],
            'personality': candidate.get('personality', ''),
            'appearance': candidate.get('appearance', ''),
            'identity': candidate.get('identity', ''),
            'created_turn': int(turn_number or 1),
        }
        created_ids.append(actor_id)

    current['actors'] = actors
    mentioned = _mentioned_actor_ids(actors, f'{user_text}\n{narrator_reply}') | set(created_ids)
    current['actor_context_index'] = _normalize_actor_context_index(current, actors, int(turn_number or 1), mentioned)
    _bind_actor_ids(current, actors, turn_number=int(turn_number or 1))
    diagnostics['created_actor_ids'] = created_ids
    current['actor_registry_diagnostics'] = diagnostics
    return current
