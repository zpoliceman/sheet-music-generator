"""多区间右手配置与网页完整成品：真实范围、循环相位、保护及持久化反例。"""
# 多区间右手配置与网页完整成品：新增行为验收，不以页面字段存在代替实际音乐生效。
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from test_guitar_section_patterns import fixture
from guitar_pattern_selection import compile_selection, assess_selection, normalize_plan
# 多区间右手配置与网页完整成品：保留初稿导入，新增关闭重开仍找回同一目录的行为验收。
# from guitar_pattern_configurations import ConfigurationStore, full_result
from guitar_pattern_configurations import ConfigurationStore, full_result, editor_workspace, remember_workspace


def interval(start, end, pattern='A02', **options):
    # 多区间右手配置与网页完整成品：新增按谱面号的可重用测试输入。
    return {'id': f'r{start}_{end}', 'start_measure': start, 'end_measure': end,
            'choice': {'pattern_id': pattern, **options} if pattern else None}


class GuitarPatternRangeTests(unittest.TestCase):
    def test_four_independent_ranges_change_only_selected_measures(self):
        original = fixture(52)
        # 多区间右手配置与网页完整成品：改用用户给出的两组上行及跨第三拍延续，保留初拟测试。
        # plan = {'ranges': [interval(5, 8), interval(9, 20, 'A05'), interval(21, 25, 'S07'), interval(26, 50)]}
        plan = {'ranges': [interval(5, 8, 'A01'), interval(9, 20, 'A10'), interval(21, 25, 'S07'), interval(26, 50, 'A01')]}
        revised, audit = compile_selection(original, plan)
        self.assertEqual(audit['arranged_measures'], list(range(5, 51)))
        sections = revised['right_hand_selection']['sections']
        self.assertEqual([(s['start_measure'], s['end_measure'], s['choice']['pattern_id']) for s in sections],
                         # 多区间右手配置与网页完整成品：修改实际期望，与用户示例候选对应。
                         # [(5, 8, 'A02'), (9, 20, 'A05'), (21, 25, 'S07'), (26, 50, 'A02')])
                         [(5, 8, 'A01'), (9, 20, 'A10'), (21, 25, 'S07'), (26, 50, 'A01')])
        kept = [n for n in original['arrangements']['guitar']['notes'] if n['start_tick'] < 4*1920 or n['start_tick'] >= 50*1920]
        actual = {n['id']: n for n in revised['arrangements']['guitar']['notes']}
        self.assertTrue(all(actual[n['id']] == n for n in kept))
        self.assertEqual(revised['accepted_vocal_project'], original['accepted_vocal_project'])
        self.assertEqual(revised['shared_analysis'], original['shared_analysis'])
        self.assertTrue(assess_selection(revised, original)['valid'])

    def test_range_cycle_origin_is_requested_start_and_not_chord_start(self):
        original = fixture(8)
        # 多区间右手配置与网页完整成品：新增不对称的两小节型，能识别错误地逐小节重置循环。
        # revised, _ = compile_selection(original, {'ranges': [interval(2, 5, note_value='quarter')]})
        revised, _ = compile_selection(original, {'ranges': [interval(2, 5, 'A04', note_value='quarter')]})
        events = revised['arrangements']['guitar']['selected_pattern_actions']
        self.assertEqual([e['start_tick'] for e in events[:8]], list(range(1920, 5760, 480)))
        # 多区间右手配置与网页完整成品：保留对称初稿期望，实际检查后半小节不会重置成低音。
        # self.assertEqual([e['token'] for e in events[:8]], ['B', '1', '2', '3', 'B', '1', '2', '3'])
        # self.assertEqual([e['token'] for e in events if e['measure'] == 3], ['B', '1', '2', '3'])
        self.assertEqual([e['token'] for e in events[:8]], ['B', '3', '2', '3', '1', '3', '2', '3'])
        self.assertEqual([e['token'] for e in events if e['measure'] == 3], ['1', '3', '2', '3'])

    def test_each_range_keeps_its_own_note_values(self):
        revised, _ = compile_selection(fixture(8), {'ranges': [interval(1, 2, note_value='sixteenth'), interval(3, 4, 'A14'), interval(5, 6, note_value='quarter')]})
        actions = revised['arrangements']['guitar']['selected_pattern_actions']
        self.assertEqual([len([e for e in actions if e['measure'] == m]) for m in (1, 3, 5)], [16, 8, 4])
        self.assertTrue(any(e['kind'] == 'pinch' and e['measure'] == 3 for e in actions))

    def test_overlaps_bad_bounds_and_duplicate_ids_fail_without_mutating_original(self):
        original = fixture(8); before = deepcopy(original)
        cases = [[interval(1, 4), interval(4, 6)], [interval(0, 2)], [interval(2, 9)], [interval(4, 3)],
                 [interval(1.5, 3)], [{**interval(1, 2), 'start_measure': True}],
                 [interval(1, 2), {**interval(3, 4), 'id': 'r1_2'}]]
        for ranges in cases:
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                compile_selection(original, {'ranges': ranges})
        self.assertEqual(original, before)

    def test_empty_choices_preserve_source_exactly(self):
        original = fixture(8)
        for plan in ({'ranges': []}, {'ranges': [interval(1, 4, None)]}):
            revised, audit = compile_selection(original, plan)
            self.assertEqual(revised, original); self.assertFalse(audit['music_changed'])

    def test_scope_crossing_original_sustain_preserves_complete_notes(self):
        original = fixture(8)
        note = original['arrangements']['guitar']['notes'][4]
        note['end_tick'] = 2400
        revised, audit = compile_selection(original, {'ranges': [interval(2, 4)]})
        self.assertNotIn(2, audit['arranged_measures']); self.assertIn(3, audit['arranged_measures'])
        self.assertEqual(next(n for n in revised['arrangements']['guitar']['notes'] if n['id'] == note['id']), note)
        self.assertTrue(any(e['reason'] == 'preserve_range_boundary_sustain' for e in audit['exceptions']))
        self.assertTrue(assess_selection(revised, original)['valid'])

    def test_partial_and_instrumental_measures_inside_ranges_are_preserved(self):
        original = fixture(8)
        note = original['arrangements']['guitar']['notes'][11]
        note.update(section='interlude', role='instrumental_melody')
        revised, audit = compile_selection(original, {'ranges': [interval(2, 5)]})
        self.assertEqual(audit['arranged_measures'], [2, 4, 5])
        self.assertEqual(next(n for n in revised['arrangements']['guitar']['notes'] if n['id'] == note['id']), note)

    def test_pickup_displayed_number_maps_to_real_measure_once(self):
        original = fixture(6)
        original['accepted_vocal_project']['timing']['measure_timeline'] = [
            {'number': i+1, 'start_tick': i*1920, 'end_tick': (i+1)*1920, 'meter': [4, 4], 'pickup': i == 0}
            for i in range(6)]
        revised, audit = compile_selection(original, {'ranges': [interval(2, 3)]})
        self.assertEqual(audit['arranged_measures'], [3, 4])
        self.assertEqual(revised['right_hand_selection']['sections'][0]['start_tick'], 3840)

    def test_tail_action_does_not_extend_beyond_range_into_next_configuration(self):
        # 多区间右手配置与网页完整成品：新增两小节循环只选一小节时的长格边界，验证独立动作占时。
        original = fixture(4)
        revised, _ = compile_selection(original, {'ranges': [interval(1, 1, 'A14', durations=[120,120,120,120,120,120,120,3000]), interval(2, 2, 'S07')]})
        actions = revised['arrangements']['guitar']['selected_pattern_actions']
        first = [e for e in actions if e['measure'] == 1]
        self.assertTrue(all(e['start_tick']+e['action_span_ticks'] <= 1920 for e in first))
        self.assertTrue(all(n['end_tick'] <= 1920 for n in revised['arrangements']['guitar']['notes'] if n.get('selection_action_id') in {e['id'] for e in first}))

    def test_saved_range_metadata_cannot_be_tampered_to_bypass_music_check(self):
        original = fixture(8)
        revised, _ = compile_selection(original, {'ranges': [interval(2, 4)]})
        revised['right_hand_selection']['plan']['ranges'][0]['end_measure'] = 5
        self.assertFalse(assess_selection(revised, original)['valid'])

    def test_legacy_default_format_still_has_same_snapshot(self):
        original = fixture(4)
        normalized = normalize_plan({'default': {'pattern_id': 'A02'}}, original)
        self.assertNotIn('ranges', normalized)
        with self.assertRaisesRegex(ValueError, '分别使用'):
            normalize_plan({'default': {'pattern_id': 'A02'}, 'ranges': [interval(1, 2)]}, original)


