#!/usr/bin/env python3
"""V2 feasibility probe — can a PURE FOLD over per-turn fact-deltas reproduce the
maintained state fields, and does per-entity `last_event` become distinct/correct
(structurally killing P1)?

Facts are derived ONLY from each turn's primitives — `main_event` (the beat) and
`onstage_npcs` (who's present) — taken from turn-trace post-state (turns 237-276,
the only per-turn structured data that exists). It deliberately IGNORES the
maintained `important_npcs` / `last_main_event` fields, so the fold is a genuine
re-derivation from "what happened + who was there", i.e. what commit() would emit
from prose. No LLM.

Usage: python3 scripts/factlog_probe.py [session_dir]
"""
import glob
import json
import re
import sys
from pathlib import Path

DEFAULT = "runtime-data/default-user/characters/九幽大陆/sessions/九幽大陆-20260520-e23032"
SESS = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)

# ---------------------------------------------------------------- entity layer
# One resolver, deterministic, used at commit time only. Strips structural
# particles + 子/儿 so infix variants (挎篮[子]妇人) collapse; never fuzzy-merges
# beyond a normalized-key exact hit (low-confidence stays separate -> P2 policy).
_NORM = re.compile(r'[的地得子儿\s]')


def norm_key(name: str) -> str:
    return _NORM.sub('', name.strip())


class Resolver:
    def __init__(self):
        self.entities: dict[str, dict] = {}   # id -> {canonical, aliases:set}
        self.by_name: dict[str, str] = {}
        self.by_norm: dict[str, str] = {}
        self.n = 0

    def resolve(self, name: str):
        name = (name or '').strip()
        if not name:
            return None
        if name in self.by_name:
            return self.by_name[name]
        nk = norm_key(name)
        eid = self.by_norm.get(nk) if nk else None
        if eid is None:
            self.n += 1
            eid = f'e{self.n:03d}'
            self.entities[eid] = {'canonical': name, 'aliases': {name}}
            if nk:
                self.by_norm[nk] = eid
        else:
            self.entities[eid]['aliases'].add(name)
        self.by_name[name] = eid
        return eid


# ---------------------------------------------------------------- commit (fold)
traces = sorted(glob.glob(str(SESS / 'turn-trace' / 'turn-*.json')))
R = Resolver()
facts: list[dict] = []
for tf in traces:
    d = json.load(open(tf, encoding='utf-8'))
    st = d.get('post_turn', {}).get('state', {})
    if not isinstance(st, dict):
        continue
    m = re.search(r'(\d+)', d.get('turn_id', '0'))
    turn = int(m.group(1)) if m else 0
    main_event = str(st.get('main_event', '') or '').strip()
    loc = str(st.get('location', '') or '').strip()
    onstage = [n for n in (st.get('onstage_npcs') or []) if isinstance(n, str) and n.strip()]
    ent_ids = []
    for n in onstage:
        eid = R.resolve(n)
        if eid:
            ent_ids.append(eid)
            facts.append({'turn': turn, 'predicate': 'present', 'subject': eid, 'value': loc})
    if main_event:
        facts.append({'turn': turn, 'predicate': 'observation', 'beat': 1,
                      'text': main_event, 'entities': ent_ids})


# ---------------------------------------------------------------- project (pure)
def project(facts):
    latest = max(f['turn'] for f in facts)
    onstage = {f['subject'] for f in facts if f['predicate'] == 'present' and f['turn'] == latest}
    last_event: dict[str, tuple] = {}
    present_turns: dict[str, set] = {}
    for f in facts:
        if f['predicate'] == 'present':
            present_turns.setdefault(f['subject'], set()).add(f['turn'])
        elif f['predicate'] == 'observation' and f.get('beat'):
            for eid in f.get('entities', []):
                cur = last_event.get(eid)
                if cur is None or f['turn'] > cur[0]:
                    last_event[eid] = (f['turn'], f['text'])
    importance = sorted(present_turns,
                        key=lambda e: (len(present_turns[e]), max(present_turns[e])),
                        reverse=True)
    return latest, onstage, last_event, importance, present_turns


