#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import opening  # noqa: E402
from character_assets import clear_character_override_root, set_character_override_root  # noqa: E402


def test_single_option_openings_file_is_direct(tmp_path):
    set_character_override_root(tmp_path)
    try:
        (tmp_path / 'openings.json').write_text(
            '{"version":1,"menu_intro":"Direct start.","options":[{"full_text":"Direct start."}]}',
            encoding='utf-8',
        )
        assert opening.opening_hooks() == []
        assert opening.build_opening_reply('开始') == 'Direct start.'
    finally:
        clear_character_override_root()


def test_opening_reply_replaces_sillytavern_char_placeholder(tmp_path):
    set_character_override_root(tmp_path)
    try:
        (tmp_path / 'character-data.json').write_text('{"name":"维克托·奥古斯特"}', encoding='utf-8')
        (tmp_path / 'openings.json').write_text(
            '{"version":1,"mode":"direct","menu_intro":"{{char}} stands ready."}',
            encoding='utf-8',
        )
        assert opening.build_opening_reply('开始') == '维克托·奥古斯特 stands ready.'
    finally:
        clear_character_override_root()
