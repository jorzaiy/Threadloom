# Memory V3 实施进展与全量代码审计报告

**日期：** 2026-10-04  
**范围：** Memory V3（P1 存储装配、P2 异步调度、P2.5 信息隔离、P3 接口与总结面板）及系统架构审计  
**状态：** P1 / P2 / P2.5 / P3 已全部完成并合入 `master`，全量自动化测试通过（651 passed, 15 skipped, 20 subtests passed）

---

## 1. 背景与架构重构

### 1.1 现状问题
原系统叙述 Prompt 拼装了约 30 个复杂区块，每轮对话同步串行跑 arbiter、state_keeper、event_ledger、summary_chunks、fact_log 等多个模型提取链路。信息每多经一层抽取，就多一次丢失或称呼漂移的机会（如将“掌柜是凡人”误漂移为“客栈掌门”）。

### 1.2 架构目标
- 记忆链路精简为四层：**逐轮小结（含【设定】/【知情】） → 大总结（每 100 轮） → 超级总结（每 500 轮） → 当前状态（state.json）**。
- 叙述正文回复后**异步生成**小结与状态，完全消除玩家同步等待时延。
- 保证每层数据可读、可手动编辑、可随时重新生成。
- 严格遵循信息隔离与白名单知情约束。

---

## 2. 各阶段实施概览

### P1：数据存储与分层上下文装配
1. **数据存储 (`backend/simple_memory.py`)**：
   - 数据文件均保存在 `<session>/memory/`：`turn_summaries.jsonl`、`big_summaries.json`、`super_summaries.json`、`state.json`。
   - 实现了四层结构的原子写入与读取。
2. **上下文组装 (`build_memory_context`)**：
   - 组装【长期记忆·超级总结】、【阶段记忆·大总结】、【近期逐轮小结】、【当前状态】。
   - 衔接规则：新大总结生成后，其覆盖范围内的最后 10 条小结继续保留在上下文中。
   - 裁减顺序：总长超过 `memory.max_memory_chars`（默认 40000）时，先裁与最近 8 轮原文重叠的小结，再裁最早大总结的剧情栏，**人物档案栏绝对不裁**。
3. **Prompt 拼装与配置优化**：
   - 原文窗口精简为 8 轮（`recent_history_turns: 8`，`recent_full_prose_turns: 8`）。
   - 彻底移除了权威人物档案、往事回溯、在场知情核对、角色注册表、当前事件目标等 12+ 个旧冗余区块。
   - 精简 `selector` 与世界书触发文本（仅使用最近 8 轮原文 + 用户输入 + 新 state 的 goal / risks / location）。

### P2：模型生成与后台 Worker 异步调度
1. **模型角色支持 (`backend/model_config.py`)**：
   - 新增 `summarizer` 角色，设置 `temperature: 0.3`、`max_output_tokens: 4000`（大总结/超级总结 8000），`stream: false`。
   - 实现无配置时的回退链：`state_keeper` → `narrator`，平滑兼容既有用户配置。
   - secondary 叙述重试模型切换为 `summarizer`。
2. **生成函数与 ★ 标记保障**：
   - `generate_turn_summary`：单次调用同时输出精简小结与状态更新。
   - `generate_big_summary` / `generate_super_summary`：固定结构生成，缺失轮次用原文回源兜底。
   - **★ 重要人物校验与自动补回**：正则提取上一版带 ★ 角色，模型遗漏时重试一次；若仍遗漏，代码自动将完整档案段落补回人物档案末尾并记录 `restored_stars`。
3. **后台 Worker 异步调度体系**：
   - 基于 `ThreadPoolExecutor(max_workers=2)` + `dict[session_id, Future]` 确保单会话单任务串行。
   - 调度链：补齐失败/pending 小结（单次最多 3 条） → 到达轮次生成大总结 → 达到份数生成超级总结。
   - **锁机制**：调用模型时不持锁，结果提交时短暂获取 `session_lock`。
   - **4.3 节有效性校验**：提交前重读 history 校验 `reply_hash`；大总结提交前校验覆盖范围小结是否被并发修改（若被改动则标记 `stale=true`）。
   - 主流程接驳：主链返回响应附带 `memory_status: 'pending'`，彻底停用旧的同步 keeper 链路与旧 `save_state`。
