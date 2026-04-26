#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

try:
    from .llm_manager import get_role_runtime
    from .local_model_client import parse_json_response
    from .model_client import call_model
    from .model_config import resolve_provider_model
    from .character_assets import character_source_base, lorebook_path
except ImportError:
    from llm_manager import get_role_runtime
    from local_model_client import parse_json_response
    from model_client import call_model
    from model_config import resolve_provider_model
    from character_assets import character_source_base, lorebook_path


FOUNDATION_FILE = 'lorebook-foundation.json'
INDEX_FILE = 'lorebook-index.json'
MAX_FOUNDATION_RULES = 18
MAX_INDEX_ITEMS = 80
MAX_HEURISTIC_FOUNDATION_RULES = 5
DISTILL_MAX_OUTPUT_TOKENS = 1200
MAX_LLM_DISTILL_ENTRIES = 10


DISTILL_SYSTEM = """你是角色卡世界书蒸馏器。

只输出 JSON，不要解释。

目标：把完整世界书压缩成两个运行期产物：
1. foundation_rules：每轮常驻的短规则/世界基础，不写剧情推进，不写当前场景状态。
2. situational_lore：只输出最关键的条件召回摘要；也可以输出空数组，遗漏条目会由脚本补齐。

输出格式：
{
  "foundation_rules": [
    {"title": "短标题", "text": "80-180字规则或世界基础", "category": "rule|world|faction|tone|other", "source_entry_ids": ["..."]}
  ],
  "situational_lore": [
    {"id": "稳定短id", "title": "短标题", "summary": "80-220字摘要", "keywords": ["检索词"], "category": "rule|world|faction|place|history|npc|mechanic|other", "source_entry_ids": ["..."]}
  ]
}

规则：
1. foundation_rules 只保留 narrator 每轮都必须知道的世界认知、禁忌、运行原则、身份边界、叙事口径。
2. situational_lore 保留可条件召回的细节，不要泛化成空话。
3. 不要把 NPC 当前短期状态、开局即时冲突、会话状态写成 foundation。
4. 每条必须能追溯 source_entry_ids。
5. keywords 只用于检索索引，应提取原文中稳定出现的名称、地点、势力或机制称呼，不要发明剧情触发词。
6. foundation_rules 最多 3 条，situational_lore 最多 3 条；不要试图覆盖全部条目，遗漏条目会由脚本 fallback 补齐。
7. 每条 text/summary 控制在 40-120 中文字，宁可少写，不要展开长列表。
"""


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _compact(value: str, limit: int = 220) -> str:
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = max(cut.rfind(token) for token in ('。', '！', '？', '. ', '; ', '；', '\n', ' - ', '，', ','))
    if boundary >= max(60, int(limit * 0.55)):
        cut = cut[:boundary + 1]
    return cut.rstrip(' ，,；;：:-—“"\'(')


