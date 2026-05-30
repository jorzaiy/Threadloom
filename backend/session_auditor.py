#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

try:
    from atomic_io import atomic_write_json
    from name_sanitizer import sanitize_runtime_name, is_protagonist_name, looks_like_bad_entity_fragment, looks_like_non_person_alias_fragment
    from runtime_store import filter_committed_history_items, load_event_summaries, load_history, load_state, session_paths
except ImportError:
    from .atomic_io import atomic_write_json
    from .name_sanitizer import sanitize_runtime_name, is_protagonist_name, looks_like_bad_entity_fragment, looks_like_non_person_alias_fragment
    from .runtime_store import filter_committed_history_items, load_event_summaries, load_history, load_state, session_paths


MICRO_ACTION_TERMS = (
    '嘴巴', '嘴唇', '下唇', '喉结', '眼珠', '眼睛', '眼睫', '睫毛', '瞳孔',
    '手指', '指尖', '五指', '掌心', '肩膀', '背脊', '下巴', '耳根', '脸色',
)

MICRO_ACTION_PATTERNS = (
    '张了一下', '合上', '动了一下', '滑了一下', '抖了一下', '缩了一下',
    '攥紧', '松开', '半寸', '一寸', '两息', '三息', '盯着',
)

NPC_AUDIT_SUFFIXES = ('男人', '女人', '女子', '男子', '姑娘', '老者', '少年', '青年', '修士', '掌柜', '小二', '老板', '妇人', '汉子')
NPC_AUDIT_PREFIXES = ('帷帽', '灰布衫', '黑脸膛', '干瘦', '鬓角', '嚼咸菜')


def _text(value: Any) -> str:
    return str(value or '').strip()


def _count_terms(text: str, terms: tuple[str, ...]) -> int:
    return sum(text.count(term) for term in terms)


def micro_action_score(text: str) -> int:
    value = _text(text)
    if not value:
        return 0
    return _count_terms(value, MICRO_ACTION_TERMS) + _count_terms(value, MICRO_ACTION_PATTERNS)


def _recent_assistant_items(history: list[dict], window_turns: int) -> list[dict]:
    committed = filter_committed_history_items(history)
    assistants = [item for item in committed if isinstance(item, dict) and item.get('role') == 'assistant']
    return assistants[-max(1, int(window_turns or 1)):]


def _turn_label(item: dict, fallback_idx: int) -> str:
    for key in ('turn_id', 'id'):
        value = _text(item.get(key))
        if value:
            return value
    return f'assistant-{fallback_idx + 1}'


def analyze_style_drift(history: list[dict], *, window_turns: int = 6) -> dict:
    assistants = _recent_assistant_items(history, window_turns)
    if not assistants:
        return {
            'status': 'insufficient_data',
            'assistant_turns': 0,
            'avg_chars': 0,
            'avg_micro_action_score': 0,
            'turns': [],
        }

    turns = []
    for idx, item in enumerate(assistants):
        content = _text(item.get('content'))
        score = micro_action_score(content)
        turns.append({
            'turn': _turn_label(item, idx),
            'chars': len(content),
            'micro_action_score': score,
            'micro_action_density_per_1000_chars': round(score * 1000 / max(1, len(content)), 2),
        })
    avg_chars = round(sum(item['chars'] for item in turns) / len(turns), 1)
    avg_score = round(sum(item['micro_action_score'] for item in turns) / len(turns), 1)
    avg_density = round(sum(item['micro_action_density_per_1000_chars'] for item in turns) / len(turns), 2)
    long_turns = [item for item in turns if item['chars'] >= 1800]
    dense_turns = [item for item in turns if item['micro_action_score'] >= 18 or item['micro_action_density_per_1000_chars'] >= 12]
    warning = len(dense_turns) >= 2 or (len(long_turns) >= 3 and avg_score >= 12)
    critical = len(dense_turns) >= 4 and avg_chars >= 1800
    return {
        'status': 'critical' if critical else ('warning' if warning else 'ok'),
        'assistant_turns': len(turns),
        'avg_chars': avg_chars,
        'avg_micro_action_score': avg_score,
        'avg_micro_action_density_per_1000_chars': avg_density,
        'turns': turns,
    }


