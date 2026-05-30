"""Tests for locked-important-NPC -> actor promotion (e23032 backlog #5 / 石根).

In no-LLM (unified) mode the heuristic fallback only created actors for
alias/descriptive names; a bare proper/given name like 石根 was rejected by the
name-pattern gate (in both _fallback_actor_candidates and _valid_actor_candidate)
even though he was a locked, present important_npc for many turns -> he never
got an actor slot, so the keeper could not attach personality hooks or a
relationship_to_protagonist. A locked important_npc is now promoted (trusted),
bypassing the name-pattern gate but keeping junk/protagonist filtering.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from actor_registry import _fallback_actor_candidates, update_actor_registry  # noqa: E402


def _state(important):
    return {
        'actors': {'protagonist': {'actor_id': 'protagonist', 'kind': 'protagonist', 'name': '主角', 'aliases': ['你', '主角'], 'created_turn': 1}},
        'actor_context_index': {'active_actor_ids': ['protagonist']},
        'important_npcs': important,
        'scene_entities': [],
    }


class LockedImportantNpcPromotionTests(unittest.TestCase):
    def test_locked_present_proper_name_promoted_to_actor(self):
        important = [{'primary_label': '石根', 'locked': True, 'present_now': True, 'role_label': '同乘骡车，低声告知补给点'}]
        cands = {c['name']: c for c in _fallback_actor_candidates(_state(important), recent_text='石根 低声说')}
        self.assertIn('石根', cands)
        self.assertTrue(cands['石根']['trusted'])
        self.assertEqual(cands['石根']['identity'], '相关场景人物')  # neutral, not the situational role_label
        out = update_actor_registry(_state(important), narrator_reply='石根低声告知补给点。', turn_number=5, recent_pairs=[], use_llm=False)
        npcs = [a for a in out['actors'].values() if a.get('name') == '石根']
        self.assertEqual(len(npcs), 1)
        self.assertEqual(npcs[0]['kind'], 'npc')
        self.assertEqual(npcs[0]['personality'], '')   # slot exists; keeper fills it on later turns

    def test_unlocked_proper_name_not_promoted(self):
        important = [{'primary_label': '王五', 'locked': False, 'present_now': True, 'role_label': 'x'}]
        cands = {c['name'] for c in _fallback_actor_candidates(_state(important), recent_text='王五 说话')}
        self.assertNotIn('王五', cands)

    def test_absent_unmentioned_locked_npc_not_promoted(self):
        important = [{'primary_label': '李铁', 'locked': True, 'present_now': False, 'role_label': 'x'}]
        cands = {c['name'] for c in _fallback_actor_candidates(_state(important), recent_text='无关文本')}
        self.assertNotIn('李铁', cands)

    def test_recently_mentioned_locked_npc_promoted_even_if_not_present(self):
        important = [{'primary_label': '赵九', 'locked': True, 'present_now': False, 'role_label': 'x'}]
        cands = {c['name'] for c in _fallback_actor_candidates(_state(important), recent_text='赵九 在远处喊了一声')}
        self.assertIn('赵九', cands)


if __name__ == '__main__':
    unittest.main()
