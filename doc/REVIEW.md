# Threadloom Review

## 当前判断

`Threadloom` 现在已经具备最小闭环，不再只是设计稿：
- Web 前端可访问
- 后端 HTTP API 可用
- narrator 已接真实模型
- session-local `history / state / summary / persona` 已写回
- opening、partial regenerate、session lifecycle 都已有代码路径

但它仍然是原型，离“稳定主链”还有明显距离。问题不在于能不能跑，而在于：事实层是否足够稳、fallback 是否足够保守、连续多轮后会不会轻微漂移累积成明显失真。

## 当前主优点

当前这套原型比旧 transcript-first 链路更好的地方：
- `runtime-rules / state / summary` 的优先级已经明显高于纯 transcript 惯性
- session-local 写回已经落地，不再直接把在线会话当唯一真相源
- opening 已经独立成状态机，而不是把“开始游戏”当普通用户输入
- partial reply 已被隔离，不再直接污染后续 state
- arbiter、threads、important NPC、persona 这几层已经开始进入统一主链
- narrator / turn_analyzer / state_keeper 已具备分模能力，而不是全部绑死在一套模型配置上

## 这轮收紧的内容

本轮额外收紧了几处会直接影响稳定性的低风险问题：
- `bootstrap_session.py` 不再靠 `canon` 文本内容判断“是否已初始化”，而是按 session-local 文件是否存在判断，降低重复 bootstrap 风险
- `handler_message.py` 现在支持首轮直接输入数字/标题/`随机开局` 进入 opening choice 分支，不必先看一轮菜单
- opening 菜单未选定时，错误输入不会误入正常 runtime 主链，而是继续停留在 opening guard
- 已进入开局后再次输入开局命令时，guard 回复现在也会写入 history，避免界面和历史不一致
- `server.py` 为 `POST /api/message`、`new-game`、`delete-session`、`regenerate-last` 增加了 session 级串行锁，降低同一 session 并发写冲突
- `regenerate_turn.py` 回滚幂等缓存时改为按 `turn_id` 清理，而不是盲删最后一个缓存项
- `frontend/app.js` 在切换 session、刷新、新游戏、删除后会重置 entity/detail/debug 侧栏，避免残留旧会话信息
- state snapshot 现在由后端直接提供 `onstage_entities / relevant_entities`，前端不再用名字反查 `entity_id`
- `frontend/app.js` 对同名实体采取保守策略：若存在多个同名实体，前端不再给出可能错误的详情入口
- `state_keeper.py` 现在已加入低信号拒收和相对上一轮 state 的回归检查
- `state_updater.py` 现在更偏保守继承，减少弱推断覆盖强状态
- `state_fragment` 已前移到主链，并在 `state_keeper` 失败时形成 `fragment-baseline -> heuristic fallback` 的双层兜底
- `runtime.json` 里的 `default_debug / show_debug_panel / history_page_size` 已贯通到 API 与前端
- 对已污染的旧 session，现已验证可通过离线重建方式直接把主状态从旧开局壳拉回当前剧情
- 前端默认会话选择已改为最近更新会话优先；旧的 `story-live` 不再应默认抢占入口
- 角色卡侧栏已改为动态读取角色卡元数据与缩略封面，不再直接吃原始大图
- narrator 输入层已加入更通用的信息边界提示，不再只针对“主角独知观察”做窄补丁
- `README.md`、`API.md`、`OPERATIONS.md` 已改为反映当前代码现状，而不是旧草图

## 当前仍然最关键的问题

### 1. `state_keeper` 仍主要依赖 narrator prose 反提

这是当前最大的结构性问题。

影响：
- narrator prose 一旦漂，state 会跟着漂
- 若 narrator 写得漂亮但信息稀，state 就会出现“字段齐但内容弱”
- 一旦 fallback `state_updater` 接管，信息质量会进一步下降

结论：
- 这块仍然是当前第一优先级
- 更理想的方向是让 narrator 同轮直接产出受约束结构化产物，或让 state keeper 使用更强约束输入，而不是纯 prose 反提

### 2. fallback state 仍偏松

`state_updater.py` 已比之前收口，而且现在前面多了一层 `fragment-baseline`，但它最后一跳本质仍是启发式兜底。

影响：
- 当 `state_keeper` 失败时，系统会继续可用，而且比之前更稳，但状态质量仍不如真正稳定的结构化提取主路
- opening、匿名实体、群体对象等场景仍容易被压扁成模糊字段

结论：
- fallback 可以保命，但还不能当可靠主路

### 3. 重要人物 / 线程 / summary 之间仍会互相放大弱信号

目前这三层都已经进入主链，但耦合也更强了。

影响：
- 一个弱判断可能先进入 state，再被 summary 固化，再反过来推高 important NPC 或 thread tracker 的权重
- 一次性服务 NPC 偶发高估仍没有完全根治

结论：
- 需要继续收紧 retained 条件和降权条件
- 尤其要盯“连续互动”和“承载主推进”的证据门槛

### 4. 同名实体仍缺完整 disambiguation

本轮已经把实体展示结构前移到后端，前端不再名字反查；但交互上仍只是保守展示，没有完整 disambiguation UI。

影响：
- 至少不会误点到错误实体
- 但还没有真正的同名实体区分交互

结论：
- 这是小问题，但会持续影响可观察性
- 后续应让 state snapshot 直接给前端可展示的 `entity_id + display_name + short role` 列表，而不是前端再拿名字回查

### 5. web 配置到 UI 的映射已打通，但还不完整

当前已打通：
- `default_debug`
- `show_debug_panel`
- `history_page_size`

但还没打通：
- `show_state_panel`

影响：
- 已接通的配置现在真的会改变前端行为
- 但仍有一部分配置停留在“有定义、未消费”的状态

结论：
- 下一步要么继续把 `show_state_panel` 接到布局层
- 要么删掉未消费配置，避免假配置继续积累

### 6. 主角 runtime 与事件归档层仍缺位

当前系统已经开始把 NPC、线程和摘要分层，但主角与已解决事件仍缺独立层。

影响：
- 主角 observer / user-side 信息若污染到 NPC 层，后续会被 `important_npcs`、threads、summary 一起放大
- 已解决的重要事件退出 active state 后，仍主要依赖 summary 和记忆层保留，不够明确

结论：
- 后续应补 `protagonist_runtime`
- 后续应补 `resolved_events / archived_threads`

### 7. NPC 间信息隔离仍主要靠软约束

当前系统已经开始把串化 observer 污染从状态层清掉，也补了 narrator 侧的通用知情边界提示，但这仍不是硬性的 knowledge scope 系统。

影响：
- 某个 NPC 独自看到/听到/推测到的信息，仍可能在叙事层被不够严谨地扩散给其他 NPC
- 新登场 NPC 是否该知道前文信息，仍主要依赖 prompt 和模型自觉，而不是独立数据结构

结论：
- 后续应补 `knowledge_scopes / protagonist_known / npc_local_known / public_known`
- narrator 和 state 只应消费这些显式知情层，而不是继续默认从 prose 反推

## 建议的下一步优先级

1. 保持 narrator 继续使用强远端模型，同时把 `state_keeper` 优先切到更稳定的本地结构化模型路径，并以保守模式使用
2. 若本地结构化模型效果稳定，再评估是否把 `turn_analyzer` 也切到同一路本地模型
3. 继续收紧 `state_keeper` 输入和有效性判断，减少“结构完整但信息空洞”的写回
4. 继续收紧 important NPC 和 thread tracker 的保留条件
5. 再决定是否还需要进一步压缩 `state_updater` 的自由度
