#!/usr/bin/env python3
import re

from runtime_store import load_context, load_history, load_state, save_state, seed_default_state
from runtime_store import load_meta
from name_sanitizer import sanitize_runtime_name, looks_like_modifier_fragment, looks_like_bad_entity_fragment
from event_ledger import build_event_ledger_with_llm, core_value_quality
from entity_candidate_judge import judge_entity_candidates
from state_bridge import infer_role_label, normalize_state_dict

try:
    from keeper_archive import load_keeper_record_archive
except Exception:
    load_keeper_record_archive = None


SCENE_HEADER_RE = re.compile(r'^\s*(?:<[Tt]ime>\s*)?『(?P<header>[^』]+)』(?:\s*</[Tt]ime>)?')
GENERIC_TIME_RE = re.compile(r'(?P<date>\d{4}年[-/]\d{1,2}月[-/]\d{1,2}日(?:[-/][^–—\n]{1,8})?)')
GENERIC_CLOCK_RE = re.compile(r'(?P<clock>\d{1,2}:\d{2})')
GENERIC_NAME_RE = re.compile(r'[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?')
GENERIC_NON_PERSON_SUFFIXES = ('场', '区', '室', '楼', '廊', '道', '台', '墙', '门', '路', '馆', '堂', '院', '课', '处', '站', '宗', '派', '盟', '教', '帮', '会', '城', '国', '族', '阁', '殿', '府', '寨', '谷', '洞')
GENERIC_NON_NAME_PREFIXES = ('他', '她', '你', '我', '这', '那', '其')
GENERIC_GRAMMAR_PARTICLES = ('的', '了', '着', '从', '在', '把', '被', '向', '和', '与', '并', '将')
GENERIC_INTRO_NAME_RE = re.compile(r'(?:我叫|他叫|她叫|名叫|叫做|自称|名字是|在下|我名|吾名)(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)')
GENERIC_STANDALONE_NAME_RE = re.compile(r'(?:^|[\n“"‘「『《（(—-])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)(?=$|[\n”"’」』》）).,，。！？!?])')
GENERIC_APPELLATION_NAMES = {'少年', '男人', '女人', '男生', '女生', '学员', '教官', '老师', '同学', '对方', '那人', '青年', '师兄', '师姐', '师弟', '师妹', '小女孩', '小男孩', '老板娘', '掌柜', '老伯', '大叔', '大婶', '老汉', '学徒', '官差'}
CONCRETE_APPELLATION_NAMES = {'掌柜', '老板娘', '老伯', '大叔', '大婶', '师兄', '师姐', '师弟', '师妹', '老汉', '学徒', '官差'}
GENERIC_HONORIFIC_SUFFIXES = ('姑娘', '公子', '小姐', '先生', '夫人', '少爷', '少侠', '道友', '前辈')
GENERIC_NON_NAME_TOKENS = {
    '今天', '明天', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日',
    '上午', '下午', '中午', '清晨', '黄昏', '入夜', '深夜', '晴', '阴', '小雨', '大雨', '雨天',
    '训练场', '休息区', '集合点', '障碍区', '图书馆', '办公室', '宿舍楼', '走廊', '连廊', '食堂',
    '任务', '名单', '资料', '档案', '记录板', '学院', '特工学院', '大事记', '压缩饼干',
    '无妨', '单纯', '同行', '哗啦', '内力', '笨蛋', '当然', '家具', '好人', '反派', '高手', '公子',
    '姑娘', '陆姑娘', '路上', '猛地', '忍不住', '不知', '轻功', '自保', '一声',
    # Common Chinese words/phrases falsely matched as names
    '地下水', '大哥', '老子', '差点', '突然', '藏品', '书里', '徒劳地', '不过', '而且',
    '于是', '但是', '然后', '已经', '可能', '当时', '一切', '这里', '那边', '如果',
    '因为', '所以', '不是', '没有', '需要', '可以', '这样', '那样', '什么', '怎么',
    '自己', '大家', '别人', '有人', '旁边', '周围', '附近', '远处', '身边', '对面',
    '时候', '之前', '之后', '现在', '刚才', '马上', '一直', '终于', '忽然', '慢慢',
    '心里', '身上', '手中', '手里', '脸上', '眼前', '眼中', '头上', '脚下', '耳边',
    '开始', '继续', '停下', '回来', '出去', '过来', '起来', '下去', '出来', '回去',
    '知道', '看到', '听到', '感觉', '发现', '觉得', '明白', '理解', '记得', '忘记',
    '世界', '地方', '东西', '事情', '问题', '办法', '原因', '结果', '意思', '声音',
    # Colloquial terms and exclamations
    '老天', '天啊', '妈的', '我靠', '真的', '假的', '厉害', '漂亮', '恐怕', '大概',
    '简直', '居然', '竟然', '果然', '似乎', '仿佛', '总算', '原来', '确实', '毕竟',
    # Verbs/adjectives commonly mismatched as names
    '保护', '攻击', '防御', '控制', '治疗', '恢复', '释放', '召唤', '觉醒', '进化',
    '安静', '危险', '安全', '正常', '异常', '特殊', '普通', '强大', '弱小', '巨大',
    # More false positive names from test data
    '话別', '炉鼎', '哎哟', '嘴上', '别跟我', '嘿嘿', '冷冷地', '小女孩', '气得',
    '昨天', '昨晚', '技术性', '嘲讽地', '不要', '明明', '当九婴', '管理员', '师兄',
    '老板娘', '以下', '也没', '谁知', '真正', '反倒', '不爱', '至少', '随口', '真要',
    '若真要', '换句话', '解毒', '只肯', '有人只肯', '旁边有人', '忙嘿嘿一', '老人冷',
    '像随口一', '嘴里含糊', '却要分开', '至少知',
}
GENERIC_ABSTRACT_NAME_TOKENS = {
    '物理接触', '肢体接触', '身体接触', '接触', '互动', '机制', '系统', '面板', '提示', '规则', '判定', '反馈',
    '设定', '限制', '条件', '代价', '状态', '异常', '效果', '能力', '技能', '天赋', '特性', '权限', '接口',
    '流程', '步骤', '进度', '事件', '剧情', '关系', '概念', '逻辑', '认知', '现象', '目标', '问题', '风险',
    '线索', '情报', '消息', '痕迹', '记忆', '意识', '情绪', '欲望', '冲动', '杀意', '敌意', '压力',
}
GENERIC_ABSTRACT_NAME_PARTS = (
    '接触', '互动', '机制', '系统', '规则', '判定', '反馈', '设定', '限制', '条件', '状态', '效果', '能力',
    '技能', '天赋', '特性', '流程', '步骤', '进度', '事件', '剧情', '关系', '概念', '逻辑', '认知', '现象',
    '目标', '问题', '风险', '线索', '情报', '记忆', '意识', '情绪', '欲望', '冲动', '杀意', '敌意',
)
GENERIC_ABSTRACT_NAME_PREFIXES = ('物理', '精神', '心理', '自动', '被动', '主动', '外部', '内部', '当前', '后续', '持续')
GENERIC_ABSTRACT_NAME_SUFFIXES = ('机制', '系统', '规则', '判定', '反馈', '设定', '限制', '条件', '状态', '效果', '能力', '技能', '关系', '概念', '逻辑', '现象', '问题', '风险', '线索', '情报')
GENERIC_INFO_PHRASE_RE = re.compile(r'^[一二三四五六七八九十两几半多整\d]+(?:处|条|座|份|项|处私盐|路|线|页|封|张|本|箱|匣|人)?[\u4e00-\u9fff]{0,6}$')
GENERIC_TIME_PERIODS = ('清晨', '早晨', '上午', '近午', '午后', '下午', '黄昏', '入夜', '夜晚', '深夜', '凌晨', '傍晚')
GENERIC_LOCATION_CANDIDATE_RE = re.compile(r'([\u4e00-\u9fffA-Za-z0-9·\-]{2,24}(?:场|区|室|楼|廊|台|门前|门口|门|路|馆|堂|院|厅|阁|府|宫|殿|街|巷|亭|轩))')
GENERIC_LOCATION_MIN_QUALITY_LEN = 3  # candidate must be ≥ 3 chars to be useful
GENERIC_BAD_LOCATION_PREFIXES = ('这句', '那句', '已经', '仍在', '正在', '随后', '然后', '如果', '因为', '所以', '只是', '开篇', '就在', '那个', '这个', '一个', '属于')
GENERIC_BAD_LOCATION_CONTAINS = ('里', '了', '说', '问', '觉得', '已经', '仍在', '正在', '掀起', '推进', '互动', '局势', '给读者', '明确的', '要给', '即将', '构筑')
GENERIC_LOCATION_LEADING_WORDS = ('在', '于', '从', '向', '到')
NAME_TRAILING_ACTION_RE = re.compile(r'^(?P<base>[\u4e00-\u9fff]{2,8}?)(?P<trail>先赔|赔笑|嗤笑|嗤|冷笑|笑了笑|笑道|笑着|低声道|低声|抬眼|抬起头|开口|回道|答道|说道|没有说话|先开口|先应声|应声|喝道|厉喝|骂道)$')


def _short_plain(text: str, limit: int = 24) -> str:
    one = ' '.join(str(text or '').split()).strip()
    if len(one) <= limit:
        return one
    return one[: limit - 3] + '...'


def _strip_scene_header(text: str) -> str:
    stripped = str(text or '').lstrip()
    match = SCENE_HEADER_RE.match(stripped)
    if not match:
        # Also try to strip <Time>...</Time> tags that wrap scene headers
        time_tag_re = re.compile(r'^\s*<[Tt]ime>[^<]*</[Tt]ime>\s*', re.MULTILINE)
        stripped = time_tag_re.sub('', stripped).lstrip('\n')
        return stripped
    return stripped[match.end():].lstrip('\n')


def _parse_scene_header(text: str) -> dict:
    raw_text = str(text or '').lstrip()
    match = SCENE_HEADER_RE.match(raw_text)
    if not match:
        # Try to find structured time/location blocks like:
        # 【血晶终端】 血蚀纪·03:12 PM ... 地点:xxx
        structured = _parse_structured_header_block(raw_text)
        if structured:
            return structured
        return {}
    raw = match.group('header').strip()
    clock_match = GENERIC_CLOCK_RE.search(raw)
    date = ''
    clock = ''
    location = ''
    weather = ''
    if clock_match:
        head = raw[:clock_match.start()].rstrip('-–— ')
        date = re.sub(r'\s+\d{1,2}:\d{2}$', '', head).strip()
        clock = clock_match.group('clock')
        tail = raw[clock_match.end():].lstrip('-–— ')
        if tail.startswith('AM') or tail.startswith('PM'):
            tail = tail[2:].lstrip('-–— ')
        if tail:
            tail_parts = [part.strip() for part in tail.split('-') if part.strip()]
            if tail_parts:
                if len(tail_parts) >= 2 and len(tail_parts[-1]) <= 4:
                    weather = tail_parts[-1]
                    location = '-'.join(tail_parts[:-1]).strip()
                else:
                    location = '-'.join(tail_parts).strip()
    else:
        parts = [part.strip() for part in re.split(r'[–—]+', raw) if part.strip()]
        date = parts[0] if parts else ''
        location = parts[1] if len(parts) >= 2 else ''
    time_label = ' '.join(part for part in (date, clock) if part).strip()
    return {
        'raw': raw,
        'date': date,
        'clock': clock,
        'location': location,
        'weather': weather,
        'time_label': time_label,
    }


