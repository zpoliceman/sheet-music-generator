"""连续源拍序与人声联合重解通用修复：新增跨拍速、漏攻击、弱起、辅音、未决及来源篡改反例。"""
from pathlib import Path
from copy import deepcopy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / 'tools'))
from continuous_pulse_sequence import solve_component, source_events, infer_sequence_clock
from continuous_vocal_rhythm import solve_rhythm, review_locks
from continuous_meter_project import derive_continuous_vocal, POLICY
# 连续源拍序与人声联合重解通用修复：新增边界交接反例；不读曲名或参考谱。
from continuous_accompaniment_seed import prepare_continuous_seeds, release_ordinary_boundary_tails
# 连续源拍序与人声联合重解通用修复：新增尾拍补全独立范围核查。
from phrase_harmony_arrange import available_ranges


# 连续源拍序与人声联合重解通用修复：新增独立合成源攻击，测试真值不由被测拍轴反算。
def event(q, label=None, period=1., offset=0.):
    return {'seconds': offset + q * period, 'candidate_labels': [q if label is None else label],
            'period': period, 'strength': 1., 'source': 'accompaniment', 'family': 'harmonic_mix'}


# 连续源拍序与人声联合重解通用修复：新增任意字与音高的音段/音素夹具，不输入样曲或参考答案。
def voice(heads, nuclei=None, initials=True):
    nuclei = heads if nuclei is None else nuclei; notes = []; chars = []
    for i, (begin, q, nucleus) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else begin + .6
        notes.append({'id': str(i), 'source_note_id': str(i), 'pitch_midi': 60 + i,
                      'start_seconds': begin, 'end_seconds': end, 'lyric_index': i, 'line_index': 0,
                      'role': 'main', 'anchor': True, 'grace': False, 'confidence': .9,
                      'start_tick': round(q * 480), 'end_tick': round((heads[i + 1][1] if i + 1 < len(heads) else q + .5) * 480),
                      'playback_start_tick': round(q * 480), 'playback_end_tick': round((q + .5) * 480)})
        phonemes = [{'role': 'nucleus', 'start_seconds': nucleus, 'end_seconds': end}]
        if initials:
            phonemes.insert(0, {'role': 'initial', 'start_seconds': begin, 'end_seconds': nucleus})
        chars.append({'index': i, 'text': chr(0x4e00 + i), 'line_index': 0, 'start_seconds': begin,
                      'end_seconds': end, 'phonemes': phonemes})
    base = {'quantized_notes': notes, 'lyrics': {'characters': chars},
            'timing': {'meter': [4, 4], 'score_start_quarter': 0., 'steady_tempo_bpm': 60.,
                       'knots': [{'quarter': 0., 'seconds': 0.}, {'quarter': 8., 'seconds': 8.}]},
            'statistics': {'total_ticks': 3840, 'bar_ticks': 1920}, 'decoder': {}}
    return base, {'vocal_project_sha256': 'bound_source'}


