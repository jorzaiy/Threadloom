# Threadloom

Threadloom 是一个面向长期角色扮演与世界模拟的 runtime-first Web 应用。

它的核心思路不是把聊天记录当成唯一真相源，而是把这些层作为主事实面：

- `canon`
- `state`
- `persona`
- `threads`
- `recent window`
- `keeper archive`

前端负责消息收发、会话切换和状态展示；后端负责上下文装配、裁定、叙事生成与事实写回。

说明：
- `summary` 当前仍会保留为 session-local 写回 / 调试产物
- `summary` 当前不再作为 narrator 主输入

## 当前定位

当前目标是先把“单用户、本地可用、角色卡可替换”的 RP runtime 做完整，而不是立刻做成多租户平台。

当前边界：
- 单用户当前可用
- 角色卡当前可替换，但产品形态仍偏“当前激活卡”
- 单站点是当前产品层简化：普通用户只维护一个站点，然后给 `Narrator / State Keeper` 选模型
- 多用户相关底层代码当前保留，但产品面默认关闭，不作为当前正式能力暴露

后续方向：
- 多用户：补显式用户身份与用户切换
- 多角色卡：继续打磨导入后的 runtime 清洗与管理体验
- 多站点：若后续确实需要，再扩展为高级配置，而不是先把普通设置页做复杂

## 当前能力

- Web UI 聊天与侧栏状态展示
- 多 session 切换、新游戏、删除会话、partial regenerate
- narrator / analyzer / keeper 分模
- session-local `state / summary / persona / threads / important_npcs`
- skeleton keeper + fill-mode keeper 的双层状态链
- session 级串行锁与 partial 污染隔离
- 动态角色卡名称、副标题与侧栏封面图
- **泛化架构**：所有卡特定逻辑已从代码移到 `character-data.json["hints"]`，支持任意角色卡
- API Key 支持环境变量引用（`$VAR` 或 `env:VAR`）
- API 韧性：模型调用自动重试 429/503 错误（指数退避，最多 3 次，尊重 `Retry-After`）
- 安全加固：后端默认仅监听 `127.0.0.1`，API 响应带基础安全头，请求体有大小上限，provider URL 会阻止常见 SSRF 目标
- 原子文件写入：所有 state/archive 写入防崩溃/断电数据损坏
- 结构化知情边界：`knowledge_scope` 独立追踪主角和各 NPC 已知信息，替代纯文本软约束
- 线程生命周期管理：按类型分级保留、`cooling_down` 过渡态、`resolved_events` 归档
- turn trace 支持通过 `trace.enabled` 和 `trace.keep_last_turns` 控制是否落盘及保留数量
- 角色卡导入已开始切到 `v0.3` 产物结构：
  - `character-data.json`
  - `lorebook.json`
  - `openings.json`
  - `system-npcs.json`
  - `import-manifest.json`
  - `assets/`

## 当前 narrator 主链

当前 narrator 主输入不是单纯“两层上下文”，而是一个 runtime-first 分层装配：

强约束层：
- `runtime-rules`
- `preset`
- `character_core`
- `player_profile`
- `canon`
- 当前硬锚点（`time / location`）
- 知情边界（`knowledge_scope` + 固定规则）
- 最近 `12` 对 `user/assistant` turn
- 结构化状态锚点（来自 `state_fragment`，不含 `immediate_goal`）

连续性层：
- `npc_roster`
- `active_threads`
- `tracked_objects / possession_state / object_visibility`
- `keeper archive`
- 条件注入的 `npc_profiles`
- `persona`

候选知识层：
- 条件注入的系统级 NPC
- 条件注入的世界书 NPC 候选
- 条件注入的世界书正文
- 条件注入的长程阶段摘要

当前明确不再作为 narrator 主输入骨架的内容：

- `summary` 不是默认常驻主输入
- 独立 `mid digest` 已降级
- 旧 `memory agent` recall 不再主导 narrator
- 世界书注入受 selector 和预算约束，不再默认整块灌入

当前世界书预算已细化到条目类型：

- foundation 底板条目单独限额
- situational 场景条目单独限额
- `rule / world / faction / history / entry` 可分别控制注入数量
- `archive_only` 条目不会进入 narrator

## 角色卡管理

当前 Web UI 已支持当前用户范围内的角色卡管理：

