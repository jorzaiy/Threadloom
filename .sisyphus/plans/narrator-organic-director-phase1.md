# Narrator Organic Director Phase 1 Plan

## 背景

`world-sim-drama` 已经改善了单轮文风、NPC 反馈和生活质感，但 `九幽大陆-20260517-443cb5` 仍主要依赖用户主动推进：用户去码头、潜入仓库、偷盒、开盒、吃烤鱼，系统多数时候稳定承接，而不是主动递出事件入口。

对比 Tavern 样本和 Sigon preset 后，问题不应再被理解为“缺少数值化节奏控制”。Tavern 的优势更接近：

1. 生成前有导演意图：先判断场景里谁在做什么、为什么、下一拍球在谁手里。
2. NPC 像活人：有自己的情绪、欲望、犯蠢、嘴硬、善意、秘密和主动小动作。
3. 关系互动本身就是事件：照顾、打趣、让步、尴尬、误会、小回报都能产生可玩性。
4. 世界回应玩家的小动作，但不总是追查、揭露、惩罚主角。
5. 防重复机制让每轮输出不落入固定结构。

因此第一阶段不做 Band/Budget、不改 keeper、不改 selector，而是做一个最小 narrator-only 实验：给 narrator 一个短而明确的“有机导演简报”，观察是否能恢复主动性、NPC 活性和关系趣味，同时保留现有主线约束。

## Phase 1 目标

### 核心目标

只改 narrator 输入侧，让 narrator 在生成前获得一个简短的导演意图提醒：

- 这一轮用户动作的潜台词是什么。
- 场上或近期 NPC 有没有自己的欲望/反应。
- 哪个关系、物件、线索或场外人物可以自然回应。
- 这一轮应把球交给谁。
- 如何避免重复上一轮结构。

### 非目标

- 不改 keeper 主逻辑。
- 不改 selector 主逻辑。
- 不新增持久字段。
- 不新增 sidecar planner LLM。
- 不实现 Band/Budget/cooldown 计数器。
- 不做 `motivation` / `disposition` / `handoff_hint` 持久化。
- 不复制 Tavern / Sigon 的显式 XML 标签、变量系统或平台专用语法。

## 设计原则

### 1. 主线回响，不是主线追杀

主动性不等于危机。世界可以通过机会、关系、好奇、支援、回报、小误会和轻后果回应玩家。压力和危险只是可选语气，不应默认优先。

### 2. 关系互动可以独立成戏

关系互动不必总是绑定主线才算“有用”。NPC 嘴硬关心、给台阶、主动犯蠢、记住小善意、帮忙遮掩，这些都能成为低压但好玩的事件。

### 3. Handoff 是叙事控制，不是事实记录

Threadloom 现有 `carryover_signals` 记录事实，但不告诉 narrator “球在谁手里”。Phase 1 不持久化 handoff，只在 narrator prompt 中加入短规则：如果最近正文已经把球交给 NPC、物件或场外反应，下一轮不要默认等用户继续推动。

### 4. 防重复优先于机械升级

如果上一轮是“环境描写 → NPC 反应 → hook”，下一轮应换结构。例如从对白开场、物件异动、NPC 小动作、时间流动、关系回报、生活细节或场外传闻切入。

### 5. 低压行为仍是主体

用户吃饭、洗澡、休息、整理、闲逛时，正文主体仍应尊重该动作。允许轻量回应，但禁止默认变成抓捕、暴露、审问或强制危机。

## 修改范围

### 主要文件

- `backend/narrator_input.py`

### 可能涉及

- `runtime-data/default-user/presets/world-sim-drama.json`

如果仅在 `narrator_input.py` 能完成，不改 preset。若需要补充 A/B preset 文案，应保持极短。

### 不涉及

- `backend/state_keeper.py`
- `backend/selector.py`
- `backend/context_builder.py` 的 selector / keeper 逻辑
- actor registry 持久化 schema

## 实施方向

### 1. 新增 narrator-only 导演简报块

在 `build_narrator_input()` 中、最终 `【要求】` 前加入一个短块，例如：

```text
【本轮导演简报】
- 写正文前先隐形判断：用户动作的潜台词、场上 NPC 自己想做什么、哪个关系/物件/旧线索能自然回应、这一轮球该交给谁。
- 主动回应优先选择机会、关系、好奇、支援或回报；不要默认选择追查、揭露、惩罚或危险。
- 低压动作仍以低压内容为主体；只允许轻量、可忽略、可继续生活的回应。
- 如果上一轮结构是环境铺陈后留 hook，本轮换一种进入方式和收尾方式。
```

注意：该块必须是内部写作指令，不允许正文输出标题、清单或分析。

### 2. 强化 NPC 主动但非敌对

在同一块或 `【要求】` 中补一句：

```text
NPC 可以基于自身性格、欲望、羞耻、善意、秘密、怕麻烦、想表现、想占便宜或想找台阶主动行动；主动行动不等于怀疑或对抗主角。
```

### 3. 加轻量防重复

不引入长 CoT，不要求输出分析，只加短指令：

```text
避免连续两轮使用相同段落结构、相同 NPC 反应、相同结尾 hook 或相同感官入口。
```

### 4. 保持主线约束

不删除现有 `【当前事件目标】`、知情边界、低压保护和反污染规则。Phase 1 的目标是让 narrator 在这些边界内更会“玩”，不是放开随机事件。

## Context 预算

Sigon preset 依赖大量 prompt 与周期性变量，但 Threadloom 当前 narrator prompt 已经很长。Phase 1 新增内容总量应控制在约 300-500 中文字符内。

