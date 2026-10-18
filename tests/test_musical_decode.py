"""自动音乐解码改造：独立已知旋律、真实合成声学和跨调/拍速语义回归。"""
# 自动音乐解码改造：新增测试夹具，不将《遇见》答案或歌曲索引写入解码程序。
import copy
import math
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import musical_decode as music
import score_export as score

# 自动音乐解码改造：新增独立的三字旋律，中央字是短促主音。
def fixture(shift=0,scale=1):
    intervals=[(0,.4,60),(.4,.5,64),(.5,1.5,67)]
    notes=[{'id':str(i),'source_note_id':str(i),'pitch_midi':p+shift,'start_seconds':s*scale,'end_seconds':e*scale,'confidence':.95,'quality':{'pitch_support_fraction':1},'review_flags':[]} for i,(s,e,p) in enumerate(intervals)]
    times=np.arange(0,1.5,.01)
    frames=[]
    for t in times:
        pitch=60 if t<.4 else 64 if t<.5 else 67
        frames.append({'time_seconds':float(t*scale),'f0_hz':440*2**((pitch+shift-69)/12),'unvoiced':False})
    analysis={'notes':notes,'pitch_frames':frames,'configuration':{'frame_step_seconds':.01*scale},'source':{'duration_seconds':4*scale,'sha256':'fixture','offset_seconds':0}}
    chars=[{'index':i,'text':text,'start_seconds':s*scale,'end_seconds':e*scale,'line_index':0,'method':'independent_test','warnings':[]} for i,(text,(s,e,_)) in enumerate(zip('春花开',intervals))]
    lyrics={'characters':chars,'reference_kind':'user_supplied','alignment_status':'test','source':analysis['source']}
    audio={'duration_seconds':4*scale,'beat_times_seconds':[i*.5*scale for i in range(9)],'meter':{'selected':'4/4','phase':0},'tempo':{'bpm':120/scale}}
    return analysis,lyrics,audio

# 自动音乐解码改造：新增普通/装饰音音段夹具。
def piece(identity,start,end,pitch,confidence=.95,anchor=True,index=0):
    return {'id':identity,'source_note_id':identity,'pitch_midi':pitch,'start_seconds':start,'end_seconds':end,'confidence':confidence,'anchor':anchor,'role':'main' if anchor else 'detail','lyric_index':index,'line_index':0}

