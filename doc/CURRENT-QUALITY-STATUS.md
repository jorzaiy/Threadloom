# Current Quality Status

更新日期：2026-04-24

## 当前结论

当前项目经过多轮代码修复和真实 HTTP 回归后，`keeper` 独立归档链与 `selector` 决策链可运行，但即时 `state` 主链仍存在明显质量问题。

当前不能认为“代码与文档完全一致”或“核心状态链已经稳定”。

## 已确认的现状

### 1. 已有改善

- 启发式人物抽取不再主要依赖关键词黑名单
- 描述型人物标签已开始规范化为更稳定的 `scene_entities.primary_label`
- `scene_entities` 已支持 `collective` 和 `count_hint`
- `carryover_signals / immediate_risks / carryover_clues` 已从整句抄写，改为更短的状态化短句
- `keeper archive` 和 `npc_registry` 的独立质量明显高于即时 `state_snapshot`
- 即时 state 主链已加入“单轮坏抽取导致整条链坍缩”的保护逻辑

### 2. 仍然存在的问题

- 即时人物抽取仍不稳定
  - 早期问题：会把 `殷勤`、`老汉先赔`、`守门军嗤` 这类错误片段当成人物
  - 当前问题：修复尾部动作剥离后，人物候选又变得过严，`掌柜`、`老汉`、`学徒` 这类称呼型人物容易被漏收
- `main_event` 仍可能长期停留在旧坏值，不能稳定跟随当前阶段推进
- `important_npcs` 仍容易被上游即时 state 污染；虽然已增加 keeper registry 补强，但整体稳定性仍不够
- `selector` 本身可运行，但其质量仍高度依赖上游 `state_snapshot`，因此会被错误人物或空人物输入拖低效果
- `summary.md` 在真实回归中仍经常没有实际落盘文件；不能把“可读取默认 summary 文本”等同于“summary 已成功写回”

## 与文档不一致的地方

### 1. keeper 主链表述过强

`README.md` 目前把当前 keeper 主链写成默认已经稳定运行的 `skeleton keeper + fill keeper` 双层链，但当前运行配置和真实回归结果不能支持这种强结论。

### 2. summary 写回表述不准确

文档写法容易让人理解为 session-local `summary` 会稳定落盘；真实回归并不支持这个结论。

### 3. 旧报告结论已过期

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

- `keeper` 与 `selector` 已可运行
- 即时 `state` 主链正在修复中
- 长记录稳定性已有提升，但人物抽取仍是当前第一瓶颈
