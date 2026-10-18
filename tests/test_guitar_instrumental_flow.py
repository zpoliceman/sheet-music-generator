"""器乐低弦分解填充：新增声部持续、真实休止、跨调及实际导出反例。"""
from copy import deepcopy
from pathlib import Path
import sys, tempfile, unittest
import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from test_accompaniment import fixture
from accompaniment_analysis import SongClock
from accompaniment_arrange import arrange_guitar, validate_playability
from accompaniment_export import build_musicxml, parse_musicxml_notes, write_midi, validate_midi
from guitar_rhythm_beams import arrangement_rhythm_events
from guitar_instrumental_flow import (POLICY, pulse_and_step, classify_curve, arrange_flow,
    audio_curve, apply_flow, validate_flow, fixed_finger_fits, build_activity_plan)
from score_export import save_json, sha256

# 器乐低弦分解填充：新增明确位于工作区的测试临时根，避免Windows隔离临时目录不支持音频写入。
TEST_TEMP = Path(__file__).resolve().parents[1] / 'test_outputs/instrumental_flow_test_temp'
TEST_TEMP.mkdir(parents=True, exist_ok=True)


# 器乐低弦分解填充：新增自拟开放C和弦，旋律长音／空拍与既有低音分别出现。
def music(capo=0):
    s, v = fixture()
    s['timing'] = deepcopy(v['timing'])
    # 器乐低弦分解填充：修改，保留旧夹具；实际XML需要合法段落文字。
    # s['sections'] = [{'kind': 'intro', 'start_tick': 0, 'end_tick': 1920},
    #     {'kind': 'vocal', 'start_tick': 1920, 'end_tick': 3840}]
    s['sections'] = [{'kind': 'intro', 'label': '前奏', 'start_tick': 0, 'end_tick': 1920},
        {'kind': 'vocal', 'label': '演唱', 'start_tick': 1920, 'end_tick': 3840}]
    g = arrange_guitar(s, v, 0)
    g['configuration']['capo_fret'] = capo
    g['configuration']['capo_segments'] = [{'start_tick': 0, 'end_tick': 3840, 'capo_fret': capo}]
    if capo:
        for h in s['harmony']:
            h['root_pc'] = (h['root_pc'] + capo) % 12
            h['bass_pc'] = (h['bass_pc'] + capo) % 12
            h['pitch_classes'] = [(p + capo) % 12 for p in h['pitch_classes']]
    rows = [('melody', 0, 960, 64, 1, 0, 0, 'instrumental_melody'),
        ('bass', 0, 1920, 48, 5, 3, 3, 'bass'),
        ('harmony', 0, 480, 52, 4, 2, 2, 'harmony'),
        ('normal', 1920, 2160, 64, 1, 0, 0, 'harmony')]
    g['notes'] = [dict(id=i, start_tick=a, end_tick=b, pitch_midi=p + capo, string=st, fret=f,
        finger=fi, role=r, hand_position=1, velocity=90 if r == 'instrumental_melody' else 70,
        source='synthetic', chord_id='h0' if a < 1920 else 'h1') for i, a, b, p, st, f, fi, r in rows]
    g['attack_events'] = [dict(start_tick=0, note_ids=['melody', 'bass', 'harmony']),
        dict(start_tick=1920, note_ids=['normal'])]
    g['hand_positions'] = [{'tick': 0, 'position': 1}]
    g['adjustments'] = []
    return s, v, g


def plan(s, intervals=None):
    return {'sections': [s['sections'][0]], 'activity': intervals or [
        {'start_seconds': 0., 'end_seconds': 20., 'state': 'active'}]}


