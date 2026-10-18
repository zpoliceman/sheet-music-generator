"""扫弦箭头与实际弦组记谱修正：直接检查实际TAB，包含篡改几何的拒绝案例。"""
# 扫弦箭头与实际弦组记谱修正：新增真实渲染／回读行为测试，避免仅检查方向元数据。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from test_guitar_pattern_live_score import source_project
from guitar_pattern_selection import compile_selection
from guitar_strum_notation import read_visible_strums, swept_note_ids
from guitar_variable_repeat import measure_timeline
from export_timing_revision import render_row

NS='{http://www.w3.org/2000/svg}'


class GuitarStrumNotationTests(unittest.TestCase):
    def setUp(self):
        # 扫弦箭头与实际弦组记谱修正：新增同一完整4/4来源的低弦下扫、全弦下扫、高弦上扫混合夹具。
        self.project,_=compile_selection(source_project(4),{'default':{'pattern_id':'S04'}})
        self.arrangement=self.project['arrangements']['guitar']
        self.root=ET.fromstring(render_row(self.project,measure_timeline(self.project),guitar=True))

    def test_down_is_up_arrow_up_is_down_arrow_and_spans_actual_strings(self):
        # 扫弦箭头与实际弦组记谱修正：新增独立从线段和箭头尖检查全弦及局部弦跨度。
        groups=[n for n in self.root.iter(NS+'g') if n.get('data-action-kind')=='strum']
        directions=set();spans=set()
        for group in groups:
            shaft=group.find(NS+'line');head=group.find(NS+'polyline')
            tail,tip=float(shaft.get('y1')),float(shaft.get('y2'))
            strings=[int(s) for s in group.get('data-strings').split(',')]
            self.assertEqual({tail,tip},{337+(min(strings)-1)*18,337+(max(strings)-1)*18})
            self.assertEqual(tip<tail,group.get('data-direction')=='down')
            points=[tuple(map(float,p.split(','))) for p in head.get('points').split()]
            self.assertEqual(points[1],(float(shaft.get('x1')),tip))
            self.assertEqual(points[0][1]>tip,tip<tail)
            self.assertIsNone(group.find(NS+'text'))
            directions.add(group.get('data-direction'));spans.add(len(strings))
        self.assertEqual(directions,{'up','down'})
        self.assertTrue({2,3}.issubset(spans));self.assertGreater(max(spans),3)
        decoded,errors=read_visible_strums(self.root,self.arrangement)
        self.assertEqual(errors,[])
        self.assertEqual({n[0] for n in decoded},swept_note_ids(self.arrangement))

    def test_strum_heads_removed_while_pinch_stays_on_its_individual_strings(self):
        # 扫弦箭头与实际弦组记谱修正：新增实际音头替代与同刻合拨保留检查。
        ids=swept_note_ids(self.arrangement)
        self.assertFalse(any(n.get('data-note-id') in ids and n.get('data-string') for n in self.root.iter(NS+'g')))
        pinch,_=compile_selection(source_project(4),{'default':{'pattern_id':'A14'}})
        root=ET.fromstring(render_row(pinch,measure_timeline(pinch),guitar=True))
        actual={n.get('data-note-id') for n in root.iter(NS+'g') if n.get('data-string') and n.find(NS+'text') is not None}
        pinch_ids={identity for e in pinch['arrangements']['guitar']['selected_pattern_actions'] if e['kind']=='pinch' for identity in e['note_ids']}
        self.assertTrue(pinch_ids);self.assertTrue(pinch_ids.issubset(actual))
        self.assertFalse(any(n.get('class')=='strum-head' for n in root.iter()))

    def test_actual_geometry_tampering_is_rejected_with_metadata_unchanged(self):
        # 扫弦箭头与实际弦组记谱修正：新增反向、缩短、错拍、隐藏、缺箭头及柱式叠画的真实篡改用例。
        for damage in ('reverse_head','shorten_shaft','move_beat','hidden','missing_head','block_heads'):
            with self.subTest(damage=damage):
                root=deepcopy(self.root)
                group=next(n for n in root.iter(NS+'g') if n.get('data-action-kind')=='strum')
                shaft=group.find(NS+'line');head=group.find(NS+'polyline')
                x,tip=float(shaft.get('x1')),float(shaft.get('y2'))
                if damage=='reverse_head':
                    head.set('points',f'{x-4},{tip-7} {x},{tip} {x+4},{tip-7}')
                elif damage=='shorten_shaft':
                    shaft.set('y1',str(float(shaft.get('y1'))-18))
                elif damage=='move_beat':
                    shaft.set('x1',str(x+9));shaft.set('x2',str(x+9))
                    head.set('points',f'{x+5},{tip+7} {x+9},{tip} {x+13},{tip+7}')
                elif damage=='hidden':
                    head.set('opacity','0')
                elif damage=='missing_head':
                    group.remove(head)
                else:
                    event=next(e for e in self.arrangement['selected_pattern_actions'] if e['id']==group.get('data-action-id'))
                    node=ET.SubElement(group,NS+'g',{'data-note-id':event['note_ids'][0]})
                    ET.SubElement(node,NS+'text').text='x'
                _,errors=read_visible_strums(root,self.arrangement)
                self.assertTrue(errors,damage)

    def test_common_visible_tab_acceptance_decodes_arrows_and_rejects_bad_span(self):
        # 扫弦箭头与实际弦组记谱修正：新增共同硬验收入口的真实文件读回，不仅调用箭头绘制器。
        from tempfile import TemporaryDirectory
        from guitar_readability_acceptance import _modern_tab_rows
        folder=Path(__file__).resolve().parents[1]/'test_outputs/accompaniment_runs/tests'
        folder.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=folder) as tmp:
            path=Path(tmp)/'voice_001.svg';ET.ElementTree(self.root).write(path)
            _,report=_modern_tab_rows([path],self.arrangement)
            self.assertTrue(report['valid'],report)
            head=next(n for n in self.root.iter() if n.get('class')=='strum-shaft')
            head.set('y2',str(float(head.get('y2'))+18))
            ET.ElementTree(self.root).write(path)
            _,report=_modern_tab_rows([path],self.arrangement)
            self.assertFalse(report['valid'])

    def test_rendering_does_not_mutate_logical_or_performance_notes(self):
        # 扫弦箭头与实际弦组记谱修正：新增渲染前后完整音乐及逐弦音序保持验证。
        from guitar_pattern_performance import performance_notes
        before=deepcopy(self.project);performance=performance_notes(self.arrangement)
        render_row(self.project,measure_timeline(self.project),guitar=True)
        self.assertEqual(self.project,before)
        self.assertEqual(performance_notes(self.arrangement),performance)

    def test_complete_reading_export_accepts_real_arrows_without_block_heads(self):
        # 扫弦箭头与实际弦组记谱修正：新增完整阅读导出覆盖实际漏接的复用音符计数入口。
        from tempfile import TemporaryDirectory
        from accompaniment_export import html_page
        from export_timing_revision import write_variable_repeat_score
        folder=Path(__file__).resolve().parents[1]/'test_outputs/accompaniment_runs/tests'
        folder.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=folder) as tmp:
            output=Path(tmp);(output/'rows').mkdir()
            body='<nav></nav><section class="score-row">'+ET.tostring(self.root,encoding='unicode')+'</section>'
            (output/'score.html').write_text(html_page('扫弦记谱自拟夹具',body),encoding='utf-8')
            result=write_variable_repeat_score(self.project,output)
            self.assertTrue(result['valid'],result)
            roots=[ET.parse(p).getroot() for p in (output/'rows').glob('repeat_*.svg')]
            self.assertTrue(any(n.get('class')=='strum-head' for root in roots for n in root.iter()))
            self.assertFalse(any(n.get('data-string') for root in roots for n in root.iter()))


if __name__=='__main__':
    unittest.main()