class ContinuousAttackTests(unittest.TestCase):
    def test_alias_is_resolved_by_complete_sequence_not_local_rank(self):
        rows = [event(q, q - .25 if 2 <= q <= 3 else q) for q in (0., .5, 1., 1.5, 2., 2.5, 3., 3.5, 4.)]
        before = deepcopy(rows)
        selected, _ = solve_component(rows, [{'seconds': 0., 'quarter': 0.}, {'seconds': 4., 'quarter': 4.}])
        self.assertEqual([r['quarter'] for r in selected], [i * .5 for i in range(9)])
        self.assertEqual(rows, before)

    def test_tempo_scaling_and_time_offset_leave_numbering_unchanged(self):
        for period in (.42, .65, 1.2):
            for offset in (0., 15.5):
                rows = [event(q, q - .25 if 1 <= q < 2.5 else q, period, offset) for q in (0., .5, 1., 1.5, 2., 2.5, 3.)]
                selected, _ = solve_component(rows, [{'seconds': offset, 'quarter': 0.}])
                self.assertEqual([r['quarter'] for r in selected], [i * .5 for i in range(7)])

    def test_missing_attack_does_not_remove_a_beat(self):
        qs = (0., .5, 1., 2., 2.5, 3., 4.)
        selected, _ = solve_component([event(q, q -.25 if q == 2 else q) for q in qs], [{'seconds': 0., 'quarter': 0.}])
        self.assertEqual([r['quarter'] for r in selected], list(qs))

    def test_real_sixteenth_and_syncopation_are_retained(self):
        qs = (0., .25, .75, 1.25, 1.5, 2.5, 3.25)
        selected, _ = solve_component([event(q) for q in qs], [{'seconds': 0., 'quarter': 0.}])
        self.assertEqual([r['quarter'] for r in selected], list(qs))

    def test_a_whole_bar_displacement_cannot_pass_independent_anchor(self):
        selected, audit = solve_component([event(i * .5, i * .5 + 4) for i in range(9)], [{'seconds': 0., 'quarter': 0.}])
        self.assertFalse(selected)
        self.assertEqual(audit['status'], 'independent_anchor_phase_conflict_preserved')

    def test_related_track_delay_does_not_become_an_extra_sixteenth(self):
        windows = [{'source': name, 'period_seconds': 1., 'observations': [{'seconds': 1. + delay, 'quarter': q}]}
                   for name, delay, q in [('accompaniment', 0., 1.), ('six_guitar', .07, 1.25)]]
        rows = source_events(windows, nominal=1.)
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['seconds'], 1.)
        self.assertEqual(rows[0]['candidate_labels'], [1., 1.25])
        self.assertEqual(source_events(windows * 7, nominal=1.)[0]['candidate_labels'], rows[0]['candidate_labels'])

    def test_same_track_distinct_attacks_are_not_merged(self):
        window = {'source': 'accompaniment', 'period_seconds': 1., 'observations': [
            {'seconds': 1., 'quarter': 1.}, {'seconds': 1.07, 'quarter': 1.25}]}
        self.assertEqual(len(source_events([window])), 2)

    # 连续源拍序与人声联合重解通用修复：新增第三声学帧偏移反例，同一次攻击不能导致根音锚冲突而拒绝整句纠错。
    def test_three_frame_track_delay_does_not_reject_a_whole_component(self):
        windows = [{'source': source, 'period_seconds': .65, 'observations': [
            {'seconds': i * .325 + delay, 'quarter': i * .5} for i in range(9)]}
            for source, delay in [('accompaniment', 0.), ('six_piano', .06966)]]
        events = source_events(windows, nominal=.65)
        self.assertEqual(len(events), 9)
        selected, audit = solve_component(events, [{'seconds': 0., 'quarter': 0.}])
        self.assertEqual([e['quarter'] for e in selected], [i * .5 for i in range(9)])
        self.assertEqual(audit['status'], 'continuous_source_sequence_selected')

    def test_sparse_or_absent_source_preserves_existing_clock(self):
        base, _ = voice([(1., 1., 1.1), (1.5, 1.5, 1.6)])
        knots, audit = infer_sequence_clock(base)
        self.assertEqual(knots, base['timing']['knots']); self.assertEqual(audit['status'], 'retained_clock')
        self.assertFalse(audit['low_coverage_is_music_certification'])


