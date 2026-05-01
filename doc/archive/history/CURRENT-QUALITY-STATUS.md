# Current Quality Status

更新日期：2026-04-27

## 当前结论

当前项目经过多轮代码修复和真实 HTTP 回归后，`keeper` 独立归档链与 `selector` 决策链可运行；本轮已补强 keeper 写入质量边界、JSON 响应约束和 fallback 诊断，但即时人物抽取与部分场景锚点质量仍需继续观察。

当前不能认为“核心状态链已经完全稳定”，但 keeper 的写入防污染、防重复和 object/knowledge 分层边界已有明确代码保护与回归测试。

2026-04-27 追加排查结论：`碎影江湖-20260426-942316` 的频繁漏写主要不是磁盘保存失败，而是 full `state_keeper` 多轮 JSON 解析失败后进入 `fragment-baseline` fallback；旧逻辑会把 `state_keeper_bootstrapped` 重新置为 `false`，导致后续回合持续被当作 bootstrap turn，跳过 skeleton keeper，并反复触发容易失败的 full keeper。已修复为：当 fallback fragment/skeleton 已经提供可用核心骨架时，允许退出 bootstrap retry 模式，后续回合恢复 skeleton keeper 的每轮骨架更新。

特别说明：`碎影江湖-20260426-942316` 当前可继续游玩的高质量记忆包含人工整理结果，不能作为 keeper 自动写入能力已经全面达标的证据。后续判断 keeper 是否稳定，应观察该 session 继续游玩后的新增回合，而不是把整理后的派生文件当成自动产物。

## 已确认的现状

### 1. 已有改善

- 启发式人物抽取不再主要依赖关键词黑名单
- 描述型人物标签已开始规范化为更稳定的 `scene_entities.primary_label`
- `scene_entities` 已支持 `collective` 和 `count_hint`
- `carryover_signals / immediate_risks / carryover_clues` 已从整句抄写，改为更短的状态化短句
- `keeper archive` 和 `npc_registry` 的独立质量明显高于即时 `state_snapshot`
- 即时 state 主链已加入“单轮坏抽取导致整条链坍缩”的保护逻辑
- `knowledge_scope` 已改为本轮 delta，长期知识进入 `knowledge_records`，并做同 holder 下轻量相似去重
- object patch 不再回填 baseline 全量对象；`consumed / destroyed / lost / archived` 物件会退出 active 层并进入 `graveyard_objects`
- `possession_state` / `object_visibility` 支持合法新状态覆盖旧状态，非法 holder 不覆盖旧合法归属
- keeper archive refresh 会 prune rollback 后的未来 records，避免 undo / regenerate 旧分支污染召回
- `state_keeper` / `state_keeper_candidate` 默认启用 JSON object 响应模式，降低成功 HTTP 调用返回非 JSON 文本导致的 fallback
- keeper fallback 诊断现在保留真实 `model_usage`，并记录 `raw_reply_empty`、`raw_reply_excerpt`，便于区分“没调用”“空回复”“非 JSON 回复”“schema 失败”
- full keeper 失败时不再无条件把 session 留在 bootstrap retry 模式；可用 fragment/skeleton fallback 会标记为已完成 bootstrap，避免后续每轮跳过 skeleton keeper

### 2. `碎影江湖-20260426-942316` 记忆整理状态

本次为继续游玩手工整理了 `碎影江湖-20260426-942316` 的 session-local 派生记忆：

- `memory/state.json`
- `memory/summary.md`
- `memory/keeper_record_archive.json`
- `memory/summary_chunks.json`

整理后的当前锚点：

- 地点：`神都坊署偏厅`
- 当前阶段：陆小环在偏厅向文吏录口供
- 在场人物：`文吏`、`小差役`
- 关键物证：`纸封`
- 关键线索：纸封由巡捕从医馆外役车上找到并带回坊署，内容未公开；年轻男子不是逃犯；受伤皂衣人称拿钱办事但不供雇主；提灯首领不开口

已清理的旧污染包括：`潜行`、`event-stealth-001`、`暴露风险`、`被惊动压`、`待确认 黄昏`、地点滞后到 `神都东坊外巷口檐下`。

