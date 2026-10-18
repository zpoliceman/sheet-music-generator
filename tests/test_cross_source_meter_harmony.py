"""跨曲低音与强拍复用通用修复：低音漏轨、错首拍、半小节漏音的音乐反例。"""
import sys
import unittest
from pathlib import Path
from copy import deepcopy
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from accompaniment_analysis import Features
from harmonic_low_register import quality_window
from source_meter_harmony import phase_from_changes, regrid_observed_entries, apply_phase
from phrase_harmony_arrange import apply_phrase_harmony, validate_phrase_harmony
from test_phrase_harmony_plan import known_music, arrangements


# 跨曲低音与强拍复用通用修复：新增已知实音特征，测试不读样曲或人工参考和弦表。
def feature(pitches, rms):
    data = np.zeros((73, 30))
    for midi, amount in pitches.items():
        data[midi - 24, :] = amount
    return Features(np.linspace(0, 1, 30), data, np.full(30, rms), np.zeros(30), [], {})


class LowRegisterTests(unittest.TestCase):
    def test_silent_bass_does_not_hide_the_guitar_root_and_minor_third(self):
        backing = feature({40: 1., 43: .4, 47: .3, 52: .3}, .08)
        f = {'accompaniment': backing, 'six_guitar': backing, 'bass': feature({39: 1e-8}, 1e-8)}
        result = quality_window(f, 0., 1., {'accompaniment': .8, 'six_guitar': .2})
        self.assertEqual(int(result[5].argmax()), 4)
        self.assertGreater(result[3][7], .08)
        self.assertEqual(result[6]['low_register']['selected_source'], 'accompaniment')

    def test_effective_independent_bass_wins_over_higher_guitar_chord_tones(self):
        f = {'accompaniment': feature({48: 1., 52: .5, 55: .4}, .08),
             'bass': feature({36: .5}, .04)}
        result = quality_window(f, 0., 1., {'accompaniment': 1.})
        self.assertEqual(result[6]['low_register']['selected_source'], 'bass')
        self.assertEqual(int(result[5].argmax()), 0)

    def test_broadband_low_noise_and_tiny_stems_do_not_become_roots(self):
        f = {'accompaniment': feature({m: .001 for m in range(24, 97)}, .08),
             'six_guitar': feature({40: 1e-10}, 1e-8), 'bass': feature({}, 0.)}
        result = quality_window(f, 0., 1., {'accompaniment': .8, 'six_guitar': .2})
        self.assertEqual(float(result[5].sum()), 0.)

    def test_correlated_guitar_copies_do_not_change_bass_confidence(self):
        a = feature({43: 1., 50: .4}, .08)
        base = quality_window({'accompaniment': a}, 0., 1., {'accompaniment': 1.})
        more = quality_window({'accompaniment': a, 'six_guitar': a, 'other': a}, 0., 1.,
                              {'accompaniment': .4, 'six_guitar': .3, 'other': .3})
        np.testing.assert_array_equal(base[5], more[5])


