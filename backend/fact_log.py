#!/usr/bin/env python3
"""V2 memory core — one append-only fact log + a pure projection.

This replaces the multi-stage mutable-state reconciliation with three pure
operations over a single log, so stages can no longer pollute each other:

    FactLog.commit_turn(state, turn)   the only per-turn write (fed, strangler-
                                       style, by the existing post-turn state)
    FactLog.seed_from_state(state, t)  one-time, for legacy sessions: their
                                       current state.json becomes seed facts
    FactLog.project()                  pure fold -> onstage / important / last_event

`last_event` is a QUERY over facts, not a stored field, so the P1 clobber cannot
be expressed. Entities are resolved exactly once, at commit, by one deterministic
resolver that biases to *under*-merge (over-merge is hard to undo in an append-only
log) and leaves uncertain cases to the auditor.

Storage: `facts.jsonl` (append-only) + `entities.json`. No SQLite, no derived
cache (projection is a ~ms fold, recomputed on demand).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    from .name_sanitizer import is_protagonist_name, sanitize_runtime_name
except ImportError:  # imported as top-level module (tests add backend/ to path)
    from name_sanitizer import is_protagonist_name, sanitize_runtime_name

PREDICATES = ('present', 'holds', 'knows', 'relation', 'observation')

# Conservative: strip only grammatical particles. NOT 子/儿 or synonyms — those
# are auditor territory (see module docstring on under- vs over-merge).
_PARTICLE = re.compile(r'[的地得]')


def _norm_key(name: str) -> str:
    return _PARTICLE.sub('', (name or '').strip())


@dataclass
class Entity:
    id: str
    canonical: str
    kind: str = 'person'           # person | object | place | protagonist
    aliases: list = field(default_factory=list)   # variant names, excludes canonical


class Resolver:
    """Maps a surface name to a stable entity id; creates entities on first sight."""

    def __init__(self, entities: dict | None = None):
        self.entities: dict[str, Entity] = {}
        self._by_name: dict[str, str] = {}
        self._by_norm: dict[str, str] = {}
        self._seq = 0
        for raw in (entities or {}).values():
            self._register(raw if isinstance(raw, Entity) else Entity(**raw))

    def _register(self, ent: Entity) -> None:
        self.entities[ent.id] = ent
        m = re.fullmatch(r'e(\d+)', ent.id)
        if m:
            self._seq = max(self._seq, int(m.group(1)))
        for nm in [ent.canonical, *ent.aliases]:
            if not nm:
                continue
            self._by_name[nm] = ent.id
            nk = _norm_key(nm)
            if nk:
                self._by_norm.setdefault(nk, ent.id)

    def resolve(self, name: str, *, kind: str = 'person') -> str | None:
        name = sanitize_runtime_name(name) or str(name or '').strip()
        if not name:
            return None
        if is_protagonist_name(name):
            if 'protagonist' not in self.entities:
                self._register(Entity(id='protagonist', canonical=name, kind='protagonist'))
            return 'protagonist'
        if name in self._by_name:
            return self._by_name[name]
        nk = _norm_key(name)
        eid = self._by_norm.get(nk) if nk else None
        if eid is None:
            self._seq += 1
            eid = f'e{self._seq:03d}'
            self._register(Entity(id=eid, canonical=name, kind=kind, aliases=[]))
        else:                                   # particle-variant of a known name
            ent = self.entities[eid]
            if name != ent.canonical and name not in ent.aliases:
                ent.aliases.append(name)
            self._by_name[name] = ent.id
        return eid


def _fact(fid, turn, predicate, *, subject=None, obj=None, value=None,
          text=None, beat=False, entities=None, span=None, supersedes=None) -> dict:
    return {
        'id': fid, 'turn': turn, 'predicate': predicate,
        'subject': subject, 'object': obj, 'value': value, 'text': text,
        'beat': bool(beat), 'entities': entities or [],
        'span': span, 'supersedes': supersedes,
    }


class FactLog:
    def __init__(self, facts: list | None = None, entities: dict | None = None):
        self.facts: list[dict] = list(facts or [])
        self.resolver = Resolver(entities)
        self._seq = max((f.get('id', 0) for f in self.facts), default=0)

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    # -- writes -------------------------------------------------------------
    def commit_turn(self, state: dict, turn: int) -> list[dict]:
        """Derive this turn's facts from its primitives (who's present + the beat)."""
        loc = str(state.get('location', '') or '').strip()
        main_event = str(state.get('main_event', '') or '').strip()
        onstage = [n for n in (state.get('onstage_npcs') or []) if isinstance(n, str) and n.strip()]
        new: list[dict] = []
        ent_ids: list[str] = []
        for name in onstage:
            eid = self.resolver.resolve(name)
            if eid and self.resolver.entities[eid].kind != 'protagonist':
                ent_ids.append(eid)
                new.append(_fact(self._next(), turn, 'present', subject=eid, value=loc))
        if main_event:
            new.append(_fact(self._next(), turn, 'observation', beat=True, text=main_event,
                             entities=ent_ids,
                             span={'turn_id': f'turn-{turn:04d}', 'excerpt': main_event[:120]}))
        self.facts.extend(new)
        return new

    def seed_from_state(self, state: dict, as_of_turn: int) -> list[dict]:
        """One-time legacy migration: turn a session's current important_npcs into
        seed facts so old NPCs exist in the log without an LLM backfill."""
        new: list[dict] = []
        for npc in state.get('important_npcs', []) or []:
            if not isinstance(npc, dict):
                continue
            label = npc.get('primary_label', '')
            eid = self.resolver.resolve(label)
            if not eid or self.resolver.entities[eid].kind == 'protagonist':
                continue
            for alias in npc.get('aliases', []) or []:
                self.resolver.resolve(alias)            # attach aliases to the same id
            inactive = int(npc.get('inactive_turns', 0) or 0)
            seen_turn = max(1, as_of_turn - inactive)
            if npc.get('present_now'):
                new.append(_fact(self._next(), as_of_turn, 'present', subject=eid,
                                 value=str(npc.get('last_location', '') or '')))
            event = str(npc.get('last_main_event', '') or '').strip()
            if event:
                new.append(_fact(self._next(), seen_turn, 'observation', beat=True,
                                 text=event, entities=[eid], span={'source': 'seed'}))
        self.facts.extend(new)
        return new

    def truncate_after(self, turn: int) -> None:
        """Rollback / regenerate = drop facts past `turn`; project() re-folds."""
        self.facts = [f for f in self.facts if f.get('turn', 0) <= turn]

    # -- read ---------------------------------------------------------------
    def project(self) -> dict:
        return project(self.facts, self.resolver.entities)

    # -- persistence --------------------------------------------------------
    def save(self, memory_dir) -> None:
        memory_dir = Path(memory_dir)
        memory_dir.mkdir(parents=True, exist_ok=True)
        with open(memory_dir / 'facts.jsonl', 'w', encoding='utf-8') as fh:
            for f in self.facts:
                fh.write(json.dumps(f, ensure_ascii=False) + '\n')
        ents = {eid: asdict(e) for eid, e in self.resolver.entities.items()}
        with open(memory_dir / 'entities.json', 'w', encoding='utf-8') as fh:
            json.dump(ents, fh, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, memory_dir) -> 'FactLog':
        memory_dir = Path(memory_dir)
        facts: list[dict] = []
        fp = memory_dir / 'facts.jsonl'
        if fp.exists():
            facts = [json.loads(ln) for ln in open(fp, encoding='utf-8') if ln.strip()]
        ents = {}
        ep = memory_dir / 'entities.json'
        if ep.exists():
            ents = json.load(open(ep, encoding='utf-8'))
        return cls(facts=facts, entities=ents)


def project(facts: list[dict], entities: dict) -> dict:
    """Pure fold. `important_npcs` and per-entity `last_event` are derived, never
    stored — so nothing downstream can clobber them."""
    if not facts:
        return {'onstage_npcs': [], 'important_npcs': [], 'entity_last_event': {}}
    latest = max(f['turn'] for f in facts)
    present_turns: dict[str, set] = {}    # turns an entity was on-stage
    seen_turns: dict[str, set] = {}       # turns an entity was present OR mentioned
    last_loc: dict[str, tuple] = {}
    last_event: dict[str, tuple] = {}
    for f in facts:
        t = f['turn']
        if f['predicate'] == 'present':
            s = f['subject']
            present_turns.setdefault(s, set()).add(t)
            seen_turns.setdefault(s, set()).add(t)
            if s not in last_loc or t >= last_loc[s][0]:
                last_loc[s] = (t, f.get('value') or '')
        elif f['predicate'] == 'observation' and f.get('beat'):
            for eid in f.get('entities', []):
                seen_turns.setdefault(eid, set()).add(t)
                cur = last_event.get(eid)
                if cur is None or t > cur[0]:
                    last_event[eid] = (t, f.get('text') or '')

    def canon(eid):
        e = entities.get(eid)
        if e is None:
            return eid
        return e.canonical if isinstance(e, Entity) else e.get('canonical', eid)

    # Importance candidates = anyone seen (present or mentioned), ranked by how
    # many turns they were actually on-stage, then by recency.
    ranked = sorted(seen_turns,
                    key=lambda e: (len(present_turns.get(e, ())), max(seen_turns[e])),
                    reverse=True)
    important = []
    for eid in ranked:
        ev = last_event.get(eid)
        present = present_turns.get(eid, set())
        important.append({
            'primary_label': canon(eid),
            'present_now': latest in present,
            'last_main_event': ev[1] if ev else '',
            'last_location': last_loc.get(eid, (0, ''))[1],
            'inactive_turns': latest - max(seen_turns[eid]),
        })
    return {
        'onstage_npcs': [canon(e) for e in ranked if latest in present_turns.get(e, set())],
        'important_npcs': important,
        'entity_last_event': {canon(e): v[1] for e, v in last_event.items()},
    }
