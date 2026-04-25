#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from paths import current_sessions_root, legacy_sessions_root


@dataclass
class SessionSummary:
    name: str
    path: str
    file_count: int
    size_bytes: int
    is_archive: bool
    has_history: bool
    has_state: bool
    has_summary: bool
    has_meta: bool
    has_context: bool
    has_persona: bool
    has_trace: bool
    session_like: bool
    empty_stub: bool


def _file_count(path: Path) -> int:
    return sum(1 for p in path.rglob('*') if p.is_file())


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob('*'):
        if not p.is_file():
            continue
        try:
            total += p.stat().st_size
        except FileNotFoundError:
            continue
    return total


def summarize_session_dir(path: Path) -> SessionSummary:
    file_count = _file_count(path)
    size_bytes = _dir_size(path)
    has_history = (path / 'memory' / 'history.jsonl').exists()
    has_state = (path / 'memory' / 'state.json').exists()
    has_summary = (path / 'memory' / 'summary.md').exists()
    has_meta = (path / 'meta.json').exists()
    has_context = (path / 'context.json').exists()
    has_persona = (path / 'persona').exists()
    has_trace = (path / 'turn-trace').exists()
    session_like = any((
        has_history,
        has_state,
        has_summary,
        has_meta,
        has_context,
        has_trace,
    ))
    empty_stub = file_count == 0
    return SessionSummary(
        name=path.name,
        path=str(path),
        file_count=file_count,
        size_bytes=size_bytes,
        is_archive=path.name.startswith('archive-'),
        has_history=has_history,
        has_state=has_state,
        has_summary=has_summary,
        has_meta=has_meta,
        has_context=has_context,
        has_persona=has_persona,
        has_trace=has_trace,
        session_like=session_like,
        empty_stub=empty_stub,
    )


def _shape_signature(path: Path) -> tuple[int, int, tuple[str, ...]]:
    rel_files: list[str] = []
    size_total = 0
    for p in sorted(path.rglob('*')):
        if not p.is_file():
            continue
        rel_files.append(str(p.relative_to(path)))
        try:
            size_total += p.stat().st_size
        except FileNotFoundError:
            continue
    return len(rel_files), size_total, tuple(rel_files)


def _same_shape(left: Path, right: Path) -> bool:
    return _shape_signature(left) == _shape_signature(right)


def build_audit_report() -> dict:
    legacy_root = legacy_sessions_root()
    current_root = current_sessions_root()

    legacy_dirs = sorted(
        [p for p in legacy_root.iterdir() if p.is_dir()],
        key=lambda p: p.name,
    ) if legacy_root.exists() else []
    current_dirs = {
        p.name: p
        for p in sorted(
            [p for p in current_root.iterdir() if p.is_dir()],
            key=lambda p: p.name,
        )
    } if current_root.exists() else {}

    legacy_only_empty: list[dict] = []
    legacy_only_session_like: list[dict] = []
    legacy_only_other: list[dict] = []
    mirrored_equal: list[dict] = []
    mirrored_different: list[dict] = []

    for legacy_dir in legacy_dirs:
        summary = summarize_session_dir(legacy_dir)
        current_dir = current_dirs.get(legacy_dir.name)
        payload = asdict(summary)

        if current_dir is None:
            if summary.empty_stub:
                payload['recommended_action'] = 'safe_delete_empty_stub'
                legacy_only_empty.append(payload)
            elif summary.session_like:
                payload['recommended_action'] = 'migrate_or_keep_before_delete'
                legacy_only_session_like.append(payload)
            else:
                payload['recommended_action'] = 'manual_review_or_drop'
                legacy_only_other.append(payload)
            continue

        payload['current_path'] = str(current_dir)
        if _same_shape(legacy_dir, current_dir):
            payload['recommended_action'] = 'safe_delete_legacy_copy'
            mirrored_equal.append(payload)
        else:
            payload['recommended_action'] = 'manual_compare_before_delete'
            mirrored_different.append(payload)

    safe_delete_now = [item['name'] for item in legacy_only_empty] + [item['name'] for item in mirrored_equal]
    blocking_items = (
        [item['name'] for item in legacy_only_session_like]
        + [item['name'] for item in legacy_only_other]
        + [item['name'] for item in mirrored_different]
    )

    return {
        'legacy_root': str(legacy_root),
        'current_root': str(current_root),
        'legacy_count': len(legacy_dirs),
        'current_count': len(current_dirs),
        'safe_to_delete_legacy_root_now': len(blocking_items) == 0,
        'safe_delete_now': safe_delete_now,
        'blocking_items': blocking_items,
        'categories': {
            'legacy_only_empty': legacy_only_empty,
            'legacy_only_session_like': legacy_only_session_like,
            'legacy_only_other': legacy_only_other,
            'mirrored_equal': mirrored_equal,
            'mirrored_different': mirrored_different,
        },
        'suggested_next_steps': [
            'Run migration with --include-sessions --include-archives before deleting legacy root if you want to preserve old archives.',
            'Delete empty legacy archive stubs first; they carry no file payload.',
            'Only delete the whole legacy sessions root after the blocking_items list is empty.',
        ],
    }


def main() -> int:
    report = build_audit_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
