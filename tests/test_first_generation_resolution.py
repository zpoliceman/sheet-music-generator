"""两曲来源补证与首次生成：鼓角色正反例、原声尾部覆盖及来源拒伪。"""
# 两曲来源补证与首次生成：新增音乐证据反例，不以歌名、既有谱或人工答案构造生产分支。
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from source_drum_roles import POLICY as DRUM_POLICY,compare_drum_roles
from source_edge_pulses import validate_fixed_grid
from first_generation_resolution import apply_resolution,inspect_unarticulated_tail
from first_generation_meter import decide_first_generation
from test_source_meter_hierarchy import fixture
from test_first_generation_tail import cached_tail


def rhythm_fixture(period=.5,duration=128.):
    # 两曲来源补证与首次生成：新增独立底鼓／噪声反拍，可构造真实快拍、慢拍和非标准鼓型。
    times=np.arange(0,duration,.01)
    bands={'times':times,'kick':np.zeros(len(times)),'lowmid':np.zeros(len(times)),'snare':np.zeros(len(times))}
    for i,s in enumerate(np.arange(0,duration,period)):
        index=round(s/.01)
        if i%2:
            bands['lowmid'][index]=3.;bands['snare'][index]=3.
        else:
            bands['kick'][index]=3.;bands['lowmid'][index]=1.;bands['snare'][index]=1.
    candidates=[]
    for index,ratio in enumerate((.5,1.,2.)):
        beats=[{'seconds':float(s),'beat':i%4+1} for i,s in enumerate(np.arange(0,duration,period*ratio))]
        candidates.append({'candidate_index':index,'bpm':60/(period*ratio),'qualification':{'eligible':True},'clock':{'beats':beats}})
    return bands,candidates


