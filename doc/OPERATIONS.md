# Operations

## 定位

这个文件记录 `Threadloom` 当前原型的实际使用方式、调试习惯和边界，不是系统主配置。

## 当前建议工作流

继续复用现有 `rp-agent` 资产：
- runtime 规则底板：`prompts/runtime-rules.md`
- 角色卡：`character/character-data.json`
- 世界书：`character/lorebook.json`
- 预设：`character/presets/*.json`
- 长期记忆：`memory/canon.md`
- 当前状态：`memory/state.md`
- 阶段摘要：`memory/summary.md`
- 原始流水：`memory/history.jsonl`
- NPC 档案：`memory/npcs/*.md`
- root persona seed：`runtime/persona-seeds/*`

`Threadloom` 不替代这些资产，而是在当前阶段把它们重新组织成 session-local runtime。

## 最小启动

推荐：

```bash
cd /Threadloom/backend
./start.sh
```

也可以直接：

```bash
cd /Threadloom/backend
python3 server.py
```

停止：

```bash
cd /Threadloom/backend
./stop.sh
```

健康检查：

```bash
curl http://127.0.0.1:8765/api/health
```

默认地址：

```text
http://127.0.0.1:8765
```

## 当前可用能力

当前已接通：
- `GET /api/sessions`
- `POST /api/message`
- `POST /api/new-game`
- `POST /api/delete-session`
- `POST /api/regenerate-last`
- `GET /api/state`
- `GET /api/history`
- `GET /api/entity`

当前前端支持：
- session 输入和 session 下拉切换
- 会话刷新
- 删除当前 session
- 开始新游戏
- 发送消息
- partial 时重新生成上一条
- 右侧状态面板和 NPC 详情查看
- 折叠调试区

## 当前运行特点

当前 prototype 的重要行为：
- 新 session 会从 root `canon / summary / state` bootstrap，不从空壳 state 起步
- opening 已经是独立状态机，不再只是输出一段开局提示
- 同一 `session_id` 的 HTTP 写请求现在会串行执行，降低并发覆盖风险
- partial assistant 回复会显示，但不会继续污染事实层
- `regenerate-last` 会回滚最后一对 `user -> assistant(partial)` 再重试
- `state_keeper` 优先，`state_updater` 兜底
- `state_keeper` 现在会拒收明显低信号或相对上一轮明显退化的 state
- `state_fragment` 现在会先作为结构化锚点进入 narrator 与 state_keeper
- `state_keeper_candidate` 现在可以作为 `skeleton keeper` sidecar 先产出最小骨架，再并入 `state_fragment`
- 完整 `state_keeper` 当前已切到 `fill-mode`：默认只在骨架状态上补 `scene_core / immediate_risks / carryover_clues` 这类次级字段，而不再整份重写 state
- 若 `state_keeper` 失败，当前会先走 `fragment-baseline`，再让 heuristic fallback 在其上补细节
- fallback `state_updater` 现在更偏保守继承，不轻易覆盖已有高信号字段
- 对已经被旧 heuristics 污染的会话，当前可以用离线重建方式直接修 `state / active_threads / important_npcs / summary`
- summary 基于 state 和最近 turn 重写，不再直接摘 narrator prose
- state snapshot 现在直接给前端 `onstage_entities / relevant_entities`
- `default_debug / show_debug_panel / history_page_size` 已从配置贯通到 API 和前端
- 前端默认会话选择已切到“最近更新的活动会话优先”，不再固化到 `story-live`
- 角色卡侧栏已改为动态读取角色卡元数据和缩略封面图
- narrator prompt 已加入更通用的知情边界约束，减少 NPC 间自动共享私下信息

## 当前适合怎么调试

建议优先用这几种方式：
- 直接在前端页面手动跑一个真实 session
- 用 `GET /api/state` 和 `GET /api/history` 看写回是否稳定
- 看调试区里的：
  - `arbiter_analysis`
  - `arbiter_results`
  - `state_keeper_diagnostics`
  - `retained_threads`
  - `retained_entities`
- 用 replay 脚本检查 continuity 和 thread 漂移

回放脚本：

```bash
python3 scripts/replay-runtime-web.py --source-session story-live --max-user-turns 20
```

说明：
- 这个脚本文件目前仍保留历史文件名 `replay-runtime-web.py`
- 这是脚本名层面的历史命名残留，不代表项目目录或服务名仍是 `runtime-web`

也可直接回放 root 历史：

```bash
python3 scripts/replay-runtime-web.py --root-history --start-user-turn 1 --max-user-turns 30
```

## 当前已知边界

当前仍属于原型的部分：
- narrator 已接入真实模型，但 state 仍主要靠 prose 反提
- arbiter 已接进主链，但还是 heuristic 版本
- `turn_analyzer` 默认仍是 heuristic
- persona 流转已接入，但规则仍偏保守启发式
- 世界书人物注入已接入，但还不是独立调度层
- 前端没有编辑能力，错误恢复也仍较薄
- `runtime.json` 里的部分 web 配置项还没完全生效到 UI

## 当前已知问题

目前最值得盯的几类问题：
- `state_keeper` 失败后 fallback state 虽已更保守，但仍可能过于空泛
- 一次性服务 NPC 仍可能偶发被高估重要性
- 同名实体仍没有完整的 disambiguation 交互，当前只是后端直出实体列表并在歧义时保守展示
- summary / important NPC / thread tracker 之间仍可能互相放大弱信号
- 主角目前还没有独立的 runtime 层，observer/主角信息仍需要继续和 NPC 层做强隔离
- 已解决事件还没有独立事件归档层，退出 active state 后仍主要依赖 summary 和记忆层保存
- 信息隔离仍主要靠 prompt 约束 + 状态收口，尚未形成独立的 knowledge scope 数据层

## 当前配模建议

当前更推荐的分工是：
- narrator：继续使用更强的远端模型
- state_keeper：优先切到稳定的本地结构化模型，例如本地 Gemma，但当前建议把它作为“保守结构化提取器”使用
- turn_analyzer：若需要进一步降本，可在 narrator 不变的前提下跟着切到本地模型

当前还额外保留一条候选试验线：
- `state_keeper_candidate`
- 这条线当前已开始以 `skeleton keeper` sidecar 形式辅助线上回合，但只负责最小骨架字段，不直接替换完整 keeper
- 当前 keeper 组合已经变成：
  - `Llama-3.3-70B`：skeleton keeper
  - 本地 Gemma 4B：fill-mode keeper
  - heuristic：最终兜底

原因：
- narrator 是中文长上下文 RP 质量的上限，不适合轻易降到小模型
- state_keeper 和 analyzer 都更接近结构化/判定任务，但 4B 级模型更适合在强约束下工作；当前 Gemma state_keeper 已收成保守模式，不让它直接主导复杂候选决策
- 更强的远端 keeper 候选当前更适合先承担 `skeleton keeper`，在主链里验证其时间/地点/主事件/在场人物/当前目标这几个骨架字段是否足够聪明且足够稳

## 运行原则

当前最重要的顺序仍然是：
1. 先稳 `state`
2. 再稳 `summary`
3. 再稳 `threads / important_npcs / persona`
4. 最后再打磨 UI 和更细的自动化
