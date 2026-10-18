"""渴首次吉他编配：新增独立乐器选择、种子迁移、共同和声和实际导出的范围验收。"""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json
import sys
import tempfile
import unittest
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
from test_accompaniment import fixture
from test_phrase_harmony_plan import known_music, performed
from accompaniment_arrange import arrange_requested, arrange_guitar, requested_instruments, validate_playability
from accompaniment_analysis import SongClock
from beat_phase_alignment import seed_existing_music, export_phase_vocal
from phrase_harmony_arrange import apply_phrase_harmony, validate_phrase_harmony
from accompaniment_export import export_all
from generate_accompaniment import load_edited_project
from score_export import save_json, sha256


class GuitarOnlyTests(unittest.TestCase):
    # 渴首次吉他编配：新增未请求钢琴不可执行其编配器的独立反例，而吉他实际音序必须与旧编配一致。
    def test_guitar_only_avoids_unrequested_piano_and_retains_music(self):
        shared, vocal = fixture(); shared['input_binding']['requested_instruments'] = ['guitar']
        expected = arrange_guitar(shared, vocal, 0)
        with patch('accompaniment_arrange.arrange_piano', side_effect=AssertionError('不应执行钢琴')):
            actual = arrange_requested(shared, vocal, 0)
        self.assertEqual(set(actual), {'guitar'})
        self.assertEqual(actual['guitar'], expected)
        self.assertTrue(validate_playability(actual['guitar'], SongClock(vocal))['valid'])

    # 渴首次吉他编配：新增历史未声明选择仍生成两乐器，避免新单乐器入口改变既有默认范围。
    def test_legacy_default_still_arranges_both(self):
        shared, vocal = fixture()
        self.assertEqual(requested_instruments(shared), ('guitar', 'piano'))
        result = arrange_requested(shared, vocal, 0)
        self.assertEqual(set(result), {'guitar', 'piano'})
        self.assertTrue(all(validate_playability(arr, SongClock(vocal))['valid'] for arr in result.values()))

    # 渴首次吉他编配：新增未知、重复、空选择拒绝，不让无效输入被误当成默认成功。
    def test_invalid_selections_rejected(self):
        shared, _ = fixture()
        for selected in ([], ['piano'], ['guitar', 'violin'], ['guitar', 'guitar'], 'guitar'):
            with self.subTest(selected=selected):
                shared['input_binding']['requested_instruments'] = selected
                with self.assertRaises(ValueError):requested_instruments(shared)

    # 渴首次吉他编配：新增实际器乐种子在同拍轴迁移后逐音保持，缺少钢琴不是丢失输入错误。
    def test_seed_migration_keeps_instrumental_guitar(self):
        shared, vocal = fixture(); shared['input_binding']['requested_instruments'] = ['guitar']
        old = arrange_requested(shared, vocal, 0); before = deepcopy(old)
        new = seed_existing_music(shared, vocal, old, shared, vocal, arrange_requested(shared, vocal, 0), source_time_sections=True)
        music = lambda arr: [(n['id'], n['start_tick'], n['end_tick'], n['pitch_midi'], n['string'], n['fret']) for n in arr['notes']]
        self.assertEqual(music(new['guitar']), music(old['guitar']))
        self.assertEqual(old, before)
        self.assertEqual(set(new), {'guitar'})

    # 渴首次吉他编配：新增自拟跨句C-Am-F-G真值，和声复用单乐器仍执行正拍低音及持续音约束。
    def test_phrase_reuse_guitar_only_preserves_known_progression(self):
        shared, vocal = known_music(); shared['input_binding']['requested_instruments'] = ['guitar']
        shared = performed(shared, vocal)
        arrangements = arrange_requested(shared, vocal, 0)
        arrangements['guitar']['source_rhythm_evidence'] = {'measures': [
            {'measure': row['measure'], 'source': 'accompaniment', 'active': True, 'rms': 1.,
             'attacks': [{'tick': n['tick'], 'strength': 1., 'pitches': n['pitches']} for n in row['attacks']]}
            for row in shared['measure_textures']]}
        # 渴首次吉他编配：修改，旧测试解包缺少派生共享分析，按真实三元返回核对。
        # result, check = apply_phrase_harmony(shared, vocal, arrangements)
        shared, result, check = apply_phrase_harmony(shared, vocal, arrangements)
        self.assertTrue(check['valid'], check['errors'])
        self.assertEqual(set(result), {'guitar'})
        self.assertTrue(validate_phrase_harmony(shared, vocal, result)['valid'])
        for phrase in shared['phrase_harmony_plan']['phrases']:
            self.assertEqual([h['root_degree_pc'] for h in phrase['progression']], [0, 9, 5, 7])

    # 渴首次吉他编配：新增真实XML/MIDI/网页导出及来源读取，导航不能引用不存在的钢琴文件。
    def test_real_guitar_export_and_reload_have_no_piano_resources(self):
        shared, vocal = fixture(); shared.update(timing=vocal['timing'], notation=vocal['notation'], harmony_windows=[])
        folder = ROOT / 'test_outputs/accompaniment_runs/tests'; folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            path = Path(temp); audio = path / 'source.wav'; source = path / 'source.json'; output = path / 'delivery'
            sf.write(audio, np.zeros(22050*4, dtype=np.float32), 22050, subtype='FLOAT'); save_json(source, vocal)
            shared['input_binding'].update(requested_instruments=['guitar'], vocal_project=str(source),
                vocal_project_sha256=sha256(source), sources={'mix': {'path': str(audio), 'sha256': sha256(audio)}})
            # 渴首次吉他编配：新增待听审拍轴状态必须在公开谱面／入口／复核页明示，不能仅藏在JSON里。
            shared['source_clock_review']={'status':'uncertain_candidate_rejected_preserve_prior_source_bound_clock'}
            arrangements = arrange_requested(shared, vocal, 0)
            result = export_all(output, shared, vocal, arrangements)
            self.assertEqual(set(result['instruments']), {'guitar'})
            export_phase_vocal(output, vocal)
            self.assertFalse((output / 'piano').exists())
            for filename in ('index.html', 'review.html', 'guitar/score.html', 'vocal/score.html'):
                text = (output / filename).read_text('utf-8')
                self.assertNotIn('piano/score.html', text); self.assertNotIn('piano/preview.wav', text)
                self.assertNotIn('piano-preview', text)
                # 渴首次吉他编配：新增独立人声页外的三个伴奏页面均须显示未决拍位提示。
                if filename!='vocal/score.html':self.assertIn('部分拍位尚待听审', text)
            project = json.loads((output / 'project.json').read_text('utf-8'))
            self.assertEqual(project['artifact_kind'], 'editable_guitar_accompaniment')
            loaded = load_edited_project(output / 'project.json')
            self.assertEqual(set(loaded[2]), {'guitar'})
            self.assertEqual(loaded[2]['guitar']['notes'], project['arrangements']['guitar']['notes'])
            # 渴首次吉他编配：新增乐器范围篡改反例，源文件与实际谱音相同也不能忽略选择不符。
            project['shared_analysis']['input_binding']['requested_instruments'] = ['guitar', 'piano']
            save_json(output / 'project.json', project)
            with self.assertRaisesRegex(ValueError, '实际乐器与绑定选择'):load_edited_project(output / 'project.json')


if __name__ == '__main__':
    unittest.main(verbosity=2)
