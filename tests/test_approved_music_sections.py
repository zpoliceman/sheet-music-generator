"""原声覆盖与选音归属通用修复：认可持续音保护与伪造来源拒绝。"""
# 原声覆盖与选音归属通用修复：新增任意音乐夹具，不使用极美或其它歌曲的固定答案。
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from approved_music_sections import preserve_sections, verified_base, merge, KEY
# 原声覆盖与选音归属通用修复：新增缓存之后的传递文件依赖核验，来源重放不能因缓存放松。
from approved_music_sections import check_dependencies
from score_export import save_json, sha256
from source_accompaniment_quality import validate_source_coverage


class ApprovedMusicTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'test_outputs/accompaniment_runs/tests'
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root); self.folder = Path(self.tmp.name)
        timing = {'meter': [4, 4], 'score_start_quarter': 0., 'steady_tempo_bpm': 120.,
                  'knots': [{'seconds': 0., 'quarter': 0.}, {'seconds': 1., 'quarter': 2.}]}
        vocal = {'timing': timing, 'statistics': {'total_ticks': 1920, 'bar_ticks': 1920}}
        harmony = [{'id': 'C', 'start_tick': 0, 'end_tick': 1920, 'name': 'C', 'root_pc': 0,
                    'bass_pc': 0, 'quality': '', 'pitch_classes': [0, 4, 7], 'key': {'tonic_pc': 0}}]
        def note(identity, a, b, pitch, velocity):
            return {'id': identity, 'start_tick': a, 'end_tick': b, 'pitch_midi': pitch,
                    'velocity': velocity, 'chord_id': 'C', 'string': 5, 'fret': pitch - 45,
                    'finger': 1, 'role': 'harmony'}
        self.old = {'accepted_vocal_project': vocal, 'shared_analysis': {'input_binding': {'fixture': 1}, 'harmony': harmony},
            'arrangements': {'guitar': {'instrument': 'guitar', 'configuration': {'capo_fret': 0},
            'notes': [note('body', 0, 240, 48, 70), note('held', 700, 1100, 48, 83), note('tail', 1200, 1680, 45, 64)],
            'attack_events': [{'start_tick': 700, 'chord_id': 'C'}], 'pedal': []}}}
        self.base = deepcopy(self.old)
        self.base['arrangements']['guitar']['notes'] = [note('newbody', 0, 240, 50, 75),
            note('wrongtail', 900, 1680, 57, 110)]
        self.source = self.folder / 'source.json'; save_json(self.source, self.old)
        self.review = {'version': 1, 'source_project': str(self.source), 'source_project_sha256': sha256(self.source),
                       'approved_sections': [{'start_tick': 900, 'end_tick': 1920}]}
        self.review_path = self.folder / 'review.json'; save_json(self.review_path, self.review)

    def tearDown(self):
        self.tmp.cleanup()

    def preserve(self):
        return preserve_sections(self.base['shared_analysis'], self.base['accepted_vocal_project'],
                                 self.base['arrangements'], self.review_path, self.folder)

    def test_approved_notes_and_held_prefix_keep_all_music_fields(self):
        shared, vocal, outputs = self.preserve()
        notes = outputs['guitar']['notes']
        self.assertEqual(notes[0], self.base['arrangements']['guitar']['notes'][0])
        actual = [{k: n[k] for k in ('start_tick', 'end_tick', 'pitch_midi', 'velocity', 'string', 'fret', 'finger')} for n in notes[1:]]
        expected = [{k: n[k] for k in ('start_tick', 'end_tick', 'pitch_midi', 'velocity', 'string', 'fret', 'finger')}
                    for n in self.old['arrangements']['guitar']['notes'][1:]]
        self.assertEqual(actual, expected); self.assertEqual(shared[KEY]['ranges'][0][0], 700)
        verified_base(shared, vocal, outputs)

    def test_changed_approved_pitch_rejected(self):
        shared, vocal, outputs = self.preserve(); outputs['guitar']['notes'][-1]['pitch_midi'] += 12
        with self.assertRaisesRegex(ValueError, '音乐被修改'):
            verified_base(shared, vocal, outputs)

    def test_changed_new_body_pitch_also_rejected(self):
        shared, vocal, outputs = self.preserve(); outputs['guitar']['notes'][0]['pitch_midi'] += 1
        with self.assertRaisesRegex(ValueError, '音乐被修改'):
            verified_base(shared, vocal, outputs)

    def test_replacing_current_source_ledger_is_rejected(self):
        shared, vocal, outputs = self.preserve()
        outputs['guitar']['instrumental_source_backbone'] = {'version': 999, 'source_plan_path': 'forged'}
        with self.assertRaisesRegex(ValueError, '音乐被修改'):
            verified_base(shared, vocal, outputs)

    def test_changed_review_range_rejected(self):
        shared, vocal, outputs = self.preserve(); shared[KEY]['ranges'][0][0] += 120
        with self.assertRaises(ValueError):verified_base(shared, vocal, outputs)

    def test_changed_parent_source_rejected_even_after_cache_read(self):
        shared, vocal, outputs = self.preserve(); verified_base(shared, vocal, outputs)
        altered = deepcopy(self.old); altered['arrangements']['guitar']['notes'][-1]['velocity'] += 1
        save_json(self.source, altered)
        with self.assertRaisesRegex(ValueError, '已改变'):
            verified_base(shared, vocal, outputs)

    def test_different_clock_cannot_merge_approved_segment(self):
        self.base['accepted_vocal_project']['timing']['knots'][1]['seconds'] += .1
        with self.assertRaisesRegex(ValueError, '同拍轴'):self.preserve()

    def test_different_source_cannot_merge_approved_segment(self):
        self.base['shared_analysis']['input_binding']['fixture'] = 2
        with self.assertRaisesRegex(ValueError, '同源'):self.preserve()

    def test_empty_arrangement_with_active_source_rejected(self):
        shared = {'method': {'source_coverage_quality': {'version': 1}}, 'measure_textures': [{
            'section': 'vocal', 'kind': 'arpeggio', 'source_rms': {'guitar': .04}, 'measure': 3,
            'start_tick': 3840, 'end_tick': 5760, 'attacks': [{'tick': 3840}]}]}
        vocal = {'quantized_notes': []}
        check = validate_source_coverage(shared, vocal, {'guitar': {'notes': []}})
        self.assertFalse(check['valid']); self.assertIn('empty:guitar:3', check['errors'][0])

    def test_real_sustain_spanning_bar_counts_as_source_coverage(self):
        shared = {'method': {'source_coverage_quality': {'version': 1}}, 'measure_textures': [{
            'section': 'vocal', 'kind': 'sustain', 'source_rms': {'guitar': .04}, 'measure': 3,
            'start_tick': 3840, 'end_tick': 5760, 'attacks': [], 'sustained_observation': {'tick': 3840}}]}
        check = validate_source_coverage(shared, {'quantized_notes': []},
            {'guitar': {'notes': [{'start_tick': 3600, 'end_tick': 6000}]}})
        self.assertTrue(check['valid'])

    def test_cached_parent_cannot_hide_changed_audio_dependency(self):
        source = self.folder / 'audio.bin'; source.write_bytes(b'original-audio')
        project = {'sources': {'voice': {'path': str(source), 'sha256': sha256(source)}}}
        self.assertEqual(check_dependencies([project]), 1)
        source.write_bytes(b'changed-audio')
        with self.assertRaisesRegex(ValueError, '依赖已改变'):check_dependencies([project])

    def test_transitive_project_dependency_is_checked(self):
        source = self.folder / 'audio.bin'; source.write_bytes(b'original-audio')
        parent = self.folder / 'parent.json'; save_json(parent, {'sources': [{'path': str(source), 'sha256': sha256(source)}]})
        project = {'upstream_project': str(parent), 'upstream_sha256': sha256(parent)}
        self.assertEqual(check_dependencies([project]), 2)
        source.write_bytes(b'changed-audio')
        with self.assertRaisesRegex(ValueError, '依赖已改变'):check_dependencies([project])


if __name__ == '__main__':
    unittest.main()
