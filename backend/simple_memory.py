#!/usr/bin/env python3
"""
Simple Memory (V3)
实现逐轮小结、大总结、超级总结及当前状态的存储、加载、上下文组装、模型生成及异步Worker调度。
"""
from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

try:
    from atomic_io import atomic_write_json, atomic_write_text
    from model_client import call_model
    from model_config import resolve_provider_model
    from paths import (
        active_character_id,
        active_user_context,
        active_user_id,
        reset_active_character_override,
        resolve_session_dir,
        set_active_character_override,
    )
    from runtime_store import load_history_turn_pair
except ImportError:
    from .atomic_io import atomic_write_json, atomic_write_text
    from .model_client import call_model
    from .model_config import resolve_provider_model
    from .paths import (
        active_character_id,
        active_user_context,
        active_user_id,
        reset_active_character_override,
        resolve_session_dir,
        set_active_character_override,
    )
    from .runtime_store import load_history_turn_pair

# 模块级会话锁获取函数（避免在顶层直接 import server 导致循环依赖）
def session_lock(session_id: str) -> threading.Lock:
    try:
        from server import session_lock as _sl
        return _sl(session_id)
    except ImportError:
        from .server import session_lock as _sl
        return _sl(session_id)

logger = logging.getLogger(__name__)

# 全局读写锁，保证并发安全
_MEMORY_LOCK = threading.RLock()


def memory_dir_for_session(session_id: str) -> Path:
    session_dir = resolve_session_dir(session_id, create=True)
    mem_dir = session_dir / 'memory'
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


def turn_summaries_path(session_id: str) -> Path:
    return memory_dir_for_session(session_id) / 'turn_summaries.jsonl'


def big_summaries_path(session_id: str) -> Path:
    return memory_dir_for_session(session_id) / 'big_summaries.json'


def super_summaries_path(session_id: str) -> Path:
    return memory_dir_for_session(session_id) / 'super_summaries.json'


def state_path(session_id: str) -> Path:
    return memory_dir_for_session(session_id) / 'state.json'


# ---------------------------------------------------------------------------
# 存储接口 (Storage APIs)
# ---------------------------------------------------------------------------

def load_turn_summaries(session_id: str) -> list[dict]:
    """读取所有逐轮小结，按 turn 升序排列。"""
    path = turn_summaries_path(session_id)
    if not path.exists():
        return []
    summaries = []
    with _MEMORY_LOCK:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if isinstance(record, dict):
                            summaries.append(record)
                    except Exception:
                        logger.warning('Skipping malformed turn summary line in %s', path)
        except OSError:
            logger.exception('Failed to read turn summaries from %s', path)
            return []
    summaries.sort(key=lambda x: int(x.get('turn', 0) or 0))
    return summaries


def save_turn_summaries(session_id: str, items: list[dict]) -> None:
    """整写所有逐轮小结。"""
    path = turn_summaries_path(session_id)
    sorted_items = sorted(items, key=lambda x: int(x.get('turn', 0) or 0))
    lines = [json.dumps(item, ensure_ascii=False) for item in sorted_items]
    content = '\n'.join(lines) + ('\n' if lines else '')
    with _MEMORY_LOCK:
        atomic_write_text(path, content)


def upsert_turn_summary(session_id: str, record: dict) -> None:
    """添加或更新一条逐轮小结。"""
    turn = int(record.get('turn', 0) or 0)
    with _MEMORY_LOCK:
        items = load_turn_summaries(session_id)
        found = False
        new_items = []
        for it in items:
            if int(it.get('turn', 0) or 0) == turn:
                new_items.append(record)
                found = True
            else:
                new_items.append(it)
        if not found:
            new_items.append(record)
        save_turn_summaries(session_id, new_items)


def delete_turn_summaries_from(session_id: str, turn: int) -> None:
    """删除 turn >= 指定值的小结。"""
    with _MEMORY_LOCK:
        items = load_turn_summaries(session_id)
        filtered = [it for it in items if int(it.get('turn', 0) or 0) < turn]
        save_turn_summaries(session_id, filtered)


def load_big_summaries(session_id: str) -> list[dict]:
    """读取大总结列表。"""
    path = big_summaries_path(session_id)
    if not path.exists():
        return []
    with _MEMORY_LOCK:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    items = data.get('items', [])
                    if isinstance(items, list):
                        return items
        except Exception:
            logger.warning('Failed to load big summaries from %s', path)
    return []


def save_big_summaries(session_id: str, items: list[dict]) -> None:
    """保存大总结列表。"""
    path = big_summaries_path(session_id)
    payload = {'items': items}
    with _MEMORY_LOCK:
        atomic_write_json(path, payload)


