"""器乐合理分句与十二品硬限制：独立音乐反例、持续音、跨夹位与真实来源重放。"""
# 器乐合理分句与十二品硬限制：新增与歌曲名称／时间无关的低音动机接高音动机反例。
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from test_guitar_instrumental_register import music
from accompaniment_analysis import SongClock
from accompaniment_arrange import validate_playability
from guitar_instrumental_register import (arrange_instrumental_register, bind_register_source,
    editable_notes, fingerprint, melodic_phrases, require_instrumental_fret_limit,
    validate_instrumental_register)
from instrumental_phrase_register import plan_phrases
from instrumental_register_upgrade import prepare_register_upgrade


def rising_motifs(capo=0, offset=120):
    shared, vocal, guitar = music(capo)
    vocal['statistics'].update(bar_ticks=1920, total_ticks=9600, measure_count=5)
    shared['statistics'] = deepcopy(vocal['statistics'])
    shared['sections'] = [{'kind': 'interlude', 'start_tick': 0, 'end_tick': 7680},
                          {'kind': 'vocal', 'start_tick': 7680, 'end_tick': 9600}]
    template = deepcopy(guitar['notes'][0])
    notes = []
    tick = offset
    for index, (pitch, duration) in enumerate(zip(
            [60, 64, 67, 65, 67, 72, 74, 79, 84],
            [960, 480, 480, 480, 480, 480, 480, 480, 960])):
        notes.append({**template, 'id': f'motif_{index}', 'start_tick': tick,
            'end_tick': tick + duration, 'pitch_midi': pitch + capo,
            'string': 1, 'fret': pitch - 64, 'role': 'instrumental_melody'})
        tick += duration
    notes += [{**template, 'id': 'root', 'start_tick': offset, 'end_tick': offset + 240,
               'pitch_midi': 50 + capo, 'string': 4, 'fret': 0, 'role': 'bass'},
              {**template, 'id': 'third', 'start_tick': offset, 'end_tick': offset + 240,
               'pitch_midi': 55 + capo, 'string': 3, 'fret': 0, 'role': 'harmony'}]
    normal = deepcopy(next(n for n in guitar['notes'] if n['id'] == 'normal'))
    normal.update(start_tick=7680, end_tick=7920)
    guitar['notes'] = sorted(notes + [normal], key=lambda n: (n['start_tick'], n['id']))
    guitar['configuration']['instrumental_register_voicing_version'] = 2
    return shared, vocal, guitar


