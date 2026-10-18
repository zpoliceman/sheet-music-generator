"""原曲器乐旋律骨干重提取：新增跨音区、多声部、起音与保护边界的音乐反例。"""
from copy import deepcopy
from pathlib import Path
import sys
# 原曲器乐旋律骨干重提取：新增单文件测试也可找到生产模块，完整测试入口原有路径保持。
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import unittest
import numpy as np
from instrumental_source_melody import (combine_tracks,continuous_voice,voice_events,structural_anchors,
    revised_guitar,POLICY,fingerprint,superseded_ids)
from test_guitar_instrumental_register import music
from accompaniment_analysis import SongClock

# 原曲器乐旋律骨干重提取：新增合成的多音检测证据，不拿歌曲答案或程序输出构造期望值。
def track(count=44,name='other'):
    return {'times':np.arange(count)*.04644,'note':np.zeros((count,88)),
        'onset':np.zeros((count,88)),'spectral':np.zeros((count,88)),'source':name}


# 原曲器乐旋律骨干重提取：新增独立音符发生器，起音／持续／包络可分别设置。
def tone(t,pitch,start,end,confidence=.8,amplitude=1.,attack=.9):
    t['note'][start:end,pitch-21]=confidence;t['spectral'][start:end,pitch-21]=amplitude
    if start<len(t['times']):t['onset'][start,pitch-21]=attack
    return t


# 原曲器乐旋律骨干重提取：新增完整声部提取测试入口，持续主音与逐攻击伴奏分开检查。
def detected(t):
    times=t['times'];e,o,a,w=combine_tracks([t],times);path=continuous_voice(e,times,o)
    s={'id':'test_section','kind':'intro','start_seconds':0.,'end_seconds':float(times[-1]+.04644)}
    return voice_events(times,path,e,o,a,w,[t],s),path


