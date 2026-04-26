#!/usr/bin/env python3
import json
from pathlib import Path

from character_assets import load_system_npcs
from keeper_record_retriever import retrieve_keeper_records
from npc_bootstrap_agent import load_npc_registry
from object_bootstrap_agent import load_object_registry
from clue_bootstrap_agent import load_clue_registry
from player_profile import load_effective_player_profile, render_runtime_player_profile_markdown
from selector import build_selector_decision
from runtime_store import is_complete_assistant_item, load_canon, load_context, load_event_summaries, load_history, load_persona_index, load_state, load_summary, load_summary_chunks
from paths import APP_ROOT, SHARED_ROOT, resolve_layered_source

ROOT = SHARED_ROOT
RUNTIME_WEB = APP_ROOT
CONFIG = RUNTIME_WEB / 'config' / 'runtime.json'


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def _distilled_lore_paths(lorebook_path: Path) -> tuple[Path, Path]:
    return lorebook_path.parent / 'lorebook-foundation.json', lorebook_path.parent / 'lorebook-index.json'


def _normalize_compact_text(text: str) -> str:
    return ' '.join(str(text or '').split()).strip()


def _short_lore_text(text: str, limit: int) -> str:
    value = _normalize_compact_text(text)
    if not value:
        return ''
    if limit <= 0 or len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + '...'


def _lorebook_match_score(entry: dict, trigger_lower: str) -> tuple[int, int]:
    score = int(entry.get('priority', 0) or 0)
    keyword_hits = 0
    title = str(entry.get('title', '') or '').strip()
    runtime_scope = str(entry.get('runtimeScope', '') or '').strip()
    entry_type = str(entry.get('entryType', '') or '').strip()
    if runtime_scope == 'archive_only' or entry_type == 'runtime_dump':
        return -10**9, 0
    if runtime_scope == 'foundation':
        score += 6
    if entry.get('featured'):
        score += 4
    if entry_type in {'npc', 'cast'}:
        score += 2
    if title and title.lower() in trigger_lower:
        score += 8
        keyword_hits += 1
    for kw in entry.get('keywords', []) or []:
        token = str(kw or '').strip()
        if not token:
            continue
        if token.lower() in trigger_lower:
            score += 6
            keyword_hits += 1
    return score, keyword_hits


def _take_scored_entries(
    selected: list[dict],
    seen_ids: set[str],
    scored_items: list[tuple[int, dict]],
    *,
    limit: int,
) -> None:
    if limit <= 0:
        return
    for _score, entry in scored_items:
        if limit <= 0:
            break
        entry_id = str(entry.get('id', entry.get('title', '')) or '').strip()
        if not entry_id or entry_id in seen_ids:
            continue
        selected.append(entry)
        seen_ids.add(entry_id)
        limit -= 1


