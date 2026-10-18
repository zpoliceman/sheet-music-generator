"""吉他编配规则与统一验收修复：历史漏检的硬约束反例。"""
# 吉他编配规则与统一验收修复：新增独立合成反例，覆盖旧通过标记、实际极短音、错误换位及旧验收复用。
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from score_export import key_definition
from guitar_readability_acceptance import assess_guitar_readability, actual_timeline, require_guitar_readability, _xml_notes
# 吉他编配规则闭环修复：新增旧文件实际解码及外部删改印刷符号的反例。
from guitar_readability_acceptance import _actual_artifacts, _actual_repeat_print
from guitar_readability_acceptance import _modern_tab_rows


def fixture():
    # 吉他编配规则与统一验收修复：新增原拍轴确定的简单开放弦材料，测试不依赖曲名或缓存。
    voice = {'title': '合成验收材料', 'timing': {'knots': [{'quarter': 0., 'seconds': 0.}, {'quarter': 16., 'seconds': 16.}],
             'meter': [4, 4], 'score_start_quarter': 0., 'steady_tempo_bpm': 60.},
             'statistics': {'bar_ticks': 1920, 'total_ticks': 7680, 'measure_count': 4},
             'notation': {'key': key_definition('C:major'), 'key_segments': []},
             'quantized_notes': [], 'events': [], 'lyrics': {'characters': []}}
    harmony = [{'id': 'c', 'start_tick': 0, 'end_tick': 7680, 'name': 'C', 'root_pc': 0,
                'quality': '', 'bass_pc': 0, 'pitch_classes': [0, 4, 7]}]
    guitar = {'instrument': 'guitar', 'notes': [{'id': 'open', 'pitch_midi': 55, 'string': 3, 'fret': 0,
               'start_tick': 0, 'end_tick': 240, 'velocity': 80, 'role': 'harmony', 'section': 'vocal'}],
              'configuration': {'capo_fret': 0, 'capo_segments': [], 'maximum_fret': 12,
                                'maximum_fretted_span': 5, 'maximum_left_hand_fingers': 4,
                                'maximum_position_change_frets_per_second': 24},
              'hand_positions': [], 'pedal': [], 'readable_harmony': harmony}
    return {'accepted_vocal_project': voice, 'shared_analysis': {'harmony': deepcopy(harmony)},
            'arrangements': {'guitar': guitar, 'piano': {'notes': [], 'instrument': 'piano'}}}


