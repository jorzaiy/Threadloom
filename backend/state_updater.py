#!/usr/bin/env python3
import re

try:
    import jieba  # type: ignore
except Exception:
    jieba = None

from runtime_store import load_context, load_history, load_state, save_state, seed_default_state
from name_sanitizer import sanitize_runtime_name
from state_bridge import infer_role_label, normalize_state_dict


SCENE_HEADER_RE = re.compile(r'^\s*『(?P<header>[^』]+)』')
GENERIC_TIME_RE = re.compile(r'(?P<date>\d{4}年[-/]\d{1,2}月[-/]\d{1,2}日(?:[-/][^–—\n]{1,8})?)')
GENERIC_CLOCK_RE = re.compile(r'(?P<clock>\d{1,2}:\d{2})')
GENERIC_NAME_RE = re.compile(r'[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?')
GENERIC_NON_PERSON_SUFFIXES = ('场', '区', '室', '楼', '廊', '道', '台', '墙', '门', '路', '馆', '堂', '院', '课', '处', '站')
GENERIC_NON_NAME_PREFIXES = ('他', '她', '你', '我', '这', '那', '其')
GENERIC_GRAMMAR_PARTICLES = ('的', '了', '着', '从', '在', '把', '被', '向', '和', '与', '并', '将')
GENERIC_INTRO_NAME_RE = re.compile(r'(?:我叫|他叫|她叫|名叫|叫做|自称|名字是)(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)')
GENERIC_STANDALONE_NAME_RE = re.compile(r'(?:^|[\n“"‘「『《（(—-])(?P<name>[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?)(?=$|[\n”"’」』》）).,，。！？!?])')
GENERIC_APPELLATION_NAMES = {'少年', '男人', '女人', '男生', '女生', '学员', '教官', '老师', '同学', '对方', '那人', '青年'}
GENERIC_NON_NAME_TOKENS = {
    '今天', '明天', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日',
    '上午', '下午', '中午', '清晨', '黄昏', '入夜', '深夜', '晴', '阴', '小雨', '大雨', '雨天',
    '训练场', '休息区', '集合点', '障碍区', '图书馆', '办公室', '宿舍楼', '走廊', '连廊', '食堂',
    '任务', '名单', '资料', '档案', '记录板', '学院', '特工学院', '大事记', '压缩饼干',
}


def _short_plain(text: str, limit: int = 24) -> str:
    one = ' '.join(str(text or '').split()).strip()
    if len(one) <= limit:
        return one
    return one[: limit - 3] + '...'


def _strip_scene_header(text: str) -> str:
    stripped = str(text or '').lstrip()
    match = SCENE_HEADER_RE.match(stripped)
    if not match:
        return stripped
    return stripped[match.end():].lstrip('\n')


def _parse_scene_header(text: str) -> dict:
    match = SCENE_HEADER_RE.match(str(text or '').lstrip())
    if not match:
        return {}
    raw = match.group('header').strip()
    clock_match = GENERIC_CLOCK_RE.search(raw)
    date = ''
    clock = ''
    location = ''
    weather = ''
    if clock_match:
        date = raw[:clock_match.start()].rstrip('-–— ')
        clock = clock_match.group('clock')
        tail = raw[clock_match.end():].lstrip('-–— ')
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
        if text in GENERIC_APPELLATION_NAMES and text not in stable_pool:
            continue
        filtered.append(text)
    return filtered


def _looks_like_character_name(candidate: str, excluded: set[str]) -> bool:
    text = sanitize_runtime_name(candidate)
    if not text or text in excluded:
        return False
    if text in GENERIC_NON_NAME_TOKENS:
        return False
    if text.startswith(GENERIC_NON_NAME_PREFIXES):
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


_jieba_tokenizer = None


def _get_jieba_tokenizer():
    global _jieba_tokenizer
    if _jieba_tokenizer is None and jieba is not None:
        _jieba_tokenizer = jieba.Tokenizer()
    return _jieba_tokenizer


def _jieba_token_set(body: str, seeded: list[str]) -> set[str]:
    tokenizer = _get_jieba_tokenizer()
    if tokenizer is None:
        return set()
    for name in seeded:
        if name:
            try:
                tokenizer.add_word(name, freq=1000000)
            except Exception:
                pass
    try:
        return {token.strip() for token in tokenizer.lcut(body) if token.strip()}
    except Exception:
        return set()


def _jieba_accepts_name(name: str, tokens: set[str]) -> bool:
    if not name:
        return False
    if jieba is None:
        return True
    return name in tokens


def _is_explicit_intro_name(body: str, name: str) -> bool:
    if not name:
        return False
    return re.search(rf'(?:我叫|他叫|她叫|名叫|叫做|自称|名字是){re.escape(name)}', body) is not None


