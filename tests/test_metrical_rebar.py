"""小节划分与拍速层级纠错：已知四拍小节、实音秒时间与错误层级的独立反例。"""
# 小节划分与拍速层级纠错：新增合成音乐测试，不把自动识别的真实歌曲当准确率真值。
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
# 小节划分与拍速层级纠错：新增完整十六分起音的合成声学接口。
from types import SimpleNamespace
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import score_export as score
import musical_decode as music
from metrical_timing import beat_level_candidates,reviewed_beat_level,rebase_timing,resolve_timing
# 小节划分与拍速层级纠错：新增谱头速度与检测脉冲独立的反例。
from metrical_timing import selected_quarter_tempo
from accompaniment_rebar import (derive_vocal,scale_tree,compare_sounding_time,
    validate_vocal_snapshot,notation_pattern,rebase_pattern_plans)
from accompaniment_analysis import SongClock,measure_textures
from accompaniment_export import build_musicxml,write_midi,parse_musicxml_notes
from guitar_structure_validation import validate_structured_rhythm
from guitar_right_hand_patterns import library
from test_score_export import project_from,note,char


# 小节划分与拍速层级纠错：新增四个原两秒小节的音乐；新四秒4/4仍按原秒时间发声。
def vocal_fixture(seconds=8):
    v=project_from([note('a',1.5,2.5,64),note('b',3.5,5.5,67)],
                   [char(0,'春',1.5,2.5),char(1,'风',3.5,5.5)],seconds)
    v['timing'].update(knots=[{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}],
                      score_start_seconds=0,steady_tempo_bpm=120,beat_origin_seconds=0)
    v['overrides']={'tempo':120}
    v['audio_analysis']={'source_sha256':'a'*64,'tempo':{'bpm':120}}
    return v


def correction():
    return {'version':1,'quarter_scale':.5,'source_vocal_project_sha256':'b'*64,
            'source_audio_sha256':'a'*64,'basis':'synthetic_confirmed_4_4'}