4. **重新生成与删除回滚 (`backend/regenerate_turn.py`)**：
   - 锁外取消后台任务，删除指定轮次后的小结，`state.json` 直接从第 `turn-1` 轮的 `state_after` 恢复，若涉及大总结覆盖范围则标记 `stale=true`。

### P2.5：信息隔离（秘密与知情）
1. **状态结构升级**：
   - `state.json` 新增 `secrets` 列表（包含 `content`, `owner`, `knowers`, `misbelief`, `suspects`）。
   - 限制最多保留 8 条 secrets，超出条目自动溢出归档转入当轮小结的【知情】行。
2. **提示词与知情边界隔离**：
   - 小结提示词增加【知情】行规范（区分亲历/告知/偷听/推测/察觉/确认，内心想法不计为知情）。
   - 主角不在场的 NPC 密谋镜头，主角严格不计入 `knowers`。
3. **大总结/超级总结新增 `## 秘密与知情` 栏目**：
   - 汇集长期秘密、身份伪装与密谋，并对 ★ 角色关联秘密实施防删保护。
4. **叙述白名单约束 (`narrator_input.py`)**：
   - 明确记忆区块为旁白全知记录而非 NPC 共享知识，NPC 严格受亲历、人物档案与【知情】/secrets 白名单约束，对 misbelief 内容坚信不疑。
   - `render_state_markdown` 支持按人展开展示秘密（知情、误以为、有所察觉）。

### P3：接口与总结面板
1. **REST API 体系 (`backend/server.py`)**：
   - `GET /api/memory`：返回状态、三层总结、任务状态及各层生成进度。
   - `POST /api/memory/state`：编辑当前状态（含 secrets）。
   - `POST /api/memory/turn-summary` & `/regenerate`：编辑小结（级联大总结 stale）与重写（409 保护 + `force: true`）。
   - `POST /api/memory/big-summary` & `/regenerate`：编辑与重写大总结。
   - `POST /api/memory/super-summary` & `/regenerate`：编辑与重写超级总结。
2. **快照重构**：
   - `runtime_store.build_state_snapshot` 统一输出精简 state（time, location, onstage, goal, risks, items, secrets）。
3. **前端总结面板重构 (`frontend/index.html` & `app.js`)**：
   - 替换旧 NPC 详情及调试/审计面板，就地呈现当前状态（表格展示/表单编辑）、逐轮小结（折叠倒序、状态标签、编辑/重写）、大总结与超级总结（Markdown 渲染、状态标记、编辑/重新生成）。
   - 交互优化：打开面板与消息返回自动拉取记忆；有 pending 任务时每 2s 定时轮询，任务完成或面板关闭自动停止。
   - 设置面板中将“状态提取”下拉框更新为“总结模型”（对应 `summarizer`）。

---

## 3. 全量代码审计与问题修复总结

在对整个 Memory V3 实现进行严格代码审计与集成回归中，重点排查并修复了以下核心缺陷：

