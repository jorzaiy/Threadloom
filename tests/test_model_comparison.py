#!/usr/bin/env python3
"""
对比测试 Llama-3.3-70B vs Kimi-k2-0905-preview
测试keeper和bootstrap agents的质量、速度、稳定性
"""
import json
import requests
import time
from pathlib import Path
from typing import Dict, List

BASE_URL = "http://localhost:8765"
USER_CONFIG_PATH = Path("runtime-data/default-user/config/model-runtime.json")
BACKUP_PATH = Path("runtime-data/default-user/config/model-runtime.json.backup")

TEST_MESSAGES = [
    "我来到一个繁华的茶馆，里面坐着一个白发老者和一个年轻书生",
    "我走向老者，询问他关于城中失踪案的消息",
    "老者递给我一块古玉，说这是关键线索",
    "我离开茶馆，前往城外的废弃寺庙",
    "寺庙中传来诡异的笛声，我看到一个黑衣人的背影",
]

def read_config() -> dict:
    """读取当前配置"""
    if USER_CONFIG_PATH.exists():
        return json.loads(USER_CONFIG_PATH.read_text())
    return {}

def write_config(config: dict):
    """写入配置"""
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))

def backup_config():
    """备份当前配置"""
    if USER_CONFIG_PATH.exists():
        config = read_config()
        BACKUP_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))
        print(f"✅ 配置已备份到: {BACKUP_PATH}")
        return config
    return None

def restore_config():
    """恢复备份配置"""
    if BACKUP_PATH.exists():
        config = json.loads(BACKUP_PATH.read_text())
        write_config(config)
        print(f"✅ 配置已恢复")
        return config
    return None

def set_model(model_id: str, model_name: str):
    """设置模型配置"""
    config = read_config()
    config['state_keeper'] = {'model': model_id}
    if isinstance(config.get('advanced_models'), dict):
        config['advanced_models'].pop('state_keeper_candidate', None)
    write_config(config)
    print(f"✅ 已切换到: {model_name} ({model_id})")

def create_session(session_id: str) -> bool:
    """创建新session"""
    try:
        resp = requests.post(f"{BASE_URL}/api/message", 
                            json={'session_id': session_id, 'text': '/开局'}, 
                            timeout=60)
        return resp.status_code == 200
    except Exception as e:
        print(f"❌ 创建session失败: {e}")
        return False

def send_message(session_id: str, text: str) -> Dict:
    """发送消息并返回结果"""
    start_time = time.time()
    try:
        resp = requests.post(f"{BASE_URL}/api/message",
                            json={'session_id': session_id, 'text': text},
                            timeout=180)
        elapsed = time.time() - start_time
        
        if resp.status_code != 200:
            return {
                'success': False,
                'error': f"HTTP {resp.status_code}",
                'elapsed': elapsed
            }
        
        data = resp.json()
        return {
            'success': True,
            'reply': data.get('reply', ''),
            'usage': data.get('usage', {}),
            'state_snapshot': data.get('state_snapshot', {}),
            'debug': data.get('debug', {}),
            'elapsed': elapsed
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            'success': False,
            'error': str(e),
            'elapsed': elapsed
        }

def get_state(session_id: str) -> Dict:
    """获取当前状态"""
    try:
        resp = requests.get(f"{BASE_URL}/api/state", 
                           params={'session_id': session_id},
                           timeout=30)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}

def analyze_result(result: Dict, message: str) -> Dict:
    """分析单轮结果"""
    if not result.get('success'):
        return {
            'success': False,
            'error': result.get('error'),
            'elapsed': result.get('elapsed', 0)
        }
    
    reply = result.get('reply', '')
    usage = result.get('usage', {})
    state = result.get('state_snapshot', {})
    debug = result.get('debug', {})
    
    # 提取关键指标
    entities_count = len(state.get('entities', []))
    events_count = len(state.get('main_events', []))
    objects_count = len(state.get('objects', []))
    
    return {
        'success': True,
        'elapsed': result['elapsed'],
        'reply_length': len(reply),
        'model': usage.get('model', 'unknown'),
        'input_tokens': usage.get('input_tokens', 0),
        'output_tokens': usage.get('output_tokens', 0),
        'entities_count': entities_count,
        'events_count': events_count,
        'objects_count': objects_count,
        'scene_mode': debug.get('scene_mode', 'unknown'),
    }

def test_model(model_id: str, model_name: str, session_id: str) -> Dict:
    """测试单个模型"""
    print(f"\n{'='*60}")
    print(f"🧪 测试模型: {model_name} ({model_id})")
    print(f"{'='*60}")
    
    # 设置模型
    set_model(model_id, model_name)
    time.sleep(2)  # 等待配置生效
    
    # 创建session
    print(f"📝 创建session: {session_id}")
    if not create_session(session_id):
        return {'error': 'Failed to create session'}
    
    time.sleep(2)
    
    # 测试消息
    results = []
    total_elapsed = 0
    
    for i, msg in enumerate(TEST_MESSAGES, 1):
        print(f"\n[{i}/{len(TEST_MESSAGES)}] 发送: {msg}")
        result = send_message(session_id, msg)
        analysis = analyze_result(result, msg)
        
        if analysis['success']:
            print(f"  ✅ 成功 | {analysis['elapsed']:.1f}s | "
                  f"Entities: {analysis['entities_count']} | "
                  f"Events: {analysis['events_count']} | "
                  f"Objects: {analysis['objects_count']}")
            total_elapsed += analysis['elapsed']
        else:
            print(f"  ❌ 失败: {analysis.get('error')}")
        
        results.append(analysis)
        time.sleep(1)  # 避免请求过快
    
    # 获取最终状态
    final_state = get_state(session_id)
    
    # 统计结果
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    summary = {
        'model_id': model_id,
        'model_name': model_name,
        'session_id': session_id,
        'total_rounds': len(TEST_MESSAGES),
        'successful_rounds': len(successful),
        'failed_rounds': len(failed),
        'total_time': total_elapsed,
        'avg_time': total_elapsed / len(successful) if successful else 0,
        'final_entities': len(final_state.get('state', {}).get('entities', [])),
        'final_events': len(final_state.get('state', {}).get('main_events', [])),
        'final_objects': len(final_state.get('state', {}).get('objects', [])),
        'results': results
    }
    
    return summary