class JointVocalTests(unittest.TestCase):
    # 连续源拍序与人声联合重解通用修复：新增失败组件不能继续改人声，旁边已确认组件仍可正常求解。
    def test_unconfirmed_pulse_component_keeps_its_word_but_not_confirmed_neighbour(self):
        base, binding = voice([(1.25, 1.25, 1.52), (2.25, 2.25, 2.52)])
        clock_audit = {'observations': [{'seconds': 2.}], 'components': [
            {'status': 'independent_anchor_phase_conflict_preserved', 'start_seconds': 1., 'end_seconds': 1.8},
            {'status': 'continuous_source_sequence_selected', 'start_seconds': 2., 'end_seconds': 3.}]}
        revised, audit = solve_rhythm(base, base['timing']['knots'], binding, clock_audit=clock_audit)
        self.assertEqual([n['start_tick'] for n in revised['quantized_notes']], [600, 1200])
        self.assertEqual(audit['uncertain_clock_locked_note_ids'], ['0'])
        self.assertEqual(audit['words'][0]['action'], 'uncertain_pulse_notation_preserved')

    def test_absent_pulse_evidence_keeps_original_notation_without_certifying_it(self):
        base, binding = voice([(1.25, 1.25, 1.52), (2.25, 2.25, 2.52)])
        revised, audit = solve_rhythm(base, base['timing']['knots'], binding,
                                     clock_audit={'observations': [], 'components': []})
        self.assertEqual([n['start_tick'] for n in revised['quantized_notes']], [600, 1080])
        self.assertEqual(audit['uncertain_clock_locked_note_ids'], ['0', '1'])

    def test_unvoiced_consonant_does_not_pull_everything_a_sixteenth_early(self):
        base, binding = voice([(1.25, 1.25, 1.52), (2.25, 2.25, 2.52), (3.25, 3.25, 3.52)])
        old = deepcopy(base); revised, _ = solve_rhythm(base, base['timing']['knots'], binding)
        self.assertEqual([n['start_tick'] for n in revised['quantized_notes']], [720, 1200, 1680])
        self.assertEqual(base, old)

    def test_real_sixteenth_onset_does_not_get_rounded_to_the_next_half(self):
        base, binding = voice([(1.25, 1.25, 1.30), (2.25, 2.25, 2.30)], initials=False)
        revised, _ = solve_rhythm(base, base['timing']['knots'], binding)
        self.assertEqual([n['start_tick'] for n in revised['quantized_notes']], [600, 1080])

    def test_real_half_beat_vocal_delay_is_not_made_a_downbeat(self):
        base, binding = voice([(1.49, 1.5, 1.6), (2.49, 2.5, 2.6)], initials=False)
        revised, _ = solve_rhythm(base, base['timing']['knots'], binding)
        self.assertEqual(revised['quantized_notes'][0]['start_tick'], 720)

    def test_long_word_in_new_bar_cannot_be_squeezed_into_previous_bar(self):
        base, binding = voice([(4.22, 3.5, 4.35), (4.70, 4.75, 4.82)], initials=False)
        revised, _ = solve_rhythm(base, base['timing']['knots'], binding)
        self.assertEqual(revised['quantized_notes'][0]['start_tick'], 1920)

    def test_explicit_unresolved_review_preserves_actual_semantics(self):
        base, binding = voice([(1.25, 1.25, 1.52), (2.25, 2.25, 2.52)])
        review = {'schema_version': 1, 'action': 'preserve_unresolved_notation',
                  'source_vocal_project_sha256': 'bound_source', 'notes': deepcopy(base['quantized_notes'])}
        revised, audit = solve_rhythm(base, base['timing']['knots'], binding, review)
        fields = ('id', 'pitch_midi', 'lyric_index', 'start_tick', 'end_tick', 'grace', 'playback_start_tick', 'playback_end_tick')
        self.assertEqual([tuple(n.get(k) for k in fields) for n in base['quantized_notes']],
                         [tuple(n.get(k) for k in fields) for n in revised['quantized_notes']])
        self.assertEqual(len(audit['locked_note_ids']), 2)

    def test_foreign_source_or_changed_note_review_is_rejected(self):
        base, binding = voice([(1.25, 1.25, 1.52)])
        review = {'schema_version': 1, 'action': 'preserve_unresolved_notation',
                  'source_vocal_project_sha256': 'foreign', 'notes': deepcopy(base['quantized_notes'])}
        with self.assertRaises(ValueError):review_locks(base, binding, review)
        review['source_vocal_project_sha256'] = 'bound_source'; review['notes'][0]['pitch_midi'] += 1
        with self.assertRaises(ValueError):review_locks(base, binding, review)

    def test_text_changes_do_not_change_musical_decision(self):
        base, binding = voice([(1.25, 1.25, 1.52), (2.25, 2.25, 2.52)])
        one, _ = solve_rhythm(base, base['timing']['knots'], binding)
        for c in base['lyrics']['characters']: c['text'] = 'arbitrary'
        two, _ = solve_rhythm(base, base['timing']['knots'], binding)
        self.assertEqual([(n['start_tick'], n['end_tick']) for n in one['quantized_notes']],
                         [(n['start_tick'], n['end_tick']) for n in two['quantized_notes']])

    def test_new_strategy_source_tampering_is_rejected(self):
        correction = {'version': 1, 'policy': deepcopy(POLICY), 'source_vocal_project_sha256': 'bad', 'source_fingerprints': {}}
        with self.assertRaises(ValueError):derive_continuous_vocal({}, {'vocal_project_sha256': 'good', 'sources': {}}, correction)

    # 连续源拍序与人声联合重解通用修复：新增三拍、二拍及复合六拍；新小节由拍号决定，不能固定为四拍。
    def test_new_bar_resolution_uses_actual_meter(self):
        for meter in ([2, 4], [3, 4], [6, 8]):
            bar_q = meter[0] * 4 / meter[1]
            base, binding = voice([(bar_q + .22, bar_q - .5, bar_q + .35),
                                   (bar_q + .70, bar_q + .75, bar_q + .82)], initials=False)
            base['timing']['meter'] = meter; base['statistics']['bar_ticks'] = round(bar_q * 480)
            revised, _ = solve_rhythm(base, base['timing']['knots'], binding)
            self.assertEqual(revised['quantized_notes'][0]['start_tick'], round(bar_q * 480))


