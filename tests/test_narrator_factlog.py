"""Step 2: narrator reads the fact-log projection as an authoritative cast block.

Verifies the new 【人物档案·权威】 block: merged names (短工=桥上探头男人 shown as
one), locked persona, and the knowledge-boundary whitelist (absent NPC = knows
nothing hidden). Also that it injects into the narrator system prompt and that an
empty/absent fact-log view falls back silently (no block)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend.narrator_input import build_narrator_input, _format_factlog_cast  # noqa: E402

VIEW = {
    'important_npcs': [
        {'primary_label': '桥上探头男人', 'present_now': True, 'inactive_turns': 0},
        {'primary_label': '灰衣青年修士', 'present_now': False, 'inactive_turns': 3},
    ],
    'entity_persona': {'灰衣青年修士': '谨慎试探，护着石板'},
    'entity_aliases': {'桥上探头男人': ['短工', '桥上那人'], '灰衣青年修士': ['灰衣青年']},
    'knowledge_boundary': {'桥上探头男人': ['主角在捞东西']},
    'entity_relationship': {'灰衣青年修士': '信任'},
    'entity_relationship_history': {'灰衣青年修士': [{'turn': 5, 'label': '戒备', 'evidence': '初见戒备'},
                                                  {'turn': 9, 'label': '信任', 'evidence': '主角救了他'}]},
}


class FactlogCastTests(unittest.TestCase):
    def test_cast_merges_name_and_shows_persona_and_known(self):
        text = _format_factlog_cast(VIEW)
        self.assertIn('【人物档案·权威】', text)
        self.assertIn('桥上探头男人（别称：短工 / 桥上那人）', text)   # split names shown as one
        self.assertIn('谨慎试探', text)                              # locked persona
        self.assertIn('主角在捞东西', text)                          # whitelisted knowledge

    def test_cast_shows_dynamic_relationship(self):
        text = _format_factlog_cast(VIEW)
        self.assertIn('对主角=信任（主角救了他）', text)

    def test_unknown_npc_marked_knows_nothing(self):
        text = _format_factlog_cast(VIEW)
        line = next(l for l in text.splitlines() if l.startswith('- 灰衣青年修士'))
        self.assertIn('对主角隐藏身份与私密信息一无所知', line)

    def test_empty_view_no_block(self):
        self.assertEqual(_format_factlog_cast(None), '')
        self.assertEqual(_format_factlog_cast({'important_npcs': []}), '')

    def test_build_narrator_input_injects_cast(self):
        system_prompt, _ = build_narrator_input({'scene_facts': {}, 'factlog': VIEW}, '测试输入')
        self.assertIn('【人物档案·权威】', system_prompt)
        self.assertIn('桥上探头男人（别称：短工 / 桥上那人）', system_prompt)

    def test_build_narrator_input_without_factlog_falls_back(self):
        system_prompt, _ = build_narrator_input({'scene_facts': {}}, '测试输入')
        self.assertNotIn('【人物档案·权威】', system_prompt)


if __name__ == '__main__':
    unittest.main()
