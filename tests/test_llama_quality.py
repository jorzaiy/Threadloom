#!/usr/bin/env python3
"""
在已有Kimi session基础上测试Llama质量
"""
import json
import requests
import time
from pathlib import Path

BASE_URL = "http://localhost:8765"
CONFIG_PATH = Path("runtime-data/default-user/config/model-runtime.json")
BACKUP_PATH = Path("runtime-data/default-user/config/model-runtime.json.backup")

# 丰富的测试消息，确保能触发keeper
TEST_MESSAGES = [
    "我走进茶楼，里面坐着三位客人：白发老者、年轻书生和红衣女子",
    "我走向白发老者，询问他关于城中失踪案的线索",
    "老者递给我一块古玉，低声说这是破案的关键",
    "我注意到角落的书生正在偷听我们的对话",
    "书生突然起身离开，我决定跟上去",
    "跟到城外废弃寺庙，书生进入后殿消失不见",
    "我在后殿发现一个密道入口，传来诡异的笛声",
    "进入密道后，看到墙上刻满古怪符文",
    "红衣女子突然出现，她说她也在调查此案",
    "女子拿出一张泛黄的地图，指向城北的古墓",
    "我们决定结伴前往古墓，路上她讲述了自己的身世",
    "古墓入口守着两名黑衣护卫",
    # 第13轮，应该触发keeper archive
    "我使用古玉破解了墓门机关",
    "墓室中央放着一口黑色石棺",
    "石棺突然打开，里面是一具千年古尸",
]

def backup_config():
    """备份配置"""
    if not BACKUP_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
        BACKUP_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))
        print(f"✅ 配置已备份")

def set_llama():
    """切换到Llama"""
    config = json.loads(CONFIG_PATH.read_text())
    config['state_keeper'] = {'model': 'Llama-3.3-70B'}
    config['advanced_models'] = config.get('advanced_models', {})
    config['advanced_models']['state_keeper_candidate'] = {
        'provider': 'site',
        'model': 'Llama-3.3-70B',
        'temperature': 0.0,
        'max_output_tokens': 800,
        'stream': False
    }
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    print(f"✅ 已切换到 Llama-3.3-70B")

def restore_config():
    """恢复配置"""
    if BACKUP_PATH.exists():
        config = json.loads(BACKUP_PATH.read_text())
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))
        BACKUP_PATH.unlink()
        print(f"✅ 配置已恢复为Kimi")

def send_message(session_id: str, text: str) -> dict:
    """发送消息"""
    start = time.time()
    try:
        resp = requests.post(f"{BASE_URL}/api/message",
                            json={'session_id': session_id, 'text': text},
                            timeout=180)
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

def get_keeper_records(session_id: str) -> dict:
    """获取keeper records"""
    char_dir = Path(f"runtime-data/default-user/characters/碎影江湖/sessions/{session_id}")
    archive_file = char_dir / "memory" / "keeper_record_archive.json"
    
    if archive_file.exists():
        return json.loads(archive_file.read_text())
    return {'records': []}

def analyze_quality(state: dict, keeper: dict, round_num: int):
    """分析质量"""
    entities = state.get('entities', [])
    events = state.get('main_events', [])
    objects = state.get('objects', [])
    records = keeper.get('records', [])
    
    print(f"\n  📊 第{round_num}轮质量:")
    print(f"     实体: {len(entities)}")
    print(f"     事件: {len(events)}")
    print(f"     物品: {len(objects)}")
    print(f"     Keeper记录: {len(records)}")
    
    if entities:
        print(f"     - 实体样例: {', '.join([e.get('name', '') for e in entities[:3]])}")
    if events:
        print(f"     - 事件样例: {events[0][:50]}...")
    if objects:
        print(f"     - 物品样例: {', '.join([o.get('name', '') for o in objects[:3]])}")
    
    return {
        'entities': len(entities),
        'events': len(events),
        'objects': len(objects),
        'keeper_records': len(records)
    }

