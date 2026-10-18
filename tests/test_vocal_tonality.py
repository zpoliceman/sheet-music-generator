"""第四首《日落大道》男声跨歌曲验证：人声取调、真实移调及拒绝伪转调的独立反例。"""
import copy,sys,tempfile,unittest,hashlib
import numpy as np
import soundfile as sf
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import musical_decode as music,score_export as score,vocal_tonality as tonal
from test_musical_decode import fixture

# 第四首《日落大道》男声跨歌曲验证：新增合成的重复唱句和已知调距，不使用实际歌曲答案。
def phrases(shift=2,octave=0):
    words=['潮汐归来映照长街','晨光落在水面之间','群山沉默等待夏天','灯火随风浮向岸边']
    pitches=[60,62,64,65,67,60,59,60];chars=[];notes=[];clock=1.
    for section,delta in enumerate((0,shift+octave)):
        if section:clock+=12.
        for line,text in enumerate(words):
            for i,ch in enumerate(text):
                idx=len(chars);chars.append({'index':idx,'text':ch,'line_index':section*4+line})
                duration=1.0 if i==7 else .4
                notes.append({'id':str(idx),'source_note_id':str(idx),'pitch_midi':pitches[i]+delta,
                              'lyric_index':idx,'line_index':section*4+line,'start_seconds':clock,'end_seconds':clock+duration,'confidence':.9})
                clock+=duration
    return notes,chars

class VocalTonalityTests(unittest.TestCase):
    # 第四首《日落大道》男声跨歌曲验证：无挂词长尾奏不能抢占人声取调统计。
    def test_unassigned_instrumental_is_excluded(self):
        notes,chars=phrases(0);base=tonal.infer_sections(notes,chars,music.infer_vocal_key,score.key_definition)[0]
        noise=[{'id':'instrument','pitch_midi':63,'lyric_index':None,'start_seconds':100.,'end_seconds':180.,'confidence':1.}]
        actual,sections=tonal.infer_sections(notes+noise,chars,music.infer_vocal_key,score.key_definition)
        self.assertEqual(base['selected'],actual['selected']);self.assertEqual(actual['excluded_unassigned_note_count'],1)
        self.assertEqual(actual['selected'],'C:major');self.assertEqual(sections,[])
    # 第四首《日落大道》男声跨歌曲验证：重复整段升二半音必须同时保留源音高并识别新的调号。
    def test_repeated_vocal_phrases_confirm_transposition(self):
        notes,chars=phrases(2);before=copy.deepcopy(notes)
        native,sections=tonal.infer_sections(notes,chars,music.infer_vocal_key,score.key_definition)
        self.assertEqual([s['source_key']['label'] for s in sections],['C:major','D:major'])
        self.assertTrue(sections[1]['evidence']['repeat_evidence']['accepted']);self.assertEqual(notes,before)
    # 第四首《日落大道》男声跨歌曲验证：同旋律高八度不会变成错误的调号变化。
    def test_octave_alone_does_not_create_modulation(self):
        notes,chars=phrases(0,12);native,sections=tonal.infer_sections(notes,chars,music.infer_vocal_key,score.key_definition)
        self.assertEqual(native['selected'],'C:major');self.assertEqual(sections,[])
    # 第四首《日落大道》男声跨歌曲验证：只有一句相似即使配对字数足够，也不能擅自确认转调。
    def test_single_phrase_is_insufficient(self):
        notes,chars=phrases(2);old=[n for n in notes if n['line_index']==0];new=[n for n in notes if n['line_index']==4]
        self.assertFalse(tonal.repeated_phrase_shift(old,new,chars,2)['accepted'])
    # 第四首《日落大道》男声跨歌曲验证：不同歌词的新段不能只因调性直方图候选不同就改变谱面调号。
    # 连续转调识别与不确定调性保护：更新“歌词不同不得识别”的旧策略，原测试完整注释保留。
    # def test_unrelated_new_lyrics_are_not_a_transposition_anchor(self):
    #     notes,chars=phrases(2)
    #     for c in chars:
    #         if c['line_index']>=4:c['text']='喵'
    #     native,sections=tonal.infer_sections(notes,chars,music.infer_vocal_key,score.key_definition)
    #     self.assertEqual(sections,[])

    # 连续转调识别与不确定调性保护：新增已知整段C到D即使歌词完全变化仍可由旋律证据确认。
    def test_unrelated_lyrics_do_not_block_known_melody_transposition(self):
        notes,chars=phrases(2);before=copy.deepcopy(notes)
        for c in chars:
            if c['line_index']>=4:c['text']='喵'
        native,sections=tonal.infer_sections(notes,chars,music.infer_vocal_key,score.key_definition)
        self.assertEqual([section['source_key']['label'] for section in sections],['C:major','D:major'])
        self.assertEqual(notes,before)
    # 第四首《日落大道》男声跨歌曲验证：XML/MIDI调号和简谱节选抬头一致，改变调号不能改播放音高。
    def test_export_changes_key_signature_without_transposing_notes(self):
        a,l,b=fixture();p=music.decode(a,l,b,verify_audio=False);p['title']='转调独立夹具';p['inputs']={'notes_path':'fixture'}
        self.assertGreaterEqual(p['statistics']['measure_count'],2)
        p['notation']['key_segments']=[{'start_measure':1,'start_tick':0,'start_seconds':0.,'key':score.key_definition('C:major'),'jianpu_reference_midi':60},
                                       {'start_measure':2,'start_tick':1920,'start_seconds':2.,'key':score.key_definition('D:major'),'jianpu_reference_midi':62}]
        before=copy.deepcopy(p['quantized_notes']);xml=score.build_musicxml(p)
        self.assertEqual([k.findtext('fifths') for k in xml.findall('part/measure/attributes/key')],['0','2'])
        scene=score.render_jianpu(p,2,2,True);self.assertIn('1=D（基准音D4）',scene.svg());self.assertIn('转1=D',scene.svg())
        self.assertEqual(score.notation_at(p,seconds=3.)[0]['label'],'D:major')
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'voice.mid';score.write_midi(path,p);self.assertTrue(music.validate_playback(path,p)['valid'])
            import mido
            signatures=[m.key for m in mido.MidiFile(path).tracks[0] if m.type=='key_signature'];self.assertEqual(signatures,['C','D'])
        self.assertEqual(p['quantized_notes'],before)

