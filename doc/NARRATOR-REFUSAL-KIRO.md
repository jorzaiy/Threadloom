# Narrator 拒答排查：claude-sonnet-4.6 返回 "I can't discuss that."

状态：已定位，未修复（2026-09-25）

## 现象

- 存档 `九幽大陆-20260922-5c52b4` 第 13 轮起，narrator（`claude-sonnet-4.6`，经 thinrelay 中转）连续十几次只回一句 `I can't discuss that.`。
- 客户端看到：`completion_tokens=5`、`finish_reason=stop`，每次 3–7 秒返回。
- 同一模型第 11–12 轮正常（22s / 36s，长篇中文正文）。
- 用户输入和最近 6 轮都是普通修仙剧情，不涉及露骨内容。

## 中转站侧查证结果（thinrelay 日志 + 源码）

| 项 | 结论 |
|---|---|
| 上游渠道 | **Kiro**（`https://runtime.us-east-1.kiro.dev/generateAssistantResponse`）。`config.yaml` 路由 `claude*` → `kiro`，无 fallback |
| 模型映射 | `claude-sonnet-4.6` → 上游 `claude-sonnet-4.5`（`kiro_format.go:44-47`） |
| 账号 | 5 个 AWS Builder ID 轮询；失败在全部 5 个账号上都出现过，不是单账号问题 |
| 这句话谁生成的 | 中转站源码/日志里搜不到 `can't discuss`，是**上游原样返回的正文**（`{"content": "I can't discuss that."}`） |
| 上游状态 | HTTP 200，无 guardrail / blocked 类事件，正常结束流 |
| token 数 | `completion_tokens=5` 是中转站按 字符数/4 估算的，不是上游数字 |
| 请求改动 | Kiro 不支持 system 角色 → **整段 system prompt 被拼到 user 消息前面**；`temperature` / `max_tokens` 被丢弃；请求带 `origin: "AI_EDITOR"` |
| 重试 | 只在 401/403 重试；200 不重试 |

## 结论

### 1. 破限块（【世界模拟引擎】/ `narrator_identity_reset`）不是原因，也不是解法

- 这个块已接入：`config/runtime.json` 配了 `narrator_identity_reset`，`backend/narrator_input.py:582` 把它拼进 prompt。
- 时间线：第一次拒答在 9/22 21:28，那时还没有这个块；9/24 下午加块并重启服务后，16:21 / 16:22 / 16:31 的请求照样被拒。有没有这个块，结果都一样。
- 这个块是给 grok 写的。Claude 不会因为 prompt 里的"身份重置"改变判断，这类写法反而更容易让它拒答。走 Kiro 时这段还被并进了 user 消息，在模型看来是用户消息里的一段越狱文本，连"开发者设定"的身份都没有。
- **不在这个方向上继续调。**

### 2. 根本问题是 Kiro 渠道本身

- thinrelay 调的是 Kiro 的服务接口，不是直接调 Claude 的接口。最终 prompt 怎么拼（很可能有 Kiro 自己的编程助手系统提示）、要不要过审核层，都是 **AWS 服务端**决定的。
- 用代理而不是用 Kiro 编辑器发请求，绕不开这一层，因为请求打到的是同一个服务端。
- 旁证：`origin: "AI_EDITOR"`、不支持 system、忽略采样参数。这说明我们并没有在直接调 Claude，而是在用一个包着 Claude 的编程助手产品。
- `I can't discuss that.` 这么短、这么格式化，不像 Claude 平时拒答的样子，更像是编程助手的系统提示约束出来的，或者是审核层的固定文案（推测，从外面分不清是哪一个）。两种都不是改 prompt 能解决的。

### 3. Threadloom 自身的 bug：拒答被写进存档

- `narrator_reply_rejection_reason`（`backend/model_client.py:164`）只检查结尾标点等格式问题，`I can't discuss that.` 以句号结尾，能通过。
- 结果：拒答被写进 `history.jsonl`、summary（"世界反馈：…"）和 state。
- regenerate 能干净回滚（trace 里 pre_turn 是干净的），所以不会自我强化；但一次没重试的拒答就会污染存档。

## 明天可以做的

1. **自己验证 Kiro 服务端的限制**（通过 thinrelay 发两次短请求）：
   - 只发"你是谁？你有什么使用限制？"。回答提到 Kiro / Amazon Q / 编程助手 → 服务端有自己的系统提示。
   - 只发"写一段三百字的修仙小说开头"（不带长设定）。这个也被拒 → 问题在渠道本身；能正常写 → 是长设定里的某部分内容加上 Kiro 一起触发的。
2. **narrator 换通用渠道**：官方 Anthropic API 或 Bedrock 这类正常对话接口，不走 Kiro。这是主要解法。
3. **加拒答检测**（Threadloom 侧）：
   - 位置：`narrator_reply_rejection_reason` 或 `_call_narrator_with_retries`（`backend/handler_message.py:308`）。
   - 规则思路：正文很短，并且没有中文（或者命中 `I can't` / `I cannot` / `I'm not able to` 这类拒答模式）→ 判定为 `refusal`。
   - 处理：不写进 history / summary / state；先重试，还不行就切备用模型，或者在前端提示"模型拒答，请换模型"。
4. 世界书（【可调入世界书 NPC】的注入范围）**暂不动**，按用户决定保留现状。

## 边界

露骨性描写是 Claude 默认不写的，换渠道也一样。这次的剧情离这个很远，和本次问题无关；换通用渠道是为了去掉编程助手这层限制，不是为了绕过模型本身的规则。
