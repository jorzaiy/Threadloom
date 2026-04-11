#!/usr/bin/env python3
"""State-Keeper: 基于模型的运行时状态提取器。

替代旧的硬编码 state_updater.py，使用与 narrator 同体系的模型配置
从叙事文本中提取结构化状态。完全泛化，不依赖特定角色卡。
"""

import logging
import json
import re

from typing import Optional

try:
    from .llm_manager import call_role_llm
    from .local_model_client import parse_json_response
    from .runtime_store import load_state, load_summary, save_state, seed_default_state
    from .state_bridge import infer_role_label, normalize_state_dict
    from .model_config import load_runtime_config
    from .state_fragment import build_state_from_fragment
    from .name_sanitizer import is_protagonist_name, protagonist_names
except ImportError:
    from llm_manager import call_role_llm
    from local_model_client import parse_json_response
    from runtime_store import load_state, load_summary, save_state, seed_default_state
    from state_bridge import infer_role_label, normalize_state_dict
    from model_config import load_runtime_config
    from state_fragment import build_state_from_fragment
    from name_sanitizer import is_protagonist_name, protagonist_names


logger = logging.getLogger(__name__)


STRING_FIELDS = ('time', 'location', 'main_event', 'scene_core', 'immediate_goal')
LIST_FIELDS = ('onstage_npcs', 'relevant_npcs', 'immediate_risks', 'carryover_clues', 'scene_entities')
LOW_SIGNAL_TOKENS = ('待确认', '暂无', 'unknown', '未明', '不明')
ENVIRONMENT_ENTITY_TOKENS = ('巷口', '雨', '刀光', '积水', '灯火', '灯影', '竹梯', '破箩筐', '砖墙', '青石', '檐角', '风灯', '车辕', '独轮车')
TRANSIENT_GROUP_TOKENS = ('更夫', '闲人', '行人', '旁人', '路人', '众人', '几人', '那几人', '几名', '外头的人', '巷外的人', '围观的人', '看热闹的人')
NON_CHARACTER_OBJECT_TOKENS = ('油布包', '纸卷', '竹筒', '账目', '名录', '令牌', '银袋', '包裹', '短镖', '铁镖', '铁牌', '木牌')
GENERIC_TARGET_TOKENS = ('深衣人', '被围', '被围之人', '被围的人', '青年', '年轻男人', '年轻人', '男人', '那人', '目标人物', '伤者')


STATE_KEEPER_SYSTEM = """你是 RP 结构化状态提取器，只做事实提取，不写叙事。

只输出 JSON。

核心字段：
time, location, main_event, scene_core,
onstage_npcs, relevant_npcs,
immediate_goal, immediate_risks, carryover_clues。

若输出 candidate_entities，最多输出 3 个，且每个 evidence 不超过 20 个字：
[
  {
    "surface": "文本里出现的称呼或短描述",
    "entity_type": "character | object | ambient_group",
    "role_hint": "角色/物件/群体的功能提示",
    "slot_hint": "conflict_target | pursuer | observer | key_object | ambient_group | unknown",
    "confidence": 0.0,
    "onstage": true,
    "evidence": "触发判断的短证据"
  }
]

若你无法稳定产出 candidate_entities，直接退回 scene_entities，不要强行凑满。

规则：
1. 优先尊重输入里的结构化状态锚点。
2. 没有明确证据，不要把已有字段改回待确认。
3. 只在正文明确表明离场、转场、时间推进时才改对应字段。
4. 不编造新人物、新地点、新事件。
5. character 才是人物；object 是关键物件；ambient_group 是背景群体。
6. 如果是人物，优先判断它更接近哪个功能槽位：conflict_target / pursuer / observer。
"""


STATE_KEEPER_FILL_SYSTEM = """你是 RP 结构化状态补全器，只在既有骨架上补字段，不重写整份 state。

只输出一个 JSON 对象，不要代码块，不要解释，不要额外文字。

默认只补这些字段：
scene_core, immediate_risks, carryover_clues,
tracked_objects, possession_state, object_visibility。

time, location, main_event, onstage_npcs, immediate_goal 已经是固定骨架。
除非叙事正文明确推翻它们，否则不要重复输出，也不要改写。

规则：
1. 若字段无需修改，直接省略，不要输出空话。
2. 不要编造新人物、新地点、新事件。
3. 不要把环境物件、背景人群当成人物。
4. 输出尽量短，只补最稳定的变化，不要扩写人物名单。
5. 若本轮出现明确的物件动作（如摸出、递给、收起、握住、亮出、塞回、放下），优先补 `tracked_objects / possession_state / object_visibility`。
6. `tracked_objects[].label` 必须是短标签，如：纸条、短刀、腰牌、记录板、水壶。不要把内容摘要、整句描述或解释写进 label。
7. `possession_state[].holder` 必须是当前场景里明确存在的人物名，或主角名；不要输出 `player_inventory`、`paper_note`、`self` 这类系统化名字。
8. `object_visibility[].visibility` 只允许使用：`private`、`public`。
9. 若正文只说明“看了一眼纸条内容”，应保留对象标签为 `纸条`，不要把纸条内容改写成一个新对象。
"""


