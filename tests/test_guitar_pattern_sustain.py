"""扫弦延音简化与右手候选扩充：普通扫弦去冗余，明确延续仍可读且演奏保持。"""
# 扫弦延音简化与右手候选扩充：新增可见谱面与真实声音的行为验证，避免只改CSS隐藏音符。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from test_guitar_pattern_live_score import source_project
from guitar_pattern_selection import compile_selection, catalogue
from guitar_pattern_performance import performance_notes
from guitar_variable_repeat import measure_timeline
from export_timing_revision import render_row

NS='{http://www.w3.org/2000/svg}'


def render(pattern,**options):
    # 扫弦延音简化与右手候选扩充：新增完整来源夹具，真实编译后渲染全部小节。
    project,_=compile_selection(source_project(4),{'default':{'pattern_id':pattern,**options}})
    return project,ET.fromstring(render_row(project,measure_timeline(project),guitar=True))


class GuitarPatternSustainTests(unittest.TestCase):
    def test_regular_strumming_keeps_arrows_and_has_no_redundant_sustain_curves(self):
        # 扫弦延音简化与右手候选扩充：新增普通前八后十六扫弦实际字形数量与零延音线验证。
        project,root=render('S04')
        expected=sum(e['kind']=='strum' for e in project['arrangements']['guitar']['selected_pattern_actions'])
        self.assertEqual(sum(n.get('class')=='strum-head' for n in root.iter()),expected)
        self.assertFalse(any(n.get('class') in ('right-hand-sustain','right-hand-sustain-group') for n in root.iter()))

    def test_explicit_empty_and_hold_have_one_grouped_hint_per_bar_without_six_string_curves(self):
        # 扫弦延音简化与右手候选扩充：新增用户稀疏扫弦保留一段集中提示，连续空／延不按弦重复。
        project,root=render('S07')
        groups=[n for n in root.iter() if n.get('class')=='right-hand-sustain-group']
        self.assertEqual(len(groups),4)
        for i,group in enumerate(groups):
            self.assertEqual(int(group.get('data-sustain-start')),i*1920+240)
            self.assertEqual(int(group.get('data-sustain-end')),i*1920+1440)
            self.assertEqual(len(group.findall(NS+'path')),1)
            self.assertIn('330',group.find(NS+'path').get('d'))
        self.assertFalse(any(n.get('class')=='right-hand-sustain' for n in root.iter()))
        self.assertTrue(any(n.get('data-action-kind')=='air' for n in root.iter()))

    def test_stop_option_has_no_false_continuation_and_real_notes_stop(self):
        # 扫弦延音简化与右手候选扩充：新增制音不能被画成延续，实际起止随显式收音选项一致。
        project,root=render('S07',silence='stop')
        self.assertFalse(any(n.get('class')=='right-hand-sustain-group' for n in root.iter()))
        notes=[n for n in project['arrangements']['guitar']['notes'] if n['start_tick']==0]
        self.assertTrue(notes);self.assertTrue(all(n['end_tick']==240 for n in notes))

    def test_long_action_and_cross_bar_hold_are_grouped_and_clipped_to_each_bar(self):
        # 扫弦延音简化与右手候选扩充：新增明确两拍及跨小节长动作的集中提示，普通自然余音不参与。
        _,root=render('S18')
        self.assertEqual(sum(n.get('class')=='right-hand-sustain-group' for n in root.iter()),8)
        # 扫弦延音简化与右手候选扩充：保留原每小节换和弦的样例调用；跨小节长音须以同一真实持续和弦测试。
        # project,root=render('S19',durations=[3840])
        source=source_project(4)
        source['shared_analysis']['harmony']=[{**source['shared_analysis']['harmony'][0],'end_tick':7680}]
        # 扫弦延音简化与右手候选扩充：新增同步自拟样例的吉他和声视图，避免仍使用原逐小节结束的副本。
        source['arrangements']['guitar']['readable_harmony']=deepcopy(source['shared_analysis']['harmony'])
        project,_=compile_selection(source,{'default':{'pattern_id':'S19','durations':[3840]}})
        root=ET.fromstring(render_row(project,measure_timeline(project),guitar=True))
        groups=[n for n in root.iter() if n.get('class')=='right-hand-sustain-group']
        self.assertEqual(len(groups),4)
        self.assertEqual({int(n.get('data-sustain-start')) for n in groups},{0,1920,3840,5760})
        self.assertEqual({int(n.get('data-sustain-end'))-int(n.get('data-sustain-start')) for n in groups},{1920})
        self.assertEqual(len([e for e in project['arrangements']['guitar']['selected_pattern_actions'] if e['kind']=='strum']),2)

    def test_arpeggio_and_pinch_keep_necessary_per_string_curves(self):
        # 扫弦延音简化与右手候选扩充：新增仅改扫弦显示的范围约束。
        for pattern in ('A03','A14'):
            with self.subTest(pattern=pattern):
                _,root=render(pattern)
                self.assertTrue(any(n.get('class')=='right-hand-sustain' for n in root.iter()))

    def test_rendering_does_not_shorten_any_note_or_change_actual_performance(self):
        # 扫弦延音简化与右手候选扩充：新增稀疏提示绘制对实际音符、音序及整工程无副作用。
        project,_=render('S07');before=deepcopy(project)
        performance=performance_notes(project['arrangements']['guitar'])
        render_row(project,measure_timeline(project),guitar=True)
        self.assertEqual(project,before)
        self.assertEqual(performance_notes(project['arrangements']['guitar']),performance)

    def test_new_candidates_have_distinct_real_patterns_sources_and_sixteenth_limit(self):
        # 扫弦延音简化与右手候选扩充：新增语义去重与来源绑定；全部类型实际编译另由公共选型测试执行。
        patterns=catalogue()['patterns']
        signatures=[tuple((e['token'],e['action_span_ticks']) for e in p['events']) for p in patterns]
        self.assertEqual(len(signatures),len(set(signatures)))
        new=[p for p in patterns if p.get('_comment','').startswith('扫弦延音简化')]
        self.assertGreaterEqual(len(new),20)
        self.assertTrue(all(p.get('source_ids') and p.get('description') for p in new))
        for pattern in new:
            self.assertEqual(sum(e['action_span_ticks'] for e in pattern['events']),1920)
            self.assertTrue(all(e['action_span_ticks']>=120 for e in pattern['events']))

    def test_alternating_bass_fallback_searches_two_real_low_strings_without_relaxing_grip(self):
        # 扫弦延音简化与右手候选扩充：新增无现成指型时的交替低音搜索，第二低弦必须真实存在且按弦有效。
        from unittest.mock import patch
        from accompaniment_arrange import TUNING,grip_info
        from guitar_pattern_selection import _shape,_strings
        chords=[{'id':'suspended','name':'Ebsus4','root_pc':3,'bass_pc':3,'quality':'sus4','pitch_classes':[3,8,10]},
                {'id':'added','name':'Abadd9','root_pc':8,'bass_pc':8,'quality':'add9','pitch_classes':[8,0,3,10]}]
        for chord in chords:
            for capo in (0,2):
                with self.subTest(chord=chord['name'],capo=capo),patch('guitar_pattern_selection.common_grips',return_value=[]):
                    shape,bass=_shape(chord,capo,['B','3','B2','2'],{'fingering_diagrams':[]},0)
                    other=_strings('B2',shape,bass)[0]
                    frets={int(s):f for s,f in shape['frets'].items()}
                    self.assertNotEqual(bass,other);self.assertGreaterEqual(other,4)
                    self.assertLessEqual(max(frets.values()),12);self.assertIsNotNone(grip_info(frets))
                    pitches=[TUNING[s]+capo+f for s,f in frets.items()]
                    self.assertEqual(min(pitches)%12,chord['bass_pc'])
                    self.assertTrue({p%12 for p in pitches}.issubset(set(chord['pitch_classes'])))

    def test_every_new_pattern_exports_actual_xml_and_midi_with_matching_intervals(self):
        # 扫弦延音简化与右手候选扩充：新增所有新型经真实文件写出后的音符／弦品／完整时值回读。
        from tempfile import TemporaryDirectory
        from accompaniment_export import build_musicxml,write_midi,validate_midi
        from guitar_readability_acceptance import _xml_notes
        folder=Path(__file__).resolve().parents[1]/'test_outputs/accompaniment_runs/tests/right_hand_expansion'
        folder.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=folder) as tmp:
            for pattern in catalogue()['patterns']:
                if not pattern.get('_comment','').startswith('扫弦延音简化'):
                    continue
                with self.subTest(pattern=pattern['id']):
                    project,_=render(pattern['id']);guitar=project['arrangements']['guitar'];voice=project['accepted_vocal_project']
                    root,_=build_musicxml(project['shared_analysis'],voice,guitar)
                    xml=Path(tmp)/'score.musicxml';ET.ElementTree(root).write(xml)
                    actual,report=_xml_notes(xml,measure_timeline(project))
                    self.assertTrue(report['valid'],report)
                    wanted=[(n['pitch_midi'],n['start_tick'],n['end_tick'],n['string'],n['fret']) for n in guitar['notes']]
                    self.assertEqual(sorted(actual),sorted(wanted))
                    midi=Path(tmp)/'score.mid';write_midi(midi,guitar,voice)
                    self.assertTrue(validate_midi(midi,guitar,voice)['valid'])


if __name__=='__main__':
    unittest.main()
