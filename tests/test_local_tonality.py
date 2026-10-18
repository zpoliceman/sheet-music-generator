"""连续转调识别与不确定调性保护：已知原音高、连续/新歌词/短桥段和拒绝伪转调反例。"""
# 连续转调识别与不确定调性保护：新增独立音乐条件测试，未使用六曲或四曲参考答案。
import copy,sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import musical_decode as music,score_export as score,vocal_tonality as tonal,tonal_rhythm_prior as prior
WORDS=['潮汐归来映照长街','晨光落在水面之间','群山沉默等待夏天','灯火随风浮向岸边']
NEW=['云海弯弯安详容貌','秋叶婆娑远方星辰','春雨萌芽芳草铃声','山间池塘幽深渔村']
PITCHES=[60,62,64,65,67,60,59,60]

# 连续转调识别与不确定调性保护：新增可变调距和阶段长度的独立音序、时间及歌词索引。
def sequence(sections=((0,12),(1,4)),gap=0.,new_words=False,new_melody=False,single_line=False):
    chars=[];notes=[];clock=1.;line=0
    for section,(delta,lines) in enumerate(sections):
        if section:clock+=gap
        for local in range(lines):
            words=(NEW if section and new_words else WORDS)[local%4]
            melody=[60,62,65,67,64,59,62,60] if section and new_melody else PITCHES
            for pos,ch in enumerate(words):
                i=len(chars);duration=1. if pos==7 else .4
                chars.append({'index':i,'text':ch,'line_index':0 if single_line else line,'start_seconds':clock,'end_seconds':clock+duration,'method':'tifa_forced_alignment'})
                notes.append({'id':str(i),'source_note_id':str(i),'pitch_midi':melody[pos]+delta,'lyric_index':i,'line_index':0 if single_line else line,'start_seconds':clock,'end_seconds':clock+duration,'confidence':.70,'stable_duration_seconds':duration})
                clock+=duration
            line+=1
    return notes,chars

# 连续转调识别与不确定调性保护：新增已知f0，模型支持为0.70仍须按整体新调保留正确音序。
def normalized(notes,chars):
    before=copy.deepcopy(notes);native,sections=tonal.infer_sections(notes,chars,music.infer_vocal_key,score.key_definition)
    frames=[]
    for n in notes:
        for t in np.arange(n['start_seconds']+.005,n['end_seconds'],.01):frames.append({'time_seconds':float(t),'f0_hz':float(440*2**((n['pitch_midi']-69)/12))})
    evidence=music.AcousticEvidence({'pitch_frames':frames,'configuration':{'frame_step_seconds':.01}},False)
    out,reviews=prior.regularize_major(notes,score.key_definition(native['selected']),sections,evidence,{'steady_tempo_bpm':120.},uncertain_regions=native['uncertain_regions'])
    assert notes==before
    return native,sections,out,reviews

