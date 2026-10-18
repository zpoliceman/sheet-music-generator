"""相似乐句和弦框架复用：独立已知音乐、和声差异、拍号、实音导出及保护反例。"""
# 相似乐句和弦框架复用：新增自拟旋律/来源向量真值，不以某首歌的自动工程当答案。
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from test_accompaniment import fixture
from score_export import PPQ, key_definition
from accompaniment_analysis import CHORD_TYPES, SongClock, chord_name
from accompaniment_arrange import arrange_guitar, arrange_piano, TUNING, validate_playability
from accompaniment_export import build_musicxml, parse_musicxml_notes, write_midi, validate_midi
from phrase_harmony_plan import (build_phrase_harmony, phrase_ranges, phrase_families, melody_signature,
    similarity, arrangement_view, candidate_scores, bass_for, variant_witnesses, fingerprint)
# 相似乐句和弦框架复用：修改，旧导入保留；踏板边界需独立反例。
# from phrase_harmony_arrange import apply_phrase_harmony, ordinary, music, validate_phrase_harmony
from phrase_harmony_arrange import apply_phrase_harmony, ordinary, music, validate_phrase_harmony, arranged_pedal
from guitar_right_hand_patterns import validate_patterns
from guitar_regular_rhythm import validate_regular_rhythm
from beat_phase_alignment import validate_beat_synchrony


