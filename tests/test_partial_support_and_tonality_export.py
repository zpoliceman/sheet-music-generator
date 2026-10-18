"""连续转调识别与不确定调性保护：混合语言和导出提示的独立边界检查。"""
# 连续转调识别与不确定调性保护：新增测试，拒绝伪造英文时间或音素及异常识别时间。
import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from lyrics_partial_support import unsupported_lines,supported_plan,mark_unsupported_characters
from lyrics_align import reference_characters
from lyrics_quality import check_mandarin_reference
import phoneme_evidence,review_summary,score_export as score,musical_decode as music

class PartialLanguageTests(unittest.TestCase):
    def test_supported_chinese_and_original_english_are_both_preserved(self):
        reference={'lines':['春花开','hello world'],'reference_kind':'user_supplied'}
        blocked=unsupported_lines(check_mandarin_reference(reference),reference)
        plan={'jobs':[{'line_indices':[0],'status':'candidate_window'},{'line_indices':[1],'status':'candidate_window'}]};before=copy.deepcopy(plan)
        result=supported_plan(plan,blocked);chars=mark_unsupported_characters(reference_characters(reference),result)
        self.assertEqual(plan,before);self.assertEqual(result['jobs'][0]['status'],'candidate_window');self.assertEqual(result['jobs'][1]['status'],'unassigned_unsupported_language')
        self.assertEqual(''.join(c['text'] for c in chars),'春花开helloworld')
        self.assertTrue(all(c['start_seconds'] is None and c['end_seconds'] is None and c.get('phonemes')==[] for c in chars if c['line_index']==1))
    def test_mixed_window_is_not_split_using_fake_uniform_times(self):
        result=supported_plan({'jobs':[{'line_indices':[0,1],'status':'candidate_window'}]},{1})
        self.assertEqual(result['backend_unaligned_line_indices'],[0,1]);self.assertEqual(result['jobs'][0]['status'],'unassigned_unsupported_language')
    def test_time_anomalies_cannot_be_bypassed(self):
        with self.assertRaises(ValueError):unsupported_lines({'issues':[{'type':'asr_text_time_requires_review'}]},{'lines':['春花开']})
    def test_all_english_still_requires_another_backend(self):
        reference={'lines':['hello world'],'reference_kind':'user_supplied'}
        with self.assertRaises(ValueError):unsupported_lines(check_mandarin_reference(reference),reference)
    def test_humming_does_not_become_unsupported(self):
        reference={'lines':['春Hu花开'],'reference_kind':'user_supplied'}
        self.assertEqual(unsupported_lines(check_mandarin_reference(reference),reference),set())
    def test_reported_unsupported_phones_remain_empty(self):
        source={'sha256':'known','offset_seconds':0.};char={'index':0,'text':'h','line_index':1,'method':'unsupported_language_unaligned','start_seconds':None,'end_seconds':None,'group_id':None,'warnings':['backend_unsupported_text']}
        lyrics={'source':source,'cache_key':{'text_sha256':'text'},'characters':[char]};report={'source':source,'cache_key':{'text_sha256':'text'},'backend_unaligned_line_indices':[1],'phrase_reports':[]}
        enriched=phoneme_evidence.enrich(lyrics,report);self.assertEqual(enriched['characters'][0]['phonemes'],[]);self.assertNotIn('phonemes',char)
        char['start_seconds']=1.
        with self.assertRaises(ValueError):phoneme_evidence.enrich(lyrics,report)
    def test_unreported_language_cannot_hide_missing_phones(self):
        source={'sha256':'known','offset_seconds':0.};char={'text':'h','line_index':1,'method':'unsupported_language_unaligned','start_seconds':None,'end_seconds':None,'group_id':None,'warnings':['backend_unsupported_text']}
        with self.assertRaises(ValueError):phoneme_evidence.enrich({'source':source,'characters':[char]},{'source':source,'phrase_reports':[]})

class TonalityExportTests(unittest.TestCase):
    def test_guard_reaches_full_decode_xml_midi_and_review(self):
        import numpy as np
        notes=[];chars=[];frames=[]
        for i in range(24):
            start=float(i+1);end=float(i+2);pitch=60+i%12
            notes.append({'id':str(i),'source_note_id':str(i),'pitch_midi':pitch,'start_seconds':start,'end_seconds':end,'confidence':1.,'review_flags':[]})
            chars.append({'index':i,'text':chr(0x4e00+i),'line_index':i//8,'start_seconds':start,'end_seconds':end,'method':'independent_test','warnings':[]})
            for t in np.arange(start+.005,end,.01):frames.append({'time_seconds':float(t),'f0_hz':float(440*2**((pitch-69)/12))})
        analysis={'notes':notes,'pitch_frames':frames,'configuration':{'frame_step_seconds':.01},'source':{'sha256':'known','duration_seconds':27.,'offset_seconds':0.}}
        lyrics={'characters':chars,'source':analysis['source'],'reference_kind':'user_supplied','alignment_status':'independent_test'}
        audio={'duration_seconds':27.,'beat_times_seconds':[float(i) for i in range(28)],'meter':{'selected':'4/4','phase':0},'tempo':{'bpm':60.}}
        project=music.decode(analysis,lyrics,audio,tempo=60,beat_origin=0.,verify_audio=False);project['title']='独立未知调性测试'
        self.assertEqual([n['pitch_midi'] for n in project['quantized_notes']],[n['pitch_midi'] for n in notes]);self.assertTrue(project['notation']['tonality_uncertain_regions'])
        # 连续转调识别与不确定调性保护：新增独立夹具的来源引用，XML入口要求真实结构字段。
        project['inputs']={'notes_path':'independent_known_fixture.json'}
        xml=score.build_musicxml(project);self.assertTrue(score.validate_score(project,xml)['valid']);self.assertIn('调性有',score.lyric_notice(project))
        # 连续转调识别与不确定调性保护：SVG是按拍HTML/PNG的实际来源，必须显示保护提示。
        self.assertIn('调性有',score.render_jianpu(project).svg())
        summary=review_summary.build_summary(project,lyrics,analysis);self.assertGreater(summary['tonality_region_count'],0)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);score.write_midi(root/'known.mid',project);self.assertTrue(music.validate_playback(root/'known.mid',project)['valid'])
            # 连续转调识别与不确定调性保护：核验调用使用目录参数，原误传文件路径保留。
            # review_summary.write_bundle(summary,root/'manual_review.html','known.wav')
            review_summary.write_bundle(summary,root,'known.wav')
            self.assertIn('调性待确认的段落',(root/'manual_review.html').read_text(encoding='utf-8'));self.assertIn('调性待确认',(root/'manual_review.md').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main(verbosity=2)
