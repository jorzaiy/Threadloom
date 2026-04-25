历史迁移、审计与实验脚本归档目录。

这些脚本不属于当前主链运行时，也不是日常运维默认入口。

当前归档内容：
- `audit_legacy_sessions.py`
- `migrate_storage_layout.py`
- `migrate_lorebook_metadata.py`
- `experiment_entity_candidate_judge.py`
- `replay_turn_trace.py`
- `rebuild_session_from_history.py`

使用原则：
- 只在需要处理历史数据、迁移旧目录、或复现实验结论时手动运行
- 运行前先确认脚本里的路径假设仍和当前仓库结构一致
