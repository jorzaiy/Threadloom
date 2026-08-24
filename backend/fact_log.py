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
    from .fact_retrieval import retrieve as retrieve_facts
    from .name_sanitizer import is_protagonist_name, sanitize_runtime_name
except ImportError:  # imported as top-level module (tests add backend/ to path)
    from fact_retrieval import retrieve as retrieve_facts
    from name_sanitizer import is_protagonist_name, sanitize_runtime_name

PREDICATES = ('present', 'holds', 'knows', 'relation', 'observation')

# Long-term important roster: drop NPCs not seen for this many turns (still kept
# in the entity table / facts — only the projected important list fades).
# Exception: locked persona means "emerged cast" and survives the fade.
IMPORTANT_INACTIVE_FADE_TURNS = 20

# Conservative: strip only grammatical particles. NOT 子/儿 or synonyms — those
# are auditor territory (see module docstring on under- vs over-merge).
_PARTICLE = re.compile(r'[的地得]')


def _norm_key(name: str) -> str:
    return _PARTICLE.sub('', (name or '').strip())


# Conservative Chinese role-category suffixes — used to fold a prefix short form
# like "灰衣青年" into "灰衣青年修士". Only these specific category tails merge.
_CATEGORY_SUFFIX = (
    '修士', '青年', '少年', '男人', '男子', '女人', '女子', '汉子', '大汉', '老者', '老头',
    '老汉', '妇人', '后生', '道人', '道士', '和尚', '尼姑', '姑娘', '小子', '书生', '女孩',
)


def _is_short_for(short: str, full: str) -> bool:
    """short == full minus one category suffix, with a >=3-char base so two-char
    names (张三 / 张三丰) never collapse."""
    if len(full) <= len(short) or not full.startswith(short) or len(short) < 3:
        return False
    return full[len(short):] in _CATEGORY_SUFFIX


def _simplify_compatible(a: str, b: str) -> bool:
    return _is_short_for(a, b) or _is_short_for(b, a)


# Descriptive hint chars (colour / build / position / garment / age …). A label
# containing any is treated as descriptive, not a proper name — keeps it conservative.
_DESCRIPTIVE_HINT = (
    '灰', '红', '青', '黑', '白', '黄', '蓝', '绿', '紫', '胖', '瘦', '高', '矮',
    '老', '桥', '门', '街', '巷', '带', '穿', '戴', '披', '长', '短',
)

# Service / occupation role words — descriptive, never a personal name.
_SERVICE_ROLE = (
    '老板', '老板娘', '掌柜', '掌柜的', '店主', '店家', '伙计', '小二', '账房', '管事',
    '摊主', '摊贩', '短工', '长工', '车夫', '船夫', '脚夫',
)


def _looks_like_proper_name(s: str) -> bool:
    """A short label that reads like a personal name, not a description: 2-4 chars,
    no role-category suffix, no service-role word, no descriptive hint char.
    沈昭 → yes; 短工 / 摊主 / 灰衣青年修士 → no."""
    s = (s or '').strip()
    if not (2 <= len(s) <= 4):
        return False
    if any(s.endswith(suf) for suf in _CATEGORY_SUFFIX):
        return False
    if any(s.endswith(role) for role in _SERVICE_ROLE):
        return False
    return not any(ch in s for ch in _DESCRIPTIVE_HINT)


_RELATION_ARROWS = ('→', '->', '⇒', '➜', '=>')


def _normalize_relation_label(label: str) -> str:
    """keeper sometimes writes a transition like 'A→B' into the label; keep only the
    final state B. Only explicit arrow marks are split — never plain Chinese chars,
    to avoid mangling a real label."""
    text = str(label or '').strip()
    for arrow in _RELATION_ARROWS:
        if arrow in text:
            text = text.split(arrow)[-1].strip()
    return text


@dataclass
class Entity:
    id: str
    canonical: str
    kind: str = 'person'           # person | object | place | protagonist
    aliases: list = field(default_factory=list)   # variant names, excludes canonical
    persona: str = ''              # 稳定性格/特质：确立一次、之后稳定，叫法变了也不丢
    identity: str = ''             # 稳定身份标签
    merged_into: str = ''          # 若本实体被并入别的实体，记幸存者 id


