#!/usr/bin/env python3
import sys
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

handler_message = importlib.import_module('handler_message')
runtime_store = importlib.import_module('runtime_store')


def _model_config(model_id: str) -> dict[str, object]:
    return {
        'provider_name': 'site',
        'provider': {'baseUrl': 'https://example.test/v1', 'apiKey': ''},
        'model': {'id': model_id},
        'temperature': 0.8,
        'max_output_tokens': 100,
        'stream': False,
    }


def test_narrator_retries_incomplete_replies(monkeypatch):
    replies = [
        ('半截正文，', {'finish_reason': 'length', 'model': 'narrator'}),
        ('仍然没有句号', {'finish_reason': 'stop', 'model': 'narrator'}),
        ('完整正文。', {'finish_reason': 'stop', 'model': 'narrator'}),
    ]

    def fake_resolve_provider_model(role):
        return _model_config(role)

    def fake_call_model(_model_cfg, _system_prompt, _user_prompt):
        return replies.pop(0)

    monkeypatch.setattr(handler_message, 'resolve_provider_model', fake_resolve_provider_model)
    monkeypatch.setattr(handler_message, 'call_model', fake_call_model)

    reply, usage, trace = handler_message._call_narrator_with_retries('system', 'user')

    assert reply == '完整正文。'
    assert usage['finish_reason'] == 'stop'
    assert trace['all_failed'] is False
    assert len(trace['attempts']) == 3
    assert trace['attempts'][0]['ok'] is False
    assert trace['attempts'][1]['ok'] is False
    assert trace['attempts'][2]['ok'] is True


def test_narrator_returns_unavailable_after_primary_and_secondary_exhausted(monkeypatch, caplog):
    attempts = []
    incomplete_reply = '像一头耐心的狼，领着一群疲惫的'

    def fake_resolve_provider_model(role):
        return _model_config(role)

    def fake_call_model(_model_cfg, _system_prompt, _user_prompt):
        attempts.append(1)
        return incomplete_reply, {'finish_reason': 'stop', 'model': 'narrator'}

    monkeypatch.setattr(handler_message, 'resolve_provider_model', fake_resolve_provider_model)
    monkeypatch.setattr(handler_message, 'call_model', fake_call_model)
    caplog.set_level('WARNING')

    reply, usage, trace = handler_message._call_narrator_with_retries('system', 'user')

    assert reply == ''
    assert usage['finish_reason'] == 'error'
    assert trace['all_failed'] is True
    assert trace['last_error'] == 'incomplete narrator reply'
    assert len(trace['attempts']) == 4
    assert len(attempts) == 4
    assert [a['role'] for a in trace['attempts']] == ['primary', 'primary', 'primary', 'secondary']
    for attempt in trace['attempts']:
        assert attempt['ok'] is False
        assert attempt['error'] == 'incomplete narrator reply'
        assert attempt['incomplete_heuristic_rejected'] is True
        assert attempt['reply_chars'] == len(incomplete_reply)
        assert attempt['reply_excerpt'] == incomplete_reply
        assert attempt['raw_reply'] == incomplete_reply
    assert 'NARRATOR_INCOMPLETE_REJECTED' in caplog.text


def test_narrator_retries_degenerated_direction_templates(monkeypatch):
    malformed = (
        '他的手抬起来了，抬的方向是自己的胸口。'
        '眼珠子移开了，移的方向是窗纸。'
        '嘴巴张了一下，张的方式是先停半息再合上。'
    )
    replies = [
        (malformed, {'finish_reason': 'stop', 'model': 'narrator'}),
        ('年轻男人按住胸口，低声说井底有问题。', {'finish_reason': 'stop', 'model': 'narrator'}),
    ]
    prompts = []

    def fake_resolve_provider_model(role):
        return _model_config(role)

    def fake_call_model(_model_cfg, system_prompt, _user_prompt):
        prompts.append(system_prompt)
        return replies.pop(0)

    monkeypatch.setattr(handler_message, 'resolve_provider_model', fake_resolve_provider_model)
    monkeypatch.setattr(handler_message, 'call_model', fake_call_model)

    reply, usage, trace = handler_message._call_narrator_with_retries('system', 'user')

    assert reply == '年轻男人按住胸口，低声说井底有问题。'
    assert usage['finish_reason'] == 'stop'
    assert trace['all_failed'] is False
    assert trace['attempts'][0]['ok'] is False
    assert trace['attempts'][0]['incomplete_heuristic_rejected'] is True
    assert trace['attempts'][0]['rejection_reason'] == 'degenerated_style_template'
    assert trace['attempts'][0]['corrective_retry_prompt'] == 'style_template'
    assert trace['attempts'][1]['ok'] is True
    assert '上次回复已被系统拒绝：叙事句式退化' in prompts[1]
    assert '严禁使用' in prompts[1]
    assert 'X的方式是' in prompts[1]
    assert malformed[:30] in prompts[1]


