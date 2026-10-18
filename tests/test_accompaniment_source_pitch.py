"""跨歌曲和弦复用与器乐准备：源调、上游绑定与提前换把的独立音乐反例。"""
# 跨歌曲和弦复用与器乐准备：新增已知移调音乐，不使用任何样曲名称或参考答案。
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from test_accompaniment import fixture
from test_instrumental_regular_rhythm import music_fixture
from accompaniment_source_pitch import restore_source_pitch, validate_source_pitch_project
from score_export import key_definition, save_json, sha256
from instrumental_regular_rhythm import regularize_instrumentals
from guitar_exact_positions import refinger_exact_positions
from guitar_grip_policy import grip_position_path
from accompaniment_arrange import TUNING


# 跨歌曲和弦复用与器乐准备：新增明确源调和声明移调，原音高证据不随目标稿改变。
def shifted_project(source='Ab:major', target='G:major', shift=-1):
    _, vocal = fixture()
    vocal['notation'].update(source_key=key_definition(source), key=key_definition(target),
                             target_key=target, transpose_semitones=shift, jianpu_reference_midi=55)
    for layer in ('quantized_notes', 'events'):
        for note in vocal[layer]:
            if note.get('pitch_midi') is not None:
                note['source_pitch_midi'] = note['pitch_midi']-shift
    return vocal


class SourcePitchTests(unittest.TestCase):
    def test_reverse_declared_transposition_preserves_source_fields_and_rhythm(self):
        original = shifted_project(); before = deepcopy(original)
        out = restore_source_pitch(original, ROOT/'unused.json', 'fixture_hash')
        self.assertEqual(original, before)
        self.assertEqual(out['notation']['key']['label'], 'Ab:major')
        self.assertEqual(out['notation']['transpose_semitones'], 0)
        self.assertEqual(out['notation']['jianpu_reference_midi'], 56)
        for field in ('lyrics', 'timing', 'statistics', 'tempo_events'):
            self.assertEqual(out[field], original[field])
        for layer in ('quantized_notes', 'events'):
            undo = deepcopy(out[layer])
            for n in undo:
                if n.get('pitch_midi') is not None: n['pitch_midi'] -= 1
            self.assertEqual(undo, original[layer])

    def test_positive_shift_is_reversed_without_guessing_source_pitch(self):
        original = shifted_project('Db:major', 'E:major', 3)
        result = restore_source_pitch(original, ROOT/'unused.json', 'fixture_hash')
        self.assertEqual(result['quantized_notes'][0]['pitch_midi'], original['quantized_notes'][0]['pitch_midi']-3)
        self.assertEqual(result['notation']['key']['label'], 'Db:major')

    def test_key_segments_keep_local_modulation_including_minor(self):
        original = shifted_project('Bb:minor', 'A:minor', -1)
        original['notation']['key_segments'] = [
            {'start_tick': 0, 'key': key_definition('A:minor')},
            {'start_tick': 1920, 'key': key_definition('F:minor')}]
        result = restore_source_pitch(original, ROOT/'unused.json', 'fixture_hash')
        self.assertEqual([s['key']['tonic_pc'] for s in result['notation']['key_segments']], [10, 6])
        self.assertEqual([s['start_tick'] for s in result['notation']['key_segments']], [0, 1920])
        self.assertTrue(all(s['key']['mode'] == 'minor' for s in result['notation']['key_segments']))

    def test_zero_shift_does_not_change_notes(self):
        original = shifted_project('C:major', 'C:major', 0)
        result = restore_source_pitch(original, ROOT/'unused.json', 'fixture_hash')
        self.assertEqual(result['quantized_notes'], original['quantized_notes'])
        self.assertEqual(result['events'], original['events'])

    def test_inconsistent_key_or_noninteger_shift_is_rejected(self):
        original = shifted_project(); original['notation']['source_key'] = key_definition('C:major')
        with self.assertRaises(ValueError): restore_source_pitch(original, ROOT/'unused.json', 'fixture_hash')
        original = shifted_project(); original['notation']['transpose_semitones'] = -.5
        with self.assertRaises(ValueError): restore_source_pitch(original, ROOT/'unused.json', 'fixture_hash')

    def test_restore_must_precede_clock_derivation(self):
        original = shifted_project(); original['local_clock_correction'] = {'version': 1}
        with self.assertRaises(ValueError): restore_source_pitch(original, ROOT/'unused.json', 'fixture_hash')

    def test_source_file_and_restored_music_both_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source.json'; original = shifted_project(); save_json(source, original)
            result = restore_source_pitch(original, source, sha256(source))
            self.assertTrue(validate_source_pitch_project(result))
            tampered = deepcopy(result); tampered['quantized_notes'][0]['pitch_midi'] += 1
            self.assertFalse(validate_source_pitch_project(tampered))
            original['title'] += ' changed'; save_json(source, original)
            self.assertFalse(validate_source_pitch_project(result))

    def test_historical_plain_input_stays_supported(self):
        self.assertTrue(validate_source_pitch_project(shifted_project()))


# 跨歌曲和弦复用与器乐准备：新增低把位音已结束但准备空档不足的真实时序反例。
class InstrumentalPreparationTests(unittest.TestCase):
    def test_regular_preparation_before_freezing_resolves_previous_ended_bass(self):
        for capo in (0, 1):
            s, v, both = music_fixture(); a = both['guitar']; a['configuration']['capo_fret'] = capo
            a['notes'] = []
            for identity, begin, end, string, fret, role in (
                ('low', 0, 240, 6, 3, 'bass'), ('lead', 0, 240, 1, 3, 'instrumental_melody'),
                ('open', 240, 480, 3, 0, 'harmony'), ('high', 480, 960, 1, 17, 'instrumental_melody')):
                a['notes'].append({'id': identity, 'start_tick': begin, 'end_tick': end,
                                   'pitch_midi': TUNING[string]+capo+fret, 'string': string, 'fret': fret,
                                   'role': role, 'velocity': 80, 'chord_id': 'h0', 'finger': 1,
                                   'hand_position': max(1, fret-5)})
            a['right_hand_patterns'] = {'measures': []}; a.pop('regular_rhythm', None)
            expected = {n['id']: (n['pitch_midi'], n['role']) for n in a['notes']}
            self.assertFalse(grip_position_path({**a, 'fingering_diagrams': []}, v)['valid'])
            with self.assertRaises(ValueError): refinger_exact_positions(s, v, deepcopy(a))
            _, result, check = regularize_instrumentals(s, v, {'guitar': a})
            new = result['guitar']; refinger_exact_positions(s, v, new)
            self.assertTrue(check['valid'])
            self.assertEqual({n['id']: (n['pitch_midi'], n['role']) for n in new['notes']}, expected)
            self.assertTrue(all(n['start_tick'] % 120 == n['end_tick'] % 120 == 0 for n in new['notes']))
            self.assertLessEqual(grip_position_path({**new, 'fingering_diagrams': []}, v)['max_frets_per_second'], 24+1e-8)


if __name__ == '__main__':
    unittest.main()
