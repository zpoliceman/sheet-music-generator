"""器乐声部恢复与规整节奏：独立多声部、短音、换把、保护及实际导出反例。"""
# 器乐声部恢复与规整节奏：新增自拟旋律/低音/和声夹具，避免用样曲人工音符作为程序答案。
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from test_accompaniment import fixture
from accompaniment_arrange import arrange_guitar, arrange_piano, TUNING, validate_playability
from accompaniment_analysis import SongClock
from accompaniment_export import build_musicxml, parse_musicxml_notes
from instrumental_regular_rhythm import regularize_instrumentals, ordered_grid, coalesce_short_repetitions
from guitar_rhythm_beams import arrangement_rhythm_events
from guitar_structure_validation import validate_structured_rhythm


# 器乐声部恢复与规整节奏：新增明确的三声部音乐，末段为独立保护的普通演唱伴奏。
def music_fixture(shift=0):
    shared, vocal = fixture()
    # 器乐声部恢复与规整节奏：修改，旧缩略段落夹具保留；实际导出需要完整段落标签。
    # shared['sections'] = [{'kind': 'intro', 'start_tick': 0, 'end_tick': 1920},
    #                       {'kind': 'vocal', 'start_tick': 1920, 'end_tick': 3840}]
    shared['sections'] = [{'kind': 'intro', 'label': '前奏', 'start_tick': 0, 'end_tick': 1920},
                          {'kind': 'vocal', 'label': '演唱', 'start_tick': 1920, 'end_tick': 3840}]
    arrangements = {'guitar': arrange_guitar(shared, vocal, 0), 'piano': arrange_piano(shared, vocal)}
    rows = [('m0', 90, 240, 72, 'instrumental_melody', 1, 8, 'right'),
            ('b0', 90, 240, 48, 'bass', 6, 8, 'left'),
            ('h0', 90, 240, 64, 'harmony', 3, 9, 'right'),
            ('m1', 330, 180, 74, 'instrumental_melody', 1, 10, 'right'),
            ('m2', 570, 90, 76, 'instrumental_melody', 1, 12, 'right'),
            ('b1', 570, 240, 50, 'bass', 6, 10, 'left'),
            ('m3', 810, 120, 74, 'instrumental_melody', 1, 10, 'right'),
            ('normal', 1920, 240, 48, 'harmony', 5, 3, 'left')]
    for instrument, a in arrangements.items():
        notes = []
        for identity, tick, duration, pitch, role, string, fret, hand in rows:
            n = {'id': identity, 'start_tick': tick, 'end_tick': tick+duration, 'pitch_midi': pitch+shift,
                 'role': role, 'velocity': 88, 'chord_id': 'h0' if tick < 1920 else 'h1', 'source': 'known_music',
                 'source_melody_id': identity if role == 'instrumental_melody' else None}
            if instrument == 'guitar':
                n.update(string=string, fret=fret+shift, finger=1, hand_position=max(1, fret+shift-3))
            else:
                n.update(hand=hand, finger=2)
                if role == 'bass':
                    n['pitch_midi'] -= 12
            notes.append(n)
        a['notes'] = notes
        a['configuration']['structure_policy'] = {'protected': True}
        a['attack_events'] = [{'start_tick': 90, 'kind': 'arpeggio', 'source': 'known_music'},
                              {'start_tick': 1920, 'kind': 'arpeggio', 'chord_id': 'h1',
                               'right_hand_duration_ticks': 240, 'right_hand_duration_source': 'regular_pattern_slot'}]
        a['pedal'] = []
        if instrument == 'guitar':
            # 器乐声部恢复与规整节奏：新增空普通模板计划；本夹具只验证保护音而不编造伴奏模板。
            a['right_hand_patterns'] = {'measures': []}
            a['regular_rhythm'] = {'version': 2, 'changed_measures': [], 'preserved_notes': deepcopy(notes),
                                   'preserved_note_ids': [n['id'] for n in notes], 'source_notes': deepcopy(notes)}
    return shared, vocal, arrangements