class SourcePhaseTests(unittest.TestCase):
    def music(self, meter, phase, tonic=0):
        # 跨曲低音与强拍复用通用修复：新增多段调内低音，弱半小节有变化、持续与主音回归确认真正首拍。
        rows = []
        for section in range(3):
            for i, pc in enumerate((0, 9, 5, 0)):
                rows.append({'pulse': section*8*meter[0]+i*meter[0]+phase,
                    'pitch_midi': 36+(pc+tonic)%12, 'duration_pulses': meter[0],
                    'relative_strength': .8, 'tonic_pc': tonic, 'section_index': section})
            rows.append({'pulse': section*8*meter[0]+meter[0]/2+phase,
                'pitch_midi': 36+(7+tonic)%12, 'duration_pulses': meter[0]/2,
                'relative_strength': .2, 'tonic_pc': tonic, 'section_index': section})
        return rows

    def test_meter_and_transposition_do_not_require_a_song_specific_phase(self):
        for meter, phase, expected in [([4,4], 3, 480), ([4,4], 0, 0), ([3,4], 2, 480), ([6,8], 5, 240)]:
            for tonic in (0, 1, 8):
                with self.subTest(meter=meter, tonic=tonic):
                    a = phase_from_changes(self.music(meter, phase, tonic), meter)
                    self.assertEqual(a['shift_ticks'], expected)

    def test_reviewed_phase_is_preserved_and_conflicting_audio_is_visible(self):
        a = phase_from_changes(self.music([4,4], 3), [4,4], reviewed=True)
        self.assertEqual(a['shift_ticks'], 0)
        self.assertEqual(a['proposed_shift_pulses'], 1)
        self.assertEqual(a['status'], 'reviewed_phase_preserved')

    def test_sparse_or_ambiguous_music_is_not_silently_shifted(self):
        rows = self.music([4,4], 3)
        self.assertEqual(phase_from_changes(rows[:3], [4,4])['shift_ticks'], 0)
        both = rows + self.music([4,4], 1)
        self.assertEqual(phase_from_changes(both, [4,4])['status'], 'ambiguous_phase_preserved')

    # 跨曲低音与强拍复用通用修复：新增负方向首拍校正的开头独奏保护，不能以夹到0tick掩盖截音。
    def test_negative_phase_adds_whole_bar_room_and_keeps_every_physical_onset(self):
        from accompaniment_analysis import SongClock
        _,v = known_music(bars=2); v['audio_analysis'] = {'duration_seconds': 12.}
        # 跨曲低音与强拍复用通用修复：新增合成歌词所有者，负相位反例验证真实挂字重建而不是空歌词简化。
        v['lyrics']['characters'] = [{'index':n['lyric_index'], 'text':'音'} for n in v['quantized_notes']]
        v['timing'].update(score_start_quarter=0., knots=[{'quarter':0.,'seconds':0.}, {'quarter':24.,'seconds':12.}])
        before = deepcopy(v); old_clock = SongClock(v)
        fixed = apply_phase(v, {'shift_ticks': -480})
        new_clock = SongClock(fixed)
        self.assertGreaterEqual(min(n['start_tick'] for n in fixed['quantized_notes']), 0)
        self.assertEqual(v, before)
        for a,b in zip(v['quantized_notes'], fixed['quantized_notes']):
            self.assertEqual(a['id'], b['id']); self.assertEqual(a['pitch_midi'], b['pitch_midi'])
            self.assertAlmostEqual(old_clock.seconds(a['start_tick']), new_clock.seconds(b['start_tick']), places=10)


