#!/usr/bin/env python3
"""
Selector质量和相关性测试

测试selector在有keeper records的session中的表现：
1. Keeper records是否被正确调取
2. Selector决策是否相关
3. Lorebook注入是否合理
4. Event summaries是否准确
"""

import requests
import json
import time
import sys
from pathlib import Path

class SelectorQualityTester:
    def __init__(self, session_id, base_url="http://localhost:8765"):
        self.session_id = session_id
        self.base_url = base_url
        
    def send_message(self, message):
        """发送消息到backend"""
        try:
            response = requests.post(
                f"{self.base_url}/api/message",
                json={"session_id": self.session_id, "text": message},
                timeout=180
            )
            return response.json()
        except Exception as e:
            print(f"[ERROR] 请求失败: {e}")
            return None
    
    def get_session_data(self):
        """获取session数据"""
        session_path = Path(f"sessions/{self.session_id}")
        if not session_path.exists():
            return None
        
        data = {}
        
        # 读取keeper_record_archive.json
        keeper_path = session_path / "keeper_record_archive.json"
        if keeper_path.exists():
            with open(keeper_path, 'r', encoding='utf-8') as f:
                data['keeper_archive'] = json.load(f)
        
        # 读取state.json
        state_path = session_path / "state.json"
        if state_path.exists():
            with open(state_path, 'r', encoding='utf-8') as f:
                data['state'] = json.load(f)
        
        # 读取history.json
        history_path = session_path / "history.json"
        if history_path.exists():
            with open(history_path, 'r', encoding='utf-8') as f:
                data['history'] = json.load(f)
        
        # 读取summary.md
        summary_path = session_path / "summary.md"
        if summary_path.exists():
            with open(summary_path, 'r', encoding='utf-8') as f:
                data['summary'] = f.read()
        
        return data
    
    def analyze_keeper_records(self, keeper_archive):
        """分析keeper records的质量"""
        if not keeper_archive or 'records' not in keeper_archive:
            return {
                'count': 0,
                'quality': 'none',
                'details': []
            }
        
        records = keeper_archive['records']
        analysis = {
            'count': len(records),
            'quality': 'good',
            'details': []
        }
        
        for i, record in enumerate(records):
            detail = {
                'index': i + 1,
                'window': f"{record.get('window_start', 'N/A')} - {record.get('window_end', 'N/A')}",
                'entities': len(record.get('stable_entities', [])),
                'events': len(record.get('ongoing_events', [])),
                'loops': len(record.get('open_loops', [])),
                'objects': len(record.get('notable_objects', [])),
                'entity_names': record.get('stable_entities', [])[:3]  # 前3个
            }
            
            # 质量检查
            if detail['entities'] == 0:
                detail['warning'] = '无实体'
                analysis['quality'] = 'poor'
            elif detail['entities'] < 2 and detail['events'] == 0 and detail['loops'] == 0:
                detail['warning'] = '内容稀少'
                analysis['quality'] = 'fair' if analysis['quality'] == 'good' else analysis['quality']
            
            analysis['details'].append(detail)
        
        return analysis
    
    def test_selector_retrieval(self, session_data):
        """测试selector是否调取了keeper records"""
        print("\n" + "="*60)
        print("📊 Keeper Records分析")
        print("="*60)
        
        if 'keeper_archive' not in session_data:
            print("✗ 未找到keeper_record_archive.json")
            return False
        
        keeper_analysis = self.analyze_keeper_records(session_data['keeper_archive'])
        
        print(f"\nKeeper Records数量: {keeper_analysis['count']}")
        print(f"总体质量: {keeper_analysis['quality'].upper()}")
        
        if keeper_analysis['count'] == 0:
            print("✗ 无keeper records，无法测试selector")
            return False
        
        print(f"\nRecords详情:")
        for detail in keeper_analysis['details']:
            print(f"\n  Record #{detail['index']}")
            print(f"    窗口: {detail['window']}")
            print(f"    实体数: {detail['entities']}")
            print(f"    事件数: {detail['events']}")
            print(f"    Open loops: {detail['loops']}")
            print(f"    Objects: {detail['objects']}")
            if detail['entity_names']:
                print(f"    实体示例: {', '.join(detail['entity_names'])}")
            if 'warning' in detail:
                print(f"    ⚠️  {detail['warning']}")
        
        return True
    
    def test_selector_decisions(self, round_num=3):
        """测试selector的决策质量"""
        print("\n" + "="*60)
        print(f"🎯 Selector决策测试 (额外{round_num}轮)")
        print("="*60)
        
        test_messages = [
            "我想起之前在茶摊听到的传闻，决定去调查一下",
            "我回忆之前遇到的那些可疑人物，他们之间可能有联系",
            "根据之前收集的线索，我推断接下来应该去哪里"
        ]
        
        results = []
        
        for i, message in enumerate(test_messages[:round_num], 1):
            print(f"\n第{i}轮测试:")
            print(f"  消息: {message}")
            
            start_time = time.time()
            response = self.send_message(message)
            elapsed = time.time() - start_time
            
            if not response:
                print(f"  ✗ 请求失败")
                results.append({'success': False})
                continue
            
            result = {
                'success': True,
                'elapsed': elapsed,
                'response_length': len(response.get('reply', '')),
                'has_context': 'context' in response
            }
            
            print(f"  ✓ 响应成功 ({elapsed:.1f}秒)")
            print(f"  回复长度: {result['response_length']}字符")
            
            # 分析回复内容是否引用了之前的信息
            reply = response.get('reply', '')
            context_keywords = ['之前', '先前', '刚才', '早先', '那时', '当时', '回忆', '想起']
            referenced = sum(1 for kw in context_keywords if kw in reply)
            result['context_references'] = referenced
            
            if referenced > 0:
                print(f"  ✓ 发现{referenced}个上下文引用关键词")
            else:
                print(f"  ⚠️  未发现明显的上下文引用")
            
            results.append(result)
            time.sleep(1)
        
        # 统计
        print(f"\n决策测试总结:")
        success_count = sum(1 for r in results if r.get('success', False))
        print(f"  成功: {success_count}/{len(results)}")
        
        if success_count > 0:
            avg_time = sum(r.get('elapsed', 0) for r in results if r.get('success', False)) / success_count
            avg_refs = sum(r.get('context_references', 0) for r in results if r.get('success', False)) / success_count
            print(f"  平均响应时间: {avg_time:.1f}秒")
            print(f"  平均上下文引用: {avg_refs:.1f}个/轮")
        
        return results
    
    def test_relevance(self, session_data):
        """测试selector调取的相关性"""
        print("\n" + "="*60)
        print("🔍 Selector相关性分析")
        print("="*60)
        
        if 'state' not in session_data or 'keeper_archive' not in session_data:
            print("✗ 缺少必要数据")
            return
        
        state = session_data['state']
        keeper_archive = session_data['keeper_archive']
        
        # 获取当前场景关键词
        current_location = state.get('location', '')
        current_main_event = state.get('main_event', '')
        
        print(f"\n当前场景:")
        print(f"  地点: {current_location}")
        print(f"  主事件: {current_main_event[:100]}...")
        
        # 分析keeper records中的内容
        print(f"\nKeeper Records内容:")
        for i, record in enumerate(keeper_archive.get('records', []), 1):
            print(f"\n  Record #{i}:")
            entities = record.get('stable_entities', [])
            events = record.get('ongoing_events', [])
            
            if entities:
                print(f"    实体: {', '.join(entities[:5])}")
            if events:
                print(f"    事件: {', '.join(events[:3])}")
            
            # 简单的相关性检查：看实体或事件是否在当前main_event中被提及
            relevance_score = 0
            for entity in entities:
                if entity in current_main_event or entity in current_location:
                    relevance_score += 1
            
            if relevance_score > 0:
                print(f"    ✓ 相关性: {relevance_score}个实体在当前场景中")
            else:
                print(f"    ⚠️  相关性: 未发现直接关联")
        
        return True

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Selector质量和相关性测试')
    parser.add_argument('--session', default='http-full-regression-test', help='Session ID')
    parser.add_argument('--rounds', type=int, default=3, help='额外测试轮数')
    parser.add_argument('--skip-new-rounds', action='store_true', help='跳过新轮测试，只分析现有数据')
    args = parser.parse_args()
    
    print("🧪 Selector质量和相关性测试")
    print(f"Session: {args.session}")
    print(f"额外测试轮数: {args.rounds}")
    print()
    
    tester = SelectorQualityTester(args.session)
    
    # 1. 获取session数据
    print("[1/4] 读取session数据...")
    session_data = tester.get_session_data()
    
    if not session_data:
        print(f"✗ Session不存在或数据不完整: {args.session}")
        return 1
    
    print(f"✓ 数据读取成功")
    print(f"  - keeper_archive: {'✓' if 'keeper_archive' in session_data else '✗'}")
    print(f"  - state: {'✓' if 'state' in session_data else '✗'}")
    print(f"  - history: {'✓' if 'history' in session_data else '✗'}")
    print(f"  - summary: {'✓' if 'summary' in session_data else '✗'}")
    
    # 2. 分析keeper records
    print("\n[2/4] 分析Keeper Records...")
    has_records = tester.test_selector_retrieval(session_data)
    
    # 3. 分析相关性
    print("\n[3/4] 分析Selector相关性...")
    tester.test_relevance(session_data)
    
    # 4. 测试新的决策
    if not args.skip_new_rounds and has_records:
        print("\n[4/4] 测试Selector决策...")
        results = tester.test_selector_decisions(args.rounds)
    else:
        print("\n[4/4] 跳过新轮测试")
    
    print("\n" + "="*60)
    print("✅ 测试完成")
    print("="*60)
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
