# 信息隔离 / Keeper 写入审计与修复 — 2026-04-30

## 背景

针对用户提出的 "信息隔离 / 杜绝信息流污染 / keeper 重复写入与 fallback 覆盖高质量内容" 三类隐患，对 `backend/` 主链做了一次定点审计并完成修复。

## 修复清单

### 1. Keeper 写入路径

| 编号 | 修复点 | 文件 | 说明 |
|------|--------|------|------|
| P1.1 | tracked_objects / possession_state / object_visibility 改为 `object_id` 字典合并 | `backend/state_keeper.py` (`_merge_keeper_fill`) | 旧实现 `(base_items + payload)[-16:]` 拼接导致 `_merge_tracked_objects` 走 `used_prev` 后第二次出现的同 id 项进入"无匹配"分支，再被 `seen_object_ids` 去重时 baseline 副本胜出，**LLM 当轮的更新被丢弃**。修复后按 `object_id` 字典合并，payload 后写覆盖 baseline，下游归一化只看到一份且是新值。 |
| P1.2 | `knowledge_scope` 改用 `state_bridge._merge_knowledge_scope` 增量合并 | `backend/state_keeper.py` (`_merge_keeper_fill`) | 旧实现直接 `merged['knowledge_scope'] = scope` 替换 baseline。开局 / 上轮未被 `actor_registry` 沉淀到 `knowledge_records` 的 scope 会被本轮 keeper 输出整体覆盖。修复后调用既有但闲置的 `_merge_knowledge_scope`，按角色 / NPC 并集去重，分别截到 30 / 15 条。 |
| P1.3 | `carryover_signals` 推导后的 risks / clues 与 baseline 累加去重 | `backend/state_keeper.py` (`_merge_keeper_fill`) | 旧实现直接 `merged['immediate_risks'] = derived_risks` 替换。当 keeper 只输出 1–2 条信号时，baseline 中长期持续的风险 / 线索会被一次抹平。修复后将派生值与 merged 中既有值（来自 baseline 或 legacy 字段）累加去重，再截到 6 条。 |

### 2. 信息隔离 / 跨卡跨用户污染

| 编号 | 修复点 | 文件 | 说明 |
|------|--------|------|------|
| P2.4 | `card_hints.load_card_hints()` 缓存按 `(user_id, character_id)` 维度 | `backend/card_hints.py` | 旧实现 `@lru_cache(maxsize=1)` 是进程级单例，对 `_ACTIVE_CHARACTER_ID_OVERRIDE` ContextVar 无感知。并发请求里第一个调用方会"赢得"缓存，其他请求拿到错卡的 hints。修复后改字典缓存，invalidate 仍按整体清空。 |
| P2.5 | `name_sanitizer.protagonist_names()` 同上 | `backend/name_sanitizer.py` | 同 P2.4，按 `(user_id, character_id)` 维度。新增 `invalidate_protagonist_names_cache()` 并接入 `character_manager.set_active_character / delete_character_card / rebuild_character_lorebook` 与 `card_importer` 的失效点。 |
| P2.6 | `paths.resolve_layered_source` 在 character override 设置时不再回退 SHARED_ROOT | `backend/paths.py` | 旧实现仅在 `is_multi_user_request_context()` 才阻止回退，单用户运行时若 layered 文件缺失会读到仓库根的 `character/` 与 `memory/`，与"per-request override 隔离"承诺冲突。修复后新增 `is_character_override_active()`，与 multi-user 检查并联。 |
| P2.7 | `runtime_store.character_data_path / character_npc_profiles_dir` 同步加 override 检查 | `backend/runtime_store.py` | 同 P2.6 一并修。 |
| P2.7' | `player_profile.base_player_profile_path` 同步加 override 检查 | `backend/player_profile.py` | 顺带把同模式的 fallback 也改了，避免主角档案在 override 下读到 shared 副本。 |

### 3. Skeleton 抽取质量

| 编号 | 修复点 | 文件 | 说明 |
|------|--------|------|------|
| P3.8 | `extract_reply_skeleton` 删除 `first[:100]` 半句兜底 | `backend/state_fragment.py` | 当 narrator 首段无完整句末标点时，旧实现切前 100 字写入 `main_event`，会污染下游 fragment baseline。修复后只在 sentence 正则匹配成功时设置该字段。 |

### 4. 文档对齐

- `README.md` 的 keeper 章节去掉了"heuristic 作为最终兜底"的旧描述（`state_updater.update_state` 自当前主链解耦后只剩 `backend/tools/` 引用），并补充本次三个 keeper 写回保证。
- `README.md` 角色卡管理章节补充本次隔离改动（override 下不回退 shared、缓存按用户/角色维度）。

## 测试

| 类别 | 增量 | 文件 |
|------|------|------|
| 回归 | `test_keeper_fill_payload_overrides_baseline_object_by_id` | `tests/test_state_fragment.py` |
| 回归 | `test_keeper_fill_merges_knowledge_scope_with_baseline` | `tests/test_state_fragment.py` |
| 回归 | `test_keeper_fill_signals_extend_baseline_risks_and_clues` | `tests/test_state_fragment.py` |
| 回归 | `test_extract_reply_skeleton_skips_main_event_without_terminal_punctuation` | `tests/test_state_fragment.py` |
| 回归 | `test_resolve_layered_source_skips_shared_fallback_under_character_override` | `tests/test_paths_helpers.py` |

执行：

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests -p 'test_*.py'
```

结果：96 个测试，5 个新增；2 个 pre-existing 失败保持不变（`test_archive_initial_load_defaults_to_safe_mode` 的签名漂移、`test_user_profile_route_uses_multi_user_context_before_loading_profile` 的 server.py 路由级遗留），与本次修复无关。

## 没做的事 / 风险记录

- **`state_bridge._merge_knowledge_scope` 之前是死代码**：本次修复将其纳入实际调用路径，不再悬空。
- **`backend/state_updater.py`**：仍保留以服务 `backend/tools/replay_turn_trace.py` 与 `backend/tools/rebuild_session_from_history.py` 的离线重放/重建路径；运行时主链不再依赖。

## 后续小优化（同次提交）

| 项 | 文件 | 说明 |
|----|------|------|
| 合并 runtime turn 末尾两次 `save_state` | `backend/handler_message.py` | 中间 save 是 actor_registry 之前的 checkpoint，但 `update_actor_registry` 完全捕获自身 LLM 异常不会向外 raise，合并后 runtime 每 turn 少一次 atomic-rename + history 缓存失效；turn-trace 仍能复现中间态。 |
| `update_important_npcs` 增加 `allow_archive_write` 形参，tools 改只读调用 | `backend/important_npc_tracker.py` / `backend/tools/replay_turn_trace.py` / `backend/tools/rebuild_session_from_history.py` | replay/rebuild 工具在 archive cache 缺失/损坏时不再静默重建并落盘，避免污染真实 session 的 keeper 缓存。 |

测试：

- `test_update_important_npcs_threads_allow_archive_write_to_archive_loader` 验证形参传透。
- handler_message 合并通过现有 e2e 测试 (`test_full_regression`、`test_keeper_summary` 等) 间接覆盖。
