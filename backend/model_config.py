#!/usr/bin/env python3
import copy
import json
import os
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

try:
    from .paths import APP_ROOT, resolve_layered_source, user_config_root
except ImportError:
    from paths import APP_ROOT, resolve_layered_source, user_config_root

GLOBAL_RUNTIME_CONFIG = APP_ROOT / 'config' / 'runtime.json'
GLOBAL_RUNTIME_EXAMPLE = APP_ROOT / 'config' / 'runtime.example.json'
GLOBAL_PROVIDERS_CONFIG = APP_ROOT / 'config' / 'providers.json'
GLOBAL_PROVIDERS_EXAMPLE = APP_ROOT / 'config' / 'providers.example.json'
USER_SITE_CONFIG = user_config_root() / 'site.json'
USER_MODEL_RUNTIME_CONFIG = user_config_root() / 'model-runtime.json'
LEGACY_USER_PROVIDERS_CONFIG = user_config_root() / 'providers.json'
SITE_PROVIDER_NAME = 'site'
SUPPORTED_PROVIDER_APIS = [
    {'value': 'openai-completions', 'label': 'OpenAI Chat Completions'},
    {'value': 'openai-responses', 'label': 'OpenAI Responses'},
]
SUPPORTED_PROVIDER_API_VALUES = {item['value'] for item in SUPPORTED_PROVIDER_APIS}
DEFAULT_SITE = {
    'baseUrl': '',
    'apiKey': '',
    'api': 'openai-completions',
    'models': [],
}
DEFAULT_NARRATOR = {
    'model': '',
}
DEFAULT_STATE_KEEPER = {
    'model': '',
}
DEFAULT_ADVANCED_MODELS = {
    'turn_analyzer': {
        'provider': 'openai-compatible',
        'model': 'heuristic-or-llm',
        'temperature': 0.2,
        'max_output_tokens': 700,
        'stream': False,
    },
    'arbiter': {
        'provider': 'openai-compatible',
        'model': '',
        'temperature': 0.2,
        'max_output_tokens': 800,
        'stream': False,
    },
    'state_keeper_candidate': {
        'provider': SITE_PROVIDER_NAME,
        'model': '',
        'temperature': 0.0,
        'max_output_tokens': 280,
        'stream': False,
    },
}
SYSTEM_ROLE_DEFAULTS = {
    'narrator': {
        'provider': 'llm',
        'model_role': 'narrator',
    },
    'turn_analyzer': {
        'provider': 'heuristic',
        'model_role': 'turn_analyzer',
    },
    'state_keeper': {
        'provider': 'llm',
        'model_role': 'state_keeper',
    },
    'state_keeper_candidate': {
        'provider': 'llm',
        'model_role': 'state_keeper_candidate',
    },
}
SYSTEM_MODEL_DEFAULTS = copy.deepcopy(DEFAULT_ADVANCED_MODELS)


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _resolve_api_key(value: str) -> str:
    text = str(value or '').strip()
    if text.startswith('$'):
        return os.environ.get(text[1:], '')
    if text.startswith('env:'):
        return os.environ.get(text[4:], '')
    return text


def _normalize_base_url(value: str, *, required: bool = True) -> str:
    text = str(value or '').strip().rstrip('/')
    if not text:
        if required:
            raise ValueError('baseUrl is required')
        return ''
    if not (text.startswith('http://') or text.startswith('https://')):
        raise ValueError('baseUrl must start with http:// or https://')
    return text


def _normalize_api(value: str) -> str:
    text = str(value or '').strip()
    if text not in SUPPORTED_PROVIDER_API_VALUES:
        raise ValueError('unsupported provider api type')
    return text


def _normalize_models(items, api_type: str) -> list[dict]:
    rows = items if isinstance(items, list) else []
    out: list[dict] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get('id', '') or '').strip()
        if not model_id or model_id in seen:
            continue
        name = str(item.get('name', '') or model_id).strip() or model_id
        out.append({
            'id': model_id,
            'name': name,
            'api': api_type,
            'reasoning': bool(item.get('reasoning', False)),
            'input': item.get('input', ['text']) if isinstance(item.get('input', ['text']), list) else ['text'],
        })
        seen.add(model_id)
    return out


