#!/usr/bin/env python3
"""
测试skeleton keeper的影响
对比开启vs关闭skeleton的状态质量差异
"""
import json
import requests
import time
from pathlib import Path

BASE_URL = "http://localhost:8765"
CONFIG_PATH = Path("config/runtime.json")
BACKUP_PATH = Path("config/runtime.json.backup")

TEST_MESSAGES = [
    "我走进热闹的市集，看到一个卖糖葫芦的老汉和一个卖布的商贩",
    "我走向卖糖葫芦的老汉，他递给我一串糖葫芦",
    "老汉低声说最近城里不太平，让我小心陌生人",
    "我注意到远处有个穿灰衣的人在盯着我看",
    "那人突然转身离开，我决定跟上去",
    "跟到一条小巷，那人进入了一家药铺",
    "我推门进入药铺，里面坐着一位药铺掌柜",
    "掌柜看了我一眼，问我要买什么药",
    "我说我要找刚才进来的那个灰衣人",
    "掌柜说没看到什么灰衣人，让我离开",
]

def read_config():
    """读取配置"""
    return json.loads(CONFIG_PATH.read_text())

def write_config(config):
    """写入配置"""
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))

def backup_config():
    """备份配置"""
    config = read_config()
    BACKUP_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    print(f"✅ 配置已备份")
    return config

def restore_config():
    """恢复配置"""
    if BACKUP_PATH.exists():
        config = json.loads(BACKUP_PATH.read_text())
        write_config(config)
        BACKUP_PATH.unlink()
        print(f"✅ 配置已恢复")

def set_skeleton_enabled(enabled: bool):
    """设置skeleton keeper"""
    config = read_config()
    
    # 确保memory配置存在
    if 'memory' not in config:
        config['memory'] = {}
    
    config['memory']['skeleton_keeper_enabled'] = enabled
    write_config(config)
    
    status = "开启" if enabled else "关闭"
    print(f"✅ Skeleton keeper已{status}")
    time.sleep(2)  # 等待配置生效

def send_message(session_id: str, text: str) -> dict:
    """发送消息"""
    start = time.time()
    try:
        resp = requests.post(f"{BASE_URL}/api/message",
                            json={'session_id': session_id, 'text': text},
                            timeout=120)
        elapsed = time.time() - start
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                'success': True,
                'elapsed': elapsed,
                'reply': data.get('reply', ''),
                'state_snapshot': data.get('state_snapshot', {}),
                'debug': data.get('debug', {}),
            }
        else:
            return {
                'success': False,
                'elapsed': elapsed,
                'error': f"HTTP {resp.status_code}"
            }
    except Exception as e:
        return {
            'success': False,
            'elapsed': time.time() - start,
            'error': str(e)
        }

def get_state_quality(session_id: str) -> dict:
    """获取状态质量指标"""
    char_dir = Path(f"runtime-data/default-user/characters/碎影江湖/sessions/{session_id}/memory")
    
    quality = {
        'scene_entities': 0,
        'npcs': 0,
        'objects': 0,
        'clues': 0,
    }
    
    # 读取state
    state_file = char_dir / "state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        quality['scene_entities'] = len(state.get('scene_entities', []))
    
    # 读取npc_registry
    npc_file = char_dir / "npc_registry.json"
    if npc_file.exists():
        npcs = json.loads(npc_file.read_text())
        quality['npcs'] = len(npcs.get('entities', []))
    
    # 读取object_registry
    obj_file = char_dir / "object_registry.json"
    if obj_file.exists():
        objs = json.loads(obj_file.read_text())
        quality['objects'] = len(objs.get('entities', []))
    
    # 读取clue_registry
    clue_file = char_dir / "clue_registry.json"
    if clue_file.exists():
        clues = json.loads(clue_file.read_text())
        quality['clues'] = len(clues.get('entries', []))
    
    return quality

def test_session(session_id: str, skeleton_enabled: bool) -> dict:
    """测试单个session"""
    mode = "开启Skeleton" if skeleton_enabled else "关闭Skeleton"
    print(f"\n{'='*70}")
    print(f"🧪 测试: {mode}")
    print(f"📝 Session: {session_id}")
    print(f"{'='*70}")
    
    set_skeleton_enabled(skeleton_enabled)
    
    results = []
    total_time = 0
    
    for i, msg in enumerate(TEST_MESSAGES, 1):
        print(f"\n[{i}/{len(TEST_MESSAGES)}] {msg[:50]}...")
        
        result = send_message(session_id, msg)
        
        if result['success']:
            state = result['state_snapshot']
            quality = get_state_quality(session_id)
            
            print(f"  ✅ {result['elapsed']:.1f}s")
            print(f"     Scene实体:{quality['scene_entities']} "
                  f"NPC:{quality['npcs']} "
                  f"物品:{quality['objects']} "
                  f"线索:{quality['clues']}")
            
            results.append({
                'round': i,
                'success': True,
                'elapsed': result['elapsed'],
                **quality
            })
            
            total_time += result['elapsed']
        else:
            print(f"  ❌ 失败: {result['error']}")
            results.append({
                'round': i,
                'success': False,
                'error': result['error']
            })
        
        time.sleep(1)
    
    # 统计
    success = [r for r in results if r['success']]
    
    if success:
        final = success[-1]
        summary = {
            'mode': mode,
            'session_id': session_id,
            'skeleton_enabled': skeleton_enabled,
            'success_rate': len(success) / len(TEST_MESSAGES),
            'avg_time': total_time / len(success),
            'total_time': total_time,
            'final_quality': {
                'scene_entities': final['scene_entities'],
                'npcs': final['npcs'],
                'objects': final['objects'],
                'clues': final['clues'],
            },
            'results': results
        }
        
        print(f"\n📊 {mode} 结果:")
        print(f"  成功率: {summary['success_rate']*100:.0f}%")
        print(f"  平均耗时: {summary['avg_time']:.1f}秒")
        print(f"  最终质量: NPC={final['npcs']} "
              f"物品={final['objects']} "
              f"线索={final['clues']}")
        
        return summary
    
    return {
        'mode': mode,
        'error': 'All failed'
    }

