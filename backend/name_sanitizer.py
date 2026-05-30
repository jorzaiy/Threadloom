#!/usr/bin/env python3
from __future__ import annotations

import ast
import re

try:
    from .paths import active_character_id, active_user_id
    from .player_profile import load_effective_player_profile
except ImportError:
    from paths import active_character_id, active_user_id
    from player_profile import load_effective_player_profile


# Per (user, character) cache: switching character cards (via ContextVar
# override or persisted active card) must not surface another card's
# protagonist names. lru_cache(maxsize=1) was process-global and leaked
# across requests when overrides differed.
_protagonist_names_cache: dict[tuple[str, str], frozenset[str]] = {}


def _protagonist_cache_key() -> tuple[str, str]:
    try:
        return (active_user_id(), active_character_id())
    except Exception:
        return ('', '')


def protagonist_names() -> set[str]:
    key = _protagonist_cache_key()
    cached = _protagonist_names_cache.get(key)
    if cached is not None:
        return set(cached)
    names: set[str] = set()
    data = load_effective_player_profile()
    for field in ('name', 'courtesyName'):
        value = str(data.get(field, '') or '').strip()
        if value:
            names.add(value)
    _protagonist_names_cache[key] = frozenset(names)
    return names


def invalidate_protagonist_names_cache() -> None:
    """Clear cached protagonist names. Call when active character/user changes."""
    _protagonist_names_cache.clear()


def sanitize_runtime_name(item) -> str:
    text = str(item or '').strip()
    if not text:
        return ''
    if text[0] == '{' and text[-1] == '}':
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return ''
        except Exception:
            return ''
    return text


GENERIC_MODIFIER_FRAGMENTS = {
    '淡淡', '轻轻', '缓缓', '静静', '冷冷', '慢慢', '低低', '轻声', '低声', '笑嘻嘻', '笑吟吟', '笑盈盈',
    '闷闷', '怔怔', '直直', '定定', '微微', '幽幽', '怯怯', '怔住', '顿住'
}


def looks_like_modifier_fragment(item) -> bool:
    text = sanitize_runtime_name(item)
    if not text:
        return False
    if text in GENERIC_MODIFIER_FRAGMENTS:
        return True
    if len(text) <= 4 and len(set(text)) <= 2 and text[:1] == text[1:2]:
        return True
    if len(text) <= 4 and text.endswith(('地', '着')):
        return True
    return False


VAGUE_ENTITY_FRAGMENTS = {
    '旁边几个', '附近几个', '周围几个', '门口几个', '门外几个',
    '这几个', '那几个', '几个', '一些', '一群', '一帮',
}

ABSTRACT_ENTITY_FRAGMENTS = {
    '时间', '空间', '规则', '概念', '逻辑', '关系', '事件', '问题', '目标', '答案', '线索', '风险',
    '情报', '记忆', '意识', '状态', '流程', '步骤', '进度', '盲区', '栏目', '标题', '课题', '题目',
}

ABSTRACT_ENTITY_PARTS = ('时间', '空间', '规则', '概念', '逻辑', '事件', '线索', '风险', '盲区', '栏目')

PERSON_ENTITY_SUFFIXES = (
    '人', '男人', '女人', '女子', '青年', '少年', '老者', '壮汉', '男生', '女生', '学员', '新生',
    '教官', '助教', '老师', '教员', '先生', '小姐', '女士', '夫人', '长官', '队长', '主管',
)

PROSE_ENTITY_PREFIXES = (
    '说是', '据说', '听说', '本以为', '谁知', '这里', '那里', '刚才', '昨夜', '今晨',
)


def looks_like_bad_entity_fragment(item) -> bool:
    """Reject short prose/quantifier fragments that are not stable entity names."""
    text = sanitize_runtime_name(item)
    if not text:
        return True
    if looks_like_modifier_fragment(text):
        return True
    if text in VAGUE_ENTITY_FRAGMENTS:
        return True
    if text in ABSTRACT_ENTITY_FRAGMENTS:
        return True
    if any(text.endswith(suffix) for suffix in ('栏', '栏位', '栏目', '盲区', '概念', '规则', '逻辑', '问题', '答案', '题目', '课题')):
        return True
    if any(part in text for part in ABSTRACT_ENTITY_PARTS) and not any(suffix in text for suffix in PERSON_ENTITY_SUFFIXES):
        return True
    if text.startswith(PROSE_ENTITY_PREFIXES):
        return True
    if re.match(r'^(?:旁边|附近|周围|门口|门外)?(?:几个|几名|一些|一群|一帮|一伙)$', text):
        return True
    return False


