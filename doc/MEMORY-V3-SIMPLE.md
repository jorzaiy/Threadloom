# Memory V3：分层总结记忆（实施方案）

本方案是交给实现者的执行文档。目标：用"逐轮小结 → 大总结 → 超级总结"三层结构，替换现在的 facts / entities / keeper / 证据包 / 事件索引等多层记忆。完成后由审核方对照第 12 节验收。

---

## 0. 背景与目标

**现状的问题**

叙述 prompt 由约 30 个区块拼成，每轮还要串行跑 arbiter、state_keeper、event_ledger、summary_chunks、fact_log 等环节。信息每多经过一层抽取，就多一次丢失或改名的机会。实例：第 17 轮玩家纠正"掌柜是凡人"，到第 24 轮时这条设定在上下文中已完全消失；实体表还把"掌柜"记成了"客栈掌门"。

**目标**

- 记忆链路只保留四层：逐轮小结、大总结、超级总结、当前状态。每层都可读、可手动编辑、可重新生成。
- 总结在叙述回复返回之后异步生成，不增加玩家等待时间。
- 角色卡、世界书、玩家档案、预设、开局流程**保持不变**。
- 老会话不做迁移。

---

## 1. 定案规则

| 项目 | 规则 |
|---|---|
| 回合 | 用户输入 + 叙述回复 = 1 轮，沿用现有 `turn-XXXX` 编号 |
| 逐轮小结 | 每轮 1~数句，复杂剧情可以多写。本轮出现的设定确认、玩家纠正、身份揭示、能力边界、关系变化，单独写成 `【设定】` 行。延续线索也写在小结里 |
| 当前状态 | 和小结在**同一次**模型调用中生成。字段：时间、地点、在场人物、当前目标、当前风险、重要物品持有 |
| 大总结 | 每满 100 条小结生成一份。固定四栏：剧情 / 人物档案 / 未解线索 / 设定 |
| 超级总结 | 每满 5 份大总结（500 轮）合并一份。人物档案在上一版基础上**更新**，剧情部分大幅压缩 |
| 衔接 | 新大总结生成后，它覆盖范围内的**最后 10 条小结**继续放在上下文里 |
| 原文 | 最近 8 轮 |
| 淡出 | 本段出场 → 完整档案；一整段未出场 → 压成一行；连续两段未出场且没有挂着未解线索 → 删除；带 `★` 的人物永久保留 |
| ★ | 只出现在大总结或超级总结的人物档案里，由用户手动添加。生成后由代码校验是否保留（见 6.4） |
| 模型 | 新增角色 `summarizer`，在设置里单独配置 |
| 编辑与重写 | 重新生成或删除某一轮时，只重写或删除那一轮的小结和状态。已生成的大总结不自动级联，在面板上标"可能过期"，由用户手动重做 |

---

## 2. 数据文件

所有文件放在 `<session>/memory/` 下，都用 `atomic_io` 原子写入。

### 2.1 `turn_summaries.jsonl`：每轮一行，按 turn 递增

```json
{
  "turn": 17,
  "turn_id": "turn-0017",
  "reply_hash": "sha1(本轮 assistant 原文)",
  "status": "ok",              // ok | pending | failed
  "summary": "陆小环一边拆补丁一边以灵网探查客栈……\n【设定】掌柜：凡人，无灵根，经脉无灵气；靠一枚刻纹铜钱感应阵法",
  "state_after": { ... 见 2.4 ... },
  "edited": false,             // 用户手动改过
  "error": "",
  "model": "xxx",
  "updated_at": 1790000000000
}
```

- 每条都带 `state_after`。删除或重新生成某一轮时，直接取上一轮的 `state_after` 来恢复状态，**不再依赖 turn-trace**（turn-trace 只保留 40 轮）。
- `reply_hash` 用于判断这条小结对应的原文是否已经变了，见 4.3。
- 规模估算：1000 轮约 1~2 MB，整读整写可以接受。实现方式参考 `runtime_store.save_history`，在 `_STORE_LOCK` 下读写。

### 2.2 `big_summaries.json`

```json
{
  "items": [
    {
      "index": 1,
      "turn_start": 1, "turn_end": 100,
      "status": "ok",            // ok | pending | failed
      "content": "## 剧情\n...\n## 人物档案\n★ 掌柜：...\n## 未解线索\n...\n## 设定\n...",
      "edited": false,
      "stale": false,            // 覆盖范围内的小结在生成后被改过
      "restored_stars": [],      // 6.4 中被代码自动补回的 ★ 人物
      "error": "", "model": "", "updated_at": 0
    }
  ]
}
```

