# Runtime Genericity and Turn Trace Audit - 2026-05-01

本轮整理目标：继续把早期角色卡特化逻辑移出 runtime 主链，同时增强对象流转、人物别名归一和每轮注入审计的可观察性。

## 已收紧内容

- `card_importer` 不再根据旧角色卡世界观词汇推断 faction，只接受显式结构化字段。
- 主角档案 override 草稿不再按武侠/修仙关键词生成题材特化默认值，避免把某张卡的世界观写进通用导入路径。
- mid-context tracked objects 过滤改为按 `story_relevant / kind` 判断，不再硬编码过滤 `包 / 铜板`。
- state normalization 会用 actor registry 的正式名和 aliases 归一 `scene_entities / onstage_npcs / relevant_npcs`，减少同一 NPC 的短名/全名分裂。
- 对象交接类回合会触发 full keeper，降低 `tracked_objects / possession_state / object_visibility` 轻量路径漏写风险。
- 每轮 response/meta 增加 compact `turn_audit`，只记录 selector、lorebook、prompt block 和 keeper 摘要信息，不落大段世界书正文。
- summary chunk fallback 去掉题材特定关键词表，改为从 chunk 文本结构里提取基础 metadata。

## 验证覆盖

- `tests/test_card_importer.py` 覆盖 faction 只能来自结构化字段。
- `tests/test_keeper_archive_windows.py` 覆盖 mid-context object salience 过滤。
- `tests/test_state_fragment.py` 覆盖 actor alias canonicalization、对象重回 full keeper、turn audit compact 存储、summary chunk metadata 和环境实体过滤。

## LSP / 临时产物说明

- 本轮 LSP 修复只修正 JSON 语法和空 JSON 解析问题。
- 运行日志、审计日志和历史临时产物未删除；如需清理，应先列出候选文件并人工确认。