def _global_runtime_store() -> dict:
    if GLOBAL_RUNTIME_CONFIG.exists():
        data = read_json(GLOBAL_RUNTIME_CONFIG)
    elif GLOBAL_RUNTIME_EXAMPLE.exists():
        data = read_json(GLOBAL_RUNTIME_EXAMPLE)
    else:
        data = {}
    return data if isinstance(data, dict) else {}


def _global_provider_store() -> dict:
    if GLOBAL_PROVIDERS_CONFIG.exists():
        data = read_json(GLOBAL_PROVIDERS_CONFIG)
    elif GLOBAL_PROVIDERS_EXAMPLE.exists():
        data = read_json(GLOBAL_PROVIDERS_EXAMPLE)
    else:
        data = {}
    return data if isinstance(data, dict) else {}


def _pick_legacy_site(store: dict) -> dict:
    if not isinstance(store, dict):
        return copy.deepcopy(DEFAULT_SITE)
    if isinstance(store.get('site'), dict):
        site = dict(DEFAULT_SITE)
        site.update(store['site'])
        api_type = str(site.get('api', 'openai-completions') or 'openai-completions')
        site['api'] = api_type if api_type in SUPPORTED_PROVIDER_API_VALUES else 'openai-completions'
        site['models'] = _normalize_models(site.get('models', []), site['api'])
        return site
    providers = store.get('providers', {})
    if not isinstance(providers, dict) or not providers:
        return copy.deepcopy(DEFAULT_SITE)
    preferred = providers.get('custom-x-yuzh')
    if not isinstance(preferred, dict):
        preferred = next((item for item in providers.values() if isinstance(item, dict)), {})
    site = {
        'baseUrl': str(preferred.get('baseUrl', '') or '').strip(),
        'apiKey': str(preferred.get('apiKey', '') or '').strip(),
        'api': str(preferred.get('api', 'openai-completions') or 'openai-completions').strip() or 'openai-completions',
        'models': _normalize_models(preferred.get('models', []), str(preferred.get('api', 'openai-completions') or 'openai-completions').strip() or 'openai-completions'),
    }
    if site['api'] not in SUPPORTED_PROVIDER_API_VALUES:
        site['api'] = 'openai-completions'
    return site


def _load_site_store_raw() -> dict:
    if USER_SITE_CONFIG.exists():
        data = read_json(USER_SITE_CONFIG)
        if isinstance(data, dict) and isinstance(data.get('site'), dict):
            return data
    legacy_user = read_json(LEGACY_USER_PROVIDERS_CONFIG) if LEGACY_USER_PROVIDERS_CONFIG.exists() else {}
    legacy_global = _global_provider_store()
    seed = {'site': _pick_legacy_site(legacy_user if legacy_user else legacy_global)}
    write_json(USER_SITE_CONFIG, seed)
    return seed


def load_site_store() -> dict:
    data = _load_site_store_raw()
    site = _pick_legacy_site(data)
    normalized = {'site': site}
    if data != normalized:
        write_json(USER_SITE_CONFIG, normalized)
    return normalized


def _available_site_models(site: dict) -> list[str]:
    return [item.get('id') for item in _normalize_models(site.get('models', []), site.get('api', 'openai-completions')) if item.get('id')]


def _legacy_model_source() -> dict:
    if USER_MODEL_RUNTIME_CONFIG.exists():
        data = read_json(USER_MODEL_RUNTIME_CONFIG)
        if isinstance(data, dict):
            return data
    return _global_runtime_store()


def _pick_model_with_fallback(preferred: list[str], available: list[str]) -> str:
    for value in preferred:
        text = str(value or '').strip()
        if not text:
            continue
        if not available or text in available:
            return text
    return available[0] if available else ''


