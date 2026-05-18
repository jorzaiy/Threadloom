#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import actor_registry


class ActorRegistryTests(unittest.TestCase):
    def test_descriptive_counter_role_does_not_duplicate_innkeeper(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '中年妇人',
                    'aliases': [],
                    'appearance': '',
                    'identity': '客栈掌柜',
                    'created_turn': 14,
                }
            },
            'scene_entities': [],
        }
        candidate = {
            'name': '柜台后的妇人',
            'aliases': [],
            'appearance': '',
            'identity': '福来客栈柜台后负责拨算盘的妇人。',
        }

        self.assertTrue(actor_registry._candidate_overlaps_existing_actor(candidate, state['actors'], state))

    def test_different_descriptive_role_can_still_be_new_actor(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '中年妇人',
                    'aliases': [],
                    'appearance': '',
                    'identity': '客栈掌柜',
                    'created_turn': 14,
                }
            },
            'scene_entities': [],
        }
        candidate = {
            'name': '门口的少年',
            'aliases': [],
            'appearance': '站在客栈门口，肩上搭着汗巾',
            'identity': '跑堂伙计',
        }

        self.assertFalse(actor_registry._candidate_overlaps_existing_actor(candidate, state['actors'], state))

    def test_room_descriptor_does_not_duplicate_same_neighboring_guest(self):
        state = {
            'actors': {
                'npc_005': {
                    'actor_id': 'npc_005',
                    'kind': 'npc',
                    'name': '隔壁的年轻人',
                    'aliases': [],
                    'appearance': '',
                    'identity': '住在主角隔壁的年轻修士',
                    'created_turn': 21,
                }
            },
            'scene_entities': [],
        }
        candidate = {
            'name': '二楼倒数第二间屋的客人',
            'aliases': [],
            'appearance': '',
            'identity': '客栈二楼倒数第二间屋内的年轻修士。',
        }

        self.assertTrue(actor_registry._candidate_overlaps_existing_actor(candidate, state['actors'], state))

    def test_generic_cultivator_role_alone_does_not_dedupe_distinct_actors(self):
        state = {
            'actors': {
                'npc_005': {
                    'actor_id': 'npc_005',
                    'kind': 'npc',
                    'name': '隔壁的年轻人',
                    'aliases': [],
                    'appearance': '',
                    'identity': '住在主角隔壁的年轻修士',
                    'created_turn': 21,
                }
            },
            'scene_entities': [],
        }
        candidate = {
            'name': '临窗的黑袍修士',
            'aliases': [],
            'appearance': '坐在窗边，穿黑袍',
            'identity': '茶肆里独坐的修士。',
        }

        self.assertFalse(actor_registry._candidate_overlaps_existing_actor(candidate, state['actors'], state))

    def test_generic_guest_role_alone_does_not_dedupe_distinct_rooms(self):
        state = {
            'actors': {
                'npc_005': {
                    'actor_id': 'npc_005',
                    'kind': 'npc',
                    'name': '二楼倒数第二间屋的客人',
                    'aliases': [],
                    'appearance': '',
                    'identity': '客栈二楼倒数第二间屋内的客人',
                    'created_turn': 21,
                }
            },
            'scene_entities': [],
        }
        candidate = {
            'name': '三楼东厢的客人',
            'aliases': [],
            'appearance': '',
            'identity': '三楼东厢房内新住下的客人。',
        }

        self.assertFalse(actor_registry._candidate_overlaps_existing_actor(candidate, state['actors'], state))


if __name__ == '__main__':
    unittest.main()