class SourceRoleResolutionTests(unittest.TestCase):
    # 两曲来源补证与首次生成：新增原声段身份丢失的真实公共入口反例；保留分句元数据后才能识别源音区交接，不能靠扩品或裁音。
    def test_initial_source_requests_retain_register_handover_context(self):
        from test_guitar_instrumental_register import music
        from accompaniment_arrange import arrange_requested
        from guitar_instrumental_register import melodic_phrases,editable_notes
        shared,voice,_=music()
        shared['input_binding']['requested_instruments']=['guitar']
        pitches=[60,64,98,76,78];lengths=[240,240,960,240,240]
        rows=[];tick=0
        for i,(pitch,length) in enumerate(zip(pitches,lengths)):
            rows.append({'id':'raw_'+str(i),'section':'intro','section_id':'independent_source_motif',
                         'start_tick':tick,'end_tick':tick+length,'duration_ticks':length,'pitch_midi':pitch,
                         'source':'original_instrument','source_start_seconds':tick/960,'source_end_seconds':(tick+length)/960})
            tick+=length
        shared['instrumental_melody']=rows
        result=arrange_requested(shared,voice,0,phrase_register=True)['guitar']
        melody=[n for n in result['notes'] if n['role']=='instrumental_melody']
        self.assertEqual({n['source_melody_id'] for n in melody},{r['id'] for r in rows})
        self.assertTrue(all(n['source_backbone_section_id']=='independent_source_motif' for n in melody))
        self.assertEqual([(n['start_tick'],n['end_tick']) for n in sorted(melody,key=lambda n:n['start_tick'])],
                         [(r['start_tick'],r['end_tick']) for r in rows])
        self.assertTrue(all(n['fret']<=12 for n in result['notes']))
        # 两曲来源补证与首次生成：修改读取准备阶段实际账本，正式来源层在后续完整编配完成后才绑定。
        # self.assertGreaterEqual(len(result['instrumental_register']['report']['phrases']),3)
        self.assertGreaterEqual(len(result['instrumental_register_preparations'][0]['phrases']),3)

    # 两曲来源补证与首次生成：新增来源v3完整投影／重放和伪造通过拒绝，原父决定及音符身份保持。
    def test_bound_resolution_replay_rejects_changed_clock(self):
        from test_first_generation_meter import source_case
        from first_generation_source import _bound_decision,load_first_decision,prepare_first_source
        from first_generation_resolution import resolve_sources
        from score_export import save_json,sha256
        parent=ROOT/'test_outputs/accompaniment_runs/tests';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            folder=Path(folder);meta,arrays,evidence,voice,binding=source_case(folder)
            path=folder/'parent.json';save_json(path,_bound_decision(decide_first_generation(meta,arrays),evidence,binding))
            old_sha=sha256(path);out=folder/'resolution.json'
            value=resolve_sources(path,binding,[],out)
            self.assertEqual(load_first_decision(out,binding),value)
            updated,_=prepare_first_source(voice,binding,folder/'analysis/features',decision_path=out)
            self.assertEqual(sha256(path),old_sha)
            for before,after in zip(voice['quantized_notes'],updated['quantized_notes']):
                for key in ('id','pitch_midi','start_seconds','end_seconds','lyric_index'):
                    self.assertEqual(before.get(key),after.get(key))
            forged=deepcopy(value);forged['result']['candidates'][0]['clock']['beats'][0]['seconds']+=.1
            save_json(folder/'forged.json',forged)
            with self.assertRaisesRegex(ValueError,'重放'):
                load_first_decision(folder/'forged.json',binding)

    # 两曲来源补证与首次生成：新增三种速度同台；证据随实际鼓角色而变，不固定优先快或慢。
    def test_positive_backbeat_can_select_fast_or_slow_without_song_answers(self):
        for period in (.5,1.):
            bands,candidates=rhythm_fixture(period)
            result=compare_drum_roles(candidates,bands,128.)
            self.assertEqual(result['status'],'selected')
            self.assertEqual(result['selected_candidate_index'],1)
            self.assertAlmostEqual(next(r['bpm'] for r in result['candidates'] if r['candidate_index']==1),60/period)
            self.assertFalse(result['policy']['human_answers_or_score_timing_used'])

    # 两曲来源补证与首次生成：新增静音、没有原模型支持及两种鼓型混用不能被强行选定。
    def test_no_drum_evidence_or_distributed_competition_stays_unresolved(self):
        bands,candidates=rhythm_fixture()
        silent={k:np.zeros_like(v) if k!='times' else v for k,v in bands.items()}
        self.assertEqual(compare_drum_roles(candidates,silent,128.)['status'],'needs_review')
        for row in candidates:row['qualification']['eligible']=False
        self.assertEqual(compare_drum_roles(candidates,bands,128.)['status'],'needs_review')
        bands,candidates=rhythm_fixture()
        changed,_=rhythm_fixture(1.)
        for k in ('kick','lowmid','snare'):bands[k][6400:]=changed[k][6400:]
        self.assertEqual(compare_drum_roles(candidates,bands,128.)['status'],'needs_review')

    # 两曲来源补证与首次生成：新增首拍／首部与主体覆盖疑问不能借尾部证据消失，父候选不变。
    def test_role_selection_does_not_clear_group_or_head_uncertainty(self):
        meta,arrays,_=fixture(1.,duration=128.,extra_model_groups=True)
        parent=decide_first_generation(meta,arrays);before=deepcopy(parent)
        parent['coverage']['issues'].append({'kind':'head_not_observed','start_seconds':0.,'end_seconds':8.})
        # 两曲来源补证与首次生成：新增实际覆盖疑问必须同时属于被选择候选，防止测试只改汇总账本却要求复制错误来源。
        for candidate in parent['candidates']:
            candidate['coverage']['issues'].append({'kind':'head_not_observed','start_seconds':0.,'end_seconds':8.})
        bands,_=rhythm_fixture(1.)
        drum=compare_drum_roles(parent['candidates'],bands,128.)
        result=apply_resolution(parent,drum)
        self.assertEqual(result['status'],'needs_review')
        self.assertEqual(result['bar_first_beat']['status'],'needs_review')
        self.assertIn('head_not_observed',[r['kind'] for r in result['issues']])
        # 两曲来源补证与首次生成：修改比较加入真实首部缺口后的候选，原快照比较行保留。
        # self.assertEqual(result['candidates'],before['candidates'])
        self.assertEqual(result['candidates'],parent['candidates'])
        self.assertFalse(result['normal_publication_allowed'])

    # 两曲来源补证与首次生成：新增实际有八分攻击的结尾，正确固定拍序可覆盖；错移四分之一拍则拒绝。
    def test_observed_tail_attacks_validate_fixed_grid_and_reject_shift(self):
        beats=[{'seconds':i*.6,'beat':i%4+1} for i in range(65)]
        events=[{'seconds':i*.3+.015,'growth_db':5.,'rms_dbfs':-25.} for i in range(80,120)]
        before=deepcopy(beats)
        valid=validate_fixed_grid(beats,events,24.,36.)
        self.assertEqual(valid['status'],'supported')
        shifted=[dict(row,seconds=row['seconds']+.15) for row in beats]
        bad=validate_fixed_grid(shifted,events,24.,36.)
        self.assertEqual(bad['status'],'needs_review')
        self.assertEqual(beats,before)

    # 两曲来源补证与首次生成：新增持续声的原曲突发攻击即使缓存漏报也不能当作无新起音尾部。
    def test_original_transient_vetoes_passive_tail(self):
        import soundfile as sf
        from score_export import sha256
        from first_generation_tail import cache_dependencies
        parent=ROOT/'test_outputs/accompaniment_runs/tests';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            binding,deps=cached_tail(folder)
            self.assertEqual(inspect_unarticulated_tail(binding,6.,deps)['status'],'supported')
            path=Path(binding['sources']['mix']['path']);audio,rate=sf.read(path)
            t=np.arange(len(audio))/rate
            audio+=(.3*np.exp(-((t-6.8)/.02)**2)*np.sin(2*np.pi*320*t))
            sf.write(path,audio,rate,subtype='FLOAT')
            for source in binding['sources'].values():source['sha256']=sha256(path)
            # 两曲来源补证与首次生成：新增故意漏报的新缓存绑定，仅原混音瞬态仍须拦住错误尾部。
            import json
            for row in deps:
                meta=Path(row['metadata_path']);value=json.loads(meta.read_text(encoding='utf-8'));value['source_sha256']=sha256(path)
                meta.write_text(json.dumps(value),encoding='utf-8');row['source_sha256']=sha256(path);row['metadata_sha256']=sha256(meta)
            result=inspect_unarticulated_tail(binding,6.,deps)
            self.assertIn('original_mix_has_new_transient',result['issues'])

    # 两曲来源补证与首次生成：新增旧的全部选择门槛与尾响活动上限保持。
    def test_previous_thresholds_remain_unchanged(self):
        from first_generation_meter import POLICY
        from source_meter_hierarchy import POLICY as BASE
        from first_generation_resolution import POLICY as NEW
        self.assertEqual(POLICY['selection_policy'],BASE)
        self.assertEqual(BASE['minimum_level_margin'],.04)
        self.assertEqual(BASE['minimum_mean_beat_support'],.65)
        self.assertEqual(POLICY['maximum_unobserved_edge_seconds'],4.)
        self.assertEqual(NEW['cached_activity_policy']['maximum_relative_peak_flux'],.25)
        self.assertEqual(NEW['cached_activity_policy']['maximum_relative_median_rms'],.08)


if __name__=='__main__':unittest.main()
