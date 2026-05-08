#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from copy import deepcopy

try:
    from .llm_manager import call_role_llm
    from .local_model_client import parse_json_response
    from .name_sanitizer import sanitize_runtime_name, is_protagonist_name, protagonist_names, looks_like_bad_entity_fragment
    from .card_hints import get_canonical_name, get_character_primary_name
except ImportError:
    from llm_manager import call_role_llm
    from local_model_client import parse_json_response
    from name_sanitizer import sanitize_runtime_name, is_protagonist_name, protagonist_names, looks_like_bad_entity_fragment
    from card_hints import get_canonical_name, get_character_primary_name


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
6. 如果只是“一名差役”“几个制服人”这类一次性功能人且没有稳定个体特征，可以不登记。
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
        if name and _looks_like_person_alias(name) and name not in out:
            out.append(name)
    return out


def _actor_names(actor: dict) -> set[str]:
    names = set(_actor_aliases(actor))
    name = _actor_name(actor)
    if name:
        names.add(name)
    return names


NPC_TITLE_SUFFIXES = (
    '教官', '老师', '先生', '小姐', '女士', '夫人', '长官', '队长', '局长', '主管', '管理员', '医生', '大夫',
)


def _name_surfaces(name: str) -> set[str]:
    clean = sanitize_runtime_name(name)
    if not clean:
        return set()
    surfaces = {clean}
    canonical = sanitize_runtime_name(get_canonical_name(clean))
    if canonical:
        surfaces.add(canonical)
    for suffix in NPC_TITLE_SUFFIXES:
        if clean.endswith(suffix) and len(clean) > len(suffix):
            stripped = clean[:-len(suffix)].strip()
            if stripped:
                surfaces.add(stripped)
                mapped = sanitize_runtime_name(get_canonical_name(stripped))
                if mapped:
                    surfaces.add(mapped)
    for item in list(surfaces):
        if '·' in item:
            surfaces.update(part for part in item.split('·') if part)
    card_name = sanitize_runtime_name(get_character_primary_name())
    if card_name and '·' in card_name:
        card_parts = {part for part in card_name.split('·') if part}
        if clean == card_name or clean in card_parts or surfaces & card_parts:
            surfaces.add(card_name)
            surfaces.update(card_parts)
            surfaces.update(f'{part}{suffix}' for part in card_parts for suffix in NPC_TITLE_SUFFIXES)
    return {item for item in surfaces if item}


def _actor_name_matches(actor: dict, name: str) -> bool:
    target_surfaces = _name_surfaces(name)
    if not target_surfaces:
        return False
    actor_surfaces: set[str] = set()
    for actor_name in _actor_names(actor):
        actor_surfaces.update(_name_surfaces(actor_name))
    return bool(actor_surfaces & target_surfaces)


def _ensure_protagonist(actors: dict, player_name: str = '') -> None:
    aliases = ['你', '主角']
    cleaned_player = sanitize_runtime_name(player_name)
    if cleaned_player and cleaned_player not in aliases:
        aliases.append(cleaned_player)
    raw_existing = actors.get('protagonist')
    existing = raw_existing if isinstance(raw_existing, dict) else {}
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
        if isinstance(actor, dict) and _actor_name_matches(actor, cleaned):
            return str(actor_id)
    return ''


NPC_EPISTEMIC_MARKERS = (
    '注意到', '观察到', '察觉', '发现', '看到', '听到', '听见', '怀疑', '觉得',
    '认为', '判断', '推断', '意识到', '留意到', '看出',
)


GENERIC_ACTOR_HINTS = (
    '男生', '女生', '学员', '新生', '高年级', '助教', '老师', '教官', '医生', '护士', '杂工', '炊事员',
    '寸头', '高个子', '圆脸', '金发', '瘦高', '迟到', '受伤', '年轻', '老人', '小个子',
)

