#!/usr/bin/env python3
"""
简化的模型对比测试 - 使用已有session或跳过开局
"""
import json
import requests
import time
from pathlib import Path

BASE_URL = "http://localhost:8765"
USER_CONFIG_PATH = Path("runtime-data/default-user/config/model-runtime.json")
BACKUP_PATH = Path("runtime-data/default-user/config/model-runtime.json.backup")

# 测试消息 - 更简单直接
TEST_MESSAGES = [
    "我走进城中的酒馆",
    "酒馆中坐着一位白发老者，正在饮酒",
    "我走向老者，询问近日城中的怪事",
    "老者递给我一块玉佩，说这是重要线索",
    "我接过玉佩，离开酒馆前往城外",
]

def backup_and_set_model(model_id: str, model_name: str):
    """备份并设置模型"""
    if not BACKUP_PATH.exists():
        config = json.loads(USER_CONFIG_PATH.read_text())
        BACKUP_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))
        print(f"✅ 配置已备份")
    
    config = json.loads(USER_CONFIG_PATH.read_text())
    config['state_keeper'] = {'model': model_id}
    config['advanced_models'] = config.get('advanced_models', {})
    config['advanced_models']['state_keeper_candidate'] = {
        'provider': 'site',
        'model': model_id,
        'temperature': 0.0,
        'max_output_tokens': 800,
        'stream': False
    }
    USER_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    print(f"✅ 已切换到: {model_name}")
    time.sleep(2)

def restore_config():
    """恢复配置"""
    if BACKUP_PATH.exists():
        config = json.loads(BACKUP_PATH.read_text())
        USER_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))
        BACKUP_PATH.unlink()
        print(f"✅ 配置已恢复")

def send_message(session_id: str, text: str, timeout: int = 180) -> dict:
    """发送消息"""
    start = time.time()
    try:
        resp = requests.post(f"{BASE_URL}/api/message",
                            json={'session_id': session_id, 'text': text},
                            timeout=timeout)
        elapsed = time.time() - start
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                'success': True,
                'elapsed': elapsed,
                'reply': data.get('reply', ''),
                'usage': data.get('usage', {}),
                'state_snapshot': data.get('state_snapshot', {}),
            }
        else:
            return {
                'success': False,
                'elapsed': elapsed,
                'error': f"HTTP {resp.status_code}"
            }
    except Exception as e:
        elapsed = time.time() - start
        return {
            'success': False,
            'elapsed': elapsed,
            'error': str(e)
        }

def test_model_simple(model_id: str, model_name: str, base_session: str) -> dict:
    """简化的模型测试 - 基于已有session"""
    print(f"\n{'='*70}")
    print(f"🧪 测试: {model_name}")
    print(f"{'='*70}")
    
    backup_and_set_model(model_id, model_name)
    
    session_id = f"{base_session}-{model_id.lower().replace('.', '-')}"
    results = []
    total_time = 0
    
    for i, msg in enumerate(TEST_MESSAGES, 1):
        print(f"\n[{i}/{len(TEST_MESSAGES)}] {msg}")
        result = send_message(session_id, msg, timeout=180)
        
        if result['success']:
            state = result['state_snapshot']
            entities = len(state.get('entities', []))
            events = len(state.get('main_events', []))
            objects = len(state.get('objects', []))
            
            print(f"  ✅ {result['elapsed']:.1f}s | "
                  f"实体:{entities} 事件:{events} 物品:{objects}")
            total_time += result['elapsed']
            
            results.append({
                'success': True,
                'elapsed': result['elapsed'],
                'entities': entities,
                'events': events,
                'objects': objects,
                'reply_len': len(result['reply'])
            })
        else:
            print(f"  ❌ 失败: {result['error']} ({result['elapsed']:.1f}s)")
            results.append({
                'success': False,
                'elapsed': result['elapsed'],
                'error': result['error']
            })
        
        time.sleep(1)
    
    success_count = sum(1 for r in results if r['success'])
    
    if success_count > 0:
        final = results[-1] if results[-1]['success'] else results[-2]
        return {
            'model_id': model_id,
            'model_name': model_name,
            'success_rate': success_count / len(TEST_MESSAGES),
            'avg_time': total_time / success_count,
            'total_time': total_time,
            'final_entities': final.get('entities', 0) if final else 0,
            'final_events': final.get('events', 0) if final else 0,
            'final_objects': final.get('objects', 0) if final else 0,
            'results': results
        }
    else:
        return {
            'model_id': model_id,
            'model_name': model_name,
            'success_rate': 0,
            'error': 'All requests failed'
        }

