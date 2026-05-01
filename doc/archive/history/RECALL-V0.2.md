# Threadloom Recall V0.2

## 目标

`v0.2` 的目标不是替换 `runtime-first` 架构，而是给 narrator 增加一层更合理的上下文召回：

- 最近 3 轮：直接给 narrator 原文
- 第 4 到 13 轮：交给中程摘要 agent 做结构化 digest
- 第 14 轮以前：交给 memory agent 只检索相关旧内容

核心原则：
- 硬事实仍由 `state / entities / threads / tracked_objects` 承担
- recall 只补上下文，不改事实层
- narrator 只读，不直接写回 recall 产物

## 三层结构

### Layer 1: Recent Window

直接保留最近 3 轮原文。

```json
{
  "recent_window": [
    {
      "turn_id": "turn-0072",
      "user": "……",
      "assistant": "……"
    }
  ]
}
```

### Layer 2: Mid Window Digest

覆盖第 4 到 13 轮，交给中程摘要 agent 处理。

只要求它抽取能跨 2 轮以上持续生效的内容：

- 时间
- 地点
- 人物
- 事件
- 物品
- 未决事项

```json
{
  "mid_window_digest": {
    "window": {
      "from_turn": "turn-0062",
      "to_turn": "turn-0071"
    },
    "time_anchor": "承和十二年，三月初七，入夜",
    "location_anchor": "福安老店",
    "stable_entities": [
      {
        "name": "掌柜",
        "role": "客栈掌柜",
        "status": "持续在局"
      }
    ],
    "ongoing_events": [
      "官差仍在搜查客栈并寻找伤者",
      "借宿者的身份和伤势仍未彻底摊开"
    ],
    "tracked_objects": [
      {
        "label": "短刀",
        "owner": "借宿者",
        "status": "持续被提及"
      }
    ],
    "open_loops": [
      "掌柜到底站在哪一边",
      "借宿者是否会继续留在店里"
    ]
  }
}
```

### Layer 3: Long Recall

覆盖 14 轮以前内容，只做相关检索。

```json
{
  "memory_bundle": {
    "query_terms": [
      "借宿者",
      "掌柜",
      "短刀"
    ],
    "memories": [
      {
        "memory_id": "mem_001",
        "kind": "relationship",
        "summary": "掌柜明面撇清关系，但暗地里替借宿者留过药。",
        "source": {
          "user_ts": 1775917000000,
          "assistant_ts": 1775917000100
        },
        "relevance": 0.82
      }
    ]
  }
}
```

## 第二层 Agent 的职责

中程摘要 agent 负责：

- 压缩第 4 到 13 轮内容
- 去掉只活一轮的小动作
- 保留跨两轮以上仍会影响判断的场面信息
- 输出结构化 digest

它不负责：

- 改 `state`
- 生成新 NPC
- 改 canon
- 代替 narrator 决定当前回复

## narrator 输入组合

`v0.2` narrator 输入建议按这个顺序：

1. `runtime-rules`
2. `state / entities / threads / tracked_objects`
3. `recent_window`
4. `mid_window_digest`
5. `memory_bundle`
6. 当前用户输入

其中优先级：

- `state` 高于 `recent_window`
- `recent_window` 高于 `mid_window_digest`
- `mid_window_digest` 高于 `memory_bundle`

## 评估标准

如果 `v0.2` 生效，理想结果应是：

- narrator 在长会话里更少忘记旧关系与旧承诺
- `main_event` 不再被每轮输入带跑
- keeper 压力下降，因为第 4 到 13 轮不必全靠当前 state 摘要字段承载
- narrator 不需要拿大段 history 也能维持连续性
