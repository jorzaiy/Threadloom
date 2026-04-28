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
    from .runtime_store import load_state, save_state, seed_default_state
    from .state_bridge import infer_role_label, normalize_state_dict
    from .model_config import load_runtime_config
    from .state_fragment import build_state_from_fragment
    from .name_sanitizer import is_protagonist_name, protagonist_names
    from .name_sanitizer import sanitize_runtime_name
    from .card_hints import (
        get_environment_tokens, get_transient_group_tokens,
        get_non_character_object_tokens, get_generic_target_tokens,
        get_known_npc_role, get_canonical_name,
    )
except ImportError:
    from llm_manager import call_role_llm
    from local_model_client import parse_json_response
    from runtime_store import load_state, save_state, seed_default_state
    from state_bridge import infer_role_label, normalize_state_dict
    from model_config import load_runtime_config
    from state_fragment import build_state_from_fragment
    from name_sanitizer import is_protagonist_name, protagonist_names
    from name_sanitizer import sanitize_runtime_name
    from card_hints import (
        get_environment_tokens, get_transient_group_tokens,
        get_non_character_object_tokens, get_generic_target_tokens,
        get_known_npc_role, get_canonical_name,
    )


logger = logging.getLogger(__name__)


STRING_FIELDS = ('time', 'location', 'main_event', 'immediate_goal')
LIST_FIELDS = ('onstage_npcs', 'relevant_npcs', 'carryover_signals', 'immediate_risks', 'carryover_clues', 'scene_entities')
LOW_SIGNAL_TOKENS = ('待确认', '暂无', 'unknown', '未明', '不明')


class StateKeeperCallError(RuntimeError):
    def __init__(self, message: str, *, usage: dict | None = None, raw_reply: str = ''):
        super().__init__(message)
        self.usage = usage if isinstance(usage, dict) else None
        self.raw_reply = raw_reply if isinstance(raw_reply, str) else ''



STATE_KEEPER_SYSTEM = """你是 RP 结构化状态提取器，只做事实提取，不写叙事。

只输出 JSON。

核心字段：
time, location, main_event,
onstage_npcs, relevant_npcs,
immediate_goal, carryover_signals。

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
3. 只在正文明确表明人物存在、地点或时间已经发生变化时才改对应字段。
4. 不编造新人物、新地点、新事件。
5. character 才是人物；object 是关键物件；ambient_group 是背景群体。
6. 如果是人物，优先判断它更接近哪个功能槽位：conflict_target / pursuer / observer。
"""