# 器乐声部恢复与规整节奏：新增实际音乐语义检查，声部和音序必须保留，不以模式标签代替。
class InstrumentalTextureTests(unittest.TestCase):
    def test_preserves_melody_bass_and_harmony(self):
        s, v, a = music_fixture()
        _, result, _ = regularize_instrumentals(s, v, a)
        for instrument in a:
            before = {n['id']: (n['pitch_midi'], n['role']) for n in a[instrument]['notes']}
            after = {n['id']: (n['pitch_midi'], n['role']) for n in result[instrument]['notes']}
            self.assertEqual(before, after)
            self.assertEqual(Counter(n['role'] for n in result[instrument]['notes'])['bass'], 2)

    def test_keeps_bass_under_upper_melody(self):
        s, v, a = music_fixture()
        _, result, _ = regularize_instrumentals(s, v, a)
        for arr in result.values():
            melody = [n for n in arr['notes'] if n['id'] == 'm0'][0]
            active = [n for n in arr['notes'] if n['start_tick'] <= melody['start_tick'] < n['end_tick']]
            self.assertIn('bass', [n['role'] for n in active])
            self.assertIn('harmony', [n['role'] for n in active])

    def test_dense_different_pitch_melody_is_not_deleted(self):
        s, v, a = music_fixture()
        for arr in a.values():
            for n in arr['notes']:
                if n['role'] == 'instrumental_melody':
                    n['start_tick'] = 300+int(n['id'][-1])*60
                    n['end_tick'] = n['start_tick']+60
        _, result, _ = regularize_instrumentals(s, v, a)
        for instrument, arr in result.items():
            expected = [n['pitch_midi'] for n in a[instrument]['notes'] if n['role'] == 'instrumental_melody']
            melody = sorted((n for n in arr['notes'] if n['role'] == 'instrumental_melody'), key=lambda n: n['start_tick'])
            self.assertEqual(expected, [n['pitch_midi'] for n in melody])
            self.assertTrue(all(y['start_tick']-x['start_tick'] >= 120 for x, y in zip(melody, melody[1:])))

    def test_short_same_pitch_repetitions_can_merge(self):
        notes = [{'id': 'a', 'role': 'instrumental_melody', 'pitch_midi': 72, 'start_tick': 0, 'end_tick': 60},
                 {'id': 'b', 'role': 'instrumental_melody', 'pitch_midi': 72, 'start_tick': 60, 'end_tick': 120}]
        selected, audit = coalesce_short_repetitions(notes, 120, 'guitar')
        self.assertEqual([(n['pitch_midi'], n['start_tick'], n['end_tick']) for n in selected], [(72, 0, 120)])
        self.assertEqual(audit[0]['note_id'], 'b')

    def test_regular_sixteenth_repetitions_stay_rearticulated(self):
        notes = [{'id': str(i), 'role': 'instrumental_melody', 'pitch_midi': 72,
                  'start_tick': i*120, 'end_tick': (i+1)*120} for i in range(4)]
        selected, audit = coalesce_short_repetitions(notes, 120, 'piano')
        self.assertEqual(len(selected), 4); self.assertFalse(audit)

    def test_short_bass_repetitions_are_not_merged(self):
        notes = [{'id': str(i), 'role': 'bass', 'pitch_midi': 36, 'hand': 'left',
                  'start_tick': i*60, 'end_tick': (i+1)*60} for i in range(3)]
        selected, audit = coalesce_short_repetitions(notes, 120, 'piano')
        self.assertEqual(len(selected), 3); self.assertFalse(audit)

    def test_dense_bass_sequence_does_not_reverse(self):
        s, v, a = music_fixture()
        for arr in a.values():
            for identity, tick in [('b0', 180), ('b1', 210)]:
                n = next(n for n in arr['notes'] if n['id'] == identity)
                n.update(start_tick=tick, end_tick=tick+60)
        _, result, _ = regularize_instrumentals(s, v, a)
        for arr in result.values():
            bass = sorted((n for n in arr['notes'] if n['role'] == 'bass'), key=lambda n: n['start_tick'])
            self.assertEqual([n['id'] for n in bass], ['b0', 'b1'])

    def test_title_does_not_control_arrangement(self):
        s, v, a = music_fixture(); renamed_s, renamed_v = deepcopy(s), deepcopy(v)
        renamed_s['title'] = '完全不同的歌'; renamed_v['title'] = '不相关标题'
        self.assertEqual(regularize_instrumentals(s, v, a)[1], regularize_instrumentals(renamed_s, renamed_v, a)[1])

    def test_transposition_preserves_rhythm_and_voices(self):
        s, v, a = music_fixture(); t, w, b = music_fixture(2)
        first = regularize_instrumentals(s, v, a)[1]; second = regularize_instrumentals(t, w, b)[1]
        for instrument in first:
            fields = lambda arr: sorted((n['id'], n['start_tick'], n['end_tick'], n['role']) for n in arr['notes'])
            self.assertEqual(fields(first[instrument]), fields(second[instrument]))
            self.assertEqual(sorted(n['pitch_midi']+2 for n in first[instrument]['notes']),
                             sorted(n['pitch_midi'] for n in second[instrument]['notes']))

    def test_impossible_density_rejects_instead_of_erasing_melody(self):
        with self.assertRaisesRegex(ValueError, '拒绝自动删掉异音'):
            ordered_grid(list(range(0, 600, 30)), {'start_tick': 0, 'end_tick': 960}, 120, 480)