class BeatLayerTests(unittest.TestCase):
    def test_half_normal_double_candidates_have_distinct_bar_lengths(self):
        rows=beat_level_candidates(120,[4,4])
        self.assertEqual([r['quarter_bpm'] for r in rows],[60,120,240])
        self.assertEqual([r['bar_seconds'] for r in rows],[4,2,1])
        self.assertEqual([r['detected_pulses_per_bar'] for r in rows],[8,4,2])

    def test_real_120_quarters_are_not_reduced_by_tempo_alone(self):
        decision=reviewed_beat_level({'source_sha256':'f'*64},120,[4,4])
        self.assertEqual(decision['quarter_scale'],1)
        self.assertEqual(decision['status'],'unresolved')

    def test_review_is_bound_to_sha_meter_and_detected_layer(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            p=Path(d)/'review.json'
            p.write_text(json.dumps({'reviews':{'a'*64:{'meter':[4,4],'detected_pulse_bpm':120,
                'quarter_scale':.5,'basis':'synthetic','review_id':'test'}}}),encoding='utf-8')
            args=({'source_sha256':'a'*64},120,[4,4])
            self.assertEqual(reviewed_beat_level(*args,review_path=p)['quarter_scale'],.5)
            self.assertEqual(reviewed_beat_level({'source_sha256':'b'*64},120,[4,4],review_path=p)['quarter_scale'],1)
            self.assertEqual(reviewed_beat_level(args[0],120,[3,4],review_path=p)['quarter_scale'],1)
            self.assertEqual(reviewed_beat_level(args[0],60,[4,4],review_path=p)['quarter_scale'],1)
            self.assertEqual(reviewed_beat_level(*args,explicit_tempo=True,review_path=p)['quarter_scale'],1)

    def test_local_tempo_changes_and_negative_score_origin_keep_seconds(self):
        old={'meter':[4,4],'score_start_quarter':-4,'score_start_seconds':-2,
             'knots':[{'seconds':0,'quarter':0},{'seconds':2,'quarter':4},{'seconds':5,'quarter':8}],
             'steady_tempo_bpm':120}
        new=rebase_timing(old,.5)
        # 小节划分与拍速层级纠错：修改，原多余局部名称保留，采用两张映射对比秒时间。
        # a,b=TempoMap=score.TempoMap(old['knots']),score.TempoMap(new['knots'])
        a,b=score.TempoMap(old['knots']),score.TempoMap(new['knots'])
        for tick in (0,480,1920,3840,5760):
            self.assertAlmostEqual(a.quarters_to_seconds(tick/480-4),b.quarters_to_seconds(tick/960))
        self.assertEqual(new['score_start_quarter'],0)
        self.assertAlmostEqual(b.tempo_at(2),60)
        self.assertAlmostEqual(b.tempo_at(4),40)

    def test_basic_and_robust_timing_use_same_review_resolver(self):
        analysis={'source_sha256':'x'*64,'beat_times_seconds':[i*.5 for i in range(25)],
                  'meter':{'selected':'4/4','phase':0},'tempo':{'bpm':120}}
        reviewed={'version':1,'quarter_scale':.5,'status':'reviewed'}
        with patch('metrical_timing.reviewed_beat_level',return_value=reviewed):
            for _,t in (score.make_timing(analysis),music.robust_timing(analysis,[],[])):
                mapping=score.TempoMap(t['knots'])
                self.assertAlmostEqual(mapping.tempo_at(t['score_start_quarter']),60)

    def test_invalid_layer_is_rejected(self):
        with self.assertRaises(ValueError):
            rebase_timing(vocal_fixture()['timing'],.3)

    def test_heading_uses_selected_quarter_tempo_when_raw_pulse_is_double(self):
        p=vocal_fixture();p['overrides']['tempo']=None
        p['timing']=rebase_timing(p['timing'],.5)
        self.assertEqual(p['audio_analysis']['tempo']['bpm'],120)
        self.assertEqual(selected_quarter_tempo(p),60)


class RebarMusicTests(unittest.TestCase):
    def test_grace_and_anchor_playback_lengths_are_preserved(self):
        old=vocal_fixture()
        pieces=[{'id':'grace','source_note_id':'grace','start_seconds':.2,'end_seconds':.25,
                 'pitch_midi':62,'grace':True,'anchor_id':'main','lyric_index':None,'role':'grace'},
                {'id':'main','source_note_id':'main','start_seconds':.25,'end_seconds':.75,
                 'pitch_midi':64,'grace':False,'lyric_index':None,'role':'main'}]
        events,notes,stats=music.musical_quantize(pieces,score.TempoMap(old['timing']['knots']),old['timing'],4)
        old.update(events=events,quantized_notes=notes,statistics=stats)
        new=derive_vocal(old,correction())
        self.assertTrue(compare_sounding_time(old,{},new,{})['valid'])
        grace,main=new['quantized_notes']
        self.assertEqual(grace['playback_end_tick'],main['playback_start_tick'])
        self.assertEqual(grace['anchor_id'],main['id'])
        self.assertAlmostEqual(grace['grace_steal_percent'],notes[0]['grace_steal_percent'])

    def test_two_old_bars_become_one_four_four_bar_without_slowing_notes(self):
        old=vocal_fixture();saved=deepcopy(old);new=derive_vocal(old,correction())
        self.assertEqual(old,saved)
        self.assertEqual(new['timing']['meter'],[4,4])
        self.assertEqual(new['statistics']['measure_count'],2)
        self.assertEqual(new['statistics']['bar_ticks'],1920)
        self.assertAlmostEqual(SongClock(new).seconds(1920),4)
        self.assertEqual([n['pitch_midi'] for n in new['quantized_notes']],[64,67])
        check=compare_sounding_time(old,{},new,{})
        self.assertTrue(check['valid'],check)
        self.assertEqual(check['maximum_onset_release_error_seconds'],0)

    def test_old_bar_tie_is_removed_but_new_bar_tie_is_preserved(self):
        new=derive_vocal(vocal_fixture(),correction())
        a=[e for e in new['events'] if e.get('piece_id')=='a']
        self.assertEqual(len(a),1)
        self.assertEqual(a[0]['ties'],[])
        b=[e for e in new['events'] if e.get('piece_id')=='b']
        self.assertEqual([e['measure'] for e in b],[1,2])
        self.assertEqual(b[0]['ties'],['start'])
        self.assertEqual(b[-1]['ties'],['stop'])
        self.assertEqual(b[0]['lyric']['text'],'风')

    def test_odd_old_bar_tail_is_padded_with_rest_without_extending_music(self):
        old=vocal_fixture(seconds=6);new=derive_vocal(old,correction())
        self.assertEqual(old['statistics']['measure_count'],3)
        self.assertEqual(new['statistics']['measure_count'],2)
        self.assertTrue(compare_sounding_time(old,{},new,{})['valid'])
        self.assertIsNone(new['events'][-1]['pitch_midi'])

    def test_lyric_extends_and_mapping_reference_only_new_events(self):
        new=derive_vocal(vocal_fixture(),correction())
        events={e['id']:e for e in new['events']}
        for item in new['lyric_mapping']['mapping']:
            self.assertTrue(all(identity in events for identity in item['event_ids']))
        a=[e for e in new['events'] if e.get('piece_id')=='a']
        self.assertIsNone(a[0]['lyric']['extend'])
        b=[e for e in new['events'] if e.get('piece_id')=='b']
        self.assertEqual(b[0]['lyric']['extend'],'start')
        self.assertEqual(b[-1]['lyric']['extend'],'stop')

    def test_mid_bar_modulation_is_rejected_instead_of_labelled_a_bar_early(self):
        old=vocal_fixture()
        old['notation']['key_segments']=[{'start_tick':1920,'start_measure':2}]
        with self.assertRaisesRegex(ValueError,'小节中途'):
            derive_vocal(old,correction())

    def test_real_pitch_and_seconds_changes_are_detected(self):
        old=vocal_fixture();new=derive_vocal(old,correction())
        wrong=deepcopy(new);wrong['quantized_notes'][0]['pitch_midi']+=1
        self.assertFalse(compare_sounding_time(old,{},wrong,{})['valid'])
        wrong=deepcopy(new);wrong['quantized_notes'][0]['start_tick']+=120
        self.assertFalse(compare_sounding_time(old,{},wrong,{})['valid'])

    def test_source_guard_allows_only_deterministic_timing_derivative(self):
        old=vocal_fixture();new=derive_vocal(old,correction())
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'original.json';score.save_json(path,old)
            binding={'vocal_project':str(path),'vocal_project_sha256':'b'*64,'sources':{'mix':{'sha256':'a'*64}}}
            self.assertTrue(validate_vocal_snapshot(new,binding))
            new['quantized_notes'][0]['pitch_midi']+=1
            self.assertFalse(validate_vocal_snapshot(new,binding))

    def test_tick_conversion_keeps_frets_pitch_seconds_and_threshold(self):
        old={'start_tick':1920,'end_tick':3840,'measure':2,'pitch_midi':60,'fret':3,
             'start_seconds':2,'minimum_duration_measures':8,'bar_ticks':1920,
             'protected_silence_gaps':[[1920,2400]],'measures':[1,2,3,4]}
        new=scale_tree(old,.5,1920)
        self.assertEqual((new['start_tick'],new['end_tick'],new['measure']),(960,1920,1))
        self.assertEqual(new['protected_silence_gaps'],[[960,1200]])
        self.assertEqual(new['measures'],[1,2])
        self.assertEqual((new['pitch_midi'],new['fret'],new['start_seconds'],new['minimum_duration_measures']),(60,3,2,8))

    def test_preserved_short_vocal_gets_four_underlines(self):
        e={'id':'short','type':'64th','offset_ticks':0,'duration_ticks':30,'grace':False}
        self.assertEqual([r['level'] for r in score.jianpu_beam_groups([e],480)],[1,2,3,4])

    def test_xml_and_midi_use_new_notation_tempo_and_same_sounding_seconds(self):
        import mido
        old=vocal_fixture();new=derive_vocal(old,correction())
        arrangement={'instrument':'piano','configuration':{},'pedal':[],
            'notes':[{'id':'p','start_tick':960,'end_tick':1440,'pitch_midi':48,'hand':'left','finger':5,'velocity':80}]}
        # 小节划分与拍速层级纠错：修改，原不完整夹具保留；补齐独立XML所需的无和声/段落上下文。
        # shared={'input_binding':{'vocal_project_sha256':'b'*64}}
        shared={'input_binding':{'vocal_project_sha256':'b'*64},'sections':[],'harmony':[]}
        root,_=build_musicxml(shared,new,arrangement)
        parsed,check=parse_musicxml_notes(root)
        self.assertTrue(check['valid'],check)
        self.assertEqual(check['measure_lengths'],[1920,1920])
        self.assertEqual(root.findtext('./part/measure/attributes/time/beats'),'4')
        self.assertEqual(float(root.find('./part/measure/direction/sound').get('tempo')),60)
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'accompaniment.mid';write_midi(path,arrangement,new)
            elapsed=0;attack=release=None
            for message in mido.MidiFile(path):
                elapsed+=message.time
                if message.type=='note_on' and message.velocity:attack=elapsed
                if message.type=='note_off':release=elapsed
            self.assertAlmostEqual(attack,2)
            self.assertAlmostEqual(release,3)


class TemplateScopeTests(unittest.TestCase):
    def test_full_sixteen_source_attacks_are_not_truncated_to_fourteen(self):
        v=derive_vocal(vocal_fixture(),correction())
        attacks=[{'seconds':i*.25,'strength':1.,'pitches':[]} for i in range(16)]
        f=SimpleNamespace(rms=np.ones(32),attacks=attacks,window=lambda a,b:slice(0,32))
        sections=[{'kind':'vocal','start_seconds':0,'end_seconds':8}]
        rows=measure_textures({'six_piano':f},SongClock(v),v,sections)
        self.assertEqual(len(rows[0]['attacks']),16)
        self.assertEqual(rows[0]['attack_grid_ticks'],list(range(0,1920,120)))

    def test_old_eighth_cycle_becomes_two_beats_of_sixteenths(self):
        p=next(p for p in library()['patterns'] if p['id']=='arp_4_4_up')
        translated=notation_pattern({'grid_correction':{'quarter_scale':.5}},p)
        self.assertEqual(translated['step_ticks'],120)
        self.assertEqual(len(translated['slots'])*translated['step_ticks'],960)
        self.assertEqual(p['step_ticks'],240)

    def test_second_cycle_in_same_bar_has_correct_scope_and_detects_missing_attack(self):
        old={'configuration':{'regular_rhythm_policy':{}},'right_hand_patterns':{'measures':[
            {'measure':2,'pattern_id':'arp_4_4_up','phase_tick':0,'leading_rest_end_tick':1920,
             # 小节划分与拍速层级纠错：修改，原缺少规整记录的夹具尾行保留。
             # 'active_end_tick':3840,'protected_silence_gaps':[]}]},'notes':[]}
             'active_end_tick':3840,'protected_silence_gaps':[]}]},'notes':[], 'regular_rhythm':{'preserved_notes':[]}}
        g=scale_tree(old,.5,1920);g['grid_correction']={'quarter_scale':.5}
        g['notes']=[{'id':str(i),'start_tick':960+i*120,'end_tick':1080+i*120,
            'right_hand_pattern_id':'arp_4_4_up','right_hand_slot':i} for i in range(8)]
        g['attack_events']=[{'start_tick':960+i*120,'right_hand_duration_ticks':120,
            'right_hand_duration_source':'regular_pattern_slot'} for i in range(8)]
        g['regular_rhythm']={'preserved_notes':[]}
        rebase_pattern_plans(old,g,.5,1920)
        s={'statistics':{'bar_ticks':1920}}
        self.assertTrue(validate_structured_rhythm(s,g)['valid'])
        g['notes'].pop(3)
        self.assertFalse(validate_structured_rhythm(s,g)['valid'])


if __name__=='__main__':unittest.main()