def _extract_structured_name_candidates(body: str, seeded: list[str], excluded: set[str]) -> list[str]:
    candidates: list[str] = []

    for name in seeded:
        if name and _contains_seed_name_exactly(body, name) and _looks_like_character_name(name, excluded) and name not in candidates:
            candidates.append(name)

    for pattern in (GENERIC_INTRO_NAME_RE,):
        for match in pattern.finditer(body):
            name = sanitize_runtime_name(match.group('name'))
            if not _looks_like_character_name(name, excluded):
                continue
            if name not in candidates:
                candidates.append(name)

    return candidates


def extract_generic_character_names(text: str, prev_state: dict, context: dict, history: list[dict], limit: int = 6) -> list[str]:
    body = _strip_scene_header(text)
    seeded = _seed_character_names(prev_state, context, history)
    excluded = _protagonist_name_hints(context, history)
    token_set = _jieba_token_set(body, seeded)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()

    for name in _extract_structured_name_candidates(body, seeded, excluded):
        if name in seen:
            continue
        if name in seeded and _contains_seed_name_exactly(body, name):
            pass
        elif _is_explicit_intro_name(body, name):
            pass
        elif not _jieba_accepts_name(name, token_set):
            continue
        seen.add(name)
        scored.append((_score_name_candidate(name, body, seeded), name))

    scored.sort(key=lambda item: (-item[0], body.find(item[1]) if item[1] in body else 10**9))
    return [name for _score, name in scored[:limit]]


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
    if clock_match and prev_state.get('time'):
        return f"{prev_state.get('time')} {clock_match.group('clock')}".strip()
    return ''


def infer_location_generic(text: str) -> str:
    header = _parse_scene_header(text)
    if header.get('location'):
        return header['location']
    return ''


def infer_main_event_generic(user_text: str, assistant_text: str, location: str, prev_location: str) -> str:
    prompt = _short_plain(user_text, 24)
    prev_effective = prev_location if has_signal(prev_location) and prev_location != '待确认' else ''
    if location and prev_effective and location != prev_effective:
        return f'场景已转到{location}，互动重点随之转入新地点。'
    if location and prompt:
        return f'{location}里的局面正围绕“{prompt}”往下发展。'
    if location:
        return f'{location}里的局面仍在往下推进。'
    if prompt:
        return f'当前局面正围绕“{prompt}”继续展开。'
    return '当前局面仍在继续推进。'


def infer_scene_core_generic(user_text: str, assistant_text: str, location: str, prev_location: str, onstage_count: int = 0) -> str:
    parts = []
    prev_effective = prev_location if has_signal(prev_location) and prev_location != '待确认' else ''
    if location:
        if prev_effective and prev_effective != location:
            parts.append(f'场景已转到{location}，新的关系与信息交换开始累积')
        else:
            parts.append(f'场景重心仍停留在{location}')
    if onstage_count >= 2:
        parts.append('人物之间的互动与试探正在推动局面变化')
    elif onstage_count == 1:
        parts.append('叙事重心暂时压在单个关键人物身上')
    if not parts:
        parts.append('局势仍在缓慢变化')
    return '；'.join(parts)


def infer_immediate_goal_generic(user_text: str, assistant_text: str, location: str, prev_location: str) -> str:
    prompt = _short_plain(user_text, 24)
    if prompt:
        return f'先处理“{prompt}”带出的眼前问题，再决定下一步。'
    prev_effective = prev_location if has_signal(prev_location) and prev_location != '待确认' else ''
    if location and prev_effective and location != prev_effective:
        return '先适应新的场景和关系，再决定下一步行动。'
    return '先看清眼前局面，再决定下一步。'


def infer_immediate_risks_generic(user_text: str, assistant_text: str, location: str, prev_location: str, onstage_count: int = 0) -> list[str]:
    risks = []
    prev_effective = prev_location if has_signal(prev_location) and prev_location != '待确认' else ''
    if location and prev_effective and location != prev_effective:
        risks.append('转场后的环境与规则还没有完全摸清。')
    if onstage_count >= 2:
        risks.append('在场人物的真实态度和下一步动作仍有不确定性。')
    if '“' in assistant_text or '"' in assistant_text:
        risks.append('本轮对话里的表态仍可能改变下一步的走向。')
    return risks[:3]


def infer_carryover_clues_generic(user_text: str, assistant_text: str, location: str, prev_location: str) -> list[str]:
    clues = []
    if user_text:
        clues.append('本轮输入带出的目标、问题或决定还会继续影响后续推进。')
    if '“' in assistant_text or '"' in assistant_text:
        clues.append('本轮对话里的表态和细节，后面还有回流的可能。')
    prev_effective = prev_location if has_signal(prev_location) and prev_location != '待确认' else ''
    if location and prev_effective and location != prev_effective:
        clues.append(f'{location}里出现的新关系和环境线索，还需要继续确认。')
    return clues[:3]


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


def infer_scene_core(text: str) -> str:
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
    for match in OBJECT_LABEL_HINT_RE.finditer(text or ''):
        label = match.group(1)
        if not _is_story_relevant_object(label, clause=text):
            continue
        _, next_index = _upsert_object(objects_by_label, next_index, label)
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
    if any(token in text for token in ('亮出', '举起', '摊开', '手里', '手中', '掌中', '端着', '拎着', '桌上', '地上')):
        return 'public'
    return 'public'


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


