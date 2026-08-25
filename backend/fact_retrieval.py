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
from itertools import zip_longest

# RRF damping. The literature's k=60 is calibrated for TREC-scale result lists; with
# ~100 facts and lanes capped at 20, 1/(60+1) vs 1/(60+15) is nearly flat, so "voted
# by two lanes at any rank" beats "top of the lexical lane" — the near-window facts
# all pick up a weak lexical vote and crowd out the answer. Measured on the recall
# bench, overall MRR by k: 60 → 0.48, 10 → 0.52, 5 → 0.55, 2 → 0.71 (and the ordering
# holds on both halves of the bench separately, so it is not fitting noise).
RRF_K = 2
# Deliberately unequal, and re-tuned on the recall bench. The near window is
# *already* in context (context_builder always carries the recent turns), so a
# recency hit is continuity support, not an answer — at 0.35 it was still buying
# head slots that the answer needed. Overall MRR at K=2: recency 0.35 / entity 0.6
# → 0.71; recency 0.15 / entity 0.35 → 0.83. Dropping recency to 0 measures the
# same within noise, so it keeps a small vote: it is what still answers a vague
# input like "继续", where there is nothing lexical to match.
LANE_WEIGHTS = {'recency': 0.15, 'lexical': 1.0, 'entity': 0.35}
BM25_K1 = 1.5
# Below the textbook 0.75: these documents are short heterogeneous sentences
# (20-90 chars), not web pages, so full length normalisation over-penalised the
# long beat observations that actually hold the answers. Measured on the live
# session's five near-verbatim recall queries: MRR 0.74 (b=0.75) -> 0.84 (b=0.35),
# with no change on the paraphrase set.
BM25_B = 0.35

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
_DURABLE_PREDICATES = ('knows', 'relation', 'holds')

# `present` rows carry no content of their own — their whole text is the entity
# label plus a location, both of which the entity lane already indexes. Letting
# them into the BM25 index is actively harmful: they are an order of magnitude
# shorter than a beat observation, and BM25's length normalisation then ranks a
# content-free "阿砚 在裂口边缘树皮上" above the long observation that actually
# answers the question.
_LEXICAL_SKIP_PREDICATES = ('present',)

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
        # Unigrams *and* bigrams: bigrams carry the phrase, unigrams catch the
        # single-character overlaps a bigram window slices apart — 赏钱 vs 谢仙师赏,
        # 护身 vs 护盾, 骨头 vs 鸟骨. Common characters are harmless here because
        # IDF prices them at ~0; it is the rare ones that pay off.
        out.extend(run)
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
    out.extend(_ASCII_RUN.findall(text))
    for term in dictionary:
        if len(term) >= 2 and term in text:
            out.append(f'@{term}')
    return out


def _bm25(doc_tokens: dict[int, list[str]], query_tokens: list[str],
          groups: dict | None = None) -> dict[int, float]:
    """Okapi BM25 with the always-positive IDF variant (log(1 + …)), so a term in
    most documents contributes ~0 rather than a negative score.

    Length is normalised **within a document group** (here: the fact's predicate),
    not against one global average. Fact types differ in length by an order of
    magnitude — a `knows` row is a dozen tokens, a beat observation sixty — so a
    single avgdl hands every short type a systematic head-of-ranking advantage that
    has nothing to do with relevance. Grouping makes a long observation compete
    against other observations.
    """
    n = len(doc_tokens)
    if not n or not query_tokens:
        return {}
    freqs = {fid: Counter(toks) for fid, toks in doc_tokens.items()}
    lengths = {fid: max(1, len(toks)) for fid, toks in doc_tokens.items()}
    groups = groups or {}
    group_of = {fid: groups.get(fid, '') for fid in doc_tokens}
    totals: dict[str, list] = {}
    for fid, length in lengths.items():
        bucket = totals.setdefault(group_of[fid], [0, 0])
        bucket[0] += length
        bucket[1] += 1
    avgdl = {key: (total / count if count else 1.0) for key, (total, count) in totals.items()}
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
            norm = lengths[fid] / max(1e-9, avgdl.get(group_of[fid], 1.0))
            denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * norm)
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
        indexable = [f for f in facts
                     if str(f.get('predicate') or '') not in _LEXICAL_SKIP_PREDICATES]
        doc_tokens = {f.get('id'): _tokens(_index_text(f, label_of), dictionary) for f in indexable}
        doc_groups = {f.get('id'): str(f.get('predicate') or '') for f in indexable}
        scored = _bm25(doc_tokens, _tokens(query, dictionary), doc_groups)
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
        own = facts_by_entity.get(eid, [])
        # Interleave the two kinds instead of ranking durable facts strictly first:
        # a chatty NPC with seven `knows` rows would otherwise eat the whole per-seed
        # quota and its actual scene beats would never enter the lane.
        durable = _ranked([(f.get('id'), (_ENTITY_PREDICATE_PRIORITY.get(str(f.get('predicate') or ''), 1),
                                          int(f.get('turn', 0) or 0), f.get('id') or 0))
                           for f in own if str(f.get('predicate') or '') in _DURABLE_PREDICATES])
        events = _ranked([(f.get('id'), (int(f.get('turn', 0) or 0), f.get('id') or 0))
                          for f in own if str(f.get('predicate') or '') == 'observation'])
        picked: list[int] = []
        for pair in zip_longest(durable, events):
            for fid in pair:
                if fid is not None and len(picked) < ENTITY_FACTS_PER_SEED:
                    picked.append(fid)
        if not picked:              # nothing but presence rows: keep one as an anchor
            picked = _ranked([(f.get('id'), (int(f.get('turn', 0) or 0), f.get('id') or 0))
                              for f in own])[:1]
        entity_lane.extend(fid for fid in picked if fid not in entity_lane)

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
