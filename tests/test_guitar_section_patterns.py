"""演唱段稳定右手型：段内一致、根音换弦、边界保护和入口反例。"""
# 演唱段稳定右手型：新增自拟音乐测试，不用曲名／固定秒数作为答案。
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from guitar_section_patterns import (arrange_section_patterns,assess_section_patterns,
    constrain_section_choices,simple_library_candidates)
from test_guitar_readability_acceptance import fixture as base_fixture


def fixture(bars=16):
    # 演唱段稳定右手型：新增重复四小节进行，旧每小节有不同混合时值。
    project=base_fixture();voice=project['accepted_vocal_project'];total=bars*1920
    voice['statistics'].update(total_ticks=total,measure_count=bars)
    voice['timing']['knots'][-1]={'quarter':total/480,'seconds':total/480}
    guitar=project['arrangements']['guitar'];guitar['notes']=[];harmony=[]
    for i in range(bars):
        pc,name,quality,pcs=[(0,'C','',[0,4,7]),(9,'Am','m',[9,0,4]),(5,'F','',[5,9,0]),(7,'G','',[7,11,2])][i%4]
        # 演唱段稳定右手型：修改自拟材料加入真实调性与重复主旋律，不以空人声诱骗音乐复用门槛。
        # a=i*1920;harmony.append({'id':f'h{i}','start_tick':a,'end_tick':a+1920,'root_pc':pc,
        #     'bass_pc':pc,'quality':quality,'pitch_classes':pcs,'name':name})
        a=i*1920;harmony.append({'id':f'h{i}','start_tick':a,'end_tick':a+1920,'root_pc':pc,
            'bass_pc':pc,'quality':quality,'pitch_classes':pcs,'name':name,'key':deepcopy(voice['notation']['key'])})
        for j,pitch in enumerate((60,64,67,65)):
            voice['quantized_notes'].append({'id':f'voice_{i}_{j}','role':'main','start_tick':a+j*480,
                'end_tick':a+(j+1)*480,'pitch_midi':pitch,'line_index':i//8,'lyric_index':i*4+j})
        for j,offset in enumerate(([0,360,720,1200,1680] if i%2 else [0,120,480,840,1440])):
            guitar['notes'].append({'id':f'old_{i}_{j}','pitch_midi':55,'string':3,'fret':0,'start_tick':a+offset,
                'end_tick':a+min(1920,offset+120+(j%3)*120),'velocity':64,'role':'harmony','section':'vocal'})
    guitar['readable_harmony']=deepcopy(harmony);project['shared_analysis'].update(harmony=harmony,
        sections=[{'kind':'vocal','start_tick':0,'end_tick':total}])
    # 演唱段稳定右手型：新增完整八小节自然乐句边界，仍不以四小节显示行当复用段。
    guitar['readable_reuse']={'phrases':[{'id':f'phrase_{i}','start_tick':i*1920,'end_tick':min(bars,i+8)*1920} for i in range(0,bars,8)]}
    return project


class GuitarSectionPatternTests(unittest.TestCase):
    # 慢拍单位与两曲最小修订：新增再次整理既有固定型不得重用旧音身份，避免保护检查误认旧音未移除。
    def test_regenerating_existing_patterns_keeps_new_identities_distinct(self):
        original = fixture()
        first, _ = arrange_section_patterns(original)
        second, _ = arrange_section_patterns(first)
        old_ids = {n['id'] for n in first['arrangements']['guitar']['notes']}
        new_ids = [n['id'] for n in second['arrangements']['guitar']['notes']]
        self.assertEqual(len(new_ids), len(set(new_ids)))
        self.assertFalse(old_ids.intersection(new_ids))
        self.assertTrue(assess_section_patterns(second, first)['valid'])

    def test_scattered_beats_become_one_actual_rhythm_with_root_string_changes(self):
        original=fixture();new,audit=arrange_section_patterns(original)
        result=assess_section_patterns(new,original)
        self.assertTrue(result['valid'],result)
        self.assertEqual(result['sections'][0]['actual_rhythm_signatures'],1)
        self.assertEqual(result['sections'][0]['note_values_ticks'],[240])
        roots=[n['string'] for n in new['arrangements']['guitar']['notes'] if n.get('role')=='bass']
        self.assertGreater(len(set(roots)),1)
        self.assertEqual(original,fixture())

    def test_instrumental_boundary_and_complete_sustain_are_unchanged(self):
        original=fixture();note={'id':'held_original','pitch_midi':64,'string':1,'fret':0,
             'start_tick':0,'end_tick':2400,'velocity':108,'role':'instrumental_melody','section':'intro','melody_accent':True}
        original['arrangements']['guitar']['notes'].append(note)
        new,audit=arrange_section_patterns(original)
        self.assertNotIn(1,audit['arranged_measures']);self.assertNotIn(2,audit['arranged_measures'])
        actual=next(n for n in new['arrangements']['guitar']['notes'] if n['id']==note['id'])
        self.assertEqual(actual,note)
        self.assertTrue(assess_section_patterns(new,original)['valid'])
        actual['end_tick']-=120
        self.assertIn('protected_instrumental_or_boundary_note_changed',assess_section_patterns(new,original)['errors'])

    def test_policy_label_cannot_hide_one_mixed_duration(self):
        original=fixture();new,_=arrange_section_patterns(original)
        new['arrangements']['guitar']['notes'][2]['end_tick']-=120
        result=assess_section_patterns(new,original)
        self.assertFalse(result['valid']);self.assertTrue(any(e.startswith('mixed_section_note_values') for e in result['errors']))

    def test_policy_label_cannot_hide_extra_attack_or_changed_upper_order(self):
        original=fixture();new,_=arrange_section_patterns(original)
        new['arrangements']['guitar']['notes'][2]['start_tick']+=120
        self.assertTrue(any(e.startswith('nonuniform_section_attacks') for e in assess_section_patterns(new,original)['errors']))
        new,_=arrange_section_patterns(original);new['arrangements']['guitar']['notes'][1]['string']=2
        self.assertTrue(any(e.startswith('unstable_upper_string_order') for e in assess_section_patterns(new,original)['errors']))

    def test_approved_voice_harmony_and_piano_are_protected(self):
        original=fixture();new,_=arrange_section_patterns(original)
        new['accepted_vocal_project']['timing']['knots'][-1]['seconds']+=.1
        new['arrangements']['piano']['notes']=[{'id':'unexpected'}]
        new['shared_analysis']['harmony'][0]['name']='changed'
        errors=assess_section_patterns(new,original)['errors']
        self.assertIn('approved_voice_or_clock_changed',errors);self.assertIn('approved_source_harmony_changed',errors)
        self.assertIn('protected_piano_changed',errors)

    def test_tiny_phrase_score_changes_cannot_switch_style_inside_section(self):
        shared={'sections':[{'kind':'vocal','start_tick':0,'end_tick':7680}], 'phrase_harmony_plan':{'families':[]}}
        phrases=[{'id':'a','start_tick':0,'end_tick':3840},{'id':'b','start_tick':3840,'end_tick':7680}]
        details={'a':[{'score':0.},{'score':3.}], 'b':[{'score':1.},{'score':0.}]}; selected={'a':0,'b':1}
        constrain_section_choices(shared,phrases,details,selected)
        self.assertEqual(selected,{'a':0,'b':0})

    def test_mixed_and_dense_candidates_are_not_default_section_patterns(self):
        from guitar_right_hand_patterns import library
        actual=simple_library_candidates(library()['patterns'])
        self.assertEqual({p['id'] for p in actual},{'arp_4_4_up','arp_4_4_roll','arp_4_4_sparse'})
        self.assertTrue(all(p['step_ticks']>=240 and '-' not in p['slots'] for p in actual))

    def test_repeat_plan_can_reuse_new_uniform_actual_music(self):
        from guitar_variable_repeat import build_repeat_plan
        original=fixture(32);new,_=arrange_section_patterns(original)
        plan=build_repeat_plan(new)
        self.assertTrue(plan['repeat_groups'])
        self.assertTrue(all(g['length_bars']>=8 for g in plan['repeat_groups']))

    def test_public_entry_routes_before_whole_song_reanalysis(self):
        from generate_accompaniment import generate
        args=SimpleNamespace(edited_project=Path('existing.json'),output=Path('new'),stable_vocal_patterns=True)
        with patch('generate_accompaniment.read_json',return_value=fixture()),patch('revise_guitar_patterns.revise',return_value={'valid':True}) as revised:
            self.assertEqual(generate(args),{'valid':True});revised.assert_called_once_with(args.edited_project,args.output,None)

    def test_shared_natural_boundaries_survive_first_pattern_revision(self):
        # 全曲目固定右手预览：新增旧工程仅有共享自然乐句时的真实长段反复反例，不用曲名或固定时点。
        from guitar_variable_repeat import build_repeat_plan,validate_repeat_plan
        original=fixture(32)
        phrases=original['arrangements']['guitar'].pop('readable_reuse')['phrases']
        original['shared_analysis']['phrase_harmony_plan']={'phrases':deepcopy(phrases)}
        new,_=arrange_section_patterns(original)
        self.assertEqual(new['arrangements']['guitar']['readable_reuse']['phrases'],phrases)
        self.assertEqual(new['shared_analysis'],original['shared_analysis'])
        plan=build_repeat_plan(new)
        self.assertTrue(plan['repeat_groups'])
        self.assertTrue(all(g['length_bars']>=8 for g in plan['repeat_groups']))
        self.assertTrue(validate_repeat_plan(plan,new)['valid'])

    def test_missing_top_level_flag_still_preserves_pattern_entry(self):
        from generate_accompaniment import generate
        original=fixture();new,_=arrange_section_patterns(original);new.pop('vocal_pattern_revision')
        args=SimpleNamespace(edited_project=Path('existing.json'),output=Path('new'))
        with patch('generate_accompaniment.read_json',return_value=new),patch('revise_guitar_patterns.revise',return_value={'valid':True}) as revised:
            self.assertEqual(generate(args),{'valid':True});self.assertTrue(revised.called)

    def test_actual_pattern_notes_cannot_bypass_source_guard_by_losing_metadata(self):
        # 演唱段稳定右手型：新增实际音符标记防降级反例，不只检查一个顶层布尔值。
        from guitar_readability_acceptance import has_guitar_readability_revision
        original=fixture();new,_=arrange_section_patterns(original)
        new.pop('vocal_pattern_revision');new.pop('guitar_readability_revision')
        new['arrangements']['guitar'].pop('section_patterns');new['arrangements']['guitar']['configuration'].pop('stable_vocal_patterns')
        self.assertTrue(has_guitar_readability_revision(new))
        self.assertFalse(assess_section_patterns(new,original)['valid'])

    def test_pattern_tag_does_not_authorize_extra_notes_in_protected_bars(self):
        # 演唱段稳定右手型：新增有标签仍不能越过器乐边界的反例。
        original=fixture();original['arrangements']['guitar']['notes'][0]['section']='intro'
        new,_=arrange_section_patterns(original);extra=deepcopy(new['arrangements']['guitar']['notes'][-1])
        extra.update(id='unexpected',start_tick=240,end_tick=480)
        new['arrangements']['guitar']['notes'].append(extra)
        self.assertIn('new_pattern_note_outside_authorized_vocal_bar',assess_section_patterns(new,original)['errors'])

    def test_confirmed_source_break_is_not_filled_by_uniform_pattern(self):
        # 演唱段稳定右手型：新增原伴奏确实静默时保留完整小节，不能为固定型机械补音。
        original=fixture();guitar=original['arrangements']['guitar']
        guitar['notes']=[n for n in guitar['notes'] if not (1440<=n['start_tick']<1920)]
        original['shared_analysis']['harmony_windows']=[{'start_seconds':0.,'end_seconds':3.,'accompaniment_rms':.1},
            {'start_seconds':3.,'end_seconds':4.,'accompaniment_rms':0.}]
        new,audit=arrange_section_patterns(original)
        self.assertNotIn(1,audit['arranged_measures'])
        self.assertTrue(any(e['reason']=='preserve_confirmed_source_break' for e in audit['exceptions']))

    def test_capo_handover_revoices_local_half_bar_without_changing_right_hand(self):
        # 演唱段稳定右手型：新增开放指型换夹的几何反例；单个指型贪心无解时应只重排前一组配音。
        original=fixture();guitar=original['arrangements']['guitar'];boundary=8*1920
        guitar['configuration']['capo_fret']=1
        guitar['configuration']['capo_segments']=[{'start_tick':0,'end_tick':boundary,'capo_fret':1},
            {'start_tick':boundary,'end_tick':16*1920,'capo_fret':2}]
        for row in guitar['readable_harmony']:
            first=row['start_tick']<boundary
            row.update(root_pc=1 if first else 6,bass_pc=1 if first else 6,quality='sus4' if first else 'm',
                       pitch_classes=[1,6,8] if first else [6,9,1],name='C#sus4' if first else 'F#m')
        original['shared_analysis']['harmony']=deepcopy(guitar['readable_harmony'])
        new,audit=arrange_section_patterns(original)
        self.assertGreater(audit['voicing_handover']['attempts'],0)
        self.assertTrue(assess_section_patterns(new,original)['valid'])
        self.assertTrue(all(e['end_tick']-e['start_tick']<=960 for e in audit['voicing_handover']['local_voicing_edits']))


if __name__=='__main__':
    # 演唱段稳定右手型：新增可单独执行的语义反例。
    unittest.main()