def compare_results(with_skeleton: dict, without_skeleton: dict):
    """对比结果"""
    print(f"\n{'='*70}")
    print(f"📊 对比分析")
    print(f"{'='*70}")
    
    if 'error' in with_skeleton or 'error' in without_skeleton:
        print("❌ 测试未完成，无法对比")
        return
    
    # 速度对比
    print(f"\n【速度】")
    print(f"  开启Skeleton: {with_skeleton['avg_time']:.1f}秒/轮")
    print(f"  关闭Skeleton: {without_skeleton['avg_time']:.1f}秒/轮")
    
    time_diff = (with_skeleton['avg_time'] - without_skeleton['avg_time']) / with_skeleton['avg_time'] * 100
    if time_diff > 0:
        print(f"  💡 关闭后快 {time_diff:.1f}%")
    else:
        print(f"  💡 开启后快 {-time_diff:.1f}%")
    
    # 质量对比
    print(f"\n【最终状态质量】")
    
    with_q = with_skeleton['final_quality']
    without_q = without_skeleton['final_quality']
    
    print(f"  开启Skeleton:")
    print(f"    NPC: {with_q['npcs']}, 物品: {with_q['objects']}, 线索: {with_q['clues']}")
    
    print(f"  关闭Skeleton:")
    print(f"    NPC: {without_q['npcs']}, 物品: {without_q['objects']}, 线索: {without_q['clues']}")
    
    # 计算质量差异
    npc_diff = (without_q['npcs'] - with_q['npcs']) / max(with_q['npcs'], 1) * 100
    obj_diff = (without_q['objects'] - with_q['objects']) / max(with_q['objects'], 1) * 100
    clue_diff = (without_q['clues'] - with_q['clues']) / max(with_q['clues'], 1) * 100
    
    print(f"\n【质量差异】")
    print(f"  NPC: {npc_diff:+.1f}%")
    print(f"  物品: {obj_diff:+.1f}%")
    print(f"  线索: {clue_diff:+.1f}%")
    
    # 结论
    print(f"\n{'='*70}")
    print(f"🎯 结论")
    print(f"{'='*70}")
    
    quality_acceptable = abs(npc_diff) < 30 and abs(obj_diff) < 30
    speed_improved = time_diff > 20
    
    if quality_acceptable and speed_improved:
        print(f"✅ 关闭Skeleton是可行的:")
        print(f"   - 速度提升 {time_diff:.1f}%")
        print(f"   - 质量损失可接受 (NPC {npc_diff:+.1f}%, 物品 {obj_diff:+.1f}%)")
        print(f"\n💡 推荐: 可以关闭skeleton keeper")
        return True
    elif not quality_acceptable:
        print(f"⚠️  关闭Skeleton会影响质量:")
        print(f"   - NPC变化 {npc_diff:+.1f}%")
        print(f"   - 物品变化 {obj_diff:+.1f}%")
        print(f"\n💡 建议: 保持skeleton keeper开启")
        return False
    else:
        print(f"⚠️  关闭Skeleton速度提升不明显:")
        print(f"   - 仅快 {time_diff:.1f}%")
        print(f"\n💡 建议: 保持skeleton keeper开启")
        return False

def main():
    print("🔬 Skeleton Keeper 影响测试")
    print("="*70)
    
    backup_config()
    
    try:
        # 测试1: 开启skeleton
        with_skeleton = test_session(
            f"skeleton-test-on-{int(time.time())}",
            skeleton_enabled=True
        )
        
        time.sleep(3)
        
        # 测试2: 关闭skeleton
        without_skeleton = test_session(
            f"skeleton-test-off-{int(time.time())}",
            skeleton_enabled=False
        )
        
        # 对比
        can_disable = compare_results(with_skeleton, without_skeleton)
        
        # 保存结果
        result = {
            'with_skeleton': with_skeleton,
            'without_skeleton': without_skeleton,
            'recommendation': 'disable' if can_disable else 'keep',
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        Path('skeleton_test_result.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        
        print(f"\n💾 结果已保存到: skeleton_test_result.json")
        
        return can_disable
        
    finally:
        restore_config()

if __name__ == '__main__':
    can_disable = main()
    print(f"\n{'='*70}\n")
    exit(0 if can_disable else 1)