def load_super_summaries(session_id: str) -> list[dict]:
    """读取超级总结列表。"""
    path = super_summaries_path(session_id)
    if not path.exists():
        return []
    with _MEMORY_LOCK:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    items = data.get('items', [])
                    if isinstance(items, list):
                        return items
        except Exception:
            logger.warning('Failed to load super summaries from %s', path)
    return []


def save_super_summaries(session_id: str, items: list[dict]) -> None:
    """保存超级总结列表。"""
    path = super_summaries_path(session_id)
    payload = {'items': items}
    with _MEMORY_LOCK:
        atomic_write_json(path, payload)


def load_simple_state(session_id: str) -> dict:
    """读取 V3 精简状态。"""
    path = state_path(session_id)
    if not path.exists():
        return {
            'session_id': session_id,
            'time': '待确认',
            'location': '待确认',
            'onstage': [],
            'goal': '待确认',
            'risks': [],
            'items': [],
            'opening_mode': 'direct',
            'opening_resolved': True,
            'opening_started': False,
            'opening_choice': None,
        }
    with _MEMORY_LOCK:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            logger.warning('Failed to load state from %s', path)
    return {}


def save_simple_state(session_id: str, state_data: dict) -> None:
    """保存 V3 精简状态（state.json 的唯一写入口）。

    兼容旧字段名（onstage_npcs / immediate_goal / immediate_risks），方便开局、
    bootstrap、新游戏等仍按旧结构构造 state 的调用方直接切换过来。
    """
    path = state_path(session_id)
    onstage = state_data.get('onstage')
    if onstage is None:
        onstage = state_data.get('onstage_npcs', [])
    goal = state_data.get('goal')
    if not goal:
        goal = state_data.get('immediate_goal') or '待确认'
    risks = state_data.get('risks')
    if risks is None:
        risks = state_data.get('immediate_risks', [])
    clean_state = {
        'session_id': session_id,
        'time': state_data.get('time', '待确认'),
        'location': state_data.get('location', '待确认'),
        'onstage': list(onstage or []),
        'goal': goal,
        'risks': list(risks or []),
        'items': list(state_data.get('items', []) or []),
        'opening_mode': state_data.get('opening_mode', 'direct'),
        'opening_resolved': bool(state_data.get('opening_resolved', True)),
        'opening_started': bool(state_data.get('opening_started', False)),
        'opening_choice': state_data.get('opening_choice'),
    }
    with _MEMORY_LOCK:
        atomic_write_json(path, clean_state)


# ---------------------------------------------------------------------------
# 上下文组装 (Context Builder)
# ---------------------------------------------------------------------------

def render_state_markdown(state: dict) -> str:
    """渲染【当前状态】区块 Markdown。"""
    if not state:
        return '暂无状态'
    lines = []
    lines.append(f"- 时间：{state.get('time', '待确认')}")
    lines.append(f"- 地点：{state.get('location', '待确认')}")
    onstage = state.get('onstage', [])
    onstage_str = '、'.join(str(p) for p in onstage) if onstage else '无其他在场人物'
    lines.append(f"- 在场人物：{onstage_str}")
    lines.append(f"- 当前目标：{state.get('goal', '待确认')}")
    risks = state.get('risks', [])
    if risks:
        lines.append("- 当前风险：" + "；".join(str(r) for r in risks))
    else:
        lines.append("- 当前风险：暂无明确风险")
    items = state.get('items', [])
    if items:
        item_parts = []
        for it in items:
            if isinstance(it, dict):
                name = it.get('name', '未命名物品')
                holder = it.get('holder', '未知')
                note = it.get('note', '')
                detail = f"{name}（持有：{holder}" + (f"，{note}" if note else "") + "）"
                item_parts.append(detail)
            else:
                item_parts.append(str(it))
        lines.append("- 重要物品：" + "；".join(item_parts))
    else:
        lines.append("- 重要物品：暂无")
    return '\n'.join(lines)


def _truncate_big_summary_plot(content: str, target_reduction: int) -> tuple[str, int]:
    """裁剪大总结中的“## 剧情”栏，人物档案/未解线索/设定原样保留。"""
    sections = re.split(r'(?m)^(?=##\s+)', content)
    new_sections = []
    reduced = 0
    for sec in sections:
        if sec.startswith('## 剧情') and target_reduction > reduced:
            header, _, body = sec.partition('\n')
            needed = target_reduction - reduced
            if len(body) <= needed:
                replacement = "（较早剧情已精简归入长期记忆）\n"
                cut_chars = len(body) - len(replacement)
                reduced += max(0, cut_chars)
                new_sections.append(f"{header}\n{replacement}")
            else:
                cut_body = body[needed:].split('\n', 1)[-1]
                reduced += (len(body) - len(cut_body))
                new_sections.append(f"{header}\n{cut_body}")
        else:
            new_sections.append(sec)
    return ''.join(new_sections), reduced