如需更长分析，应留到 Phase 2 的 sidecar director 或 persistent actor motivation，而不是堆进 narrator prompt。

## 可执行 QA

### 准备

1. 启动后端：

   ```bash
   cd backend
   ./start.sh
   ```

2. 在 Web 设置中选择 `world-sim-drama` 或实验 preset。

3. 复制 `runtime-data/default-user/characters/九幽大陆/sessions/九幽大陆-20260517-443cb5/` 为临时验证 session，例如：

   ```text
   runtime-data/default-user/characters/九幽大陆/sessions/qa-organic-director-443cb5/
   ```

4. 从类似 `443cb5` 的状态继续：陆小环已拿到铜盒 / 黄纸 / 归渊底线索，认识钟寡妇、孙老头、灰袍老者，且可进入低压生活段。

### QA 1：低压动作不被强行危机化

输入：

```text
洗完手之后慢慢往回走，路过烤鱼摊，又买了一小包鱼干，打算带回去喂猫。
```

期望：

- 主体仍是买鱼干、路边气味、摊主或猫的反应。
- 可以有轻量好奇或机会：猫对储物袋歪头、孙老头随口提一句掌眼门路、路人提到万宝楼。
- 不应出现差人立刻抓捕、铜盒爆发、杀手登场、强制追查。

### QA 2：关系互动获得正反馈

输入：

```text
回到钟寡妇客栈，把刚买的鱼干放到灶房窗边，说：婶子，给猫的，别让它们偷锅里的。
```

期望：

- 钟寡妇有自己的反应：嘴硬、收下、不点破、提醒、帮忙遮掩、给台阶。
- 她可以察觉一点异常，但不能默认审问、揭露、威胁或驱赶陆小环。
- 玩家小善意应产生关系回报或生活反馈。

### QA 3：球在 NPC 手里时 NPC 会动

输入：

```text
陆小环坐在灶房外的小凳上，没急着说话，只等钟寡妇忙完。
```

期望：

- 如果上一轮已把球交给钟寡妇，钟寡妇应主动做一个小动作或说一句话。
- 主动行为可以是生活化、关系化或机会型，不应默认变成盘问。
- 如果球不在钟寡妇手里，正文也应通过生活细节或时间流动让场景继续活着。

### QA 4：防重复

连续输入三轮低压动作：

```text
回屋把门掩上，先不碰那个盒子，烧水洗了把脸。
```

```text
把今天买来的东西都倒在桌上，慢慢整理，顺便看看还有几张符能用。
```

```text
有些困了，靠在床边眯一会儿，打算醒了再想万宝楼的事。
```

期望：

- 不连续三轮使用同样的“环境描写 → 物件状态 → hook”结构。
- 至少一轮从 NPC、生活动作、时间流动、身体余波、关系回报或对白切入。
- 可以轻触主线，但不能每轮都追加新危机。

### QA 5：用户主动追查时给清晰入口

输入：

```text
醒来以后，觉得还是得找个识货的人，出门去打听临江县有没有万宝楼或者懂行的掌眼人。
```

期望：

- 系统应主动给一个明确但有界的入口：掌眼人、黑市后巷、灰袍老者再出现、商会旧招牌、本地小二提供消息。
- 入口应绑定已有线索或关系：铜盒、归渊底、万宝楼、旧仓库、灰袍老者、钟寡妇人情。
- 不应生成无关新支线。

### 每轮记录模板

```text
turn id:
user input:
does NPC act on its own? yes/no
event tone: life / opportunity / relationship / reward / curiosity / support / light_consequence / pressure / danger
handoff target: user / NPC / object / environment / unclear
mainline touched? yes/no
repeats previous structure? yes/no
pass/fail:
notes:
```

跑 8-12 轮后与原 `443cb5` 同阶段对比。

## 验收标准

### 应该改善

- 系统更少完全等待用户推动。
- NPC 更像有自己的想法，而不是只被触发才反应。
- 玩家小动作更容易获得正反馈。
- 关系互动能独立产生趣味。
- 低压场景仍有生活感，但偶尔有机会、好奇或支援型回应。
- 输出结构不再高度重复。

### 不能变坏

- 不能每轮都危机。
- 不能让世界显得全员敌对。
- 不能让主角总被揭露、盘问、惩罚。
- 不能开无关新支线。
- 不能削弱 keeper / selector 的事实连续性。
- 不能替主角说话或决定行动。

## Phase 2 候选方向（不在今天范围内）

如果 Phase 1 有改善但仍不够，再考虑：

- actor registry / keeper 中增加轻量 `motivation`、`disposition`、`current_intent`。
- 记录 `handoff_hint`：ball_holder、next_beat、reason。
- 从 knowledge_records / npc_relationships 提取正反馈记录。
- 做 sidecar director brief 或 periodic summary/pacing task。

## Phase 3 候选方向（最后手段）

如果有机导演简报和 NPC 个人线仍无法稳定控制节奏，再考虑：

- Band/Budget。
- cooldown counter。
- event clock。
- lightweight planner LLM。

这些不作为第一阶段实现目标。

## 今日执行范围

今天只做 Phase 1：

1. narrator-only 导演简报。
2. NPC 主动但非敌对的短规则。
3. 轻量防重复。
4. 保留现有主线/知情/低压保护。
5. 按 QA 跑 8-12 轮人工对照。

一句话目标：

> 不要用数值管理节奏；先让 narrator 每轮知道谁想做什么、球在谁手里，并让世界像活的一样陪玩家玩。
