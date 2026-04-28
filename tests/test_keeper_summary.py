#!/usr/bin/env python3
"""测试 keeper summary 生成"""

import sys
import signal
import logging
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("操作超时")


def test_keeper_archive(session_id: str, timeout_seconds: int = 30):
    """测试 keeper archive 生成（带超时保护）"""
    from keeper_archive import build_keeper_record_archive, save_keeper_record_archive
    from runtime_store import load_history
    
    logger.info(f"测试session: {session_id}")
    
    # 设置超时
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    
    try:
        # 加载历史
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
        
        logger.info(f"历史消息数: {len(history)}")
        logger.info(f"对话对数: {len(pairs)}")
        
        # 构建 archive（跳过 bootstrap 避免LLM调用阻塞，使用 heuristic）
        logger.info("开始构建 keeper record archive（使用 heuristic 模式）...")
        archive = build_keeper_record_archive(session_id, skip_bootstrap=True, use_llm=False)
        
        # 取消超时
        signal.alarm(0)
        
        # 检查结果
        records = archive.get('records', [])
        logger.info(f"\n✅ 成功生成 {len(records)} 条 keeper records")
        
        if records:
            logger.info("\n记录详情:")
            for idx, record in enumerate(records):
                window = record.get('window', {})
                logger.info(f"\n  Record #{idx + 1}:")
                logger.info(f"    窗口: {window.get('from_turn')} 至 {window.get('to_turn')}")
                logger.info(f"    对话对数: {window.get('pair_count')}")
                
                entities = record.get('stable_entities', [])
                logger.info(f"    稳定实体: {[e.get('name') for e in entities]}")
                
                events = record.get('ongoing_events', [])
                if events:
                    logger.info(f"    持续事件: {events[0][:50]}..." if len(events[0]) > 50 else f"    持续事件: {events[0]}")
                
                loops = record.get('open_loops', [])
                if loops:
                    logger.info(f"    未决线索: {loops[0][:50]}..." if len(loops[0]) > 50 else f"    未决线索: {loops[0]}")
            
            # 保存
            save_keeper_record_archive(session_id, archive)
            logger.info(f"\n✅ Archive 已保存")
            return True
        else:
            logger.warning("\n⚠️  未生成任何 records")
            logger.info("可能原因:")
            logger.info("  - 对话对数不足（需要 > 13 对）")
            logger.info("  - 过滤条件未满足")
            return False
            
    except TimeoutError:
        signal.alarm(0)
        logger.error(f"\n❌ 操作超时 ({timeout_seconds}秒)")
        logger.error("可能是 LLM 调用阻塞，请检查：")
        logger.error("  1. API配置是否正确")
        logger.error("  2. 网络连接是否正常")
        logger.error("  3. 是否需要禁用 LLM 调用使用纯 heuristic")
        return False
    except Exception as e:
        signal.alarm(0)
        logger.error(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


test_keeper_archive.__test__ = False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='测试 keeper summary 生成')
    parser.add_argument('session_id', help='Session ID')
    parser.add_argument('--timeout', type=int, default=30, help='超时时间（秒）')
    args = parser.parse_args()
    
    success = test_keeper_archive(args.session_id, args.timeout)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