整理前备份已保留在该 session 的 `memory/` 目录中：

- `state.json.pre-play-cleanup-20260427`
- `summary.md.pre-play-cleanup-20260427`
- `keeper_record_archive.json.pre-play-cleanup-20260427`

这次整理是人工纠偏，不是 keeper 自动从历史里一次性生成了这些高质量文件。继续游玩后如需分析，应重点检查新增 turn trace 中的 `state_keeper_diagnostics`、`raw_reply_empty`、`raw_reply_excerpt`、`model_usage`，以及新增回合是否继续保持 `坊署偏厅 / 口供 / 纸封` 等关键锚点。

### 3. 仍然存在的问题

- 即时人物抽取仍不稳定
  - 早期问题：会把 `殷勤`、`老汉先赔`、`守门军嗤` 这类错误片段当成人物
  - 当前问题：修复尾部动作剥离后，人物候选又变得过严，`掌柜`、`老汉`、`学徒` 这类称呼型人物容易被漏收
- `main_event` 仍可能长期停留在旧坏值，不能稳定跟随当前阶段推进
- `important_npcs` 仍容易被上游即时 state 污染；虽然已增加 keeper registry 补强，但整体稳定性仍不够
- `selector` 本身可运行，但其质量仍高度依赖上游 `state_snapshot`，因此会被错误人物或空人物输入拖低效果
- `summary.md` 在真实回归中仍经常没有实际落盘文件；不能把“可读取默认 summary 文本”等同于“summary 已成功写回”
- full keeper 仍可能因为模型非 JSON 输出而 fallback；本次修复解决的是 fallback 后的 bootstrap 循环放大问题，不代表 full keeper JSON 成功率已经完全稳定

## 与文档仍需注意的地方

### 1. summary 写回表述不准确

文档写法容易让人理解为 session-local `summary` 会稳定落盘；真实回归并不支持这个结论。

### 2. 旧报告结论已过期

`DOC_AUDIT_REPORT.md` 中“代码与文档一致性 100%”的结论已失效。

## 当前最需要继续修复的部分

### 第一优先级

1. 称呼型人物的通用准入
   - 目标：让 `掌柜`、`学徒`、`老汉`、`官差` 这类中文叙事中的人物称呼，在明确动作/说话语境下被稳定收进 state
   - 要求：不能靠角色卡关键词或卡专属词表

2. 即时 state 主链的人物稳定性
   - 目标：避免错误候选进入 `scene_entities / onstage_npcs / relevant_npcs`
   - 目标：避免修复错收后又变成漏收

3. `main_event` 的坏值淘汰与阶段更新
   - 目标：让 `main_event` 更稳定地跟随当前 1-3 轮阶段总结推进，而不是长期停留在旧对白或旧场景片段

### 第二优先级

1. `important_npcs` 的抗污染能力继续提升
2. `selector` 在 state 较弱时对 keeper registry / continuity 的利用增强
3. `summary` 落盘策略与触发条件澄清
4. keeper 写入质量继续做 HTTP 长跑回归，观察 `knowledge_records` 膨胀率、`graveyard_objects` 是否误归档、非法 holder 拦截是否过严

## 下一步计划

### 计划中的修复顺序

1. 修通“称呼型人物”的通用准入规则
   - 重点不是加词表，而是基于中文叙事结构识别“人物主体 + 动作/说话尾巴”

2. 在修复称呼型人物后，重新跑最小 HTTP smoke
   - 检查是否仍出现错误人物
   - 检查是否出现“全部漏收”

3. 再跑一轮 13+ 轮 HTTP 回归
   - 重点观察：
   - `scene_entities`
   - `onstage_npcs / relevant_npcs`
   - `important_npcs`
   - `main_event`
   - `carryover_signals`
   - `keeper archive`
   - `selector.npc_roster`

4. 根据回归结果继续修 `main_event` 和 `important_npcs`

## 当前建议

在下一轮修复完成前，不建议把当前状态链描述为“已稳定”。

更准确的说法是：

- `keeper` 与 `selector` 已可运行，keeper 写入质量边界已有回归测试保护
- 即时 `state` 主链正在修复中
- 长记录稳定性已有提升，但人物抽取仍是当前第一瓶颈
