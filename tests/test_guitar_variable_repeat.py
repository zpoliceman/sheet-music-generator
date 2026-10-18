"""吉他编配规则闭环修复：可变小节长段反复、真实图元及源时钟回归。"""
# 吉他编配规则闭环修复：新增自拟音乐与故意篡改的反例，不使用曲名或固定原曲答案。
from bisect import bisect_right
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
from test_guitar_repeat_score import section_music
from guitar_variable_repeat import build_repeat_plan, validate_repeat_plan, measure_timeline
from guitar_repeat_readability import expand_printed_bars
from export_timing_revision import render_row, local_view, write_variable_repeat_score
from accompaniment_analysis import SongClock
from accompaniment_export import html_page

NS = '{http://www.w3.org/2000/svg}'


def project_fixture(variable=True, length=8, gap=4):
    # 吉他编配规则闭环修复：新增两遍同主题各有一处2/4，不能把短小节错当完整4/4。
    shared, vocal, guitar = section_music(length=length, gap=gap)
    project = {'accepted_vocal_project': vocal, 'shared_analysis': shared, 'arrangements': {'guitar': guitar}}
    if not variable:
        return project
    count = vocal['statistics']['measure_count']
    lengths = [960 if i in (0, length + gap) else 1920 for i in range(count)]
    begins = [0]
    for length_ticks in lengths:
        begins.append(begins[-1] + length_ticks)
    def mapped(tick):
        index = min(count - 1, max(0, int(tick // 1920)))
        return begins[index] + round((tick - index * 1920) * lengths[index] / 1920)
    for rows in (shared['harmony'], shared['sections'], shared['phrase_harmony_plan']['phrases'],
                 guitar['notes'], guitar['attack_events'], vocal['quantized_notes']):
        for item in rows:
            for field in ('start_tick', 'end_tick'):
                if field in item:
                    item[field] = mapped(item[field])
    for event in vocal['events']:
        before = event['start_tick']; after = before + event['duration_ticks']
        event.update(start_tick=mapped(before), duration_ticks=mapped(after) - mapped(before),
                     offset_ticks=mapped(before) - begins[event['measure'] - 1])
    vocal['timing']['measure_timeline'] = [
        {'number': i + 1, 'start_tick': begins[i], 'end_tick': begins[i + 1], 'pickup': False,
         'meter': [2, 4] if lengths[i] == 960 else [4, 4], 'start_seconds': begins[i] / 960,
         'end_seconds': begins[i + 1] / 960} for i in range(count)]
    vocal['statistics']['total_ticks'] = begins[-1]
    return project


class VariableRepeatTests(unittest.TestCase):
    def test_different_vocal_onsets_are_included_in_folded_line_width(self):
        # 全曲目固定右手预览：新增第二遍轻切分扩大联合字形列的实际渲染反例；缩短显示行不能丢掉8小节复用或改音乐。
        project=project_fixture(variable=False);voice=project['accepted_vocal_project'];timeline=measure_timeline(project)
        for event in voice['events']:
            # 全曲目固定右手预览：修改自拟素材只变一小节，保持整体主题相似；仍以实际联合宽度断言显示不溢出。
            # if 13<=event['measure']<=20 and event.get('pitch_midi') is not None:
            if event['measure']==13 and event.get('pitch_midi') is not None:
                event.update(start_tick=event['start_tick']+120,offset_ticks=event['offset_ticks']+120,
                             duration_ticks=event['duration_ticks']-120,type='eighth',dots=1)
        for note in voice['quantized_notes']:
            # 全曲目固定右手预览：修改主音段与上述单小节实际事件保持同一变体。
            # if timeline[12]['start_tick']<=note['start_tick']<timeline[20]['start_tick']:note['start_tick']+=120
            if timeline[12]['start_tick']<=note['start_tick']<timeline[13]['start_tick']:note['start_tick']+=120
        config=project['arrangements']['guitar']['configuration']
        # 全曲目固定右手预览：修改自拟显示预算，使单遍两小节合适而联合两小节确实超宽。
        # config.update(maximum_bars_per_reading_line=4,reading_maximum_native_width=900,
        config.update(maximum_bars_per_reading_line=4,reading_maximum_native_width=820,
            reading_measure_widths={str(m['number']):float(ET.fromstring(render_row(project,[m],True)).get('width')) for m in timeline})
        before=deepcopy(project);plan=build_repeat_plan(project)
        self.assertEqual(plan['saved_bars'],8)
        self.assertTrue(any(b['length_bars']>1 for b in plan['blocks'] if not b['repeat_group']))
        for block in plan['blocks']:
            if not block['repeat_group']:continue
            canonical=timeline[block['canonical_first']-1:block['canonical_last']]
            layers=[timeline[o['first']-1:o['last']] for o in block['occurrences']]
            width=float(ET.fromstring(render_row(project,canonical,True,vocal_measures=layers)).get('width'))
            # 全曲目固定右手预览：修改断言与自拟显示预算一致，未降低生产音乐门槛。
            # self.assertLessEqual(width,900)
            self.assertLessEqual(width,820)
        self.assertTrue(validate_repeat_plan(plan,project)['valid'])
        self.assertEqual(project,before)

    def test_short_bar_lengths_and_complete_source_order_survive_two_endings(self):
        project = project_fixture(); before = deepcopy(project)
        plan = build_repeat_plan(project)
        self.assertEqual(plan['saved_bars'], 8)
        self.assertEqual(plan['repeat_groups'][0]['method'], 'volta')
        self.assertEqual(expand_printed_bars(plan), list(range(1, 25)))
        self.assertEqual(plan['actual_measure_timeline'][0]['end_tick'], 960)
        self.assertTrue(validate_repeat_plan(plan, project)['valid'])
        self.assertEqual(project, before)

    def test_twelve_bars_and_long_bridge_keep_existing_plain_and_ds_capability(self):
        for length, gap, kind in ((12, 0, 'repeat'), (8, 12, 'ds')):
            project = project_fixture(length=length, gap=gap)
            plan = build_repeat_plan(project)
            self.assertEqual(plan['saved_bars'], length)
            self.assertEqual(plan['repeat_groups'][0]['method'], kind)
            self.assertTrue(validate_repeat_plan(plan, project)['valid'])

    def test_actual_hold_string_and_meter_variants_cannot_fold(self):
        for field, value in (('end_tick', 23041), ('string', 6), ('fret', 2)):
            project = project_fixture()
            project['arrangements']['guitar']['notes'][48][field] = value
            self.assertEqual(build_repeat_plan(project)['saved_bars'], 0)
        project = project_fixture()
        project['accepted_vocal_project']['timing']['measure_timeline'][12]['meter'] = [4, 4]
        self.assertEqual(build_repeat_plan(project)['saved_bars'], 0)

    def test_no_short_jump_and_no_claim_that_unplanned_means_no_candidate(self):
        project = project_fixture(length=3)
        plan = build_repeat_plan(project)
        self.assertEqual(plan['saved_bars'], 0)
        self.assertTrue(plan['planning_executed'])
        self.assertTrue(plan['evaluated_boundaries'])
        self.assertTrue(plan['no_fold_reason'])

    def test_original_clock_offset_is_preserved_in_local_bar_adapter(self):
        project = project_fixture(variable=False)
        vocal = project['accepted_vocal_project']
        vocal['timing']['score_start_quarter'] = -4.
        original_clock = SongClock(vocal)
        measure = measure_timeline(project)[7]
        local, _, _ = local_view(project, measure, 'guitar')
        self.assertAlmostEqual(SongClock(local).seconds(0), original_clock.seconds(measure['start_tick']))
        self.assertAlmostEqual(SongClock(local).seconds(480), original_clock.seconds(measure['start_tick'] + 480))

    def test_render_rejects_dense_right_hand_instead_of_hiding_beams(self):
        project = project_fixture(variable=False)
        project['arrangements']['guitar']['notes'][0]['end_tick'] = 60
        with self.assertRaisesRegex(ValueError, '十六分'):
            render_row(project, measure_timeline(project)[:4], True)

    def test_stacked_lyrics_and_one_tab_have_actual_symbols_and_unfolded_attachment(self):
        project = project_fixture(); timeline = measure_timeline(project)
        baseline = deepcopy(project)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); (folder / 'rows').mkdir()
            full = html_page('合成', '<h1>合成</h1><nav></nav><section class="score-row">原顺序内容</section>')
            (folder / 'score.html').write_text(full, 'utf-8')
            result = write_variable_repeat_score(project, folder)
            self.assertTrue(result['valid'])
            self.assertGreater(result['print_marks']['visible_symbols'], 0)
            self.assertIn('原顺序内容', (folder / 'score_full.html').read_text('utf-8'))
            first = ET.parse(folder / 'rows/repeat_001.svg').getroot()
            vocal_measures = [n for n in first.iter() if n.get('data-vocal-pass')]
            self.assertEqual(len(vocal_measures), 8)
            self.assertEqual({n.get('data-vocal-pass') for n in vocal_measures}, {'1', '2'})
            self.assertEqual(len([n for n in first.iter() if n.get('data-string')]), 16)
            for index in range(4):
                self.assertEqual(vocal_measures[index * 2].get('x'), vocal_measures[index * 2 + 1].get('x'))
        self.assertEqual(project, baseline)

    def test_readable_harmony_used_by_guitar_leaves_original_analysis_unchanged(self):
        project = project_fixture(variable=False)
        guitar = project['arrangements']['guitar']; original = deepcopy(project['shared_analysis'])
        guitar['readable_harmony'] = deepcopy(original['harmony'])
        guitar['readable_harmony'][0].update(name='Am', root_pc=9, quality='m')
        _, shared, _ = local_view(project, measure_timeline(project)[0], 'guitar')
        self.assertEqual(shared['harmony'][0]['name'], 'Am')
        self.assertEqual(project['shared_analysis'], original)


if __name__ == '__main__':
    unittest.main()
