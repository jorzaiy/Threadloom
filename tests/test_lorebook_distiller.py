#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

from lorebook_distiller import _build_llm_prompt, _fallback_distill, _normalize_llm  # noqa: E402


def _academy_entry():
    return {
        'id': '1',
        'title': '世界观设定',
        'keywords': ['学院', '特工学院'],
        'alwaysOn': True,
        'priority': 50,
        'entryType': 'world',
        'runtimeScope': 'foundation',
        'content': '''World_Setting:
  era: 现代架空
Organization:
  name: 第七局
Academy:
  name: 鹰巢特工学院
Student_Policy:
  social:
    - 学员之间可以正常交往、交友
    - 学院为男校，不存在恋爱氛围
    - 鼓励学员之间建立战友情谊和团队默契
    - 师生之间保持适当距离，但私下交流不被禁止
''',
    }


def test_fallback_distill_promotes_negative_world_constraints():
    foundation, index = _fallback_distill([_academy_entry()], provider='heuristic')

    foundation_text = json.dumps(foundation, ensure_ascii=False)
    index_text = json.dumps(index, ensure_ascii=False)

    assert '学院为男校，不存在恋爱氛围' in foundation_text
    assert '师生之间保持适当距离' in foundation_text
    assert '学院为男校，不存在恋爱氛围' in index_text


def test_llm_prompt_includes_late_constraints_before_truncation():
    prompt = _build_llm_prompt([_academy_entry()])

    assert '学院为男校，不存在恋爱氛围' in prompt
    assert '师生之间保持适当距离' in prompt


def test_normalize_llm_backfills_constraints_when_model_omits_them():
    payload = {
        'foundation_rules': [
            {
                'title': '世界基础设定',
                'text': '现代架空世界，第七局负责反恐与反间谍任务。',
                'category': 'world',
                'source_entry_ids': ['1'],
            }
        ],
        'situational_lore': [
            {
                'id': 'academy',
                'title': '世界观设定',
                'summary': '鹰巢特工学院隶属第七局训练体系。',
                'keywords': ['学院'],
                'category': 'world',
                'source_entry_ids': ['1'],
            }
        ],
    }

    foundation, index = _normalize_llm(payload, [_academy_entry()])

    assert '学院为男校，不存在恋爱氛围' in json.dumps(foundation, ensure_ascii=False)
    assert '学院为男校，不存在恋爱氛围' in json.dumps(index, ensure_ascii=False)
