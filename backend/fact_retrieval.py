#!/usr/bin/env python3
"""V2 memory read path — `retrieve()`, the third pure op over the fact log.

`project()` answers "what is true now". This answers "what is relevant to *this*
query", which is the long-tail recall the design doc left at zero.

It replaces the selector's char-bigram set-overlap scoring — which weights a rare
name (灵貂) exactly like filler (一个) because a set intersection has no term
weights — with three ranked lanes fused by RRF:

    recency   the near window; always eligible, independent of wording
    lexical   BM25 over each fact's rendered text — IDF is what demotes filler
    entity    a name/alias in the query (or an NPC on stage right now) pulls that
              entity's own facts, folded through `canon_eid` so a merged or
              renamed entity still answers to its old surface

Fusing *ranks* rather than raw scores means the lanes need no score calibration,
and a fourth lane (embeddings) can be added later without retuning these three —
which is exactly why the embedding decision doesn't block this.

Pure functions, no I/O, no cached index: the index is rebuilt per call from the
same `facts` list `project()` folds over (~100 facts in a live session, so the
fold is sub-millisecond and a cache would only be a thing to invalidate wrongly).
"""
from __future__ import annotations

import math
import re
from collections import Counter

RRF_K = 60                       # standard reciprocal-rank-fusion damping
LANE_WEIGHTS = {'recency': 1.0, 'lexical': 1.0, 'entity': 1.0}
BM25_K1 = 1.5
BM25_B = 0.75

# Per-lane candidate caps: a lane only votes with its head, so one very long lane
# cannot dominate fusion just by being long.
RECENCY_LANE_CAP = 12
LEXICAL_LANE_CAP = 20
ENTITY_FACTS_PER_SEED = 4

# Within one entity's own facts, prefer the durable ones. A `present` row is the
# least informative thing we know about someone (the projection already says who
# is on stage), so without this a chatty NPC's presence rows would crowd out the
# knowledge / relationship lines that are the reason to pull the entity at all.
_ENTITY_PREDICATE_PRIORITY = {'knows': 3, 'relation': 3, 'holds': 2, 'observation': 1, 'present': 0}

_ASCII_RUN = re.compile(r'[a-z0-9]+')
_CJK_RUN = re.compile(r'[一-鿿]+')
# Same conservative particle strip as the resolver, kept local so this module has
# no dependency on fact_log (fact_log imports *this*).
_PARTICLE = re.compile(r'[的地得]')


def _norm(text: str) -> str:
    return _PARTICLE.sub('', str(text or '').strip()).lower()


def _tokens(text: str, dictionary=()) -> list[str]:
    """Bag of tokens for BM25 — no segmenter dependency.

    CJK runs become char bigrams (a single-char run stays whole), ASCII/digit runs
    become words, and any registered entity surface found in the text is emitted
    whole under an `@` prefix so an exact name match carries its own IDF instead of
    dissolving into overlapping bigrams.
    """
    text = _norm(text)
    out: list[str] = []
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            out.append(run)
            continue
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
    out.extend(_ASCII_RUN.findall(text))
    for term in dictionary:
        if len(term) >= 2 and term in text:
            out.append(f'@{term}')
    return out


def _bm25(doc_tokens: dict[int, list[str]], query_tokens: list[str]) -> dict[int, float]:
    """Okapi BM25 with the always-positive IDF variant (log(1 + …)), so a term in
    most documents contributes ~0 rather than a negative score."""
    n = len(doc_tokens)
    if not n or not query_tokens:
        return {}
    freqs = {fid: Counter(toks) for fid, toks in doc_tokens.items()}
    lengths = {fid: max(1, len(toks)) for fid, toks in doc_tokens.items()}
    avgdl = sum(lengths.values()) / n
    df: Counter = Counter()
    for f in freqs.values():
        df.update(f.keys())
    scores: dict[int, float] = {}
    for term in set(query_tokens):
        d = df.get(term, 0)
        if not d:
            continue
        idf = math.log(1 + (n - d + 0.5) / (d + 0.5))
        for fid, f in freqs.items():
            tf = f.get(term, 0)
            if not tf:
                continue
            denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * lengths[fid] / avgdl)
            scores[fid] = scores.get(fid, 0.0) + idf * tf * (BM25_K1 + 1) / denom
    return scores


