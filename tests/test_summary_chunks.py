#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend.summary_chunks import _structured_keywords


class SummaryChunkKeywordTests(unittest.TestCase):
    def test_keywords_prefer_story_terms_over_cut_fragments(self):
        payload = {
            'dense_summary': [
                '陆小环在人界苍梧城西市茶肆发现城主府悬赏榜文，随后追查吸灵螺与灵田异常。',
                '青布短衫人和灰袍散修都与榜文线索有关，南墟旧摊可能藏有完整图册。',
            ],
            'key_events': [
                '陆小环发现灰白螺旋壳、病壳和地下管壁，畸形黑影正在泥坑附近搜查。',
            ],
            'unresolved': ['凹地壳群与黑烂树木的来源仍未解决。'],
            'locations': ['苍梧城西市茶肆', '城主府后灵田', '苍梧岭南坡松林边缘'],
            'actors_mentioned': ['陆小环', '青布短衫人', '灰袍散修'],
            'objects_mentioned': ['吸灵螺', '灰白螺旋壳', '短剑'],
        }

        keywords = _structured_keywords(payload, {}, [], limit=30)

        self.assertIn('吸灵螺', keywords)
        self.assertIn('灰白螺旋壳', keywords)
        self.assertIn('青布短衫人', keywords)
        self.assertIn('城主府后灵田', keywords)
        self.assertNotIn('陆小环在', keywords)
        self.assertNotIn('人界苍梧', keywords)


if __name__ == '__main__':
    unittest.main()
