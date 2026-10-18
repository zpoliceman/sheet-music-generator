"""最小拍轴与词音伴奏修复：完整音值、词音冲突、可变小节与导出反例。"""
# 最小拍轴与词音伴奏修复：新增保护已确认音乐的有意义反例，不使用曲名／手填原曲答案。
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from score_export import key_definition, TempoMap
from source_timing_revision import refine_word_heads, project_voice, project_arrangements, build_revision, regularize_notation
from export_timing_revision import build_xml, inspect_xml, write_meter_events


def fixture():
    # 最小拍轴与词音伴奏修复：新增长音跨四拍／两拍小节和带空白倚音的合成谱。
    characters = [{'index': i, 'text': chr(65 + i), 'line_index': 0, 'start_seconds': a,
                   'end_seconds': b, 'phonemes': []} for i, (a, b) in enumerate(((.5, 7.3), (8.25, 9.)))]
    notes = [{'id': 'long', 'start_seconds': .5, 'end_seconds': 7.3, 'pitch_midi': 60, 'lyric_index': 0, 'grace': False},
             {'id': 'grace', 'start_seconds': 8., 'end_seconds': 8.1, 'pitch_midi': 61, 'lyric_index': None, 'grace': True},
             {'id': 'last', 'start_seconds': 8.25, 'end_seconds': 9., 'pitch_midi': 62, 'lyric_index': 1, 'grace': False}]
    for note in notes:
        note.update(start_tick=round(note['start_seconds'] * 480), end_tick=round(note['end_seconds'] * 480))
    voice = {'title': '合成材料', 'inputs': {'notes_path': 'synthetic'}, 'lyrics': {'characters': characters},
             'timing': {'knots': [{'quarter': 0., 'seconds': 0.}, {'quarter': 12., 'seconds': 12.}],
                        'meter': [4, 4], 'score_start_quarter': 0., 'steady_tempo_bpm': 60.},
             'notation': {'key': key_definition('C:major'), 'key_segments': [], 'jianpu_reference_midi': 60},
             'statistics': {'bar_ticks': 1920, 'total_ticks': 5760, 'measure_count': 3},
             'quantized_notes': notes,
             'events': [{'id': n['id'], 'piece_id': n['id'], 'pitch_midi': n['pitch_midi'], 'grace': n['grace'],
                         'lyric_index': n['lyric_index'], 'start_tick': n['start_tick'], 'duration_ticks': n['end_tick'] - n['start_tick'],
                         'type': 'quarter', 'dots': 0, 'ties': [], 'measure': 1, 'offset_ticks': n['start_tick']}
                        for n in notes]}
    clock = {'knots': [{'quarter': float(i), 'seconds': float(i)} for i in range(11)], 'source_duration_seconds': 12.,
             'measure_timeline': [{'number': i + 1, 'start_tick': a, 'end_tick': b, 'meter': meter, 'pickup': False,
                                  'start_seconds': a / 480, 'end_seconds': b / 480}
                                 for i, (a, b, meter) in enumerate(((0, 1920, [4, 4]), (1920, 2880, [2, 4]), (2880, 4800, [4, 4])))]}
    return voice, clock