class LocalTonalityTests(unittest.TestCase):
    # 连续转调识别与不确定调性保护：连续升半音必须识别新调，所有已知正确音高保留。
    def test_continuous_half_step_modulation_preserves_every_pitch(self):
        notes,chars=sequence();native,sections,out,_=normalized(notes,chars)
        self.assertEqual([s['source_key']['label'] for s in sections],['C:major','Db:major'])
        self.assertEqual(sections[1]['first_character_index'],96)
        self.assertEqual([n['pitch_midi'] for n in out],[n['pitch_midi'] for n in notes])
    # 连续转调识别与不确定调性保护：两秒呼吸不是转调必要条件。
    def test_short_pause_does_not_block_modulation(self):
        n,c=sequence(gap=2.);_,s,o,_=normalized(n,c)
        self.assertEqual([x['source_key']['label'] for x in s],['C:major','Db:major']);self.assertEqual([x['pitch_midi'] for x in o],[x['pitch_midi'] for x in n])
    # 连续转调识别与不确定调性保护：新歌词和不同旋律的稳定桥段可凭持续音阶证据识别。
    def test_new_words_and_new_melody_need_no_text_repetition(self):
        n,c=sequence(new_words=True,new_melody=True);_,s,o,_=normalized(n,c)
        self.assertEqual([x['source_key']['label'] for x in s],['C:major','Db:major']);self.assertEqual([x['pitch_midi'] for x in o],[x['pitch_midi'] for x in n])
    # 连续转调识别与不确定调性保护：短升调桥段之后回到原调，两次边界均可追溯。
    def test_bridge_can_return_to_original_key(self):
        n,c=sequence(sections=((0,12),(1,2),(0,4)),new_words=True);_,s,o,_=normalized(n,c)
        self.assertEqual([x['source_key']['label'] for x in s],['C:major','Db:major','C:major']);self.assertEqual([x['first_character_index'] for x in s],[0,96,112])
        self.assertEqual([x['pitch_midi'] for x in o],[x['pitch_midi'] for x in n])
    # 连续转调识别与不确定调性保护：不足确认门槛的一句桥段保音，不擅自当旧调纠错。
    def test_one_phrase_bridge_is_guarded_even_if_not_confirmed(self):
        n,c=sequence(sections=((0,12),(1,1),(0,4)));native,s,o,r=normalized(n,c)
        self.assertEqual(s,[]);self.assertTrue(native['uncertain_regions'])
        bridge=[x for x in o if 96<=x['lyric_index']<104]
        self.assertTrue(all(x.get('tonality_guard') for x in bridge));self.assertEqual([x['pitch_midi'] for x in o],[x['pitch_midi'] for x in n])
        self.assertTrue(any(x['type']=='tonality_uncertain_region' for x in r))
    # 连续转调识别与不确定调性保护：整份歌词只有一行时仍能按音段扫描。
    def test_single_text_line_still_has_local_windows(self):
        n,c=sequence(single_line=True);_,s,o,_=normalized(n,c)
        self.assertEqual([x['source_key']['label'] for x in s],['C:major','Db:major']);self.assertEqual([x['pitch_midi'] for x in o],[x['pitch_midi'] for x in n])
    # 连续转调识别与不确定调性保护：升八度不是转调。
    def test_octave_changes_do_not_create_new_key(self):
        n,c=sequence(sections=((0,12),(12,4)));native,s,o,_=normalized(n,c)
        self.assertEqual(native['selected'],'C:major');self.assertEqual(s,[]);self.assertEqual(native['uncertain_regions'],[])
        self.assertEqual([x['pitch_midi'] for x in o],[x['pitch_midi'] for x in n])
    # 连续转调识别与不确定调性保护：孤立短半音沿用既有保守修正，不触发局部保护或换调。
    def test_isolated_chromatic_is_not_a_modulation(self):
        n,c=sequence(sections=((0,12),));n[42]['pitch_midi']=63
        native,s,o,_=normalized(n,c);self.assertEqual(s,[]);self.assertEqual(native['uncertain_regions'],[])
        self.assertNotEqual(o[42]['pitch_midi'],63)
    # 连续转调识别与不确定调性保护：后段更长不能反向改写起始调。
    def test_later_majority_cannot_overwrite_clear_initial_key(self):
        n,c=sequence(sections=((0,4),(1,12)));native,s,o,_=normalized(n,c)
        self.assertEqual(native['selected'],'C:major');self.assertEqual([x['source_key']['label'] for x in s],['C:major','Db:major'])
        self.assertEqual([x['pitch_midi'] for x in o],[x['pitch_midi'] for x in n])
    # 连续转调识别与不确定调性保护：强小调证据只提示支持范围，禁止拿大调候选改原音。
    def test_minor_diagnostic_actually_guards_pitch_correction(self):
        profile=[6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]
        n=[];c=[];clock=1.
        for i,duration in enumerate(profile):
            n.append({'id':str(i),'source_note_id':str(i),'pitch_midi':60+(i+9)%12,'lyric_index':i,'start_seconds':clock,'end_seconds':clock+duration,'confidence':.9})
            c.append({'index':i,'text':chr(0x4e00+i),'line_index':i//6});clock+=duration
        native,_,o,_=normalized(n,c)
        self.assertTrue(native['unsupported_minor_may_fit_better']);self.assertTrue(all(x.get('tonality_guard') for x in o))
        self.assertEqual([x['pitch_midi'] for x in o],[x['pitch_midi'] for x in n])
    # 连续转调识别与不确定调性保护：保护区域不改变原挂词、音段时间及记录的原音高。
    def test_guard_preserves_ownership_timing_and_original_segments(self):
        n,c=sequence(sections=((0,12),(1,1),(0,4)));_,_,o,_=normalized(n,c)
        for raw,after in zip(n,o):
            for k in ('lyric_index','start_seconds','end_seconds'):self.assertEqual(raw[k],after[k])
            self.assertEqual(after['performance_segments'][0]['pitch_midi'],raw['pitch_midi'])
    # 连续转调识别与不确定调性保护：字外音按时间保护，不能添造歌词归属。
    def test_guard_for_unassigned_note_uses_time(self):
        note={'id':'unowned','source_note_id':'unowned','pitch_midi':63,'lyric_index':None,'start_seconds':1.,'end_seconds':1.4,'confidence':.70}
        region={'id':'unknown','first_character_index':0,'last_character_index':1,'start_seconds':.8,'end_seconds':1.6,'candidate_key':'Db:major','reason':'possible_unconfirmed_modulation'}
        out,r=prior.regularize_major([note],score.key_definition('C:major'),[],music.AcousticEvidence({'configuration':{}},False),uncertain_regions=[region])
        self.assertEqual(out[0]['pitch_midi'],63);self.assertIsNone(out[0]['lyric_index']);self.assertEqual(r[0]['preserved_note_count'],1)

    # 连续转调识别与不确定调性保护：平坦音高证据只给零分，输出严格JSON且保音。
    def test_flat_profile_has_finite_scores_and_guard(self):
        import json
        n=[];c=[]
        for i in range(24):
            n.append({'id':str(i),'source_note_id':str(i),'pitch_midi':60+i%12,'lyric_index':i,'start_seconds':float(i),'end_seconds':float(i+1),'confidence':1.})
            c.append({'index':i,'text':chr(0x4e00+i),'line_index':i//8})
        native,_,out,_=normalized(n,c)
        json.dumps(native,allow_nan=False)
        self.assertEqual(native['candidates'][0]['correlation'],0.)
        self.assertTrue(all(note.get('tonality_guard') for note in out))
        self.assertEqual([note['pitch_midi'] for note in out],[note['pitch_midi'] for note in n])

    # 连续转调识别与不确定调性保护：字外长音跨入未知区时整个实际声段保音。
    def test_unassigned_note_overlapping_unknown_boundary_is_guarded(self):
        note={'id':'boundary','source_note_id':'boundary','pitch_midi':63,'lyric_index':None,'start_seconds':.5,'end_seconds':1.5,'confidence':.7}
        region={'id':'unknown','first_character_index':0,'last_character_index':1,'start_seconds':1.,'end_seconds':1.6,'candidate_key':'Db:major','reason':'possible_unconfirmed_modulation'}
        out,_=prior.regularize_major([note],score.key_definition('C:major'),[],music.AcousticEvidence({'configuration':{}},False),uncertain_regions=[region])
        self.assertEqual(out[0]['pitch_midi'],63);self.assertTrue(out[0]['tonality_guard'])

if __name__=='__main__':unittest.main(verbosity=2)