def load_lorebook(
    lorebook_path: Path,
    trigger_text: str,
    *,
    max_entries: int = 12,
    min_entries: int = 2,
    include_always_on: bool = True,
    always_on_limit: int = 3,
    matched_limit: int = 4,
    foundation_rule_limit: int = 1,
    foundation_world_limit: int = 1,
    foundation_faction_limit: int = 1,
    situational_faction_limit: int = 1,
    situational_history_limit: int = 1,
    situational_entry_limit: int = 2,
) -> list[dict]:
    """按预算加载世界书，避免 alwaysOn 整块压过最近窗口。"""
    data = read_json(lorebook_path)
    entries = data.get('entries', [])
    selected: list[dict] = []
    seen_ids: set[str] = set()
    trigger_lower = trigger_text.lower()

    always_on_scored: list[tuple[int, dict]] = []
    matched_scored: list[tuple[int, dict]] = []
    for entry in entries:
        entry_id = str(entry.get('id', entry.get('title', '')) or '').strip()
        if not entry_id:
            continue
        score, keyword_hits = _lorebook_match_score(entry, trigger_lower)
        runtime_scope = str(entry.get('runtimeScope', '') or '').strip()
        if score < -10**8:
            continue
        include_as_foundation = bool(entry.get('alwaysOn')) or runtime_scope == 'foundation'
        if include_as_foundation:
            if include_always_on:
                always_on_scored.append((score, entry))
            continue
        if keyword_hits > 0:
            matched_scored.append((score, entry))

    always_on_scored.sort(key=lambda item: item[0], reverse=True)
    matched_scored.sort(key=lambda item: item[0], reverse=True)
    all_scored = sorted(always_on_scored + matched_scored, key=lambda item: item[0], reverse=True)

    foundation_buckets = {
        'rule': [],
        'world': [],
        'faction': [],
        'other': [],
    }
    for item in always_on_scored:
        entry = item[1]
        entry_type = str(entry.get('entryType', '') or '').strip()
        if entry_type == 'rule':
            foundation_buckets['rule'].append(item)
        elif entry_type in {'world', 'region'}:
            foundation_buckets['world'].append(item)
        elif entry_type == 'faction':
            foundation_buckets['faction'].append(item)
        else:
            foundation_buckets['other'].append(item)

    foundation_budget_used = 0
    _take_scored_entries(selected, seen_ids, foundation_buckets['rule'], limit=min(always_on_limit, foundation_rule_limit))
    foundation_budget_used = len(selected)
    remaining_always_on = max(0, always_on_limit - foundation_budget_used)
    _take_scored_entries(selected, seen_ids, foundation_buckets['world'], limit=min(remaining_always_on, foundation_world_limit))
    foundation_budget_used = len(selected)
    remaining_always_on = max(0, always_on_limit - foundation_budget_used)
    _take_scored_entries(selected, seen_ids, foundation_buckets['faction'], limit=min(remaining_always_on, foundation_faction_limit))
    foundation_budget_used = len(selected)
    remaining_always_on = max(0, always_on_limit - foundation_budget_used)
    _take_scored_entries(selected, seen_ids, foundation_buckets['other'], limit=remaining_always_on)

    situational_buckets = {
        'faction': [],
        'history': [],
        'entry': [],
        'other': [],
    }
    for item in matched_scored:
        entry = item[1]
        entry_type = str(entry.get('entryType', '') or '').strip()
        if entry_type == 'faction':
            situational_buckets['faction'].append(item)
        elif entry_type == 'history':
            situational_buckets['history'].append(item)
        elif entry_type in {'entry', 'region', 'npc', 'cast'}:
            situational_buckets['entry'].append(item)
        else:
            situational_buckets['other'].append(item)

    matched_budget_used = 0
    _take_scored_entries(selected, seen_ids, situational_buckets['faction'], limit=min(matched_limit, situational_faction_limit))
    matched_budget_used = len(selected) - foundation_budget_used
    remaining_matched = max(0, matched_limit - matched_budget_used)
    _take_scored_entries(selected, seen_ids, situational_buckets['history'], limit=min(remaining_matched, situational_history_limit))
    matched_budget_used = len(selected) - foundation_budget_used
    remaining_matched = max(0, matched_limit - matched_budget_used)
    _take_scored_entries(selected, seen_ids, situational_buckets['entry'], limit=min(remaining_matched, situational_entry_limit))
    matched_budget_used = len(selected) - foundation_budget_used
    remaining_matched = max(0, matched_limit - matched_budget_used)
    _take_scored_entries(selected, seen_ids, situational_buckets['other'], limit=remaining_matched)

    minimum_target = min(max_entries, max(0, min_entries))
    if len(selected) < minimum_target:
        for pool in (always_on_scored, matched_scored, all_scored):
            for _score, entry in pool:
                if len(selected) >= minimum_target:
                    break
                entry_id = str(entry.get('id', entry.get('title', '')) or '').strip()
                if entry_id in seen_ids:
                    continue
                selected.append(entry)
                seen_ids.add(entry_id)
            if len(selected) >= minimum_target:
                break

    return selected[:max_entries]