STATE_KEEPER_FILL_SYSTEM = """你是 RP 结构化状态补全器，只在既有骨架上补字段，不重写整份 state。

只输出一个 JSON 对象，不要代码块，不要解释，不要额外文字。

默认只补这些字段：
carryover_signals,
tracked_objects, possession_state, object_visibility,
knowledge_scope。

不要维护 NPC 基础设定；姓名、别称、性格、外貌、身份由 actor registry 创建后锁定。
不要记录短期人物状态；人物的临时处境、在场关系、行动阶段和当前位置只由最近窗口承载。

time, location, main_event, onstage_npcs, immediate_goal 已经是固定骨架。
除非叙事正文明确推翻它们，否则不要重复输出，也不要改写。

各补全字段要求：
- carryover_signals（数组，每项为对象，最多4项）：本轮出现、且后续仍会影响局势推进的关键信号。
  格式：
  [
    {"type": "risk|clue|mixed", "text": "短句描述"}
  ]
  要求：
  - 只保留真正会延续到下一轮或后续几轮的信号
  - `text` 控制在 30 字以内，不要抄原文长句，不要半句 prose
  - `type=risk`：更偏直接威胁、压力、暴露、失控后果
  - `type=clue`：更偏情报、身份、物件、动机、线索
  - `type=mixed`：同时兼具线索与风险，不必硬分
  好的例子：
    - {"type":"risk","text":"门外守卫开始排查同行者"}
    - {"type":"clue","text":"陌生人反复追问遗失文件"}
    - {"type":"mixed","text":"角落观察者立场不明"}
  坏的例子：
    - {"type":"risk","text":"她声音清冷，却在这嘈杂雨声中异常清晰地送入对方耳中"}
    - {"type":"clue","text":"就是这一滞，左臂旧伤像是又被牵开"}
- knowledge_scope（对象）：本轮各角色的知情边界增量。只记录本轮新增的信息，不要重复之前的。
  格式：
  ```
  "knowledge_scope": {
    "protagonist": {
      "learned": ["本轮主角新获知的具体信息，如：看到林越手臂有旧伤疤"]
    },
    "npc_local": {
      "NPC名": {
        "learned": ["本轮该NPC新获知的信息"]
      }
    }
  }
  ```
  规则：
  - 只记录本轮叙事中明确发生的信息获取（看到、听到、被告知、发现）
  - 不要推测、不要编造；"可能知道"不算
  - 主角和NPC的信息获取必须分开；主角看到的不等于NPC也看到
  - 如果本轮无新信息获取，或只是再次提及已知信息，必须省略整个字段

规则：
1. 若字段无需修改，直接省略，不要输出空话。
2. 不要编造新人物、新地点、新事件。
3. 不要把环境物件、背景人群当成人物。
4. 输出尽量短，只补最稳定的变化，不要扩写人物名单。
5. 把本轮输出当作增量 patch，而不是整表重写：已有物件和情报默认沿用，只有明确新增或明确变化才输出。
6. 若本轮出现明确的物件动作（如摸出、递给、收起、握住、亮出、塞回、放下），优先补 `tracked_objects / possession_state / object_visibility`。
7. 物件归属只需要在 `possession_state` 写 `object_id + holder + status`；后处理会自动把物件和 NPC 双向绑定，不要为了绑定而重复改写整个人物表。
8. `tracked_objects[].label` 必须是短标签，如：纸条、短刀、腰牌、记录板、水壶。不要把内容摘要、整句描述或解释写进 label。
9. `possession_state[].holder` 必须是当前场景里明确存在的人物名，或主角名；不要输出 `player_inventory`、`paper_note`、`self` 这类系统化名字。
10. `object_visibility[].visibility` 只允许使用：`private`、`public`。
11. 若正文只说明"看了一眼纸条内容"，应保留对象标签为 `纸条`，不要把纸条内容改写成一个新对象。
12. 只有当物件存在明确的持有、展示、转移、搜出、收起、放下、遗失、证物化等"可持续物理状态"时，才写入物件层。
13. 不要把动作词、策略词或复合短语里截出来的一部分误当物件标签；例如不能把某个词组中的局部字面片段当成 `tracked_objects[].label`。
14. 一次性付款、零散货币、临时消耗品，默认不要进入 `tracked_objects`；只有当它们变成明确证物、持续持有物、关键交易物或后续还会被追踪时，才写入物件层。
15. 若物件既没有明确持有者，也没有明确场景落点（如桌上、柜台上、地上、床边、窗边、桶里、门后），默认不要写入物件层。
16. 若物件被明确消耗、摧毁、遗失或退出追踪，在 tracked_objects 中输出原 object_id/label，并写 lifecycle_status: consumed|destroyed|lost|archived；不要直接删除。
"""


SKELETON_KEEPER_SYSTEM = """你是 RP 最小骨架状态提取器，从叙事正文中提取 5 个核心字段。
只输出一个 JSON 对象，不要代码块，不要解释，不要额外文字。

只允许字段：time, location, main_event, onstage_npcs, immediate_goal。
禁止输出其他字段。

各字段要求：
- time：提取正文中明确出现的时间信息（日期、钟点、时段）。只提取文本中实际出现的，不要推测。
- location：提取主角当前所在的具体场景。格式简洁，如"城市东门·茶摊旁"或"空间站下层维修廊"。不要复制长句。
- main_event：用一句话概括本轮叙事的核心事件。要求：描述"谁做了什么"或"发生了什么"，不要用模糊标签（如"训练考核""同行安排""当前互动"）。
  好的例子："主角在3000米跑中故意掉速观察教官反应"、"实验体在地下实验室中突然失控"。
  坏的例子："训练考核"、"同行安排：xxx"、"当前互动"。
- onstage_npcs：本轮正文中实际在场、有动作或对话的人物（不含主角）。最多 3 个。只写名字，不要加描述。
- immediate_goal：主角在本轮结束时面临的下一步行动或决策。要求：概括意图，不要照搬玩家原文。
  好的例子："找机会溜出丹房"、"试探教官对威胁邮件的态度"、"判断是否要介入巷中杀局"。
  优先输出单一的“下一拍目标”，不要把两个备选方案并列写进同一句。
  坏的例子（照搬原文）："耸耸肩说看吧我说我上了二楼他们就会..."。

若不确定，字符串字段写"待确认"，数组字段写空数组。
不要重新命名稳定人物；优先沿用输入中的结构化状态锚点。
"""