def compare_and_decide(kimi: dict, llama: dict) -> bool:
    """对比并决策"""
    print(f"\n{'='*70}")
    print(f"📊 对比结果")
    print(f"{'='*70}")
    
    if 'error' in kimi or 'error' in llama:
        print("❌ 测试未完成")
        return False
    
    print(f"\n成功率:")
    print(f"  Kimi:  {kimi['success_rate']*100:.0f}%")
    print(f"  Llama: {llama['success_rate']*100:.0f}%")
    
    print(f"\n响应速度:")
    print(f"  Kimi:  {kimi['avg_time']:.1f}s/轮 (总{kimi['total_time']:.1f}s)")
    print(f"  Llama: {llama['avg_time']:.1f}s/轮 (总{llama['total_time']:.1f}s)")
    
    speed_diff = (kimi['avg_time'] - llama['avg_time']) / kimi['avg_time'] * 100
    if speed_diff > 0:
        print(f"  💡 Llama快 {speed_diff:.1f}%")
    else:
        print(f"  💡 Kimi快 {-speed_diff:.1f}%")
    
    print(f"\n状态提取:")
    print(f"  Kimi:  {kimi['final_entities']}实体 {kimi['final_events']}事件 {kimi['final_objects']}物品")
    print(f"  Llama: {llama['final_entities']}实体 {llama['final_events']}事件 {llama['final_objects']}物品")
    
    # 计算质量分数
    kimi_score = kimi['final_entities'] + kimi['final_events']*2 + kimi['final_objects']
    llama_score = llama['final_entities'] + llama['final_events']*2 + llama['final_objects']
    
    print(f"\n质量评分 (实体+事件×2+物品):")
    print(f"  Kimi:  {kimi_score}分")
    print(f"  Llama: {llama_score}分")
    
    quality_ratio = llama_score / max(kimi_score, 1)
    quality_diff = abs(1 - quality_ratio) * 100
    
    print(f"\n{'='*70}")
    print(f"🎯 结论")
    print(f"{'='*70}")
    
    # 判断标准
    good_success = llama['success_rate'] >= 0.8
    good_quality = quality_ratio >= 0.85  # 允许15%质量差异
    
    if good_success and good_quality:
        print(f"✅ Llama-3.3-70B 表现良好:")
        print(f"   - 成功率: {llama['success_rate']*100:.0f}%")
        print(f"   - 质量: {quality_ratio*100:.0f}% (相差{quality_diff:.1f}%)")
        
        if speed_diff > 0:
            print(f"   - 速度: 快{speed_diff:.1f}%")
        elif speed_diff > -20:
            print(f"   - 速度: 略慢{-speed_diff:.1f}% (可接受)")
        
        print(f"\n✅ 推荐: 可以替换为 Llama-3.3-70B")
        return True
    else:
        print(f"⚠️  Llama-3.3-70B 表现不足:")
        if not good_success:
            print(f"   - 成功率低: {llama['success_rate']*100:.0f}%")
        if not good_quality:
            print(f"   - 质量差异大: {quality_diff:.1f}%")
        
        print(f"\n❌ 不推荐替换，保持Kimi")
        return False

def main():
    print("🔬 Llama vs Kimi 快速对比测试\n")
    
    try:
        # 测试Kimi
        kimi = test_model_simple('kimi-k2-0905-preview', 'Kimi', 'compare')
        
        time.sleep(3)
        
        # 测试Llama  
        llama = test_model_simple('Llama-3.3-70B', 'Llama-3.3-70B', 'compare')
        
        # 保存结果
        result = {
            'kimi': kimi,
            'llama': llama,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        Path('model_comparison_result.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        
        # 对比决策
        can_replace = compare_and_decide(kimi, llama)
        
        return can_replace
        
    finally:
        restore_config()

if __name__ == '__main__':
    can_replace = main()
    print(f"\n{'='*70}\n")
    exit(0 if can_replace else 1)
