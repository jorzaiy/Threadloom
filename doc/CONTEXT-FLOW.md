# Context Flow

## 旧链路

```text
online session
  -> transcript
  -> history sync
  -> state / summary 提炼
  -> prompt build
  -> narrator
  -> 新 transcript
```

问题不在“有没有 state / summary”，而在：
- transcript 既是输入来源，又不断吸收输出结果。
- prompt 最后仍会把 recent history 大块拼回去。
- 长时间运行后，模型更容易延续自己刚写出的文本惯性，而不是回到运行态文件。

## 新链路

```text
web input
  -> runtime handler
  -> runtime rules
  -> card / preset / lore / canon / state / persona / recent window / keeper archive
  -> narrator
  -> skeleton keeper / state keeper fill
  -> optional summary writer
  -> session-local state / summary / history
```

关键差异：
- `state` 是 narrator 的前置硬约束，`summary` 不再是 narrator 主输入。
- `history` 只保留最近窗口承接，不再承担完整骨架职责。
- 更早历史优先收敛成 keeper archive，而不是自由摘要层。
- 写回时先收口到结构化状态；`summary` 可继续保留为调试/运维产物，但不再主导 narrator。
- state 写入分三类：opening 只做开局状态机 checkpoint；`handler_message.py` 负责每个完整 turn 的最终权威提交；keeper archive 写入只维护派生缓存。
- keeper 写回按增量 patch 执行：骨架字段由 skeleton keeper 维护，fill keeper 只补信号、物件、持有关系、可见性和本轮知情 delta。
- `knowledge_scope` 是本轮 delta，长期知识落到 `knowledge_records`；物件退出 active 状态通过 `lifecycle_status` 和 `graveyard_objects` 表达。
- keeper archive 是派生缓存，刷新时会清理超过当前有效 pair index 的未来 records，避免撤回/重试后的旧分支污染召回。
- keeper archive 的读路径默认允许维护派生缓存；需要只读检查时，调用方可通过 `allow_archive_write=False` 禁止 prune/rebuild 落盘，默认运行行为不变。

当前分工草案（设计目标，不代表所有实现都已完全收口）：
- `signals`：当前方向约束层。用于承接后续仍会影响局势推进的 `risk / clue / mixed` 信号，可直接进入 narrator / selector。
- `event`：中程检索层。默认不直送 narrator，主要作为 3 回合级事件总结与 recall / summary 的前置索引。
- `summary`：长程压缩层。默认只在 selector 判断 recent window 不足、且旧事件确实回流时才补给 narrator。
- `thread`：当前实验中已开始降级为 state/debug 辅助层，不再默认主导 narrator 或 selector。

更具体地说：
- narrator 主导“当前这轮怎么写”，不由 `thread` 或 `event` 直接接管。
- selector 主导“这一轮要不要把旧东西拿回来”，优先参考 `recent window + state + signals + event recall`。
- 世界书由三层处理：开局首个 narrator 回合用原始 alwaysOn/foundation 条目大预算定底；后续每轮常驻蒸馏出的基础护栏；selector 命中世界书 index 后回源到原始 `lorebook.json` 片段交给 narrator，而不是只给蒸馏摘要。
- keeper 主导“后台结构化维护世界状态”，其中：
  - `signals` 负责“当前还没消失、会继续影响下一拍”的东西；
  - `knowledge_scope` 只负责本轮新增知情 delta，长期情报由 `knowledge_records` 承担；
  - `objects` 负责 active 物件、持有关系、可见性和生命周期退出；
  - `event` 负责“前几轮到底发生了什么值得检索”；
  - `summary` 负责“更长阶段该如何压缩”；
  - `thread` 若保留，也更偏 debug/state 辅助，而不是 steering 层。
- 当前 event 链已开始按这个方向实现：事件总结默认读取最近 `1~3` 对 turn 窗口，并在 selector 判断需要时作为 recall / summary 的前置材料使用，而不是把 event 当当前 narrator 的常驻 steering 块。

## 2026-04-28 Keeper / Selector 稳定性修复

针对 `维克托奥古斯特-20260428-f773f2` 的检查结果，已收紧以下运行链路：

- 用户继续输入时，若 history 尾部仍是 `completion_status=partial` 的 assistant 回复，会先移除该半截回复再追加新 user turn，避免 partial 文本污染 keeper / selector。
- keeper archive 构建 turn pairs 时只接受 complete assistant 回复；partial assistant 会关闭当前 pair，不进入 archive 统计和摘要。
- state keeper fill 的用户提示明确要求输出必须以 `{` 开头、以 `}` 结尾；非空但不可解析的输出会自动重试一次，并在重试提示中禁止解释、代码块和 JSON 前后文字。
- selector 现在会基于 state、recent window、user text 对 `event_summaries` 做 topic/actor overlap 命中，`event_hits` 不再固定为空。
- summary chunk 命中增加轻量 topic overlap 兜底，并在命中结果里保留 `keyword_hits` 便于 trace 诊断。

这组修复的目标不是扩大 narrator 输入，而是保证 recall 层只带入可用、完整、与当前 query 相关的历史材料。

## 当前 Threadloom 的建议优先级

1. 先稳 `state`。
2. 再稳 `recent window -> keeper archive` 的两层上下文。
3. 再接入 arbiter / persona 流转。
4. 最后再继续打磨 UI。