class InstrumentalFlowTests(unittest.TestCase):
    # 器乐低弦分解填充：新增长旋律期间也有低弦攻击，固定骨干和正常唱段全部字段。
    def test_long_melody_has_lower_activity_without_shortening(self):
        s, v, g = music(); before = deepcopy((s, v, g))
        a, r = arrange_flow(s, v, g, plan(s))
        self.assertEqual((s, v, g), before)
        self.assertEqual(next(n for n in a['notes'] if n['id'] == 'melody'), g['notes'][0])
        self.assertEqual(next(n for n in a['notes'] if n['id'] == 'normal'), g['notes'][-1])
        self.assertTrue(any(n.get('instrumental_flow_fill') and 0 < n['start_tick'] < 960 for n in a['notes']))
        self.assertGreater(r['added_notes'], 0)
        self.assertTrue(validate_playability(a, SongClock(v))['valid'])

    def test_melody_rest_does_not_stop_lower_arpeggio(self):
        s, v, g = music(); a, _ = arrange_flow(s, v, g, plan(s))
        self.assertTrue(any(n.get('instrumental_flow_fill') and 960 <= n['start_tick'] < 1920 for n in a['notes']))

    def test_true_source_rest_has_no_added_attack_or_hold(self):
        s, v, g = music(); clock = SongClock(v)
        activity = [{'start_seconds': 0., 'end_seconds': clock.seconds(720), 'state': 'active'},
            {'start_seconds': clock.seconds(720), 'end_seconds': clock.seconds(1200), 'state': 'source_rest'},
            {'start_seconds': clock.seconds(1200), 'end_seconds': 20., 'state': 'active'}]
        a, _ = arrange_flow(s, v, g, plan(s, activity))
        added = [n for n in a['notes'] if n.get('instrumental_flow_fill')]
        self.assertFalse(any(n['start_tick'] < 1200 and n['end_tick'] > 720 for n in added))

    def test_unknown_and_terminal_ringout_are_not_filled(self):
        for state in ('uncertain', 'terminal_ringout', 'source_rest'):
            s, v, g = music(); a, r = arrange_flow(s, v, g, plan(s, [{'start_seconds': 0., 'end_seconds': 20., 'state': state}]))
            self.assertEqual(a['notes'], sorted(g['notes'], key=lambda n: (n['start_tick'], n['id'])))
            self.assertEqual(r['added_notes'], 0)

    def test_only_lower_strings_and_chord_tones_on_regular_grid(self):
        s, v, g = music(); a, _ = arrange_flow(s, v, g, plan(s))
        chord = s['harmony'][0]
        for n in a['notes']:
            if not n.get('instrumental_flow_fill'):
                continue
            self.assertIn(n['string'], (4, 5, 6)); self.assertLessEqual(n['fret'], 12)
            self.assertIn(n['pitch_midi'] % 12, chord['pitch_classes'])
            self.assertEqual(n['start_tick'] % 240, 0)
            self.assertIn(n['end_tick'] - n['start_tick'], (120, 240))

    def test_same_pitch_retrigger_releases_only_accompaniment(self):
        s, v, g = music(); a, r = arrange_flow(s, v, g, plan(s))
        self.assertTrue(r['release_adjustments'])
        for change in r['release_adjustments']:
            self.assertNotEqual(change['note_id'], 'melody')
            self.assertTrue(any(n.get('instrumental_flow_fill') and n['start_tick'] == change['end_tick'] and
                n['string'] == change['string'] and n['pitch_midi'] == change['pitch_midi'] for n in a['notes']))
        self.assertTrue(validate_playability(a, SongClock(v))['valid'])

    def test_held_melody_string_is_never_taken(self):
        s, v, g = music()
        g['notes'][0].update(pitch_midi=52, string=4, fret=2, finger=2)
        g['notes'] = [n for n in g['notes'] if n['id'] != 'harmony']
        a, _ = arrange_flow(s, v, g, plan(s))
        self.assertFalse(any(n.get('instrumental_flow_fill') and n['string'] == 4 and n['start_tick'] < 960 for n in a['notes']))

    def test_sustained_finger_cannot_be_borrowed(self):
        held = [{'string': 1, 'fret': 3, 'finger': 2}]
        self.assertFalse(fixed_finger_fits(held, {'string': 4, 'fret': 2, 'finger': 2}))
        self.assertTrue(fixed_finger_fits(held, {'string': 4, 'fret': 2, 'finger': 1}))

    def test_capo_transposition_keeps_same_frets_and_patterns(self):
        outputs = []
        for capo in (0, 1, 3):
            s, v, g = music(capo); a, _ = arrange_flow(s, v, g, plan(s))
            outputs.append([(n['start_tick'], n['string'], n['fret'], n['pitch_midi'] - capo)
                for n in a['notes'] if n.get('instrumental_flow_fill')])
        self.assertEqual(outputs[0], outputs[1]); self.assertEqual(outputs[0], outputs[2])

    def test_compound_meter_uses_eighth_grouping(self):
        self.assertEqual(pulse_and_step([6, 8]), (720, 240))
        self.assertEqual(pulse_and_step([9, 8]), (720, 240))
        self.assertEqual(pulse_and_step([3, 4]), (480, 240))
        s, v, g = music(); v['timing']['meter'] = [6, 8]; s['timing']['meter'] = [6, 8]
        a, _ = arrange_flow(s, v, g, plan(s))
        self.assertTrue(all(n['start_tick'] % 240 == 0 for n in a['notes'] if n.get('instrumental_flow_fill')))

    def test_uncertain_chord_is_not_silence_or_invented_fill(self):
        s, v, g = music(); s['harmony'][0]['name'] = 'N.C.'
        _, r = arrange_flow(s, v, g, plan(s))
        self.assertEqual(r['added_notes'], 0)
        self.assertGreater(r['decision_counts']['uncertain_harmony'], 0)

    def test_existing_attack_is_not_duplicated_each_halfbeat(self):
        s, v, g = music()
        g['notes'].append({**g['notes'][0], 'id': 'short_lead', 'start_tick': 240, 'end_tick': 480})
        a, _ = arrange_flow(s, v, g, plan(s))
        self.assertFalse(any(n.get('instrumental_flow_fill') and n['start_tick'] == 240 for n in a['notes']))

    def test_right_hand_beam_uses_attack_grid_while_melody_holds(self):
        s, v, g = music(); a, _ = arrange_flow(s, v, g, plan(s))
        events = arrangement_rhythm_events(a, [4, 4], 1920)
        self.assertEqual(next(e for e in events if e['tick'] == 0)['duration'], 240)
        self.assertEqual(next(n for n in a['notes'] if n['id'] == 'melody')['end_tick'], 960)

    def test_actual_xml_and_midi_keep_all_final_notes_and_melody_duration(self):
        s, v, g = music(); a, _ = arrange_flow(s, v, g, plan(s))
        root, _ = build_musicxml(s, v, a); notes, check = parse_musicxml_notes(root)
        self.assertTrue(check['valid'])
        self.assertEqual({i: (n['start_tick'], n['end_tick'], n['pitch_midi']) for i, n in notes.items()},
            {n['id']: (n['start_tick'], n['end_tick'], n['pitch_midi']) for n in a['notes']})
        # 器乐低弦分解填充：修改，旧默认临时目录保留；清理对象固定在已解析的工作区测试根下。
        # with tempfile.TemporaryDirectory() as tmp:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP.resolve()) as tmp:
            path = Path(tmp) / 'actual.mid'; write_midi(path, a, v)
            self.assertTrue(validate_midi(path, a, v)['valid'])

    # 器乐低弦分解填充：新增独立声学夹具，真实静音与无重起的持续音分别检查。
    def test_sustain_with_no_new_onsets_is_active(self):
        s, v, _ = music(); times = np.arange(100) * .04
        curve = {'times': times, 'rms': np.ones(100) * .1, 'flux': np.zeros(100), 'flatness': np.ones(100) * .05}
        states, _ = classify_curve(curve, s['sections'], SongClock(v))
        self.assertTrue(all(x == 'active' for x in states))

    def test_silent_gap_remains_silent_even_with_leaky_stem(self):
        s, v, _ = music(); times = np.arange(100) * .04
        rms = np.ones(100) * .1; rms[30:45] = 0
        curve = {'times': times, 'rms': rms, 'flux': np.zeros(100), 'flatness': np.ones(100) * .05}
        states, _ = classify_curve(curve, s['sections'], SongClock(v), [
            {'times': times, 'rms': np.ones(100)}])
        self.assertTrue(all(x == 'source_rest' for x in states[30:45]))

    def test_decaying_terminal_sustain_stops_new_attacks(self):
        s, v, _ = music(); s['sections'][0]['kind'] = 'outro'
        times = np.arange(100) * .04; rms = np.exp(-times * 1.8) * .1
        flux = np.zeros(100); flux[1] = 10
        curve = {'times': times, 'rms': rms, 'flux': flux, 'flatness': np.ones(100) * .04}
        states, _ = classify_curve(curve, s['sections'], SongClock(v))
        # 器乐低弦分解填充：修改，旧断言落在尾奏之后；核查1.2秒的真实尾奏范围。
        # self.assertIn('terminal_ringout', states); self.assertNotEqual(states[60], 'active')
        self.assertIn('terminal_ringout', states); self.assertNotEqual(states[30], 'active')

    def test_audio_time_offset_is_respected(self):
        # 器乐低弦分解填充：修改，旧默认临时目录保留，限制在工作区内。
        # with tempfile.TemporaryDirectory() as tmp:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP.resolve()) as tmp:
            path = Path(tmp) / 'tone.wav'; rate = 22050
            t = np.arange(rate) / rate; sf.write(path, .1 * np.sin(2 * np.pi * 220 * t), rate)
            curve = audio_curve({'path': str(path), 'offset_seconds': 2.})
            self.assertGreaterEqual(curve['times'][0], 2.)
            self.assertAlmostEqual(curve['end_seconds'], 3., places=3)

    def test_missing_full_accompaniment_is_rejected(self):
        s, v, _ = music(); s['input_binding'] = {'sources': {}}
        # 器乐低弦分解填充：修改，旧默认临时目录保留，限制在工作区内。
        # with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP.resolve()) as tmp, self.assertRaises(ValueError):
            build_activity_plan(s, v, tmp)

    # 器乐低弦分解填充：新增真实音频／源文件绑定及篡改反例，不能只比较自填字段。
    def test_bound_flow_replay_and_tamper_rejection(self):
        s, v, g = music()
        # 器乐低弦分解填充：修改，旧默认临时目录保留，限制在工作区内。
        # with tempfile.TemporaryDirectory() as tmp:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP.resolve()) as tmp:
            tmp = Path(tmp); path = tmp / 'tone.wav'; rate = 11025
            t = np.arange(rate * 5) / rate; sf.write(path, .1 * np.sin(2 * np.pi * 130.81 * t), rate)
            s['input_binding'] = {'sources': {'accompaniment': {'path': str(path), 'sha256': sha256(path), 'offset_seconds': 0.}}}
            upstream = tmp / 'parent.json'; save_json(upstream, {'shared_analysis': s, 'accepted_vocal_project': v, 'arrangements': {'guitar': g}})
            a, _ = apply_flow(s, v, g, upstream, tmp / 'features')
            self.assertTrue(validate_flow(s, v, a, replay=True)['valid'])
            b = deepcopy(a); b['notes'][0]['pitch_midi'] += 12
            self.assertFalse(validate_flow(s, v, b)['valid'])
            b = deepcopy(a); b['attack_events'][0]['right_hand_duration_ticks'] = 60
            self.assertFalse(validate_flow(s, v, b)['valid'])
            b = deepcopy(a); b['hand_positions'][0]['position'] += 1
            self.assertFalse(validate_flow(s, v, b)['valid'])
            b = deepcopy(a); b['instrumental_flow']['report']['release_adjustments'] = []
            self.assertFalse(validate_flow(s, v, b)['valid'])
            again, _ = apply_flow(s, v, a, upstream, tmp / 'features')
            self.assertEqual(a, again)
            path.write_bytes(path.read_bytes() + b'changed')
            self.assertFalse(validate_flow(s, v, a)['valid'])


if __name__ == '__main__':
    unittest.main()