def _clean_source_text(value: str) -> str:
    text = str(value or '').strip()
    text = re.sub(r'^```[A-Za-z0-9_-]*\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    parsed = None
    if text.startswith('{') and text.endswith('}'):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
    if isinstance(parsed, dict):
        parts = []
        for key in ('content', 'description', 'text', 'summary'):
            item = parsed.get(key)
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
        keys = parsed.get('keys')
        if isinstance(keys, list):
            labels = [str(item or '').strip() for item in keys if str(item or '').strip()]
            if labels:
                parts.insert(0, '关键词：' + '、'.join(labels[:8]))
        if parts:
            text = '\n'.join(parts)
    # YAML-like cards are useful, but narrator does not need code fences or raw nesting syntax.
    text = re.sub(r'^\s*([A-Za-z_][A-Za-z0-9_ -]{0,40}):\s*', lambda m: f'{m.group(1).strip()}：', text, flags=re.M)
    text = text.replace('{{user}}', '玩家')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _stable_id(prefix: str, text: str) -> str:
    digest = hashlib.md5(text.encode('utf-8')).hexdigest()[:10]
    return f'{prefix}-{digest}'


def _entry_id(entry: dict, index: int) -> str:
    value = str(entry.get('id', '') or '').strip()
    if value:
        return value
    title = str(entry.get('title', '') or '').strip()
    return _stable_id(f'entry-{index:04d}', title + str(index))


def _enabled_entries(lorebook: dict) -> list[dict]:
    entries = lorebook.get('entries', []) if isinstance(lorebook.get('entries', []), list) else []
    out = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        if entry.get('disable') is True or entry.get('enabled') is False:
            continue
        content = str(entry.get('content', '') or '').strip()
        if not content:
            continue
        item = dict(entry)
        item['id'] = _entry_id(item, index)
        item['content'] = content
        out.append(item)
    return out


def _source_hash(entries: list[dict]) -> str:
    payload = [
        {
            'id': item.get('id'),
            'title': item.get('title'),
            'keywords': item.get('keywords'),
            'content': item.get('content'),
            'alwaysOn': item.get('alwaysOn'),
            'priority': item.get('priority'),
        }
        for item in entries
    ]
    return hashlib.md5(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _keywords(entry: dict) -> list[str]:
    values = []
    title = str(entry.get('title', '') or '').strip()
    if title:
        values.append(title)
        for part in re.split(r'[\s/／|｜·・:：()（）\[\]【】,，]+', title):
            token = part.strip('☁️-*# ')
            if 2 <= len(token) <= 12 and token not in values:
                values.append(token)
    for field in ('keywords', 'secondary_keywords'):
        raw = entry.get(field, [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            continue
        for item in raw:
            text = str(item or '').strip()
            if text and text not in values:
                values.append(text)
    content = _clean_source_text(str(entry.get('content', '') or ''))[:1200]
    quoted = re.findall(r'[《“"「『]([^》”"」』]{2,12})[》”"」』]', content)
    proper = re.findall(r'(?<![\u4e00-\u9fff])([\u4e00-\u9fffA-Za-z0-9·]{2,12}(?:城|司|门|教|宗|派|阁|楼|盟|府|山|原|关|军|团|会|所|塔|沼泽|大陆|王朝|商会|安全区|研究所|异能|晶核|雷劫|秘境|丧尸|病毒))(?![\u4e00-\u9fff])', content)
    labels = re.findall(r'(?:势力|领袖|总部|地点|组织|阵营|类型|化名|姓名|别名|关键词)[:：]\s*([\u4e00-\u9fffA-Za-z0-9·/／、，,]{2,40})', content)
    for token in quoted + proper:
        token = token.strip(' ，,；;：:。.-')
        if 2 <= len(token) <= 12 and token not in values:
            values.append(token)
    for label in labels:
        for token in re.split(r'[/／、，,\s]+', label):
            token = token.strip(' ，,；;：:。.-')
            if 2 <= len(token) <= 12 and token not in values:
                values.append(token)
    return values[:18]


def _category(entry: dict) -> str:
    entry_type = str(entry.get('entryType', '') or '').strip()
    if entry_type in {'rule', 'world', 'faction', 'history', 'npc', 'mechanic', 'place'}:
        return entry_type
    title = str(entry.get('title', '') or '')
    content = str(entry.get('content', '') or '')
    if title.startswith('NPC：'):
        return 'npc'
    if any(token in title + content[:160] for token in ('规则', '必须', '禁止', '自检', 'Identity', '玩家', '异人', '需同时满足', '全洁')):
        return 'rule'
    if any(token in title for token in ('世界观', '世界基础')):
        return 'world'
    if any(token in title.lower() for token in ('location', '地点', '地理')):
        return 'place'
    if any(token in title for token in ('历史', '时间线', '事件')):
        return 'history'
    if any(token in title for token in ('派', '门', '帮', '司', '盟', '寨', '阁')):
        return 'faction'
    return 'other'


def _foundation_score(entry: dict, category: str) -> int:
    title = str(entry.get('title', '') or '')
    content = _clean_source_text(str(entry.get('content', '') or ''))[:400]
    if any(token in title for token in ('人物总览', '关键人物', '重要历史', '时间线', '地点总览', '主要势力', '势力与组织', '势力与npc', 'NPC：', 'npc：', 'Npc-')):
        if not any(token in title + content[:160] for token in ('身份边界', '自检', '运行规则', '动态规则', '禁区', '禁止', '必须', 'Identity', '玩家', '异人', '土著')):
            return -100
    if category not in {'rule', 'world'}:
        return -100
    score = int(entry.get('priority', 0) or 0) // 20
    if bool(entry.get('alwaysOn')) or str(entry.get('runtimeScope', '') or '') == 'foundation':
        score += 10
    if category == 'rule':
        score += 8
    elif category == 'world' and not any(token in title for token in ('地点', 'location', '人物总览', '势力', '组织')):
        score += 6
    elif category in {'place', 'history', 'npc', 'faction'}:
        score -= 4
    if any(token in title + content for token in ('身份边界', '世界观', '运行规则', '动态规则', '禁区', '禁止', '必须', '玩家', '异人', '土著')):
        score += 5
    if any(token in title for token in ('人物总览', '关键人物', '势力与npc', 'NPC', 'npc')):
        score -= 8
    return score


def _fallback_distill(entries: list[dict], *, provider: str = 'heuristic') -> tuple[dict, dict]:
    foundation_candidates = []
    situational = []
    for entry in entries:
        title = str(entry.get('title', entry.get('id', '未命名')) or '未命名').strip()
        content = _clean_source_text(str(entry.get('content', '') or '').strip())
        category = _category(entry)
        source_ids = [str(entry.get('id', '') or '').strip()]
        keywords = _keywords(entry)
        foundation_score = _foundation_score(entry, category)
        if foundation_score >= 8:
            foundation_candidates.append((foundation_score, {
                'title': _compact(title, 80),
                'text': _compact(content, 220 if category == 'rule' else 180),
                'category': category if category in {'rule', 'world', 'tone'} else 'other',
                'source_entry_ids': source_ids,
            }))
        situational.append({
            'id': _stable_id('lore', str(entry.get('id')) + title),
            'title': _compact(title, 80),
            'summary': _compact(content, 260),
            'keywords': keywords,
            'category': category,
            'source_entry_ids': source_ids,
            'priority': int(entry.get('priority', 0) or 0),
        })
    foundation_candidates.sort(key=lambda row: row[0], reverse=True)
    foundation_rules = [item for _score, item in foundation_candidates[:MAX_HEURISTIC_FOUNDATION_RULES]]
    if not foundation_rules:
        for item in situational[:3]:
            if item.get('category') in {'npc', 'history', 'faction', 'place'}:
                continue
            foundation_rules.append({
                'title': item['title'],
                'text': _compact(item['summary'], 180),
                'category': item.get('category', 'other'),
                'source_entry_ids': item.get('source_entry_ids', []),
            })
            if len(foundation_rules) >= 3:
                break
    situational.sort(key=lambda item: (-int(item.get('priority', 0) or 0), item.get('title', '')))
    meta = {'version': 1, 'provider': provider, 'source_hash': _source_hash(entries), 'entry_count': len(entries)}
    foundation = {**meta, 'rules': foundation_rules[:MAX_HEURISTIC_FOUNDATION_RULES]}
    index = {**meta, 'items': situational[:MAX_INDEX_ITEMS]}
    return foundation, index


def _normalize_list(value, limit: int, item_limit: int = 180) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = _compact(str(item or ''), item_limit)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _normalize_llm(payload: dict, entries: list[dict]) -> tuple[dict, dict]:
    fallback_foundation, fallback_index = _fallback_distill(entries, provider='llm')
    valid_source_ids = {str(item.get('id', '') or '') for item in entries}
    rules = []
    for item in payload.get('foundation_rules', []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        source_ids = [x for x in _normalize_list(item.get('source_entry_ids', []), 8, 80) if x in valid_source_ids]
        text = _compact(item.get('text', ''), 220)
        title = _compact(item.get('title', ''), 80)
        if not text or not source_ids:
            continue
        rules.append({
            'title': title or '世界基础',
            'text': text,
            'category': str(item.get('category', 'other') or 'other')[:24],
            'source_entry_ids': source_ids,
        })
        if len(rules) >= MAX_FOUNDATION_RULES:
            break
    items = []
    for item in payload.get('situational_lore', []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        source_ids = [x for x in _normalize_list(item.get('source_entry_ids', []), 8, 80) if x in valid_source_ids]
        summary = _compact(item.get('summary', ''), 260)
        title = _compact(item.get('title', ''), 80)
        if not summary or not source_ids:
            continue
        key = str(item.get('id', '') or '').strip() or _stable_id('lore', title + summary)
        items.append({
            'id': re.sub(r'[^0-9A-Za-z_\-]+', '-', key).strip('-')[:80] or _stable_id('lore', title + summary),
            'title': title or '世界书条目',
            'summary': summary,
            'keywords': _normalize_list(item.get('keywords', []), 16, 40),
            'category': str(item.get('category', 'other') or 'other')[:24],
            'source_entry_ids': source_ids,
        })
        if len(items) >= MAX_INDEX_ITEMS:
            break
    if not rules:
        rules = fallback_foundation['rules']
    seen_sources = {source_id for item in items for source_id in (item.get('source_entry_ids', []) or [])}
    for item in fallback_index['items']:
        source_ids = [str(x or '') for x in (item.get('source_entry_ids', []) or [])]
        if any(source_id in seen_sources for source_id in source_ids):
            continue
        items.append(item)
        seen_sources.update(source_ids)
        if len(items) >= MAX_INDEX_ITEMS:
            break
    if not items:
        items = fallback_index['items']
    meta = {'version': 1, 'provider': 'llm', 'source_hash': _source_hash(entries), 'entry_count': len(entries)}
    return {**meta, 'rules': rules}, {**meta, 'items': items}


def _build_llm_prompt(entries: list[dict]) -> str:
    compact_entries = []
    for entry in entries:
        compact_entries.append({
            'id': entry.get('id'),
            'title': entry.get('title'),
            'keywords': _keywords(entry),
            'alwaysOn': bool(entry.get('alwaysOn')),
            'entryType': entry.get('entryType'),
            'runtimeScope': entry.get('runtimeScope'),
            'priority': entry.get('priority'),
            'content': _compact(entry.get('content', ''), 300),
        })
    return json.dumps({'entries': compact_entries}, ensure_ascii=False, indent=2)


def _llm_candidate_entries(entries: list[dict], limit: int = MAX_LLM_DISTILL_ENTRIES) -> list[dict]:
    scored = []
    for index, entry in enumerate(entries):
        category = _category(entry)
        score = max(0, _foundation_score(entry, category))
        score += int(entry.get('priority', 0) or 0) // 25
        if bool(entry.get('alwaysOn')) or str(entry.get('runtimeScope', '') or '') == 'foundation':
            score += 4
        if category in {'rule', 'world'}:
            score += 4
        elif category in {'faction', 'place', 'history'}:
            score += 2
        scored.append((score, -index, entry))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [entry for _score, _index, entry in scored[:limit]]


def _call_distill_llm(system_prompt: str, user_prompt: str) -> tuple[str, dict]:
    runtime = get_role_runtime('state_keeper_candidate')
    if runtime['provider'] != 'llm':
        raise RuntimeError('state_keeper_candidate is not configured for llm provider')
    model_cfg = dict(resolve_provider_model(runtime['model_role']))
    model_cfg['stream'] = False
    model_cfg['max_output_tokens'] = max(int(model_cfg.get('max_output_tokens', 0) or 0), DISTILL_MAX_OUTPUT_TOKENS)
    reply, usage = call_model(model_cfg, system_prompt, user_prompt)
    usage['role'] = 'lorebook_distiller'
    usage['model_role'] = runtime['model_role']
    return reply, usage


def _distill_with_llm(entries: list[dict], *, attempts: int = 2) -> tuple[dict, dict]:
    user_prompt = _build_llm_prompt(_llm_candidate_entries(entries))
    last_error: Exception | None = None
    for _attempt in range(max(1, attempts)):
        try:
            reply, _usage = _call_distill_llm(DISTILL_SYSTEM, user_prompt)
            if not str(reply or '').strip():
                raise ValueError('empty LLM response')
            return _normalize_llm(parse_json_response(reply), entries)
        except Exception as err:
            last_error = err
    if last_error:
        raise last_error
    raise RuntimeError('LLM distillation failed')


def distill_lorebook(lorebook_file: Path, *, force_llm: bool = False) -> tuple[dict, dict]:
    lorebook = _read_json(lorebook_file)
    entries = _enabled_entries(lorebook)
    if not entries:
        meta = {'version': 1, 'provider': 'empty', 'source_hash': '', 'entry_count': 0}
        return {**meta, 'rules': []}, {**meta, 'items': []}
    if force_llm:
        return _distill_with_llm(entries, attempts=2)
    try:
        return _distill_with_llm(entries, attempts=2)
    except Exception:
        return _fallback_distill(entries, provider='heuristic')


def rebuild_lorebook_distillation(source_root: Path | None = None, *, force_llm: bool = False) -> dict:
    root = source_root or character_source_base()
    lorebook_file = root / 'lorebook.json'
    foundation, index = distill_lorebook(lorebook_file, force_llm=force_llm)
    _write_json(root / FOUNDATION_FILE, foundation)
    _write_json(root / INDEX_FILE, index)
    return {
        'success': True,
        'lorebook': str(lorebook_file),
        'foundation': str(root / FOUNDATION_FILE),
        'index': str(root / INDEX_FILE),
        'provider': foundation.get('provider'),
        'foundation_rules': len(foundation.get('rules', [])),
        'index_items': len(index.get('items', [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Build cached Threadloom lorebook distillation files.')
    parser.add_argument('--source-root', help='Character source directory containing lorebook.json. Defaults to active character source.')
    parser.add_argument('--lorebook', help='Explicit lorebook.json path; outputs next to it.')
    parser.add_argument('--force-llm', action='store_true', help='Fail if LLM distillation cannot run instead of using heuristic fallback.')
    args = parser.parse_args()
    if args.lorebook:
        lore_file = Path(args.lorebook).expanduser().resolve()
        root = lore_file.parent
    elif args.source_root:
        root = Path(args.source_root).expanduser().resolve()
    else:
        root = lorebook_path().parent
    report = rebuild_lorebook_distillation(root, force_llm=args.force_llm)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
