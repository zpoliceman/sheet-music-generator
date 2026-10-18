"""强拍相位与伴奏同步纠错：新增用户音乐基准与合成错拍反例，验证实际发声而非标签。"""
from copy import deepcopy
from pathlib import Path
import sys,json,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from workspace_location import local_path
from beat_phase_alignment import (phase_review,apply_phase_timing,nucleus_onsets,derive_phase_vocal,
                                 validate_reviewed_beats,validate_beat_synchrony,validate_piano_beats)
from accompaniment_rebar import validate_vocal_snapshot
from score_export import TempoMap
from test_guitar_right_hand_patterns import known
from guitar_right_hand_patterns import measure_notes
from beat_phase_alignment import score_row_ranges,display_measure
from metrical_timing import resolve_timing
from verify_accompaniment_delivery import renderer_attacks_match


# 强拍相位与伴奏同步纠错：新增明确的480tick拍、720tick元音与声母时间夹具。
def onset_fixture(role='initial',start=.78,nucleus=1.01):
    timing={'steady_tempo_bpm':60.,'score_start_quarter':0,'meter':[4,4],
            'beat_phase':{'review_id':'synthetic'}}
    mapping=TempoMap([{'seconds':0.,'quarter':0.},{'seconds':1.,'quarter':1.}])
    pieces=[{'id':'p','start_seconds':start,'end_seconds':1.5,'pitch_midi':60,'lyric_index':0,
             'notation_onset_prior':{'quarter':9.}}]
    chars=[{'index':0,'start_seconds':start,'phonemes':[{'role':role,'start_seconds':start},
                                                         {'role':'nucleus','start_seconds':nucleus}]}]
    return pieces,chars,mapping,timing


class NucleusOnsetTests(unittest.TestCase):
    def test_unvoiced_initial_uses_vowel_beat(self):
        p,c,m,t=onset_fixture();out,audit=nucleus_onsets(p,c,m,t)
        self.assertEqual(out[0]['notation_onset_prior']['quarter'],1.)
        self.assertEqual(p[0]['notation_onset_prior']['quarter'],9.)

    def test_voiced_initial_is_not_moved(self):
        out,audit=nucleus_onsets(*onset_fixture('voiced_initial'))
        self.assertNotIn('notation_onset_prior',out[0]);self.assertEqual(audit,[])

    def test_late_vowel_does_not_move_quarter_pickup_to_downbeat(self):
        out,audit=nucleus_onsets(*onset_fixture(start=.66,nucleus=.85))
        self.assertNotIn('notation_onset_prior',out[0])

    def test_missing_phoneme_drops_stale_grid_prior(self):
        p,c,m,t=onset_fixture();c[0]['phonemes']=[]
        out,audit=nucleus_onsets(p,c,m,t);self.assertNotIn('notation_onset_prior',out[0])

    def test_stable_independent_lead_pitch_is_retained(self):
        p,c,m,t=onset_fixture();p[0].update(stable_duration_seconds=.15,independent_pitch_support=.9)
        p.append({**p[0],'id':'p2','pitch_midi':62,'start_seconds':1.2,'end_seconds':1.8})
        out,audit=nucleus_onsets(p,c,m,t);self.assertNotIn('notation_onset_prior',out[0])


class PhaseReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project=json.loads((ROOT/'results/accompaniment/雨天_v11_小节划分纠正/project.json').read_text(encoding='utf-8'))
        cls.base=cls.project['accepted_vocal_project'];cls.binding=cls.project['shared_analysis']['input_binding']
        cls.source=json.loads(local_path(cls.binding['vocal_project']).read_text(encoding='utf-8'))
        cls.correction={'version':1,'source_vocal_project_sha256':cls.binding['vocal_project_sha256'],
                        'source_audio_sha256':cls.binding['sources']['mix']['sha256'],
                        'base_grid_correction':cls.base['grid_correction'],
                        'review':phase_review(cls.base['audio_analysis'],cls.base['timing'])}
        cls.vocal=derive_phase_vocal(cls.source,cls.correction)

    def test_unknown_source_has_no_phase_answer(self):
        self.assertIsNone(phase_review({'source_sha256':'unknown'},self.base['timing']))

    def test_wrong_tempo_does_not_reuse_phase(self):
        t=deepcopy(self.base['timing']);t['knots']=[{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}]
        self.assertIsNone(phase_review(self.base['audio_analysis'],t))

    def test_explicit_origin_wins(self):
        t=deepcopy(self.base['timing']);t['beat_origin_source']='user_override'
        self.assertEqual(apply_phase_timing(self.base['audio_analysis'],t),t)

    def test_pulse_rebase_also_preserves_explicit_origin(self):
        t=deepcopy(self.source['timing']);t.update(beat_origin_source='user_override',beat_origin_seconds=.8)
        mapping,out=resolve_timing(self.source['audio_analysis'],t)
        self.assertAlmostEqual(mapping.quarters_to_seconds(0),.8)
        self.assertEqual(out['beat_origin_source'],'user_override');self.assertNotIn('beat_phase',out)

    def test_all_sixteen_user_beats(self):
        r=validate_reviewed_beats(self.vocal);self.assertTrue(r['valid'],r['errors']);self.assertEqual(len(r['beats']),16)

    def test_one_eighth_shift_is_detected(self):
        v=deepcopy(self.vocal)
        for n in v['quantized_notes']:n['start_tick']+=240;n['end_tick']+=240
        self.assertFalse(validate_reviewed_beats(v)['valid'])

    def test_new_word_on_sustain_beat_is_detected(self):
        v=deepcopy(self.vocal);target=round((28-v['timing']['score_start_quarter'])*480)
        for n in v['quantized_notes']:
            if n.get('lyric_index')==15:n['start_tick']=max(target,n['start_tick'])
        self.assertFalse(validate_reviewed_beats(v)['valid'])

    def test_empty_lyric_beat_can_still_sound(self):
        r=validate_reviewed_beats(self.vocal);row=next(x for x in r['beats'] if x['quarter']==30)
        self.assertEqual(row['active_characters'],[17]);self.assertEqual(row['new_word_characters'],[])

    def test_pitches_piece_ids_and_graces_are_preserved(self):
        fields=lambda v:[(n['id'],n['pitch_midi'],n.get('grace'),n.get('anchor_id')) for n in v['quantized_notes']]
        self.assertEqual(fields(self.vocal),fields(self.source))
        self.assertEqual(sum(n.get('grace',False) for n in self.vocal['quantized_notes']),15)

    def test_read_only_source_and_one_text_correction(self):
        self.assertEqual(self.source,json.loads(local_path(self.binding['vocal_project']).read_text(encoding='utf-8')))
        a=[x['text'] for x in self.source['lyrics']['characters']];b=[x['text'] for x in self.vocal['lyrics']['characters']]
        self.assertEqual([(i,x,y) for i,(x,y) in enumerate(zip(a,b)) if x!=y],[(15,'剩','想')])

    def test_derived_loader_rejects_arbitrary_pitch_edit(self):
        self.assertTrue(validate_vocal_snapshot(self.vocal,self.binding))
        v=deepcopy(self.vocal);v['quantized_notes'][0]['pitch_midi']+=1
        self.assertFalse(validate_vocal_snapshot(v,self.binding))

    def test_derived_loader_rejects_fake_review(self):
        v=deepcopy(self.vocal);v['beat_phase_correction']['review']['anchor_seconds']+=.5
        self.assertFalse(validate_vocal_snapshot(v,self.binding))

    def test_pickup_is_separate_from_four_formal_bars(self):
        rows=score_row_ranges(self.vocal);self.assertEqual(rows[:3],[(1,1),(2,5),(6,9)])
        self.assertEqual(len(rows),16);self.assertEqual(rows[-1],(58,60))

    def test_first_phrase_display_numbers_match_formal_bars(self):
        self.assertEqual([display_measure(self.vocal,i) for i in (1,2,6,9)],['弱起','1','5','8'])


