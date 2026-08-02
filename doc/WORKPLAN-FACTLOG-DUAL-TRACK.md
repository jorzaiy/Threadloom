# 工作计划：fact-log 双轨收口（写回切片）

**日期**：2026-07-11（更新：2026-07-12）  
**状态**：第 1 步代码已合入（写回**默认关**）；真实 session 基线已跑；**尚未默认开**  
**背景**：`memory-v2` 上 fact-log 已影子写入 + narrator【人物档案·权威】部分接管，但 `state.json` 仍由旧 reconciliation 写名单与 `last_event`。双轨拖久会放大每次改动成本。  
**相关**：`doc/MEMORY-V2-DESIGN.md`、`doc/ROADMAP.md`、`doc/OPERATIONS.md`、`backend/fact_log.py`、`backend/handler_message.py`、`backend/regenerate_turn.py`

---

## 当前进度（一览）

| 项 | 状态 |
|----|------|
| 影子 commit + 诊断 `factlog_shadow.jsonl` | ✅ |
| narrator 读侧权威块（`THREADLOOM_FACTLOG_NARRATOR`，默认开） | ✅ |
| `WRITE_IMPORTANT` 写回路径（schema 合并，默认关） | ✅ 代码就绪 |
| regenerate / delete-latest `truncate_after` + fact 文件 restore | ✅ |
| 投影：ephemeral 路人过滤 | ✅ |
| 投影：长期 inactive 淡出（≥20 轮，persona 锁定例外） | ✅ |
| 真实长 session 影子/投影基线 | ✅ 见下文「基线结论」 |
| 默认打开 `WRITE_IMPORTANT` | ❌ 未做 |
| 手测（UI + regenerate） | ❌ 未做（不必绑 b93051） |
| 第 2 步 `WRITE_ONSTAGE` | ❌ |

**一句话**：写回随时可开 flag 试；默认仍走旧 tracker。名单膨胀已靠 inactive 淡出压过一轮；欠并（如掌柜/周掌柜）与策略差（城门路人 vs 当前戏）还在。

---

## 原则

1. **第一刀不换 commit 形态**：`commit_turn` 继续吃 keeper 产出的 state（strangler），不先改成 prose→fact。
2. **第一刀不删大文件**：不先拆/删 `state_bridge` / `state_keeper`；先让投影成为**一小撮字段**的唯一写入者。
3. **读者尽量不动，但 schema 不能瘦死**：UI 主要读 `primary_label`；后端仍依赖 `locked` / `aliases` / `role_label` / `key` → **禁止**瘦投影 dict 整表裸替换。
4. **开关 + 可回退**：写/读开关分开；失败不覆盖、打日志、不阻断回合。
5. **语义检索 / NPC 目标 / persona 演化**：可并行，但**不算**收双轨。

---

## 不要从这些开刀

| 事项 | 原因 |
|------|------|
| 大拆/删除 `state_bridge` | 仍服务 time/location/objects/signals |
| 先做语义检索当双轨解药 | 解长尾召回，不解双写 |
| commit 直接 prose→fact | 终局；上游仍是 keeper |
| 一次切 onstage + important + 删 tracker | 面太大 |
| 瘦投影整表覆盖 `important_npcs` | 会弄坏 continuity/selector |

---

## 第 1 步：接管 `important_npcs`（含 per-entity `last_event`）

### Schema 合并（硬约束）

| 字段来源 | 字段 |
|----------|------|
| **投影权威** | 成员资格、`primary_label`、`present_now`、`last_main_event`、`last_location`、`inactive_turns` |
| **prev / entity 补齐** | `key`、`aliases`、`role_label`、`locked`、`importance_score`、… |

实现：`merge_projected_important_npcs(prev, projected, entity_aliases)`。

### 投影过滤（名单质量）

| 规则 | 常量/条件 | 效果 |
|------|-----------|------|
| ephemeral | 在场恰 1 次且离场 ≥2 | 一次性路人不进长期名单 |
| inactive 淡出 | `inactive ≥ IMPORTANT_INACTIVE_FADE_TURNS`（**20**）且不在场 | 早期 NPC 不永久占槽 |
| persona 例外 | 实体已锁定 persona | 淡出豁免（出过戏的角色） |
| 实体表 | 始终保留 | 淡出只影响投影名单，facts 不删 |

### 唯一写入者（flag 开时）

`save_state` 前最后写 `important_npcs` 的是 fact-log 合并投影。跳过 tracker / continuity；actor_registry / bridge / maintenance 可先摸，最终被 project 盖掉。opening 同规则。

### 开关

| 开关 | 含义 | 默认 |
|------|------|------|
| `THREADLOOM_FACTLOG_NARRATOR` | 读侧权威块 | **开** |
| `THREADLOOM_FACTLOG_WRITE_IMPORTANT` | 写侧合并写回 important + 停 tracker | **关** |
| `THREADLOOM_FACTLOG_WRITE_ONSTAGE` | 写回 onstage | 未做 |

```bash
export THREADLOOM_FACTLOG_WRITE_IMPORTANT=1
# 重启 backend 后生效；关掉则 export ...=0 或 unset 后重启
```

### 目标时序（flag 开）

```text
keeper + actor_registry 等仍跑
    → 跳过 tracker / continuity
    → commit_turn(state) → project → merge → state['important_npcs']
    → save_state
```

flag 关：tracker 照跑，`save_state` 后 shadow-only。

