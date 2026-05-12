# Keeper 精简优化与 Event Ledger 回退修复

**日期：** 2026-05-12  
**范围：** 后端 keeper pipeline、event_ledger、前端消息重发防重复  
**触发：** session 71a731 出现明显遗忘上文现象

---

## 问题诊断

### 症状
Session 71a731（66 轮）在 turn-55 之后出现明显遗忘：narrator 不记得 turns 13-54 中的关键剧情（任务规则、队伍分组、补给箱战斗等）。

### 根因
2026-05-11 的 keeper 精简优化 #1（event_ledger 在 fill 轮次复用 state_keeper 的 signal 输出）引入了严重的记忆退化：

1. `_ledger_from_keeper_signals` 用 `state.main_event` 作为事件摘要
2. `main_event` 在很多轮次只是时间+地点字符串（如 `"2026年9月1日 上午，东侧树林第三个岔口。"`）
3. 导致 66 个 event_summaries 中有 26 个是无意义的纯时间戳
4. Selector 的关键词匹配无法从这些空摘要中召回中期历史
5. Narrator context 中缺少 turns 13-54 的关键剧情 → 遗忘

### 附带发现
- Selector 的 event_hits（4 条）全部来自 recent window 内的轮次（turns 62-65），完全冗余
- Summary chunks 只命中了 turns 1-12 的早期历史
- Turns 13-54 在 narrator context 中完全没有表示

---

## 修复措施

### 1. 回退 event_ledger keeper_signals 优化
- 恢复每轮都用 LLM 生成事件摘要
- `_ledger_from_keeper_signals` 函数保留但不再被调用

### 2. 修复已有坏数据
- 用 heuristic fallback 从 turn traces 重新生成了 25 个坏摘要
- 修复后仅剩 1 个无法修复（turn-0038，trace 中 narrator reply 信息不足）

### 3. 保留的其他优化（未受影响）
- #2: 合并轮次跳过 skeleton keeper（fill 已覆盖所有字段）✅
- #5: persona_updater 依赖 important_npc_tracker 锁定结果 ✅
- #6: 去掉 state_keeper 内部的 semantic_cleanup ✅

---

## 教训

Event summary 是 selector 召回中期历史的唯一通道。任何降低 event summary 质量的优化都会直接导致记忆退化。`main_event` 字段不适合直接作为事件摘要——它是状态锚点，不是叙事摘要。

未来如果要优化 event_ledger 的 LLM 调用，应该：
- 确保 summary_text 包含动作/事件/结果，而不仅是时间地点
- 或者用 narrator_reply 的首句/关键句作为摘要来源
- 任何替代方案都需要在 20+ 轮 session 上验证 selector 召回质量

---

## 同期修复

### 前端消息重发防重复（2026-05-11）
- 问题：客户端断开连接后重发消息生成新 client_turn_id，导致重复 turn
- 修复：前端在发送失败时保留 `pendingClientTurnId`，重发时复用同一 ID 触发服务端去重
- 文件：`frontend/app.js`

---

## 测试结果

270 passed, 1 skipped, 20 subtests passed (44.47s)
