#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Optional

from runtime_store import is_complete_assistant_item, load_canon, load_context, load_history, load_persona_index, load_state, load_summary
from paths import APP_ROOT, SHARED_ROOT, resolve_layered_source

ROOT = SHARED_ROOT
RUNTIME_WEB = APP_ROOT
CONFIG = RUNTIME_WEB / 'config' / 'runtime.json'


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def load_lorebook(lorebook_path: Path, trigger_text: str, max_entries: int = 12) -> list[dict]:
    """加载世界书，根据 alwaysOn 和关键词匹配筛选条目。

    Args:
        lorebook_path: 世界书 JSON 文件路径
        trigger_text: 用于关键词匹配的文本（通常是用户输入 + 近期历史）
        max_entries: 最多返回的条目数

    Returns:
        筛选后的世界书条目列表
    """
    data = read_json(lorebook_path)
    entries = data.get('entries', [])
    selected = []
    seen_ids = set()

    # 先加 alwaysOn 条目
    for entry in entries:
        if entry.get('alwaysOn'):
            entry_id = entry.get('id', entry.get('title', ''))
            if entry_id not in seen_ids:
                selected.append(entry)
                seen_ids.add(entry_id)

    # 再根据关键词匹配（不区分大小写）
    trigger_lower = trigger_text.lower()
    for entry in entries:
        if entry.get('alwaysOn'):
            continue
        entry_id = entry.get('id', entry.get('title', ''))
        if entry_id in seen_ids:
            continue
        keywords = entry.get('keywords', [])
        if any(kw.lower() in trigger_lower for kw in keywords):
            selected.append(entry)
            seen_ids.add(entry_id)

    # 按 priority 排序（高优先级在前）
    selected.sort(key=lambda x: x.get('priority', 0), reverse=True)
    return selected[:max_entries]


def format_lorebook_entries(entries: list[dict]) -> str:
    """将世界书条目格式化为可注入 prompt 的文本"""
    if not entries:
        return '暂无相关世界书条目'

    lines = []
    for entry in entries:
        title = entry.get('title', entry.get('id', '未命名'))
        content = entry.get('content', '')
        lines.append(f'### {title}')
        lines.append(content)
        lines.append('')
    return '\n'.join(lines).strip()


def extract_lorebook_npc_candidates(entries: list[dict], onstage: list[str], relevant: list[str], limit: int = 8) -> list[dict]:
    names_in_use = set(onstage or []) | set(relevant or [])
    candidates: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        title = (entry.get('title') or '').strip()
        if not title.startswith('NPC：'):
            continue
        npc_name = title.split('NPC：', 1)[1].split('/', 1)[0].strip()
        if not npc_name or npc_name in names_in_use or npc_name in seen:
            continue
        seen.add(npc_name)
        candidates.append({
            'name': npc_name,
            'title': title,
            'summary': (entry.get('content') or '').strip(),
            'priority': entry.get('priority', 0),
        })
        if len(candidates) >= limit:
            break
    return candidates


def _extract_keyword_names(entries: list[dict], names_in_use: set[str]) -> list[str]:
    """Extract NPC names from lorebook entry keywords."""
    names: list[str] = []
    for entry in entries:
        for kw in entry.get('keywords', []) or []:
            token = (kw or '').strip()
            if not token or len(token) < 2 or len(token) > 8:
                continue
            title = (entry.get('title') or '').strip()
            if token == title:
                continue
            if token in names_in_use or token in names:
                continue
            names.append(token)
    return names


