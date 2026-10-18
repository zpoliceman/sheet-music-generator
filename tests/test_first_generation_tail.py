"""尾段原声局部补证：独立衰减／新演奏反例和来源保护。"""
# 尾段原声局部补证：新增有实际局部音频的正反例，不能仅以无缓存起音判尾响。
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from score_export import sha256,save_json,read_json
from first_generation_tail import (POLICY,cache_dependencies,inspect_decay,apply_tail_evidence,
                                   supplement_tail,replay_tail_decision,constrain_terminal_events,constrain_shared_tail)
from first_generation_source import _bound_decision,prepare_first_source,load_first_decision,project_first_voice
from first_generation_meter import decide_first_generation
from test_first_generation_meter import source_case


def cached_tail(folder, flat=False):
    # 尾段原声局部补证：新增独立指数衰减原音及三份缓存，不使用任何真实曲目位置。
    folder=Path(folder);rate=4000
    t=np.arange(8*rate)/rate
    envelope=np.full(len(t),.2)
    envelope[t>=6]=.2*np.exp(-5*(t[t>=6]-6))
    if flat:envelope[t>=6]=.0001
    audio=folder/'source.wav';sf.write(audio,envelope*np.sin(2*np.pi*190*t),rate,subtype='FLOAT')
    source={'path':str(audio),'sha256':sha256(audio)}
    binding={'sources':{role:deepcopy(source) for role in ('mix','accompaniment','bass','six_piano')},'duration_seconds':8.}
    token='v1_'+source['sha256'][:16]+'_22050_512_24_96'
    times=np.arange(0,8.001,.02)
    rms=np.where(times<6,1.,.01*np.exp(-5*(times-6)))
    flux=np.where(times<6,1.,.001)
    np.savez_compressed(folder/(token+'.npz'),times=times,rms=rms,flux=flux)
    save_json(folder/(token+'.json'),{'version':1,'source_sha256':source['sha256'],'attacks':[{'seconds':5.5}]})
    dependencies=cache_dependencies(binding,[folder])
    return binding,dependencies


