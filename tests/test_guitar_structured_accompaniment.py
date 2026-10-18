"""结构稳定伴奏与人声合播：已知节奏、结构、夹位及实际音频样本的反例。"""
# 结构稳定伴奏与人声合播：新增独立音乐真值，不以雨天自动分析作为准确率真值。
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from test_guitar_right_hand_patterns import known
from guitar_pattern_grid import pattern_schedule,pattern_duration,validate_regular_pattern
from guitar_structure_patterns import (score_pattern,weighted_sources,structure_phrases,
    structured_phrase_plan,ornament_aliases,display_chord,apply_structured_patterns)
from guitar_right_hand_patterns import library,measure_notes
from guitar_regular_rhythm import apply_regular_patterns
from guitar_capo import plan_capo,apply_capo,capo_at,validate_capo
from accompaniment_export import build_musicxml
from accompaniment_vocal_playback import align_samples,prepare_vocals,write_singing_preview,validate_singing_preview
from score_export import sha256


# 结构稳定伴奏与人声合播：新增可控来源，起音直接给定，不调用旧编配统计。
def evidence(guitar, offsets, measure=1, phase=0):
    guitar['source_rhythm_evidence']={'measures':[{'measure':measure,'source':'accompaniment',
        'active':True,'rms':1.,'attacks':[{'tick':(measure-1)*1920+t+phase,'strength':1.,'pitches':[]} for t in offsets]}]}


def pattern(identity):
    return next(p for p in library()['patterns'] if p['id']==identity)


# 结构稳定伴奏与人声合播：新增9小节已知转调；新调8小节，旋律与和声明确支持。
def modulation_fixture(new_bars=8):
    s,v,g=known();total=(new_bars+1)*1920
    for stats in (s['statistics'],v['statistics']):
        stats.update(total_ticks=total,measure_count=new_bars+1)
    v['notation']['key_segments'][1]['evidence']={'accepted_change':True}
    s['harmony'][1]['end_tick']=total
    v['quantized_notes']=[{'id':'d','pitch_midi':66,'start_tick':1920,'end_tick':total,'role':'main','grace':False}]
    return s,v,g


class SourceRhythmTests(unittest.TestCase):
    # 结构稳定伴奏与人声合播：新增均匀和移相八分不能被多填十六分“提高匹配”反例。
    def test_exact_eighth_does_not_reward_extra_sixteenths(self):
        s,_,g=known();evidence(g,range(0,1920,240))
        a=score_pattern(s,g,[1],pattern('arp_4_4_up'))
        b=score_pattern(s,g,[1],pattern('arp_4_4_sixteenth_up'))
        self.assertLess(a['score'],b['score'])
        self.assertGreater(b['components']['extra'],0)

    def test_shifted_eighth_is_still_eighth_density(self):
        s,_,g=known();evidence(g,range(0,1920,240),phase=120)
        a=score_pattern(s,g,[1],pattern('arp_4_4_up'))
        b=score_pattern(s,g,[1],pattern('arp_4_4_sixteenth_up'))
        self.assertLess(a['score'],b['score'])
        self.assertEqual(a['source_details'][0]['matched_attack_pairs'],8)

    def test_true_sixteenths_select_sixteenth_candidate(self):
        s,_,g=known();evidence(g,range(0,1920,120))
        a=score_pattern(s,g,[1],pattern('arp_4_4_sixteenth_up'))
        self.assertLess(a['score'],score_pattern(s,g,[1],pattern('arp_4_4_up'))['score'])
        self.assertEqual(a['source_details'][0]['matched_attack_pairs'],16)

    def test_mixed_known_attacks_win_over_uniform_eighth(self):
        s,_,g=known();p=pattern('arp_4_4_mixed_back')
        evidence(g,[0,120,240,480,600,720,960,1080,1200,1440,1560,1680])
        self.assertLess(score_pattern(s,g,[1],p)['score'],score_pattern(s,g,[1],pattern('arp_4_4_up'))['score'])

    def test_old_arrangement_density_does_not_change_score(self):
        s,_,g=known();evidence(g,range(0,1920,240));p=pattern('arp_4_4_up')
        before=score_pattern(s,g,[1],p)
        g['notes']=[{'start_tick':t,'pitch_midi':80} for t in range(0,1920,30)]
        self.assertEqual(before,score_pattern(s,g,[1],p))

    def test_inactive_stem_has_no_vote_and_correlated_group_has_fixed_mass(self):
        rows=[{'source':s,'active':True,'rms':1.,'attacks':[{}]} for s in ('accompaniment','six_guitar','six_piano','other','six_other','bass','mix')]
        result=dict((r['source'],w) for r,w in weighted_sources(rows))
        self.assertAlmostEqual(sum(result[s] for s in ('six_guitar','six_piano','other','six_other')),.4)
        rows[1]['active']=False
        self.assertNotIn('six_guitar',[r['source'] for r,w in weighted_sources(rows)])