# 器乐声部恢复与规整节奏：新增正常演唱保护、真实持续音/夹位/节奏事件及MusicXML独立回读。
class InstrumentalTimingAndProtectionTests(unittest.TestCase):
    def test_inputs_remain_readonly(self):
        s, v, a = music_fixture(); before = deepcopy((s, v, a))
        regularize_instrumentals(s, v, a)
        self.assertEqual((s, v, a), before)

    def test_normal_music_and_attack_event_stay_exact(self):
        s, v, a = music_fixture()
        _, result, _ = regularize_instrumentals(s, v, a)
        for instrument in a:
            self.assertEqual(next(n for n in a[instrument]['notes'] if n['id'] == 'normal'),
                             next(n for n in result[instrument]['notes'] if n['id'] == 'normal'))
            self.assertEqual(a[instrument]['attack_events'][-1], result[instrument]['attack_events'][-1])

    def test_real_musicxml_contains_no_32nd_or_dotted_sixteenth(self):
        s, v, a = music_fixture()
        _, result, _ = regularize_instrumentals(s, v, a)
        for arr in result.values():
            xml, _ = build_musicxml(s, v, arr)
            for n in xml.iter('note'):
                self.assertNotIn(n.findtext('type'), ['32nd', '64th', '128th', '256th'])
                self.assertFalse(n.findtext('type') == '16th' and n.find('dot') is not None)
            notes, check = parse_musicxml_notes(xml)
            self.assertTrue(check['valid'])
            self.assertEqual({n['id']: (n['start_tick'], n['end_tick'], n['pitch_midi']) for n in arr['notes']},
                             {identity: (n['start_tick'], n['end_tick'], n['pitch_midi']) for identity, n in notes.items()})

    def test_stale_instrumental_events_are_replaced(self):
        s, v, a = music_fixture()
        _, result, _ = regularize_instrumentals(s, v, a)
        for arr in result.values():
            events = [e for e in arr['attack_events'] if e['start_tick'] < 1920]
            starts = {n['start_tick'] for n in arr['notes'] if n['start_tick'] < 1920}
            self.assertEqual({e['start_tick'] for e in events}, starts)
            self.assertTrue(all(e['start_tick'] % 120 == 0 for e in events))

    def test_real_tab_events_use_regular_values_without_dots(self):
        s, v, a = music_fixture()
        _, result, _ = regularize_instrumentals(s, v, a)
        events = arrangement_rhythm_events(result['guitar'], [4, 4], 1920)
        self.assertTrue(all(e['dots'] == 0 and e['flags'] <= 2 for e in events))

    def test_accepted_vocal_clock_is_exactly_unchanged(self):
        s, v, a = music_fixture(); before = deepcopy(v)
        new_s, _, _ = regularize_instrumentals(s, v, a)
        self.assertEqual(v, before); self.assertEqual(s, new_s)
        self.assertEqual(SongClock(v).seconds(1920), SongClock(before).seconds(1920))

    def test_protection_ledger_keeps_source_and_new_intervals(self):
        s, v, a = music_fixture(); old_source = deepcopy(a['guitar']['regular_rhythm']['source_notes'])
        _, result, _ = regularize_instrumentals(s, v, a)
        ledger = result['guitar']['regular_rhythm']
        self.assertEqual(ledger['source_notes'], old_source)
        self.assertTrue(ledger['retimed_instrumental_source_notes'])
        self.assertTrue(validate_structured_rhythm(s, result['guitar'])['valid'])
        next(n for n in result['guitar']['notes'] if n['id'] == 'normal')['pitch_midi'] += 1
        self.assertFalse(validate_structured_rhythm(s, result['guitar'])['valid'])

    def test_mixed_measure_boundary_does_not_replace_vocal_notes(self):
        s, v, a = music_fixture(); s['sections'][0]['end_tick'] = 1800; s['sections'][1]['start_tick'] = 1800
        for arr in a.values():
            next(n for n in arr['notes'] if n['id'] == 'normal').update(start_tick=1800, end_tick=1920)
            arr['attack_events'][-1]['start_tick'] = 1800
        _, result, _ = regularize_instrumentals(s, v, a)
        for instrument in a:
            self.assertEqual(next(n for n in a[instrument]['notes'] if n['id'] == 'normal'),
                             next(n for n in result[instrument]['notes'] if n['id'] == 'normal'))

    def test_preparation_gap_keeps_both_melody_attacks(self):
        s, v, a = music_fixture()
        guitar = a['guitar']
        guitar['notes'] = [dict(guitar['notes'][0], id='high', start_tick=0, end_tick=120, pitch_midi=74, string=1, fret=10),
                           dict(guitar['notes'][0], id='low', start_tick=120, end_tick=360, pitch_midi=67, string=1, fret=3),
                           next(n for n in guitar['notes'] if n['id'] == 'normal')]
        _, result, _ = regularize_instrumentals(s, v, {'guitar': guitar})
        melody = [n for n in result['guitar']['notes'] if n['role'] == 'instrumental_melody']
        self.assertEqual([n['pitch_midi'] for n in melody], [74, 67])
        self.assertTrue(all(n['end_tick']-n['start_tick'] >= 120 for n in melody))
        self.assertTrue(validate_playability(result['guitar'], SongClock(v))['valid'])

    def test_change_capo_recomputes_actual_fret(self):
        s, v, a = music_fixture(); guitar = a['guitar']
        guitar['configuration']['capo_segments'] = [{'start_tick': 0, 'capo_fret': 0}, {'start_tick': 240, 'capo_fret': 1}]
        # 器乐声部恢复与规整节奏：新增源按法按原夹位标注；整理前后都保持真实音高。
        for n in guitar['notes']:
            if n['start_tick'] >= 240:
                n['fret'] -= 1
        _, result, _ = regularize_instrumentals(s, v, {'guitar': guitar})
        for n in result['guitar']['notes']:
            capo = 0 if n['start_tick'] < 240 else 1
            self.assertEqual(TUNING[n['string']]+n['fret']+capo, n['pitch_midi'])

    def test_other_meter_uses_same_minimum_sixteenth(self):
        for meter, bar in [([3, 4], 1440), ([6, 8], 1440)]:
            s, v, a = music_fixture(); v['timing']['meter'] = meter
            v['statistics'].update(bar_ticks=bar, total_ticks=4320, measure_count=3)
            s['statistics'] = deepcopy(v['statistics'])
            _, result, _ = regularize_instrumentals(s, v, a)
            for arr in result.values():
                self.assertTrue(validate_playability(arr, SongClock(v))['valid'])
                self.assertTrue(all(n['start_tick'] % 120 == n['end_tick'] % 120 == 0 for n in arr['notes']))


if __name__ == '__main__':
    unittest.main()
