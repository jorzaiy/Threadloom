# Threadloom Backend

第一版后端仍采用 Python 标准库实现，目标是先跑通最小链路，不先引入额外框架依赖。

## 当前文件

- `server.py`：HTTP 服务入口
- `handler_message.py`：`POST /api/message` 主链入口
- `runtime_store.py`：session 目录、文件读写（原子写入）与状态快照
- `bootstrap_session.py`：新 session bootstrap
- `context_builder.py`：runtime 上下文装配，当前 narrator 主链为 `recent window + keeper archive`
- `narrator_input.py`：narrator prompt 拼装；含 `_format_knowledge_scope()` 渲染结构化知情边界
- `model_config.py` / `model_client.py`：模型配置与模型调用（含 429/503 自动重试）
- `local_model_client.py`：本地模型调用（含 429/503 自动重试）
- `card_hints.py`：卡级语义提示加载器，从 `character-data.json["hints"]` 读取实体分类 token、NPC 角色映射、persona 原型等
- `state_bridge.py`：root `memory/state.md` 到 session-local `state.json` 的桥接；含 `_merge_knowledge_scope()` 增量合并
- `state_keeper.py`：优先用统一模型调用链提取结构化 state（数据驱动，不依赖特定角色卡）；fill prompt 已扩展为同时提取 `knowledge_scope` 增量
- `state_updater.py`：`state_keeper` 失败时的保守兜底（仅延续上一轮状态 + generic 推理）
- `summary_updater.py`：围绕当前 state + 最近 turn 生成 session-local summary；当前主要作为写回 / 调试产物，不再进入 narrator 主输入
- `persona_updater.py` / `persona_runtime.py`：session-local persona 流转与展示骨架
- `arbiter_runtime.py` / `arbiter_state.py`：最小 arbiter 主链与状态合并
- `turn_analyzer.py`：用户输入 + scene signal 的统一分析层
- `thread_tracker.py`：active threads 更新；按类型分级保留（`THREAD_RETENTION_CONFIG`），含 `cooling_down` 中间态和 `resolved_events` 归档
- `important_npc_tracker.py` / `continuity_resolver.py`：重要人物与连续性稳定器
- `opening.py`：opening 菜单与开局状态机
- `card_importer.py` / `import_character_card.py`：角色卡导入与规范化产物生成
- `character_assets.py`：角色卡 source 目录下的导入产物与封面资产读取
- `session_lifecycle.py`：new game / delete / session list
- `regenerate_turn.py`：partial 回复回滚与重试

## 当前主策略

当前已经不是 stub backend，而是最小可运行主链：
- narrator 已接上真实模型调用
- 新 session 会继承 root `canon / summary / state`
- state / summary / persona / threads / important NPC 都已接入 session-local 写回
- narrator 当前已经收敛为两层上下文主链：
  - 最近 `10` 对 turn 直给 narrator
  - 更早历史只走 keeper archive 命中
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
- narrator 对“半句中止但 provider 未标 partial”的返回增加了不完整输出保护，避免坏回复继续污染事实层
- state fallback 现在会更严格地区分“可持续追踪物件”和“短语残片 / 动作词片段”
- 已支持对旧污染 session 做离线重建，直接修复 `state / threads / important_npcs / summary`
- state snapshot 已可直接提供前端实体展示结构
- web 配置项中的 `default_debug / show_debug_panel / history_page_size` 已可驱动 API 与前端
- 前端默认会话选择已改为最近更新会话优先
- 角色卡侧栏已动态读取角色卡元数据和缩略封面图
- narrator prompt 已加入更通用的知情边界约束，减少 NPC 间私下信息自动外溢
- NPC 间信息隔离已升级为结构化 `knowledge_scope` 系统：state 中追踪 `protagonist.learned[]` 和 `npc_local.{name}.learned[]`，keeper 按回合提取增量，`state_bridge.py` 合并去重，`narrator_input.py` 渲染为结构化知情边界
- 所有文件写入已改为原子写入模式（`_atomic_write_text()` / `_atomic_write_json()`）：写临时文件 → fsync → `os.replace`（POSIX 原子），防止崩溃/断电导致数据损坏
- 模型调用已加入 API 韧性层：`_retry_on_rate_limit` 装饰器在 429/503 错误时自动指数退避重试（最多 3 次），尊重 `Retry-After` 响应头；远端和本地模型调用均已覆盖
- `summary` 与独立 `mid digest` 当前不再作为 narrator prompt 的主输入块
- 世界书注入当前已改成预算驱动，避免 `alwaysOn` 与整段 lore 压过最近窗口
 - 世界书预算当前已细化到 `runtimeScope / entryType`：
  - foundation 与 situational 分开限额
  - `rule / world / faction / history / entry` 可分别限额
  - `archive_only` 条目直接排除，不进入 narrator
- turn trace / debug 当前会自动记录：
  - 实际注入的 lorebook 条目列表
  - 每条条目的 `entryType / runtimeScope / priority / injected_chars`
  - `【世界书】` 总字符数
  - prompt 各大区块字符占比

## 当前配置边界

当前配置层已经分成两类：

