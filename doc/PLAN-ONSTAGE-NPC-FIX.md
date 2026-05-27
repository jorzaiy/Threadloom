# 修复计划：onstage_npcs 偏窄 / 丢失问题

## 问题现象

session `九幽大陆-20260520-e23032` 最近 15 轮中，`state_after_keeper.onstage_npcs` 频繁为空或不完整，即使 narrator 正文中明确有多个 NPC 在场、有动作和对话。

## 根因分析

### 1. Keeper LLM 输出格式与 normalize 不匹配

Keeper prompt 要求 `onstage_npcs` 输出简单名字列表，但 LLM（mimo-v2.5-pro）经常输出 scene_entities 格式的 dict 列表：

```json
"onstage_npcs": [
  {"entity_id": "npc_003", "primary_label": "黑脸膛男人", "onstage": true, ...}
]
```

`_normalize_keeper_payload()` 对每个 item 做 `str(item).strip()`，dict 变成 `"{'entity_id': ...}"` 字符串，后续 `is_protagonist_name()` 检查不会命中，但这个字符串不是有效的 NPC 名字。

最终 merge 阶段（第 1205-1220 行）再次对 payload 做 `str(item).strip()`，产生同样的问题。结果是 `_current_turn_onstage_npcs` 被设为这些无效字符串，而 state_after_keeper 中的 onstage_npcs 在后续清洗中被清空。

### 2. Prompt 限制"最多 3 个"过于严格

当前 prompt：
> onstage_npcs 只写本轮正文中实际在场、有动作或对话的人物，最多3个

实际场景中经常有 4-5 个 NPC 同时在场（如关卡场景：年轻士兵、黑脸小子、束发女人、灵貂、少年）。限制 3 个导致 LLM 必须做取舍，有时会输出空列表（可能因为无法决定取舍）。

### 3. state_fragment 与 keeper 的 onstage 信息不同步

- `state_fragment_initial`（来自上一轮）：`['束发女人', '灵貂', '车夫']`
- keeper payload：`[黑脸膛男人, 年轻士兵, 灵貂]`（dict 格式）
- `state_after_keeper`：`[]`（被清空）

keeper 的输出本应覆盖 state_fragment，但因为格式问题被丢弃后，最终 state 中的 onstage_npcs 变成空。

## 修复方案

### Fix 1：normalize 阶段兼容 dict 格式（必须）

`_normalize_keeper_payload()` 中 onstage_npcs 的处理：

```python
for item in onstage:
    if isinstance(item, dict):
        name = str(item.get('primary_label', item.get('name', '')) or '').strip()
    else:
        name = str(item or '').strip()
    if name and not is_protagonist_name(name) and name not in cleaned:
        cleaned.append(name)
```

同样的修复需要应用到 merge 阶段（第 1205-1220 行）的 `onstage_npcs` 和 `relevant_npcs` 处理。

### Fix 2：放宽上限从 3 → 5（建议）

将 prompt 中的"最多3个"改为"最多5个"，normalize 中的 `len(cleaned) >= 3` 改为 `>= 5`。

理由：
- 实际场景中 4-5 人同时在场很常见
- onstage_npcs 的作用是告诉 narrator 当前谁在场，漏掉人会导致 narrator 忽略在场角色
- 5 个上限仍然能防止 LLM 把所有 scene_entities 都塞进来

### Fix 3：field_acceptance 中 onstage_npcs 为空时回退到 state_fragment（建议）

当 keeper 输出的 onstage_npcs 经过 normalize 后为空，但 state_fragment 中有值时，保留 state_fragment 的值而不是写入空列表。这是一个安全网，防止格式问题导致信息丢失。

## 影响范围

- `backend/state_keeper.py`：normalize、merge、prompt 文本
- 测试：`tests/test_state_keeper_partial_accept.py`、`tests/test_state_fragment.py` 可能需要更新

## 验证方式

1. 用 turn-0177 的 keeper payload 作为测试输入，确认 normalize 后 onstage_npcs = `['黑脸膛男人', '年轻士兵', '灵貂']`
2. 跑完整测试套件
3. 在线验证：下次游玩时观察 state_after_keeper.onstage_npcs 是否正确填充
