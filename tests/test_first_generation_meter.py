"""首次生成自动拍轴交接：原声正反例、局部拍号及真实生成入口衔接。"""
# 首次生成自动拍轴交接：新增功能与来源反例，不以真实歌曲候选当真值。
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from test_source_meter_hierarchy import fixture
from test_score_export import project_from, note
from first_generation_meter import decide_first_generation, cycle_counterfactual, evidence_tracks, POLICY
from first_generation_source import (prepare_first_source, load_first_decision, project_first_voice,
                                     UnresolvedFirstSource, read_bound_evidence)
from score_export import sha256, save_json


def source_case(folder, silent_tail=0.):
    # 首次生成自动拍轴交接：新增任意合成源与匿名包；音源只供摘要绑定，不运行真实模型或识别。
    folder = Path(folder)
    meta, arrays, _ = fixture(duration=96., silent_tail=silent_tail)
    # 首次生成自动拍轴交接：修改来源夹具为真实全长WAV，实际时长也必须被验收，不能只验摘要。
    # audio = folder / 'original-source.bin'
    # audio.write_bytes(b'independent synthetic original source')
    import soundfile as sf
    audio = folder / 'original-source.wav'
    sf.write(audio, np.zeros(96 * 200, dtype=np.float32), 200, subtype='PCM_16')
    source = {'path': str(audio), 'sha256': sha256(audio)}
    for track in meta['tracks']:
        track['source_sha256'] = source['sha256']
    meta['mix_sha256'] = source['sha256']
    archive = folder / 'evidence.npz'
    np.savez_compressed(archive, **arrays)
    meta['array_sha256'] = sha256(archive)
    evidence = folder / 'evidence.json'
    save_json(evidence, meta)
    vocal = project_from([note('a', 5.1, 5.5), note('b', 5.5, 6.0, 64)], seconds=96.)
    vocal.update(lyrics={'characters': []}, audio_analysis={'duration_seconds': 96.,
                 'tempo': {'bpm': 240., 'requires_confirmation': True, 'half_double_time_ambiguity_unresolved': True}})
    vocal['timing']['knots'] = [{'quarter': 0., 'seconds': 0.}, {'quarter': 1., 'seconds': .25}]
    path = folder / 'vocal.json'
    save_json(path, vocal)
    binding = {'vocal_project': str(path), 'vocal_project_sha256': sha256(path), 'duration_seconds': 96.,
               'sources': {role: deepcopy(source) for role in ('mix', 'bass', 'accompaniment', 'drums')}}
    save_json(folder / 'binding.json', binding)
    return meta, arrays, evidence, vocal, binding