### 2.3 `super_summaries.json`

结构同 2.2，`turn_start` 和 `turn_end` 跨 500 轮。另外加一个字段 `big_range: [1, 5]`，记录合并了哪几份大总结。

### 2.4 `state.json`（精简后）

```json
{
  "session_id": "...",
  "time": "丑时",
  "location": "人界，青州城，悦来客栈，天字三号房内",
  "onstage": ["掌柜", "青衫年轻人"],
  "goal": "继续运功调息，分析活物身份",
  "risks": ["掌柜可能发现阵中活物被调包"],
  "items": [{"name": "木盒（内有小猫）", "holder": "陆小环", "note": "在储物袋中"}],
  "secrets": [{"content": "…", "owner": "陆小环", "knowers": ["陆小环"], "misbelief": {"掌柜": "…"}, "suspects": {"青衫年轻人": "…"}}],
  "opening_mode": "...", "opening_resolved": true, "opening_started": false, "opening_choice": null
}
```

- `secrets` 的定义和规则见 P2.5 节。字段名以这里为准，P2.5 和 P3 两边都按这个格式实现。
- 开局相关的四个字段原样保留，`opening.py` 和 `bootstrap_session.py` 还要用。
- 实现前先 grep `opening_` 的使用处，确认没有遗漏的字段。

### 2.5 不再读写的文件

`facts.jsonl`、`entities.json`、`event_summaries.json`、`summary_chunks.json`、`keeper_record_archive.json`、`continuity_hints.json`、`summary.md`、`persona/*`。

新会话不再创建这些文件。老会话里已有的文件不删，只是不再读取。

---

## 3. 新模块：`backend/simple_memory.py`

这一个模块负责所有新逻辑。下面是建议的接口，签名可以按需调整：

```python
# 存储
load_turn_summaries(session_id) -> list[dict]
upsert_turn_summary(session_id, record) -> None
delete_turn_summaries_from(session_id, turn) -> None      # 删除 >= turn 的记录
load_big_summaries / save_big_summaries
load_super_summaries / save_super_summaries

# 上下文
build_memory_context(session_id) -> dict   # 返回 super / big / turn 三层文本，供 narrator_input 使用

# 生成（同步函数，由 worker 调用）
generate_turn_summary(session_id, turn) -> dict           # 一次模型调用，同时产出 summary 和 state
generate_big_summary(session_id, index) -> dict
generate_super_summary(session_id, index) -> dict

# 调度
enqueue_after_turn(session_id, turn)       # 每轮提交后调用
wait_idle(session_id, timeout_s) -> bool   # 下一轮开始前调用
cancel_and_wait(session_id)                # 重新生成或删除前调用
job_status(session_id) -> dict
```

prompt 模板放在 `prompts/memory/` 下：`turn-summary.md`、`big-summary.md`、`super-summary.md`。

---

## 4. 异步调度

当前后端没有任何后台执行设施：一轮对话在 HTTP 线程里同步跑完，期间持有会话锁（`server.py:442`）。需要新建一个最小的 worker。

### 4.1 Worker

- 进程内一个 `ThreadPoolExecutor(max_workers=2)`，另外维护 `dict[session_id, Future]`，保证**同一会话同一时刻最多一个任务**。
- 任务按顺序执行：
  1. 补齐缺失或失败的小结，每次最多补 3 条，避免一次占用太久；
  2. 判断是否满足大总结条件，满足就生成；
  3. 判断是否满足超级总结条件，满足就生成。
- worker 里的代码要带上用户上下文：先 `active_user_context(user_id)`，再按角色卡设置 override（参考 `paths.set_active_character_override`）。否则路径会解析到错误的用户或角色卡目录。

### 4.2 锁

- **调用模型时不持有会话锁。** 模型调用可能要几十秒，持锁会把下一条消息卡住。
- 只在**提交结果时**短暂加锁。提交前检查结果是否还有效（见 4.3），无效就丢弃。
- `server.py` 里的会话锁目前是 Handler 的内部实现，需要把它提到模块级函数，比如 `session_lock(session_id)`，让 worker 也能用。

