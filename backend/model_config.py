#!/usr/bin/env python3
import json
from pathlib import Path

try:
    from .paths import APP_ROOT, SHARED_ROOT
except ImportError:
    from paths import APP_ROOT, SHARED_ROOT

CONFIG = APP_ROOT / 'config' / 'runtime.json'
PROVIDERS_CONFIG = APP_ROOT / 'config' / 'providers.json'
PROVIDERS_EXAMPLE = APP_ROOT / 'config' / 'providers.example.json'


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def load_runtime_config() -> dict:
    return read_json(CONFIG)


def resolve_source(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else (SHARED_ROOT / path_str)


def load_openclaw_models() -> dict:
    if PROVIDERS_CONFIG.exists():
        return read_json(PROVIDERS_CONFIG)
    if PROVIDERS_EXAMPLE.exists():
        return read_json(PROVIDERS_EXAMPLE)
    cfg = load_runtime_config()
    path = resolve_source(cfg.get('sources', {}).get('openclaw_models', ''))
    return read_json(path) if path.exists() else {}


def resolve_provider_model(role: str = 'narrator') -> dict:
    """解析指定角色的模型配置。

    支持两种 provider 类型：
    - 'local-gemma': 使用本地 llama.cpp server，直接从 runtime.json 读取配置
    - 其他: 使用 OpenClaw models.json 中的远程 provider
    """
    cfg = load_runtime_config()
    role_cfg = cfg.get('models', {}).get(role, {})

    # --- 本地模型路径 ---
    provider_type = role_cfg.get('provider', '')
    if provider_type == 'local-gemma':
        api_key = role_cfg.get('apiKey', role_cfg.get('api_key', ''))
        return {
            'provider_name': 'local-gemma',
            'provider': {
                'baseUrl': role_cfg.get('base_url', 'http://localhost:8080/v1'),
                'apiKey': api_key,
            },
            'model': {'id': role_cfg.get('model', 'gemma')},
            'base_url': role_cfg.get('base_url', 'http://localhost:8080/v1'),
            'temperature': role_cfg.get('temperature', 0.3),
            'max_output_tokens': role_cfg.get('max_output_tokens', 800),
            'stream': False,
            'is_local': True,
        }

    # --- 远程模型路径（OpenClaw models.json）---
    providers = load_openclaw_models().get('providers', {})

    preferred_provider = role_cfg.get('provider') or ''
    preferred_model = role_cfg.get('model') or ''

    provider_name = None
    provider = None
    if preferred_provider and preferred_provider in providers:
        provider_name = preferred_provider
        provider = providers[preferred_provider]
    elif 'custom-x-yuzh' in providers:
        provider_name = 'custom-x-yuzh'
        provider = providers[provider_name]
    elif providers:
        provider_name = next(iter(providers.keys()))
        provider = providers[provider_name]
    else:
        raise RuntimeError('No provider available from OpenClaw models.json')

    model = None
    if preferred_model:
        for item in provider.get('models', []):
            if item.get('id') == preferred_model:
                model = item
                break
    if model is None:
        for item in provider.get('models', []):
            if item.get('id') == 'gpt-5.4':
                model = item
                break
    if model is None and provider.get('models'):
        model = provider['models'][0]
    if model is None:
        raise RuntimeError(f'No model configured for provider {provider_name}')

    return {
        'provider_name': provider_name,
        'provider': provider,
        'model': model,
        'temperature': role_cfg.get('temperature', 0.9),
        'max_output_tokens': role_cfg.get('max_output_tokens', 1200),
        'stream': bool(role_cfg.get('stream', role == 'narrator')),
        'is_local': False,
    }