class PhraseRegisterTests(unittest.TestCase):
    # 器乐合理分句与十二品硬限制：新增真实冲突型反例，旧一句既不能降也不能12品内保留。
    def test_rising_low_to_high_material_is_replanned_without_high_fret_fallback(self):
        shared, vocal, guitar = rising_motifs()
        original = deepcopy((shared, vocal, guitar))
        result, report = arrange_instrumental_register(shared, vocal, guitar)
        self.assertEqual((shared, vocal, guitar), original)
        self.assertEqual(report['after']['above_twelve'], 0)
        self.assertTrue(report['phrase_plan']['additional_boundaries'])
        self.assertTrue(all(attempt['maximum_fret'] <= 12 for attempt in report['attempts']))
        self.assertTrue(validate_playability(result, SongClock(vocal))['valid'])
        before, after = {n['id']: n for n in guitar['notes']}, {n['id']: n for n in result['notes']}
        self.assertEqual(set(before), set(after))
        for identity in before:
            self.assertEqual(tuple(before[identity][k] for k in ('start_tick', 'end_tick', 'role', 'velocity')),
                             tuple(after[identity][k] for k in ('start_tick', 'end_tick', 'role', 'velocity')))
            self.assertEqual(before[identity]['pitch_midi'] % 12, after[identity]['pitch_midi'] % 12)
        self.assertEqual(before['normal'], after['normal'])
        for phrase in report['phrases']:
            self.assertEqual(len({after[i]['pitch_midi'] - before[i]['pitch_midi'] for i in phrase['note_ids']}), 1)

    def test_capo_and_unseen_timing_offsets_keep_same_musical_solution(self):
        outputs = []
        for capo, offset in ((0, 120), (2, 240), (4, 360)):
            with self.subTest(capo=capo, offset=offset):
                shared, vocal, guitar = rising_motifs(capo, offset)
                result, report = arrange_instrumental_register(shared, vocal, guitar)
                self.assertEqual(report['after']['above_twelve'], 0)
                outputs.append([(n['id'], n['pitch_midi'] - capo) for n in result['notes']])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])

    def test_title_and_lyrics_do_not_choose_new_boundaries(self):
        shared, vocal, guitar = rising_motifs()
        first, a = arrange_instrumental_register(shared, vocal, guitar)
        vocal['title'] = '全新虚构曲目'
        for char in vocal['lyrics']['characters']:
            char['text'] = '词'
        second, b = arrange_instrumental_register(shared, vocal, guitar)
        self.assertEqual(first['notes'], second['notes'])
        self.assertEqual(a['phrase_plan'], b['phrase_plan'])

    def test_each_added_boundary_is_released_and_has_an_independent_motif(self):
        shared, vocal, guitar = rising_motifs()
        _, report = arrange_instrumental_register(shared, vocal, guitar)
        notes = {n['id']: n for n in guitar['notes']}
        for boundary in report['phrase_plan']['additional_boundaries']:
            self.assertIn(boundary['reason'], ('released_rest', 'released_register_handover',
                                              'released_metric_harmony_boundary'))
            phrase = next(p for p in report['phrases'] if p['id'] == boundary['phrase_id'])
            self.assertGreaterEqual(phrase['end_tick'] - phrase['start_tick'], 960)
            self.assertTrue(all(n['end_tick'] <= boundary['tick'] for n in notes.values()
                if n['role'] == 'instrumental_melody' and n['start_tick'] < boundary['tick']))

    def test_new_register_handover_does_not_introduce_a_large_octave_drop(self):
        shared, vocal, guitar = rising_motifs()
        result, report = arrange_instrumental_register(shared, vocal, guitar)
        after = {n['id']: n for n in result['notes']}
        for phrase in report['phrases']:
            if not phrase.get('register_handover_from_phrase_id'):
                continue
            previous = next(p for p in report['phrases'] if p['id'] == phrase['register_handover_from_phrase_id'])
            interval = after[phrase['note_ids'][0]]['pitch_midi'] - after[previous['note_ids'][-1]]['pitch_midi']
            self.assertLessEqual(abs(interval), phrase['register_handover_maximum_interval'])

    def test_held_melody_is_never_cut_to_make_individual_notes_fit(self):
        shared, vocal, guitar = rising_motifs()
        first = next(n for n in guitar['notes'] if n['id'] == 'motif_0')
        first['end_tick'] = max(n['end_tick'] for n in guitar['notes'] if n['role'] == 'instrumental_melody')
        with self.assertRaisesRegex(ValueError, '不会自动放宽'):
            arrange_instrumental_register(shared, vocal, guitar)

    def test_short_alternating_registers_cannot_be_folded_note_by_note(self):
        shared, vocal, guitar = rising_motifs()
        melody = [n for n in guitar['notes'] if n['role'] == 'instrumental_melody']
        for index, note in enumerate(melody):
            note.update(start_tick=120 + index * 120, end_tick=240 + index * 120,
                        pitch_midi=60 if index % 2 == 0 else 84)
        with self.assertRaisesRegex(ValueError, '不会自动放宽'):
            arrange_instrumental_register(shared, vocal, guitar)

    def test_necessary_five_to_twelve_keeps_one_valid_motif(self):
        shared, vocal, guitar = music()
        template = deepcopy(guitar['notes'][0])
        guitar['notes'] = [{**template, 'id': 'a', 'start_tick': 120, 'end_tick': 600,
                            'pitch_midi': 72, 'role': 'instrumental_melody'},
                          {**template, 'id': 'b', 'start_tick': 600, 'end_tick': 1080,
                            'pitch_midi': 84, 'role': 'instrumental_melody'},
                          {**template, 'id': 'bass', 'start_tick': 120, 'end_tick': 360,
                            'pitch_midi': 50, 'role': 'bass', 'string': 4, 'fret': 0}]
        result, report = arrange_instrumental_register(shared, vocal, guitar)
        self.assertFalse(report['phrase_plan']['additional_boundaries'])
        melody = [n for n in result['notes'] if n['role'] == 'instrumental_melody']
        self.assertEqual({n['instrumental_register_octave_shift'] for n in melody}, {-12})
        self.assertGreater(max(n['fret'] for n in melody), 4)
        self.assertLessEqual(max(n['fret'] for n in melody), 12)

    def test_failed_search_stops_instead_of_retrying_twenty_frets(self):
        shared, vocal, guitar = music()
        with patch('guitar_instrumental_register.solve_path', return_value=(None, {'failed_tick': 240})) as solver:
            with self.assertRaisesRegex(ValueError, '不会自动放宽十二品'):
                arrange_instrumental_register(shared, vocal, guitar)
        self.assertTrue(all(call.args[5] <= 12 for call in solver.call_args_list))

    def test_final_limit_also_rejects_high_fret_fill_notes(self):
        shared, vocal, guitar = music()
        result, _ = arrange_instrumental_register(shared, vocal, guitar)
        note = deepcopy(result['notes'][0])
        note.update(id='new_fill', role='harmony', fret=18)
        result['notes'].append(note)
        with self.assertRaisesRegex(ValueError, '拒绝导出'):
            require_instrumental_fret_limit(shared, result)

    def test_tampered_high_fret_is_rejected_even_with_new_music_hash(self):
        shared, vocal, guitar = music()
        result, _ = arrange_instrumental_register(shared, vocal, guitar)
        result['notes'][0]['fret'] = 18
        result['instrumental_register']['result_notes_sha256'] = fingerprint(result['notes'])
        self.assertIn('instrumental_register_above_twelve',
                      validate_instrumental_register(shared, vocal, result)['errors'])

    def test_tampered_boundary_plan_is_rejected(self):
        shared, vocal, guitar = rising_motifs()
        result, _ = arrange_instrumental_register(shared, vocal, guitar)
        result['instrumental_register']['report']['phrase_plan']['additional_boundaries'][0]['tick'] += 120
        self.assertIn('instrumental_register_phrase_plan_changed',
                      validate_instrumental_register(shared, vocal, result)['errors'])

    def test_new_version_is_idempotent_and_does_not_lower_twice(self):
        shared, vocal, guitar = rising_motifs()
        result, report = arrange_instrumental_register(shared, vocal, guitar)
        again, _ = arrange_instrumental_register(shared, vocal, result)
        self.assertEqual(result, again)
        self.assertTrue(report['hard_fret_limit_passed'])

    def test_legacy_source_replay_and_explicit_upgrade_are_separate(self):
        shared, vocal, guitar = music()
        parent = Path(__file__).resolve().parents[1] / 'test_outputs/accompaniment_runs/20261013_instrumental_phrase_register_fix/unit_temp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            path = Path(directory) / 'source.json'
            path.write_text(json.dumps({'shared_analysis': shared, 'accepted_vocal_project': vocal,
                'arrangements': {'guitar': guitar}}), encoding='utf-8')
            legacy, _ = arrange_instrumental_register(shared, vocal, guitar, replay_version=1)
            bind_register_source(legacy, path, shared, vocal)
            restored, report = prepare_register_upgrade(shared, vocal, legacy)
            self.assertEqual(restored['notes'], guitar['notes'])
            self.assertEqual(report['new_version'], 2)
            upgraded, _ = arrange_instrumental_register(shared, vocal, restored)
            self.assertEqual(upgraded['instrumental_register']['version'], 2)
            self.assertEqual(legacy['instrumental_register']['version'], 1)
            self.assertTrue(validate_instrumental_register(shared, vocal, legacy, replay=True)['valid'])

    def test_policy_downgrade_cannot_disable_new_fret_requirement(self):
        shared, vocal, guitar = music()
        result, _ = arrange_instrumental_register(shared, vocal, guitar)
        result['configuration']['instrumental_register_strategy_version'] = 1
        self.assertIn('instrumental_register_strict_policy_changed',
                      validate_instrumental_register(shared, vocal, result)['errors'])

    # 器乐合理分句与十二品硬限制：新增JSON实际来源重放，升级摘要／分句域也必须由绑定输入确定生成。
    def test_serialized_new_source_replays_with_upgrade_context(self):
        shared, vocal, guitar = rising_motifs()
        guitar['configuration']['instrumental_register_strategy_version'] = 2
        guitar['instrumental_register_upgrade_source'] = {'diagnostic': 'unseen_bound_input'}
        parent = Path(__file__).resolve().parents[1] / 'test_outputs/accompaniment_runs/20261013_instrumental_phrase_register_fix/unit_temp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            path = Path(directory) / 'source.json'
            path.write_text(json.dumps({'shared_analysis': shared, 'accepted_vocal_project': vocal,
                'arrangements': {'guitar': guitar}}), encoding='utf-8')
            result, _ = arrange_instrumental_register(shared, vocal, guitar)
            bind_register_source(result, path, shared, vocal)
            serialized = json.loads(json.dumps(result))
            self.assertTrue(validate_instrumental_register(shared, vocal, serialized, replay=True)['valid'])

    def test_changed_bound_strategy_cannot_claim_new_planning(self):
        shared, vocal, guitar = music()
        guitar['configuration']['instrumental_register_strategy_version'] = 2
        parent = Path(__file__).resolve().parents[1] / 'test_outputs/accompaniment_runs/20261013_instrumental_phrase_register_fix/unit_temp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            path = Path(directory) / 'source.json'
            seed = {'shared_analysis': shared, 'accepted_vocal_project': vocal, 'arrangements': {'guitar': guitar}}
            path.write_text(json.dumps(seed), encoding='utf-8')
            result, _ = arrange_instrumental_register(shared, vocal, guitar)
            bind_register_source(result, path, shared, vocal)
            seed['arrangements']['guitar']['configuration']['instrumental_register_strategy_version'] = 1
            path.write_text(json.dumps(seed), encoding='utf-8')
            from score_export import sha256
            result['instrumental_register']['source_sha256'] = sha256(path)
            self.assertIn('instrumental_register_bound_strategy_version_changed',
                          validate_instrumental_register(shared, vocal, result)['errors'])


if __name__ == '__main__':
    unittest.main()
