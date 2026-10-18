"""常用指型与器乐独奏：常用真值、器乐不强配图及实际覆盖/时序反例。"""
# 常用指型与器乐独奏：新增自拟音符夹具，不以自动识别的真实歌曲结果作音乐真值。
import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from test_accompaniment import fixture
from accompaniment_arrange import TUNING,shape_candidates
from guitar_grip_library import common_grips,load_library,validate_definition
# 常用指型与器乐独奏：修改，原导入保留；增加持握结束后下一次攻击的边界反例。
# from guitar_grip_policy import assess_grip,select_common,validate_grip_policy
from guitar_grip_policy import assess_grip,select_common,validate_grip_policy,grip_position_path
from guitar_chord_diagrams import prepare_diagrams
# 常用指型与器乐独奏：新增持续换把修正的精确音高与必要释音反例。
from guitar_exact_positions import refinger_exact_positions
import accompaniment_export as export
import score_export as score
NS='{http://www.w3.org/2000/svg}'


# 常用指型与器乐独奏：新增固定弦品和声夹具，可明确选择器乐或演唱区。
def known(root=0,quality='',section='vocal',capo=0,pairs=None):
    shared,vocal=fixture()
    shared['sections']=[{'kind':section,'label':'演唱' if section=='vocal' else '前奏','start_tick':0,'end_tick':3840}]
    for row in shared['measure_textures']:row['section']=section
    key=score.key_definition('C:major')
    from accompaniment_analysis import CHORD_TYPES,chord_name
    chord={'id':'common_h','root_pc':(root+capo)%12,'quality':quality,'bass_pc':(root+capo)%12,'key':key,
           'pitch_classes':[(root+capo+i)%12 for i in CHORD_TYPES[quality]],'start_tick':0,'end_tick':3840}
    chord['name']=chord_name(chord['root_pc'],quality,chord['bass_pc'],key);shared['harmony']=[chord]
    notes=[]
    for index,pair in enumerate(pairs or [(5,3),(1,0),(2,1),(3,0)]):
        string,fret=pair;tick=index*240
        notes.append({'id':'common_note_'+str(index),'string':string,'fret':fret,'pitch_midi':TUNING[string]+capo+fret,
                      'start_tick':tick,'end_tick':tick+180,'role':'instrumental_melody','finger':0 if fret==0 else 1,
                      'hand_position':1,'velocity':80})
    guitar={'instrument':'guitar','configuration':{'capo_fret':capo},'notes':notes,'attack_events':[],
            'hand_positions':[{'tick':0,'position':1}], 'adjustments':[], 'pedal':[]}
    return shared,vocal,guitar


