"""Tests for the V2 read path (backend/fact_retrieval.py).

Covers the properties long-tail recall actually rests on, as opposed to "a query
returns something":

- **term weighting**: a rare name beats filler that overlaps the query more. This
  is the whole reason BM25 replaces the selector's bigram *set overlap* — a set
  intersection has no term weights, so 玉简 (seen once) counts exactly as much as
  在路 (seen every turn);
- **same person, other name**: a late alias merges two entities, and the old
  surface still retrieves the merged entity's earlier facts (folded through
  `canon_eid`, without rewriting the append-only log);
- **on-stage pull**: whoever is on stage right now brings their durable facts
  (knowledge / relationship) even when the query says nothing about them and the
  facts are 40 turns old — neither recency nor wording would surface those;
- **budget + traceability**: hits are capped by count and chars, and every recalled
  line carries its `span` back to the turn that produced it;
- **corrections**: a superseding fact retires the line it replaces.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend.fact_log import FactLog  # noqa: E402
from backend.fact_retrieval import retrieve  # noqa: E402


def _turn(loc, event, onstage, **extra):
    state = {'location': loc, 'main_event': event, 'onstage_npcs': list(onstage)}
    state.update(extra)
    return state


def _lane_rank(hits, fact_id, lane):
    for hit in hits:
        if hit['fact_id'] == fact_id:
            return hit['lanes'].get(lane)
    return None


def _texts(hits):
    return [hit['text'] for hit in hits]


class TermWeightingTests(unittest.TestCase):
    """The rare-word case the bigram baseline gets wrong."""

    def setUp(self):
        self.log = FactLog()
        # Turn 1 holds the long-tail detail, with two terms nothing else uses.
        self.log.commit_turn(_turn('古树下', '灵貂在树根下扒出一枚沁血玉简', ['灵貂']), 1)
        # Five chatty turns that all share "在路上看到" with the query below, so a
        # set-overlap scorer sees more matching bigrams here than in turn 1.
        for t in range(2, 7):
            self.log.commit_turn(_turn('山道', f'他在路上看到几个赶集的人，又走了一段路（第{t}段）', []), t)
        self.facts = self.log.facts

    def test_rare_term_outranks_higher_overlap_filler(self):
        target = next(f['id'] for f in self.facts if '玉简' in str(f.get('text') or ''))
        filler = next(f['id'] for f in self.facts
                      if '第6段' in str(f.get('text') or ''))
        hits = retrieve(self.facts, self.log.resolver.entities,
                        '我记得之前在路上看到的那枚玉简', limit=8)
        target_rank = _lane_rank(hits, target, 'lexical')
        filler_rank = _lane_rank(hits, filler, 'lexical')
        self.assertIsNotNone(target_rank, f'rare-term fact not recalled at all: {_texts(hits)}')
        self.assertEqual(target_rank, 1, f'rare term did not win its lane: {_texts(hits)}')
        if filler_rank is not None:
            self.assertLess(target_rank, filler_rank)

    def test_recall_survives_six_turns_of_distance(self):
        target = next(f['id'] for f in self.facts if '玉简' in str(f.get('text') or ''))
        hits = retrieve(self.facts, self.log.resolver.entities, '那枚玉简呢', limit=3)
        self.assertIn(target, [hit['fact_id'] for hit in hits])

    def test_lexical_lane_is_silent_without_a_query(self):
        hits = retrieve(self.facts, self.log.resolver.entities, '', limit=5)
        self.assertTrue(hits)
        self.assertTrue(all('lexical' not in hit['lanes'] for hit in hits))
        # …and what is left is the near window, newest first.
        self.assertEqual(hits[0]['turn'], 6)


class AliasRecallTests(unittest.TestCase):
    """A late alias merges two entities; the old surface must still retrieve."""

    def test_alias_retrieves_the_merged_entity_earlier_facts(self):
        log = FactLog()
        log.commit_turn(_turn('石桥', '桥上探头男人打量了主角一眼', ['桥上探头男人']), 1)
        for t in range(2, 5):
            log.commit_turn(_turn('镇口', f'主角在镇口买了碗面（第{t}轮）', ['面摊老板']), t)
        # Turn 5: the keeper finally tags 短工 as the same person.
        log.commit_turn(_turn('码头', '短工蹲在码头卸货', ['短工'],
                              scene_entities=[{'primary_label': '短工',
                                               'aliases': ['桥上探头男人']}]), 5)
        hits = log.retrieve('那个短工', limit=8)
        recalled = [hit for hit in hits if '桥上探头男人' in hit['labels'] or '短工' in hit['labels']]
        self.assertTrue(recalled, f'alias pulled nothing: {_texts(hits)}')
        self.assertTrue(any(hit['turn'] == 1 for hit in recalled),
                        f'alias did not reach the pre-merge fact: {[(h["turn"], h["text"]) for h in recalled]}')

    def test_particle_variant_query_still_hits(self):
        log = FactLog()
        log.commit_turn(_turn('石桥', '带短刀的男人挡在桥头', ['带短刀的男人']), 1)
        for t in range(2, 6):
            log.commit_turn(_turn('山道', f'主角赶路（第{t}轮）', []), t)
        hits = log.retrieve('带短刀男人', limit=5)          # differs only by 的
        self.assertTrue(any('带短刀的男人' in hit['labels'] for hit in hits), _texts(hits))


class OnstagePullTests(unittest.TestCase):
    """On-stage NPCs bring their durable facts, however old and however unrelated
    the query."""

    def setUp(self):
        self.log = FactLog()
        self.log.commit_turn(_turn('茶馆', '沈昭盘问主角的来路', ['沈昭'],
                                   knowledge_scope={'npc_local': {'沈昭': {'learned': ['主角是散修']}}},
                                   actors={'a1': {'name': '沈昭', 'personality': '话少',
                                                  'relationship_to_protagonist': {'label': '戒备',
                                                                                  'evidence': '初见即盘问'}}}), 1)
        for t in range(2, 9):
            self.log.commit_turn(_turn('山道', f'主角独自赶路（第{t}轮）', []), t)
        self.log.commit_turn(_turn('渡口', '沈昭又出现在渡口', ['沈昭']), 9)

    def test_old_knowledge_of_an_onstage_npc_is_recalled_for_an_unrelated_query(self):
        hits = self.log.retrieve('今天天气怎么样', limit=8)
        knows = [hit for hit in hits if hit['predicate'] == 'knows']
        self.assertTrue(knows, f'on-stage NPC knowledge not pulled: {_texts(hits)}')
        self.assertEqual(knows[0]['turn'], 1)
        self.assertIn('主角是散修', knows[0]['text'])

    def test_presence_rows_do_not_crowd_out_durable_facts(self):
        hits = self.log.retrieve('', limit=8)
        entity_lane = [hit for hit in hits if 'entity' in hit['lanes']]
        self.assertTrue(any(hit['predicate'] in ('knows', 'relation') for hit in entity_lane),
                        f'entity lane returned only presence rows: '
                        f'{[(h["predicate"], h["text"]) for h in entity_lane]}')

    def test_relationship_line_is_retrievable_with_its_evidence(self):
        hits = self.log.retrieve('沈昭', limit=8)
        rel = [hit for hit in hits if hit['predicate'] == 'relation']
        self.assertTrue(rel, _texts(hits))
        self.assertIn('戒备', rel[0]['text'])
        self.assertIn('初见即盘问', rel[0]['text'])


class BudgetAndTraceTests(unittest.TestCase):
    def setUp(self):
        self.log = FactLog()
        for t in range(1, 13):
            self.log.commit_turn(_turn('长街', f'第{t}轮：主角在长街上遇到一些事', ['货郎']), t)

    def test_count_budget_is_respected(self):
        self.assertEqual(len(self.log.retrieve('长街', limit=3)), 3)
        self.assertEqual(len(self.log.retrieve('长街', limit=0)), 0)

    def test_char_budget_truncates_but_always_yields_one_hit(self):
        hits = self.log.retrieve('长街', limit=8, max_chars=1)
        self.assertEqual(len(hits), 1)
        roomy = self.log.retrieve('长街', limit=8, max_chars=10_000)
        self.assertGreater(len(roomy), 1)

    def test_every_beat_hit_carries_a_span_back_to_its_turn(self):
        hits = self.log.retrieve('长街', limit=8)
        beats = [hit for hit in hits if hit['predicate'] == 'observation']
        self.assertTrue(beats)
        for hit in beats:
            self.assertIsInstance(hit['span'], dict)
            self.assertEqual(hit['span'].get('turn_id'), f'turn-{hit["turn"]:04d}')

    def test_hits_are_ordered_by_fused_score(self):
        hits = self.log.retrieve('长街', limit=8)
        scores = [hit['score'] for hit in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))


class CorrectionAndEdgeTests(unittest.TestCase):
    def test_superseded_fact_is_not_recalled(self):
        facts = [
            {'id': 1, 'turn': 1, 'predicate': 'observation', 'beat': True,
             'text': '主角拿到的是青玉符', 'entities': [], 'span': {'turn_id': 'turn-0001'}},
            {'id': 2, 'turn': 2, 'predicate': 'observation', 'beat': True,
             'text': '主角拿到的其实是青玉简', 'entities': [], 'span': {'turn_id': 'turn-0002'},
             'supersedes': 1},
        ]
        hits = retrieve(facts, {}, '青玉', limit=5)
        self.assertEqual([hit['fact_id'] for hit in hits], [2])

    def test_empty_inputs_are_not_an_error(self):
        self.assertEqual(retrieve([], {}, '任何'), [])
        self.assertEqual(retrieve(None, {}, ''), [])
        log = FactLog()
        self.assertEqual(log.retrieve('沈昭'), [])

    def test_malformed_facts_are_skipped(self):
        facts = [None, 'nonsense',
                 {'id': 7, 'turn': 3, 'predicate': 'observation', 'beat': True,
                  'text': '风雪封了山口', 'entities': []}]
        hits = retrieve(facts, {}, '山口', limit=5)
        self.assertEqual([hit['fact_id'] for hit in hits], [7])

    def test_lane_weights_are_tunable(self):
        log = FactLog()
        log.commit_turn(_turn('古井', '井底有半截断碑', []), 1)
        for t in range(2, 8):
            log.commit_turn(_turn('山道', f'主角赶路（第{t}轮）', []), t)
        lexical_only = log.retrieve('断碑', limit=1, weights={'recency': 0.0, 'entity': 0.0})
        self.assertIn('断碑', lexical_only[0]['text'])


class LaneBalanceTests(unittest.TestCase):
    """The three defects a replay against the live session exposed. Each one let
    near-window noise bury the actual answer (MRR 0.26 vs the bigram baseline's
    0.87 before the fixes, 0.84 after), and none of them showed up in a fixture
    small enough to eyeball — hence these are pinned."""

    def _log(self):
        log = FactLog()
        log.commit_turn(_turn('客栈', '陆小环探出少年经脉有被强行抽离灵力的旧伤', ['阿砚']), 1)
        # Eight chatty turns: short presence rows plus a `knows` row every turn, all
        # newer than the answer.
        for t in range(2, 10):
            log.commit_turn(_turn('山道', f'两人冒雨赶路（第{t}轮）', ['阿砚'],
                                  knowledge_scope={'npc_local': {'阿砚': {'learned': [f'第{t}轮路上听来的闲话']}}}), t)
        return log

    def test_lexical_answer_outranks_near_window_noise(self):
        # Equal lane weights tie a recency rank-1 with a lexical rank-1, and the
        # turn-descending tie-break then hands the head to whatever just happened.
        hits = self._log().retrieve('少年的旧伤', limit=3)
        self.assertIn('旧伤', hits[0]['text'], _texts(hits))

    def test_presence_rows_stay_out_of_the_lexical_lane(self):
        # They are ~10 tokens of pure label+location, so BM25 length normalisation
        # ranked them above the prose that answers the query.
        hits = self._log().retrieve('阿砚在山道上', limit=20)
        lexical = [hit for hit in hits if 'lexical' in hit['lanes']]
        self.assertTrue(lexical)
        self.assertTrue(all(hit['predicate'] != 'present' for hit in lexical),
                        [(h['predicate'], h['text']) for h in lexical])

    def test_entity_lane_keeps_room_for_scene_beats(self):
        # Strict durable-first ordering let eight `knows` rows eat the per-seed
        # quota, so the entity's own beats never entered the lane.
        lane = [hit for hit in self._log().retrieve('阿砚', limit=20) if 'entity' in hit['lanes']]
        self.assertTrue(any(hit['predicate'] == 'knows' for hit in lane))
        self.assertTrue(any(hit['predicate'] == 'observation' for hit in lane),
                        [(h['predicate'], h['text']) for h in lane])


if __name__ == '__main__':
    unittest.main()