- 共享配置：
  - `config/runtime.json`
  - 用于内容层来源、全局运行策略、默认模型参数

- 用户配置：
  - `runtime-data/<user>/config/site.json`
  - `runtime-data/<user>/config/model-runtime.json`
  - 用于当前用户自己的站点、模型选择

当前明确结论：
- 单用户当前可用，默认用户目录是主工作路径
- 单站点是当前产品层简化，不是永久平台承诺
- `Narrator / State Keeper` 已有用户级模型选择
- `Analyzer / Arbiter / Skeleton Keeper` 这类高级角色当前不暴露给普通用户界面，但已可通过用户级 `model-runtime.json -> advanced_models` 做高级覆盖
- 当前角色卡管理也已进入 Web UI：
  - 当前用户角色卡列表可枚举
  - 可切换当前活跃角色卡
  - 可在设置面板内导入新的角色卡
  - 当前默认用户标签固定显示为 `default_user`
  - 当前阶段不做用户管理，只在接口和展示层保留用户作用域

当前建议配模方向：
- narrator 继续使用强远端模型
- `state_keeper` 线上和线下均以 `gemma-4-31b-it` 为主力模型
- skeleton keeper 和 fill keeper 均使用同一模型，通过 prompt 分工
- 当前 keeper 主链路是：
  - `skeleton keeper`（`gemma-4-31b-it`）→ 最小骨架
  - `fill keeper`（`gemma-4-31b-it`）→ 补次级字段
  - `heuristic fallback` → 最终兜底
- turn_analyzer 可在 narrator 不变前提下评估是否跟着切本地

当前 keeper 调教样本分工：

- `维克托·奥古斯特`
  - 用于校准结构清晰场景下的：
    - `main_event`
    - `scene_core`
    - `threads`
    - `objects`

- `九幽大陆`
  - 用于校准无系统级 NPC 前提下的：
    - 动态 NPC 抽取
    - 长文探险线物件/线程稳定性
    - keeper archive 延续性
  - 当前已经证明：
    - `gemma-4-31b-it` 可以在中等窗口长跑中稳定保住人物、主事件、线程
    - 弱语义 `role_label` 已开始生效，不再长期全部停在 `待确认`

- `血蚀纪`
  - 用于校准：
    - 日常互动型文本的场景锚点
    - 事件标签
    - 假人物过滤

## 角色卡导入 v0.3

当前推荐的角色卡导入产物已经改成分层结构，而不是把 Tavern 原字段直接散落到运行时文件：

- `character-data.json`
  - 只保留角色核心、简介、来源信息、精简系统摘要
- `lorebook.json`
  - 只保留规范化世界书条目
  - 导入器会为条目补 `entryType / runtimeScope / featured`
  - 当前主要用于区分：
    - foundation 底板规则 / 世界观条目
    - situational 场景相关 lore
    - NPC / cast / faction 等可调入层
 - 对旧卡可使用：
   - `python3 backend/migrate_lorebook_metadata.py`
   - 为既有 `lorebook.json` 回填上述 metadata
- `openings.json`
  - 开局菜单、开局 bootstrap、开局选项
- `system-npcs.json`
  - 从导入卡中明确提取出的系统级 NPC
  - 当前分成：
    - `core`：最明确、最值得直接进入运行时的人物
    - `faction_named`：势力条目中的命名人物
    - `roster`：更边缘的命名人物，只做存档
- `import-manifest.json`
  - 导入来源、产物路径、统计信息
- `assets/`
  - 封面图与缩略图
- `imported/`
  - raw card 与原始 PNG 备份

当前导入命令：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.png
```

或：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.raw-card.json
```

当前运行时的消费方式：

- `opening.py` 优先读取 `openings.json`
- `context_builder.py` 优先读取 `system-npcs.json`，再补世界书 NPC 候选
- 当前 narrator 默认优先只吃 `system-npcs.core`
- `faction_named / roster` 当前主要用于存档和后续导入器调优，不默认高频注入
- `runtime_store.py` / `server.py` 优先读取 `assets/` 下的角色卡封面

当前目标不是“导得越多越好”，而是：

- 只保留对 runtime 真正有价值的结构产物
- 把“世界知识”“开局菜单”“系统级 NPC”“封面资产”明确拆开
- 减少旧 Tavern 前端字段、视觉字段、规则缝合内容直接污染运行时

## API Key 安全

`model_config.py` 支持环境变量引用：在 `providers.json` 的 `apiKey` 字段中使用 `$ENV_VAR_NAME` 或 `env:ENV_VAR_NAME` 格式即可从环境变量读取密钥。

## 当前仍不稳定的部分

- `state_keeper` 仍主要从 narrator prose 反提 state
- arbiter 仍主要覆盖少数高风险事件类型
- analyzer / state keeper 虽已分模，但默认配置仍偏实验态
- 主角 runtime 仍未独立落地
- ~~NPC 间信息隔离仍未独立成结构化 knowledge scope 层~~ → 已补 `knowledge_scope`
- ~~已解决事件归档层仍未独立落地~~ → 已补 `resolved_events`
