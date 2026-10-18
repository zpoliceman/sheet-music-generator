"""规整分解节奏与延音显示：实际拍点、延响、指型用途及可见几何反例。"""
# 规整分解节奏与延音显示：新增已知两小节夹具验证，不把歌曲自动候选当作原曲音乐真值。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from test_guitar_right_hand_patterns import known
from test_chord_diagrams import known_score
from guitar_regular_rhythm import POLICY, apply_regular_patterns, validate_regular_rhythm
from guitar_right_hand_patterns import measure_notes, complete_quality
from guitar_rhythm_beams import arrangement_rhythm_events, rhythm_events, draw_rhythm
from guitar_chord_diagrams import set_tab_display, visible_diagrams
from guitar_sustain_display import validate_continuations
from accompaniment_export import guitar_row

NS = '{http://www.w3.org/2000/svg}'


# 规整分解节奏与延音显示：新增普通伴奏真实时间检查和错误拍格反例。
class RegularRhythmTests(unittest.TestCase):
    def test_late_phase_moves_to_known_beat_grid(self):
        s, v, g = known()
        for n in g['notes']: n['start_tick'] += 120; n['end_tick'] += 120
        for e in g['attack_events']: e['start_tick'] += 120
        apply_regular_patterns(s, v, g)
        ticks = sorted({n['start_tick'] for n in g['notes'] if n['start_tick'] < 1920})
        self.assertEqual(ticks, list(range(0, 1920, 240)))
        self.assertTrue(validate_regular_rhythm(s, g)['valid'])

    def test_fractional_entry_starts_at_complete_beat(self):
        s, _, g = known(); g['configuration']['regular_rhythm_policy'] = POLICY
        g['notes'] = [n for n in g['notes'] if n['start_tick'] >= 840]
        # 规整分解节奏与延音显示：新增独立840tick进入时间，普通拍格从第二拍480tick开始。
        first = next(n for n in g['notes'] if n['start_tick'] < 1920)
        first['start_tick'] = 840; first['end_tick'] = 1080
        ns, _, row, _ = measure_notes(s, g, 1, {'pattern_id':'arp_4_4_roll','phase_tick':0}, 1)
        self.assertEqual(min(n['start_tick'] for n in ns), 480)
        self.assertEqual(row['source_entry_tick'], 840)

    def test_whole_beat_leading_rest_remains(self):
        s, _, g = known(); g['configuration']['regular_rhythm_policy'] = POLICY
        g['notes'] = [n for n in g['notes'] if n['start_tick'] >= 960]
        ns, _, _, _ = measure_notes(s, g, 1, {'pattern_id':'arp_4_4_roll','phase_tick':0}, 1)
        self.assertEqual(min(n['start_tick'] for n in ns), 960)

    def test_vocal_and_shared_data_are_read_only(self):
        s, v, g = known(); a, b = deepcopy(s), deepcopy(v)
        apply_regular_patterns(s, v, g)
        self.assertEqual((s, v), (a, b))

    def test_second_application_preserves_manual_edit(self):
        s, v, g = known(); apply_regular_patterns(s, v, g)
        g['notes'][0]['velocity'] = 59; before = deepcopy(g)
        apply_regular_patterns(s, v, g); self.assertEqual(g, before)

    def test_feature_notes_remain_field_for_field(self):
        s, v, g = known()
        for n in g['notes']:
            if n['start_tick'] >= 1920: n['role'] = 'instrumental_melody'
        protected = deepcopy([n for n in g['notes'] if n['start_tick'] >= 1920])
        apply_regular_patterns(s, v, g)
        # 规整分解节奏与延音显示：修改，旧列表顺序比较保留；逐编号比较完整字段，允许同刻多弦排序。
        # self.assertEqual([n for n in g['notes'] if n['start_tick'] >= 1920], protected)
        self.assertEqual({n['id']:n for n in g['notes'] if n['start_tick'] >= 1920}, {n['id']:n for n in protected})
        self.assertEqual(len(g['regular_rhythm']['preserved_notes']), len(protected))

    def test_off_grid_attack_is_rejected(self):
        s, v, g = known(); apply_regular_patterns(s, v, g)
        g['notes'][0]['start_tick'] += 120
        self.assertFalse(validate_regular_rhythm(s, g)['valid'])

    def test_dotted_slot_override_is_rejected(self):
        s, v, g = known(); apply_regular_patterns(s, v, g)
        g['attack_events'][0]['right_hand_duration_ticks'] = 360
        self.assertFalse(validate_regular_rhythm(s, g)['valid'])

    def test_missing_eighth_partner_is_rejected(self):
        s, v, g = known(); apply_regular_patterns(s, v, g)
        g['notes'] = [n for n in g['notes'] if n['start_tick'] != 240]
        self.assertIn('unpaired_eighth_attack:0', validate_regular_rhythm(s, g)['errors'])

    def test_quality_completion_uses_unique_new_namespace(self):
        s, _, _ = known()
        notes = [{'id':f'guitar_regular_note_{i}', 'chord_id':'h0','pitch_midi':48,
                  'string':5,'fret':3,'role':'bass','start_tick':i*480,'end_tick':i*480+240,
                  'right_hand_pattern_id':'arp_4_4_roll','right_hand_token':'B',
                  'pattern_baseline_frets':{'5':3,'4':2,'3':0,'2':1,'1':0},
                  'pattern_string_map':{'B':5,'3':3,'2':2,'1':1}}
                 for i in range(4)]
        complete_quality(s, notes, [], [], 0, 509)
        self.assertEqual(notes[-1]['id'], 'guitar_regular_quality_00509')
        self.assertEqual(notes[-1]['pitch_midi'] % 12, 4)

    # 规整分解节奏与延音显示：新增其它拍号真实时间夹具，不把库中的参考例误当4/4默认重编。
    def test_other_meters_do_not_receive_four_four_regular_grid(self):
        for meter in ([3,4],[6,8]):
            with self.subTest(meter=meter):
                s, v, g = known(); s['timing']['meter'] = meter; v['timing']['meter'] = meter
                s['statistics']['bar_ticks'] = 1440; s['statistics']['total_ticks'] = 2880
                for rows in (g['notes'],g['attack_events'],s['harmony'],s['sections'],s['measure_textures']):
                    for row in rows:
                        for key in ('start_tick','end_tick'):
                            if key in row: row[key] = row[key]*3//4
                before = {n['id']:deepcopy(n) for n in g['notes']}
                apply_regular_patterns(s, v, g)
                self.assertEqual({n['id']:n for n in g['notes']},before)
                self.assertNotIn('regular_rhythm',g)
                self.assertNotIn('regular_rhythm_policy',g['configuration'])


