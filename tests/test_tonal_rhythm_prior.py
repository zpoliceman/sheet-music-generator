"""大调约束与强拍先验：已知波形、弱起/切分及同源吞字的独立反例。"""
# 大调约束与强拍先验：新增真实合成波形验证，不使用日落大道固定字索引或参考音符。
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import tonal_rhythm_prior as prior
import musical_decode as music
import score_export as score
from test_musical_decode import piece,fixture

# 大调约束与强拍先验：新增已知音高的连续f0和正弦音源；源标签可故意错误。
def acoustic_fixture(pitch=63,duration=.4):
    rate=16000;t=np.arange(round(duration*rate))/rate
    wave=.4*np.sin(2*np.pi*440*2**((pitch-69)/12)*t)
    rows=[{'time_seconds':float(t),'f0_hz':float(440*2**((pitch-69)/12))} for t in np.arange(0,duration,.005)]
    return wave,{'pitch_frames':rows,'configuration':{'frame_step_seconds':.005},'source':{'duration_seconds':duration}}

class TonalPriorTests(unittest.TestCase):
    # 大调约束与强拍先验：新增明确唱出的降3/升4在C大调中也必须保留，不能硬吸附。
    def test_stable_borrowed_eb_and_sharp_f_are_retained_with_waveform(self):
        for pitch in (63,66):
            wave,analysis=acoustic_fixture(pitch)
            with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
                path=Path(d)/'borrowed.wav';sf.write(path,wave,16000,subtype='FLOAT')
                analysis['source'].update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                evidence=music.AcousticEvidence(analysis,True)
                notes=[piece('borrowed',0,.4,pitch,.95)]
                before=copy.deepcopy((notes,analysis))
                out,reviews=prior.regularize_major(notes,score.key_definition('C:major'),[],evidence)
                self.assertEqual(out[0]['pitch_midi'],pitch)
                self.assertEqual(out[0]['chromatic_status'],'stable_exception_retained')
                self.assertGreaterEqual(reviews[0]['platforms'][0]['independent_agreement'],.70)
                self.assertEqual((notes,analysis),before)

    # 大调约束与强拍先验：新增错误降3标签实际为E平台时，只改变派生记谱，保留源降3和时间。
    def test_wrong_chromatic_label_corrected_by_known_in_scale_waveform(self):
        wave,analysis=acoustic_fixture(64)
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'major.wav';sf.write(path,wave,16000,subtype='FLOAT')
            analysis['source'].update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            ns=[piece('mislabeled',0,.4,63,.2)]
            out,reviews=prior.regularize_major(ns,score.key_definition('C:major'),[],music.AcousticEvidence(analysis,True))
            self.assertEqual(out[0]['pitch_midi'],64)
            self.assertEqual(out[0]['source_pitch_midi'],63)
            self.assertEqual(out[0]['performance_segments'][0]['pitch_midi'],63)
            self.assertEqual((out[0]['start_seconds'],out[0]['end_seconds']),(0,.4))
            self.assertEqual(ns[0]['pitch_midi'],63)
            self.assertEqual(reviews[0]['type'],'tonal_prior_adjusted')

    # 大调约束与强拍先验：新增缺乏连续音高证据时保留不确定半音，不靠键盘距离凭空修正。
    # 调外音宁缺毋滥：用户收紧策略，原测试完整注释保留。
    # def test_no_evidence_retains_ambiguous_note(self):
    # _,analysis=acoustic_fixture();analysis['pitch_frames']=[]
    # out,reviews=prior.regularize_major([piece('unknown',0,.4,63,.2)],score.key_definition('C:major'),[],music.AcousticEvidence(analysis,False))
    # self.assertEqual(out[0]['pitch_midi'],63)
    # self.assertEqual(reviews[0]['type'],'ambiguous_chromatic_retained_for_review')
    # 调外音宁缺毋滥：修改缺证据半音策略，主谱用调内候选、原半音留复核；原测试注释保留。
    def test_no_evidence_uses_scale_prior_and_preserves_review(self):
        _,analysis=acoustic_fixture();analysis['pitch_frames']=[]
        notes=[piece('unknown',0,.4,63,.2)]
        out,reviews=prior.regularize_major(notes,score.key_definition('C:major'),[],music.AcousticEvidence(analysis,False))
        self.assertEqual(out[0]['pitch_midi'],62)
        self.assertEqual(out[0]['source_pitch_midi'],63)
        self.assertEqual(reviews[0]['performance_pitch_midi'],63)
        self.assertEqual(out[0]['chromatic_status'],'omitted_from_score_preserved_in_review')
        self.assertEqual(notes[0]['pitch_midi'],63)

    # 大调约束与强拍先验：新增真实波形仍无模型平台的反例，按不确定保留且不能越界访问。
    # 调外音宁缺毋滥：用户收紧策略，原测试完整注释保留。
    # def test_missing_pitch_platform_with_real_waveform_is_safe(self):
    # wave,analysis=acoustic_fixture(63);analysis['pitch_frames']=[]
    # with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
    # path=Path(d)/'no_frames.wav';sf.write(path,wave,16000,subtype='FLOAT')
    # analysis['source'].update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    # out,reviews=prior.regularize_major([piece('no_platform',0,.4,63,.2)],score.key_definition('C:major'),[],music.AcousticEvidence(analysis,True))
    # self.assertEqual(out[0]['pitch_midi'],63)
    # self.assertEqual(reviews[0]['type'],'ambiguous_chromatic_retained_for_review')
    # 调外音宁缺毋滥：修改真实波形无模型平台时的记谱期望，不越界、主谱调内、来源保留。
    def test_missing_pitch_platform_with_real_waveform_is_safe(self):
        wave,analysis=acoustic_fixture(63);analysis['pitch_frames']=[]
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'no_frames.wav';sf.write(path,wave,16000,subtype='FLOAT')
            analysis['source'].update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            out,reviews=prior.regularize_major([piece('no_platform',0,.4,63,.2)],score.key_definition('C:major'),[],music.AcousticEvidence(analysis,True))
            self.assertEqual(out[0]['pitch_midi'],62)
            self.assertEqual(reviews[0]['performance_pitch_midi'],63)

    # 大调约束与强拍先验：新增真实整段转调采用该段音阶，C大调的C不被当成B大调调外音。
    def test_confirmed_modulation_uses_local_major_scale(self):
        _,analysis=acoustic_fixture(60);note=piece('after',0,.4,60,index=10)
        sections=[{'first_character_index':10,'start_seconds':0,'source_key':score.key_definition('C:major')}]
        out,reviews=prior.regularize_major([note],score.key_definition('B:major'),sections,music.AcousticEvidence(analysis,False))
        self.assertEqual(out[0]['pitch_midi'],60);self.assertEqual(reviews,[])

    # 大调约束与强拍先验：新增无挂词器乐不因人声调式而被强制改音。
    # 调外音宁缺毋滥：用户收紧策略，原测试完整注释保留。
    # def test_unassigned_notes_do_not_receive_vocal_pitch_prior(self):
    # _,analysis=acoustic_fixture(64)
    # out,reviews=prior.regularize_major([piece('instrument',0,.4,63,index=None)],score.key_definition('C:major'),[],music.AcousticEvidence(analysis,False))
    # self.assertEqual(out[0]['pitch_midi'],63);self.assertEqual(reviews,[])
    # 调外音宁缺毋滥：修改无挂词但打印在主谱的音也采用保守记谱；仅原声和取调证据保持不变。
    def test_printed_unassigned_note_is_regularized_without_false_lyrics(self):
        _,analysis=acoustic_fixture(64)
        ns=[piece('instrument',0,.4,63,index=None)]
        out,reviews=prior.regularize_major(ns,score.key_definition('C:major'),[],music.AcousticEvidence(analysis,False))
        self.assertEqual(out[0]['pitch_midi'],64)
        self.assertIsNone(out[0]['lyric_index'])
        self.assertEqual(out[0]['performance_segments'][0]['pitch_midi'],63)
        self.assertEqual(ns[0]['pitch_midi'],63)

    # 大调约束与强拍先验：新增大调候选限定及未支持小调更吻合的透明诊断。
    def test_major_only_ranking_does_not_claim_minor_is_supported(self):
        profile=[6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]
        ns=[piece(str(i),0,d,60+(i+9)%12) for i,d in enumerate(profile)]
        found=music.infer_vocal_key(ns)
        self.assertTrue(all(c['key'].endswith(':major') for c in found['candidates']))
        self.assertEqual(found['supported_modes'],['major'])
        self.assertTrue(found['unsupported_minor_may_fit_better'])

    # 大调约束与强拍先验：新增同音归并仍保留被替换音的各个来源，且不能跨两个字。
    def test_coalescing_preserves_performance_sources_and_word_boundary(self):
        ns=[piece('a',0,.2,64,index=0),piece('b',.2,.4,64,index=0),piece('c',.4,.6,64,index=1)]
        for n in ns:prior.remember(n)
        ns[1]['performance_segments'][0]['pitch_midi']=63;ns[1]['source_pitch_midi']=63
        out=prior.merge_same_word(ns)
        self.assertEqual(len(out),2)
        self.assertEqual([n['pitch_midi'] for n in out[0]['performance_segments']],[64,63])
        self.assertEqual(out[1]['lyric_index'],1)