def format_lorebook_entries(entries: list[dict], *, max_entry_chars: int = 320, max_total_chars: int = 2200) -> str:
    """将世界书条目压缩为 narrator 可用的摘要形态。"""
    if not entries:
        return '暂无相关世界书条目'

    lines = []
    total_chars = 0
    for entry in entries:
        title = entry.get('title', entry.get('id', '未命名'))
        content = _short_lore_text(entry.get('content', ''), max_entry_chars)
        if not content:
            continue
        block = f"### {title}\n{content}\n"
        if lines and total_chars + len(block) > max_total_chars:
            break
        if not lines and len(block) > max_total_chars:
            allowed = max(80, max_total_chars - len(f"### {title}\n") - 1)
            block = f"### {title}\n{_short_lore_text(content, allowed)}\n"
        lines.append(block.rstrip())
        total_chars += len(block)
    return '\n\n'.join(lines).strip() if lines else '暂无相关世界书条目'


def summarize_lorebook_entries(entries: list[dict], *, max_entry_chars: int = 320, max_total_chars: int = 2200) -> dict:
    blocks = []
    total_chars = 0
    items = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get('title', entry.get('id', '未命名')) or '未命名').strip()
        content = _short_lore_text(entry.get('content', ''), max_entry_chars)
        if not content:
            continue
        block = f"### {title}\n{content}\n"
        if blocks and total_chars + len(block) > max_total_chars:
            break
        if not blocks and len(block) > max_total_chars:
            allowed = max(80, max_total_chars - len(f"### {title}\n") - 1)
            content = _short_lore_text(content, allowed)
            block = f"### {title}\n{content}\n"
        blocks.append(block.rstrip())
        item_chars = len(block.rstrip())
        total_chars += len(block)
        items.append({
            'id': str(entry.get('id', '') or '').strip(),
            'title': title,
            'entryType': str(entry.get('entryType', '') or '').strip() or 'entry',
            'runtimeScope': str(entry.get('runtimeScope', '') or '').strip() or 'situational',
            'featured': bool(entry.get('featured', False)),
            'priority': int(entry.get('priority', 0) or 0),
            'injected_chars': item_chars,
        })
    return {
        'text': '\n\n'.join(blocks).strip() if blocks else '暂无相关世界书条目',
        'items': items,
        'total_chars': len('\n\n'.join(blocks).strip()) if blocks else 0,
    }


def format_lorebook_foundation(path: Path, *, max_rule_chars: int = 180, max_total_chars: int = 1600) -> dict:
    data = read_json(path)
    rules = data.get('rules', []) if isinstance(data.get('rules', []), list) else []
    blocks = []
    items = []
    total = 0
    for item in rules:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title', '') or '世界基础').strip()
        text = _short_lore_text(item.get('text', ''), max_rule_chars)
        if not text:
            continue
        block = f'- {title}: {text}'
        if blocks and total + len(block) > max_total_chars:
            break
        blocks.append(block)
        total += len(block)
        items.append({
            'title': title,
            'category': str(item.get('category', '') or '').strip(),
            'source_entry_ids': item.get('source_entry_ids', []) if isinstance(item.get('source_entry_ids', []), list) else [],
        })
    return {
        'text': '\n'.join(blocks).strip(),
        'items': items,
        'provider': str(data.get('provider', '') or '').strip(),
        'total_chars': len('\n'.join(blocks).strip()) if blocks else 0,
    }


def load_lorebook_index_hits(path: Path, trigger_text: str, *, limit: int = 4, max_item_chars: int = 220, max_total_chars: int = 1200) -> dict:
    data = read_json(path)
    items = data.get('items', []) if isinstance(data.get('items', []), list) else []
    trigger_lower = str(trigger_text or '').lower()
    scored: list[tuple[int, dict, list[str]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title', '') or '').strip()
        keywords = [str(x or '').strip() for x in (item.get('keywords', []) or []) if str(x or '').strip()] if isinstance(item.get('keywords', []), list) else []
        hits = []
        score = 0
        if title and title.lower() in trigger_lower:
            score += 6
            hits.append(title)
        for keyword in keywords:
            if keyword.lower() in trigger_lower:
                score += 4
                hits.append(keyword)
        if score <= 0:
            continue
        scored.append((score, item, hits[:6]))
    scored.sort(key=lambda row: row[0], reverse=True)
    blocks = []
    hit_items = []
    total = 0
    for score, item, hits in scored[:limit]:
        title = str(item.get('title', '') or '世界书线索').strip()
        summary = _short_lore_text(item.get('summary', ''), max_item_chars)
        if not summary:
            continue
        block = f"### {title}\n{summary}"
        if blocks and total + len(block) > max_total_chars:
            break
        blocks.append(block)
        total += len(block)
        hit_items.append({
            'id': str(item.get('id', '') or '').strip(),
            'title': title,
            'score': score,
            'keyword_hits': hits,
            'category': str(item.get('category', '') or '').strip(),
            'source_entry_ids': item.get('source_entry_ids', []) if isinstance(item.get('source_entry_ids', []), list) else [],
        })
    return {
        'text': '\n\n'.join(blocks).strip(),
        'items': hit_items,
        'provider': str(data.get('provider', '') or '').strip(),
        'total_chars': len('\n\n'.join(blocks).strip()) if blocks else 0,
    }


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
            'source': 'lorebook_npc',
        })
        if len(candidates) >= limit:
            break
    return candidates