# 相似乐句和弦框架复用：新增多拍号重复音乐；源和弦故意写作C，真值为独立四声谱能证据。
def known_music(bars=4, count=3, meter=(4, 4), transposes=None, tails=None):
    shared, vocal = fixture(); bar = int(PPQ*4*meter[0]/meter[1]); total = count*bars*bar
    key_segments = []; harmony = []; windows = []; textures = []; notes = []; sections = []
    roots = [(0, ''), (9, 'm'), (5, ''), (7, '')]
    transposes = transposes or [0]*count
    vocal['title'] = '自拟'; vocal['lyrics'] = {'characters': [], 'lines': []}
    for phrase in range(count):
        shift = transposes[phrase]; key = key_definition(('C', 'Db', 'D')[shift]+':major')
        beginning = phrase*bars*bar
        key_segments.append({'start_tick': beginning, 'start_measure': phrase*bars+1,
                             'start_seconds': beginning/960, 'key': key, 'jianpu_reference_midi': 60+shift})
        sections.append({'kind': 'vocal', 'label': '演唱', 'start_tick': beginning,
                         'end_tick': beginning+bars*bar, 'start_seconds': beginning/960,
                         'end_seconds': (beginning+bars*bar)/960})
        for index in range(bars):
            start = beginning+index*bar; root, quality = roots[index % 4]
            pitches = [(root+p+shift) % 12 for p in CHORD_TYPES[quality]]
            h = {'id': f'raw_{phrase}_{index}', 'root_pc': shift, 'bass_pc': shift, 'quality': '',
                 'pitch_classes': [(shift+p) % 12 for p in (0, 4, 7)], 'name': chord_name(shift, '', shift, key),
                 'key': key, 'start_tick': start, 'end_tick': start+bar,
                 'start_seconds': start/960, 'end_seconds': (start+bar)/960, 'requires_review': False}
            harmony.append(h)
            for tick in range(start, start+bar, int(PPQ*4/meter[1])):
                chroma = np.zeros(12); chroma[pitches] = 1/len(pitches)
                bass = np.zeros(12); bass[(root+shift) % 12] = 1.
                windows.append({'start_tick': tick, 'end_tick': min(tick+int(PPQ*4/meter[1]), start+bar),
                                'key': key, 'chroma': chroma.tolist(), 'bass_chroma': bass.tolist()})
            attacks = []
            for i, tick in enumerate(range(start, start+bar, PPQ//2)):
                pitch = (60, 64, 67, 72, 67, 64, 67, 72)[i % 8]+shift
                attacks.append({'tick': tick, 'seconds': tick/960, 'strength': 1., 'source': 'known_audio',
                                'pitches': [{'pitch_midi': pitch, 'relative_weight': 1., 'weight': 1.}]})
            textures.append({'measure': start//bar+1, 'start_tick': start, 'end_tick': start+bar,
                             'start_seconds': start/960, 'end_seconds': (start+bar)/960,
                             'section': 'vocal', 'kind': 'arpeggio', 'source': 'known_audio', 'attacks': attacks})
            melody = (64, 67, 60, 67) if index == 0 else (64, 67, 69, 64) if index == 1 else (
                65, 69, 72, 69) if index == 2 else (67, 71, 74, 71)
            if tails and phrase in tails and index == bars-1: melody = tails[phrase]
            for j, pitch in enumerate(melody):
                a = start+j*bar//4; b = start+(j+1)*bar//4
                identity = len(notes)
                notes.append({'id': f'v_{identity}', 'pitch_midi': pitch+shift, 'start_tick': a, 'end_tick': b,
                              'start_seconds': a/960, 'end_seconds': b/960, 'duration_ticks': b-a,
                              'lyric_index': identity, 'line_index': phrase*bars+index,
                              'role': 'main', 'grace': False})
    vocal['quantized_notes'] = notes; vocal['notation']['key_segments'] = key_segments
    vocal['notation']['source_key'] = key_segments[0]['key']
    vocal['timing']['meter'] = list(meter)
    for stats in (shared['statistics'], vocal['statistics']):
        stats.update(total_ticks=total, bar_ticks=bar, measure_count=count*bars)
    shared.update(timing={'meter': list(meter)}, notation={'key': key_segments[0]['key']},
                  harmony=harmony, harmony_windows=windows, measure_textures=textures,
                  sections=sections, instrumental_melody=[], melodic_motif_matches=[])
    shared['input_binding']['sources'] = {}
    return shared, vocal


def performed(shared, vocal):
    plan = build_phrase_harmony(shared, vocal); result = deepcopy(shared)
    result['arranged_harmony'] = plan.pop('arranged_harmony'); result['phrase_harmony_plan'] = plan
    return result


def arrangements(shared, vocal, capo=0):
    result = {'guitar': arrange_guitar(shared, vocal, capo), 'piano': arrange_piano(shared, vocal)}
    result['guitar']['source_rhythm_evidence'] = {'measures': [
        {'measure': row['measure'], 'source': 'accompaniment', 'active': True, 'rms': 1.,
         'attacks': [{'tick': n['tick'], 'strength': 1., 'pitches': n['pitches']} for n in row['attacks']]}
        for row in shared['measure_textures']]}
    return result


class PhrasePlanTests(unittest.TestCase):
    # 相似乐句和弦框架复用：新增跨句共同进行的独立C-Am-F-G真值，原分析保持原样。
    def test_joint_progression_uses_harmonic_evidence_and_same_change_beats(self):
        s, v = known_music(); before = deepcopy((s, v)); plan = build_phrase_harmony(s, v)
        self.assertEqual((s, v), before)
        self.assertEqual(len(plan['families']), 1)
        for p in plan['phrases']:
            self.assertEqual([(h['offset_tick'], h['root_degree_pc'], h['quality']) for h in p['progression']],
                             [(0, 0, ''), (1920, 9, 'm'), (3840, 5, ''), (5760, 7, '')])

    def test_title_lyrics_and_reference_have_no_musical_input(self):
        s, v = known_music(); before = build_phrase_harmony(s, v)
        v['title'] = '别的歌曲'; v['lyrics'] = {'characters': [{'text': '不同字'}]}
        s['input_binding']['references'] = [{'path': '不存在的参考图片.jpg'}]
        after = build_phrase_harmony(s, v)
        self.assertEqual(after['arranged_harmony'], before['arranged_harmony'])
        self.assertFalse(after['lyrics_text_used'])

    def test_three_bar_and_two_bar_phrases_not_four_bar_rows(self):
        for bars in (2, 3, 6):
            s, v = known_music(bars=bars)
            ranges = phrase_ranges(s, v)
            self.assertEqual([p['end_tick']-p['start_tick'] for p in ranges], [bars*1920]*3)
            self.assertEqual(len(build_phrase_harmony(s, v)['families']), 1)

    def test_relative_key_reuse_after_real_transposition(self):
        s, v = known_music(transposes=[0, 2, 2]); plan = build_phrase_harmony(s, v)
        self.assertEqual(len(plan['families']), 1)
        for p in plan['phrases']:
            self.assertEqual([h['root_degree_pc'] for h in p['progression']], [0, 9, 5, 7])
        self.assertEqual([h['root_pc'] for h in plan['arranged_harmony'][4:8]], [2, 11, 7, 9])

    def test_mere_head_similarity_does_not_merge_unrelated_full_phrase(self):
        s, v = known_music()
        for n in v['quantized_notes']:
            if n['line_index'] in (9, 10, 11): n['pitch_midi'] += 6
        groups = phrase_families(s, v, phrase_ranges(s, v))
        self.assertEqual(sorted(len(f['members']) for f in groups), [1, 2])

    def test_no_transitive_unchecked_family_join(self):
        s, v = known_music()
        for n in v['quantized_notes']:
            n['pitch_midi'] += n['line_index']//4*2
        groups = phrase_families(s, v, phrase_ranges(s, v))
        self.assertEqual(sorted(len(f['members']) for f in groups), [1, 2])

    def test_missing_and_all_zero_evidence_cannot_invent_c_progression(self):
        s, v = known_music(); s.pop('harmony_windows')
        p = build_phrase_harmony(s, v)
        self.assertEqual(p['arranged_harmony'], s['harmony']); self.assertEqual(p['phrases'], [])
        s, v = known_music()
        for w in s['harmony_windows']: w['chroma'] = w['bass_chroma'] = [0.]*12
        p = build_phrase_harmony(s, v)
        self.assertTrue(all(x['action'] == 'preserve_source_insufficient_evidence' for x in p['phrases']))
        self.assertEqual([(h['root_pc'], h['quality']) for h in p['arranged_harmony']], [(0, '')]*12)

    def test_weak_member_does_not_vote_against_supported_family(self):
        s, v = known_music()
        for w in s['harmony_windows']:
            if w['start_tick'] >= 15360: w['chroma'] = w['bass_chroma'] = [0.]*12
        p = build_phrase_harmony(s, v)
        self.assertEqual(p['phrases'][-1]['action'], 'preserve_source_insufficient_evidence')
        self.assertEqual([h['root_degree_pc'] for h in p['phrases'][0]['progression']], [0, 9, 5, 7])

    def test_sustained_different_bass_has_explicit_local_variant(self):
        s, v = known_music()
        for w in s['harmony_windows']:
            if 15360 <= w['start_tick'] < 17280:
                w['bass_chroma'] = [0.]*12; w['bass_chroma'][9] = 1.
                w['chroma'] = [0.]*12
                for pc in (9, 0, 4): w['chroma'][pc] = 1/3
        p = build_phrase_harmony(s, v); last = p['phrases'][-1]
        self.assertEqual(last['action'], 'supported_local_variant')
        self.assertEqual(last['progression'][0]['root_degree_pc'], 9)
        self.assertTrue(all(x['witness']['supported'] for x in last['variants']))
        self.assertLessEqual(len(last['variant_bar_positions']), 2)

    def test_one_beat_passing_bass_does_not_split_whole_chord(self):
        rows = [{'bass': np.eye(12)[pc]} for pc in (0, 0, 4, 0)]
        self.assertEqual(bass_for(rows, (0, '')), 0)
        self.assertEqual(bass_for([{'bass': np.eye(12)[4]}], (0, '')), 0)
        self.assertEqual(bass_for([{'bass': np.eye(12)[4]}]*4, (0, '')), 4)

    # 相似乐句和弦框架复用：新增同旋律/同根低音但真实大小性质不同，不能只为了复用强行统一。
    def test_same_melody_and_bass_but_sustained_minor_third_preserves_variant(self):
        s, v = known_music()
        for n in v['quantized_notes']:
            if n['line_index'] % 4 == 0:
                n['pitch_midi'] = (67, 60, 62, 67)[n['lyric_index'] % 4]
        for w in s['harmony_windows']:
            if 15360 <= w['start_tick'] < 17280:
                w['chroma'] = [0.]*12
                for pc in (0, 3, 7):w['chroma'][pc] = 1/3
        p = build_phrase_harmony(s, v)
        self.assertEqual(len(p['families']), 1)
        last = p['phrases'][-1]
        self.assertEqual(last['action'], 'supported_local_variant')
        self.assertEqual((last['progression'][0]['root_degree_pc'], last['progression'][0]['quality']), (0, 'm'))
        self.assertTrue(any(x['witness'].get('sustained_accompaniment_third_pitch_classes') == [3] for x in last['variants']))

    def test_single_chromatic_accompaniment_attack_not_sustained_quality_variant(self):
        s, v = known_music(); first = phrase_ranges(s, v)[0]
        from phrase_harmony_plan import phrase_evidence
        s['harmony_windows'][0]['chroma'] = [0.]*12
        for pc in (0, 3, 7):s['harmony_windows'][0]['chroma'][pc] = 1/3
        rows = phrase_evidence(s, v, first, 480)
        witness = variant_witnesses(rows, np.array([r['stable_voice'] for r in rows]), [0]*len(rows), [(0, '')], 0)
        self.assertFalse(witness['supported'])

    def test_same_melody_and_bass_keep_major_seventh_and_dominant_seventh(self):
        s, v = known_music(bars=1)
        for w in s['harmony_windows']:
            w['chroma'] = [0.]*12
            for pc in (0, 4, 7, 11 if w['start_tick'] < 3840 else 10):w['chroma'][pc] = .25
        p = build_phrase_harmony(s, v)
        self.assertEqual(len(p['families']), 1)
        self.assertEqual([h['quality'] for h in p['arranged_harmony']], ['maj7', 'maj7', '7'])
        self.assertTrue(all(x['witness']['supported'] for phrase in p['phrases'] for x in phrase['variants']))

    def test_single_seventh_passing_attack_does_not_force_seventh_chord(self):
        s, v = known_music(); first = phrase_ranges(s, v)[0]
        from phrase_harmony_plan import phrase_evidence
        s['harmony_windows'][0]['chroma'] = [0.]*12
        for pc in (0, 4, 7, 10):s['harmony_windows'][0]['chroma'][pc] = .25
        rows = phrase_evidence(s, v, first, 480)
        witness = variant_witnesses(rows, np.array([r['stable_voice'] for r in rows]), [0]*len(rows), [(0, '')], 0)
        self.assertFalse(witness['supported'])

    def test_short_turn_cannot_open_local_variant(self):
        s, v = known_music(); p = phrase_ranges(s, v)[0]
        from phrase_harmony_plan import phrase_evidence
        n = v['quantized_notes'][0]; n.update(pitch_midi=61, role='turn', end_tick=n['start_tick']+120)
        rows = phrase_evidence(s, v, p, 480); proto = [0]*len(rows)
        w = variant_witnesses(rows, np.zeros((len(rows), 12)), proto, [(0, '')], 0)
        self.assertFalse(w['supported'])

    def test_actual_sus_and_seventh_not_blanket_deleted(self):
        for quality, pcs in (('sus4', [0, 5, 7]), ('m7', [9, 0, 4, 7])):
            s, v = known_music(bars=1, count=1)
            root = 9 if quality == 'm7' else 0
            for w in s['harmony_windows']:
                w['chroma'] = [0.]*12; w['bass_chroma'] = [0.]*12; w['bass_chroma'][root] = 1.
                for pc in pcs: w['chroma'][pc] = 1/len(pcs)
            plan = build_phrase_harmony(s, v)
            self.assertEqual(plan['arranged_harmony'][0]['quality'], quality)

    def test_source_and_vocal_or_clock_changes_invalidate_plan(self):
        s, v = known_music(); s = performed(s, v)
        cases = [('windows', lambda x: x['harmony_windows'][0]['chroma'].__setitem__(0, .123)),
                 ('key', lambda x: x['harmony'][0].__setitem__('bass_pc', 4)),
                 ('binding', lambda x: x['input_binding'].__setitem__('vocal_project_sha256', 'b'*64)),
                 ('landmark', lambda x: x.__setitem__('melodic_motif_matches', [{'reference_line': 1, 'target_line': 2}]))]
        for _, edit in cases:
            modified = deepcopy(s); edit(modified)
            with self.assertRaises(ValueError): arrangement_view(modified, v)
        for field, value in (('steady_tempo_bpm', 100), ('score_start_seconds', 2)):
            vv = deepcopy(v); vv['timing'][field] = value
            with self.assertRaises(ValueError): arrangement_view(s, vv)
        vv = deepcopy(v); vv['quantized_notes'][0]['pitch_midi'] += 1
        with self.assertRaises(ValueError): arrangement_view(s, vv)

    def test_different_durations_and_constant_tone_not_false_repetition(self):
        s, v = known_music(bars=1)
        a = melody_signature(s, v, 0, 1920); b = melody_signature(s, v, 1920, 5760)
        self.assertFalse(similarity(a, b)['accepted'])
        for n in v['quantized_notes']: n['pitch_midi'] = 64
        groups = phrase_families(s, v, phrase_ranges(s, v))
        self.assertTrue(all(len(g['members']) == 1 for g in groups))


class ActualArrangementTests(unittest.TestCase):
    # 相似乐句和弦框架复用：新增两乐器发声/XML/MIDI的独立真值与保护，不只比较规划标签。
    def test_guitar_and_piano_really_play_planned_pitch_classes(self):
        s, v = known_music(); old = arrangements(s, v); frozen = deepcopy((s, v, old))
        new, both, check = apply_phrase_harmony(s, v, old)
        self.assertTrue(check['valid']); self.assertEqual((s, v, old), frozen)
        active = arrangement_view(new, v)
        self.assertEqual(new['harmony'], s['harmony'])
        for name, a in both.items():
            self.assertTrue(validate_playability(a, SongClock(v))['valid'])
            root, _ = build_musicxml(new, v, a); parsed, result = parse_musicxml_notes(root)
            self.assertTrue(result['valid'])
            self.assertEqual({i: (n['start_tick'], n['end_tick'], n['pitch_midi']) for i, n in parsed.items()},
                             {n['id']: (n['start_tick'], n['end_tick'], n['pitch_midi']) for n in a['notes']})
            self.assertEqual(len(root.findall('part/measure/harmony')), 12)
            for h in active['harmony']:
                body = [n for n in a['notes'] if h['start_tick'] <= n['start_tick'] < h['end_tick']]
                self.assertTrue(body)
                self.assertTrue(all(n['pitch_midi'] % 12 in h['pitch_classes'] for n in body))
                self.assertTrue(any(n['start_tick'] == h['start_tick'] and n['role'] == 'bass'
                                    and n['pitch_midi'] % 12 == h['bass_pc'] for n in body))
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'real.mid'; write_midi(path, a, v)
                self.assertTrue(validate_midi(path, a, v)['valid'])
        self.assertTrue(validate_patterns(active, both['guitar'])['valid'])
        self.assertTrue(validate_regular_rhythm(active, both['guitar'])['valid'])
        self.assertTrue(validate_beat_synchrony(active, v, both['guitar'])['valid'])
        cnotes = [n for n in both['guitar']['notes'] if n['start_tick'] < 1920]
        self.assertEqual([(n['string'], n['fret']) for n in cnotes[:4]], [(5, 3), (3, 0), (2, 1), (1, 0)])

    def test_idempotent_upgrade_preserves_edited_velocity(self):
        s, v = known_music(); s, a, _ = apply_phrase_harmony(s, v, arrangements(s, v))
        a['guitar']['notes'][0]['velocity'] = 91; before = deepcopy((s, a))
        s2, a2, check = apply_phrase_harmony(s, v, a)
        self.assertEqual((s2, a2), before); self.assertTrue(check['valid'])

    def test_instrumental_and_feature_fill_stay_exact_in_both_instruments(self):
        s, v = known_music(); s['sections'][0]['kind'] = 'intro'
        old = arrangements(s, v)
        for name, a in old.items():
            n = deepcopy(next(n for n in a['notes'] if n['start_tick'] >= 7680))
            n.update(id=name+'_feature', role='instrumental_melody', source_melody_id='source_feature',
                     start_tick=9600, end_tick=10080)
            a['notes'] = [x for x in a['notes'] if not 9600 <= x['start_tick'] < 10080]+[n]
        protected = {name: {n['id']: music(n) for n in a['notes'] if not ordinary(s, n)} for name, a in old.items()}
        new, both, check = apply_phrase_harmony(s, v, old)
        self.assertTrue(check['valid'])
        for name, a in both.items():
            present = {n['id']: music(n) for n in a['notes']}
            self.assertTrue(all(present[i] == n for i, n in protected[name].items()))
            self.assertFalse(any(n.get('phrase_harmony_generated') and 9600 <= n['start_tick'] < 10080 for n in a['notes']))

    def test_weak_evidence_keeps_old_notes_rather_than_filling_silence(self):
        s, v = known_music(); old = arrangements(s, v)
        for w in s['harmony_windows']:
            if w['start_tick'] >= 15360: w['chroma'] = w['bass_chroma'] = [0.]*12
        new, both, check = apply_phrase_harmony(s, v, old)
        self.assertTrue(check['valid'])
        for name, a in both.items():
            self.assertEqual({n['id']: music(n) for n in old[name]['notes'] if n['start_tick'] >= 15360},
                             {n['id']: music(n) for n in a['notes'] if n['start_tick'] >= 15360})

    def test_other_meters_have_actual_measure_length_and_no_thirty_seconds(self):
        for meter in ((3, 4), (6, 8), (5, 4)):
            s, v = known_music(bars=2, meter=meter); old = arrangements(s, v)
            new, both, check = apply_phrase_harmony(s, v, old)
            self.assertTrue(check['valid'])
            for a in both.values():
                root, _ = build_musicxml(new, v, a); _, result = parse_musicxml_notes(root)
                self.assertTrue(result['valid'])
                self.assertEqual(set(result['measure_lengths']), {s['statistics']['bar_ticks']})
                self.assertFalse(root.findall('.//type[.="32nd"]'))
                self.assertTrue(all(n['end_tick'] > n['start_tick'] for n in a['notes']))

    def test_capo_shapes_really_sound_at_transposed_pitch(self):
        s, v = known_music(bars=2, transposes=[2, 2, 2]); new, a, check = apply_phrase_harmony(s, v, arrangements(s, v, 2))
        self.assertTrue(check['valid'])
        for n in a['guitar']['notes']:
            self.assertEqual(n['pitch_midi'], TUNING[n['string']]+2+n['fret'])
        self.assertEqual([(n['string'], n['fret']) for n in a['guitar']['notes'][:4]], [(5, 3), (3, 0), (2, 1), (1, 0)])

    def test_changed_played_pitch_fails_even_if_name_still_correct(self):
        s, v = known_music(); s, a, _ = apply_phrase_harmony(s, v, arrangements(s, v))
        a['piano']['notes'][0]['pitch_midi'] += 1
        self.assertFalse(validate_phrase_harmony(s, v, a)['valid'])

    def test_changed_protected_instrumental_fails(self):
        s, v = known_music(); s['sections'][0]['kind'] = 'intro'; old = arrangements(s, v)
        s, a, _ = apply_phrase_harmony(s, v, old)
        a['guitar']['notes'][0]['end_tick'] += 120
        self.assertFalse(validate_phrase_harmony(s, v, a)['valid'])

    def test_shared_plan_gap_fails_and_source_harmony_is_not_replaced(self):
        s, v = known_music(); s, a, _ = apply_phrase_harmony(s, v, arrangements(s, v))
        s['arranged_harmony'][0]['end_tick'] -= 120
        self.assertFalse(validate_phrase_harmony(s, v, a)['valid'])

    # 相似乐句和弦框架复用：新增正式导出发现的尾奏边界踏板回归，以及账本/标签篡改反例。
    def test_pedal_state_at_instrumental_entry_restores_source(self):
        s, v = known_music(); s['sections'][-1]['kind'] = 'outro'; old = arrangements(s, v)
        old['piano']['pedal'] = [{'tick': 14880, 'value': 127}, {'tick': 16320, 'value': 0}]
        new, both, check = apply_phrase_harmony(s, v, old)
        self.assertTrue(check['valid'])
        def state(events, tick):return next((e['value'] for e in reversed(events) if e['tick'] <= tick), 0)
        self.assertEqual(state(both['piano']['pedal'], 15360), 127)
        self.assertEqual(state(both['piano']['pedal'], 16320), 0)
        both['piano']['pedal'] = [e for e in both['piano']['pedal'] if e.get('reason') != 'restore_preserved_instrumental_pedal_state']
        self.assertFalse(validate_phrase_harmony(new, v, both)['valid'])

    def test_deleted_protection_ledger_cannot_mask_instrumental_omission(self):
        s, v = known_music(); s['sections'][0]['kind'] = 'intro'; s, a, _ = apply_phrase_harmony(s, v, arrangements(s, v))
        identity = a['guitar']['notes'][0]['id']; a['guitar']['notes'].pop(0)
        info = a['guitar']['phrase_harmony_performance']; info['protected_notes'] = [n for n in info['protected_notes'] if n['id'] != identity]
        self.assertFalse(validate_phrase_harmony(s, v, a)['valid'])

    def test_false_chord_label_or_reuse_record_cannot_pass(self):
        s, v = known_music(); s, a, _ = apply_phrase_harmony(s, v, arrangements(s, v))
        changed = deepcopy(s); changed['arranged_harmony'][0]['name'] = 'Am'
        self.assertFalse(validate_phrase_harmony(changed, v, a)['valid'])
        changed = deepcopy(s); changed['phrase_harmony_plan']['phrases'][0]['progression'][0]['root_degree_pc'] = 9
        self.assertFalse(validate_phrase_harmony(changed, v, a)['valid'])

    def test_note_crossing_next_harmony_fails(self):
        s, v = known_music(); s, a, _ = apply_phrase_harmony(s, v, arrangements(s, v))
        a['guitar']['notes'][0]['end_tick'] = 2040
        self.assertFalse(validate_phrase_harmony(s, v, a)['valid'])


if __name__ == '__main__': unittest.main()