def build_featured_cast(lorebook_path: Path, trigger_text: str, onstage: list[str], relevant: list[str], limit: int = 10) -> list[dict]:
    data = read_json(lorebook_path)
    entries = data.get('entries', [])
    names_in_use = set(onstage or []) | set(relevant or [])

    featured_entries = [
        entry for entry in entries
        if entry.get('entryType') == 'cast'
        or entry.get('featured')
        or (entry.get('priority', 0) or 0) >= 50
    ]
    if not featured_entries:
        featured_entries = [
            entry for entry in entries
            if (entry.get('priority', 0) or 0) >= 20
            and not (entry.get('title') or '').strip().startswith('NPC：')
        ]

    trigger_lower = trigger_text.lower()
    scored: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for entry in featured_entries:
        title = (entry.get('title') or '').strip()
        content = (entry.get('content') or '').strip()
        base_score = int(entry.get('priority', 0) or 0)
        keywords = entry.get('keywords', []) or []
        keyword_bonus = 0
        if any((kw or '').lower() in trigger_lower for kw in keywords):
            keyword_bonus += 8
        candidate_names = _extract_keyword_names([entry], names_in_use)
        for name in candidate_names:
            if name in names_in_use or name in seen:
                continue
            seen.add(name)
            score = base_score + keyword_bonus
            if name in trigger_text:
                score += 10
            scored.append((score, {
                'name': name,
                'title': f'世界书 / {title}',
                'summary': content,
                'priority': score,
            }))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _score, item in scored[:limit]]


def load_runtime_config() -> dict:
    return read_json(CONFIG)


def resolve_source(path_str: str) -> Path:
    return resolve_layered_source(path_str)


def extract_prefixed_value(text: str, prefix: str, fallback: str = '待确认') -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.split('：', 1)[1].strip().rstrip('。')
    return fallback


def extract_section_lines(text: str, section: str):
    lines = text.splitlines()
    out = []
    in_section = False
    for line in lines:
        if line.startswith('## '):
            in_section = line.strip() == f'## {section}'
            if in_section:
                continue
            elif out:
                break
        elif in_section:
            out.append(line)
    return out