SKELETON_KEEPER_SYSTEM = """你是最小骨架状态提取器。
只输出一个 JSON 对象，不要代码块，不要解释，不要额外文字。
只允许字段：
time, location, main_event, onstage_npcs, immediate_goal。
禁止输出其他字段。
若不确定，字符串字段写待确认，数组字段写空数组。
onstage_npcs 最多 3 个。
不要重新命名稳定人物；优先沿用输入中的结构化状态锚点。
"""


def _slim_state_for_model(state: dict) -> dict:
    out = {}
    for field in ('time', 'location', 'main_event', 'scene_core', 'immediate_goal'):
        value = str(state.get(field, '') or '').strip()
        if value:
            out[field] = value
    for field in ('onstage_npcs', 'relevant_npcs', 'immediate_risks', 'carryover_clues'):
        values = [str(item).strip() for item in (state.get(field, []) or []) if str(item).strip()]
        if values:
            out[field] = values[:6]
    entities = []
    for item in (state.get('scene_entities', []) or [])[:8]:
        if not isinstance(item, dict):
            continue
        entity = {
            'entity_id': str(item.get('entity_id', '') or '').strip(),
            'primary_label': str(item.get('primary_label', '') or '').strip(),
            'role_label': str(item.get('role_label', '') or '').strip(),
            'onstage': bool(item.get('onstage')),
        }
        aliases = [str(alias).strip() for alias in (item.get('aliases', []) or []) if str(alias).strip()][:3]
        if aliases:
            entity['aliases'] = aliases
        entities.append(entity)
    if entities:
        out['scene_entities'] = entities
    if isinstance(state.get('tracked_objects', []), list) and state.get('tracked_objects'):
        out['tracked_objects'] = state.get('tracked_objects', [])[:6]
    if isinstance(state.get('possession_state', []), list) and state.get('possession_state'):
        out['possession_state'] = state.get('possession_state', [])[:6]
    if isinstance(state.get('object_visibility', []), list) and state.get('object_visibility'):
        out['object_visibility'] = state.get('object_visibility', [])[:6]
    return out


def _slim_fragment_for_model(fragment: dict) -> dict:
    allowed = {
        'time', 'location', 'main_event', 'scene_core', 'onstage_npcs', 'relevant_npcs',
        'immediate_goal', 'immediate_risks', 'carryover_clues', 'scene_entities',
        'turn_mode', 'arbiter_events', 'stability_hints'
    }
    base = {key: fragment.get(key) for key in allowed if key in fragment}
    return _slim_state_for_model(base) | {
        key: base[key]
        for key in ('turn_mode', 'arbiter_events', 'stability_hints')
        if key in base and base[key]
    }


def _summary_excerpt(summary: str, limit: int = 700) -> str:
    text = (summary or '').strip()
    return text[:limit]


def skeleton_keeper_enabled() -> bool:
    cfg = load_runtime_config()
    roles = cfg.get('roles', {}) or {}
    models = cfg.get('models', {}) or {}
    role_cfg = roles.get('state_keeper_candidate', {}) or {}
    model_cfg = models.get('state_keeper_candidate', {}) or {}
    return bool(role_cfg.get('provider') == 'llm' and model_cfg.get('model'))


def _skeleton_user_prompt(prev_state: dict, state_fragment: dict, narrator_reply: str) -> str:
    prev_min = {
        'time': str(prev_state.get('time', '') or '').strip(),
        'location': str(prev_state.get('location', '') or '').strip(),
        'main_event': str(prev_state.get('main_event', '') or '').strip(),
        'immediate_goal': str(prev_state.get('immediate_goal', '') or '').strip(),
        'onstage_npcs': [str(item).strip() for item in (prev_state.get('onstage_npcs', []) or []) if str(item).strip()][:3],
    }
    fragment_min = {
        'time': str(state_fragment.get('time', '') or '').strip(),
        'location': str(state_fragment.get('location', '') or '').strip(),
        'main_event': str(state_fragment.get('main_event', '') or '').strip(),
        'immediate_goal': str(state_fragment.get('immediate_goal', '') or '').strip(),
        'onstage_npcs': [str(item).strip() for item in (state_fragment.get('onstage_npcs', []) or []) if str(item).strip()][:3],
    }
    return f"""上一轮骨架状态：
{json.dumps(prev_min, ensure_ascii=False, indent=2)}

本轮结构化状态锚点：
{json.dumps(fragment_min, ensure_ascii=False, indent=2)}

本轮叙事正文：
{narrator_reply}

请只输出最小骨架 JSON。"""


def _fill_user_prompt(baseline_state: dict, narrator_reply: str, summary_excerpt: str, user_text: str = '') -> str:
    baseline = _slim_state_for_model(baseline_state)
    sections = [f"""当前固定骨架状态：
{json.dumps(baseline, ensure_ascii=False, indent=2)}

本轮叙事正文：
{narrator_reply}
"""]
    if user_text.strip():
        sections.append(f"""本轮玩家输入：
{user_text.strip()}
""")
    sections.append(f"""当前摘要：
{summary_excerpt}

请只输出需要补充或纠正的 JSON 字段；若骨架字段没有被正文明确推翻，就不要重复输出。""")
    return '\n'.join(sections)


def _extract_string_field(text: str, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.S)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"')
    except Exception:
        return match.group(1)