def _polluted_event_summaries(items: list[dict], *, limit: int = 20) -> list[dict]:
    out = []
    for item in (items or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        summary = _text(item.get('summary'))
        score = micro_action_score(summary)
        if score >= 8 or (len(summary) > 180 and score >= 4):
            out.append({
                'event_id': _text(item.get('event_id')),
                'turn_id': _text(item.get('turn_id')),
                'provider': _text(item.get('provider')),
                'summary_chars': len(summary),
                'micro_action_score': score,
                'summary_excerpt': summary[:160],
            })
    return out


def _persona_hook_findings(state: dict) -> list[dict]:
    hooks = state.get('actor_persona_hooks', {}) if isinstance(state.get('actor_persona_hooks', {}), dict) else {}
    findings = []
    for actor_id, hook in hooks.items():
        if not isinstance(hook, dict):
            continue
        serialized = json.dumps(hook, ensure_ascii=False)
        score = micro_action_score(serialized)
        if score >= 5:
            findings.append({
                'actor_id': str(actor_id),
                'micro_action_score': score,
                'display_name': _text(hook.get('display_name')),
            })
    return findings


def _actor_surfaces(state: dict) -> set[str]:
    surfaces: set[str] = set()
    actors = state.get('actors', {}) if isinstance(state.get('actors', {}), dict) else {}
    for actor in actors.values():
        if not isinstance(actor, dict):
            continue
        for value in [actor.get('name', '')] + list(actor.get('aliases', []) or []):
            name = sanitize_runtime_name(value)
            if name:
                surfaces.add(name)
    for item in state.get('important_npcs', []) or []:
        if not isinstance(item, dict):
            continue
        for value in [item.get('primary_label', '')] + list(item.get('aliases', []) or []):
            name = sanitize_runtime_name(value)
            if name:
                surfaces.add(name)
    for item in state.get('scene_entities', []) or []:
        if not isinstance(item, dict):
            continue
        for value in [item.get('primary_label', '')] + list(item.get('aliases', []) or []):
            name = sanitize_runtime_name(value)
            if name:
                surfaces.add(name)
    return surfaces


def _looks_like_npc_audit_name(value: object) -> bool:
    name = sanitize_runtime_name(value)
    if not name or is_protagonist_name(name) or looks_like_bad_entity_fragment(name) or looks_like_non_person_alias_fragment(name):
        return False
    if any(ch.isdigit() for ch in name):
        return False
    if len(name) > 8:
        return False
    if name in {'来人', '客人', '众人', '几人', '那人', '有人', '掌柜', '修士'}:
        return False
    return any(name.endswith(suffix) for suffix in NPC_AUDIT_SUFFIXES) or any(prefix in name for prefix in NPC_AUDIT_PREFIXES)


def _recent_actor_mentions(history: list[dict], *, window_turns: int) -> dict[str, dict]:
    mentions: dict[str, dict] = {}
    for item in _recent_assistant_items(history, window_turns):
        content = _text(item.get('content'))
        if not content:
            continue
        candidates = set(re.findall(r'[\u4e00-\u9fff]{1,6}(?:男人|女人|女子|男子|姑娘|老者|少年|青年|修士|掌柜|小二|老板|妇人|汉子)', content))
        for raw_name in candidates:
            name = sanitize_runtime_name(raw_name)
            for prefix in ('了个', '那个', '这个', '一位', '一个', '几个', '从', '朝', '把', '瞥了眼', '他收走', '不是朝', '气息从', '角落那桌'):
                if name.startswith(prefix) and len(name) > len(prefix) + 2:
                    name = name[len(prefix):]
            if not _looks_like_npc_audit_name(name):
                continue
            entry = mentions.setdefault(name, {'name': name, 'sources': [], 'excerpt': ''})
            entry['sources'].append(_turn_label(item, len(entry['sources'])))
            if not entry['excerpt']:
                idx = content.find(name)
                entry['excerpt'] = content[max(0, idx - 50):idx + 110] if idx >= 0 else content[:160]
    return mentions


def npc_consistency_findings(state: dict, history: list[dict], event_items: list[dict], *, window_turns: int = 6) -> list[dict]:
    known = _actor_surfaces(state)
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, severity: str, name: str, evidence: dict) -> None:
        clean = sanitize_runtime_name(name)
        key = (kind, clean)
        if not clean or key in seen:
            return
        seen.add(key)
        findings.append({'type': kind, 'severity': severity, 'name': clean, 'evidence': evidence})

    for name, data in _recent_actor_mentions(history, window_turns=window_turns).items():
        if name not in known and len(data.get('sources', [])) >= 2:
            add('unregistered_npc_candidate', 'warning', name, data)

    for item in (event_items or [])[-max(6, window_turns):]:
        if not isinstance(item, dict):
            continue
        for actor in item.get('actors', []) or []:
            name = sanitize_runtime_name(actor)
            if _looks_like_npc_audit_name(name) and name not in known:
                add('summary_actor_missing_from_registry', 'warning', name, {'event_id': item.get('event_id'), 'turn_id': item.get('turn_id')})

    scope = state.get('knowledge_scope', {}) if isinstance(state.get('knowledge_scope', {}), dict) else {}
    npc_local = scope.get('npc_local', {}) if isinstance(scope.get('npc_local', {}), dict) else {}
    for raw_name, payload in npc_local.items():
        name = sanitize_runtime_name(raw_name)
        if _looks_like_npc_audit_name(name) and name not in known:
            learned = payload.get('learned', []) if isinstance(payload, dict) and isinstance(payload.get('learned', []), list) else []
            add('orphan_npc_knowledge_scope', 'warning', name, {'learned': learned[:3]})

    entity_names_by_id: dict[str, set[str]] = {}
    for item in (state.get('resolved_events', []) or [])[-20:]:
        if not isinstance(item, dict):
            continue
        entity_id = _text(item.get('entity_id'))
        name = sanitize_runtime_name(item.get('primary_label', ''))
        if entity_id and name:
            entity_names_by_id.setdefault(entity_id, set()).add(name)
    for entity_id, names in entity_names_by_id.items():
        if len(names) > 1:
            add('scene_entity_id_reuse', 'warning', entity_id, {'names': sorted(names)})
    return findings