### 4.3 有效性校验（防止和重新生成、删除产生竞争）

提交小结前，重新读一次 history，确认 `turn_id` 对应的 assistant 原文 hash 还等于 `reply_hash`。如果不等，或者这一轮已经不存在了，就丢弃结果。

大总结提交前，确认它覆盖的 100 条小结的 `updated_at` 都没有晚于任务开始的时间。如果有晚的，不丢弃结果，而是标记 `stale=true`。

### 4.4 和对话轮次的衔接

- `handle_message` 开头调用 `wait_idle(session_id, timeout_s=20)`：
  - 如果超时，不等了，直接用现有的小结和状态继续。最近 8 轮原文能兜住这个空档。
  - 第 N 轮的状态还没写完时，用第 N-1 轮的 `state_after`。
- 重新生成或删除最新一轮之前调用 `cancel_and_wait`。`Future` 已经开始执行时无法真正取消，靠 4.3 的校验丢弃结果即可。

### 4.5 失败处理

- 模型调用失败或 JSON 解析失败：记录 `status=failed` 和 `error`，下次任务时自动补跑。连续失败 3 次后停止自动重试，只能在面板上手动重试。
- 满足大总结条件、但区间内还有 failed 的小结：先补跑这些小结。补跑后仍然失败，就照常生成大总结，并在 prompt 里注明"第 X 轮小结缺失"，同时把这几轮的原文直接附在 prompt 里。

---

## 5. 叙述 prompt 组装

### 5.1 保留的区块

改动集中在 `narrator_input.py:680-1000` 和 `context_builder.py`。以下区块保留：

世界模拟引擎、runtime_rules、预设框架、角色核心、世界设定锁、玩家档案、命中玩家档案细节、命中 NPC 档案（角色卡素材）、系统级 NPC、可调入世界书 NPC、世界书基础规则、情境世界书、知情边界的**静态规则部分**、知情边界补充、推进规则、本轮裁定结果、本轮导演简报、要求、当前用户输入、近端约束提醒。

注意：`本轮导演简报` 和 `要求` 的文本里提到了"证据包"和"提纲"，需要改成新的区块名称。

### 5.2 删除的区块

人物档案·权威、往事回溯·检索、当前在场 NPC 知情核对、角色注册表、当前事件目标、NPC 表现层人格、召回的归档提纲、keeper archive 命中、历史原文证据包、命中事件索引、最近窗口前段提纲、重要物件与持有关系、知情边界里依赖 state 数据的部分。

### 5.3 新增区块（按顺序放在世界书之后、推进规则之前）

```
【长期记忆·超级总结】   所有 super_summaries（status=ok）
【阶段记忆·大总结】     最后一份超级总结之后的 big_summaries
【近期逐轮小结】        最后一份大总结 turn_end-9 之后的所有小结，每条格式 "第N轮：..."
【当前状态】            state.json 渲染（时间/地点/在场/目标/风险/物品）
【最近8轮完整上下文】   原有区块，轮数改为 8
```

- 小结如果和最近 8 轮原文重叠，**照样保留**。小结里有 `【设定】` 行，值得重复出现一次。
- `config/runtime.json` 改为 `memory.recent_full_prose_turns: 8`，`recent_history_turns` 改为 8。`narrator_input.py:858` 里的默认值也同步改成 8。
- `context_builder.py:1131` 里世界书触发用的 `recent_history[-6:]` 也改成读这个配置值。

### 5.4 世界书触发和 selector

- `context_builder.py:1114-1133` 现在用 state 里的 `carryover_signals`、`immediate_risks`、`carryover_clues`、`arbiter_signals` 拼接世界书触发文本。改成：最近 8 轮原文 + 本轮输入 + 新 state 的 `goal`、`risks`、`location`。
- `selector.build_selector_decision` 同时管世界书、NPC 候选和玩家档案细节，**不能删**。只去掉它的记忆类输入：event_summaries、summary_chunks、keeper 相关参数，以及对应的 hits 输出。改完要跑一遍世界书命中的回归测试，确认结果没有变差。

### 5.5 叙述回复的校验与重试

`_unsupported_prior_event_assertion_reason`（`handler_message.py:441`）会用 `grounding_text` 判断回复里有没有引用不存在的往事。grounding 里必须加入三层总结和小结的全文，否则模型正确引用了大总结里的往事，也会被误判为编造。