def _extract_string_list_field(text: str, field: str) -> list[str] | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*\[(.*?)\]', text, re.S)
    if not match:
        return None
    values = []
    for item in re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1), re.S):
        try:
            value = json.loads(f'"{item}"')
        except Exception:
            value = item
        value = str(value or '').strip()
        if value and value not in values:
            values.append(value)
    return values


def _parse_fill_payload(text: str) -> dict:
    try:
        payload = parse_json_response(text)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        fallback = {}
        scene_core = _extract_string_field(text, 'scene_core')
        if scene_core:
            fallback['scene_core'] = scene_core
        immediate_risks = _extract_string_list_field(text, 'immediate_risks')
        if immediate_risks:
            fallback['immediate_risks'] = immediate_risks
        carryover_clues = _extract_string_list_field(text, 'carryover_clues')
        if carryover_clues:
            fallback['carryover_clues'] = carryover_clues
        if fallback:
            return fallback
        raise


def _coerce_tracked_object_item(item, idx: int) -> dict | None:
    if isinstance(item, str):
        label = str(item or '').strip()
        if not label:
            return None
        return {
            'object_id': f'obj_{idx + 1:02d}',
            'label': label,
            'kind': 'item',
            'story_relevant': True,
        }
    if not isinstance(item, dict):
        return None
    object_id = str(item.get('object_id', f'obj_{idx + 1:02d}') or f'obj_{idx + 1:02d}').strip()
    label = str(item.get('label', item.get('name', '')) or '').strip()
    if not object_id or not label:
        return None
    return {
        'object_id': object_id,
        'label': label,
        'kind': str(item.get('kind', '') or 'item').strip() or 'item',
        'story_relevant': bool(item.get('story_relevant', True)),
    }


def _build_object_index_from_baseline(state: dict) -> tuple[dict[str, dict], int]:
    objects_by_label: dict[str, dict] = {}
    alias_to_label: dict[str, str] = {}
    max_idx = 0
    for item in (state.get('tracked_objects', []) or []):
        if not isinstance(item, dict):
            continue
        label = str(item.get('label', '') or '').strip()
        object_id = str(item.get('object_id', '') or '').strip()
        if not label:
            continue
        objects_by_label[label] = dict(item)
        alias_to_label[label] = label
        if object_id.startswith('obj_'):
            try:
                max_idx = max(max_idx, int(object_id.split('_', 1)[1]))
            except Exception:
                pass
    return objects_by_label, max_idx


def _known_holders_from_baseline(state: dict) -> set[str]:
    names: set[str] = set()
    for field in ('onstage_npcs', 'relevant_npcs'):
        for item in (state.get(field, []) or []):
            text = str(item or '').strip()
            if text:
                names.add(text)
    for item in (state.get('scene_entities', []) or []):
        if not isinstance(item, dict):
            continue
        primary = str(item.get('primary_label', '') or '').strip()
        if primary:
            names.add(primary)
        for alias in (item.get('aliases', []) or []):
            alias_text = str(alias or '').strip()
            if alias_text:
                names.add(alias_text)
    names.update(protagonist_names())
    return names


def _normalize_holder_name(holder: str, known_holders: set[str]) -> str:
    text = str(holder or '').strip()
    if not text:
        return ''
    protagonist_aliases = {'player_inventory', 'protagonist', 'player', 'user', 'self', '主角', '玩家', '自己'}
    if text in protagonist_aliases:
        protagonists = protagonist_names()
        if protagonists:
            return next(iter(protagonists))
    if text in known_holders:
        return text
    return ''


def _ensure_object_for_label(label: str, objects_by_label: dict[str, dict], next_idx: int) -> tuple[dict | None, int]:
    text = str(label or '').strip()
    if not text:
        return None, next_idx
    current = objects_by_label.get(text)
    if current:
        return current, next_idx
    next_idx += 1
    item = {
        'object_id': f'obj_{next_idx:02d}',
        'label': text,
        'kind': 'item',
        'story_relevant': True,
    }
    objects_by_label[text] = item
    return item, next_idx


def _normalize_object_label(text: str) -> str:
    value = str(text or '').strip()
    if not value:
        return ''
    value = value.split('（', 1)[0].split('(', 1)[0].strip()
    translations = {
        'paper_note': '纸条',
        'note': '纸条',
        'slip': '纸条',
        'knife': '短刀',
        'short_blade': '短刀',
    }
    return translations.get(value, value)


