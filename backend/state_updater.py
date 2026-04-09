#!/usr/bin/env python3
from runtime_store import load_history, load_state, save_state, seed_default_state
from name_sanitizer import sanitize_runtime_name
from state_bridge import normalize_state_dict


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
    for marker in ['清晨', '上午', '近午', '午后', '黄昏', '入夜', '深夜']:
        if marker in text:
            return f'承和十二年，三月初七，{marker}'
    if '夜' in text:
        return '承和十二年，三月初七，入夜'
    return '待确认'


def infer_location(text: str) -> str:
    if any(k in text for k in ['后院', '后檐', '偏房', '柴房', '木榻', '水缸', '窗边', '窗下', '临水', '小舟', '船缆']):
        return '临水后院与偏房一带'
    if any(k in text for k in ['灶间', '后门', '后厨', '门帘', '灶房', '灶台', '前堂', '酒肆', '掌柜', '伙计']):
        return '酒肆灶间与后门一带'
    if '客栈' in text or '房' in text or '住下' in text:
        return '渡口客栈一带'
    if '码头' in text or '埠头' in text or '渡口' in text or '河' in text or '船' in text:
        return '河岸与渡口一带'
    if '客栈' in text or '房' in text or '住下' in text:
        return '渡口客栈一带'
    if '船' in text or '渡口' in text or '河' in text:
        return '河岸与渡口一带'
    if '药铺' in text:
        return '药铺前后堂一带'
    if '密林' in text or '树下' in text:
        return '密林与树下藏身处一带'
    return '待确认'


def infer_main_event(text: str) -> str:
    if any(k in text for k in ['柴房', '偏房', '木榻', '水缸', '窗边', '后墙', '翻出去', '躲在这', '搜门', '查门', '断船', '断路']):
        return '在临时藏身处稳住伤势并寻找脱困路径。'
    if any(k in text for k in ['堵门', '让开', '自己出来', '例行查问', '腰牌', '里面还有谁', '谁先说', '看住门']):
        return '门口盘问、堵门对峙并试图逼出伤者身份。'
    if any(k in text for k in ['灶间', '后门', '掌柜', '伙计']) and any(k in text for k in ['伤', '血', '官爷', '皂衣人', '门口']):
        return '灶间藏人暴露后，皂衣人逼问并收紧局势。'
    if any(k in text for k in ['住下', '睡', '歇', '过夜']):
        return '安顿、休整并决定下一步去向。'
    if any(k in text for k in ['住店', '客栈', '房钱', '通铺', '单间']):
        return '寻找落脚处并安排过夜。'
    if any(k in text for k in ['问船', '摆渡', '下船', '渡口']):
        return '完成转场并寻找下一段路线。'
    if any(k in text for k in ['追', '逃', '围杀', '搜捕']):
        return '处理眼前追索、威胁或正面冲突。'
    return '观察局势并等待新的明确变化。'


def infer_scene_core(text: str) -> str:
    bits = []
    if any(k in text for k in ['柴房', '偏房', '木榻', '水缸', '窗边', '后墙', '搜门', '查门', '断船', '断路']):
        bits.append('临时藏身处并不安全，外部搜查与出口封锁正在逼近')
    if any(k in text for k in ['堵门', '门框', '门口', '让开', '自己出来', '例行查问', '腰牌', '里面还有谁']):
        bits.append('门口对峙与身份盘问正在把局面逼实')
    if any(k in text for k in ['灶间', '后门', '掌柜', '伙计']) and any(k in text for k in ['伤', '血', '藏', '里面', '官爷', '皂衣人']):
        bits.append('藏人局面已经暴露，遮掩空间迅速缩小')
    if any(k in text for k in ['睡', '歇', '安顿', '住下']):
        bits.append('场面暂时转入安顿与恢复')
    if any(k in text for k in ['住店', '客栈', '房钱', '通铺', '单间']):
        bits.append('寻找落脚处与夜间安顿成为当前重点')
    if any(k in text for k in ['问船', '渡口', '下船', '上船', '转场']):
        bits.append('转场工具或逃离路径仍在影响局势选择')
    if any(k in text for k in ['伤', '血', '痛']):
        bits.append('伤势与风险压着场面')
    if any(k in text for k in ['说', '问', '试探']):
        bits.append('人物之间的话术试探正在重塑局面')
    return '；'.join(bits) if bits else '局势仍在流动。'


