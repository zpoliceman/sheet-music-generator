"""吉他既有规则闭环修复：独立验证真实音符、旧音乐保护与有依据的模板共享。"""
# 吉他既有规则闭环修复：新增行为回归，覆盖半拍和弦、密集拨弦、真实变体与完整保护。
import copy
import json
import sys
from pathlib import Path

import numpy as np
# 吉他既有规则闭环修复：修改为项目既有unittest运行器，原pytest依赖注释保留。
# import pytest
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from guitar_readable_arrangement import (SourceEvidence, _quantize_instrumental,
                                        guitar_shared_view, revise_guitar_arrangement)
# 吉他既有规则闭环修复：新增实际右手循环和策略身份的行为检查入口。
from guitar_readable_arrangement import _pattern_strings, _shape, POLICY
from guitar_chord_diagrams import draw_diagram, read_diagram


def fixture_project(bars=2, repeated=False):
    # 吉他既有规则闭环修复：新增与具体歌曲无关的完整来源小工程；速度与和声身份独立构造。
    key = {'label': 'C:major', 'tonic': 'C', 'mode': 'major', 'tonic_pc': 0,
           'fifths': 0, 'jianpu_one': 'C', 'jianpu_one_pc': 0}
    total = bars * 1920
    timeline = [{'number': i + 1, 'start_tick': i * 1920, 'end_tick': (i + 1) * 1920,
                 'meter': [4, 4], 'pickup': False} for i in range(bars)]
    voice_notes = [{'id': f'v_{i}', 'pitch_midi': [60, 62, 64, 65, 67, 69, 71, 72][i % 8],
                    'start_tick': i * 480, 'end_tick': i * 480 + 360, 'lyric_index': i,
                    'line_index': i // 16, 'start_seconds': float(i), 'end_seconds': i + .75,
                    'role': 'main'} for i in range(bars * 4)]
    vocal = {'timing': {'knots': [{'quarter': 0., 'seconds': 0.}, {'quarter': bars * 4., 'seconds': bars * 4.}],
                        'meter': [4, 4], 'score_start_quarter': 0., 'measure_timeline': timeline},
             'statistics': {'bar_ticks': 1920, 'total_ticks': total, 'measure_count': bars},
             'notation': {'key': key}, 'quantized_notes': voice_notes, 'events': [],
             'lyrics': {'characters': [{'index': i, 'text': '字'} for i in range(bars * 4)]}}
    harmony, windows, notes, diagrams = [], [], [], []
    for i in range(bars):
        a = i * 1920
        for j, (offset, duration, quality, pcs) in enumerate([(0, 240, 'sus4', [0, 5, 7]), (240, 1680, '', [0, 4, 7])]):
            harmony.append({'id': f'h_{i}_{j}', 'root_pc': 0, 'bass_pc': 0, 'quality': quality,
                            'pitch_classes': pcs, 'name': 'C' + quality, 'key': key,
                            'start_tick': a + offset, 'end_tick': a + offset + duration,
                            'start_seconds': (a + offset) / 480, 'end_seconds': (a + offset + duration) / 480})
        windows.append({'start_seconds': a / 480, 'end_seconds': (a + 1920) / 480,
                        'chroma': [.35, 0, 0, 0, .35, 0, 0, .30, 0, 0, 0, 0],
                        'bass_chroma': [1., 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                        'accompaniment_rms': .1, 'start_tick': a, 'end_tick': a + 1920, 'key': key})
        for j in range(8):
            string, fret, pitch = [(5, 3, 48), (3, 0, 55), (2, 1, 60), (1, 0, 64)][j % 4]
            notes.append({'id': f'n_{i}_{j}', 'pitch_midi': pitch, 'string': string, 'fret': fret,
                          'finger': 0 if fret == 0 else 1, 'role': 'bass' if string == 5 else 'harmony',
                          'section': 'vocal', 'start_tick': a + j * 240, 'end_tick': a + (j + 1) * 240,
                          'velocity': 72, 'hand_position': 1, 'chord_id': f'h_{i}_1'})
        diagrams.append({'id': f'chart_{i}', 'frets': {'5': 3, '4': 2, '3': 0, '2': 1, '1': 0},
                         'position': 1, 'shape_name': 'C', 'sounding_name': 'C', 'capo': 0,
                         'start_tick': a, 'end_tick': a + 1920, 'chord_id': f'h_{i}_1'})
    guitar = {'configuration': {'capo_fret': 0, 'maximum_fret': 12, 'maximum_fretted_span': 5},
              'instrument': 'guitar', 'notes': notes, 'fingering_diagrams': diagrams,
              'hand_positions': [{'tick': 0, 'position': 1}], 'notation_regions': [],
              'right_hand_patterns': {'stale': True}, 'regular_rhythm': {'stale': True}}
    shared = {'harmony': harmony, 'harmony_windows': windows, 'sections': [
        {'kind': 'vocal', 'start_tick': 0, 'end_tick': total}], 'notation': {'key': key},
        'timing': copy.deepcopy(vocal['timing']), 'statistics': copy.deepcopy(vocal['statistics']),
        '_phrase_harmony_view': True}
    if repeated:
        shared['phrase_harmony_plan'] = {'phrases': [
            {'id': f'p_{i}', 'family_id': 'same_musical_phrase', 'start_tick': i * total // 2,
             'end_tick': (i + 1) * total // 2, 'action': 'shared_progression'} for i in range(2)]}
    return {'accepted_vocal_project': vocal, 'shared_analysis': shared,
            'arrangements': {'guitar': guitar, 'piano': {'notes': [{'pitch_midi': 48}]}},
            'music_acceptance': {'status': 'needs_review'}}


def test_half_beat_chord_is_rearranged_in_real_audio_notes():
    project = fixture_project()
    before = copy.deepcopy(project)
    result, audit = revise_guitar_arrangement(project)
    guitar = result['arrangements']['guitar']
    assert project == before
    assert result['accepted_vocal_project'] == before['accepted_vocal_project']
    assert result['shared_analysis'] == before['shared_analysis']
    assert result['arrangements']['piano'] == before['arrangements']['piano']
    assert all(h['start_tick'] % 480 == 0 and h['end_tick'] - h['start_tick'] >= 480 for h in guitar['readable_harmony'])
    assert all(n['start_tick'] % 120 == n['end_tick'] % 120 == 0 for n in guitar['notes'])
    assert all(n['pitch_midi'] % 12 in {0, 4, 7} for n in guitar['notes'])
    assert all(len([h for h in guitar['readable_harmony'] if h['readable_measure'] == m]) <= 2 for m in [1, 2])
    assert audit['grip_path']['valid']
    assert 'regular_rhythm' not in guitar
    assert guitar['readability_ancestor_evidence']['regular_rhythm'] == {'stale': True}


def test_protected_instrumental_order_frets_and_expression_survive_dense_grid():
    notes = [{'id': f'i{i}', 'start_tick': a, 'end_tick': a + 90, 'pitch_midi': 62 + i,
              'string': 2, 'fret': 3 + i, 'role': 'instrumental_melody', 'section': 'intro',
              'velocity': 108, 'melody_accent': True} for i, a in enumerate([30, 90, 210])]
    result, edits = _quantize_instrumental(notes, 1920)
    assert [n['id'] for n in result] == [n['id'] for n in notes]
    for before, after in zip(notes, result):
        assert {k: before[k] for k in ['id', 'pitch_midi', 'string', 'fret', 'role', 'velocity', 'melody_accent']} == {
            k: after[k] for k in ['id', 'pitch_midi', 'string', 'fret', 'role', 'velocity', 'melody_accent']}
        assert after['start_tick'] % 120 == after['end_tick'] % 120 == 0
        assert after['end_tick'] - after['start_tick'] >= 120
        assert abs(after['start_tick'] - before['start_tick']) <= 240
    assert edits


def test_unplayably_dense_instrumental_material_stops_instead_of_fine_grid():
    notes = [{'id': f'i{i}', 'start_tick': 30 + i, 'end_tick': 40 + i, 'pitch_midi': 64,
              'string': 1, 'fret': 0} for i in range(9)]
    # 吉他既有规则闭环修复：修改为无需新增依赖的异常行为检查。
    # with pytest.raises(ValueError, match='十六分'):
    with unittest.TestCase().assertRaisesRegex(ValueError, '十六分'):
        _quantize_instrumental(notes, 1920)


def test_source_compatible_repeated_phrases_share_actual_notes():
    result, audit = revise_guitar_arrangement(fixture_project(16, repeated=True))
    notes = result['arrangements']['guitar']['notes']
    def signature(start, end):
        return [(n['start_tick'] - start, n['end_tick'] - n['start_tick'], n['pitch_midi'], n['string'], n['fret'])
                for n in notes if start <= n['start_tick'] < end]
    assert signature(0, 15360) == signature(15360, 30720)
    assert len(audit['shared_bars']) == 8
    assert not audit['preserved_variants']


def test_source_supported_harmonic_variant_is_not_erased_to_force_repeat():
    project = fixture_project(16, repeated=True)
    # 吉他既有规则闭环修复：新增反例，第二遍有独立低音与和声变化时不得强做完全共用。
    for chord in project['shared_analysis']['harmony']:
        if 15360 <= chord['start_tick'] < 17280:
            chord.update(root_pc=2, bass_pc=2, quality='m', pitch_classes=[2, 5, 9], name='Dm')
    source = project['shared_analysis']['harmony_windows'][8]
    source['chroma'] = [0, 0, .3, 0, 0, .35, 0, 0, 0, .35, 0, 0]
    source['bass_chroma'] = [0, 0, 1., 0, 0, 0, 0, 0, 0, 0, 0, 0]
    result, audit = revise_guitar_arrangement(project)
    assert any(r['bar_position'] == 0 for r in audit['preserved_variants'])
    assert all(h['root_pc'] == 2 for h in result['arrangements']['guitar']['readable_harmony'] if 15360 <= h['start_tick'] < 17280)


def test_one_variant_occurrence_does_not_block_two_matching_occurrences():
    # 吉他既有规则闭环修复：新增三遍句反例；第一遍有真和声差异，后两遍仍可合法共享完整8小节。
    project = fixture_project(24, repeated=True)
    project['shared_analysis']['phrase_harmony_plan']['phrases'] = [
        {'id': f'p_{i}', 'family_id': 'three_occurrences', 'start_tick': i * 15360,
         'end_tick': (i + 1) * 15360, 'action': 'shared_progression'} for i in range(3)]
    for chord in project['shared_analysis']['harmony']:
        if 1920 <= chord['start_tick'] < 3840:
            chord.update(root_pc=2, bass_pc=2, quality='m', pitch_classes=[2, 5, 9], name='Dm')
    source = project['shared_analysis']['harmony_windows'][1]
    source.update(chroma=[0, 0, .3, 0, 0, .35, 0, 0, 0, .35, 0, 0],
                  bass_chroma=[0, 0, 1., 0, 0, 0, 0, 0, 0, 0, 0, 0])
    result, audit = revise_guitar_arrangement(project)
    notes = result['arrangements']['guitar']['notes']
    def signature(start, end):
        return [(n['start_tick'] - start, n['end_tick'] - n['start_tick'], n['pitch_midi'], n['string'], n['fret'])
                for n in notes if start <= n['start_tick'] < end]
    assert signature(0, 15360) != signature(15360, 30720)
    assert signature(15360, 30720) == signature(30720, 46080)
    assert any(r.get('subset_member_ids') == ['p_1', 'p_2'] for r in audit['shared_bars'])


def test_compliant_music_keeps_notes_and_only_repairs_release():
    project = fixture_project()
    project['shared_analysis']['harmony'] = [h for h in project['shared_analysis']['harmony'] if h['quality'] == '']
    for chord in project['shared_analysis']['harmony']:
        chord['start_tick'] -= 240
    project['arrangements']['guitar']['notes'][1]['end_tick'] -= 30
    result, audit = revise_guitar_arrangement(project)
    before, after = project['arrangements']['guitar']['notes'], result['arrangements']['guitar']['notes']
    assert len(before) == len(after)
    assert [n['id'] for n in before] == [n['id'] for n in after]
    assert all([n[k] for k in ['pitch_midi', 'string', 'fret', 'start_tick']] == [m[k] for k in ['pitch_midi', 'string', 'fret', 'start_tick']] for n, m in zip(before, after))
    assert len(audit['all_local_timing_edits']) == 1
    assert audit['whole_vocal_rearrangement'] is False


def test_revision_is_idempotent_but_changed_source_cannot_reuse_pass():
    first, audit = revise_guitar_arrangement(fixture_project())
    second, again = revise_guitar_arrangement(first)
    assert first == second and audit == again
    first['shared_analysis']['harmony'][0]['root_pc'] = 1
    # 吉他既有规则闭环修复：修改为项目既有unittest异常检查。
    # with pytest.raises(ValueError, match='已改变'):
    with unittest.TestCase().assertRaisesRegex(ValueError, '已改变'):
        revise_guitar_arrangement(first)


def test_guitar_view_does_not_change_shared_or_piano_harmony():
    original = fixture_project()
    result, _ = revise_guitar_arrangement(original)
    assert guitar_shared_view(result)['harmony'] == result['arrangements']['guitar']['readable_harmony']
    assert result['shared_analysis']['harmony'] == original['shared_analysis']['harmony']


def test_negative_source_seconds_do_not_borrow_first_recording_frame():
    project = fixture_project()
    project['accepted_vocal_project']['timing']['score_start_quarter'] = -4.
    class ForbiddenFirstFrame:
        def chroma(self, *args):
            raise AssertionError('无录音区间不应读取首帧')
    row = SourceEvidence(project, {'accompaniment': ForbiddenFirstFrame()}).at(0, 480)
    assert row['available'] is False
    assert np.sum(row['chroma']) == 0


def test_fret_and_source_binding_conflicts_are_not_silent_fallbacks():
    # 吉他既有规则闭环修复：新增12品及来源身份硬界限的反例，不能回退到宽松路线。
    project = fixture_project()
    project['arrangements']['guitar']['notes'][0]['fret'] = 13
    with unittest.TestCase().assertRaisesRegex(ValueError, '12品'):
        revise_guitar_arrangement(project)
    project = fixture_project()
    project['shared_analysis']['input_binding'] = {'sources': {'bass': {'sha256': 'correct'}}}
    class WrongRecording:
        source = {'sha256': 'wrong'}
    with unittest.TestCase().assertRaisesRegex(ValueError, '音源不一致'):
        revise_guitar_arrangement(project, {'bass': WrongRecording()})


def test_fresh_search_shape_obeys_real_diagram_schema_and_visible_frets():
    # 吉他既有规则闭环修复：新增真实生产绘图器与可见黑点回读，不手工补齐候选缺失字段。
    project = fixture_project()
    project['arrangements']['guitar']['fingering_diagrams'] = []
    result, _ = revise_guitar_arrangement(project)
    for chart in result['arrangements']['guitar']['fingering_diagrams']:
        placed = {**chart, 'display_id': chart['id'], 'draw_tick': chart['start_tick'],
                  'display_end_tick': chart['end_tick']}
        decoded = read_diagram(draw_diagram(placed, 100))
        assert decoded['frets'] == {s: chart['frets'].get(str(s), -1) for s in range(1, 7)}
        assert decoded['position'] >= 1


def test_actual_isolated_project_generated_diagrams_can_render_and_read_back():
    # 吉他既有规则闭环修复：新增真实已认可工程作为集成夹具；曲名仅定位测试材料，不进入生产答案。
    source = Path(__file__).resolve().parents[1] / 'test_outputs/accompaniment_runs/20261015_minimal_clock_lyric_accompaniment/我不难过/time_revision_v5_readable/project.json'
    if not source.exists():
        raise unittest.SkipTest('本机实际来源工程未提供；独立图式schema测试仍执行')
    project = json.loads(source.read_text(encoding='utf8'))
    result, _ = revise_guitar_arrangement(project)
    charts = result['arrangements']['guitar']['fingering_diagrams']
    assert charts
    for chart in charts:
        placed = {**chart, 'display_id': chart['id'], 'draw_tick': chart['start_tick'],
                  'display_end_tick': chart['end_tick']}
        decoded = read_diagram(draw_diagram(placed, 100))
        assert decoded['frets'] == {s: chart['frets'].get(str(s), -1) for s in range(1, 7)}


def test_three_and_four_string_shapes_keep_four_slot_bass_groups():
    # 吉他既有规则闭环修复：新增三弦不缩成六格反例，握法少一根弦不能改变右手循环拍长。
    chord = {'root_pc': 0, 'bass_pc': 0, 'pitch_classes': [0, 4, 7]}
    shapes = [{'capo': 0, 'frets': {'3': 5, '2': 5, '1': 3}},
              {'capo': 0, 'frets': {'5': 3, '3': 0, '2': 1, '1': 0}}]
    for shape in shapes:
        sequence = _pattern_strings(shape, chord)
        assert len(sequence) == 8
        assert [i for i, string in enumerate(sequence) if string == sequence[0]] == [0, 4]
        assert [i * 120 for i, string in enumerate(sequence) if string == sequence[0]] == [0, 480]
        assert [i * 240 for i, string in enumerate(sequence) if string == sequence[0]] == [0, 960]


def test_short_attack_prevents_early_new_root_but_allows_independently_supported_correction():
    # 吉他既有规则闭环修复：新增原唱段首半拍仍C、后半拍G的反例；整拍平均不能提前换根。
    project = fixture_project(1)
    current, following = project['shared_analysis']['harmony']
    current.update(quality='', pitch_classes=[0, 4, 7], name='C')
    following.update(root_pc=7, bass_pc=7, quality='', pitch_classes=[7, 11, 2], name='G')
    class BassRecording:
        source = {'sha256': 'synthetic_source_bound_test'}
        def __init__(self, old_root_really_wrong=False):
            self.old_root_really_wrong = old_root_really_wrong
        def chroma(self, a, b, *args):
            values = np.zeros(12)
            values[0 if b <= .26 and not self.old_root_really_wrong else 7] = .95
            return values
    result, _ = revise_guitar_arrangement(project, {'bass': BassRecording()})
    bass = [n for n in result['arrangements']['guitar']['notes'] if n['role'] == 'bass']
    assert bass[0]['start_tick'] == 0 and bass[0]['pitch_midi'] % 12 == 0
    assert all(n['start_tick'] >= 480 for n in bass if n['pitch_midi'] % 12 == 7)
    corrected, _ = revise_guitar_arrangement(project, {'bass': BassRecording(old_root_really_wrong=True)})
    corrected_bass = [n for n in corrected['arrangements']['guitar']['notes'] if n['role'] == 'bass']
    assert corrected_bass[0]['pitch_midi'] % 12 == 7


def test_actual_existing_inversion_is_preserved_even_when_old_chord_label_omits_it():
    # 吉他既有规则闭环修复：新增原实A是F三音但标签仍F的反例；不能机械把实低音改回标签F。
    project = fixture_project(1)
    for h in project['shared_analysis']['harmony']:
        h.update(root_pc=5, bass_pc=5, quality='', pitch_classes=[5, 9, 0], name='F')
    for n in project['arrangements']['guitar']['notes']:
        if n['role'] == 'bass':
            n.update(pitch_midi=45, string=5, fret=0)
    class BassRecording:
        source = {'sha256': 'synthetic_inversion_source'}
        def chroma(self, *args):
            values = np.zeros(12)
            values[9] = .8
            values[5] = .05
            return values
    result, _ = revise_guitar_arrangement(project, {'bass': BassRecording()})
    guitar = result['arrangements']['guitar']
    assert all(n['pitch_midi'] % 12 == 9 for n in guitar['notes'] if n['role'] == 'bass')
    assert all(h['root_pc'] == 5 and h['bass_pc'] == 9 for h in guitar['readable_harmony'])
    assert all(h['start_tick'] % 480 == 0 and h['end_tick'] - h['start_tick'] >= 480 for h in guitar['readable_harmony'])


def test_source_bass_short_and_sustained_windows_cannot_cancel_each_other():
    # 吉他既有规则闭环修复：新增120tick音头D、240tick平均Eb的反例，短音真实支持不得被长窗冲掉。
    project = fixture_project(1)
    project['arrangements']['guitar']['notes'][0].update(pitch_midi=50, string=4, fret=0)
    class BassRecording:
        def chroma(self, a, b, *args):
            values = np.zeros(12)
            values[2] = .9 if b <= .26 else .6
            values[3] = .02 if b <= .26 else .3
            return values
    evidence = SourceEvidence(project, {'bass': BassRecording()})
    evidence.pattern_periods = [(0, 1920, 480)]
    assert not evidence.bass_allowed({'bass_pc': 3}, 0, 480)
    assert evidence.bass_allowed({'bass_pc': 2}, 0, 480)


def test_strong_existing_bass_survives_a_slightly_higher_neighboring_pitch_peak():
    # 吉他既有规则闭环修复：新增滑音/分离音高峰偏移反例，原低音相对仍强不能因非最大峰而失去保护。
    class BassRecording:
        def chroma(self, *args):
            values = np.zeros(12)
            values[0], values[1], values[11] = .7, .9, .1
            return values
    evidence = SourceEvidence(fixture_project(1), {'bass': BassRecording()})
    assert evidence.bass_anchor(0, 480)['supported']
    assert evidence.bass_anchor(0, 480)['dominant_pc'] == 0
    assert not evidence.bass_allowed({'bass_pc': 11}, 0, 480)


def test_old_policy_output_cannot_claim_idempotent_success_after_upgrade():
    # 吉他既有规则闭环修复：新增旧策略重放反例；音符未改也必须从明确祖先重新执行新护栏。
    result, _ = revise_guitar_arrangement(fixture_project())
    result['arrangements']['guitar']['guitar_readability_revision']['version'] = POLICY['version'] - 1
    with unittest.TestCase().assertRaisesRegex(ValueError, '旧编配策略版本'):
        revise_guitar_arrangement(result)


def test_low_fret_shape_does_not_drop_existing_bass_register_to_save_two_strings():
    # 吉他既有规则闭环修复：新增同为低品的三弦高F与完整低F反例；不能为少按两弦丢失原低音音区。
    project = fixture_project(1)
    guitar = project['arrangements']['guitar']
    guitar['notes'][0].update(pitch_midi=41, string=6, fret=1)
    guitar['fingering_diagrams'] = [{'frets': {'4': 3, '3': 2, '2': 1}, 'position': 1}]
    chord = {**project['shared_analysis']['harmony'][0], 'root_pc': 5, 'bass_pc': 5,
             'quality': '', 'pitch_classes': [5, 9, 0], 'name': 'F'}
    shape = _shape(chord, guitar, 0, {})
    assert shape['readable_bass_register']['selected_pitch_midi'] == 41
    assert max(shape['frets'].values()) <= 4


def test_common_upper_template_rewrites_real_pitches_and_keeps_first_bass():
    # 吉他既有规则闭环修复：新增同基础C和弦仅后半小节C/E不同的复用正例；上声部须真换弦音而非改角色。
    project = fixture_project(16, repeated=True)
    for n in project['arrangements']['guitar']['notes']:
        if n['start_tick'] == 16320 and n['role'] == 'bass':
            n.update(pitch_midi=52, string=4, fret=2)
    class BassRecording:
        source = {'sha256': 'synthetic_shared_inversion_source'}
        def chroma(self, a, b, *args):
            values = np.zeros(12)
            values[4 if 34 <= a < 36 else 0] = .95
            return values
    result, audit = revise_guitar_arrangement(project, {'bass': BassRecording()})
    notes = result['arrangements']['guitar']['notes']
    blocks = [[n for n in notes if start <= n['start_tick'] < start + 1920] for start in [0, 15360]]
    assert any(s.get('common_upper_simplification') for s in audit['shared_bars'])
    assert len(blocks[0]) == len(blocks[1]) == 8
    for block in blocks:
        assert block[0]['role'] == 'bass' and block[0]['pitch_midi'] % 12 == 0
        assert all(n['role'] == 'harmony' and n['string'] <= 3 and
                   n['pitch_midi'] >= block[0]['pitch_midi'] + 7 for n in block[1:])
    assert [(n['pitch_midi'], n['string'], n['fret']) for n in blocks[0]] == [(n['pitch_midi'], n['string'], n['fret']) for n in blocks[1]]


def test_common_upper_omission_cannot_hide_a_different_first_bass_or_weak_upper_source():
    # 吉他既有规则闭环修复：新增首拍转位不同及上声部无原音支持的反例；不为凑反复扩大省略范围。
    from guitar_readable_arrangement import _common_upper_only
    project = fixture_project(2)
    bars = project['accepted_vocal_project']['timing']['measure_timeline']
    chord = copy.deepcopy(project['shared_analysis']['harmony'][1])
    plans = {m['number']: [{**chord, 'start_tick': m['start_tick'], 'end_tick': m['end_tick']}] for m in bars}
    plans[2][0]['bass_pc'] = 4
    assert _common_upper_only(bars, plans, SourceEvidence(project, None)) is None
    plans[2] = [{**chord, 'start_tick': 1920, 'end_tick': 2880},
                {**chord, 'start_tick': 2880, 'end_tick': 3840, 'bass_pc': 4}]
    project['shared_analysis']['harmony_windows'][1]['chroma'] = [1.] + [0.] * 11
    assert _common_upper_only(bars, plans, SourceEvidence(project, None)) is None


def load_tests(loader, standard_tests, pattern):
    # 吉他既有规则闭环修复：新增函数案例接入unittest发现，保持现有全套测试可运行。
    return unittest.TestSuite(unittest.FunctionTestCase(value) for name, value in globals().items()
                              if name.startswith('test_') and callable(value))


if __name__ == '__main__':
    # 吉他既有规则闭环修复：新增可单独重放的真实规则反例集。
    unittest.main()
