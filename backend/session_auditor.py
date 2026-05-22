#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:
    from atomic_io import atomic_write_json
    from runtime_store import filter_committed_history_items, load_event_summaries, load_history, load_state, session_paths
except ImportError:
    from .atomic_io import atomic_write_json
    from .runtime_store import filter_committed_history_items, load_event_summaries, load_history, load_state, session_paths


MICRO_ACTION_TERMS = (
    '嘴巴', '嘴唇', '下唇', '喉结', '眼珠', '眼睛', '眼睫', '睫毛', '瞳孔',
    '手指', '指尖', '五指', '掌心', '肩膀', '背脊', '下巴', '耳根', '脸色',
)

MICRO_ACTION_PATTERNS = (
    '张了一下', '合上', '动了一下', '滑了一下', '抖了一下', '缩了一下',
    '攥紧', '松开', '半寸', '一寸', '两息', '三息', '盯着',
)


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
        },
        'style_drift': style,
        'issues': issues,
        'safe_auto_repairs': [],
        'note': 'MVP 审计只写 diagnostics，不写入 narrator/keeper/selector 使用的主记忆。',
    }
    if save:
        save_audit_report(session_id, report)
    return report
