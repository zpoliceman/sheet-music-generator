"""慢拍单位与两曲最小修订：真实秒坐标、词音身份、来源防篡改及公共入口顺序。"""
# 慢拍单位与两曲最小修订：新增独立合成音乐反例，不使用曲名或人工数拍答案。
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from score_export import save_json, sha256, key_definition
from accompaniment_analysis import SongClock
from phrase_harmony_plan import shared_fingerprint, vocal_fingerprint, arrangement_view
from meter_unit_projection import project_existing_music, projected_timing
from meter_unit_entry import verify_projected_shared, load_verified_decision
from meter_unit_guitar import regularize_complete_sustain
from source_meter_bar_groups import group_fixed_pulses


def fixture():
    # 慢拍单位与两曲最小修订：新增带预备拍、非零源起点和微小速度变化的合成旧工程。
    voice = {'timing': {'meter': [4, 4], 'score_start_quarter': -2., 'steady_tempo_bpm': 120.,
        'knots': [{'quarter': 0., 'seconds': .37}, {'quarter': 8., 'seconds': 4.37},
                  {'quarter': 16., 'seconds': 8.61}]},
        'statistics': {'total_ticks': 7680, 'bar_ticks': 1920, 'measure_count': 4},
        'notation': {'key': key_definition('C:major'), 'key_segments': []},
        'tempo_events': [{'tick': 0, 'bpm': 120.}, {'tick': 4800, 'bpm': 60 / .53}],
        'quantized_notes': [], 'lyrics': {'characters': []}, 'events': []}
    for i, (a, b, pitch) in enumerate(((960, 2400, 60), (2400, 3840, 62))):
        voice['quantized_notes'].append({'id': 'n' + str(i), 'pitch_midi': pitch, 'grace': False,
            'start_tick': a, 'end_tick': b, 'playback_start_tick': a, 'playback_end_tick': b,
            'start_seconds': SongClock(voice).seconds(a), 'end_seconds': SongClock(voice).seconds(b),
            'lyric_index': i, 'role': 'main'})
        voice['lyrics']['characters'].append({'index': i, 'text': chr(0x4e00 + i), 'line_index': 0})
    harmony = [{'id': 'h1', 'start_tick': 0, 'end_tick': 7680, 'root_pc': 0, 'quality': '',
                'bass_pc': 0, 'pitch_classes': [0, 4, 7], 'name': 'C'}]
    shared = {'timing': deepcopy(voice['timing']), 'statistics': deepcopy(voice['statistics']),
              'notation': deepcopy(voice['notation']), 'harmony': harmony, 'arranged_harmony': deepcopy(harmony)}
    shared['phrase_harmony_plan'] = {'version': 1, 'source_shared_sha256': shared_fingerprint(shared),
        'source_vocal_sha256': vocal_fingerprint(voice), 'phrases': [], 'families': [], 'unit_ticks': 480}
    guitar = {'configuration': {'capo_fret': 0}, 'notes': [{'id': 'g1', 'start_tick': 960,
        'end_tick': 2880, 'pitch_midi': 64, 'string': 1, 'fret': 0, 'section': 'intro'}],
        'fingering_diagrams': [], 'hand_positions': []}
    return {'accepted_vocal_project': voice, 'shared_analysis': shared, 'arrangements': {'guitar': guitar}}