---

## 基线结论（2026-07-12，九幽大陆真实 session）

数据：`runtime-data/default-user/characters/九幽大陆/sessions/*`（含 shadow + 现网 `facts.jsonl` 重投影）。`sess-001` 无 facts，忽略。

**inactive 淡出后** live → proj：

| Session | live | proj | 备注 |
|---------|------|------|------|
| e23032 | 22 | **8** | 原 proj 26；路人膨胀压住。P1：live 多人共用触手事件，proj 分叉更好 |
| b93051 | 4 | **2** | 沈昭+桥上探头男人；live 把沈昭/灰衣青年修士拆成两人 |
| c88796 | 6 | **3** | 柳絮/女修/店小二；城门路人被筛掉（策略差，非纯 bug） |
| c15550 | 1 | **2** | 周掌柜+掌柜 **欠并** |
| 47be85 | 1 | 1 | 短样本，已对齐 |

**门槛**：名单膨胀 ✅改善；专名系统性丢失 无明显事故；事件多样性多 ≥ live；**手测未做 → 不默认开**。

已知剩余问题：

1. **欠并**：周掌柜 / 掌柜（c15550）  
2. **策略差**：旧 tracker「锁死长留」vs 投影「当前戏 + inactive 淡出」（c88796）  
3. seed-only 早期专名（无 present、无 persona）会随 inactive 淡出（可接受，或靠 persona 蒸馏保住）

---

## 手测（不必玩 b93051）

手测目标：开 flag 打几轮，看 UI 重要人物、`last_main_event` 是否分叉、regenerate 是否半截。**任意有 fact-log 的 session 或新档都行。**

### 推荐替代（按省事程度）

| 方式 | 说明 |
|------|------|
| **A. 新开短 session（最推荐）** | 九幽大陆新档，开 `WRITE_IMPORTANT=1`，刻意让 2 个 NPC 先后出场再换场；看名单与 last_event。不碰旧档感情线。 |
| **B. 副本旧档再测** | `rebuild_session_from_history` 或手动复制 session 目录 → 只在副本上开 flag，原 b93051/c88796 只读不动。 |
| **C. 续打 c88796 / c15550 / e23032** | 若还想接着某条故事：c88796 看「当前戏」名单；c15550 短、能暴露欠并；e23032 长、clobber 收益明显。 |
| **D. 不玩，只离线对照** | 已做：重投影 + 与 live diff。可再跑 `scripts/factlog_probe.py`。**不能替代** regenerate/UI 手测，但可继续收投影规则。 |

### 手测清单（任选 A/B/C）

1. `export THREADLOOM_FACTLOG_WRITE_IMPORTANT=1`，重启 backend  
2. 打 3–5 轮（至少两个在场 NPC 换场）  
3. 查 `memory/state.json` → `important_npcs[*].last_main_event` 是否按人不同  
4. 查 `diagnostics/factlog_shadow.jsonl` 最新行 `wrote_important: true`  
5. regenerate 一轮，确认 fact-log 与名单不半截  
6. 测完 `unset` / 设回 `0` 并重启（避免日常误开）

---

## Todo checklist

### 第 0 步 · 基线与硬门禁

- [x] 汇总真实 session 影子 / 现网重投影  
- [x] regenerate / delete-latest 接 `truncate_after` + fact 文件 snapshot/restore  
- [x] inactive 淡出压路人膨胀  

### 第 1 步 · `WRITE_IMPORTANT`（默认关）

- [x] flag 开：save 前 commit + merge 写回；跳过 tracker/continuity  
- [x] 失败保留旧名单；单测（分叉 / ephemeral / merge 厚字段 / flag 关）  
- [ ] **手测**（新档或副本即可，不绑 b93051）  
- [ ] 欠并小修（掌柜/周掌柜类）— 可选，挡默认开质量  
- [ ] 默认打开（门槛见下）  

### 第 2–4 步

- [ ] `WRITE_ONSTAGE`  
- [ ] 读侧去双份（弱化旧知情/注册表重复段）  
- [ ] 删 tracker / continuity 写路径；更新 BACKEND / MEMORY-V2 终态  

### 刻意后置

- 语义检索（roadmap P1）、NPC 目标、persona 重大演化、prose-commit  

---

## 验收

### 代码可合（已满足）

1. flag 开时 per-entity `last_main_event` 可分叉  
2. merge 保留厚字段  
3. flag 关 = 旧行为；写失败不炸回合  
4. regenerate 截断 fact-log  

### 默认开门槛（未满足）

1. 手测通过（新档或副本）  
2. only_live 无系统性专名丢失  
3. only_proj 路人噪声可控（淡出后 e23032 已改善）  
4. `proj_distinct_events` 稳定不劣于 live  

---

## 实现触点

| 位置 | 角色 |
|------|------|
| `backend/fact_log.py` | commit / project / ephemeral / inactive 淡出 / merge |
| `backend/handler_message.py` | WRITE_IMPORTANT 主链、tracker 跳过、shadow |
| `backend/regenerate_turn.py` | truncate + fact restore |
| `tests/test_fact_log.py` / `test_factlog_write_important.py` | 投影与写回 |
| `scripts/factlog_probe.py` | 真数据探针 |

---

## 一句话

**写回代码已就绪、默认关**；投影侧已加 inactive 淡出。下一步优先：**新档或副本手测**（不必续玩 b93051），可选再修欠并，过门槛再默认开。