def build_scene_entities(onstage: list[str], text: str = '', focal_entity: dict | None = None) -> list[dict]:
    entities = []
    for idx, name in enumerate(onstage, start=1):
        entity = {
            'entity_id': f'scene_npc_{idx:02d}',
            'primary_label': name,
            'aliases': [name],
            'role_label': infer_role_label(name),
            'onstage': True,
            'possible_link': None,
            'collective': False,
            'count_hint': None,
        }
        entities.append(entity)
    if focal_entity and focal_entity.get('primary_label'):
        names = {item['primary_label'] for item in entities}
        if focal_entity['primary_label'] not in names:
            focal = dict(focal_entity)
            focal.setdefault('entity_id', f'scene_npc_{len(entities)+1:02d}')
            focal.setdefault('collective', False)
            focal.setdefault('count_hint', None)
            entities.insert(0, focal)
    return entities


def build_scene_entities_generic(onstage: list[str], prev_state: dict, context: dict, history: list[dict], text: str = '', focal_entity: dict | None = None) -> list[dict]:
    entities = []
    for idx, name in enumerate(onstage, start=1):
        prev_role_label = ''
        for item in (prev_state.get('scene_entities', []) or []):
            if not isinstance(item, dict):
                continue
            if sanitize_runtime_name(item.get('primary_label', '')) == name:
                prev_role_label = str(item.get('role_label', '') or '').strip()
                break
        entity = {
            'entity_id': f'scene_npc_{idx:02d}',
            'primary_label': name,
            'aliases': [name],
            'role_label': prev_role_label or '待确认',
            'onstage': True,
            'possible_link': None,
            'collective': False,
            'count_hint': None,
        }
        entities.append(entity)

    if focal_entity and focal_entity.get('primary_label'):
        existing = {item['primary_label'] for item in entities}
        if focal_entity['primary_label'] not in existing:
            focal = dict(focal_entity)
            focal.setdefault('entity_id', f'scene_npc_{len(entities)+1:02d}')
            focal.setdefault('collective', False)
            focal.setdefault('count_hint', None)
            entities.insert(0, focal)

    return entities


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
    generic_location = infer_location_generic(assistant_focus)
    focal_entity = infer_focal_entity_generic(base_text, state, context, history)
    inferred_onstage = [sanitize_runtime_name(name) for name in infer_onstage_npcs_generic(base_text, state, context, history) if sanitize_runtime_name(name)]
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
    inferred_main_event = infer_main_event_generic(user_focus, assistant_focus, inferred_location, prev_location)
    inferred_scene_core = infer_scene_core_generic(user_focus, assistant_focus, inferred_location, prev_location, onstage_count=len(inferred_onstage))
    inferred_goal = infer_immediate_goal_generic(user_focus, assistant_focus, inferred_location, prev_location)
    inferred_risks = infer_immediate_risks_generic(user_focus, assistant_focus, inferred_location, prev_location, onstage_count=len(inferred_onstage))
    inferred_clues = infer_carryover_clues_generic(user_focus, assistant_focus, inferred_location, prev_location)
    tracked_objects, possession_state, object_visibility = infer_tracked_objects(broad_text, state)
    scene_entities = build_scene_entities_generic(inferred_onstage, state, context, history, text=base_text, focal_entity=focal_entity)
    if not scene_entities:
        scene_entities = build_scene_entities(inferred_onstage, base_text, focal_entity)

    next_state = {
        'time': state.get('time') if opening_locked and state.get('time') not in {'', None, '待确认'} else prefer_existing(state.get('time'), inferred_time),
        'location': state.get('location') if opening_locked and state.get('location') not in {'', None, '待确认'} else prefer_existing(state.get('location'), inferred_location),
        'main_event': state.get('main_event') if opening_locked and state.get('main_event') else prefer_existing(state.get('main_event'), inferred_main_event),
        'scene_core': state.get('scene_core') if opening_locked and state.get('scene_core') else prefer_existing(state.get('scene_core'), inferred_scene_core),
        'onstage_npcs': inferred_onstage,
        'scene_entities': scene_entities,
        'relevant_npcs': [sanitize_runtime_name(name) for name in inferred_relevant if sanitize_runtime_name(name)],
        'immediate_goal': state.get('immediate_goal') if opening_locked and state.get('immediate_goal') else prefer_existing(state.get('immediate_goal'), inferred_goal),
        'immediate_risks': inferred_risks,
        'carryover_clues': inferred_clues,
        'tracked_objects': tracked_objects,
        'possession_state': possession_state,
        'object_visibility': object_visibility,
    }
    next_state = retain_strong_lists(state, next_state)
    next_state = retain_relevant_window(state, next_state, history, window_pairs=3)
    state = normalize_state_dict(next_state, prev_state=state, session_id=session_id)

    save_state(session_id, state)
    return state
