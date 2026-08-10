"""Persona distillation: plain-text call must not inherit the role's JSON contract.

Regression for a silent 100% failure: `state_keeper_candidate` carries
response_format=json_object (its other callers all emit JSON), but PERSONA_SYSTEM
asks for one bare Chinese line and never says "json" — providers answer 400, the
bare `except` swallowed it, and no NPC ever got a persona. Personas are the only
exemption from the important-roster inactivity fade, so the roster then eroded.
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

persona_distiller = importlib.import_module('persona_distiller')

OBSERVATIONS = ['招呼客人殷勤，连声应好', '手脚麻利，转身就去备茶']


@pytest.fixture
def captured_call(monkeypatch):
    """Stub the model layer; record the config the persona call actually sends."""
    seen: dict = {}

    def fake_runtime(role):
        return {'role': role, 'provider': 'llm', 'model_role': role, 'config': {}}

    def fake_resolve(model_role):
        # Mirrors STATE_KEEPER_CANDIDATE_DEFAULT: the role is pinned to JSON.
        return {
            'provider': {'baseUrl': 'https://example.invalid/v1', 'apiKey': 'k'},
            'model': {'id': 'keeper-tier'},
            'temperature': 0.0,
            'response_format': {'type': 'json_object'},
        }

    def fake_call_model(cfg, system_prompt, user_prompt):
        seen['cfg'] = cfg
        seen['system'] = system_prompt
        seen['user'] = user_prompt
        return '殷勤周到，手脚麻利，干活利落。', {}

    monkeypatch.setattr(persona_distiller, 'get_role_runtime', fake_runtime)
    monkeypatch.setattr(persona_distiller, 'resolve_provider_model', fake_resolve)
    monkeypatch.setattr(persona_distiller, 'call_model', fake_call_model)
    return seen


def test_persona_prompt_never_says_json():
    """Why json_object is illegal here — keep the two facts adjacent."""
    assert 'json' not in persona_distiller.PERSONA_SYSTEM.lower()


def test_persona_call_drops_json_response_format(captured_call):
    persona_distiller.distill_persona('小二', OBSERVATIONS)

    assert 'response_format' not in captured_call['cfg']
    # The rest of the role config must survive untouched.
    assert captured_call['cfg']['model']['id'] == 'keeper-tier'


def test_persona_call_does_not_mutate_shared_role_config(captured_call, monkeypatch):
    """Popping must hit a copy — the resolved role config is reused elsewhere."""
    shared = {
        'provider': {'baseUrl': 'https://example.invalid/v1', 'apiKey': 'k'},
        'model': {'id': 'keeper-tier'},
        'response_format': {'type': 'json_object'},
    }
    monkeypatch.setattr(persona_distiller, 'resolve_provider_model', lambda _r: shared)

    persona_distiller.distill_persona('小二', OBSERVATIONS)

    assert shared['response_format'] == {'type': 'json_object'}


def test_distill_persona_returns_clean_line(captured_call):
    assert persona_distiller.distill_persona('小二', OBSERVATIONS) == '殷勤周到，手脚麻利，干活利落。'


def test_call_failure_is_logged_not_swallowed(captured_call, monkeypatch, caplog):
    def boom(_cfg, _system, _user):
        raise RuntimeError("HTTP Error 400: Bad Request")

    monkeypatch.setattr(persona_distiller, 'call_model', boom)

    with caplog.at_level(logging.WARNING, logger='persona_distiller'):
        assert persona_distiller.distill_persona('小二', OBSERVATIONS) == ''

    assert any('PERSONA_DISTILL_CALL_FAILED' in r.message for r in caplog.records)


def test_too_few_observations_skips_the_call(captured_call):
    assert persona_distiller.distill_persona('刘婆子', ['只出场一次']) == ''
    assert 'cfg' not in captured_call
