#!/usr/bin/env python3
import json
import logging
import os
import re
import time
import urllib.request
from urllib.error import HTTPError

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


@_retry_on_rate_limit
def _post_json(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=_request_timeout()) as resp:
        return json.loads(resp.read().decode('utf-8'))


@_retry_on_rate_limit
def _post_stream_chat(url: str, payload: dict, headers: dict) -> tuple[str, dict, str | None]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    content_parts = []
    usage = {'prompt_tokens': 0, 'completion_tokens': 0}
    finish_reason = None
    with urllib.request.urlopen(req, timeout=_request_timeout()) as resp:
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
    return ''.join(content_parts).strip(), usage, finish_reason


def _extract_chat_content(data: dict) -> str:
    choice = (data.get('choices') or [{}])[0]
    message = choice.get('message', {})
    content = message.get('content', '')
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get('type') in {'text', 'output_text'} and isinstance(item.get('text'), str):
                    parts.append(item['text'])
        return '\n'.join(parts).strip()
    return ''


def _extract_responses_text(data: dict) -> str:
    if isinstance(data.get('output_text'), str) and data.get('output_text').strip():
        return data['output_text'].strip()
    outputs = data.get('output') or []
    parts = []
    for item in outputs:
        for content in item.get('content', []) if isinstance(item, dict) else []:
            if isinstance(content, dict) and content.get('type') == 'output_text':
                parts.append(content.get('text', ''))
    return '\n'.join(p for p in parts if p).strip()


def _looks_incomplete_reply(text: str) -> bool:
    body = str(text or '').rstrip()
    if not body:
        return True
    last_line = body.splitlines()[-1].strip()
    if not last_line:
        return True
    if len(last_line) <= 2:
        return True
    if body.endswith(('。', '！', '？', '.', '!', '?', '」', '』', '"', '”', '…')):
        return False
    if body.endswith(('，', '、', ',', ':', '：', '；', ';', '——', '—')):
        return True
    if len(body) >= 8 and re.search(r'[\u4e00-\u9fff]{2,}$', body):
        return True
    if re.search(r'[\u4e00-\u9fffA-Za-z0-9]$', body):
        return True
    return False


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