class TerminalTailTests(unittest.TestCase):
    # 首拍与首尾局部补证：新增最后半小节跨余音时通用模板不得续填；之前音的结束仍保留。
    def test_pattern_scheduler_does_not_fill_partial_terminal_decay_bar(self):
        from test_guitar_section_patterns import fixture
        from guitar_right_hand_patterns import measure_notes,library
        from first_generation_tail import pattern_attack_allowed
        p=fixture(bars=2);shared=p['shared_analysis'];shared['timing']=deepcopy(p['accepted_vocal_project']['timing'])
        # 首拍与首尾局部补证：新增真实模板调用所需共享统计／原攻击字段，不能以缺字段夹具冒充算法失败。
        shared['statistics']=deepcopy(p['accepted_vocal_project']['statistics'])
        for n in p['arrangements']['guitar']['notes']:n.update(source='synthetic',source_attack_seconds=n['start_tick']/480)
        shared['terminal_decay_constraint']={'observation':{'status':'supported','kind':'decay_of_preexisting_sound','start_seconds':5.1,'end_seconds':8.}}
        guitar=p['arrangements']['guitar'];guitar['configuration'].update(capo_fret=0)
        library_pattern=next(row for row in library()['patterns'] if row['meter']==[4,4])
        plan={'pattern_id':library_pattern['id'],'phase_tick':0}
        notes,events,_,_=measure_notes(shared,guitar,2,plan,1)
        self.assertTrue(notes);self.assertTrue(all(n['start_tick']<5.1*480 for n in notes))
        self.assertTrue(all(e['start_tick']<5.1*480 for e in events))
        self.assertTrue(pattern_attack_allowed(shared,2400));self.assertFalse(pattern_attack_allowed(shared,2640))

    # 首拍与首尾局部补证：新增稳定唱段规则将余音交界留作边界，原有尾音不被删除或重新铺满。
    def test_stable_patterns_preserve_terminal_boundary_measure(self):
        from test_guitar_section_patterns import fixture
        from guitar_section_patterns import _editable_bars,section_blocks
        p=fixture(bars=2);p['shared_analysis']['timing']=deepcopy(p['accepted_vocal_project']['timing'])
        p['shared_analysis']['terminal_decay_constraint']={'observation':{'status':'supported','kind':'decay_of_preexisting_sound','start_seconds':5.1,'end_seconds':8.}}
        selected,exceptions=_editable_bars(p,section_blocks(p))
        self.assertNotIn(2,selected);self.assertIn('source_terminal_decay_boundary',[r['reason'] for r in exceptions])

    # 尾段原声局部补证：新增弱起音恢复／分解填充均不得把旧和声尾响重新变为实际攻击，前一个音仍可延续。
    def test_terminal_texture_and_generated_subdivisions_have_no_new_attacks(self):
        from test_accompaniment import fixture
        from accompaniment_arrange import performance_groups
        # 尾段原声局部补证：修改旧最简夹具补上实际生产必需的来源时钟，避免测试缺字段冒充音乐失败。
        # shared,_=fixture();before=deepcopy(shared)
        shared,voice=fixture();shared['timing']=deepcopy(voice['timing']);before=deepcopy(shared)
        observation={'status':'supported','kind':'decay_of_preexisting_sound','start_seconds':3.,'end_seconds':4.}
        result=constrain_shared_tail(shared,observation)
        self.assertEqual(result['harmony'],before['harmony'])
        self.assertEqual(shared,before)
        self.assertTrue(all(attack['seconds']<3. for texture in result['measure_textures'] for attack in texture['attacks']))
        groups=performance_groups(result)
        self.assertTrue(groups)
        self.assertTrue(all(row['tick']<2880 for row in groups))
        self.assertGreater(groups[-1]['tick']+groups[-1]['duration_ticks'],2880)

    # 尾段原声局部补证：新增真实2/4过渡后的织体时间窗不能继续按全曲模四，旧v1固定分箱可重放。
    def test_first_source_texture_uses_actual_short_measure_boundaries(self):
        from test_accompaniment import fixture
        from accompaniment_analysis import Features,SongClock,measure_textures
        _,voice=fixture();voice['statistics'].update(measure_count=3,total_ticks=4800)
        timeline=[{'number':1,'start_tick':0,'end_tick':1920,'meter':[4,4]},
                  {'number':2,'start_tick':1920,'end_tick':2880,'meter':[2,4]},
                  {'number':3,'start_tick':2880,'end_tick':4800,'meter':[4,4]}]
        voice['timing']['measure_timeline']=timeline
        voice['first_source_meter_correction']={'version':2}
        times=np.arange(0,6.01,.02)
        feature=Features(times,np.ones((73,len(times))),np.ones(len(times))*.1,np.zeros(len(times)),[],{})
        sections=[{'kind':'outro','start_seconds':0.,'end_seconds':6.}]
        rows=measure_textures({'other':feature},SongClock(voice),voice,sections)
        self.assertEqual([(r['start_tick'],r['end_tick']) for r in rows],[(0,1920),(1920,2880),(2880,4800)])
        self.assertEqual([(r['start_seconds'],r['end_seconds']) for r in rows],[(0.,2.),(2.,3.),(3.,5.)])
        voice['first_source_meter_correction']={'version':1}
        old=measure_textures({'other':feature},SongClock(voice),voice,sections)
        self.assertEqual(old[2]['start_tick'],3840)

    # 尾段原声局部补证：新增旧快拍转调坐标越过新曲长的反例；只换算坐标，调名与音符身份保持，v1仍原样重放。
    def test_modulation_seconds_project_to_new_ticks_without_new_key_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            meta,arrays,_,vocal,_=source_case(folder)
            decision=decide_first_generation(meta,arrays)
            from score_export import key_definition
            key=key_definition('D')
            vocal['notation']['key_segments']=[{'start_tick':0,'start_measure':1,'start_seconds':0.,'key':vocal['notation']['key']},
                # 尾段原声局部补证：修改夹具的旧坐标为原快轴曲长内、慢轴曲长外的真实小节边界。
                # {'start_tick':200000,'start_measure':105,'start_seconds':75.,'key':key,'source_key':key,'evidence':{'kept':True}}]
                {'start_tick':120960,'start_measure':64,'start_seconds':75.,'key':key,'source_key':key,'evidence':{'kept':True}}]
            old=project_first_voice(vocal,decision,version=1)
            current=project_first_voice(vocal,decision,version=2)
            segment=current['notation']['key_segments'][1]
            # 尾段原声局部补证：修改断言跟随有效旧边界夹具，旧v1仍精确保留。
            # self.assertEqual(old['notation']['key_segments'][1]['start_tick'],200000)
            self.assertEqual(old['notation']['key_segments'][1]['start_tick'],120960)
            self.assertEqual(segment['start_seconds'],75.)
            self.assertEqual(segment['key'],key)
            self.assertEqual(segment['evidence'],{'kept':True})
            self.assertLess(segment['start_tick'],current['statistics']['total_ticks'])
            for a,b in zip(vocal['quantized_notes'],current['quantized_notes']):
                for k in ('id','pitch_midi','start_seconds','end_seconds','lyric_index'):
                    self.assertEqual(a.get(k),b.get(k))

    # 尾段原声局部补证：新增变调夹接管低音后无需手指继续停在旧按弦位置；速度／持音／十二品仍不放宽。
    def test_capo_covered_bass_releases_obsolete_hand_lock_with_full_sustain(self):
        from test_guitar_instrumental_register import music
        from guitar_instrumental_register import solve_path,melodic_phrases
        shared,voice,guitar=music(capo=3)
        template=guitar['notes'][0]
        guitar['notes']=[dict(template,id='bass',role='bass',pitch_midi=44,string=6,fret=1,start_tick=0,end_tick=480),
                        dict(template,id='lead',role='instrumental_melody',pitch_midi=67,string=2,fret=5,start_tick=0,end_tick=120),
                        dict(template,id='next',role='harmony',pitch_midi=56,string=4,fret=2,start_tick=240,end_tick=360)]
        guitar['configuration']['capo_segments']=[{'start_tick':0,'capo_fret':3},{'start_tick':240,'capo_fret':4}]
        guitar['fingering_diagrams']=[];guitar['notation_regions']=[]
        editable={'lead'};phrases=melodic_phrases(shared,guitar['notes'],editable)
        before=deepcopy(guitar['notes'])
        old,_=solve_path(shared,voice,guitar,editable,phrases,12,48,search_version=2)
        guitar['configuration']['capo_covered_hold_transition_version']=1
        current,_=solve_path(shared,voice,guitar,editable,phrases,12,48,search_version=2)
        self.assertIsNone(old)
        self.assertIsNotNone(current)
        self.assertEqual(guitar['notes'],before)
        self.assertEqual(guitar['notes'][0]['end_tick'],480)

    # 尾段原声局部补证：新增从原匿名决定到补证／人声投影／普通重放的完整集成反例，防止自填通过或缓存绕过。
    def test_bound_parent_tail_projection_replay_and_tamper_rejection(self):
        parent=ROOT/'test_outputs/accompaniment_runs/tests'
        parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            folder=Path(folder)
            meta,arrays,evidence,vocal,binding=source_case(folder,silent_tail=8.)
            arrays['beat_logits']=arrays['beat_logits'][:4500]
            arrays['downbeat_logits']=arrays['downbeat_logits'][:4500]
            arrays['beats']=arrays['beats'][arrays['beats']<=88]
            arrays['downbeats']=arrays['downbeats'][arrays['downbeats']<=88]
            rate=2000;t=np.arange(96*rate)/rate
            y=.2*np.sin(2*np.pi*190*t)*np.exp(-3*np.maximum(0.,t-88))
            audio=Path(binding['sources']['mix']['path']);sf.write(audio,y,rate,subtype='FLOAT')
            source_sha=sha256(audio)
            for source in binding['sources'].values():source['sha256']=source_sha
            binding['sources']['six_piano']=deepcopy(binding['sources']['mix'])
            for track in meta['tracks']:track['source_sha256']=source_sha
            meta['mix_sha256']=source_sha
            np.savez_compressed(evidence.with_suffix('.npz'),**arrays)
            meta['array_sha256']=sha256(evidence.with_suffix('.npz'));save_json(evidence,meta)
            result=decide_first_generation(meta,arrays)
            self.assertEqual(result['issues'],[{'kind':'tail_not_observed','start_seconds':88.,'end_seconds':96.}])
            original=folder/'parent.json';save_json(original,_bound_decision(result,evidence,binding));original_sha=sha256(original)
            token='v1_'+source_sha[:16]+'_22050_512_24_96'
            at=np.arange(0,96.001,.02)
            np.savez_compressed(folder/(token+'.npz'),times=at,rms=np.where(at<88,1.,.01*np.exp(-3*(at-88))),
                                flux=np.where(at<88,1.,.001))
            cache_meta=folder/(token+'.json')
            save_json(cache_meta,{'version':1,'source_sha256':source_sha,'attacks':[{'seconds':87.5}]})
            path=folder/'tail.json';value=supplement_tail(original,binding,[folder],path)
            self.assertEqual(value['result']['status'],'passed')
            self.assertEqual(value['result']['candidates'],result['candidates'])
            self.assertEqual(sha256(original),original_sha)
            self.assertEqual(load_first_decision(path,binding),value)
            self.assertEqual(load_first_decision(path,binding),value)
            updated,_=prepare_first_source(vocal,binding,folder/'analysis/features',decision_path=path)
            from accompaniment_rebar import validate_vocal_snapshot,correct_accompaniment_grid
            self.assertTrue(validate_vocal_snapshot(updated,binding))
            for old,new in zip(vocal['quantized_notes'],updated['quantized_notes']):
                for key in ('id','pitch_midi','start_seconds','end_seconds','lyric_index'):
                    self.assertEqual(old.get(key),new.get(key))
            shared={'input_binding':binding};arrangements={}
            self.assertEqual(correct_accompaniment_grid(shared,updated,arrangements,folder),(shared,updated,arrangements))
            with self.assertRaisesRegex(ValueError,'再次缩放'):
                correct_accompaniment_grid(shared,updated,arrangements,folder,2.)
            # 尾段原声局部补证：新增时间导出和冻结阅读都不能把假尾部攻击借已验拍轴放行。
            from accompaniment_analysis import SongClock
            from first_generation_tail import require_terminal_arrangements
            bad={'guitar':{'notes':[{'id':'new_in_decay','start_tick':round(SongClock(updated).tick(90.))}]}}
            self.assertTrue(require_terminal_arrangements(shared,updated,{})['valid'])
            fake_project={'shared_analysis':shared,'accepted_vocal_project':updated,'arrangements':bad}
            from revise_guitar_reading import verify_reading_source
            with self.assertRaisesRegex(ValueError,'尾响内仍有新编配攻击'):
                verify_reading_source(fake_project,folder/'bad.json')
            save_json(folder/'bad.json',fake_project)
            from export_timing_revision import export_revision
            with self.assertRaisesRegex(ValueError,'尾响内仍有新编配攻击'):
                export_revision(folder/'bad.json',folder/'blocked_export',instruments=('guitar',))
            forged=deepcopy(value);forged['result']['candidates'][0]['clock']['beats'][0]['seconds']+=.1
            fake=folder/'fake.json';save_json(fake,forged)
            with self.assertRaisesRegex(ValueError,'确定性重放'):
                load_first_decision(fake,binding)
            cache_meta.write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'缓存已改变'):
                load_first_decision(path,binding)

    # 尾段原声局部补证：新增尾响不能变新拨弦，之前开始的实际持续音完整保留。
    def test_sustain_continuation_preserved_but_new_tail_attack_not_created(self):
        observation={'status':'supported','kind':'decay_of_preexisting_sound','start_seconds':6.,'end_seconds':8.}
        events=[{'id':'held','source_start_seconds':5.4,'source_end_seconds':7.5,'pitch_midi':76},
                {'id':'phantom','source_start_seconds':6.8,'source_end_seconds':7.9,'pitch_midi':52}]
        actual,audit=constrain_terminal_events(events,observation)
        self.assertEqual(actual,[events[0]])
        self.assertEqual(audit['unarticulated_decay_candidates'],[events[1]])
        self.assertEqual(events[0]['source_end_seconds'],7.5)

    def test_continuous_existing_sound_decay_passes_without_new_beats(self):
        with tempfile.TemporaryDirectory() as folder:
            binding,dependencies=cached_tail(folder)
            result=inspect_decay(binding,6.,8.,dependencies)
            self.assertEqual(result['status'],'supported',result['issues'])
            self.assertEqual(result['kind'],'decay_of_preexisting_sound')
            self.assertFalse(result['new_attack_or_new_beat_claimed'])
            self.assertTrue(result['audio_tail_must_be_retained'])

    def test_quiet_constant_sound_is_not_proven_terminal_decay(self):
        with tempfile.TemporaryDirectory() as folder:
            binding,dependencies=cached_tail(folder,flat=True)
            result=inspect_decay(binding,6.,8.,dependencies)
            self.assertEqual(result['status'],'needs_review')
            self.assertIn('terminal_fade_not_established',result['issues'])

    def test_new_cached_attack_under_fading_mix_still_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            binding,dependencies=cached_tail(folder)
            path=Path(dependencies[0]['metadata_path']);value=read_json(path)
            value['attacks'].append({'seconds':6.5});save_json(path,value)
            result=inspect_decay(binding,6.,8.,cache_dependencies(binding,[folder]))
            self.assertEqual(result['status'],'needs_review')
            self.assertTrue(any('active_or_ambiguous_tail' in issue for issue in result['issues']))

    def test_first_half_new_flux_is_not_skipped_by_only_checking_end(self):
        with tempfile.TemporaryDirectory() as folder:
            binding,dependencies=cached_tail(folder)
            path=Path(dependencies[0]['path'])
            with np.load(path) as data:arrays={key:data[key].copy() for key in data.files}
            arrays['flux'][310]=.8
            np.savez_compressed(path,**arrays)
            result=inspect_decay(binding,6.,8.,cache_dependencies(binding,[folder]))
            self.assertEqual(result['status'],'needs_review')

    def test_original_mix_rebound_blocks_even_with_missing_cached_attack(self):
        with tempfile.TemporaryDirectory() as folder:
            binding,dependencies=cached_tail(folder)
            path=Path(binding['sources']['mix']['path']);audio,rate=sf.read(path)
            audio[int(7*rate):int(7.25*rate)]*=100
            sf.write(path,audio,rate,subtype='FLOAT')
            binding['sources']['mix']['sha256']=sha256(path)
            result=inspect_decay(binding,6.,8.,dependencies)
            self.assertIn('original_mix_grows_again',result['issues'])

    def test_tail_does_not_clear_unit_or_phase_issues_or_change_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            binding,dependencies=cached_tail(folder)
            observation=inspect_decay(binding,6.,8.,dependencies)
        gap={'kind':'tail_not_observed','start_seconds':6.,'end_seconds':8.}
        other={'kind':'notation_level_unresolved'}
        parent={'coverage':{'issues':[gap],'edge_ranges':[{'kind':'tail'}]},'issues':[other,gap],
                'candidates':[{'clock':{'beats':[{'seconds':5.3,'beat':3}]}}]}
        actual=apply_tail_evidence(parent,observation)
        self.assertEqual(actual['issues'],[other])
        self.assertEqual(actual['status'],'needs_review')
        self.assertEqual(actual['candidates'],parent['candidates'])
        self.assertEqual(parent['issues'],[other,gap])

    def test_referenced_cache_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            binding,dependencies=cached_tail(folder)
            Path(dependencies[0]['metadata_path']).write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'缓存已改变'):
                inspect_decay(binding,6.,8.,dependencies)

    def test_existing_activity_thresholds_not_relaxed(self):
        self.assertEqual(POLICY['maximum_relative_peak_flux'],.25)
        self.assertEqual(POLICY['maximum_relative_median_rms'],.08)
        from first_generation_meter import POLICY as old
        self.assertEqual(old['maximum_unobserved_edge_seconds'],4.)


if __name__=='__main__':
    unittest.main()