class StrongBeatTests(unittest.TestCase):
    # 大调约束与强拍先验：新增移调及速度变化的合成句首，不使用任何实际歌词答案。
    def setup_phrase(self,scale=1,shift=0):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5*scale,'quarter':1}])
        timing={'meter':[4,4],'score_start_quarter':0,'steady_tempo_bpm':120/scale}
        ns=[piece('scoop',1.88*scale,2.18*scale,59+shift,.25,False),
            piece('platform',2.18*scale,2.45*scale,60+shift,.92)]
        ns[0]['stable_duration_seconds']=0;ns[0]['independent_pitch_support']=0
        ns[1]['stable_duration_seconds']=.15*scale;ns[1]['independent_pitch_support']=.95
        ns[0]['source_note_id']=ns[1]['source_note_id']='same'
        for n in ns:prior.remember(n)
        c={'index':0,'text':'春','line_index':0,'start_seconds':1.90*scale,'end_seconds':2.45*scale,
           'phonemes':[{'role':'initial','start_seconds':1.90*scale,'end_seconds':2.03*scale},
                       {'role':'nucleus','start_seconds':2.03*scale,'end_seconds':2.45*scale}]}
        return ns,[c],mapping,timing

    # 大调约束与强拍先验：新增辅音提前、元音近小节强拍的不稳定起音归并，时间来源保留。
    def test_ambiguous_scoop_becomes_main_on_downbeat(self):
        ns,cs,m,t=self.setup_phrase();before=copy.deepcopy((ns,cs))
        out,reviews=prior.phrase_onsets(ns,cs,m,t)
        self.assertEqual(len(out),1);self.assertEqual(out[0]['pitch_midi'],60)
        self.assertEqual(out[0]['notation_onset_prior']['quarter'],4)
        self.assertEqual(len(out[0]['performance_segments']),2)
        classified,_=music.classify(out,m,cs);events,quantized,_=music.musical_quantize(classified,m,t,3.)
        self.assertEqual(quantized[0]['start_tick'],1920)
        self.assertEqual(next(e['measure'] for e in events if e['pitch_midi'] is not None),2)
        self.assertEqual((ns,cs),before)

    # 大调约束与强拍先验：新增可靠短起音不被当滑音吞掉。
    def test_real_stable_ornament_is_not_absorbed(self):
        ns,cs,m,t=self.setup_phrase()
        ns[0].update(confidence=.92,stable_duration_seconds=.15,independent_pitch_support=.95)
        out,_=prior.phrase_onsets(ns,cs,m,t)
        self.assertEqual([n['pitch_midi'] for n in out],[59,60])
        # 大调约束与强拍先验：新增独立稳定前导音拍位也必须保护，不能只检查音序。
        self.assertFalse(any(n.get('notation_onset_prior') for n in out))

    # 大调约束与强拍先验：新增真正的半拍弱起及四分之一拍切分有明确元音起点，强拍加分不得移动。
    def test_pickup_and_syncopation_remain_at_acoustic_grid(self):
        for q in (3.5,3.75,4.5):
            ns,cs,m,t=self.setup_phrase()
            start=q*.5;ns=[piece('real',start,start+.3,60,.95)]
            cs[0].update(start_seconds=start,end_seconds=start+.3,
                phonemes=[{'role':'nucleus','start_seconds':start,'end_seconds':start+.3}])
            out,reviews=prior.phrase_onsets(ns,cs,m,t)
            self.assertNotIn('notation_onset_prior',out[0]);self.assertEqual(reviews,[])
            events,quantized,_=music.musical_quantize(out,m,t,3.)
            self.assertEqual(quantized[0]['start_tick'],round(q*480))

    # 大调约束与强拍先验：新增无停顿的句内音不能被强拍倾向改变。
    def test_no_breath_gap_does_not_gain_phrase_prior(self):
        ns,cs,m,t=self.setup_phrase()
        previous=piece('earlier',1.60,1.85,67,index=1);prior.remember(previous)
        out,reviews=prior.phrase_onsets([previous]+ns,cs,m,t)
        self.assertEqual(len(out),3);self.assertFalse(any(n.get('notation_onset_prior') for n in out))

    # 大调约束与强拍先验：新增缺音素证据以及非四四拍保守保持原拍位。
    def test_missing_nucleus_or_different_meter_has_no_prior(self):
        for mode in ('missing','meter'):
            ns,cs,m,t=self.setup_phrase()
            if mode=='missing':cs[0]['phonemes']=[]
            else:t['meter']=[3,4]
            out,reviews=prior.phrase_onsets(ns,cs,m,t)
            self.assertEqual(len(out),2);self.assertEqual(reviews,[])

    # 大调约束与强拍先验：新增整句提前过多不能靠强拍倾向强行修正。
    def test_large_shift_is_rejected(self):
        ns,cs,m,t=self.setup_phrase();ns[0]['start_seconds']=1.70;cs[0]['start_seconds']=1.70
        out,_=prior.phrase_onsets(ns,cs,m,t)
        self.assertEqual(len(out),2);self.assertNotIn('notation_onset_prior',out[0])

    # 大调约束与强拍先验：新增跨调及常见速度的相同行为，避免只适配一个歌曲。
    def test_transposition_and_tempo_equivariance(self):
        for scale in (.8,1,1.3):
            for shift in (-5,0,7):
                ns,cs,m,t=self.setup_phrase(scale,shift);out,_=prior.phrase_onsets(ns,cs,m,t)
                self.assertEqual(len(out),1);self.assertEqual(out[0]['pitch_midi'],60+shift)
                self.assertEqual(out[0]['notation_onset_prior']['quarter'],4)

    # 大调约束与强拍先验：新增共享边界反例，后音落强拍时前音终点必须同一拍格。
    def test_adjacent_note_boundary_shares_selected_onset(self):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}])
        timing={'meter':[4,4],'score_start_quarter':0,'steady_tempo_bpm':120}
        ns=[piece('before',0,.44,60,index=0),piece('phrase',.45,.95,62,index=1)]
        ns[1]['notation_onset_prior']={'quarter':1}
        _,qs,_=music.musical_quantize(ns,mapping,timing,2.)
        self.assertEqual(qs[0]['end_tick'],480);self.assertEqual(qs[1]['start_tick'],480)