# -- entity-table access (tolerates both `Entity` dataclasses and plain dicts) --
def _attr(ent, name: str, default=''):
    if ent is None:
        return default
    if isinstance(ent, dict):
        return ent.get(name, default)
    return getattr(ent, name, default)


def _surfaces(ent) -> list[str]:
    out = [str(_attr(ent, 'canonical') or '')]
    out.extend(str(a or '') for a in (_attr(ent, 'aliases', []) or []))
    return [s for s in out if s]


_PREDICATE_RENDER = {
    'present': '{subj} 在{value}',
    'holds': '{subj} 持有{value}',
    'knows': '{subj} 已知：{value}',
    'relation': '{subj} 与主角关系：{value}',
}


def _display_text(fact: dict, label_of) -> str:
    """One readable line per fact — what a caller can paste into a prompt, and
    (plus participant labels) what BM25 indexes."""
    pred = str(fact.get('predicate') or '')
    text = str(fact.get('text') or '').strip()
    value = str(fact.get('value') or '').strip()
    if pred == 'observation':
        return text or value
    subj = label_of(fact.get('subject'))
    template = _PREDICATE_RENDER.get(pred)
    if not template:
        return text or value
    line = template.format(subj=subj, value=value).strip()
    if pred == 'relation' and text:
        line = f'{line}（{text}）'
    return line


def _index_text(fact: dict, label_of) -> str:
    """Display line + participant canonical labels. Aliases are deliberately left
    out: the entity lane already handles "same person, other name", and stuffing
    every alias into every one of that entity's facts would flatten BM25's ability
    to tell those facts apart."""
    parts = [_display_text(fact, label_of)]
    for eid in fact.get('entities') or []:
        parts.append(label_of(eid))
    return ' '.join(p for p in parts if p)


def _ranked(pairs) -> list[int]:
    """[(fact_id, sort_key)] -> fact ids, best first, stable."""
    return [fid for fid, _ in sorted(pairs, key=lambda item: item[1], reverse=True)]