latest, onstage, last_event, importance, present_turns = project(facts)
canon = lambda eid: R.entities[eid]['canonical']
state = json.load(open(SESS / 'memory' / 'state.json', encoding='utf-8'))

earliest = min(f['turn'] for f in facts)
print(f"=== window: {len(traces)} turn-traces, turns {earliest}-{latest}, {len(facts)} facts ===")
print(f"entity resolution: {len(R.by_name)} distinct names -> {len(R.entities)} entities")
merges = {e: sorted(v['aliases']) for e, v in R.entities.items() if len(v['aliases']) > 1}
if merges:
    print("  collapsed near-duplicate names (P2 at the source):")
    for e, al in merges.items():
        print(f"    {e} <- {al}")
else:
    print("  (no near-duplicate names appeared in this window)")

print("\n=== reproduction: onstage @ latest turn ===")
proj_on = sorted(canon(e) for e in onstage)
cur_on = sorted(state.get('onstage_npcs', []) or [])
print(f"  projection: {proj_on}")
print(f"  state.json: {cur_on}")
print(f"  match: {set(proj_on) == set(cur_on)}")

print("\n=== HEADLINE: per-entity last_event distinctness (P1) ===")
cur_imp = state.get('important_npcs', []) or []
cur_distinct = {str(x.get('last_main_event', '')) for x in cur_imp}
proj_distinct = {v[1] for v in last_event.values()}
print(f"  current state.json: {len(cur_imp)} important NPCs share {len(cur_distinct)} distinct last_main_event value(s)")
print(f"  V2 projection:      {len(last_event)} entities -> {len(proj_distinct)} distinct last_event value(s)")
print("  per-entity (projection, by recency):")
for e in importance:
    if e in last_event:
        t, txt = last_event[e]
        print(f"    {canon(e):<14} last onstage t{t}: {txt[:46]}")

print("\n=== important_npcs overlap (window-limited) ===")
proj_top = [canon(e) for e in importance[:12]]
cur_labels = [x.get('primary_label', '') for x in cur_imp]
seen = {n for e in R.entities for n in R.entities[e]['aliases']}
overlap = [l for l in cur_labels if l in seen]
outside = [l for l in cur_labels if l not in seen]
print(f"  projection top-{len(proj_top)}: {proj_top}")
print(f"  of {len(cur_labels)} current important NPCs, {len(overlap)} appear in the 40-turn window, "
      f"{len(outside)} were last active before it:")
print(f"    in-window: {overlap}")
print(f"    pre-window (need facts from turn 1): {outside}")

# ---- B demo: run the commit-time resolver over the ACTUAL fragmented names ----
# (the real duplicates live across actors/scene_entities/important, mostly pre-window)
print("\n=== entity resolution over ALL current names (how much of P2 dies at the source) ===")
names = []
for a in state.get('actors', {}).values():
    if isinstance(a, dict) and a.get('kind') != 'protagonist':
        names.append(a.get('name', ''))
        names += a.get('aliases', []) or []
for x in state.get('important_npcs', []) or []:
    names.append(x.get('primary_label', ''))
    names += x.get('aliases', []) or []
for e in state.get('scene_entities', []) or []:
    names.append(e.get('primary_label', ''))
    names += e.get('aliases', []) or []
names = [n for n in (str(s).strip() for s in names) if n]

R2 = Resolver()
for n in names:
    R2.resolve(n)
collapsed = {e: sorted(v['aliases']) for e, v in R2.entities.items() if len(v['aliases']) > 1}
print(f"  {len(set(names))} distinct names -> {len(R2.entities)} entities "
      f"({len(set(names)) - len(R2.entities)} fragments collapsed by particle-normalization alone)")
for e, al in collapsed.items():
    print(f"    {al}")
print("  (synonym pairs like 灰衣/灰布衫, 男人/汉子 are intentionally NOT auto-merged here -> small synonym table or auditor)")