| 缺陷分类 | 问题现象 | 根因分析 | 修复方案 |
|---|---|---|---|
| **死锁 / 性能** | 用户发送下一句消息白等 20 秒，后台任务提交卡住 | `_post_message` 先拿 `session_lock`，在锁内执行 `wait_idle(20s)`；而 Worker 提交结果也需要拿同一把 `session_lock`，导致互相死锁等待直到 20s 超时 | 将 `wait_idle` 与 `cancel_and_wait` 调整到获取 `session_lock` 之前（锁外等待） |
| **模板解析** | 小结 100% 生成失败，报错 `KeyError` | 提示词模板末尾包含 JSON 示例 `{ "summary": ... }`，调用 `str.format()` 导致原样花括号触发语法异常 | 实现单遍非贪婪正则替换 `fill_prompt_template`，仅替换已知 `{key}`，不解析 JSON 示例及文本内的花括号 |
| **持久化覆盖** | 面板手动修改的状态在下一轮对话后被覆盖 | 生成下一轮小结时前序状态取的是上一轮小结记录的 `state_after`，未感知 `state.json` 的修改 | 在 `save_simple_state` 中同步更新最新一条小结记录的 `state_after` |
| **上下文缺失** | 重新生成大总结时旧大总结从上下文消失，失败则永久丢失 | 接口调用时直接将大总结 `status` 标为 `pending`，而上下文仅读取 `status='ok'` 的记录 | 重新生成期间保留旧内容与 `status='ok'`，标记 `regenerating=True`；失败时保留旧内容并标记 `status='failed'`，`build_memory_context` 读取只要有内容的总结 |
| **前序错误** | 重新生成大总结/超级总结时拿错了上一份总结 | 代码写为 `bigs[-1]`，重新生成中间总结时将后续总结当成了前文 | 改为按 `index - 1` 精确查找前序总结 |
| **任务隔离** | 重新生成任务绕开 Worker 调度与锁管控 | 原 `enqueue_*_job` 直接向线程池抛任务，脱离 `_SESSION_FUTURES` 追踪，也未受 `cancel_and_wait` 控制 | 将重新生成全部统一收敛到主 Worker 执行队列，复用 `wait_idle`、`cancel_and_wait` 和锁校验 |
| **裁定污染** | 重新生成旧小结会冲掉最新轮次的裁定结果 | `enqueue_after_turn` 无条件覆盖 `_LATEST_ARBITER` | 增加 `update_arbiter=False`，重新生成旧轮次时不修改最新裁定结果 |
| **前端异常** | 页面加载报错“初始化失败”，应用完全不可用 | `resetSidePanels()` 访问了已删除的未声明变量 `entityEl`，抛出 `ReferenceError` 导致 `init()` 中断 | 清理未声明旧元素访问，安全调用 `renderDebug(null)`，删除残留的旧 `loadEntity` |
| **前端轮询** | 任务生成中状态不自动刷新 | `startMemoryPolling` 依据 `aria-hidden === 'true'` 判断，而打开面板只设置了 `dataset.open`，`aria-hidden` 仍为初始值 | 同步更新 `aria-hidden`，并改为以 `dataset.open === 'true'` 为准判定轮询 |
| **重启遗留** | 服务重启后大总结/超级总结一直显示“生成中” | 内存中任务因重启丢失，但 JSON 中存有 `regenerating=True` | 增加 `clean_stale_regenerating_flags`，在 `_get_memory` 时若后台无任务则自动清理遗留标记 |
| **数据容错** | 状态编辑输入单个对象导致后端解析成属性名列表 | `state.items` / `secrets` 输入单个对象时 `list({...})` 会将其转为键列表 | 前后端均加入判断：若为 dict 则自动包裹为单元素 list；缺省 secrets 时保留既有数据 |
| **JSON 容错** | 部分模型输出带闲聊或 Markdown 包裹导致小结提取失败 | 模型输出首尾携带自然语言解释，普通 `json.loads` 抛出 `JSONDecodeError` | 新增 `_parse_json_from_reply`：支持代码块剥离及首尾花括号边界截取兜底 |
| **类型规范** | 类型检查报错 3 处 | `handler_message` 中 `audit` 可能为 None；`regenerate_turn` 中 `restored_state` 类型推导含 None | 修复安全链式读取，类型检查 `basedpyright` 达到 **0 errors, 0 warnings, 0 notes** |

---

## 4. 自动化测试与验证

本次重构新增了一整套专项自动化测试套件：
- `tests/test_simple_memory.py`：基础存储 CRUD、分层上下文组装、衔接轮次与超长截断规则。
- `tests/test_simple_memory_p2.py`：★ 人物自动补回机制、掌柜凡人关键回归用例（20 轮以上全程凡人且无“客栈掌门”）。
- `tests/test_simple_memory_worker.py`：真实模板无 KeyError、小阈值全流程分层生成、会话锁互等回归、并发手动修改防覆盖。
- `tests/test_simple_memory_p25.py`：秘密结构展开、NPC 独立密谋隔离、secrets 8 条上限与溢出知情行、★ 角色秘密防删。
- `tests/test_simple_memory_p3.py` & `p3_fixes.py`：7 个 REST API 验证、权限与 409 保护、锁外 wait_idle、旧裁定保护、状态编辑继承、重生成失败旧内容留存、重启标记清理。

**测试执行结果：**
```
651 passed, 15 skipped, 20 subtests passed in 73.23s
```
测试全部通过，服务运行平稳。
