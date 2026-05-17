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


if __name__ == '__main__':
    unittest.main()