class GridAndStructureTests(unittest.TestCase):
    # 结构稳定伴奏与人声合播：新增实际时值真值与六小节乐句，不依靠四小节机械分段。
    def test_full_sixteenth_has_sixteen_quarter_beat_subdivisions(self):
        p=pattern('arp_4_4_sixteenth_up');rows=pattern_schedule(p)
        self.assertEqual([r['offset'] for r in rows],list(range(0,1920,120)))
        self.assertEqual([r['duration'] for r in rows],[120]*16)
        self.assertTrue(validate_regular_pattern(p)['valid'])

    def test_mixed_back_eighth_stems_are_not_marked_sixteenth(self):
        p=pattern('arp_4_4_mixed_back')
        self.assertEqual([r['duration'] for r in pattern_schedule(p)],[120,120,240]*4)
        self.assertEqual(pattern_duration(p,2),240)

    def test_generated_mixed_c_plays_correct_strings_and_pitches(self):
        s,_,g=known();g['configuration']['structure_policy']={'version':1}
        notes,_,_,_=measure_notes(s,g,1,{'pattern_id':'arp_4_4_mixed_back','phase_tick':0},1)
        self.assertEqual([n['start_tick'] for n in notes],[0,120,240,480,600,720,960,1080,1200,1440,1560,1680])
        self.assertEqual([n['pitch_midi'] for n in notes[:6]],[48,55,60,64,55,60])
        self.assertEqual([n['string'] for n in notes[:6]],[5,3,2,1,3,2])

    def test_one_lyric_phrase_can_span_six_bars(self):
        s,v,_=known();s['sections'][0]['end_tick']=11520
        v['lyrics']['characters']=[{'line_index':0,'text':'春风'}]
        v['quantized_notes']=[{'line_index':0,'lyric_index':0,'role':'main','start_tick':0,'end_tick':11520,'pitch_midi':64}]
        phrases,_=structure_phrases(s,v,list(range(1,7)))
        self.assertEqual([p['measures'] for p in phrases],[[1,2,3,4,5,6]])

    def test_transposed_repeat_reuses_compatible_main_pattern(self):
        s,v,g=known();v['lyrics']['characters']=[{'line_index':i,'text':t} for i in (0,1) for t in ('春','风')]
        v['quantized_notes']=[{'line_index':i,'lyric_index':i*2+j,'role':'main','start_tick':i*1920+j*480,
            'end_tick':i*1920+(j+1)*480,'pitch_midi':64+i+j*3} for i in (0,1) for j in (0,1)]
        evidence(g,range(0,1920,240));row=deepcopy(g['source_rhythm_evidence']['measures'][0]);row['measure']=2
        for a in row['attacks']:a['tick']+=1920
        g['source_rhythm_evidence']['measures'].append(row);g['_structure_vocal']=v
        plans=structured_phrase_plan(s,g,[1,2])
        self.assertEqual(plans[0]['repeat_group'],plans[1]['repeat_group'])
        self.assertEqual(plans[0]['pattern_id'],plans[1]['pattern_id'])
        self.assertTrue(all(p['repeat_action']=='reuse_main_pattern' for p in plans))

    def test_clear_rhythm_change_in_repeat_remains_a_documented_variant(self):
        # 结构稳定伴奏与人声合播：修改测试夹具，单音没有重复音程证据；用两个相同音程的主音。
        # s,v,g=known();v['lyrics']['characters']=[{'line_index':i,'text':'春风'} for i in (0,1)]
        # v['quantized_notes']=[{'line_index':i,'lyric_index':i,'role':'main','start_tick':i*1920,'end_tick':(i+1)*1920,'pitch_midi':64+i} for i in (0,1)]
        s,v,g=known();v['lyrics']['characters']=[{'line_index':i,'text':t} for i in (0,1) for t in ('春','风')]
        v['quantized_notes']=[{'line_index':i,'lyric_index':i*2+j,'role':'main','start_tick':i*1920+j*480,
            'end_tick':i*1920+(j+1)*480,'pitch_midi':64+i+j*3} for i in (0,1) for j in (0,1)]
        evidence(g,range(0,1920,480));row=deepcopy(g['source_rhythm_evidence']['measures'][0]);row['measure']=2
        row['attacks']=[{'tick':1920+t,'strength':1.,'pitches':[]} for t in range(0,1920,120)]
        g['source_rhythm_evidence']['measures'].append(row);g['_structure_vocal']=v
        plans=structured_phrase_plan(s,g,[1,2])
        self.assertTrue(any(p['repeat_action']=='original_rhythm_variant' for p in plans))
        self.assertNotEqual(plans[0]['pattern_id'],plans[1]['pattern_id'])

    def test_non_four_four_never_loads_four_four_evidence(self):
        s,v,g=known();s['timing']['meter']=[3,4]
        with patch('guitar_structure_patterns.collect_rhythm_evidence',side_effect=AssertionError('不应读取4/4来源')):
            apply_structured_patterns(s,v,g,ROOT/'test_outputs')
        self.assertEqual(g['configuration']['rows_measures'],4)
        self.assertEqual(g['structure_fallback']['meter'],[3,4])

    def test_edit_reexport_is_idempotent(self):
        s,v,g=known();g['structure_stability']={'version':1};g['notes'][0]['velocity']=99
        before=deepcopy(g)
        apply_structured_patterns(s,v,g,ROOT/'test_outputs')
        self.assertEqual(before,g)


