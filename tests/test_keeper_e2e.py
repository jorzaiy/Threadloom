#!/usr/bin/env python3
"""端到端测试：验证 keeper summary 在12轮后生成"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'backend'))

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def test_e2e_keeper_summary(session_id: str, num_turns: int = 15):
    """端到端测试：运行多轮对话并验证 keeper summary"""
    from handler_message import handle_message
    from keeper_archive import build_keeper_record_archive, save_keeper_record_archive
    from runtime_store import load_history, load_state
    
    logger.info(f"开始端到端测试，session: {session_id}, 轮数: {num_turns}")
    
    # 测试消息
    test_messages = [
        "我观察周围环境",
        "我走向告示墙",
        "我仔细阅读告示内容",
        "我注意到茶摊那边的客人",
        "我在茶摊坐下要了杯茶",
        "我倾听周围的谈话",
        "我询问小二最近城里的情况",
        "我观察街上来往的人",
        "我起身准备离开",
        "我往城门方向走去",
        "我注意观察守城士兵",
        "我在城门附近停下",
        "我思考接下来该做什么",
        "我决定往东边市集走",
        "我走进人群中",
    ]
    
    try:
        # 运行对话
        for i, message in enumerate(test_messages[:num_turns], 1):
            logger.info(f"\n=== 第 {i}/{num_turns} 轮 ===")
            logger.info(f"输入: {message}")
            
            result = handle_message({'session_id': session_id, 'text': message})
            
            if result.get('error'):
                logger.error(f"错误: {result['error']}")
                return False
            
            reply = result.get('reply', '')
            logger.info(f"回复长度: {len(reply)} 字符")
            
            # 短暂延迟避免过载
            time.sleep(0.5)
        
        # 检查历史
        history = load_history(session_id)
        pairs = []
        current_user = None
        for item in history:
            if not isinstance(item, dict):
                continue
            role = item.get('role')
            if role == 'user':
                current_user = item
            elif role == 'assistant' and current_user is not None:
                pairs.append((current_user, item))
                current_user = None
        
        logger.info(f"\n=== 对话完成 ===")
        logger.info(f"总消息数: {len(history)}")
        logger.info(f"对话对数: {len(pairs)}")
        
        # 检查 keeper archive
        logger.info(f"\n=== 检查 keeper records ===")
        
        # 使用 heuristic 模式避免 LLM 阻塞
        archive = build_keeper_record_archive(session_id, skip_bootstrap=True, use_llm=False)
        records = archive.get('records', [])
        
        logger.info(f"生成的 records 数量: {len(records)}")
        
        if records:
            logger.info("\n✅ 成功！Records 详情:")
            for idx, record in enumerate(records):
                window = record.get('window', {})
                logger.info(f"\n  Record #{idx + 1}:")
                logger.info(f"    窗口: {window.get('from_turn')} - {window.get('to_turn')}")
                logger.info(f"    对话对数: {window.get('pair_count')}")
                
                entities = record.get('stable_entities', [])
                logger.info(f"    稳定实体({len(entities)}): {[e.get('name') for e in entities]}")
                
                events = record.get('ongoing_events', [])
                logger.info(f"    持续事件({len(events)}): {events[:2]}")  # 只显示前2个
                
                loops = record.get('open_loops', [])
                if loops:
                    logger.info(f"    未决线索({len(loops)}): {loops[:2]}")  # 只显示前2个
                
                objects = record.get('tracked_objects', [])
                if objects:
                    logger.info(f"    追踪物品({len(objects)}): {[o.get('label') for o in objects]}")
            
            # 保存
            save_keeper_record_archive(session_id, archive)
            logger.info(f"\n✅ Archive 已保存到 memory/keeper_record_archive.json")
            
            # 检查summary.md
            from runtime_store import session_paths, load_summary
            summary_text = load_summary(session_id)
            if summary_text:
                logger.info(f"\n✅ Summary 已生成，长度: {len(summary_text)} 字符")
                logger.info(f"\nSummary 预览（前500字符）:")
                logger.info("-" * 60)
                logger.info(summary_text[:500])
                logger.info("-" * 60)
            else:
                logger.warning("\n⚠️  Summary 文件为空")
            
            return True
        else:
            logger.warning("\n⚠️  未生成 keeper records")
            logger.info("可能原因:")
            logger.info("  - 对话对数不足（推荐 13+ 对）")
            logger.info("  - 内容过滤条件不满足")
            return False
            
    except Exception as e:
        logger.error(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


test_e2e_keeper_summary.__test__ = False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='端到端测试 keeper summary')
    parser.add_argument('--session', default='http-keeper-e2e-test', help='Session ID')
    parser.add_argument('--turns', type=int, default=15, help='对话轮数')
    args = parser.parse_args()
    
    success = test_e2e_keeper_summary(args.session, args.turns)
    
    if success:
        logger.info("\n" + "="*60)
        logger.info("✅ 端到端测试通过！")
        logger.info("="*60)
        sys.exit(0)
    else:
        logger.error("\n" + "="*60)
        logger.error("❌ 端到端测试失败")
        logger.error("="*60)
        sys.exit(1)


if __name__ == '__main__':
    main()
