#!/usr/bin/env python3
import json
import logging
import os
import re
import time
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError

try:
    from safe_http import UnsafeTargetError, open_safe_connection
except ImportError:
    from .safe_http import UnsafeTargetError, open_safe_connection

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 429/503 重试
# ---------------------------------------------------------------------------
_RETRY_STATUS_CODES = (429, 503)
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0


def _request_timeout() -> int:
    try:
        return max(5, int(os.environ.get('THREADLOOM_MODEL_TIMEOUT', '45') or 45))
    except Exception:
        return 45


def _retry_on_rate_limit(func):
    """装饰器：遇到 429/503 时指数退避重试。"""
    def wrapper(*args, **kwargs):
        last_err = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except HTTPError as err:
                if err.code not in _RETRY_STATUS_CODES or attempt >= _MAX_RETRIES:
                    raise
                wait = _BACKOFF_BASE ** attempt
                retry_after = err.headers.get('Retry-After') if hasattr(err, 'headers') else None
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except (ValueError, TypeError):
                        pass
                log.warning('HTTP %d，第 %d 次重试，等待 %.1fs', err.code, attempt + 1, wait)
                last_err = err
                time.sleep(wait)
        raise last_err  # type: ignore[misc]
    return wrapper


def _build_http_error(url: str, status: int, reason: str, headers, body: bytes) -> HTTPError:
    msg = Message()
    if headers is not None:
        for key, value in headers:
            msg[key] = value
    return HTTPError(url, status, reason or '', msg, BytesIO(body))