def test_llama_quality():
    """测试Llama质量"""
    print("🧪 Llama-3.3-70B 质量测试")
    print("="*70)
    print("策略: 用Llama在新session上运行15轮，观察keeper质量\n")
    
    backup_config()
    
    try:
        set_llama()
        time.sleep(2)
        
        session_id = f"llama-quality-test-{int(time.time())}"
        print(f"📝 Session: {session_id}\n")
        
        results = []
        total_time = 0
        
        for i, msg in enumerate(TEST_MESSAGES, 1):
            print(f"[{i}/{len(TEST_MESSAGES)}] {msg[:50]}...")
            
            result = send_message(session_id, msg)
            
            if result['success']:
                state = result['state_snapshot']
                keeper = get_keeper_records(session_id)
                
                quality = analyze_quality(state, keeper, i)
                
                print(f"  ⏱️  耗时: {result['elapsed']:.1f}秒")
                
                results.append({
                    'round': i,
                    'success': True,
                    'elapsed': result['elapsed'],
                    **quality
                })
                
                total_time += result['elapsed']
                
                # 第13轮后检查keeper
                if i == 13:
                    if quality['keeper_records'] > 0:
                        print(f"\n  ✅ 第13轮成功生成 {quality['keeper_records']} 条keeper记录！")
                    else:
                        print(f"\n  ⚠️  第13轮未生成keeper记录")
                
            else:
                print(f"  ❌ 失败: {result['error']}")
                results.append({
                    'round': i,
                    'success': False,
                    'error': result['error']
                })
            
            time.sleep(1)
        
        # 最终统计
        print(f"\n{'='*70}")
        print(f"📊 测试完成")
        print(f"{'='*70}")
        
        success = [r for r in results if r['success']]
        
        print(f"\n成功率: {len(success)}/{len(TEST_MESSAGES)} ({len(success)/len(TEST_MESSAGES)*100:.0f}%)")
        print(f"平均耗时: {total_time/len(success):.1f}秒/轮")
        print(f"总耗时: {total_time:.1f}秒")
        
        if success:
            final = success[-1]
            print(f"\n最终状态:")
            print(f"  实体: {final['entities']}")
            print(f"  事件: {final['events']}")
            print(f"  物品: {final['objects']}")
            print(f"  Keeper记录: {final['keeper_records']}")
            
            # 质量评分
            quality_score = final['entities'] + final['events']*2 + final['objects']
            print(f"\n质量评分: {quality_score} (实体 + 事件×2 + 物品)")
            
            # 判断
            print(f"\n{'='*70}")
            print(f"🎯 结论")
            print(f"{'='*70}")
            
            if len(success) >= 12 and quality_score >= 5:
                print(f"✅ Llama-3.3-70B 质量合格:")
                print(f"   - 成功率: {len(success)/len(TEST_MESSAGES)*100:.0f}%")
                print(f"   - 质量分数: {quality_score}")
                print(f"   - Keeper记录: {final['keeper_records']}条")
                print(f"\n✅ 推荐替换为 Llama-3.3-70B")
                return True
            else:
                print(f"⚠️  Llama-3.3-70B 质量不足:")
                if len(success) < 12:
                    print(f"   - 成功率低: {len(success)}/{len(TEST_MESSAGES)}")
                if quality_score < 5:
                    print(f"   - 质量分数低: {quality_score}")
                print(f"\n❌ 暂不推荐替换")
                return False
        
        # 保存结果
        Path('llama_quality_test_result.json').write_text(
            json.dumps({
                'session_id': session_id,
                'results': results,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }, ensure_ascii=False, indent=2)
        )
        
    finally:
        restore_config()

if __name__ == '__main__':
    can_replace = test_llama_quality()
    print(f"\n{'='*70}\n")
    exit(0 if can_replace else 1)