其他几项校验（`narrator_reply_rejection_reason`、场景跳跃、替玩家说话、NPC 私密知识）先保持不变。

---

## 6. Prompt 草稿

### 6.1 逐轮小结 + 状态（`prompts/memory/turn-summary.md`）

模型输入：
- 角色卡核心的简短版本
- 最近 3 条小结（用于保持称呼一致）
- 当前大总结里的人物档案栏（如果有）
- 上一轮的 state
- 本轮用户输入 + 本轮回复原文

输出 JSON（`response_format=json_object`）：

```json
{
  "summary": "一到数句，按发生顺序写本轮发生了什么；用档案里已有的称呼，不要另起名字。\n【设定】……（可多行，没有就省略）",
  "state": {"time": "", "location": "", "onstage": [], "goal": "", "risks": [], "items": [{"name":"","holder":"","note":""}]}
}
```

要求要点：
1. 以玩家角色为主语，写客观事实，不写文学描写。
2. `【设定】` 只写本轮**新确认**的设定。玩家明确纠正的内容优先级最高，要写清"玩家纠正：……"。
3. 写下本轮新出现、或有进展的线索（比如"补丁手法粗糙，疑似他人所加"）。
4. 人名、地名沿用已有档案里的写法。不确定时用原文里的称呼，**不要**升级成头衔（"掌柜"不能写成"掌门"）。
5. state 只根据本轮原文更新，原文没提到的字段保持上一轮的值。

### 6.2 大总结（`prompts/memory/big-summary.md`）

模型输入：
- 上一份大总结全文（如果有）
- 本区间 100 条小结
- 当前 state

输出 Markdown，固定四个二级标题：

```
## 剧情
按时间顺序写主要事件，每个事件 1~3 句；只保留对后续有影响的事。
## 人物档案
每人一段：名字 / 身份 / 性格 / 能力边界 / 与主角关系 / 他知道什么。
## 未解线索
每条一行，写明线索来源（第几轮前后）。
## 设定
世界规则、地点、物品的长期设定。
```

要求要点：
1. 区间内所有 `【设定】` 行都要合并进人物档案或设定栏，不能丢。如果和上一份大总结冲突，以较新的为准。
2. 人物档案要在上一份大总结的基础上**更新**，不要重写。淡出规则：本区间出场的写完整档案；本区间没出场的压成一行；上一份已经是一行、这一份仍然没出场、也没挂着未解线索的，删除。
3. 带 `★` 的人物必须保留，`★` 标记保留，档案不得压缩成一行，也不得删除。
4. 已经解决的线索从"未解线索"里移除，结果写进剧情栏。

### 6.3 超级总结（`prompts/memory/super-summary.md`）

模型输入：
- 上一份超级总结（如果有）
- 本区间 5 份大总结

输出格式同 6.2 的四栏。剧情栏压缩到每 100 轮 3~6 句。人物档案和 ★ 的规则同 6.2。

### 6.4 ★ 校验（代码实现，不依赖模型）

1. 从上一版（大总结或超级总结）的人物档案栏里，用正则 `^\s*[-*]?\s*★\s*([^\s：:（(]+)` 提取所有带 ★ 的名字。
2. 检查新生成的内容里是否包含 `★名字`。
3. 有缺失时：自动重试一次。重试后仍然缺失，就把上一版里这些人物的档案段落原样追加到新版"人物档案"栏的末尾，并把名字写入 `restored_stars`。面板上显示"已自动补回：xxx"。

---

## 7. `handle_message` 改造

### 7.1 保留

- 校验与幂等
- bootstrap
- 开局分支
- `build_runtime_context`（精简后）
- arbiter（见 7.3）
- `build_narrator_input`
- `_call_narrator_with_retries`
- 完整性检查
- `append_turn_history`
- `meta.last_turn_id += 1`
- turn audit（精简）
- `finalize_response` / turn-trace

### 7.2 删除的同步步骤

`build_state_fragment`、fact_log 的 view / recall / commit / shadow commit、`merge_reply_skeleton`、`call_skeleton_keeper`、`call_state_keeper`、`retry_possession_keeper`、`merge_arbiter_state`、`apply_thread_tracker`、`continuity hints`、`_apply_important_npc_trackers`、`_add_lightweight_knowledge_delta`、`update_actor_registry`、`canonicalize_state_memory`、`resolve_stale_state_threads`、`_apply_pending_npc_bios`、`update_summary_chunks`、event_ledger 系列、`update_summary`、`update_persona`、`_consolidate_factlog_personas`。