NON_NAME_DIALOGUE = {
    '不用', '不要', '到', '嗯', '哦', '医务室', '理论课', '名字', '腿', '看前面', '跟上', '去食堂',
    '迟到', '作业', '地图', '目标', '漏洞', '卫星图', '我也不想', '你叫什么', '不能', '没有',
    '下一个', '终端', '别迟到', '时间到', '谁先说', '你们两个', '他说的',
}

COMMON_SURNAME_PREFIXES = set(
    '赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕张孔曹严华金魏陶姜'
    '戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐'
    '费廉岑薛雷贺倪汤滕殷罗毕郝安常乐于时傅皮卞齐康伍余元卜顾孟平黄'
    '和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董'
    '梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡'
    '凌霍虞万支柯管卢莫房裴陆沙风漠月血刑关白柳顾韩沈秦谢宋苏萧裴'
)

PERSON_ALIAS_SUFFIXES = (
    '人', '男人', '女人', '女子', '青年', '少年', '老者', '壮汉', '男生', '女生', '学员', '新生',
    '教官', '助教', '老师', '教员', '先生', '小姐', '女士', '夫人', '长官', '队长', '主管',
)

NON_ALIAS_SUFFIXES = (
    '馆', '柜台', '窗口', '日志', '编号', '代码', '排序', '机位', '模块', '组件', '系统', '终端',
    '文件', '文件夹', '文件袋', '地图', '档案', '名单', '公司', '区域', '教室', '楼层', '走廊',
)

NON_ALIAS_CONTAINS = (
    '代码', '日志', '终端', '编号', 'DNS', '批量', '组件', '模块', '上午', '下午', '两点', '三十五秒',
    '第一组', '第三波', '一组', '两人一组', '本机', '窗口', '银行', '咖啡馆', '鹰巢',
)

NON_ALIAS_PREFIXES = ('在', '抱着', '拿着', '拎着', '看着', '听着', '想着', '说着', '低声', '继续')


def _looks_like_person_alias(value: str) -> bool:
    name = sanitize_runtime_name(value)
    if not name or name in NON_NAME_DIALOGUE or is_protagonist_name(name) or looks_like_bad_entity_fragment(name):
        return False
    if any(ch.isdigit() for ch in name):
        return False
    if any(mark in name for mark in ('，', '。', '！', '？', ',', '.', '!', '?', '：', ':', '“', '”', '"')):
        return False
    if any(name.startswith(prefix) for prefix in NON_ALIAS_PREFIXES):
        return False
    if any(token in name for token in NON_ALIAS_CONTAINS):
        return False
    if name.endswith(NON_ALIAS_SUFFIXES):
        return False
    if re.fullmatch(r'[A-Za-z0-9_-]+', name):
        return False
    if '·' in name and all(re.fullmatch(r'[\u4e00-\u9fff]{1,8}', part or '') for part in name.split('·')):
        return True
    if name.startswith('阿') and 2 <= len(name) <= 4:
        return True
    if name[:1] in COMMON_SURNAME_PREFIXES and 2 <= len(name) <= 4:
        return True
    if any(suffix in name for suffix in PERSON_ALIAS_SUFFIXES):
        return True
    return False


def _looks_like_proper_person_name(value: str) -> bool:
    name = sanitize_runtime_name(value)
    return bool(_looks_like_person_alias(name) and ((name.startswith('阿') and 2 <= len(name) <= 4) or (name[:1] in COMMON_SURNAME_PREFIXES and 2 <= len(name) <= 4)))


def _is_descriptive_actor_name(value: str) -> bool:
    name = sanitize_runtime_name(value)
    if not name:
        return False
    return any(hint in name for hint in GENERIC_ACTOR_HINTS) or any(name.endswith(suffix) for suffix in PERSON_ALIAS_SUFFIXES)


