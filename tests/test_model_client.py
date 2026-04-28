#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import model_client


def _base_config(**overrides):
    config = {
        'provider': {'baseUrl': 'https://example.test/v1', 'apiKey': ''},
        'model': {'id': 'test-model'},
        'temperature': 0.1,
        'max_output_tokens': 20,
        'stream': False,
    }
    config.update(overrides)
    return config


def test_call_model_passes_response_format(monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers):
        captured['payload'] = payload
        return {
            'choices': [{'message': {'content': '{"ok": true}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 2},
        }

    monkeypatch.setattr(model_client, '_post_json', fake_post_json)

    reply, usage = model_client.call_model(
        _base_config(response_format={'type': 'json_object'}),
        'system',
        'user',
    )

    assert reply == '{"ok": true}'
    assert usage['finish_reason'] == 'stop'
    assert captured['payload']['response_format'] == {'type': 'json_object'}


def test_extract_chat_content_uses_reasoning_content_when_content_empty():
    data = {
        'choices': [
            {
                'message': {
                    'content': '',
                    'reasoning_content': '{"carryover_signals": []}',
                }
            }
        ]
    }

    assert model_client._extract_chat_content(data) == '{"carryover_signals": []}'