def _slim_runtime_from_legacy(source: dict, site: dict) -> dict:
    available = _available_site_models(site)
    if isinstance(source.get('narrator'), dict) and isinstance(source.get('state_keeper'), dict):
        narrator = dict(DEFAULT_NARRATOR)
        state_keeper = dict(DEFAULT_STATE_KEEPER)
        narrator['model'] = _pick_model_with_fallback([
            source.get('narrator', {}).get('model'),
            narrator.get('model'),
        ], available)
        state_keeper['model'] = _pick_model_with_fallback([
            source.get('state_keeper', {}).get('model'),
            state_keeper.get('model'),
            narrator['model'],
        ], available)
        payload = {
            'version': 1,
            'narrator': narrator,
            'state_keeper': state_keeper,
        }
        if isinstance(source.get('advanced_models'), dict):
            payload['advanced_models'] = copy.deepcopy(source['advanced_models'])
        return payload

    legacy_models = source.get('models', {}) if isinstance(source.get('models', {}), dict) else {}
    narrator_legacy = legacy_models.get('narrator', {}) if isinstance(legacy_models.get('narrator', {}), dict) else {}
    keeper_legacy = legacy_models.get('state_keeper', {}) if isinstance(legacy_models.get('state_keeper', {}), dict) else {}
    candidate_legacy = legacy_models.get('state_keeper_candidate', {}) if isinstance(legacy_models.get('state_keeper_candidate', {}), dict) else {}

    narrator = dict(DEFAULT_NARRATOR)
    narrator['model'] = _pick_model_with_fallback([
        narrator_legacy.get('model'),
        candidate_legacy.get('model'),
        keeper_legacy.get('model'),
    ], available)

    state_keeper = dict(DEFAULT_STATE_KEEPER)
    state_keeper['model'] = _pick_model_with_fallback([
        candidate_legacy.get('model'),
        keeper_legacy.get('model') if str(keeper_legacy.get('provider', '') or '').strip() not in {'local-gemma'} else '',
        narrator['model'],
    ], available)
    payload = {
        'version': 1,
        'narrator': narrator,
        'state_keeper': state_keeper,
    }
    payload['advanced_models'] = copy.deepcopy(DEFAULT_ADVANCED_MODELS)
    return payload


def load_user_model_store() -> dict:
    site = load_site_store()['site']
    current = read_json(USER_MODEL_RUNTIME_CONFIG) if USER_MODEL_RUNTIME_CONFIG.exists() else {}
    if isinstance(current.get('narrator'), dict) and isinstance(current.get('state_keeper'), dict):
        available = _available_site_models(site)
        slim = {
            'version': 1,
            'narrator': {
                'model': _pick_model_with_fallback([current.get('narrator', {}).get('model')], available),
            },
            'state_keeper': {
                'model': _pick_model_with_fallback([current.get('state_keeper', {}).get('model')], available),
            },
        }
        if isinstance(current.get('advanced_models'), dict):
            slim['advanced_models'] = copy.deepcopy(current['advanced_models'])
    else:
        source = _legacy_model_source()
        slim = _slim_runtime_from_legacy(source if isinstance(source, dict) else {}, site)
        if isinstance(current.get('advanced_models'), dict):
            slim['advanced_models'] = copy.deepcopy(current['advanced_models'])
    if current != slim:
        write_json(USER_MODEL_RUNTIME_CONFIG, slim)
    return slim


def _site_status(site: dict) -> tuple[str, str]:
    base_url = str(site.get('baseUrl', '') or '').strip()
    api_type = str(site.get('api', '') or '').strip()
    key_meta = api_key_meta(str(site.get('apiKey', '') or ''))
    models = _normalize_models(site.get('models', []), api_type or 'openai-completions')
    if not base_url or api_type not in SUPPORTED_PROVIDER_API_VALUES:
        return 'invalid', '配置无效'
    if key_meta['reference'] and not key_meta['resolved']:
        return 'env-missing', '环境变量未解析'
    if not key_meta['configured']:
        return 'no-key', '未设置 API Key'
    if not models:
        return 'no-models', '还没获取模型'
    return 'ready', '已就绪'


