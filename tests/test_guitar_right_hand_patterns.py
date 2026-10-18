"""常用右手伴奏型：新增音乐语义、边界保护与篡改反例验证。"""
# 常用右手伴奏型：新增独立已知C和弦音序，不以重跑相同实现作为测试真值。
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from test_accompaniment import fixture
from accompaniment_arrange import arrange_guitar, TUNING
# 常用右手伴奏型：修改，保留原导入；增加短和弦性质音合拨的独立反例。
# from guitar_right_hand_patterns import library, eligible_measures, apply_common_patterns, measure_notes, validate_patterns, shape_for
from guitar_right_hand_patterns import library, eligible_measures, apply_common_patterns, measure_notes, validate_patterns, shape_for, complete_quality


# 常用右手伴奏型：新增两小节已知演唱夹具，无器乐主线，实际声学攻击仍留作来源。
def known():
    s, v = fixture()
    s['timing'] = {'meter': [4,4]}; s['sections'][0]['kind'] = 'vocal'
    s['instrumental_melody'] = []
    for texture in s['measure_textures']: texture['section'] = 'vocal'
    g = arrange_guitar(s, v, 0)
    return s, v, g


class RightHandPatternTests(unittest.TestCase):
    # 常用右手伴奏型：新增源教学精确扫弦相位与复合拍重音真值。
    def test_old_faithful_has_no_unattributed_final_upstroke(self):
        p = next(p for p in library()['patterns'] if p['id'] == 'strum_4_4_old_faithful')
        self.assertEqual(p['slots'], ['D','-','D','U','-','U','D','-'])

    def test_three_four_and_six_eight_have_different_accents(self):
        ps = {p['id']: p for p in library()['patterns']}
        self.assertEqual(ps['arp_3_4']['accent_slots'], [0,2,4])
        self.assertEqual(ps['arp_6_8']['accent_slots'], [0,3])

    def test_c_roll_known_pitches_and_strings(self):
        s, v, g = known()
        # 常用右手伴奏型：新增C真实发声60/67/60/67/64等真值，使用现有低音实际八度48。
        h = s['harmony'][0]; h.update(root_pc=0, bass_pc=0, quality='', pitch_classes=[0,4,7], name='C')
        ns, _, _, _ = measure_notes(s, g, 1, {'pattern_id':'arp_4_4_roll','phase_tick':0}, 1)
        self.assertEqual([n['string'] for n in ns], [5,3,2,3,1,3,2,3])
        self.assertEqual([n['pitch_midi'] for n in ns], [48,55,60,55,64,55,60,55])
        self.assertTrue(all(n['onset_origin'] == 'arranged_common_pattern' for n in ns))

    def test_slash_bass_is_played_instead_of_root(self):
        s, _, _ = known(); h = s['harmony'][0]
        h.update(root_pc=0, bass_pc=4, quality='', pitch_classes=[0,4,7], name='C/E')
        shape, mapping = shape_for(h, 0); string = mapping['B']
        self.assertEqual((TUNING[string] + shape['frets'][str(string)]) % 12, 4)

    def test_instrumental_sections_stay_unchanged(self):
        s, v = fixture(); s['timing'] = {'meter':[4,4]}; g = arrange_guitar(s,v,1)
        before = deepcopy(g['notes']); apply_common_patterns(s,v,g)
        self.assertEqual(g['notes'], sorted(before, key=lambda n:(n['start_tick'],n['string'])))
        self.assertEqual(g['right_hand_patterns']['changed_measures'], [])

    def test_feature_fill_in_vocal_protects_whole_measure(self):
        s, _, g = known(); g['notes'][0]['role'] = 'countermelody'
        good, skipped = eligible_measures(s,g)
        self.assertNotIn(1,good)
        self.assertIn({'measure':1,'reason':'protected_feature_melody'},skipped)

    def test_confirmed_simultaneous_attacks_are_preserved(self):
        s, _, g = known(); g['attack_events'][0]['arrangement_reason'] = 'retained_cross_supported_simultaneous_chord'
        self.assertNotIn(1,eligible_measures(s,g)[0])

    def test_mixed_boundary_is_protected(self):
        s, _, g = known(); s['sections'][0]['start_tick'] = 120
        self.assertNotIn(1,eligible_measures(s,g)[0])

    def test_late_entry_is_not_filled_with_early_notes(self):
        s, _, g = known(); g['notes'] = [n for n in g['notes'] if n['start_tick'] >= 720]
        ns, _, row, _ = measure_notes(s,g,1,{'pattern_id':'arp_4_4_sparse','phase_tick':0},1)
        self.assertEqual(min(n['start_tick'] for n in ns),720)
        self.assertEqual(row['leading_rest_end_tick'],720)

    def test_shared_analysis_and_vocal_are_read_only(self):
        s, v, g = known(); a, b = deepcopy(s), deepcopy(v)
        apply_common_patterns(s,v,g)
        self.assertEqual(s,a); self.assertEqual(v,b)
        self.assertTrue(validate_patterns(s,g)['valid'])

    def test_second_application_does_not_rearrange_again(self):
        s,v,g = known(); apply_common_patterns(s,v,g); before=deepcopy(g)
        apply_common_patterns(s,v,g); self.assertEqual(g,before)

    def test_fret_tampering_is_detected(self):
        s,v,g = known(); apply_common_patterns(s,v,g)
        next(n for n in g['notes'] if n.get('right_hand_pattern_id'))['fret'] += 1
        self.assertFalse(validate_patterns(s,g)['valid'])

    def test_wrong_slash_bass_tampering_is_detected(self):
        s,v,g = known(); apply_common_patterns(s,v,g)
        n=next(n for n in g['notes'] if n.get('right_hand_pattern_id') and n['role']=='bass')
        n['pitch_midi'] += 2
        self.assertTrue(any('wrong_slash_bass' in e for e in validate_patterns(s,g)['errors']))

    # 常用右手伴奏型：新增实际C三度缺失时的合拨真值，不能将合拨冒称扫弦。
    def test_quality_pinch_adds_third_without_strum(self):
        s,_,g=known();ns,_,_,_=measure_notes(s,g,1,{'pattern_id':'arp_4_4_roll','phase_tick':0},1)
        base=ns[0];notes=[]
        for i in range(4):
            n=deepcopy(base);n.update(id='test_bass_'+str(i),start_tick=i*240,end_tick=(i+1)*240)
            notes.append(n)
        events=[{'start_tick':i*240,'kind':'arpeggio'} for i in range(4)]
        complete_quality(s,notes,events,[],0,10)
        high=[n for n in notes if n['role']=='harmony']
        self.assertEqual(len(high),1);self.assertEqual(high[0]['pitch_midi']%12,4)
        self.assertEqual(high[0]['start_tick'],0)
        self.assertTrue(all(e['kind']=='arpeggio' for e in events))

    def test_unplayed_quality_tone_is_detected(self):
        s,v,g=known();apply_common_patterns(s,v,g)
        for n in g['notes']:
            if n.get('right_hand_pattern_id') and n['chord_id']=='h0' and n['pitch_midi']%12==4:
                n['pitch_midi']-=4
        self.assertIn('pattern_missing_chord_quality:h0',validate_patterns(s,g)['errors'])

    # 常用右手伴奏型：新增空白起音小节仍保留前小节延音，独立指定E持续至2160tick。
    def test_held_only_following_measure_does_not_cut_bridge(self):
        s,v,g=known();g['notes']=[n for n in g['notes'] if n['start_tick']<1920]
        old=g['notes'][-1];old.update(string=1,fret=0,pitch_midi=64,end_tick=2160)
        s['harmony']=s['harmony'][:1];s['harmony'][0]['end_tick']=3840
        s['measure_textures'][1]['attacks']=[]
        apply_common_patterns(s,v,g)
        self.assertTrue(any(n.get('held_bridge_source_note_id')==old['id'] and n['end_tick']==2160 for n in g['notes']))
        self.assertNotIn(2,g['right_hand_patterns']['changed_measures'])


if __name__ == '__main__':
    unittest.main()