class Resolver:
    """Maps a surface name to a stable entity id. Creates entities on first sight,
    and MERGES when a later mention reveals two were the same person — via a shared
    alias, a particle variant, or a category-suffix short form. Biased to
    under-merge: only those high-precision signals merge; uncertain synonyms
    (灰衣 vs 灰布衫) stay separate for the auditor."""

    def __init__(self, entities: dict | None = None):
        self.entities: dict[str, Entity] = {}
        self._by_name: dict[str, str] = {}
        self._by_norm: dict[str, str] = {}
        self._canon: dict[str, str] = {}          # merged-away id -> survivor id
        self._seq = 0
        for raw in (entities or {}).values():
            ent = raw if isinstance(raw, Entity) else Entity(**raw)
            self.entities[ent.id] = ent
            m = re.fullmatch(r'e(\d+)', ent.id)
            if m:
                self._seq = max(self._seq, int(m.group(1)))
        for ent in self.entities.values():        # rebuild merge map, then index
            if ent.merged_into:
                self._canon[ent.id] = ent.merged_into
        for ent in self.entities.values():
            target = self.canon_eid(ent.id)
            for nm in [ent.canonical, *ent.aliases]:
                self._index(nm, target)

    def _index(self, nm: str, eid: str) -> None:
        if not nm:
            return
        self._by_name[nm] = eid
        nk = _norm_key(nm)
        if nk:
            self._by_norm.setdefault(nk, eid)

    def canon_eid(self, eid: str) -> str:
        seen: set = set()
        while eid in self._canon and eid not in seen:
            seen.add(eid)
            eid = self._canon[eid]
        return eid

    def _seq_of(self, eid: str) -> int:
        m = re.fullmatch(r'e(\d+)', eid)
        return int(m.group(1)) if m else 0

    def _merge(self, keep: str, drop: str) -> None:
        if keep == drop or drop not in self.entities:
            return
        k, d = self.entities[keep], self.entities[drop]
        for nm in [d.canonical, *d.aliases]:
            if nm and nm != k.canonical and nm not in k.aliases:
                k.aliases.append(nm)
        if not k.persona and d.persona:
            k.persona = d.persona
        if not k.identity and d.identity:
            k.identity = d.identity
        d.merged_into = keep
        self._canon[drop] = keep
        for mapping in (self._by_name, self._by_norm):
            for key, eid in list(mapping.items()):
                if eid == drop:
                    mapping[key] = keep

    def resolve(self, name: str, *, kind: str = 'person', aliases=None) -> str | None:
        name = sanitize_runtime_name(name) or str(name or '').strip()
        if not name:
            return None
        if is_protagonist_name(name):
            if 'protagonist' not in self.entities:
                self.entities['protagonist'] = Entity(id='protagonist', canonical=name, kind='protagonist')
            return 'protagonist'
        # name + caller-supplied aliases are all surface forms of ONE entity.
        surfaces = [name] + [sanitize_runtime_name(a) or str(a or '').strip() for a in (aliases or [])]
        surfaces = [s for s in surfaces if s and not is_protagonist_name(s)]
        # Collect every existing entity these surfaces point at (may reveal a split).
        hits: list[str] = []
        for s in surfaces:                                   # exact name/alias (trusted)
            if s in self._by_name:
                hits.append(self.canon_eid(self._by_name[s]))
        if not hits:                                         # particle variant
            for s in surfaces:
                nk = _norm_key(s)
                if nk in self._by_norm:
                    hits.append(self.canon_eid(self._by_norm[nk]))
        for s in surfaces:                                   # category-suffix short form
            for eid, ent in self.entities.items():
                if ent.merged_into or ent.kind == 'protagonist':
                    continue
                if any(_simplify_compatible(s, t) for t in [ent.canonical, *ent.aliases]):
                    hits.append(self.canon_eid(eid))
                    break
        hits = [h for h in dict.fromkeys(hits) if h in self.entities]
        if hits:
            keep = min(hits, key=self._seq_of)               # oldest = most stable canonical
            for drop in hits:
                self._merge(keep, drop)
        else:
            self._seq += 1
            keep = f'e{self._seq:03d}'
            self.entities[keep] = Entity(id=keep, canonical=name, kind=kind, aliases=[])
        ent = self.entities[keep]
        for s in surfaces:                                   # attach all surfaces to survivor
            if s != ent.canonical and s not in ent.aliases:
                ent.aliases.append(s)
            self._index(s, keep)
        # Promote canonical to a proper name once one appears (沈昭 over 灰衣青年修士).
        # One-way: if canonical already reads like a proper name, keep it (no thrashing).
        if not _looks_like_proper_name(ent.canonical):
            proper = next((s for s in surfaces if _looks_like_proper_name(s)), '')
            if proper:
                if ent.canonical and ent.canonical not in ent.aliases:
                    ent.aliases.append(ent.canonical)
                ent.canonical = proper
                if proper in ent.aliases:
                    ent.aliases.remove(proper)
        return keep

    def set_persona(self, eid: str, persona: str, *, identity: str = '') -> None:
        """确立一次、之后稳定——锁住 NPC 性格，不被后续轮次的漂移覆盖。"""
        ent = self.entities.get(self.canon_eid(eid))
        if ent is None:
            return
        persona = str(persona or '').strip()
        if persona and not ent.persona:
            ent.persona = persona
        identity = str(identity or '').strip()
        if identity and not ent.identity:
            ent.identity = identity


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
    def _latest_relation_label(self, eid: str) -> str:
        cid = self.resolver.canon_eid(eid)
        label = ''
        for f in self.facts:
            if f.get('predicate') == 'relation' and self.resolver.canon_eid(f.get('subject')) == cid:
                label = f.get('value') or label
        return label

    def _known_values(self) -> set[tuple[str, str]]:
        values: set[tuple[str, str]] = set()
        for f in self.facts:
            if f.get('predicate') != 'knows':
                continue
            subject = f.get('subject')
            value = str(f.get('value') or '').strip()
            if subject and value:
                values.add((self.resolver.canon_eid(subject), value))
        return values

    def commit_turn(self, state: dict, turn: int) -> list[dict]:
        """Derive this turn's facts from its primitives. Also registers known
        actors (canonical id + alias unification), fixes their persona once (then
        stable), and records per-NPC knowledge deltas as `knows` facts."""
        new: list[dict] = []
        # 0. known cast: unify entities by alias + lock persona (once, stable)
        for a in (state.get('actors') or {}).values():
            if not isinstance(a, dict) or a.get('kind') == 'protagonist':
                continue
            eid = self.resolver.resolve(a.get('name', ''), aliases=a.get('aliases'))
            if eid:
                self.resolver.set_persona(eid, a.get('personality', ''), identity=a.get('identity', ''))
                # relationship is DYNAMIC: append a `relation` fact only when the
                # label changes, so the relationship line keeps its history (when /
                # why) without being locked like persona.
                rel = a.get('relationship_to_protagonist')
                if isinstance(rel, dict):
                    label = _normalize_relation_label(rel.get('label', ''))
                    if label and label != self._latest_relation_label(eid):
                        new.append(_fact(self._next(), turn, 'relation', subject=eid,
                                         value=label, text=str(rel.get('evidence', '') or '').strip(),
                                         span={'turn_id': f'turn-{turn:04d}'}))
        # 0b. scene_entities carry the freshest aliases — the keeper records "短工"
        #     as an alias of "桥上探头男人" here before it reaches the actor table.
        #     Feeding them lets a late alias unify a previously split entity.
        for e in (state.get('scene_entities') or []):
            if isinstance(e, dict) and e.get('primary_label'):
                self.resolver.resolve(e.get('primary_label', ''), aliases=e.get('aliases'))
        # 1. presence + this turn's beat
        loc = str(state.get('location', '') or '').strip()
        main_event = str(state.get('main_event', '') or '').strip()
        onstage = [n for n in (state.get('onstage_npcs') or []) if isinstance(n, str) and n.strip()]
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
        # 2. knowledge-boundary delta: what each NPC newly learned -> `knows` facts
        #    (a whitelist — absence means "does not know", the safe default)
        npc_local = (state.get('knowledge_scope') or {}).get('npc_local') or {}
        known_values = self._known_values()
        if isinstance(npc_local, dict):
            for nm, payload in npc_local.items():
                eid = self.resolver.resolve(nm)
                if not eid or self.resolver.entities[eid].kind == 'protagonist':
                    continue
                cid = self.resolver.canon_eid(eid)
                learned = payload.get('learned') if isinstance(payload, dict) else payload
                if isinstance(learned, list):
                    for item in learned:
                        text = str(item or '').strip()
                        key = (cid, text)
                        if text and key not in known_values:
                            known_values.add(key)
                            new.append(_fact(self._next(), turn, 'knows', subject=eid, value=text,
                                             span={'turn_id': f'turn-{turn:04d}'}))
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
        return project(self.facts, self.resolver.entities, self.resolver.canon_eid)

    def retrieve(self, query: str = '', **kwargs) -> list[dict]:
        """Long-tail recall for one query (see `fact_retrieval.retrieve`). Entity
        ids are folded through the resolver, so an old surface name still answers
        after a merge."""
        return retrieve_facts(self.facts, self.resolver.entities, query,
                              canon_eid=self.resolver.canon_eid, **kwargs)

    def entity_observations(self, eid: str, limit: int = 12) -> list[str]:
        """Beat-observation texts this entity took part in — material for distilling
        a persona from how it actually behaved in-story."""
        cid = self.resolver.canon_eid(eid)
        out: list[str] = []
        for f in self.facts:
            if f.get('predicate') == 'observation' and f.get('beat'):
                if any(self.resolver.canon_eid(e) == cid for e in f.get('entities', [])):
                    text = f.get('text')
                    if text:
                        out.append(text)
        return out[-limit:]

    def personaless_active(self, min_turns: int = 3) -> list[str]:
        """Surviving NPCs with screen time (present on >= min_turns) but no persona
        yet — candidates for one-time persona distillation."""
        present: dict[str, set] = {}
        for f in self.facts:
            if f.get('predicate') == 'present':
                present.setdefault(self.resolver.canon_eid(f['subject']), set()).add(f.get('turn'))
        out = []
        for eid, ent in self.resolver.entities.items():
            if ent.merged_into or ent.kind == 'protagonist' or ent.persona:
                continue
            if len(present.get(eid, ())) >= min_turns:
                out.append(eid)
        return out

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