def extract_system_npc_candidates(onstage: list[str], relevant: list[str], limit: int = 8) -> list[dict]:
    data = load_system_npcs()
    core_items = data.get('core', []) if isinstance(data.get('core', []), list) else []
    faction_items = data.get('faction_named', []) if isinstance(data.get('faction_named', []), list) else []
    roster_items = data.get('roster', []) if isinstance(data.get('roster', []), list) else []
    names_in_use = set(onstage or []) | set(relevant or [])
    candidates: list[dict] = []
    seen: set[str] = set()
    bucket_label = {
        'core': 'system_npc',
        'faction_named': 'system_npc_faction',
        'roster': 'system_npc_roster',
    }
    for bucket_name, bucket in (
        ('core', core_items),
        ('faction_named', faction_items),
        ('roster', roster_items),
    ):
        for item in bucket:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name', '') or '').strip()
            if not name or name in names_in_use or name in seen:
                continue
            seen.add(name)
            candidates.append({
                'name': name,
                'title': f"系统级 NPC：{name}",
                'summary': str(item.get('summary', '') or '').strip(),
                'priority': int(item.get('priority', 0) or 0),
                'faction': str(item.get('faction', '') or '').strip(),
                'role_label': str(item.get('role_label', '') or '').strip(),
                'source': bucket_label.get(bucket_name, 'system_npc'),
            })
            if len(candidates) >= limit:
                return candidates
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
                'source': 'featured_cast',
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


def select_recent_history_window(items: list[dict], limit_pairs: int) -> list[dict]:
    if limit_pairs <= 0:
        return []
    filtered = []
    for item in items or []:
        if item.get('role') == 'assistant' and not is_complete_assistant_item(item):
            continue
        filtered.append(item)
    if not filtered:
        return []

    pair_count = 0
    start_index = len(filtered)
    pending_user = False
    for index in range(len(filtered) - 1, -1, -1):
        role = filtered[index].get('role')
        if role == 'assistant':
            pending_user = True
            start_index = index
        elif role == 'user' and pending_user:
            pair_count += 1
            pending_user = False
            start_index = index
            if pair_count >= limit_pairs:
                break
    return filtered[start_index:]


def count_complete_turn_pairs(items: list[dict]) -> int:
    pair_count = 0
    pending_user = False
    for item in items or []:
        role = item.get('role')
        if role == 'user':
            pending_user = True
        elif role == 'assistant' and pending_user and is_complete_assistant_item(item):
            pair_count += 1
            pending_user = False
    return pair_count


def _slim_character_core(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}
    keep = {}
    for key in ('name', 'role', 'description', 'personality', 'scenario', 'first_mes'):
        value = data.get(key)
        if value:
            keep[key] = value
    core = data.get('coreDescription') if isinstance(data.get('coreDescription'), dict) else {}
    if core:
        keep['coreDescription'] = {k: v for k, v in core.items() if k in {'title', 'tagline', 'summary', 'protagonist'} and v}
    hints = data.get('hints') if isinstance(data.get('hints'), dict) else {}
    if hints:
        keep['hints'] = {k: v for k, v in hints.items() if k in {'runtimeRules', 'style', 'protagonist'} and v}
    return keep