class OrnamentTests(unittest.TestCase):
    # 结构稳定伴奏与人声合播：新增短挂留沿小和弦及性质音/转位不误简化反例。
    def test_short_sus_in_minor_context_keeps_minor_base_and_original_harmony(self):
        s,_,g=known();s['harmony'][0].update(quality='sus2',end_tick=480)
        s['harmony'][1].update(root_pc=0,bass_pc=0,quality='m',pitch_classes=[0,3,7],start_tick=480)
        before=deepcopy(s);g['ornament_display']={'aliases':ornament_aliases(s)}
        self.assertEqual(display_chord(s,g,s['harmony'][0])['quality'],'m')
        self.assertEqual(before,s)

    def test_seventh_slash_and_long_sus_are_not_ornament_aliases(self):
        for quality,bass,duration in (('7',0,240),('sus2',4,240),('sus4',0,960)):
            s,_,_=known();s['harmony'][0].update(quality=quality,bass_pc=bass,end_tick=duration)
            s['harmony'][1].update(root_pc=0,bass_pc=0,start_tick=duration)
            self.assertEqual(ornament_aliases(s),{})

    def test_minor_add9_is_not_turned_into_major(self):
        s,_,_=known();s['harmony'][0].update(quality='madd9',end_tick=240)
        s['harmony'][1].update(root_pc=0,bass_pc=0,quality='',start_tick=240)
        self.assertEqual(ornament_aliases(s),{})