- 设置面板内可切换当前用户的角色卡
- 设置面板内可直接导入新的角色卡文件（`.png` / `.json`）
- 角色卡枚举范围只限于当前用户目录下的 `runtime-data/<user>/characters/`
- 当前默认且唯一用户会显示为 `default_user`
- 当前暂不提供用户切换或用户管理 UI

## 当前 keeper 结构

当前主链已经是：

1. narrator 生成正文
2. `state_keeper.model` 作为 skeleton keeper 提取最小骨架：
   - `time`
   - `location`
   - `main_event`
   - `onstage_npcs`
   - `immediate_goal`
3. `state_keeper.model` 作为 fill-mode keeper，在骨架上补：
   - `immediate_risks`
   - `carryover_clues`
   - `tracked_objects`
   - `possession_state`
   - `object_visibility`
4. heuristic 作为普通 runtime 路径下的最终兜底

说明：
- `main_event` 目前已比早期版本稳定得多，opening 首轮也能落下有效主事件。
- `immediate_goal` 虽然仍在骨架字段里，但当前稳定性明显低于 `time / location / main_event`，部分回合仍可能回到 `待确认`；它当前更主要影响 `threads / lore trigger / summary`，而不是直接强控 narrator 正文。
- opening-choice 首轮当前会优先走 `skeleton keeper + fill keeper`，而不是直接依赖 heuristic 反提。

当前 keeper 改进要点：
- skeleton keeper 和 fill keeper 的 LLM prompt 已全面重写，加入字段级质量约束和好坏示例
- skeleton keeper `max_output_tokens` 已从 120 调高到 280，避免中文 JSON 截断
- `local_model_client.py` 增加了截断 JSON 的括号补全 fallback 解析
- heuristic fallback 已从旧关键词匹配重构为基于评分的抽取架构：
  - 统一 `_score_sentence()` 按用途加权
  - `_extract_top_sentences()` 替换旧的 `_extract_key_sentence()`
  - `_summarize_event()` 产出「用户动作→叙事响应」格式
  - 中文自然断点智能截断
  - 阈值过滤（≥2.0）用于 risks/clues
  - 元文本过滤（角色卡字段、AI 自评注、HTML 注释）

## 目录结构

- `backend/`
- `frontend/`
- `config/`
- `prompts/`
- `examples/`
- `character/`
- `memory/`
- `runtime/`
- `doc/`

## 启动

1. 复制配置模板：

```bash
cp config/runtime.example.json config/runtime.json
cp .env.local.example .env.local
```

2. 按你的环境填写：

```bash
config/runtime.json
.env.local
```

`.env.local` 里填真实密钥，`config/*.json` 里只保留 `env:VAR` 引用。

说明：
- `config/runtime.json` 现在主要保留共享内容层与全局运行策略
- 用户自己的站点与模型配置会落到 `runtime-data/<user>/config/`
- 前端设置面板修改的是当前用户自己的站点和模型，不会再把这部分写回共享 `config/`
 - 用户级文件包括：
  - `runtime-data/<user>/config/site.json`
  - `runtime-data/<user>/config/model-runtime.json`
 - 当前前端设置页已经简化为：
   - 站点 URL / API Key / API 类型
   - 获取模型
   - Narrator 模型选择
   - State Keeper 模型选择
 - `temperature` 与 `max_output_tokens` 已回收到共享默认配置：
   - `config/runtime.json -> model_defaults`
 - 高级角色（如 `turn_analyzer / arbiter / state_keeper_candidate`）当前不在普通设置页里改，但可以通过 `runtime-data/<user>/config/model-runtime.json -> advanced_models` 手动覆盖
  - 当前前端会话管理入口：
    - 点击底部当前会话名，弹出最近会话下拉管理
    - 显示当前角色卡下最近更新的最多 5 个会话
    - 下拉中可直接切换、删除、开始新游戏

3. 准备你自己的内容层：

- `character/`
- `memory/`
- `runtime/persona-seeds/`
- `USER.md`
- `player-profile.json`
- `player-profile.md`

公开仓库同时附带一套最小模板内容：

- `examples/character/`
- `examples/memory/`
- `examples/player-profile.*`
- `examples/USER.md`

如果你暂时还没有准备真实内容，可以先用 `examples/` 跑通最小链路，再逐步替换为自己的本地文件。