# 连续源拍序与人声联合重解通用修复：新增真实源音和自动循环的互斥来源夹具，防止重编覆盖/缺低音。
class ContinuousSeedTests(unittest.TestCase):
    def test_last_partial_beat_cannot_invent_an_unsupported_eighth_attack(self):
        shared = {'sections': [{'kind': 'vocal', 'start_tick': 0, 'end_tick': 700}]}
        source = [{'role': 'bass', 'start_tick': 480, 'end_tick': 720}]
        ranges = available_ranges(shared, 480, 960, [], source_notes=source)
        self.assertEqual(ranges, [(480, 720)])
        self.assertFalse(any(a <= 720 < b for a, b in ranges))
        source[0]['end_tick'] = 960
        self.assertEqual(available_ranges(shared, 480, 960, [], source_notes=source), [(480, 960)])

    def test_obsolete_loop_is_removed_but_real_instrumental_fill_is_kept(self):
        seed = {'id': 'loop', 'section': 'vocal', 'role': 'harmony', 'start_tick': 0, 'end_tick': 240,
                'onset_origin': 'arranged_common_pattern', 'phrase_harmony_generated': True}
        real = {**seed, 'id': 'real', 'source_melody_id': 'actual_source', 'role': 'bass'}
        observed = {**seed, 'id': 'observed', 'onset_origin': 'observed', 'phrase_harmony_generated': False}
        old = {'guitar': {'notes': [seed, real, observed]}}
        fresh = deepcopy(old)
        fresh['guitar']['attack_events'] = [{'start_tick': 0}]
        for n in fresh['guitar']['notes']: n['section'] = 'interlude'
        result = prepare_continuous_seeds(old, fresh)['guitar']
        self.assertEqual([n['id'] for n in result['notes']], ['real', 'observed'])
        self.assertEqual(real['phrase_harmony_generated'], True)
        self.assertEqual(result['notes'][0]['source_melody_id'], 'actual_source')
        self.assertNotIn('phrase_harmony_generated', result['notes'][0])
        self.assertEqual(result['attack_events'], [{'start_tick': 0}])

    def test_piano_preserved_id_does_not_hide_obsolete_vocal_seed(self):
        seed = {'id': 'piano_loop', 'section': 'vocal', 'role': 'bass', 'start_tick': 0, 'end_tick': 240,
                'onset_origin': 'arranged_common_pattern'}
        result = prepare_continuous_seeds({'piano': {'notes': [seed]}},
            {'piano': {'notes': [{**seed, 'id': 'preserved_piano_loop', 'section': 'interlude'}],
                       'attack_events': [{'start_tick': 0}]}})['piano']
        self.assertFalse(result['notes']); self.assertFalse(result['attack_events'])

    def test_complete_beat_rearticulates_bass_without_moving_real_pickup_or_melody(self):
        shared = {'continuous_source_meter': {'version': 1}, 'timing': {'meter': [4, 4]},
                  'sections': [{'kind': 'vocal', 'start_tick': 0, 'end_tick': 1920}],
                  'phrase_harmony_plan': {'beat_boundary_version': 1,
                      'phrases': [{'start_tick': 480, 'end_tick': 1920, 'action': 'shared_progression'}]}}
        bass = {'id': 'bass', 'section': 'vocal', 'role': 'bass', 'start_tick': 240, 'end_tick': 960}
        melody = {**bass, 'id': 'fill', 'source_melody_id': 'real_melody'}
        originals = {'piano': {'notes': [bass, melody]}}
        result = release_ordinary_boundary_tails(shared, originals)['piano']
        self.assertEqual([(n['start_tick'], n['end_tick']) for n in result['notes']], [(240, 480), (240, 960)])

    def test_old_strategy_and_weak_source_phrases_keep_their_sustain(self):
        shared = {'timing': {'meter': [4, 4]}, 'sections': [{'kind': 'vocal', 'start_tick': 0, 'end_tick': 1920}],
                  'phrase_harmony_plan': {'beat_boundary_version': 1, 'phrases': [
                      {'start_tick': 480, 'end_tick': 1920, 'action': 'preserve_source_insufficient_evidence'}]}}
        original = {'piano': {'notes': [{'id': 'bass', 'section': 'vocal', 'role': 'bass', 'start_tick': 240, 'end_tick': 960}]}}
        self.assertEqual(release_ordinary_boundary_tails(shared, deepcopy(original)), original)
        shared['continuous_source_meter'] = {'version': 1}
        revised = release_ordinary_boundary_tails(shared, deepcopy(original))
        self.assertEqual(revised['piano']['notes'], original['piano']['notes'])


if __name__ == '__main__':
    unittest.main()
