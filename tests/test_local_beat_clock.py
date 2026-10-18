"""局部拍轴与原唱同步纠错：新增变速、漏拍、真实弱起、旧源重建和音乐外部基准回归。"""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json, sys, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from score_export import TempoMap,read_json
# 局部拍轴与原唱同步纠错：修改，保留原导入；增加旧换夹结果失效与用户偏好保持回归。
# from local_beat_clock import fit_clock,fuse_candidates,infer_clock,derive_local_vocal,POLICY as CLOCK_POLICY
from local_beat_clock import fit_clock,fuse_candidates,infer_clock,derive_local_vocal,reusable_guitar_configuration,POLICY as CLOCK_POLICY
from phrase_rhythm_local import solve_words,entry_candidates,music_phrases,choose_phrases,POLICY as RHYTHM_POLICY
from phrase_rhythm import word_models
# 局部拍轴与原唱同步纠错：修改，保留原导入；增加器乐种子和新伴奏的同一时间分区回归。
# from beat_phase_alignment import validate_reviewed_beats
# 局部拍轴与原唱同步纠错：修改，保留原导入；加入器乐填句跨段边界的来源保护。
# from beat_phase_alignment import validate_reviewed_beats, piano_source_time_partition
from beat_phase_alignment import validate_reviewed_beats, piano_source_time_partition, seed_existing_music
from accompaniment_rebar import validate_vocal_snapshot


# 局部拍轴与原唱同步纠错：新增任意文字与独立合成拍点，不使用样曲身份或生产人工答案。
def pulse_nodes(times, missing=(), offbeats=False):
    nodes=[{'seconds':float(t),'strength':2.5,'tracks':['bass','accompaniment']}
           for i,t in enumerate(times) if i not in missing]
    if offbeats:
        nodes += [{'seconds':float((a+b)/2),'strength':.25,'tracks':['other']}
                  for a,b in zip(times,times[1:])]
    return sorted(nodes,key=lambda n:n['seconds'])


# 局部拍轴与原唱同步纠错：新增一般字音夹具，原秒时间/音高/角色保持可检查。
def vocal_fixture(intervals,jobs=None):
    notes=[{'id':str(i),'source_note_id':str(i),'pitch_midi':60+i,
            'start_seconds':a,'end_seconds':b,'lyric_index':i,'role':'main','grace':False}
           for i,(a,b) in enumerate(intervals)]
    chars=[{'index':i,'text':chr(0x4e10+i),'start_seconds':a,'end_seconds':b,
            'phrase_job_id':jobs[i] if jobs else 0,'phonemes':[]}
           for i,(a,b) in enumerate(intervals)]
    mapping=TempoMap([{'seconds':0,'quarter':0},{'seconds':8,'quarter':8}])
    timing={'meter':[4,4],'score_start_quarter':0,'steady_tempo_bpm':60}
    return notes,chars,mapping,timing