当前主角档案建议：

- 用户级基础档案：`runtime-data/<user>/profile/player-profile.base.json`
- 角色卡特化覆盖：`runtime-data/<user>/characters/<character_id>/source/player-profile.override.json`
- 运行时会先加载基础档案，再叠加当前角色卡覆盖
- `USER.md` 现在不再参与 RP narrator 主链，只保留给通用协作备注
- narrator 运行时只消费一份收短后的玩家档案摘要，完整档案仍保留在 JSON 真相源中
- `player-profile.json` / `player-profile.md` 目前保留为兼容副本与可读导出
- narrator prompt 当前采用“强约束层 / 连续性层 / 候选知识层”的分层权重，避免世界书候选压过最近窗口与当前 state

## 角色卡导入

当前推荐把角色卡导入到当前用户/当前角色卡的 source 目录，而不是再手改仓库根下旧 `character/` 目录。

导入命令：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.png
```

或直接导入已提取的 Tavern raw card：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.raw-card.json
```

导入后当前角色卡 source 目录下会生成：

- `character-data.json`
- `lorebook.json`
- `openings.json`
- `system-npcs.json`
- `import-manifest.json`
- `imported/`
- `assets/`

当前设计原则：

- `character-data.json` 只保留角色核心
- `lorebook.json` 只保留 runtime 可消费的世界知识条目
- `openings.json` 单独保存开局菜单与 bootstrap
- `system-npcs.json` 单独保存系统级 NPC，当前分成：
  - `core`
  - `faction_named`
  - `roster`
- 当前 runtime 默认优先只消费 `core`
- 导入时会尽量剔除 SillyTavern 的前端模板、隐藏脚本、状态栏与关系模板条目
- `assets/` 用于角色卡封面与缩略图

4. 启动：

```bash
cd /root/Threadloom/backend
./start.sh
```

`./start.sh` 会自动加载仓库根目录下的 `.env.local`。

前台启动：

```bash
cd /root/Threadloom/backend
python3 server.py
```

默认监听本机回环地址：

```text
http://127.0.0.1:8765
```

如果需要让其他设备访问，不建议直接改成公网监听；应放在可信反向代理后，并补全认证、TLS 与访问控制。

## 文档

建设和设计文档已经移到 `doc/`：

- `doc/API.md`
- `doc/ARCHITECTURE.md`
- `doc/BACKEND.md`
- `doc/CONTEXT-FLOW.md`
- `doc/OPERATIONS.md`
- `doc/REVIEW.md`
- `doc/RUNTIME.md`

## 常用脚本

当前主用入口：

- 启动后端：`backend/start.sh`
- 停止后端：`backend/stop.sh`
- 导入角色卡：`backend/import_character_card.py`
- 导入 SillyTavern 聊天：`backend/import_sillytavern_chat.py`
- 单回合精确回放：`backend/tools/replay_turn_trace.py`
- 从历史重建副本 session：`backend/tools/rebuild_session_from_history.py`

历史迁移 / 实验脚本已清理；当前只保留仍用于调试的 `backend/tools/` 工具。

配置模板：

- `config/runtime.example.json`
- `config/providers.example.json`（仅历史兼容 / 参考）

说明：
- 仓库不包含真实的 `config/runtime.json`
- 仓库不包含真实的 `config/providers.json`
- 发布版本默认保留配置模板，实际端点和 API key 需要本地自行填写
- 仓库默认提交的是 `examples/` 模板内容，而不是你的真实角色卡、memory、session 或用户档案

---

## 📚 相关文档

### 核心文档
- **[doc/audit/KEEPER_SUMMARY_FIX.md](doc/audit/KEEPER_SUMMARY_FIX.md)** - Keeper Summary 修复详情
- **[doc/audit/PERFORMANCE_OPTIMIZATION.md](doc/audit/PERFORMANCE_OPTIMIZATION.md)** - 性能优化总结
- **[doc/audit/DOC_AUDIT_REPORT.md](doc/audit/DOC_AUDIT_REPORT.md)** - 文档一致性审查报告
- **[doc/audit/SECURITY_AUDIT_2026-04-29.md](doc/audit/SECURITY_AUDIT_2026-04-29.md)** - 安全审计与修复记录