### 7.3 Arbiter

arbiter 属于玩法逻辑，基于规则，默认不调用模型。**保留 `run_arbiter` 和【本轮裁定结果】区块**，删除 `merge_arbiter_state`（它会往 `risks` 和线索里写固定模板文本，和新 state 冲突）。

**需要用户确认：**
- 是否把裁定结果也传给小结 prompt，作为参考输入。默认：传。
- arbiter 整体是否保留。默认：保留。

### 7.4 新的一轮流程

```
wait_idle(session, 20s)
→ 构建上下文（三层总结 + state + 8 轮原文 + 角色卡/世界书）
→ run_arbiter
→ 叙述（含重试与校验）
→ append_turn_history；meta 递增
→ 在 turn_summaries 里写一条 status=pending 的占位记录
→ enqueue_after_turn(session, turn)
→ 返回响应（state_snapshot 用上一轮的 state，附带 memory_status: pending）
```

---

## 8. 重新生成和删除（`regenerate_turn.py`）

`_rollback_derived_artifacts` 改为：

1. `cancel_and_wait(session)`
2. `delete_turn_summaries_from(session, turn)`
3. `state.json` 恢复为第 turn-1 轮的 `state_after`。如果 turn=1 或者没有这条记录，回退到 turn-trace 的 `pre_turn.state`；还没有就用 bootstrap 默认值。
4. 如果 turn 落在某份大总结的范围内（这种情况只会出现在删除操作里），把那份大总结标记为 `stale=true`。

删除所有和 summary_chunks、keeper archive、event_summaries、FactLog 相关的回滚代码。

如果之后要支持"编辑某一轮的原文"，按同样的思路处理：先改原文，再把这一轮的小结标记为 pending，然后 enqueue。

---

## 9. 接口

在 `server.py` 中新增以下路由，同时更新 `tests/test_server_routing.py` 里的 `EXPECTED_GET` / `EXPECTED_POST`。所有接口都需要登录（Bearer），并通过 `_resolve_scoped_session` 限定在当前用户和当前角色卡之下；写操作要持有会话锁。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/memory?session_id=` | 返回 state、三层总结、任务状态，以及每层下一次生成的进度（如"小结 37/100"） |
| POST | `/api/memory/state` | `{session_id, state}` 编辑当前状态 |
| POST | `/api/memory/turn-summary` | `{session_id, turn, summary}` 编辑小结，同时设置 `edited=true`；如果这一轮已被大总结覆盖，把那份大总结标记为 `stale` |
| POST | `/api/memory/turn-summary/regenerate` | `{session_id, turn, force}` 重写小结。`edited=true` 且没有传 `force` 时返回 409，前端弹窗确认后带 `force` 重发 |
| POST | `/api/memory/big-summary` | `{session_id, index, content}` 编辑大总结 |
| POST | `/api/memory/big-summary/regenerate` | `{session_id, index, force}` 重新生成大总结，409 规则同上 |
| POST | `/api/memory/super-summary` | 同上 |
| POST | `/api/memory/super-summary/regenerate` | 同上 |

- regenerate 类接口只负责把任务放进队列，立即返回 `{status: "pending"}`。前端轮询 `GET /api/memory` 获取进度，轮询间隔 2s，任务结束后停止。
- 输入校验：
  - 文本长度：小结 ≤ 4000 字，大总结和超级总结 ≤ 30000 字。
  - `turn` 和 `index` 必须存在。
  - `state` 只接受 2.4 中列出的字段，其他字段丢弃。

---

## 10. 模型配置

### 10.1 后端

- 新增角色 `summarizer`，需要在以下几处同步修改：
  - `SYSTEM_ROLE_DEFAULTS`
  - `load_user_model_store` 中精简存储结构的白名单
  - `load_runtime_config`
  - `get_model_config_snapshot`
  - `update_model_config`
  - `discover_site_models` 的 fallback
- 默认值：temperature 0.3，`max_output_tokens` 4000（大总结和超级总结用 8000），`stream=false`。逐轮小结使用 `response_format=json_object`。
- 用户没有配置时的回退顺序：已有的 `state_keeper` 模型 → narrator 模型。老用户切换后，总结会自动使用他原来的状态提取模型，不需要重新配置。
- `_call_narrator_with_retries` 里的 secondary 重试目前用的是 state_keeper 模型，改为 `summarizer`。
- 删除 `state_keeper`、`state_keeper_candidate` 两个角色，同时删除 `entity_recovery` 配置段。

### 10.2 前端

- 设置 → 模型分配：把"状态提取"下拉框改成"总结模型"。具体改动点见 `index.html:261-285`、`app.js:41-43`、`app.js:464-496`、`app.js:763-806`。

---

## 11. 前端：状态面板改为总结面板

### 11.1 入口与结构

- 入口不变：`#debugToggleBtn` 打开 `#debugFloatPanel`。
- `index.html:90-143` 改成以下结构，删除调试诊断和 session audit：