class SourceMelodyTests(unittest.TestCase):
    # 原曲器乐旋律骨干重提取：新增快拍和缺证据跨曲反例，不能以遇见的慢拍阈值处理所有歌曲。
    def test_fast_sixteenth_melody_is_not_deleted_by_fixed_milliseconds(self):
        t=track(count=8)
        for a,p in [(0,76),(2,78),(4,80),(6,78)]:tone(t,p,a,a+2,.95,1.)
        times=t['times'];e,o,active,winner=combine_tracks([t],times)
        path=continuous_voice(e,times,o,quarter_seconds=.4)
        section={'id':'fast','kind':'intro','start_seconds':0.,'end_seconds':float(times[-1]+.04644),'quarter_seconds':.4}
        rows=voice_events(times,path,e,o,active,winner,[t],section)
        self.assertEqual([r['pitch_midi'] for r in rows],[76,78,80,78])

    def test_audible_section_without_reliable_backbone_keeps_old_melody(self):
        s,v,g=music();plan={'sections':[{'id':'s','kind':'intro','start_tick':0,'end_tick':1920,
            'decision':'preserve_old_melody_due_to_insufficient_evidence'}],'notes':[]}
        result,replaced=revised_guitar(s,v,g,plan)
        self.assertEqual(replaced,[])
        self.assertEqual({n['id'] for n in result['notes']},{n['id'] for n in g['notes']})

    # 原曲器乐旋律骨干重提取：新增高阶泛音及近静音分轨伪高音的实际故障反例。
    def test_fourth_harmonic_does_not_replace_fundamental(self):
        t=tone(track(),63,0,44,.82,1.,.9);tone(t,87,0,44,.75,.30,.8)
        e,_,_,_=combine_tracks([t],t['times'])
        self.assertLess(e[:,66].max(),.13)
        self.assertEqual(set(continuous_voice(e,t['times'])),{63})

    def test_nearly_silent_stem_cannot_outvote_original_frequency(self):
        original=tone(track(),76,0,44,.8,1.)
        tone(original,88,0,44,.4,.02)
        false=tone(track(name='six_guitar'),88,0,44,.99,.001)
        e,_,_,_=combine_tracks([original,false],original['times'])
        self.assertEqual(float(e[:,67].max()),0.)

    def test_duplicate_stem_does_not_increase_support(self):
        original=tone(track(),76,0,44,.8,1.)
        copy=deepcopy(original);copy['source']='six_piano'
        one=combine_tracks([original,copy],original['times'])[0]
        two=combine_tracks([original,copy,deepcopy(copy)],original['times'])[0]
        np.testing.assert_array_equal(one,two)

    # 原曲器乐旋律骨干重提取：新增内声部起音不切断长主音的反例。
    def test_sustained_lead_is_not_replaced_at_arpeggio_attacks(self):
        t=tone(track(),79,0,44,.78)
        for a,p in [(5,60),(12,64),(19,67),(26,60),(33,64)]:tone(t,p,a,min(a+7,44),.92,.65)
        notes,path=detected(t)
        self.assertEqual(set(path),{79});self.assertEqual([n['pitch_midi'] for n in notes],[79])

    def test_new_descending_attack_replaces_old_resonance(self):
        t=tone(track(),84,0,12,.8)
        tone(t,84,12,30,.22,.17,0.)
        tone(t,80,12,44,.85,1.,.95)
        notes,path=detected(t)
        self.assertIn(80,path[14:]);self.assertEqual(notes[-1]['pitch_midi'],80)
        self.assertLess(notes[-1]['source_start_seconds'],.7)

    def test_weak_synchronous_octave_partial_is_not_melody(self):
        t=tone(track(),76,0,44,.88,1.)
        tone(t,88,0,44,.50,.10,.75)
        e,_,_,_=combine_tracks([t],t['times'])
        self.assertLess(e[:,88-21].max(),.15)
        self.assertEqual(set(continuous_voice(e,t['times'])),{76})

    def test_independently_strong_high_note_is_not_forced_down(self):
        t=tone(track(),76,0,44,.55,.30,.6)
        tone(t,88,0,44,.86,1.,.95)
        notes,path=detected(t)
        self.assertEqual(set(path),{88});self.assertEqual(notes[0]['pitch_midi'],88)

    def test_separation_artifact_requires_original_support(self):
        original=tone(track(),67,0,44,.8)
        separated=tone(track(name='six_guitar'),94,0,44,.99,8.)
        e,_,_,_=combine_tracks([original,separated],original['times'])
        self.assertEqual(float(e[:,94-21].max()),0.)

    def test_quiet_tail_is_not_amplified_into_melody(self):
        t=tone(track(),76,0,30,.8,1.)
        tone(t,89,34,44,.99,.0001)
        e,_,active,_=combine_tracks([t],t['times'])
        self.assertEqual(float(active[34:,89-21].max()),0.)

    def test_transposition_uses_same_contour_without_fixed_midi_range(self):
        output=[]
        for shift in (-17,0,7):
            t=tone(track(),76+shift,0,18,.9);tone(t,78+shift,18,32,.9);tone(t,76+shift,32,44,.9)
            notes,path=detected(t);output.append([n['pitch_midi']-shift for n in notes])
        self.assertEqual(output[0],output[1]);self.assertEqual(output[1],output[2])
        self.assertEqual(output[0],[76,78,76])

    def test_low_register_solo_is_not_removed_by_old_60_cutoff(self):
        t=tone(track(),48,0,22,.9);tone(t,50,22,44,.9)
        notes,path=detected(t)
        self.assertEqual([n['pitch_midi'] for n in notes],[48,50])

    def test_bass_after_upper_voice_is_not_new_upper_melody(self):
        t=tone(track(),79,0,29,.9);tone(t,40,29,44,.9)
        notes,path=detected(t)
        self.assertNotIn(40,[n['pitch_midi'] for n in notes])

    def test_false_repeated_onsets_without_envelope_growth_are_ignored(self):
        t=tone(track(),76,0,44,.9)
        t['onset'][16,55]=.88;t['onset'][30,55]=.88
        notes,_=detected(t)
        self.assertEqual(len(notes),1)

    def test_true_same_pitch_reattack_retains_two_notes(self):
        t=tone(track(),76,0,44,.9)
        t['spectral'][20:30,55]=2.5;t['onset'][20,55]=.94
        notes,_=detected(t)
        self.assertEqual(len(notes),2);self.assertEqual([n['pitch_midi'] for n in notes],[76,76])

    def test_clear_short_upper_onset_recovers_structural_pitch(self):
        t=tone(track(),75,0,44,.9,.8)
        tone(t,80,15,26,.72,1.2,.94)
        e,o,a,w=combine_tracks([t],t['times']);path=np.full(44,75)
        s={'id':'s','kind':'intro','start_seconds':0.,'end_seconds':2.}
        rows=[dict(source_start_seconds=0.,source_end_seconds=2.,pitch_midi=75,source='other',section='intro',section_id='s',activation=.9,onset_activation=.9,role='instrumental_melody')]
        result=structural_anchors(rows,t['times'],path,a,o,[t],s)
        self.assertIn(80,[r['pitch_midi'] for r in result]);self.assertEqual(rows[0]['source_end_seconds'],2.)

    def test_short_inner_voice_dip_is_removed_but_bass_ledger_is_unrelated(self):
        t=tone(track(),76,0,44,.9);times=t['times'];s={'id':'s','kind':'intro','start_seconds':0.,'end_seconds':2.}
        rows=[dict(source_start_seconds=a,source_end_seconds=b,pitch_midi=p) for a,b,p in [(0.,.6,76),(.6,.9,60),(.9,2.,78)]]
        result=structural_anchors(rows,times,np.full(44,76),t['note'],t['onset'],[t],s)
        self.assertEqual([r['pitch_midi'] for r in result],[76,78])

    def test_silence_generates_no_notes(self):
        t=track();notes,path=detected(t)
        self.assertEqual(notes,[]);self.assertEqual(set(path),{0})

    def test_original_track_time_offset_is_respected(self):
        t=tone(track(),76,0,22,.9);t['times']=t['times']+1.
        e,_,_,_=combine_tracks([t],np.arange(44)*.04644)
        # 原曲器乐旋律骨干重提取：偏移前不得使用未来第一帧；此断言检查真实声学时间而非文件路径。
        self.assertEqual(float(e[:20].max()),0.)

    def test_only_validated_revision_can_supersede_old_melody(self):
        g={'instrumental_source_backbone':{'superseded_note_ids':['old_melody']}}
        self.assertEqual(superseded_ids(g,{'valid':False}),set())
        self.assertEqual(superseded_ids(g,{'valid':True}),{'old_melody'})

    def test_guitar_revision_keeps_every_bass_harmony_and_normal_note(self):
        s,v,g=music();clock=SongClock(v)
        plan={'sections':[{'id':'s','kind':'intro','start_tick':0,'end_tick':1920}],
            'notes':[dict(id='bone1',pitch_midi=87,start_tick=0,end_tick=480,duration_ticks=480,
            source_start_seconds=clock.seconds(0),source_end_seconds=clock.seconds(480),section_id='s',section='intro',source='other')]}
        before=deepcopy((s,v,g));new,replaced=revised_guitar(s,v,g,plan)
        self.assertEqual((s,v,g),before);present={n['id']:n for n in new['notes']}
        for note in g['notes']:
            if note['id'] not in replaced:self.assertEqual(note,present[note['id']])
        self.assertEqual(set(replaced),{'m0','m1','m2'})
        self.assertEqual(present['guitar_bone1']['source_backbone_pitch_midi'],87)
        self.assertEqual(present['guitar_bone1']['pitch_midi']%12,87%12)

    def test_instrumental_role_inside_singing_is_not_replaced(self):
        s,v,g=music();g['notes'][-1]['role']='instrumental_melody'
        plan={'sections':[{'id':'s','kind':'intro','start_tick':0,'end_tick':1920}],'notes':[]}
        new,replaced=revised_guitar(s,v,g,plan)
        self.assertNotIn('normal',replaced);self.assertIn(g['notes'][-1],new['notes'])

    # 原曲器乐旋律骨干重提取：新增真实XML连梁反例，源骨干替换不能改变相邻已认可唱段的单旗。
    def test_actual_xml_keeps_singing_beam_separate_from_revised_solo(self):
        from accompaniment_export import build_musicxml
        s,v,g=music();s['sections']=[{'kind':'vocal','label':'唱段','start_tick':0,'end_tick':240},
            {'kind':'intro','label':'器乐','start_tick':240,'end_tick':1920},
            {'kind':'vocal','label':'唱段','start_tick':1920,'end_tick':3840}]
        template=deepcopy(g['notes'][-1]);template.update(id='sung_end',start_tick=0,end_tick=240,pitch_midi=60,string=2,fret=1)
        solo={**deepcopy(template),'id':'solo_start','start_tick':240,'end_tick':480,'role':'instrumental_melody'}
        g['notes']=[template,solo];g['instrumental_source_backbone']={'version':1}
        root,_=build_musicxml(s,v,g)
        note=next(n for n in root.iter('note') if n.get('id')=='sung_end_fragment_0')
        self.assertIsNone(note.find('beam'))
