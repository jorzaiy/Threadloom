#!/usr/bin/env python3
"""Recall benchmark — is fact-log `retrieve()` actually better than the lexical
baseline it replaces, on real sessions?

Scores hand-labelled queries (`tests/fixtures/recall_bench.jsonl`: query -> the
turns whose facts *should* come back) against two rankers:

    baseline    |query bigrams ∩ fact bigrams|, recency as tie-break — the scoring
                core of selector.py, which is what long-tail recall used before
    retrieve()  BM25 + entity link + near window, fused by RRF

Two deliberate properties of the label set:

- it is split into **verbatim** and **paraphrase**. Queries written by lifting rare
  words out of the gold text measure the baseline's best case; the actual complaint
  ("同义换个说法就漏召") only shows up on paraphrases, so a single blended number
  hides the thing worth knowing.
- baseline ranks are computed over the facts it can actually score. Where overlap is
  zero the baseline still "returns" the gold fact eventually — that is its recency
  tie-break landing on it by accident, not recall, so `--strict-baseline` (default)
  reports those as a miss rather than crediting a rank.

Usage:
    python3 scripts/recall_bench.py [--bench PATH] [--data-root DIR] [--gate] [--lenient-baseline]

`runtime-data/` is gitignored, so a git worktree has no sessions of its own — point
`--data-root` (or `$THREADLOOM_DATA_ROOT`) at the checkout that actually holds them.

`--gate` exits non-zero unless retrieve() beats the baseline on overall MRR without
regressing recall@8 — the promotion condition for THREADLOOM_RETRIEVE_V2 (see
doc/ROADMAP.md P1).
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend.fact_log import FactLog                         # noqa: E402
from backend.fact_retrieval import _display_text             # noqa: E402
from backend.selector import _topic_tokens                    # noqa: E402


def _label_resolver(log: FactLog):
    def label_of(eid):
        if not eid:
            return ''
        ent = log.resolver.entities.get(log.resolver.canon_eid(eid))
        return getattr(ent, 'canonical', '') or str(eid)
    return label_of

DEFAULT_BENCH = ROOT / 'tests/fixtures/recall_bench.jsonl'
SESSIONS_GLOB = 'runtime-data/*/characters/*/sessions'
KS = (1, 3, 8)


def find_session(session_id: str, data_root: Path) -> Path | None:
    for sessions_dir in data_root.glob(SESSIONS_GLOB):
        candidate = sessions_dir / session_id
        if (candidate / 'memory' / 'facts.jsonl').exists():
            return candidate
    return None


def baseline_ranks(log: FactLog, query: str, gold: set, *, strict: bool) -> int | None:
    """Rank of the first gold fact under bigram set overlap.

    Scored over the *same* candidate pool retrieve() sees, rendered the same way.
    Restricting the baseline to `observation` facts (its historical pool, since the
    selector only ever searched event summaries) would hand it a cleaner field with
    fewer distractors and measure the pool, not the scoring function.
    """
    tokens = _topic_tokens(query)
    label_of = _label_resolver(log)
    scored = []
    for fact in log.facts:
        text = _display_text(fact, label_of)
        overlap = len(tokens & _topic_tokens(text))
        if strict and overlap == 0:
            continue
        scored.append((overlap, int(fact.get('turn', 0) or 0)))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    for rank, (_, turn) in enumerate(scored, start=1):
        if turn in gold:
            return rank
    return None


def retrieve_rank(log: FactLog, query: str, gold: set) -> int | None:
    for rank, hit in enumerate(log.retrieve(query, limit=len(log.facts)), start=1):
        if int(hit.get('turn', 0) or 0) in gold:
            return rank
    return None


def summarise(ranks: list) -> dict:
    n = len(ranks) or 1
    out = {f'recall@{k}': sum(1 for r in ranks if r and r <= k) / n for k in KS}
    out['MRR'] = sum(1 / r for r in ranks if r) / n
    out['misses'] = sum(1 for r in ranks if not r)
    return out


def fmt(label: str, stats: dict) -> str:
    cells = '  '.join(f'{k} {stats[k]:.2f}' for k in (f'recall@{k}' for k in KS))
    return f'  {label:<24} {cells}  MRR {stats["MRR"]:.3f}  misses {stats["misses"]}'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bench', default=str(DEFAULT_BENCH))
    parser.add_argument('--data-root', default=os.environ.get('THREADLOOM_DATA_ROOT', str(ROOT)),
                        help='checkout holding runtime-data/ (gitignored, so a worktree has none)')
    parser.add_argument('--gate', action='store_true')
    parser.add_argument('--lenient-baseline', action='store_true',
                        help='credit the baseline for zero-overlap facts its recency tie-break happens to surface')
    args = parser.parse_args()
    data_root = Path(args.data_root)

    rows = [json.loads(line) for line in Path(args.bench).read_text(encoding='utf-8').splitlines() if line.strip()]
    logs: dict[str, FactLog] = {}
    results = []
    for row in rows:
        session_id = row['session']
        if session_id not in logs:
            session_dir = find_session(session_id, data_root)
            if session_dir is None:
                print(f'!! session not on disk under {data_root}, skipping its rows: {session_id}')
                logs[session_id] = None
            else:
                logs[session_id] = FactLog.load(session_dir / 'memory')
        log = logs[session_id]
        if log is None:
            continue
        gold = set(row['gold_turns'])
        results.append({
            'kind': row.get('kind', 'unlabelled'),
            'query': row['query'],
            'base': baseline_ranks(log, row['query'], gold, strict=not args.lenient_baseline),
            'new': retrieve_rank(log, row['query'], gold),
        })
    if not results:
        print('no scorable rows — is the benchmark session present under runtime-data/?')
        return 1

    print(f'\n{len(results)} queries over {len({r for r in logs if logs[r]})} session(s)'
          f'   [baseline: {"lenient" if args.lenient_baseline else "strict"}]')
    for kind in ('verbatim', 'paraphrase'):
        subset = [r for r in results if r['kind'] == kind]
        if not subset:
            continue
        print(f'\n### {kind} ({len(subset)})')
        print(fmt('baseline (bigram)', summarise([r['base'] for r in subset])))
        print(fmt('retrieve() RRF', summarise([r['new'] for r in subset])))
    overall_base = summarise([r['base'] for r in results])
    overall_new = summarise([r['new'] for r in results])
    print('\n### overall')
    print(fmt('baseline (bigram)', overall_base))
    print(fmt('retrieve() RRF', overall_new))

    print('\n### per query (rank of first gold fact; · = miss)')
    for r in sorted(results, key=lambda r: r['kind']):
        base = r['base'] if r['base'] else '·'
        new = r['new'] if r['new'] else '·'
        flag = '  <-- worse' if (r['new'] or 999) > (r['base'] or 999) else ''
        print(f'  [{r["kind"][:4]}] base {str(base):>4} -> new {str(new):>4}   {r["query"]}{flag}')

    better_mrr = overall_new['MRR'] > overall_base['MRR']
    no_regression = overall_new['recall@8'] >= overall_base['recall@8']
    verdict = 'PASS' if (better_mrr and no_regression) else 'FAIL'
    print(f'\nVERDICT {verdict} — MRR {overall_new["MRR"]:.3f} vs {overall_base["MRR"]:.3f}, '
          f'recall@8 {overall_new["recall@8"]:.2f} vs {overall_base["recall@8"]:.2f}')
    if verdict == 'FAIL':
        print('  (promotion condition for THREADLOOM_RETRIEVE_V2 not met — keep injection off)')
    return 1 if (args.gate and verdict == 'FAIL') else 0


if __name__ == '__main__':
    raise SystemExit(main())