def build_memory_context(session_id: str, *, max_memory_chars: int = 40000, current_turn: int = 0) -> dict:
    """
    组装分层记忆上下文：
    1. 【长期记忆·超级总结】所有 super_summaries (status=ok)
    2. 【阶段记忆·大总结】最后一份超级总结之后的 big_summaries (status=ok)
    3. 【近期逐轮小结】最后一份总结 covered_end-9 之后的所有小结
    4. 【当前状态】state.json 渲染
    """
    supers = [s for s in load_super_summaries(session_id) if s.get('status') == 'ok' and s.get('content')]
    bigs = [b for b in load_big_summaries(session_id) if b.get('status') == 'ok' and b.get('content')]
    turn_summaries = load_turn_summaries(session_id)
    state = load_simple_state(session_id)

    # 1. 超级总结
    super_texts = []
    last_super_turn_end = 0
    for s in supers:
        content = s.get('content', '').strip()
        if content:
            super_texts.append(content)
            last_super_turn_end = max(last_super_turn_end, int(s.get('turn_end', 0) or 0))
    super_block = '\n\n---\n\n'.join(super_texts)

    # 2. 大总结：最后一份超级总结之后的 big_summaries
    active_bigs = [b for b in bigs if int(b.get('turn_start', 0) or 0) > last_super_turn_end] if last_super_turn_end > 0 else bigs
    active_big_items = []
    last_big_turn_end = 0
    for b in active_bigs:
        content = b.get('content', '').strip()
        if content:
            idx = b.get('index', 1)
            t_start = b.get('turn_start', 1)
            t_end = b.get('turn_end', 100)
            active_big_items.append({
                'header': f"### 大总结 B{idx} (第{t_start}-{t_end}轮)",
                'content': content,
                'index': idx,
                'turn_start': t_start,
                'turn_end': t_end,
            })
            last_big_turn_end = max(last_big_turn_end, int(t_end or 0))

    # 3. 近期逐轮小结：最后一份总结 covered_end-9 之后的小结
    covered_end = max(last_super_turn_end, last_big_turn_end)
    start_turn = max(1, covered_end - 9) if covered_end > 0 else 1
    recent_turns = [t for t in turn_summaries if int(t.get('turn', 0) or 0) >= start_turn]

    # 4. 当前状态
    state_block = render_state_markdown(state)

    def _format_big_block(items: list[dict]) -> str:
        return '\n\n---\n\n'.join(f"{it['header']}\n{it['content']}" for it in items)

    big_block = _format_big_block(active_big_items)

    turn_entries = []
    for t in recent_turns:
        t_num = int(t.get('turn', 0) or 0)
        summary = str(t.get('summary', '') or '').strip()
        if summary:
            turn_entries.append({'turn': t_num, 'text': f"第{t_num}轮：{summary}"})

    turns_block = '\n'.join(entry['text'] for entry in turn_entries)

    # 裁剪
    total_chars = len(super_block) + len(big_block) + len(turns_block) + len(state_block)
    if total_chars > max_memory_chars:
        excess = total_chars - max_memory_chars
        max_turn = current_turn if current_turn > 0 else (max([e['turn'] for e in turn_entries], default=0))
        overlap_threshold = max(1, max_turn - 7)

        non_overlap_entries = [e for e in turn_entries if e['turn'] < overlap_threshold]
        overlap_entries = [e for e in turn_entries if e['turn'] >= overlap_threshold]

        if overlap_entries:
            trimmed_overlap = []
            overlap_cut_chars = 0
            for e in overlap_entries:
                if overlap_cut_chars < excess:
                    overlap_cut_chars += len(e['text']) + 1
                else:
                    trimmed_overlap.append(e)
            turn_entries = non_overlap_entries + trimmed_overlap
            turns_block = '\n'.join(entry['text'] for entry in turn_entries)
            total_chars = len(super_block) + len(big_block) + len(turns_block) + len(state_block)

        if total_chars > max_memory_chars and active_big_items:
            excess = total_chars - max_memory_chars
            earliest_big = active_big_items[0]
            new_content, reduced = _truncate_big_summary_plot(earliest_big['content'], excess)
            earliest_big['content'] = new_content
            big_block = _format_big_block(active_big_items)

    return {
        'super_summary_block': super_block,
        'big_summary_block': big_block,
        'turn_summary_block': turns_block,
        'state_block': state_block,
        'state_json': state,
        'last_big_turn_end': last_big_turn_end,
        'last_super_turn_end': last_super_turn_end,
    }


# ---------------------------------------------------------------------------
# Prompt 加载与辅助
# ---------------------------------------------------------------------------

def _load_prompt_template(filename: str) -> str:
    path = Path(__file__).resolve().parent.parent / 'prompts' / 'memory' / filename
    if path.exists():
        return path.read_text(encoding='utf-8')
    return ''