class GuitarConfigurationTests(unittest.TestCase):
    # 多区间右手配置与网页完整成品：新增启动器接续与记忆路径保护，覆盖实际关闭重开场景。
    def test_reopening_without_arguments_recovers_saved_workspace(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            self.assertEqual(editor_workspace(root), root/'test_outputs/accompaniment_runs/right_hand_editor')
            actual = root/'test_outputs/accompaniment_runs/custom_editor'
            remember_workspace(root, actual)
            self.assertEqual(editor_workspace(root), actual)
            self.assertEqual(editor_workspace(root, 'test_outputs/accompaniment_runs/another'), root/'test_outputs/accompaniment_runs/another')
            self.assertEqual(editor_workspace(root), actual)

    def test_remembered_workspace_cannot_select_normal_scores_or_external_path(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with self.assertRaises(ValueError): editor_workspace(root, root/'results/accompaniment/current')
            with self.assertRaises(ValueError): editor_workspace(root, root.parent/'external')

    def test_multiple_named_configurations_reload_and_update_without_losing_other_sets(self):
        with TemporaryDirectory() as folder:
            store = ConfigurationStore(folder); project = 'a'*16
            first = store.prepare(project, 'source-sha', {'name': '主歌分解'})
            second = store.prepare(project, 'source-sha', {'name': '副歌扫弦'})
            plan = {'ranges': [interval(2, 4)]}
            store.save(first, plan, {'version': 'v1'})
            store.save(second, {'ranges': [interval(4, 6, 'S07')]}, {'version': 'v2'})
            loaded = ConfigurationStore(folder).list(project, 'source-sha')
            self.assertEqual({r['name'] for r in loaded}, {'主歌分解', '副歌扫弦'})
            self.assertTrue(all(r['compatible'] for r in loaded))
            updated = store.prepare(project, 'source-sha', {'id': first['id'], 'name': '主歌分解'})
            store.save(updated, {'ranges': [interval(2, 5)]}, {'version': 'v3'})
            loaded = ConfigurationStore(folder).list(project, 'source-sha')
            self.assertEqual(len(loaded), 2)
            self.assertEqual(next(r for r in loaded if r['id'] == second['id'])['result'], {'version': 'v2'})
            self.assertEqual(plan['ranges'][0]['end_measure'], 4)

    def test_changed_source_is_marked_incompatible_and_cannot_overwrite_configuration(self):
        with TemporaryDirectory() as folder:
            store = ConfigurationStore(folder); first = store.prepare('a'*16, 'old-sha', {'name': '配置'})
            store.save(first, {'ranges': [interval(2, 4)]}, {'version': 'v1'})
            self.assertFalse(store.list('a'*16, 'new-sha')[0]['compatible'])
            with self.assertRaisesRegex(ValueError, '改变'):
                store.prepare('a'*16, 'new-sha', {'id': first['id'], 'name': '配置'})
            self.assertEqual(store.list('b'*16, 'old-sha'), [])

    def test_configuration_identifiers_never_become_arbitrary_paths(self):
        with TemporaryDirectory() as folder:
            store = ConfigurationStore(folder)
            with self.assertRaises(ValueError): store.list('../source', 'sha')
            with self.assertRaises(ValueError): store.prepare('a'*16, 'sha', {'id': '../source'})
            with self.assertRaises(ValueError): store.prepare('a'*16, 'sha', {'name': 'x'*81})

    def test_full_result_uses_actual_full_score_and_full_audio_paths(self):
        with TemporaryDirectory() as folder:
            output = Path(folder); (output/'guitar').mkdir()
            result = full_result(output, 'v123')
            self.assertEqual(result['score_url'], '/saved/v123/guitar/score.html')
            (output/'guitar/score_full.html').write_text('<svg></svg>', encoding='utf-8')
            self.assertEqual(full_result(output, 'v123')['score_url'], '/saved/v123/guitar/score_full.html')
            self.assertEqual(result['audio_url'], '/saved/v123/guitar/preview.wav')


if __name__ == '__main__':
    unittest.main()