class StableMainTests(unittest.TestCase):
    # 第四首《日落大道》男声跨歌曲验证：字外高置信声段不能抢字内真实候选的主音，所有原音仍保留。
    def test_outside_word_cannot_steal_main(self):
        from test_musical_decode import piece
        notes=[piece('early',.6,.7,72,.99),piece('inside',1.,1.3,60,.35)]
        chars=[{'index':0,'start_seconds':1.,'end_seconds':1.3}];before=copy.deepcopy(notes)
        output,reviews=music.classify(notes,score.TempoMap([{'seconds':0.,'quarter':0.},{'seconds':.5,'quarter':1.}]),chars)
        self.assertEqual(next(n['id'] for n in output if n['role']=='main'),'inside')
        self.assertEqual(len(output),2);self.assertEqual(notes,before)
    # 第四首《日落大道》男声跨歌曲验证：字外有间隔的候选显式无挂词，但音高时间保留且真实字不失挂。
    def test_outside_segment_is_retained_without_false_owner(self):
        from test_musical_decode import piece
        ns=[piece('outside',.6,.7,72,.99),piece('inside',1.,1.3,60,.35,anchor=False)]
        output,issues=music.release_outside_lyric_segments(ns,[{'index':0,'start_seconds':1.,'end_seconds':1.3}],[])
        self.assertIsNone(output[0]['lyric_index']);self.assertFalse(output[0]['anchor']);self.assertTrue(output[1]['anchor'])
        self.assertEqual([(n['pitch_midi'],n['start_seconds'],n['end_seconds']) for n in output],[(72,.6,.7),(60,1.,1.3)])
        self.assertEqual(issues[0]['type'],'word_ownership_no_overlap_unassigned')
    # 第四首《日落大道》男声跨歌曲验证：音段确实交叠相邻字时不靠删除归属改写联合路径。
    def test_overlap_with_neighbor_is_not_released(self):
        from test_musical_decode import piece
        ns=[piece('neighbor',.6,.7,72,.99),piece('inside',1.,1.3,60,.35,anchor=False)]
        chars=[{'index':0,'start_seconds':1.,'end_seconds':1.3},{'index':1,'start_seconds':.5,'end_seconds':.8}]
        output,issues=music.release_outside_lyric_segments(ns,chars,[])
        self.assertEqual(output[0]['lyric_index'],0);self.assertEqual(issues,[])

    # 第四首《日落大道》男声跨歌曲验证：已知合成滑音后120ms稳定平台真实YIN复核，前缀不被抹去。
    def test_short_stable_tail_is_preserved_with_independent_waveform(self):
        rate=16000;times=np.arange(rate)/rate;pitch=np.where(times<.86,35+24*times/.86,59.)
        hz=440*2**((pitch-69)/12);wave=.4*np.sin(2*np.pi*np.cumsum(hz)/rate)
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as d:
            path=Path(d)/'glide.wav';sf.write(path,wave.astype(np.float32),rate,subtype='FLOAT')
            ft=np.arange(0,1.,.005);fp=np.where(ft<.86,35+24*ft/.86,59.)
            a={'notes':[{'id':'one','pitch_midi':58,'start_seconds':0.,'end_seconds':1.,'confidence':.2,'quality':{'pitch_support_fraction':.2}}],
               'pitch_frames':[{'time_seconds':float(t),'f0_hz':float(440*2**((p-69)/12))} for t,p in zip(ft,fp)],
               'configuration':{'frame_step_seconds':.005},'source':{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}
            before=copy.deepcopy(a);notes,reviews=music.acoustic_candidates(a,verify_audio=True)
            self.assertTrue(any(n['pitch_midi']==59 for n in notes));self.assertTrue(any(n['pitch_midi']==58 for n in notes))
            self.assertEqual(notes[0]['start_seconds'],0.);self.assertEqual(notes[-1]['end_seconds'],1.)
            self.assertTrue(all(abs(x['end_seconds']-y['start_seconds'])<1e-6 for x,y in zip(notes,notes[1:])))
            self.assertTrue(any(r.get('type')=='supported_short_core_preserved' for r in reviews));self.assertEqual(a,before)
            without_wave,_=music.acoustic_candidates(a,verify_audio=False)
            self.assertFalse(any(n.get('boundary_source')=='supported_short_core_transition_preserved' for n in without_wave))

if __name__=='__main__':unittest.main(verbosity=2)
