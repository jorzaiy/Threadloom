# State normalization and helper consolidation audit

Date: 2026-04-29

## Scope

This pass addressed the low-risk items from the runtime audit:

- Make keeper archive read-path cache writes explicit without changing default behavior.
- Consolidate duplicated slug and JSON read helpers while preserving existing output and error behavior.
- Centralize only pure entity/object/signal normalization predicates; keep keeper payload coercion and heuristic extraction local to their callers.

## Changes

### Keeper archive cache writes

`retrieve_keeper_records()` now accepts `allow_archive_write=True`.

- Default behavior is unchanged: derived keeper archives may still be pruned, rebuilt, and saved while reading context.
- Callers that need a read-only inspection path can pass `allow_archive_write=False` to suppress prune-save and rebuild-save side effects.
- Missing or corrupt archives loaded through `load_keeper_record_archive()` also honor `allow_archive_write`.

This keeps the documented derived-cache behavior while making the write boundary visible at the API boundary.

### Shared path helpers

`paths.py` now exposes:

- `slugify(text, fallback)` for character/session-adjacent directory slugs.
- `read_json_file(path)` for strict UTF-8 JSON reads when missing-file fallback is handled by the caller.

Existing wrappers in character management and import/config/context code still preserve their previous public behavior.

### Shared state normalization predicates

`state_bridge.py` remains the canonical runtime normalizer and now exposes pure helpers for:

- entity descriptor signatures
- entity label compatibility
- carryover signal normalization
- risk/clue derivation from carryover signals
- keeper object label cleanup

`state_keeper.py` delegates to these helpers where behavior was already equivalent. It still keeps keeper-specific payload coercion, holder normalization, semantic cleanup, and LLM-output tolerance local.

### State write boundary

`call_state_keeper()` returns a normalized state but does not save it directly. Runtime request handlers persist the final state after arbiter, thread, important-NPC, and actor-registry merges, preventing an intermediate keeper result from overwriting later same-turn enrichments.

## Explicit non-changes

- `normalize_state_dict()` merge flow was not rewritten.
- `state_updater.py` heuristic extraction was not collapsed into `state_bridge.py`; its count/collective handling and legacy fallback behavior remain local.
- Object lifecycle semantics are unchanged: retired objects still leave active object state and enter `graveyard_objects`.
- Opening initialization save behavior is unchanged because architecture docs allow opening state to be saved before final keeper consolidation.

## Verification focus

Regression coverage now locks:

- slug behavior for Chinese, ASCII, punctuation-only, and empty names
- shared JSON read behavior
- keeper archive read-only mode versus default write-on-read cache maintenance
- shared entity/signal/object helper contracts
