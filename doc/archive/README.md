# Threadloom Documentation Archive

这个目录集中保存 v1.0 之前已经完成、过时、重复或只适合作为历史证据的文档。

归档原则：

- `completed/`：已经落地的计划、todo、实施 prompt。
- `history/`：旧版本说明、过时审计、被当前核心文档覆盖的状态快照。
- `test-reports/`：一次性测试报告与历史验证记录。

历史 UI 原型模板（如 `stitch*.html`）也归档在 `history/`；当前产品入口是 `frontend/index.html`，这些模板不再参与运行。

当前活跃文档只保留在 `doc/` 根目录与 `doc/audit/` 中：

- `doc/API.md`
- `doc/ARCHITECTURE.md`
- `doc/BACKEND.md`
- `doc/CONTEXT-FLOW.md`
- `doc/OPERATIONS.md`
- `doc/REVIEW.md`
- `doc/RUNTIME.md`
- `doc/audit/SECURITY_AUDIT_2026-04-29.md`
- `doc/audit/ISOLATION_AND_KEEPER_FIX_2026-04-30.md`
- `doc/audit/MULTI_USER_HARDENING_2026-05-01.md`
- `doc/audit/MULTI_USER_UI_SHIPPED_2026-05-01.md`
- `doc/audit/RUNTIME_GENERICITY_AND_TRACE_2026-05-01.md`

需要查旧路线、旧版本目标或一次性修复记录时，从本目录读取；实现和运维应优先看活跃文档。
