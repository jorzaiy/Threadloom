#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import player_profile


def test_normalize_preserves_canonical_top_level_fields():
    profile = {
        'name': '陆小环',
        'courtesyName': '小环',
        'character': {'name': '不应覆盖'},
    }

    normalized = player_profile.normalize_player_profile(profile)

    assert normalized['name'] == '陆小环'
    assert normalized['courtesyName'] == '小环'
    assert normalized['character']['name'] == '不应覆盖'


def test_normalize_lifts_character_fields_without_dropping_source_data():
    profile = {
        'character': {
            'name': '陆小环',
            'age': 18,
            'gender': '女',
            'birthday': '二月十八',
            'height': '170cm',
        },
        'appearance': {'hair': '乌黑长发'},
    }

    normalized = player_profile.normalize_player_profile(profile)

    assert normalized['name'] == '陆小环'
    assert normalized['courtesyName'] == '陆小环'
    assert normalized['age'] == 18
    assert normalized['gender'] == '女'
    assert normalized['birthday'] == '二月十八'
    assert normalized['height'] == '170cm'
    assert normalized['character']['name'] == '陆小环'
    assert normalized['appearance'] == {'hair': '乌黑长发'}


def test_normalize_supports_chinese_field_aliases():
    profile = {
        '名字': '陆小环',
        '常用称呼': '小环',
        '性别': '女',
        '年龄': '19',
        '生辰': '二月十八',
        '身量': '170cm',
        '出身': '神都',
        '身份': '异人 / 玩家',
    }

    normalized = player_profile.normalize_player_profile(profile)

    assert normalized['name'] == '陆小环'
    assert normalized['courtesyName'] == '小环'
    assert normalized['gender'] == '女'
    assert normalized['age'] == '19'
    assert normalized['birthday'] == '二月十八'
    assert normalized['height'] == '170cm'
    assert normalized['origin'] == '神都'
    assert normalized['status'] == '异人 / 玩家'


def test_normalize_keeps_blank_canonical_field_from_blocking_alias():
    profile = {
        'name': '   ',
        'character': {'name': '陆小环'},
    }

    normalized = player_profile.normalize_player_profile(profile)

    assert normalized['name'] == '陆小环'
    assert normalized['courtesyName'] == '陆小环'


def test_effective_profile_normalizes_after_merge(monkeypatch):
    monkeypatch.setattr(player_profile, 'base_player_profile_path', lambda: Path('/missing/base.json'))
    monkeypatch.setattr(player_profile, 'character_player_profile_override_path', lambda: Path('/missing/override.json'))
    monkeypatch.setattr(player_profile, '_read_json', lambda path: {'character': {'name': '陆小环'}} if 'base' in str(path) else {'昵称': '小环'})

    profile = player_profile.load_effective_player_profile()

    assert profile['name'] == '陆小环'
    assert profile['courtesyName'] == '小环'