class CommonGripPolicyTests(unittest.TestCase):
    # 常用指型与器乐独奏：新增基础完整指型真值，同时检查进入真实编配候选。
    def test_complete_c_is_first_arrangement_candidate(self):
        self.assertEqual(shape_candidates(0,'',0,0)[0]['frets'],{'5':3,'4':2,'3':0,'2':1,'1':0})

    def test_c_unused_pressed_strings_are_kept_in_diagram(self):
        s,v,g=known(pairs=[(5,3),(1,0)])
        prepare_diagrams(s,g,v)
        self.assertEqual(g['fingering_diagrams'][0]['frets'],{'5':3,'4':2,'3':0,'2':1,'1':0})

    def test_complete_am_open_grip(self):
        s,v,g=known(9,'m',pairs=[(5,0),(2,1),(1,0)])
        prepare_diagrams(s,g,v)
        self.assertEqual(g['fingering_diagrams'][0]['frets'],{'5':0,'4':2,'3':2,'2':1,'1':0})

    def test_capo_translates_chord_semantics_without_transposing_frets(self):
        s,v,g=known(capo=1)
        prepare_diagrams(s,g,v);chart=g['fingering_diagrams'][0]
        # 常用指型与器乐独奏：修改，原Db期望保留；夹具使用C大调的升号拼写，应为等音C#。
        # self.assertEqual(chart['shape_name'],'C');self.assertEqual(chart['sounding_name'],'Db')
        self.assertEqual(chart['shape_name'],'C');self.assertEqual(chart['sounding_name'],'C#')
        self.assertEqual(chart['frets']['5'],3)

    def test_catalog_rejects_cadd9_mislabeled_as_csus2(self):
        item={'root_pc':0,'quality':'sus2','bass_pc':0,'frets_6_to_1':[-1,3,2,0,3,3]}
        self.assertFalse(validate_definition(item))

    def test_gadd9_catalog_actual_notes(self):
        entry=next(e for e in common_grips(7,'add9',7) if e['frets_6_to_1']==[3,-1,0,2,0,3])
        pcs={(t+f)%12 for t,f in zip([40,45,50,55,59,64],entry['frets_6_to_1']) if f>=0}
        self.assertEqual(pcs,{7,11,2,9})

    def test_high_melody_is_solo_instead_of_forced_gadd9(self):
        s,v,g=known(7,'add9','intro',pairs=[(3,0),(1,10),(1,12)])
        before=copy.deepcopy(g['notes']);prepare_diagrams(s,g,v)
        self.assertEqual(g['notes'],before);self.assertEqual(g['fingering_diagrams'],[])
        self.assertTrue(all(r['mode']=='solo_tab' for r in g['notation_regions']))

    def test_numeric_solo_includes_open_zero_and_no_x(self):
        s,v,g=known(7,'add9','intro',pairs=[(3,0),(1,10),(1,12)])
        vocal_notes=copy.deepcopy(v['quantized_notes']);v['quantized_notes']=[]
        prepare_diagrams(s,g,v);root=ET.fromstring(export.guitar_row(s,v,g,1,2))
        values=[node.find(NS+'text').text for node in root.iter(NS+'g') if node.get('data-string')]
        self.assertEqual(values,['0','10','12']);self.assertEqual(root.get('data-instrumental-tab-only'),'true')
        self.assertLess(float(root.get('height')),300)
        self.assertTrue(export.validate_tab([{'guitar':ET.tostring(root,encoding='unicode')}],g)['valid'])
        self.assertTrue(vocal_notes)

    def test_solo_xml_omits_harmony_but_keeps_all_notes(self):
        s,v,g=known(7,'add9','intro',pairs=[(3,0),(1,10),(1,12)])
        prepare_diagrams(s,g,v);root,_=export.build_musicxml(s,v,g)
        self.assertEqual(root.findall('part/measure/harmony'),[])
        parsed,check=export.parse_musicxml_notes(root)
        self.assertTrue(check['valid'],check)
        self.assertEqual({k:(n['pitch_midi'],n['start_tick'],n['end_tick']) for k,n in parsed.items()},
                         {n['id']:(n['pitch_midi'],n['start_tick'],n['end_tick']) for n in g['notes']})

    def test_matching_instrumental_c_can_keep_chord(self):
        s,v,g=known(section='intro')
        prepare_diagrams(s,g,v)
        self.assertEqual(g['fingering_diagrams'][0]['shape_name'],'C')
        self.assertTrue(g['fingering_diagrams'][0].get('common_grip_id'))

    def test_same_pitch_on_other_string_does_not_count_as_matching_grip(self):
        s,v,g=known(pairs=[(3,5)])
        entry=next(e for e in common_grips(0,'',0) if e['frets_6_to_1']==[-1,3,2,0,1,0])
        check=assess_grip(entry,g['notes'],0,3840)
        self.assertEqual(check['match_ratio'],0.);self.assertFalse(check['valid'])

    def test_small_melodic_finger_addition_can_keep_common_grip(self):
        s,v,g=known(pairs=[(5,3),(2,1),(3,0),(1,1)])
        selected=select_common(s['harmony'][0],g['notes'],0,3840,0)
        self.assertIsNotNone(selected);self.assertLessEqual(selected[1]['max_temporary_finger_changes'],2)

    def test_more_than_two_finger_changes_reject_even_with_high_match_ratio(self):
        s,v,g=known(pairs=[(5,3)]*10+[(4,0),(3,2),(2,3),(1,2)])
        for note in g['notes'][10:]:note['start_tick']=2640;note['end_tick']=2820
        entry=next(e for e in common_grips(0,'',0) if e['frets_6_to_1']==[-1,3,2,0,1,0])
        check=assess_grip(entry,g['notes'],0,3840)
        self.assertGreater(check['match_ratio'],.65)
        self.assertGreater(check['max_temporary_finger_changes'],2);self.assertFalse(check['valid'])

    def test_static_fret_span_failure_rejects_full_grip(self):
        s,v,g=known(pairs=[(5,3),(2,1),(3,0),(1,12)])
        entry=next(e for e in common_grips(0,'',0) if e['frets_6_to_1']==[-1,3,2,0,1,0])
        self.assertEqual(assess_grip(entry,g['notes'],0,3840)['reason'],'complete_grip_and_sustains_not_coverable')

    def test_lost_diagram_and_replaced_x_are_still_rejected(self):
        s,v,g=known();prepare_diagrams(s,g,v);root=ET.fromstring(export.guitar_row(s,v,g,1,2))
        for node in list(root):
            if node.get('class')=='chord-diagram':root.remove(node)
        notes={n['id']:n for n in g['notes']}
        for group in root.iter(NS+'g'):
            if group.get('data-string'):
                group.find(NS+'text').text=str(notes[group.get('id')]['fret']);group.attrib.pop('data-diagram-id',None)
        self.assertFalse(export.validate_tab([{'guitar':ET.tostring(root,encoding='unicode')}],g)['valid'])

    def test_changed_common_library_geometry_is_rejected(self):
        s,v,g=known();prepare_diagrams(s,g,v)
        g['fingering_diagrams'][0]['frets'].pop('4')
        self.assertFalse(validate_grip_policy(s,g,v)['valid'])

    def test_solo_x_without_current_grip_is_rejected(self):
        s,v,g=known(7,'add9','intro',pairs=[(3,0),(1,10),(1,12)])
        prepare_diagrams(s,g,v);root=ET.fromstring(export.guitar_row(s,v,g,1,2))
        next(n for n in root.iter(NS+'g') if n.get('data-string')).find(NS+'text').text='x'
        self.assertFalse(export.validate_tab([{'guitar':ET.tostring(root,encoding='unicode')}],g)['valid'])

    def test_derived_c_fingering_matches_complete_grip_without_changing_notes(self):
        s,v,g=known(pairs=[(5,3),(2,1)])
        before=copy.deepcopy(g['notes']);prepare_diagrams(s,g,v)
        self.assertEqual(g['notes'],before);self.assertEqual(g['grip_fingerings']['common_note_0'],3)

    def test_high_csus2_does_not_force_obscure_instrumental_diagram(self):
        s,v,g=known(0,'sus2','intro',pairs=[(2,8),(1,10)])
        prepare_diagrams(s,g,v)
        self.assertEqual(g['fingering_diagrams'],[])

    def test_whole_library_has_unique_ids_and_valid_chord_semantics(self):
        entries=load_library()['entries']
        self.assertEqual(len(entries),len({e['id'] for e in entries}))
        self.assertTrue(all(validate_definition(e) for e in entries))

    # 常用指型与器乐独奏：新增静态可按但换把时间不足的反例，必须撤销常用图而不能放宽时序。
    def test_common_grip_is_rejected_when_transition_is_too_fast(self):
        s,v,g=known(pairs=[(1,8),(5,3),(1,0)])
        g['notes'][0].update(start_tick=0,end_tick=120)
        g['notes'][1].update(start_tick=130,end_tick=300)
        g['notes'][2].update(start_tick=480,end_tick=660)
        g['hand_positions']=[{'tick':0,'position':3}]
        chord=copy.deepcopy(s['harmony'][0]);chord.update(start_tick=120)
        s['harmony']=[chord]
        s['sections']=[{'kind':'intro','label':'前奏','start_tick':0,'end_tick':120},
                       {'kind':'vocal','label':'演唱','start_tick':120,'end_tick':3840}]
        before=copy.deepcopy(g['notes']);prepare_diagrams(s,g,v)
        self.assertEqual(g['notes'],before)
        self.assertTrue(any(r['reason']=='common_grip_rejected_transition' for r in g['notation_regions']))
        self.assertLessEqual(g['grip_position_rate'],24+1e-8)
        self.assertTrue(validate_grip_policy(s,g,v)['valid'])

    # 常用指型与器乐独奏：新增小节内人声开始的边界，器乐选择不跨到后半小节。
    def test_instrumental_and_vocal_boundary_inside_measure(self):
        s,v,g=known(pairs=[(5,3),(1,0),(2,1),(3,0)])
        s['sections']=[{'kind':'intro','label':'前奏','start_tick':0,'end_tick':480},
                       {'kind':'vocal','label':'演唱','start_tick':480,'end_tick':3840}]
        prepare_diagrams(s,g,v)
        self.assertEqual([(r['start_tick'],r['end_tick'],r['section']) for r in g['notation_regions']],
                         [(0,480,'intro'),(480,3840,'vocal')])
        self.assertEqual(g['fingering_diagrams'][0]['end_tick'],480)
        root=ET.fromstring(export.guitar_row(s,v,g,1,2))
        self.assertIsNone(root.get('data-instrumental-tab-only'))

    # 常用指型与器乐独奏：新增同音换弦保持完整时值的独立音高真值。
    def test_same_pitch_refingering_keeps_attack_and_release(self):
        s,v,g=known(section='intro',pairs=[(1,15),(2,8)])
        g['notes'][0].update(start_tick=0,end_tick=240)
        g['notes'][1].update(start_tick=240,end_tick=480)
        check=refinger_exact_positions(s,v,g)
        self.assertEqual((g['notes'][1]['string'],g['notes'][1]['fret']),(3,12))
        self.assertEqual((g['notes'][1]['pitch_midi'],g['notes'][1]['start_tick'],g['notes'][1]['end_tick']),(67,240,480))
        self.assertEqual(check['changed_note_count'],1);self.assertEqual(check['release_change_count'],0)

    # 常用指型与器乐独奏：新增固定低音阻止所有同音解时的最小释音，音高与起音仍须精确。
    def test_fixed_low_bass_uses_only_minimum_necessary_release(self):
        s,v,g=known(section='outro',pairs=[(1,11),(1,4),(6,4)])
        g['notes'][0].update(start_tick=0,end_tick=480)
        for note in g['notes'][1:]:note.update(start_tick=480,end_tick=960)
        check=refinger_exact_positions(s,v,g)
        self.assertEqual(check['changed_note_count'],0);self.assertEqual(check['release_change_count'],1)
        self.assertEqual(g['notes'][0]['end_tick'],360)
        self.assertEqual([(n['pitch_midi'],n['start_tick']) for n in g['notes']],[(75,0),(68,480),(44,480)])
        self.assertLessEqual(check['maximum_actual_note_position_rate'],24+1e-8)

    # 常用指型与器乐独奏：新增同时延续的两个低把位音必须联合结束，不能只释放一个就假称可移动。
    # 常用指型与器乐独奏：修改，原两音均截短用例保留；旋律同音换弦配合低音释放应保持旋律延音。
    # def test_two_held_notes_need_joint_minimum_release(self):
    def test_refingering_and_bass_release_keep_held_melody(self):
        s,v,g=known(section='outro',pairs=[(1,2),(6,2),(1,9)])
        for note in g['notes'][:2]:note.update(start_tick=0,end_tick=480)
        g['notes'][2].update(start_tick=480,end_tick=720)
        check=refinger_exact_positions(s,v,g)
        # 常用指型与器乐独奏：修改，原两音释放期望保留；用第二弦七品延续同音，只释放固定低音。
        # self.assertEqual(check['release_change_count'],2)
        # self.assertEqual([n['end_tick'] for n in g['notes'][:2]],[360,360])
        self.assertEqual(check['release_change_count'],1)
        self.assertEqual([n['end_tick'] for n in g['notes'][:2]],[480,360])
        self.assertEqual((g['notes'][0]['string'],g['notes'][0]['fret']),(2,7))
        self.assertEqual(g['notes'][2]['start_tick'],480)

    # 常用指型与器乐独奏：新增两个固定低音确实不能同音换弦，必须联合释放，禁止把同弦重叠当可行。
    def test_two_fixed_low_notes_still_need_joint_release(self):
        s,v,g=known(section='outro',pairs=[(6,1),(5,1),(1,9)])
        for note in g['notes'][:2]:note.update(start_tick=0,end_tick=480)
        g['notes'][2].update(start_tick=480,end_tick=720)
        check=refinger_exact_positions(s,v,g)
        self.assertEqual(check['release_change_count'],2)
        self.assertEqual([n['end_tick'] for n in g['notes'][:2]],[360,360])
        self.assertEqual(check['changed_note_count'],0)

    # 常用指型与器乐独奏：新增提前三次攻击规划的案例，最高音本身只有一种位置，禁止移八度绕过。
    def test_joint_earlier_refingering_prepares_fixed_high_note(self):
        s,v,g=known(section='interlude',pairs=[(1,5),(5,8),(3,0),(2,13),(1,17)])
        for note,begin,end in zip(g['notes'],[0,360,360,480,600],[360,480,480,600,840]):
            note.update(start_tick=begin,end_tick=end)
        before=[(n['pitch_midi'],n['start_tick'],n['end_tick']) for n in g['notes']]
        check=refinger_exact_positions(s,v,g)
        self.assertEqual(before,[(n['pitch_midi'],n['start_tick'],n['end_tick']) for n in g['notes']])
        self.assertEqual(check['release_change_count'],0)
        self.assertEqual((g['notes'][-1]['string'],g['notes'][-1]['fret']),(1,17))
        self.assertEqual(check['changed_note_count'],2)

    # 常用指型与器乐独奏：新增图式已结束但准备时间不足，须定位前一持握，不能误称数字段本身无解。
    def test_ended_grip_still_explains_next_attack_transition_failure(self):
        s,v,g=known(pairs=[(3,6),(1,11)])
        g['notes'][0].update(start_tick=0,end_tick=480)
        g['notes'][1].update(start_tick=480,end_tick=720)
        g['fingering_diagrams']=[{'id':'ended_grip','start_tick':0,'end_tick':420,
                                  'frets':{'3':6,'1':2}}]
        check=grip_position_path(g,v)
        self.assertFalse(check['valid']);self.assertEqual(check['tick'],480)
        self.assertEqual(check['chart_id'],'ended_grip')
        g['fingering_diagrams']=[]
        self.assertTrue(grip_position_path(g,v)['valid'])

    # 常用指型与器乐独奏：新增无和声器乐段仍为数字TAB，既不画图也不残留和弦文字。
    def test_no_chord_instrumental_region_has_no_harmony_text(self):
        s,v,g=known(section='intro',pairs=[(3,0),(1,10)])
        s['harmony'][0]['name']='N.C.';v['quantized_notes']=[]
        prepare_diagrams(s,g,v);root=ET.fromstring(export.guitar_row(s,v,g,1,2))
        self.assertFalse(g['fingering_diagrams'])
        self.assertNotIn('N.C.',[n.text for n in root.iter(NS+'text')])
        self.assertTrue(export.validate_tab([{'guitar':ET.tostring(root,encoding='unicode')}],g)['valid'])

    # 常用指型与器乐独奏：新增非网格器乐/演唱边界，通过和弦offset表达而不是产生无法记谱的碎音。
    def test_non_grid_region_boundary_does_not_split_musicxml_notes(self):
        s,v,g=known(pairs=[(5,3),(1,0),(2,1),(3,0)])
        s['sections']=[{'kind':'intro','label':'前奏','start_tick':0,'end_tick':333},
                       {'kind':'vocal','label':'演唱','start_tick':333,'end_tick':3840}]
        prepare_diagrams(s,g,v);root,_=export.build_musicxml(s,v,g)
        parsed,check=export.parse_musicxml_notes(root)
        self.assertTrue(check['valid'],check)
        self.assertEqual({k:(n['start_tick'],n['end_tick'],n['pitch_midi']) for k,n in parsed.items()},
                         {n['id']:(n['start_tick'],n['end_tick'],n['pitch_midi']) for n in g['notes']})
        self.assertIn('333',[n.text for n in root.findall('part/measure/harmony/offset')])

    # 常用指型与器乐独奏：新增演唱区无图时移除空白指型层，仍保留人声简谱层与全部TAB。
    def test_vocal_numeric_row_has_no_empty_diagram_space(self):
        s,v,g=known(section='vocal',pairs=[(5,3),(1,0)])
        s['harmony'][0]['name']='N.C.'
        prepare_diagrams(s,g,v);root=ET.fromstring(export.guitar_row(s,v,g,1,2))
        self.assertTrue(v['quantized_notes']);self.assertIsNone(root.get('data-instrumental-tab-only'))
        self.assertLess(float(root.get('height')),450)
        self.assertTrue(export.validate_tab([{'guitar':ET.tostring(root,encoding='unicode')}],g)['valid'])


if __name__=='__main__':unittest.main()
