"""4/4可选右手与实时谱面试听：实际动作、余音、来源保护和产物反例。"""
# 4/4可选右手与实时谱面试听：新增有音乐行为的自拟用例，覆盖用户三个示例及错误输入，不使用歌曲专用答案。
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys
import json
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from test_guitar_section_patterns import fixture
from guitar_pattern_selection import (compile_selection, assess_selection, catalogue, has_selection,
    normalize_choice, normalize_plan)
from guitar_pattern_performance import performance_notes


def selected(pattern='A01', project=None, **options):
    # 4/4可选右手与实时谱面试听：新增以实际编译产物作为测试对象。
    original=project if project is not None else fixture(4)
    revised,audit=compile_selection(original,{'default':{'pattern_id':pattern,**options}})
    return original,revised,audit


class GuitarPatternSelectionTests(unittest.TestCase):
    # 4/4可选右手与实时谱面试听：新增未选型完整保护，避免打开编辑器便改变既有音乐。
    def test_no_selection_is_exact_and_does_not_mutate_source(self):
        original=fixture(4);before=deepcopy(original)
        for plan in (None,{}, {'version':1,'default':None,'sections':[]}):
            actual,audit=compile_selection(original,plan)
            self.assertEqual(actual,before);self.assertEqual(original,before)
            self.assertFalse(audit['music_changed'])

    def test_every_catalogue_choice_compiles_actual_4_4_music_and_grip(self):
        for pattern in catalogue()['patterns']:
            with self.subTest(pattern=pattern['id']):
                original,revised,audit=selected(pattern['id'])
                check=assess_selection(revised,original)
                self.assertTrue(check['valid'],check)
                self.assertTrue(audit['music_changed'])
                self.assertTrue(performance_notes(revised['arrangements']['guitar']))

    def test_user_reverse_example_has_correct_eighth_positions_and_strings(self):
        _,revised,_=selected('A02')
        actions=revised['arrangements']['guitar']['selected_pattern_actions'][:8]
        self.assertEqual([e['start_tick'] for e in actions],list(range(0,1920,240)))
        self.assertEqual([e['strings'][0] for e in actions],[5,1,2,3,5,1,2,3])

    def test_empty_slot_rings_without_retrigger_and_stop_is_distinct(self):
        _,ring,_=selected('A03');_,stop,_=selected('A03',silence='stop')
        r=ring['arrangements']['guitar'];s=stop['arrangements']['guitar']
        self.assertFalse(any(n['start_tick']==960 for n in r['notes']))
        old=next(n for n in r['notes'] if n['start_tick']==720)
        muted=next(n for n in s['notes'] if n['start_tick']==720)
        self.assertEqual(old['end_tick'],1680)
        self.assertEqual(muted['end_tick'],960)
        self.assertEqual(r['selected_pattern_actions'][4]['kind'],'air')
        self.assertEqual(s['selected_pattern_actions'][4]['kind'],'stop')

    def test_other_strings_continue_while_new_string_is_plucked(self):
        _,revised,_=selected()
        notes=revised['arrangements']['guitar']['notes']
        bass=next(n for n in notes if n['start_tick']==0)
        self.assertEqual(bass['end_tick'],960)
        self.assertTrue(any(n['start_tick']==240 and n['end_tick']>480 for n in notes))

    def test_user_sparse_strum_has_four_attacks_and_first_eighth_does_not_choke(self):
        _,revised,_=selected('S07')
        events=[e for e in revised['arrangements']['guitar']['selected_pattern_actions'] if e['start_tick']<1920]
        attacks=[e for e in events if e['note_ids']]
        self.assertEqual([e['start_tick'] for e in attacks],[0,1440,1680,1800])
        self.assertEqual([e['action_span_ticks'] for e in attacks],[240,240,120,120])
        self.assertEqual(attacks[-1]['direction'],'up')
        self.assertTrue(all(n['end_tick']>=1440 for n in revised['arrangements']['guitar']['notes'] if n['start_tick']==0))

    def test_pinch_is_simultaneous_and_up_down_have_actual_opposite_string_orders(self):
        _,pinch,_=selected('A14');arr=pinch['arrangements']['guitar']
        event=arr['selected_pattern_actions'][2]
        self.assertEqual(event['kind'],'pinch');self.assertEqual(event['strings'],[1,2])
        actual={n['id']:n for n in performance_notes(arr)}
        self.assertEqual({actual[i]['start_tick'] for i in event['note_ids']},{480})
        _,strum,_=selected('S04');arr=strum['arrangements']['guitar']
        actual={n['id']:n for n in performance_notes(arr)}
        for event in arr['selected_pattern_actions'][:3]:
            ordered=sorted((actual[i]['start_tick'],actual[i]['string']) for i in event['note_ids'])
            strings=[s for _,s in ordered]
            self.assertEqual(strings,sorted(strings,reverse=event['direction']=='down'))
            self.assertLessEqual(max(t for t,_ in ordered)-min(t for t,_ in ordered),20)

    def test_fake_sweep_cannot_hide_distinct_subdivision_attacks(self):
        _,revised,_=selected('S01');arr=revised['arrangements']['guitar']
        identity=arr['selected_pattern_actions'][0]['note_ids'][0]
        next(n for n in arr['notes'] if n['id']==identity)['start_tick']+=30
        with self.assertRaisesRegex(ValueError,'独立拨弦'):
            performance_notes(arr)

    def test_note_value_changes_cycle_without_squeezing(self):
        _,quarters,_=selected('A02',note_value='quarter')
        self.assertEqual(quarters['right_hand_selection']['plan']['default']['cycle_ticks'],3840)
        starts=[e['start_tick'] for e in quarters['arrangements']['guitar']['selected_pattern_actions']]
        self.assertEqual(starts[:8],list(range(0,3840,480)))
        _,sixteenths,_=selected('A02',note_value='sixteenth')
        starts=[e['start_tick'] for e in sixteenths['arrangements']['guitar']['selected_pattern_actions']]
        self.assertEqual(starts[:16],list(range(0,1920,120)))

    def test_individual_values_and_invalid_lengths_are_not_silently_filled(self):
        _,revised,_=selected('A03',durations=[480,120,120,240,240,240,240,240])
        actual=revised['arrangements']['guitar']['selected_pattern_actions'][:8]
        self.assertEqual([e['start_tick'] for e in actual],[0,480,600,720,960,1200,1440,1680])
        with self.assertRaisesRegex(ValueError,'循环长'):
            normalize_choice({'pattern_id':'A03','durations':[120,240,240,240,240,240,240,240]})
        with self.assertRaisesRegex(ValueError,'混合时值'):
            normalize_choice({'pattern_id':'S03','note_value':'sixteenth'})
        with self.assertRaises(ValueError):
            normalize_choice({'pattern_id':'A01','durations':[60]*8})
        with self.assertRaises(ValueError):
            normalize_choice({'pattern_id':'not-a-pattern'})

    def test_fixed_fifth_string_remains_fifth(self):
        _,revised,_=selected('A02',bass_mode='fixed_5')
        events=revised['arrangements']['guitar']['selected_pattern_actions']
        self.assertTrue(all(e['strings']==[5] for i,e in enumerate(events) if i%4==0))

    def test_instrumental_boundary_full_sustain_is_exactly_preserved(self):
        original=fixture(4)
        held={'id':'held','start_tick':0,'end_tick':2400,'pitch_midi':64,'string':1,'fret':0,
              'velocity':100,'role':'instrumental_melody','section':'intro','melody_accent':True}
        original['arrangements']['guitar']['notes'].append(held)
        _,revised,audit=selected('A14',original)
        self.assertEqual(audit['arranged_measures'],[3,4])
        self.assertEqual(next(n for n in revised['arrangements']['guitar']['notes'] if n['id']=='held'),held)
        self.assertTrue(assess_selection(revised,original)['valid'])

    def test_capo_boundary_uses_bounded_voicing_without_changing_actions(self):
        # 4/4可选右手与实时谱面试听：新增开放指型在换夹处无法提前到达的实际反例，保持原手位门槛。
        original=fixture(2);guitar=original['arrangements']['guitar']
        guitar['configuration']['capo_segments']=[{'start_tick':0,'capo_fret':1},{'start_tick':1920,'capo_fret':2}]
        harmony=original['shared_analysis']['harmony']
        harmony[0].update(name='C#sus4',root_pc=1,bass_pc=1,quality='sus4',pitch_classes=[1,6,8])
        harmony[1].update(name='F#m',root_pc=6,bass_pc=6,quality='m',pitch_classes=[6,9,1])
        guitar['readable_harmony']=deepcopy(harmony)
        guitar['fingering_diagrams']=[{'id':'old0','start_tick':0,'end_tick':1920,'frets':{'5':3,'4':3,'3':0,'2':1,'1':1},'capo':1},
            {'id':'old1','start_tick':1920,'end_tick':3840,'frets':{'6':0,'5':2,'4':2,'3':0,'2':0,'1':0},'capo':2}]
        _,new,_=selected('A14',original)
        self.assertTrue(new['right_hand_selection']['voicing_handover']['valid'])
        self.assertTrue(new['right_hand_selection']['voicing_handover']['edits'])
        self.assertEqual([e['start_tick'] for e in new['arrangements']['guitar']['selected_pattern_actions']],list(range(0,3840,240)))
        self.assertTrue(assess_selection(new,original)['valid'])

    def test_one_section_override_protects_every_other_note(self):
        original=fixture(12)
        for n in original['arrangements']['guitar']['notes']:
            if 4*1920<=n['start_tick']<5*1920:n['section']='interlude'
        new,audit=compile_selection(original,{'sections':[{'section_id':'vocal_section_001','choice':{'pattern_id':'S01'}}]})
        self.assertEqual(audit['arranged_measures'],[1,2,3,4])
        actual={n['id']:n for n in new['arrangements']['guitar']['notes']}
        self.assertTrue(all(actual[n['id']]==n for n in original['arrangements']['guitar']['notes'] if n['start_tick']>=4*1920))
        self.assertTrue(assess_selection(new,original)['valid'])

    def test_plan_labels_cannot_hide_changed_notes_actions_voice_or_piano(self):
        original,new,_=selected('A14')
        for field in ('end_tick','pitch_midi','string'):
            bad=deepcopy(new);bad['arrangements']['guitar']['notes'][0][field]+=120 if field=='end_tick' else 1
            self.assertFalse(assess_selection(bad,original)['valid'])
        bad=deepcopy(new);bad['arrangements']['guitar']['selected_pattern_actions'][0]['strings']=[6]
        self.assertFalse(assess_selection(bad,original)['valid'])
        bad=deepcopy(new);bad['accepted_vocal_project']['timing']['knots'][-1]['seconds']+=1
        self.assertFalse(assess_selection(bad,original)['valid'])
        bad=deepcopy(new);bad['arrangements']['piano']['notes']=[{'id':'unexpected'}]
        self.assertFalse(assess_selection(bad,original)['valid'])

    def test_lost_metadata_still_triggers_selection_guard(self):
        original,new,_=selected();new.pop('right_hand_selection')
        self.assertTrue(has_selection(new));self.assertFalse(assess_selection(new,original)['valid'])
        from guitar_readability_acceptance import has_guitar_readability_revision
        self.assertTrue(has_guitar_readability_revision(new))

    def test_saved_json_preserves_actual_shape_and_cannot_hide_fret_edit(self):
        # 4/4可选右手与实时谱面试听：新增真实JSON往返，弦号键规范化后仍校验实际按法。
        original,new,_=selected('A14')
        saved=json.loads(json.dumps(new,ensure_ascii=False))
        self.assertTrue(assess_selection(saved,original)['valid'])
        saved['arrangements']['guitar']['fingering_diagrams'][0]['frets']['1']+=1
        self.assertFalse(assess_selection(saved,original)['valid'])

    def test_protected_natural_release_keeps_sound_and_gets_readable_notation(self):
        # 4/4可选右手与实时谱面试听：新增旧自然余音在格点间结束的反例，音频／MIDI不裁音，谱面不引入极短动作。
        from guitar_pattern_performance import notation_notes
        source=fixture(4)
        notes=source['arrangements']['guitar']['notes']
        held={'id':'protected_natural_release','string':1,'fret':0,'pitch_midi':64,'start_tick':0,'end_tick':450,
              'velocity':80,'role':'instrumental_melody','section':'intro'}
        source['arrangements']['guitar']['notes']=[held]+[n for n in notes if n['start_tick']>=1920]
        _,new,_=selected('A14',source);g=new['arrangements']['guitar']
        self.assertEqual(next(n for n in g['notes'] if n['id']==held['id']),held)
        self.assertEqual(next(n for n in notation_notes(g) if n['id']==held['id'])['end_tick'],480)
        self.assertEqual(next(n for n in performance_notes(g) if n['id']==held['id'])['end_tick'],450)
        self.assertTrue(assess_selection(new,source)['valid'])
        g['natural_release_notation'][0]['notation_end_tick']=600
        self.assertFalse(assess_selection(new,source)['valid'])

    def test_real_tab_xml_midi_and_audio_are_all_driven_by_choice(self):
        from accompaniment_export import build_musicxml,write_midi,validate_midi,_synthesis_buffer
        from export_timing_revision import render_row
        from guitar_variable_repeat import measure_timeline
        from guitar_readability_acceptance import _xml_notes
        import numpy as np
        for pattern in ('A03','A14','S07'):
            from test_score_export import project_from,note
            source=fixture(4)
            voice=project_from([note('held_voice',0,8,64)],seconds=8)
            voice['timing'].update(source['accepted_vocal_project']['timing'])
            voice['lyrics']={'characters':[]}
            source['accepted_vocal_project']=voice
            source['shared_analysis']['input_binding']={'vocal_project_sha256':'synthetic'}
            source['shared_analysis']['sections'][0]['label']='演唱段'
            original,new,_=selected(pattern,source);g=new['arrangements']['guitar'];voice=new['accepted_vocal_project']
            folder=Path(__file__).resolve().parents[1]/'test_outputs/accompaniment_runs/tests'
            folder.mkdir(parents=True,exist_ok=True)
            with TemporaryDirectory(dir=folder) as tmp:
                path=Path(tmp)/'score.mid';write_midi(path,g,voice)
                self.assertTrue(validate_midi(path,g,voice)['valid'])
                root,_=build_musicxml(new['shared_analysis'],voice,g)
                path=Path(tmp)/'score.musicxml';ET.ElementTree(root).write(path)
                actual,check=_xml_notes(path,measure_timeline(new))
                self.assertTrue(check['valid'],check)
                self.assertEqual(sorted(actual),sorted((n['pitch_midi'],n['start_tick'],n['end_tick'],n['string'],n['fret']) for n in g['notes']))
                svg=render_row(new,measure_timeline(new)[:2],True)
                self.assertIn('right-hand-action',svg)
                if pattern=='S07':self.assertIn('arpeggiate',ET.tostring(root,encoding='unicode'))
                if pattern=='S07':
                    from guitar_pattern_performance import validate_action_artifacts
                    folder=Path(tmp)/'guitar';(folder/'rows').mkdir(parents=True)
                    ET.ElementTree(root).write(folder/'score.musicxml')
                    complete_svg=render_row(new,measure_timeline(new),True)
                    (folder/'rows/voice_001.svg').write_text(complete_svg,encoding='utf-8')
                    self.assertTrue(validate_action_artifacts(new,Path(tmp))['valid'])
                    # 扫弦箭头与实际弦组记谱修正：停用Unicode换向伪造，实际移走箭头尖必须被硬验收拒绝。
                    # (folder/'rows/voice_001.svg').write_text(complete_svg.replace('↓','↑',1),encoding='utf-8')
                    damaged=ET.fromstring(complete_svg)
                    next(n for n in damaged.iter() if n.get('class')=='strum-head').set('points','0,0 0,9 5,0')
                    (folder/'rows/voice_001.svg').write_text(ET.tostring(damaged,encoding='unicode'),encoding='utf-8')
                    self.assertFalse(validate_action_artifacts(new,Path(tmp))['valid'])
                audio,_=_synthesis_buffer(g,voice,start_tick=0,end_tick=1920)
                self.assertEqual(len(audio),round(4*22050));self.assertGreater(float(np.max(abs(audio))),.01)

    def test_public_generate_dispatches_explicit_selection_before_old_protection(self):
        from generate_accompaniment import generate
        original=fixture(4);original['bar_boundary_revision']={'old':'kept'}
        args=SimpleNamespace(edited_project=Path('old.json'),output=Path('new'),right_hand_plan=Path('choice.json'))
        with patch('generate_accompaniment.read_json',return_value=original),patch('revise_guitar_selection.revise_selection',return_value={'valid':True}) as called:
            self.assertEqual(generate(args),{'valid':True})
            called.assert_called_once_with(args.edited_project,args.output,args.right_hand_plan,None)

    def test_repeat_signature_includes_direction_and_silent_action(self):
        from guitar_variable_repeat import bar_signature,measure_timeline
        _,new,_=selected('S01');row=measure_timeline(new)[0]
        original=bar_signature(new,row)
        new['arrangements']['guitar']['selected_pattern_actions'][0]['direction']='up'
        self.assertNotEqual(bar_signature(new,row),original)

    def test_no_choice_current_delivery_copy_is_exact_and_explicit_edits_exit_it(self):
        # 4/4可选右手与实时谱面试听：新增实际原样另存、发布授权不迁移、非空目录与明确编辑反例。
        import guitar_pattern_preservation as keep
        from score_export import save_json
        folder=Path(__file__).resolve().parents[1]/'test_outputs/accompaniment_runs/tests'
        folder.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=folder) as tmp:
            root=Path(tmp);source=root/'results/accompaniment/approved'
            (source/'guitar').mkdir(parents=True)
            save_json(source/'project.json',fixture(4))
            (source/'guitar/score.html').write_text('<html>既有曲谱</html>',encoding='utf-8')
            (source/'guitar/preview.wav').write_bytes(b'unchanged_audio')
            (source/'publication.json').write_text('{}',encoding='utf-8')
            (source/'revision_report.json').write_text('{"historical":true}',encoding='utf-8')
            (source.parent/'index.html').write_text('<a href="approved/index.html">当前曲谱</a>',encoding='utf-8')
            output=root/'test_outputs/accompaniment_runs/copy'
            args=SimpleNamespace(edited_project=source/'project.json',output=output,right_hand_plan=None)
            with patch.object(keep,'ROOT',root),patch('revise_guitar_selection.validate_parent',return_value={'valid':True}),patch('revise_guitar_selection.verify_sources',return_value={}),patch('scoped_music_publication.require_scoped_publication',return_value={'valid':True}) as approval:
                self.assertTrue(keep.frozen_delivery_request(args))
                args.refresh_reading=True;self.assertFalse(keep.frozen_delivery_request(args));args.refresh_reading=False
                report=keep.copy_frozen_delivery(args.edited_project,output)
                self.assertFalse(report['music_changed'])
                self.assertEqual((output/'project.json').read_bytes(),(source/'project.json').read_bytes())
                self.assertEqual((output/'guitar/preview.wav').read_bytes(),b'unchanged_audio')
                self.assertFalse((output/'publication.json').exists())
                self.assertEqual((output/'revision_report.json').read_text(encoding='utf-8'),'{"historical":true}')
                approval.assert_called_once()
                with self.assertRaises(ValueError):keep.copy_frozen_delivery(args.edited_project,output)
                approval.side_effect=ValueError('交付文件改变')
                with self.assertRaisesRegex(ValueError,'交付文件改变'):
                    keep.copy_frozen_delivery(args.edited_project,root/'test_outputs/accompaniment_runs/rejected')
            from revise_guitar_selection import validate_parent
            with patch('scoped_music_publication.require_scoped_publication',side_effect=ValueError('认可基线已变')):
                with self.assertRaisesRegex(ValueError,'认可基线已变'):
                    validate_parent(fixture(4),source/'project.json')


if __name__=='__main__':
    # 4/4可选右手与实时谱面试听：新增单独执行入口。
    unittest.main()
