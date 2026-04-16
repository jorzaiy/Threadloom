#!/usr/bin/env python3
"""Character card importer for Threadloom v0.3+.

The importer no longer dumps Tavern fields directly into runtime-facing files.
It generates a clean character source bundle under:

- character-data.json     : card core / runtime-facing role data
- lorebook.json           : normalized world knowledge entries
- openings.json           : opening menu + bootstrap
- system-npcs.json        : explicit system-level NPC roster
- import-manifest.json    : provenance / import stats
- assets/                 : cover assets
- imported/               : raw card backups
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import struct
from pathlib import Path
from typing import Any

try:
    from .card_hints import invalidate_card_hints_cache
    from .character_assets import (
        clear_character_override_root,
        character_assets_root,
        character_source_base,
        character_core_path,
        import_manifest_path,
        imported_card_root,
        lorebook_path,
        openings_path,
        set_character_override_root,
        system_npcs_path,
    )
except ImportError:
    from card_hints import invalidate_card_hints_cache
    from character_assets import (
        clear_character_override_root,
        character_assets_root,
        character_source_base,
        character_core_path,
        import_manifest_path,
        imported_card_root,
        lorebook_path,
        openings_path,
        set_character_override_root,
        system_npcs_path,
    )

logger = logging.getLogger(__name__)


def _read_png_chunks(data: bytes) -> list[tuple[str, bytes]]:
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a valid PNG file')
    chunks = []
    offset = 8
    while offset < len(data):
        if offset + 8 > len(data):
            break
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8].decode('ascii', errors='replace')
        chunk_data = data[offset + 8:offset + 8 + length]
        chunks.append((chunk_type, chunk_data))
        offset += 12 + length
    return chunks


def _extract_text_chunks(data: bytes) -> dict[str, str]:
    result = {}
    for chunk_type, chunk_data in _read_png_chunks(data):
        if chunk_type == 'tEXt':
            null_pos = chunk_data.find(b'\x00')
            if null_pos >= 0:
                key = chunk_data[:null_pos].decode('latin-1')
                value = chunk_data[null_pos + 1:].decode('latin-1')
                result[key] = value
        elif chunk_type == 'iTXt':
            null_pos = chunk_data.find(b'\x00')
            if null_pos < 0:
                continue
            key = chunk_data[:null_pos].decode('utf-8', errors='replace')
            rest = chunk_data[null_pos + 1:]
            if len(rest) < 2:
                continue
            comp_flag = rest[0]
            rest = rest[2:]
            null2 = rest.find(b'\x00')
            if null2 >= 0:
                rest = rest[null2 + 1:]
            null3 = rest.find(b'\x00')
            if null3 >= 0:
                rest = rest[null3 + 1:]
            if comp_flag == 0:
                result[key] = rest.decode('utf-8', errors='replace')
            else:
                try:
                    import zlib
                    result[key] = zlib.decompress(rest).decode('utf-8', errors='replace')
                except Exception:
                    result[key] = rest.decode('utf-8', errors='replace')
    return result


def extract_card_json(png_data: bytes) -> dict:
    text_chunks = _extract_text_chunks(png_data)
    for key in ('chara', 'ccv3'):
        encoded = text_chunks.get(key, '')
        if not encoded:
            continue
        try:
            return json.loads(base64.b64decode(encoded))
        except Exception as err:
            logger.warning('Failed to decode %s chunk: %s', key, err)
    raise ValueError('no SillyTavern character data found in PNG')


def load_raw_card(path: str | Path) -> dict:
    raw_path = Path(path)
    return json.loads(raw_path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _clean_text(value: Any) -> str:
    text = str(value or '').strip()
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()


def _stable_hash(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode('utf-8')
    return hashlib.md5(content).hexdigest()[:16]


def _extract_card_payload(card_json: dict) -> dict:
    data = card_json.get('data', {}) if isinstance(card_json.get('data'), dict) else {}
    return data or card_json


def _extract_opening_options(card_payload: dict) -> list[dict]:
    first_message = _clean_text(card_payload.get('first_mes', ''))
    menu_options = _extract_menu_options(first_message)
    if menu_options:
        return menu_options

    options: list[dict] = []
    if first_message:
        options.append({
            'id': 'opening-default',
            'title': '默认开场',
            'prompt': first_message[:240],
            'full_text': first_message,
        })

    greetings = card_payload.get('alternate_greetings', [])
    if not isinstance(greetings, list):
        greetings = []
    for index, item in enumerate(greetings, start=1):
        text = _clean_text(item)
        if not text:
            continue
        title = text
        prompt = text
        if '：' in text:
            title, prompt = text.split('：', 1)
        elif ':' in text:
            title, prompt = text.split(':', 1)
        options.append({
            'id': f'opening-{index:02d}',
            'title': title.strip()[:80] or f'开局 {index}',
            'prompt': prompt.strip()[:240] or text[:240],
            'full_text': text,
        })
    return options


def _extract_menu_options(first_message: str) -> list[dict]:
    if not first_message:
        return []
    options = []
    for raw_line in first_message.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r'^\d{1,2}\s*[：:、.]?\s*[「"]?([^」":]+)[」"]?\s*(.*)$', line)
        if not match:
            continue
        title = _clean_text(match.group(1))
        prompt = _clean_text(match.group(2))
        if not title:
            continue
        options.append({
            'id': f'opening-{len(options) + 1:02d}',
            'title': title[:80],
            'prompt': prompt[:240] or title[:240],
            'full_text': f'{title}：{prompt}'.strip('：'),
        })
    return options


def _extract_character_core(card_json: dict) -> dict:
    payload = _extract_card_payload(card_json)
    name = _clean_text(payload.get('name') or card_json.get('name'))
    description = _clean_text(payload.get('description') or card_json.get('description'))
    scenario = _clean_text(payload.get('scenario') or card_json.get('scenario'))
    personality = _clean_text(payload.get('personality') or card_json.get('personality'))
    system_prompt = _clean_text(payload.get('system_prompt', ''))
    creator_notes = _clean_text(payload.get('creator_notes') or payload.get('creatorcomment') or card_json.get('creatorcomment'))

    summary_parts = [part for part in (description, scenario) if part]
    core = {
        'name': name or '未命名角色卡',
        'role': personality[:240],
        'coreDescription': {
            'title': name or '未命名角色卡',
            'tagline': scenario[:120],
            'summary': '\n\n'.join(summary_parts)[:1200],
        },
        'opening': '故事将从这里开始。',
        'notes': creator_notes[:800],
        'source': {
            'spec': str(card_json.get('spec', '') or '').strip(),
            'spec_version': str(card_json.get('spec_version', '') or '').strip(),
        },
    }
    if system_prompt:
        core['system_summary'] = system_prompt[:1200]
    return core


def _classify_lorebook_entry(title: str, content: str, keywords: list[str], always_on: bool) -> dict:
    title_text = str(title or '').strip()
    keyword_text = ' '.join(str(item or '').strip() for item in (keywords or []) if str(item or '').strip())
    combined = '\n'.join(part for part in (title_text, content, keyword_text) if part)
    lower_title = title_text.lower()

    def has_any(tokens: tuple[str, ...]) -> bool:
        return any(token in title_text or token in combined for token in tokens)

    if has_any((
        '状态栏',
        '推荐bgm',
        '动态世界线',
        '开场白',
        '开局',
        '选开',
        '导引',
        'Relationship Rules',
        '人际规则',
        '人际模板',
        '玩家档案',
        'TavernDB-ACU-WrapperStart',
        'TavernDB-ACU-WrapperEnd',
        'WrapperStart',
        'WrapperEnd',
        '总结条目',
        '重要人物表-',
        'ReadableDataTable',
        'OutlineTable',
        'ImportantPersonsIndex',
        'PersonsHeader',
    )):
        return {
            'entryType': 'runtime_aux',
            'runtimeScope': 'archive_only',
            'featured': False,
        }

    if (
        'TavernDB-' in title_text
        or title_text.startswith('总结条目')
        or title_text.startswith('重要人物表-')
        or 'WrapperStart' in title_text
        or '重要对话' in content
        or 'AM000' in combined
    ):
        return {
            'entryType': 'runtime_dump',
            'runtimeScope': 'archive_only',
            'featured': False,
        }

    if lower_title.startswith('npc：') or lower_title.startswith('npc:'):
        return {
            'entryType': 'npc',
            'runtimeScope': 'situational',
            'featured': False,
        }

    if has_any(('认知迷雾', '过滤', '规则', '机制', '自检', '状态栏', '动态世界线', 'Relationship Rules')):
        if has_any(('开场白', '开局', '选开', '导引')):
            return {
                'entryType': 'runtime_aux',
                'runtimeScope': 'archive_only',
                'featured': False,
            }
        return {
            'entryType': 'rule',
            'runtimeScope': 'foundation',
            'featured': False,
        }

    if has_any(('世界基石', '世界观', '世界设定')):
        return {
            'entryType': 'world',
            'runtimeScope': 'foundation',
            'featured': False,
        }

    if has_any(('地点总览', '风貌', '地理', '地区', '地图')):
        return {
            'entryType': 'region',
            'runtimeScope': 'foundation' if always_on else 'situational',
            'featured': False,
        }

    if has_any(('历史事件', '历史真相', '往事')):
        return {
            'entryType': 'history',
            'runtimeScope': 'foundation' if always_on else 'situational',
            'featured': False,
        }

    if has_any(('关键人物总览', '知名人物', '皇家成员', '朝堂相关要员', '太子势力', '人物总览')):
        return {
            'entryType': 'cast',
            'runtimeScope': 'situational',
            'featured': True,
        }

    if has_any(('势力', '组织', '门派', '教派')):
        return {
            'entryType': 'faction',
            'runtimeScope': 'foundation' if always_on or has_any(('总览', '主要')) else 'situational',
            'featured': bool(has_any(('关键', '主要'))),
        }

    return {
        'entryType': 'entry',
        'runtimeScope': 'foundation' if always_on else 'situational',
        'featured': False,
    }


def _convert_lorebook_entry(entry: dict) -> dict:
    keys = entry.get('keys', [])
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.split(',') if k.strip()]
    secondary = entry.get('secondary_keys', [])
    if isinstance(secondary, str):
        secondary = [k.strip() for k in secondary.split(',') if k.strip()]

    title = _clean_text(entry.get('comment', entry.get('name', '')))
    content = _clean_text(entry.get('content', ''))
    keywords = [item for item in keys + secondary if str(item or '').strip()]
    always_on = bool(entry.get('constant', False))
    metadata = _classify_lorebook_entry(title, content, keywords, always_on)
    return {
        'id': str(entry.get('id', entry.get('uid', ''))),
        'title': title,
        'keywords': keywords,
        'content': content,
        'alwaysOn': always_on,
        'priority': int(entry.get('insertion_order', entry.get('order', 0)) or 0),
        'enabled': bool(entry.get('enabled', True)),
        'entryType': metadata.get('entryType', 'entry'),
        'runtimeScope': metadata.get('runtimeScope', 'situational'),
        'featured': bool(metadata.get('featured', False)),
    }


def _extract_lorebook(card_json: dict) -> dict:
    payload = _extract_card_payload(card_json)
    raw_book = payload.get('character_book', card_json.get('character_book', {}))
    entries = raw_book.get('entries', []) if isinstance(raw_book, dict) else []
    if isinstance(entries, dict):
        entries = list(entries.values())
    normalized = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        converted = _convert_lorebook_entry(item)
        if converted.get('content'):
            normalized.append(converted)
    return {
        'name': _clean_text((raw_book or {}).get('name', '')),
        'entries': normalized,
    }


def _looks_like_system_npc(title: str, content: str) -> bool:
    title_lower = title.lower()
    if any(token in title for token in ('过滤', '势力', '拉郎配', '选开', '自检', '江湖')):
        return False
    if title_lower.startswith('npc：') or title_lower.startswith('npc:'):
        return True
    if title_lower.startswith('npc ') or title_lower.startswith('npc-'):
        return True
    if '角色详情:' in content:
        return True
    if '绝对禁止把他写成' in content or '绝对禁区:' in content:
        return True
    if '该角色有两个动态状态' in content or '动态角色' in content:
        return True
    if '核心规则:' in content and ('触发条件:' in content or '触发:' in content):
        return True
    return False


def _extract_system_npcs(lorebook: dict, card_json: dict | None = None) -> dict:
    descriptor_prefixes = ('身份:', '外貌:', '性格:', '武器:', '定位:', '形象:', '来历:', '核心:', '本质:', '职责:')
    non_heading_prefixes = (
        '形象:', '外貌:', '身份:', '性格:', '武器:', '定位:', '本质:', '核心:', '力量:', '关系:', '职责:',
        '部落:', '类型:', '总部:', '信仰', '核心目的:', '主要成员:', '特殊能力:', '合作:', '准则:',
        '权力实质:', '据点:', '行事准则:', '现状:', '业务:', '体系:', '统帅:', '自称:', '潜在', '魅力:'
    )
    container_heading_tokens = (
        '代表人物', '狼王十三骑', '四方血裔', '太子心腹', '法定配置', '个人经营', '与各方关系',
        '关系与历史', '核心与理念', '实力与影响', '当前', '说明', '规则', '总览', '势力', '组织',
        '状态栏', '导引', '开场', 'Relationship Rules'
    )
    skip_embedded_entry_tokens = ('规则', '选开', '状态栏', '风貌', '世界基石', '自检', '推荐bgm', '动态世界线', '玩家', '土著', '档案', '开场白')
    skip_embedded_exact_titles = {'主要势力与组织', '知名玩家档案', 'TavernDB-ACU-ImportantPersonsIndex', 'TavernDB-ACU-PersonsHeader'}
    non_person_suffixes = ('堂', '局', '楼', '阁', '门', '帮', '司', '军', '派')
    template_title_tokens = ('[event]', '[system]', '[meta]', '状态栏', '人际', 'number', 'favor', 'meet', 'wrapper', 'memory')
    runtime_dump_title_tokens = ('总结条目', '重要人物条目', 'TavernDB-', 'ReadableDataTable', 'OutlineTable', 'ImportantPersonsIndex', 'PersonsHeader')

    def _is_non_character_system_item(name: str, role_label: str = '', summary: str = '') -> bool:
        text = f'{name} {role_label} {summary}'.strip()
        if any(token in name for token in ('设定', '状态栏', '规则', '世界观', '世界基石')):
            return True
        if name in {'世界观', '状态栏', '人际', '记忆', 'number', 'favor', 'meet'}:
            return True
        if any(token in text for token in ('作者指令', '状态栏', '世界设定', '动态规则', '关系模板')):
            return True
        return False

    def _maybe_add_card_primary_npc() -> list[dict]:
        payload = _extract_card_payload(card_json or {})
        name = _clean_text(payload.get('name') or (card_json or {}).get('name'))
        description = _clean_text(payload.get('description') or (card_json or {}).get('description'))
        scenario = _clean_text(payload.get('scenario') or (card_json or {}).get('scenario'))
        summary = '\n\n'.join(part for part in (description, scenario) if part).strip()
        world_tokens = ('开放世界', '世界裁定者', '世界模拟', 'world', '设定集', '资料片')
        non_character_name_tokens = ('大陆', '纪', '世界', '学院', '组织', '计划', '设定', '档案', '系统')
        if not name:
            return []
        if any(token.lower() in summary.lower() for token in world_tokens):
            return []
        if any(token in name for token in non_character_name_tokens):
            return []
        if len(name) > 24:
            return []
        if not ('·' in name or 2 <= len(name) <= 8):
            return []
        return [{
            'name': name,
            'aliases': [],
            'role_label': name,
            'faction': '',
            'summary': summary[:1200],
            'source_entry_id': 'card-core',
            'priority': 1000,
        }]

    def _looks_like_template_entry(title: str, content: str) -> bool:
        lower_title = title.lower()
        if any(token in lower_title for token in template_title_tokens):
            return True
        stripped = content.strip()
        if stripped.startswith('{') and '"entries"' in stripped[:400]:
            return True
        if '{%' in content or '{{' in content:
            return True
        if '<world_setting>' in content.lower():
            return True
        return False

    def _looks_like_runtime_dump_entry(title: str, content: str) -> bool:
        lower_title = title.lower()
        if any(token.lower() in lower_title for token in runtime_dump_title_tokens):
            return True
        if 'AM0001' in content or '重要对话' in content or '时间跨度' in content:
            return True
        return False

    def _extract_template_relationship_npcs(entry: dict) -> list[dict]:
        content = str(entry.get('content', '') or '')
        if 'user.relationships' not in content and "'name':" not in content and '"name":' not in content:
            return []
        block_matches = re.findall(r'\{\\?\s*(.*?)\\?\s*\}', content, re.S)
        out: list[dict] = []
        for block in block_matches:
            name_match = re.search(r"""['"]name['"]\s*:\s*['"]([^'"]+)['"]""", block)
            if not name_match:
                continue
            clean_name = str(name_match.group(1)).strip()
            if not clean_name or clean_name in {'{{user.name or ', '小美', '人际', '状态栏', '[EVENT]meet', '[SYSTEM]晶核动态系统', '血蚀纪'}:
                continue
            if len(clean_name) > 24:
                continue
            role_match = re.search(r"""['"]type['"]\s*:\s*['"]([^'"]+)['"]""", block)
            personality_match = re.search(r"""['"]personality['"]\s*:\s*['"]([^'"]+)['"]""", block)
            role_label = role_match.group(1).strip() if role_match else clean_name
            summary = personality_match.group(1).strip() if personality_match else ''
            out.append({
                'name': clean_name,
                'aliases': [],
                'role_label': role_label,
                'faction': '',
                'summary': summary[:1200],
                'source_entry_id': str(entry.get('id', '') or ''),
                'priority': int(entry.get('priority', 0) or 0) + 500,
            })
        deduped: list[dict] = []
        seen_names: set[str] = set()
        for item in out:
            if item['name'] in seen_names:
                continue
            seen_names.add(item['name'])
            deduped.append(item)
        return deduped

    def _extract_markdown_table_npcs(entry: dict) -> list[dict]:
        title = str(entry.get('title', '') or '').strip()
        content = str(entry.get('content', '') or '')
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        rows = [line for line in lines if line.startswith('|') and line.count('|') >= 4]
        if not rows:
            return []

        structured_table = len(rows) >= 3 and ('姓名' in rows[0] or '人物名称' in rows[0])
        single_row_person_entry = title.startswith('重要人物条目') and len(rows) >= 1
        if not structured_table and not single_row_person_entry:
            return []

        out: list[dict] = []
        data_rows = rows[2:] if structured_table else rows[:1]
        for row in data_rows:
            cells = [cell.strip() for cell in row.strip('|').split('|')]
            if not cells:
                continue
            name = cells[0].strip()
            if not name or name in {'姓名', '人物名称'}:
                continue
            if any(token in name for token in ('人物名称',)):
                continue
            if len(name) > 24:
                continue
            out.append({
                'name': name.strip('“”"\' '),
                'aliases': [],
                'role_label': title or '重要人物',
                'faction': '',
                'summary': row[:1200],
                'source_entry_id': str(entry.get('id', '') or ''),
                'priority': int(entry.get('priority', 0) or 0),
            })
        return out

    def _extract_name_parts(raw_heading: str, content: str) -> tuple[str, list[str], str]:
        heading = raw_heading.strip().rstrip('：:').strip()
        heading = re.sub(r'^\[[^\]]+\]', '', heading).strip()
        heading = heading.strip('"').strip("'").strip()
        aliases: list[str] = []
        alias_match = re.search(r'化名[:：]\s*([^\)\n\r]+)', content)
        if alias_match:
            alias_value = alias_match.group(1).strip()
            if alias_value:
                aliases.append(alias_value)

        role_label = heading
        if '(化名:' in heading or '（化名:' in heading or '(化名：' in heading or '（化名：' in heading:
            alias_inline = re.search(r'化名[:：]\s*([^\)）]+)', heading)
            if alias_inline:
                alias_value = alias_inline.group(1).strip()
                if alias_value and alias_value not in aliases:
                    aliases.append(alias_value)
        heading = re.sub(r'\((?!化名[:：])[^)]*\)', '', heading).strip()
        heading = re.sub(r'（(?!化名[:：])[^）]*）', '', heading).strip()
        heading = re.sub(r'\s*\(化名[:：][^)]*\)\s*', '', heading).strip()
        heading = re.sub(r'\s*（化名[:：][^）]*）\s*', '', heading).strip()
        if '·' in heading:
            parts = [part.strip(' "\'') for part in heading.split('·') if part.strip(' "\'')]
            if parts:
                name = parts[-1]
                if len(parts) > 1:
                    role_label = heading
                return name, aliases, role_label
        tokens = re.findall(r'[\u4e00-\u9fffA-Za-z]{2,12}', heading)
        if len(tokens) >= 2:
            return tokens[-1], aliases, role_label
        return heading, aliases, role_label

    def _is_org_heading(line: str, next_line: str) -> bool:
        text = line.strip().rstrip('：:')
        if text in {'正道', '中立', '邪道'}:
            return True
        if any(token in text for token in ('势力', '组织', '阵营', '总览', '世界', '规则', '风貌', '状态栏')):
            return True
        if any(text.endswith(token) for token in ('盟', '派', '楼', '堂', '阁', '府', '军', '司', '门', '教', '帮', '骑')):
            if next_line.startswith(('定位:', '行事准则:', '权力实质:', '据点:', '类型:', '总部', '核心与理念:', '历史真相:')):
                return True
        return False

    def _is_role_container_heading(text: str) -> bool:
        clean = text.strip().rstrip('：:')
        return any(token in clean for token in container_heading_tokens)

    def _is_person_name_heading(text: str, next_line: str) -> bool:
        clean = text.strip().rstrip('：:')
        if not clean or clean.startswith(('-', '<', '[')):
            return False
        if any(token in clean for token in ('，', '。', ',', '.', ';', '；', '!', '！', '?', '？')):
            return False
        if (':' in clean or '：' in clean) and not text.strip().endswith(('：', ':')):
            return False
        if clean in {'正道', '中立', '邪道'}:
            return False
        if any(clean.startswith(prefix.rstrip(':')) for prefix in non_heading_prefixes):
            return False
        if _is_org_heading(clean, next_line) or _is_role_container_heading(clean):
            return False
        if re.fullmatch(r'[0-9IVXivx一二三四五六七八九十]+[.)、：:]?', clean):
            return False
        if next_line.startswith(descriptor_prefixes):
            return True
        if re.match(r'^\d+\.\s*["“][^"”]+["”]\s*·\s*[\u4e00-\u9fffA-Za-z]{2,12}$', clean):
            return True
        if '·' in clean and len(clean) <= 24:
            return True
        if len(clean) <= 12 and next_line.startswith(('身份:', '外貌:', '定位:', '形象:')):
            return True
        return False

    def _is_role_heading_with_name_block(text: str) -> bool:
        clean = text.strip()
        if not clean.endswith(('：', ':')):
            return False
        if _is_org_heading(clean, '') or _is_role_container_heading(clean):
            return False
        return any(token in clean for token in ('门主', '掌门', '楼主', '祭司', '指挥使', '大将军', '少帅', '堂主'))

    def _looks_like_person_block(line: str, next_line: str) -> bool:
        text = line.strip()
        if not text:
            return False
        if _is_person_name_heading(text, next_line):
            return True
        if _is_role_heading_with_name_block(text):
            return True
        return False

    def _extract_embedded_npcs(entry: dict) -> list[dict]:
        content = str(entry.get('content', '') or '')
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        out: list[dict] = []
        current_faction = ''
        index = 0
        while index < len(lines):
            line = lines[index]
            next_line = lines[index + 1] if index + 1 < len(lines) else ''

            if any(line.startswith(prefix) for prefix in non_heading_prefixes):
                index += 1
                continue

            if line.startswith('势力:'):
                current_faction = line.split(':', 1)[1].strip() if ':' in line else line.split('：', 1)[1].strip()
                index += 1
                continue
            if _is_org_heading(line, next_line):
                current_faction = line.strip().rstrip('：:')
                index += 1
                continue

            if not _looks_like_person_block(line, next_line):
                index += 1
                continue

            block_lines = [line]
            index += 1
            while index < len(lines):
                probe = lines[index]
                probe_next = lines[index + 1] if index + 1 < len(lines) else ''
                if _is_org_heading(probe, probe_next) or _looks_like_person_block(probe, probe_next):
                    break
                block_lines.append(probe)
                index += 1

            heading = block_lines[0]
            summary = '\n'.join(block_lines).strip()
            if _is_role_heading_with_name_block(heading):
                explicit_name = ''
                for probe in block_lines[1:6]:
                    if probe.startswith('姓名:') or probe.startswith('姓名：'):
                        explicit_name = probe.split(':', 1)[1].strip() if ':' in probe else probe.split('：', 1)[1].strip()
                        break
                if not explicit_name:
                    continue
                name, aliases, role_label = _extract_name_parts(explicit_name, summary)
                role_label = heading.strip().rstrip('：:')
            else:
                name, aliases, role_label = _extract_name_parts(heading, summary)
            if not name or len(name) < 2:
                continue
            if any(token in name for token in ('势力', '规则', '总览', '风貌', '世界', '状态栏', '部落', '锻造', '狩猎')):
                continue
            if any(name.startswith(prefix.rstrip(':')) for prefix in non_heading_prefixes):
                continue
            if any(name.endswith(token) for token in non_person_suffixes):
                continue
            if len(name) > 12:
                continue
            out.append({
                'name': name,
                'aliases': aliases,
                'role_label': role_label,
                'faction': current_faction,
                'summary': summary[:1200],
                'source_entry_id': str(entry.get('id', '') or ''),
                'priority': int(entry.get('priority', 0) or 0),
            })
        return out

    core_items = _maybe_add_card_primary_npc()
    faction_named_items = []
    roster_items = []
    for entry in lorebook.get('entries', []):
        if not isinstance(entry, dict):
            continue
        title = str(entry.get('title', '') or '').strip()
        content = str(entry.get('content', '') or '').strip()
        if _looks_like_runtime_dump_entry(title, content):
            continue
        relationship_items = _extract_template_relationship_npcs(entry)
        if relationship_items:
            core_items.extend(relationship_items)
            continue
        if _looks_like_template_entry(title, content):
            continue
        table_items = _extract_markdown_table_npcs(entry)
        if table_items:
            for item in table_items:
                core_items.append(item)
            continue
        if title in skip_embedded_exact_titles:
            if not _looks_like_system_npc(title, content):
                continue
        if any(token in title for token in skip_embedded_entry_tokens):
            if not _looks_like_system_npc(title, content):
                continue
        if not _looks_like_system_npc(title, content):
            embedded = _extract_embedded_npcs(entry)
            for item in embedded:
                title_text = str(item.get('role_label', '') or '')
                name = str(item.get('name', '') or '')
                if len(name) <= 2 and '·' not in title_text:
                    roster_items.append(item)
                elif any(ch in title_text for ch in ('·', '“', '"')) or '掌门' in title_text or '门主' in title_text or '楼主' in title_text or '祭司' in title_text or '少帅' in title_text or '指挥使' in title_text:
                    faction_named_items.append(item)
                else:
                    roster_items.append(item)
            continue

        if title.lower().startswith('npc：'):
            name_block = title.split('：', 1)[1]
        elif title.lower().startswith('npc:'):
            name_block = title.split(':', 1)[1]
        elif title.lower().startswith('npc-'):
            name_block = title.split('-', 1)[1]
        else:
            match = re.search(r'角色详情[:：]\s*([^\n\r]+)', content)
            name_block = match.group(1).strip() if match else title

        content_head = content.splitlines()[0].strip() if content.strip() else ''
        if content_head and '·' in content_head and '定位' in content:
            name_block = content_head.rstrip('：:').strip()

        primary_name, aliases, role_label = _extract_name_parts(name_block, content)
        faction = ''
        if '太子' in title or '东宫' in content:
            faction = '东宫'
        elif '镇北司' in content:
            faction = '镇北司'
        elif '黄泉引' in content:
            faction = '黄泉引'
        elif '拜月教' in content:
            faction = '拜月教'
        elif '七绝门' in content:
            faction = '七绝门'
        core_items.append({
            'name': primary_name,
            'aliases': aliases,
            'role_label': role_label or primary_name,
            'faction': faction,
            'summary': content[:1200],
            'source_entry_id': str(entry.get('id', '') or ''),
            'priority': int(entry.get('priority', 0) or 0),
        })

    combined = core_items + faction_named_items + roster_items
    combined.sort(key=lambda item: item.get('priority', 0), reverse=True)
    deduped_core = []
    deduped_faction = []
    deduped_roster = []
    seen = set()
    for item in combined:
        name = item.get('name')
        if not name or name in seen:
            continue
        seen.add(name)
        if _is_non_character_system_item(
            str(item.get('name', '') or ''),
            str(item.get('role_label', '') or ''),
            str(item.get('summary', '') or ''),
        ):
            continue
        if item in core_items:
            deduped_core.append(item)
        elif item in faction_named_items:
            deduped_faction.append(item)
        else:
            deduped_roster.append(item)
    return {
        'version': 2,
        'core': deduped_core,
        'faction_named': deduped_faction,
        'roster': deduped_roster,
        'items': deduped_core + deduped_faction,
    }


def _extract_openings_payload(card_json: dict) -> dict:
    payload = _extract_card_payload(card_json)
    core = _extract_character_core(card_json)
    first_message = _clean_text(payload.get('first_mes', ''))
    options = _extract_opening_options(payload)
    return {
        'version': 1,
        'menu_intro': first_message[:1200] if first_message else str(core.get('opening', '') or '故事将从这里开始。').strip(),
        'bootstrap': {
            'time': '待确认',
            'location': '待确认',
            'main_event': '开局待展开。',
            'scene_core': '等待第一轮输入来确立当前场景。',
            'immediate_goal': '先进入开局场景，再决定第一步行动。',
        },
        'options': options,
    }


def _write_cover_assets(png_data: bytes | None, *, raw_card_hash: str) -> dict:
    assets_root = character_assets_root()
    assets_root.mkdir(parents=True, exist_ok=True)
    result = {'cover_saved': False, 'cover_paths': []}
    if not png_data:
        return result
    original_path = assets_root / 'cover-original.png'
    small_path = assets_root / 'cover-small.png'
    original_path.write_bytes(png_data)
    small_path.write_bytes(png_data)
    result['cover_saved'] = True
    result['cover_paths'] = [str(original_path), str(small_path)]
    return result


def _write_imported_backups(card_json: dict, png_data: bytes | None, *, raw_card_hash: str) -> dict:
    imported_root = imported_card_root()
    imported_root.mkdir(parents=True, exist_ok=True)
    raw_path = imported_root / f'{raw_card_hash}.raw-card.json'
    _write_json(raw_path, card_json)
    png_path = None
    if png_data:
        png_path = imported_root / f'{raw_card_hash}.original.png'
        png_path.write_bytes(png_data)
    return {
        'raw_card_path': str(raw_path),
        'png_backup_path': str(png_path) if png_path else '',
    }


def _write_manifest(card_json: dict, lorebook: dict, system_npcs: dict, openings: dict, backups: dict, covers: dict, *, raw_card_hash: str) -> dict:
    payload = _extract_card_payload(card_json)
    manifest = {
        'version': 1,
        'importer': 'threadloom-v0.3',
        'card_name': _clean_text(payload.get('name') or card_json.get('name')),
        'raw_card_hash': raw_card_hash,
        'source': {
            'spec': str(card_json.get('spec', '') or '').strip(),
            'spec_version': str(card_json.get('spec_version', '') or '').strip(),
            'creator': str(payload.get('creator', '') or '').strip(),
        },
        'artifacts': {
            'character_core': str(character_core_path()),
            'lorebook': str(lorebook_path()),
            'openings': str(openings_path()),
            'system_npcs': str(system_npcs_path()),
            'raw_card': backups.get('raw_card_path', ''),
            'png_backup': backups.get('png_backup_path', ''),
            'cover_paths': covers.get('cover_paths', []),
        },
        'stats': {
            'lorebook_entries': len(lorebook.get('entries', [])),
            'lorebook_foundation_entries': sum(1 for item in (lorebook.get('entries', []) or []) if item.get('runtimeScope') == 'foundation'),
            'lorebook_featured_entries': sum(1 for item in (lorebook.get('entries', []) or []) if item.get('featured')),
            'system_npcs': len(system_npcs.get('items', [])),
            'opening_options': len(openings.get('options', [])),
        },
    }
    _write_json(import_manifest_path(), manifest)
    return manifest


def _finalize_character_core(core: dict, manifest: dict) -> dict:
    updated = dict(core)
    updated['source'] = {
        **(updated.get('source', {}) if isinstance(updated.get('source', {}), dict) else {}),
        'import_manifest': str(import_manifest_path()),
        'raw_card': manifest.get('artifacts', {}).get('raw_card', ''),
    }
    return updated


def _write_runtime_baselines(core: dict, lorebook: dict, system_npcs: dict) -> None:
    source_root = character_source_base()
    canon_path = source_root / 'canon.md'
    state_path = source_root / 'state.md'
    summary_path = source_root / 'summary.md'
    npc_dir = source_root / 'memory' / 'npcs'
    npc_dir.mkdir(parents=True, exist_ok=True)

    world_title = str(core.get('name', '') or '未命名角色卡').strip() or '未命名角色卡'
    world_summary = str((core.get('coreDescription', {}) if isinstance(core.get('coreDescription', {}), dict) else {}).get('summary', '') or '').strip()
    canon_lines = [
        '# Canon',
        '',
        '## 世界长期事实',
        f'- 世界或角色卡：{world_title}。',
        '- 长期事实应优先来自当前角色卡 source 目录，而不是共享旧根目录。',
    ]
    if world_summary:
        canon_lines.append(f'- 简介：{world_summary[:800]}')
    canon_lines.extend([
        '',
        '## 长期运行原则',
        '- 新开局、新导入聊天记录与 runtime context 应优先读取当前角色卡层基线文件。',
        '- 系统级 NPC 应优先来自 system-npcs.json，不在这里重复堆叠整份人物表。',
        '',
    ])
    canon_path.write_text('\n'.join(canon_lines), encoding='utf-8')

    state_lines = [
        '# State',
        '',
        '## Usage Rules',
        '- 这里只放角色卡层的基础运行态模板，不写任何旧 session 残留。',
        '- 进入具体会话后，应尽快由 session-local state 接管。',
        '',
        '## World Time',
        '- 当前时间：待确认。',
        '',
        '## Current Scene',
        '- 当前地点：待确认。',
        '- 当前主事件：等待开局选择。',
        '- 当前局势核心：等待开局落地，暂不预设具体场景冲突。',
        '',
        '## Protagonist Runtime',
        '- 主角：待从角色卡与聊天上下文建立。',
        '- 当前状态：待确认。',
        '',
        '## Scene Entities',
        '- 暂无预置 scene entity。',
        '',
        '## Onstage NPCs',
        '- 暂无。',
        '',
        '## Relevant NPCs',
        '- 暂无。',
        '',
        '## Active Threads',
        '- 主线程：等待开局建立。',
        '',
        '## Immediate Goal',
        '- 先完成开局选择并建立当前局势。',
        '',
    ]
    state_path.write_text('\n'.join(state_lines), encoding='utf-8')

    npc_count = len(system_npcs.get('items', [])) if isinstance(system_npcs.get('items', []), list) else 0
    summary_lines = [
        '# Summary',
        '',
        '## 当前状态锚点',
        '- 等待开局建立。',
        '',
        '## 活跃线程',
        '- 暂无。',
        '',
        '## 当前裁定信号',
        '- 暂无。',
        '',
        '## 最近变化',
        f'- 当前角色卡导入已完成，检测到 {npc_count} 个系统级 NPC 候选。',
        '',
        '## 未决问题',
        '- 第一条主线会从哪个开局进入。',
        '- 第一批在场人物如何进入当前局势。',
        '',
    ]
    summary_path.write_text('\n'.join(summary_lines), encoding='utf-8')


def import_card_bundle(card_json: dict, *, png_data: bytes | None = None) -> dict:
    raw_card_hash = _stable_hash(json.dumps(card_json, ensure_ascii=False, sort_keys=True))
    core = _extract_character_core(card_json)
    lorebook = _extract_lorebook(card_json)
    system_npcs = _extract_system_npcs(lorebook, card_json)
    openings = _extract_openings_payload(card_json)
    backups = _write_imported_backups(card_json, png_data, raw_card_hash=raw_card_hash)
    covers = _write_cover_assets(png_data, raw_card_hash=raw_card_hash)
    manifest = _write_manifest(card_json, lorebook, system_npcs, openings, backups, covers, raw_card_hash=raw_card_hash)
    core = _finalize_character_core(core, manifest)

    _write_json(character_core_path(), core)
    _write_json(lorebook_path(), lorebook)
    _write_json(openings_path(), openings)
    _write_json(system_npcs_path(), system_npcs)
    _write_runtime_baselines(core, lorebook, system_npcs)

    invalidate_card_hints_cache()

    return {
        'success': True,
        'name': core.get('name', '未命名角色卡'),
        'lorebook_entries_count': len(lorebook.get('entries', [])),
        'system_npcs_count': len(system_npcs.get('items', [])),
        'opening_options_count': len(openings.get('options', [])),
        'cover_saved': bool(covers.get('cover_saved')),
        'raw_card_path': backups.get('raw_card_path', ''),
        'import_manifest_path': str(import_manifest_path()),
    }


def import_card(png_data: bytes) -> dict:
    card_json = extract_card_json(png_data)
    return import_card_bundle(card_json, png_data=png_data)


def import_raw_card_file(path: str | Path) -> dict:
    card_json = load_raw_card(path)
    return import_card_bundle(card_json, png_data=None)


def import_card_to_target(source: str | Path, *, target_source_root: Path) -> dict:
    source_path = Path(source).expanduser().resolve()
    target_root = target_source_root.expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    set_character_override_root(target_root)
    try:
        if source_path.suffix.lower() == '.png':
            return import_card(source_path.read_bytes())
        if source_path.suffix.lower() == '.json':
            return import_raw_card_file(source_path)
        raise ValueError('source must be a .png or .json raw card')
    finally:
        clear_character_override_root()