def test_narrator_retries_conjecture_to_prior_history_assertion(monkeypatch):
    replies = [
        ('林岚和守灯人。围着塔楼旧仪器。一起把港口灯塔点亮了。', {'finish_reason': 'stop', 'model': 'narrator'}),
        ('林岚只能先把塔楼仪器和港口灯塔记作可能有关，具体关系还需要查证。', {'finish_reason': 'stop', 'model': 'narrator'}),
    ]
    prompts = []

    def fake_resolve_provider_model(role):
        return _model_config(role)

    def fake_call_model(_model_cfg, system_prompt, _user_prompt):
        prompts.append(system_prompt)
        return replies.pop(0)

    monkeypatch.setattr(handler_message, 'resolve_provider_model', fake_resolve_provider_model)
    monkeypatch.setattr(handler_message, 'call_model', fake_call_model)

    system_prompt = '【历史原文证据包】\n塔楼仪器持续发热。港口灯塔亮了三次，但未确认两者有关。'
    user_prompt = '【当前用户输入】\n塔楼仪器和港口灯塔会不会有关？\n\n【近端约束提醒】\n只输出正文。'

    reply, usage, trace = handler_message._call_narrator_with_retries(system_prompt, user_prompt)

    assert reply == '林岚只能先把塔楼仪器和港口灯塔记作可能有关，具体关系还需要查证。'
    assert usage['finish_reason'] == 'stop'
    assert trace['attempts'][0]['ok'] is False
    assert trace['attempts'][0]['rejection_reason'] == 'unsupported_conjecture_to_history_assertion'
    assert trace['attempts'][0]['corrective_retry_prompt'] == 'grounding_prior_event'
    assert '把用户的提问、猜测、类比、求证或人物推理改写成已完成旧事实' in prompts[1]


def test_narrator_grounding_guard_allows_supported_prior_chain():
    reply = '林岚和守灯人围着塔楼旧仪器，一起把港口灯塔点亮了。'
    grounding = '【历史原文证据包】\n林岚和守灯人围着塔楼旧仪器，一起把港口灯塔点亮了。'
    user_prompt = '【当前用户输入】\n塔楼仪器和港口灯塔会不会有关？\n\n【近端约束提醒】\n只输出正文。'

    assert handler_message._unsupported_prior_event_assertion_reason(reply, grounding, user_prompt) == ''


def test_narrator_grounding_guard_allows_present_action_under_conjectural_query():
    """Regression for session 九幽大陆-20260520-e23032 turn-0141: a conjectural user query
    that also dictates a present-tense action ('把灵貂抱在怀里') must not cause the narrator's
    faithful continuation to be flagged just because it shares scene nouns (灵貂/怀里).
    """
    reply = (
        '九幽历三千七百二十二年，四月十九，清晨。人界，青石镇外围山林，隐蔽山洞。\n\n'
        '灵貂被她捞进怀里，下巴搁在她锁骨窝，两条后腿搭在小臂上，尾巴垂着。'
        '陆小环的拇指按在它后颈，揉了两下，指尖陷进那层薄薄的绒毛底下，摸得到脊椎骨一节一节的。\n\n'
        '山洞外鸟叫多了起来，叽叽喳喳隔松林传进来，闷的。桐木盒搁在凹陷里，'
        '泥壳灰白，圆球挂在根须断段上，黏膜还在缓缓吸水。'
    )
    grounding = '【最近上下文】\n两人在山洞里休整。桐木盒搁在凹陷里。'
    user_prompt = (
        '【当前用户输入】\n'
        '把灵貂抱在怀里捏着玩，想着：井里还有邪物，或者那些人利用井产生邪物，'
        '虽然他们一只脚踏进了修仙之路，但是如果灵力必须要靠井产生，自己的灵力也要渡进去，'
        '那有什么意义呢，那些人都形容枯槁，可见这灵力对他们并没有什么好处，'
        '又或者… 有人或者有东西能从这件事里得到好处？\n\n'
        '【近端约束提醒】\n只输出正文。'
    )

    assert handler_message._unsupported_prior_event_assertion_reason(reply, grounding, user_prompt) == ''


def test_narrator_grounding_guard_allows_in_scene_callback_with_刚才():
    """'刚才那声咕沉半拍' is an immediate within-scene callback, not a prior-event assertion.
    Combined with '看过去' (which only contains the lone char '过') it must not flag.
    """
    reply = '它又"嗯"了一声，比刚才那声"咕"沉半拍，拖着尾巴，像在等她看过去。'
    grounding = '【最近上下文】\n灵貂的鼻翼扇了一下。'
    user_prompt = '【当前用户输入】\n继续观察灵貂的反应。\n\n【近端约束提醒】\n只输出正文。'

    assert handler_message._unsupported_prior_event_assertion_reason(reply, grounding, user_prompt) == ''