class FirstGenerationDecisionTests(unittest.TestCase):
    # 首次生成自动拍轴交接：新增整条原始候选计算正例，真快拍不会被两小节和声循环强制变慢。
    def test_clear_raw_source_produces_usable_clock_not_publication(self):
        meta, arrays, _ = fixture(duration=96.)
        before = {key: value.copy() for key, value in arrays.items()}
        result = decide_first_generation(meta, arrays)
        self.assertEqual(result['status'], 'passed', result['issues'])
        self.assertAlmostEqual(result['notation_level']['bpm'], 120.)
        self.assertTrue(result['downstream_timing_revision_allowed'])
        self.assertFalse(result['normal_publication_allowed'])
        for key in arrays:
            np.testing.assert_array_equal(arrays[key], before[key])

    # 首次生成自动拍轴交接：新增真实慢拍的第三拍也强时，不能仅因分组多解就改选快拍。
    def test_strong_third_does_not_force_fast_notation_level(self):
        meta, arrays, _ = fixture(1., duration=128., extra_model_groups=True)
        result = decide_first_generation(meta, arrays)
        self.assertEqual(result['notation_level']['status'], 'selected')
        self.assertAlmostEqual(result['notation_level']['bpm'], 60.)
        self.assertEqual(result['bar_first_beat']['status'], 'needs_review')
        self.assertFalse(result['downstream_timing_revision_allowed'])

    # 首次生成自动拍轴交接：新增安静尾窗不否定主体单位，也不能当作完整覆盖自动通过。
    def test_unobserved_tail_blocks_generation_without_discarding_unit(self):
        meta, arrays, _ = fixture(duration=128., silent_tail=32.)
        result = decide_first_generation(meta, arrays)
        self.assertEqual(result['notation_level']['status'], 'selected')
        self.assertEqual(result['coverage']['status'], 'needs_review')
        self.assertFalse(result['downstream_timing_revision_allowed'])

    # 首次生成自动拍轴交接：新增动态分组后的反证使用当前拍位，不能把旧全局模四当成来源冲突。
    def test_content_counterfactual_uses_labels_after_short_bar(self):
        meta, arrays, decoded = fixture(duration=96.)
        candidate = decoded[1]
        for index, beat in enumerate(candidate['beats']):
            if index >= 82:
                beat['beat'] = (index - 82) % 4 + 1
        for track in meta['tracks']:
            if track['role'] == 'drums':
                continue
            values = arrays[track['prefix'] + '_novelty']
            values[:] = 0.
            for beat in candidate['beats']:
                if beat['beat'] == 1:
                    values[round(beat['seconds'] * 50)] = .8
        result = cycle_counterfactual(candidate, evidence_tracks(meta, arrays), [(48., 80.)])
        self.assertTrue(result['windows'][0]['first_role_supported'])
        self.assertFalse(result['windows'][0]['third_role_supported'])

    # 首次生成自动拍轴交接：新增不降低既有数值门槛，前序策略单独版本保持。
    def test_existing_thresholds_are_retained(self):
        from source_meter_hierarchy import POLICY as old
        self.assertEqual(POLICY['selection_policy'], old)
        self.assertEqual(POLICY['maximum_unobserved_edge_seconds'], 4.)


