"""默认入口原曲节拍强制复核：未经校准旧谱、伪可信标记、快捷绕过及失败降级反例。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import sys
import unittest
import numpy as np
import soundfile as sf

# 默认入口原曲节拍强制复核：新增任意声音／歌词的独立夹具，真实绑定文件SHA，不采用四首歌曲答案。
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from test_source_meter_rebuild import voice_fixture,temporary_workspace
from source_meter_entry import inspect_source_meter,prepare_edited_request,require_calibrated_source
from guitar_repeat_edition import notation_only_request,generate_repeat_edition
from generate_accompaniment import generate
from score_export import save_json,sha256


# 默认入口原曲节拍强制复核：新增实际原声和未校准旧工程，允许测试真实文件变动与输出前拒绝。
def unverified_project(folder,extra=None):
    vocal,timing=voice_fixture(folder,[(1.,1.7,0,False)],[(1.,1.7)])
    vocal.setdefault('audio_analysis',{}).update(tempo={'bpm':120.},duration_seconds=4.)
    if extra:extra(vocal)
    path=folder/'source_vocal.json';save_json(path,vocal)
    audio=folder/'source_mix.wav';t=np.arange(22050*4)/22050
    sf.write(audio,.1*np.sin(2*np.pi*220*t),22050,subtype='FLOAT')
    binding={'vocal_project':str(path),'vocal_project_sha256':sha256(path),
        'sources':{'mix':{'path':str(audio),'sha256':sha256(audio)}},'references':[]}
    shared={'input_binding':binding};project=folder/'project.json'
    save_json(project,{'shared_analysis':shared,'accepted_vocal_project':vocal,'arrangements':{},
        'guitar_score_layout':{'mode':'repeat_folded'}})
    save_json(folder/'manifest.json',{'files':[{'path':'project.json','sha256':sha256(project),'bytes':project.stat().st_size}]})
    args=SimpleNamespace(edited_project=project,output=folder/'new',analysis_dir=folder/'cache',report=None,
        rearrange=False,capo=None,fold_repeats=False,common_right_hand=False)
    return vocal,binding,shared,args


class SourceEntryTests(unittest.TestCase):
    # 默认入口原曲节拍强制复核：新增人工覆盖字段也不能短路真实锚点核验，登记与原轴不合时须重建。
    def test_user_override_cannot_falsely_match_registered_downbeat(self):
        with temporary_workspace() as temp:
            v,b,_,_=unverified_project(Path(temp))
            v['audio_analysis']['source_sha256']=b['sources']['mix']['sha256']
            v['timing']['beat_origin_source']='user_override'
            save_json(b['vocal_project'],v);b['vocal_project_sha256']=sha256(b['vocal_project'])
            review={'review_id':'synthetic_source_review','meter':[4,4],'quarter_bpm':120.,'anchor_seconds':.13,'anchor_quarter':0.}
            with patch('beat_phase_alignment.phase_review',return_value=review):
                self.assertTrue(inspect_source_meter(v,b)['needs_rebuild'])

    # 默认入口原曲节拍强制复核：新增真实源SHA及实际复核点一致的人工轴保留，不自动覆盖人工选择。
    def test_registered_review_matching_actual_clock_is_retained(self):
        from beat_phase_alignment import apply_phase_timing
        with temporary_workspace() as temp:
            v,b,_,_=unverified_project(Path(temp))
            v['audio_analysis']['source_sha256']=b['sources']['mix']['sha256']
            review={'review_id':'synthetic_source_review','meter':[4,4],'quarter_bpm':120.,'anchor_seconds':.13,'anchor_quarter':0.}
            v['timing']=apply_phase_timing(v['audio_analysis'],v['timing'],review)
            save_json(b['vocal_project'],v);b['vocal_project_sha256']=sha256(b['vocal_project'])
            with patch('beat_phase_alignment.phase_review',return_value=review):
                check=inspect_source_meter(v,b)
            self.assertFalse(check['needs_rebuild'])
            self.assertEqual(check['status'],'source_bound_human_review_retained')

    # 默认入口原曲节拍强制复核：新增自报已通过及完整清单仍不能使未校准拍轴直接交付。
    def test_complete_package_and_success_labels_do_not_certify_clock(self):
        with temporary_workspace() as temp:
            folder=Path(temp)
            def annotate(v):
                v['quality_status']='approved';v['timing']['requires_confirmation']=False
                v['timing']['tempo_source']='independent_source_attack_sequence'
            v,b,s,args=unverified_project(folder,annotate)
            check=inspect_source_meter(v,b)
            self.assertTrue(check['needs_rebuild'])
            updated,check=prepare_edited_request(args)
            self.assertTrue(updated.rebuild_source_meter)
            self.assertFalse(hasattr(args,'rebuild_source_meter'))
            self.assertFalse(notation_only_request(updated))

    # 默认入口原曲节拍强制复核：新增拍轴结点多也不能替代来源校正，避免把复杂数据误当正确。
    def test_many_knots_do_not_qualify_as_source_correction(self):
        with temporary_workspace() as temp:
            def annotate(v):v['timing']['knots']=[{'quarter':i,'seconds':i*.5} for i in range(80)]
            v,b,_,_=unverified_project(Path(temp),annotate)
            self.assertTrue(inspect_source_meter(v,b)['needs_rebuild'])

    # 默认入口原曲节拍强制复核：新增孤立人工复核标记不能跳过真实登记的原声／轴匹配。
    def test_unbound_review_id_does_not_bypass_clock_gate(self):
        with temporary_workspace() as temp:
            def annotate(v):v['timing']['beat_phase']={'review_id':'arbitrary_label'}
            v,b,_,_=unverified_project(Path(temp),annotate)
            self.assertTrue(inspect_source_meter(v,b)['needs_rebuild'])
            with self.assertRaisesRegex(ValueError,'停止生成'):require_calibrated_source(v,b)

    # 默认入口原曲节拍强制复核：新增伪校正层必须严格重放失败，不能有字段就自动认可。
    def test_forged_correction_is_rejected_instead_of_retained(self):
        with temporary_workspace() as temp:
            v,b,_,_=unverified_project(Path(temp))
            v['source_meter_rebuild_correction']={'version':1,'policy':{}}
            with self.assertRaisesRegex(ValueError,'不能由原来源重建'):inspect_source_meter(v,b)

    # 默认入口原曲节拍强制复核：新增源音轨变动在旧谱快捷分支及自动重建前停止。
    def test_changed_audio_is_rejected_before_any_output(self):
        with temporary_workspace() as temp:
            v,b,_,args=unverified_project(Path(temp));Path(b['sources']['mix']['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'原音轨来源已改变'):prepare_edited_request(args)
            self.assertFalse(args.output.exists())

    # 默认入口原曲节拍强制复核：新增未知旧轴与历史选项不混用，不能以明确选项悄悄绕过前置复核。
    def test_legacy_options_do_not_silently_keep_unverified_clock(self):
        with temporary_workspace() as temp:
            _,_,_,args=unverified_project(Path(temp));args.local_beat_clock=True
            with self.assertRaisesRegex(ValueError,'不能继续沿未经核对'):prepare_edited_request(args)
            self.assertFalse(args.output.exists())

    # 默认入口原曲节拍强制复核：新增自动模式真实进入先纠拍后编配，不依赖用户指定修复开关。
    def test_ordinary_old_project_request_rebuilds_before_first_arrangement(self):
        with temporary_workspace() as temp:
            v,b,s,args=unverified_project(Path(temp));new={'stage':'calibrated'}
            class FinishedOrderProbe(Exception):pass
            def gate(value,binding):
                self.assertIs(value,new);return {'status':'probe_verified'}
            # 保音持续按弦与整句八度衔接：修改顺序反例同时要求初次配音启用整句规划，原夹具签名保留。
            # def arrange(shared,vocal,capo):
            #     self.assertIs(vocal,new);raise FinishedOrderProbe()
            def arrange(shared,vocal,capo,phrase_register=False):
                self.assertTrue(phrase_register)
                self.assertIs(vocal,new);raise FinishedOrderProbe()
            with patch('generate_accompaniment.load_edited_project',return_value=(s,v,{})), patch('source_meter_project.rebuild_source_project',return_value=(s,new)) as rebuild, patch('source_meter_entry.require_calibrated_source',side_effect=gate), patch('generate_accompaniment.arrange_requested',side_effect=arrange), patch('generate_accompaniment.export_all',side_effect=AssertionError('未达到导出阶段')):
                with self.assertRaises(FinishedOrderProbe):generate(args)
                rebuild.assert_called_once()
            self.assertFalse(args.output.exists())

    # 默认入口原曲节拍强制复核：新增纠拍证据不足不得捕获后降级使用原旧谱。
    def test_failed_auto_calibration_never_falls_back_to_old_music(self):
        with temporary_workspace() as temp:
            v,b,s,args=unverified_project(Path(temp))
            with patch('generate_accompaniment.load_edited_project',return_value=(s,v,{})), patch('source_meter_project.rebuild_source_project',side_effect=ValueError('独立首拍歧义')) as rebuild, patch('generate_accompaniment.arrange_requested') as arrange, patch('generate_accompaniment.export_all') as export:
                with self.assertRaisesRegex(ValueError,'独立首拍歧义'):generate(args)
                arrange.assert_not_called();export.assert_not_called()
            self.assertFalse(args.output.exists())

    # 默认入口原曲节拍强制复核：新增直接纯排版API拒绝未校准轴，完整清单及已存在音频不能绕过。
    def test_direct_repeat_api_rejects_unverified_clock_before_copy(self):
        with temporary_workspace() as temp:
            # 默认入口原曲节拍强制复核：修改，旧输出位于源目录内先被路径保护拒绝保留；模拟真正允许的另存目录再测拍轴门槛。
            # v,b,s,args=unverified_project(Path(temp))
            source=Path(temp)/'input';source.mkdir()
            v,b,s,args=unverified_project(source);args.output=Path(temp)/'new'
            with patch('generate_accompaniment.load_edited_project',return_value=(s,v,{})), patch('guitar_repeat_edition.copytree') as copy:
                with self.assertRaisesRegex(ValueError,'不能仅复制旧谱排版'):generate_repeat_edition(args)
                copy.assert_not_called()
            self.assertFalse(args.output.exists())

    # 默认入口原曲节拍强制复核：新增新曲prepare自报成功但未建立真实校正时，和声与乐器均不能先生成。
    def test_uncalibrated_new_input_stops_before_harmony_analysis(self):
        with temporary_workspace() as temp:
            v,b,s,args=unverified_project(Path(temp));binding_path=Path(temp)/'binding.json';save_json(binding_path,b)
            args.edited_project=None;args.binding=binding_path;args.shared_analysis=None;args.six_sources=False;args.reference=[]
            with patch('source_meter_project.prepare_source_vocal',return_value=(v,{'status':'claimed_success'})), patch('generate_accompaniment.analyze') as analysis, patch('generate_accompaniment.arrange_requested') as arrange:
                with self.assertRaisesRegex(ValueError,'停止生成'):generate(args)
                analysis.assert_not_called();arrange.assert_not_called()
            self.assertFalse(args.output.exists())


if __name__=='__main__':unittest.main()