def test_narrator_secondary_fallback_runs_when_primary_exhausted(monkeypatch):
    """Primary heuristic-rejects 3 times; secondary must still get a turn and can save the round."""
    rejected_primary = '林岚和守灯人。围着塔楼旧仪器。一起把港口灯塔点亮了。'
    saved_by_secondary = '林岚把仪器搁回桌面，灯塔的事还需要查证，先记下来。'
    calls = []

    def fake_resolve_provider_model(role):
        return _model_config(role)

    def fake_call_model(_model_cfg, _system_prompt, _user_prompt):
        calls.append(_model_cfg['model']['id'])
        if len(calls) <= 3:
            return rejected_primary, {'finish_reason': 'stop', 'model': 'narrator'}
        return saved_by_secondary, {'finish_reason': 'stop', 'model': 'state_keeper'}

    monkeypatch.setattr(handler_message, 'resolve_provider_model', fake_resolve_provider_model)
    monkeypatch.setattr(handler_message, 'call_model', fake_call_model)

    system_prompt = '【历史原文证据包】\n塔楼仪器持续发热。港口灯塔亮了三次，但未确认两者有关。'
    user_prompt = '【当前用户输入】\n塔楼仪器和港口灯塔会不会有关？\n\n【近端约束提醒】\n只输出正文。'

    reply, usage, trace = handler_message._call_narrator_with_retries(system_prompt, user_prompt)

    assert reply == saved_by_secondary
    assert trace['all_failed'] is False
    assert trace['provider_used'] == 'secondary'
    assert trace['fallback_to_secondary'] is True
    assert [a['role'] for a in trace['attempts']] == ['primary', 'primary', 'primary', 'secondary']
    assert trace['attempts'][3]['ok'] is True


def test_narrator_grounding_guard_allows_non_conjectural_current_user_statement():
    reply = '林岚低声说：“我们之前见过。”'
    grounding = '【最近上下文】\n两人站在门口。'
    user_prompt = '【当前用户输入】\n我低声说：“我们之前见过。”\n\n【近端约束提醒】\n只输出正文。'

    assert handler_message._unsupported_prior_event_assertion_reason(reply, grounding, user_prompt) == ''


def test_narrator_grounding_guard_still_rejects_conjectural_user_question_as_support():
    reply = '林岚和守灯人之前一起把港口灯塔点亮过。'
    grounding = '【历史原文证据包】\n塔楼仪器持续发热。港口灯塔亮了三次，但未确认两者有关。'
    user_prompt = '【当前用户输入】\n林岚和守灯人之前有没有可能一起点亮过港口灯塔？\n\n【近端约束提醒】\n只输出正文。'

    assert handler_message._unsupported_prior_event_assertion_reason(reply, grounding, user_prompt) == 'unsupported_prior_event_assertion'


def test_narrator_rejects_repeated_degenerated_templates(monkeypatch):
    malformed = (
        '他的声音不抖了——不抖的方式是舌头顶住上牙膛。'
        '他的眼珠子移开了，移的方向是窗纸。'
        '他的手抬起来了，抬的方向是胸口。'
    )
    attempts = []

    def fake_resolve_provider_model(role):
        return _model_config(role)

    def fake_call_model(_model_cfg, _system_prompt, _user_prompt):
        attempts.append(1)
        return malformed, {'finish_reason': 'stop', 'model': 'narrator'}

    monkeypatch.setattr(handler_message, 'resolve_provider_model', fake_resolve_provider_model)
    monkeypatch.setattr(handler_message, 'call_model', fake_call_model)

    reply, usage, trace = handler_message._call_narrator_with_retries('system', 'user')

    assert reply == ''
    assert usage['finish_reason'] == 'error'
    assert trace['all_failed'] is True
    assert len(attempts) == 4
    assert [a['role'] for a in trace['attempts']] == ['primary', 'primary', 'primary', 'secondary']
    for attempt in trace['attempts']:
        assert attempt['ok'] is False
        assert attempt['incomplete_heuristic_rejected'] is True
        assert attempt['rejection_reason'] == 'degenerated_style_template'


def test_history_filter_hides_partial_turn_pair():
    history = [
        {'role': 'assistant', 'content': '开场。'},
        {'role': 'user', 'content': '继续'},
        {'role': 'assistant', 'content': '半截正文', 'completion_status': 'partial'},
    ]

    assert runtime_store.filter_committed_history_items(history) == [
        {'role': 'assistant', 'content': '开场。'},
    ]


def test_append_history_discards_existing_partial_pair_before_new_user(monkeypatch):
    history = [
        {'role': 'assistant', 'content': '开场。'},
        {'role': 'user', 'content': '继续'},
        {'role': 'assistant', 'content': '半截正文', 'completion_status': 'partial'},
    ]
    saved = {}

    monkeypatch.setattr(runtime_store, 'load_history', lambda _session_id: list(history))
    monkeypatch.setattr(runtime_store, 'save_history', lambda _session_id, items: saved.setdefault('items', items))

    runtime_store.append_history('session', {'role': 'user', 'content': '换个动作'})

    assert saved['items'] == [
        {'role': 'assistant', 'content': '开场。'},
        {'role': 'user', 'content': '换个动作'},
    ]