class TimeProjectionTests(unittest.TestCase):
    def accompaniment(self, fret=0):
        # 最小拍轴与词音伴奏修复：新增两段会竞争同弦拍点的完整循环，不靠删音解决。
        voice, candidate = fixture()
        voice['timing']['knots'] = [{'quarter': 0., 'seconds': .65}, {'quarter': 12., 'seconds': 6.65}]
        def note(identity, tick, origin):
            return {'id': identity, 'start_tick': tick, 'end_tick': tick + 200, 'pitch_midi': 55 + fret,
                    'string': 3, 'fret': fret, 'velocity': 70, 'role': 'harmony',
                    'onset_origin': 'arranged_common_pattern', 'pattern_cycle_origin_tick': origin}
        project = {'accepted_vocal_project': voice, 'shared_analysis': {
                    'harmony': [{'id': 'h', 'name': 'C', 'start_tick': 0, 'end_tick': 5760}],
                    'sections': [{'kind': 'vocal', 'start_tick': 0, 'end_tick': 5760}]},
                   # 最小拍轴与词音伴奏修复：新增合成谱的明确零夹配置，与实际弦品校验使用同一标准调弦。
                   # 'arrangements': {'guitar': {'instrument': 'guitar', 'configuration': {'capo_segments': []},
                   'arrangements': {'guitar': {'instrument': 'guitar', 'configuration': {'capo_segments': [], 'capo_fret': 0},
                                             'notes': [note('first', 1200, 0), note('second', 1680, 1440)]}}}
        revised = project_voice(fixture()[0], candidate, fixture()[0]['quantized_notes'])
        return project, revised

    def test_cycle_collision_refines_whole_origins_and_keeps_both_notes(self):
        old, revised = self.accompaniment()
        shared, arrangements, audit = project_arrangements(old, revised, {})
        notes = arrangements['guitar']['notes']
        self.assertEqual([(n['id'], n['pitch_midi']) for n in notes], [('first', 55), ('second', 55)])
        self.assertLess(notes[0]['start_tick'], notes[1]['start_tick'])
        self.assertTrue(any(n['time_only_pattern_cycle']['cycle_anchor_grid_ticks'] < 480 for n in notes))
        self.assertEqual(shared['harmony'][0]['name'], 'C')
        self.assertEqual(old['arrangements']['guitar']['notes'][0]['start_tick'], 1200)

    def test_high_fret_never_silently_relaxes_to_twenty(self):
        old, revised = self.accompaniment(13)
        with self.assertRaisesRegex(ValueError, '不能放宽限制'):
            project_arrangements(old, revised, {})

    def test_long_note_pitch_identity_and_complete_tail_survive_short_bar(self):
        old, clock = fixture()
        voice = project_voice(old, clock, old['quantized_notes'])
        note = voice['quantized_notes'][0]
        self.assertEqual((note['id'], note['pitch_midi'], note['end_seconds']), ('long', 60, 7.3))
        # 最小拍轴与词音伴奏修复：修改完整尾端测试读取真实播放，原读取记谱式保留；正文规整允许小幅音值约化，实际发声不裁。
        # actual_end = TempoMap(clock['knots']).quarters_to_seconds(note['end_tick'] / 480)
        actual_end = TempoMap(clock['knots']).quarters_to_seconds(note['playback_end_tick'] / 480)
        self.assertLess(abs(actual_end - 7.3), .032)
        parts = [e for e in voice['events'] if e.get('piece_id') == 'long']
        self.assertEqual({e['measure'] for e in parts}, {1, 2, 3})
        # 最小拍轴与词音伴奏修复：修改逐tick镜像断言为长音保护反例；不能再将一秒长音裁成零点几秒。
        # self.assertAlmostEqual(sum(e['duration_ticks'] for e in parts) / 480, 6.8125)
        self.assertGreaterEqual(sum(e['duration_ticks'] for e in parts) / 480, 6.8 * .9)

    def test_audio_origin_does_not_depend_on_old_whole_music_rebuild(self):
        from accompaniment_analysis import SongClock
        voice, clock = fixture()
        clock['knots'] = [{'quarter': row['quarter'], 'seconds': row['seconds'] + 12.} for row in clock['knots']]
        voice['quantized_notes'] = [{**n, 'start_seconds': n['start_seconds'] + 12., 'end_seconds': n['end_seconds'] + 12.}
                                    for n in voice['quantized_notes']]
        revised = project_voice(voice, clock, voice['quantized_notes'])
        self.assertNotIn('source_meter_rebuild_correction', revised)
        self.assertEqual(SongClock(revised).seconds(0), 12.)
        self.assertEqual(SongClock(revised).audio_origin_seconds, 0.)

    def test_rest_before_grace_is_counted_once_in_actual_xml(self):
        old, clock = fixture()
        voice = project_voice(old, clock, old['quantized_notes'])
        root = build_xml({'accepted_vocal_project': voice})
        check = inspect_xml(root, clock['measure_timeline'])
        self.assertTrue(check['valid'], check)
        self.assertEqual([r['actual_ticks'] for r in check['measure_durations']], [1920, 960, 1920])

    def test_xml_keeps_meter_changes_and_does_not_repeat_clef_every_bar(self):
        voice, clock = fixture()
        revised = project_voice(voice, clock, voice['quantized_notes'])
        root = build_xml({'accepted_vocal_project': revised})
        meters = [(int(node.findtext('beats')), int(node.findtext('beat-type')))
                  for node in root.findall('part/measure/attributes/time')]
        self.assertEqual(meters, [(4, 4), (2, 4), (4, 4)])
        self.assertEqual(len(root.findall('part/measure/attributes/clef')), 1)
        self.assertEqual(len(root.findall('part/measure/barline')), 1)
        self.assertGreaterEqual(len(root.findall('part/measure/direction/sound')), 3)

    def test_changed_candidate_cannot_reuse_passed_assessment(self):
        voice, candidate = fixture()
        assessment = {'status': 'passed', 'valid': True, 'issues': [], 'downstream_timing_revision_allowed': True,
                      'candidate_sha256': 'another-candidate', 'mix_sha256': 'source'}
        with self.assertRaisesRegex(ValueError, '实际输入不一致'):
            build_revision({'accepted_vocal_project': voice}, candidate, assessment,
                           {'sources': {'mix': {'sha256': 'source'}}}, None, None)

    def test_midi_really_contains_short_meter_and_return(self):
        import mido
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'score.mid'
            midi = mido.MidiFile()
            midi.tracks.append(mido.MidiTrack([mido.MetaMessage('end_of_track', time=4800)]))
            midi.save(str(path))
            events = write_meter_events(path, fixture()[1]['measure_timeline'])
            self.assertEqual(events, [(0, 4, 4), (1920, 2, 4), (2880, 4, 4)])
            self.assertEqual(sum(m.time for m in mido.MidiFile(str(path)).tracks[0]), 4800)