def api_key_meta(value: str) -> dict:
    text = str(value or '').strip()
    reference = text if text.startswith('$') or text.startswith('env:') else None
    resolved = _resolve_api_key(text) if text else ''
    source = resolved or ('' if reference else text)
    masked = f'****{source[-4:]}' if source else ''
    return {
        'configured': bool(text),
        'masked': masked,
        'reference': reference,
        'resolved': bool(resolved) if reference else bool(text),
    }


def get_site_config_snapshot() -> dict:
    site = load_site_store()['site']
    status, status_label = _site_status(site)
    key_meta = api_key_meta(str(site.get('apiKey', '') or ''))
    models = _normalize_models(site.get('models', []), site.get('api', 'openai-completions'))
    return {
        'base_url': str(site.get('baseUrl', '') or '').strip(),
        'api': str(site.get('api', 'openai-completions') or 'openai-completions').strip() or 'openai-completions',
        'api_key_masked': key_meta['masked'],
        'api_key_reference': key_meta['reference'],
        'api_key_configured': key_meta['configured'],
        'status': status,
        'status_label': status_label,
        'model_count': len(models),
        'models': [
            {
                'id': item.get('id'),
                'name': item.get('name') or item.get('id'),
            }
            for item in models
        ],
    }


def update_site_config(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError('site payload must be an object')
    store = load_site_store()
    site = store['site']
    site['baseUrl'] = _normalize_base_url(payload.get('baseUrl', payload.get('base_url', site.get('baseUrl', ''))))
    site['api'] = _normalize_api(payload.get('api', site.get('api', 'openai-completions')))
    replace_api_key = bool(payload.get('replace_api_key'))
    api_key_value = payload.get('apiKey', payload.get('api_key'))
    if replace_api_key:
        site['apiKey'] = str(api_key_value or '').strip()
    elif api_key_value not in (None, ''):
        site['apiKey'] = str(api_key_value).strip()
    site['models'] = _normalize_models(site.get('models', []), site['api'])
    write_json(USER_SITE_CONFIG, {'site': site})
    return get_site_config_snapshot()


def _extract_discovered_models(data: dict, api_type: str) -> list[dict]:
    raw_items = data.get('data', []) if isinstance(data.get('data', []), list) else []
    out = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get('id', '') or '').strip()
        if not model_id:
            continue
        out.append({
            'id': model_id,
            'name': str(item.get('name', '') or model_id).strip() or model_id,
            'api': api_type,
            'input': ['text'],
        })
    return _normalize_models(out, api_type)


