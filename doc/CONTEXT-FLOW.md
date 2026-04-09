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
  -> card / preset / lore / canon / state / summary / persona
  -> narrator
  -> state keeper
  -> summary writer
  -> session-local state / summary / history
```

关键差异：
- `state` 和 `summary` 是 narrator 的前置约束，不是 transcript 的事后附属品。
- `history` 只保留少量上下文承接，不再承担主骨架职责。
- 写回时先收口到结构化状态，再生成下一轮的摘要层。

## 当前 Threadloom 的建议优先级

1. 先稳 `state`。
2. 再稳 `summary`。
3. 再接入 arbiter / persona 流转。
4. 最后再继续打磨 UI。
