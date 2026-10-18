"""原曲拍轴与歌词拍位通用修复：独立拍序、真实字头、跨字音、硬时序边界和安全生成反例。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import sys
import tempfile
import unittest
import numpy as np

# 原曲拍轴与歌词拍位通用修复：新增测试仅使用独立合成声音／任意字，不用歌曲答案作为生产输入。
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from source_meter_clock import periodic_candidate, robust_pulse_fit, infer_source_clock
from source_vocal_rebuild import prepare_pieces, rebuild_source_vocal, quantize_source_notes
from source_meter_project import derive_source_vocal, POLICY as PROJECT_POLICY
from score_export import sha256, TempoMap
from generate_accompaniment import piano_copy_source, generate
from guitar_repeat_edition import notation_only_request


# 原曲拍轴与歌词拍位通用修复：新增项目内隔离临时目录，避开Windows受限的系统Temp；清理路径先确认在工作区内。
def temporary_workspace():
    folder = (ROOT / 'test_outputs/accompaniment_runs/tests').resolve()
    folder.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(dir=folder, prefix='source_meter_')
    if not Path(temporary.name).resolve().is_relative_to(folder):
        raise ValueError('测试临时目录越出工作区。')
    return temporary


# 原曲拍轴与歌词拍位通用修复：新增任意可变拍速／缺攻击／额外弱拍的原秒证据。
def pulse_rows(bpm, offset=.13):
    period = 60 / bpm
    result = [{'seconds': offset + i * period, 'strength': 1. + .2 * (i % 4 == 0)}
              for i in range(180) if i % 13 != 7]
    result += [{'seconds': offset + (i + .5) * period, 'strength': .12} for i in range(0, 180, 3)]
    return sorted(result, key=lambda row: row['seconds'])


# 原曲拍轴与歌词拍位通用修复：新增真实f0／音素夹具与绑定SHA，支持检查静音、滑音和连续跨字音。
def voice_fixture(folder, spans, chars, voiced=None, duration=4., period=.5):
    notes = []
    for i, (a, b, owner, grace) in enumerate(spans):
        notes.append({'id': 'n' + str(i), 'source_note_id': 's' + str(i), 'pitch_midi': 60,
            'source_pitch_midi': 60, 'start_seconds': a, 'end_seconds': b,
            'lyric_index': owner, 'line_index': 0, 'grace': grace, 'role': 'grace' if grace else 'main',
            'anchor': not grace, 'confidence': .9, 'start_tick': round(a / period * 480),
            'end_tick': round(b / period * 480), 'playback_start_tick': round(a / period * 480),
            'playback_end_tick': round(b / period * 480)})
    for i, n in enumerate(notes):
        if n['grace']:
            n['anchor_id'] = notes[i + 1]['id']
    chars = [{'index': i, 'text': chr(0x4e00 + i), 'line_index': 0, 'start_seconds': a, 'end_seconds': b,
        'phonemes': [{'role': 'voiced_initial', 'start_seconds': a, 'end_seconds': a + .02},
                     {'role': 'nucleus', 'start_seconds': a + .02, 'end_seconds': b}]} for i, (a, b) in enumerate(chars)]
    frames = []
    for t in np.arange(0, duration, .005):
        active = any(a <= t < b for a, b in (voiced or [(a, b) for a, b, _, _ in spans]))
        frames.append({'time_seconds': float(t), 'f0_hz': 261.625565 if active else 0.})
    analysis = folder / 'notes.json'; analysis.write_text(json.dumps({'pitch_frames': frames}), encoding='utf-8')
    lyrics = folder / 'lyrics.json'; lyrics.write_text(json.dumps({'characters': chars}), encoding='utf-8')
    timing = {'meter': [4, 4], 'score_start_quarter': 0., 'steady_tempo_bpm': 60 / period,
        'knots': [{'quarter': 0., 'seconds': 0.}, {'quarter': 1., 'seconds': period}]}
    base = {'quantized_notes': notes, 'lyrics': {'characters': chars}, 'timing': deepcopy(timing),
        'inputs': {'notes_path': str(analysis), 'notes_sha256': sha256(analysis),
                   'lyrics_path': str(lyrics), 'lyrics_sha256': sha256(lyrics)},
        'audio_analysis': {'duration_seconds': duration}, 'notation': {'key_segments': []},
        'decoder': {}, 'statistics': {'bar_ticks': 1920, 'total_ticks': 7680}}
    return base, timing


class IndependentPulseTests(unittest.TestCase):
    # 原曲拍轴与歌词拍位通用修复：新增检测数组不是音乐拍号的反例，缺拍和额外弱拍都不能使速度累计漂移。
    def test_missing_and_extra_attacks_do_not_change_true_period(self):
        for bpm in (83., 119., 147.):
            attacks = pulse_rows(bpm)
            candidate = periodic_candidate(attacks, bpm * 1.008)
            self.assertEqual(candidate['status'], 'periodic')
            phase, period, witnesses = robust_pulse_fit(attacks, candidate)
            self.assertAlmostEqual(60 / period, bpm, places=5)
            self.assertGreater(len(witnesses), 150)
            self.assertLess(max(abs(w['residual_seconds']) for w in witnesses), 1e-7)

    # 原曲拍轴与歌词拍位通用修复：新增未知来源不得把先前拍轴误称作校准，低覆盖明确失败。
    def test_sparse_events_are_not_certified(self):
        self.assertEqual(periodic_candidate(pulse_rows(120)[:4], 120)['status'], 'insufficient_attacks')

    # 原曲拍轴与歌词拍位通用修复：新增歌名／文字／旧谱速度变动不影响独立源结果。
    def test_old_notation_and_text_are_not_phase_inputs(self):
        attacks = pulse_rows(108)
        onset = {'drums_low': {'source': 'drums', 'attacks': attacks}}
        phase = {'status': 'independent_downbeat_supported', 'phase_beats': 0,
            'changes': [], 'phase_scores': [40., 0., 3., 0.], 'margin': .9}
        binding = {'sources': {'drums': {'sha256': 'source'}}}
        base = {'audio_analysis': {'tempo': {'bpm': 109.}}, 'timing': {'meter': [4, 4], 'steady_tempo_bpm': 200.,
            'score_start_quarter': -4., 'knots': [{'quarter': 0., 'seconds': 2.}, {'quarter': 1., 'seconds': 2.3}]}}
        with patch('source_meter_clock.extract_source_onsets', return_value=(onset, 'accompaniment')), patch('source_meter_clock.bass_phase_evidence', return_value=phase):
            a, evidence_a = infer_source_clock(base, binding, '.')
            renamed = deepcopy(base); renamed['title'] = '任意标题'; renamed['lyrics'] = {'text': '任意文字'}
            renamed['timing']['steady_tempo_bpm'] = 35.
            b, evidence_b = infer_source_clock(renamed, binding, '.')
        self.assertEqual(a['knots'], b['knots']); self.assertEqual(evidence_a, evidence_b)
        self.assertAlmostEqual(a['steady_tempo_bpm'], 108., places=5)

    # 原曲拍轴与歌词拍位通用修复：新增来源绑定人工首拍不可被自动重估覆盖。
    def test_reviewed_clock_is_retained_without_audio_reanalysis(self):
        base = {'timing': {'beat_phase': {'review_id': 'source_review'}, 'knots': [{'quarter': 0., 'seconds': 2.}]}}
        with patch('source_meter_clock.extract_source_onsets', side_effect=AssertionError('禁止重解人工首拍')):
            timing, evidence = infer_source_clock(base, {}, '.')
        self.assertEqual(timing, base['timing']); self.assertEqual(evidence['status'], 'reviewed_source_clock_retained')


class SourceVocalTests(unittest.TestCase):
    # 原曲拍轴与歌词拍位通用修复：新增有声元音首段不能零时值化，源音及旧输入保持。
    def test_voiced_syllable_head_gets_metered_lyric_and_duration(self):
        # 原曲拍轴与歌词拍位通用修复：修改，旧系统Temp保留；使用项目内隔离目录。
        # with tempfile.TemporaryDirectory() as temp:
        with temporary_workspace() as temp:
            base, timing = voice_fixture(Path(temp), [(1., 1.18, 0, True), (1.18, 1.7, 0, False)], [(1., 1.7)])
            old = deepcopy(base); output, audit = rebuild_source_vocal(base, timing)
            self.assertFalse(output['quantized_notes'][0]['grace'])
            first = next(e for e in output['events'] if e.get('lyric', {}).get('text'))
            self.assertEqual(first['piece_id'], 'n0'); self.assertEqual(first['start_tick'], 960)
            self.assertGreater(output['quantized_notes'][0]['playback_end_tick'] - output['quantized_notes'][0]['playback_start_tick'], 60)
            self.assertEqual(base, old); self.assertTrue(audit['source_identity_pitch_interval_preserved'])

    # 原曲拍轴与歌词拍位通用修复：新增无基频前缀不得形成早唱，实际源秒不覆盖。
    def test_unvoiced_prefix_is_excluded_from_musical_onset(self):
        # 原曲拍轴与歌词拍位通用修复：修改，旧系统Temp保留；使用项目内隔离目录。
        # with tempfile.TemporaryDirectory() as temp:
        with temporary_workspace() as temp:
            base, timing = voice_fixture(Path(temp), [(1., 1.7, 0, False)], [(1.3, 1.7)], voiced=[(1.34, 1.7)])
            out, _ = rebuild_source_vocal(base, timing); n = out['quantized_notes'][0]
            self.assertEqual(n['start_seconds'], 1.)
            self.assertGreaterEqual(TempoMap(timing['knots']).quarters_to_seconds(n['start_tick'] / 480), 1.25)
            self.assertAlmostEqual(n['notation_source_start_seconds'], 1.34, places=3)

    # 原曲拍轴与歌词拍位通用修复：新增滑音全程有声，即使暂离目标音高也不能当静音裁剪。
    def test_pitched_glide_does_not_get_trimmed_as_silence(self):
        # 原曲拍轴与歌词拍位通用修复：修改，旧系统Temp保留；使用项目内隔离目录。
        # with tempfile.TemporaryDirectory() as temp:
        with temporary_workspace() as temp:
            base, timing = voice_fixture(Path(temp), [(1., 1.7, 0, False)], [(1., 1.7)])
            path = Path(base['inputs']['notes_path']); raw = json.loads(path.read_text())
            for frame in raw['pitch_frames']:
                if 1 <= frame['time_seconds'] < 1.2:frame['f0_hz'] = 220.
            path.write_text(json.dumps(raw), encoding='utf-8'); base['inputs']['notes_sha256'] = sha256(path)
            notes, _ = prepare_pieces(base, timing)
            self.assertEqual(notes[0]['notation_source_start_seconds'], 1.)

    # 原曲拍轴与歌词拍位通用修复：新增跨字持音必须完整分区，不复制整段、丢源音或改音高。
    def test_continuous_tone_spanning_two_words_is_partitioned(self):
        # 原曲拍轴与歌词拍位通用修复：修改，旧系统Temp保留；使用项目内隔离目录。
        # with tempfile.TemporaryDirectory() as temp:
        with temporary_workspace() as temp:
            base, timing = voice_fixture(Path(temp), [(1.2, 1.75, 0, False), (1.75, 2., 1, False)], [(1.2, 1.38), (1.38, 2.)])
            out, audit = rebuild_source_vocal(base, timing)
            self.assertEqual(len(out['quantized_notes']), 3); self.assertEqual(len(audit['cross_word_splits']), 1)
            parts = [n for n in out['quantized_notes'] if n['rebuild_source_piece_id'] == 'n0']
            self.assertEqual([(n['start_seconds'], n['end_seconds']) for n in parts], [(1.2, 1.38), (1.38, 1.75)])
            self.assertTrue(all(n['pitch_midi'] == 60 for n in parts)); self.assertEqual(out['lyric_mapping']['mapped_characters'], 2)

    # 原曲拍轴与歌词拍位通用修复：新增确有十六分字头不能为粗格规整移走。
    def test_real_sixteenth_head_is_kept(self):
        # 原曲拍轴与歌词拍位通用修复：修改，旧系统Temp保留；使用项目内隔离目录。
        # with tempfile.TemporaryDirectory() as temp:
        with temporary_workspace() as temp:
            base, timing = voice_fixture(Path(temp), [(1.25, 1.8, 0, False)], [(1.25, 1.8)], period=1.)
            out, _ = rebuild_source_vocal(base, timing)
            self.assertEqual(out['quantized_notes'][0]['start_tick'], 600)

    # 原曲拍轴与歌词拍位通用修复：新增过密源音冲突必须拒绝，不能游标挤压或静默删音。
    def test_impossible_dense_notes_fail_instead_of_cursor_push(self):
        notes = [{'id': str(i), 'source_note_id': str(i), 'pitch_midi': 60, 'role': 'main', 'grace': False,
            'lyric_index': i, 'start_seconds': 1. + i * .005, 'end_seconds': 1. + (i + 1) * .005} for i in range(8)]
        timing = {'meter': [4, 4], 'steady_tempo_bpm': 120., 'score_start_quarter': 0., 'knots': [{'quarter': 0., 'seconds': 0.}, {'quarter': 1., 'seconds': .5}]}
        with self.assertRaisesRegex(ValueError, '真实起音联合网格冲突'):
            quantize_source_notes(notes, [], TempoMap(timing['knots']), timing, 3.)

    # 原曲拍轴与歌词拍位通用修复：新增源f0／音素篡改拒绝，不能换数据后沿用校正结果。
    def test_changed_source_analysis_is_rejected(self):
        # 原曲拍轴与歌词拍位通用修复：修改，旧系统Temp保留；使用项目内隔离目录。
        # with tempfile.TemporaryDirectory() as temp:
        with temporary_workspace() as temp:
            base, timing = voice_fixture(Path(temp), [(1., 1.7, 0, False)], [(1., 1.7)])
            Path(base['inputs']['notes_path']).write_text('{}')
            with self.assertRaisesRegex(ValueError, '源音段或音素已改变'):rebuild_source_vocal(base, timing)


class SafePipelineTests(unittest.TestCase):
    # 原曲拍轴与歌词拍位通用修复：新增工作种子绝不能进入钢琴复制分支。
    def test_work_seed_has_no_copyable_piano_delivery(self):
        # 原曲拍轴与歌词拍位通用修复：修改，旧系统Temp保留；使用项目内隔离目录。
        # with tempfile.TemporaryDirectory() as temp:
        with temporary_workspace() as temp:
            path = Path(temp) / 'seed.json'; path.write_text('{}')
            self.assertIsNone(piano_copy_source(path))

    # 原曲拍轴与歌词拍位通用修复：新增完整交付按实际文件SHA判断，损坏清单拒绝。
    def test_only_complete_verified_piano_package_can_be_copied(self):
        # 原曲拍轴与歌词拍位通用修复：修改，旧系统Temp保留；使用项目内隔离目录。
        # with tempfile.TemporaryDirectory() as temp:
        with temporary_workspace() as temp:
            root = Path(temp); path = root / 'project.json'; path.write_text('{}'); rows = []
            for name in ('piano/score.musicxml', 'piano/accompaniment.mid', 'piano/preview.wav', 'piano/score.html'):
                file = root / name; file.parent.mkdir(exist_ok=True); file.write_bytes(name.encode())
                rows.append({'path': name, 'sha256': sha256(file), 'bytes': file.stat().st_size})
            (root / 'manifest.json').write_text(json.dumps({'files': rows}))
            self.assertEqual(piano_copy_source(path), root.resolve())
            (root / 'piano/preview.wav').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '清单无效'):piano_copy_source(path)

    # 原曲拍轴与歌词拍位通用修复：新增音乐重建／独立简谱不得被反复排版快捷分支忽略。
    def test_explicit_rebuild_and_vocal_export_bypass_notation_only_path(self):
        for flag in ('rebuild_source_meter', 'export_vocal'):
            args = SimpleNamespace(**{flag: True}, edited_project='nonexistent.json')
            self.assertFalse(notation_only_request(args))

    # 原曲拍轴与歌词拍位通用修复：新增真正编配前必须确定新共同人声拍轴的执行顺序反例。
    def test_explicit_rebuild_precedes_first_new_arrangement(self):
        folder = ROOT / 'test_outputs/accompaniment_runs/tests'; folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            root = Path(temp); old = root / 'project.json'; old.write_text('{}')
            args = SimpleNamespace(edited_project=old, output=root / 'new', report=None, analysis_dir=root / 'cache',
                rebuild_source_meter=True, rearrange=False, capo=None, common_right_hand=False)
            shared, before, after = {'input_binding': {}}, {'stage': 'old'}, {'stage': 'new'}
            class StopAfterCorrectOrder(Exception):pass
            # 保音持续按弦与整句八度衔接：修改顺序反例接收新配音策略，并验证真正传入；原签名保留。
            # def arrange(fresh, vocal, capo):
            def arrange(fresh, vocal, capo, phrase_register=False):
                self.assertTrue(phrase_register)
                self.assertIs(vocal, after)
                raise StopAfterCorrectOrder()
            # 默认入口原曲节拍强制复核：修改，原阶段顺序夹具保留；虚拟准备结果的来源门槛由专门反例覆盖，这里只测顺序。
            # with patch('generate_accompaniment.load_edited_project', return_value=(shared, before, {})), patch('source_meter_project.rebuild_source_project', return_value=(shared, after)) as prepare, patch('generate_accompaniment.arrange_requested', side_effect=arrange):
            with patch('source_meter_entry.require_calibrated_source', return_value={'status':'test_verified'}), patch('generate_accompaniment.load_edited_project', return_value=(shared, before, {})), patch('source_meter_project.rebuild_source_project', return_value=(shared, after)) as prepare, patch('generate_accompaniment.arrange_requested', side_effect=arrange):
                with self.assertRaises(StopAfterCorrectOrder):generate(args)
                prepare.assert_called_once()

    # 原曲拍轴与歌词拍位通用修复：新增策略／来源篡改必须拒绝，即使用户提供了完整结果也不能绕过重放。
    def test_forged_policy_cannot_be_accepted(self):
        correction = {'version': 1, 'policy': {'arbitrary': True}, 'source_vocal_project_sha256': 'bound', 'source_fingerprints': {}}
        with self.assertRaisesRegex(ValueError, '版本／策略／来源不符'):
            derive_source_vocal({}, {'vocal_project_sha256': 'bound', 'sources': {}}, correction)


# 原曲拍轴与歌词拍位通用修复：新增真实持音冲突及正首拍完整原声反例，均使用任意合成音乐。
class SourceDeliveryBoundaryTests(unittest.TestCase):
    # 原曲拍轴与歌词拍位通用修复：新增完整首小节必须与页面说明一致，不能在修正拍轴后仍虚标弱起预备。
    def test_full_first_bar_is_not_labeled_as_pickup(self):
        from test_accompaniment import fixture
        from beat_phase_alignment import export_phase_vocal
        _,vocal=fixture()
        vocal['timing'].pop('initial_pickup_measure',None)
        with temporary_workspace() as temp:
            output=Path(temp);(output/'index.html').write_text('<h1>合成谱</h1><b>2</b>全曲小节',encoding='utf-8')
            export_phase_vocal(output,vocal)
            self.assertNotIn('弱起预备',(output/'index.html').read_text('utf-8'))
            self.assertNotIn('弱起预备',(output/'vocal/score.html').read_text('utf-8'))
            # 原曲拍轴与歌词拍位通用修复：新增重复导出及旧错误标签恢复核验。
            (output/'index.html').write_text((output/'index.html').read_text('utf-8').replace('全曲小节','正式小节 + 弱起预备'),encoding='utf-8')
            export_phase_vocal(output,vocal)
            entry=(output/'index.html').read_text('utf-8')
            self.assertNotIn('弱起预备',entry)
            self.assertEqual(entry.count('href="vocal/score.html"'),1)

    # 原曲拍轴与歌词拍位通用修复：新增当前能按但堵住下一音换把的填充反例，下一手位须在持音释放前可达。
    def test_fill_release_endpoint_respects_next_prepared_hand_position(self):
        from test_guitar_instrumental_flow import music
        from guitar_instrumental_flow import choose_fill
        from guitar_grip_policy import grip_position_path
        s,v,g=music(capo=2)
        g['notes']=[{'id':'m1','start_tick':0,'end_tick':480,'pitch_midi':64,'string':3,'fret':7,'finger':3,'role':'instrumental_melody'},
            {'id':'open','start_tick':240,'end_tick':480,'pitch_midi':52,'string':4,'fret':0,'finger':0,'role':'harmony'},
            {'id':'m2','start_tick':480,'end_tick':960,'pitch_midi':71,'string':2,'fret':10,'finger':3,'role':'instrumental_melody'}]
        g['hand_positions']=[{'tick':0,'position':2},{'tick':240,'position':2},{'tick':480,'position':6},{'tick':960,'position':6}]
        g['fingering_diagrams']=[]
        self.assertTrue(grip_position_path(g,v)['valid'])
        chord={'root_pc':9,'quality':'m','bass_pc':9,'pitch_classes':[9,0,4]}
        legacy=choose_fill(g['notes'],g,s,chord,240,480,6,True)
        self.assertEqual(legacy[0]['fret'],3)
        blocked=deepcopy(g);blocked['notes'].append({**legacy[0],'id':'fill','start_tick':240,'end_tick':480})
        self.assertFalse(grip_position_path(blocked,v)['valid'])
        g['configuration']['instrumental_flow_motion_version']=2
        selected=choose_fill(g['notes'],g,s,chord,240,480,6,True)
        self.assertIsNotNone(selected);self.assertGreaterEqual(selected[0]['fret'],6)
        safe=deepcopy(g);safe['notes'].append({**selected[0],'id':'fill','start_tick':240,'end_tick':480})
        self.assertTrue(grip_position_path(safe,v)['valid'])

    # 原曲拍轴与歌词拍位通用修复：新增器乐准备只读未定稿普通伴奏反例，旧认可保护入口不变。
    def test_provisional_rhythm_never_freezes_or_refingers_ordinary_prototype(self):
        from generate_accompaniment import regularize_provisional_instrumentals
        shared={'sections':[{'kind':'intro','start_tick':0,'end_tick':480}]}
        guitar={'notes':[{'id':'instrumental','start_tick':0,'end_tick':480},
            {'id':'ordinary','start_tick':480,'end_tick':960,'string':4,'fret':3}],
            'attack_events':[{'start_tick':0,'note_ids':['instrumental']},{'start_tick':480,'note_ids':['ordinary']}]}
        original=deepcopy(guitar)
        def prepare(s,v,arr):
            self.assertEqual([n['id'] for n in arr['guitar']['notes']],['instrumental'])
            self.assertEqual(len(arr['guitar']['attack_events']),1)
            arr['guitar']['notes'][0]['end_tick']=240
            return s,arr,{'instruments':{'guitar':{}}}
        with patch('instrumental_regular_rhythm.regularize_instrumentals',side_effect=prepare):
            _,new,_=regularize_provisional_instrumentals(shared,{}, {'guitar':guitar})
        self.assertEqual(guitar,original)
        self.assertEqual(new['guitar']['notes'][1],original['notes'][1])
        self.assertEqual(len(new['guitar']['attack_events']),2)

    # 原曲拍轴与歌词拍位通用修复：新增伴奏上移候选恢复合法配音，全部旋律保持整句八度及原演奏门限。
    def register_fixture(self):
        from test_guitar_instrumental_register import music
        shared,vocal,guitar=music(capo=4)
        rows=[('melody_high',0,480,76,1,8,'instrumental_melody'),
              ('bass_low',240,480,45,6,1,'bass'),
              ('melody_low',480,960,64,3,5,'instrumental_melody'),
              ('harmony',720,960,57,4,3,'harmony'),('bass',720,960,52,5,3,'bass')]
        guitar['notes']=[{'id':identity,'start_tick':a,'end_tick':b,'pitch_midi':pitch,
            'string':string,'fret':fret,'finger':1,'hand_position':1,'role':role,
            'velocity':90,'source':'synthetic_unaccepted_music','chord_id':'h0'}
            for identity,a,b,pitch,string,fret,role in rows]
        return shared,vocal,guitar

    def test_accompaniment_octave_up_resolves_held_melody_without_relaxing_limits(self):
        from guitar_instrumental_register import arrange_instrumental_register,validate_instrumental_register
        from accompaniment_arrange import validate_playability
        from accompaniment_analysis import SongClock
        s,v,g=self.register_fixture()
        with self.assertRaisesRegex(ValueError,'未找到可行路径'):arrange_instrumental_register(s,v,g)
        original=deepcopy(g);g['configuration']['instrumental_register_voicing_version']=2
        rebuilt,report=arrange_instrumental_register(s,v,g)
        old={n['id']:n for n in original['notes']};new={n['id']:n for n in rebuilt['notes']}
        self.assertEqual(set(old),set(new))
        for identity,n in old.items():
            self.assertEqual((n['pitch_midi']%12,n['role'],n['start_tick'],n['end_tick']),
                (new[identity]['pitch_midi']%12,new[identity]['role'],new[identity]['start_tick'],new[identity]['end_tick']))
        self.assertEqual(new['bass_low']['pitch_midi'],57)
        self.assertEqual([new[i]['pitch_midi'] for i in ('melody_high','melody_low')],[76,64])
        self.assertTrue(validate_playability(rebuilt,SongClock(v))['valid'])
        self.assertTrue(validate_instrumental_register(s,v,rebuilt)['valid'])
        forged=deepcopy(rebuilt);forged['configuration']['instrumental_register_voicing_version']=1
        self.assertFalse(validate_instrumental_register(s,v,forged)['valid'])
        self.assertEqual(report['voicing_version'],2)

    # 原曲拍轴与歌词拍位通用修复：新增新层正首拍保留原声前沿，伴奏同步延后且旧工程音频零点不变。
    def test_positive_source_downbeat_keeps_complete_singer_and_preview_lead(self):
        import soundfile as sf
        from test_accompaniment import fixture
        from accompaniment_analysis import SongClock
        from accompaniment_vocal_playback import prepare_vocals
        from accompaniment_export import _synthesis_buffer
        shared,vocal=fixture();offset=.075
        for knot in vocal['timing']['knots']:knot['seconds']+=offset
        self.assertAlmostEqual(SongClock(vocal).audio_origin_seconds,offset)
        vocal['source_meter_rebuild_correction']={'version':1}
        self.assertEqual(SongClock(vocal).audio_origin_seconds,0.)
        sr=8000;t=np.arange(4*sr)/sr;raw=(.1*np.cos(2*np.pi*220*t)).astype(np.float32)[:,None]
        with temporary_workspace() as temp:
            root=Path(temp);source=root/'raw.wav';sf.write(source,raw,sr,subtype='FLOAT')
            shared['input_binding']['sources']['vocals']={'path':str(source),'sha256':sha256(source),'offset_seconds':0.}
            aligned,meta=prepare_vocals(root,shared,vocal)
            self.assertTrue(meta['original_source_frames_preserved'])
            self.assertEqual(meta['placement']['source_crop_samples'],0)
            np.testing.assert_array_equal(aligned[:len(raw)],raw)
            delivered,_=sf.read(root/'audio/vocals_aligned.wav',always_2d=True,dtype='float32')
            self.assertLessEqual(float(np.max(np.abs(delivered[:len(raw)]-raw))),1/32768)
        accompaniment={'instrument':'guitar','notes':[{'start_tick':0,'end_tick':480,'pitch_midi':60,'velocity':90}]}
        # 原曲拍轴与歌词拍位通用修复：修改，旧测试误把输出音频／采样率元组作音频保留；按实际返回签名取样本。
        # preview=_synthesis_buffer(accompaniment,vocal,sr)
        preview,_=_synthesis_buffer(accompaniment,vocal,sr)
        self.assertEqual(float(np.abs(preview[:round(offset*sr)]).max()),0.)
        self.assertGreater(float(np.abs(preview[round(offset*sr)+10:]).max()),.01)


if __name__ == '__main__':unittest.main()
