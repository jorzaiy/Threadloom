"""Tests for persona-hook micro-action filtering (e23032 backlog #2).

The keeper auto-captures one-off bodily postures (e.g. '耳朵朝声源转一下又转回')
into actor_persona_hooks; injecting them into the actor registry every turn
primes the narrator to repeat the gesture. looks_like_transient_posture detects
them and _format_actor_registry drops them at render time.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from name_sanitizer import looks_like_transient_posture  # noqa: E402
from narrator_input import _format_actor_registry  # noqa: E402

# Real hook values pulled from session e23032.
POSTURES = [
    '耳朵朝声源转一下又转回', '尾巴尖搭手腕晃晃又缩回', '手指弯了弯又松开', '喉结动一下',
    '黑豆眼扫视后缩回', '眼角肌肉细微跳动', '嘴角下拉抿紧', '耳朵压低一瞬又竖起',
    '被拢进怀里时眼睛眯缝，探头扫一眼又缩回',
]
ABSTRACT = [
    '低声回答', '短暂停顿', '讲话压低声音', '谨慎多疑',
    '愿意透露镇上近期多人怪病及陈掌柜治疗细节', '先确认对方身份和来历再决定是否进一步接触',
    '无意识地攥短褐下摆',
]


class TransientPostureDetectorTests(unittest.TestCase):
    def test_flags_one_off_postures(self):
        for s in POSTURES:
            self.assertTrue(looks_like_transient_posture(s), s)

    def test_keeps_abstract_dispositions(self):
        for s in ABSTRACT:
            self.assertFalse(looks_like_transient_posture(s), s)

    def test_empty_and_non_string(self):
        self.assertFalse(looks_like_transient_posture(''))
        self.assertFalse(looks_like_transient_posture(None))


class ActorRegistryRenderTests(unittest.TestCase):
    def _render(self, hooks):
        actors = {'npc_x': {'name': '灵貂'}}
        ctx = {'active_actor_ids': ['npc_x']}
        return _format_actor_registry(actors, ctx, {'npc_x': hooks})

    def test_postures_dropped_abstract_kept(self):
        out = self._render({
            'speech_style': '低声回答',
            'behavior_mode': '被拢进怀里时眼睛眯缝，探头扫一眼又缩回',  # posture
            'decision_bias': '先确认身份再接触',
            'mannerisms': ['耳朵朝声源转一下又转回', '黑豆眼扫视后缩回', '谨慎观察周围'],
        })
        self.assertIn('灵貂', out)               # actor still rendered
        self.assertIn('低声回答', out)            # abstract speech kept
        self.assertIn('先确认身份再接触', out)     # abstract decision kept
        self.assertIn('谨慎观察周围', out)         # abstract mannerism kept
        self.assertNotIn('眼睛眯缝', out)          # posture behavior_mode dropped
        self.assertNotIn('耳朵朝声源转', out)      # posture mannerism dropped
        self.assertNotIn('黑豆眼扫视', out)

    def test_all_posture_hooks_leave_no_hook_block(self):
        out = self._render({
            'behavior_mode': '手指弯了弯又松开',
            'mannerisms': ['喉结动一下', '眼角肌肉细微跳动'],
        })
        self.assertIn('灵貂', out)               # actor still listed
        self.assertNotIn('表达钩子', out)          # nothing survives -> no hook block
        self.assertNotIn('习惯动作', out)


if __name__ == '__main__':
    unittest.main()
