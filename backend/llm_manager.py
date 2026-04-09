#!/usr/bin/env python3
from __future__ import annotations

try:
    from .model_client import call_model
    from .model_config import load_runtime_config, resolve_provider_model
except ImportError:
    from model_client import call_model
    from model_config import load_runtime_config, resolve_provider_model


def get_role_runtime(role: str) -> dict:
    cfg = load_runtime_config()
    roles = cfg.get('roles', {}) or {}
    role_cfg = roles.get(role, {}) or {}
    provider = role_cfg.get('provider', 'llm')
    model_role = role_cfg.get('model_role', role)
    return {
        'role': role,
        'provider': provider,
        'model_role': model_role,
        'config': role_cfg,
    }


def call_role_llm(role: str, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
    runtime = get_role_runtime(role)
    if runtime['provider'] != 'llm':
        raise RuntimeError(f'role {role} is not configured for llm provider')
    model_cfg = resolve_provider_model(runtime['model_role'])
    reply, usage = call_model(model_cfg, system_prompt, user_prompt)
    usage['role'] = role
    usage['model_role'] = runtime['model_role']
    return reply, usage