class MusicalDecodeTests(unittest.TestCase):
    # 自动音乐解码改造：短主音必须普通记谱，并保留全部字；不能以舍入零值变成倚音。
    def test_short_primary_survives_and_inputs_are_immutable(self):
        a,l,b=fixture();before=copy.deepcopy((a,l,b));p=music.decode(a,l,b,verify_audio=False)
        self.assertEqual(p['lyric_mapping']['mapped_characters'],3)
        self.assertEqual([n['pitch_midi'] for n in p['quantized_notes']],[60,64,67])
        self.assertTrue(all(not n['grace'] and n['end_tick']>n['start_tick'] for n in p['quantized_notes']))
        self.assertEqual((a,l,b),before)
        self.assertEqual(p['notation']['transpose_semitones'],0)

    # 自动音乐解码改造：跨源调和拍速仍保留相同音乐音序，不依赖歌曲名/固定索引。
    def test_transposition_and_tempo_equivariance(self):
        for shift in [-5,0,2,7]:
            for scale in [.7,1,1.3]:
                a,l,b=fixture(shift,scale);p=music.decode(a,l,b,verify_audio=False)
                self.assertEqual([n['pitch_midi'] for n in p['quantized_notes']],[60+shift,64+shift,67+shift])
                self.assertEqual(p['lyric_mapping']['mapped_characters'],3)
                self.assertEqual(p['notation']['transpose_semitones'],0)

    # 自动音乐解码改造：输出调的转换只影响派生层，默认实际源音高与目标调分开。
    def test_target_key_transposes_from_inferred_source(self):
        # 自动音乐解码改造：修改，提供足够主调证据；只有三音且长停属音不能证明源D调，原用例保留。
        # a,l,b=fixture(2);p=music.decode(a,l,b,target_key='C:major',verify_audio=False)
        a,l,b=fixture(2)
        intervals=[(0,1.0,62),(1.0,1.1,66),(1.1,1.5,69)]
        for n,c,(start,end,pitch) in zip(a['notes'],l['characters'],intervals):
            n.update(start_seconds=start,end_seconds=end,pitch_midi=pitch)
            c.update(start_seconds=start,end_seconds=end)
        for row in a['pitch_frames']:
            t=row['time_seconds'];pitch=62 if t<1 else 66 if t<1.1 else 69
            row['f0_hz']=440*2**((pitch-69)/12)
        p=music.decode(a,l,b,target_key='C:major',verify_audio=False)
        self.assertEqual(p['notation']['source_key']['label'],'D:major')
        self.assertEqual(p['notation']['transpose_semitones'],-2)
        self.assertEqual([n['pitch_midi'] for n in p['quantized_notes']],[60,64,67])
        self.assertEqual([n['source_pitch_midi'] for n in p['quantized_notes']],[62,66,69])

    # 自动音乐解码改造：软边界扰动不能切碎/删掉主音。
    def test_character_boundary_perturbation(self):
        for delta in [-.08,0,.08]:
            a,l,b=fixture()
            l['characters'][0]['end_seconds']+=delta
            l['characters'][1]['start_seconds']+=delta
            p=music.decode(a,l,b,verify_audio=False)
            self.assertEqual([n['pitch_midi'] for n in p['quantized_notes']],[60,64,67])
            self.assertEqual(p['lyric_mapping']['mapped_characters'],3)

    # 自动音乐解码改造：复核真实合成声学；原模型漏掉转音，f0和YIN一致才能修复。
    def test_independent_yin_recovers_missing_turn(self):
        import soundfile as sf
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as directory:
            path=Path(directory)/'known_turn.wav';sr=16000
            times=np.arange(sr)/sr;pitch=np.where(times<.4,60,np.where(times<.6,64,60))
            hz=440*2**((pitch-69)/12);phase=2*np.pi*np.cumsum(hz)/sr
            sf.write(path,.3*np.sin(phase),sr)
            a,_,_=fixture();a['source'].update(path=str(path),sha256=score.sha256(path),duration_seconds=1)
            a['notes']=[{'id':'missing_turn','pitch_midi':60,'start_seconds':0,'end_seconds':1,'confidence':.5,'quality':{'pitch_support_fraction':.5}}]
            a['pitch_frames']=[{'time_seconds':i/100,'f0_hz':440*2**(((60 if i<40 or i>=60 else 64)-69)/12),'unvoiced':False} for i in range(100)]
            notes,reviews=music.acoustic_candidates(a,True)
            self.assertEqual([n['pitch_midi'] for n in notes],[60,64,60])
            self.assertTrue(any(r['action']=='stable_core_resegmented' for r in reviews))

    # 自动音乐解码改造：小幅颤音不可扩成多个半音音符。
    def test_vibrato_does_not_create_note_attacks(self):
        a,_,_=fixture();a['notes']=a['notes'][:1];a['notes'][0]['end_seconds']=1
        a['pitch_frames']=[{'time_seconds':i/100,'f0_hz':440*2**((60+.25*math.sin(i*2*math.pi/20)-69)/12)} for i in range(100)]
        notes,_=music.acoustic_candidates(a,False)
        self.assertEqual([n['pitch_midi'] for n in notes],[60])

    # 自动音乐解码改造：稳定中心偏离半音格的滑音，不强行新增该半音。
    def test_pitch_boundary_glide_is_not_a_new_chromatic_note(self):
        a,_,_=fixture();a['notes']=a['notes'][:1];a['notes'][0]['end_seconds']=1
        a['pitch_frames']=[{'time_seconds':i/100,'f0_hz':440*2**((60.58-69)/12)} for i in range(100)]
        notes,_=music.acoustic_candidates(a,False)
        self.assertEqual([n['pitch_midi'] for n in notes],[60])

    # 自动音乐解码改造：稳定支持比持续时长更重要，短稳定主音不得被长低支持过渡替代。
    def test_stable_short_anchor_and_attached_grace(self):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}])
        group=[piece('approach',0,.15,60,.45,True),piece('primary',.15,.27,62,.95,False)]
        # 自动音乐解码改造：新增稳定平台证据，低置信度本身不能证明可靠倚音。
        group[0]['stable_duration_seconds']=.15
        notes,_=music.classify(group,mapping)
        self.assertEqual([(n['pitch_midi'],n['role']) for n in notes],[(60,'grace'),(62,'main')])

    # 自动音乐解码改造：多音转音链保留实际时值；不能把所有短音都变成装饰音。
    def test_metered_turn_chain_remains_metered(self):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}])
        group=[piece('a',0,.15,60,.95,False),piece('b',.15,.30,64,.95,True),piece('c',.30,.45,62,.95,False)]
        notes,_=music.classify(group,mapping)
        self.assertEqual([n['pitch_midi'] for n in notes],[60,64,62])
        self.assertTrue(all(not n['grace'] for n in notes))

    # 自动音乐解码改造：完整音段跨字重起，保持两字同音发声与转音落音，不跨字硬删。
    def test_long_same_pitch_can_reattack_at_character(self):
        notes=[piece('long',0,1.5,60),piece('next',1.5,2,62)]
        chars=[{'index':0,'text':'春','start_seconds':0,'end_seconds':.5},{'index':1,'text':'风','start_seconds':.5,'end_seconds':1.5},{'index':2,'text':'来','start_seconds':1.5,'end_seconds':2}]
        pieces,_,_=music.soft_lyrics(notes,{'characters':chars})
        anchors=[n for n in pieces if n['anchor']]
        self.assertEqual([(n['lyric_index'],n['pitch_midi']) for n in anchors],[(0,60),(1,60),(2,62)])

    # 自动音乐解码改造：倚音分配不重叠；XML的连奏与延音、MIDI实际播放一致。
    def test_grace_slur_tie_and_midi_semantics(self):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}])
        timing={'meter':[4,4],'score_start_quarter':0,'steady_tempo_bpm':120}
        notes=[dict(piece('grace',.85,1,60,anchor=False),grace=True,role='grace',anchor_id='main'),dict(piece('main',1,2.5,62),grace=False,role='main')]
        events,q,stats=music.musical_quantize(notes,mapping,timing,3)
        project={'title':'独立音乐例','inputs':{'notes_path':'synthetic'},'notation':{'key':score.key_definition('C:major'),'ppq':480},'timing':timing,
                 'events':events,'quantized_notes':q,'statistics':stats,'tempo_events':[{'tick':0,'bpm':120}]}
        score.attach_lyrics(events,[{'index':0,'text':'啊'}]);xml=score.build_musicxml(project)
        self.assertTrue(score.validate_score(project,xml)['valid'])
        self.assertTrue(xml.findall('.//grace')[0].get('steal-time-following'))
        self.assertTrue(xml.findall('.//slur'))
        self.assertTrue(xml.findall('.//tied'))
        self.assertLess(q[0]['playback_start_tick'],q[0]['playback_end_tick'])
        self.assertEqual(q[0]['playback_end_tick'],q[1]['playback_start_tick'])
        with tempfile.TemporaryDirectory(dir=ROOT/'test_outputs') as directory:
            path=Path(directory)/'test.mid';score.write_midi(path,project)
            self.assertTrue(music.validate_playback(path,project)['valid'])

    # 自动音乐解码改造：持续音不必每拍切开，跨小节仍拆分。
    def test_dotted_duration_not_split_at_every_quarter(self):
        parts=music.split_notation(240,960,1920)
        self.assertEqual([p['duration_ticks'] for p in parts],[720])
        self.assertEqual([p['duration_ticks'] for p in music.split_notation(1680,2400,1920)],[240,480])

    # 自动音乐解码改造：稳定半音借用不能因调性先验而吸附回调内音。
    def test_chromatic_notes_are_not_projected_to_scale(self):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}])
        notes=[piece('a',0,.2,60),piece('b',.2,.4,61,index=1),piece('c',.4,.8,62,index=2)]
        out,_=music.classify(notes,mapping)
        self.assertEqual([n['pitch_midi'] for n in out],[60,61,62])

    # 自动音乐解码改造：异常尾拍不拖快前段，拍速估计与人为覆盖分别可核查。
    def test_tail_beat_outlier_rejected(self):
        a,l,b=fixture();b['beat_times_seconds']=[i*.5 for i in range(21)]+[10.3+i*.3 for i in range(4)]
        n=[piece('x',1,2,60)];_,timing=music.robust_timing(b,n,[])
        self.assertAlmostEqual(timing['steady_tempo_bpm'],120)
        self.assertGreater(timing['rejected_beat_count'],0)

    # 自动音乐解码改造：错误音符时间轴需拒绝，而非按正时值约束掩盖输入重叠。
    def test_overlap_rejected(self):
        a,_,_=fixture();a['notes'][1]['start_seconds']=.3
        with self.assertRaisesRegex(ValueError,'重叠'): music.acoustic_candidates(a,False)

    # 自动音乐解码改造：明确未对齐字不能声称已自动补全。
    # 第四首《日落大道》男声跨歌曲验证：修改原全曲失败用例，验证缺字保留/null且其余字真实导出；旧用例保留。
    # def test_missing_lyrics_fail_explicitly(self):
    # a,l,b=fixture();l['characters'][1]['start_seconds']=None
    # with self.assertRaises(ValueError): music.decode(a,l,b,verify_audio=False)
    def test_missing_lyric_is_disclosed_and_its_time_is_not_fabricated(self):
        a,l,b=fixture();l['characters'][1]['start_seconds']=None
        before=copy.deepcopy(l);p=music.decode(a,l,b,verify_audio=False)
        self.assertEqual(p['lyric_mapping']['unmapped_character_indices'],[1])
        self.assertEqual(p['lyric_mapping']['mapped_characters'],2)
        self.assertEqual([c['text'] for c in p['lyrics']['characters']],list('春花开'))
        self.assertIsNone(p['lyrics']['characters'][1]['start_seconds'])
        self.assertEqual(l,before)
        self.assertTrue(any(i['type']=='lyric_unaligned' for i in p['alignment_issues']))


    # 自动音乐解码改造：独立重复弱起旋律，验证相位推断不依赖《遇见》首字位置。
    def test_repeated_pickup_phase_and_explicit_origin(self):
        _,_,audio=fixture()
        audio['beat_times_seconds']=[i*.5 for i in range(21)]
        notes=[]
        for line,start in enumerate([1.0,3.0,5.0]):
            a=piece(str(line)+'a',start,start+.25,62)
            b=piece(str(line)+'b',start+.25,start+1,60,index=line*2+1)
            a['line_index']=b['line_index']=line
            notes.extend([a,b])
        mapping,timing=music.robust_timing(audio,notes,[])
        self.assertEqual(timing['pickup_pattern_count'],3)
        self.assertAlmostEqual(mapping.seconds_to_quarters(1.0)%4,3,places=1)
        override,_=music.robust_timing(audio,notes,[],beat_origin=0)
        self.assertAlmostEqual(override.seconds_to_quarters(1.0),2)

    # 自动音乐解码改造：独立审计反例，低置信长音必须保留为待核转音，不能全变后音。
    def test_low_confidence_long_note_is_not_swallowed(self):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}])
        notes=[piece('weak',0,.8,60,.2,False),piece('strong',.8,1.4,67,.95,True)]
        out,reviews=music.classify(notes,mapping)
        self.assertEqual([(n['pitch_midi'],n['start_seconds'],n['end_seconds']) for n in out],[(60,0,.8),(67,.8,1.4)])
        self.assertTrue(any(r['type']=='uncertain_detail_retained' for r in reviews))

    # 自动音乐解码改造：相同字内的真正休止不能被细节归并或倚音依附填掉。
    def test_merging_and_grace_do_not_fill_rest_gap(self):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}])
        for seconds,confidence in [(.3,.2),(.05,.2),(.15,.9)]:
            notes=[piece('prefix',0,seconds,60,confidence,False),piece('main',.8,1.4,62,.99,True)]
            out,_=music.classify(notes,mapping)
            self.assertEqual(out[-1]['start_seconds'],.8)
            self.assertTrue(all(not n['grace'] for n in out))

    # 自动音乐解码改造：多个连续待删尾片必须归并到已保留音，不能延长一个已经删除的片段。
    def test_consecutive_tiny_tails_preserve_covered_end(self):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}])
        notes=[piece('main',0,.5,60,.99,True),piece('tail1',.5,.54,61,.1,False),piece('tail2',.54,.58,62,.1,False)]
        out,_=music.classify(notes,mapping)
        self.assertEqual(len(out),1)
        self.assertAlmostEqual(out[0]['end_seconds'],.58)

    # 自动音乐解码改造：倚音跨小节延音时，XML百分比必须以紧随的拆符时值回算，且等于MIDI。
    def test_grace_allocation_uses_first_xml_tied_note(self):
        mapping=score.TempoMap([{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}])
        timing={'meter':[4,4],'score_start_quarter':0,'steady_tempo_bpm':120}
        notes=[dict(piece('g',1.6,1.75,60,anchor=False),grace=True,role='grace',anchor_id='a'),dict(piece('a',1.75,2.5,62),grace=False,role='main')]
        events,q,stats=music.musical_quantize(notes,mapping,timing,3)
        project={'title':'跨小节倚音例','inputs':{'notes_path':'synthetic'},'notation':{'key':score.key_definition('C:major'),'ppq':480},'timing':timing,'events':events,'quantized_notes':q,'statistics':stats,'tempo_events':[{'tick':0,'bpm':120}]}
        xml=score.build_musicxml(project)
        self.assertTrue(music.validate_grace_allocation(xml,project)['valid'])
        first=next(e for e in events if e.get('piece_id')=='a')['duration_ticks']
        stolen=q[0]['playback_end_tick']-q[0]['playback_start_tick']
        self.assertAlmostEqual(q[0]['grace_steal_percent']*first/100,stolen)
        self.assertLess(first,q[1]['end_tick']-q[1]['start_tick'])
        # 自动音乐解码改造：新增负例，旧整段分母必须被检查器拒绝。
        xml.find('.//grace').set('steal-time-following',str(100*stolen/(q[1]['end_tick']-q[1]['start_tick'])))
        with self.assertRaises(ValueError): music.validate_grace_allocation(xml,project)

    # 自动音乐解码改造：独立快节奏同高双字反例，原模型两个重发不能提前合并造成失败。
    def test_fast_repeated_pitch_preserves_two_characters(self):
        a,l,b=fixture()
        a['notes']=[{'id':str(i),'pitch_midi':60,'start_seconds':i*.18,'end_seconds':(i+1)*.18,'confidence':.95} for i in range(2)]
        a['pitch_frames']=[{'time_seconds':i/100,'f0_hz':440*2**((60-69)/12)} for i in range(36)]
        l['characters']=[{'index':i,'text':text,'start_seconds':i*.18,'end_seconds':(i+1)*.18,'line_index':0} for i,text in enumerate('春风')]
        project=music.decode(a,l,b,verify_audio=False)
        self.assertEqual(project['lyric_mapping']['mapped_characters'],2)
        self.assertEqual([(n['pitch_midi'],n['lyric_index']) for n in project['quantized_notes']],[(60,0),(60,1)])
        self.assertTrue(all(not n['grace'] for n in project['quantized_notes']))
        # 自动音乐解码改造：新增只有一个原同音平台时也能按正长字界重起。
        a['notes']=[dict(a['notes'][0],end_seconds=.36)]
        project=music.decode(a,l,b,verify_audio=False)
        self.assertEqual(project['lyric_mapping']['mapped_characters'],2)
        self.assertEqual([n['lyric_index'] for n in project['quantized_notes']],[0,1])

if __name__=='__main__': unittest.main()