_PLACEHOLDER_RE = re.compile(r'\{([a-z_]+)\}')


def fill_prompt_template(template: str, **values: str) -> str:
    """单遍替换 {name} 占位符。

    不使用 str.format：模板里的 JSON 示例、以及填入的用户/模型文本都可能含有花括号。
    单遍 re.sub 只替换已知键，未知的 {xxx}（如 JSON 示例）原样保留，
    且替换进来的值不会被二次解析。
    """
    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key in values:
            return str(values[key])
        return match.group(0)
    return _PLACEHOLDER_RE.sub(_sub, template)


def extract_starred_names(markdown_text: str) -> list[str]:
    """从人物档案栏提取所有带 ★ 的角色名。"""
    names = []
    for line in markdown_text.splitlines():
        match = re.search(r'^\s*[-*]?\s*★\s*([^\s：:（(]+)', line)
        if match:
            names.append(match.group(1).strip())
    return names


def verify_and_restore_stars(new_content: str, prev_content: str) -> tuple[str, list[str]]:
    """校验带 ★ 人物，如果新内容遗漏则从上一版的人物档案原样补回。"""
    if not prev_content:
        return new_content, []
    prev_stars = extract_starred_names(prev_content)
    if not prev_stars:
        return new_content, []

    missing = [name for name in prev_stars if f"★{name}" not in new_content and f"★ {name}" not in new_content]
    if not missing:
        return new_content, []

    # 提取上一版人物档案中丢失人物的段落
    prev_sections = re.split(r'(?m)^(?=##\s+)', prev_content)
    prev_profiles_text = ''
    for sec in prev_sections:
        if sec.startswith('## 人物档案'):
            prev_profiles_text = sec
            break

    restored_paragraphs = []
    restored_names = []
    for name in missing:
        pattern = rf'(?m)^[^\n]*★\s*{re.escape(name)}.*?(?=(?:^[^\n]*★)|(?:\n\n)|(?:\Z))'
        found = re.search(pattern, prev_profiles_text, re.DOTALL)
        if found:
            restored_paragraphs.append(found.group(0).strip())
            restored_names.append(name)

    if not restored_paragraphs:
        return new_content, []

    # 将段落补回新版“## 人物档案”的末尾
    new_sections = re.split(r'(?m)^(?=##\s+)', new_content)
    final_sections = []
    appended = False
    for sec in new_sections:
        if sec.startswith('## 人物档案'):
            sec_trimmed = sec.rstrip()
            sec_with_restored = sec_trimmed + '\n' + '\n'.join(restored_paragraphs) + '\n\n'
            final_sections.append(sec_with_restored)
            appended = True
        else:
            final_sections.append(sec)

    if not appended:
        final_sections.append('## 人物档案\n' + '\n'.join(restored_paragraphs) + '\n\n')

    return ''.join(final_sections), restored_names


# ---------------------------------------------------------------------------
# 同步生成函数 (Generation Functions)
# ---------------------------------------------------------------------------