def project(facts: list[dict], entities: dict, canon_eid=None) -> dict:
    """Pure fold. `important_npcs`, per-entity `last_event`, persona and the
    knowledge boundary are all derived, never stored — so nothing downstream can
    clobber them. `knowledge_boundary` is a whitelist: an entity absent from it
    knows none of the protagonist's hidden facts (the safe default). `canon_eid`
    folds merged-away entity ids onto their survivor, so the append-only log never
    needs rewriting when two entities later turn out to be one person."""
    cz = canon_eid or (lambda e: e)
    empty = {'onstage_npcs': [], 'important_npcs': [], 'entity_last_event': {},
             'entity_persona': {}, 'entity_aliases': {}, 'knowledge_boundary': {},
             'entity_relationship': {}, 'entity_relationship_history': {}}
    if not facts:
        return empty
    latest = max(f['turn'] for f in facts)
    present_turns: dict[str, set] = {}    # turns an entity was on-stage
    seen_turns: dict[str, set] = {}       # turns an entity was present OR mentioned
    last_loc: dict[str, tuple] = {}
    last_event: dict[str, tuple] = {}
    boundary: dict[str, list] = {}        # entity -> things it has learned (whitelist)
    rel_now: dict[str, tuple] = {}        # entity -> (turn, label, evidence): current relationship
    rel_history: dict[str, list] = {}     # entity -> [(turn, label, evidence)]: relationship line
    for f in facts:
        t = f['turn']
        pred = f['predicate']
        if pred == 'present':
            s = cz(f['subject'])
            present_turns.setdefault(s, set()).add(t)
            seen_turns.setdefault(s, set()).add(t)
            if s not in last_loc or t >= last_loc[s][0]:
                last_loc[s] = (t, f.get('value') or '')
        elif pred == 'observation' and f.get('beat'):
            for eid in f.get('entities', []):
                eid = cz(eid)
                seen_turns.setdefault(eid, set()).add(t)
                cur = last_event.get(eid)
                if cur is None or t > cur[0]:
                    last_event[eid] = (t, f.get('text') or '')
        elif pred == 'knows':
            s = cz(f['subject'])
            vals = boundary.setdefault(s, [])
            v = f.get('value') or ''
            if v and v not in vals:
                vals.append(v)
        elif pred == 'relation':
            s = cz(f['subject'])
            entry = (t, f.get('value') or '', f.get('text') or '')
            rel_history.setdefault(s, []).append(entry)
            if s not in rel_now or t >= rel_now[s][0]:
                rel_now[s] = entry

    def _ent(eid):
        return entities.get(eid)

    def canon(eid):
        e = _ent(eid)
        if e is None:
            return eid
        return e.canonical if isinstance(e, Entity) else e.get('canonical', eid)

    def persona_of(eid):
        e = _ent(eid)
        if e is None:
            return ''
        return e.persona if isinstance(e, Entity) else e.get('persona', '')

    def merged(eid):
        e = _ent(eid)
        if e is None:
            return False
        return bool(e.merged_into if isinstance(e, Entity) else e.get('merged_into', ''))

    def aliases_of(eid):
        e = _ent(eid)
        if e is None:
            return []
        return list((e.aliases if isinstance(e, Entity) else e.get('aliases', [])) or [])

    def kind_of(eid):
        e = _ent(eid)
        if e is None:
            return ''
        return e.kind if isinstance(e, Entity) else e.get('kind', '')

    # Importance candidates = anyone seen (present or mentioned), ranked by how
    # many turns they were actually on-stage, then by recency.
    def is_ephemeral(eid):
        # One-time passer-by: on-stage exactly once and already gone a couple of
        # turns. Kept in the entity table, but doesn't take a long-term-roster slot
        # (important / authoritative cast) — so name-spam doesn't accrete. present==1
        # (not 0): a seeded / only-mentioned NPC has no `present` fact and is exempt.
        pt = present_turns.get(eid, set())
        return len(pt) == 1 and (latest - max(seen_turns[eid])) >= 2

    def is_inactive_faded(eid):
        # Long absence: drop from important roster so early road NPCs don't accrete
        # forever (e23032-class bloat). Entity + facts remain; only the projected
        # list fades. Persona-locked NPCs are "emerged cast" and stay listed.
        present = present_turns.get(eid, set())
        if latest in present:
            return False
        inactive = latest - max(seen_turns[eid])
        if inactive < IMPORTANT_INACTIVE_FADE_TURNS:
            return False
        if persona_of(eid):
            return False
        return True

    ranked = sorted(seen_turns,
                    key=lambda e: (len(present_turns.get(e, ())), max(seen_turns[e])),
                    reverse=True)
    important = []
    for eid in ranked:
        if is_ephemeral(eid) or is_inactive_faded(eid):
            continue
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
        'entity_persona': {canon(eid): persona_of(eid) for eid in entities
                           if persona_of(eid) and not merged(eid)},
        'entity_aliases': {canon(eid): aliases_of(eid) for eid in entities
                           if not merged(eid) and kind_of(eid) != 'protagonist'},
        'knowledge_boundary': {canon(e): vals for e, vals in boundary.items()},
        'entity_relationship': {canon(e): v[1] for e, v in rel_now.items()},
        'entity_relationship_history': {canon(e): [{'turn': t, 'label': lb, 'evidence': ev} for (t, lb, ev) in h]
                                        for e, h in rel_history.items()},
    }