def retrieve(facts: list[dict], entities: dict, query: str = '', *,
             canon_eid=None, recent_turns: int = 3, limit: int = 8,
             max_chars: int | None = None, weights: dict | None = None,
             now_turn: int | None = None) -> list[dict]:
    """Rank facts by relevance to `query`, newest-first within equal relevance.

    Returns hits shaped for both prompt injection and diagnostics::

        {'fact_id', 'turn', 'predicate', 'text', 'span', 'labels',
         'score', 'lanes': {lane: rank}}

    `span` rides along on every hit so any recalled line stays traceable to the
    turn it came from — recall without a source pointer is how confabulation gets
    laundered into context.
    """
    cz = canon_eid or (lambda e: e)
    facts = [f for f in (facts or []) if isinstance(f, dict)]
    if not facts:
        return []
    # A superseding fact retires the fact it replaces — never recall a corrected line.
    retired = {f.get('supersedes') for f in facts if f.get('supersedes') is not None}
    facts = [f for f in facts if f.get('id') not in retired]
    if not facts:
        return []
    by_id = {f.get('id'): f for f in facts}
    latest = now_turn if now_turn is not None else max(int(f.get('turn', 0) or 0) for f in facts)
    lane_w = {**LANE_WEIGHTS, **(weights or {})}

    def label_of(eid):
        if not eid:
            return ''
        ent = entities.get(cz(eid)) or entities.get(eid)
        return str(_attr(ent, 'canonical') or eid)

    # -- entity surfaces, folded onto survivors -------------------------------
    surface_to_eid: dict[str, str] = {}
    for eid, ent in (entities or {}).items():
        if _attr(ent, 'kind') == 'protagonist':
            continue
        target = cz(eid)
        for surface in _surfaces(ent):
            key = _norm(surface)
            if len(key) >= 2:
                surface_to_eid.setdefault(key, target)
    dictionary = sorted(surface_to_eid, key=len, reverse=True)

    # -- lane 1: recency ------------------------------------------------------
    window_start = latest - max(0, recent_turns - 1)
    recency = _ranked([(f.get('id'), (int(f.get('turn', 0) or 0), f.get('id') or 0))
                       for f in facts if int(f.get('turn', 0) or 0) >= window_start])[:RECENCY_LANE_CAP]

    # -- lane 2: lexical (BM25) ----------------------------------------------
    query_norm = _norm(query)
    lexical: list[int] = []
    if query_norm:
        doc_tokens = {f.get('id'): _tokens(_index_text(f, label_of), dictionary) for f in facts}
        scored = _bm25(doc_tokens, _tokens(query, dictionary))
        lexical = _ranked([(fid, (score, int(by_id[fid].get('turn', 0) or 0)))
                           for fid, score in scored.items() if score > 0])[:LEXICAL_LANE_CAP]

    # -- lane 3: entity link --------------------------------------------------
    # Seeds: entities named in the query first, then whoever is on stage right now
    # (their persona / knowledge / relationship is relevant even if it was recorded
    # 40 turns ago, which no amount of recency or wording will surface).
    query_seeds = [eid for surface, eid in surface_to_eid.items() if surface in query_norm]
    onstage = [cz(f.get('subject')) for f in facts
               if f.get('predicate') == 'present' and int(f.get('turn', 0) or 0) == latest]
    seeds: list[str] = []
    for eid in [*query_seeds, *onstage]:
        if eid and eid not in seeds:
            seeds.append(eid)
    facts_by_entity: dict[str, list[dict]] = {}
    for f in facts:
        touched = {cz(e) for e in (f.get('entities') or []) if e}
        if f.get('subject'):
            touched.add(cz(f.get('subject')))
        for eid in touched:
            facts_by_entity.setdefault(eid, []).append(f)
    entity_lane: list[int] = []
    for eid in seeds:
        own = _ranked([(f.get('id'), (_ENTITY_PREDICATE_PRIORITY.get(str(f.get('predicate') or ''), 1),
                                      int(f.get('turn', 0) or 0), f.get('id') or 0))
                       for f in facts_by_entity.get(eid, [])])[:ENTITY_FACTS_PER_SEED]
        entity_lane.extend(fid for fid in own if fid not in entity_lane)

    # -- fuse (RRF over ranks) ------------------------------------------------
    fused: dict[int, float] = {}
    lanes: dict[int, dict] = {}
    for lane, ordered in (('recency', recency), ('lexical', lexical), ('entity', entity_lane)):
        for rank, fid in enumerate(ordered, start=1):
            fused[fid] = fused.get(fid, 0.0) + lane_w.get(lane, 1.0) / (RRF_K + rank)
            lanes.setdefault(fid, {})[lane] = rank
    order = sorted(fused, key=lambda fid: (fused[fid], int(by_id[fid].get('turn', 0) or 0), fid),
                   reverse=True)

    hits: list[dict] = []
    used = 0
    for fid in order:
        if len(hits) >= max(0, limit):
            break
        f = by_id[fid]
        text = _display_text(f, label_of)
        if max_chars is not None and used + len(text) > max_chars and hits:
            break
        used += len(text)
        labels = [label_of(f.get('subject'))] if f.get('subject') else []
        labels += [label_of(e) for e in (f.get('entities') or [])]
        hits.append({
            'fact_id': fid,
            'turn': int(f.get('turn', 0) or 0),
            'predicate': str(f.get('predicate') or ''),
            'text': text,
            'span': f.get('span'),
            'labels': [lb for lb in dict.fromkeys(labels) if lb],
            'score': round(fused[fid], 6),
            'lanes': lanes.get(fid, {}),
        })
    return hits