```
总结面板
├─ 当前状态   表格展示；[编辑] 后切换为表单，保存时调用 /api/memory/state
├─ 逐轮小结   本段 N/100；倒序列表，每条显示"第N轮 · 文本"
│             状态标记：生成中 / 失败(可重试) / 已编辑
│             操作：[编辑] [重写]
├─ 大总结     折叠列表，标题为"B1 · 第1-100轮"
│             状态标记：生成中 / 失败 / 已编辑 / 可能过期 / 已自动补回★
│             操作：[编辑]（textarea）[重新生成]
└─ 超级总结   同大总结
```

### 11.2 交互

- 渲染：用 `marked` 渲染总结文本，编辑时切换为 textarea。渲染时要转义或做净化，防止 XSS。现有 `renderMarkdown` 怎么处理就照着做。
- 数据刷新：
  - 每轮 `/api/message` 返回后调用 `loadMemory()`；
  - 有 pending 任务时，每 2s 轮询一次，任务结束后停止；
  - 面板关闭时也停止轮询。
- 编辑确认：对 `edited=true` 的条目点重写或重新生成时，`confirm()` 弹窗"会覆盖你的手动修改"，用户确认后带 `force` 重发请求。
- 代码清理：删除 `renderState` 里的 NPC、物件、实体详情部分，删除 `renderDebug`、`renderSessionAudit`、`loadEntity` 以及相关 CSS。`/api/entity` 和 `/api/session-audit` 两个路由一并删除。
- 可访问性：按钮加 `aria-label`；状态不能只用颜色区分，要配文字。

---

## 12. 分阶段实施与验收

每个阶段结束都要跑通 `pytest`。删除旧模块的同时，删除或改写对应的测试。

### P1：存储与上下文（不接异步）

- 完成 `simple_memory.py` 的存储部分和 `build_memory_context`，以及 prompt 改造（第 5 节）、state 精简、配置改成 8 轮。
- 验收：
  - 手工写一份 `turn_summaries.jsonl` 和一份大总结，确认叙述 prompt 里出现三个新区块；
  - 确认 prompt 里已经没有第 5.2 节列出的旧区块；
  - 世界书命中回归测试通过。

### P2：生成与异步

- 完成 worker、`generate_*`、`handle_message` 改造（第 7 节）、重新生成和删除（第 8 节）、`summarizer` 角色（第 10.1 节）。
- **先停掉旧的 `runtime_store.save_state` 写入。** 旧格式和新格式共用 `memory/state.json`。只要旧的 state_keeper 链路还在写，就会覆盖新字段（goal/onstage/items），导致【当前状态】只剩时间和地点。改为只由 `save_simple_state` 写入；如果有地方还需要读旧字段，改成读新字段。
- 验收：
  - 新会话连续对话，每轮之后小结和状态都会出现，并且响应时间不比现在长；
  - 用小阈值测试分层（配置项 `memory.big_every=5`、`memory.super_every=2`，测试用）：确认大总结和超级总结按时生成，上下文按 5.3 的规则切换，衔接时最后 10 条小结仍在；
  - 生成小结的过程中执行重新生成或删除，结果被正确丢弃，没有脏数据；
  - 把模型故意配错，确认 failed 状态能记录，修复配置后能自动补跑。

### P2.5：信息隔离（秘密与知情）

**背景**