def _slim_state_for_model(state: dict) -> dict:
    out = {}
    for field in ('time', 'location', 'main_event', 'immediate_goal'):
        value = str(state.get(field, '') or '').strip()
        if value:
            out[field] = value
    for field in ('onstage_npcs', 'relevant_npcs', 'immediate_risks', 'carryover_clues'):
        values = [str(item).strip() for item in (state.get(field, []) or []) if str(item).strip()]
        if values:
            out[field] = values[:6]
    signal_items = []
    for item in (state.get('carryover_signals', []) or [])[:6]:
        if not isinstance(item, dict):
            continue
        signal_text = str(item.get('text', '') or '').strip()
        signal_type = str(item.get('type', '') or '').strip()
        if not signal_text:
            continue
        signal_items.append({'type': signal_type or 'mixed', 'text': signal_text})
    if signal_items:
        out['carryover_signals'] = signal_items
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
        'time', 'location', 'main_event', 'onstage_npcs', 'relevant_npcs',
        'immediate_goal', 'carryover_signals', 'immediate_risks', 'carryover_clues', 'scene_entities',
        'turn_mode', 'arbiter_events', 'stability_hints'
    }
    base = {key: fragment.get(key) for key in allowed if key in fragment}
    return _slim_state_for_model(base) | {
        key: base[key]
        for key in ('turn_mode', 'arbiter_events', 'stability_hints')
        if key in base and base[key]
    }


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


def _fill_user_prompt(baseline_state: dict, narrator_reply: str, user_text: str = '') -> str:
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
    sections.append("""请只输出需要补充或纠正的 JSON 字段；若骨架字段没有被正文明确推翻，就不要重复输出。输出必须以 { 开头、以 } 结尾，禁止解释、分析过程、Markdown 代码块。""")
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


def _extract_json_field_value(text: str, field: str):
    match = re.search(rf'"{re.escape(field)}"\s*:', text, re.S)
    if not match:
        return None
    idx = match.end()
    while idx < len(text) and text[idx].isspace():
        idx += 1
    if idx >= len(text):
        return None

    opener = text[idx]
    if opener == '"':
        end = idx + 1
        escaped = False
        while end < len(text):
            ch = text[end]
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                try:
                    return json.loads(text[idx:end + 1])
                except Exception:
                    return None
            end += 1
        return None

    pairs = {'[': ']', '{': '}'}
    if opener not in pairs:
        return None
    stack = [pairs[opener]]
    end = idx + 1
    in_string = False
    escaped = False
    while end < len(text):
        ch = text[end]
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in pairs:
                stack.append(pairs[ch])
            elif stack and ch == stack[-1]:
                stack.pop()
                if not stack:
                    try:
                        return json.loads(text[idx:end + 1])
                    except Exception:
                        return None
        end += 1
    return None


def _parse_fill_payload(text: str) -> dict:
    try:
        payload = parse_json_response(text)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        fallback = {}
        carryover_signals = _extract_signal_list_field(text, 'carryover_signals')
        if carryover_signals:
            fallback['carryover_signals'] = carryover_signals
        immediate_risks = _extract_string_list_field(text, 'immediate_risks')
        if immediate_risks:
            fallback['immediate_risks'] = immediate_risks
        carryover_clues = _extract_string_list_field(text, 'carryover_clues')
        if carryover_clues:
            fallback['carryover_clues'] = carryover_clues
        for field in ('tracked_objects', 'possession_state', 'object_visibility'):
            value = _extract_json_field_value(text, field)
            if isinstance(value, list) and value:
                fallback[field] = value
        knowledge_scope = _extract_json_field_value(text, 'knowledge_scope')
        if isinstance(knowledge_scope, (dict, str)):
            fallback['knowledge_scope'] = knowledge_scope
        if fallback:
            return fallback
        raise