# 调外音宁缺毋滥：新增已知合成波形验证严格独立音及滑音桥，而非固定真实歌曲答案。
class ChromaticPrecisionTests(unittest.TestCase):
    # 调外音宁缺毋滥：新增短平台即使两个提取器一致，也不自动记成独立调外音。
    def test_short_perfect_chromatic_plateau_is_omitted(self):
        wave,a=acoustic_fixture(63,.12)
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'short.wav';sf.write(path,wave,16000,subtype='FLOAT')
            a['source'].update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            ns=[piece('short',0,.12,63,.99)]
            out,reviews=prior.regularize_major(ns,score.key_definition('C:major'),[],music.AcousticEvidence(a,True))
            self.assertIn(out[0]['pitch_midi'],(62,64))
            self.assertEqual(reviews[0]['performance_pitch_midi'],63)
            self.assertEqual(ns[0]['pitch_midi'],63)

    # 调外音宁缺毋滥：新增模型支持不足不能仅凭YIN平台保留半音。
    def test_strong_yin_but_moderate_model_support_is_omitted(self):
        wave,a=acoustic_fixture(63,.4)
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'moderate.wav';sf.write(path,wave,16000,subtype='FLOAT')
            a['source'].update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            out,_=prior.regularize_major([piece('moderate',0,.4,63,.64)],score.key_definition('C:major'),[],music.AcousticEvidence(a,True))
            self.assertIn(out[0]['pitch_midi'],(62,64))

    # 调外音宁缺毋滥：新增模型与f0都高但真实波形不同，不能靠单源平台批准半音。
    def test_waveform_disagreement_overrides_high_model_support(self):
        wave,a=acoustic_fixture(63,.4);rate=16000;times=np.arange(len(wave))/rate
        wave=.4*np.sin(2*np.pi*440*2**((65-69)/12)*times)
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'contradiction.wav';sf.write(path,wave,rate,subtype='FLOAT')
            a['source'].update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            out,review=prior.regularize_major([piece('bad',0,.4,63,.99)],score.key_definition('C:major'),[],music.AcousticEvidence(a,True))
            self.assertIn(out[0]['pitch_midi'],(62,64))
            self.assertLess(review[0]['platforms'][0]['independent_agreement'],.85)

    # 调外音宁缺毋滥：新增原升1标签的连续音高实际靠近1，不能靠舍入选择成2。
    def test_sharp_tonic_label_uses_measured_tonic_center(self):
        wave,a=acoustic_fixture(60.15,.4)
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'tonic.wav';sf.write(path,wave,16000,subtype='FLOAT')
            a['source'].update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            out,_=prior.regularize_major([piece('tonic',0,.4,61,.62)],score.key_definition('C:major'),[],music.AcousticEvidence(a,True))
            self.assertEqual(out[0]['pitch_midi'],60)

    # 调外音宁缺毋滥：新增2到3真实滑音经过降3，归并后只打印两端并以跨字slur相连。
    # 调外音宁缺毋滥：修改夹具增加较弱调内端点，原签名保留。
    # def check_glide(self,descending=False,following_owner=False):
    # 调外音宁缺毋滥：修改夹具增加同字转音，原签名保留。
    # def check_glide(self,descending=False,following_owner=False,right_confidence=.95):
    def check_glide(self,descending=False,following_owner=False,right_confidence=.95,same_word=False):
        rate=16000;times=np.arange(round(.85*rate))/rate
        left,right=(64,62) if descending else (62,64)
        pitches=np.where(times<.35,left,np.where(times<.47,left+(right-left)*(times-.35)/.12,right))
        wave=.4*np.sin(2*np.pi*np.cumsum(440*2**((pitches-69)/12))/rate)
        frames=[{'time_seconds':float(t),'f0_hz':float(440*2**((p-69)/12))} for t,p in zip(times[::80],pitches[::80])]
        ns=[piece('left',0,.35,left,.95,index=0),piece('middle',.35,.47,63,.25,False,index=1 if following_owner else 0),
            # 调外音宁缺毋滥：修改右端支持可参数化，原夹具保留。
            # piece('right',.47,.85,right,.95,index=1)]
            piece('right',.47,.85,right,right_confidence,index=1)]
        ns[0]['stable_duration_seconds']=.30;ns[2]['stable_duration_seconds']=.30
        chars=[{'index':0,'text':'春','line_index':0,'start_seconds':0.,'end_seconds':.35 if following_owner else .47},
               {'index':1,'text':'风','line_index':0,'start_seconds':.35 if following_owner else .47,'end_seconds':.85}]
        # 调外音宁缺毋滥：新增同一字的2到3转音，不应重复附加第二条slur。
        if same_word:
            for note in ns:note['lyric_index']=0
            chars=chars[:1];chars[0]['end_seconds']=.85
        mapping=score.TempoMap([{'seconds':0.,'quarter':0.},{'seconds':.5,'quarter':1.}])
        timing={'meter':[4,4],'score_start_quarter':0,'steady_tempo_bpm':120}
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'glide.wav';sf.write(path,wave,rate,subtype='FLOAT')
            a={'pitch_frames':frames,'configuration':{'frame_step_seconds':.005},
               'source':{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}
            before=copy.deepcopy((ns,chars,a))
            out,reviews=prior.regularize_major(ns,score.key_definition('C:major'),[],music.AcousticEvidence(a,True),timing)
            self.assertEqual(reviews[0]['notation_adjustment']['reason'],'diatonic_glide_bridge')
            merged=prior.merge_same_word(out)
            self.assertEqual([n['pitch_midi'] for n in merged],[left,right])
            self.assertEqual(sum(len(n['performance_segments']) for n in merged),3)
            classified,_=music.classify(merged,mapping,chars)
            events,quantized,_=music.musical_quantize(classified,mapping,timing,2.)
            score.attach_lyrics(events,chars)
            # 调外音宁缺毋滥：修改同字/跨字的原文期望，原断言保留。
            # self.assertEqual([e['lyric']['text'] for e in events if e.get('lyric',{}).get('text')],['春','风'])
            self.assertEqual([e['lyric']['text'] for e in events if e.get('lyric',{}).get('text')],['春'] if same_word else ['春','风'])
            starts=[s['number'] for e in events for s in e.get('slurs',[]) if s['type']=='start']
            stops=[s['number'] for e in events for s in e.get('slurs',[]) if s['type']=='stop']
            self.assertEqual(starts,stops);self.assertEqual(len(starts),1)
            self.assertTrue(all(1<=v<=16 for v in starts))
            project={'events':events,'quantized_notes':quantized,'statistics':{'measure_count':1,'bar_ticks':1920,'total_ticks':1920},
                     # 调外音宁缺毋滥：修正新增夹具的tempo字段为导出器实际tick，原夹具保留。
                     # 'notation':{'key':score.key_definition('C:major'),'ppq':480},'timing':timing,'tempo_events':[{'start_tick':0,'bpm':120}],
                     'notation':{'key':score.key_definition('C:major'),'ppq':480},'timing':timing,'tempo_events':[{'tick':0,'bpm':120}],
                     'title':'真实滑音桥反例','inputs':{'notes_path':'synthetic'}}
            xml=score.build_musicxml(project)
            self.assertEqual(len(xml.findall('part/measure/note/notations/slur')),2)
            self.assertEqual((ns,chars,a),before)

    def test_ascending_glide_slur_keeps_original_word_ownership(self):
        self.check_glide()
    def test_descending_glide_slur_keeps_original_word_ownership(self):
        self.check_glide(descending=True)
    def test_glide_assigned_to_following_word_is_not_moved_to_previous_word(self):
        self.check_glide(following_owner=True)

    # 调外音宁缺毋滥：新增一端调内模型支持中等但平台清楚，仍应省掉中间半音。
    def test_clear_diatonic_platform_with_moderate_model_support_accepts_glide_bridge(self):
        self.check_glide(right_confidence=.55)

    # 调外音宁缺毋滥：新增同字转音XML只含一对slur，防止图片中双弧线。
    def test_same_word_glide_has_only_one_slur(self):
        self.check_glide(same_word=True)

class ConfirmedElisionTests(unittest.TestCase):
    # 大调约束与强拍先验：新增来源/原文受校验的用户吞字标记，原文及NULL时间必须保留。
    def setup_annotation(self):
        cs=[{'index':0,'text':'的','start_seconds':None,'end_seconds':None}]
        annotations={'source_sha256':'source','canonical_text_sha256':hashlib.sha256('的'.encode()).hexdigest(),
                     'characters':[{'index':0,'text':'的','status':'user_confirmed_elided','confirmed_by':'user'}]}
        return cs,annotations,{'sha256':'source'}
    def test_elision_is_status_only_and_source_is_immutable(self):
        cs,a,s=self.setup_annotation();out=prior.annotate_confirmed_elision(cs,a,s)
        self.assertIsNone(out[0]['start_seconds']);self.assertIsNone(out[0]['end_seconds'])
        self.assertEqual(out[0]['text'],'的');self.assertNotIn('human_review',cs[0])
        self.assertEqual(out[0]['human_review']['status'],'user_confirmed_elided')
    # 大调约束与强拍先验：新增错误歌曲、原文及已有真实时间拒绝复用人工确认。
    def test_mismatched_or_timed_elision_is_rejected(self):
        for kind in ('source','text','timed'):
            cs,a,s=self.setup_annotation()
            if kind=='source':s['sha256']='different'
            elif kind=='text':a['canonical_text_sha256']='wrong'
            else:cs[0].update(start_seconds=0.,end_seconds=.1)
            with self.assertRaises(ValueError):prior.annotate_confirmed_elision(cs,a,s)

if __name__=='__main__':unittest.main()