def infer_relevant_npcs(text: str, onstage: list[str]) -> list[str]:
    relevant = []
    for name in ['师兄', '褐袍人', '掌柜', '伙计', '老汉', '船夫', '皂衣人', '高个皂衣人', '少年', '姓苏的']:
        if name in onstage:
            continue
        if name in text and name not in relevant:
            relevant.append(name)
    return relevant[:4]


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


def preserve_recent_names(prev_state: dict, assistant_text: str, onstage: list[str], relevant: list[str]) -> tuple[list[str], list[str]]:
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
        for name in prev_onstage:
            if name not in onstage and len(onstage) < 5:
                onstage.append(name)
        for name in prev_relevant:
            if name not in onstage and name not in relevant and len(relevant) < 5:
                relevant.append(name)
        for name in important_names:
            if name not in onstage and name not in relevant:
                if len(onstage) < 5:
                    onstage.append(name)
                elif len(relevant) < 5:
                    relevant.append(name)
        for name in hinted_names:
            if name not in onstage and name not in relevant and len(relevant) < 5:
                relevant.append(name)
    return onstage[:6], relevant[:6]


def infer_carryover_clues(text: str) -> list[str]:
    clues = []
    if any(k in text for k in ['柴房', '偏房', '木榻', '水缸', '窗边', '后墙', '搜门', '查门', '断船', '断路']):
        clues.append('藏身处周边的出口、墙根与搜查路径仍在持续变化。')
    if any(k in text for k in ['掌柜', '伙计', '后门', '灶间']) and any(k in text for k in ['皂衣人', '官爷', '盘问', '堵门']):
        clues.append('掌柜与伙计的立场、胆量与后续站位仍会影响局势。')
    if any(k in text for k in ['追兵', '搜捕', '盘问']) and not any(k in text for k in ['眼前', '立刻', '逼近']):
        clues.append('外部追索仍在背景层存在。')
    if any(k in text for k in ['伤', '血', '伤者']):
        clues.append('伤势与恢复进度仍会影响后续节奏。')
    return clues[:3]


def infer_onstage_npcs(text: str) -> list[str]:
    names = []
    for name in ['师兄', '褐袍人', '掌柜', '伙计', '老汉', '船夫', '皂衣人', '高个皂衣人', '少年', '姓苏的']:
        if name in text and name not in names:
            names.append(name)
    return names[:4]


def infer_focal_entity(text: str) -> dict | None:
    if not text:
        return None
    injury_markers = ['伤', '血', '还活着', '扶住', '扶着', '伤口', '失血', '半昏半醒', '站不稳', '肋下']
    conflict_markers = ['围攻', '追', '拿下', '砍', '死了', '冲出', '被围']

    if any(token in text for token in injury_markers):
        aliases = []
        for token in ['那人', '那名劲装人', '劲装人', '青年', '被围攻的人', '伤者']:
            if token in text and token not in aliases:
                aliases.append(token)
        return {
            'primary_label': '伤者',
            'aliases': aliases or ['伤者'],
            'role_label': '当前伤者 / 冲突核心对象',
            'onstage': True,
            'possible_link': None,
        }

    if any(token in text for token in conflict_markers):
        aliases = []
        for token in ['那人', '被围攻的人', '中间那人', '劲装人', '青年']:
            if token in text and token not in aliases:
                aliases.append(token)
        return {
            'primary_label': '被围攻者',
            'aliases': aliases or ['被围攻者'],
            'role_label': '当前被围攻对象 / 冲突核心对象',
            'onstage': True,
            'possible_link': None,
        }

    return None


def infer_group_hints(text: str) -> dict[str, dict]:
    hints: dict[str, dict] = {}
    patterns = {
        '皂衣人': r'([一二三四五六七八九十两几半]+)(?:名|道|个)?皂衣人',
        '伙计': r'([一二三四五六七八九十两几半]+)(?:名|个)?伙计',
        '船夫': r'([一二三四五六七八九十两几半]+)(?:名|个)?船夫',
    }
    for label, pattern in patterns.items():
        m = __import__('re').search(pattern, text)
        if m:
            hints[label] = {
                'collective': True,
                'count_hint': m.group(1),
            }
    return hints


def filter_transient_npcs(text: str, onstage: list[str]) -> list[str]:
    filtered = []
    for name in onstage:
        if name == '伙计' and any(token in text for token in ['探出半个身子', '喊了一声', '门口', '看热闹', '有人真朝这边喊了一声']):
            continue
        filtered.append(name)
    return filtered[:4]