def _coerce_object_layers(payload: dict, baseline_state: dict | None = None) -> dict:
    normalized = dict(payload or {})
    baseline = baseline_state if isinstance(baseline_state, dict) else {}
    objects_by_label, max_idx = _build_object_index_from_baseline(baseline)
    known_holders = _known_holders_from_baseline(baseline)
    object_fields_used = False

    tracked_objects = normalized.get('tracked_objects')
    if isinstance(tracked_objects, list):
        object_fields_used = True
        for idx, item in enumerate(tracked_objects):
            coerced = _coerce_tracked_object_item(item, idx)
            if not coerced:
                continue
            coerced['label'] = _normalize_object_label(coerced.get('label', ''))
            objects_by_label[coerced['label']] = coerced
            object_id = str(coerced.get('object_id', '') or '').strip()
            if object_id.startswith('obj_'):
                try:
                    max_idx = max(max_idx, int(object_id.split('_', 1)[1]))
                except Exception:
                    pass

    possession_state = normalized.get('possession_state')
    coerced_possession = []
    if isinstance(possession_state, list):
        object_fields_used = True
        for item in possession_state:
            coerced = _coerce_possession_item(item, known_holders=known_holders, objects_by_label=objects_by_label, next_idx=max_idx)
            if coerced:
                value, max_idx = coerced
                if value:
                    coerced_possession.append(value)
    elif isinstance(possession_state, dict):
        object_fields_used = True
        for holder, labels in possession_state.items():
            holder_text = _normalize_holder_name(holder, known_holders)
            if not holder_text:
                continue
            label_items = labels if isinstance(labels, list) else [labels]
            for raw_label in label_items:
                normalized_label = _normalize_object_label(raw_label)
                obj, max_idx = _ensure_object_for_label(normalized_label, objects_by_label, max_idx)
                if not obj:
                    continue
                coerced_possession.append({
                    'object_id': obj['object_id'],
                    'holder': holder_text,
                    'status': 'carried',
                    'location': '',
                    'updated_by_turn': '',
                })
    if coerced_possession:
        normalized['possession_state'] = coerced_possession

    object_visibility = normalized.get('object_visibility')
    coerced_visibility = []
    if isinstance(object_visibility, list):
        object_fields_used = True
        for item in object_visibility:
            coerced = _coerce_object_visibility_item(item)
            if coerced:
                coerced_visibility.append(coerced)
    elif isinstance(object_visibility, dict):
        object_fields_used = True
        for label, vis in object_visibility.items():
            normalized_label = _normalize_object_label(label)
            obj, max_idx = _ensure_object_for_label(normalized_label, objects_by_label, max_idx)
            if not obj:
                continue
            if isinstance(vis, dict):
                coerced = _coerce_object_visibility_item({'object_id': obj['object_id'], **vis})
            else:
                coerced = _coerce_object_visibility_item({
                    'object_id': obj['object_id'],
                    'visibility': str(vis or '').strip() or 'private',
                })
            if coerced:
                coerced_visibility.append(coerced)
    if coerced_visibility:
        normalized['object_visibility'] = coerced_visibility

    if object_fields_used:
        normalized['tracked_objects'] = list(objects_by_label.values())[:8]
    return normalized


def _coerce_possession_item(item, known_holders: set[str] | None = None, objects_by_label: dict[str, dict] | None = None, next_idx: int = 0) -> tuple[dict | None, int]:
    if not isinstance(item, dict):
        return None, next_idx
    known = known_holders or set()
    objects = objects_by_label or {}
    holder = _normalize_holder_name(str(item.get('holder', '') or '').strip(), known)
    if not holder:
        return None, next_idx
    object_id = str(item.get('object_id', '') or '').strip()
    if not object_id:
        object_label = _normalize_object_label(item.get('object_label', item.get('label', '')))
        obj, next_idx = _ensure_object_for_label(object_label, objects, next_idx)
        if not obj:
            return None, next_idx
        object_id = obj['object_id']
    if not object_id:
        return None, next_idx
    return {
        'object_id': object_id,
        'holder': holder,
        'status': str(item.get('status', '') or 'carried').strip() or 'carried',
        'location': str(item.get('location', '') or '').strip(),
        'updated_by_turn': str(item.get('updated_by_turn', '') or '').strip(),
    }, next_idx


def _coerce_object_visibility_item(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    object_id = str(item.get('object_id', '') or '').strip()
    if not object_id:
        return None
    known_to = item.get('known_to', [])
    if isinstance(known_to, str):
        known_to = [known_to] if known_to.strip() else []
    if not isinstance(known_to, list):
        known_to = []
    return {
        'object_id': object_id,
        'visibility': str(item.get('visibility', '') or 'private').strip() or 'private',
        'known_to': [str(name).strip() for name in known_to if str(name).strip()][:6],
        'note': str(item.get('note', '') or '').strip(),
    }


def _normalize_skeleton_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError('skeleton payload must be an object')
    normalized = {}
    for field in ('time', 'location', 'main_event', 'immediate_goal'):
        value = str(payload.get(field, '') or '').strip()
        if value:
            normalized[field] = value
    onstage = payload.get('onstage_npcs', [])
    if isinstance(onstage, str):
        onstage = [onstage] if onstage.strip() else []
    if isinstance(onstage, list):
        cleaned = []
        for item in onstage:
            name = str(item or '').strip()
            if name and not is_protagonist_name(name) and name not in cleaned:
                cleaned.append(name)
            if len(cleaned) >= 3:
                break
        normalized['onstage_npcs'] = cleaned
    return normalized


def _merge_keeper_fill(baseline_state: dict, payload: dict) -> dict:
    merged = dict(baseline_state or {})
    if not isinstance(payload, dict):
        return merged

    for field in ('time', 'location', 'main_event', 'scene_core', 'immediate_goal'):
        if field not in payload:
            continue
        value = str(payload.get(field, '') or '').strip()
        if value and not _has_low_signal(value):
            merged[field] = value

    for field in ('onstage_npcs', 'relevant_npcs', 'immediate_risks', 'carryover_clues'):
        if field not in payload:
            continue
        raw = payload.get(field)
        if isinstance(raw, str):
            raw = [raw] if raw.strip() else []
        if not isinstance(raw, list):
            continue
        cleaned = []
        for item in raw:
            text = str(item or '').strip()
            if not text or text in cleaned:
                continue
            cleaned.append(text)
        if field == 'onstage_npcs':
            if cleaned:
                merged[field] = cleaned[:6]
        else:
            merged[field] = cleaned[:6]

    for field in ('tracked_objects', 'possession_state', 'object_visibility'):
        if field in payload and isinstance(payload.get(field), list):
            merged[field] = payload.get(field, [])[:8]

    return merged


def call_skeleton_keeper(prev_state: dict, state_fragment: dict, narrator_reply: str, *, return_trace: bool = False):
    reply_text, usage = call_role_llm('state_keeper_candidate', SKELETON_KEEPER_SYSTEM, _skeleton_user_prompt(prev_state, state_fragment, narrator_reply))
    usage['prompt_chars'] = len(SKELETON_KEEPER_SYSTEM) + len(_skeleton_user_prompt(prev_state, state_fragment, narrator_reply))
    payload = _normalize_skeleton_payload(parse_json_response(reply_text))
    if return_trace:
        return payload, usage, {
            'raw_reply': reply_text,
            'payload': payload,
        }
    return payload, usage


def _require_string(payload: dict, field: str) -> None:
    value = payload.get(field)
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f'state field {field} must be a string')


