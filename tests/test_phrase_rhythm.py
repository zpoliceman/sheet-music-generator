"""乐句节奏与音值分组：新增独立节拍、拍号和语义播放反例，不向生产提供每字答案。"""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from score_export import TempoMap,read_json,jianpu_beam_groups
from rhythm_notation import MeterTree,split_rhythm,validate_grouping
from phrase_rhythm import solve_words,allocate_playback,notation_events,POLICY,allocate_durations,has_sounding_gap
from beat_phase_alignment import derive_phase_vocal
from accompaniment_rebar import validate_vocal_snapshot
from guitar_right_hand_patterns import next_note_serial

# 乐句节奏与音值分组：新增未知歌曲快速短音组，任意文字及误导元音先验不得改变声学推断。
def rapid_fixture():
    intervals=[(.20,.45),(.46,.71),(.72,.96),(.97,1.95)]
    pieces=[{'id':str(i),'source_note_id':str(i),'pitch_midi':60+i,'start_seconds':a,'end_seconds':b,
             'lyric_index':i,'role':'main','grace':False,'notation_onset_prior':{'quarter':100+i}}
            for i,(a,b) in enumerate(intervals)]
    chars=[{'index':i,'text':chr(0x4e00+i),'start_seconds':a,'end_seconds':b,
            'phrase_job_id':0,'phonemes':[{'role':'nucleus','start_seconds':a+.15,'end_seconds':b}]} for i,(a,b) in enumerate(intervals)]
    timing={'score_start_quarter':0,'steady_tempo_bpm':60,'meter':[4,4]}
    mapping=TempoMap([{'seconds':0,'quarter':0},{'seconds':4,'quarter':4}])
    return pieces,chars,mapping,timing


class MeterGroupingTests(unittest.TestCase):
    def test_six_eight_uses_two_compound_beats(self):
        tree=MeterTree.from_meter([6,8]);self.assertEqual(tree.boundaries,(0,720,1440))
        self.assertEqual([p['duration_ticks'] for p in split_rhythm(480,960,[6,8])],[240,240])

    def test_seven_eight_explicit_grouping(self):
        self.assertEqual(MeterTree.from_meter([7,8],[2,2,3]).boundaries,(0,480,960,1680))

    def test_invalid_group_rejected(self):
        with self.assertRaises(ValueError):MeterTree.from_meter([6,8],[2,2])

    def test_offbeat_quarter_rest_reveals_boundary(self):
        self.assertEqual([p['duration_ticks'] for p in split_rhythm(1080,1560,rest=True)],[360,120])

    def test_real_dotted_eighth_retained_inside_beat(self):
        self.assertEqual(split_rhythm(120,480),[{'start_tick':120,'duration_ticks':360,'type':'eighth','dots':1}])

    def test_offbeat_sustain_split_at_beat_and_bar(self):
        parts=split_rhythm(1800,2160)
        self.assertEqual([(p['start_tick'],p['duration_ticks']) for p in parts],[(1800,120),(1920,240)])

    def test_whole_bar_and_half_note_remain_readable(self):
        self.assertEqual(len(split_rhythm(0,1920)),1)
        self.assertEqual(len(split_rhythm(960,1920)),1)

    def test_arbitrary_tuplet_not_faked_as_binary(self):
        with self.assertRaises(ValueError):split_rhythm(0,160)

    def test_validator_rejects_hidden_beat_even_if_bar_total_valid(self):
        e={'start_tick':120,'duration_ticks':480,'type':'quarter','dots':0,'pitch_midi':60}
        self.assertFalse(validate_grouping([e],[4,4])['valid'])

    def test_four_sixteenths_share_beams_and_next_beat_separates(self):
        events=[{'id':str(i),'offset_ticks':i*120,'duration_ticks':120,'type':'16th','grace':False} for i in range(8)]
        beams=jianpu_beam_groups(events,480)
        self.assertEqual([len(g['events']) for g in beams],[4,4,4,4])


