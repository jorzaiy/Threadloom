# Threadloom

**当前版本：v1.0**

Threadloom 是一个面向长期角色扮演与世界模拟的 runtime-first Web 应用。

它不是把聊天记录当成唯一真相源，而是把 `canon`、`state`、`persona`、`threads`、recent window 与 keeper archive 作为多层事实面：前端负责消息收发、会话切换和状态展示，后端负责上下文装配、裁定、叙事生成与事实写回。

当前 v1.0 的目标是把“本地可用、角色卡可替换、可选多用户”的 RP runtime 做成稳定主线，而不是扩展成通用 SaaS 平台。

## 主要能力

- 沉浸式 Web UI：聊天、设置抽屉、状态面板、会话切换和角色卡管理
- 多 session：切换、新游戏、删除、partial regenerate
- Runtime 主链：narrator / state keeper / arbiter / selector / actor registry
- 分层记忆：session-local state、summary、persona、threads、keeper archive
- 角色卡导入：生成 `character-data.json`、`lorebook.json`、`openings.json`、`system-npcs.json`、资产和导入清单
- 可选多用户：管理员启用、普通用户隔离、Bearer token、登录限速、用户禁用/归档删除
- 安全边界：默认仅监听 loopback，真实配置与用户数据不进入 git，公网部署需通过可信反向代理

## 快速启动

```bash
cp .env.local.example .env.local
cd backend
./start.sh
```

默认地址：

```text
http://127.0.0.1:8765
```

详细启动、配置、导入和部署说明见 [Operations](doc/OPERATIONS.md)。

## 文档

- [Architecture](doc/ARCHITECTURE.md)：产品边界、整体结构、角色卡/session 隔离、narrator 分层
- [Runtime Flow](doc/RUNTIME.md)：一轮消息的 runtime 流程、刷新策略、keeper/writeback 行为
- [Backend](doc/BACKEND.md)：后端模块、配置边界、多用户安全边界、开发/LSP 说明
- [API](doc/API.md)：HTTP API 与多用户认证约定
- [Operations](doc/OPERATIONS.md)：启动、角色卡导入、多用户操作、公网部署前检查、常用脚本
- [Context Flow](doc/CONTEXT-FLOW.md)：上下文装配与 prompt 流向
- [Review](doc/REVIEW.md)：当前审查记录与质量边界

## 仓库边界

仓库只保留代码、文档和示例模板。真实运行数据与个人配置应保留在本地：

- `runtime-data/`
- `character/`
- `memory/`
- `runtime/`
- `config/runtime.json`
- `config/providers.json`
- `.env.local`
- `USER.md`
- `player-profile.*`

这些路径默认被 `.gitignore` 排除。