def _require_string_list(payload: dict, field: str) -> None:
    value = payload.get(field)
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError(f'state field {field} must be a list')
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f'state field {field}[{idx}] must be a string')


def _validate_scene_entities(payload: dict) -> None:
    value = payload.get('scene_entities')
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError('state field scene_entities must be a list')
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f'scene_entities[{idx}] must be an object')
        for key in ('entity_id', 'primary_label', 'role_label'):
            entry = item.get(key)
            if entry is not None and not isinstance(entry, str):
                raise ValueError(f'scene_entities[{idx}].{key} must be a string')
        aliases = item.get('aliases')
        if aliases is not None:
            if not isinstance(aliases, list):
                raise ValueError(f'scene_entities[{idx}].aliases must be a list')
            for alias_idx, alias in enumerate(aliases):
                if not isinstance(alias, str):
                    raise ValueError(f'scene_entities[{idx}].aliases[{alias_idx}] must be a string')
        onstage = item.get('onstage')
        if onstage is not None and not isinstance(onstage, bool):
            raise ValueError(f'scene_entities[{idx}].onstage must be a boolean')


def _coerce_scene_entity_item(item, idx: int) -> dict | None:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {
            'entity_id': f'scene_npc_{idx + 1:02d}',
            'primary_label': text,
            'aliases': [text],
            'role_label': '待确认',
            'onstage': True,
        }
    if not isinstance(item, dict):
        return None
    primary = str(item.get('primary_label', item.get('name', '')) or '').strip()
    if not primary:
        return None
    aliases_raw = item.get('aliases', [])
    aliases = []
    if isinstance(aliases_raw, list):
        aliases = [str(alias).strip() for alias in aliases_raw if str(alias).strip()]
    elif isinstance(aliases_raw, str) and aliases_raw.strip():
        aliases = [aliases_raw.strip()]
    if primary not in aliases:
        aliases.insert(0, primary)
    return {
        'entity_id': str(item.get('entity_id', f'scene_npc_{idx + 1:02d}') or f'scene_npc_{idx + 1:02d}').strip(),
        'primary_label': primary,
        'aliases': aliases[:4],
        'role_label': str(item.get('role_label', item.get('role', '待确认')) or '待确认').strip(),
        'onstage': bool(item.get('onstage', item.get('present', True))),
    }


def _coerce_state_payload(payload: dict, baseline_state: dict | None = None) -> dict:
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    if 'scene_entities' in normalized and isinstance(normalized.get('scene_entities'), list):
        entities = []
        for idx, item in enumerate(normalized.get('scene_entities', [])):
            entity = _coerce_scene_entity_item(item, idx)
            if entity:
                entities.append(entity)
        normalized['scene_entities'] = entities
    for field in ('onstage_npcs', 'relevant_npcs', 'immediate_risks', 'carryover_clues'):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = [value] if value.strip() else []
    return _coerce_object_layers(normalized, baseline_state)


def _coerce_candidate_entity_item(item) -> dict | None:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {
            'surface': text,
            'entity_type': 'character',
            'role_hint': '',
            'confidence': 0.5,
            'onstage': False,
            'evidence': '',
        }
    if not isinstance(item, dict):
        return None
    surface = str(item.get('surface', item.get('name', item.get('primary_label', ''))) or '').strip()
    if not surface:
        return None
    entity_type = str(item.get('entity_type', item.get('type', 'character')) or 'character').strip().lower()
    if entity_type not in {'character', 'object', 'ambient_group'}:
        entity_type = 'character'
    try:
        confidence = float(item.get('confidence', 0.5))
    except Exception:
        confidence = 0.5
    confidence = max(0.0, min(confidence, 1.0))
    return {
        'surface': surface,
        'entity_type': entity_type,
        'role_hint': str(item.get('role_hint', item.get('role_label', item.get('role', ''))) or '').strip(),
        'slot_hint': str(item.get('slot_hint', item.get('slot', 'unknown')) or 'unknown').strip().lower(),
        'confidence': confidence,
        'onstage': bool(item.get('onstage', item.get('present', False))),
        'evidence': str(item.get('evidence', '') or '').strip(),
    }