NON_PERSON_STRUCTURAL_SUBSTRINGS = (
    '代码', '日志', '终端', '编号', 'DNS', '批量', '组件', '模块', '本机', '窗口',
)

NON_PERSON_PLACE_SUFFIXES = (
    '馆', '柜台', '窗口', '日志', '编号', '代码', '排序', '机位', '模块', '组件', '系统', '终端',
    '文件', '文件夹', '文件袋', '地图', '档案', '名单', '公司', '区域', '教室', '楼层', '走廊',
    '学院', '学校', '基地', '中心', '部门', '办公室', '医务室', '训练场', '食堂', '宿舍', '靶场',
)


def looks_like_time_fragment(item) -> bool:
    text = sanitize_runtime_name(item)
    if not text:
        return False
    if any(period in text for period in ('凌晨', '清晨', '早晨', '上午', '中午', '午后', '下午', '傍晚', '晚上', '夜里', '深夜')):
        return True
    return bool(re.search(r'(?:\d+|[零一二两三四五六七八九十百半]+)\s*(?:点|时|分|秒)', text))


def looks_like_group_fragment(item) -> bool:
    text = sanitize_runtime_name(item)
    if not text:
        return False
    ordinal = r'(?:第\s*)?(?:\d+|[一二两三四五六七八九十百]+)'
    return bool(
        re.search(ordinal + r'\s*(?:组|波|队|批|轮|号位|号|排)', text)
        or re.search(r'(?:\d+|[一二两三四五六七八九十百]+)\s*人一组', text)
    )


def looks_like_non_person_alias_fragment(item) -> bool:
    text = sanitize_runtime_name(item)
    if not text:
        return True
    if any(part in text for part in NON_PERSON_STRUCTURAL_SUBSTRINGS):
        return True
    if looks_like_time_fragment(text) or looks_like_group_fragment(text):
        return True
    if text.endswith(NON_PERSON_PLACE_SUFFIXES):
        return True
    return False


def looks_like_low_quality_signal_fragment(item) -> bool:
    text = sanitize_runtime_name(item)
    if not text:
        return True
    if looks_like_modifier_fragment(text):
        return True
    if len(text) <= 4 and (text.endswith(('了', '着')) or len(set(text)) <= 2):
        return True
    if re.search(r'[\u4e00-\u9fff]{1,2}了[\u4e00-\u9fff]{1,2}$', text) and len(text) <= 5:
        return True
    return False


_POSTURE_BODY_PARTS = (
    '耳朵', '耳根', '尾巴', '手指', '指尖', '手腕', '手掌', '掌心', '五指', '拳', '指甲',
    '喉结', '喉咙', '眼', '眼睛', '眼角', '眼珠', '眼睫', '睫毛', '瞳孔', '嘴', '嘴角',
    '嘴唇', '下唇', '舌', '舌根', '肩', '肩膀', '背', '背脊', '脊', '下巴', '脖', '颈',
    '眉', '眉心', '脸', '脸色', '鼻', '脚', '腿', '膝', '胸', '腰',
)
_POSTURE_MOTIONS = (
    '转', '竖', '弯', '缩', '抬', '压低', '眯', '翘', '扫', '晃', '滚动', '跳动',
    '抿', '攥', '松开', '滑', '抖', '垂', '挑', '歪', '蜷', '颤', '哆嗦', '眨',
    '动一下', '动了', '一下', '一瞬', '半寸', '一寸', '两息', '三息', '盯着', '张了',
)


def looks_like_transient_posture(item) -> bool:
    """True for a one-off bodily posture / micro-action: a body part plus a
    transient motion, e.g. '耳朵朝声源转一下又转回' or '喉结动一下'.

    Such phrases get auto-captured by the keeper as persona hooks (mannerisms /
    behavior_mode), then re-injected into the actor registry every turn, priming
    the narrator to repeat the same gesture. Abstract dispositions ('谨慎多疑',
    '低声回答', '先确认身份') contain no body part and are kept.
    """
    text = str(item or '').strip()
    if not text:
        return False
    has_body = any(part in text for part in _POSTURE_BODY_PARTS)
    has_motion = any(motion in text for motion in _POSTURE_MOTIONS)
    return has_body and has_motion


def is_protagonist_name(item) -> bool:
    text = sanitize_runtime_name(item)
    if not text:
        return False
    return text in protagonist_names()
