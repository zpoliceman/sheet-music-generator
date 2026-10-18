"""第四首《日落大道》男声跨歌曲验证：长缺锚窗、静音幻觉、来源坐标及未知字不伪造的独立反例。"""
from pathlib import Path
import copy,json,sys,tempfile,unittest
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import lyrics_window_recovery as recovery
from lyrics_align_phrases import text_cost,boundary_line_support,match_lines
from lyrics_transcribe import file_sha256
from test_musical_decode import fixture
import musical_decode as music
from review_summary import build_summary,write_bundle

class WindowRecoveryTests(unittest.TestCase):
    # 第四首《日落大道》男声跨歌曲验证：只重检长缺锚窗，短窗/可靠窗不耗GPU，次数有限。
    def test_window_limits_and_tail_first(self):
        job={'status':'candidate_window','warnings':['asr_missing_line'],'start_seconds':10.,'end_seconds':70.}
        windows=recovery.retry_windows(job);self.assertEqual(windows[0],(46.,70.));self.assertLessEqual(len(windows),4)
        self.assertTrue(all(10<=s<e<=70 and e-s<=24 for s,e in windows))
        self.assertFalse(recovery.retry_windows({**job,'warnings':[]}));self.assertFalse(recovery.retry_windows({**job,'end_seconds':30.}))
    # 第四首《日落大道》男声跨歌曲验证：长停顿后的独立声学窗不复制诊断秒数，四次上限仍保护。
    def test_acoustic_gap_adds_bounded_retry(self):
        job={'status':'candidate_window','warnings':['asr_missing_line'],'start_seconds':2.,'end_seconds':58.}
        notes=[{'start_seconds':3.,'end_seconds':5.,'quality':{'voiced_fraction':.8}},
               {'start_seconds':38.,'end_seconds':42.,'quality':{'voiced_fraction':.8}},
               {'start_seconds':47.,'end_seconds':55.,'quality':{'voiced_fraction':.8}}]
        windows=recovery.retry_windows(job,{'notes':notes})
        self.assertEqual(windows[0],(34.,58.));self.assertIn((35.,58.),windows)
        notes[1]['start_seconds']=39.;windows=recovery.retry_windows(job,{'notes':notes})
        self.assertIn((36.,58.),windows);self.assertLessEqual(len(windows),4)
        self.assertTrue(all(2<=a<b<=58 and b-a<=24 for a,b in windows))

    # 第四首《日落大道》男声跨歌曲验证：安静间奏残余只影响定位，不删原音符；停顿后歌词从响度证据起算。
    def test_quiet_residual_does_not_anchor_retry(self):
        job={'status':'candidate_window','warnings':['asr_missing_line'],'start_seconds':2.,'end_seconds':58.}
        def n(a,b,rms):return {'start_seconds':a,'end_seconds':b,'quality':{'voiced_fraction':.8,'rms_dbfs':rms}}
        notes=[n(3,5,-17),n(31,33,-48),n(39,42,-15),n(47,55,-16)]
        windows=recovery.retry_windows(job,{'notes':notes})
        self.assertIn((36.,58.),windows);self.assertNotIn((28.,52.),windows)
        self.assertEqual(len(notes),4)

    # 第四首《日落大道》男声跨歌曲验证：拒绝不相关幻觉、倒序时间与不可能的歌词密度。
    def test_text_and_time_gate(self):
        seg={'text':'风吹过长街','start':1.,'end':4.}
        self.assertTrue(recovery.validate_segment(seg,['风吹过长街'],text_cost,boundary_line_support))
        for changed in [{**seg,'text':'字幕由某某制作'},{**seg,'end':1.01},{**seg,'end':0.},{**seg,'start':float('nan')}]:
            self.assertFalse(recovery.validate_segment(changed,['风吹过长街'],text_cost,boundary_line_support))
    # 第四首《日落大道》男声跨歌曲验证：显式偏移换算后字词仍同源，输入不变。
    def test_global_offset_and_word_times_are_not_shared_or_mutated(self):
        seg={'text':'风吹过长街','start':1.,'end':4.,'words':[{'word':'风','start':1.,'end':1.4}]};before=copy.deepcopy(seg)
        new=recovery.globalize_segment(seg,100.,80.)
        self.assertEqual((new['start'],new['end']),(21.,24.));self.assertEqual(new['words'][0]['start'],21.)
        self.assertEqual(seg,before)
    # 第四首《日落大道》男声跨歌曲验证：不同遍相同歌词不是重复识别，时间重叠同词才去重。
    def test_duplicates_preserve_other_performances(self):
        seg={'text':'风吹过长街','start':21.,'end':24.}
        self.assertTrue(recovery.duplicate_segment(seg,[{**seg,'start':20.9}],text_cost))
        self.assertFalse(recovery.duplicate_segment(seg,[{**seg,'start':1.,'end':4.}],text_cost))
    # 第四首《日落大道》男声跨歌曲验证：已知合成源和假的识别器只验证坐标/文本保护，不宣称模型识别准确。
    def test_recovery_preserves_anchor_source_and_resolves_missing_line(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as directory:
            directory=Path(directory);path=directory/'audio.wav';sf.write(path,np.zeros(50*8000,dtype=np.float32),8000)
            source={'path':str(path),'sha256':file_sha256(path),'offset_seconds':0.,'duration_seconds':50.}
            ref={'source':source,'lines':['起点的声音','风吹过长街','暮色中的回声']}
            anchor={'source':source,'configuration':{'model':'medium'},'result':{'segments':[{'text':ref['lines'][0],'start':0.,'end':4.},{'text':ref['lines'][2],'start':45.,'end':50.}]}}
            plan={'jobs':[{'job_id':1,'status':'candidate_window','line_indices':[1],'warnings':['asr_missing_line'],'start_seconds':5.,'end_seconds':44.}]};before=copy.deepcopy(anchor)
            def fake(src,model,out,force):
                raw={'source':src,'result':{'segments':[{'text':'风吹过长街','start':5.,'end':8.}]}};(out/'asr_raw.json').write_text(json.dumps(raw),encoding='utf-8');return raw,{'status':'fixture'}
            result,evidence=recovery.recover_long_gaps(ref,anchor,plan,directory/'out',match_lines,text_cost,boundary_line_support,fake)
            self.assertEqual(anchor,before);self.assertEqual(result['source'],source);self.assertEqual(len(evidence['attempts']),1)
            self.assertEqual(evidence['added_segments'],1);self.assertEqual(result['result']['segments'][1]['start'],25.)
            self.assertEqual(evidence['attempts'][0]['recovered_line_indices'],[1])
    # 第四首《日落大道》男声跨歌曲验证：来源SHA错误必须拒绝，不能从另一音源补词。
    def test_source_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as directory:
            path=Path(directory)/'audio.wav';path.write_bytes(b'wrong')
            job={'job_id':0,'status':'candidate_window','line_indices':[0],'warnings':['asr_missing_line'],'start_seconds':0.,'end_seconds':40.}
            with self.assertRaisesRegex(ValueError,'SHA'):
                recovery.recover_long_gaps({'source':{'path':str(path),'sha256':'other'},'lines':['风吹过长街']},{},{'jobs':[job]},Path(directory)/'out',match_lines,text_cost,boundary_line_support)

class UnresolvedLyricsTests(unittest.TestCase):
    # 第四首《日落大道》男声跨歌曲验证：缺字空隙的真实音保持无挂词，不能转成前后字的假转音。
    def test_unknown_gap_pitch_is_preserved_without_fake_owner(self):
        a,l,b=fixture();l['characters'][1]['start_seconds']=None
        p=music.decode(a,l,b,verify_audio=False);middle=[n for n in p['quantized_notes'] if n['pitch_midi']==64]
        self.assertEqual(len(middle),1);self.assertIsNone(middle[0]['lyric_index']);self.assertIsNone(p['lyrics']['characters'][1]['start_seconds'])
        p['title']='独立未定位夹具';scene=__import__('score_export').render_jianpu(p)
        self.assertIn('基准音',scene.svg());self.assertIn('另有1个歌词单位未定位',scene.svg())
    # 第四首《日落大道》男声跨歌曲验证：整曲无任何可靠歌词不能标成有效部分稿。
    def test_all_missing_still_fails(self):
        a,l,b=fixture()
        for c in l['characters']:c['start_seconds']=None
        with self.assertRaisesRegex(ValueError,'没有可靠'):music.decode(a,l,b,verify_audio=False)
    # 第四首《日落大道》男声跨歌曲验证：HTML/JSON必须公开缺字和原文；只提供整句试听上下文。
    def test_review_bundle_discloses_missing_text(self):
        a,l,b=fixture();l['characters'][1]['start_seconds']=None;p=music.decode(a,l,b,verify_audio=False)
        summary=build_summary(p,l,a);self.assertEqual(summary['unmapped_character_count'],1)
        self.assertEqual(summary['unmapped_characters'][0]['context'],'春【花】开')
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as directory:
            write_bundle(summary,Path(directory),'audio.wav')
            text=(Path(directory)/'manual_review.html').read_text(encoding='utf-8')
            self.assertIn('尚未可靠挂谱的歌词',text);self.assertIn('春【花】开',text)

if __name__=='__main__':unittest.main(verbosity=2)