def _clean_actor_aliases(aliases: list[str], actor_name: str = '') -> list[str]:
    out: list[str] = []
    primary = sanitize_runtime_name(actor_name)
    for alias in aliases or []:
        text = sanitize_runtime_name(alias)
        if not text or text == primary or text in out:
            continue
        if not _looks_like_person_alias(text):
            continue
        out.append(text)
    return out[:6]


def _protagonist_labels(actors: dict) -> set[str]:
    labels = set(protagonist_names())
    raw_protagonist = actors.get('protagonist')
    protagonist = raw_protagonist if isinstance(raw_protagonist, dict) else {}
    name = sanitize_runtime_name(protagonist.get('name', ''))
    if name:
        labels.add(name)
    for alias in protagonist.get('aliases', []) or []:
        alias_name = sanitize_runtime_name(alias)
        if alias_name and not is_protagonist_name(alias_name):
            labels.add(alias_name)
    return labels


def _mentions_protagonist(text: str, actors: dict) -> bool:
    value = str(text or '')
    if any(label and label in value for label in _protagonist_labels(actors)):
        return True
    return value.startswith(('主角', '玩家', '她', '他'))


def _frame_npc_protagonist_knowledge(text: str, *, holder_name: str, actors: dict) -> str:
    value = _clean_text(text, 160)
    if not value or not holder_name or not _mentions_protagonist(value, actors):
        return value
    if any(marker in value for marker in NPC_EPISTEMIC_MARKERS):
        return value
    return _clean_text(f'{holder_name}注意到{value}', 160)


def _looks_like_revealed_name(value: str) -> bool:
    name = sanitize_runtime_name(re.sub(r'[—\-－~～…\s]+', '', str(value or '')))
    if not _looks_like_person_alias(name) or '什么' in name:
        return False
    if not re.fullmatch(r'[\u4e00-\u9fff]{2,4}', name):
        return False
    if any(name.endswith(suffix) for suffix in ('学员', '新生', '男生', '女生', '教官', '助教', '老师')):
        return False
    return True


def _clean_revealed_name(value: str) -> str:
    name = sanitize_runtime_name(re.sub(r'[—\-－~～…\s]+', '', str(value or '')))
    if len(name) >= 3 and name[0] == name[1]:
        name = name[1:]
    return name


def _extract_name_reveals(text: str) -> list[dict]:
    value = str(text or '')
    reveals: list[dict] = []
    for match in re.finditer(r'["“](?P<quoted>[^"”]{1,16})["”]', value):
        quoted = str(match.group('quoted') or '').strip().strip('。！？!?，,')
        candidates = [quoted]
        if '姓' in quoted:
            candidates = []
            continue
        if '——' in quoted or '—' in quoted or '-' in quoted or '－' in quoted:
            candidates.append(_clean_revealed_name(quoted))
        for candidate in candidates:
            name = _clean_revealed_name(candidate)
            if not _looks_like_revealed_name(name):
                continue
            before = value[max(0, match.start() - 900):match.start()]
            after = value[match.end():min(len(value), match.end() + 120)]
            surname = name[:1]
            surname_match = bool(re.search(rf'["“]姓{re.escape(surname)}[。！？!?]?["”]', before[-160:]))
            reveals.append({'name': name, 'window': before + after, 'surname_match': surname_match})
    deduped: list[dict] = []
    seen = set()
    for item in reveals:
        name = item.get('name')
        if name and name not in seen:
            deduped.append(item)
            seen.add(name)
    return deduped[:6]


def _generic_actor_terms(actor: dict) -> set[str]:
    text = ' '.join(str(actor.get(key, '') or '') for key in ('name', 'appearance', 'identity'))
    text += ' ' + ' '.join(str(alias or '') for alias in actor.get('aliases', []) or [])
    terms = set()
    for hint in GENERIC_ACTOR_HINTS:
        if hint in text:
            terms.add(hint)
    for token in re.findall(r'[\u4e00-\u9fff]{2,5}', text):
        if any(hint in token for hint in GENERIC_ACTOR_HINTS):
            terms.add(token)
    return {term for term in terms if term}