def _extract_signal_list_field(text: str, field: str) -> list[dict] | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*\[(.*?)\]', text, re.S)
    if not match:
        return None
    block = match.group(1)
    items = []
    for raw in re.finditer(r'\{(.*?)\}', block, re.S):
        chunk = '{' + raw.group(1) + '}'
        try:
            payload = json.loads(chunk)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        signal_type = str(payload.get('type', '') or 'mixed').strip() or 'mixed'
        signal_text = str(payload.get('text', '') or '').strip()
        if not signal_text:
            continue
        items.append({'type': signal_type, 'text': signal_text})
    return items or None


def _normalize_carryover_signals(payload: dict) -> list[dict]:
    items = payload.get('carryover_signals', []) if isinstance(payload.get('carryover_signals', []), list) else []
    normalized = []
    seen = set()
    for item in items:
        if isinstance(item, str):
            signal_type = 'mixed'
            text = str(item or '').strip()
        elif isinstance(item, dict):
            signal_type = str(item.get('type', '') or 'mixed').strip() or 'mixed'
            text = str(item.get('text', '') or '').strip()
        else:
            continue
        if not text:
            continue
        key = (signal_type, text)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({'type': signal_type, 'text': text})
        if len(normalized) >= 6:
            break
    return normalized


def _derive_risks_clues_from_signals(signals: list[dict]) -> tuple[list[str], list[str]]:
    risks = []
    clues = []
    for item in signals or []:
        if not isinstance(item, dict):
            continue
        signal_type = str(item.get('type', '') or 'mixed').strip() or 'mixed'
        text = str(item.get('text', '') or '').strip()
        if not text:
            continue
        if signal_type in {'risk', 'mixed'} and text not in risks:
            risks.append(text)
        if signal_type in {'clue', 'mixed'} and text not in clues:
            clues.append(text)
    return risks[:4], clues[:4]


def _derive_signals_from_legacy_lists(payload: dict) -> list[dict]:
    signals = []
    seen = set()
    for item in payload.get('immediate_risks', []) or []:
        text = str(item or '').strip()
        if not text:
            continue
        key = ('risk', text)
        if key in seen:
            continue
        seen.add(key)
        signals.append({'type': 'risk', 'text': text})
    for item in payload.get('carryover_clues', []) or []:
        text = str(item or '').strip()
        if not text:
            continue
        signal_type = 'mixed' if ('risk', text) in seen else 'clue'
        key = (signal_type, text)
        if key in seen:
            continue
        seen.add(key)
        signals.append({'type': signal_type, 'text': text})
    return signals[:6]


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
    lifecycle_status = str(item.get('lifecycle_status', item.get('status', 'active')) or 'active').strip() or 'active'
    if lifecycle_status not in {'active', 'consumed', 'destroyed', 'lost', 'archived'}:
        lifecycle_status = 'active'
    out = {
        'object_id': object_id,
        'label': label,
        'kind': str(item.get('kind', '') or 'item').strip() or 'item',
        'story_relevant': bool(item.get('story_relevant', True)),
    }
    if lifecycle_status != 'active':
        out['lifecycle_status'] = lifecycle_status
        out['lifecycle_reason'] = str(item.get('lifecycle_reason', item.get('reason', '')) or '').strip()
    return out


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
    return value