def print_comparison(kimi_summary: Dict, llama_summary: Dict):
    """打印对比结果"""
    print(f"\n{'='*80}")
    print(f"📊 对比结果")
    print(f"{'='*80}")
    
    print(f"\n【成功率】")
    print(f"  Kimi:  {kimi_summary['successful_rounds']}/{kimi_summary['total_rounds']} "
          f"({kimi_summary['successful_rounds']/kimi_summary['total_rounds']*100:.1f}%)")
    print(f"  Llama: {llama_summary['successful_rounds']}/{llama_summary['total_rounds']} "
          f"({llama_summary['successful_rounds']/llama_summary['total_rounds']*100:.1f}%)")
    
    print(f"\n【响应速度】")
    print(f"  Kimi:  平均 {kimi_summary['avg_time']:.1f}秒/轮 | 总计 {kimi_summary['total_time']:.1f}秒")
    print(f"  Llama: 平均 {llama_summary['avg_time']:.1f}秒/轮 | 总计 {llama_summary['total_time']:.1f}秒")
    if llama_summary['avg_time'] > 0:
        speedup = (kimi_summary['avg_time'] - llama_summary['avg_time']) / kimi_summary['avg_time'] * 100
        if speedup > 0:
            print(f"  💡 Llama快 {speedup:.1f}%")
        else:
            print(f"  💡 Kimi快 {-speedup:.1f}%")
    
    print(f"\n【状态提取质量】")
    print(f"  Kimi:  {kimi_summary['final_entities']} 实体 | "
          f"{kimi_summary['final_events']} 事件 | {kimi_summary['final_objects']} 物品")
    print(f"  Llama: {llama_summary['final_entities']} 实体 | "
          f"{llama_summary['final_events']} 事件 | {llama_summary['final_objects']} 物品")
    
    # 质量评分
    kimi_quality = (kimi_summary['final_entities'] + 
                    kimi_summary['final_events'] * 2 + 
                    kimi_summary['final_objects'])
    llama_quality = (llama_summary['final_entities'] + 
                     llama_summary['final_events'] * 2 + 
                     llama_summary['final_objects'])
    
    print(f"\n【综合评分】(实体 + 事件×2 + 物品)")
    print(f"  Kimi:  {kimi_quality} 分")
    print(f"  Llama: {llama_quality} 分")
    
    quality_diff = abs(llama_quality - kimi_quality) / max(kimi_quality, 1) * 100
    
    print(f"\n{'='*80}")
    print(f"🎯 结论")
    print(f"{'='*80}")
    
    # 判断是否可以替换
    can_replace = (
        llama_summary['successful_rounds'] >= kimi_summary['successful_rounds'] * 0.8 and
        quality_diff < 30  # 质量差异小于30%
    )
    
    if can_replace:
        if llama_quality >= kimi_quality * 0.9:
            print(f"✅ Llama-3.3-70B 质量与Kimi接近 (相差 {quality_diff:.1f}%)")
        else:
            print(f"⚠️  Llama-3.3-70B 质量略低于Kimi (相差 {quality_diff:.1f}%)")
        
        if llama_summary['avg_time'] < kimi_summary['avg_time']:
            speedup = (kimi_summary['avg_time'] - llama_summary['avg_time']) / kimi_summary['avg_time'] * 100
            print(f"✅ Llama-3.3-70B 响应速度更快 ({speedup:.1f}%)")
        else:
            slowdown = (llama_summary['avg_time'] - kimi_summary['avg_time']) / kimi_summary['avg_time'] * 100
            print(f"⚠️  Llama-3.3-70B 响应速度略慢 ({slowdown:.1f}%)")
        
        print(f"\n✅ 推荐: 可以替换为 Llama-3.3-70B")
        return True
    else:
        print(f"❌ Llama-3.3-70B 质量或稳定性不足")
        print(f"   - 成功率: {llama_summary['successful_rounds']}/{llama_summary['total_rounds']}")
        print(f"   - 质量差异: {quality_diff:.1f}%")
        print(f"\n⚠️  不推荐替换，建议保持Kimi")
        return False

def main():
    print("🔬 Llama-3.3-70B vs Kimi-k2-0905-preview 对比测试")
    print("="*80)
    
    # 备份配置
    original_config = backup_config()
    if not original_config:
        print("❌ 无法读取当前配置")
        return
    
    try:
        # 测试Kimi
        kimi_summary = test_model(
            'kimi-k2-0905-preview',
            'Kimi',
            'model-test-kimi'
        )
        
        time.sleep(5)
        
        # 测试Llama
        llama_summary = test_model(
            'Llama-3.3-70B',
            'Llama-3.3-70B',
            'model-test-llama'
        )
        
        # 保存结果
        results = {
            'kimi': kimi_summary,
            'llama': llama_summary,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        result_file = Path('test_results_model_comparison.json')
        result_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\n💾 结果已保存到: {result_file}")
        
        # 打印对比
        can_replace = print_comparison(kimi_summary, llama_summary)
        
        return can_replace
        
    finally:
        # 恢复配置
        print(f"\n{'='*80}")
        restore_config()

if __name__ == '__main__':
    can_replace = main()
    exit(0 if can_replace else 1)
