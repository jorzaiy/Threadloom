#!/usr/bin/env python3
"""本地模型调用封装（llama.cpp server / OpenAI 兼容接口）

支持通过 llama.cpp server 暴露的 OpenAI 兼容 API 调用本地模型。
"""

import json
import logging
import time
import urllib.request
from urllib.error import HTTPError, URLError

log = logging.getLogger(__name__)

_RETRY_STATUS_CODES = (429, 503)
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0


def call_local_model(config: dict, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
    """调用本地 llama.cpp server。

    Args:
        config: 包含 base_url, model, temperature, max_output_tokens 的配置字典
        system_prompt: 系统提示词
        user_prompt: 用户提示词

    Returns:
        (reply_text, usage_dict)
    """
    base_url = str(config.get('base_url') or '').rstrip('/')
    model = str(config.get('model') or '').strip()
    if not base_url:
        raise ValueError('local model base_url is required')
    if not model:
        raise ValueError('local model model is required')
    temperature = config.get('temperature', 0.3)
    max_tokens = config.get('max_output_tokens', 800)

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': temperature,
        'max_tokens': max_tokens,
    }

    headers = {
        'Content-Type': 'application/json',
    }

    url = f'{base_url}/chat/completions'
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers=headers,
        method='POST',
    )

    try:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                break
            except HTTPError as err:
                if err.code not in _RETRY_STATUS_CODES or attempt >= _MAX_RETRIES:
                    body = err.read().decode('utf-8', errors='ignore')[:500]
                    raise RuntimeError(f'Local model error {err.code}: {body}') from err
                wait = _BACKOFF_BASE ** attempt
                log.warning('本地模型 HTTP %d，第 %d 次重试，等待 %.1fs', err.code, attempt + 1, wait)
                time.sleep(wait)
    except URLError as err:
        raise RuntimeError(f'Local model unreachable at {url}: {err}') from err

    # 提取回复内容
    choice = (data.get('choices') or [{}])[0]
    message = choice.get('message', {})
    content = message.get('content', '')
    if isinstance(content, str):
        content = content.strip()

    usage = data.get('usage', {})
    return content, {
        'model': model,
        'input_tokens': usage.get('prompt_tokens', 0),
        'output_tokens': usage.get('completion_tokens', 0),
    }


def parse_json_response(text: str) -> dict:
    """从模型输出中解析 JSON，带容错处理。

    模型可能在 JSON 前后输出额外文本，尝试多种方式提取。
    """
    text = text.strip()

    # 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    if '```json' in text:
        start = text.index('```json') + 7
        end = text.index('```', start) if '```' in text[start:] else len(text)
        try:
            return json.loads(text[start:end].strip())
        except json.JSONDecodeError:
            pass

    # 尝试提取 { ... } 最外层
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass

    # 截断容错：若 JSON 被 max_tokens 截断（有 { 但无闭合 }），
    # 尝试补全闭合括号后解析
    if first_brace != -1:
        fragment = text[first_brace:]
        # 逐步尝试补全：先补 "]}" 再补 "}" 再补 '"}' 等
        for suffix in ('"}', '"]', '"]}', '"}]', ']', '}', '"]}', '"}]}'):
            try:
                return json.loads(fragment + suffix)
            except json.JSONDecodeError:
                continue

    raise ValueError(f'Failed to parse JSON from model output: {text[:200]}')