# 规整分解节奏与延音显示：新增低音响720tick仍采用半拍拨弦记法，独奏附点继续按原时值显示。
class AttackAndSustainTests(unittest.TestCase):
    def test_long_bass_and_next_eighth_share_beam(self):
        notes = [{'id':'bass','start_tick':0,'end_tick':720},
                 {'id':'upper','start_tick':240,'end_tick':480}]
        arr = {'notes':notes,'attack_events':[{'start_tick':t,'right_hand_duration_ticks':240,
                'right_hand_duration_source':'regular_pattern_slot'} for t in (0,240)]}
        events = arrangement_rhythm_events(arr, [4,4], 1920)
        self.assertEqual([(e['duration'],e['dots'],e['flags']) for e in events], [(240,0,1),(240,0,1)])
        self.assertEqual(events[0]['sounding_duration_ticks'], 720)
        root = ET.Element(NS+'svg'); root.extend(draw_rhythm(events, lambda t:40+t/10))
        lines = [n for n in root.iter(NS+'line') if n.get('class')=='tab-rhythm-beam']
        self.assertEqual([(float(n.get('x1')),float(n.get('x2'))) for n in lines], [(40,64)])

    def test_unmodified_solo_keeps_dotted_eighth(self):
        events = rhythm_events([{'id':'solo','start_tick':0,'end_tick':360}], [4,4], 1920)
        self.assertEqual((events[0]['type'], events[0]['dots']), ('eighth',1))


# 规整分解节奏与延音显示：新增空弦延响无需整张图、按弦延音需图及图随真实起音的独立真值。
class DiagramPurposeTests(unittest.TestCase):
    def situation(self, fret):
        s, _, g = known_score(); set_tab_display(g)
        g['fingering_diagrams'][0]['end_tick'] = 480
        g['fingering_diagrams'][1]['start_tick'] = 480
        g['notes'] = [{'id':'previous','start_tick':-240,'end_tick':480,'string':2 if fret else 3,
                       'fret':fret}, {'id':'new','start_tick':480,'end_tick':720,'string':1,'fret':2}]
        return visible_diagrams(s, g, 1, 1)

    def test_open_only_continuation_has_no_unused_chord_diagram(self):
        self.assertEqual([(d['id'],d['draw_tick']) for d in self.situation(0)], [('d',480)])

    def test_fretted_continuation_still_identifies_held_grip(self):
        self.assertEqual([(d['id'],d['draw_tick']) for d in self.situation(1)], [('c',0),('d',480)])


# 规整分解节奏与延音显示：新增从可见括号品数与实际续音线核查，缺失/偏移/冒充起音均拒绝。
class ContinuationGeometryTests(unittest.TestCase):
    def situation(self):
        s, v, g = known_score()
        g['notes'].append({'id':'open_held','start_tick':1680,'end_tick':2400,'string':3,'fret':0,
                           'pitch_midi':55,'role':'harmony','finger':0,'hand_position':1})
        root = ET.fromstring(guitar_row(s, v, g, 1, 2))
        return root, g

    def check(self, mutate=None):
        root, g = self.situation()
        group = next(n for n in root.iter(NS+'g') if n.get('class')=='tab-continuation')
        if mutate: mutate(root, group)
        return validate_continuations([{'guitar':ET.tostring(root,encoding='unicode')}], g)

    def test_open_held_is_visible_but_has_no_new_attack(self):
        root, _ = self.situation()
        group = next(n for n in root.iter(NS+'g') if n.get('class')=='tab-continuation')
        self.assertEqual(group.find(NS+'text').text, '(0)')
        self.assertIsNone(group.get('data-string'))
        self.assertEqual(self.check()['visible_continuations'], 1)
        self.assertTrue(self.check()['valid'])

    def test_shifted_continuation_is_rejected(self):
        def mutate(_, group):
            text = group.find(NS+'text'); text.set('x', str(float(text.get('x'))+7))
        self.assertFalse(self.check(mutate)['valid'])

    def test_shortened_hold_line_is_rejected(self):
        def mutate(_, group):
            line = group.find(NS+'line'); line.set('x2', str(float(line.get('x2'))-17))
        self.assertFalse(self.check(mutate)['valid'])

    def test_missing_continuation_is_rejected(self):
        def mutate(root, group):
            next(p for p in root.iter() if group in list(p)).remove(group)
        self.assertFalse(self.check(mutate)['valid'])

    def test_continuation_cannot_claim_new_attack(self):
        self.assertFalse(self.check(lambda _,g:g.set('data-string','3'))['valid'])


if __name__ == '__main__': unittest.main()
