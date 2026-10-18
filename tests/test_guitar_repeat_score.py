"""重复乐句折叠与多遍挂词：独立重复音乐、真实可见字形及故意篡改的反例。"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
from test_score_export import project_from, note, char
from score_export import key_definition
from guitar_repeat_plan import build_repeat_plan, validate_repeat_plan, expand_route
from guitar_repeat_score import render_lines, validate_repeat_rows
NS = '{http://www.w3.org/2000/svg}'


# 重复乐句折叠与多遍挂词：新增自拟C主题／Am与Em过渡／C再现，歌词各遍不同，无样曲答案。
def music():
    source = []; lyrics = []
    for measure in range(6):
        for beat, pitch in enumerate((60, 62, 64, 67)):
            index = measure * 4 + beat; start = measure * 2 + beat / 2
            source.append(note(str(index), start, start + .5, pitch))
            lyrics.append(char(index, '春风细雨再相遇啊甲乙丙丁天地玄黄月光照我回家路上'[index], start, start + .5))
    v = project_from(source, lyrics, seconds=12)
    v['audio_analysis'] = {'tempo': {'bpm': 120}}; v['overrides'] = {'tempo': 120}
    v['timing']['knots'] = [{'seconds': 0., 'quarter': 0.}, {'seconds': .5, 'quarter': 1.}]
    s = {'statistics': deepcopy(v['statistics']), 'harmony': [],
         'sections': [{'kind': 'vocal', 'start_tick': 0, 'end_tick': 11520}],
         'measure_textures': [{'section': 'vocal', 'kind': 'arpeggio'} for _ in range(6)],
         'phrase_harmony_plan': {'phrases': [
             {'id': 'a', 'family_id': 'theme', 'action': 'shared_progression', 'start_tick': 0, 'end_tick': 3840},
             {'id': 'b', 'family_id': 'theme', 'action': 'shared_progression', 'start_tick': 7680, 'end_tick': 11520}]}}
    g = {'instrument': 'guitar', 'configuration': {'capo_fret': 0, 'rows_measures': 4},
         'notes': [], 'attack_events': [], 'fingering_diagrams': [], 'notation_regions': []}
    for measure in range(6):
        root, quality = (9, 'm') if measure == 2 else (4, 'm') if measure == 3 else (0, '')
        start = measure * 1920; chord = 'h' + str(measure)
        s['harmony'].append({'id': chord, 'start_tick': start, 'end_tick': start + 1920,
                             'root_pc': root, 'bass_pc': root, 'quality': quality,
                             'name': 'Am' if measure == 2 else 'Em' if measure == 3 else 'C', 'key': v['notation']['key']})
        tones = [(48, 5, 3), (55, 3, 0), (60, 2, 1), (64, 1, 0)]
        if measure == 2: tones = [(45, 5, 0), (57, 3, 2), (60, 2, 1), (64, 1, 0)]
        if measure == 3: tones = [(40, 6, 0), (55, 3, 0), (59, 2, 0), (64, 1, 0)]
        for beat, (pitch, string, fret) in enumerate(tones):
            tick = start + beat * 480; identity = f'n{measure}_{beat}'
            g['notes'].append({'id': identity, 'start_tick': tick, 'end_tick': tick + 240,
                               'pitch_midi': pitch, 'string': string, 'fret': fret, 'finger': int(fret > 0),
                               'hand_position': 1, 'velocity': 75, 'role': 'bass' if beat == 0 else 'harmony',
                               'right_hand_duration_ticks': 480, 'chord_id': chord})
            g['attack_events'].append({'start_tick': tick, 'kind': 'arpeggio', 'chord_id': chord,
                                       'stroke': None, 'note_ids': [identity], 'right_hand_duration_ticks': 480})
    return s, v, g


# 重复乐句折叠与多遍挂词：新增从实际输出修改图元，避免只检查规划器自报结果。
def rendered():
    s, v, g = music(); plan = build_repeat_plan(s, v, g)
    with tempfile.TemporaryDirectory() as folder:
        rows = render_lines(plan, s, v, g, Path(folder))
    return s, v, g, plan, rows


# 吉他长段反复与流畅阅读：修改旧碎片折叠测试预期，原测试逐行注释保留。
# class RepeatPlanTests(unittest.TestCase):
#     # 重复乐句折叠与多遍挂词：新增自然乐句共用两小节、各遍挂词、反复展开和音乐保护正例。
#     def test_repeated_theme_folds_two_bars_and_keeps_other_music(self):
#         s, v, g = music(); p = build_repeat_plan(s, v, g)
#         self.assertEqual(p['saved_bars'], 2)
#         b = next(b for b in p['blocks'] if len(b['occurrences']) > 1)
#         self.assertEqual([(o['first'], o['last']) for o in b['occurrences']], [(1, 2), (5, 6)])
#         self.assertTrue(validate_repeat_plan(p, s, v, g)['valid'])
# 
#     def test_lyrics_and_small_vocal_variants_keep_separate_complete_layers(self):
#         s, v, g = music(); next(e for e in v['events'] if e['measure'] == 5)['pitch_midi'] = 65
#         self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 2)
# 
#     def test_performed_harmony_difference_is_not_hidden(self):
#         s, v, g = music(); s['harmony'][4]['quality'] = 'maj7'
#         p = build_repeat_plan(s, v, g)
#         self.assertEqual(p['saved_bars'], 1)
# 
#     def test_exact_pitch_on_other_string_is_a_real_tab_variant(self):
#         s, v, g = music(); g['notes'][16].update(string=6, fret=8)
#         self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 1)
# 
#     def test_right_hand_attack_shift_is_preserved(self):
#         s, v, g = music(); g['notes'][16]['start_tick'] += 120; g['attack_events'][16]['start_tick'] += 120
#         self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 1)
# 
#     def test_held_release_difference_is_preserved(self):
#         s, v, g = music(); g['notes'][16]['end_tick'] += 120
#         self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 1)
# 
#     def test_incoming_sustain_difference_is_preserved(self):
#         s, v, g = music(); g['notes'][15]['end_tick'] = 7800
#         self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 1)
# 
#     def test_capo_change_cannot_fold_into_original_grip(self):
#         s, v, g = music(); g['configuration']['capo_segments'] = [
#             {'start_tick': 0, 'start_measure': 1, 'capo_fret': 0},
#             {'start_tick': 7680, 'start_measure': 5, 'capo_fret': 2}]
#         self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 0)
# 
#     def test_key_change_cannot_erase_numeric_pitch_context(self):
#         s, v, g = music(); v['notation']['key_segments'] = [
#             {'start_tick': 7680, 'start_measure': 5, 'key': key_definition('D:major'), 'jianpu_reference_midi': 62}]
#         self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 0)
# 
#     def test_melody_accent_difference_is_not_collapsed(self):
#         s, v, g = music(); g['notes'][16]['melody_accent'] = True
#         self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 1)
# 
#     def test_velocity_variation_can_share_notation_without_changing_it(self):
#         s, v, g = music(); g['notes'][16]['velocity'] = 103; before = deepcopy(g)
#         self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 2); self.assertEqual(g, before)
# 
#     def test_both_fine_and_coda_pairing_expand_once_in_source_order(self):
#         s, v, g = music(); p = build_repeat_plan(s, v, g)
#         self.assertEqual(expand_route(p), [o['id'] for o in p['route']])
#         self.assertEqual(p['jumps'][0]['kind'], 'ds_al_fine')
# 
#     def test_missing_jump_target_and_infinite_loop_are_rejected(self):
#         s, v, g = music(); p = build_repeat_plan(s, v, g); p['jumps'][0]['to_occurrence'] = p['route'][0]['id']
#         with self.assertRaises(ValueError): expand_route(p)
# 
#     def test_stale_plan_after_music_edit_is_rejected(self):
#         s, v, g = music(); p = build_repeat_plan(s, v, g); g['notes'][0]['fret'] = 4
#         self.assertFalse(validate_repeat_plan(p, s, v, g)['valid'])
# 
#     def test_all_printed_lines_have_at_most_four_bars(self):
#         s, v, g = music(); p = build_repeat_plan(s, v, g); sizes = {b['id']: b['length_bars'] for b in p['blocks']}
#         self.assertTrue(all(sum(sizes[n] for n in row) <= 4 for row in p['lines']))
# 
#     def test_pickup_keeps_its_own_printed_line(self):
#         s, v, g = music(); v['timing']['initial_pickup_measure'] = True; s['phrase_harmony_plan']['phrases'] = []
#         p = build_repeat_plan(s, v, g)
#         self.assertEqual(p['blocks'][0]['length_bars'], 1); self.assertEqual(p['lines'][0], ['A'])
# 
#     def test_build_never_modifies_any_input_music(self):
#         s, v, g = music(); before = deepcopy((s, v, g)); build_repeat_plan(s, v, g)
#         self.assertEqual(before, (s, v, g))
# 
# 

class RepeatVisibleScoreTests(unittest.TestCase):
    # 重复乐句折叠与多遍挂词：新增可见上下两遍、歌词、时间列及单份实际TAB的正例和反例。
    def test_all_vocal_notes_and_24_lyric_units_visible_and_aligned(self):
        s, v, g, p, rows = rendered(); result = validate_repeat_rows(p, rows, v, g, s)
        self.assertTrue(result['valid'], result); self.assertEqual(result['visible_lyric_units'], 24)
        self.assertEqual(result['max_alignment_error_pixels'], 0)

    def corrupt(self, kind):
        s, v, g, p, rows = rendered(); root = ET.fromstring(rows[0]['guitar'])
        layers = [n for n in root.iter(NS + 'g') if n.get('class') == 'repeat-vocal-layer']
        if kind == 'shift': layers[-1].set('transform', 'translate(9,0)')
        if kind == 'lyric': next(t for t in root.iter(NS + 'text') if t.get('data-lyric-event-id')).text = '错'
        if kind == 'pitch': next(n for n in root.iter(NS + 'g') if n.get('class') == 'vocal-time-glyph').find(NS + 'text').text = '9'
        if kind in ('delete_lyric', 'delete_tab'):
            parents = {c: p for p in root.iter() for c in p}
            target = next(n for n in root.iter() if (n.get('data-lyric-event-id') if kind == 'delete_lyric' else n.get('data-string')))
            parents[target].remove(target)
        rows[0]['guitar'] = ET.tostring(root, encoding='unicode')
        return validate_repeat_rows(p, rows, v, g, s)

    def test_shifted_second_voice_is_rejected(self): self.assertFalse(self.corrupt('shift')['valid'])
    def test_changed_visible_word_is_rejected(self): self.assertFalse(self.corrupt('lyric')['valid'])
    def test_deleted_word_is_rejected(self): self.assertFalse(self.corrupt('delete_lyric')['valid'])
    def test_changed_visible_jianpu_pitch_is_rejected(self): self.assertFalse(self.corrupt('pitch')['valid'])
    def test_deleted_shared_tab_attack_is_rejected(self): self.assertFalse(self.corrupt('delete_tab')['valid'])

    def test_rendering_keeps_all_input_fields_unchanged(self):
        s, v, g = music(); before = deepcopy((s, v, g)); p = build_repeat_plan(s, v, g)
        with tempfile.TemporaryDirectory() as folder: render_lines(p, s, v, g, Path(folder))
        self.assertEqual(before, (s, v, g))


# 吉他长段反复与流畅阅读：新增自拟长段测试素材，不包含任何歌曲答案。
def section_music(length=8, gap=4, tail=4):
    source = []; lyrics = []; count = length * 2 + gap + tail
    for measure in range(count):
        for beat, pitch in enumerate((60, 62, 64, 67)):
            index = measure * 4 + beat; start = measure * 2 + beat / 2
            source.append(note(str(index), start, start + .5, pitch))
            lyrics.append(char(index, '春' if measure < length else '雨', start, start + .5))
    v = project_from(source, lyrics, seconds=count * 2)
    v['audio_analysis'] = {'tempo': {'bpm': 120}}; v['overrides'] = {'tempo': 120}
    v['timing']['knots'] = [{'seconds': 0., 'quarter': 0.}, {'seconds': .5, 'quarter': 1.}]
    s = {'statistics': deepcopy(v['statistics']), 'harmony': [],
         'sections': [{'kind': 'vocal', 'start_tick': 0, 'end_tick': count * 1920}],
         'measure_textures': [{'section': 'vocal', 'kind': 'arpeggio'} for _ in range(count)],
         'phrase_harmony_plan': {'phrases': []}}
    boundaries = sorted({0, length, length + gap, length * 2 + gap, count})
    for a, z in zip(boundaries, boundaries[1:]):
        s['phrase_harmony_plan']['phrases'].append({'id': str(a), 'family_id': 'theme' if a in (0, length + gap) else 'ending',
            'action': 'shared_progression', 'start_tick': a * 1920, 'end_tick': z * 1920})
    g = {'instrument': 'guitar', 'configuration': {'capo_fret': 0, 'rows_measures': 4},
         'notes': [], 'attack_events': [], 'fingering_diagrams': [], 'notation_regions': []}
    for measure in range(count):
        body = measure < length or length + gap <= measure < length * 2 + gap
        root = 0 if body else (9 if measure < length + gap else 4)
        quality = '' if body else 'm'; start = measure * 1920; chord = 'h' + str(measure)
        s['harmony'].append({'id': chord, 'start_tick': start, 'end_tick': start + 1920,
                            'root_pc': root, 'bass_pc': root, 'quality': quality,
                            'name': 'C' if body else 'Am' if root == 9 else 'Em', 'key': v['notation']['key']})
        tones = [(48, 5, 3), (55, 3, 0), (60, 2, 1), (64, 1, 0)] if body else (
                [(45, 5, 0), (57, 3, 2), (60, 2, 1), (64, 1, 0)] if root == 9 else [(40, 6, 0), (55, 3, 0), (59, 2, 0), (64, 1, 0)])
        for beat, (pitch, string, fret) in enumerate(tones):
            tick = start + beat * 480; identity = f'n{measure}_{beat}'
            g['notes'].append({'id': identity, 'start_tick': tick, 'end_tick': tick + 240,
                'pitch_midi': pitch, 'string': string, 'fret': fret, 'finger': int(fret > 0), 'hand_position': 1,
                'velocity': 75, 'role': 'bass' if beat == 0 else 'harmony', 'right_hand_duration_ticks': 480, 'chord_id': chord})
            g['attack_events'].append({'start_tick': tick, 'kind': 'arpeggio', 'chord_id': chord,
                'stroke': None, 'note_ids': [identity], 'right_hand_duration_ticks': 480})
    return s, v, g


# 吉他长段反复与流畅阅读：新增用户可感知行为与故意篡改的反例，不把规划器自报值当正确答案。
class RepeatPlanTests(unittest.TestCase):
    def test_short_two_bar_theme_is_written_in_full(self):
        s, v, g = music(); p = build_repeat_plan(s, v, g)
        self.assertEqual(p['saved_bars'], 0); self.assertEqual(p['jumps'], [])
        self.assertEqual(p['printed_bars'], 6)

    # 完整乐句与实际时长复用：修改旧“1到7小节一律拒绝”断言；短促远跳仍拒绝，完整慢乐句由单位不变性测试保护。
    # def test_one_to_seven_bars_do_not_create_remote_jumps(self):
    #     for length in range(1, 8):
    #         with self.subTest(length=length):
    #             s, v, g = section_music(length); p = build_repeat_plan(s, v, g)
    #             self.assertEqual(p['saved_bars'], 0); self.assertEqual(p['jumps'], [])
    def test_short_fast_fragments_do_not_create_remote_jumps(self):
        for length in range(1, 4):
            with self.subTest(length=length):
                s, v, g = section_music(length); p = build_repeat_plan(s, v, g)
                self.assertEqual(p['saved_bars'], 0); self.assertEqual(p['jumps'], [])

    def test_adjacent_eight_bars_use_one_plain_repeat_across_two_lines(self):
        s, v, g = section_music(gap=0); p = build_repeat_plan(s, v, g)
        self.assertEqual(p['saved_bars'], 8); self.assertEqual(len(p['repeat_groups']), 1)
        self.assertEqual(p['repeat_groups'][0]['method'], 'repeat')
        self.assertEqual(len(p['jumps']), 1); self.assertEqual(p['jumps'][0]['kind'], 'repeat')
        self.assertEqual(p['printed_bars'], 12); self.assertTrue(validate_repeat_plan(p, s, v, g)['valid'])

    def test_two_endings_use_volta_and_keep_complete_original_order(self):
        s, v, g = section_music(); p = build_repeat_plan(s, v, g)
        self.assertEqual(p['repeat_groups'][0]['method'], 'volta')
        self.assertEqual(p['repeat_groups'][0]['first_ending'], [9, 12])
        self.assertEqual(p['repeat_groups'][0]['second_ending'], [21, 24])
        from guitar_repeat_readability import expand_printed_bars
        self.assertEqual(expand_printed_bars(p), list(range(1, 25)))
        self.assertEqual(expand_route(p), [o['id'] for o in p['route']])

    def test_long_independent_bridge_uses_one_ds_and_delayed_coda(self):
        s, v, g = section_music(gap=12); p = build_repeat_plan(s, v, g)
        self.assertEqual(p['repeat_groups'][0]['method'], 'ds')
        self.assertEqual(p['jumps'][0]['kind'], 'ds_al_coda')
        self.assertEqual(p['jumps'][0]['uninterrupted_bars'], 8)
        self.assertTrue(validate_repeat_plan(p, s, v, g)['valid'])

    def test_final_long_reprise_uses_fine_after_second_pass(self):
        s, v, g = section_music(gap=12, tail=0); p = build_repeat_plan(s, v, g)
        self.assertEqual(p['jumps'][0]['kind'], 'ds_al_fine')
        self.assertEqual(expand_route(p), [o['id'] for o in p['route']])

    def test_inner_accompaniment_variants_expand_instead_of_short_islands(self):
        for field, value in [('pitch_midi', 49), ('string', 6), ('end_tick', 24400), ('fret', 4), ('melody_accent', True)]:
            s, v, g = section_music(); n = g['notes'][12 * 4]
            n[field] = value
            with self.subTest(field=field): self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 0)

    def test_attack_chord_capo_and_key_variants_cannot_be_hidden(self):
        s, v, g = section_music(); g['attack_events'][48]['start_tick'] += 120
        self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 0)
        s, v, g = section_music(); s['harmony'][12]['quality'] = 'maj7'
        self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 0)
        s, v, g = section_music(); g['configuration']['capo_segments'] = [{'start_tick': 0, 'capo_fret': 0}, {'start_tick': 23040, 'capo_fret': 2}]
        self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 0)
        s, v, g = section_music(); v['notation']['key_segments'] = [{'start_tick': 23040, 'start_measure': 13, 'key': key_definition('D:major'), 'jianpu_reference_midi': 62}]
        self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 0)

    def test_different_words_vocal_variants_and_velocity_preserve_each_pass(self):
        s, v, g = section_music(); before = deepcopy((s, v, g)); g['notes'][48]['velocity'] = 103
        next(e for e in v['events'] if e['measure'] == 13)['pitch_midi'] = 65
        p = build_repeat_plan(s, v, g); self.assertEqual(p['saved_bars'], 8)
        self.assertEqual(g['notes'][48]['velocity'], 103)
        self.assertEqual(len(v['events']), len(before[1]['events']))

    def test_partial_phrase_match_is_not_forced_to_eight_bar_fold(self):
        s, v, g = section_music(length=12)
        g['notes'][24 * 4 - 1]['fret'] = 2
        self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 0)

    def test_short_after_return_metadata_and_missing_target_are_rejected(self):
        s, v, g = section_music(); p = build_repeat_plan(s, v, g); p['jumps'][0]['uninterrupted_bars'] = 2
        self.assertFalse(validate_repeat_plan(p, s, v, g)['valid'])
        p = build_repeat_plan(s, v, g); p['jumps'][0]['to_occurrence'] = p['route'][0]['id']
        with self.assertRaises(ValueError): expand_route(p)

    def test_corrupted_volta_range_cannot_omit_music(self):
        s, v, g = section_music(); p = build_repeat_plan(s, v, g)
        p['repeat_groups'][0]['second_last'] += 1
        self.assertFalse(validate_repeat_plan(p, s, v, g)['valid'])

    def test_all_lines_are_at_most_four_bars_and_input_music_is_unchanged(self):
        s, v, g = section_music(); before = deepcopy((s, v, g)); p = build_repeat_plan(s, v, g)
        self.assertEqual(before, (s, v, g)); blocks = {b['id']: b for b in p['blocks']}
        self.assertTrue(all(sum(blocks[b]['length_bars'] for b in line) <= 4 for line in p['lines']))

    def test_pickup_is_kept_separate(self):
        s, v, g = section_music(); v['timing']['initial_pickup_measure'] = True
        p = build_repeat_plan(s, v, g); self.assertEqual(p['blocks'][0]['length_bars'], 1)

    # 吉他长段反复与流畅阅读：新增整曲选择和证据不足保护反例。
    def test_complete_sixteen_bars_win_over_two_small_reuses(self):
        s, v, g = section_music(length=16)
        s['phrase_harmony_plan']['phrases'] += [
            {'id': 'inside1', 'family_id': 'theme', 'action': 'shared_progression', 'start_tick': 8 * 1920, 'end_tick': 16 * 1920},
            {'id': 'inside2', 'family_id': 'theme', 'action': 'shared_progression', 'start_tick': 28 * 1920, 'end_tick': 36 * 1920}]
        p = build_repeat_plan(s, v, g)
        self.assertEqual(len(p['repeat_groups']), 1); self.assertEqual(p['repeat_groups'][0]['length_bars'], 16)
        self.assertEqual(len(p['jumps']), 1)

    def test_source_insufficient_phrases_are_not_forced_into_repeat(self):
        s, v, g = section_music()
        for phrase in s['phrase_harmony_plan']['phrases']: phrase['action'] = 'preserve_source_insufficient_evidence'
        self.assertEqual(build_repeat_plan(s, v, g)['saved_bars'], 0)

    def test_long_unfolded_score_does_not_hit_recursion_limit(self):
        from guitar_repeat_readability import select_candidates
        self.assertEqual(select_candidates([], 1500), [])


# 吉他长段反复与流畅阅读：新增实际图元正例和缺失／错写房子等反例。
class LongRepeatVisibleTests(unittest.TestCase):
    def render(self, **kwargs):
        s, v, g = section_music(**kwargs); p = build_repeat_plan(s, v, g)
        with tempfile.TemporaryDirectory() as folder: rows = render_lines(p, s, v, g, Path(folder))
        return s, v, g, p, rows

    def test_volta_prints_one_return_and_preserves_all_96_words(self):
        s, v, g, p, rows = self.render()
        r = validate_repeat_rows(p, rows, v, g, s); self.assertTrue(r['valid'], r)
        self.assertEqual(r['visible_lyric_units'], 96)
        kinds = [n.get('data-marker-kind') for row in rows for n in ET.fromstring(row['guitar']).iter(NS + 'g') if n.get('class') == 'repeat-print-symbol']
        self.assertEqual(kinds.count('repeat_start'), 1); self.assertEqual(kinds.count('repeat_end'), 1)
        self.assertEqual(kinds.count('volta_1'), 1); self.assertEqual(kinds.count('volta_2'), 1)
        self.assertNotIn('segno', kinds); self.assertNotIn('to_coda', kinds)

    def test_deleted_repeat_dots_and_changed_house_are_rejected(self):
        for kind in ['dots', 'house', 'symbol']:
            s, v, g, p, rows = self.render()
            for row in rows:
                root = ET.fromstring(row['guitar']); parents = {c: parent for parent in root.iter() for c in parent}
                node = next((n for n in root.iter(NS + 'g') if n.get('class') == 'repeat-print-symbol' and n.get('data-marker-kind') == ('volta_1' if kind == 'house' else 'repeat_end')), None)
                if node is None: continue
                if kind == 'dots': node.remove(node.find(NS + 'circle'))
                elif kind == 'house': node.find(NS + 'text').text = '2.'
                else: parents[node].remove(node)
                row['guitar'] = ET.tostring(root, encoding='unicode'); break
            with self.subTest(kind=kind): self.assertFalse(validate_repeat_rows(p, rows, v, g, s)['valid'])

    def test_ds_boundary_markers_are_not_repeated_on_each_row(self):
        s, v, g, p, rows = self.render(length=12, gap=16)
        result = validate_repeat_rows(p, rows, v, g, s); self.assertTrue(result['valid'], result)
        kinds = [n.get('data-marker-kind') for row in rows for n in ET.fromstring(row['guitar']).iter(NS + 'g') if n.get('class') == 'repeat-print-symbol']
        for kind in ['segno', 'ds', 'to_coda', 'coda']: self.assertEqual(kinds.count(kind), 1)

    # 吉他长段反复与流畅阅读：新增房子与人声遍次不矛盾的实际图元反例。
    def test_independent_second_ending_does_not_show_first_pass_number(self):
        s, v, g, p, rows = self.render()
        shared_numbers = []
        for row in rows:
            root = ET.fromstring(row['guitar'])
            labels = [n.text for n in root.iter(NS + 'text') if n.get('class') == 'repeat-pass-number']
            if root.find('.//' + NS + "g[@data-marker-kind='volta_2']") is not None:
                self.assertEqual(labels, [])
            shared_numbers += labels
        self.assertEqual(shared_numbers, ['1.', '2.', '1.', '2.'])


# 吉他长段反复与流畅阅读：保留直接运行测试入口，新增测试在入口前定义。
if __name__ == '__main__': unittest.main()