def _coerce_object_layers(payload: dict, baseline_state: dict | None = None) -> dict:
    normalized = dict(payload or {})
    baseline = baseline_state if isinstance(baseline_state, dict) else {}
    objects_by_label, max_idx = _build_object_index_from_baseline(baseline)
    baseline_labels = set(objects_by_label.keys())
    known_holders = _known_holders_from_baseline(baseline)
    object_fields_used = False
    explicit_objects_by_label: dict[str, dict] = {}

    tracked_objects = normalized.get('tracked_objects')
    if isinstance(tracked_objects, list):
        object_fields_used = True
        for idx, item in enumerate(tracked_objects):
            coerced = _coerce_tracked_object_item(item, idx)
            if not coerced:
                continue
            coerced['label'] = _normalize_object_label(coerced.get('label', ''))
            objects_by_label[coerced['label']] = coerced
            explicit_objects_by_label[coerced['label']] = coerced
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
                if normalized_label not in baseline_labels:
                    explicit_objects_by_label[normalized_label] = obj
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
            if normalized_label not in baseline_labels:
                explicit_objects_by_label[normalized_label] = obj
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

    if object_fields_used and explicit_objects_by_label:
        normalized['tracked_objects'] = list(explicit_objects_by_label.values())
    return normalized


def _coerce_knowledge_scope(value) -> dict:
    if isinstance(value, str):
        text = value.strip()
        return {'protagonist': {'learned': [text]}} if text else {}
    if not isinstance(value, dict):
        return {}
    result: dict = {}
    protagonist = value.get('protagonist', {})
    if isinstance(protagonist, str):
        protagonist = {'learned': [protagonist]}
    if isinstance(protagonist, dict):
        learned = protagonist.get('learned', [])
        if isinstance(learned, str):
            learned = [learned]
        cleaned = []
        if isinstance(learned, list):
            for item in learned:
                text = str(item or '').strip()
                if text and text not in cleaned:
                    cleaned.append(text)
        if cleaned:
            result['protagonist'] = {'learned': cleaned[:10]}
    npc_local_raw = value.get('npc_local', {})
    npc_local: dict = {}
    if isinstance(npc_local_raw, dict):
        for name, data in npc_local_raw.items():
            holder = str(name or '').strip()
            if not holder:
                continue
            if isinstance(data, str):
                data = {'learned': [data]}
            if not isinstance(data, dict):
                continue
            learned = data.get('learned', [])
            if isinstance(learned, str):
                learned = [learned]
            cleaned = []
            if isinstance(learned, list):
                for item in learned:
                    text = str(item or '').strip()
                    if text and text not in cleaned:
                        cleaned.append(text)
            if cleaned:
                npc_local[holder] = {'learned': cleaned[:10]}
    if npc_local:
        result['npc_local'] = npc_local
    return result


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

    for field in ('immediate_risks', 'carryover_clues'):
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
        if cleaned:
            merged[field] = cleaned[:6]

    signals = _normalize_carryover_signals(payload)
    if not signals:
        signals = _derive_signals_from_legacy_lists(payload)
    if signals:
        merged['carryover_signals'] = signals
        derived_risks, derived_clues = _derive_risks_clues_from_signals(signals)
        merged['immediate_risks'] = derived_risks
        merged['carryover_clues'] = derived_clues

    if 'knowledge_scope' in payload:
        scope = _coerce_knowledge_scope(payload.get('knowledge_scope'))
        if scope:
            merged['knowledge_scope'] = scope

    for field in ('tracked_objects', 'possession_state', 'object_visibility'):
        if field in payload and isinstance(payload.get(field), list) and payload.get(field):
            base_items = baseline_state.get(field, []) if isinstance(baseline_state.get(field, []), list) else []
            merged[field] = (base_items + payload.get(field, []))[-16:]

    return merged


def call_skeleton_keeper(prev_state: dict, state_fragment: dict, narrator_reply: str, *, return_trace: bool = False):
    reply_text, usage = call_role_llm('state_keeper_candidate', SKELETON_KEEPER_SYSTEM, _skeleton_user_prompt(prev_state, state_fragment, narrator_reply))
    if not isinstance(usage, dict):
        usage = {}
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