class GuitarReadabilityAcceptanceTests(unittest.TestCase):
    def test_obsolete_acceptance_policy_cannot_be_reused(self):
        # 吉他编配规则与统一验收修复：新增数据未变也不能以旧政策通过掩盖后加入的原声门槛。
        project = fixture()
        assessment = assess_guitar_readability(project, require_repeat=False)
        assessment['version'] = 1
        with self.assertRaisesRegex(ValueError, '策略已更新'):
            require_guitar_readability(project, assessment, final=False)

    def test_revised_guitar_cannot_bypass_independent_source_bass_check(self):
        # 吉他编配规则与统一验收修复：新增新分支遗漏原低音验收会被同一终检拦截。
        project = fixture()
        project['guitar_readability_revision'] = {'version': 1}
        result = assess_guitar_readability(project)
        self.assertIn('changed_bass_source_acceptance_missing', result['errors'])

    def check(self, project, **kwargs):
        # 吉他编配规则与统一验收修复：新增中间阶段显式标识，最终仍要求规划及实际文件。
        return assess_guitar_readability(project, require_repeat=False, **kwargs)

    def test_valid_open_string_preflight_is_not_final_delivery(self):
        project = fixture()
        result = self.check(project)
        self.assertTrue(result['valid'], result)
        with self.assertRaisesRegex(ValueError, '验收未通过'):
            require_guitar_readability(project, result)

    def test_old_passed_metadata_cannot_hide_short_actual_attack(self):
        project = fixture()
        guitar = project['arrangements']['guitar']
        guitar['regular_rhythm'] = {'valid': True, 'version': 2}
        guitar['notes'][0]['end_tick'] = 30
        guitar['notes'].append({**guitar['notes'][0], 'id': 'next', 'start_tick': 30, 'end_tick': 240})
        result = self.check(project)
        self.assertIn('guitar_attack_gap_shorter_than_sixteenth', result['errors'])
        self.assertIn('guitar_note_shorter_than_sixteenth', result['errors'])

    def test_half_beat_chord_is_rejected_even_when_every_fret_is_low(self):
        project = fixture()
        harmony = project['arrangements']['guitar']['readable_harmony']
        harmony[0]['end_tick'] = 240
        harmony.append({**harmony[0], 'id': 'am', 'name': 'Am', 'root_pc': 9, 'quality': 'm', 'start_tick': 240, 'end_tick': 7680})
        result = self.check(project)
        self.assertIn('harmony_change_density_failed', result['errors'])
        self.assertEqual(result['register']['maximum_fret'], 0)

    def test_chord_of_one_beat_still_cannot_change_midbeat(self):
        project = fixture()
        chord = project['arrangements']['guitar']['readable_harmony'][0]
        chord.update(start_tick=120, end_tick=600)
        self.assertIn('harmony_change_density_failed', self.check(project)['errors'])

    def test_three_whole_beat_chords_are_flagged_as_source_review_preference(self):
        project = fixture()
        source = project['arrangements']['guitar']['readable_harmony'][0]
        project['arrangements']['guitar']['readable_harmony'] = [
            {**source, 'id': str(i), 'name': name, 'start_tick': a, 'end_tick': b}
            for i, (name, a, b) in enumerate((('C', 0, 480), ('Am', 480, 960), ('F', 960, 7680)))]
        result = self.check(project)
        self.assertTrue(result['valid'], result)
        self.assertTrue(result['harmony']['bars_above_preferred_two'])

    def test_silent_fret_limit_relaxation_is_rejected(self):
        project = fixture()
        guitar = project['arrangements']['guitar']
        guitar['configuration']['maximum_fret'] = 20
        guitar['notes'][0].update(fret=13, pitch_midi=68)
        self.assertIn('guitar_fret_above_twelve', self.check(project)['errors'])

    def test_actual_note_mutation_invalidates_old_assessment(self):
        project = fixture()
        assessment = self.check(project)
        project['arrangements']['guitar']['notes'][0]['velocity'] -= 1
        with self.assertRaisesRegex(ValueError, '已失效'):
            require_guitar_readability(project, assessment, final=False)

    def test_final_check_requires_repeat_planner_to_have_run(self):
        project = fixture()
        project['time_only_revision'] = {'minimum_continuous_repeat_measures': 8}
        result = assess_guitar_readability(project)
        self.assertIn('repeat_planner_not_run', result['errors'])

    def test_source_clock_change_fails_protection(self):
        baseline = fixture()
        revised = deepcopy(baseline)
        revised['accepted_vocal_project']['timing']['knots'][1]['seconds'] = 15.9
        result = self.check(revised, baseline_project=baseline)
        self.assertIn('protected_vocal_clock_notes_or_lyrics_changed', result['errors'])

    def test_instrumental_octave_or_fret_change_cannot_pass_as_rhythm_cleanup(self):
        baseline = fixture()
        baseline['arrangements']['guitar']['notes'][0]['section'] = 'intro'
        revised = deepcopy(baseline)
        revised['arrangements']['guitar']['notes'][0].update(pitch_midi=67, fret=12)
        result = self.check(revised, baseline_project=baseline)
        self.assertIn('protected_instrumental_pitch_fret_or_expression_changed', result['errors'])

    def test_derived_legacy_timeline_does_not_change_source_music(self):
        baseline = fixture()
        revised = deepcopy(baseline)
        revised['accepted_vocal_project']['timing']['measure_timeline'] = actual_timeline(baseline['accepted_vocal_project'])
        self.assertTrue(self.check(revised, baseline_project=baseline)['valid'])

    def test_xml_reader_detects_real_short_fragment(self):
        # 吉他编配规则与统一验收修复：新增真实XML反例；参数宣称十六分不掩盖文件内32分。
        xml = '<score-partwise><part id="P1"><measure number="1"><attributes><divisions>480</divisions></attributes><note id="a"><pitch><step>G</step><octave>3</octave></pitch><duration>60</duration><type>32nd</type><notations><technical><string>3</string><fret>0</fret></technical></notations></note><note><rest/><duration>1860</duration><type>whole</type></note></measure></part></score-partwise>'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'score.musicxml'
            path.write_text(xml, 'utf-8')
            notes, result = _xml_notes(path, actual_timeline(fixture()['accepted_vocal_project'])[:1])
        self.assertFalse(result['valid'])
        self.assertEqual(result['sub_sixteenth_fragments'][0]['type'], '32nd')
        self.assertEqual(notes, [(55, 0, 60, 3, 0)])