class PhraseInferenceTests(unittest.TestCase):
    def test_compound_phrase_entry_uses_dotted_quarter(self):
        from phrase_rhythm import word_models,phrase_entry
        p,c,m,t=rapid_fixture()
        for n in p:n['start_seconds']+=1.5;n['end_seconds']+=1.5
        for ch in c:ch['start_seconds']+=1.5;ch['end_seconds']+=1.5
        words=word_models(p,c,m,t)
        entry,latency,method=phrase_entry(words,1.5)
        self.assertEqual(entry,1.5)

    def test_repeat_soft_reference_uses_actual_observed_copy(self):
        p,c,m,t=rapid_fixture();p2=deepcopy(p);c2=deepcopy(c)
        for n in p2:n['id']+='copy';n['source_note_id']+='copy';n['lyric_index']+=4;n['start_seconds']+=4;n['end_seconds']+=4
        for ch in c2:ch['index']+=4;ch['start_seconds']+=4;ch['end_seconds']+=4;ch['phrase_job_id']=1
        n,a=solve_words(p+p2,c+c2,m,t,8)
        self.assertEqual(a['observed_repeat_groups'],[[0,1]])
        self.assertTrue(all(ph['observed_repeat_soft_reference'] for ph in a['phrases']))

    def test_rapid_group_jointly_recovers_equal_grid_without_prior_override(self):
        p,c,m,t=rapid_fixture();before=deepcopy(p)
        n,a=solve_words(p,c,m,t,4)
        self.assertEqual([x['start_tick'] for x in n],[0,120,240,360])
        self.assertEqual(p,before);self.assertFalse(a['human_beat_answers_used_by_solver'])

    def test_text_and_irrelevant_human_answers_not_used(self):
        p,c,m,t=rapid_fixture();n,_=solve_words(p,c,m,t,4)
        for ch in c:ch['text']='word'+str(ch['index'])
        t['beat_phase']={'vocal_beats':[{'quarter':999,'character_index':0}]}
        other,_=solve_words(p,c,m,t,4)
        self.assertEqual([(x['start_tick'],x['end_tick']) for x in n],[(x['start_tick'],x['end_tick']) for x in other])

    def test_pitch_and_tempo_equivariance(self):
        p,c,m,t=rapid_fixture();n,_=solve_words(p,c,m,t,4)
        for x in p:x['start_seconds']*=2;x['end_seconds']*=2;x['pitch_midi']+=7
        for x in c:
            x['start_seconds']*=2;x['end_seconds']*=2
            x['phonemes']=[]
        t['steady_tempo_bpm']=30;m=TempoMap([{'seconds':0,'quarter':0},{'seconds':8,'quarter':4}])
        out,_=solve_words(p,c,m,t,8)
        self.assertEqual([(x['start_tick'],x['end_tick']) for x in n],[(x['start_tick'],x['end_tick']) for x in out])
        self.assertEqual([x['pitch_midi'] for x in out],[x['pitch_midi']+7 for x in n])

    def test_infeasible_word_duration_has_no_cursor_fallback(self):
        cost,lengths=allocate_durations((.2,.2,.2),120)
        self.assertEqual(lengths,());self.assertEqual(cost,float('inf'))

    def test_consonant_bridge_is_not_a_rest(self):
        left={'voiced_end':1.};right={'voiced_start':1.3,'initial_interval':(.98,1.31)}
        self.assertFalse(has_sounding_gap(left,right));right['initial_interval']=None
        self.assertTrue(has_sounding_gap(left,right))

    def test_grace_playback_invariant_under_meter_fragment_change(self):
        notes=[{'id':'g','anchor_id':'a','grace':True,'start_tick':240,'end_tick':240,'pitch_midi':62,'start_seconds':.2,'end_seconds':.28},
               {'id':'a','grace':False,'start_tick':240,'end_tick':960,'pitch_midi':60,'start_seconds':.28,'end_seconds':1.8,'role':'main','lyric_index':0}]
        a,b=deepcopy(notes),deepcopy(notes)
        allocate_playback(a,{'steady_tempo_bpm':60});allocate_playback(b,{'steady_tempo_bpm':60})
        notation_events(a,1920,{'meter':[4,4]});notation_events(b,2880,{'meter':[6,8]})
        self.assertNotEqual(a[0]['grace_steal_percent'],b[0]['grace_steal_percent'])
        self.assertEqual([(n['playback_start_tick'],n['playback_end_tick']) for n in a],[(n['playback_start_tick'],n['playback_end_tick']) for n in b])

    def test_new_ids_cannot_collide_with_upgrade_seeds(self):
        self.assertEqual(next_note_serial([{'id':'guitar_beat_note_100095'},{'id':'guitar_note_00042'}]),100096)


class SourceDerivedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=read_json(ROOT/'results/accompaniment/雨天_v12_强拍与伴奏同步/project.json')
        cls.binding=cls.p['shared_analysis']['input_binding'];cls.original=read_json(cls.binding['vocal_project'])
        correction=deepcopy(cls.p['accepted_vocal_project']['beat_phase_correction'])
        correction['phrase_rhythm']={'version':1,'policy':deepcopy(POLICY)}
        cls.vocal=derive_phase_vocal(cls.original,correction)

    def test_all_original_pitch_ids_seconds_and_roles_preserved(self):
        for old,new in zip(self.original['quantized_notes'],self.vocal['quantized_notes']):
            self.assertEqual(tuple(old[k] for k in ('id','pitch_midi','start_seconds','end_seconds','role')),
                             tuple(new[k] for k in ('id','pitch_midi','start_seconds','end_seconds','role')))

    def test_user_second_phrase_onset_and_sustain_independent_fixture(self):
        heads={i:min(n['start_tick'] for n in self.vocal['quantized_notes'] if n.get('lyric_index')==i and not n.get('grace')) for i in range(18,40)}
        self.assertEqual([heads[i] for i in (19,21,23,25,29,33,37,39)],[round(q*480) for q in (37,38,39,40,43,45,47,48)])
        self.assertEqual([heads[i] for i in (27,28,29,30,31,32)],[round(q*480) for q in (40.75,41.25,43,43.25,43.5,43.75)])

    def test_mei_continuation_and_you_dotted_eighth_fill_one_beat(self):
        e=[e for e in self.vocal['events'] if 19680<=e['start_tick']<20160 and not e['grace']]
        self.assertEqual([(e['lyric_index'],e['duration_ticks']) for e in e],[(27,120),(28,360)])
        self.assertIn('stop',e[0]['ties']);self.assertEqual(e[1]['dots'],1)

    def test_strict_snapshot_and_tamper_rejection(self):
        self.assertTrue(validate_vocal_snapshot(self.vocal,self.binding))
        bad=deepcopy(self.vocal);bad['quantized_notes'][10]['start_tick']+=120
        self.assertFalse(validate_vocal_snapshot(bad,self.binding))
        bad=deepcopy(self.vocal);bad['beat_phase_correction']['phrase_rhythm']['policy']['word_grid_ticks']=60
        self.assertFalse(validate_vocal_snapshot(bad,self.binding))

    def test_legacy_v12_still_reproduces_exactly(self):
        self.assertTrue(validate_vocal_snapshot(self.p['accepted_vocal_project'],self.binding))

    def test_full_curve_has_no_sound_overlap_or_noncanonical_fragments(self):
        notes=sorted((n for n in self.vocal['quantized_notes'] if not n['grace']),key=lambda n:n['start_tick'])
        self.assertTrue(all(a['end_tick']<=b['start_tick'] for a,b in zip(notes,notes[1:])))
        self.assertTrue(validate_grouping(self.vocal['events'],[4,4])['valid'])


if __name__=='__main__':unittest.main()