def _validate_knowledge_scope(payload: dict) -> None:
    value = payload.get('knowledge_scope')
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError('state field knowledge_scope must be an object')
    protagonist = value.get('protagonist')
    if protagonist is not None:
        if not isinstance(protagonist, dict):
            raise ValueError('knowledge_scope.protagonist must be an object')
        learned = protagonist.get('learned', [])
        if learned is not None and not isinstance(learned, list):
            raise ValueError('knowledge_scope.protagonist.learned must be a list')
        for idx, item in enumerate(learned or []):
            if not isinstance(item, str):
                raise ValueError(f'knowledge_scope.protagonist.learned[{idx}] must be a string')
    npc_local = value.get('npc_local')
    if npc_local is not None:
        if not isinstance(npc_local, dict):
            raise ValueError('knowledge_scope.npc_local must be an object')
        for name, data in npc_local.items():
            if not str(name or '').strip():
                raise ValueError('knowledge_scope.npc_local key must be non-empty')
            if not isinstance(data, dict):
                raise ValueError(f'knowledge_scope.npc_local.{name} must be an object')
            learned = data.get('learned', [])
            if learned is not None and not isinstance(learned, list):
                raise ValueError(f'knowledge_scope.npc_local.{name}.learned must be a list')
            for idx, item in enumerate(learned or []):
                if not isinstance(item, str):
                    raise ValueError(f'knowledge_scope.npc_local.{name}.learned[{idx}] must be a string')


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
    if 'carryover_signals' in normalized and isinstance(normalized.get('carryover_signals'), list):
        normalized['carryover_signals'] = _normalize_carryover_signals(normalized)
    else:
        normalized['carryover_signals'] = _derive_signals_from_legacy_lists(normalized)
    if normalized.get('carryover_signals'):
        derived_risks, derived_clues = _derive_risks_clues_from_signals(normalized['carryover_signals'])
        if derived_risks:
            normalized['immediate_risks'] = derived_risks
        if derived_clues:
            normalized['carryover_clues'] = derived_clues
    if 'knowledge_scope' in normalized:
        normalized['knowledge_scope'] = _coerce_knowledge_scope(normalized.get('knowledge_scope'))
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


def _descriptor_signature(name: str) -> str:
    text = sanitize_runtime_name(name)
    if not text:
        return ''
    for suffix in (
        '身影', '背影', '影子', '影', '之人', '那人', '此人', '来人',
        '男人', '女人', '女子', '青年', '少年', '老者', '壮汉',
        '皂衣人', '黑衣人', '灰衣人', '白衣人', '毡笠人', '人',
    ):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[:-len(suffix)].strip()
    return text


def _labels_compatible(left: str, right: str) -> bool:
    left_text = sanitize_runtime_name(left)
    right_text = sanitize_runtime_name(right)
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    if _is_shadow_like_label(left_text) or _is_shadow_like_label(right_text):
        return False
    left_sig = _descriptor_signature(left_text)
    right_sig = _descriptor_signature(right_text)
    return bool(left_sig and right_sig and left_sig == right_sig)


def _is_shadow_like_label(name: str) -> bool:
    text = sanitize_runtime_name(name)
    if not text:
        return True
    if text in {'暗影', '黑影', '影子', '人影'}:
        return True
    if text.endswith(('身影', '背影')):
        return True
    return False


def _is_generic_role_label(role_label: str) -> bool:
    text = str(role_label or '').strip()
    if not text:
        return True
    return text in {'待确认', '当前互动核心人物', '相关场景人物', '当前场景人物'}


def _looks_like_environment_entity(name: str, role_label: str) -> bool:
    text = f'{name} {role_label}'.strip()
    if not text:
        return True
    if name in {'姑娘', '陆姑娘', '路上', '猛地', '忍不住', '不知', '轻功', '自保', '一声'}:
        return True
    env_tokens = get_environment_tokens()
    if env_tokens and any(token in name for token in env_tokens):
        return True
    if any(token in role_label for token in ('环境', '地点', '物件', '道具', '光影')):
        return True
    return False


def _looks_like_transient_group(name: str, role_label: str) -> bool:
    text = f'{name} {role_label}'.strip()
    if not text:
        return True
    group_tokens = get_transient_group_tokens()
    if group_tokens and any(token in text for token in group_tokens):
        return True
    if any(token in name for token in ('（', '）', '和', '以及')):
        return True
    return False


