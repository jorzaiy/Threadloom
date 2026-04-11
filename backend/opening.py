#!/usr/bin/env python3
import json
import random
import re
from pathlib import Path

from runtime_store import save_state


ROOT = Path(__file__).resolve().parents[1]
CHAR = ROOT / 'character' / 'character-data.json'


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def load_character() -> dict:
    return read_json(CHAR)


def opening_bootstrap() -> dict:
    char = load_character()
    data = char.get('openingBootstrap') or char.get('openingState') or {}
    return data if isinstance(data, dict) else {}


def opening_hooks() -> list[str]:
    char = load_character()
    return char.get('openingHooks', []) or []


def has_opening_hooks() -> bool:
    return bool(opening_hooks())


def is_opening_command(text: str) -> bool:
    t = (text or '').strip()
    return t in {'开始', '开始游戏', '开始新游戏', '重新开始', '随机开局', '随机开始'}


def build_opening_reply(user_text: str) -> str:
    char = load_character()
    opening = char.get('opening', '故事将从这里开始。')
    hooks = opening_hooks()
    t = (user_text or '').strip()

    if t in {'随机开局', '随机开始'} and hooks:
        picked = random.choice(hooks)
        return f"{opening}\n\n本次随机开局：{picked}"

    if hooks:
        lines = [opening, '', '可用开局：']
        for idx, item in enumerate(hooks, start=1):
            lines.append(f'{idx}. {item}')
        lines.append('')
        lines.append('可直接说“随机开局”，或报数字/开局名字。')
        return '\n'.join(lines)

    return opening


def parse_hook(item: str) -> tuple[str, str]:
    text = (item or '').strip()
    if '：' in text:
        title, detail = text.split('：', 1)
        return title.strip(), detail.strip()
    return text, text


def resolve_opening_choice(text: str) -> str | None:
    value = (text or '').strip()
    hooks = opening_hooks()
    if not hooks:
        return None
    if value in {'随机开局', '随机开始'}:
        return random.choice(hooks)
    normalized = re.sub(r'\s+', '', value)
    digit_match = re.fullmatch(r'(?:开局|选择|选|第)?(\d+)(?:个|号)?', normalized)
    if digit_match:
        idx = int(digit_match.group(1))
        if 1 <= idx <= len(hooks):
            return hooks[idx - 1]
    for item in hooks:
        title, detail = parse_hook(item)
        if value == item or value == title or value == detail:
            return item
        compact_title = re.sub(r'\s+', '', title)
        compact_item = re.sub(r'\s+', '', item)
        if normalized == compact_title or normalized == compact_item:
            return item
    return None


def build_opening_choice_reply(choice: str) -> str:
    title, detail = parse_hook(choice)
    bootstrap = opening_bootstrap()
    time_label = bootstrap.get('time', '')
    lines = []
    if time_label:
        lines.append(f'{time_label}。')
        lines.append('')
    lines.append(f'开局已定：{title}。')
    lines.append('')
    lines.append(detail)
    return '\n'.join(lines)


def initialize_opening_state(session_id: str) -> dict:
    bootstrap = opening_bootstrap()
    hooks_present = has_opening_hooks()
    state = {
        'session_id': session_id,
        'time': bootstrap.get('time', '待确认'),
        'location': bootstrap.get('location', '待确认'),
        'main_event': bootstrap.get('main_event', '开局待展开。'),
        'scene_core': bootstrap.get('scene_core', '开局状态已建立，等待具体场景展开。'),
        'scene_entities': [],
        'onstage_npcs': [],
        'relevant_npcs': [],
        'immediate_goal': bootstrap.get('immediate_goal', '先进入开局场景，再决定第一步行动。'),
        'immediate_risks': [],
        'carryover_clues': [],
        'opening_mode': 'menu' if hooks_present else 'direct',
        'opening_resolved': not hooks_present,
        'opening_started': False,
        'opening_choice': None,
    }
    save_state(session_id, state)
    return state


def initialize_opening_choice_state(session_id: str, choice: str) -> dict:
    title, detail = parse_hook(choice)
    bootstrap = opening_bootstrap()
    state = {
        'session_id': session_id,
        'time': bootstrap.get('time', '待确认'),
        'location': bootstrap.get('location', '待根据开局建立'),
        'main_event': bootstrap.get('main_event', f'开局：{title}。'),
        'scene_core': detail or bootstrap.get('scene_core', '开局已落定，等待进一步展开。'),
        'scene_entities': [],
        'onstage_npcs': [],
        'relevant_npcs': [],
        'immediate_goal': bootstrap.get('immediate_goal', '先应对当前开局局势，再决定第一步行动。'),
        'immediate_risks': [],
        'carryover_clues': [],
        'opening_mode': 'resolved',
        'opening_resolved': True,
        'opening_started': False,
        'opening_choice': choice,
    }
    save_state(session_id, state)
    return state