def _severity_from_issues(issues: list[dict]) -> str:
    if any(item.get('severity') == 'critical' for item in issues):
        return 'critical'
    if any(item.get('severity') == 'warning' for item in issues):
        return 'warning'
    return 'ok'


def _diagnostics_dir(session_id: str) -> Path:
    session_dir = session_paths(session_id)['session_dir']
    path = session_dir / 'diagnostics'
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_audit_report(session_id: str, report: dict) -> None:
    diagnostics_dir = _diagnostics_dir(session_id)
    latest_path = diagnostics_dir / 'audit_latest.json'
    reports_path = diagnostics_dir / 'audit_reports.json'
    atomic_write_json(latest_path, report, indent=2)
    previous = []
    if reports_path.exists():
        try:
            payload = json.loads(reports_path.read_text(encoding='utf-8'))
            previous = payload.get('reports', []) if isinstance(payload, dict) else []
        except Exception:
            previous = []
    previous.append(report)
    atomic_write_json(reports_path, {'version': 1, 'reports': previous[-20:]}, indent=2)


def run_session_audit(session_id: str, *, window_turns: int = 6, save: bool = True) -> dict:
    history = load_history(session_id)
    state = load_state(session_id)
    event_items = load_event_summaries(session_id).get('items', [])

    style = analyze_style_drift(history, window_turns=window_turns)
    polluted_events = _polluted_event_summaries(event_items)
    persona_findings = _persona_hook_findings(state)
    npc_findings = npc_consistency_findings(state, history, event_items, window_turns=window_turns)

    issues: list[dict] = []
    if style['status'] in {'warning', 'critical'}:
        issues.append({
            'type': 'style_drift',
            'severity': style['status'],
            'message': '最近叙事存在身体微动作/动作拆解密度偏高的风格漂移。',
            'evidence': style,
            'suggested_action': '后续数轮加入短期风格校正：限制微动作密度，优先推进对白、信息和因果结果。',
        })
    if polluted_events:
        issues.append({
            'type': 'polluted_event_summaries',
            'severity': 'warning',
            'message': '部分 event summary 疑似保留了 narrator prose fragment，可能被 selector 当事实召回。',
            'evidence': polluted_events,
            'suggested_action': '标记这些事件索引为 style_polluted，或用结构化事实摘要替换。',
        })
    if persona_findings:
        issues.append({
            'type': 'persona_micro_action_hooks',
            'severity': 'warning',
            'message': '部分 persona hook 可能固化了单轮微动作，后续会强化 narrator 重复描写。',
            'evidence': persona_findings,
            'suggested_action': '人工审查并将微动作改成更抽象的行为倾向。',
        })
    if npc_findings:
        issues.append({
            'type': 'npc_consistency',
            'severity': 'warning',
            'message': '最近叙事或记忆中存在疑似 NPC，但未稳定进入 actor / important_npcs / scene_entities。',
            'evidence': npc_findings,
            'suggested_action': '审查候选 NPC；确认后注册 actor、important_npc 或添加忽略规则。',
        })

    report = {
        'version': 1,
        'session_id': session_id,
        'mode': 'manual_mvp',
        'created_at_ms': int(time.time() * 1000),
        'window_turns': window_turns,
        'severity': _severity_from_issues(issues),
        'summary': {
            'issue_count': len(issues),
            'style_status': style['status'],
            'polluted_event_summary_count': len(polluted_events),
            'persona_hook_issue_count': len(persona_findings),
            'npc_consistency_issue_count': len(npc_findings),
        },
        'style_drift': style,
        'issues': issues,
        'safe_auto_repairs': [],
        'note': 'MVP 审计只写 diagnostics，不写入 narrator/keeper/selector 使用的主记忆。',
    }
    if save:
        save_audit_report(session_id, report)
    return report