def _looks_like_environment_entity(name: str, role_label: str) -> bool:
    text = f'{name} {role_label}'.strip()
    if not text:
        return True
    if any(token in name for token in ENVIRONMENT_ENTITY_TOKENS):
        return True
    if any(token in role_label for token in ('环境', '地点', '物件', '道具', '光影')):
        return True
    return False


def _looks_like_transient_group(name: str, role_label: str) -> bool:
    text = f'{name} {role_label}'.strip()
    if not text:
        return True
    if any(token in text for token in TRANSIENT_GROUP_TOKENS):
        return True
    if any(token in name for token in ('（', '）', '和', '以及')) and not any(key in name for key in ('皂衣人', '高个皂衣人')):
        return True
    return False


def _looks_like_non_character_object(name: str, role_label: str) -> bool:
    text = f'{name} {role_label}'.strip()
    if not text:
        return True
    if any(token in name for token in NON_CHARACTER_OBJECT_TOKENS):
        return True
    if any(token in role_label for token in ('物件', '证物', '道具', '包裹', '卷宗', '账册')):
        return True
    return False


def _canonical_character_name(name: str, known_names: set[str]) -> str:
    text = str(name or '').strip()
    if not text:
        return ''
    if text in known_names:
        return text
    if '皂衣人' in text:
        return '高个皂衣人' if '高个' in text or '领头' in text else '皂衣人'
    if any(token in text for token in GENERIC_TARGET_TOKENS):
        for candidate in ('伤者', '师兄', '褐袍人', '少年'):
            if candidate in known_names:
                return candidate
        return '伤者'
    if '掌柜' in text:
        return '掌柜'
    if '伙计' in text:
        return '伙计'
    if '师兄' in text:
        return '师兄'
    return text


def _canonical_candidate_name(surface: str, role_hint: str, known_names: set[str], scene_hint: str) -> str:
    text = _canonical_character_name(surface, known_names)
    combined = f'{surface} {role_hint} {scene_hint}'.strip()
    if text in known_names:
        return text
    if '皂衣人' in combined:
        return '高个皂衣人' if any(token in combined for token in ('高个', '领头', '头领')) else '皂衣人'
    if any(token in combined for token in ('围攻', '围杀', '被围', '伤', '血', '受伤', '目标', '深衣', '青年', '男人', '伤者')):
        return '伤者'
    if '师兄' in combined:
        return '师兄'
    if '掌柜' in combined:
        return '掌柜'
    if '伙计' in combined:
        return '伙计'
    return text


def _slot_hint_for_candidate(item: dict, scene_hint: str) -> str:
    slot = str(item.get('slot_hint', 'unknown') or 'unknown').strip().lower()
    if slot in {'conflict_target', 'pursuer', 'observer', 'key_object', 'ambient_group'}:
        return slot
    surface = str(item.get('surface', '') or '').strip()
    role_hint = str(item.get('role_hint', '') or '').strip()
    combined = f'{surface} {role_hint} {scene_hint}'.strip()
    entity_type = str(item.get('entity_type', 'character') or 'character').strip().lower()
    if entity_type == 'object':
        return 'key_object'
    if entity_type == 'ambient_group':
        return 'ambient_group'
    if any(token in combined for token in ('围攻', '围杀', '被围', '受伤', '伤口', '血', '目标', '深衣', '年轻男人', '青年', '那人')):
        return 'conflict_target'
    if any(token in combined for token in ('皂衣人', '镇北司', '追兵', '围攻者', '持弩', '头领', '封路')):
        return 'pursuer'
    if any(token in combined for token in ('旁观', '观察', '躲在巷口', '檐影', '巷口外', '外头观察')):
        return 'observer'
    return 'unknown'


def _default_name_for_slot(slot: str) -> str:
    return {
        'conflict_target': '伤者',
        'pursuer': '皂衣人',
        'observer': '旁观者',
        'key_object': '关键物件',
        'ambient_group': '背景人群',
    }.get(slot, '')


def _role_label_for_name(name: str, role_label: str, scene_hint: str) -> str:
    text = str(role_label or '').strip()
    if text and text != '待确认':
        return text
    if name == '伤者':
        return '当前伤者 / 冲突核心对象'
    if name == '被围攻者':
        return '当前被围攻对象 / 冲突核心对象'
    if any(token in scene_hint for token in ('围攻', '围杀', '追索', '伤', '血')) and name in {'伤者', '师兄', '褐袍人', '少年'}:
        return '当前伤者 / 冲突核心对象'
    inferred = infer_role_label(name)
    return inferred if inferred else '待确认'