def generate_turn_summary(session_id: str, turn: int, *, arbiter_result: Optional[dict] = None) -> dict:
    """一次模型调用，同时产出 summary 和 state。"""
    pair = load_history_turn_pair(session_id, turn)
    user_input = pair.get('user', {}).get('content', '') if pair else ''
    narrator_reply = pair.get('assistant', {}).get('content', '') if pair else ''
    if not user_input and not narrator_reply:
        raise ValueError(f"Turn {turn} history pair not found in session {session_id}")

    # 读取上一轮的 state
    all_turns = load_turn_summaries(session_id)
    prev_state = {}
    for t in reversed(all_turns):
        if int(t.get('turn', 0) or 0) < turn and t.get('state_after'):
            prev_state = t.get('state_after')
            break
    if not prev_state:
        prev_state = load_simple_state(session_id)

    # 最近 3 条小结
    recent_3 = [t for t in all_turns if int(t.get('turn', 0) or 0) < turn][-3:]
    recent_turn_summaries = '\n'.join(f"第{t.get('turn')}轮：{t.get('summary', '')}" for t in recent_3) or "暂无前序小结"

    # 当前大总结里的人物档案
    bigs = load_big_summaries(session_id)
    latest_big = bigs[-1].get('content', '') if bigs else ''
    big_summary_profiles = "暂无大总结档案"
    if latest_big:
        for sec in re.split(r'(?m)^(?=##\s+)', latest_big):
            if sec.startswith('## 人物档案'):
                big_summary_profiles = sec.strip()
                break

    template = _load_prompt_template('turn-summary.md')
    user_prompt = fill_prompt_template(template, 
        character_core_brief="请维持主角身份与世界观设定一致",
        recent_turn_summaries=recent_turn_summaries,
        big_summary_profiles=big_summary_profiles,
        previous_state=json.dumps(prev_state, ensure_ascii=False, indent=2),
        user_input=user_input,
        narrator_reply=narrator_reply,
    )
    if arbiter_result:
        user_prompt += f"\n\n- 【参考输入】本轮裁定结果：\n{json.dumps(arbiter_result, ensure_ascii=False, indent=2)}"

    system_prompt = "你是严谨的故事记忆提炼助手。你必须直接输出合法的 JSON 对象，不输出任何解释或 Markdown 格式包裹。"
    model_cfg = resolve_provider_model('summarizer')
    model_cfg['max_output_tokens'] = max(int(model_cfg.get('max_output_tokens', 4000) or 4000), 4000)
    model_cfg['stream'] = False
    model_cfg['response_format'] = {'type': 'json_object'}

    reply, usage = call_model(model_cfg, system_prompt, user_prompt)
    reply_clean = reply.strip()
    if reply_clean.startswith('```'):
        reply_clean = re.sub(r'^```(?:json)?\s*', '', reply_clean)
        reply_clean = re.sub(r'\s*```$', '', reply_clean)

    parsed = json.loads(reply_clean)
    summary_text = str(parsed.get('summary', '') or '').strip()
    raw_state = parsed.get('state', {}) if isinstance(parsed.get('state'), dict) else {}

    # 保留开局等基础字段
    merged_state = {
        'session_id': session_id,
        'time': raw_state.get('time') or prev_state.get('time', '待确认'),
        'location': raw_state.get('location') or prev_state.get('location', '待确认'),
        'onstage': list(raw_state.get('onstage', []) or prev_state.get('onstage', []) or []),
        'goal': raw_state.get('goal') or prev_state.get('goal', '待确认'),
        'risks': list(raw_state.get('risks', []) or prev_state.get('risks', []) or []),
        'items': list(raw_state.get('items', []) or prev_state.get('items', []) or []),
        'opening_mode': prev_state.get('opening_mode', 'direct'),
        'opening_resolved': bool(prev_state.get('opening_resolved', True)),
        'opening_started': bool(prev_state.get('opening_started', False)),
        'opening_choice': prev_state.get('opening_choice'),
    }

    reply_hash = hashlib.sha1(narrator_reply.encode('utf-8')).hexdigest()
    return {
        'turn': turn,
        'turn_id': f'turn-{turn:04d}',
        'reply_hash': reply_hash,
        'status': 'ok',
        'summary': summary_text,
        'state_after': merged_state,
        'edited': False,
        'error': '',
        'model': model_cfg.get('model', ''),
        'updated_at': int(time.time() * 1000),
    }


def _memory_thresholds() -> tuple[int, int]:
    """读取 memory.big_every / memory.super_every，缺省 100 / 5。"""
    try:
        try:
            from model_config import load_runtime_config
        except ImportError:
            from .model_config import load_runtime_config
        mem = (load_runtime_config() or {}).get('memory', {}) or {}
    except Exception:
        mem = {}
    big_every = max(1, int(mem.get('big_every', 100) or 100))
    super_every = max(1, int(mem.get('super_every', 5) or 5))
    return big_every, super_every


