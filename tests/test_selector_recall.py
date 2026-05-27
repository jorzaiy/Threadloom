#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend.selector import build_selector_decision, event_summary_hits, player_profile_detail_hits


class SelectorRecallTests(unittest.TestCase):
    def test_selector_hits_event_summaries_by_current_actor_and_topic(self):
        decision = build_selector_decision(
            state_json={
                'location': '青岚训练基地训练场器械区',
                'main_event': '教官甲宣布前往战术教室参加观察与记忆测试',
                'onstage_npcs': ['教官甲'],
                'relevant_npcs': [],
                'immediate_risks': ['观察与记忆测试'],
            },
            recent_history=[{'role': 'user', 'content': '继续观察同学训练'}],
            keeper_records={'records': []},
            active_threads=[],
            important_npcs=[{'primary_label': '教官甲', 'role_label': '教官'}],
            onstage=['教官甲'],
            relevant=[],
            lorebook_entries=[],
            system_npc_candidates=[],
            lorebook_npc_candidates=[],
            event_summaries=[{
                'event_id': 'evt_training_001',
                'summary': '教官甲在训练场组织障碍组合，并预告观察与记忆测试。',
                'actors': ['教官甲'],
                'keywords': ['训练场', '观察与记忆测试'],
            }],
            summary_text='',
            summary_chunks=[],
            user_text='靠着树继续看训练',
        )

        self.assertEqual(decision['event_hits'][0]['event_id'], 'evt_training_001')
        self.assertGreaterEqual(decision['event_hits'][0]['score'], 2)

    def test_event_recall_prefers_current_scene_over_stale_same_actor_events(self):
        events = [
            {
                'event_id': 'evt_0002',
                'turn_id': 'turn-0002',
                'summary': '教官甲在器械区组织引体向上，学员刻意拉开与教官的距离。',
                'actors': ['教官甲'],
                'clues': ['学员刻意拉开与教官的距离'],
            },
            {
                'event_id': 'evt_0003',
                'turn_id': 'turn-0003',
                'summary': '主角完成十二个引体向上，教官甲判定勉强达标。',
                'actors': ['教官甲'],
                'clues': ['学员刻意拉开与教官的距离'],
            },
            {
                'event_id': 'evt_0011',
                'turn_id': 'turn-0011',
                'summary': '主角在障碍场观察两米高矮墙，寻找墙顶和墙根鞋印作为借力点。',
                'actors': ['教官甲'],
                'clues': ['左边双杠握把间距比其他宽两寸'],
            },
            {
                'event_id': 'evt_0012',
                'turn_id': 'turn-0012',
                'summary': '主角计算矮墙助跑起跳点，教官甲宣布剩余两分钟时限。',
                'actors': ['教官甲'],
                'clues': ['左边双杠握把间距比其他宽两寸'],
            },
        ]

        hits = event_summary_hits(
            events,
            state_json={
                'location': '青岚训练基地主训练场障碍场矮墙西侧泥地',
                'main_event': '主角准备挑战矮墙并计算助跑距离',
                'onstage_npcs': ['教官甲'],
                'immediate_risks': ['学员刻意拉开与教官的距离'],
                'carryover_signals': [{'type': 'clue', 'text': '学员刻意拉开与教官的距离'}],
            },
            recent_history=[{'role': 'user', 'content': '看着矮墙计算借力的位置和距离'}],
            user_text='准备试着翻过矮墙',
        )

        self.assertEqual([hit['event_id'] for hit in hits[:2]], ['evt_0011', 'evt_0012'])

    def test_event_recall_tie_breaks_to_newer_turn(self):
        events = [
            {'event_id': 'evt_0001', 'turn_id': 'turn-0001', 'summary': '教官甲宣布训练规则。', 'actors': ['教官甲']},
            {'event_id': 'evt_0002', 'turn_id': 'turn-0002', 'summary': '教官甲宣布训练规则。', 'actors': ['教官甲']},
        ]

        hits = event_summary_hits(
            events,
            state_json={'main_event': '教官甲宣布训练规则', 'onstage_npcs': ['教官甲']},
            recent_history=[],
            user_text='继续听训练规则',
        )

        self.assertEqual(hits[0]['event_id'], 'evt_0002')

    def test_event_recall_finds_older_background_origin_event_outside_recent_window(self):
        events = [
            {
                'event_id': f'evt_{idx:04d}',
                'turn_id': f'turn-{idx:04d}',
                'summary': f'无关路人事件 {idx}。',
                'actors': ['路人'],
                'keywords': ['无关'],
            }
            for idx in range(1, 53)
        ]
        events.extend([
            {
                'event_id': 'evt_0053',
                'turn_id': 'turn-0053',
                'summary': '陆小环进入主街药铺买药，年轻男人在药铺附近看见她与灵貂，药铺掌柜在蓝布帘后观察。',
                'actors': ['年轻男人', '药铺掌柜', '灵貂'],
                'keywords': ['药铺掌柜', '药铺老板', '井', '来历', '年轻男人'],
                'clues': ['年轻男人与陆小环在药铺线相遇'],
            },
            {
                'event_id': 'evt_0057',
                'turn_id': 'turn-0057',
                'summary': '年轻男人追出药铺门外向陆小环求助，蓝布帘后的药铺掌柜影子动了一下。',
                'actors': ['年轻男人', '药铺掌柜'],
                'keywords': ['药铺掌柜', '药铺老板', '井', '来历'],
                'clues': ['药铺掌柜与年轻男人求助有关'],
            },
        ])
        events.extend([
            {
                'event_id': f'evt_{idx:04d}',
                'turn_id': f'turn-{idx:04d}',
                'summary': f'年轻男人在客栈二楼房间恢复，灵貂守着泥壳，近期动作 {idx}。',
                'actors': ['年轻男人', '灵貂'],
                'keywords': ['年轻男人', '灵貂', '泥壳'],
            }
            for idx in range(64, 84)
        ])

        hits = event_summary_hits(
            events,
            state_json={
                'location': '人界，青石镇，客栈二楼房间',
                'main_event': '陆小环询问年轻男人药铺掌柜的来历。',
                'onstage_npcs': ['年轻男人', '灵貂'],
                'relevant_npcs': ['药铺掌柜'],
                'carryover_signals': [{'type': 'clue', 'text': '药铺掌柜来历待说明'}],
            },
            recent_history=[{'role': 'assistant', 'content': '年轻男人刚恢复，陆小环坐下询问药铺掌柜是什么来历。'}],
            user_text='我对他不感兴趣，但是我想弄清楚井里的东西是什么，听说药铺老板对那口井很在意。',
        )

        hit_ids = [hit['event_id'] for hit in hits]
        self.assertIn('evt_0053', hit_ids)
        self.assertTrue(hit_ids.index('evt_0053') < 3)
        self.assertNotIn('evt_0001', hit_ids)

    def test_event_recall_skips_carryover_only_stale_clue_hits_after_scene_shift(self):
        events = [
            {
                'event_id': 'evt_0004',
                'turn_id': 'turn-0004',
                'summary': '教官甲在训练场记录体检日单独跟进。',
                'actors': ['教官甲'],
                'clues': ["教官甲记录'体检日，单独跟进'。"],
            },
            {
                'event_id': 'evt_0014',
                'turn_id': 'turn-0014',
                'summary': '安全组人员在图书馆指出系统记录与主角说法不符。',
                'actors': ['拿平板的人', '管理员'],
                'clues': [],
            },
        ]

        hits = event_summary_hits(
            events,
            state_json={
                'location': '青岚训练基地图书馆公共终端区',
                'main_event': '安全组人员要求主角前往训练部安全组谈话',
                'onstage_npcs': ['拿平板的人', '管理员'],
                'relevant_npcs': [],
                'carryover_signals': [{'type': 'clue', 'text': "教官甲记录'体检日，单独跟进'"}],
            },
            recent_history=[{'role': 'user', 'content': '我在查资料'}],
            user_text='跟着安全组人员走',
        )

        self.assertEqual([hit['event_id'] for hit in hits], ['evt_0014'])

    def test_event_recall_skips_sensitive_actor_only_hits_on_quiet_turn(self):
        events = [{
            'event_id': 'evt_0008',
            'turn_id': 'turn-0008',
            'summary': '教官甲注意到主角旧伤导致呼吸困难，后续存在暴露风险。',
            'actors': ['教官甲'],
            'clues': ['旧伤导致呼吸困难，存在暴露风险'],
        }]

        quiet_hits = event_summary_hits(
            events,
            state_json={
                'location': '青岚训练基地食堂',
                'main_event': '主角坐在角落吃午饭',
                'onstage_npcs': ['教官甲'],
            },
            recent_history=[{'role': 'assistant', 'content': '教官甲之前巡视过训练场。'}],
            user_text='低头吃完米饭和菜',
        )
        direct_hits = event_summary_hits(
            events,
            state_json={
                'location': '青岚训练基地宿舍',
                'main_event': '主角发现旧伤牵扯得呼吸困难',
                'onstage_npcs': [],
            },
            recent_history=[],
            user_text='旧伤牵扯得呼吸困难',
        )

        self.assertEqual(quiet_hits, [])
        self.assertEqual(direct_hits[0]['event_id'], 'evt_0008')

    def test_selector_targets_locked_important_npc_from_selected_event(self):
        decision = build_selector_decision(
            state_json={
                'location': '青岚训练基地训练楼靶场',
                'main_event': '主角查看射击成绩',
                'onstage_npcs': [],
                'relevant_npcs': [],
            },
            recent_history=[{'role': 'assistant', 'content': '电子屏显示成绩逐轮提升。'}],
            keeper_records={'records': []},
            active_threads=[],
            important_npcs=[{'primary_label': '教官甲', 'role_label': '教官', 'locked': True}],
            onstage=[],
            relevant=[],
            lorebook_entries=[],
            system_npc_candidates=[],
            lorebook_npc_candidates=[],
            event_summaries=[{
                'event_id': 'evt_0025',
                'turn_id': 'turn-0025',
                'summary': '主角查看成绩时，教官甲折返回来称赞其成绩并提醒下午理论课。',
                'actors': ['教官甲'],
                'keywords': ['射击成绩', '理论课'],
            }],
            summary_text='',
            summary_chunks=[],
            user_text='看自己的射击成绩',
        )

        self.assertIn('教官甲', decision['npc_profile_targets'])
        self.assertEqual(decision['event_hits'][0]['event_id'], 'evt_0025')

    def test_common_mundane_object_does_not_trigger_broad_old_event_recall(self):
        decision = build_selector_decision(
            state_json={
                'location': '客栈后院',
                'main_event': '主角坐在后院休息。',
                'onstage_npcs': [],
                'relevant_npcs': [],
                'tracked_objects': [],
            },
            recent_history=[{'role': 'assistant', 'content': '主角在后院坐下。'}],
            keeper_records={'records': []},
            active_threads=[],
            important_npcs=[],
            onstage=[],
            relevant=[],
            lorebook_entries=[],
            system_npc_candidates=[],
            lorebook_npc_candidates=[],
            event_summaries=[
                {'event_id': 'evt_0001', 'turn_id': 'turn-0001', 'summary': '主角在集市买过一张饼。', 'keywords': ['饼', '集市']},
                {'event_id': 'evt_0002', 'turn_id': 'turn-0002', 'summary': '路边摊有人吃饼闲聊。', 'keywords': ['饼', '路边摊']},
            ],
            summary_text='',
            summary_chunks=[
                {'chunk_id': 'chunk_0001', 'dense_summary': ['主角在集市买过一张饼。'], 'keywords': ['饼', '集市']},
                {'chunk_id': 'chunk_0002', 'dense_summary': ['路边摊有人吃饼闲聊。'], 'keywords': ['饼', '路边摊']},
            ],
            user_text='吃饼',
        )

        self.assertEqual(decision['event_hits'], [])
        self.assertEqual(decision['summary_chunk_hits'], [])
        self.assertFalse(decision['inject_summary'])

    def test_event_hit_suppresses_broad_summary_chunk_for_same_topic(self):
        decision = build_selector_decision(
            state_json={
                'location': '客栈二楼房间',
                'main_event': '主角打坐恢复灵力。',
                'onstage_npcs': [],
                'relevant_npcs': ['灰眼男人'],
                'tracked_objects': [],
                'knowledge_records': [],
            },
            recent_history=[{'role': 'assistant', 'content': '主角回到房间后想起灰眼男人提出一百二十灵石。'}],
            keeper_records={'records': []},
            active_threads=[],
            important_npcs=[],
            onstage=[],
            relevant=['灰眼男人'],
            lorebook_entries=[],
            system_npc_candidates=[],
            lorebook_npc_candidates=[],
            event_summaries=[{
                'event_id': 'evt_0112',
                'turn_id': 'turn-0112',
                'summary': '灰眼男人提出一百二十灵石交易条件，主角暂未答应。',
                'actors': ['灰眼男人'],
                'keywords': ['灰眼男人', '一百二十灵石', '交易条件'],
            }],
            summary_text='',
            summary_chunks=[{
                'chunk_id': 'chunk_0008',
                'turn_start': 85,
                'turn_end': 96,
                'actors_mentioned': ['灰眼男人'],
                'dense_summary': ['主角与灰眼男人围绕铜片和交易条件反复试探。'],
                'keywords': ['灰眼男人', '交易条件'],
            }],
            user_text='先打坐恢复一下灵力',
        )

        self.assertEqual(decision['event_hits'][0]['event_id'], 'evt_0112')
        self.assertEqual(decision['summary_chunk_hits'], [])
        self.assertFalse(decision['inject_summary'])

    def test_turn_id_only_event_hit_suppresses_broad_summary_chunk(self):
        decision = build_selector_decision(
            state_json={
                'location': '客栈二楼房间',
                'main_event': '主角打坐恢复灵力。',
                'onstage_npcs': [],
                'relevant_npcs': ['灰眼男人'],
                'tracked_objects': [],
                'knowledge_records': [],
            },
            recent_history=[{'role': 'assistant', 'content': '主角回到房间后想起灰眼男人提出一百二十灵石。'}],
            keeper_records={'records': []},
            active_threads=[],
            important_npcs=[{'primary_label': '灰眼男人', 'role_label': '交易对象'}],
            onstage=[],
            relevant=['灰眼男人'],
            lorebook_entries=[],
            system_npc_candidates=[],
            lorebook_npc_candidates=[],
            event_summaries=[{
                'turn_id': 'turn-0112',
                'summary': '灰眼男人提出一百二十灵石交易条件，主角暂未答应。',
                'actors': ['灰眼男人'],
                'keywords': ['灰眼男人', '一百二十灵石', '交易条件'],
            }],
            summary_text='',
            summary_chunks=[{
                'chunk_id': 'chunk_0008',
                'turn_start': 85,
                'turn_end': 96,
                'actors_mentioned': ['灰眼男人'],
                'dense_summary': ['主角与灰眼男人围绕铜片和交易条件反复试探。'],
                'keywords': ['灰眼男人', '交易条件'],
            }],
            user_text='先打坐恢复一下灵力',
        )

        self.assertEqual(decision['event_hits'][0]['event_id'], 'turn-0112')
        self.assertEqual(decision['summary_chunk_hits'], [])
        self.assertFalse(decision['inject_summary'])
        self.assertIn('灰眼男人', decision['npc_profile_targets'])
        self.assertIn('灰眼男人', [item['name'] for item in decision['npc_roster']])

    def test_player_profile_detail_hits_background_on_direct_memory_prompt(self):
        hits = player_profile_detail_hits(
            [{
                'section_id': 'background',
                'title': '背景细节',
                'items': ['幼年在青州城外随散修叔父长大，熟悉野路子阵法。'],
                'text': '幼年在青州城外随散修叔父长大，熟悉野路子阵法。',
                'sensitivity': 'narrator_only',
            }],
            state_json={'main_event': '主角回忆自己的身世。'},
            recent_history=[],
            user_text='想起小时候在青州城外的过去',
        )

        self.assertEqual(hits[0]['section_id'], 'background')

    def test_player_profile_detail_skips_private_on_quiet_turn_without_anchor(self):
        hits = player_profile_detail_hits(
            [{
                'section_id': 'privateBoundaries',
                'title': '私密边界细节',
                'items': ['真实身份是逃亡继承人，不自动对 NPC 公开。'],
                'text': '真实身份是逃亡继承人，不自动对 NPC 公开。',
                'sensitivity': 'private',
            }],
            state_json={'main_event': '主角坐在客栈二楼休息。'},
            recent_history=[{'role': 'assistant', 'content': '房间里很安静。'}],
            user_text='先休息一会儿',
        )

        self.assertEqual(hits, [])


if __name__ == '__main__':
    unittest.main()