class FirstGenerationSourceTests(unittest.TestCase):
    # 首次生成自动拍轴交接：新增不能通过裁短原声匿名时长掩盖尾段未决。
    def test_shortened_evidence_duration_cannot_hide_tail(self):
        parent = ROOT / 'test_outputs/accompaniment_runs/tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            meta, _, evidence, _, binding = source_case(folder)
            meta['duration_seconds'] -= 8.
            save_json(evidence, meta)
            with self.assertRaisesRegex(ValueError, '时长不符'):
                read_bound_evidence(evidence, binding)

    # 首次生成自动拍轴交接：新增无预填决定／匿名包时，真实准备入口自动调用原声证据准备。
    def test_no_precomputed_decision_automatically_prepares_raw_evidence(self):
        parent = ROOT / 'test_outputs/accompaniment_runs/tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            _, _, evidence, vocal, binding = source_case(folder)
            with patch('select_source_meter.prepare_evidence', return_value=evidence) as prepare:
                updated, _ = prepare_first_source(vocal, binding, Path(folder) / 'analysis/features',
                                                  feature_caches=[Path(folder) / 'read_only'], model_cache='raw-model-cache')
            prepare.assert_called_once()
            self.assertEqual(prepare.call_args.args[0], binding)
            self.assertEqual(prepare.call_args.args[2], 'raw-model-cache')
            self.assertIn('first_source_meter_correction', updated)
            self.assertNotIn('time_only_revision', updated)

    # 首次生成自动拍轴交接：新增真实来源准备和重放，不依赖人工确认或旧正确拍轴。
    def test_first_source_projects_only_time_and_replays(self):
        parent = ROOT / 'test_outputs/accompaniment_runs/tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            _, _, evidence, vocal, binding = source_case(folder)
            with patch('source_meter_project.infer_source_clock', side_effect=AssertionError('不得猜回旧拍轴')), \
                 patch('source_meter_project.prepare_quality_vocal', side_effect=AssertionError('不得整曲重建词音')):
                from source_meter_project import prepare_source_vocal
                updated, audit = prepare_source_vocal(vocal, binding, Path(folder) / 'analysis/features',
                                                       quality=True, first_generation=True, evidence=evidence)
            self.assertIn('first_source_meter_correction', updated)
            self.assertNotEqual(updated['timing']['knots'], vocal['timing']['knots'])
            for a, b in zip(vocal['quantized_notes'], updated['quantized_notes']):
                for key in ('id', 'pitch_midi', 'start_seconds', 'end_seconds', 'lyric_index'):
                    self.assertEqual(a.get(key), b.get(key))
            from accompaniment_rebar import validate_vocal_snapshot
            self.assertTrue(validate_vocal_snapshot(updated, binding))
            damaged = deepcopy(updated)
            damaged['quantized_notes'][0]['pitch_midi'] += 1
            self.assertFalse(validate_vocal_snapshot(damaged, binding))
            decision = load_first_decision(audit['decision_path'], binding)
            self.assertFalse(decision['normal_publication_allowed'])

    # 首次生成自动拍轴交接：新增未决从真实准备抛出并保存证据，不能产生验收后人声或调用投影。
    def test_unresolved_source_is_saved_and_stops_before_projection(self):
        parent = ROOT / 'test_outputs/accompaniment_runs/tests'
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            _, _, evidence, vocal, binding = source_case(folder, silent_tail=32.)
            with patch('first_generation_source.project_first_voice', side_effect=AssertionError('不得投影未决拍轴')):
                with self.assertRaises(UnresolvedFirstSource) as captured:
                    prepare_first_source(vocal, binding, Path(folder) / 'analysis/features', evidence)
            self.assertTrue(Path(captured.exception.decision_path).is_file())
            self.assertFalse((Path(captured.exception.decision_path).parent / 'accepted_vocal_project.json').exists())

    # 首次生成自动拍轴交接：新增首次公共生成入口确实先选拍／来源重放，再到共享和声；不只测独立函数。
    def test_raw_binding_generation_reaches_harmony_with_verified_clock(self):
        from generate_accompaniment import generate
        parent = ROOT / 'test_outputs/accompaniment_runs/tests'
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            _, _, evidence, vocal, binding = source_case(folder)
            root = Path(folder)
            args = SimpleNamespace(edited_project=None, rearrange=False, output=root / 'new', report=None,
                                   binding=root / 'binding.json', analysis_dir=root / 'analysis',
                                   shared_analysis=None, six_sources=False, capo=None, source_meter_evidence=evidence)
            class ReachedHarmony(Exception):
                pass
            def analyze(actual_binding, actual_vocal, cache, **kwargs):
                self.assertIn('first_source_meter_correction', actual_vocal)
                self.assertNotEqual(actual_vocal['timing']['knots'], vocal['timing']['knots'])
                from source_meter_entry import require_calibrated_source
                self.assertEqual(require_calibrated_source(actual_vocal, actual_binding)['status'],
                                 'source_verified_first_generation_clock_retained')
                raise ReachedHarmony()
            with patch('generate_accompaniment.validate_source_pitch_project', return_value=True), \
                 patch('generate_accompaniment.analyze', side_effect=analyze), \
                 patch('source_meter_project.infer_source_clock', side_effect=AssertionError('旧轴不应触发')):
                with self.assertRaises(ReachedHarmony):
                    generate(args)

    # 首次生成自动拍轴交接：新增篡改匿名缓存不得沿用来源决定。
    def test_changed_evidence_and_forged_pass_are_rejected(self):
        parent = ROOT / 'test_outputs/accompaniment_runs/tests'
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            _, _, evidence, vocal, binding = source_case(folder)
            updated, audit = prepare_first_source(vocal, binding, Path(folder) / 'analysis/features', evidence)
            path = Path(audit['decision_path'])
            bound = json.loads(path.read_text(encoding='utf-8'))
            bound['result']['selected_candidate_index'] = -1
            save_json(path, bound)
            with self.assertRaisesRegex(ValueError, '无法由原声'):
                load_first_decision(path, binding)
            evidence.with_suffix('.npz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '已变'):
                load_first_decision(path, binding)

    # 首次生成自动拍轴交接：新增旧工程不能通过首次输入参数要求隐式重选拍。
    def test_old_project_rejects_fresh_source_arguments(self):
        from generate_accompaniment import generate
        with self.assertRaisesRegex(ValueError, '不能覆盖已有工程'):
            generate(SimpleNamespace(edited_project='old.json', source_meter_evidence='raw.json'))


if __name__ == '__main__':
    unittest.main()
