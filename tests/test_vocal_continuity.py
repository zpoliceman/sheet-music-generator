"""人声连续音值与长休止漏音通用修复：跨拍速／音域、串音、真休止及严格保留反例。"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
# 人声连续音值与长休止漏音通用修复：新增工作区内私有测试临时根，避免Windows系统临时目录沙箱权限。
TEST_TMP = (ROOT / 'test_outputs/accompaniment_runs/20261011_vocal_continuity_fix/test_tmp').resolve()
if not TEST_TMP.is_relative_to(ROOT):
    raise RuntimeError('测试临时目录必须位于当前工作区。')
TEST_TMP.mkdir(parents=True, exist_ok=True)
from score_export import sha256, TempoMap
from vocal_continuity import recover_rest_tails, repair_continuity, SourceVerifier, allocate_boundaries
# 人声连续音值与长休止漏音通用修复：修改，原导入保留；补充局部修复伴奏关联的篡改反例。
# from vocal_continuity_project import derive_continuity_vocal, source_dependencies, POLICY
from vocal_continuity_project import derive_continuity_vocal, source_dependencies, POLICY, accompaniment_revision_compatible

# 人声连续音值与长休止漏音通用修复：新增独立合成原秒真值，文字仅任意标签，无样曲答案。
def fixture(period=.7, pitch=61, recovered_pitch=63, split=False):
    heads = [0., 1.5 * period, 2.5 * period]
    notes = [dict(id='a', source_note_id='a', start_seconds=0., end_seconds=1.5 * period,
                  pitch_midi=pitch, lyric_index=0, line_index=0, role='main', anchor=True,
                  grace=False, start_tick=0, end_tick=480, playback_start_tick=0, playback_end_tick=480,
                  confidence=.95, stable_duration_seconds=1.4 * period),
             dict(id='b', source_note_id='b', start_seconds=heads[1], end_seconds=heads[2],
                  pitch_midi=pitch+2, lyric_index=1, line_index=0, role='main', anchor=True,
                  grace=False, start_tick=720, end_tick=1200, playback_start_tick=720, playback_end_tick=1200,
                  confidence=.95, stable_duration_seconds=.8 * period)]
    if split:
        notes[0].update(end_seconds=period, end_tick=240, playback_end_tick=240, anchor=False, role='turn')
        notes.insert(1, dict(notes[0], id='a2', source_note_id='a2', start_seconds=period,
                            end_seconds=1.5 * period, start_tick=240, end_tick=480,
                            playback_start_tick=240, playback_end_tick=480,
                            pitch_midi=pitch+1, role='main', anchor=True))
    chars = [dict(index=i, text=chr(0x5400+i), start_seconds=s, end_seconds=e, line_index=0,
                  phonemes=[dict(role='nucleus', start_seconds=s, end_seconds=e)])
             for i, (s, e) in enumerate(zip(heads, heads[1:]+[3 * period]))]
    base = {'quantized_notes': notes, 'lyrics': {'characters': chars},
            'timing': {'meter': [4, 4], 'score_start_quarter': 0., 'steady_tempo_bpm': 60 / period,
                       'knots': [{'seconds': 0., 'quarter': 0.}, {'seconds': 8 * period, 'quarter': 8.}]},
            'statistics': {'total_ticks': 3840, 'bar_ticks': 1920}, 'decoder': {}}
    frames = []
    for t in np.arange(0., 8 * period, .005):
        p = pitch if t < period and split else pitch+1 if t < 1.5*period and split else pitch
        frames.append({'time_seconds': float(t), 'f0_hz': float(440 * 2**((p-69)/12)) if t < 1.5*period else 0.})
    analysis = {'configuration': {'frame_step_seconds': .005}, 'pitch_frames': frames, 'notes': []}
    return base, analysis, {'vocal_project_sha256': 'synthetic_source'}


# 人声连续音值与长休止漏音通用修复：新增漏音夹具，独立原平台位于长休止内，整体平均率不足仍可局部复核。
def tail_fixture(period=.7, pitch=61, recovered_pitch=63):
    base, analysis, binding = fixture(period, pitch)
    base['quantized_notes'] = base['quantized_notes'][:1]
    base['quantized_notes'][0].update(end_seconds=.5*period, end_tick=480, playback_end_tick=480)
    base['lyrics']['characters'] = base['lyrics']['characters'][:1]
    base['lyrics']['characters'][0]['end_seconds'] = 1.5*period
    base['lyrics']['characters'][0]['phonemes'][0]['end_seconds'] = 1.5*period
    analysis['notes'] = [dict(id='source_rest', is_rest=True, pitch_midi=0,
                              start_seconds=.5*period, end_seconds=24., quality={'voiced_fraction': .01})]
    for frame in analysis['pitch_frames']:
        t = frame['time_seconds']
        if .5*period <= t < 1.5*period:
            frame['f0_hz'] = 440 * 2**((recovered_pitch-69)/12)
    return base, analysis, binding


# 人声连续音值与长休止漏音通用修复：新增各证据门限替身；真实YIN／原轨SNR另有实际音域测试。
def supported(core):
    return {'yin_agreement': .96, 'vocal_dbfs': -25., 'foreground_ratio_db': 4.,
            'independent_source_audio_checked': True}


class VocalContinuityTests(unittest.TestCase):
    def test_continuous_tail_removes_false_rest_across_tempo_and_pitch(self):
        for period, pitch in [(.45, 48), (.7, 65), (1.2, 78)]:
            base, analysis, binding = fixture(period, pitch)
            original = deepcopy(base)
            updated, audit = repair_continuity(base, binding, analysis=analysis, verifier=supported)
            self.assertEqual(updated['quantized_notes'][0]['end_tick'], 720)
            self.assertEqual(updated['quantized_notes'][1], base['quantized_notes'][1])
            self.assertEqual(updated['timing'], base['timing']); self.assertEqual(base, original)
            self.assertEqual(len(audit['changes']), 1)

    def test_absolute_internal_boundary_does_not_advance_main_tone(self):
        base, analysis, binding = fixture(split=True)
        updated, _ = repair_continuity(base, binding, analysis=analysis, verifier=supported)
        self.assertEqual([(n['start_tick'], n['end_tick']) for n in updated['quantized_notes'][:2]], [(0,480),(480,720)])

    def test_actual_silent_gap_is_preserved(self):
        base, analysis, binding = fixture()
        base['quantized_notes'][0]['end_seconds'] = .7
        updated, audit = repair_continuity(base, binding, analysis=analysis, verifier=supported)
        self.assertEqual(updated, base); self.assertEqual(audit['changes'], [])

    def test_unknown_voice_support_does_not_fill_notated_rest(self):
        base, analysis, binding = fixture(); analysis['pitch_frames'] = []
        updated, audit = repair_continuity(base, binding, analysis=analysis, verifier=supported)
        self.assertEqual(updated, base)
        self.assertEqual(audit['changes'][0]['action'], 'preserve_insufficient_continuous_voice')

    def test_source_bound_review_preserves_complete_fields(self):
        base, analysis, binding = fixture()
        review = {'schema_version':1, 'action':'preserve_unresolved_notation',
                  'source_vocal_project_sha256':'synthetic_source', 'notes':[deepcopy(base['quantized_notes'][0])]}
        updated, _ = repair_continuity(base, binding, review, analysis, supported)
        self.assertEqual(updated, base)

    def test_review_of_different_source_is_rejected(self):
        base, analysis, binding = fixture()
        review = {'schema_version':1, 'action':'preserve_unresolved_notation', 'source_vocal_project_sha256':'wrong', 'notes':[]}
        with self.assertRaises(ValueError):
            repair_continuity(base, binding, review, analysis, supported)

    def test_local_tail_is_recovered_despite_long_rest_average(self):
        base, analysis, binding = tail_fixture()
        updated, audit = repair_continuity(base, binding, analysis=analysis, verifier=supported)
        self.assertEqual(len(updated['quantized_notes']), 2)
        self.assertEqual(updated['quantized_notes'][1]['pitch_midi'], 63)
        self.assertEqual(updated['quantized_notes'][1]['source_note_id'], 'source_rest')
        self.assertEqual(updated['quantized_notes'][1]['start_tick'], 240)
        self.assertTrue(audit['source_clock_preserved'])

    def test_recovered_tail_preserves_existing_source_seconds_and_pitch(self):
        base, analysis, binding = tail_fixture()
        updated, _ = repair_continuity(base, binding, analysis=analysis, verifier=supported)
        for field in ['id','source_note_id','start_seconds','end_seconds','pitch_midi','lyric_index']:
            self.assertEqual(updated['quantized_notes'][0][field], base['quantized_notes'][0][field])

    def test_tone_already_present_is_not_duplicated(self):
        base, analysis, binding = tail_fixture()
        updated, _ = repair_continuity(base, binding, analysis=analysis, verifier=supported)
        twice, audit = repair_continuity(updated, binding, analysis=analysis, verifier=supported)
        self.assertEqual(twice, updated); self.assertEqual(audit['recovered_note_ids'], [])

    def test_matching_yin_instrument_bleed_is_rejected(self):
        base, analysis, binding = tail_fixture()
        updated, audit = repair_continuity(base, binding, analysis=analysis,
                                           verifier=lambda c: dict(supported(c), foreground_ratio_db=-24.))
        self.assertEqual(updated, base)
        self.assertEqual(audit['recovery'][0]['action'], 'reject_weak_or_bleed_evidence')

    def test_independent_pitch_disagreement_is_rejected(self):
        base, analysis, binding = tail_fixture()
        updated, _ = repair_continuity(base, binding, analysis=analysis,
                                        verifier=lambda c: dict(supported(c), yin_agreement=.30))
        self.assertEqual(updated, base)

    def test_no_actual_audio_confirmation_is_not_automatic_recovery(self):
        base, analysis, binding = tail_fixture()
        updated, _ = repair_continuity(base, binding, analysis=analysis,
                                        verifier=lambda c: dict(supported(c), independent_source_audio_checked=False))
        self.assertEqual(updated, base)

    def test_no_nucleus_or_vocal_neighbor_does_not_use_lyrics_as_truth(self):
        for which in ('nucleus', 'neighbor'):
            base, analysis, _ = tail_fixture()
            if which == 'nucleus':
                base['lyrics']['characters'][0]['phonemes'] = []
            else:
                base['quantized_notes'] = []
            notes, _ = recover_rest_tails(analysis, base['lyrics']['characters'], base['quantized_notes'], .7, supported)
            self.assertEqual(notes, [])

    def test_long_disconnected_platform_is_not_appended_to_word(self):
        base, analysis, _ = tail_fixture()
        base['quantized_notes'][0]['end_seconds'] = .1
        notes, _ = recover_rest_tails(analysis, base['lyrics']['characters'], base['quantized_notes'], .7, supported)
        self.assertEqual(notes, [])

    # 人声连续音值与长休止漏音通用修复：修改，原只查显示延音的测试注释保留；主谱保留同音未决，避免物理MIDI多一次重发。
    # def test_same_pitch_recovery_ties_instead_of_false_reattack(self):
    #     base, analysis, binding = tail_fixture(recovered_pitch=61)
    #     updated, _ = repair_continuity(base, binding, analysis=analysis, verifier=supported)
    #     first = [e for e in updated['events'] if e.get('piece_id') == 'a'][-1]
    #     later = [e for e in updated['events'] if (e.get('piece_id') or '').startswith('source_rest')][0]
    #     self.assertIn('start', first['ties']); self.assertIn('stop', later['ties'])
    def test_same_pitch_tail_does_not_add_an_unproven_midi_reattack(self):
        base, analysis, binding = tail_fixture(recovered_pitch=61)
        updated, audit = repair_continuity(base, binding, analysis=analysis, verifier=supported)
        self.assertEqual(updated, base)
        self.assertEqual(audit['recovery'][0]['action'], 'same_pitch_tail_requires_duration_review')

    def test_existing_real_short_tones_keep_their_fine_boundaries(self):
        mapping=TempoMap([{'seconds':0.,'quarter':0.},{'seconds':4.,'quarter':4.}])
        notes=[dict(start_seconds=a,end_seconds=b,start_tick=round(a*480),end_tick=round(b*480))
               for a,b in [(0.,.125),(.125,.25),(.25,.75)]]
        self.assertEqual(allocate_boundaries(notes,0,360,mapping,0.),(60,60,240))

    def test_text_changes_have_no_effect_on_selected_notes(self):
        base, analysis, binding = tail_fixture(); changed = deepcopy(base)
        changed['lyrics']['characters'][0]['text'] = 'unrelated English word'
        one, _ = repair_continuity(base, binding, analysis=analysis, verifier=supported)
        two, _ = repair_continuity(changed, binding, analysis=analysis, verifier=supported)
        self.assertEqual(one['quantized_notes'], two['quantized_notes'])

    def test_invalid_source_duration_does_not_export(self):
        note = dict(start_seconds=1.,end_seconds=.5)
        with self.assertRaises(ValueError):
            allocate_boundaries([note],0,480,TempoMap([{'seconds':0,'quarter':0},{'seconds':4,'quarter':4}]),0.)

    def test_modified_policy_rejected_before_reconstruction(self):
        correction = dict(version=1, policy=deepcopy(POLICY), source_vocal_project_sha256='source', source_fingerprints={})
        correction['policy']['voice_policy']['minimum_yin_agreement'] = 0.
        with self.assertRaises(ValueError):
            derive_continuity_vocal({}, {'vocal_project_sha256':'source','sources':{}}, correction)

    # 人声连续音值与长休止漏音通用修复：新增伴奏只在完整派生关联匹配时保留，不能盲改旧人声指纹。
    def test_explicit_accompaniment_revision_detects_note_tampering(self):
        from phrase_harmony_plan import vocal_fingerprint
        base, analysis, binding = fixture()
        updated, evidence = repair_continuity(base,binding,analysis=analysis,verifier=supported)
        before, after = vocal_fingerprint(base), vocal_fingerprint(updated)
        updated['vocal_continuity_correction']={'policy':deepcopy(POLICY),'base_vocal_sha256':before,
                                               'derived_vocal_sha256':after,'evidence':evidence}
        plan={'source_vocal_sha256':before,'vocal_revision_compatibility':{
            'version':1,'action':'preserve_accepted_accompaniment_after_source_bound_local_vocal_repair',
            'base_vocal_sha256':before,'derived_vocal_sha256':after,'harmony_reselected':False}}
        self.assertTrue(accompaniment_revision_compatible(plan,updated))
        updated['quantized_notes'][0]['pitch_midi']+=1
        self.assertFalse(accompaniment_revision_compatible(plan,updated))

    def test_unrelated_accompaniment_plan_is_not_compatible(self):
        from phrase_harmony_plan import vocal_fingerprint
        base,analysis,binding=fixture()
        updated,evidence=repair_continuity(base,binding,analysis=analysis,verifier=supported)
        updated['vocal_continuity_correction']={'policy':deepcopy(POLICY),'base_vocal_sha256':'base',
                                               'derived_vocal_sha256':vocal_fingerprint(updated),'evidence':evidence}
        plan={'source_vocal_sha256':'different','vocal_revision_compatibility':{
            'version':1,'action':'preserve_accepted_accompaniment_after_source_bound_local_vocal_repair',
            'base_vocal_sha256':'base','derived_vocal_sha256':vocal_fingerprint(updated),'harmony_reselected':False}}
        self.assertFalse(accompaniment_revision_compatible(plan,updated))

    def test_modified_pitch_cache_rejected(self):
        # 人声连续音值与长休止漏音通用修复：修改，原系统临时目录保留；只在已校验工作区根内创建与清理。
        # with tempfile.TemporaryDirectory() as folder:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as folder:
            path = Path(folder) / 'analysis.json'; path.write_text('{}','utf8')
            vocal = {'inputs': {'notes_path':str(path),'notes_sha256':'altered'}}
            with self.assertRaises(ValueError): source_dependencies(vocal)

    def test_independent_yin_across_low_and_high_registers(self):
        import soundfile as sf
        for pitch in (40, 64, 80):
            # 人声连续音值与长休止漏音通用修复：修改，原系统临时目录保留；实际音轨测试使用工作区私有根。
            # with tempfile.TemporaryDirectory() as folder:
            with tempfile.TemporaryDirectory(dir=TEST_TMP) as folder:
                path = Path(folder); rate=24000; times=np.arange(rate*2)/rate
                frequency=440 * 2**((pitch-69)/12)
                phase=2*np.pi*frequency*times + .025*np.sin(2*np.pi*5*times)
                voice=.12*np.sin(phase)+.05*np.sin(2*phase)
                sf.write(path/'voice.wav',voice,rate,subtype='FLOAT')
                sf.write(path/'accomp.wav',voice*.04,rate,subtype='FLOAT')
                sources={name:{'path':str(path/file),'sha256':sha256(path/file)}
                         for name,file in [('vocals','voice.wav'),('accompaniment','accomp.wav')]}
                verifier=SourceVerifier({'sources':sources},{'source':sources['vocals']})
                result=verifier({'start_seconds':.4,'end_seconds':1.5,'pitch_midi':pitch})
                self.assertGreater(result['yin_agreement'],.9); self.assertGreater(result['foreground_ratio_db'],15.)

if __name__ == '__main__':
    unittest.main()