_STRUCTURED_CLOCK_RE = re.compile(r'(\d{1,2}:\d{2})\s*(?:AM|PM)?')
_STRUCTURED_LOCATION_RE = re.compile(r'地点[:：]\s*(.+?)(?:\s*$|\s*\n)', re.MULTILINE)


def _parse_structured_header_block(text: str) -> dict:
    """Parse structured header blocks like 【血晶终端】 or 晶核/异能 stat blocks."""
    # Look for 地点: pattern
    loc_match = _STRUCTURED_LOCATION_RE.search(text[:600])
    if not loc_match:
        return {}
    location = loc_match.group(1).strip().strip("'\"''""")
    # Look for clock in the same block
    clock = ''
    clock_match = _STRUCTURED_CLOCK_RE.search(text[:loc_match.start()])
    if clock_match:
        clock = clock_match.group(1)
    time_label = clock or ''
    return {
        'raw': '',
        'date': '',
        'clock': clock,
        'location': location,
        'weather': '',
        'time_label': time_label,
    }


def _recent_role_item(items: list[dict], role: str) -> dict:
    for item in reversed(items):
        if item.get('role') == role:
            return item
    return {}


def _history_source_names(items: list[dict], role: str | None = None, limit: int = 12) -> list[str]:
    names = []
    for item in items or []:
        if role and item.get('role') != role:
            continue
        text = sanitize_runtime_name(item.get('source_name', ''))
        if text and text not in names:
            names.append(text)
        if len(names) >= limit:
            break
    return names


def _protagonist_name_hints(context: dict, history: list[dict]) -> set[str]:
    names = set(_history_source_names(history, role='user', limit=8))
    imported_user_name = sanitize_runtime_name((context or {}).get('imported_user_name', ''))
    if imported_user_name:
        names.add(imported_user_name)
    return names


def _seed_character_names(prev_state: dict, context: dict, history: list[dict]) -> list[str]:
    names = []
    for field in ('onstage_npcs', 'relevant_npcs'):
        for item in (prev_state.get(field, []) or []):
            text = sanitize_runtime_name(item)
            if text and text not in names:
                names.append(text)
    for item in (prev_state.get('important_npcs', []) or []):
        if not isinstance(item, dict):
            continue
        text = sanitize_runtime_name(item.get('primary_label', ''))
        if text and text not in names:
            names.append(text)
    imported_character_name = sanitize_runtime_name((context or {}).get('imported_character_name', ''))
    if imported_character_name and imported_character_name not in names:
        names.append(imported_character_name)
    for text in _history_source_names(history, role='assistant', limit=8):
        if text not in names:
            names.append(text)
    return names[:16]


def _prune_generic_appellations(names: list[str], prev_state: dict, context: dict, history: list[dict]) -> list[str]:
    stable_pool = set(_seed_character_names(prev_state, context, history))
    filtered = []
    for name in names or []:
        text = sanitize_runtime_name(name)
        if not text or text in filtered:
            continue
        if text in GENERIC_APPELLATION_NAMES and text not in stable_pool and text not in CONCRETE_APPELLATION_NAMES:
            continue
        filtered.append(text)
    return filtered


def _looks_like_character_name(candidate: str, excluded: set[str]) -> bool:
    text = sanitize_runtime_name(candidate)
    if not text or text in excluded:
        return False
    if looks_like_bad_entity_fragment(text):
        return False
    if text in CONCRETE_APPELLATION_NAMES:
        return True
    if not _has_character_label_shape(text):
        return False
    if text in GENERIC_NON_NAME_TOKENS:
        return False
    if _looks_like_function_fragment(text):
        return False
    if _looks_like_abstract_entity_name(text):
        return False
    if GENERIC_INFO_PHRASE_RE.match(text):
        return False
    if any(text.endswith(token) for token in GENERIC_HONORIFIC_SUFFIXES):
        return False
    if any(token in text for token in ('那个', '这样', '这种', '什么', '哪里', '怎么', '为什么')):
        return False
    if any(token in text for token in ('那桌', '这桌', '桌上', '桌边', '茶摊', '摊前', '摊边')):
        return False
    if text.endswith(('桌', '摊', '铺', '店', '柜台', '路口', '街口')):
        return False
    if text.startswith(GENERIC_NON_NAME_PREFIXES):
        return False
    if text.startswith(('先', '再', '又', '还', '仍', '继续', '低声', '终于', '忽然')):
        return False
    if any(token in text for token in GENERIC_GRAMMAR_PARTICLES):
        return False
    if any(ch.isdigit() for ch in text):
        return False
    if any(token in text for token in ('年', '月', '日', '星期', '『', '』')):
        return False
    if text.endswith(GENERIC_NON_PERSON_SUFFIXES):
        return False
    if len(text) < 2 or len(text) > 16:
        return False
    return True


def _has_character_label_shape(candidate: str) -> bool:
    text = sanitize_runtime_name(candidate)
    if not text:
        return False
    if '·' in text:
        return True
    if text in GENERIC_APPELLATION_NAMES:
        return True
    if text.endswith(('人', '者', '客', '汉', '夫', '妇', '翁', '婆', '伯', '叔', '婶', '姨', '童', '士', '兵', '差', '役', '吏', '商', '贩', '主', '老板', '掌柜', '摊主', '伙计', '小二', '客人', '老人', '老头', '男子', '女子', '男人', '女人', '青年', '少年', '姑娘', '公子')):
        return True
    if text.startswith(('老', '小', '阿')) and 2 <= len(text) <= 4:
        return True
    return False


def _looks_like_function_fragment(candidate: str) -> bool:
    text = sanitize_runtime_name(candidate)
    if not text:
        return True
    if len(text) <= 2 and text not in CONCRETE_APPELLATION_NAMES:
        return True
    fragment_tokens = (
        '也', '没', '不', '要', '真', '正', '反', '倒', '至少', '随口', '若', '却', '只', '肯', '知',
        '句话', '有人', '旁边', '忙', '嘿嘿', '含糊', '分开', '解毒', '真正', '反倒', '谁知',
    )
    if any(token in text for token in fragment_tokens):
        return True
    if text.endswith(('地', '得', '了', '着', '过', '一')):
        return True
    return False


def _looks_like_abstract_entity_name(candidate: str) -> bool:
    text = sanitize_runtime_name(candidate)
    if not text:
        return False
    if text in GENERIC_ABSTRACT_NAME_TOKENS:
        return True
    if text.endswith(GENERIC_ABSTRACT_NAME_SUFFIXES):
        return True
    if any(text.startswith(prefix) and any(part in text[len(prefix):] for part in GENERIC_ABSTRACT_NAME_PARTS) for prefix in GENERIC_ABSTRACT_NAME_PREFIXES):
        return True
    if sum(1 for part in GENERIC_ABSTRACT_NAME_PARTS if part in text) >= 2:
        return True
    return False


def _score_name_candidate(name: str, text: str, seeded: list[str]) -> int:
    score = text.count(name)
    if name in seeded:
        score += 4
    if '·' in name:
        score += 3
    if re.search(rf'{re.escape(name)}(?:说|问|看|笑|道|想|站|走|跑|转|盯|看向|低声|开口|回答)', text):
        score += 2
    if re.search(rf'(?:对|朝|跟|叫|望向|看着){re.escape(name)}', text):
        score += 1
    return score


def _contains_seed_name_exactly(body: str, name: str) -> bool:
    if not name:
        return False
    if '·' in name:
        return name in body
    pattern = rf'(?<![\u4e00-\u9fff]){re.escape(name)}(?![\u4e00-\u9fff])'
    return re.search(pattern, body) is not None


def _name_occurrence_count(body: str, name: str) -> int:
    if not name:
        return 0
    if '·' in name:
        return body.count(name)
    pattern = rf'(?<![\u4e00-\u9fff]){re.escape(name)}(?![\u4e00-\u9fff])'
    return len(re.findall(pattern, body))


def _looks_like_character_context(body: str, name: str) -> bool:
    if not name:
        return False
    patterns = [
        rf'{re.escape(name)}(?:没有说话|开口|低声|轻声|笑道|说道|问道|答道|回道|说|问|笑|道|看向|转过头|抬起头|抬眼)',
        rf'{re.escape(name)}(?:朝|向|对|把|将|伸手|伸了手|递给|接过|拦住|站起|坐下|退后|走近|靠近)',
        rf'(?:看向|望向|听见|听到|对上){re.escape(name)}',
        rf'{re.escape(name)}(?:先生|公子|姑娘|少爷|小姐)',
    ]
    return any(re.search(pattern, body) for pattern in patterns)


def _strip_name_trailing_action(name: str) -> str:
    text = sanitize_runtime_name(name)
    if not text:
        return ''
    match = NAME_TRAILING_ACTION_RE.match(text)
    if not match:
        return text
    base = sanitize_runtime_name(match.group('base'))
    return base if len(base) >= 2 else text


def _is_action_anchored_appellation(body: str, name: str) -> bool:
    text = sanitize_runtime_name(name)
    if text not in CONCRETE_APPELLATION_NAMES:
        return False
    patterns = [
        rf'{re.escape(text)}(?:抬眼|低声|开口|回道|答道|说道|没有说话|赔笑|应声|嗤笑|喝道|厉喝|递给|拦住|盘问|追问|点头|摇头|招呼|提醒)',
        rf'{re.escape(text)}(?:看了她一眼|看了他一眼|看向|望向)',
    ]
    return any(re.search(pattern, body) for pattern in patterns)


def _has_strong_character_anchor(body: str, name: str, seeded: list[str]) -> bool:
    if not name:
        return False
    if name in seeded and _contains_seed_name_exactly(body, name):
        return True
    if _is_action_anchored_appellation(body, name):
        return True
    if _is_explicit_intro_name(body, name):
        return True
    occurrence_count = _name_occurrence_count(body, name)
    if _looks_like_character_context(body, name):
        return True
    if occurrence_count >= 2:
        return True
    return False


def _is_explicit_intro_name(body: str, name: str) -> bool:
    if not name:
        return False
    return re.search(rf'(?:我叫|他叫|她叫|名叫|叫做|自称|名字是){re.escape(name)}', body) is not None


def _extract_structured_name_candidates(body: str, seeded: list[str], excluded: set[str]) -> list[str]:
    candidates: list[str] = []
    explicit_names: set[str] = set()

    for name in seeded:
        if name and _contains_seed_name_exactly(body, name) and _looks_like_character_name(name, excluded) and name not in candidates:
            candidates.append(name)

    for pattern in (GENERIC_INTRO_NAME_RE,):
        for match in pattern.finditer(body):
            name = _strip_name_trailing_action(match.group('name'))
            if not _looks_like_character_name(name, excluded):
                continue
            if name not in candidates:
                candidates.append(name)
            explicit_names.add(name)

    for name in sorted(CONCRETE_APPELLATION_NAMES, key=len, reverse=True):
        if name in excluded:
            continue
        if not _is_action_anchored_appellation(body, name):
            continue
        if _looks_like_character_name(name, excluded) and name not in candidates:
            candidates.append(name)

    for match in GENERIC_STANDALONE_NAME_RE.finditer(body):
        name = _strip_name_trailing_action(match.group('name'))
        if not _looks_like_character_name(name, excluded):
            continue
        if not _has_strong_character_anchor(body, name, seeded):
            continue
        if name not in candidates:
            candidates.append(name)

    # More explicit inline speaker/name patterns for long-form prose.
    inline_patterns = [
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)见',
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)问',
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)说',
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)笑',
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)道',
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)那个',
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)抬起头',
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)没有说话',
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)的回答',
        r'(?:^|[\n。！？“"‘「『（(，, ])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)(?:朝|向|对|把|将|递给|接过|拦住|站起|坐下|退后|走近|靠近)',
    ]
    for pattern in inline_patterns:
        for match in re.finditer(pattern, body):
            name = _strip_name_trailing_action(match.group('name'))
            if not _looks_like_character_name(name, excluded):
                continue
            if not _has_strong_character_anchor(body, name, seeded):
                continue
            if name not in candidates:
                candidates.append(name)

    filtered: list[str] = []
    for name in candidates:
        if name in filtered:
            continue
        if name in explicit_names and _has_strong_character_anchor(body, name, seeded):
            filtered.append(name)
            continue
        if name in seeded and _contains_seed_name_exactly(body, name):
            filtered.append(name)
            continue
        if _has_strong_character_anchor(body, name, seeded):
            filtered.append(name)
            continue
    return filtered


