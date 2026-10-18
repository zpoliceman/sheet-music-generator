"""G大调记谱与参考谱差异分析：验证目标音高、节奏保留和错误输入保护。"""
# G大调记谱与参考谱差异分析：新增独立三音夹具，不以误估Eb调名计算移调量。
import copy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import rekey_simplified_score as rekey
import score_export as score

def fixture():
    notes=[{'id':str(i),'pitch_midi':pitch,'start_tick':i*480,'end_tick':(i+1)*480,
            'lyric_index':i,'collapsed_to_grace':False} for i,pitch in enumerate((63,60,56))]
    characters=[{'index':i,'text':text} for i,text in enumerate('听见开')]
    events=[{'pitch_midi':n['pitch_midi'],'duration_ticks':480,'grace':False,
             'lyric':{'character_index':i,'text':characters[i]['text']}} for i,n in enumerate(notes)]
    return {'title':'测试','notation':{'key':score.key_definition('Eb:major'),'jianpu_reference_midi':51},
            'overrides':{'key':None},'quantized_notes':notes,'events':events,'lyrics':{'characters':characters},
            'simplification':{'profile':'main_melody_with_important_turns'},'timing':{'meter':[4,4]},
            'tempo_events':[{'tick':0,'bpm':92}], 'statistics':{'total_ticks':1920},
            'lyric_mapping':{'mapped_characters':3},'inputs':{'path':'raw'},
            'raw_analysis_preservation':{'sha256':'fixed'}}

class RekeyTests(unittest.TestCase):
    # G大调记谱与参考谱差异分析：新增已知G目标D/B/G、反向还原及不触碰原稿的核查。
    def test_reference_opening_is_d_b_g(self):
        old=fixture();new=rekey.revise_project(old,'source.json','sha','G:major',-1,55)
        self.assertEqual([n['pitch_midi'] for n in new['quantized_notes']],[62,59,55])
        self.assertEqual([score.jianpu_pitch(n['pitch_midi'],new['notation']['key'],55)[0]
                          for n in new['quantized_notes']],['5','3','1'])
        self.assertEqual(new['notation']['key']['fifths'],1)

    def test_original_is_unchanged_and_pitches_reverse_exactly(self):
        old=fixture();frozen=copy.deepcopy(old)
        new=rekey.revise_project(old,'source.json','sha','G:major',-1,55)
        self.assertTrue(rekey.validate_revision(old,new,-1)['valid'])
        self.assertEqual(old,frozen)
        self.assertEqual(new['tempo_events'],old['tempo_events'])
        self.assertEqual(new['lyrics'],old['lyrics'])

    # G大调记谱与参考谱差异分析：新增非法基准/越界音高/隐含节奏修改拒绝测试。
    def test_reject_wrong_tonic_reference(self):
        with self.assertRaises(ValueError):rekey.revise_project(fixture(),'p','s','G:major',-1,56)

    def test_reject_out_of_range_pitch(self):
        old=fixture();old['quantized_notes'][0]['pitch_midi']=1
        with self.assertRaises(ValueError):rekey.revise_project(old,'p','s','G:major',-1,55)

    def test_reject_accidental_rhythm_change(self):
        old=fixture();new=rekey.revise_project(old,'p','s','G:major',-1,55)
        new['quantized_notes'][0]['end_tick']+=120
        with self.assertRaises(ValueError):rekey.validate_revision(old,new,-1)

    def test_reject_accidental_lyric_change(self):
        old=fixture();new=rekey.revise_project(old,'p','s','G:major',-1,55)
        new['lyrics']['characters'][0]['text']='错'
        with self.assertRaises(ValueError):rekey.validate_revision(old,new,-1)

if __name__=='__main__':unittest.main()
