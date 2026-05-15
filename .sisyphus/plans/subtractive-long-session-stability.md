# Subtractive Long-Session Stability Plan

## Goal

Make long Threadloom sessions degrade less by reducing keeper responsibilities, preventing header-only event pollution, and tracking only still-active mundane object instances. This plan avoids role-card/session keywords and avoids adding broad new memory layers.

## Non-goals

- Do not add world-specific or character-specific keyword rules.
- Do not make keeper maintain more long-term narrative summaries.
- Do not expand default selector recall volume.
- Do not rewrite the whole runtime architecture in one pass.
- Do not mutate or commit `runtime-data/`.

## Principles

1. Reduce global state surface area where possible.
2. Prefer current-turn evidence over summarized history.
3. Treat header/date/location as metadata, never as an event.
4. Track mundane details only when they remain physically actionable.
5. Make missing extraction distinct from deliberate empty state where feasible.

## Implementation Scope

### 1. General header/event separation guard

Strengthen generic header-only detection in existing normalization paths:

- `backend/state_fragment.py`
- `backend/state_bridge.py`

The detection should remain generic:

- identify date/time/location-style first lines, including non-Gregorian calendar prose;
- strip markdown wrappers;
- require absence of concrete action before treating as header-only;
- fall back to the previous meaningful event or a later action sentence where already available.

No world-specific terms such as a particular calendar name, city, shop, or character may be used.

### 2. Preserve current-turn participants through keeper paths

Finish the current-turn participant preservation path generically:

- skeleton/current-turn `onstage_npcs` must survive both skeleton-only and full keeper paths;
- full keeper baseline must retain the private current-turn marker until final normalization;
- actor canonical surfaces should match without requiring actor registry creation first;
- final persisted state must not keep private `_current_turn_onstage_npcs`.

This keeps short-term encounter participants reliable without forcing actor registration.

### 3. Reduce keeper authority over core fields when output is incomplete

If full keeper output is truncated or partial:

- do not let the partial payload overwrite or degrade core scene fields;
- keep object/knowledge patches only when parseable and well-formed;
- preserve the deterministic fragment/baseline for time, location, event, goal, and participants.

This should be implemented as a small validation/merge guard around existing keeper fill, not a new keeper mode.

### 4. Active object instance lifecycle for actionable mundane details

Use existing object layers as the place for active mundane instances, but narrow their lifecycle:

- create/keep an object only when the prose or user action leaves it physically actionable after the turn:
  - carried/stored/worn/held/placed nearby;
  - partially consumed or intentionally saved;
  - transferred to another holder;
  - visible as a specific scene object that can be acted on.
- do not keep objects that are consumed immediately or only appear as background description.
- when an active object becomes consumed/lost/archived, retire it from active tracked objects.

The plan should prefer improving existing `tracked_objects`, `possession_state`, `object_visibility`, and graveyard handling rather than adding a new large memory subsystem.

### 5. Selector restraint for mundane detail recall

Adjust selector/context behavior to avoid broad recall for mundane items:

- do not default-inject large old event/summary context just because a common object term appears;
- prefer active tracked objects and recent window before summary chunks for concrete item references;
- keep trace/audit visibility for why a detail was injected.

Keep this change narrow. If precise active-object injection needs a larger design, leave it as a follow-up rather than overbuilding now.

Concrete QA for this scope:

- Add or update a selector/context-builder regression where the current user text mentions a common mundane object that appears in multiple old summaries, but no active tracked object exists. Expected result: broad summary/lore/event injection is not increased solely by that common object term.
- Add or update a selector/context-builder regression where an active tracked object exists with possession state and the current user text refers to it. Expected result: active object evidence is available to context/prompt without requiring a broad summary chunk recall.
- Verify through `python3 -m pytest tests/test_context_builder.py` and, if selector-specific tests are touched, the relevant selector test file.

### 6. Narrator instruction tightening without adding content

Tighten generic narrator constraints so concrete mundane details cannot be invented:

- item source, remaining quantity, current location, and who has seen it must come from recent text or injected evidence;
- without evidence, narrator should keep references vague rather than inventing specifics;
- this should be a rule adjustment, not a new memory block.

Concrete QA for this scope:

- Add or update a prompt-building regression that inspects narrator prompt text and asserts it contains the generic “do not invent concrete item source/quantity/location/visibility without evidence” constraint.
- Add or update a prompt/context regression proving the constraint is present without adding a new large prompt block or broad memory payload.
- Verify through `python3 -m pytest tests/test_context_builder.py` or the existing narrator-input prompt test file if one is more appropriate.

## Test Plan

Add focused regressions in existing tests where possible:

1. Header-only first line using a non-Gregorian-style date/time/location does not become `main_event`.
2. A current-turn participant extracted by skeleton survives full keeper baseline normalization and is removed only as a private marker at final output.
3. Partial/truncated keeper fill cannot overwrite core scene fields with weaker output.
4. A saved half-consumed carried mundane object remains active and can be distinguished from a later consumed similar object.
5. Fully consumed immediate-use mundane object does not remain active.
6. Common mundane object mentions do not by themselves trigger broad old summary/event injection.
7. Narrator prompt includes a generic no-invention constraint for item source, quantity, location, and visibility, without adding a large new memory block.

Run at minimum:

- `python3 -m pytest tests/test_state_fragment.py tests/test_context_builder.py`
- `PYTHONPATH=/root/Threadloom:/root/Threadloom/backend python3 -m pytest tests/test_http_regression_current.py tests/test_regenerate_turn.py`
- `lsp_diagnostics` on every changed Python/JS file.

## Risks

- Over-filtering may suppress legitimate event summaries if header detection is too broad.
- Tracking active mundane objects can become noisy if lifecycle criteria are too permissive.
- Selector restraint can reduce continuity if active object evidence is not injected when needed.

## Rollback/Containment

- Keep changes small and localized.
- Add tests before broadening behavior.
- Prefer guards that preserve previous stable state over deleting information.
- Do not modify historical session data as part of implementation.