class PartialEntryTests(unittest.TestCase):
    # 跨曲低音与强拍复用通用修复：新增完整长句装饰差异，固定格位不同仍须核心音序相同，真正移位的旋律不合并。
    def test_complete_long_phrase_reuse_checks_core_notes_through_turns(self):
        from phrase_harmony_plan import phrase_families, melody_signature, similarity
        s,v=known_music(bars=4,count=2);s['method']={'harmonic_source_quality':{'version':2}}
        added=[]
        for n in v['quantized_notes']:
            if n['start_tick']>=7680:
                turn=deepcopy(n);turn.update(id=n['id']+'_lead',role='turn',pitch_midi=n['pitch_midi']+7,
                                           end_tick=n['start_tick']+240,end_seconds=n['start_seconds']+.25)
                n['start_tick']+=240;n['start_seconds']+=.25;added.append(turn)
        v['quantized_notes'].extend(added)
        self.assertFalse(similarity(melody_signature(s,v,0,7680),melody_signature(s,v,7680,15360))['accepted'])
        phrases=[{'id':'one','start_tick':0,'end_tick':7680},{'id':'two','start_tick':7680,'end_tick':15360}]
        self.assertEqual(len(phrase_families(s,v,phrases)),1)
        for n in v['quantized_notes']:
            if n['start_tick']>=7680:n['pitch_midi']+=5
        self.assertEqual(len(phrase_families(s,v,phrases)),2)

    # 跨曲低音与强拍复用通用修复：新增真正属和弦三音见证，即使低音是旧和弦五音也必须允许换和弦。
    def test_distinct_dominant_third_beats_bass_continuity_prior(self):
        from phrase_harmony_plan import candidate_scores,decode_phrase
        from phrase_harmony_source import source_scores
        from score_export import key_definition
        candidates=[(0,''),(7,''),(7,'sus4')];rows=[]
        for i in range(8):
            c=np.zeros(12);c[[0,4,7] if i<4 else [7,11,2]]=1/3
            b=np.zeros(12);b[0 if i<4 else 7]=1
            rows.append({'chroma':c,'bass':b,'voice':np.zeros(12),'key':key_definition('C:major')})
        scores=source_scores(rows,candidates,candidate_scores(rows,candidates))
        path=decode_phrase(scores,candidates,[i*480 for i in range(8)],1920,480,source_aware=True)
        self.assertEqual([candidates[i] for i in path],[(0,'')]*4+[(7,'')]*4)

    # 跨曲低音与强拍复用通用修复：新增尾拍范围的独立来源验收，不把人声提前收音误当伴奏也必须立即停。
    def test_final_pulse_completion_requires_an_actual_sustaining_source_note(self):
        from guitar_right_hand_patterns import validate_patterns
        s,v = known_music(bars=2); new,both,_ = apply_phrase_harmony(s,v,arrangements(s,v))
        a=both['guitar']; target=max((n for n in a['notes'] if n.get('phrase_harmony_generated')),key=lambda n:n['start_tick'])
        last=new['sections'][-1]; last['end_tick']=target['start_tick']-8
        source=next(n for n in a['phrase_harmony_performance']['source_notes'] if n['id'] in target['source_note_ids'])
        source['start_tick']=target['start_tick']-240;source['end_tick']=target['start_tick']+240
        active={**new,'harmony':new['arranged_harmony']}
        self.assertTrue(validate_patterns(active,a)['valid'])
        source['end_tick']=target['start_tick']
        self.assertTrue(any('pattern_outside_vocal' in e for e in validate_patterns(active,a)['errors']))

    # 跨曲低音与强拍复用通用修复：新增转位不是终止的反例，避免副歌第二小节被误切为完整句。
    def test_tonic_inversion_inside_a_phrase_does_not_create_a_cadence_boundary(self):
        from phrase_harmony_plan import phrase_ranges
        s,v=known_music(bars=4,count=1);s['method']={'harmonic_source_quality':{'version':2}}
        for w in s['harmony_windows']:
            bar=w['start_tick']//1920;root,bass=((5,5),(0,4),(7,7),(0,0))[bar]
            w['selected']={'root_pc':root,'bass_pc':bass}
        self.assertEqual([(p['start_tick'],p['end_tick']) for p in phrase_ranges(s,v)],[(0,7680)])

    # 跨曲低音与强拍复用通用修复：新增真实来源攻击纠正陈旧种子，合成循环/特色器乐必须保持。
    def test_source_attack_regrids_an_early_seed_but_not_solo_or_synthetic_notes(self):
        from accompaniment_analysis import SongClock
        s,v = known_music(bars=2); old = arrangements(s,v); clock = SongClock(v)
        # 跨曲低音与强拍复用通用修复：新增真正半小节入口条件，内部种子不参与此次边界重定位。
        s['sections'][0]['start_tick'] = 960
        note = deepcopy(old['guitar']['notes'][0])
        note.update(id='observed_early_seed', start_tick=900, end_tick=1380, section='vocal',
                    onset_origin='observed', arpeggio_step=0, source_attack_seconds=clock.seconds(960))
        solo = dict(note, id='protected_solo', source_melody_id='real_solo')
        synthetic = dict(note, id='synthetic_pattern', onset_origin='arranged_common_pattern')
        old['guitar']['notes'] = [note,solo,synthetic]; old['piano']['notes'] = []
        source_seconds = note['source_attack_seconds']
        regrid_observed_entries(s,v,old)
        self.assertEqual(note['start_tick'], 960)
        self.assertEqual(note['source_attack_seconds'], source_seconds)
        self.assertEqual(solo['start_tick'], 900); self.assertEqual(synthetic['start_tick'], 900)

    def case(self):
        s,v = known_music(bars=2); old = arrangements(s,v)
        s['sections'][0]['start_tick'] = 960
        for a in old.values():
            a['notes'] = [n for n in a['notes'] if n['start_tick'] >= 960]
            a['attack_events'] = [e for e in a['attack_events'] if e['start_tick'] >= 960]
        return s,v,old

    def test_half_bar_vocal_entry_generates_real_bass_for_both_instruments(self):
        s,v,old = self.case(); new,both,check = apply_phrase_harmony(s,v,old)
        self.assertTrue(check['valid'], check['errors'])
        for a in both.values():
            self.assertTrue(any(n['start_tick']==960 and n['role']=='bass' for n in a['notes']))

    def test_deleting_source_backed_entry_is_a_validation_failure(self):
        s,v,old = self.case(); new,both,_ = apply_phrase_harmony(s,v,old)
        for a in both.values():
            a['notes'] = [n for n in a['notes'] if n['start_tick'] >= 1920]
        check = validate_phrase_harmony(new,v,both)
        self.assertFalse(check['valid'])
        self.assertTrue(any('source_backed_chord_entry_missing' in e for e in check['errors']))

    def test_actual_rest_does_not_require_invented_chord_attacks(self):
        s,v,old = self.case()
        for a in old.values():
            a['notes'] = [n for n in a['notes'] if n['start_tick'] >= 1920]
        new,both,check = apply_phrase_harmony(s,v,old)
        self.assertTrue(check['valid'], check['errors'])
        self.assertTrue(all(n['start_tick']>=1920 for a in both.values() for n in a['notes']))


if __name__ == '__main__':
    unittest.main()
