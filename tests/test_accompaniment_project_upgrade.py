"""旧工程功能自动升级与三曲器乐表现统一：独立旧数据、真实导出、幂等及来源篡改反例。"""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import mido
import numpy as np
import soundfile as sf
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
from test_guitar_instrumental_expression import prepared
from test_guitar_repeat_score import music as repeat_music
from accompaniment_project_upgrade import (inspect_project_features, ensure_project_features,
    repair_missing_expression_fields, validate_upgrade_scope, delivery_capabilities)
from accompaniment_export import write_midi, synthesize, build_musicxml, guitar_row
from guitar_repeat_score import write_repeat_score
from guitar_repeat_edition import notation_only_request,generate_repeat_edition
import contextlib
import io
from score_export import save_json, sha256
from types import SimpleNamespace

TEMP = ROOT / 'test_outputs/accompaniment_runs/project_upgrade_tests'; TEMP.mkdir(parents=True, exist_ok=True)


# 旧工程功能自动升级与三曲器乐表现统一：新增已知C主题／低弦填充／普通唱段夹具，不用真实歌曲答案。
def fixture(folder):
    shared, vocal, guitar, parent, _ = prepared(folder)
    # 旧工程功能自动升级与三曲器乐表现统一：新增合法时间顺序，旧夹具的末尾插入填充不作为事件排序变更测试。
    guitar['attack_events'].sort(key=lambda e:e['start_tick'])
    save_json(parent,{'shared_analysis':shared,'accepted_vocal_project':vocal,'arrangements':{'guitar':guitar}})
    return shared, vocal, {'guitar': guitar}, parent


