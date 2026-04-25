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
  -> state keeper
  -> optional summary writer
  -> session-local state / summary / history
```

关键差异：
- `state` 是 narrator 的前置硬约束，`summary` 不再是 narrator 主输入。
- `history` 只保留最近窗口承接，不再承担完整骨架职责。
- 更早历史优先收敛成 keeper archive，而不是自由摘要层。
- 写回时先收口到结构化状态；`summary` 可继续保留为调试/运维产物，但不再主导 narrator。

当前分工草案（设计目标，不代表所有实现都已完全收口）：
- `signals`：当前方向约束层。用于承接后续仍会影响局势推进的 `risk / clue / mixed` 信号，可直接进入 narrator / selector。
- `event`：中程检索层。默认不直送 narrator，主要作为 3 回合级事件总结与 recall / summary 的前置索引。
- `summary`：长程压缩层。默认只在 selector 判断 recent window 不足、且旧事件确实回流时才补给 narrator。
- `thread`：当前实验中已开始降级为 state/debug 辅助层，不再默认主导 narrator 或 selector。

更具体地说：
- narrator 主导“当前这轮怎么写”，不由 `thread` 或 `event` 直接接管。
- selector 主导“这一轮要不要把旧东西拿回来”，优先参考 `recent window + state + signals + event recall`。
- keeper 主导“后台结构化维护世界状态”，其中：
  - `signals` 负责“当前还没消失、会继续影响下一拍”的东西；
  - `event` 负责“前几轮到底发生了什么值得检索”；
  - `summary` 负责“更长阶段该如何压缩”；
  - `thread` 若保留，也更偏 debug/state 辅助，而不是 steering 层。
- 当前 event 链已开始按这个方向实现：事件总结默认读取最近 `1~3` 对 turn 窗口，并在 selector 判断需要时作为 recall / summary 的前置材料使用，而不是把 event 当当前 narrator 的常驻 steering 块。

## 当前 Threadloom 的建议优先级

1. 先稳 `state`。
2. 再稳 `recent window -> keeper archive` 的两层上下文。
3. 再接入 arbiter / persona 流转。
4. 最后再继续打磨 UI。