def _actor_reveal_score(actor: dict, reveal: dict, haystack: str) -> int:
    if not isinstance(actor, dict) or actor.get('kind') == 'protagonist':
        return 0
    if _actor_name_matches(actor, str(reveal.get('name', '') or '')):
        return 0
    terms = _generic_actor_terms(actor)
    if not terms:
        return 0
    window = str(reveal.get('window', '') or '')
    score = 0
    for term in terms:
        if term and term in haystack:
            score += 1
        if term and term in window:
            score += 2
    actor_name = _actor_name(actor)
    if actor_name and actor_name in haystack:
        score += 3
    if reveal.get('surname_match'):
        score += 2
    return score


def _upsert_revealed_actor_aliases(actors: dict, narrator_reply: str) -> list[dict]:
    reveals = _extract_name_reveals(narrator_reply)
    if not reveals:
        return []
    haystack = str(narrator_reply or '')
    updates: list[dict] = []
    for reveal in reveals:
        name = str(reveal.get('name', '') or '')
        if not name or _find_actor_id_by_name(actors, name):
            continue
        scored = []
        for actor_id, actor in actors.items():
            score = _actor_reveal_score(actor, reveal, haystack)
            if score > 0:
                scored.append((score, str(actor_id), actor))
        if not scored:
            continue
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            continue
        score, actor_id, actor = scored[0]
        if score < 4:
            continue
        actor_name = _actor_name(actor)
        aliases = _clean_actor_aliases(_actor_aliases(actor), actor_name)
        promoted = False
        if _looks_like_proper_person_name(name) and _is_descriptive_actor_name(actor_name):
            if actor_name and actor_name not in aliases and _looks_like_person_alias(actor_name):
                aliases.insert(0, actor_name)
            actor['name'] = name
            promoted = True
        elif name not in aliases and name != actor_name:
            aliases.append(name)
        actor['aliases'] = _clean_actor_aliases(aliases, actor.get('name', actor_name))
        updates.append({'actor_id': actor_id, 'alias': name, 'score': score, 'promoted_to_name': promoted})
    return updates


def _valid_actor_candidate(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    name = sanitize_runtime_name(item.get('name', ''))
    if not name or is_protagonist_name(name) or looks_like_bad_entity_fragment(name):
        return None
    aliases = []
    for alias in item.get('aliases', []) or []:
        alias_name = sanitize_runtime_name(alias)
        if alias_name and alias_name != name and _looks_like_person_alias(alias_name) and alias_name not in aliases:
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
        if isinstance(actor, dict) and any(_actor_name_matches(actor, name) for name in names):
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
        holder_name = _actor_name(actors.get(actor_id, {})) or sanitize_runtime_name(name)
        for text in data.get('learned', []) or []:
            value = _clean_text(text, 160)
            if value:
                value = _frame_npc_protagonist_knowledge(value, holder_name=holder_name, actors=actors)
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
    for actor in actors.values():
        if isinstance(actor, dict) and actor.get('kind') != 'protagonist':
            actor['aliases'] = _clean_actor_aliases(list(actor.get('aliases', []) or []), _actor_name(actor))

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

    alias_updates = _upsert_revealed_actor_aliases(actors, narrator_reply)
    current['actors'] = actors
    mentioned = _mentioned_actor_ids(actors, f'{user_text}\n{narrator_reply}') | set(created_ids)
    mentioned.update(str(item.get('actor_id')) for item in alias_updates if item.get('actor_id'))
    current['actor_context_index'] = _normalize_actor_context_index(current, actors, int(turn_number or 1), mentioned)
    _bind_actor_ids(current, actors, turn_number=int(turn_number or 1))
    diagnostics['created_actor_ids'] = created_ids
    diagnostics['alias_updates'] = alias_updates
    current['actor_registry_diagnostics'] = diagnostics
    return current
