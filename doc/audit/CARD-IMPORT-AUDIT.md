# Card Import Audit & Fix — 2026-04-25

A code-level audit of `backend/card_importer.py` and its downstream consumers,
followed by P0/P1 fixes. See `tests/test_card_importer.py` and
`tests/test_card_importer_e2e.py` for verification.

## Scope

The importer ingests SillyTavern v2 / v3 character cards (PNG with `chara` /
`ccv3` tEXt or iTXt chunks, or raw JSON) and emits five JSON artefacts:

```
character-data.json     # core character data
lorebook.json           # normalized world-info entries
openings.json           # opening menu + bootstrap
system-npcs.json        # explicit system-level NPC roster
import-manifest.json    # provenance + import stats
```

## Findings

### P0 — Data loss

**P0-1 — `system_npcs.items` dropped the roster bucket**

`card_importer.py` writes:

```python
'items': deduped_core + deduped_faction
```

while the runtime consumes `items` exclusively (`state_bridge.infer_role_label`,
`context_builder.extract_system_npc_candidates`). Result: every NPC the
importer found via the `roster` heuristic was silently dropped at runtime.

**P0-2 — SillyTavern v2/v3 fields were not read at all**

Character core dropped: `mes_example`, `post_history_instructions`, `tags`,
`extensions`, `nickname`, `talkativeness`, `character_version`, `creator`,
`creator_notes_multilingual`, `creation_date`, `modification_date`,
`group_only_greetings`.

Lorebook entry dropped: `selective`, `selective_logic`, `position`,
`case_sensitive`, `match_whole_words`, `depth`, `probability`,
`useProbability`, `group`, `groupOverride`, `groupWeight`, `vectorized`,
`disable`, `extensions`. Lorebook top-level dropped: `description`,
`scan_depth`, `token_budget`, `recursive_scanning`, `extensions`.

**P0-3 — `personality` truncated to 240 chars**

Real-world cards routinely have 1k–3k character `personality` blocks. The hard
240-char limit cut these in half; `_truncate` did not respect sentence
boundaries.

### P1 — False negatives / robustness

**P1-5 — Faction inference inlined card-specific factions**

`'太子' / '镇北司' / '黄泉引' / '拜月教' / '七绝门'` were hardcoded mid-function;
any other card got `faction == ''`.

**P1-6 — `'小美'` and `'血蚀纪'` baked into a name blocklist**

These are character / setting names from one specific RP card. Any other card
that legitimately used those names had its NPCs dropped. The blocklist also
mixed in real template tokens (`'{{user.name or '`, `'[EVENT]meet'`) that
should be detected by pattern, not enumerated.

**P1-7 — Card primary NPC rejected English / longer names**

`len(name) <= 8` and `not ('·' in name or 2 <= len(name) <= 8)` excluded
`Aria Stark`, `Captain Olen`, etc. — i.e. for any English card, the primary
character never made it into `system-npcs.json`.

**P1-8 — Embedded NPC heuristics were CJK-only**

`_extract_embedded_npcs` recognises only Chinese descriptor prefixes
(`身份:`, `形象:`, `定位:`, …). Latin-script cards' NPCs in lore-block format
were silently skipped.

## Fixes

| ID  | Change |
|-----|--------|
| P0-1 | `system_npcs.items` now includes `core + faction_named + roster`. |
| P0-2 | `_extract_character_core` and `_convert_lorebook_entry` now preserve all known v2/v3 fields; `_extract_lorebook` preserves top-level metadata; `_extract_opening_options` handles `group_only_greetings`. |
| P0-3 | `personality` 240→1500, summary 1200→2400, system_summary 1200→4000, creator_notes 800→2000, all using `_truncate_at_boundary`. |
| P1-5 | `_infer_faction` extracted to module-scope, table-driven, default empty. |
| P1-6 | New `_looks_like_template_token` (Jinja `{{`, `{%`, `[FOO]meet`, snake_case ids, dotted refs) replaces the hardcoded name blocklist. |
| P1-7 | Length cap raised to 60; ASCII names with separators (`Aria Stark`) accepted; chars excluding whitespace counted for CJK names. |
| P1-8 | `_extract_embedded_npcs_latin` added: markdown headings, `**Bold**:` blocks, `Name\nRole: …` blocks. Skipped when content is CJK-dominant. |
| P2-9 | `_extract_lorebook` now keeps entries with empty content but valid keywords (link-trigger only). |
| Downstream | `context_builder.extract_system_npc_candidates` now falls back through `core → faction_named → roster`. `persona_updater._infer_candidate_identity` accepts any `system_npc*` source. |
| Bug A | `_classify_lorebook_entry` now treats `'重要人物条目X'` titles the same as `'重要人物表-N'` and `'总结条目-N'` — i.e. ACU runtime cache, classified `archive_only` and filtered out of the runtime lorebook.json. Caught when re-importing 维克托·奥古斯特.png: SillyTavern Cyborg framework writes its in-session NPC dump back to `character_book.entries`, polluting the imported lorebook with 12 stale entries. |
| Bug D | `_extract_template_relationship_npcs` now skips names equal to the card name or the lorebook name. Caught when re-importing 血蚀纪.png: the card name `血蚀纪` was being surfaced as an NPC because `[EVENT]meet`-style templates reference the card name in their wrapping JSON. |
| Bug E | Single-`first_mes` cards now import as `openings.mode: direct` with empty `options`, so runtime no longer appends the multi-opening “随机开局 / 报数字 / 开局名字” instructions. `opening.py` also ignores legacy one-option files as menu candidates. |
| Bug F | Opening text now applies basic SillyTavern placeholder replacement: `{{char}}` becomes the imported character name and `{{user}}` becomes `玩家`; runtime applies the same replacement as a fallback for older imported cards. Caught when re-importing 维克托·奥古斯特.png. |

## Deferred (P2)

The following were noted but **not** fixed in this pass:
- PNG chunk CRC validation in `_read_png_chunks`.
- Backup directory naming (only `{hash}.raw-card.json`, no version suffix).
- `extract_card_json` error message could include observed chunk keys.
- Lorebook classification still relies on a hardcoded Chinese token list in
  `_classify_lorebook_entry`. Tokens are kept as-is for backwards compatibility
  with the original RP card; not currently configurable per-card.

## Verification

```
$ python3 -m pytest tests/test_card_importer.py tests/test_card_importer_e2e.py
======================= 27 passed in 0.09s =======================
```

### Real-card sanity check (re-imported from tmp/*.png)

| Card                | raw lorebook | kept | system NPCs | NPC source |
|---------------------|--------------|------|-------------|------------|
| 九幽大陆            | 548          | 2    | 0           | (correct: pure world card, no character roster) |
| 维克托·奥古斯特     | 309          | 2    | 1           | card_core (just 教官 himself; the 12 `重要人物条目X` entries are ACU runtime cache, correctly filtered) |
| 血蚀纪              | 7            | 1    | 6           | relationship_template (贺景 / 闻钰 / 凌烨 / 沐霖 / 沐许 / 舒行 — card name `血蚀纪` correctly excluded) |

The single-unit suite covers each fix point individually; the E2E suite
imports a synthetic v3 card with all v2/v3 fields populated, asserts every
output JSON is field-complete, and verifies the importer is idempotent on
re-import.

2026-04-28 sanity check: re-imported `维克托·奥古斯特` from its backed-up PNG.
The generated `openings.json` is `mode: direct`, `opening_options_count: 0`,
and its `menu_intro` contains `维克托·奥古斯特` instead of raw `{{char}}`.