class LocalClockTests(unittest.TestCase):
    def test_instrumental_fill_keeps_source_identity_inside_vocal_bar(self):
        vocal={'timing':{'knots':[{'seconds':0,'quarter':0},{'seconds':4,'quarter':4}],
                         'score_start_quarter':0},'statistics':{'bar_ticks':1920,'total_ticks':1920}}
        # 局部拍轴与原唱同步纠错：修正测试夹具缺失的小节统计，生产逻辑及断言保持。
        # shared={'sections':[{'kind':'vocal','start_seconds':0,'end_seconds':4,'start_tick':0,'end_tick':1920}],
        shared={'statistics':{'bar_ticks':1920},
                'sections':[{'kind':'vocal','start_seconds':0,'end_seconds':4,'start_tick':0,'end_tick':1920}],
                'harmony':[{'id':'harmony','start_tick':0,'end_tick':1920,'name':'C','bass_pc':0}]}
        melody={'id':'fill','role':'instrumental_melody','source_melody_id':'observed_phrase',
                'section':'interlude','pitch_midi':64,'string':1,'fret':0,'start_tick':480,'end_tick':960}
        old={'guitar':{'notes':[melody],'attack_events':[]},'piano':{'notes':[],'attack_events':[]}}
        def fresh():return {'guitar':{'configuration':{'capo_fret':0}},
                            'piano':{'notes':[],'attack_events':[],'adjustments':[]}}
        new=seed_existing_music(shared,vocal,old,shared,vocal,fresh(),source_time_sections=True)['guitar']['notes'][0]
        legacy=seed_existing_music(shared,vocal,old,shared,vocal,fresh())['guitar']['notes'][0]
        self.assertEqual(new['source_melody_id'],'observed_phrase')
        self.assertEqual(new['role'],'instrumental_melody')
        self.assertEqual((new['start_tick'],new['end_tick'],new['pitch_midi']),(480,960,64))
        self.assertEqual(legacy['role'],'harmony')
        self.assertNotIn('source_melody_id',legacy)
        self.assertEqual(old['guitar']['notes'][0],melody)

    def test_old_capo_cache_invalidated_without_losing_user_preferences(self):
        config={'capo_fret':1,'capo_policy':{'version':1},'capo_segments':[{'start_tick':20000}],
                'fixed_capo_entire_song':False,'rows_measures':4,'maximum_fretted_span':5}
        before=deepcopy(config)
        result=reusable_guitar_configuration(config)
        self.assertEqual(result,{'capo_fret':1,'rows_measures':4,'maximum_fretted_span':5})
        self.assertEqual(config,before)

    def test_piano_source_partition_uses_note_time_not_bar_texture_label(self):
        class Clock:
            def seconds(self, tick): return tick/480
        shared={'sections':[{'kind':'interlude','start_seconds':0,'end_seconds':2},
                            {'kind':'vocal','start_seconds':2,'end_seconds':4}]}
        notes=[{'id':'instrument','section':'vocal','start_tick':480,'pitch_midi':44},
               {'id':'singer_accompaniment','section':'interlude','start_tick':1200,'pitch_midi':39}]
        before=deepcopy(notes)
        ordinary=piano_source_time_partition(notes,shared,Clock(),'vocal')
        instrumental=piano_source_time_partition(notes,shared,Clock(),'interlude')
        self.assertEqual([n['id'] for n in ordinary],['singer_accompaniment'])
        self.assertEqual([n['id'] for n in instrumental],['instrument'])
        self.assertEqual(ordinary[0]['section'],'vocal')
        self.assertEqual(instrumental[0]['pitch_midi'],44)
        self.assertEqual(notes,before)

    def test_constant_pulse_ignores_weaker_offbeats(self):
        times=[1+i for i in range(24)]
        beats=fit_clock(pulse_nodes(times,offbeats=True),1,0,1)
        observed={int(b['quarter']):b['seconds'] for b in beats}
        self.assertEqual(max(observed),23)
        for q,t in observed.items():self.assertAlmostEqual(t,times[q],places=6)

    def test_gradual_tempo_change_retains_beat_count(self):
        times=[1.]
        for i in range(31):times.append(times[-1]+1+.004*i)
        beats=fit_clock(pulse_nodes(times,offbeats=True),1,0,1)
        observed={int(b['quarter']):b['seconds'] for b in beats}
        self.assertEqual(max(observed),31)
        for q,t in observed.items():self.assertLess(abs(t-times[q]),.08)

    def test_missing_beat_is_interpolated_and_not_called_observed(self):
        times=[1+i for i in range(24)]
        beats=fit_clock(pulse_nodes(times,missing=(10,11)),1,0,1)
        by_q={int(b['quarter']):b for b in beats}
        for q in [10,11]:
            self.assertAlmostEqual(by_q[q]['seconds'],times[q],places=6)
            self.assertEqual(by_q[q]['kind'],'interpolated_missing_beat')
            self.assertEqual(by_q[q]['tracks'],[])

    def test_fixed_anchor_is_not_replaced_by_interpolation(self):
        times=[i+.25 for i in range(24)]
        beats=fit_clock(pulse_nodes(times,missing=(8,)),8.1,8,1)
        self.assertEqual(next(b['seconds'] for b in beats if b['quarter']==8),8.1)

    def test_empty_audio_evidence_retains_original_map(self):
        base={'timing':{'meter':[4,4],'knots':[{'seconds':0,'quarter':0},{'seconds':4,'quarter':4}],
                        'beat_origin_seconds':0,'steady_tempo_bpm':60},'statistics':{'bar_ticks':1920}}
        with patch('local_beat_clock.collect_candidates',return_value=[]):
            knots,audit=infer_clock({'sources':{}},base,ROOT/'test_outputs/accompaniment_runs/test')
        self.assertEqual(knots,base['timing']['knots'])
        self.assertEqual(audit['status'],'insufficient_evidence')

    def test_duplicate_one_track_cannot_inflate_support(self):
        nodes=fuse_candidates([{'seconds':1.,'strength':.5,'track':'bass'},
                               {'seconds':1.02,'strength':1.,'track':'bass'},
                               {'seconds':1.03,'strength':.5,'track':'accompaniment'}])
        self.assertEqual(len(nodes),1)
        self.assertEqual(nodes[0]['tracks'],['accompaniment','bass'])
        self.assertAlmostEqual(nodes[0]['strength'],1.5)

    def test_compound_beat_quarter_coordinates_preserved(self):
        beats=fit_clock(pulse_nodes([1+1.5*i for i in range(16)]),1,0,1.5,1.5)
        self.assertEqual([b['quarter'] for b in beats], [1.5*i for i in range(16)])


