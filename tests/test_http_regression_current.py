#!/usr/bin/env python3
"""当前架构可用的 HTTP 回归脚本。

特点：
- 先走 opening，再进入正文回合
- 通过 /api/message 真实调用后端
- 读取 runtime-data/<user>/characters/<character>/sessions/<session>/memory 下的落盘产物
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.paths import active_character_id  # noqa: E402
from backend.runtime_store import session_paths  # noqa: E402


DEFAULT_MESSAGES = [
    '我先不急着暴露目的，只在原地观察周围的人、摊位和路口动静。',
    '我走向最近的茶摊，点茶后听他们谈论最近城里的异常和传闻。',
    '我主动追问茶摊老板，最近有没有受伤的人、陌生面孔或可疑买卖。',
    '我留意旁边那位一直沉默的客人，观察他的手、鞋底泥痕和腰间东西。',
    '我把茶摊听来的地点、人名和异常细节都记住，再慢慢起身离开。',
    '我去附近药铺，询问掌柜近两天是否有人买过止血、金创或解毒的药。',
    '如果掌柜含糊其辞，我就换个说法，问昨夜有没有带伤赶路的人来过。',
    '我把药铺掌柜的回答和茶摊传闻互相对照，找其中重复出现的线索。',
    '我走到巷口停一下，借着观察路人确认有没有人从茶摊一路跟着我。',
    '若暂时没有危险，我就回到先前经过的路口，再看周围布局和人流变化。',
    '我整理目前掌握的信息：茶摊、药铺、可疑客人、伤药、去向，然后判断下一步。',
    '我回想茶摊和药铺里都提到过的人与地点，试着拼出一条完整的行动线。',
    '我结合前面收集的传闻、掌柜反应和可疑客人的表现，决定现在最该追哪条线索。',
]


def post_json(base_url: str, path: str, payload: dict, *, timeout: int) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        base_url.rstrip('/') + path,
        data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def get_json(base_url: str, path: str, *, timeout: int = 60) -> dict:
    with urllib.request.urlopen(base_url.rstrip('/') + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def read_json_if_exists(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def run_round(base_url: str, session_id: str, text: str, round_no: int, *, timeout: int) -> dict:
    start = time.time()
    try:
        payload = {
            'session_id': session_id,
            'text': text,
            'client_turn_id': f'{session_id}-turn-{round_no}',
            'meta': {'debug': True, 'source': 'http-regression-current'},
        }
        data = post_json(base_url, '/api/message', payload, timeout=timeout)
        elapsed = round(time.time() - start, 2)
        state = data.get('state_snapshot') or {}
        selector = (data.get('debug') or {}).get('selector') or {}
        return {
            'round': round_no,
            'input': text,
            'ok': 'error' not in data,
            'elapsed_sec': elapsed,
            'reply_len': len(data.get('reply', '') or ''),
            'reply_excerpt': (data.get('reply', '') or '')[:180],
            'state_snapshot': state,
            'selector': selector,
            'error': data.get('error'),
        }
    except Exception as exc:
        return {
            'round': round_no,
            'input': text,
            'ok': False,
            'elapsed_sec': round(time.time() - start, 2),
            'error': str(exc),
        }


def build_report(base_url: str, session_id: str, results: list[dict]) -> dict:
    paths = session_paths(session_id)
    history = get_json(base_url, f'/api/history?session_id={session_id}')
    state = get_json(base_url, f'/api/state?session_id={session_id}')
    archive = read_json_if_exists(paths['keeper_archive']) or {}
    summary_text = read_text_if_exists(paths['summary'])
    trace_dir = paths['trace_dir']
    trace_files = sorted(p.name for p in trace_dir.glob('*.json')) if trace_dir.exists() else []
    return {
        'session_id': session_id,
        'character_id': active_character_id(),
        'results': results,
        'history_total_count': history.get('total_count'),
        'final_state': state.get('state') or {},
        'keeper_archive_exists': paths['keeper_archive'].exists(),
        'keeper_records_count': len(archive.get('records') or []),
        'keeper_archive': archive,
        'summary_exists': paths['summary'].exists(),
        'summary_length': len(summary_text),
        'summary_excerpt': summary_text[:600],
        'trace_files_count': len(trace_files),
        'trace_files_tail': trace_files[-5:],
        'session_dir': str(paths['session_dir']),
        'memory_dir': str(paths['memory_dir']),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='适配当前 Threadloom 架构的 HTTP 回归脚本')
    parser.add_argument('--base-url', default='http://127.0.0.1:8765', help='后端地址')
    parser.add_argument('--session', default=f'http-regression-{int(time.time())}', help='session id')
    parser.add_argument('--timeout', type=int, default=300, help='单轮请求超时（秒）')
    parser.add_argument('--opening', action='store_true', help='先发送 开始游戏')
    parser.add_argument('--output', default='', help='结果 JSON 输出路径')
    args = parser.parse_args()

    results: list[dict] = []
    round_no = 1
    if args.opening:
        setup = run_round(args.base_url, args.session, '开始游戏', round_no, timeout=args.timeout)
        results.append(setup)
        print(json.dumps({
            'round': round_no,
            'ok': setup.get('ok'),
            'elapsed_sec': setup.get('elapsed_sec'),
            'reply_len': setup.get('reply_len', 0),
            'error': setup.get('error'),
        }, ensure_ascii=False))
        if not setup.get('ok'):
            report = build_report(args.base_url, args.session, results)
            print('===FINAL===')
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        round_no += 1

    for text in DEFAULT_MESSAGES:
        result = run_round(args.base_url, args.session, text, round_no, timeout=args.timeout)
        results.append(result)
        state = result.get('state_snapshot') or {}
        selector = result.get('selector') or {}
        print(json.dumps({
            'round': round_no,
            'ok': result.get('ok'),
            'elapsed_sec': result.get('elapsed_sec'),
            'reply_len': result.get('reply_len', 0),
            'location': state.get('location'),
            'main_event': state.get('main_event'),
            'onstage_npcs': state.get('onstage_npcs') or [],
            'selector_event_hits': len(selector.get('event_hits') or []),
            'selector_inject_summary': bool(selector.get('inject_summary')),
            'selector_inject_lorebook_text': bool(selector.get('inject_lorebook_text')),
            'selector_inject_npc_candidates': bool(selector.get('inject_npc_candidates')),
            'error': result.get('error'),
        }, ensure_ascii=False))
        if not result.get('ok'):
            break
        round_no += 1

    report = build_report(args.base_url, args.session, results)
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('===FINAL===')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(item.get('ok') for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