class ActualLegacyAndRepeatArtifactsTests(unittest.TestCase):
    def test_modern_visible_glyph_and_extra_beam_cannot_hide_behind_correct_data(self):
        # 吉他编配规则闭环修复：新增保留隐藏属性但篡改实际数字／增画第三层横梁的反例。
        from test_guitar_variable_repeat import project_fixture
        from export_timing_revision import render_row
        from guitar_variable_repeat import measure_timeline
        project = project_fixture(); ns = '{http://www.w3.org/2000/svg}'
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            timeline = measure_timeline(project)
            for index in range(0, len(timeline), 4):
                path = Path(directory) / f'voice_{index:03}.svg'
                path.write_text(render_row(project, timeline[index:index + 4], True), 'utf-8'); paths.append(path)
            self.assertTrue(_modern_tab_rows(paths, project['arrangements']['guitar'])[1]['valid'])
            original = paths[0].read_text('utf-8'); root = ET.fromstring(original)
            next(n for n in root.iter() if n.get('data-string')).find(ns + 'text').text = '11'
            ET.ElementTree(root).write(paths[0], encoding='utf-8')
            self.assertFalse(_modern_tab_rows(paths, project['arrangements']['guitar'])[1]['valid'])
            root = ET.fromstring(original); parents = {n: p for p in root.iter() for n in p}
            stem = next(n for n in root.iter() if n.get('data-rhythm-duration'))
            ET.SubElement(parents[stem], ns + 'line', {'x1': stem.get('x1'), 'x2': str(float(stem.get('x1')) + 9),
                           'y1': '455', 'y2': '455', 'stroke-width': '2', 'stroke': 'black'})
            ET.ElementTree(root).write(paths[0], encoding='utf-8')
            result = _modern_tab_rows(paths, project['arrangements']['guitar'])[1]
            self.assertIn('visible_modern_beams_differ_from_actual_duration', result['errors'])

    def legacy_files(self, directory):
        # 吉他编配规则闭环修复：新增真实旧XML／MIDI／数字TAB文件，不补伪造的新格式data属性。
        from test_guitar_repeat_score import section_music
        from accompaniment_export import build_musicxml, write_midi, guitar_row
        shared, voice, guitar = section_music(length=8)
        shared['input_binding'] = {'vocal_project_sha256': 'synthetic'}
        for section in shared['sections']:
            section['label'] = '合成段'
        project = {'accepted_vocal_project': voice, 'shared_analysis': shared, 'arrangements': {'guitar': guitar}}
        folder = Path(directory) / 'guitar'; folder.mkdir(); (folder / 'rows').mkdir()
        ET.ElementTree(build_musicxml(shared, voice, guitar)[0]).write(folder / 'score.musicxml', encoding='utf-8')
        write_midi(folder / 'accompaniment.mid', guitar, voice)
        rows = []
        for first in range(1, voice['statistics']['measure_count'] + 1, 4):
            last = min(first + 3, voice['statistics']['measure_count'])
            svg = guitar_row(shared, voice, guitar, first, last)
            (folder / 'rows' / f'measures_{first:03}_{last:03}.svg').write_text(svg, 'utf-8')
            rows.append(svg)
        (folder / 'score.html').write_text('<html>' + ''.join(rows) + '</html>', 'utf-8')
        return project, folder

    def test_legacy_midi_and_visible_numeric_tab_are_really_decoded(self):
        with tempfile.TemporaryDirectory() as directory:
            project, folder = self.legacy_files(directory)
            result = _actual_artifacts(project, directory, actual_timeline(project['accepted_vocal_project']))
            self.assertTrue(result['valid'], result)
            self.assertEqual(result['midi']['files'], ['accompaniment.mid'])
            self.assertEqual(result['tab']['format'], 'legacy_actual_numeric_x_and_grip')
            path = next((folder / 'rows').glob('*.svg'))
            root = ET.parse(path).getroot()
            node = next(n for n in root.iter() if n.get('data-string'))
            node.find('{http://www.w3.org/2000/svg}text').text = '11'
            ET.ElementTree(root).write(path, encoding='utf-8')
            altered = _actual_artifacts(project, directory, actual_timeline(project['accepted_vocal_project']))
            self.assertIn('chronological_tab_notes_differ_from_project', altered['errors'])

    def test_missing_technical_string_or_changed_fret_is_not_excused_as_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            project, folder = self.legacy_files(directory)
            path = folder / 'score.musicxml'; root = ET.parse(path).getroot()
            root.find('part/measure/note/notations/technical/fret').text = '11'
            ET.ElementTree(root).write(path, encoding='utf-8')
            result = _actual_artifacts(project, directory, actual_timeline(project['accepted_vocal_project']))
            self.assertIn('xml_actual_notes_differ_from_project', result['errors'])

    def repeat_files(self, directory):
        # 吉他编配规则闭环修复：新增可变拍／房子的真实主HTML与独立SVG文件。
        from test_guitar_variable_repeat import project_fixture
        from export_timing_revision import write_variable_repeat_score
        from accompaniment_export import html_page
        import json
        project = project_fixture(); folder = Path(directory); (folder / 'rows').mkdir()
        # 完整乐句与实际时长复用：修改符号反例的底稿为真实展开谱，新版须同时核验实际书写量和面积。
        # (folder / 'score.html').write_text(html_page('合成', '<nav></nav><section class="score-row">原序</section>'), 'utf-8')
        from export_timing_revision import render_row
        from guitar_variable_repeat import measure_timeline
        timeline=measure_timeline(project)
        body=''.join('<section class="score-row">'+render_row(project,timeline[i:i+4],True)+'</section>' for i in range(0,len(timeline),4))
        (folder/'score.html').write_text(html_page('合成','<nav></nav>'+body),'utf-8')
        write_variable_repeat_score(project, folder)
        return project, folder, json.loads((folder / 'repeat_plan.json').read_text('utf-8'))

    def test_deleted_repeat_dots_fail_file_readback_even_with_unchanged_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            project, folder, plan = self.repeat_files(directory)
            self.assertTrue(_actual_repeat_print(project, folder, plan)['valid'])
            path = folder / 'rows/repeat_001.svg'; root = ET.parse(path).getroot()
            marker = next(n for n in root.iter() if n.get('data-marker-kind') == 'repeat_start')
            marker.remove(marker.find('{http://www.w3.org/2000/svg}circle'))
            ET.ElementTree(root).write(path, encoding='utf-8')
            result = _actual_repeat_print(project, folder, plan)
            self.assertFalse(result['valid'])
            self.assertTrue(any('双点缺失' in error for error in result['errors']))

    def test_primary_html_cannot_omit_symbols_while_external_svg_stays_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            project, folder, plan = self.repeat_files(directory)
            page = folder / 'score.html'
            page.write_text(page.read_text('utf-8').replace('repeat-print-symbol', 'removed-print-symbol', 1), 'utf-8')
            result = _actual_repeat_print(project, folder, plan)
            self.assertFalse(result['valid'])
            self.assertTrue(any('actual_page_differs' in error for error in result['errors']))

    def test_wrong_folded_tab_in_both_html_and_svg_cannot_borrow_unfolded_pass(self):
        # 吉他编配规则闭环修复：新增主折叠谱与外存SVG同时出现错品数字的反例，展开附页正确也不能免责。
        with tempfile.TemporaryDirectory() as directory:
            project, folder, plan = self.repeat_files(directory)
            path, page = folder / 'rows/repeat_001.svg', folder / 'score.html'
            before = path.read_text('utf-8')
            root = ET.fromstring(before)
            next(n for n in root.iter() if n.get('data-string')).find('{http://www.w3.org/2000/svg}text').text = '99'
            changed = ET.tostring(root, encoding='unicode')
            path.write_text(changed, 'utf-8')
            page.write_text(page.read_text('utf-8').replace(before, changed), 'utf-8')
            result = _actual_repeat_print(project, folder, plan)
            self.assertFalse(result['valid'])
            self.assertTrue(result['actual_page_matches_svg_files'])
            self.assertTrue(any('visible_modern_fret_differs' in error for error in result['errors']))

    def test_extra_folded_rhythm_beam_in_both_html_and_svg_is_rejected(self):
        # 吉他编配规则闭环修复：新增主阅读谱双文件同时多画第三层横梁，不能仅凭data-flags通过。
        with tempfile.TemporaryDirectory() as directory:
            project, folder, plan = self.repeat_files(directory)
            path, page = folder / 'rows/repeat_001.svg', folder / 'score.html'
            before = path.read_text('utf-8'); root = ET.fromstring(before)
            parents = {n: p for p in root.iter() for n in p}; ns = '{http://www.w3.org/2000/svg}'
            stem = next(n for n in root.iter() if n.get('data-rhythm-duration'))
            ET.SubElement(parents[stem], ns + 'line', {'x1': stem.get('x1'), 'x2': str(float(stem.get('x1')) + 9),
                           'y1': '455', 'y2': '455', 'stroke-width': '2', 'stroke': 'black'})
            changed = ET.tostring(root, encoding='unicode')
            path.write_text(changed, 'utf-8')
            page.write_text(page.read_text('utf-8').replace(before, changed), 'utf-8')
            result = _actual_repeat_print(project, folder, plan)
            self.assertFalse(result['valid'])
            self.assertTrue(result['actual_page_matches_svg_files'])
            self.assertIn('visible_modern_beams_differ_from_actual_duration', result['errors'])


if __name__ == '__main__':
    unittest.main()