def merge_projected_important_npcs(
    prev_items: list | None,
    projected_items: list | None,
    entity_aliases: dict | None = None,
) -> list[dict]:
    """Build the authoritative important_npcs roster from a fact-log projection
    without dropping the thick schema downstream consumers still need.

    Projection owns membership and dynamic anchors:
      primary_label, present_now, last_main_event, last_location, inactive_turns
    Previous rows (matched by label/alias) and entity_aliases supply:
      key, aliases, role_label, locked, importance_score, retained, …
    """
    prev = [item for item in (prev_items or []) if isinstance(item, dict)]
    projected = [item for item in (projected_items or []) if isinstance(item, dict)]
    aliases_by_label = entity_aliases if isinstance(entity_aliases, dict) else {}

    # Index previous rows by primary label and every alias surface.
    prev_by_surface: dict[str, dict] = {}
    for item in prev:
        label = str(item.get('primary_label', '') or '').strip()
        if label and label not in prev_by_surface:
            prev_by_surface[label] = item
        for alias in item.get('aliases', []) or []:
            surface = str(alias or '').strip()
            if surface and surface not in prev_by_surface:
                prev_by_surface[surface] = item

    merged: list[dict] = []
    seen_labels: set[str] = set()
    for proj in projected:
        label = str(proj.get('primary_label', '') or '').strip()
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)

        prev_hit = prev_by_surface.get(label)
        if prev_hit is None:
            # Also match when prev's primary is listed as an alias of this canonical.
            for surface, item in prev_by_surface.items():
                if surface == label:
                    prev_hit = item
                    break
                prev_primary = str(item.get('primary_label', '') or '').strip()
                proj_alias_set = {
                    str(a or '').strip()
                    for a in (aliases_by_label.get(label) or [])
                    if str(a or '').strip()
                }
                if prev_primary and prev_primary in proj_alias_set:
                    prev_hit = item
                    break
                prev_aliases = {
                    str(a or '').strip()
                    for a in (item.get('aliases') or [])
                    if str(a or '').strip()
                }
                if label in prev_aliases:
                    prev_hit = item
                    break

        row: dict = dict(prev_hit) if isinstance(prev_hit, dict) else {}
        # Projection-owned fields always win.
        row['primary_label'] = label
        row['present_now'] = bool(proj.get('present_now'))
        row['last_main_event'] = str(proj.get('last_main_event', '') or '')
        row['last_location'] = str(proj.get('last_location', '') or '')
        row['inactive_turns'] = int(proj.get('inactive_turns', 0) or 0)

        # Thick schema defaults / enrichment.
        if not row.get('key'):
            row['key'] = f'important:{label}'
        else:
            # Keep key stable if label upgraded (沈昭 vs 灰衣青年); only rewrite when empty-ish.
            pass
        ent_aliases = [
            str(a or '').strip()
            for a in (aliases_by_label.get(label) or [])
            if str(a or '').strip() and str(a or '').strip() != label
        ]
        prev_aliases = [
            str(a or '').strip()
            for a in (row.get('aliases') or [])
            if str(a or '').strip() and str(a or '').strip() != label
        ]
        # Prefer entity-table aliases; keep previous surfaces that aren't the new primary.
        combined: list[str] = []
        for alias in ent_aliases + prev_aliases:
            if alias not in combined:
                combined.append(alias)
        row['aliases'] = combined
        if 'role_label' not in row or not str(row.get('role_label') or '').strip():
            row['role_label'] = '待确认'
        if 'anchor_type' not in row:
            row['anchor_type'] = 'continuous'
        if 'worldbook_candidate' not in row:
            row['worldbook_candidate'] = False
        if 'reference_source' not in row:
            row['reference_source'] = 'factlog_project'
        if 'importance_score' not in row:
            row['importance_score'] = 3
        # Continuity / state_updater filter on locked — projected long-term roster is locked.
        if 'locked' not in row:
            row['locked'] = True
        if 'retained' not in row:
            row['retained'] = not bool(row.get('present_now'))
        row['newly_locked'] = False if prev_hit is not None else True
        merged.append(row)
    return merged
