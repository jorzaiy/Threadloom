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
cp /Threadloom/.env.local.example /Threadloom/.env.local
cd /Threadloom/backend
./start.sh
```

说明：
- `backend/start.sh` 会自动加载 `/Threadloom/.env.local`
- 推荐把真实密钥只放在 `.env.local`，`config/*.json` 中使用 `env:VAR` 引用
- 当前用户自己的站点与模型配置会写到 `runtime-data/<user>/config/`
- `config/runtime.json` 继续承载共享内容层与全局策略，不再作为用户站点管理的主存储
- 当前用户模型/站点文件：
  - `runtime-data/default-user/config/site.json`
  - `runtime-data/default-user/config/model-runtime.json`
- 当前设置页已简化为单站点模式：
  - 用户只维护一个站点 URL / API Key / API 类型
  - 先点“获取模型”
  - 再给 Narrator / State Keeper 选模型
  - `temperature / max_output_tokens` 不再暴露给普通用户，统一走 `config/runtime.json -> model_defaults`

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
- 点击顶部当前会话名，展开最近会话下拉
- 最近会话下拉支持切换、删除、开始新游戏
- 最近会话按最后一条消息时间从新到旧排列
- 发送消息
- partial 时重新生成上一条
- 右侧状态面板和 NPC 详情查看
- 折叠调试区
- 居中设置弹窗

## 当前运行特点

当前 prototype 的重要行为：
- 新 session 会从 root `canon / summary / state` bootstrap，不从空壳 state 起步
- opening 已经是独立状态机，不再只是输出一段开局提示
- 同一 `session_id` 的 HTTP 写请求现在会串行执行，降低并发覆盖风险
- 每个 turn 现在会额外落一份 `turn-trace/turn-XXXX.json`，用于单回合精确回放
- `runtime.json -> trace.enabled / trace.keep_last_turns` 可控制 trace 是否启用以及最多保留多少轮
- partial assistant 回复会显示，但不会继续污染事实层
- `regenerate-last` 会回滚最后一对 `user -> assistant(partial)` 再重试
- `state_keeper` 优先，`state_updater` 兜底
- `state_keeper` 现在会拒收明显低信号或相对上一轮明显退化的 state
- `state_fragment` 现在会先作为结构化锚点进入 narrator 与 state_keeper
- `state_keeper_candidate` 现在可以作为 `skeleton keeper` sidecar 先产出最小骨架，再并入 `state_fragment`
- 完整 `state_keeper` 当前已切到 `fill-mode`：默认只在骨架状态上补 `scene_core / immediate_risks / carryover_clues` 这类次级字段，而不再整份重写 state
- 轻量物件状态层已接入：
  - `tracked_objects`
  - `possession_state`
  - `object_visibility`
- 物件层当前已可在真实 live 回合中落下基础结果：
  - 物件可进入 `tracked_objects`
  - 玩家持有可映射到主角名
  - 物件可见性可写回 `object_visibility`
  - `纸条 / 短刀` 这类动作物件已可在 live 验证中进入 `tracked_objects`
- 若 `state_keeper` 失败，当前会先走 `fragment-baseline`，再让 heuristic fallback 在其上补细节
- `state_keeper` 不可达时，物件状态 fallback 已不会再因为正则模板格式化错误而崩掉；此时仍可正常产出 turn trace
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
- 直接看 `sessions/<session_id>/turn-trace/turn-XXXX.json`，确认本轮 pre-turn / narrator / keeper / post-turn 是否符合预期
- 若当前环境下 narrator / keeper 模型不可达，也可以先故意在本地跑一轮，拿到 fallback 产出的 trace，再用单回合回放调 `threads / important_npcs / persona / summary`
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

单回合精确回放：

```bash
cd /Threadloom
python3 backend/replay_turn_trace.py --source-session story-live --turn-id turn-0012 --target-session replay-story-live-turn-0012
```

说明：
- 这条链不重新开局，也不重新发送整段历史
- 它会从 `sessions/<source>/turn-trace/turn-XXXX.json` 里恢复该回合的 pre-turn 状态与人格层
- 然后只重跑该回合的后半段写回链，适合快速调 `threads / important_npcs / persona / summary`

SillyTavern 聊天导入：

```bash
cd /Threadloom
python3 backend/import_sillytavern_chat.py --source '/root/Threadloom/tmp/你的聊天记录.jsonl' --target-session import-your-chat-001
```

当前第一版行为：
- 支持导入单角色 SillyTavern `jsonl` 聊天导出
- 首行 `chat_metadata` 会单独保留到 `imports/sillytavern-chat-metadata.json`
- 原始导出文件会复制到 `sessions/<session_id>/imports/`
- 消息正文只导当前采用的 `mes`
- `extra.reasoning`、`swipes`、`swipe_info` 当前不会进入 Threadloom 主历史

当前第一版边界：
- 还不处理 group chat
- 还不保留 swipe 分支到 Threadloom 历史
- 导入后只是先生成 session 与 `history.jsonl`
- 后续仍建议再接一次 replay / state 重建，把 `state / summary / persona / threads` 真正建起来

当前 history-only 重建链补充：
- `backend/rebuild_session_from_history.py` 现在支持：
  - `--target-session`
  - `--force-recreate`
- 推荐总是在副本 session 上做离线重建测试，不直接覆盖原始导入档。
- 当前 `state` 主路径在副本测试里的最新状态：
  - `onstage / scene_entities` 已明显变干净
  - `relevant_npcs` 已能非常有限地补回稳定离场人物
  - `active_threads` 已可稳定收成 `main / risk / clue`
  - 长窗口下旧幽灵实体不会再回流污染现代题材样本
  - 物件层在导入样本中已能开始产出 `tracked_objects / possession_state / object_visibility`

当前存档分层重构进度：
- 目标结构已经明确为：
  - 用户层：`USER.md`、`player-profile.*`、`presets/`
  - 角色卡层：`character-data.json`、`lorebook.json`、`canon.md`、静态 NPC 资料
  - session 层：`history/state/summary/persona/trace/imports/meta/context`
- `backend/paths.py` 与核心 store/lifecycle 模块已开始接入这套三层路径模型。
- 现在已经有显式来源抽象：
  - `user.*`
  - `character.*`
  - `session.*`
- 新路径模型已能描述用户层 / 角色卡层 / session 层的目标目录，而不是只靠旧的平铺 `sources` 字符串路径。
- 当前仍处于“兼容式第一阶段”：
  - 新路径模型已建立
  - 旧 `/sessions` 与旧根目录资源仍可继续读取
  - 还没有执行真实迁移，不会立刻搬动现有数据
- 当前结论：暂不急着上数据库记录元数据；先把目录分层、显式来源解析和迁移链做稳，再评估是否需要 SQLite 之类的元数据层。
- 第二阶段迁移补充：
  - `backend/migrate_storage_layout.py` 现已支持把旧 session 复制到新角色卡层下的 session 根。
  - 新建 session 已确认可以真实落到新根：
    - `runtime-data/default-user/characters/<character_id>/sessions/<session_id>`
  - 当前仍属于“兼容期”：
    - 新根已可写
    - 旧根仍保留作回退与数据兜底
  - 暂不建议立刻引入数据库；等新根稳定跑一段时间、用户层/角色卡层/session 层都真实使用起来后，再评估是否用 SQLite 记录元数据。

旧 `sessions/` 清理前的最后安全检查：
- 现在可用：
  - `python3 backend/audit_legacy_sessions.py`
- 这个脚本会把旧根目录分成几类：
  - `safe_delete_now`
  - `legacy_only_session_like`
  - `legacy_only_other`
  - `mirrored_equal`
  - `mirrored_different`
- 当前实测结果：
  - 旧 `/root/Threadloom/sessions` 里只剩 `12` 个目录，而且全部是 `archive-*`
  - 其中 `9` 个是空壳 archive，可直接删除
  - 当前阻止整个旧根直接删除的只有 `3` 个目录：
    - `archive-20260408-140823-story-live`
    - `archive-20260411-130423-story-live`
    - `archive-20260405-cleanup`
- 当前清理建议：
  - 先删空壳 archive
  - 若想保留旧 archive 历史，先跑：
    - `python3 backend/migrate_storage_layout.py --include-sessions --include-archives`
  - 再次运行 `python3 backend/audit_legacy_sessions.py`
  - 只有当 `blocking_items` 为空时，才删除整个旧 `sessions/` 根目录
- 本轮实际执行结果：
  - 旧根里的空壳 archive 已删除
  - `archive-20260408-140823-story-live` 与 `archive-20260411-130423-story-live` 已复制到新 session 根
  - `archive-20260405-cleanup` 不属于标准单 session，已单独移动到：
    - `runtime-data/default-user/characters/<character_id>/legacy-archives/archive-20260405-cleanup`
  - 旧 `/root/Threadloom/sessions` 已清空并删除
  - 当前审计结果已变为：
    - `legacy_count = 0`
    - `blocking_items = []`

四要素现状：
- 时间：已接近可用，优先吃场景头与显式时间推进，稳定度较高。
- 地点：已接近可用，优先吃场景头与显式转场，稳定度较高。
- 人物：当前最接近可用，`onstage / relevant / scene_entities / important_npcs` 已基本进入可控状态。
- 事件：已可用，但 `main_event / scene_core / goal / risks / clues` 的文案仍偏模板化，后续更像体验优化而非结构修 bug。
- 物品：链路已通，且已在 live 回合中成功落下基础结果；当前主要剩余问题是精度、归一化和部分动作物件的稳定性。
  - 当前 keeper 侧已支持把 `player_inventory / protagonist / 主角 / 玩家 / 自己` 这类值归一化到主角名。

空白起步与首页加载补充：
- 现在前端与后端都已修正：
  - 当 session 列表为空时，不再默认用 `story-live` 自动请求 `history/state`
  - `/api/sessions` 在空列表时，`default_session_id` 现在返回空字符串，不再硬塞 `story-live`
  - `/api/history` 与 `/api/state` 对不存在的 session 现在只返回空结果，不会顺手 bootstrap 出一个新目录
- 这意味着：
  - 清空当前角色卡下的 session 后，页面保持空白等待用户点击“开始新游戏”
  - 不会再因为页面初始化而自动长回 `sessions/story-live`
- 当前首页变慢的判断：
  - 主要风险更像是 session 列表过多时的枚举与排序，而不是封面图本身
  - 角色卡缩略图当前文件约 `267 KB`
  - 已给 `/character-cover` 增加缓存头，减少重复加载成本

## State TODO

今天已经确认的结论：
- `state_updater.py` 不能继续走“按题材/角色卡补关键词”的路线。
- SillyTavern 导入样本已经证明：旧 heuristics 会把异题材长记录拉回旧武侠幽灵状态。
- 当前在线 RP 仍然应该优先，离线历史重建只作为压测和回归验证手段。

明天继续时的主方向：
- 重构 `backend/state_updater.py` 主路径为 `previous-state-driven merge`，而不是全文题材分类。
- 使用 `1` 轮主更新 + `2-3` 轮连续性窗口：
  - `time / location / main_event` 以最近一轮显式变化为主，默认继承上一轮。
  - `onstage / relevant / scene_entities` 用 `2-3` 轮窗口做连续性稳态。
- `main_event / scene_core / immediate_goal / immediate_risks / carryover_clues` 只允许结构化、低想象力的增量生成，不再靠题材关键词猜世界。
- 旧武侠 heuristics 只保留在 legacy fallback，不再作为主逻辑。

实体主路径的收缩原则：
- 只允许这几类来源进入实体候选池：
  - 已知稳定名字池：`source_name`、已有 `scene_entities`、`important_npcs`、导入时的 `character_name / user_name`
  - 明确命名结构：`我叫X / 他叫X / 她叫X / 名叫X / 叫做X`
  - 结构上独立出现的人名：例如独立在引号、换行、标点边界上的名字
- 禁止从自由 prose 中裸扫任意中文片段当名字。
- 若没有足够置信度，宁可少报实体，也不要生成伪实体。

明天优先顺序：
1. 先把实体候选来源收紧，解决 `到背后那 / 几个还没 / 声响` 这种伪实体。
2. 再稳定 `onstage / relevant / scene_entities`。
3. 最后再继续收口 `main_event / scene_core / goal / risks / clues`。

当前阶段性结果：
- `extract_generic_character_names()` 已收成“严格候选筛选器”。
- 第一轮样本里，`维克托·奥古斯特 / 高崎` 已能同时保住。
- `少年` 这类旧 fallback 泄漏的 relevant 已被清掉。
- `active_threads` 的轻量去重已经接上，当前可稳定收成 `main / risk / clue`。
- 正常在线 RP 风格样本验证已通过：一轮一轮的对话里，NPC 仍可被正常抓到。
- 长窗口副本验证已通过：旧 `伤者 / 被围攻者` 幽灵不会再在异题材样本中反污染回来。
- `relevant_npcs` 当前已从“乱抓”进入“非常有限地补回稳定离场人物”的阶段。
- live 物件验证已通过：
  - `纸条` 可进入 `tracked_objects`
  - 玩家持有可映射到主角名
  - `短刀` 也已开始进入 live state
- 进一步的 live 物件验证已通过：
  - `纸条 / 短刀` 可同时进入 `tracked_objects`
  - `师兄 / 陆小环` 这类持有者已可落入 `possession_state`
  - 物件层已进入“live 可用、精度继续优化”的阶段
- 目前剩下的主要问题已经不是污染，而是文案仍偏模板化，以及物件层还需要继续精修精度与归一化。

明天可对比的第二路线：
- 评估是否让 `Llama-3.3-70B` 只承担“候选提取器”职责，而不是直接重写整份 state。
- 若尝试这条线，职责应限制为：
  - 从最近 `1-3` 轮里提取 `entity candidates`
  - 提取显式 `time / location` 候选
  - 提取 `goal / risks / clues` 候选
  - 每项都带 `confidence + evidence`
- 本地 merge 层仍负责：
  - 默认继承上一轮 state
  - 只接受高置信更新
  - 对实体做 add/retain/alias merge，不让模型直接删除稳定实体
- 明天需要比较：
  - 继续收紧本地通用 extractor 是否已经足够
  - 还是需要引入 `Llama-3.3-70B` 做候选提取器来提高跨题材抽取能力

今天补充实验结果：
- 已安装 `jieba`，并尝试把它接成可选的实体边界辅助层。
- 当前结论：
  - `jieba` 更适合做“候选边界辅助/坏候选否决器”，不适合直接当实体真相源。
  - 对当前样本，`jieba` 尚未直接解决 `维克托·奥古斯特已 / 再 / 淡` 这类截断伪实体。
  - 当前实现还暴露了性能问题：若每次提取都重建 tokenizer，离线重建会明显变慢。
- 明天若继续这条线，应先做：
  - tokenizer 缓存
  - 只对严格候选池做 `jieba` 校验
  - 不再让 `jieba` 参与自由文本候选生成

测试约束：
- 继续用导入的 SillyTavern 长记录做压测，但不要为了某一张卡补专用规则。
- 需要做破坏性重建测试时，优先用副本 session，不直接污染原始导入档。

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
- 物件状态层已经接线完成，但当前真实回合中的抽取强度还不够；链路已通，实际产出仍需要继续调强
- 当前单回合精确回放已优先覆盖 runtime 主链；opening 菜单态暂不作为主要回放目标
- `state_updater.py` 当前仍处于主路径重构中；旧 heuristics 已被证明会对异题材记录产生幽灵状态，明天应继续把它们下沉到 legacy fallback

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