@_retry_on_rate_limit
def _post_json(url: str, payload: dict, headers: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req_headers = dict(headers)
    req_headers.setdefault('Content-Length', str(len(body)))
    try:
        conn, path = open_safe_connection(url, timeout=_request_timeout())
    except UnsafeTargetError as err:
        raise ValueError(f'model endpoint is not allowed: {err}') from err
    try:
        conn.request('POST', path, body=body, headers=req_headers)
        resp = conn.getresponse()
        resp_body = resp.read()
        if resp.status >= 400:
            raise _build_http_error(url, resp.status, resp.reason, resp.getheaders(), resp_body)
        return json.loads(resp_body.decode('utf-8'))
    finally:
        conn.close()


@_retry_on_rate_limit
def _post_stream_chat(url: str, payload: dict, headers: dict) -> tuple[str, dict, str | None]:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req_headers = dict(headers)
    req_headers.setdefault('Content-Length', str(len(body)))
    try:
        conn, path = open_safe_connection(url, timeout=_request_timeout())
    except UnsafeTargetError as err:
        raise ValueError(f'model endpoint is not allowed: {err}') from err
    content_parts = []
    usage = {'prompt_tokens': 0, 'completion_tokens': 0}
    finish_reason = None
    try:
        conn.request('POST', path, body=body, headers=req_headers)
        resp = conn.getresponse()
        if resp.status >= 400:
            raise _build_http_error(url, resp.status, resp.reason, resp.getheaders(), resp.read())
        for raw in resp:
            line = raw.decode('utf-8', errors='ignore').strip()
            if not line or not line.startswith('data:'):
                continue
            data_str = line[5:].strip()
            if data_str == '[DONE]':
                break
            try:
                data = json.loads(data_str)
            except Exception:
                continue
            choice = (data.get('choices') or [{}])[0]
            if choice.get('finish_reason'):
                finish_reason = choice.get('finish_reason')
            delta = choice.get('delta', {})
            piece = delta.get('content')
            if isinstance(piece, str):
                content_parts.append(piece)
            if data.get('usage'):
                usage = data['usage']
    finally:
        conn.close()
    return ''.join(content_parts).strip(), usage, finish_reason


def _extract_chat_content(data: dict) -> str:
    choice = (data.get('choices') or [{}])[0]
    message = choice.get('message', {})
    content = message.get('content', '')
    if isinstance(content, str):
        stripped = content.strip()
        if stripped:
            return stripped
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get('type') in {'text', 'output_text'} and isinstance(item.get('text'), str):
                    parts.append(item['text'])
        joined = '\n'.join(parts).strip()
        if joined:
            return joined
    for key in ('text', 'reasoning_content'):
        value = choice.get(key) if key == 'text' else message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _extract_responses_text(data: dict) -> str:
    output_text = data.get('output_text')
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    outputs = data.get('output') or []
    parts = []
    for item in outputs:
        for content in item.get('content', []) if isinstance(item, dict) else []:
            if isinstance(content, dict) and content.get('type') == 'output_text':
                parts.append(content.get('text', ''))
    return '\n'.join(p for p in parts if p).strip()


def narrator_reply_rejection_reason(text: str) -> str:
    body = str(text or '').rstrip()
    if not body:
        return 'empty'
    if _looks_like_degenerated_narrator_template(body):
        return 'degenerated_style_template'
    if _looks_like_excessive_micro_detail_density(body):
        return 'excessive_micro_detail_density'
    last_line = body.splitlines()[-1].strip()
    if not last_line:
        return 'empty_last_line'
    if len(last_line) <= 2:
        return 'too_short_last_line'
    if body.endswith(('。', '！', '？', '.', '!', '?', '」', '』', '"', '”', '…')):
        return ''
    if body.endswith(('，', '、', ',', ':', '：', '；', ';', '——', '—')):
        return 'dangling_punctuation'
    if len(body) >= 8 and re.search(r'[\u4e00-\u9fff]{2,}$', body):
        return 'unfinished_chinese_tail'
    if re.search(r'[\u4e00-\u9fffA-Za-z0-9]$', body):
        return 'unfinished_tail'
    return ''


def _looks_incomplete_reply(text: str) -> bool:
    return bool(narrator_reply_rejection_reason(text))


def _looks_like_degenerated_narrator_template(text: str) -> bool:
    body = str(text or '')
    if not body:
        return False
    if '不抖的方式是' in body:
        return True
    template_hits = re.findall(
        r'(?:抬|移|转|松|舔|钻|漏|沉|靠|散|走|爬|跑|跳|盯|顶|咬|攥|按|搁|蹲|站|坐|落|吸|贴|伸|收|探|灌|抖|绷|塌|张|合|放|拿|撤|滑|扇|竖|弯|偏|吞|咽|喝|看|听|说|问|答|开|闭|停|断|低|稳|碎|慢|快|轻|重)的(?:方式|方向)是',
        body,
    )
    if len(template_hits) >= 3:
        return True
    return False


MICRO_DETAIL_BODY_TERMS = (
    '嘴巴', '嘴唇', '唇', '下唇', '舌头', '舌尖', '牙膛', '喉结', '喉咙', '嗓子',
    '眼珠', '眼睛', '眼尾', '瞳孔', '目光', '视线', '鼻翼', '鼻尖', '耳朵', '左耳', '右耳',
    '手指', '指尖', '五指', '掌心', '手腕', '肩膀', '肩胛骨', '背脊', '脊背', '膝盖',
    '布料', '衣料', '领口', '褶子', '潮印子',
)
MICRO_DETAIL_ACTION_TERMS = (
    '张开', '合上', '抖', '动了一下', '动了半寸', '移到', '移回', '转了半寸', '顶了一下',
    '舔了一下', '咽了口', '滚了一下', '塌了一分', '直了一分', '绷着', '绷直', '收紧',
    '松开', '攥了一下', '按了一下', '扫了一下', '折了折', '扇了', '竖着', '压低', '压着',
    '停了两息', '停了一息', '短的', '轻的', '碎到', '慢到', '小到', '半寸', '一分', '一寸',
)


def _micro_detail_sentence(sentence: str) -> bool:
    clean = re.sub(r'\s+', '', str(sentence or ''))
    if not clean:
        return False
    return any(term in clean for term in MICRO_DETAIL_BODY_TERMS) and any(term in clean for term in MICRO_DETAIL_ACTION_TERMS)


def _looks_like_excessive_micro_detail_density(text: str) -> bool:
    body = str(text or '')
    sentences = [item for item in re.split(r'(?<=[。！？!?])', body) if item.strip()]
    if len(sentences) < 8:
        return False
    detail_flags = [_micro_detail_sentence(sentence) for sentence in sentences]
    detail_count = sum(1 for item in detail_flags if item)
    if detail_count < 6:
        return False
    longest_run = 0
    current_run = 0
    for is_detail in detail_flags:
        if is_detail:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    ratio = detail_count / len(sentences)
    if longest_run >= 5:
        return True
    return detail_count >= 8 and ratio >= 0.45


def looks_incomplete_reply(text: str) -> bool:
    return _looks_incomplete_reply(text)


def call_model(config: dict, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
    provider = config['provider']
    model = config['model']
    base_url = provider['baseUrl'].rstrip('/')
    api_key = provider.get('apiKey', '')
    api_kind = provider.get('api') or model.get('api') or 'openai-completions'

    headers = {
        'Content-Type': 'application/json',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    if api_kind == 'openai-responses':
        data = _post_json(
            f'{base_url}/responses',
            {
                'model': model['id'],
                'input': [
                    {'role': 'system', 'content': [{'type': 'input_text', 'text': system_prompt}]},
                    {'role': 'user', 'content': [{'type': 'input_text', 'text': user_prompt}]},
                ],
                'temperature': config['temperature'],
                'max_output_tokens': config['max_output_tokens'],
            },
            headers,
        )
        reply = _extract_responses_text(data)
        usage = data.get('usage', {})
        return reply, {
            'model': model['id'],
            'input_tokens': usage.get('input_tokens', 0),
            'output_tokens': usage.get('output_tokens', 0),
            'finish_reason': 'stop',
        }

    payload = {
        'model': model['id'],
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': config['temperature'],
        'max_tokens': config['max_output_tokens'],
    }
    response_format = config.get('response_format')
    if response_format:
        payload['response_format'] = response_format
    if config.get('stream'):
        payload['stream'] = True
        try:
            reply, usage, finish_reason = _post_stream_chat(f'{base_url}/chat/completions', payload, headers)
            if finish_reason is None and _looks_incomplete_reply(reply):
                payload.pop('stream', None)
                data = _post_json(f'{base_url}/chat/completions', payload, headers)
                reply = _extract_chat_content(data)
                usage = data.get('usage', {})
                choice = (data.get('choices') or [{}])[0]
                finish_reason = choice.get('finish_reason')
        except HTTPError as err:
            if err.code != 403:
                raise
            payload.pop('stream', None)
            data = _post_json(f'{base_url}/chat/completions', payload, headers)
            reply = _extract_chat_content(data)
            usage = data.get('usage', {})
            choice = (data.get('choices') or [{}])[0]
            finish_reason = choice.get('finish_reason')
    else:
        data = _post_json(f'{base_url}/chat/completions', payload, headers)
        reply = _extract_chat_content(data)
        usage = data.get('usage', {})
        choice = (data.get('choices') or [{}])[0]
        finish_reason = choice.get('finish_reason')
    return reply, {
        'model': model['id'],
        'input_tokens': usage.get('prompt_tokens', 0),
        'output_tokens': usage.get('completion_tokens', 0),
        'finish_reason': finish_reason,
    }