class UnitProjectionTests(unittest.TestCase):
    # 慢拍单位与两曲最小修订：新增通用CLI保留未决并阻止覆盖旧证据，无需任何曲名参数。
    def test_decision_cli_records_unresolved_without_authorizing_generation(self):
        from meter_unit_entry import main
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'decision.json'
            args = ['--project','source.json','--evidence','raw.json','--selection','selection.json',
                    '--quarter-scale','0.5','--output',str(output)]
            decision = {'status':'needs_review','projection_allowed':False}
            with patch('meter_unit_entry.read_json',return_value={}), \
                    patch('meter_unit_entry.inspect_unit_decision',return_value=decision):
                self.assertEqual(main(args),2)
                self.assertTrue(output.is_file())
                with self.assertRaisesRegex(ValueError,'不能覆盖'):
                    main(args)

    # 慢拍单位与两曲最小修订：新增顶层身份丢失反例，必须来源重放而非重新套稳定右手。
    def test_dropped_top_marker_still_uses_preserved_unit_entry(self):
        from generate_accompaniment import generate
        args = SimpleNamespace(edited_project='base.json', output='out', report=None)
        project = {'accepted_vocal_project': {'meter_unit_correction': {'source_project': 'bound'}}}
        with patch('generate_accompaniment.read_json', return_value=project), \
                patch('revise_meter_unit.export_preserved', return_value={'preserved': True}) as exported, \
                patch('revise_guitar_patterns.revise', side_effect=AssertionError('old pattern branch')):
            self.assertEqual(generate(args), {'preserved': True})
            exported.assert_called_once()
        args.local_beat_clock = True
        with patch('generate_accompaniment.read_json', return_value=project):
            with self.assertRaises(ValueError):
                generate(args)

    # 慢拍单位与两曲最小修订：新增原点不能偷换零秒，跨小节长音、挂字和发声完全保留。
    def test_projection_preserves_seconds_pitch_owners_and_pickup(self):
        base = fixture(); before = deepcopy(base)
        revised, check = project_existing_music(base, .5, 4.)
        self.assertEqual(base, before)
        self.assertTrue(check['valid']); self.assertLess(check['maximum_onset_release_error_seconds'], 1e-10)
        voice = revised['accepted_vocal_project']
        self.assertEqual(voice['timing']['score_start_quarter'], -3.)
        self.assertEqual(voice['timing']['measure_timeline'][0]['end_tick'], 1440)
        self.assertTrue(voice['timing']['measure_timeline'][0]['pickup'])
        for a, b in zip(base['accepted_vocal_project']['quantized_notes'], voice['quantized_notes']):
            self.assertEqual((a['pitch_midi'], a['lyric_index'], a['start_seconds'], a['end_seconds']),
                             (b['pitch_midi'], b['lyric_index'], b['start_seconds'], b['end_seconds']))
        self.assertFalse(revised['music_acceptance']['publication_allowed'])

    # 慢拍单位与两曲最小修订：新增和声计划只做验证后的时间换算，过期旧计划不得刷新摘要放行。
    def test_valid_plan_projects_but_stale_plan_is_rejected(self):
        base = fixture(); revised, _ = project_existing_music(base, .5, 0.)
        view = arrangement_view(revised['shared_analysis'], revised['accepted_vocal_project'])
        self.assertEqual(view['harmony'][0]['end_tick'], 3840)
        base['shared_analysis']['harmony'][0]['root_pc'] = 1
        with self.assertRaises(ValueError):
            project_existing_music(base, .5, 0.)

    # 慢拍单位与两曲最小修订：新增认可覆盖层同样投影，否则会在新谱错误时刻生效。
    def test_approved_harmony_overlay_is_projected(self):
        base = fixture()
        base['shared_analysis']['approved_section_preservation'] = {'harmony': deepcopy(base['shared_analysis']['harmony'])}
        revised, _ = project_existing_music(base, .5, 0.)
        self.assertEqual(arrangement_view(revised['shared_analysis'])['harmony'][0]['end_tick'], 3840)

    # 慢拍单位与两曲最小修订：新增首拍分组不能暗中移动脉冲秒值。
    def test_grouping_cannot_move_existing_seconds(self):
        base = fixture()['accepted_vocal_project']
        grouping = {'seconds_changed': False, 'old_quarters': [0., 2., 4.],
                    'beats': [{'seconds': .37, 'beat': 1}, {'seconds': 1.37, 'beat': 2}, {'seconds': 2.38, 'beat': 1}]}
        with self.assertRaises(ValueError):
            projected_timing(base, .5, 0., grouping)

    # 慢拍单位与两曲最小修订：新增实际来源重放抓住自行刷新指纹后的和弦篡改。
    def test_shared_replay_rejects_self_refreshed_harmony(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(); source = Path(tmp) / 'source.json'; save_json(source, base)
            decision = {'quarter_scale': .5, 'first_downbeat_old_quarter': 0., 'fixed_pulse_grouping': None}
            revised, _ = project_existing_music(base, .5, 0.)
            revised['accepted_vocal_project']['meter_unit_correction'] = {
                'source_project': str(source), 'source_project_sha256': sha256(source), 'decision': 'bound_test_decision'}
            with patch('meter_unit_entry.load_verified_decision', return_value=decision):
                self.assertTrue(verify_projected_shared(revised)['valid'])
                revised['shared_analysis']['arranged_harmony'][0]['root_pc'] = 1
                revised['shared_analysis']['phrase_harmony_plan']['source_shared_sha256'] = shared_fingerprint(revised['shared_analysis'])
                with self.assertRaises(ValueError):
                    verify_projected_shared(revised)

    # 慢拍单位与两曲最小修订：新增自改基线SHA也不能省略原音／缩短持续声部。
    def test_unit_reexport_rejects_shortened_note_and_self_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(); source = Path(tmp) / 'source.json'; save_json(source, base)
            decision = {'quarter_scale': .5, 'first_downbeat_old_quarter': 0., 'fixed_pulse_grouping': None}
            revised, _ = project_existing_music(base, .5, 0.)
            revised['accepted_vocal_project']['meter_unit_correction'] = {
                'source_project': str(source), 'source_project_sha256': sha256(source), 'decision': 'bound_test_decision'}
            revised['arrangements']['guitar']['notes'][0]['end_tick'] -= 120
            with patch('meter_unit_entry.load_verified_decision', return_value=decision):
                with self.assertRaisesRegex(ValueError, '完整延音'):
                    verify_projected_shared(revised)
                fake = Path(tmp) / 'fake_baseline.json'; save_json(fake, revised)
                revised['readability_source'] = {'baseline_project': str(fake), 'baseline_project_sha256': sha256(fake),
                    'baseline_is_verified_unit_projection_of_source': True}
                with self.assertRaisesRegex(ValueError, '自证'):
                    verify_projected_shared(revised)

    # 慢拍单位与两曲最小修订：新增伪造passed或陈旧决定不能交给生成器。
    def test_forged_decision_cannot_bypass_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'decision.json'
            value = {'evidence_path': 'evidence', 'selection_path': 'selection', 'quarter_scale': .5,
                     'projection_allowed': True}
            save_json(path, value)
            with patch('meter_unit_entry.inspect_unit_decision', return_value={**value, 'projection_allowed': False}):
                with self.assertRaises(ValueError):
                    load_verified_decision(fixture(), path)

    # 慢拍单位与两曲最小修订：新增公共入口先采用单位决定，旧稳定右手标记不能导回旧拍轴。
    def test_actual_entry_routes_unit_before_old_pattern_path(self):
        from generate_accompaniment import generate
        args = SimpleNamespace(edited_project='base.json', meter_unit_decision='decision.json', output='out', report=None)
        with patch('generate_accompaniment.read_json', return_value={'arrangements': {'guitar': {'section_patterns': {}}}}), \
                patch('revise_meter_unit.revise', return_value={'unit_path': True}) as revised, \
                patch('revise_guitar_patterns.revise', side_effect=AssertionError('old path called')):
            self.assertEqual(generate(args), {'unit_path': True})
            revised.assert_called_once()
        args.rearrange = True
        with patch('generate_accompaniment.read_json', return_value=fixture()):
            with self.assertRaises(ValueError):
                generate(args)


class LocalSustainTests(unittest.TestCase):
    # 慢拍单位与两曲最小修订：新增独立旋律攻击不能挤成和弦；不吞音、不截尾，远处已合规音乐保持。
    def test_grid_fix_preserves_all_notes_duration_and_order(self):
        guitar = {'notes': [
            {'id': 'a', 'start_tick': 60, 'end_tick': 180, 'pitch_midi': 64, 'string': 1, 'fret': 0, 'role': 'instrumental_melody'},
            {'id': 'b', 'start_tick': 180, 'end_tick': 300, 'pitch_midi': 62, 'string': 2, 'fret': 3, 'role': 'instrumental_melody'},
            {'id': 'c', 'start_tick': 1440, 'end_tick': 1680, 'pitch_midi': 67, 'string': 1, 'fret': 3, 'role': 'instrumental_melody'}]}
        result, audit = regularize_complete_sustain(guitar, 1920)
        self.assertEqual(result['notes'][-1], guitar['notes'][-1])
        self.assertLess(result['notes'][0]['start_tick'], result['notes'][1]['start_tick'])
        for old, new in zip(guitar['notes'], result['notes']):
            self.assertEqual(old['pitch_midi'], new['pitch_midi'])
            self.assertGreaterEqual(new['end_tick'] - new['start_tick'], old['end_tick'] - old['start_tick'])
            self.assertGreaterEqual(new['end_tick'], old['end_tick'])
            self.assertEqual(new['start_tick'] % 120, 0); self.assertEqual(new['end_tick'] % 120, 0)
            self.assertLessEqual(new['fret'], 12)

    # 慢拍单位与两曲最小修订：新增不足时间容纳所有旋律时明确失败，不自动放宽64分或删除音。
    def test_impossible_density_and_high_fret_fail(self):
        notes = [{'id': str(i), 'start_tick': i * 30, 'end_tick': i * 30 + 30, 'pitch_midi': 64,
                  'string': 1, 'fret': 0, 'role': 'instrumental_melody'} for i in range(8)]
        with self.assertRaises(ValueError):
            regularize_complete_sustain({'notes': notes}, 480)
        notes[0]['fret'] = 18
        with self.assertRaises(ValueError):
            regularize_complete_sustain({'notes': notes}, 1920)


class FixedGroupingTests(unittest.TestCase):
    # 慢拍单位与两曲最小修订：新增低信心／同样强的第一三拍不能凭最佳路径自称分组通过。
    def test_silence_and_equal_first_third_remain_unresolved(self):
        seconds = np.arange(80, dtype=float); times = np.arange(4000) / 50
        empty = np.full(len(times), -12.)
        tracks = {'accompaniment': {'times': times, 'novelty': np.zeros(len(times))}}
        result = group_fixed_pulses(seconds, {'beat_logits': empty, 'downbeat_logits': empty}, tracks, version=3)
        self.assertEqual(result['status'], 'needs_review')
        bp, dp = empty.copy(), empty.copy(); bp[(seconds * 50).astype(int)] = 8.
        dp[np.arange(0, 80, 2) * 50] = 8.
        tracks['accompaniment']['novelty'][np.arange(0, 80, 2) * 50] = .8
        result = group_fixed_pulses(seconds, {'beat_logits': bp, 'downbeat_logits': dp}, tracks, version=3)
        self.assertEqual(result['status'], 'needs_review')

    # 慢拍单位与两曲最小修订：新增尾部孤立强音没有后续上下文，不能创造两拍小节。
    def test_tail_single_peak_cannot_create_short_bar(self):
        seconds = np.arange(80, dtype=float); times = np.arange(4000) / 50
        bp = np.full(len(times), -12.); dp = bp.copy(); novelty = np.zeros(len(times))
        bp[(seconds * 50).astype(int)] = 8.
        firsts = np.r_[np.arange(0, 80, 4), 78]
        dp[firsts * 50] = 8.; novelty[firsts * 50] = .8
        result = group_fixed_pulses(seconds, {'beat_logits': bp, 'downbeat_logits': dp},
            {'accompaniment': {'times': times, 'novelty': novelty}}, version=3)
        self.assertEqual(result['short_bars'], [])
        self.assertEqual([r['seconds'] for r in result['beats']], seconds.tolist())

    # 慢拍单位与两曲最小修订：新增有稳定前后证据的两拍过渡，不可通过局部加速凑四拍。
    def test_two_beat_transition_preserves_every_pulse(self):
        seconds = np.arange(80, dtype=float)
        times = np.arange(4000) / 50
        bp = np.full(len(times), -12.); dp = bp.copy(); novelty = np.zeros(len(times))
        bp[(seconds * 50).astype(int)] = 8.
        firsts = np.r_[np.arange(0, 33, 4), np.arange(34, 80, 4)]
        dp[firsts * 50] = 8.; novelty[firsts * 50] = .8
        result = group_fixed_pulses(seconds, {'beat_logits': bp, 'downbeat_logits': dp},
            {'accompaniment': {'times': times, 'novelty': novelty}})
        self.assertEqual(result['status'], 'supported')
        self.assertEqual([(r['start_seconds'], r['end_seconds']) for r in result['short_bars']], [(32., 34.)])
        self.assertEqual([r['seconds'] for r in result['beats']], seconds.tolist())
        self.assertFalse(result['full_music_accepted'])


if __name__ == '__main__':
    unittest.main()
