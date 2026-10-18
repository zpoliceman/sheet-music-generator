"""保音持续按弦与整句八度衔接：持续抢弦、局部重规划、原音高及历史保护反例。"""
from copy import deepcopy
import unittest

from test_guitar_instrumental_register import music
from accompaniment_analysis import SongClock
from accompaniment_arrange import arrange_requested, validate_playability
from generate_accompaniment import prepare_provisional_instrumentals
from guitar_instrumental_register import arrange_instrumental_register, melodic_phrases, solve_path, validate_instrumental_register
from instrumental_phrase_register import plan_phrases
from instrumental_source_melody import revised_guitar


# 保音持续按弦与整句八度衔接：新增完全自拟反例，在不同夹位和时间偏移下复现持续低音抢弦。
def occupied_string_music(capo=1, offset=0):
    shared, vocal, guitar = music(capo)
    guitar['configuration']['instrumental_register_voicing_version'] = 2
    rows = [('a', 0, 360, 82, 'instrumental_melody'),
            ('b', 360, 720, 75, 'instrumental_melody'),
            ('c', 720, 960, 70, 'instrumental_melody'),
            ('d', 960, 1200, 70, 'instrumental_melody'),
            ('low', 600, 1080, 51, 'bass'), ('inner', 840, 960, 67, 'harmony')]
    normal = next(note for note in guitar['notes'] if note['id'] == 'normal')
    guitar['notes'] = [{'id': identity, 'start_tick': begin + offset, 'end_tick': end + offset,
                        'pitch_midi': pitch + capo - 1, 'role': role, 'velocity': 80,
                        'string': 1, 'fret': pitch - 65, 'finger': 1, 'hand_position': 1,
                        'source': 'synthetic', 'chord_id': 'h0'} for identity, begin, end, pitch, role in rows] + [normal]
    return shared, vocal, guitar