def _looks_like_non_character_object(name: str, role_label: str) -> bool:
    text = f'{name} {role_label}'.strip()
    if not text:
        return True
    obj_tokens = get_non_character_object_tokens()
    if obj_tokens and any(token in name for token in obj_tokens):
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
    canonical = get_canonical_name(text)
    if canonical:
        return canonical
    target_tokens = get_generic_target_tokens()
    if target_tokens and any(token in text for token in target_tokens):
        for candidate in known_names:
            if candidate:
                return candidate
    return text


def _canonical_candidate_name(surface: str, role_hint: str, known_names: set[str], scene_hint: str) -> str:
    text = _canonical_character_name(surface, known_names)
    if text in known_names:
        return text
    canonical = get_canonical_name(surface)
    if canonical:
        return canonical
    return text


def _slot_hint_for_candidate(item: dict, scene_hint: str) -> str:
    slot = str(item.get('slot_hint', 'unknown') or 'unknown').strip().lower()
    if slot in {'conflict_target', 'pursuer', 'observer', 'key_object', 'ambient_group'}:
        return slot
    entity_type = str(item.get('entity_type', 'character') or 'character').strip().lower()
    if entity_type == 'object':
        return 'key_object'
    if entity_type == 'ambient_group':
        return 'ambient_group'
    return 'unknown'


def _role_label_for_name(name: str, role_label: str, scene_hint: str) -> str:
    text = str(role_label or '').strip()
    if text and text != '待确认':
        return text
    card_role = get_known_npc_role(name)
    if card_role:
        return card_role
    inferred = infer_role_label(name)
    return inferred if inferred else '待确认'


