"""Tests for the V2 fact-log core (backend/fact_log.py).

Covers the architectural guarantees the design rests on:
- entity resolution merges particle variants but NOT synonyms (conservative, biased
  to under-merge because over-merge is hard to undo in an append-only log);
- per-entity `last_event` is a query, so an absent NPC keeps its own anchor — the
  P1 clobber cannot be expressed;
- rollback = truncate + re-fold;
- legacy `state.json` can be seeded without an LLM.

The final test replays the real e23032 session if its data is present (skips otherwise).
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend.fact_log import FactLog, Resolver  # noqa: E402

E23032 = ROOT / 'runtime-data/default-user/characters/九幽大陆/sessions/九幽大陆-20260520-e23032'


def _turn(loc, event, onstage):
    return {'location': loc, 'main_event': event, 'onstage_npcs': onstage}


class ResolverTests(unittest.TestCase):
    def test_merges_grammatical_particle_variants(self):
        r = Resolver()
        a = r.resolve('带短刀的男人')
        b = r.resolve('带短刀男人')          # differs only by 的
        self.assertEqual(a, b)
        self.assertEqual(r.entities[a].canonical, '带短刀的男人')   # first-seen wins
        self.assertIn('带短刀男人', r.entities[a].aliases)

    def test_does_not_merge_synonyms(self):
        r = Resolver()
        x = r.resolve('灰衣年轻人')
        y = r.resolve('灰布衫年轻人')        # synonym, not a particle variant
        self.assertNotEqual(x, y)           # conservative: left for the auditor

    def test_distinct_names_get_distinct_ids(self):
        r = Resolver()
        self.assertNotEqual(r.resolve('石根'), r.resolve('沈青'))


class ProjectionTests(unittest.TestCase):
    def test_absent_npc_keeps_own_last_event(self):
        """The P1 invariant, structurally: 张麻子 is absent at the latest turn and
        must keep his own t261 event, not inherit the t276 scene."""
        log = FactLog()
        log.commit_turn(_turn('北门', '张麻子在北门盘问路引。', ['张麻子']), 261)
        log.commit_turn(_turn('东巷', '触手从门缝探出拦路。', ['灵貂']), 276)
        view = log.project()

        le = view['entity_last_event']
        self.assertEqual(le['张麻子'], '张麻子在北门盘问路引。')
        self.assertEqual(le['灵貂'], '触手从门缝探出拦路。')
        self.assertEqual(view['onstage_npcs'], ['灵貂'])
        # distinct per entity — the thing the old pipeline collapsed to one value
        self.assertEqual(len({v for v in le.values()}), 2)

    def test_present_now_and_inactivity(self):
        log = FactLog()
        log.commit_turn(_turn('北门', '盘问。', ['张麻子']), 261)
        log.commit_turn(_turn('东巷', '触手拦路。', ['灵貂']), 276)
        by = {n['primary_label']: n for n in log.project()['important_npcs']}
        self.assertTrue(by['灵貂']['present_now'])
        self.assertFalse(by['张麻子']['present_now'])
        self.assertEqual(by['张麻子']['inactive_turns'], 15)

    def test_truncate_after_rolls_back(self):
        log = FactLog()
        log.commit_turn(_turn('北门', '盘问。', ['张麻子']), 261)
        log.commit_turn(_turn('东巷', '触手拦路。', ['灵貂']), 276)
        log.truncate_after(261)               # regenerate/rollback to t261
        view = log.project()
        self.assertEqual(view['onstage_npcs'], ['张麻子'])
        self.assertNotIn('灵貂', view['entity_last_event'])

    def test_seed_from_state_preserves_absent_npcs(self):
        state = {'important_npcs': [
            {'primary_label': '张麻子', 'aliases': ['张叔'], 'present_now': False,
             'inactive_turns': 5, 'last_location': '北门',
             'last_main_event': '张麻子在北门盘问路引。'},
            {'primary_label': '灵貂', 'present_now': True, 'inactive_turns': 0,
             'last_location': '东巷', 'last_main_event': '触手拦路。'},
        ]}
        log = FactLog()
        log.seed_from_state(state, as_of_turn=276)
        view = log.project()
        labels = {n['primary_label'] for n in view['important_npcs']}
        self.assertEqual(labels, {'张麻子', '灵貂'})          # absent NPC preserved
        self.assertEqual(view['entity_last_event']['张麻子'], '张麻子在北门盘问路引。')
        self.assertEqual(view['onstage_npcs'], ['灵貂'])

    def test_roundtrip_save_load(self):
        import tempfile
        log = FactLog()
        log.commit_turn(_turn('东巷', '触手拦路。', ['灵貂']), 276)
        with tempfile.TemporaryDirectory() as d:
            log.save(d)
            reloaded = FactLog.load(d)
        self.assertEqual(reloaded.project(), log.project())


@unittest.skipUnless(E23032.exists(), 'e23032 session data not present')
class E23032ReplayTests(unittest.TestCase):
    def test_replay_reproduces_onstage_and_distinct_events(self):
        import glob
        import re
        log = FactLog()
        for tf in sorted(glob.glob(str(E23032 / 'turn-trace' / 'turn-*.json'))):
            d = json.load(open(tf, encoding='utf-8'))
            st = d.get('post_turn', {}).get('state', {})
            if not isinstance(st, dict):
                continue
            m = re.search(r'(\d+)', d.get('turn_id', '0'))
            log.commit_turn(st, int(m.group(1)) if m else 0)

        view = log.project()
        state = json.load(open(E23032 / 'memory' / 'state.json', encoding='utf-8'))

        # projection reproduces the latest-turn onstage set
        self.assertEqual(set(view['onstage_npcs']), set(state.get('onstage_npcs', []) or []))
        # V2 projection gives DISTINCT per-entity events (the property the old clobber
        # destroyed). e23032's live state.json no longer shows the P1 symptom now that
        # the fix shipped, so we assert only the V2 invariant, not the old breakage.
        self.assertGreater(len(set(view['entity_last_event'].values())), 1)


class PersonaAndKnowledgeTests(unittest.TestCase):
    """The 'foundation': canonical entity carries a stable persona + a knowledge
    boundary, so 'NPC turns into someone else' and 'knows what it shouldn't' can't
    happen at the entity layer."""

    def test_persona_attached_to_canonical_survives_alias_variant(self):
        state = {
            'location': '集市', 'main_event': '带短刀男人盯着摊位。',
            'onstage_npcs': ['带短刀男人'],                       # particle variant
            'actors': {'a1': {'kind': 'npc', 'name': '带短刀的男人',
                              'personality': '沉默警惕', 'identity': '佣兵'}},
        }
        log = FactLog()
        log.commit_turn(state, 1)
        view = log.project()
        # variant unified onto the canonical entity; persona is reachable
        self.assertEqual(view['entity_persona'].get('带短刀的男人'), '沉默警惕')
        self.assertIn('带短刀的男人', view['onstage_npcs'])

    def test_persona_is_locked_after_first_established(self):
        s1 = {'location': 'x', 'main_event': 'e1', 'onstage_npcs': ['沈青'],
              'actors': {'a': {'kind': 'npc', 'name': '沈青', 'personality': '紧张拘谨'}}}
        s2 = {'location': 'x', 'main_event': 'e2', 'onstage_npcs': ['沈青'],
              'actors': {'a': {'kind': 'npc', 'name': '沈青', 'personality': '暴躁好斗'}}}  # keeper drift
        log = FactLog()
        log.commit_turn(s1, 1)
        log.commit_turn(s2, 2)
        self.assertEqual(log.project()['entity_persona']['沈青'], '紧张拘谨')  # not overwritten

    def test_alias_unification_merges_knowledge(self):
        state = {
            'location': 'x', 'main_event': 'e', 'onstage_npcs': [],
            'actors': {'a': {'kind': 'npc', 'name': '面摊老板', 'aliases': ['面摊摊主', '摊主']}},
            'knowledge_scope': {'npc_local': {
                '面摊摊主': {'learned': ['陆小环带灵貂吃面']},
                '摊主': {'learned': ['陆小环要去玄幽城']},
            }},
        }
        log = FactLog()
        log.commit_turn(state, 1)
        kb = log.project()['knowledge_boundary']
        self.assertIn('面摊老板', kb)                              # unified to canonical
        self.assertEqual(set(kb['面摊老板']), {'陆小环带灵貂吃面', '陆小环要去玄幽城'})
        self.assertNotIn('摊主', kb)                               # no second entity

    def test_knowledge_boundary_is_whitelist_default_unknown(self):
        known = {'location': 'x', 'main_event': 'e', 'onstage_npcs': ['张三'],
                 'actors': {'a': {'kind': 'npc', 'name': '张三'}},
                 'knowledge_scope': {'npc_local': {'张三': {'learned': ['主角是散修']}}}}
        log = FactLog()
        log.commit_turn(known, 1)
        self.assertEqual(log.project()['knowledge_boundary'].get('张三'), ['主角是散修'])

        # an NPC with no `knows` fact is simply absent -> knows nothing (safe default)
        unknown = {'location': 'x', 'main_event': 'e', 'onstage_npcs': ['李四'],
                   'actors': {'b': {'kind': 'npc', 'name': '李四'}}}
        log2 = FactLog()
        log2.commit_turn(unknown, 1)
        self.assertNotIn('李四', log2.project()['knowledge_boundary'])


if __name__ == '__main__':
    unittest.main()