class RendererPrecisionTests(unittest.TestCase):
    # 强拍相位与伴奏同步纠错：新增原生PPQ120的半tick真值，不允许扩大音乐拍点容差。
    def test_half_native_tick_is_exactly_floored(self):
        self.assertTrue(renderer_attacks_match([(1828.,2000.,60)],[(1830,2000,60)],120))

    def test_full_native_tick_shift_is_rejected(self):
        self.assertFalse(renderer_attacks_match([(1824.,2000.,60)],[(1830,2000,60)],120))

    def test_project_ppq_renderer_has_no_two_tick_allowance(self):
        self.assertFalse(renderer_attacks_match([(1828.,2000.,60)],[(1830,2000,60)],480))

    def test_wrong_pitch_is_never_rounding(self):
        self.assertFalse(renderer_attacks_match([(1828.,2000.,61)],[(1830,2000,60)],120))


class LoopRestartTests(unittest.TestCase):
    # 强拍相位与伴奏同步纠错：新增已知C转Am，第二拍换和弦后必须B/3/2/1而非原循环的2/1。
    def notes(self):
        s,v,g=known();c=deepcopy(s['harmony'][0]);c.update(root_pc=0,bass_pc=0,quality='',pitch_classes=[0,4,7],name='C',end_tick=480)
        a=deepcopy(c);a.update(id='am',root_pc=9,bass_pc=9,quality='m',pitch_classes=[9,0,4],name='Am',start_tick=480,end_tick=1920)
        s['harmony']=[c,a]+[h for h in s['harmony'] if h['start_tick']>=1920]
        g['configuration']['beat_synchronous_patterns']=True
        ns,events,row,_=measure_notes(s,g,1,{'pattern_id':'arp_4_4_up','phase_tick':0},1)
        g['notes']=ns;g['attack_events']=events
        for n in ns:n['section']='vocal'
        return s,v,g,row

    def test_change_on_second_beat_restarts_at_bass(self):
        s,v,g,row=self.notes();ns=g['notes'];n=next(n for n in ns if n['start_tick']==480)
        self.assertEqual((n['right_hand_slot'],n['right_hand_token'],n['pattern_cycle_origin_tick']),(0,'B',480))
        self.assertEqual([n['right_hand_token'] for n in ns if 480<=n['start_tick']<1440],['B','3','2','1'])
        self.assertTrue(validate_beat_synchrony(s,v,g)['valid'])

    def test_inner_string_as_first_attack_is_rejected(self):
        s,v,g,row=self.notes();n=next(n for n in g['notes'] if n['start_tick']==480);n['right_hand_token']='3'
        self.assertFalse(validate_beat_synchrony(s,v,g)['valid'])

    def test_actual_wrong_fret_is_rejected_despite_bass_label(self):
        s,v,g,row=self.notes();n=next(n for n in g['notes'] if n['start_tick']==480);n['fret']+=1
        self.assertFalse(validate_beat_synchrony(s,v,g)['valid'])

    def test_old_ordinary_note_phase_is_rejected(self):
        s,v,g,row=self.notes();g['notes'][0].pop('right_hand_pattern_id')
        self.assertFalse(validate_beat_synchrony(s,v,g)['valid'])

    def test_piano_offbeat_entry_is_rejected(self):
        s,v,g,row=self.notes();p={'beat_bass_alignment':{},'notes':[],'attack_events':[]}
        p['beat_bass_alignment']={'version':1};p['notes']=[{'id':'b','chord_id':s['harmony'][0]['id'],
                          'section':'vocal','role':'bass','start_tick':120,'pitch_midi':48}]
        self.assertFalse(validate_piano_beats(s,p)['valid'])


if __name__=='__main__':unittest.main()