def _semantic_cleanup(payload: dict, prev_state: dict, state_fragment: dict) -> dict:
    normalized = dict(payload or {})
    known_names = set(str(item).strip() for item in (prev_state.get('onstage_npcs', []) or []) + (prev_state.get('relevant_npcs', []) or []))
    known_names.update(str(item).strip() for item in (state_fragment.get('onstage_npcs', []) or []) + (state_fragment.get('relevant_npcs', []) or []))
    scene_hint = ' '.join([
        str(normalized.get('main_event', '') or ''),
        str(state_fragment.get('main_event', '') or ''),
    ])

    def clean_legacy_entities() -> tuple[list[dict], list[str], list[str]]:
        cleaned_entities = []
        seen_names: set[str] = set()
        seen_entity_ids: dict[str, str] = {}
        raw_entities = [item for item in (normalized.get('scene_entities', []) or []) if isinstance(item, dict)]
        raw_labels = [
            _canonical_character_name(item.get('primary_label', ''), known_names)
            for item in raw_entities
            if _canonical_character_name(item.get('primary_label', ''), known_names)
        ]
        max_entity_idx = 0
        for item in raw_entities:
            entity_id = str(item.get('entity_id', '') or '').strip()
            if entity_id.startswith('scene_npc_'):
                try:
                    max_entity_idx = max(max_entity_idx, int(entity_id.split('_')[-1]))
                except Exception:
                    pass
        next_entity_idx = max_entity_idx + 1 if max_entity_idx else 1

        for idx, item in enumerate(normalized.get('scene_entities', []) or []):
            if not isinstance(item, dict):
                continue
            primary = _canonical_character_name(item.get('primary_label', ''), known_names)
            role_label = _role_label_for_name(primary, item.get('role_label', ''), scene_hint)
            if _looks_like_environment_entity(primary, role_label) or _looks_like_transient_group(primary, role_label) or _looks_like_non_character_object(primary, role_label):
                continue
            aliases_raw = item.get('aliases', []) or []
            normalized_aliases = [
                _canonical_character_name(alias, known_names)
                for alias in aliases_raw
                if _canonical_character_name(alias, known_names)
            ]
            if _is_shadow_like_label(primary):
                has_concrete_peer = any(
                    other != primary and not _is_shadow_like_label(other) and _labels_compatible(primary, other)
                    for other in raw_labels
                )
                if has_concrete_peer and not bool(item.get('onstage')) and _is_generic_role_label(role_label):
                    continue
                if not bool(item.get('onstage')) and _is_generic_role_label(role_label) and len(normalized_aliases) == 0:
                    continue
            if not primary or primary in seen_names:
                continue
            seen_names.add(primary)
            aliases = [primary]
            for alias_text in normalized_aliases:
                if alias_text and alias_text not in aliases and not _looks_like_environment_entity(alias_text, role_label) and not _looks_like_transient_group(alias_text, role_label) and not _looks_like_non_character_object(alias_text, role_label):
                    aliases.append(alias_text)
            entity_id = str(item.get('entity_id', f'scene_npc_{idx + 1:02d}') or f'scene_npc_{idx + 1:02d}').strip()
            prior_primary = seen_entity_ids.get(entity_id, '')
            if prior_primary and prior_primary != primary and not _labels_compatible(prior_primary, primary):
                entity_id = f'scene_npc_{next_entity_idx:02d}'
                next_entity_idx += 1
            seen_entity_ids[entity_id] = primary
            cleaned_entities.append({
                'entity_id': entity_id,
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
            if item['entity_type'] == 'character' and _is_shadow_like_label(item.get('surface', '')):
                strong_shadow_signal = (
                    item['confidence'] >= 0.85
                    and bool(item.get('onstage'))
                    and not _is_generic_role_label(item.get('role_hint', ''))
                    and bool(item.get('evidence'))
                )
                if not strong_shadow_signal:
                    continue
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
    if 'carryover_signals' in payload:
        recognized += 1
    if 'scene_entities' in payload:
        recognized += 1
        _validate_scene_entities(payload)
    if 'knowledge_scope' in payload:
        recognized += 1
        _validate_knowledge_scope(payload)

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


def _call_state_keeper_llm(user_prompt: str, *, max_attempts: int = 2) -> tuple[str, dict, int]:
    reply_text = ''
    usage: dict | None = None
    attempts = 0
    prompt = user_prompt
    for attempt in range(1, max(1, max_attempts) + 1):
        attempts = attempt
        reply_text, usage = call_role_llm('state_keeper', STATE_KEEPER_FILL_SYSTEM, prompt)
        if not isinstance(usage, dict):
            usage = {}
        usage['prompt_chars'] = len(STATE_KEEPER_FILL_SYSTEM) + len(prompt)
        if str(reply_text or '').strip():
            try:
                _parse_fill_payload(str(reply_text or ''))
                break
            except Exception:
                if attempt >= max(1, max_attempts):
                    break
                logger.warning('State-keeper returned unparsable output; retrying once')
                prompt = user_prompt + '\n\n上一次输出无法解析。请重新输出严格 JSON 对象；不要解释，不要代码块，不要在 JSON 前后添加文字。'
                continue
            break
        if attempt == 1:
            logger.warning('State-keeper returned empty output; retrying once')
    final_usage = usage if isinstance(usage, dict) else {}
    final_usage['retry_count'] = max(0, attempts - 1)
    return str(reply_text or ''), final_usage, attempts


def call_state_keeper(session_id: str, narrator_reply: str, state_fragment: Optional[dict] = None, *, user_text: str = '', return_trace: bool = False):
    """调用模型提取状态。

    Args:
        session_id: 会话 ID
        narrator_reply: 本轮 narrator 生成的叙事正文

    Returns:
        新的 state 字典
    """
    prev_state = load_state(session_id) or seed_default_state(session_id)
    state_fragment = state_fragment if isinstance(state_fragment, dict) else {}
    baseline_state = build_state_from_fragment(prev_state, state_fragment, session_id)
    user_prompt = _fill_user_prompt(baseline_state, narrator_reply, user_text=user_text)

    reply_text = ''
    usage: dict | None = None
    attempts = 0
    try:
        reply_text, usage, attempts = _call_state_keeper_llm(user_prompt)
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
        if isinstance(usage, dict):
            usage['retry_count'] = max(usage.get('retry_count', 0), max(0, attempts - 1))
        raise StateKeeperCallError(
            f'state_keeper_failed: {err}',
            usage=usage,
            raw_reply=reply_text,
        ) from err

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
            'user_text': user_text,
            'user_prompt': user_prompt,
            'raw_reply': reply_text,
            'payload': payload,
            'retry_count': max(0, attempts - 1),
        }
    return new_state
