"""第三首《我不难过》跨歌曲验证：跨ASR句界和未定位音素身份的通用反例。"""
# 第三首《我不难过》跨歌曲验证：新增已知文本边界与真实owner格式验证。
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import lyrics_align_phrases as windows
import phoneme_evidence as phones


def job(identity, line, start, end, segment):
    return {'job_id':identity, 'line_indices':[line], 'status':'candidate_window',
            'reference_text':'fixture', 'start_seconds':start, 'end_seconds':end,
            'matches':[{'segments':[segment]}], 'warnings':[], 'melody_evidence':{}}


class CrossLineBoundaryTests(unittest.TestCase):
    # 第三首《我不难过》跨歌曲验证：新增句尾被移入下一ASR段的联合窗真值。
    def test_tail_in_next_asr_segment_is_joined_without_changing_text(self):
        reference={'lines':['窗前看看白云远去','我在风中慢慢前行']}
        jobs=[job(0,0,0,4,0),job(1,1,3.5,8,1)]
        before=copy.deepcopy(jobs)
        anchor={'segments':[{'text':'窗前看看'},{'text':'白云远去我在风中慢慢前行'}]}
        result=windows.merge_shared_boundaries(jobs,reference,anchor,[])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['line_indices'],[0,1])
        self.assertEqual(result[0]['reference_text'],'窗前看看白云远去\n我在风中慢慢前行')
        self.assertEqual((result[0]['start_seconds'],result[0]['end_seconds']),(0,8))
        self.assertEqual(jobs,before)

    # 第三首《我不难过》跨歌曲验证：新增重复词正好就是下一句首词时不能误并。
    def test_repeated_head_and_unrelated_prefix_do_not_merge(self):
        reference={'lines':['请你听见我的声音','我的声音正在回响']}
        jobs=[job(0,0,0,4,0),job(1,1,3.5,8,1)]
        for observed in ['我的声音正在回响','另一种声音正在回响']:
            result=windows.merge_shared_boundaries(jobs,reference,{'segments':[{'text':'前句'},{'text':observed}]},[])
            self.assertEqual(len(result),2)

    # 第三首《我不难过》跨歌曲验证：新增长时间间隔不能仅凭文本合并。
    def test_large_gap_does_not_merge(self):
        reference={'lines':['窗前看看白云远去','我在风中慢慢前行']}
        result=windows.merge_shared_boundaries([job(0,0,0,4,0),job(1,1,10,14,1)],reference,
                    {'segments':[{'text':'窗前看看'},{'text':'白云远去我在风中慢慢前行'}]},[])
        self.assertEqual(len(result),2)

    # 第三首《我不难过》跨歌曲验证：新增Hu独立行必须保留。
    def test_vocalization_line_does_not_merge(self):
        reference={'lines':['白云远去Hu','我在风中慢慢前行']}
        result=windows.merge_shared_boundaries([job(0,0,0,4,0),job(1,1,3.5,8,1)],reference,
                    {'segments':[{'text':'白云远去'},{'text':'远去Hu我在风中慢慢前行'}]},[])
        self.assertEqual(len(result),2)


    # 第三首《我不难过》跨歌曲验证：新增真实锚点result.segments结构进入完整计划的集成反例。
    def test_full_planner_uses_filtered_segments_from_nested_anchor(self):
        from unittest.mock import patch
        reference={'lines':['窗前看看白云远去','我在风中慢慢前行'],
                   'source':{'duration_seconds':10.},'reference_kind':'user_supplied'}
        anchor={'result':{'segments':[{'text':'窗前看看','start':0.,'end':4.},
                                    {'text':'白云远去我在风中慢慢前行','start':4.,'end':8.}]}}
        mapping=[{'kind':'match','line':i,'lines':[i],'segments':[i],'weighted_edit_ratio':0.} for i in range(2)]
        with patch.object(windows,'match_lines',return_value=(mapping,[],0.)):
            result=windows.plan_jobs(reference,anchor,{'notes':[]},.35)
        self.assertEqual(len(result['jobs']),1)
        self.assertEqual(result['jobs'][0]['line_indices'],[0,1])
        self.assertEqual(result['jobs'][0]['window_method'],'asr_shared_boundary_joint_tifa')


class SkippedPhoneOwnerTests(unittest.TestCase):
    # 第三首《我不难过》跨歌曲验证：新增完全跳过字的owner仍来自原G2P而不是猜测或时间均分。
    def fixture(self, directory):
        directory=Path(directory);crop=directory/'crop.wav';crop.write_bytes(b'identity')
        source={'sha256':'source','offset_seconds':0}
        local={'path':str(crop),'sha256':phones.sha256(crop),'offset_seconds':10}
        raw=directory/'raw.json';raw.write_text(json.dumps({'source':local,'results':[{'texts':['云'],
            'phoneme_states':[{'word_owner':1,'text':'云','phoneme':'zh/uen','start_seconds':0,'end_seconds':0}]}]}),encoding='utf-8')
        character={'index':0,'text':'云','group_id':'phrase_0_None','phrase_job_id':0,'start_seconds':None,'end_seconds':None,
                   'phoneme_source':{'word_owner':1},'warnings':['alignment_missing']}
        lyrics={'source':source,'cache_key':{'text_sha256':'text'},'characters':[character]}
        report={'source':source,'cache_key':{'text_sha256':'text'},'phrase_reports':[{'job_id':0,'crop':local,'original_source':source,'raw_alignment':str(raw)}]}
        return lyrics,report

    def test_valid_raw_owner_keeps_times_unassigned_and_state_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            lyrics,report=self.fixture(directory);original=copy.deepcopy(lyrics)
            result=phones.enrich(lyrics,report)['characters'][0]
            self.assertIsNone(result['start_seconds']);self.assertIsNone(result['end_seconds'])
            self.assertTrue(result['phonemes'][0]['skipped']);self.assertEqual(result['phoneme_source']['word_owner'],1)
            self.assertEqual(lyrics,original)

    # 第三首《我不难过》跨歌曲验证：新增无owner/冲突owner仍拒绝，不能放宽原有身份校验。
    def test_absent_or_conflicting_owner_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lyrics,report=self.fixture(directory)
            changed=copy.deepcopy(lyrics);changed['characters'][0]['phoneme_source']={}
            with self.assertRaises(ValueError): phones.enrich(changed,report)
            changed=copy.deepcopy(lyrics);changed['characters'][0]['group_id']='phrase_0_tifa_word_2'
            with self.assertRaisesRegex(ValueError,'冲突'): phones.enrich(changed,report)


if __name__=='__main__': unittest.main(verbosity=2)
