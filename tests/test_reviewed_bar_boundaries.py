"""局部两拍过渡听辨修订：来源防篡改、闭合边界和实际导出分组测试。"""
# 局部两拍过渡听辨修订：新增自拟音乐反例，不内置任何歌名、歌词或原曲秒数。
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
from test_guitar_variable_repeat import project_fixture
from reviewed_bar_boundaries import planned_timeline,_derive,verify_revision,notation_voice
from score_export import save_json,sha256
from guitar_variable_repeat import measure_timeline,build_repeat_plan,validate_repeat_plan
from guitar_readability_acceptance import music_payload,fingerprint
from export_timing_revision import local_view,build_xml,inspect_xml


class ReviewedBarBoundaryTests(unittest.TestCase):
    # 局部两拍过渡听辨修订：新增临时来源绑定，测试只有局部记谱层可改变。
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)/'source.json';self.review_path=Path(self.tmp.name)/'review.json'
        # 局部两拍过渡听辨修订：修改合成来源补足XML要求的来源标签，不冒充真实音频绑定。
        # self.base=project_fixture();self.base['shared_analysis']['input_binding']={'sources':{'mix':{'sha256':'synthetic'}}}
        self.base=project_fixture();self.base['shared_analysis']['input_binding']={'vocal_project_sha256':'synthetic','sources':{'mix':{'sha256':'synthetic'}}}
        # 局部两拍过渡听辨修订：新增合成挂词来源，旧阅读夹具只有绘图事件，不能代表完整生成工程。
        self.base['accepted_vocal_project']['lyrics']={'characters':[
            {'index':n['lyric_index'],'text':'春','start_seconds':n['start_seconds'],'end_seconds':n['end_seconds']}
            for n in self.base['accepted_vocal_project']['quantized_notes']]}
        # 局部两拍过渡听辨修订：新增完整XML夹具的段落显示名。
        for section in self.base['shared_analysis']['sections']:section['label']='合成乐段'
        # 局部两拍过渡听辨修订：新增完整原分组记谱夹具，阅读测试的简化事件不等于生成工程。
        from source_timing_revision import rebuild_events
        rebuild_events(self.base['accepted_vocal_project'],measure_timeline(self.base))
        save_json(self.source,self.base)
        self.review={'source_project_sha256':sha256(self.source),'mix_sha256':'synthetic','edits':[
            {'id':'local','first_measure':1,'old_beats':[2,4],'new_beats':[4,2],
             'beat_constraints':[{'source_seconds':1.,'beat':3}]}]}
        save_json(self.review_path,self.review)
        self.new=_derive(self.base,self.review,self.source,self.review_path)

    def test_performance_and_closed_window_stay_exact(self):
        self.assertEqual(self.new['accepted_vocal_project'],self.base['accepted_vocal_project'])
        self.assertEqual(self.new['shared_analysis'],self.base['shared_analysis'])
        self.assertEqual(self.new['arrangements'],self.base['arrangements'])
        old=measure_timeline(self.base);new=measure_timeline(self.new)
        self.assertEqual(new[2:],old[2:]);self.assertEqual(new[0]['start_tick'],old[0]['start_tick'])
        self.assertEqual(new[1]['end_tick'],old[1]['end_tick']);self.assertEqual(new[0]['end_tick'],1920)
        self.assertTrue(verify_revision(self.new,verify_source=False)['valid'])

    def test_source_pitch_lyric_and_boundary_tampering_rejected(self):
        mutations=[lambda p:p['accepted_vocal_project']['quantized_notes'][0].update(pitch_midi=30),
            lambda p:p['arrangements']['guitar']['notes'][0].update(end_tick=1),
            lambda p:p['bar_boundary_revision']['measure_timeline'][0].update(end_tick=960),
            lambda p:p['bar_boundary_revision']['events'][0].update(lyric_index=999)]
        for mutate in mutations:
            p=deepcopy(self.new);mutate(p)
            with self.assertRaises(ValueError):verify_revision(p,verify_source=False)

    def test_review_file_change_rejected(self):
        self.review['edits'][0]['beat_constraints'][0]['beat']=1;save_json(self.review_path,self.review)
        with self.assertRaises(ValueError):verify_revision(self.new,verify_source=False)

    def test_wrong_original_sequence_and_out_of_window_anchor_rejected(self):
        for change in ({'old_beats':[4,2]}, {'beat_constraints':[{'source_seconds':5.,'beat':1}]},
                       {'new_beats':[4,4]}, {'beat_constraints':[]}):
            review=deepcopy(self.review);review['edits'][0].update(change)
            with self.assertRaises(ValueError):planned_timeline(self.base,review)

    def test_overlapping_edits_and_pickup_rejected(self):
        review=deepcopy(self.review);review['edits'].append(deepcopy(review['edits'][0]))
        with self.assertRaises(ValueError):planned_timeline(self.base,review)
        base=deepcopy(self.base);base['accepted_vocal_project']['timing']['measure_timeline'][0]['pickup']=True
        with self.assertRaises(ValueError):planned_timeline(base,self.review)

    def test_engraved_events_share_actual_new_boundaries(self):
        timeline=measure_timeline(self.new);voice=notation_voice(self.new)
        for event in voice['events']:
            m=timeline[event['measure']-1]
            self.assertGreaterEqual(event['start_tick'],m['start_tick'])
            self.assertLessEqual(event['start_tick']+event['duration_ticks'],m['end_tick'])
        local=local_view(self.new,timeline[0])[0]
        self.assertEqual(local['statistics']['bar_ticks'],1920)
        xml=build_xml(self.new,'guitar')
        self.assertTrue(inspect_xml(xml,timeline,'guitar')['valid'])
        self.assertEqual(xml.findtext('part/measure/attributes/time/beats'),'4')

    def test_derived_grouping_invalidates_old_reading_acceptance(self):
        self.assertNotEqual(fingerprint(music_payload(self.base)),fingerprint(music_payload(self.new)))
        plan=build_repeat_plan(self.new)
        self.assertTrue(validate_repeat_plan(plan,self.new)['valid'])
        self.assertFalse(validate_repeat_plan(build_repeat_plan(self.base),self.new)['valid'])

    def test_public_entry_uses_local_route_without_arranging(self):
        from generate_accompaniment import generate
        args=SimpleNamespace(edited_project=self.source,bar_boundary_review=self.review_path,output='unused',report=None)
        with patch('reviewed_bar_boundaries.revise',return_value={'local':True}) as revised,patch('revise_meter_unit.revise',side_effect=AssertionError('not allowed')):
            self.assertEqual(generate(args),{'local':True});revised.assert_called_once()
        args.rearrange=True
        with self.assertRaises(ValueError):generate(args)

    def test_source_is_verified_before_accepting_notation_layer(self):
        with patch('revise_guitar_reading.verify_reading_source',side_effect=ValueError('untrusted source')):
            with self.assertRaises(ValueError):verify_revision(self.new)

    def test_unrelated_special_notation_cannot_be_silently_replaced(self):
        # 局部两拍过渡听辨修订：修改跨来源反例为特殊连音记法；旧合成乐段没有休止。
        # event=next(e for e in base['accepted_vocal_project']['events'] if e['measure']>2 and e.get('piece_id') is None)
        # event['source_notation_annotation']='保留的原记法'
        base=deepcopy(self.base)
        event=next(e for e in base['accepted_vocal_project']['events'] if e['measure']>2)
        event['tuplet']={'actual':3,'normal':2}
        with self.assertRaisesRegex(ValueError,'局部窗口外'):_derive(base,self.review,self.source,self.review_path)


if __name__=='__main__':unittest.main()
