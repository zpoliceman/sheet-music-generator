"""连续转调识别与不确定调性保护：跨句冲突需要联合原声预测的独立条件。"""
# 连续转调识别与不确定调性保护：新增通用时间/词内共享/语言隔离边界测试。
import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from lyrics_boundary_recovery import conflicting_groups,joint_window

def char(index,start,end,job):return {'index':index,'start_seconds':start,'end_seconds':end,'phrase_job_id':job}

class BoundaryRecoveryTests(unittest.TestCase):
    def test_reverse_and_duplicate_voice_are_detected(self):
        chars=[char(0,1.,1.4,0),char(1,.98,1.5,1),char(2,2.,2.5,2),char(3,2.3,2.7,3)];before=copy.deepcopy(chars)
        self.assertEqual(conflicting_groups(chars),[[0,1],[2,3]]);self.assertEqual(chars,before)
    def test_shared_word_span_in_same_prediction_is_valid(self):
        self.assertEqual(conflicting_groups([char(0,1.,2.,0),char(1,1.,2.,0)]),[])
        self.assertEqual(conflicting_groups([char(0,1.,2.,0),char(1,2.01,3.,1)]),[])
    def test_joint_window_uses_whole_original_text_and_source_bounds(self):
        plan={'jobs':[{'job_id':0,'line_indices':[0],'status':'candidate_window','start_seconds':1.,'end_seconds':3.},{'job_id':1,'line_indices':[1],'status':'candidate_window','start_seconds':2.8,'end_seconds':5.}]};reference={'lines':['放心离开我','我会记得这一刻']};before=copy.deepcopy(plan)
        job=joint_window(plan,[0,1],reference,2);self.assertEqual(job['reference_text'],'放心离开我\n我会记得这一刻');self.assertEqual((job['start_seconds'],job['end_seconds']),(1.,5.));self.assertEqual(plan,before)
    def test_unsupported_window_is_not_silently_merged(self):
        plan={'jobs':[{'job_id':0,'line_indices':[0],'status':'candidate_window','start_seconds':1.,'end_seconds':3.},{'job_id':1,'line_indices':[1],'status':'unassigned_unsupported_language'}]}
        with self.assertRaises(ValueError):joint_window(plan,[0,1],{'lines':['中文','hello']},2)

if __name__=='__main__':unittest.main(verbosity=2)
