"""右手选择后主谱实时可见更新：完整当前谱必须显示实际动作并覆盖全部小节。"""
# 右手选择后主谱实时可见更新：新增实际SVG行为检查，不能再只测隐藏的局部谱有变化。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from test_guitar_section_patterns import fixture
from test_score_export import project_from, note, char
from guitar_pattern_selection import compile_selection
from guitar_pattern_live_score import render_live_score


def source_project(bars=6):
    # 右手选择后主谱实时可见更新：新增完整自拟词音，保留标准4/4与真实渲染所需来源绑定。
    source=fixture(bars)
    characters=[char(0,'歌',0,bars*2)]
    voice=project_from([note('held_voice',0,bars*2,64)],characters,seconds=bars*2)
    voice['timing'].update(source['accepted_vocal_project']['timing'])
    voice['lyrics']={'characters':characters}
    source['accepted_vocal_project']=voice
    source['shared_analysis']['input_binding']={'vocal_project_sha256':'synthetic'}
    source['shared_analysis']['sections'][0]['label']='演唱段'
    return source


class GuitarPatternLiveScoreTests(unittest.TestCase):
    def test_full_visible_score_covers_unselected_bars_and_selected_sweep_actions(self):
        source=source_project();before=deepcopy(source)
        revised,_=compile_selection(source,{'ranges':[{'id':'middle','start_measure':2,'end_measure':3,'choice':{'pattern_id':'S07'}}]})
        html=render_live_score(revised);root=ET.fromstring('<root>'+html+'</root>')
        sections=list(root)
        covered=[m for row in sections for m in range(int(row.get('data-first-measure')),int(row.get('data-last-measure'))+1)]
        self.assertEqual(covered,list(range(1,7)))
        self.assertTrue(all(int(row.get('data-last-measure'))-int(row.get('data-first-measure'))<4 for row in sections))
        actions=[n for n in root.iter() if n.get('data-action-kind')]
        self.assertTrue(any(n.get('data-action-kind')=='strum' for n in actions))
        actual={n.get('data-action-id') for n in actions}
        expected={e['id'] for e in revised['arrangements']['guitar']['selected_pattern_actions']}
        self.assertEqual(actual,expected)
        self.assertEqual(source,before)

    def test_visible_score_changes_between_arpeggio_pinch_and_sweep(self):
        source=source_project(4);htmls=[]
        for pattern,kind in [('A02','pluck'),('A14','pinch'),('S01','strum')]:
            revised,_=compile_selection(source,{'default':{'pattern_id':pattern}})
            html=render_live_score(revised);htmls.append(html)
            root=ET.fromstring('<root>'+html+'</root>')
            self.assertTrue(any(node.get('data-action-kind')==kind for node in root.iter()))
            self.assertEqual(revised['accepted_vocal_project'],source['accepted_vocal_project'])
        self.assertEqual(len(set(htmls)),3)


if __name__=='__main__':
    unittest.main()