def generate_big_summary(session_id: str, index: int, *, big_every: int | None = None) -> dict:
    """生成第 index 份大总结（覆盖 big_every 轮小结）。"""
    if big_every is None:
        big_every, _ = _memory_thresholds()
    turn_start = (index - 1) * big_every + 1
    turn_end = index * big_every
    all_turns = load_turn_summaries(session_id)
    interval_turns = [t for t in all_turns if turn_start <= int(t.get('turn', 0) or 0) <= turn_end]

    # 检查是否有 failed 或缺失的小结
    summaries_text_lines = []
    for t_num in range(turn_start, turn_end + 1):
        matching = next((it for it in interval_turns if int(it.get('turn', 0) or 0) == t_num), None)
        if matching and matching.get('status') == 'ok' and matching.get('summary'):
            summaries_text_lines.append(f"第{t_num}轮：{matching.get('summary')}")
        else:
            # 缺失或失败的小结：附上原文
            pair = load_history_turn_pair(session_id, t_num)
            u = pair.get('user', {}).get('content', '') if pair else ''
            a = pair.get('assistant', {}).get('content', '') if pair else ''
            summaries_text_lines.append(f"第{t_num}轮小结缺失（原文：用户：{u}；叙事：{a}）")

    interval_turn_summaries = '\n'.join(summaries_text_lines)

    # 上一份大总结
    bigs = load_big_summaries(session_id)
    prev_big_content = bigs[-1].get('content', '') if bigs else "暂无上一份大总结"

    state = load_simple_state(session_id)
    template = _load_prompt_template('big-summary.md')
    user_prompt = fill_prompt_template(template, 
        previous_big_summary=prev_big_content,
        interval_turn_summaries=interval_turn_summaries,
        current_state=json.dumps(state, ensure_ascii=False, indent=2),
    )
    system_prompt = "你是长期记忆整合助手。必须严格按照'## 剧情'、'## 人物档案'、'## 未解线索'、'## 设定'四个二级标题组织 Markdown 输出。"

    model_cfg = resolve_provider_model('summarizer')
    model_cfg['max_output_tokens'] = 8000
    model_cfg['stream'] = False

    reply, _ = call_model(model_cfg, system_prompt, user_prompt)
    content = reply.strip()

    # ★ 校验与自动重试/补回
    restored_stars = []
    if prev_big_content and prev_big_content != "暂无上一份大总结":
        prev_stars = extract_starred_names(prev_big_content)
        missing_stars = [n for n in prev_stars if f"★{n}" not in content and f"★ {n}" not in content]
        if missing_stars:
            logger.info("Big summary retry for missing stars: %s", missing_stars)
            retry_prompt = user_prompt + f"\n\n注意：上一版人物档案中的重要角色 {missing_stars} 必须保留 ★ 标记与完整档案！请重新输出完整大总结。"
            try:
                retry_reply, _ = call_model(model_cfg, system_prompt, retry_prompt)
                content = retry_reply.strip()
            except Exception:
                pass
            content, restored_stars = verify_and_restore_stars(content, prev_big_content)

    return {
        'index': index,
        'turn_start': turn_start,
        'turn_end': turn_end,
        'status': 'ok',
        'content': content,
        'edited': False,
        'stale': False,
        'restored_stars': restored_stars,
        'error': '',
        'model': model_cfg.get('model', ''),
        'updated_at': int(time.time() * 1000),
    }


def generate_super_summary(session_id: str, index: int, *, big_every: int | None = None, super_every: int | None = None) -> dict:
    """生成第 index 份超级总结（合并 super_every 份大总结）。"""
    if big_every is None or super_every is None:
        cfg_big, cfg_super = _memory_thresholds()
        big_every = big_every or cfg_big
        super_every = super_every or cfg_super
    big_start_idx = (index - 1) * super_every + 1
    big_end_idx = index * super_every
    turn_start = (big_start_idx - 1) * big_every + 1
    turn_end = big_end_idx * big_every

    bigs = load_big_summaries(session_id)
    interval_bigs = [b for b in bigs if big_start_idx <= int(b.get('index', 0) or 0) <= big_end_idx and b.get('content')]
    bigs_text = '\n\n---\n\n'.join(f"### 大总结 B{b.get('index')}\n{b.get('content')}" for b in interval_bigs)

    supers = load_super_summaries(session_id)
    prev_super_content = supers[-1].get('content', '') if supers else "暂无上一份超级总结"

    template = _load_prompt_template('super-summary.md')
    user_prompt = fill_prompt_template(template, 
        previous_super_summary=prev_super_content,
        interval_big_summaries=bigs_text,
    )
    system_prompt = "你是超级记忆提炼专家。必须严格按照'## 剧情'、'## 人物档案'、'## 未解线索'、'## 设定'四个二级标题组织 Markdown 输出。"

    model_cfg = resolve_provider_model('summarizer')
    model_cfg['max_output_tokens'] = 8000
    model_cfg['stream'] = False

    reply, _ = call_model(model_cfg, system_prompt, user_prompt)
    content = reply.strip()

    restored_stars = []
    reference_for_stars = prev_super_content if prev_super_content != "暂无上一份超级总结" else bigs_text
    if reference_for_stars:
        prev_stars = extract_starred_names(reference_for_stars)
        missing_stars = [n for n in prev_stars if f"★{n}" not in content and f"★ {n}" not in content]
        if missing_stars:
            retry_prompt = user_prompt + f"\n\n注意：重要角色 {missing_stars} 必须保留 ★ 标记与完整档案！请重新输出。"
            try:
                retry_reply, _ = call_model(model_cfg, system_prompt, retry_prompt)
                content = retry_reply.strip()
            except Exception:
                pass
            content, restored_stars = verify_and_restore_stars(content, reference_for_stars)

    return {
        'index': index,
        'turn_start': turn_start,
        'turn_end': turn_end,
        'big_range': [big_start_idx, big_end_idx],
        'status': 'ok',
        'content': content,
        'edited': False,
        'stale': False,
        'restored_stars': restored_stars,
        'error': '',
        'model': model_cfg.get('model', ''),
        'updated_at': int(time.time() * 1000),
    }


# ---------------------------------------------------------------------------
# 异步调度与 Worker (Async Dispatcher)
# ---------------------------------------------------------------------------

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='simple_memory_worker')
_SESSION_FUTURES: dict[str, concurrent.futures.Future] = {}
_FUTURES_LOCK = threading.Lock()