def _stable_name_pool(prev_state: dict, history: list[dict]) -> list[str]:
    names = []
    for item in (prev_state.get('scene_entities', []) or []):
        if not isinstance(item, dict):
            continue
        primary = sanitize_runtime_name(item.get('primary_label', ''))
        if primary and primary not in names:
            names.append(primary)
        for alias in (item.get('aliases', []) or []):
            alias_text = sanitize_runtime_name(alias)
            if alias_text and alias_text not in names:
                names.append(alias_text)
    for field in ('onstage_npcs', 'relevant_npcs'):
        for item in (prev_state.get(field, []) or []):
            text = sanitize_runtime_name(item)
            if text and text not in names:
                names.append(text)
    for item in (prev_state.get('important_npcs', []) or []):
        if not isinstance(item, dict):
            continue
        text = sanitize_runtime_name(item.get('primary_label', ''))
        if text and text not in names:
            names.append(text)
    for item in history[-8:]:
        if item.get('role') != 'assistant':
            continue
        source_name = sanitize_runtime_name(item.get('source_name', ''))
        if source_name and source_name not in names:
            names.append(source_name)
    return names[:20]


def extract_generic_character_names(text: str, prev_state: dict, context: dict, history: list[dict], limit: int = 6) -> list[str]:
    body = _strip_scene_header(text)
    seeded = _seed_character_names(prev_state, context, history)
    excluded = _protagonist_name_hints(context, history)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()

    for name in _extract_structured_name_candidates(body, seeded, excluded):
        if name in seen:
            continue
        if name in seeded and _contains_seed_name_exactly(body, name):
            pass
        elif _is_explicit_intro_name(body, name):
            pass
        elif name in CONCRETE_APPELLATION_NAMES and _is_action_anchored_appellation(body, name):
            pass
        elif not _has_strong_character_anchor(body, name, seeded):
            continue
        seen.add(name)
        scored.append((_score_name_candidate(name, body, seeded), name))

    scored.sort(key=lambda item: (-item[0], body.find(item[1]) if item[1] in body else 10**9))
    heuristic_candidates = [name for _score, name in scored[: max(limit * 2, 8)]]
    anchored_concrete = [
        name for _score, name in scored
        if name in CONCRETE_APPELLATION_NAMES and _has_strong_character_anchor(body, name, seeded)
    ]
    judged = judge_entity_candidates(heuristic_candidates, body, _stable_name_pool(prev_state, history))
    if judged is not None:
        accepted = []
        for name in anchored_concrete:
            if name in excluded:
                continue
            if not _looks_like_character_name(name, excluded):
                continue
            if name not in accepted:
                accepted.append(name)
            if len(accepted) >= limit:
                return accepted
        for name in judged:
            if name in excluded:
                continue
            if not _looks_like_character_name(name, excluded):
                continue
            if not _has_strong_character_anchor(body, name, seeded):
                continue
            if name not in accepted:
                accepted.append(name)
            if len(accepted) >= limit:
                break
        return accepted
    accepted = []
    for _score, name in scored:
        if not _looks_like_character_name(name, excluded):
            continue
        if not _has_strong_character_anchor(body, name, seeded):
            continue
        if name not in accepted:
            accepted.append(name)
        if len(accepted) >= limit:
            break
    return accepted


def _extract_date_portion(time_str: str) -> str:
    """Extract only the date portion from a time string, discarding accumulated clocks."""
    text = str(time_str or '').strip()
    if not text:
        return ''
    date_match = GENERIC_TIME_RE.search(text)
    if date_match:
        return date_match.group('date').strip()
    # If no formal date, check for time-period words at the start
    for token in GENERIC_TIME_PERIODS:
        if text.startswith(token):
            return ''
    # If the string contains spaces, the first part might be a date-like token
    parts = text.split()
    if len(parts) >= 2 and GENERIC_CLOCK_RE.match(parts[-1]):
        return ' '.join(parts[:-1])
    # Single token that isn't a clock — treat as date-like context
    if parts and not GENERIC_CLOCK_RE.match(parts[0]):
        return parts[0]
    return ''


def infer_time_generic(text: str, prev_state: dict) -> str:
    header = _parse_scene_header(text)
    if header.get('time_label'):
        return header['time_label']
    body = _strip_scene_header(text)
    date_match = GENERIC_TIME_RE.search(body)
    clock_match = GENERIC_CLOCK_RE.search(body)
    if date_match and clock_match:
        return f"{date_match.group('date')} {clock_match.group('clock')}"
    if date_match:
        return date_match.group('date')
    if clock_match:
        # Replace the clock portion only — never append to an ever-growing string
        prev_date = _extract_date_portion(prev_state.get('time', ''))
        new_clock = clock_match.group('clock')
        return f'{prev_date} {new_clock}'.strip() if prev_date else new_clock
    for token in GENERIC_TIME_PERIODS:
        if token in body:
            prev_date = _extract_date_portion(prev_state.get('time', ''))
            return f'{prev_date} {token}'.strip() if prev_date else token
    return ''


def infer_location_generic(text: str) -> str:
    header = _parse_scene_header(text)
    if header.get('location'):
        return header['location']
    body = _strip_scene_header(text)
    for match in GENERIC_LOCATION_CANDIDATE_RE.finditer(body):
        candidate = match.group(1).strip()
        if not candidate or len(candidate) < GENERIC_LOCATION_MIN_QUALITY_LEN:
            continue
        for prefix in GENERIC_LOCATION_LEADING_WORDS:
            if candidate.startswith(prefix) and len(candidate) >= len(prefix) + 2:
                candidate = candidate[len(prefix):].strip()
        if candidate.startswith(GENERIC_BAD_LOCATION_PREFIXES):
            continue
        if any(token in candidate for token in GENERIC_BAD_LOCATION_CONTAINS):
            continue
        if candidate.endswith('轩') and len(candidate) <= 2:
            continue
        # Reject candidates that look like sentence fragments (too many common chars)
        common_chars = sum(1 for ch in candidate if ch in '的了着是在从到把被向和与并将有没不也')
        if common_chars >= len(candidate) // 2:
            continue
        if candidate and len(candidate) >= GENERIC_LOCATION_MIN_QUALITY_LEN:
            return candidate
    return ''



# ---------------------------------------------------------------------------
# Prompt wrapper stripping (for user text that contains template tags)
# ---------------------------------------------------------------------------
_PROMPT_WRAPPER_RE = re.compile(r'<本轮用户输入>\s*(.*?)\s*</本轮用户输入>', re.DOTALL)
_PROMPT_PREFIX_RE = re.compile(r'^以下是用户的本轮输入[：:]\s*', re.MULTILINE)
_PROMPT_SUFFIX_RE = re.compile(r'\s*以上是用户的本轮输入.*$', re.MULTILINE | re.DOTALL)

# Meta/system text markers — lines containing these are prompt instructions, not RP content
_META_MARKERS = (
    '当前在什么', '剧情的主线', '适合进行', 'OOC', '给主角留出',
    '主角本轮行动', '写正文时', '以上是用户', '场景指导',
    'interactive_input', 'scene_direction', '以下输入', '代码为接下',
    '本轮用户输入', '极简要解读', '不做多余揣测', '情境分析',
    '**', '##',
    '阵营（', '阵营:', '种族:', '职业:', '属性:', '等级:',
    '性别:', '年龄:', '身高:', '体重:',
    '灵根（', '灵根:', '修为:', '境界:', '门派:',
)


def _strip_prompt_wrappers(text: str) -> str:
    """Strip prompt template wrappers from user text to get the actual RP content."""
    if not text:
        return ''
    match = _PROMPT_WRAPPER_RE.search(text)
    if match:
        return match.group(1).strip()
    result = _PROMPT_PREFIX_RE.sub('', text)
    result = _PROMPT_SUFFIX_RE.sub('', result)
    return result.strip()


def _is_meta_line(s: str) -> bool:
    """Check if a line is a meta/system instruction rather than RP content."""
    stripped = s.strip()
    if not stripped:
        return True
    if stripped.startswith(('- ', '1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')):
        return True
    # AI self-commentary / out-of-character meta
    if stripped.startswith(('修正：', '修正:', '注意：', '注意:', '说明：', '说明:',
                            '人物位置：', '人物位置:', '用户输入',
                            '<!--', '<!')):
        return True
    return any(marker in stripped for marker in _META_MARKERS)


# ---------------------------------------------------------------------------
# Sentence extraction and scoring
# ---------------------------------------------------------------------------
# Action verbs that indicate narrative events (scored higher)
_ACTION_VERBS = (
    '发现', '决定', '开始', '试图', '准备', '面对', '遇到', '进入', '离开',
    '攻击', '逃跑', '拒绝', '答应', '提出', '要求', '警告', '透露', '揭露',
    '改变', '获得', '失去', '保护', '选择', '觉醒', '突破', '完成', '失败',
    '对峙', '追逐', '战斗', '躲避', '潜入', '逃离', '拦住', '质问', '坦白',
    '救下', '抓住', '放手', '冲向', '退开', '挡住', '解开', '触发', '打断',
)

# Dialogue markers
_DIALOGUE_MARKERS = ('\u201c', '\u201d', '\u300c', '\u300d', '\uff1a', '说道', '问道', '喊道', '低声')

# Transition/event markers (very high score)
_EVENT_MARKERS = (
    '突然', '忽然', '猛地', '就在这时', '紧接着', '与此同时',
    '话音刚落', '不料', '谁知', '终于', '转而', '随即',
)

_GOAL_DECISION_PREFIXES = (
    '判断是否', '决定是否', '先判断', '先看看', '先看清', '先确认', '找机会', '设法', '尽量',
)

