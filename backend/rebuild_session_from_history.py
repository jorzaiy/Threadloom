#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from continuity_hints import normalized_hint_entries
from continuity_resolver import resolve_important_npc_continuity
from important_npc_tracker import update_important_npcs
from persona_updater import update_persona
from runtime_store import (
    build_state_snapshot,
    load_canon,
    load_context,
    load_history,
    load_state,
    save_canon,
    save_context,
    save_history,
    save_meta,
    save_session_persona_layers,
    save_state,
    save_summary,
    seed_default_state,
    session_paths,
)
from state_updater import update_state
from summary_updater import update_summary
from thread_tracker import apply_thread_tracker


ROOT = Path(__file__).resolve().parents[1]


def _safe_empty_dir(path: Path) -> bool:
    if not path.exists():
        return True
    for item in path.iterdir():
        if item.is_dir():
            if any(item.iterdir()):
                return False
        else:
            return False
    return True


def _load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _is_rebuild_artifact(path: Path, *, source_session: str | None = None) -> bool:
    context = _load_json_file(path / 'context.json')
    if not isinstance(context, dict):
        return False
    if context.get('rebuild_mode') == 'history-only':
        return True
    if source_session and context.get('rebuild_source_session') == source_session:
        return True
    return False


def _remove_target_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _assistant_pairs(items: list[dict]) -> list[tuple[int, dict, dict]]:
    pairs: list[tuple[int, dict, dict]] = []
    current_user: tuple[int, dict] | None = None
    for idx, item in enumerate(items):
        role = item.get('role')
        if role == 'user':
            current_user = (idx, item)
        elif role == 'assistant' and current_user is not None:
            user_idx, user_item = current_user
            if item.get('completion_status', 'complete') != 'complete':
                current_user = None
                continue
            pairs.append((user_idx, user_item, item))
            current_user = None
    return pairs


def _reset_runtime_layers(session_id: str) -> None:
    paths = session_paths(session_id)
    save_state(session_id, seed_default_state(session_id))
    save_summary(session_id, '# Summary\n\n## 当前状态锚点\n- 暂无\n\n## 活跃线程\n- 暂无\n\n## 当前裁定信号\n- 暂无\n\n## 最近变化\n- 暂无\n\n## 未决问题\n- 暂无\n')
    save_meta(session_id, {'last_turn_id': 0, 'processed_client_turn_ids': {}})
    save_session_persona_layers(session_id, {'scene': {}, 'archive': {}, 'longterm': {}})
    trace_dir = paths['trace_dir']
    if trace_dir.exists():
        shutil.rmtree(trace_dir)


def _prepare_target_session(source_session: str, target_session: str, *, force_recreate: bool = False) -> list[dict]:
    source_paths = session_paths(source_session)
    raw_target_dir = ROOT / 'sessions' / target_session
    if raw_target_dir.exists():
        if force_recreate or _safe_empty_dir(raw_target_dir) or _is_rebuild_artifact(raw_target_dir, source_session=source_session):
            _remove_target_dir(raw_target_dir)
        else:
            raise RuntimeError(f'target session already exists and is not empty: {target_session}')
    target_paths = session_paths(target_session)

    history = load_history(source_session)
    save_history(target_session, history)
    save_canon(target_session, load_canon(source_session))
    save_context(target_session, {
        **load_context(source_session),
        'rebuild_source_session': source_session,
        'rebuild_mode': 'history-only',
    })
    return history


def rebuild_session_from_history(source_session: str, *, target_session: str | None = None, max_pairs: int | None = None, force_recreate: bool = False) -> dict:
    session_id = target_session or source_session
    using_target_copy = bool(target_session and target_session != source_session)
    try:
        if using_target_copy:
            full_history = _prepare_target_session(source_session, target_session, force_recreate=force_recreate)
        else:
            full_history = load_history(session_id)
    except Exception:
        if using_target_copy:
            raw_target_dir = ROOT / 'sessions' / session_id
            if _safe_empty_dir(raw_target_dir):
                shutil.rmtree(raw_target_dir, ignore_errors=True)
        raise
    pairs = _assistant_pairs(full_history)
    if max_pairs is not None:
        pairs = pairs[:max_pairs]

    try:
        _reset_runtime_layers(session_id)
        rebuilt_history: list[dict] = []
        reports: list[dict] = []

        for pair_index, (_user_idx, user_item, assistant_item) in enumerate(pairs, start=1):
            rebuilt_history.append(dict(user_item))
            rebuilt_history.append(dict(assistant_item))
            save_history(session_id, rebuilt_history)

            state = update_state(session_id)
            state = apply_thread_tracker(
                state,
                user_text=str(user_item.get('content', '') or ''),
                narrator_reply=str(assistant_item.get('content', '') or ''),
                arbiter=None,
            )
            state['continuity_hints'] = normalized_hint_entries(session_id)
            state = update_important_npcs(state, rebuilt_history, [])
            state = resolve_important_npc_continuity(state)
            save_state(session_id, state)
            persona_counts = update_persona(session_id, [])
            summary_text = update_summary(session_id)

            reports.append({
                'pair_index': pair_index,
                'user_preview': str(user_item.get('content', '') or '')[:120],
                'assistant_preview': str(assistant_item.get('content', '') or '')[:120],
                'state_snapshot': build_state_snapshot(load_state(session_id)),
                'persona_counts': persona_counts,
                'summary_chars': len(summary_text),
            })

        final_state = load_state(session_id)
        report = {
            'session_id': session_id,
            'source_session': source_session,
            'pair_count': len(pairs),
            'history_message_count': len(rebuilt_history),
            'final_state_snapshot': build_state_snapshot(final_state),
            'turn_reports': reports[-8:],
        }
        report_path = session_paths(session_id)['session_dir'] / 'rebuild-report.json'
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return report
    except Exception:
        if using_target_copy:
            raw_target_dir = ROOT / 'sessions' / session_id
            if _safe_empty_dir(raw_target_dir):
                shutil.rmtree(raw_target_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description='Rebuild state/summary/persona/threads from an existing session history')
    parser.add_argument('--session', required=True, help='Existing source session id')
    parser.add_argument('--target-session', help='Optional target session id for safe rebuild testing')
    parser.add_argument('--max-pairs', type=int, help='Optional max number of complete user/assistant pairs to rebuild')
    parser.add_argument('--force-recreate', action='store_true', help='Allow deleting an existing rebuild target session before regenerating it')
    args = parser.parse_args()

    report = rebuild_session_from_history(
        args.session,
        target_session=args.target_session,
        max_pairs=args.max_pairs,
        force_recreate=args.force_recreate,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