def prioritize_scene_targets(text: str, onstage: list[str]) -> list[str]:
    current = list(onstage)
    if not text:
        return current

    target_weights = {
        '师兄': 0,
        '褐袍人': 0,
        '掌柜': 0,
        '伙计': 0,
        '老汉': 0,
        '船夫': 0,
        '皂衣人': 0,
        '高个皂衣人': 0,
        '少年': 0,
        '姓苏的': 0,
    }

    for name in target_weights:
        if name not in text:
            continue
        target_weights[name] += 1
        if any(token in text for token in ['砍', '围攻', '追', '拿下', '死', '伤', '血', '扶住', '救命', '怎么样', '还活着']):
            if name in ['师兄', '褐袍人', '少年']:
                target_weights[name] += 3
            elif name in ['皂衣人', '高个皂衣人']:
                target_weights[name] += 2
            else:
                target_weights[name] -= 1
        if any(token in text for token in ['喊', '问他', '扶起', '护', '救']):
            if name in ['师兄', '褐袍人', '少年']:
                target_weights[name] += 2
        if name == '伙计' and any(token in text for token in ['酒肆门口', '探出半个身子', '喊了一声', '路人', '旁边']):
            target_weights[name] -= 2

    ranked = sorted(target_weights.items(), key=lambda item: item[1], reverse=True)
    prioritized = [name for name, score in ranked if score > 0]
    merged = []
    for name in prioritized + current:
        if name not in merged:
            merged.append(name)
    return merged[:4]


def build_scene_entities(onstage: list[str], text: str = '', focal_entity: dict | None = None) -> list[dict]:
    group_hints = infer_group_hints(text)
    entities = []
    for idx, name in enumerate(onstage, start=1):
        entity = {
            'entity_id': f'scene_npc_{idx:02d}',
            'primary_label': name,
            'aliases': [name],
            'role_label': '待确认',
            'onstage': True,
            'possible_link': None,
            'collective': group_hints.get(name, {}).get('collective', False),
            'count_hint': group_hints.get(name, {}).get('count_hint'),
        }
        if name == '师兄':
            entity['role_label'] = '同行伤者 / 师兄'
        elif name == '褐袍人':
            entity['role_label'] = '褐袍同行者'
            entity['possible_link'] = '师兄（待验证是否为同一人）'
        elif name == '掌柜':
            entity['role_label'] = '掌柜'
        elif name == '伙计':
            entity['role_label'] = '伙计'
        elif name == '老汉':
            entity['role_label'] = '掌舵老汉'
        elif name == '船夫':
            entity['role_label'] = '船夫'
        elif name == '皂衣人':
            entity['role_label'] = '镇北司皂衣人'
            if '高个皂衣人' in onstage:
                entity['possible_link'] = '高个皂衣人（待确认是否为其领头者）'
        elif name == '高个皂衣人':
            entity['role_label'] = '镇北司高个皂衣人'
            if '皂衣人' in onstage:
                entity['possible_link'] = '皂衣人群体（待确认是否同属一批追索者）'
        elif name == '少年':
            entity['role_label'] = '抱包少年'
        elif name == '姓苏的':
            entity['role_label'] = '待确认公子 / 苏姓青年'
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


def infer_immediate_goal(text: str) -> str:
    if any(k in text for k in ['柴房', '偏房', '木榻', '水缸', '窗边', '后墙', '翻出去', '搜门', '查门', '断船', '断路']):
        return '先稳住伤势，再判断藏身处出口与脱困路径。'
    if any(k in text for k in ['堵门', '门口', '让开', '里面还有谁', '自己出来', '腰牌', '谁先说']):
        return '先稳住门口局势，避免伤者身份立刻暴露。'
    if any(k in text for k in ['灶间', '后门', '掌柜', '伙计']) and any(k in text for k in ['伤', '血', '藏', '官爷', '皂衣人']):
        return '先拖住皂衣人，再决定是继续隐瞒、谈条件还是强行突围。'
    if any(k in text for k in ['睡', '住下', '过夜']):
        return '先安顿下来，恢复体力，等下一步。'
    if any(k in text for k in ['住店', '客栈', '房钱', '通铺', '单间']):
        return '先把落脚和过夜问题安排稳。'
    if any(k in text for k in ['问船', '渡口']):
        return '先确认下一段路线和落脚方式。'
    if any(k in text for k in ['追', '逃', '搜捕']):
        return '先稳住眼前局势，避免被截住或失手。'
    return '先看清局势，再决定下一步。'


