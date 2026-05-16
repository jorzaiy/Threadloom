# Threadloom

Threadloom 是一个面向长期角色扮演的 runtime-first Web 应用，支持本地自托管与可选多用户部署。

它以 `canon`、`state`、`persona`、`threads`、recent window 和 keeper archive 作为多层事实面，而非把聊天记录当成唯一真相源。前端负责消息收发、会话切换与状态展示；后端负责上下文装配、裁定、叙事生成与事实写回。

## 功能

- **沉浸式 Web UI**：聊天界面、设置抽屉、状态面板、会话切换、角色卡管理
- **多 session**：新游戏、切换、删除、单轮重新生成
- **Runtime 主链**：narrator / state keeper / arbiter / selector / actor registry
- **分层记忆**：session-local state、summary、persona、threads、keeper archive
- **角色卡导入**：从角色卡生成 `character-data.json`、`lorebook.json`、`openings.json`、`system-npcs.json` 及资产清单
- **可选多用户**：管理员启用、用户隔离、Bearer token 认证、登录限速、用户禁用与归档
- **安全边界**：默认仅监听 loopback；公网部署需通过可信反向代理

## 环境要求

- Python 3.11+
- 依赖已列于 `requirements.txt`，通过 `pip install -r requirements.txt` 安装

## 快速启动

```bash
cp .env.local.example .env.local
# 编辑 .env.local，填入 API key
cd backend
./start.sh
```

默认监听地址：

```
http://127.0.0.1:8765
```

详细启动、配置、角色卡导入与部署说明见 [Operations](doc/OPERATIONS.md)。

## 文档

| 文档 | 内容 |
|------|------|
| [Architecture](doc/ARCHITECTURE.md) | 产品边界、整体结构、角色卡与 session 隔离、narrator 分层 |
| [Runtime Flow](doc/RUNTIME.md) | 单轮消息的完整 runtime 流程、刷新策略、keeper/writeback 行为 |
| [Backend](doc/BACKEND.md) | 后端模块说明、配置边界、多用户安全边界、开发环境配置 |
| [API](doc/API.md) | HTTP API 端点与多用户认证约定 |
| [Operations](doc/OPERATIONS.md) | 启动、角色卡导入、多用户操作、公网部署检查清单 |
| [Context Flow](doc/CONTEXT-FLOW.md) | 上下文装配与 prompt 流向 |
| [Review](doc/REVIEW.md) | 当前审查记录与质量边界 |

## 数据与配置

以下路径存放运行时数据与本地配置，不纳入版本控制（已在 `.gitignore` 中排除）：

```
runtime-data/
character/
memory/
runtime/
config/runtime.json
config/providers.json
.env.local
```
