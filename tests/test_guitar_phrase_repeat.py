"""完整乐句与实际时长复用：单位不变性、真实路线时长和冻结入口反例。"""
# 完整乐句与实际时长复用：新增完全自拟音乐，不把歌曲名、既知歌词或实际歌曲秒数写成答案。
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
from test_guitar_variable_repeat import project_fixture
from test_guitar_repeat_variants import fixture
from guitar_variable_repeat import build_repeat_plan, validate_repeat_plan
from guitar_phrase_repeat import validate_route_evidence


def merge_units(original):
    # 完整乐句与实际时长复用：新增等价记谱转换测试材料，保留所有音符实际秒数，只把四分拍单位减半。
    project = deepcopy(original)
    def scale(value):
        if isinstance(value, dict):
            return {k: (int(v / 2) if isinstance(v, (int, float)) and (k.endswith('_tick') or k.endswith('_ticks'))
                        and k != 'bar_ticks' else scale(v)) for k, v in value.items()}
        if isinstance(value, list): return [scale(v) for v in value]
        return value
    project = scale(project)
    voice = project['accepted_vocal_project']
    voice['statistics']['measure_count'] //= 2
    voice['timing']['score_start_quarter'] /= 2
    for knot in voice['timing']['knots']: knot['quarter'] /= 2
    voice['timing'].pop('measure_timeline', None)
    for event in voice['events']: event['measure'] = event['start_tick'] // 1920 + 1
    project['shared_analysis']['statistics'] = deepcopy(voice['statistics'])
    project['shared_analysis']['timing'] = deepcopy(voice['timing'])
    selected = project['arrangements']['guitar'].get('section_patterns', {}).get('arranged_measures')
    if selected is not None:
        project['arrangements']['guitar']['section_patterns']['arranged_measures'] = sorted({(i - 1) // 2 + 1 for i in selected})
    return project


class PhraseDurationRepeatTests(unittest.TestCase):
    def test_eight_ten_twelve_bars_merge_without_losing_phrase_or_time(self):
        # 完整乐句与实际时长复用：新增独立比较实际秒数及整段音符数量，防止门槛仅从8机械改成4。
        for length in (8, 10, 12):
            with self.subTest(length=length):
                old = project_fixture(variable=False, length=length, gap=16)
                new = merge_units(old); protected = deepcopy(new)
                left, right = build_repeat_plan(old), build_repeat_plan(new)
                self.assertEqual(len(left['repeat_groups']), 1)
                self.assertEqual(len(right['repeat_groups']), 1)
                a, b = left['repeat_groups'][0], right['repeat_groups'][0]
                self.assertEqual(a['length_bars'], 2 * b['length_bars'])
                self.assertEqual(a['phrase_reuse_assessment']['occurrences'], b['phrase_reuse_assessment']['occurrences'])
                self.assertEqual(a['phrase_reuse_assessment']['saved_attack_glyphs'], b['phrase_reuse_assessment']['saved_attack_glyphs'])
                self.assertAlmostEqual(a['phrase_reuse_assessment']['reading_gain'], b['phrase_reuse_assessment']['reading_gain'])
                self.assertTrue(validate_repeat_plan(right, new)['valid'])
                self.assertEqual(new, protected)

    def test_note_difference_fraction_does_not_double_when_bars_merge(self):
        old = fixture((5,)); new = merge_units(old)
        a = build_repeat_plan(old)['repeat_groups'][0]
        b = build_repeat_plan(new)['repeat_groups'][0]
        self.assertAlmostEqual(a['phrase_reuse_assessment']['shared_note_duration_ratio'], b['phrase_reuse_assessment']['shared_note_duration_ratio'])
        self.assertEqual(len(b['variant_bars']), 1)
        self.assertTrue(validate_repeat_plan(build_repeat_plan(new), new)['valid'])

    def test_dense_but_four_second_section_is_not_rescued_by_many_bars(self):
        project = project_fixture(variable=False, length=8, gap=16)
        for knot in project['accepted_vocal_project']['timing']['knots']: knot['seconds'] /= 4
        self.assertEqual(build_repeat_plan(project)['repeat_groups'], [])

    def test_long_silence_does_not_create_reading_gain(self):
        project = project_fixture(variable=False, length=12, gap=16)
        project['arrangements']['guitar']['notes'] = []
        project['arrangements']['guitar']['attack_events'] = []
        self.assertEqual(build_repeat_plan(project)['repeat_groups'], [])

    def test_single_long_hold_does_not_count_as_many_repeated_attacks(self):
        project = project_fixture(variable=False, length=12, gap=16)
        guitar = project['arrangements']['guitar']
        original = guitar['notes']; guitar['notes'] = []
        for first in (0, 28 * 1920):
            note = deepcopy(next(n for n in original if n['start_tick'] == first))
            note['end_tick'] = first + 12 * 1920; guitar['notes'].append(note)
        guitar['attack_events'] = []
        self.assertEqual(build_repeat_plan(project)['repeat_groups'], [])

    def test_plain_repeat_measures_continuation_after_common_section(self):
        project = project_fixture(variable=False, length=8, gap=0)
        plan = build_repeat_plan(project)
        group = plan['repeat_groups'][0]
        self.assertGreater(group['actual_continuous_return_seconds'], group['phrase_reuse_assessment']['continuous_return_seconds'])
        self.assertTrue(validate_route_evidence(plan, project['accepted_vocal_project'])['valid'])

    def test_forged_seconds_or_missing_phrase_proof_cannot_pass(self):
        project = project_fixture(variable=False, length=8, gap=16)
        for mutation in ('seconds', 'phrase'):
            plan = build_repeat_plan(project)
            if mutation == 'seconds': plan['jumps'][0]['uninterrupted_seconds'] += 1
            else: plan['repeat_groups'][0].pop('phrase_reuse_assessment')
            self.assertFalse(validate_repeat_plan(plan, project)['valid'])

    def test_current_short_measure_and_pickup_remain_unchanged(self):
        project = project_fixture(variable=True, length=8, gap=4); old = deepcopy(project)
        plan = build_repeat_plan(project)
        self.assertTrue(validate_repeat_plan(plan, project)['valid'])
        self.assertEqual(project, old)
        self.assertEqual(plan['actual_measure_timeline'], project['accepted_vocal_project']['timing']['measure_timeline'])

    def test_scattered_variants_can_cost_more_than_shared_tab(self):
        project = fixture((1, 3, 5, 7, 9))
        plan = build_repeat_plan(project)
        self.assertEqual(plan['repeat_groups'], [])
        self.assertIn('navigation_or_variant_reading_cost_exceeds_saved_tab', plan['phrase_candidate_audit']['rejections'])


class ReadingEntryTests(unittest.TestCase):
    def test_frozen_time_revision_checks_highest_voice_and_audio_not_old_replay(self):
        # 完整乐句与实际时长复用：新增最高层来源篡改反例，保护后续局部词音而不绕过音源核验。
        from revise_guitar_reading import verify_reading_source
        from score_export import sha256
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);audio=folder/'source.wav';audio.write_bytes(b'original')
            binding={'sources':{'mix':{'path':str(audio),'sha256':sha256(audio)}}}
            voice={'time_only_revision':{'version':1},'quantized_notes':[{'lyric':'a','pitch_midi':60}]}
            base=folder/'base.json';base.write_text(json.dumps({'accepted_vocal_project':voice,'shared_analysis':{'input_binding':binding}}),'utf8')
            project={'accepted_vocal_project':deepcopy(voice),'shared_analysis':{'input_binding':binding},
                'readability_source':{'project':str(base),'project_sha256':sha256(base)}}
            with patch('revise_guitar_readability.protected_baseline'),patch('guitar_source_bass_acceptance.require_changed_bass_source'),patch('source_meter_entry.require_calibrated_source') as old:
                self.assertEqual(verify_reading_source(project,base)['status'],'verified_frozen_time_revision')
                old.assert_not_called()
                project['accepted_vocal_project']['quantized_notes'][0]['pitch_midi']=61
                with self.assertRaisesRegex(ValueError,'最高层词音'):verify_reading_source(project,base)
                project['accepted_vocal_project']=deepcopy(voice);audio.write_bytes(b'altered')
                with self.assertRaisesRegex(ValueError,'原音来源'):verify_reading_source(project,base)

    def test_actual_added_page_area_can_reject_nominal_positive_reuse(self):
        # 完整乐句与实际时长复用：新增真实SVG面积反例，候选正收益不能让巨大空白版面通过。
        from guitar_reading_load import assess_printed_reading_load
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            def page(count,height):
                return '<section class="score-row"><svg xmlns="http://www.w3.org/2000/svg" width="100" height="'+str(height)+'">'+('<g data-string="1"><text>0</text></g>'*count)+'</svg></section>'
            (folder/'score_full.html').write_text(page(100,100),'utf8')
            (folder/'score.html').write_text(page(80,101),'utf8')
            self.assertTrue(assess_printed_reading_load(folder,{'repeat_groups':[{}]})['valid'])
            (folder/'score.html').write_text(page(80,130),'utf8')
            result=assess_printed_reading_load(folder,{'repeat_groups':[{}]})
            self.assertFalse(result['valid']);self.assertIn('actual_layout_cost_exceeds_saved_tab',result['errors'])

    def args(self, folder, **changes):
        # 完整乐句与实际时长复用：新增只测试分流协议的最小绑定工程，真正来源重放由集成回归执行。
        path = Path(folder) / 'project.json'
        path.write_text(json.dumps({'meter_unit_revision': {'version': 1}}), 'utf-8')
        values = {'edited_project': path, 'refresh_reading': True, 'output': Path(folder) / 'out', 'report': None}
        values.update(changes)
        return SimpleNamespace(**values)

    def test_reading_only_dispatches_before_meter_or_arrangement(self):
        from generate_accompaniment import generate
        with tempfile.TemporaryDirectory() as folder, patch('revise_guitar_reading.revise_reading', return_value={'reading': True}) as reading, patch('revise_meter_unit.export_preserved') as music:
            result = generate(self.args(folder))
            self.assertEqual(result, {'reading': True}); reading.assert_called_once(); music.assert_not_called()

    def test_mutating_flags_including_capo_zero_are_rejected(self):
        from generate_accompaniment import generate
        for change in ({'rearrange': True}, {'capo': 0}, {'stable_vocal_patterns': True}, {'bar_length_factor': .5}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder, patch('revise_guitar_reading.revise_reading') as reading:
                with self.assertRaisesRegex(ValueError, '纯阅读'): generate(self.args(folder, **change))
                reading.assert_not_called()


if __name__ == '__main__':
    # 完整乐句与实际时长复用：新增直接执行测试入口。
    unittest.main()
