#!/usr/bin/env python3
import json
import urllib.request
from urllib.error import HTTPError


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode('utf-8'))


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
    with urllib.request.urlopen(req, timeout=120) as resp:
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