小结和总结都是从全知旁白的视角写的，例如"陆小环调包了阵中活物，骗过了掌柜"。叙述模型读到这句，只知道事情发生过，不知道谁知情，很容易写成众人皆知。另外，旧的泄密校验 `_unsupported_npc_private_knowledge_reason`（`handler_message.py:369`）依赖已经删除的【当前在场 NPC 知情核对】区块，现在实际上已经失效。

**原则**：记忆是旁白的全知记录，不是 NPC 的共享知识。"谁知道"必须写进记忆本身，不再另建一套追踪系统。整个 P2.5 **不增加任何模型调用**。

**1. state 新增 `secrets`（由逐轮小结那次调用一起更新）**

```json
"secrets": [
  {
    "content": "阵中活物已被陆小环调包，藏进储物袋",
    "owner": "陆小环",
    "knowers": ["陆小环"],
    "misbelief": {"掌柜": "以为活物仍封在阵中"},
    "suspects": {"青衫年轻人": "知道隔壁有人动过阵，不知道结果"}
  },
  {
    "content": "掌柜与青衫年轻人约定，拍卖会后把阵中之物转交万宝商会",
    "owner": "掌柜",
    "knowers": ["掌柜", "青衫年轻人"],
    "misbelief": {},
    "suspects": {}
  }
]
```

- 字段：
  - `owner`：秘密属于谁，可以是主角，也可以是 NPC；
  - `knowers`：明确知情的人；
  - `misbelief`：被误导的人，以及他误以为的内容；
  - `suspects`：察觉到一部分但不知道全貌的人。
- **NPC 之间的秘密和密谋也要记录。** 只要叙述原文写到了主角不在场的镜头，就照样记进来。这种情况下主角不在 `knowers` 里。
- 只记录存在知情边界的事。公开发生的事不写进来。
- 秘密公开或失去意义后，就从列表里删除，同时在小结里写一行 `【知情】…已被…得知`。
- **最多 8 条。** 超出时由代码保留最近被提到的 8 条，被挤出的条目写进当轮小结的【知情】行，避免直接丢失。

**2. 小结增加 `【知情】` 行**

本轮出现知情变化时（亲眼看见、被告知、偷听、推测），单独写一行，并注明信息是怎么来的：

`【知情】青衫年轻人：灵识察觉隔壁有人破阵（推测，不知道是谁）`

小结 prompt 需要补充的规则：

- 玩家输入里的内心想法、没有说出口的话，不能写成"对某人说了"或"某人得知"。
- 推测、察觉、确认三种程度要分开写。
- 主角不在场的镜头，只记录在场者知道的内容。

**3. 大总结和超级总结增加一栏**

在四栏之后新增 `## 秘密与知情`，用来保存跨越多个分段的长期秘密，比如真实身份、伪装、密谋。人物档案里除了"他知道什么"，再加一项"他不知道或误以为什么"。生成时，要把区间内所有的【知情】行和当前的 `secrets` 都合并进来。带 ★ 的人物，他们相关的秘密不能删除。

**4. 叙述规则：改为白名单**

在【知情边界】区块中新增：

> 上方的记忆区块（超级总结、大总结、逐轮小结、当前状态）是旁白视角的全知记录，不是 NPC 的共享知识。NPC 只能知道这三类内容：
> - 自己亲身在场经历过的事；
> - 【知情】行和"秘密"里明确列出他知道的内容；
> - 人物档案里写明他知道的内容。
>
> 没有写明的，一律按不知道处理。被列在 misbelief 里的 NPC，要按他误以为的内容行事。被列在 suspects 里的 NPC，只能表现出怀疑，不能直接说破。

`render_state_markdown` 渲染秘密时按人展开，例如：`调包活物 —— 知情：陆小环；误以为：掌柜（活物仍在阵中）；有所察觉：青衫年轻人`。

**5. 泄密校验（可选，最后做）**

把 `_unsupported_npc_private_knowledge_reason` 改为读取 `state.secrets`。如果对白中出现某条秘密的关键词，而说话的 NPC 不在 `knowers` 里，就触发重试。关键词匹配误判率高，建议先只做第 1 到 4 项，观察实际游玩效果，再决定要不要开启这项。在决定之前，请把旧校验对已删除区块的依赖去掉，或者明确标注为"已停用"。

**6. 面板（交给 P3）**

状态编辑区需要支持编辑 `secrets`：增删条目，修改知情者、误以为、察觉这几项。

**验收**