class ProjectFeatureUpgradeTests(unittest.TestCase):
    def run_case(self, action):
        with tempfile.TemporaryDirectory(dir=TEMP) as temporary: return action(Path(temporary))

    # 旧工程功能自动升级与三曲器乐表现统一：新增缺失自动填、音值／低音／正文保护及零背景重筛。
    def test_missing_old_feature_automatically_adds_known_focus(self):
        def case(folder):
            s,v,a,parent=fixture(folder); new,report=ensure_project_features(s,v,a,parent,folder)
            notes={n['id']:n for n in new['guitar']['notes']}
            self.assertTrue(report['changed']);self.assertEqual(notes['melody']['velocity'],106)
            self.assertTrue(notes['melody']['melody_accent']);self.assertEqual(notes['fill']['velocity'],50)
            self.assertEqual(report['migrations'][0]['changes']['rest_changes'],0)
            self.assertTrue(report['scope']['valid']);self.assertTrue(report['after']['complete'])
        self.run_case(case)

    def test_false_version_tag_cannot_substitute_for_actual_data(self):
        def case(folder):
            s,v,a,parent=fixture(folder);a['guitar']['feature_versions']={'guitar_instrumental_expression':1}
            self.assertTrue(inspect_project_features(s,v,a)['data_capabilities']['guitar_instrumental_expression']['needed'])
            new,report=ensure_project_features(s,v,a,parent,folder);self.assertTrue(report['changed'])
        self.run_case(case)

    def test_complete_feature_is_idempotent_on_multiple_reexports(self):
        def case(folder):
            s,v,a,parent=fixture(folder); first,_=ensure_project_features(s,v,a,parent,folder)
            second,report=ensure_project_features(s,v,first,parent,folder)
            third,third_report=ensure_project_features(s,v,second,parent,folder)
            self.assertEqual(first,second);self.assertEqual(second,third)
            self.assertFalse(report['changed']);self.assertFalse(third_report['changed'])
        self.run_case(case)

    def test_missing_accent_attribute_is_recovered_from_bound_source(self):
        def case(folder):
            s,v,a,parent=fixture(folder);first,_=ensure_project_features(s,v,a,parent,folder)
            old=deepcopy(first['guitar']);next(n for n in old['notes'] if n['id']=='melody').pop('melody_accent')
            new,repairs=repair_missing_expression_fields(s,v,old)
            self.assertEqual(new,first['guitar']);self.assertEqual(repairs,[{'note_id':'melody','field':'melody_accent'}])
        self.run_case(case)

    def test_missing_original_velocity_and_velocity_are_recovered_without_reboost(self):
        def case(folder):
            s,v,a,parent=fixture(folder);first,_=ensure_project_features(s,v,a,parent,folder)
            old=deepcopy(first['guitar']);target=next(n for n in old['notes'] if n['id']=='fill')
            target.pop('velocity');target.pop('expression_original_velocity')
            new,repairs=repair_missing_expression_fields(s,v,old)
            self.assertEqual(new,first['guitar']);self.assertEqual(len(repairs),2)
        self.run_case(case)

    def test_existing_wrong_accent_value_is_rejected_instead_of_overwritten(self):
        def case(folder):
            s,v,a,parent=fixture(folder);first,_=ensure_project_features(s,v,a,parent,folder)
            next(n for n in first['guitar']['notes'] if n['id']=='melody')['melody_accent']=False
            with self.assertRaises(ValueError):ensure_project_features(s,v,first,parent,folder)
        self.run_case(case)

    def test_existing_wrong_velocity_is_rejected(self):
        def case(folder):
            s,v,a,parent=fixture(folder);first,_=ensure_project_features(s,v,a,parent,folder)
            next(n for n in first['guitar']['notes'] if n['id']=='melody')['velocity']=1
            with self.assertRaises(ValueError):ensure_project_features(s,v,first,parent,folder)
        self.run_case(case)

    def test_bound_source_changed_after_upgrade_is_rejected(self):
        def case(folder):
            s,v,a,parent=fixture(folder);first,_=ensure_project_features(s,v,a,parent,folder)
            # 旧工程功能自动升级与三曲器乐表现统一：修改篡改目标，旧夹具路径保留；验证实际绑定的来源（内存元组可能需要另存快照）。
            # parent.write_text(parent.read_text('utf-8')+' ','utf-8')
            bound=Path(first['guitar']['instrumental_expression']['upstream_project'])
            bound.write_text(bound.read_text('utf-8')+' ','utf-8')
            with self.assertRaises(ValueError):ensure_project_features(s,v,first,parent,folder)
        self.run_case(case)

    def test_unbound_existing_emphasis_is_not_double_applied(self):
        def case(folder):
            s,v,a,parent=fixture(folder);a['guitar']['notes'][0]['melody_accent']=True
            with self.assertRaisesRegex(ValueError,'来源绑定'):ensure_project_features(s,v,a,parent,folder)
        self.run_case(case)

    def test_unknown_expression_policy_is_rejected(self):
        def case(folder):
            s,v,a,parent=fixture(folder);first,_=ensure_project_features(s,v,a,parent,folder)
            first['guitar']['instrumental_expression']['version']=999
            with self.assertRaises(ValueError):ensure_project_features(s,v,first,parent,folder)
        self.run_case(case)

    def test_normal_notes_and_nonfill_bass_are_completely_unchanged(self):
        def case(folder):
            s,v,a,parent=fixture(folder);first,_=ensure_project_features(s,v,a,parent,folder)
            new={n['id']:n for n in first['guitar']['notes']}
            for identity in ('normal','bass'):
                self.assertEqual(new[identity],next(n for n in a['guitar']['notes'] if n['id']==identity))
        self.run_case(case)

    def test_vocal_instrumental_role_is_not_automatically_emphasized(self):
        def case(folder):
            s,v,a,parent=fixture(folder);target=next(n for n in a['guitar']['notes'] if n['id']=='normal');target['role']='instrumental_melody'
            first,_=ensure_project_features(s,v,a,parent,folder)
            self.assertEqual(next(n for n in first['guitar']['notes'] if n['id']=='normal'),target)
        self.run_case(case)

    def test_upgrade_never_invokes_background_filter(self):
        def case(folder):
            s,v,a,parent=fixture(folder)
            with patch('instrumental_clarity.build_clarity_plan',side_effect=AssertionError('unexpected background filter')):
                first,report=ensure_project_features(s,v,a,parent,folder)
            self.assertFalse(report['background_and_density_rhythm_reanalysis'])
            self.assertEqual(first['guitar']['instrumental_expression']['settings']['rest_intervals'],[])
            self.assertEqual(len(first['guitar']['notes']),len(a['guitar']['notes']))
        self.run_case(case)

    def test_maximum_existing_velocity_is_not_lowered_or_overflowed(self):
        def case(folder):
            s,v,a,parent=fixture(folder);a['guitar']['notes'][0]['velocity']=127
            first,_=ensure_project_features(s,v,a,parent,folder)
            self.assertEqual(next(n for n in first['guitar']['notes'] if n['id']=='melody')['velocity'],127)
        self.run_case(case)

    def test_piano_fingering_and_pedal_objects_are_preserved(self):
        def case(folder):
            s,v,a,parent=fixture(folder);a['piano']={'notes':[{'id':'p','pitch_midi':60,'velocity':80}],
                'pedal_events':[{'tick':0,'state':'down'}],'hand_positions':[{'tick':0,'position':60}]}
            before=deepcopy(a['piano']);first,_=ensure_project_features(s,v,a,parent,folder)
            self.assertEqual(first['piano'],before)
        self.run_case(case)

    def test_actual_input_objects_and_legacy_files_are_never_modified(self):
        def case(folder):
            s,v,a,parent=fixture(folder);before=deepcopy((s,v,a));digest=sha256(parent)
            ensure_project_features(s,v,a,parent,folder)
            self.assertEqual((s,v,a),before);self.assertEqual(sha256(parent),digest)
        self.run_case(case)

    def test_changed_fret_rhythm_chord_or_normal_velocity_fail_scope_guard(self):
        def case(folder):
            s,v,a,parent=fixture(folder)
            for field,value in (('fret',19),('start_tick',33),('chord_id','wrong'),('velocity',1)):
                tampered=deepcopy(a);next(n for n in tampered['guitar']['notes'] if n['id']=='normal')[field]=value
                self.assertFalse(validate_upgrade_scope(s,v,a,tampered)['valid'])
        self.run_case(case)

    def test_real_rest_and_attack_events_are_preserved(self):
        def case(folder):
            # 旧工程功能自动升级与三曲器乐表现统一：修改休止夹具，旧只改音符却保留错误攻击元数据保留；保留真实原有空档。
            # s,v,a,parent=fixture(folder);a['guitar']['notes'][0]['start_tick']=120;a['guitar']['notes'][0]['end_tick']=240
            s,v,a,parent=fixture(folder)
            a['guitar']['notes']=[n for n in a['guitar']['notes'] if n['start_tick']!=0]
            a['guitar']['attack_events']=[e for e in a['guitar']['attack_events'] if e['start_tick']!=0]
            first,_=ensure_project_features(s,v,a,parent,folder)
            self.assertEqual(a['guitar']['attack_events'],first['guitar']['attack_events'])
            # 旧工程功能自动升级与三曲器乐表现统一：修改真实休止范围，旧120tick保留；原首拍已有空档必须仍为空。
            # self.assertEqual([n['start_tick'] for n in a['guitar']['notes'] if n['start_tick']<120],
            #                  [n['start_tick'] for n in first['guitar']['notes'] if n['start_tick']<120])
            self.assertEqual([n['start_tick'] for n in first['guitar']['notes'] if n['start_tick']<480],[])
        self.run_case(case)

    def test_no_applicable_instrumental_notes_does_not_invent_accents(self):
        def case(folder):
            s,v,a,parent=fixture(folder);s['sections']=[{**section,'kind':'vocal'} for section in s['sections']]
            first,report=ensure_project_features(s,v,a,parent,folder)
            self.assertEqual(first,a);self.assertFalse(report['changed']);self.assertTrue(report['after']['complete'])
        self.run_case(case)

    def test_display_capability_only_registered_after_actual_validation(self):
        def case(folder):
            s,v,a,parent=fixture(folder);_,report=ensure_project_features(s,v,a,parent,folder)
            with self.assertRaises(ValueError):delivery_capabilities(report,{'valid':False})
            # 吉他长段反复与流畅阅读：修改显示能力版本预期，原1版注释保留；音乐升级边界仍由其它断言保护。
            # self.assertEqual(delivery_capabilities(report,{'valid':True})['display_capabilities']['guitar_repeat_layout']['version'],1)
            self.assertEqual(delivery_capabilities(report,{'valid':True})['display_capabilities']['guitar_repeat_layout']['version'],2)
        self.run_case(case)

    # 旧工程功能自动升级与三曲器乐表现统一：新增真实XML／SVG／SMF／PCM校验，不能只写版本标签或黑点。
    def test_actual_xml_and_svg_add_accent_to_only_main_melody(self):
        def case(folder):
            s,v,a,parent=fixture(folder);new,_=ensure_project_features(s,v,a,parent,folder)
            root,_=build_musicxml(s,v,new['guitar']);self.assertEqual(len(root.findall('.//articulations/accent')),1)
            svg=ET.fromstring(guitar_row(s,v,new['guitar'],1,2));ns='{http://www.w3.org/2000/svg}'
            accents=[n for n in svg.iter(ns+'circle') if n.get('class')=='melody-accent']
            self.assertEqual([n.get('data-note-id') for n in accents],['melody'])
        self.run_case(case)

    def test_actual_midi_velocity_and_intervals_follow_upgraded_notes(self):
        def case(folder):
            s,v,a,parent=fixture(folder);new,_=ensure_project_features(s,v,a,parent,folder);path=folder/'new.mid'
            write_midi(path,new['guitar'],v);attacks=[]
            for track in mido.MidiFile(path).tracks:
                tick=0
                for message in track:
                    tick+=message.time
                    if message.type=='note_on' and message.velocity:attacks.append((tick,message.note,message.velocity))
            self.assertCountEqual(attacks,[(n['start_tick'],n['pitch_midi'],n['velocity']) for n in new['guitar']['notes']])
        self.run_case(case)

    def test_actual_pcm_changes_emphasis_and_idempotent_wave_is_identical(self):
        def case(folder):
            s,v,a,parent=fixture(folder);new,_=ensure_project_features(s,v,a,parent,folder)
            again,_=ensure_project_features(s,v,new,parent,folder)
            synthesize(folder/'old.wav',a['guitar'],v);synthesize(folder/'new.wav',new['guitar'],v);synthesize(folder/'again.wav',again['guitar'],v)
            self.assertNotEqual(sha256(folder/'old.wav'),sha256(folder/'new.wav'))
            self.assertEqual(sha256(folder/'new.wav'),sha256(folder/'again.wav'))
        self.run_case(case)

    def test_inherited_folded_edition_selected_without_per_song_upgrade_flags(self):
        def case(folder):
            path=folder/'project.json';save_json(path,{'guitar_score_layout':{'mode':'repeat_folded'}})
            save_json(folder/'manifest.json',{'files':[{'path':'project.json','sha256':sha256(path)}]})
            args=SimpleNamespace(edited_project=path,fold_repeats=False,capo=None)
            self.assertTrue(notation_only_request(args))
            args.rearrange=True;self.assertFalse(notation_only_request(args))
        self.run_case(case)

    def test_fresh_chronological_export_replaces_stale_full_page(self):
        def case(folder):
            s,v,g=repeat_music();(folder/'score_full.html').write_text('OLD','utf-8');(folder/'score.html').write_text('NEW','utf-8')
            with patch('guitar_repeat_score.write_repeat_html'):
                write_repeat_score(folder,s,v,g,fresh_chronological=True)
            self.assertEqual((folder/'score_full.html').read_text('utf-8'),'NEW')
        self.run_case(case)

    # 旧工程功能自动升级与三曲器乐表现统一：新增完整工程真实复制入口回归，布局必须收到吉他对象且不调用音频重合成。
    def test_complete_package_copy_passes_only_guitar_to_layout(self):
        def case(folder):
            s,v,a,parent=fixture(folder);a,report=ensure_project_features(s,v,a,parent,folder)
            source=folder/'source';source.mkdir();(source/'guitar').mkdir()
            save_json(source/'project.json',{'shared_analysis':s,'accepted_vocal_project':v,'arrangements':a})
            save_json(source/'manifest.json',{'files':[]});save_json(source/'validation.json',{'valid':True})
            (source/'index.html').write_text('<nav></nav>','utf-8');(source/'guitar/score.html').write_text('accepted','utf-8')
            report['changed']=False;report['migrations']=[]
            actual={n['id']:n for n in a['guitar']['notes']}
            def draw(path,shared,vocal,guitar):
                self.assertEqual(guitar,a['guitar']);self.assertIn('notes',guitar)
                # 吉他编配规则闭环修复：新增纯接口夹具的计划文件；真实印刷／硬验收由独立产物反例覆盖。
                save_json(path/'repeat_plan.json',{'expanded_bars':2,'printed_bars':2})
                return {'valid':True,'plan':{'expanded_bars':2,'printed_bars':2}}
            args=SimpleNamespace(edited_project=source/'project.json',output=folder/'output',analysis_dir=folder,report=None)
            # 默认入口原曲节拍强制复核：修改，旧纯复制布局夹具入口保留；本例模拟已复核音乐，拍轴绕过由新增测试独立验证。
            # with patch('generate_accompaniment.validate_output_path',return_value=args.output), \
            with patch('source_meter_entry.require_calibrated_source',return_value={'status':'test_verified'}), patch('generate_accompaniment.validate_output_path',return_value=args.output), \
                 patch('generate_accompaniment.load_edited_project',return_value=(s,v,a)), \
                 patch('generate_accompaniment.write_collection_index'), \
                 patch('accompaniment_project_upgrade.ensure_project_features',return_value=(a,report)), \
                 patch('accompaniment_export.export_all',side_effect=AssertionError('complete audio regenerated')), \
                 patch('guitar_repeat_edition.ET.parse',return_value=SimpleNamespace(getroot=lambda:None)), \
                 patch('accompaniment_export.parse_musicxml_notes',return_value=(actual,{'valid':True})), \
                 patch('accompaniment_export.validate_midi',return_value={'valid':True}), \
                 patch('guitar_readability_acceptance.assess_guitar_readability',return_value={'valid':True,'errors':[]}) as contract, \
                 patch('guitar_readability_acceptance.require_guitar_readability',return_value=True) as gate, \
                 patch('guitar_repeat_edition.write_repeat_score',side_effect=draw),contextlib.redirect_stdout(io.StringIO()):
                result=generate_repeat_edition(args)
            # 吉他编配规则闭环修复：新增确保纯复制入口确实执行共用实际验收，而不是跳过新增门槛。
            contract.assert_called_once();gate.assert_called_once()
            self.assertFalse(result['repeat_edition_preservation']['music_feature_upgrade'])
            self.assertEqual((args.output/'guitar/score.html').read_text('utf-8'),'accepted')
        self.run_case(case)


if __name__=='__main__':unittest.main()
