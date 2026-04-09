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
cp config/providers.example.json config/providers.json
```

2. 按你的环境填写：

```bash
config/runtime.json
config/providers.json
```

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
- `config/providers.example.json`

说明：
- 仓库不包含真实的 `config/runtime.json`
- 仓库不包含真实的 `config/providers.json`
- 发布版本默认保留配置模板，实际端点和 API key 需要本地自行填写
- 仓库默认提交的是 `examples/` 模板内容，而不是你的真实角色卡、memory、session 或用户档案