class CapoTests(unittest.TestCase):
    # 结构稳定伴奏与人声合播：新增阈值两侧、无空档换夹、XML只改图不改音反例。
    def test_seven_bars_keep_capo_eight_bars_change(self):
        s,v,_=modulation_fixture(7);self.assertEqual(len(plan_capo(s,v,0)[0]),1)
        s,v,_=modulation_fixture(8);plan,meta=plan_capo(s,v,0)
        self.assertEqual([(p['start_tick'],p['capo_fret']) for p in plan],[(0,0),(1920,2)])
        self.assertFalse(meta['sliding_capo_operation_time_gate'])

    def test_long_key_label_without_vocal_support_cannot_change_capo(self):
        s,v,_=modulation_fixture();v['quantized_notes'][0]['pitch_midi']=65
        self.assertEqual(len(plan_capo(s,v,0)[0]),1)

    def test_capo_refingering_preserves_pitch_onset_release_velocity(self):
        s,v,g=modulation_fixture();fields=('id','pitch_midi','start_tick','end_tick','velocity')
        before=[tuple(n[k] for k in fields) for n in g['notes']]
        apply_capo(s,v,g)
        self.assertEqual(before,[tuple(n[k] for k in fields) for n in g['notes']])
        self.assertEqual(capo_at(g,1920),2)
        self.assertTrue(validate_capo(g,v)['valid'])

    def test_musicxml_wrong_fret_is_caught_even_when_capo_labels_correct(self):
        s,v,g=modulation_fixture();apply_capo(s,v,g)
        root,_=build_musicxml(s,v,g)
        self.assertTrue(validate_capo(g,v,root)['valid'])
        node=root.find('./part/measure/note/notations/technical/fret');node.text=str(int(node.text)+1)
        self.assertIn('musicxml_capo_actual_sound_mismatch',str(validate_capo(g,v,root)['errors']))


class VoiceClockTests(unittest.TestCase):
    # 结构稳定伴奏与人声合播：新增原样本已知脉冲，覆盖正补偿、负裁剪和实源错位检测。
    def test_positive_offset_pads_exactly_known_impulse(self):
        source=np.array([1.,2.,3.],dtype=np.float32)
        actual,meta=align_samples(source,10,10,.2,6)
        np.testing.assert_array_equal(actual[:,0],[0,0,1,2,3,0])
        self.assertEqual(meta['offset_samples'],2)

    def test_negative_offset_crops_source_without_inserting_fake_audio(self):
        actual,meta=align_samples(np.array([1.,2.,3.,4.]),10,10,-.2,3)
        np.testing.assert_array_equal(actual[:,0],[3,4,0])
        self.assertEqual(meta['source_crop_samples'],2)

    def test_resampling_and_rounding_keep_exact_sheet_duration(self):
        actual,meta=align_samples(np.ones((10,2)),10,20,.026,24)
        self.assertEqual(actual.shape,(24,2))
        self.assertEqual(meta['destination_pad_samples'],1)

    def test_actual_source_shift_is_rejected_even_with_correct_metadata(self):
        s,v,_=known();folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            out=Path(tmp);(out/'guitar').mkdir()
            source=np.zeros((32000,2),np.float32);source[1000:1020]=.4
            sf.write(out/'source.wav',source,8000,subtype='FLOAT')
            s['input_binding']['sources']['vocals']={'path':str(out/'source.wav'),'sha256':sha256(out/'source.wav'),'offset_seconds':.01}
            voice,vm=prepare_vocals(out,s,v)
            sf.write(out/'guitar/preview.wav',np.zeros(32000),8000,subtype='PCM_16')
            write_singing_preview(out/'guitar',out/'guitar/preview.wav',voice,vm)
            self.assertTrue(validate_singing_preview(out/'guitar',s,v)['valid'])
            shifted=np.roll(voice,80,axis=0)
            sf.write(out/'audio/vocals_aligned.wav',shifted,8000,subtype='PCM_16')
            errors=validate_singing_preview(out/'guitar',s,v)['errors']
            self.assertIn('aligned_voice_samples_differ_from_original_source',errors)


if __name__=='__main__':unittest.main()