def extract_scene_entities(state_text: str) -> list[dict]:
    lines = extract_section_lines(state_text, 'Scene Entities')
    entities = []
    current = None
    for line in lines:
        if line.startswith('- entity_id:'):
            if current:
                entities.append(current)
            current = {
                'entity_id': line.split(':', 1)[1].strip(),
                'primary_label': '',
                'aliases': [],
                'role_label': '待确认',
                'onstage': False,
                'possible_link': None,
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith('- 当前主称呼：'):
            current['primary_label'] = stripped.split('：', 1)[1].strip()
        elif stripped.startswith('- 其他称呼：'):
            raw = stripped.split('：', 1)[1].strip()
            current['aliases'] = [x.strip() for x in raw.split('/') if x.strip()]
        elif stripped.startswith('- 身份标签：'):
            current['role_label'] = stripped.split('：', 1)[1].strip()
        elif stripped.startswith('- 是否当前在场：'):
            current['onstage'] = stripped.split('：', 1)[1].strip().startswith('是')
        elif stripped.startswith('- 可能关联：'):
            current['possible_link'] = stripped.split('：', 1)[1].strip()
    if current:
        entities.append(current)
    return entities


def extract_named_entries(state_text: str, section: str):
    names = []
    for line in extract_section_lines(state_text, section):
        if line.startswith('- ') and '：' in line:
            name = line[2:].split('：', 1)[0].strip()
            if any(name.startswith(x) for x in ['暂无', '参考模板', '单个活跃 NPC']):
                continue
            names.append(name)
    return names


def load_persona_summaries(names: list[str], limit: int = 6, session_id: str | None = None) -> list[dict]:
    persona_index = load_persona_index(session_id)
    if not persona_index:
        return []
    out = []
    ordered_names = list(dict.fromkeys(names or []))
    for display in ordered_names:
        data = persona_index.get(display)
        if not data:
            continue
        hooks = data.get('persona_seed', {}).get('runtime_hooks', {})
        out.append({
            'name': display,
            'layer': data.get('seed_layer', 'scene'),
            'tier': data.get('seed_confidence_tier', 'normal'),
            'mbti': data.get('persona_seed', {}).get('mbti', {}),
            'archetype': data.get('persona_seed', {}).get('archetype', {}),
            'hooks': {
                'decision_style': hooks.get('decision_style', {}).get('value', '待确认'),
                'social_strategy': hooks.get('social_strategy', {}).get('value', '待确认'),
                'conflict_style': hooks.get('conflict_style', {}).get('value', '待确认'),
                'speech_rhythm': hooks.get('speech_rhythm', {}).get('value', '待确认'),
                'stress_response': hooks.get('stress_response', {}).get('value', '待确认'),
            }
        })
        if len(out) >= limit:
            break
    return out[:limit]


def load_npc_profiles(npc_dir: Path, names: list[str], limit: int = 4) -> list[dict]:
    """加载 NPC 档案内容（而不仅仅是路径）"""
    if not npc_dir.exists():
        return []
    out = []
    for path in sorted(npc_dir.glob('*.md')):
        name = path.stem
        if names and name not in names:
            continue
        content = read_text(path)
        out.append({'name': name, 'content': content})
    return out[:limit]


def build_runtime_context(session_id: str) -> dict:
    cfg = load_runtime_config()
    sources = cfg.get('sources', {})

    runtime_rules = read_text(resolve_source(sources['runtime_rules']))
    state_json = load_state(session_id)
    summary_text = load_summary(session_id)
    canon_text = load_canon(session_id)
    session_context = load_context(session_id)
    character_core = read_json(resolve_source(sources['character_core']))
    user_text = read_text(resolve_source(sources.get('user', 'USER.md')))
    player_profile_md = read_text(resolve_source(sources.get('player_profile_md', 'player-profile.md')))
    player_profile_json = read_json(resolve_source(sources.get('player_profile_json', 'player-profile.json')))

    preset_dir = resolve_source(sources['preset_dir'])
    active_preset_name = sources.get('active_preset', 'world-sim-balanced')
    preset = read_json(preset_dir / f'{active_preset_name}.json')

    state_text = ''
    if state_json:
        state_text = '\n'.join([
            f"- 当前时间：{state_json.get('time', '待确认')}。",
            f"- 当前地点：{state_json.get('location', '待确认')}。",
            f"- 当前主事件：{state_json.get('main_event', '待确认')}。",
            f"- 当前局势核心：{state_json.get('scene_core', '待确认')}。",
        ])
    onstage = state_json.get('onstage_npcs', [])
    relevant = state_json.get('relevant_npcs', [])

    persona = load_persona_summaries(onstage + relevant, session_id=session_id)
    npc_profiles = load_npc_profiles(resolve_source(sources['npc_profiles_dir']), onstage + relevant)
    recent_history_all = load_history(session_id)
    recent_history = []
    for item in recent_history_all:
        if item.get('role') == 'assistant' and not is_complete_assistant_item(item):
            continue
        recent_history.append(item)
    recent_history = recent_history[-cfg.get('refresh_policy', {}).get('recent_history_turns', 10):]
    arbiter_signals = state_json.get('arbiter_signals', {}) if isinstance(state_json.get('arbiter_signals', {}), dict) else {}
    active_threads = state_json.get('active_threads', []) if isinstance(state_json.get('active_threads', []), list) else []
    important_npcs = state_json.get('important_npcs', []) if isinstance(state_json.get('important_npcs', []), list) else []

    # --- 世界书加载 ---
    lorebook_path = resolve_source(sources.get('lorebook', 'character/lorebook.json'))
    # 关键词触发源优先围绕当前 state / scene entities，再辅以少量 recent history
    trigger_parts = []
    trigger_parts.append(state_json.get('main_event', ''))
    trigger_parts.append(state_json.get('scene_core', ''))
    trigger_parts.append(state_json.get('time', ''))
    trigger_parts.append(state_json.get('location', ''))
    trigger_parts.append(state_json.get('immediate_goal', ''))
    trigger_parts.extend(state_json.get('immediate_risks', []) or [])
    trigger_parts.extend(state_json.get('carryover_clues', []) or [])
    for item in arbiter_signals.get('events', []) if isinstance(arbiter_signals.get('events', []), list) else []:
        if not isinstance(item, dict):
            continue
        trigger_parts.append(item.get('event_id', ''))
        trigger_parts.append(item.get('result', ''))
    for item in active_threads[:4]:
        if not isinstance(item, dict):
            continue
        for field in ('label', 'goal', 'obstacle', 'latest_change', 'kind'):
            trigger_parts.append(str(item.get(field, '')))
    for item in important_npcs[:6]:
        if not isinstance(item, dict):
            continue
        for field in ('primary_label', 'role_label', 'anchor_type'):
            trigger_parts.append(str(item.get(field, '')))
    for key, value in arbiter_signals.get('flags', {}).items() if isinstance(arbiter_signals.get('flags', {}), dict) else []:
        trigger_parts.append(str(key))
        trigger_parts.append(str(value))
    for npc in onstage + relevant:
        trigger_parts.append(npc)
    for entity in state_json.get('scene_entities', []) or []:
        if not isinstance(entity, dict):
            continue
        trigger_parts.append(entity.get('primary_label', ''))
        trigger_parts.append(entity.get('role_label', ''))
        trigger_parts.extend(entity.get('aliases', []) or [])
        possible_link = entity.get('possible_link')
        if possible_link:
            trigger_parts.append(possible_link)
    for item in recent_history[-4:]:
        trigger_parts.append(item.get('content', ''))
    trigger_text = '\n'.join(trigger_parts)

    lorebook_strategy = preset.get('lorebookStrategy', {})
    max_lore_entries = lorebook_strategy.get('maxEntries', 12)
    lorebook_entries = load_lorebook(lorebook_path, trigger_text, max_lore_entries)
    lorebook_text = format_lorebook_entries(lorebook_entries)
    lorebook_npc_candidates = extract_lorebook_npc_candidates(lorebook_entries, onstage, relevant)
    featured_cast = build_featured_cast(lorebook_path, trigger_text, onstage, relevant)
    merged_candidates = list(lorebook_npc_candidates)
    seen_candidate_names = {item['name'] for item in merged_candidates}
    for item in featured_cast:
        if item['name'] in seen_candidate_names:
            continue
        merged_candidates.append(item)
        seen_candidate_names.add(item['name'])

    # --- Preset 内容提取 ---
    preset_system_template = preset.get('systemTemplate', '')
    preset_reply_rules = preset.get('replyRules', [])

    return {
        'runtime_rules': runtime_rules,
        'session_context': session_context,
        'character_core': character_core,
        'user_text': user_text,
        'player_profile_md': player_profile_md,
        'player_profile_json': player_profile_json,
        'canon': canon_text,
        'state_text': state_text,
        'summary_text': summary_text,
        'active_preset': {
            'name': active_preset_name,
            'data': preset,
            'system_template': preset_system_template,
            'reply_rules': preset_reply_rules,
        },
        'lorebook_text': lorebook_text,
        'lorebook_entries': lorebook_entries,
        'lorebook_npc_candidates': merged_candidates,
        'scene_facts': {
            'time': state_json.get('time', '待确认'),
            'location': state_json.get('location', '待确认'),
            'main_event': state_json.get('main_event', '待确认'),
            'scene_core': state_json.get('scene_core', '待确认'),
            'scene_entities': state_json.get('scene_entities', []),
            'onstage_npcs': onstage,
            'relevant_npcs': relevant,
            'immediate_goal': [state_json.get('immediate_goal', '待确认')],
            'immediate_risks': state_json.get('immediate_risks', []),
            'carryover_clues': state_json.get('carryover_clues', []),
            'arbiter_signals': arbiter_signals,
            'active_threads': active_threads,
            'important_npcs': important_npcs,
        },
        'persona': persona,
        'npc_profiles': npc_profiles,
        'recent_history': recent_history,
    }
