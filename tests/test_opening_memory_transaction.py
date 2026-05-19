#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import opening


def test_opening_choice_state_can_skip_checkpoint_save(monkeypatch):
    saves = []
    monkeypatch.setattr(opening, 'save_state', lambda session_id, state: saves.append((session_id, state)))
    monkeypatch.setattr(opening, 'opening_bootstrap', lambda: {'time': '清晨', 'location': '茶肆'})

    state = opening.initialize_opening_choice_state('session', '开局一：进入茶肆', persist=False)

    assert state['opening_resolved'] is True
    assert saves == []


def test_opening_choice_state_keeps_checkpoint_save_by_default(monkeypatch):
    saves = []
    monkeypatch.setattr(opening, 'save_state', lambda session_id, state: saves.append((session_id, state)))
    monkeypatch.setattr(opening, 'opening_bootstrap', lambda: {'time': '清晨', 'location': '茶肆'})

    opening.initialize_opening_choice_state('session', '开局一：进入茶肆')

    assert len(saves) == 1