def _semantic_cleanup(payload: dict, prev_state: dict, state_fragment: dict) -> dict:
    normalized = dict(payload or {})
    known_names = set(str(item).strip() for item in (prev_state.get('onstage_npcs', []) or []) + (prev_state.get('relevant_npcs', []) or []))
    known_names.update(str(item).strip() for item in (state_fragment.get('onstage_npcs', []) or []) + (state_fragment.get('relevant_npcs', []) or []))
    scene_hint = ' '.join([
        str(normalized.get('main_event', '') or ''),
        str(normalized.get('scene_core', '') or ''),
        str(state_fragment.get('main_event', '') or ''),
        str(state_fragment.get('scene_core', '') or ''),
    ])

    def clean_legacy_entities() -> tuple[list[dict], list[str], list[str]]:
        cleaned_entities = []
        seen_names: set[str] = set()
        for idx, item in enumerate(normalized.get('scene_entities', []) or []):
            if not isinstance(item, dict):
                continue
            primary = _canonical_character_name(item.get('primary_label', ''), known_names)
            role_label = _role_label_for_name(primary, item.get('role_label', ''), scene_hint)
            if _looks_like_environment_entity(primary, role_label) or _looks_like_transient_group(primary, role_label) or _looks_like_non_character_object(primary, role_label):
                continue
            if not primary or primary in seen_names:
                continue
            seen_names.add(primary)
            aliases = [primary]
            for alias in item.get('aliases', []) or []:
                alias_text = _canonical_character_name(alias, known_names)
                if alias_text and alias_text not in aliases and not _looks_like_environment_entity(alias_text, role_label) and not _looks_like_transient_group(alias_text, role_label) and not _looks_like_non_character_object(alias_text, role_label):
                    aliases.append(alias_text)
            cleaned_entities.append({
                'entity_id': str(item.get('entity_id', f'scene_npc_{idx + 1:02d}') or f'scene_npc_{idx + 1:02d}').strip(),
                'primary_label': primary,
                'aliases': aliases[:4],
                'role_label': role_label,
                'onstage': bool(item.get('onstage', True)),
            })

        onstage_names = []
        relevant_names = []
        for field, target in (('onstage_npcs', onstage_names), ('relevant_npcs', relevant_names)):
            for name in normalized.get(field, []) or []:
                canonical = _canonical_character_name(name, known_names)
                role = _role_label_for_name(canonical, '', scene_hint)
                if not canonical or _looks_like_environment_entity(canonical, role) or _looks_like_transient_group(canonical, role) or _looks_like_non_character_object(canonical, role) or canonical in target:
                    continue
                target.append(canonical)
        return cleaned_entities, onstage_names[:6], [name for name in relevant_names if name not in onstage_names][:6]

    def looks_like_attacker(entity: dict) -> bool:
        text = f"{entity.get('primary_label', '')} {entity.get('role_label', '')}".strip()
        return any(token in text for token in ('皂衣人', '镇北司', '围攻者', '敌人'))

    def merge_entities(primary_entities: list[dict], fallback_entities: list[dict]) -> list[dict]:
        merged = []
        seen = set()
        for item in primary_entities + fallback_entities:
            if not isinstance(item, dict):
                continue
            primary = str(item.get('primary_label', '') or '').strip()
            if not primary or primary in seen:
                continue
            seen.add(primary)
            merged.append(item)
        if any(token in scene_hint for token in ('围攻', '围杀', '追索', '伤', '血')):
            non_attackers = [item for item in merged if not looks_like_attacker(item)]
            if not non_attackers:
                for item in fallback_entities:
                    if not looks_like_attacker(item):
                        primary = str(item.get('primary_label', '') or '').strip()
                        if primary and primary not in seen:
                            seen.add(primary)
                            merged.append(item)
                            break
        return merged

    legacy_entities, legacy_onstage, legacy_relevant = clean_legacy_entities()

    candidate_entities = []
    for item in normalized.get('candidate_entities', []) or []:
        candidate = _coerce_candidate_entity_item(item)
        if candidate:
            candidate_entities.append(candidate)

    key_objects = []
    ambient_groups = []
    if candidate_entities:
        for item in candidate_entities:
            slot = _slot_hint_for_candidate(item, scene_hint)
            if item['entity_type'] == 'object' or slot == 'key_object':
                if item['confidence'] >= 0.45:
                    key_objects.append({
                        'surface': item['surface'],
                        'role_hint': item['role_hint'],
                        'confidence': item['confidence'],
                        'evidence': item['evidence'],
                    })
                continue
            if item['entity_type'] == 'ambient_group' or slot == 'ambient_group':
                if item['confidence'] >= 0.45:
                    ambient_groups.append({
                        'surface': item['surface'],
                        'role_hint': item['role_hint'],
                        'confidence': item['confidence'],
                        'evidence': item['evidence'],
                    })
                continue

        normalized['scene_entities'] = legacy_entities
        normalized['onstage_npcs'] = legacy_onstage
        normalized['relevant_npcs'] = legacy_relevant
        if key_objects:
            normalized['key_objects'] = key_objects[:6]
        if ambient_groups:
            normalized['ambient_groups'] = ambient_groups[:6]
        return normalized

    normalized['scene_entities'] = legacy_entities
    normalized['onstage_npcs'] = legacy_onstage
    normalized['relevant_npcs'] = legacy_relevant

    return normalized


def _clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def _has_low_signal(value: str) -> bool:
    text = _clean_text(value)
    return not text or any(token == text or token in text for token in LOW_SIGNAL_TOKENS)


def _useful_string_count(payload: dict) -> int:
    return sum(
        1
        for field in STRING_FIELDS
        if isinstance(payload.get(field), str) and not _has_low_signal(payload.get(field, ''))
    )