_GOAL_SPLIT_MARKERS = ('，或', '或者', '还是', '再决定', '然后', '再看')


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences, filtering empty/too-short ones."""
    raw = re.split(r'[。！？\n]+', text)
    result = []
    for s in raw:
        s = s.strip().strip('""\'\"「」『』〈〉《》')
        if len(s) >= 4:
            result.append(s)
    return result


def _score_sentence(s: str, purpose: str = 'event') -> float:
    """Score a sentence for relevance to a given purpose.

    purpose: 'event' (main_event), 'goal' (immediate_goal),
             'risk' (immediate_risks), 'clue' (carryover_clues)
    """
    score = 0.0
    slen = len(s)

    # Length preference: prefer moderate-length sentences (15-50 chars)
    if 15 <= slen <= 50:
        score += 1.0
    elif slen < 8 or slen > 80:
        score -= 1.0

    # Penalize meta lines
    if _is_meta_line(s):
        return -10.0

    # Action verbs
    action_count = sum(1 for v in _ACTION_VERBS if v in s)
    score += min(action_count * 1.5, 4.0)

    # Dialogue presence (moderate value)
    if any(m in s for m in _DIALOGUE_MARKERS):
        score += 0.5 if purpose == 'event' else 1.0

    # Event transition markers (high value for events)
    if purpose == 'event' and any(m in s for m in _EVENT_MARKERS):
        score += 2.0

    # Purpose-specific scoring
    if purpose == 'risk':
        risk_words = ('危险', '威胁', '陷阱', '暴露', '怀疑', '受伤', '失控', '追兵',
                      '中毒', '感染', '围堵', '风险', '死', '杀', '伤', '恐', '惧')
        score += sum(1.5 for w in risk_words if w in s)
    elif purpose == 'clue':
        clue_words = ('发现', '线索', '秘密', '真相', '情报', '暗示', '记忆', '异常',
                      '标记', '信号', '证据', '密码', '隐藏', '记号', '钥匙', '地图')
        score += sum(1.5 for w in clue_words if w in s)
    elif purpose == 'goal':
        goal_words = ('想要', '打算', '决定', '准备', '需要', '必须', '得', '要',
                      '试试', '找', '去', '问', '看看', '确认', '弄清')
        score += sum(1.0 for w in goal_words if w in s)

    return score


def _extract_top_sentences(text: str, purpose: str = 'event',
                           max_count: int = 1, max_len: int = 40) -> list[str]:
    """Extract the top-scoring sentences from text for a given purpose."""
    if not text:
        return []
    sentences = _split_into_sentences(text)
    if not sentences:
        return []

    scored = [(s, _score_sentence(s, purpose)) for s in sentences]
    scored.sort(key=lambda x: -x[1])

    results = []
    for s, sc in scored:
        if sc < 0:
            continue
        if len(s) > max_len:
            # Try to truncate at a natural break
            for brk in ('，', '；', ',', '——', '……'):
                idx = s.find(brk, max_len // 2)
                if 0 < idx < max_len:
                    s = s[:idx]
                    break
            else:
                s = s[:max_len - 1] + '…'
        results.append(s)
        if len(results) >= max_count:
            break
    return results


def _extract_key_sentence(text: str, max_len: int = 40) -> str:
    """Extract the single most informative sentence from text."""
    results = _extract_top_sentences(text, purpose='event', max_count=1, max_len=max_len)
    return results[0] if results else ''


def _normalize_goal_phrase(text: str) -> str:
    value = ' '.join(str(text or '').split()).strip()
    if not value:
        return ''
    value = re.sub(r'^(?:我|她|他|主角)?(?:没有|并未|没)?(?:立刻|马上|直接)?(?:出手|行动|过去|上前)[，,、 ]*', '', value)
    value = re.sub(r'^(?:只|只是|仍|还)?(?:在|先)?(?:檐下|暗处|原地)?(?:继续)?(?:看着?|观察着?|打量着?)?[，,、 ]*', '', value)
    value = re.sub(r'^(?:想|准备|打算)(?:着)?', '', value)
    for marker in _GOAL_SPLIT_MARKERS:
        idx = value.find(marker)
        if idx > 0:
            value = value[:idx].strip(' ，、；:：')
            break
    value = value.strip(' ，、；:：。！？!?,')
    if len(value) > 28:
        for brk in ('，', '；', ',', '——', '……'):
            idx = value.find(brk, 10)
            if 0 < idx < 28:
                value = value[:idx].strip()
                break
        else:
            value = value[:28].rstrip('，、；:：')
    return value


def _looks_like_goal_phrase(text: str) -> bool:
    value = _normalize_goal_phrase(text)
    if not value:
        return False
    if len(value) < 5:
        return False
    if _looks_like_core_fragment(value):
        return False
    goalish_tokens = ('判断', '决定', '确认', '试探', '观察', '藏身', '介入', '脱身', '避开', '救人', '离开', '靠近', '跟上', '稳住', '拖住')
    if any(value.startswith(prefix) for prefix in _GOAL_DECISION_PREFIXES):
        return True
    if any(token in value for token in goalish_tokens):
        return True
    return False


def _looks_like_core_fragment(text: str) -> bool:
    value = ' '.join(str(text or '').split()).strip()
    if not value:
        return True
    if '→' in value:
        return True
    if len(value) < 4:
        return True
    if value.count('：') + value.count(':') >= 1:
        return True
    if len(value) <= 18 and value[:1] in {'我', '你', '他', '她'}:
        return True
    if len(value) <= 24 and '，' in value:
        return True
    if value.startswith(('靠着', '贴着', '撇撇嘴', '皱着眉', '仰着头', '低头', '吃了一半', '喝了几口', '满足的')):
        return True
    return False


# ---------------------------------------------------------------------------
# Main event inference
# ---------------------------------------------------------------------------
def _summarize_event(user_text: str, assistant_text: str, onstage_names: list[str] = None) -> str:
    """Try to build a concise main_event summary from the narrative.

    Strategy:
    1. Find the highest-scoring event sentence from assistant text
    2. If user text has a clear action, combine: "主角动作 → 叙事响应"
    3. Fallback to best sentence alone
    """
    clean_user = _strip_prompt_wrappers(user_text)

    # Get the best event sentence from assistant response
    asst_best = _extract_top_sentences(assistant_text, purpose='event', max_count=1, max_len=35)

    # Get user action (shorter, focused on intent)
    user_best = _extract_top_sentences(clean_user, purpose='goal', max_count=1, max_len=20)

    if user_best and _looks_like_core_fragment(user_best[0]):
        user_best = []
    if user_best and asst_best:
        return f'{user_best[0]}→{asst_best[0]}'
    if asst_best:
        return asst_best[0]
    if user_best:
        return user_best[0]
    return ''


def _is_generic_main_event(value: str) -> bool:
    text = ' '.join(str(value or '').split()).strip()
    if not text:
        return True
    generic_patterns = (
        '当前局势正围绕', '当前局面仍在', '局势已转到',
        '里的局势正围绕', '成为当前场面重心',
        '当前互动', '局势推进', '训练考核', '同行安排',
    )
    return any(p in text for p in generic_patterns)


def infer_main_event_generic(user_text: str, assistant_text: str, location: str, prev_location: str) -> str:
    summary = _summarize_event(user_text, assistant_text)
    if summary and not _looks_like_core_fragment(summary):
        return summary

    # Fallback: try to describe using location change
    prev_effective = prev_location if has_signal(prev_location) and prev_location != '待确认' else ''
    if location and prev_effective and location != prev_effective:
        return f'场景转至{location}'
    if location:
        key = _extract_key_sentence(assistant_text, max_len=30)
        return key if key and not _looks_like_core_fragment(key) else f'{location}中的互动'
    return '剧情推进中'


def _refine_main_event(summary_text: str, fallback: str, location: str) -> str:
    candidate = ' '.join(str(summary_text or '').split()).strip()
    if candidate and len(candidate) >= 8 and len(candidate) <= 72 and not _is_generic_main_event(candidate):
        return candidate
    fallback_text = ' '.join(str(fallback or '').split()).strip()
    if fallback_text and not _is_generic_main_event(fallback_text):
        return fallback_text
    if location:
        return f'{location}中的局势持续推进'
    return fallback_text or candidate or '剧情推进中'


def _should_replace_stale_main_event(current_main_event: str, ledger_summary: str, *, current_onstage: list[str]) -> bool:
    current_text = ' '.join(str(current_main_event or '').split()).strip()
    summary_text = ' '.join(str(ledger_summary or '').split()).strip()
    if not summary_text:
        return False
    if _is_generic_main_event(current_text):
        return True
    if current_text and len(current_text) <= 24 and ('“' in current_text or '：' in current_text):
        return True
    overlap = sum(1 for name in (current_onstage or []) if name and name in current_text and name in summary_text)
    if overlap == 0 and current_text and summary_text and current_text != summary_text:
        return True
    return False


def _should_refresh_main_event(session_id: str, prev_state: dict, inferred_location: str, assistant_text: str, inferred_onstage: list[str]) -> bool:
    meta = load_meta(session_id)
    next_turn_id = int(meta.get('last_turn_id', 0) or 0) + 1
    prev_location = str(prev_state.get('location', '') or '').strip()
    if inferred_location and inferred_location != prev_location and has_signal(prev_location):
        return True
    prev_onstage = [sanitize_runtime_name(name) for name in (prev_state.get('onstage_npcs', []) or []) if sanitize_runtime_name(name)]
    overlap = len(set(prev_onstage) & set(inferred_onstage))
    if prev_onstage and inferred_onstage and overlap <= max(0, min(len(prev_onstage), len(inferred_onstage)) - 2):
        return True
    return next_turn_id <= 2 or next_turn_id % 12 == 0


# ---------------------------------------------------------------------------
# Immediate goal inference
# ---------------------------------------------------------------------------
def infer_immediate_goal_generic(user_text: str, assistant_text: str, location: str, prev_location: str) -> str:
    """Extract the player's current intention or next action from user text.

    Tries to summarize the intent rather than copying raw user text verbatim.
    """
    clean_user = _strip_prompt_wrappers(user_text)

    normalized_user_goal = _normalize_goal_phrase(clean_user)
    if _looks_like_goal_phrase(normalized_user_goal):
        return normalized_user_goal

    # If the user text contains an explicit decision/intent phrase anywhere,
    # prefer that over narrator-derived continuation text.
    user_goal_candidates = _extract_top_sentences(clean_user, purpose='goal', max_count=3, max_len=28)
    for candidate in user_goal_candidates:
        raw = _normalize_goal_phrase(candidate)
        raw = re.sub(r'^(?:小声|低声|嘟囔着|呜咽着|咕哝着|笑着|皱着眉头)?(?:说|问|道|喊|叫|答|喃喃|嘟囔)\s*[：:]\s*', '', raw)
        if _looks_like_goal_phrase(raw):
            return raw

    # If the user text is short enough already (< 20 chars), use it directly
    if clean_user and len(clean_user) <= 20 and not _is_meta_line(clean_user) and not _looks_like_core_fragment(clean_user):
        return clean_user

    # Try from assistant's narrative only when the user text is too weak to
    # produce a stable next-beat goal.
    asst_goal = _extract_top_sentences(assistant_text, purpose='goal', max_count=1, max_len=25)
    if asst_goal:
        raw = _normalize_goal_phrase(asst_goal[0])
        if _looks_like_goal_phrase(raw):
            return raw

    # Fallback based on context
    prev_effective = prev_location if has_signal(prev_location) and prev_location != '待确认' else ''
    if location and prev_effective and location != prev_effective:
        return '适应新场景，决定下一步行动'
    return '观察眼前局面，决定下一步'


# ---------------------------------------------------------------------------
# Immediate risks inference
# ---------------------------------------------------------------------------
def infer_immediate_risks_generic(user_text: str, assistant_text: str, location: str, prev_location: str, onstage_count: int = 0) -> list[str]:
    """Extract concrete risks/threats from the narrative text (assistant only)."""
    # Only extract risks from assistant text — user text is player intent, not narrative threats
    risk_sentences = _extract_top_sentences(assistant_text, purpose='risk', max_count=3, max_len=30)
    risks = [s for s in risk_sentences if _score_sentence(s, 'risk') >= 2.0]
    return _clean_signal_list(risks, limit=3)


# ---------------------------------------------------------------------------
# Carryover clues inference
# ---------------------------------------------------------------------------
def infer_carryover_clues_generic(user_text: str, assistant_text: str, location: str, prev_location: str) -> list[str]:
    """Extract information clues worth tracking from the narrative."""
    # Extract clue-relevant sentences from assistant text (primary source)
    clue_sentences = _extract_top_sentences(assistant_text, purpose='clue', max_count=3, max_len=30)
    clues = [s for s in clue_sentences if _score_sentence(s, 'clue') >= 2.0]
    return _clean_signal_list(clues, limit=3)


def _build_carryover_signals(risks: list[str], clues: list[str], limit: int = 6) -> list[dict]:
    signals = []
    seen = set()
    risk_set = {str(item).strip() for item in (risks or []) if str(item).strip()}
    clue_set = {str(item).strip() for item in (clues or []) if str(item).strip()}
    for text in list(risk_set) + list(clue_set):
        signal_type = 'mixed' if (text in risk_set and text in clue_set) else ('risk' if text in risk_set else 'clue')
        key = (signal_type, text)
        if key in seen:
            continue
        seen.add(key)
        signals.append({'type': signal_type, 'text': text})
        if len(signals) >= limit:
            break
    return signals




def infer_onstage_npcs_generic(text: str, prev_state: dict, context: dict, history: list[dict]) -> list[str]:
    return extract_generic_character_names(text, prev_state, context, history, limit=4)


def infer_relevant_npcs_generic(text: str, onstage: list[str], prev_state: dict, context: dict, history: list[dict]) -> list[str]:
    seeded = []
    for item in (prev_state.get('important_npcs', []) or []):
        if not isinstance(item, dict):
            continue
        name = sanitize_runtime_name(item.get('primary_label', ''))
        if name and name not in seeded:
            seeded.append(name)
    for item in (prev_state.get('scene_entities', []) or []):
        if not isinstance(item, dict):
            continue
        name = sanitize_runtime_name(item.get('primary_label', ''))
        if name and name not in seeded:
            seeded.append(name)
    recent_assistant = '\n'.join(
        str(item.get('content', '') or '')
        for item in history[-6:]
        if item.get('role') == 'assistant'
    )
    relevant = []
    for name in seeded:
        if name in onstage:
            continue
        if name and _contains_seed_name_exactly(recent_assistant, name) and name not in relevant:
            relevant.append(name)
        if len(relevant) >= 6:
            break
    return relevant[:6]


def retain_relevant_window(prev_state: dict, next_state: dict, history: list[dict], *, window_pairs: int = 3) -> dict:
    onstage = [sanitize_runtime_name(name) for name in (next_state.get('onstage_npcs', []) or []) if sanitize_runtime_name(name)]
    relevant = [sanitize_runtime_name(name) for name in (next_state.get('relevant_npcs', []) or []) if sanitize_runtime_name(name) and sanitize_runtime_name(name) not in onstage]
    if not history:
        next_state['relevant_npcs'] = relevant[:6]
        return next_state

    recent_pairs = []
    current_user = None
    for item in history:
        if item.get('role') == 'user':
            current_user = item
        elif item.get('role') == 'assistant' and current_user is not None:
            recent_pairs.append((current_user, item))
            current_user = None
    recent_pairs = recent_pairs[-window_pairs:]
    recent_text = '\n'.join(
        str(part.get('content', '') or '')
        for pair in recent_pairs
        for part in pair
    )

    scene_entity_names = [
        sanitize_runtime_name(item.get('primary_label', ''))
        for item in (prev_state.get('scene_entities', []) or [])
        if isinstance(item, dict) and sanitize_runtime_name(item.get('primary_label', ''))
    ]
    important_names = [
        sanitize_runtime_name(item.get('primary_label', ''))
        for item in (prev_state.get('important_npcs', []) or [])
        if isinstance(item, dict) and sanitize_runtime_name(item.get('primary_label', ''))
    ]
    relevant_pool = []
    for name in important_names + scene_entity_names + [
        sanitize_runtime_name(name)
        for name in (prev_state.get('relevant_npcs', []) or [])
        if sanitize_runtime_name(name)
    ]:
        if name and name not in relevant_pool:
            relevant_pool.append(name)

    for name in relevant_pool:
        if not name or name in onstage or name in relevant:
            continue
        if _contains_seed_name_exactly(recent_text, name):
            relevant.append(name)
        if len(relevant) >= 6:
            break

    next_state['relevant_npcs'] = relevant[:6]
    return next_state


def has_signal(value: str) -> bool:
    text = (value or '').strip()
    if not text or text == '待确认' or '暂无' in text:
        return False
    if text in {'待根据开局建立', '待开局生成'}:
        return False
    if text.startswith('开局：'):
        return False
    if text.startswith('先应对当前开局局势'):
        return False
    return True


def prefer_existing(existing: str, inferred: str) -> str:
    existing_text = (existing or '').strip()
    inferred_text = (inferred or '').strip()
    if has_signal(existing_text) and not has_signal(inferred_text):
        return existing_text
    return inferred_text or existing_text or '待确认'


def merge_name_lists(prev_items: list[str], inferred_items: list[str], *, limit: int = 5) -> list[str]:
    merged = []
    for item in inferred_items + prev_items:
        text = str(item or '').strip()
        if not text or text in merged:
            continue
        merged.append(text)
        if len(merged) >= limit:
            break
    return merged


def retain_strong_lists(prev_state: dict, next_state: dict) -> dict:
    prev_onstage = [sanitize_runtime_name(name) for name in (prev_state.get('onstage_npcs', []) or []) if sanitize_runtime_name(name)]
    next_onstage = [sanitize_runtime_name(name) for name in (next_state.get('onstage_npcs', []) or []) if sanitize_runtime_name(name)]
    prev_relevant = [sanitize_runtime_name(name) for name in (prev_state.get('relevant_npcs', []) or []) if sanitize_runtime_name(name)]
    next_relevant = [sanitize_runtime_name(name) for name in (next_state.get('relevant_npcs', []) or []) if sanitize_runtime_name(name)]

    if prev_onstage and len(next_onstage) < max(1, min(2, len(prev_onstage) - 1)):
        next_state['onstage_npcs'] = merge_name_lists(prev_onstage, next_onstage, limit=6)
    if prev_relevant and not next_relevant:
        next_state['relevant_npcs'] = merge_name_lists(prev_relevant, next_relevant, limit=6)
    return next_state


def _looks_weak_entity_name(name: str) -> bool:
    text = sanitize_runtime_name(name)
    if not text:
        return True
    if text in CONCRETE_APPELLATION_NAMES:
        return False
    if len(text) <= 2:
        return True
    if text in GENERIC_NON_NAME_TOKENS:
        return True
    return False


def _guard_entity_collapse(prev_state: dict, next_state: dict) -> dict:
    prev_entities = [item for item in (prev_state.get('scene_entities', []) or []) if isinstance(item, dict)]
    next_entities = [item for item in (next_state.get('scene_entities', []) or []) if isinstance(item, dict)]
    prev_names = [sanitize_runtime_name(item.get('primary_label', '')) for item in prev_entities if sanitize_runtime_name(item.get('primary_label', ''))]
    next_names = [sanitize_runtime_name(item.get('primary_label', '')) for item in next_entities if sanitize_runtime_name(item.get('primary_label', ''))]
    if len(prev_names) >= 2 and len(next_names) == 1 and _looks_weak_entity_name(next_names[0]):
        next_state['scene_entities'] = prev_entities
        next_state['onstage_npcs'] = [sanitize_runtime_name(name) for name in (prev_state.get('onstage_npcs', []) or []) if sanitize_runtime_name(name)][:6]
        next_state['relevant_npcs'] = [sanitize_runtime_name(name) for name in (prev_state.get('relevant_npcs', []) or []) if sanitize_runtime_name(name)][:6]
    return next_state


def recent_role_text(items, role: str, limit: int = 4) -> str:
    selected = [i.get('content', '') for i in items if i.get('role') == role]
    return '\n'.join(selected[-limit:])


def recent_text(items, limit: int = 8) -> str:
    return '\n'.join(i.get('content', '') for i in items[-limit:])


def infer_time(text: str) -> str:
    return ''


def infer_location(text: str) -> str:
    return ''


def infer_main_event(text: str) -> str:
    return ''


def infer_relevant_npcs(text: str, onstage: list[str]) -> list[str]:
    return []


def _legacy_state_signals(text: str) -> bool:
    return False


def infer_implicit_relevant(prev_state: dict, assistant_text: str, onstage: list[str], relevant: list[str]) -> list[str]:
    text = assistant_text or ''
    important_npcs = [
        item for item in (prev_state.get('important_npcs', []) or [])
        if isinstance(item, dict) and item.get('locked')
    ]
    active_threads = [
        item for item in (prev_state.get('active_threads', []) or [])
        if isinstance(item, dict) and item.get('status') in {'active', 'watch'}
    ]
    thread_haystack = ' '.join(
        ' '.join(str(item.get(field, '') or '') for field in ('label', 'goal', 'obstacle', 'latest_change'))
        for item in active_threads
    )
    clue_haystack = ' '.join(prev_state.get('carryover_clues', []) or [])
    risk_haystack = ' '.join(prev_state.get('immediate_risks', []) or [])
    combined = ' '.join([text, thread_haystack, clue_haystack, risk_haystack])

    for item in important_npcs:
        label = sanitize_runtime_name(item.get('primary_label', ''))
        if not label or label in onstage or label in relevant:
            continue
        aliases = [sanitize_runtime_name(alias) for alias in (item.get('aliases') or []) if sanitize_runtime_name(alias)]
        name_tokens = [label] + aliases
        continuity_hits = 0
        if any(token and token in combined for token in name_tokens):
            continuity_hits += 2
        if any(token and token in thread_haystack for token in name_tokens):
            continuity_hits += 1
        role_label = str(item.get('role_label', '') or '').strip()
        if role_label and role_label in combined:
            continuity_hits += 1
        if item.get('retained'):
            continuity_hits += 1
        if continuity_hits >= 2 and len(relevant) < 5:
            relevant.append(label)
    return relevant[:6]


def preserve_recent_names(prev_state: dict, assistant_text: str, onstage: list[str], relevant: list[str], *, location_changed: bool = False) -> tuple[list[str], list[str]]:
    prev_onstage = [sanitize_runtime_name(name) for name in (prev_state.get('onstage_npcs', []) or []) if sanitize_runtime_name(name)]
    prev_relevant = [sanitize_runtime_name(name) for name in (prev_state.get('relevant_npcs', []) or []) if sanitize_runtime_name(name)]
    important_names = [
        sanitize_runtime_name(item.get('primary_label', ''))
        for item in (prev_state.get('important_npcs', []) or [])
        if isinstance(item, dict) and item.get('locked') and sanitize_runtime_name(item.get('primary_label', ''))
    ]
    hinted_names = [
        sanitize_runtime_name(item.get('primary_label', ''))
        for item in (prev_state.get('continuity_hints', []) or [])
        if isinstance(item, dict) and sanitize_runtime_name(item.get('primary_label', ''))
    ]
    text = assistant_text or ''

    explicit_departure = any(token in text for token in ['离去', '离开', '走远', '不见了', '消失', '散了', '各自散了', '只剩下'])
    if not explicit_departure:
        if not location_changed:
            for name in prev_onstage:
                if name not in onstage and len(onstage) < 5:
                    onstage.append(name)
        else:
            for name in prev_onstage:
                if name not in onstage and name not in relevant and len(relevant) < 5:
                    relevant.append(name)
        for name in prev_relevant:
            if name not in onstage and name not in relevant and len(relevant) < 5:
                relevant.append(name)
        for name in important_names:
            if name not in onstage and name not in relevant:
                if location_changed:
                    relevant.append(name)
                elif len(onstage) < 5:
                    onstage.append(name)
                elif len(relevant) < 5:
                    relevant.append(name)
        for name in hinted_names:
            if name not in onstage and name not in relevant and len(relevant) < 5:
                relevant.append(name)
    return onstage[:6], relevant[:6]


def infer_carryover_clues(text: str) -> list[str]:
    return []


def infer_onstage_npcs(text: str) -> list[str]:
    return []


OBJECT_MEASURE_PREFIX = re.compile(r'^(那|这|一|几|数)(?:个|件|封|卷|包|把|枚|只|本|张|份|块|柄)?')
OBJECT_LABEL_HINT_RE = re.compile(r'(帆布包|记录板|信封|纸条|名单|档案|本子|笔记|腰牌|令牌|钥匙|门闩|短刀|药瓶|药包|作训服|束胸带|水壶|水杯|台灯|油灯|铜牌|瓷瓶|热水|药布|布巾|餐盘|筷子|信|包)')
ENTITY_COUNT_PREFIX_RE = re.compile(r'^(?P<count>一|二|两|三|四|五|六|七|八|九|十|几|数)(?:个|名|位)?(?P<body>.+)$')
ENTITY_LEADING_VERB_RE = re.compile(r'^(穿着?|戴着?|披着?|背着?|提着?|拎着?|握着?|拿着?|持着?)')
ENTITY_DESCRIPTOR_SUFFIXES = ('中年人', '年轻人', '老年人', '灰衣人', '白衣人', '黑衣人', '皂衣人', '汉子', '老者', '青年', '女子', '男人', '女人', '人')
ENTITY_SLOT_MARKERS = ('高个', '矮个', '左侧', '右侧', '前头', '后侧', '靠门', '靠窗', '斗笠', '佩刀', '长衫', '灰衣', '黑衣', '白衣', '皂衣')


def _known_holder_names(prev_state: dict) -> list[str]:
    names = []
    for item in (prev_state.get('scene_entities', []) or []):
        if not isinstance(item, dict):
            continue
        label = sanitize_runtime_name(item.get('primary_label', ''))
        if label and label not in names:
            names.append(label)
        for alias in (item.get('aliases', []) or []):
            alias_text = sanitize_runtime_name(alias)
            if alias_text and alias_text not in names:
                names.append(alias_text)
    for field in ('onstage_npcs', 'relevant_npcs'):
        for item in (prev_state.get(field, []) or []):
            name = sanitize_runtime_name(item)
            if name and name not in names:
                names.append(name)
    return names[:12]


def _clean_object_label(label: str) -> str:
    text = str(label or '').strip().strip('“”"\' ')
    text = OBJECT_MEASURE_PREFIX.sub('', text).strip()
    text = re.sub(r'[，。；：、]+$', '', text).strip()
    return text[:20]


def _has_anchor_for_object(clause: str, holder: str = '', status: str = '', visibility: str = '') -> bool:
    if holder or status:
        return True
    text = str(clause or '').strip()
    if any(token in text for token in ('桌上', '地上', '柜台上', '床边', '窗边', '门后', '墙角', '榻上', '案上', '盘里', '桶里')):
        return True
    return False


def _upsert_object(objects_by_label: dict, next_index: int, label: str) -> tuple[dict, int]:
    normalized = _clean_object_label(label)
    if not normalized:
        return {}, next_index
    current = objects_by_label.get(normalized)
    if current:
        return current, next_index
    item = {
        'object_id': f'obj_{next_index:02d}',
        'label': normalized,
        'kind': 'item',
        'story_relevant': True,
    }
    objects_by_label[normalized] = item
    return item, next_index + 1


def _infer_object_kind(label: str) -> str:
    text = str(label or '').strip()
    if any(token in text for token in ('名单', '档案', '记录板', '本子', '笔记', '纸条', '信', '信封')):
        return 'document'
    if any(token in text for token in ('腰牌', '令牌', '钥匙')):
        return 'key_item'
    if any(token in text for token in ('包', '帆布包')):
        return 'container'
    if any(token in text for token in ('短刀',)):
        return 'weapon'
    if any(token in text for token in ('水壶', '水杯', '油灯', '台灯', '热水', '瓷瓶', '药瓶', '药包', '药布', '布巾')):
        return 'tool'
    return 'item'


def _is_story_relevant_object(label: str, *, status: str = '', holder: str = '', clause: str = '') -> bool:
    text = str(label or '').strip()
    if not text:
        return False
    if len(text) <= 1 and not (status or holder):
        return False
    discard_by_default = ('热水', '布巾', '药布', '餐盘', '筷子')
    if any(token in text for token in discard_by_default):
        return False
    always_keep = ('名单', '档案', '记录板', '纸条', '信', '信封', '腰牌', '令牌', '钥匙', '门闩', '帆布包', '包', '短刀')
    if any(token in text for token in always_keep):
        return True
    if status in {'revealed', 'transferred', 'seized'}:
        return True
    if any(token in text for token in ('作训服', '束胸带', '台灯', '水壶', '水杯')):
        return True
    if clause and any(token in clause for token in ('关键', '证据', '名单', '档案', '记录', '打开', '上锁', '开锁', '交给', '搜出', '摸出', '掏出')):
        return True
    return False


def _mark_object_with_holder(obj: dict, possession: dict, visibility: dict, holder: str, status: str, default_visibility: str) -> None:
    object_id = obj['object_id']
    possession[object_id] = {
        'object_id': object_id,
        'holder': holder,
        'status': status,
        'location': '身上' if status in {'carried', 'held'} else '',
        'updated_by_turn': '',
    }
    visibility[object_id] = {
        'object_id': object_id,
        'visibility': default_visibility,
        'known_to': [],
        'note': '',
    }


def _extract_free_objects(text: str, objects_by_label: dict, next_index: int) -> tuple[dict, int]:
    return objects_by_label, next_index


def _split_object_clauses(text: str) -> list[str]:
    return [chunk.strip() for chunk in re.split(r'[\n。！？；;]+', text or '') if chunk.strip()]


def _find_holders_in_clause(text: str, holders: list[str]) -> list[str]:
    found = []
    for holder in holders:
        if holder and holder in text and holder not in found:
            found.append(holder)
    return found


def _extract_object_labels_from_clause(text: str) -> list[str]:
    labels = []
    for match in OBJECT_LABEL_HINT_RE.finditer(text or ''):
        label = _clean_object_label(match.group(1))
        if label and label not in labels:
            labels.append(label)
    return labels


def _infer_object_status_from_clause(text: str) -> str:
    if any(token in text for token in ('亮出', '举起', '摊开', '摸出', '取出', '掏出', '拿出', '抛给', '抛出')):
        return 'revealed'
    if any(token in text for token in ('递给', '塞给', '交给', '交到')):
        return 'transferred'
    if any(token in text for token in ('搜出', '夺过', '收走')):
        return 'seized'
    if any(token in text for token in ('手里', '手中', '掌中', '握着', '拿着', '攥着', '提着', '端着', '拎着')):
        return 'held'
    if any(token in text for token in ('怀里', '袖中', '身上', '腰间', '口袋', '兜里', '抽屉', '床头柜')):
        return 'carried'
    return ''


def _infer_object_visibility_from_clause(text: str) -> str:
    if any(token in text for token in ('怀里', '袖中', '腰间', '口袋', '兜里', '抽屉', '床头柜')):
        return 'private'
    if any(token in text for token in ('亮出', '举起', '摊开', '手里', '手中', '掌中', '端着', '拎着', '桌上', '地上', '柜台上', '床边', '窗边', '案上', '盘里', '桶里')):
        return 'public'
    return ''


def infer_tracked_objects(text: str, prev_state: dict | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    prev_state = prev_state or {}
    prev_objects = prev_state.get('tracked_objects', []) if isinstance(prev_state.get('tracked_objects', []), list) else []
    prev_possession = prev_state.get('possession_state', []) if isinstance(prev_state.get('possession_state', []), list) else []
    prev_visibility = prev_state.get('object_visibility', []) if isinstance(prev_state.get('object_visibility', []), list) else []

    objects_by_label = {}
    max_idx = 0
    for item in prev_objects:
        if not isinstance(item, dict):
            continue
        label = _clean_object_label(item.get('label', ''))
        object_id = str(item.get('object_id', '') or '').strip()
        if not label or not object_id:
            continue
        objects_by_label[label] = dict(item)
        if object_id.startswith('obj_'):
            try:
                max_idx = max(max_idx, int(object_id.split('_', 1)[1]))
            except Exception:
                pass

    possession = {str(item.get('object_id', '')): dict(item) for item in prev_possession if isinstance(item, dict) and item.get('object_id')}
    visibility = {str(item.get('object_id', '')): dict(item) for item in prev_visibility if isinstance(item, dict) and item.get('object_id')}

    holders = _known_holder_names(prev_state)
    if not holders:
        return list(objects_by_label.values())[:8], list(possession.values())[:8], list(visibility.values())[:8]

    next_index = max_idx + 1 if max_idx else 1
    holder_patterns = [
        (r'{holder}(?:怀里|袖中|身上|腰间)(?:还|仍|正)?(?:藏着|揣着|带着|夹着)?(?P<label>[^，。；：]{1,16})', 'carried', 'private'),
        (r'{holder}(?:手里|手中|掌中)(?:还|仍|正)?(?:拿着|握着|攥着|提着)?(?P<label>[^，。；：]{1,16})', 'held', 'public'),
        (r'{holder}(?:亮出|举起|摊开|摸出|取出|掏出|拿出)(?P<label>[^，。；：]{1,16})', 'revealed', 'public'),
        (r'{holder}(?:递给|塞给|交给)(?P<label>[^，。；：]{1,16})', 'transferred', 'public'),
        (r'{holder}(?:搜出|夺过)(?P<label>[^，。；：]{1,16})', 'seized', 'public'),
    ]

    for holder in holders:
        holder_re = re.escape(holder)
        for pattern, status, default_visibility in holder_patterns:
            compiled_pattern = pattern.replace('{holder}', holder_re)
            for match in re.finditer(compiled_pattern, text):
                label = match.groupdict().get('label', '')
                if not _is_story_relevant_object(label, status=status, holder=holder, clause=text):
                    continue
                obj, next_index = _upsert_object(objects_by_label, next_index, label)
                if not obj:
                    continue
                obj['kind'] = _infer_object_kind(obj.get('label', ''))
                _mark_object_with_holder(obj, possession, visibility, holder, status, default_visibility)

    objects_by_label, next_index = _extract_free_objects(text, objects_by_label, next_index)
    for clause in _split_object_clauses(text):
        labels = _extract_object_labels_from_clause(clause)
        if not labels:
            continue
        status = _infer_object_status_from_clause(clause)
        vis = _infer_object_visibility_from_clause(clause)
        clause_holders = _find_holders_in_clause(clause, holders)
        chosen_holder = clause_holders[0] if len(clause_holders) == 1 else ''
        for label in labels:
            if not _has_anchor_for_object(clause, holder=chosen_holder, status=status, visibility=vis):
                continue
            if not _is_story_relevant_object(label, status=status, holder=chosen_holder, clause=clause):
                continue
            obj, next_index = _upsert_object(objects_by_label, next_index, label)
            if not obj:
                continue
            obj['kind'] = _infer_object_kind(obj.get('label', ''))
            if chosen_holder and status:
                _mark_object_with_holder(obj, possession, visibility, chosen_holder, status, vis)
            elif obj['object_id'] not in visibility and vis:
                visibility[obj['object_id']] = {
                    'object_id': obj['object_id'],
                    'visibility': vis,
                    'known_to': [],
                    'note': '',
                }
    for item in objects_by_label.values():
        if not item.get('kind'):
            item['kind'] = _infer_object_kind(item.get('label', ''))

    return list(objects_by_label.values())[:8], list(possession.values())[:8], list(visibility.values())[:8]


def infer_focal_entity(text: str) -> dict | None:
    return None


def infer_focal_entity_generic(text: str, prev_state: dict, context: dict, history: list[dict]) -> dict | None:
    names = extract_generic_character_names(text, prev_state, context, history, limit=3)
    if not names:
        return None
    primary = names[0]
    if primary in {'暗影', '黑影', '影子', '人影'}:
        return None
    return {
        'primary_label': primary,
        'aliases': [primary],
        'role_label': '当前互动核心人物',
        'onstage': True,
        'possible_link': None,
    }


def filter_transient_npcs(text: str, onstage: list[str]) -> list[str]:
    return list(onstage)[:6]


def prioritize_scene_targets(text: str, onstage: list[str]) -> list[str]:
    return list(onstage)[:6]


def _count_hint_from_prefix(token: str) -> int | None:
    mapping = {
        '一': 1,
        '二': 2,
        '两': 2,
        '三': 3,
        '四': 4,
        '五': 5,
        '六': 6,
        '七': 7,
        '八': 8,
        '九': 9,
        '十': 10,
    }
    text = str(token or '').strip()
    if text == '几':
        return 3
    if text == '数':
        return 4
    return mapping.get(text)


def _normalize_entity_label(name: str) -> tuple[str, list[str], bool, int | None]:
    original = sanitize_runtime_name(name)
    if not original:
        return '', [], False, None

    count_hint = None
    collective = False
    body = original
    count_match = ENTITY_COUNT_PREFIX_RE.match(body)
    if count_match:
        parsed = _count_hint_from_prefix(count_match.group('count'))
        if parsed:
            count_hint = parsed
            collective = parsed > 1
            body = sanitize_runtime_name(count_match.group('body')) or body

    primary = body
    if '的' in body:
        parts = [sanitize_runtime_name(part) for part in body.split('的') if sanitize_runtime_name(part)]
        if len(parts) >= 2:
            base = parts[-1]
            modifier = ENTITY_LEADING_VERB_RE.sub('', parts[-2]).strip()
            if any(base.endswith(suffix) for suffix in ENTITY_DESCRIPTOR_SUFFIXES):
                primary = base

    primary = sanitize_runtime_name(primary)
    aliases = []
    for candidate in (original, body):
        text = sanitize_runtime_name(candidate)
        if text and text != primary and text not in aliases:
            aliases.append(text)
    return primary or original, aliases, collective, count_hint


def _entity_labels_compatible(left: str, right: str) -> bool:
    left_text = sanitize_runtime_name(left)
    right_text = sanitize_runtime_name(right)
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    for shadow in {'暗影', '黑影', '影子', '人影'}:
        if left_text == shadow or right_text == shadow:
            return False
    left_primary, left_aliases, _, _ = _normalize_entity_label(left_text)
    right_primary, right_aliases, _, _ = _normalize_entity_label(right_text)
    return bool(left_primary and right_primary and left_primary == right_primary)


def _align_name_to_scene_entities(name: str, scene_entities: list[dict]) -> str:
    target = sanitize_runtime_name(name)
    if not target:
        return ''
    for item in scene_entities or []:
        if not isinstance(item, dict):
            continue
        primary = sanitize_runtime_name(item.get('primary_label', ''))
        aliases = [sanitize_runtime_name(alias) for alias in (item.get('aliases', []) or []) if sanitize_runtime_name(alias)]
        if any(label for label in [primary] + aliases if label == target or _entity_labels_compatible(label, target)):
            return primary or target
    return target


def _align_names_to_scene_entities(names: list[str], scene_entities: list[dict], *, limit: int = 6) -> list[str]:
    aligned = []
    for name in names or []:
        primary = _align_name_to_scene_entities(name, scene_entities)
        if primary and primary not in aligned:
            aligned.append(primary)
        if len(aligned) >= limit:
            break
    return aligned


def _compress_signal_phrase(text: str, *, limit: int = 24) -> str:
    value = ' '.join(str(text or '').split()).strip().strip('“”"\'')
    if not value:
        return ''
    value = re.sub(r'^(?:忽然|突然|只见|只听|只道|便见|便听|这时|此时|随即|旋即|紧接着)', '', value).strip('，。；：、 ')
    value = re.sub(r'^(?:他|她|那人|对方|其中一人|另一人|其中一个|另一个)(?:又|便|就|只|仍)?', '', value).strip('，。；：、 ')
    if '：“' in value:
        value = value.split('：“', 1)[0].strip()
    if '，' in value:
        value = value.split('，', 1)[0].strip()
    if '。' in value:
        value = value.split('。', 1)[0].strip()
    if len(value) > limit:
        value = value[:limit].rstrip('，。；：、 ')
    return value


def _clean_signal_list(items: list[str], *, limit: int = 3) -> list[str]:
    cleaned = []
    for item in items or []:
        text = _state_like_signal(item)
        if not text or len(text) < 4:
            continue
        if text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _entity_slot_hint(primary: str, aliases: list[str]) -> str:
    haystack = ' '.join([sanitize_runtime_name(primary)] + [sanitize_runtime_name(alias) for alias in aliases or []])
    for marker in ENTITY_SLOT_MARKERS:
        if marker and marker in haystack:
            return marker
    return ''


def _dedupe_scene_entities_by_slot(entities: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    ordered: list[dict] = []
    for item in entities or []:
        if not isinstance(item, dict):
            continue
        primary = sanitize_runtime_name(item.get('primary_label', ''))
        aliases = [sanitize_runtime_name(alias) for alias in (item.get('aliases', []) or []) if sanitize_runtime_name(alias)]
        slot_hint = _entity_slot_hint(primary, aliases)
        key = (primary, slot_hint)
        current = grouped.get(key)
        if current is None:
            current = dict(item)
            current['aliases'] = aliases
            grouped[key] = current
            ordered.append(current)
            continue
        merged_aliases = list(current.get('aliases', []) or [])
        for alias in aliases:
            if alias and alias not in merged_aliases:
                merged_aliases.append(alias)
        current['aliases'] = merged_aliases
        current['onstage'] = bool(current.get('onstage')) or bool(item.get('onstage'))
        current['collective'] = bool(current.get('collective')) or bool(item.get('collective'))
        if not current.get('count_hint') and item.get('count_hint'):
            current['count_hint'] = item.get('count_hint')
    return ordered


def _state_like_signal(text: str) -> str:
    value = _compress_signal_phrase(text, limit=28)
    if not value:
        return ''
    if _looks_like_prose_signal_fragment(value):
        return ''
    replacements = (
        ('画像画得潦草', '画像只能辨认轮廓'),
        ('顺势侧过了身', '已借位遮挡身形'),
        ('没有立刻接话', '暂未正面回应'),
        ('低声道', '压低声音表态'),
        ('抬眼看了她一眼', '正观察主角反应'),
    )
    for source, target in replacements:
        if source in value:
            value = target if value == source else value.replace(source, target)
    return value


def _looks_like_prose_signal_fragment(text: str) -> bool:
    value = ' '.join(str(text or '').split()).strip()
    if not value:
        return True
    if any(mark in value for mark in ('“', '”', '「', '」', '：', ':')):
        return True
    if value.startswith(('他', '她', '它', '那人', '对方', '其中一人', '另一个', '另一人')) and len(value) <= 24:
        return True
    if value.startswith(('声音', '目光', '手上', '脚下', '嘴上', '眼角', '眉头')):
        return True
    if value.endswith(('了声', '一眼', '一下', '半分', '些', '着', '了')) and len(value) <= 24:
        return True
    if any(token in value for token in ('压低了声', '笑着打断', '抬眼', '低声道', '嘴上这么说', '手里捏着', '把壶放下')):
        return True
    meaningful_tokens = (
        '追', '查', '搜', '封', '锁', '伤', '毒', '死', '杀', '失踪', '暴露', '怀疑', '身份', '来历',
        '证据', '线索', '传闻', '情报', '口供', '文件', '名单', '账册', '钥匙', '信', '地图', '标记',
    )
    return not any(token in value for token in meaningful_tokens)


def build_scene_entities(onstage: list[str], text: str = '', focal_entity: dict | None = None) -> list[dict]:
    def _descriptor_signature(name: str) -> str:
        text_value = sanitize_runtime_name(name)
        for suffix in ('身影', '背影', '影子', '影', '之人', '那人', '此人', '来人', '男人', '女人', '女子', '青年', '少年', '老者', '壮汉', '皂衣人', '黑衣人', '灰衣人', '白衣人', '毡笠人', '人'):
            if text_value.endswith(suffix) and len(text_value) > len(suffix):
                return text_value[:-len(suffix)].strip()
        return text_value

    def _labels_compatible(left: str, right: str) -> bool:
        left_text = sanitize_runtime_name(left)
        right_text = sanitize_runtime_name(right)
        if not left_text or not right_text:
            return False
        if left_text == right_text:
            return True
        if left_text in {'暗影', '黑影', '影子', '人影'} or right_text in {'暗影', '黑影', '影子', '人影'}:
            return False
        return bool(_descriptor_signature(left_text) and _descriptor_signature(left_text) == _descriptor_signature(right_text))

    entities = []
    for idx, name in enumerate(onstage, start=1):
        primary, aliases, collective, count_hint = _normalize_entity_label(name)
        entity = {
            'entity_id': f'scene_npc_{idx:02d}',
            'primary_label': primary,
            'aliases': aliases,
            'role_label': infer_role_label(primary),
            'onstage': True,
            'possible_link': None,
            'collective': collective,
            'count_hint': count_hint,
        }
        entities.append(entity)
    if focal_entity and focal_entity.get('primary_label'):
        names = {item['primary_label'] for item in entities}
        if not any(_labels_compatible(focal_entity['primary_label'], existing) for existing in names):
            focal = dict(focal_entity)
            focal.setdefault('entity_id', f'scene_npc_{len(entities)+1:02d}')
            focal.setdefault('collective', False)
            focal.setdefault('count_hint', None)
            entities.insert(0, focal)
    return entities


def build_scene_entities_generic(onstage: list[str], prev_state: dict, context: dict, history: list[dict], text: str = '', focal_entity: dict | None = None) -> list[dict]:
    def _descriptor_signature(name: str) -> str:
        text_value = sanitize_runtime_name(name)
        for suffix in ('身影', '背影', '影子', '影', '之人', '那人', '此人', '来人', '男人', '女人', '女子', '青年', '少年', '老者', '壮汉', '皂衣人', '黑衣人', '灰衣人', '白衣人', '毡笠人', '人'):
            if text_value.endswith(suffix) and len(text_value) > len(suffix):
                return text_value[:-len(suffix)].strip()
        return text_value

    def _labels_compatible(left: str, right: str) -> bool:
        left_text = sanitize_runtime_name(left)
        right_text = sanitize_runtime_name(right)
        if not left_text or not right_text:
            return False
        if left_text == right_text:
            return True
        if left_text in {'暗影', '黑影', '影子', '人影'} or right_text in {'暗影', '黑影', '影子', '人影'}:
            return False
        return bool(_descriptor_signature(left_text) and _descriptor_signature(left_text) == _descriptor_signature(right_text))

    def _find_prev_entity_id(name: str, prev_entities: list[dict], used_ids: set[str]) -> str:
        target = sanitize_runtime_name(name)
        if not target:
            return ''
        for item in prev_entities or []:
            if not isinstance(item, dict):
                continue
            entity_id = str(item.get('entity_id', '') or '').strip()
            if not entity_id or entity_id in used_ids:
                continue
            primary = sanitize_runtime_name(item.get('primary_label', ''))
            aliases = [sanitize_runtime_name(alias) for alias in (item.get('aliases', []) or []) if sanitize_runtime_name(alias)]
            if any(_labels_compatible(target, candidate) for candidate in [primary] + aliases if candidate):
                return entity_id
        return ''

    entities = []
    prev_entities = [item for item in (prev_state.get('scene_entities', []) or []) if isinstance(item, dict)]
    used_ids: set[str] = set()
    max_prev_idx = 0
    for item in prev_entities:
        entity_id = str(item.get('entity_id', '') or '').strip()
        if entity_id.startswith('scene_npc_'):
            try:
                max_prev_idx = max(max_prev_idx, int(entity_id.split('_')[-1]))
            except Exception:
                pass
    next_id = max_prev_idx + 1 if max_prev_idx else 1
    for idx, name in enumerate(onstage, start=1):
        primary, aliases, collective, count_hint = _normalize_entity_label(name)
        prev_role_label = ''
        for item in (prev_state.get('scene_entities', []) or []):
            if not isinstance(item, dict):
                continue
            existing_primary = sanitize_runtime_name(item.get('primary_label', ''))
            existing_aliases = [sanitize_runtime_name(alias) for alias in (item.get('aliases', []) or []) if sanitize_runtime_name(alias)]
            if any(label for label in [existing_primary] + existing_aliases if _labels_compatible(label, primary) or label == primary):
                prev_role_label = str(item.get('role_label', '') or '').strip()
                break
        entity_id = _find_prev_entity_id(primary, prev_entities, used_ids)
        if not entity_id:
            entity_id = f'scene_npc_{next_id:02d}'
            next_id += 1
        used_ids.add(entity_id)
        entity = {
            'entity_id': entity_id,
            'primary_label': primary,
            'aliases': aliases,
            'role_label': prev_role_label or '待确认',
            'onstage': True,
            'possible_link': None,
            'collective': collective,
            'count_hint': count_hint,
        }
        entities.append(entity)

    if focal_entity and focal_entity.get('primary_label'):
        existing = {item['primary_label'] for item in entities}
        if not any(_labels_compatible(focal_entity['primary_label'], existing_name) for existing_name in existing):
            focal = dict(focal_entity)
            focal_entity_id = _find_prev_entity_id(focal_entity['primary_label'], prev_entities, used_ids)
            if not focal_entity_id:
                focal_entity_id = f'scene_npc_{next_id:02d}'
                next_id += 1
            focal.setdefault('entity_id', focal_entity_id)
            focal.setdefault('collective', False)
            focal.setdefault('count_hint', None)
            used_ids.add(focal['entity_id'])
            entities.insert(0, focal)

    return _dedupe_scene_entities_by_slot(entities)


def infer_immediate_goal(text: str) -> str:
    return ''


def infer_immediate_risks(text: str) -> list[str]:
    return []


def update_state(session_id: str) -> dict:
    history = load_history(session_id)
    state = load_state(session_id) or seed_default_state(session_id)
    context = load_context(session_id)
    if state.get('opening_mode') in {'menu', 'direct'} and not state.get('opening_resolved'):
        save_state(session_id, state)
        return state
    assistant_focus_item = _recent_role_item(history, 'assistant')
    user_focus_item = _recent_role_item(history, 'user')
    assistant_focus = str(assistant_focus_item.get('content', '') or '')
    user_focus = str(user_focus_item.get('content', '') or '')
    focus_text = assistant_focus + '\n' + user_focus
    broad_text = recent_text(history, 10)

    base_text = assistant_focus or focus_text
    generic_time = infer_time_generic(assistant_focus, state)
    generic_location = ''
    focal_entity = infer_focal_entity_generic(base_text, state, context, history)
    inferred_onstage = [sanitize_runtime_name(name) for name in infer_onstage_npcs_generic(base_text, state, context, history) if sanitize_runtime_name(name)]
    recent_assistant_window = recent_role_text(history, 'assistant', limit=4)
    if len(inferred_onstage) < 2 and recent_assistant_window and recent_assistant_window != base_text:
        recent_onstage = [
            sanitize_runtime_name(name)
            for name in infer_onstage_npcs_generic(recent_assistant_window, state, context, history)
            if sanitize_runtime_name(name)
        ]
        for name in recent_onstage:
            if name not in inferred_onstage:
                inferred_onstage.append(name)
            if len(inferred_onstage) >= 4:
                break
    inferred_onstage = _prune_generic_appellations(inferred_onstage, state, context, history)
    if focal_entity and focal_entity['primary_label'] not in inferred_onstage:
        inferred_onstage = [focal_entity['primary_label']] + inferred_onstage
        inferred_onstage = inferred_onstage[:4]
    inferred_relevant = infer_relevant_npcs_generic(broad_text, inferred_onstage, state, context, history)
    inferred_relevant = _prune_generic_appellations(inferred_relevant, state, context, history)
    inferred_relevant = infer_implicit_relevant(state, assistant_focus or focus_text, inferred_onstage, inferred_relevant)
    prev_effective_location = str(state.get('location', '') or '').strip()
    location_changed = bool(
        has_signal(prev_effective_location)
        and has_signal(generic_location or '')
        and (generic_location or '').strip() != prev_effective_location
    )
    inferred_onstage, inferred_relevant = preserve_recent_names(
        state,
        assistant_focus or focus_text,
        inferred_onstage,
        inferred_relevant,
        location_changed=location_changed,
    )

    opening_locked = bool(state.get('opening_resolved')) and not state.get('opening_started')
    if state.get('opening_resolved') and state.get('opening_started'):
        current_location = str(state.get('location', '') or '').strip()
        current_main_event = str(state.get('main_event', '') or '').strip()
        if current_location in {'', '待确认', '待根据开局建立'} or current_main_event.startswith('开局：'):
            opening_locked = False

    prev_location = str(state.get('location', '') or '').strip()
    inferred_time = generic_time
    inferred_location = generic_location
    recent_pairs = []
    current_user = None
    for item in history:
        if item.get('role') == 'user':
            current_user = item
        elif item.get('role') == 'assistant' and current_user is not None:
            recent_pairs.append((str(current_user.get('content', '') or ''), str(item.get('content', '') or '')))
            current_user = None
    recent_pairs = recent_pairs[-3:]

    ledger = build_event_ledger_with_llm(
        user_text=user_focus,
        narrator_reply=assistant_focus,
        prev_state=state,
        onstage_names=inferred_onstage,
        location=inferred_location or prev_location,
        recent_pairs=recent_pairs,
        current_state=state,
    )
    ledger_main = next((item.get('text', '') for item in ledger.get('main_event_candidates', []) if isinstance(item, dict)), '')
    inferred_main_event = ledger_main or infer_main_event_generic(user_focus, assistant_focus, inferred_location, prev_location)
    current_main_event = str(state.get('main_event', '') or '').strip()
    skeleton_main_event = str(state.get('main_event', '') or '').strip()
    should_refresh_main = _should_refresh_main_event(session_id, state, inferred_location, assistant_focus, inferred_onstage)
    if bool(ledger.get('scene_shift', {}).get('changed')):
        should_refresh_main = True
    if not should_refresh_main and core_value_quality(skeleton_main_event, inferred_onstage) >= core_value_quality(inferred_main_event, inferred_onstage):
        inferred_main_event = skeleton_main_event or inferred_main_event
    if not should_refresh_main:
        if not (
            _is_generic_main_event(current_main_event)
            and inferred_main_event
            and not _is_generic_main_event(inferred_main_event)
        ):
            inferred_main_event = current_main_event or inferred_main_event
    elif _is_generic_main_event(inferred_main_event) and current_main_event and not _is_generic_main_event(current_main_event):
        inferred_main_event = current_main_event
    inferred_goal = str(state.get('immediate_goal', '') or '').strip() or '待确认'
    inferred_risks = infer_immediate_risks_generic(user_focus, assistant_focus, inferred_location, prev_location, onstage_count=len(inferred_onstage))
    inferred_clues = infer_carryover_clues_generic(user_focus, assistant_focus, inferred_location, prev_location)
    carryover_signals = _build_carryover_signals(inferred_risks, inferred_clues)
    tracked_objects, possession_state, object_visibility = infer_tracked_objects(broad_text, state)
    scene_entities = build_scene_entities_generic(inferred_onstage, state, context, history, text=base_text, focal_entity=focal_entity)
    if not scene_entities:
        scene_entities = build_scene_entities(inferred_onstage, base_text, focal_entity)
    inferred_onstage = _align_names_to_scene_entities(inferred_onstage, scene_entities, limit=6)
    inferred_relevant = [
        name for name in _align_names_to_scene_entities(inferred_relevant, scene_entities, limit=6)
        if name not in inferred_onstage
    ]
    inferred_main_event = _refine_main_event(
        str(ledger.get('summary_text', '') or '').strip(),
        inferred_main_event,
        inferred_location or prev_location,
    )
    if _should_replace_stale_main_event(current_main_event, str(ledger.get('summary_text', '') or '').strip(), current_onstage=inferred_onstage):
        current_main_event = ''

    next_state = {
        'time': state.get('time') if opening_locked and state.get('time') not in {'', None, '待确认'} else prefer_existing(state.get('time'), inferred_time),
        'location': state.get('location') if state.get('location') not in {'', None, '待确认'} else prefer_existing(state.get('location'), inferred_location),
        'main_event': state.get('main_event') if opening_locked and state.get('main_event') else prefer_existing(current_main_event, inferred_main_event),
        'onstage_npcs': inferred_onstage,
        'scene_entities': scene_entities,
        'relevant_npcs': [sanitize_runtime_name(name) for name in inferred_relevant if sanitize_runtime_name(name)],
        'immediate_goal': state.get('immediate_goal') if opening_locked and state.get('immediate_goal') else prefer_existing(state.get('immediate_goal'), inferred_goal),
        'immediate_risks': inferred_risks,
        'carryover_clues': inferred_clues,
        'carryover_signals': carryover_signals,
        'tracked_objects': tracked_objects,
        'possession_state': possession_state,
        'object_visibility': object_visibility,
        'event_ledger': ledger,
    }
    next_state = _guard_entity_collapse(state, next_state)
    next_state = retain_strong_lists(state, next_state)
    next_state = retain_relevant_window(state, next_state, history, window_pairs=3)
    prev_for_normalize = dict(state)
    prev_for_normalize['_recent_history_items'] = history[-8:]
    state = normalize_state_dict(next_state, prev_state=prev_for_normalize, session_id=session_id)

    save_state(session_id, state)
    return state
