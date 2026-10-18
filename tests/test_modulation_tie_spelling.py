"""连续转调识别与不确定调性保护：跨调号延音必须保持一致音名且实际声音不变。"""
# 连续转调识别与不确定调性保护：新增已知Db转D音名/拒绝错误延音反例，不读取雨天答案。
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import score_export as score
from test_score_export import project_from,note,char

class ModulationTieSpellingTests(unittest.TestCase):
    def project(self):
        p=project_from([note('long',1.75,2.375,61)],[char(0,'风',1.75,2.375)])
        p['notation']['key']=score.key_definition('Db:major');p['notation']['jianpu_reference_midi']=61
        p['notation']['key_segments']=[{'start_measure':1,'start_tick':0,'key':score.key_definition('Db:major'),'jianpu_reference_midi':61},{'start_measure':2,'start_tick':1920,'key':score.key_definition('D:major'),'jianpu_reference_midi':62}]
        return p
    def test_enharmonic_tied_note_keeps_start_spelling_across_modulation(self):
        p=self.project();xml=score.build_musicxml(p);self.assertTrue(score.validate_score(p,xml)['valid'])
        tied=[n for n in xml.findall('part/measure/note') if n.find('tie') is not None]
        self.assertEqual([(n.findtext('pitch/step'),n.findtext('pitch/alter'),n.findtext('pitch/octave')) for n in tied],[('D','-1','4'),('D','-1','4')]);self.assertEqual([e['pitch_midi'] for e in p['events'] if e['pitch_midi'] is not None],[61,61])
    def test_wrong_sounding_tie_is_rejected_instead_of_rewritten(self):
        p=self.project();stop=next(e for e in p['events'] if 'stop' in e['ties']);stop['pitch_midi']=62
        with self.assertRaises(ValueError):score.build_musicxml(p)

if __name__=='__main__':unittest.main(verbosity=2)