def infer_immediate_risks(text: str) -> list[str]:
    risks = []
    if any(k in text for k in ['柴房', '偏房', '木榻', '水缸', '窗边', '后墙', '搜门', '查门', '断船', '断路']):
        risks.append('藏身处出口正在被逐步封死，搜查可能很快贴近。')
    if any(k in text for k in ['堵门', '让开', '自己出来', '里面还有谁', '看住门', '谁先说']):
        risks.append('伤者身份与藏身位置正在迅速暴露。')
    if any(k in text for k in ['追兵', '搜捕', '搜查', '盘问']):
        risks.append('场景中的追索或盘问压力仍可能迅速回到前台。')
    if any(k in text for k in ['伤', '血', '痛']):
        risks.append('场景中的伤势与失血仍可能限制下一步行动。')
    if any(k in text for k in ['船', '客栈', '药铺', '渡口']):
        risks.append('当前落脚点或转场路径的安全性尚未完全坐实。')
    return risks[:3]


def update_state(session_id: str) -> dict:
    history = load_history(session_id)
    state = load_state(session_id) or seed_default_state(session_id)
    if state.get('opening_mode') in {'menu', 'direct'} and not state.get('opening_resolved'):
        save_state(session_id, state)
        return state
    assistant_focus = recent_role_text(history, 'assistant', 4)
    user_focus = recent_role_text(history, 'user', 4)
    focus_text = assistant_focus + '\n' + user_focus
    broad_text = recent_text(history, 10)

    base_text = assistant_focus or focus_text
    focal_entity = infer_focal_entity(base_text)
    inferred_onstage = [sanitize_runtime_name(name) for name in infer_onstage_npcs(base_text) if sanitize_runtime_name(name)]
    inferred_onstage = filter_transient_npcs(assistant_focus or focus_text, inferred_onstage)
    inferred_onstage = prioritize_scene_targets(base_text, inferred_onstage)
    if focal_entity and focal_entity['primary_label'] not in inferred_onstage:
        inferred_onstage = [focal_entity['primary_label']] + inferred_onstage
        inferred_onstage = inferred_onstage[:4]
    inferred_relevant = infer_relevant_npcs(broad_text, inferred_onstage)
    inferred_relevant = infer_implicit_relevant(state, assistant_focus or focus_text, inferred_onstage, inferred_relevant)
    inferred_onstage, inferred_relevant = preserve_recent_names(state, assistant_focus or focus_text, inferred_onstage, inferred_relevant)

    opening_locked = bool(state.get('opening_resolved')) and not state.get('opening_started')
    if state.get('opening_resolved') and state.get('opening_started'):
        current_location = str(state.get('location', '') or '').strip()
        current_main_event = str(state.get('main_event', '') or '').strip()
        if current_location in {'', '待确认', '待根据开局建立'} or current_main_event.startswith('开局：'):
            opening_locked = False

    inferred_time = infer_time(focus_text)
    inferred_location = infer_location(assistant_focus or focus_text)
    inferred_main_event = infer_main_event(focus_text)
    inferred_scene_core = infer_scene_core(focus_text)
    inferred_goal = infer_immediate_goal(focus_text)

    next_state = {
        'time': state.get('time') if opening_locked and state.get('time') not in {'', None, '待确认'} else prefer_existing(state.get('time'), inferred_time),
        'location': state.get('location') if opening_locked and state.get('location') not in {'', None, '待确认'} else prefer_existing(state.get('location'), inferred_location),
        'main_event': state.get('main_event') if opening_locked and state.get('main_event') else prefer_existing(state.get('main_event'), inferred_main_event),
        'scene_core': state.get('scene_core') if opening_locked and state.get('scene_core') else prefer_existing(state.get('scene_core'), inferred_scene_core),
        'onstage_npcs': inferred_onstage,
        'scene_entities': build_scene_entities(inferred_onstage, base_text, focal_entity),
        'relevant_npcs': [sanitize_runtime_name(name) for name in inferred_relevant if sanitize_runtime_name(name)],
        'immediate_goal': state.get('immediate_goal') if opening_locked and state.get('immediate_goal') else prefer_existing(state.get('immediate_goal'), inferred_goal),
        'immediate_risks': infer_immediate_risks(focus_text),
        'carryover_clues': infer_carryover_clues(broad_text),
    }
    next_state = retain_strong_lists(state, next_state)
    state = normalize_state_dict(next_state, prev_state=state, session_id=session_id)

    save_state(session_id, state)
    return state
