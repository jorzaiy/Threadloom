# Threadloom

Threadloom 是一个面向长期角色扮演与世界模拟的 runtime-first Web 应用。

它的核心思路不是把聊天记录当成唯一真相源，而是把这些层作为主事实面：

- `canon`
- `state`
- `summary`
- `persona`
- `threads`

前端负责消息收发、会话切换和状态展示；后端负责上下文装配、裁定、叙事生成与事实写回。

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
- turn trace 支持通过 `trace.enabled` 和 `trace.keep_last_turns` 控制是否落盘及保留数量

## 当前 keeper 结构

当前主链已经是：

1. narrator 生成正文
2. `Llama-3.3-70B` 作为 skeleton keeper 提取最小骨架：
   - `time`
   - `location`
   - `main_event`
   - `onstage_npcs`
   - `immediate_goal`
3. 本地 Gemma 4B 作为 fill-mode keeper，在骨架上补：
   - `scene_core`
   - `immediate_risks`
   - `carryover_clues`
4. heuristic 作为最终兜底

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
 - 当前前端会话管理入口：
   - 点击顶部当前会话名，弹出最近会话下拉管理
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

4. 启动：

```bash
cd /Threadloom/backend
./start.sh
```

`./start.sh` 会自动加载仓库根目录下的 `.env.local`。

前台启动：

```bash
cd /Threadloom/backend
python3 server.py
```

默认监听：

```text
http://127.0.0.1:8765
```

## 文档

建设和设计文档已经移到 `doc/`：

- `doc/API.md`
- `doc/ARCHITECTURE.md`
- `doc/BACKEND.md`
- `doc/CONTEXT-FLOW.md`
- `doc/OPERATIONS.md`
- `doc/REVIEW.md`
- `doc/RUNTIME.md`

配置模板：

- `config/runtime.example.json`
- `config/providers.example.json`（仅历史兼容 / 参考）

说明：
- 仓库不包含真实的 `config/runtime.json`
- 仓库不包含真实的 `config/providers.json`
- 发布版本默认保留配置模板，实际端点和 API key 需要本地自行填写
- 仓库默认提交的是 `examples/` 模板内容，而不是你的真实角色卡、memory、session 或用户档案