class LocalPhraseTests(unittest.TestCase):
    def test_early_pitch_platform_does_not_extend_word_past_trusted_phoneme_end(self):
        notes,chars,mapping,timing=vocal_fixture([(0,1),(1,1.5),(1.5,2.25)])
        chars[1].update(start_seconds=1.25,end_seconds=1.5,
                        phonemes=[{'role':'final','start_seconds':1.25,'end_seconds':1.5,'skipped':False}])
        original_notes,original_chars=deepcopy(notes),deepcopy(chars)
        fitted,audit=solve_words(notes,chars,mapping,timing,5)
        self.assertEqual((fitted[1]['start_tick'],fitted[1]['end_tick']),(600,720))
        self.assertEqual(fitted[2]['start_tick'],720)
        self.assertEqual((notes,chars),(original_notes,original_chars))
        self.assertEqual((fitted[1]['start_seconds'],fitted[1]['end_seconds']),(1,1.5))

    def test_real_sixteenth_pickup_survives_soft_binary_prior(self):
        notes,chars,mapping,timing=vocal_fixture([(3.75,5.4)])
        result,audit=solve_words(notes,chars,mapping,timing,8)
        self.assertEqual(result[0]['start_tick'],1800)
        self.assertGreater(audit['phrases'][0]['entry_candidate_count'],1)

    def test_cross_bar_eighth_followed_by_dotted_eighth(self):
        notes,chars,mapping,timing=vocal_fixture([(3.75,4.25),(4.25,5.)])
        result,_=solve_words(notes,chars,mapping,timing,8)
        self.assertEqual([(n['start_tick'],n['end_tick']) for n in result],[(1800,2040),(2040,2400)])

    def test_recognition_job_boundary_is_not_automatic_music_boundary(self):
        notes,chars,mapping,timing=vocal_fixture([(.2,.45),(.46,.71),(.72,.96),(.97,1.95)],jobs=[0,0,1,1])
        words=word_models(notes,chars,mapping,timing)
        self.assertEqual(len(music_phrases(words)),1)

    def test_actual_quarter_rest_retained(self):
        notes,chars,mapping,timing=vocal_fixture([(0.,1.),(2.,3.)])
        result,_=solve_words(notes,chars,mapping,timing,8)
        self.assertEqual([(n['start_tick'],n['end_tick']) for n in result],[(0,480),(960,1440)])

    def test_words_and_unrelated_human_answers_do_not_set_timings(self):
        notes,chars,mapping,timing=vocal_fixture([(.2,.45),(.46,.71),(.72,.96),(.97,1.95)])
        before=deepcopy(notes)
        result,audit=solve_words(notes,chars,mapping,timing,8)
        for c in chars:c['text']='unrelated'+str(c['index'])
        timing['beat_phase']={'vocal_beats':[{'quarter':999,'character_index':0}]}
        other,_=solve_words(notes,chars,mapping,timing,8)
        self.assertEqual([(n['start_tick'],n['end_tick']) for n in result],[(n['start_tick'],n['end_tick']) for n in other])
        self.assertEqual(notes,before)
        self.assertFalse(audit['human_beat_answers_used_by_solver'])

    def test_pitch_and_tempo_equivariance(self):
        notes,chars,mapping,timing=vocal_fixture([(.2,.45),(.46,.71),(.72,.96),(.97,1.95)])
        result,_=solve_words(notes,chars,mapping,timing,8)
        for n in notes:n['start_seconds']*=2;n['end_seconds']*=2;n['pitch_midi']+=5
        for c in chars:c['start_seconds']*=2;c['end_seconds']*=2
        mapping=TempoMap([{'seconds':0,'quarter':0},{'seconds':16,'quarter':8}]);timing['steady_tempo_bpm']=30
        other,_=solve_words(notes,chars,mapping,timing,16)
        self.assertEqual([(n['start_tick'],n['end_tick']) for n in result],[(n['start_tick'],n['end_tick']) for n in other])
        self.assertEqual([n['pitch_midi']+5 for n in result],[n['pitch_midi'] for n in other])

    def test_adjacent_phrases_choose_feasible_release_before_pickup(self):
        phrases=[[{'voiced_end':3.}],[{'voiced_start':3.1}]]
        first=[{'cost':0.,'path':((0,1680,(1680,)),)}, {'cost':.2,'path':((0,1440,(1440,)),)}]
        second=[{'cost':0.,'path':((1560,1920,(360,)),)}]
        selected=choose_phrases(phrases,[first,second])
        self.assertEqual(selected[0]['path'][0][1],1440)


class OriginalMusicRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=read_json(ROOT/'results/accompaniment/雨天_v13_乐句节奏与音值分组/project.json')
        cls.binding=cls.old['shared_analysis']['input_binding']
        base=cls.old['accepted_vocal_project'];cache=ROOT/'test_outputs/accompaniment_runs/20261009_phrase_v13/features'
        _,audit=infer_clock(cls.binding,base,cache)
        correction={'version':1,'policy':deepcopy(CLOCK_POLICY),'rhythm_policy':deepcopy(RHYTHM_POLICY),
                    'source_vocal_project_sha256':cls.binding['vocal_project_sha256'],
                    'source_audio_sha256':cls.binding['sources']['mix']['sha256'],
                    'base_phase_correction':deepcopy(base.get('beat_phase_correction')),
                    'base_grid_correction':deepcopy(base.get('grid_correction')),
                    'feature_cache':str(cache),'clock_evidence':audit}
        cls.vocal=derive_local_vocal(read_json(cls.binding['vocal_project']),cls.binding,correction)

    def test_first_user_phrase_still_passes(self):
        check=validate_reviewed_beats(self.vocal)
        self.assertTrue(check['valid'],check['errors'])

    def test_second_phrase_syncopation_and_cadence_preserved(self):
        heads={}
        for n in self.vocal['quantized_notes']:
            if not n.get('grace'):heads.setdefault(n.get('lyric_index'),n['start_tick'])
        expected={19:37,21:38,23:39,25:40,27:40.75,28:41.25,29:43,32:43.75,33:45,35:45.75,37:47,39:48}
        for i,q in expected.items():self.assertEqual(heads[i],round(q*480),(i,q))

    def test_reference_twenty_word_heads_independent_of_solver(self):
        reference=read_json(ROOT/'reports/accompaniment/20261009_playback_lyric_audit/music_clock_reference_checks.json')
        heads={}
        for n in self.vocal['quantized_notes']:
            if not n.get('grace'):heads.setdefault(n.get('lyric_index'),n['start_tick'])
        for row in reference['word_head_comparison']:
            self.assertEqual(heads[row['index']],round(row['reference_score_quarter']*480),row['text'])

    def test_raw_pitch_seconds_identity_ownership_and_roles_preserved(self):
        fields=('id','source_note_id','start_seconds','end_seconds','pitch_midi','lyric_index','role','grace')
        old=sorted(tuple(n.get(k) for k in fields) for n in self.old['accepted_vocal_project']['quantized_notes'])
        current=sorted(tuple(n.get(k) for k in fields) for n in self.vocal['quantized_notes'])
        self.assertEqual(old,current)

    def test_strict_source_replay_and_tampered_clock_rejected(self):
        self.assertTrue(validate_vocal_snapshot(self.vocal,self.binding))
        bad=deepcopy(self.vocal)
        bad['local_clock_correction']['clock_evidence']['beats'][25]['seconds']+=.2
        self.assertFalse(validate_vocal_snapshot(bad,self.binding))


if __name__=='__main__':unittest.main()
