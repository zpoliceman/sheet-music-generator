"""首拍与首尾局部补证：独立内容证据及保留未决的反例。"""
# 首拍与首尾局部补证：新增真实算法正反例，不以歌曲名称、答案或测试数代替音乐验收。
import sys
from pathlib import Path
from copy import deepcopy
import tempfile
import unittest
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from source_clock_content import POLICY,content_grouping,residual_calibration,inspect_prefix
from first_generation_content import apply_content
from source_meter_sequence import VECTOR_KEYS
from score_export import save_json


def fixture(phase=0,bass=True):
    # 首拍与首尾局部补证：新增每四拍改变稳态内容、首三拍模型打平的匿名材料。
    at=np.arange(0,129,.02);beats=[{'seconds':float(i),'beat':i%4+1} for i in range(129)]
    candidate={'clock':{'beats':beats},'candidate_index':1,'grouping':{'issues':[{'kind':'insufficient_independent_grouping_support'}]},'counterfactual_issues':[]}
    roles={}
    for role in ('accompaniment','six_guitar','bass'):
        if role=='bass' and not bass:continue
        state=((np.floor(at).astype(int)-phase)//4)%3
        roles[role]={'times':at,'rms':np.ones(len(at)),**{key:(state==i).astype(float) if i<3 else np.zeros(len(at)) for i,key in enumerate(VECTOR_KEYS[:12])}}
    return candidate,roles


class SourceContentTests(unittest.TestCase):
    def test_two_steady_ranges_and_temporal_distribution(self):
        c,tr=fixture();value=content_grouping(c,tr,128.)
        self.assertEqual(value['status'],'supported')
        self.assertTrue(all(r['supported'] and len(r['temporal_thirds'])==3 for r in value['ranges']))

    def test_correlated_harmonic_stems_cannot_replace_bass(self):
        c,tr=fixture(bass=False)
        self.assertEqual(content_grouping(c,tr,128.)['status'],'needs_review')

    def test_opposite_content_phase_rejected(self):
        c,tr=fixture(phase=2)
        self.assertEqual(content_grouping(c,tr,128.)['status'],'needs_review')

    def test_local_source_consensus_cannot_be_averaged_away(self):
        c,tr=fixture()
        for role,row in tr.items():
            use=(row['times']>=64)&(row['times']<96)
            state=((np.floor(row['times'][use]).astype(int)-2)//4)%3
            for i,key in enumerate(VECTOR_KEYS[:12]):row[key][use]=(state==i).astype(float) if i<3 else 0.
        self.assertEqual(content_grouping(c,tr,128.)['status'],'needs_review')

    def test_low_energy_bass_is_not_independent_evidence(self):
        c,tr=fixture();tr['bass']['rms'][:int(.9*len(tr['bass']['rms']))]=.0001
        self.assertEqual(content_grouping(c,tr,128.)['status'],'needs_review')

    def test_explicit_model_or_short_bar_conflict_preserved(self):
        for kind in ('fixed_grid_phase_conflict','short_bar_context_insufficient'):
            c,tr=fixture();c['grouping']['issues'].append({'kind':kind})
            self.assertEqual(content_grouping(c,tr,128.)['status'],'needs_review')

    def test_source_counterfactual_is_not_cleared(self):
        c,tr=fixture();c['counterfactual_issues']=[{'kind':'source_roles_support_third'}]
        self.assertEqual(content_grouping(c,tr,128.)['status'],'needs_review')

    def test_apply_does_not_infer_unit_or_delete_parent_candidates(self):
        c,_=fixture();parent={'notation_level':{'status':'needs_review','issues':['unit_ambiguous']},
          'bar_first_beat':{'status':'needs_review','issues':[{'kind':'insufficient_independent_grouping_support'}]},
          'coverage':{'issues':[{'kind':'source_window_unresolved','start_seconds':32.,'end_seconds':64.}]},
          'selected_candidate_index':1,'candidates':[c]}
        before=deepcopy(parent);out=apply_content(parent,{'status':'supported'},{'status':'needs_review'},None)
        self.assertEqual(out['status'],'needs_review');self.assertEqual(out['candidates'],before['candidates']);self.assertEqual(parent,before)
        self.assertEqual([r['kind'] for r in out['issues']],['notation_level_unresolved','source_window_unresolved'])

    def test_calibration_requires_actual_full_second_original_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'mix.wav';rate=8000;t=np.arange(2*rate)/rate
            sf.write(path,.001*np.sin(2*np.pi*220*t),rate,subtype='FLOAT')
            binding={'duration_seconds':2.,'sources':{'mix':{'path':str(path)}}}
            self.assertEqual(residual_calibration(binding)['status'],'needs_review')
            sf.write(path,np.zeros(2*rate),rate,subtype='FLOAT')
            self.assertEqual(residual_calibration(binding)['status'],'supported')

    def test_missing_prefix_positive_evidence_stays_unresolved(self):
        c,_=fixture()
        self.assertEqual(inspect_prefix({'duration_seconds':128.},c,[],{'status':'needs_review'})['status'],'needs_review')

    def test_fourth_source_version_replays_and_rejects_forged_effective_clock(self):
        # 首拍与首尾局部补证：新增真实来源绑定／完整重放，篡改有效拍轴而保留passed也必须失败。
        from test_first_generation_meter import source_case
        from first_generation_source import _bound_decision,load_first_decision
        from first_generation_meter import decide_first_generation
        from first_generation_resolution import resolve_sources
        from first_generation_content import resolve_content
        from score_export import sha256
        root=Path(__file__).resolve().parents[1];folder_root=root/'test_outputs/accompaniment_runs/tests';folder_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder_root) as temp:
            folder=Path(temp);meta,arrays,evidence,voice,binding=source_case(folder)
            parent=folder/'parent.json';save_json(parent,_bound_decision(decide_first_generation(meta,arrays),evidence,binding))
            p3=folder/'roles.json';resolve_sources(parent,binding,[],p3)
            p4=folder/'content.json';value=resolve_content(p3,binding,p4)
            original_sha=sha256(parent);self.assertEqual(load_first_decision(p4,binding),value)
            forged=deepcopy(value);forged['result']['effective_source_clock']={'beats':[{'seconds':0.,'beat':1},{'seconds':1.,'beat':2}]}
            save_json(folder/'forged.json',forged)
            with self.assertRaisesRegex(ValueError,'重放'):load_first_decision(folder/'forged.json',binding)
            self.assertEqual(sha256(parent),original_sha)


if __name__=='__main__':unittest.main()
