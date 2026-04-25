#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'backend'))

from keeper_contract import keeper_contract_summary, unknown_keeper_state_fields


class KeeperContractTests(unittest.TestCase):
    def test_contract_layers_are_explicit(self):
        summary = keeper_contract_summary()

        self.assertEqual(summary['scene_core'], ['time', 'location', 'main_event', 'immediate_goal'])
        self.assertIn('named_character', summary['entity_types'])
        self.assertIn('descriptive_character', summary['entity_types'])
        self.assertIn('collective_group', summary['entity_types'])
        self.assertIn('risk', summary['signal_types'])
        self.assertIn('public', summary['object_visibility'])

    def test_unknown_keeper_state_fields(self):
        unknown = unknown_keeper_state_fields({
            'time': '上午',
            'location': '茶摊',
            'main_event': '主角观察茶摊',
            'scene_core': 'legacy field',
            'card_specific_magic': True,
        })

        self.assertEqual(unknown, ['card_specific_magic', 'scene_core'])


if __name__ == '__main__':
    unittest.main()
