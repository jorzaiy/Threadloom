#!/usr/bin/env python3
from __future__ import annotations

from runtime_store import is_complete_assistant_item, load_history, load_state, save_summary


def summarize_text(text: str, limit: int = 90) -> str:
    one = ' '.join((text or '').split()).strip()
    return one[: limit - 3] + '...' if len(one) > limit else one


def recent_turn_pairs(history: list[dict], limit: int = 4) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    current_user = None
    for item in history:
        role = item.get('role')
        content = item.get('content', '')
        if role == 'user':
            current_user = content
        elif role == 'assistant' and current_user is not None and is_complete_assistant_item(item):
            pairs.append((current_user, content))
            current_user = None
    return pairs[-limit:]


def build_open_questions(state: dict) -> list[str]:
    clues = state.get('carryover_clues', []) or []
    risks = state.get('immediate_risks', []) or []
    arbiter_signals = state.get('arbiter_signals', {}) if isinstance(state.get('arbiter_signals', {}), dict) else {}
    arbiter_events = arbiter_signals.get('events', []) if isinstance(arbiter_signals.get('events', []), list) else []

    items: list[str] = []
    if clues:
        items.append(f"延续线索中哪些会在下一轮真正回到前台：{' / '.join(clues[:3])}")
    if risks:
        items.append(f"当前风险里哪一条会最先落地：{' / '.join(risks[:3])}")
    for event in arbiter_events[:3]:
        if event.get('dice_needed'):
            items.append(f"{event.get('event_id', 'unknown-event')} 仍需进一步裁定或不确定性处理")
        else:
            items.append(f"{event.get('event_id', 'unknown-event')} 的边界已给出，但后续落地方式仍待演出确认")
    if not items and state.get('main_event'):
        items.append(f"当前主事件接下来最自然的推进方式仍待下一轮确认：{state.get('main_event')}")
    return items[:6]


def filtered_threads(state: dict) -> list[dict]:
    threads = state.get('active_threads', []) if isinstance(state.get('active_threads', []), list) else []
    out = []
    for item in threads:
        if not isinstance(item, dict):
            continue
        if item.get('status') == 'watch':
            continue
        out.append(item)
    return out


def filtered_arbiter_events(state: dict) -> list[dict]:
    arbiter_signals = state.get('arbiter_signals', {}) if isinstance(state.get('arbiter_signals', {}), dict) else {}
    events = arbiter_signals.get('events', []) if isinstance(arbiter_signals.get('events', []), list) else []
    out = []
    for item in events:
        if not isinstance(item, dict):
            continue
        result = str(item.get('result', '') or '').strip()
        if not result or result in {'unknown', 'none', '待确认'}:
            continue
        out.append(item)
    return out


def build_summary_lines(state: dict, history: list[dict]) -> list[str]:
    onstage = state.get('onstage_npcs', [])
    relevant = state.get('relevant_npcs', [])
    risks = state.get('immediate_risks', [])
    clues = state.get('carryover_clues', [])
    arbiter_events = filtered_arbiter_events(state)
    active_threads = filtered_threads(state)
    open_questions = build_open_questions(state)

    lines = [
        '# Summary',
        '',
        '## 当前状态锚点',
        f"- 时间：{state.get('time', '待确认')}",
        f"- 地点：{state.get('location', '待确认')}",
        f"- 主事件：{state.get('main_event', '待确认')}",
        f"- 当前在场人物：{' / '.join(onstage) if onstage else '暂无'}",
        f"- 当前相关人物：{' / '.join(relevant) if relevant else '暂无'}",
        f"- 当前直接目标：{state.get('immediate_goal', '待确认')}",
        f"- 当前风险：{' / '.join(risks) if risks else '暂无'}",
        f"- 延续线索：{' / '.join(clues) if clues else '暂无'}",
        '',
        '## 活跃线程',
    ]

    if active_threads:
        for item in active_threads[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('thread_id', 'thread')} / {item.get('kind', 'unknown')}：{item.get('label', '待确认')}")
            lines.append(f"- 目标：{item.get('goal', '待确认')}")
            lines.append(f"- 阻碍：{item.get('obstacle', '待确认')}")
    else:
        lines.append('- 暂无')

    lines.extend([
        '',
        '## 当前裁定信号',
    ])

    if arbiter_events:
        for item in arbiter_events[:6]:
            lines.append(f"- {item.get('event_id', 'unknown-event')}：{item.get('result', 'unknown')}")
    else:
        lines.append('- 暂无')

    lines.extend([
        '',
        '## 最近变化',
    ])

    pairs = recent_turn_pairs(history, 4)
    if pairs:
        for user_text, reply_text in pairs:
            lines.append(f"- 用户动作：{summarize_text(user_text)}")
            lines.append(f"- 世界反馈：{summarize_text(reply_text)}")
    else:
        lines.append('- 暂无')

    lines.extend([
        '',
        '## 未决问题',
    ])
    if open_questions:
        for item in open_questions:
            lines.append(f'- {item}')
    else:
        lines.append('- 暂无')

    return lines


def update_summary(session_id: str) -> str:
    history = load_history(session_id)
    state = load_state(session_id)
    content = '\n'.join(build_summary_lines(state, history)) + '\n'
    save_summary(session_id, content)
    return content
