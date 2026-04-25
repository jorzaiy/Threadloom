#!/usr/bin/env python3
"""
完整HTTP回归测试 - Keeper & Selector全功能验证
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent / 'backend'))

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class RegressionTester:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.results = []
        
    def run_round(self, round_num: int, message: str) -> dict:
        """运行一轮测试"""
        from handler_message import handle_message
        
        logger.info(f"{'='*60}")
        logger.info(f"第 {round_num}/15 轮")
        logger.info(f"消息: {message[:50]}...")
        logger.info(f"{'='*60}")
        
        start_time = time.time()
        
        try:
            # 调用handler
            result = handle_message({'session_id': self.session_id, 'text': message})
            elapsed = time.time() - start_time
            
            if result.get('error'):
                logger.error(f"❌ HTTP错误: {result['error']}")
                return {
                    'round': round_num,
                    'http_success': False,
                    'error': str(result['error']),
                    'elapsed': elapsed
                }
            
            # 基础验证
            reply = result.get('reply', '')
            state_snapshot = result.get('state_snapshot', {})
            
            logger.info(f"✓ HTTP响应成功")
            logger.info(f"✓ 回复长度: {len(reply)} 字符")
            logger.info(f"✓ 用时: {elapsed:.2f}秒")
            
            # 验证state
            state_validations = self.validate_state(state_snapshot, round_num)
            
            # 验证keeper（12轮后）
            keeper_validations = {}
            if round_num >= 12:
                keeper_validations = self.validate_keeper(round_num)
            
            # 验证selector（13轮后）
            selector_validations = {}
            if round_num >= 13:
                selector_validations = self.validate_selector(round_num)
            
            return {
                'round': round_num,
                'http_success': True,
                'reply_length': len(reply),
                'elapsed': elapsed,
                'state': state_validations,
                'keeper': keeper_validations,
                'selector': selector_validations,
                'error': None
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                'round': round_num,
                'http_success': False,
                'error': str(e),
                'elapsed': elapsed
            }
    
    def validate_state(self, state: dict, round_num: int) -> dict:
        """验证state更新"""
        logger.info(f"\n[State验证]")
        
        validations = {
            'has_time': bool(state.get('time')),
            'has_location': bool(state.get('location')),
            'has_main_event': bool(state.get('main_event')),
            'has_immediate_goal': bool(state.get('immediate_goal')),
            'has_active_threads': len(state.get('active_threads', [])) > 0,
        }
        
        for key, value in validations.items():
            status = "✓" if value else "✗"
            logger.info(f"  {status} {key}: {value}")
        
        # 显示关键信息
        logger.info(f"\n  时间: {state.get('time', 'N/A')}")
        logger.info(f"  地点: {state.get('location', 'N/A')}")
        logger.info(f"  主事件: {state.get('main_event', 'N/A')[:50]}...")
        logger.info(f"  当前目标: {state.get('immediate_goal', 'N/A')[:50]}...")
        logger.info(f"  活跃线程数: {len(state.get('active_threads', []))}")
        
        return validations
    
    def validate_keeper(self, round_num: int) -> dict:
        """验证keeper功能"""
        logger.info(f"\n[Keeper验证 - 第{round_num}轮]")
        
        from keeper_archive import load_keeper_record_archive
        from runtime_store import load_summary, load_history
        
        validations = {}
        
        try:
            # 1. 检查keeper records
            archive = load_keeper_record_archive(self.session_id)
            records = archive.get('records', [])
            
            validations['records_generated'] = len(records) > 0
            validations['records_count'] = len(records)
            
            logger.info(f"  ✓ Keeper records: {len(records)} 条")
            
            if records:
                for idx, record in enumerate(records, 1):
                    window = record.get('window', {})
                    entities = record.get('stable_entities', [])
                    events = record.get('ongoing_events', [])
                    
                    logger.info(f"    Record #{idx}:")
                    logger.info(f"      窗口: {window.get('from_turn')} - {window.get('to_turn')}")
                    logger.info(f"      实体数: {len(entities)}")
                    logger.info(f"      事件数: {len(events)}")
            
            # 2. 检查summary
            summary = load_summary(self.session_id)
            validations['summary_generated'] = len(summary) > 100
            validations['summary_length'] = len(summary)
            
            logger.info(f"  ✓ Summary长度: {len(summary)} 字符")
            
            # 3. 检查历史
            history = load_history(self.session_id)
            pairs = self._count_pairs(history)
            validations['history_pairs'] = pairs
            
            logger.info(f"  ✓ 对话对数: {pairs}")
            
            # 质量检查
            if records:
                validations['quality_check'] = self._check_keeper_quality(records)
            
        except Exception as e:
            logger.error(f"  ❌ Keeper验证失败: {e}")
            validations['error'] = str(e)
        
        return validations
    
    def validate_selector(self, round_num: int) -> dict:
        """验证selector功能"""
        logger.info(f"\n[Selector验证 - 第{round_num}轮]")
        
        from context_builder import build_runtime_context
        from runtime_store import load_history, load_state
        
        validations = {}
        
        try:
            # 构建context（这会触发selector）
            history = load_history(self.session_id)
            state = load_state(self.session_id)
            
            context = build_runtime_context(
                session_id=self.session_id,
                recent_history=history[-20:] if len(history) > 20 else history,
                state_json=state
            )
            
            # 1. 检查keeper records注入
            keeper_records = context.get('keeper_records', {})
            validations['keeper_records_injected'] = bool(keeper_records.get('records'))
            validations['keeper_records_count'] = len(keeper_records.get('records', []))
            
            logger.info(f"  ✓ Keeper records注入: {validations['keeper_records_count']} 条")
            
            # 2. 检查selector决策
            selector_decision = context.get('selector_decision', {})
            validations['selector_decision_exists'] = bool(selector_decision)
            
            if selector_decision:
                logger.info(f"  ✓ Selector决策存在")
                logger.info(f"    - 注入lorebook: {selector_decision.get('inject_lorebook', False)}")
                logger.info(f"    - 注入NPC候选: {selector_decision.get('inject_candidates', False)}")
                logger.info(f"    - Profile目标数: {len(selector_decision.get('profile_targets', []))}")
                logger.info(f"    - Event命中数: {len(selector_decision.get('event_hits', []))}")
                
                validations['inject_lorebook'] = selector_decision.get('inject_lorebook', False)
                validations['inject_candidates'] = selector_decision.get('inject_candidates', False)
                validations['profile_targets_count'] = len(selector_decision.get('profile_targets', []))
                validations['event_hits_count'] = len(selector_decision.get('event_hits', []))
            
            # 3. 检查lorebook entries
            lorebook = context.get('lorebook_entries', [])
            validations['lorebook_entries_count'] = len(lorebook)
            logger.info(f"  ✓ Lorebook条目: {len(lorebook)} 条")
            
            # 4. 检查event summaries
            event_summaries = context.get('event_summaries', [])
            validations['event_summaries_count'] = len(event_summaries)
            logger.info(f"  ✓ Event summaries: {len(event_summaries)} 条")
            
            # 5. 检查continuity candidates
            continuity = context.get('continuity_candidates', [])
            validations['continuity_candidates_count'] = len(continuity)
            logger.info(f"  ✓ Continuity候选: {len(continuity)} 条")
            
        except Exception as e:
            logger.error(f"  ❌ Selector验证失败: {e}")
            validations['error'] = str(e)
            import traceback
            traceback.print_exc()
        
        return validations
    
    def _count_pairs(self, history: list) -> int:
        """统计对话对数"""
        pairs = 0
        current_user = None
        for item in history:
            if not isinstance(item, dict):
                continue
            role = item.get('role')
            if role == 'user':
                current_user = item
            elif role == 'assistant' and current_user is not None:
                pairs += 1
                current_user = None
        return pairs
    
    def _check_keeper_quality(self, records: list) -> dict:
        """检查keeper quality"""
        checks = {
            'all_have_window': all('window' in r for r in records),
            'all_have_entities': all(len(r.get('stable_entities', [])) >= 1 for r in records),
            'has_events_or_loops': any(r.get('ongoing_events') or r.get('open_loops') for r in records),
        }
        
        passed = all(checks.values())
        logger.info(f"  质量检查: {'✓ 通过' if passed else '✗ 未通过'}")
        for key, value in checks.items():
            logger.info(f"    - {key}: {value}")
        
        return checks
    
    def print_summary(self):
        """打印测试总结"""
        logger.info(f"\n{'='*60}")
        logger.info(f"测试总结")
        logger.info(f"{'='*60}")
        
        total = len(self.results)
        success = sum(1 for r in self.results if r['http_success'])
        failed = total - success
        
        logger.info(f"总轮数: {total}")
        logger.info(f"成功: {success} ✓")
        logger.info(f"失败: {failed} ✗")
        
        if failed > 0:
            logger.info(f"\n失败的轮次:")
            for r in self.results:
                if not r['http_success']:
                    logger.info(f"  - 第{r['round']}轮: {r.get('error', 'Unknown error')}")
        
        # Keeper总结
        keeper_rounds = [r for r in self.results if 'keeper' in r and r['keeper']]
        if keeper_rounds:
            logger.info(f"\nKeeper功能:")
            last_keeper = keeper_rounds[-1]['keeper']
            logger.info(f"  Records生成: {'✓' if last_keeper.get('records_generated') else '✗'}")
            logger.info(f"  Records数量: {last_keeper.get('records_count', 0)}")
            logger.info(f"  Summary生成: {'✓' if last_keeper.get('summary_generated') else '✗'}")
        
        # Selector总结
        selector_rounds = [r for r in self.results if 'selector' in r and r['selector']]
        if selector_rounds:
            logger.info(f"\nSelector功能:")
            last_selector = selector_rounds[-1]['selector']
            logger.info(f"  Keeper records注入: {'✓' if last_selector.get('keeper_records_injected') else '✗'}")
            logger.info(f"  Selector决策: {'✓' if last_selector.get('selector_decision_exists') else '✗'}")
            logger.info(f"  Lorebook条目: {last_selector.get('lorebook_entries_count', 0)}")
            logger.info(f"  Event summaries: {last_selector.get('event_summaries_count', 0)}")
        
        logger.info(f"\n{'='*60}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='完整HTTP回归测试')
    parser.add_argument('--session', default='http-full-regression-test', help='Session ID')
    parser.add_argument('--rounds', type=int, default=15, help='测试轮数')
    parser.add_argument('--delay', type=float, default=1.0, help='轮次间延迟（秒）')
    args = parser.parse_args()
    
    # 测试消息
    messages = [
        '我观察周围的环境，注意街道上的人群和建筑',
        '我走向告示墙，仔细查看上面张贴的告示内容',
        '我在茶摊坐下，要一壶茶，倾听周围的谈话',
        '我询问小二最近城里有什么新鲜事',
        '我注意到街角有几个形迹可疑的人，暗中观察他们',
        '我起身离开茶摊，往城门方向走去',
        '我观察守城士兵的盘查情况，评估城门的戒备程度',
        '我转身往市集方向走，混入人群中',
        '我在市集里随意走走，注意周围有没有人跟踪',
        '我走进一家看起来普通的药铺，假装挑选药材',
        '我向药铺掌柜打听城中局势，探探口风',
        '我买了些常用药材作为掩护，然后离开药铺',
        '我找个僻静的巷子，整理一下得到的情报',
        '我回想刚才观察到的所有细节，判断接下来该怎么做',
        '我决定前往城西的客栈，先找个落脚的地方',
    ]
    
    tester = RegressionTester(args.session)
    
    logger.info(f"\n🚀 开始完整HTTP回归测试")
    logger.info(f"Session: {args.session}")
    logger.info(f"测试轮数: {args.rounds}")
    logger.info(f"")
    
    # 执行测试
    for round_num in range(1, args.rounds + 1):
        message = messages[round_num - 1] if round_num <= len(messages) else f"继续探索（第{round_num}轮）"
        
        result = tester.run_round(round_num, message)
        tester.results.append(result)
        
        # 轮次间延迟
        if round_num < args.rounds:
            time.sleep(args.delay)
    
    # 打印总结
    tester.print_summary()
    
    # 返回状态
    all_success = all(r['http_success'] for r in tester.results)
    sys.exit(0 if all_success else 1)


if __name__ == '__main__':
    main()
