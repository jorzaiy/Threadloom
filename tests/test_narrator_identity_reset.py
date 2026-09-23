#!/usr/bin/env python3
"""Tests for the narrator_identity_reset (世界模拟引擎) block injection.

Verifies:
(a) when narrator_identity_reset is in context, system_prompt starts with 【世界模拟引擎】block;
(b) when absent, system_prompt does not contain it (backward compat);
(c) prompt_block_stats correctly recognizes the new block.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

from narrator_input import build_narrator_input, prompt_block_stats  # noqa: E402


_IDENTITY_RESET_TEXT = (
    "You are not an AI assistant. You are a World Simulation Engine.\n"
    "Judgment priority: physics > social norms > NPC personality > player expectations.\n"
    "The user is a player whose input is an action attempt, not a command."
)


def test_identity_reset_block_present_when_context_has_it():
    """When context contains narrator_identity_reset, system_prompt starts with 【世界模拟引擎】."""
    system_prompt, _user_prompt = build_narrator_input(
        {
            'narrator_identity_reset': _IDENTITY_RESET_TEXT,
            'runtime_rules': 'runtime rules text',
            'scene_facts': {},
            'active_preset': {},
        },
        '走进酒馆',
    )

    assert system_prompt.startswith('【世界模拟引擎】')
    assert 'World Simulation Engine' in system_prompt
    assert 'physics > social norms' in system_prompt
    # runtime_rules should still be present, after the identity reset block
    assert 'runtime rules text' in system_prompt


def test_identity_reset_block_absent_when_context_lacks_it():
    """When context does NOT contain narrator_identity_reset, system_prompt
    does not have the 【世界模拟引擎】block — backward compatibility."""
    system_prompt, _user_prompt = build_narrator_input(
        {
            'runtime_rules': 'runtime rules text',
            'scene_facts': {},
            'active_preset': {},
        },
        '走进酒馆',
    )

    assert '【世界模拟引擎】' not in system_prompt
    assert 'World Simulation Engine' not in system_prompt
    # runtime_rules should still be present
    assert 'runtime rules text' in system_prompt


def test_identity_reset_block_empty_string_does_not_inject():
    """Empty string for narrator_identity_reset should not inject the block."""
    system_prompt, _user_prompt = build_narrator_input(
        {
            'narrator_identity_reset': '',
            'runtime_rules': 'runtime rules text',
            'scene_facts': {},
            'active_preset': {},
        },
        '走进酒馆',
    )

    assert '【世界模拟引擎】' not in system_prompt


def test_identity_reset_block_recognized_by_prompt_block_stats():
    """prompt_block_stats should recognize 【世界模拟引擎】as a valid block."""
    system_prompt, _user_prompt = build_narrator_input(
        {
            'narrator_identity_reset': _IDENTITY_RESET_TEXT,
            'runtime_rules': 'runtime rules text',
            'scene_facts': {},
            'active_preset': {},
        },
        '走进酒馆',
    )

    stats = prompt_block_stats(system_prompt)
    labels = [s['label'] for s in stats]

    assert '【世界模拟引擎】' in labels
    # It should be the first block
    assert labels[0] == '【世界模拟引擎】'
    # The block should have non-zero char count
    sim_block = next(s for s in stats if s['label'] == '【世界模拟引擎】')
    assert sim_block['chars'] > 0


def test_identity_reset_block_precedes_runtime_rules():
    """The identity reset block must appear before runtime_rules in the prompt."""
    system_prompt, _user_prompt = build_narrator_input(
        {
            'narrator_identity_reset': _IDENTITY_RESET_TEXT,
            'runtime_rules': 'RUNTIME_MARKER',
            'scene_facts': {},
            'active_preset': {},
        },
        '走进酒馆',
    )

    sim_pos = system_prompt.find('【世界模拟引擎】')
    runtime_pos = system_prompt.find('RUNTIME_MARKER')

    assert sim_pos != -1
    assert runtime_pos != -1
    assert sim_pos < runtime_pos