class WordHeadTests(unittest.TestCase):
    def articulation(self, same_line=True):
        # 最小拍轴与词音伴奏修复：新增“清辅音间隙”和“真正换气”反例，记谱连贯不得填造实际发声。
        mapping = TempoMap([{'quarter': 0., 'seconds': 0.}, {'quarter': 5., 'seconds': 5.}])
        notes = [{'id': 'a', 'pitch_midi': 60, 'start_seconds': 0., 'end_seconds': 1., 'lyric_index': 0,
                  'playback_start_tick': 0, 'playback_end_tick': 480},
                 {'id': 'b', 'pitch_midi': 62, 'start_seconds': 1.25, 'end_seconds': 2., 'lyric_index': 1,
                  'playback_start_tick': 600, 'playback_end_tick': 960,
                  'time_only_head_correction': {'before_start_seconds': 1.02}}]
        chars = [{'index': 0, 'line_index': 0}, {'index': 1, 'line_index': 0 if same_line else 1}]
        regularize_notation(notes, mapping, chars)
        return notes

    def test_verified_initial_gap_is_not_printed_as_a_false_rest(self):
        notes = self.articulation()
        self.assertEqual(notes[0]['end_tick'], notes[1]['start_tick'])
        self.assertEqual(notes[0]['playback_end_tick'], 480)
        self.assertEqual(notes[1]['playback_start_tick'], 600)
        self.assertEqual(notes[0]['end_seconds'], 1.)

    def test_phrase_breath_is_not_filled_by_articulation_rule(self):
        notes = self.articulation(False)
        self.assertLess(notes[0]['end_tick'], notes[1]['start_tick'])
        self.assertIsNone(notes[0]['time_only_notation']['articulation_bridge'])

    def material(self, early_voiced):
        char = {'index': 0, 'text': '字', 'start_seconds': 0., 'end_seconds': .9,
                'phonemes': [{'role': 'initial', 'start_seconds': 0., 'end_seconds': .2},
                             {'role': 'nucleus', 'start_seconds': .2, 'end_seconds': .9}]}
        note = {'id': 'protected', 'pitch_midi': 60, 'start_seconds': 0., 'end_seconds': 1., 'lyric_index': 0}
        times = np.arange(0, 1., .005)
        values = np.full(len(times), 60.)
        if not early_voiced:
            values[times < .2] = np.nan
        acoustic = SimpleNamespace(times=times, midi=values)
        verifier = lambda core: {'yin_agreement': 1., 'vocal_dbfs': -20., 'foreground_ratio_db': 12.}
        return {'quantized_notes': [note], 'lyrics': {'characters': [char]}}, acoustic, verifier

    def test_real_early_pitch_is_not_cut_to_the_nucleus(self):
        voice, acoustic, verifier = self.material(True)
        notes, audit = refine_word_heads(voice, acoustic, verifier)
        self.assertEqual(notes, voice['quantized_notes'])
        self.assertFalse(audit['edits'])
        self.assertTrue(audit['early_pitch_protected'])

    def test_unvoiced_prefix_can_change_without_changing_pitch_or_tail(self):
        voice, acoustic, verifier = self.material(False)
        notes, audit = refine_word_heads(voice, acoustic, verifier)
        self.assertEqual(notes[0]['start_seconds'], .2)
        self.assertEqual((notes[0]['pitch_midi'], notes[0]['end_seconds'], notes[0]['id']), (60, 1., 'protected'))
        self.assertEqual(len(audit['edits']), 1)

    def test_short_word_conflict_keeps_presence_and_does_not_borrow_other_word(self):
        voice, acoustic, verifier = self.material(False)
        voice['quantized_notes'][0]['start_seconds'] = .3
        voice['lyrics']['characters'][0]['end_seconds'] = .1
        voice['lyrics']['characters'][0]['phonemes'] = []
        notes, audit = refine_word_heads(voice, acoustic, verifier)
        self.assertEqual(notes[0]['lyric_index'], 0)
        self.assertEqual(notes[0]['start_seconds'], .3)
        self.assertEqual(len(audit['unresolved']), 1)
        self.assertIn('do_not_borrow', audit['unresolved'][0]['action'])


if __name__ == '__main__':
    unittest.main()