# 同一会话在任务运行期间又收到 enqueue 时，记一个"需要再跑一轮"的标记，
# 任务结束时（在 _FUTURES_LOCK 内）检查并续跑，避免新一轮小结被拖到再下一轮。
_RERUN_REQUESTED: set[str] = set()
# 每个会话只保存"最新一轮"的裁定结果：(turn, arbiter_result)。
# 补跑旧轮次时不传裁定结果，避免把别的轮次的裁定喂给它。
_LATEST_ARBITER: dict[str, tuple[int, Optional[dict]]] = {}


def _current_reply_hash(session_id: str, turn: int) -> str | None:
    """返回该轮 assistant 原文的 hash；该轮不存在时返回 None。"""
    pair = load_history_turn_pair(session_id, turn)
    if not pair:
        return None
    content = pair.get('assistant', {}).get('content', '') or ''
    return hashlib.sha1(content.encode('utf-8')).hexdigest()


def _find_turn_record(session_id: str, turn: int) -> dict | None:
    for rec in load_turn_summaries(session_id):
        if int(rec.get('turn', 0) or 0) == turn:
            return rec
    return None


def _process_turn_summary(session_id: str, t_rec: dict, arbiter_for_turn: Optional[dict]) -> None:
    t_num = int(t_rec.get('turn', 0) or 0)
    expected_hash = t_rec.get('reply_hash', '')
    try:
        result = generate_turn_summary(session_id, t_num, arbiter_result=arbiter_for_turn)
        error: Exception | None = None
    except Exception as err:  # 模型失败 / JSON 解析失败
        logger.exception("Failed to generate turn summary for turn %d", t_num)
        result, error = None, err

    # 4.3 有效性校验：成功和失败两条分支都在锁内确认该轮仍然存在且原文未变
    with session_lock(session_id):
        current = _find_turn_record(session_id, t_num)
        cur_hash = _current_reply_hash(session_id, t_num)
        if current is None or cur_hash is None:
            # 该轮已被删除：丢弃结果，不"复活"记录
            logger.info("Discarding turn summary for turn %d (turn deleted)", t_num)
            return
        if (current.get('reply_hash') or '') != (expected_hash or ''):
            # 记录已被重新生成替换，新的 pending 记录会由下一次任务处理
            logger.info("Discarding turn summary for turn %d (record replaced)", t_num)
            return
        if expected_hash and cur_hash != expected_hash:
            # 原文变了但记录没被替换：标记失败计入重试，避免无限补跑
            logger.info("Discarding turn summary for turn %d (reply changed)", t_num)
            result, error = None, RuntimeError('reply changed since placeholder was written')

        if result is not None:
            upsert_turn_summary(session_id, result)
            # 只有在这一轮仍是最新一轮时才更新全局 state.json
            latest_turns = load_turn_summaries(session_id)
            if latest_turns and int(latest_turns[-1].get('turn', 0) or 0) == t_num:
                save_simple_state(session_id, result['state_after'])
        else:
            failed = dict(current)
            failed['status'] = 'failed'
            failed['error'] = str(error)
            failed['retry_count'] = int(current.get('retry_count', 0) or 0) + 1
            failed['updated_at'] = int(time.time() * 1000)
            upsert_turn_summary(session_id, failed)


