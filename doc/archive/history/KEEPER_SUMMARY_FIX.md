# Keeper Summary 修复文档

## 问题描述

Keeper的12轮一次summary不生成总结。具体表现为：
- `keeper_record_archive.json` 中的 `records` 字段为空数组
- 即使有足够的对话历史，也无法生成中程窗口摘要

## 根本原因

1. **过滤条件过于严格**：在 `keeper_archive.py` 中，即使 `build_mid_window_digest` 成功生成了digest，也会因为以下条件被过滤掉：
   - 要求至少2个 `stable_entities`（实际很多场景只有1个主要实体）
   - 要求必须同时有 `ongoing_events` 或 `open_loops`

2. **LLM调用可能阻塞**：`mid_context_agent.py` 中调用 `state_keeper_candidate` 角色的LLM可能因为API问题超时或阻塞，虽然有fallback到heuristic的机制，但超时时间过长（120秒）

## 修复内容

### 1. 放宽过滤条件 (keeper_archive.py:76-82)

**修改前：**
```python
if len(digest.get('stable_entities', []) or []) < 2:
    continue
if not (digest.get('ongoing_events') or digest.get('open_loops')):
    continue
records.append(digest)
```

**修改后：**
```python
# 放宽过滤条件：只需要有实体或有事件/线索即可
has_entities = len(digest.get('stable_entities', []) or []) >= 1
has_content = (digest.get('ongoing_events') or digest.get('open_loops') or 
              digest.get('tracked_objects') or digest.get('history_digest'))
if not (has_entities or has_content):
    continue
records.append(digest)
```

**改进说明：**
- 实体要求从 ≥2 降低到 ≥1
- 内容检查扩展到包括 `tracked_objects` 和 `history_digest`
- 只要有实体或有内容即可，不要求两者同时满足

### 2. 添加LLM跳过选项 (mid_context_agent.py:292-298)

**新增参数：**
```python
def build_mid_window_digest(
    *,
    history: list[dict],
    hard_anchors: dict,
    max_pairs: int = 10,
    use_llm: bool = True,  # 新增
) -> dict:
```

**新增逻辑：**
```python
# 允许调用方禁用 LLM 直接使用 heuristic
if not use_llm:
    return _heuristic_digest(mid_pairs, hard_anchors, from_turn, to_turn)
```

### 3. 在keeper_archive中传递use_llm参数

**keeper_archive.py:20**
```python
def build_keeper_record_archive(
    session_id: str, 
    *, 
    window_size: int = 10, 
    overlap_recent_pairs: int = 3, 
    skip_bootstrap: bool = False,  # 新增
    use_llm: bool = True  # 新增
) -> dict:
```

**keeper_archive.py:60-71**
```python
digest = build_mid_window_digest(
    history=flat_history,
    hard_anchors={...},
    max_pairs=window_size,
    use_llm=use_llm,  # 传递参数
)
```

### 4. 改进异常日志 (mid_context_agent.py:317-321)

**修改前：**
```python
except Exception:
    return _heuristic_digest(mid_pairs, hard_anchors, from_turn, to_turn)
```

**修改后：**
```python
except Exception as e:
    import logging
    _logger = logging.getLogger(__name__)
    _logger.warning('Mid-context LLM digest failed (%s), using heuristic fallback', str(e)[:100])
    return _heuristic_digest(mid_pairs, hard_anchors, from_turn, to_turn)
```

## 测试验证

### 测试1：使用现有session验证

```bash
cd /root/Threadloom
python3 test_keeper_summary.py http-10turn-audit-001 --timeout 10
```

**结果：**
- ✅ 成功生成 2 条 keeper records
- ✅ Archive 已保存
- ✅ Summary 正常生成（1575字符）

### 测试2：检查生成的records

```python
# 查看生成的keeper records
import json
with open('runtime-data/.../keeper_record_archive.json') as f:
    archive = json.load(f)
    print(f"Records: {len(archive['records'])}")
    for record in archive['records']:
        print(f"  Window: {record['window']['from_turn']} - {record['window']['to_turn']}")
```

## 使用建议

### 1. 生产环境推荐配置

如果LLM API不稳定或经常超时，建议在调用时使用heuristic模式：

```python
from keeper_archive import build_keeper_record_archive

# 快速模式：跳过bootstrap和LLM
archive = build_keeper_record_archive(
    session_id, 
    skip_bootstrap=True,  # 跳过NPC/Object/Clue bootstrap
    use_llm=False  # 使用heuristic而非LLM
)
```

### 2. 质量优先配置

如果追求最高质量的summary，且LLM API稳定：

```python
# 完整模式：使用所有LLM功能
archive = build_keeper_record_archive(
    session_id,
    skip_bootstrap=False,  # 完整的bootstrap处理
    use_llm=True  # 使用LLM生成digest
)
```

### 3. 混合模式

```python
# 跳过bootstrap但使用LLM生成digest
archive = build_keeper_record_archive(
    session_id,
    skip_bootstrap=True,  # 避免bootstrap LLM调用
    use_llm=True  # 但保留digest的LLM生成
)
```

## 质量对比

### Heuristic模式
- **优点**：快速、可靠、不依赖API
- **缺点**：可能遗漏一些语义理解
- **适用场景**：API不稳定、需要快速响应、对质量要求不是极高

### LLM模式
- **优点**：语义理解更准确、能识别隐含关系
- **缺点**：可能超时、依赖API可用性
- **适用场景**：API稳定、追求最高质量、可以接受较长处理时间

## 后续建议

1. **监控LLM调用成功率**：在日志中记录LLM digest成功/失败比例
2. **考虑添加配置项**：在runtime.json中添加全局配置控制是否使用LLM
3. **优化heuristic算法**：持续改进_heuristic_digest的质量
4. **保持窗口稳定**：archive refresh 应优先按窗口 upsert，不应反复重写已稳定的旧窗口
5. **处理撤回/重试**：refresh 前需要按当前有效 pair count prune `end_pair_index` 更大的未来 records，避免 undo / regenerate 后旧分支污染召回

## 当前追加的写入质量约束

本修复文档最初只覆盖 keeper archive records 生成问题。当前 keeper 写入质量链路又补充了以下约束：

- `knowledge_scope` 只保留本轮新增知情 delta，不再长期合并旧 scope。
- 长期知识由 actor-id 版 `knowledge_records` 保存，并在同一 holder 下做轻量相似去重。
- keeper object patch 不应因为更新 possession / visibility 而回填 baseline 全量对象。
- 物件消耗、摧毁、遗失或归档通过 `lifecycle_status` 表达，并写入 `graveyard_objects`。
- `possession_state` / `object_visibility` 允许本轮合法新状态覆盖旧状态；非法 holder 不覆盖旧合法归属。
- `keeper_record_archive.json` 是派生缓存，刷新前会 prune rollback 后的未来 records。

## 相关文件

- `backend/keeper_archive.py` - archive 构建
- `backend/keeper_record_retriever.py` - archive 刷新、safe-mode 默认值与 rollback prune
- `backend/state_keeper.py` - fill-mode prompt、knowledge/object patch 清洗
- `backend/state_bridge.py` - state 标准化、object lifecycle、holder 合法覆盖、knowledge delta
- `backend/actor_registry.py` - actor-id 绑定与 `knowledge_records` 相似去重
- `backend/mid_context_agent.py` - LLM调用和heuristic fallback
- `backend/summary_updater.py` - Summary文本生成
- `test_keeper_summary.py` - 测试脚本