- 构造场景：主角独自调包了活物，掌柜随后去探查阵法。第 1 到 4 项完成后：
  - 状态里有对应的秘密，`misbelief` 中记录了掌柜；
  - 叙述 prompt 的【当前状态】里，能看到按人展开的秘密内容。
- 构造一段主角不在场、NPC 之间密谋的叙述原文，确认生成的小结和 `secrets` 中，主角都不在知情者里。
- 用假模型输出 12 条秘密，确认代码最终只保留 8 条，被挤出的条目写进了【知情】行。
- 大总结 prompt 和超级总结 prompt 都包含 `## 秘密与知情` 栏，并且 ★ 人物相关的秘密不会被删除。

### P3：接口与面板

- 完成第 9、11 节，以及第 10.2 节。
- **`build_state_snapshot` 改为读取新字段。** 它现在仍按旧字段（`immediate_goal`、`onstage_npcs` 等）读取，新格式的 `goal`/`onstage`/`risks`/`items` 全部会丢掉。`/api/message` 返回的 `state_snapshot` 改为直接返回精简后的 state，前端面板也读这份数据。
- **状态编辑要支持 `secrets`（见 P2.5 第 6 项）**：增删秘密条目，编辑 `knowers` / `misbelief` / `suspects`。如果 P2.5 还没完成，先预留出这块位置。
- 验收：
  - 面板上的编辑、重写、重新生成、确认弹窗、轮询都正常工作；
  - ★ 校验：手动给大总结加一个 ★ 人物，然后重新生成，该人物仍然保留；用 mock 让模型丢掉这个人物，确认代码能自动补回并在面板上提示。

### P4：清理

删除下列模块及对应测试：

- fact_log、fact_retrieval、event_ledger、keeper_archive、keeper_contract、keeper_record_retriever
- summary_chunks、summary_updater、thread_tracker、actor_registry、important_npc_tracker
- persona_updater、persona_distiller、mid_context_agent、entity_candidate_judge
- state_keeper、state_fragment、state_updater、continuity_resolver、memory_maintenance、memory_agent
- `tools/` 下依赖以上模块的脚本

删除前需要先处理的共享依赖（逐个 grep 确认）：

- `persona_runtime.infer_persona_traits` 被 `runtime_store` 使用；
- `npc/clue/object_bootstrap_agent` 被 context_builder 用来加载注册表；
- `continuity_hints` 被 `state_bridge` 使用；
- `state_bridge` 被 `bootstrap_session` 和 `import_sillytavern_chat` 使用，需要保留并精简。

`tests/test_handle_message_paths.py` 里 mock 了约 60 个符号，需要按新流程重写。

验收：

- `pytest` 全部通过；
- `basedpyright` 没有新增错误；
- 在 `backend/` 下 grep 上面列出的模块名，结果为 0；
- 重新生成、删除、新游戏、导入 SillyTavern 聊天、开局选择这几条流程各手动跑一次。

### 关键回归用例（P2 结束时必须通过）

复现掌柜 bug 的场景：在第 3 轮由玩家输入"掌柜只是凡人"，然后继续对话 20 轮以上。

- 第 3 轮的小结里必须有 `【设定】掌柜：凡人……`；
- 之后每一轮的叙述 prompt 里都能找到这条设定；
- 用小阈值生成大总结后，人物档案里掌柜仍然是"凡人"；
- 全程不出现"客栈掌门"这个称呼。

---

## 13. 风险与注意事项

- **上下文长度。** 最坏情况下约 3~4 万字。不同 provider 的上下文上限不同，要在 `prompt_block_stats` 里继续记录各区块的长度。
  - 如果总长超过配置值（新增 `memory.max_memory_chars`，默认 40000），按这个顺序裁剪：先裁掉与原文重叠的那部分小结，再裁最早的大总结的剧情栏。人物档案栏不要裁。
- **成本。** 每轮多一次小结调用，每 100 轮多一次大总结调用。在设置里标注这一点，建议为总结模型选择价格较低的模型。
- **多进程部署。** worker 和锁都只在单进程内有效。现在是单进程的 `ThreadingHTTPServer`，所以没问题；如果以后改成多进程，需要换成文件锁。
- **进程重启。** 重启时还没跑完的任务会丢失，状态停在 pending。下一轮 enqueue 时会自动补跑；面板也可以手动重试。
- **turn-trace。** 继续保留，作为调试用，但回滚不再依赖它。