def discover_site_models() -> dict:
    store = load_site_store()
    site = store['site']
    base_url = _normalize_base_url(site.get('baseUrl', ''), required=True)
    api_type = _normalize_api(site.get('api', 'openai-completions'))
    headers = {'Content-Type': 'application/json'}
    resolved_key = _resolve_api_key(site.get('apiKey', ''))
    if resolved_key:
        headers['Authorization'] = f'Bearer {resolved_key}'
    req = urllib.request.Request(f'{base_url}/models', headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except HTTPError as err:
        body = err.read().decode('utf-8', errors='ignore')[:300]
        raise ValueError(f'provider model discovery failed: http {err.code} {body}'.strip()) from err
    except URLError as err:
        raise ValueError(f'provider model discovery failed: {err.reason}') from err
    except Exception as err:
        raise ValueError(f'provider model discovery failed: {err}') from err
    site['models'] = _extract_discovered_models(data if isinstance(data, dict) else {}, api_type)
    write_json(USER_SITE_CONFIG, {'site': site})
    model_store = load_user_model_store()
    available = _available_site_models(site)
    changed = False
    for role_name in ('narrator', 'state_keeper'):
        current_model = model_store[role_name].get('model', '')
        if current_model not in available:
            fallback = _pick_model_with_fallback([current_model], available)
            model_store[role_name]['model'] = fallback
            changed = True
    if changed:
        write_json(USER_MODEL_RUNTIME_CONFIG, model_store)
    snapshot = get_site_config_snapshot()
    snapshot['discovered_models'] = snapshot['models']
    return snapshot


def get_model_config_snapshot() -> dict:
    store = load_user_model_store()
    return {
        'site': get_site_config_snapshot(),
        'narrator': copy.deepcopy(store.get('narrator', DEFAULT_NARRATOR)),
        'state_keeper': copy.deepcopy(store.get('state_keeper', DEFAULT_STATE_KEEPER)),
        'advanced_models': copy.deepcopy(store.get('advanced_models', DEFAULT_ADVANCED_MODELS)),
    }


def update_model_config(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError('model config payload must be an object')
    site = load_site_store()['site']
    available = _available_site_models(site)
    if not available:
        raise ValueError('site models are empty; fetch models first')
    store = load_user_model_store()
    if 'narrator' in payload:
        narrator = payload.get('narrator')
        if not isinstance(narrator, dict):
            raise ValueError('narrator config must be an object')
        model_id = str(narrator.get('model', '') or '').strip()
        if model_id not in available:
            raise ValueError('narrator model not found in fetched site models')
        store['narrator'] = {
            'model': model_id,
        }
    if 'state_keeper' in payload:
        state_keeper = payload.get('state_keeper')
        if not isinstance(state_keeper, dict):
            raise ValueError('state_keeper config must be an object')
        model_id = str(state_keeper.get('model', '') or '').strip()
        if model_id not in available:
            raise ValueError('state_keeper model not found in fetched site models')
        store['state_keeper'] = {
            'model': model_id,
        }
    write_json(USER_MODEL_RUNTIME_CONFIG, store)
    return get_model_config_snapshot()


def load_runtime_config() -> dict:
    global_cfg = copy.deepcopy(_global_runtime_store())
    user_store = load_user_model_store()
    narrator = user_store.get('narrator', DEFAULT_NARRATOR)
    state_keeper = user_store.get('state_keeper', DEFAULT_STATE_KEEPER)
    models = copy.deepcopy(SYSTEM_MODEL_DEFAULTS)
    advanced = copy.deepcopy(user_store.get('advanced_models', DEFAULT_ADVANCED_MODELS))
    narrator_defaults = _global_runtime_store().get('model_defaults', {}).get('narrator', {}) if isinstance(_global_runtime_store().get('model_defaults', {}), dict) else {}
    state_keeper_defaults = _global_runtime_store().get('model_defaults', {}).get('state_keeper', {}) if isinstance(_global_runtime_store().get('model_defaults', {}), dict) else {}
    models['narrator'] = {
        'provider': SITE_PROVIDER_NAME,
        'model': narrator.get('model', ''),
        'temperature': float(narrator_defaults.get('temperature', 0.9) or 0.9),
        'max_output_tokens': int(narrator_defaults.get('max_output_tokens', 1200) or 1200),
        'stream': bool(narrator_defaults.get('stream', True)),
    }
    models['state_keeper'] = {
        'provider': SITE_PROVIDER_NAME,
        'model': state_keeper.get('model', ''),
        'temperature': float(state_keeper_defaults.get('temperature', 0.1) or 0.1),
        'max_output_tokens': int(state_keeper_defaults.get('max_output_tokens', 480) or 480),
        'stream': bool(state_keeper_defaults.get('stream', False)),
    }
    models['state_keeper_candidate'] = {
        **copy.deepcopy(advanced.get('state_keeper_candidate', DEFAULT_ADVANCED_MODELS['state_keeper_candidate'])),
    }
    if not models['state_keeper_candidate'].get('model'):
        models['state_keeper_candidate']['model'] = state_keeper.get('model', '') or narrator.get('model', '')
    for role_name in ('turn_analyzer', 'arbiter'):
        models[role_name] = {
            **copy.deepcopy(DEFAULT_ADVANCED_MODELS[role_name]),
            **copy.deepcopy(advanced.get(role_name, {})),
        }
    global_cfg['models'] = models
    global_cfg['roles'] = copy.deepcopy(SYSTEM_ROLE_DEFAULTS)
    return global_cfg


def load_openclaw_models() -> dict:
    site = load_site_store()['site']
    provider = {
        'baseUrl': site.get('baseUrl', ''),
        'apiKey': site.get('apiKey', ''),
        'api': site.get('api', 'openai-completions'),
        'models': _normalize_models(site.get('models', []), site.get('api', 'openai-completions')),
    }
    return {'providers': {SITE_PROVIDER_NAME: provider}}


def resolve_source(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else resolve_layered_source(path_str)


def resolve_provider_model(role: str = 'narrator') -> dict:
    cfg = load_runtime_config()
    role_cfg = cfg.get('models', {}).get(role, {})
    override_env = f'THREADLOOM_OVERRIDE_{role.upper()}_MODEL'
    override_model = str(os.environ.get(override_env, '') or '').strip()
    override_max_tokens_env = f'THREADLOOM_OVERRIDE_{role.upper()}_MAX_TOKENS'
    override_stream_env = f'THREADLOOM_OVERRIDE_{role.upper()}_STREAM'
    providers = load_openclaw_models().get('providers', {})
    provider_name = role_cfg.get('provider') or SITE_PROVIDER_NAME
    provider = providers.get(provider_name)
    if not provider:
        raise RuntimeError('No site configured for current user')
    preferred_model = override_model or role_cfg.get('model') or ''
    models = _normalize_models(provider.get('models', []), provider.get('api', 'openai-completions'))
    model = next((item for item in models if item.get('id') == preferred_model), None)
    if model is None and models:
        model = models[0]
    if model is None:
        model = {'id': preferred_model} if preferred_model else None
    if model is None:
        raise RuntimeError(f'No model configured for role {role}')
    resolved_provider = dict(provider)
    resolved_provider['apiKey'] = _resolve_api_key(resolved_provider.get('apiKey', ''))
    max_output_tokens = role_cfg.get('max_output_tokens', 1200)
    override_max_tokens = str(os.environ.get(override_max_tokens_env, '') or '').strip()
    if override_max_tokens:
        try:
            max_output_tokens = int(override_max_tokens)
        except Exception:
            pass
    stream = bool(role_cfg.get('stream', role == 'narrator'))
    override_stream = str(os.environ.get(override_stream_env, '') or '').strip().lower()
    if override_stream in {'0', 'false', 'no'}:
        stream = False
    elif override_stream in {'1', 'true', 'yes'}:
        stream = True
    return {
        'provider_name': provider_name,
        'provider': resolved_provider,
        'model': model,
        'temperature': role_cfg.get('temperature', 0.9),
        'max_output_tokens': max_output_tokens,
        'stream': stream,
        'is_local': False,
    }


# Compatibility wrappers for older callers/routes.
def list_provider_configs() -> dict:
    snapshot = get_site_config_snapshot()
    return {
        'providers': [
            {
                'name': SITE_PROVIDER_NAME,
                'base_url': snapshot['base_url'],
                'api': snapshot['api'],
                'api_key_masked': snapshot['api_key_masked'],
                'api_key_reference': snapshot['api_key_reference'],
                'api_key_configured': snapshot['api_key_configured'],
                'status': snapshot['status'],
                'status_label': snapshot['status_label'],
                'model_count': snapshot['model_count'],
                'models': snapshot['models'],
            }
        ],
        'supported_api_types': copy.deepcopy(SUPPORTED_PROVIDER_APIS),
    }


def upsert_provider_config(payload: dict) -> dict:
    update_site_config(payload)
    return {
        'provider': list_provider_configs()['providers'][0],
        'renamed_roles': [],
        'providers': list_provider_configs()['providers'],
    }


def delete_provider_config(name: str) -> dict:
    raise ValueError('site deletion is not supported')


def discover_provider_models(name: str) -> dict:
    return discover_site_models()