def _run_session_memory_job(session_id: str, user_id: str, character_id: str) -> None:
    """后台任务执行体：补齐小结 -> 按轮次触发大总结 -> 按份数触发超级总结。"""
    with active_user_context(user_id):
        token = set_active_character_override(character_id)
        needs_more = False
        try:
            big_every, super_every = _memory_thresholds()

            # 1. 补齐 pending / failed 小结，每次最多 3 条
            turn_summaries = load_turn_summaries(session_id)
            need_run_turns = [
                t for t in turn_summaries
                if t.get('status') in {'pending', 'failed'} and int(t.get('retry_count', 0) or 0) < 3
            ]
            with _FUTURES_LOCK:
                latest_arbiter = _LATEST_ARBITER.get(session_id)
            for t_rec in need_run_turns[:3]:
                t_num = int(t_rec.get('turn', 0) or 0)
                arbiter_for_turn = latest_arbiter[1] if latest_arbiter and latest_arbiter[0] == t_num else None
                _process_turn_summary(session_id, t_rec, arbiter_for_turn)
            if len(need_run_turns) > 3:
                needs_more = True

            # 2. 大总结：按轮次到达触发（缺失/失败的小结在生成函数里用原文代替）
            all_turns = load_turn_summaries(session_id)
            max_turn = max((int(t.get('turn', 0) or 0) for t in all_turns), default=0)
            bigs = load_big_summaries(session_id)
            next_big_index = len(bigs) + 1
            big_start = (next_big_index - 1) * big_every + 1
            big_end = next_big_index * big_every
            if max_turn >= big_end:
                interval = [t for t in all_turns if big_start <= int(t.get('turn', 0) or 0) <= big_end]
                # 区间内还有从未尝试过的 pending 小结：先补跑，下一轮任务再生成大总结
                if any(t.get('status') == 'pending' for t in interval):
                    needs_more = True
                else:
                    task_start_time = int(time.time() * 1000)
                    try:
                        big_res = generate_big_summary(session_id, next_big_index, big_every=big_every)
                        with session_lock(session_id):
                            cur_bigs = load_big_summaries(session_id)
                            if len(cur_bigs) + 1 == next_big_index:
                                interval_now = [
                                    t for t in load_turn_summaries(session_id)
                                    if big_start <= int(t.get('turn', 0) or 0) <= big_end
                                ]
                                if any(int(t.get('updated_at', 0) or 0) > task_start_time for t in interval_now):
                                    big_res['stale'] = True
                                cur_bigs.append(big_res)
                                save_big_summaries(session_id, cur_bigs)
                    except Exception:
                        logger.exception("Failed to generate big summary %d", next_big_index)

            # 3. 超级总结：大总结份数到达触发
            bigs = load_big_summaries(session_id)
            supers = load_super_summaries(session_id)
            next_super_index = len(supers) + 1
            if len(bigs) >= next_super_index * super_every:
                try:
                    super_res = generate_super_summary(
                        session_id, next_super_index, big_every=big_every, super_every=super_every,
                    )
                    with session_lock(session_id):
                        cur_supers = load_super_summaries(session_id)
                        if len(cur_supers) + 1 == next_super_index:
                            cur_supers.append(super_res)
                            save_super_summaries(session_id, cur_supers)
                except Exception:
                    logger.exception("Failed to generate super summary %d", next_super_index)
        finally:
            reset_active_character_override(token)
            with _FUTURES_LOCK:
                rerun = needs_more or session_id in _RERUN_REQUESTED
                _RERUN_REQUESTED.discard(session_id)
                if rerun:
                    _SESSION_FUTURES[session_id] = _EXECUTOR.submit(
                        _run_session_memory_job, session_id, user_id, character_id,
                    )
                else:
                    _SESSION_FUTURES.pop(session_id, None)


def enqueue_after_turn(session_id: str, turn: int, *, arbiter_result: Optional[dict] = None) -> None:
    """每轮提交后放入队列调度。已有任务在跑时，标记续跑而不是丢弃。"""
    user_id = active_user_id()
    char_id = active_character_id()
    with _FUTURES_LOCK:
        _LATEST_ARBITER[session_id] = (int(turn), arbiter_result)
        existing = _SESSION_FUTURES.get(session_id)
        if existing and not existing.done():
            _RERUN_REQUESTED.add(session_id)
            return
        _SESSION_FUTURES[session_id] = _EXECUTOR.submit(_run_session_memory_job, session_id, user_id, char_id)


def wait_idle(session_id: str, timeout_s: float = 20.0) -> bool:
    """等待该会话的后台任务（包括续跑的任务）结束，最多 timeout_s 秒。

    调用方不能持有会话锁：后台任务提交结果时需要这把锁。
    """
    deadline = time.monotonic() + timeout_s
    while True:
        with _FUTURES_LOCK:
            future = _SESSION_FUTURES.get(session_id)
        if not future or future.done():
            # done 之后 finally 可能刚续跑了新任务，再看一次
            with _FUTURES_LOCK:
                nxt = _SESSION_FUTURES.get(session_id)
            if not nxt or nxt.done() or nxt is future:
                return True
            future = nxt
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning("wait_idle timed out for session %s after %ss", session_id, timeout_s)
            return False
        try:
            future.result(timeout=remaining)
        except concurrent.futures.TimeoutError:
            logger.warning("wait_idle timed out for session %s after %ss", session_id, timeout_s)
            return False
        except Exception:
            logger.exception("Background memory job failed in wait_idle")


def cancel_and_wait(session_id: str, timeout_s: float = 5.0) -> None:
    """重新生成或删除前调用（锁外）。取消续跑标记，并等待正在运行的任务结束。

    已开始执行的任务无法真正取消，靠提交时的 hash / 存在性校验丢弃结果。
    """
    with _FUTURES_LOCK:
        _RERUN_REQUESTED.discard(session_id)
        future = _SESSION_FUTURES.get(session_id)
    if not future:
        return
    future.cancel()
    try:
        future.result(timeout=timeout_s)
    except Exception:
        pass


def job_status(session_id: str) -> dict:
    """获取当前任务执行状态。"""
    with _FUTURES_LOCK:
        future = _SESSION_FUTURES.get(session_id)
        running = bool(future and not future.done())
    return {
        'running': running,
    }