class RegisterLookaheadTests(unittest.TestCase):
    # 保音持续按弦与整句八度衔接：新增明确重编入口不得绕回旧逐音配音，普通重导与此入口分开。
    def test_explicit_rearrangement_uses_phrase_register_voicing(self):
        from unittest.mock import patch
        from generate_accompaniment import load_edited_project
        shared, vocal, _ = music()
        shared['input_binding'].update(vocal_project='bound_vocal.json', vocal_project_sha256='a' * 64, sources={})
        data = {'shared_analysis': shared, 'accepted_vocal_project': vocal, 'arrangements': {}}
        with patch('generate_accompaniment.read_json', side_effect=lambda path: vocal if str(path) == 'bound_vocal.json' else data), \
             patch('generate_accompaniment.sha256', return_value='a' * 64), \
             patch('generate_accompaniment.validate_source_pitch_project', return_value=True), \
             patch('generate_accompaniment.validate_vocal_snapshot', return_value=True), \
             patch('generate_accompaniment.arrange_requested', return_value={'guitar': {}}) as arrange:
            load_edited_project('project.json', rearrange=True, capo=2)
        self.assertTrue(arrange.call_args.kwargs['phrase_register'])

    # 保音持续按弦与整句八度衔接：新增只有密集小节单独成行，其余仍可并排，8小节音乐复用不被切碎。
    def test_one_dense_measure_does_not_force_every_measure_onto_its_own_row(self):
        from test_guitar_variable_repeat import project_fixture
        from guitar_variable_repeat import build_repeat_plan, validate_repeat_plan
        project = project_fixture(variable=False)
        original = build_repeat_plan(project)
        config = project['arrangements']['guitar']['configuration']
        config.update(maximum_bars_per_reading_line=4, reading_maximum_native_width=1300,
                      reading_measure_widths={str(number): 1000 if number == 1 else 400
                                             for number in range(1, project['accepted_vocal_project']['statistics']['measure_count'] + 1)})
        plan = build_repeat_plan(project)
        self.assertEqual(plan['blocks'][0]['length_bars'], 1)
        self.assertTrue(any(block['length_bars'] > 1 for block in plan['blocks'][1:]))
        self.assertEqual(plan['repeat_groups'], original['repeat_groups'])
        self.assertTrue(validate_repeat_plan(plan, project)['valid'])

    # 保音持续按弦与整句八度衔接：新增图式拥挤时实际可见TAB仍可独立解读，不靠隐藏data-fret证明x正确。
    def test_note_uses_numeric_fret_when_its_diagram_is_not_visible(self):
        from pathlib import Path
        import tempfile
        from test_guitar_variable_repeat import project_fixture
        from export_timing_revision import render_row
        from guitar_variable_repeat import measure_timeline
        from guitar_readability_acceptance import _modern_tab_rows
        project = project_fixture(variable=False)
        guitar = project['arrangements']['guitar']
        guitar['notes'] = [{'id': 'first', 'start_tick': 0, 'end_tick': 120, 'pitch_midi': 60,
                            'string': 2, 'fret': 1, 'finger': 1, 'role': 'harmony', 'velocity': 70},
                           {'id': 'second', 'start_tick': 120, 'end_tick': 240, 'pitch_midi': 60,
                            'string': 2, 'fret': 1, 'finger': 1, 'role': 'harmony', 'velocity': 70}]
        common = {'position': 1, 'frets': {'1': 0, '2': 1, '3': 0, '4': 2, '5': 3},
                  'barre': None, 'finger_count': 3, 'shape_name': 'C', 'sounding_name': 'C',
                  'capo': 0, 'simplified': False, 'chord_id': project['shared_analysis']['harmony'][0]['id']}
        guitar['fingering_diagrams'] = [{**common, 'id': 'first_chart', 'start_tick': 0, 'end_tick': 1},
                                        {**common, 'id': 'second_chart', 'start_tick': 1, 'end_tick': 1920}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'row.svg'
            path.write_text(render_row(project, measure_timeline(project)[:1], True), encoding='utf-8')
            _, report = _modern_tab_rows([path], guitar)
            self.assertTrue(report['valid'], report['errors'])
            self.assertEqual(report['actual_notes'], 2)

    # 保音持续按弦与整句八度衔接：新增排版空操作不得使原表现层的音符摘要失效。
    def test_already_regular_notes_are_not_rewritten_by_readability(self):
        from guitar_readable_arrangement import _quantize_instrumental
        notes = [{'id': 'held', 'start_tick': 0, 'end_tick': 480, 'string': 6,
                  'pitch_midi': 40, 'right_hand_duration_ticks': 120,
                  'right_hand_duration_source': 'original_regular_pluck', 'melody_accent': False}]
        result, changes = _quantize_instrumental(notes, 1920)
        self.assertEqual(result, notes)
        self.assertEqual(changes, [])

    # 保音持续按弦与整句八度衔接：新增显示行缩短时仍保留原8小节音乐复用，不产生1–3小节短回跳。
    def test_shorter_display_rows_keep_full_long_repeat(self):
        from test_guitar_variable_repeat import project_fixture
        from guitar_variable_repeat import build_repeat_plan, validate_repeat_plan
        project = project_fixture(variable=False)
        original = build_repeat_plan(project)
        project['arrangements']['guitar']['configuration']['maximum_bars_per_reading_line'] = 2
        plan = build_repeat_plan(project)
        self.assertEqual(plan['repeat_groups'], original['repeat_groups'])
        self.assertTrue(plan['repeat_groups'])
        self.assertTrue(all(block['length_bars'] <= 2 for block in plan['blocks']))
        self.assertTrue(all(group['length_bars'] >= 8 for group in plan['repeat_groups']))
        self.assertTrue(validate_repeat_plan(plan, project)['valid'])

    # 保音持续按弦与整句八度衔接：新增持音端点同品但中间弦须空弦的反例，不能只保留较省指的横按。
    def test_individual_fingers_survive_when_future_open_string_breaks_barre(self):
        shared, vocal, guitar = music()
        guitar['notes'] = [
            {'id': 'low', 'start_tick': 0, 'end_tick': 480, 'pitch_midi': 43,
             'string': 6, 'fret': 3, 'finger': 1, 'role': 'bass', 'velocity': 70},
            {'id': 'upper', 'start_tick': 0, 'end_tick': 480, 'pitch_midi': 62,
             'string': 2, 'fret': 3, 'finger': 2, 'role': 'harmony', 'velocity': 70},
            {'id': 'middle_open', 'start_tick': 120, 'end_tick': 240, 'pitch_midi': 55,
             'string': 3, 'fret': 0, 'finger': 0, 'role': 'harmony', 'velocity': 70}]
        legacy, _ = solve_path(shared, vocal, guitar, set(), [], 12, 48, search_version=1)
        current, _ = solve_path(shared, vocal, guitar, set(), [], 12, 48, search_version=2)
        self.assertIsNone(legacy)
        self.assertIsNotNone(current)
        first = next(row for row in current if row['tick'] == 0)
        self.assertEqual(sum(bool(unit) for unit in first['fingers']), 2)
        self.assertEqual(set(identity for row in current for identity in row['added']), {'low', 'upper', 'middle_open'})

    # 保音持续按弦与整句八度衔接：新增真实失败机制反例，不能靠少音、短延音或放宽品数通过。
    def test_retains_sustained_bass_on_alternate_string(self):
        for capo, offset in ((0, 120), (1, 0), (3, 240)):
            with self.subTest(capo=capo, offset=offset):
                shared, vocal, guitar = occupied_string_music(capo, offset)
                original = deepcopy((shared, vocal, guitar))
                result, report = arrange_instrumental_register(shared, vocal, guitar)
                self.assertEqual((shared, vocal, guitar), original)
                before = {note['id']: note for note in guitar['notes']}
                after = {note['id']: note for note in result['notes']}
                self.assertEqual(set(before), set(after))
                self.assertEqual(after['low']['pitch_midi'], before['low']['pitch_midi'])
                self.assertEqual((after['low']['string'], after['low']['fret']), (5, 5))
                for identity, note in before.items():
                    self.assertEqual((note['start_tick'], note['end_tick'], note['role']),
                                     (after[identity]['start_tick'], after[identity]['end_tick'], after[identity]['role']))
                self.assertEqual({after[identity]['pitch_midi'] - before[identity]['pitch_midi'] for identity in 'abcd'}, {-12})
                self.assertTrue(validate_playability(result, SongClock(vocal))['valid'])
                self.assertEqual(report['after']['above_twelve'], 0)
                self.assertTrue(any(attempt.get('sustained_search', {}).get('statistics', {}).get('future_rejected', 0)
                                    for attempt in report['attempts']))

    # 保音持续按弦与整句八度衔接：新增瞬时和弦可按但未来换把太快的反例，须恢复真实窗口前状态并重新准备手位。
    def test_local_replanning_keeps_prior_sustains_and_prepares_future_position(self):
        shared, vocal, guitar = music()
        shared['sections'] = [{'kind': 'intro', 'start_tick': 0, 'end_tick': 120},
                              {'kind': 'vocal', 'start_tick': 120, 'end_tick': 3840}]
        guitar['notes'] = [
            {'id': 'open', 'start_tick': 0, 'end_tick': 120, 'pitch_midi': 40,
             'role': 'instrumental_melody', 'velocity': 90, 'string': 6, 'fret': 0, 'finger': 0},
            {'id': 'fixed', 'start_tick': 120, 'end_tick': 240, 'pitch_midi': 76,
             'role': 'harmony', 'velocity': 70, 'string': 1, 'fret': 12, 'finger': 1}]
        guitar['hand_positions'] = [{'tick': 0, 'position': 12}]
        editable = {'open'}
        phrases = melodic_phrases(shared, guitar['notes'], editable)
        path, report = solve_path(shared, vocal, guitar, editable, phrases, 12, 1,
                                  low_fret_priority=True, search_version=2)
        self.assertIsNotNone(path)
        self.assertTrue(report['sustained_search']['local_replanning'])
        self.assertEqual(path[0]['position'], 12)
        self.assertEqual(set(identity for row in path for identity in row['added']), {'open', 'fixed'})
        self.assertTrue(all(not row['notes_or_releases_changed'] for row in report['sustained_search']['local_replanning']))

    # 保音持续按弦与整句八度衔接：新增原始极高音可一次降三个八度，不借20品初始化，也不逐音改变旋律关系。
    def test_canonical_source_can_choose_three_octaves_once(self):
        shared, vocal, guitar = music()
        guitar['configuration'].update(source_register_input_version=2, instrumental_register_voicing_version=2)
        guitar['notes'] = [
            {'id': 'high', 'start_tick': 0, 'end_tick': 960, 'pitch_midi': 98,
             'role': 'instrumental_melody', 'velocity': 90, 'string': 1, 'fret': 34, 'finger': 1},
            {'id': 'low', 'start_tick': 0, 'end_tick': 960, 'pitch_midi': 48,
             'role': 'bass', 'velocity': 70, 'string': 5, 'fret': 3, 'finger': 1}]
        result, report = arrange_instrumental_register(shared, vocal, guitar)
        melody = next(note for note in result['notes'] if note['id'] == 'high')
        self.assertLessEqual(melody['fret'], 4)
        self.assertEqual(melody['instrumental_register_source_pitch_midi'], 98)
        self.assertLessEqual(melody['instrumental_register_octave_shift'], -36)
        self.assertTrue(validate_instrumental_register(shared, vocal, result)['valid'])
        again, _ = arrange_instrumental_register(shared, vocal, result)
        self.assertEqual(again, result)
        self.assertIn(-36, report['source_octave_candidates'])

    # 保音持续按弦与整句八度衔接：新增全新公共初次编配入口的高音反例，旧逐音初始化不会在乐句规划前拦住它。
    def test_initial_public_voicing_plans_before_high_note_assignment(self):
        shared, vocal, _ = music()
        shared['instrumental_melody'][0].update(pitch_midi=98, duration_ticks=240)
        shared['input_binding']['requested_instruments'] = ['guitar']
        arranged = arrange_requested(shared, vocal, 0, phrase_register=True)['guitar']
        self.assertTrue(arranged['initial_phrase_register_preparation']['all_source_melody_requests_retained'])
        self.assertTrue(all(note['fret'] <= 12 for note in arranged['notes']))
        self.assertEqual(prepare_provisional_instrumentals(shared, vocal, arranged), arranged)

    # 保音持续按弦与整句八度衔接：新增来源重提取原音高种子与真实历史初始化区分，防止旧账本被隐式升级。
    def test_source_seed_raw_pitch_and_legacy_seed_remain_separate(self):
        shared, vocal, guitar = music()
        plan = {'sections': [{'id': 'source', 'kind': 'intro', 'start_tick': 0, 'end_tick': 1920}],
                'notes': [{'id': 'raw', 'section_id': 'source', 'pitch_midi': 98,
                           'start_tick': 0, 'end_tick': 240, 'duration_ticks': 240,
                           'source_start_seconds': 0, 'source_end_seconds': .25,
                           'source': 'synthetic', 'section': 'intro'}]}
        old, _ = revised_guitar(shared, vocal, guitar, plan)
        raw, _ = revised_guitar(shared, vocal, guitar, plan, register_input_version=2)
        old_note = next(note for note in old['notes'] if note['id'] == 'guitar_raw')
        raw_note = next(note for note in raw['notes'] if note['id'] == 'guitar_raw')
        self.assertLess(old_note['pitch_midi'], 98)
        self.assertEqual(raw_note['pitch_midi'], 98)
        self.assertEqual(raw_note['source_backbone_initial_octave_shift'], 0)
        self.assertEqual(raw['configuration']['source_register_input_version'], 2)


if __name__ == '__main__':
    # 保音持续按弦与整句八度衔接：新增独立测试入口。
    unittest.main()