def build_runtime_context(session_id: str, user_text: str = '') -> dict:
    cfg = load_runtime_config()
    sources = cfg.get('sources', {})
    memory_cfg = cfg.get('memory', {}) if isinstance(cfg.get('memory', {}), dict) else {}
    refresh_policy = cfg.get('refresh_policy', {}) if isinstance(cfg.get('refresh_policy', {}), dict) else {}

    runtime_rules = read_text(resolve_source(sources['runtime_rules']))
    state_json = load_state(session_id)
    canon_text = load_canon(session_id)
    summary_text = load_summary(session_id)
    event_summaries = load_event_summaries(session_id).get('items', [])
    summary_chunks = load_summary_chunks(session_id).get('chunks', [])
    session_context = load_context(session_id)
    character_core = _slim_character_core(read_json(resolve_source(sources['character_core'])))
    player_profile_json = load_effective_player_profile()
    player_profile_md = render_runtime_player_profile_markdown(player_profile_json)

    preset_dir = resolve_source(sources['preset_dir'])
    active_preset_name = sources.get('active_preset', 'world-sim-balanced')
    preset = read_json(preset_dir / f'{active_preset_name}.json')

    onstage = state_json.get('onstage_npcs', [])
    relevant = state_json.get('relevant_npcs', [])

    persona = load_persona_summaries(onstage + relevant, session_id=session_id)
    recent_history_all = load_history(session_id)
    current_pair_count = count_complete_turn_pairs(recent_history_all)
    npc_registry = load_npc_registry(session_id)
    object_registry = load_object_registry(session_id)
    clue_registry = load_clue_registry(session_id)
    recent_history_pairs = int(
        memory_cfg.get(
            'recent_history_turns',
            refresh_policy.get('recent_history_turns', 12),
        ) or 12
    )
    recent_history_pairs = max(1, recent_history_pairs)
    recent_history = select_recent_history_window(
        recent_history_all,
        recent_history_pairs,
    )
    keeper_records = retrieve_keeper_records(
        session_id,
        state_json,
        recent_window_pairs=recent_history_pairs,
        current_pair_count=current_pair_count,
        limit=4,
    )
    arbiter_signals = state_json.get('arbiter_signals', {}) if isinstance(state_json.get('arbiter_signals', {}), dict) else {}
    active_threads = state_json.get('active_threads', []) if isinstance(state_json.get('active_threads', []), list) else []
    important_npcs = state_json.get('important_npcs', []) if isinstance(state_json.get('important_npcs', []), list) else []

    # --- 世界书加载：只作为 selector 候选池，不默认注入 ---
    lorebook_path = resolve_source(sources.get('lorebook', 'character/lorebook.json'))
    lorebook_foundation_path, lorebook_index_path = _distilled_lore_paths(lorebook_path)
    # Situational lore matching should stay close to the active scene, with only
    # a small recent-history tail to avoid stale opening-menu terms dominating.
    trigger_parts = []
    trigger_parts.append(user_text)
    for item in state_json.get('carryover_signals', []) or []:
        if not isinstance(item, dict):
            continue
        trigger_parts.append(str(item.get('type', '') or ''))
        trigger_parts.append(str(item.get('text', '') or ''))
    trigger_parts.extend(state_json.get('immediate_risks', []) or [])
    trigger_parts.extend(state_json.get('carryover_clues', []) or [])
    for item in arbiter_signals.get('events', []) if isinstance(arbiter_signals.get('events', []), list) else []:
        if not isinstance(item, dict):
            continue
        trigger_parts.append(item.get('event_id', ''))
        trigger_parts.append(item.get('result', ''))
    for key, value in arbiter_signals.get('flags', {}).items() if isinstance(arbiter_signals.get('flags', {}), dict) else []:
        trigger_parts.append(str(key))
        trigger_parts.append(str(value))
    for item in recent_history[-6:]:
        trigger_parts.append(item.get('content', ''))
    trigger_text = '\n'.join(trigger_parts)

    lorebook_strategy = preset.get('lorebookStrategy', {})
    max_lore_entries = int(lorebook_strategy.get('maxEntries', 6) or 6)
    min_lore_entries = int(lorebook_strategy.get('minEntries', 2) or 2)
    include_always_on = bool(lorebook_strategy.get('includeAlwaysOn', True)) and current_pair_count == 0
    if current_pair_count > 0:
        min_lore_entries = 0
    always_on_limit = int(lorebook_strategy.get('alwaysOnMaxEntries', 3) or 3)
    matched_limit = int(lorebook_strategy.get('matchedMaxEntries', max(0, max_lore_entries - always_on_limit)) or max(0, max_lore_entries - always_on_limit))
    foundation_rule_limit = int(lorebook_strategy.get('foundationRuleMaxEntries', 1) or 1)
    foundation_world_limit = int(lorebook_strategy.get('foundationWorldMaxEntries', 1) or 1)
    foundation_faction_limit = int(lorebook_strategy.get('foundationFactionMaxEntries', 1) or 1)
    situational_faction_limit = int(lorebook_strategy.get('situationalFactionMaxEntries', 1) or 1)
    situational_history_limit = int(lorebook_strategy.get('situationalHistoryMaxEntries', 1) or 1)
    situational_entry_limit = int(lorebook_strategy.get('situationalEntryMaxEntries', 2) or 2)
    max_entry_chars = int(lorebook_strategy.get('maxEntryChars', 320) or 320)
    max_total_chars = int(lorebook_strategy.get('maxTotalChars', 2200) or 2200)
    system_npc_limit = int(lorebook_strategy.get('systemNpcLimit', 3) or 3)
    lorebook_npc_limit = int(lorebook_strategy.get('lorebookNpcLimit', 4) or 4)
    featured_cast_limit = int(lorebook_strategy.get('featuredCastLimit', 3) or 3)

    lorebook_entries = load_lorebook(
        lorebook_path,
        trigger_text,
        max_entries=max_lore_entries,
        min_entries=min_lore_entries,
        include_always_on=include_always_on,
        always_on_limit=always_on_limit,
        matched_limit=matched_limit,
        foundation_rule_limit=foundation_rule_limit,
        foundation_world_limit=foundation_world_limit,
        foundation_faction_limit=foundation_faction_limit,
        situational_faction_limit=situational_faction_limit,
        situational_history_limit=situational_history_limit,
        situational_entry_limit=situational_entry_limit,
    )
    lorebook_summary = summarize_lorebook_entries(
        lorebook_entries,
        max_entry_chars=max_entry_chars,
        max_total_chars=max_total_chars,
    )
    lorebook_index_hits = load_lorebook_index_hits(
        lorebook_index_path,
        trigger_text,
        limit=int(lorebook_strategy.get('situationalIndexMaxItems', 2) or 2),
        max_item_chars=int(lorebook_strategy.get('situationalIndexMaxItemChars', 220) or 220),
        max_total_chars=int(lorebook_strategy.get('situationalIndexMaxTotalChars', 700) or 700),
    )
    lorebook_foundation = format_lorebook_foundation(
        lorebook_foundation_path,
        max_rule_chars=int(lorebook_strategy.get('foundationMaxRuleChars', 180) or 180),
        max_total_chars=int(lorebook_strategy.get('foundationMaxTotalChars', 1600) or 1600),
    )
    lorebook_text = lorebook_index_hits['text'] or lorebook_summary['text']
    system_npc_candidates = extract_system_npc_candidates(onstage, relevant, limit=system_npc_limit)
    lorebook_npc_candidates = extract_lorebook_npc_candidates(lorebook_entries, onstage, relevant, limit=lorebook_npc_limit)
    featured_cast = build_featured_cast(lorebook_path, trigger_text, onstage, relevant, limit=featured_cast_limit)
    merged_lorebook_candidates = list(lorebook_npc_candidates)
    seen_lorebook_candidate_names = {item['name'] for item in merged_lorebook_candidates}
    for item in featured_cast:
        if item['name'] in seen_lorebook_candidate_names:
            continue
        merged_lorebook_candidates.append(item)
        seen_lorebook_candidate_names.add(item['name'])

    continuity_candidates = list(system_npc_candidates)
    seen_candidate_names = {item['name'] for item in continuity_candidates}
    for item in merged_lorebook_candidates:
        if item['name'] in seen_candidate_names:
            continue
        continuity_candidates.append(item)
        seen_candidate_names.add(item['name'])

    selector_decision = build_selector_decision(
        state_json=state_json,
        recent_history=recent_history,
        keeper_records=keeper_records,
        active_threads=active_threads,
        important_npcs=important_npcs,
        onstage=onstage,
        relevant=relevant,
        lorebook_entries=lorebook_entries,
        system_npc_candidates=system_npc_candidates,
        lorebook_npc_candidates=merged_lorebook_candidates,
        event_summaries=event_summaries,
        summary_text=summary_text,
        summary_chunks=summary_chunks,
        user_text=user_text,
    )
    inject_lorebook_text = bool(selector_decision.get('inject_lorebook_text')) or bool(lorebook_index_hits.get('items'))
    if inject_lorebook_text:
        selector_decision['inject_lorebook_text'] = True
    inject_npc_candidates = bool(selector_decision.get('inject_npc_candidates'))
    npc_profile_targets = selector_decision.get('npc_profile_targets', []) or []
    npc_profiles = load_npc_profiles(resolve_source(sources['npc_profiles_dir']), npc_profile_targets) if npc_profile_targets else []
    if not inject_npc_candidates:
        system_npc_candidates = []
        merged_lorebook_candidates = []
    if not inject_lorebook_text:
        lorebook_text = ''

    # --- Preset 内容提取 ---
    preset_system_template = preset.get('systemTemplate', '')
    preset_reply_rules = preset.get('replyRules', [])

    return {
        'runtime_rules': runtime_rules,
        'session_context': session_context,
        'character_core': character_core,
        'player_profile_md': player_profile_md,
        'player_profile_json': player_profile_json,
        'canon': canon_text,
        'state_text': '',
        'active_preset': {
            'name': active_preset_name,
            'data': preset,
            'system_template': preset_system_template,
            'reply_rules': preset_reply_rules,
        },
        'lorebook_text': lorebook_text,
        'lorebook_entries': lorebook_entries,
        'lorebook_foundation_text': lorebook_foundation.get('text', ''),
        'lorebook_foundation': lorebook_foundation,
        'lorebook_index_hits': lorebook_index_hits,
        'lorebook_injection': {
            **lorebook_summary,
            'foundation': lorebook_foundation,
            'index_hits': lorebook_index_hits,
        },
        'lorebook_npc_candidates': merged_lorebook_candidates,
        'system_npc_candidates': system_npc_candidates,
        'continuity_candidates': continuity_candidates,
        'context_audit': selector_decision,
        'scene_facts': {
            'time': state_json.get('time', '待确认'),
            'location': state_json.get('location', '待确认'),
            'main_event': state_json.get('main_event', '待确认'),
            'scene_entities': state_json.get('scene_entities', []),
            'onstage_npcs': onstage,
            'relevant_npcs': relevant,
            'immediate_goal': [state_json.get('immediate_goal', '待确认')],
            'carryover_signals': state_json.get('carryover_signals', []),
            'immediate_risks': state_json.get('immediate_risks', []),
            'carryover_clues': state_json.get('carryover_clues', []),
            'tracked_objects': state_json.get('tracked_objects', []),
            'possession_state': state_json.get('possession_state', []),
            'object_visibility': state_json.get('object_visibility', []),
            'knowledge_scope': state_json.get('knowledge_scope', {}),
            'knowledge_records': state_json.get('knowledge_records', []),
            'actors': state_json.get('actors', {}),
            'actor_context_index': state_json.get('actor_context_index', {}),
            'resolved_events': state_json.get('resolved_events', []),
            'arbiter_signals': arbiter_signals,
            'active_threads': active_threads,
            'important_npcs': important_npcs,
        },
        'persona': persona,
        'npc_profiles': npc_profiles,
        'recent_history': recent_history,
        'npc_registry': npc_registry,
        'keeper_records': keeper_records,
        'summary_text': '',
        'summary_chunks': summary_chunks,
        'selected_summary_chunks': [chunk for chunk in summary_chunks if str(chunk.get('chunk_id', '') or '') in {str(hit.get('chunk_id', '') or '') for hit in (selector_decision.get('summary_chunk_hits', []) or [])}] if bool(selector_decision.get('inject_summary')) else [],
        'event_summaries': event_summaries,
        'npc_roster': selector_decision.get('npc_roster', []),
    }
