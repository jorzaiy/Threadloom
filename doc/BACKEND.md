# Threadloom Backend

第一版后端仍采用 Python 标准库实现，目标是先跑通最小链路，不先引入额外框架依赖。

## 当前文件

- `server.py`：HTTP 服务入口
- `handler_message.py`：`POST /api/message` 主链入口
- `runtime_store.py`：session 目录、文件读写与状态快照
- `bootstrap_session.py`：新 session bootstrap
- `context_builder.py`：runtime 上下文装配
- `narrator_input.py`：narrator prompt 拼装
- `model_config.py` / `model_client.py`：模型配置与模型调用
- `card_hints.py`：卡级语义提示加载器，从 `character-data.json["hints"]` 读取实体分类 token、NPC 角色映射、persona 原型等
- `state_bridge.py`：root `memory/state.md` 到 session-local `state.json` 的桥接
- `state_keeper.py`：优先用统一模型调用链提取结构化 state（数据驱动，不依赖特定角色卡）
- `state_updater.py`：`state_keeper` 失败时的保守兜底（仅延续上一轮状态 + generic 推理）
- `summary_updater.py`：围绕当前 state + 最近 turn 生成 session-local summary
- `persona_updater.py` / `persona_runtime.py`：session-local persona 流转与展示骨架
- `arbiter_runtime.py` / `arbiter_state.py`：最小 arbiter 主链与状态合并
- `turn_analyzer.py`：用户输入 + scene signal 的统一分析层
- `thread_tracker.py`：active threads 更新
- `important_npc_tracker.py` / `continuity_resolver.py`：重要人物与连续性稳定器
- `opening.py`：opening 菜单与开局状态机
- `session_lifecycle.py`：new game / delete / session list
- `regenerate_turn.py`：partial 回复回滚与重试

## 当前主策略

当前已经不是 stub backend，而是最小可运行主链：
- narrator 已接上真实模型调用
- 新 session 会继承 root `canon / summary / state`
- state / summary / persona / threads / important NPC 都已接入 session-local 写回
- `state_keeper` 优先，`state_updater` 兜底
- arbiter 已接入主链，不再只是文档占位
- partial reply 有独立处理路径，不再继续污染事实层
- opening 已升级为独立状态机
- session 生命周期已覆盖：新游戏、切换、删除、partial regenerate
- 同一 `session_id` 的写请求现会串行执行，降低并发写冲突
- `state_keeper` 已加入低信号拒收与回归检查
- `state_fragment` 已前移到 narrator / state_keeper 主链，并在失败分支提供 `fragment-baseline`
- `state_keeper_candidate` 当前可作为 `skeleton keeper` sidecar 先产出最小骨架，并并入 `state_fragment` 再交给完整 keeper
- 完整 `state_keeper` 当前已切到 `fill-mode`：先以 `state_fragment + skeleton` 形成基线，再只补次级字段
- `state_updater` 已更偏保守继承，不轻易覆盖已有高信号状态
- 已支持对旧污染 session 做离线重建，直接修复 `state / threads / important_npcs / summary`
- state snapshot 已可直接提供前端实体展示结构
- web 配置项中的 `default_debug / show_debug_panel / history_page_size` 已可驱动 API 与前端
- 前端默认会话选择已改为最近更新会话优先
- 角色卡侧栏已动态读取角色卡元数据和缩略封面图
- narrator prompt 已加入更通用的知情边界约束，减少 NPC 间私下信息自动外溢

当前建议配模方向：
- narrator 继续使用强远端模型
- state_keeper 优先切到稳定的本地结构化模型，并以保守结构化提取模式运行
- 更强的远端 keeper 候选当前更适合作为 `skeleton keeper` 使用，先只负责最小骨架状态，而不直接替换完整 keeper
- 当前 keeper 主链组合已经是：`skeleton keeper -> fill-mode keeper -> heuristic fallback`
- turn_analyzer 可在 narrator 不变前提下评估是否跟着切本地

## 泛化架构

所有卡特定逻辑已从代码移到数据层：

- `character-data.json["hints"]` 定义卡级语义提示（实体分类 token、NPC 角色映射、persona 原型等）
- `card_hints.py` 提供统一的查询接口，所有模块通过它读取配置
- 没有 hints 的角色卡也能正常工作：token 过滤器为空（不误杀实体），role_label 回退为 `待确认`，LLM keeper 承担全部语义理解
- state_keeper / state_bridge / important_npc_tracker / persona_runtime / persona_updater 均已改为数据驱动
- state_updater 的 legacy heuristic 已简化为保守延续策略，不再包含卡特定推理

### hints 字段说明

```json
{
  "hints": {
    "environment_tokens": ["巷口", "雨", ...],
    "transient_group_tokens": ["路人", "闲人", ...],
    "non_character_object_tokens": ["油布包", "纸卷", ...],
    "generic_target_tokens": ["被围", "伤者", ...],
    "service_role_tokens": ["掌柜", "伙计", ...],
    "known_npc_roles": {"师兄": "同行伤者 / 师兄", ...},
    "npc_canonical_mappings": {"领头皂衣人": "高个皂衣人", ...},
    "time_era_prefix": "承和十二年",
    "persona_archetypes": [
      {"match_tokens": ["掌柜", "老板"], "mbti": "ISTJ", "archetype": "秩序维护者", ...}
    ]
  }
}
```

## API Key 安全

`model_config.py` 支持环境变量引用：在 `providers.json` 的 `apiKey` 字段中使用 `$ENV_VAR_NAME` 或 `env:ENV_VAR_NAME` 格式即可从环境变量读取密钥。

## 当前仍不稳定的部分

- `state_keeper` 仍主要从 narrator prose 反提 state
- arbiter 仍主要覆盖少数高风险事件类型
- analyzer / state keeper 虽已分模，但默认配置仍偏实验态
- 主角 runtime 与已解决事件归档层仍未独立落地
- NPC 间信息隔离仍未独立成结构化 knowledge scope 层