def _useful_list_count(payload: dict) -> int:
    count = 0
    for field in ('onstage_npcs', 'relevant_npcs', 'immediate_risks', 'carryover_clues'):
        values = payload.get(field, [])
        if isinstance(values, list) and any(_clean_text(str(item)) and not _has_low_signal(str(item)) for item in values):
            count += 1
    return count


def _useful_entity_count(payload: dict) -> int:
    items = payload.get('scene_entities', [])
    if not isinstance(items, list):
        return 0
    count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        primary = str(item.get('primary_label', '') or '').strip()
        role = str(item.get('role_label', '') or '').strip()
        if primary and not _has_low_signal(primary) and not _has_low_signal(role):
            count += 1
    return count


def _validate_against_prev_state(payload: dict, prev_state: dict) -> None:
    prev_state = prev_state or {}
    useful_now = _useful_string_count(payload) + _useful_list_count(payload) + _useful_entity_count(payload)
    useful_prev = _useful_string_count(prev_state) + _useful_list_count(prev_state) + _useful_entity_count(prev_state)

    if useful_now < 2:
        raise ValueError('state payload contains too little useful signal')
    if useful_prev >= 4 and useful_now + 2 < useful_prev:
        raise ValueError('state payload regressed too far from previous useful signal')

    prev_onstage = set(prev_state.get('onstage_npcs', []) or [])
    next_onstage = set(payload.get('onstage_npcs', []) or [])
    if prev_onstage and not next_onstage and _useful_entity_count(payload) == 0:
        raise ValueError('state payload dropped all onstage entities without replacement')


def validate_state_payload(payload: dict, prev_state: dict | None = None) -> None:
    if not isinstance(payload, dict):
        raise ValueError('state payload must be an object')

    recognized = 0
    for field in STRING_FIELDS:
        if field in payload:
            recognized += 1
            _require_string(payload, field)
    for field in ('onstage_npcs', 'relevant_npcs', 'immediate_risks', 'carryover_clues'):
        if field in payload:
            recognized += 1
            _require_string_list(payload, field)
    if 'scene_entities' in payload:
        recognized += 1
        _validate_scene_entities(payload)

    if recognized < 5:
        raise ValueError('state payload contains too few recognized fields')

    useful_strings = _useful_string_count(payload)
    useful_lists = _useful_list_count(payload)
    useful_entities = _useful_entity_count(payload) > 0
    if useful_strings == 0 and useful_lists == 0 and not useful_entities:
        raise ValueError('state payload does not contain useful state signal')
    _validate_against_prev_state(payload, prev_state or {})


def _with_diagnostics(state: dict, *, provider_requested: str, provider_used: str, usage: dict | None, fallback_used: bool, fallback_reason: str | None) -> dict:
    output = dict(state)
    output['diagnostics'] = {
        'provider_requested': provider_requested,
        'provider_used': provider_used,
        'model_usage': usage,
        'fallback_used': fallback_used,
        'fallback_reason': fallback_reason,
    }
    return output


def call_state_keeper(session_id: str, narrator_reply: str, state_fragment: Optional[dict] = None, *, user_text: str = '', return_trace: bool = False):
    """调用模型提取状态。

    Args:
        session_id: 会话 ID
        narrator_reply: 本轮 narrator 生成的叙事正文

    Returns:
        新的 state 字典
    """
    prev_state = load_state(session_id) or seed_default_state(session_id)
    summary = load_summary(session_id)
    state_fragment = state_fragment if isinstance(state_fragment, dict) else {}
    baseline_state = build_state_from_fragment(prev_state, state_fragment, session_id)
    summary_excerpt = _summary_excerpt(summary, 700)
    user_prompt = _fill_user_prompt(baseline_state, narrator_reply, summary_excerpt, user_text=user_text)

    try:
        reply_text, usage = call_role_llm('state_keeper', STATE_KEEPER_FILL_SYSTEM, user_prompt)
        usage['prompt_chars'] = len(STATE_KEEPER_FILL_SYSTEM) + len(user_prompt)
        payload = _coerce_state_payload(_parse_fill_payload(reply_text), baseline_state=baseline_state)
        new_state = _merge_keeper_fill(baseline_state, payload)
        new_state = _semantic_cleanup(new_state, prev_state, state_fragment)
        validate_state_payload(new_state, prev_state)
        new_state = _with_diagnostics(
            new_state,
            provider_requested='llm',
            provider_used='llm-fill',
            usage=usage,
            fallback_used=False,
            fallback_reason=None,
        )
    except Exception as err:
        logger.warning('State-keeper extraction failed: %s', err)
        raise RuntimeError(f'state_keeper_failed: {err}') from err

    new_state = normalize_state_dict(new_state, prev_state=prev_state, session_id=session_id)
    diagnostics = new_state.pop('diagnostics', None)
    new_state['state_keeper_diagnostics'] = diagnostics if isinstance(diagnostics, dict) else {
        'provider_requested': 'llm',
        'provider_used': 'llm',
        'model_usage': None,
        'fallback_used': False,
        'fallback_reason': None,
    }
    save_state(session_id, new_state)
    if return_trace:
        return new_state, {
            'baseline_state': baseline_state,
            'summary_excerpt': summary_excerpt,
            'user_text': user_text,
            'user_prompt': user_prompt,
            'raw_reply': reply_text,
            'payload': payload,
        }
    return new_state
