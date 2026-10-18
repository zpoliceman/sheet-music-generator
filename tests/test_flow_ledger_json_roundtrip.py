"""渴首次吉他编配：新增原指型账本整数弦号JSON往返及真实修改拒绝的独立音频反例。"""
from copy import deepcopy
from pathlib import Path
import sys, tempfile, unittest
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
from test_guitar_instrumental_flow import music, TEST_TEMP
from guitar_instrumental_flow import apply_flow, validate_flow
from score_export import save_json, sha256


class FlowLedgerRoundtripTests(unittest.TestCase):
    # 渴首次吉他编配：新增真实源音频、JSON上游和运行时整数键共存，不将序列化类型变化当音乐变化。
    def test_integer_string_keys_preserved_but_real_finger_edit_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP.resolve()) as tmp:
            tmp=Path(tmp); audio=tmp/'source.wav'; rate=11025; t=np.arange(rate*5)/rate
            sf.write(audio,.1*np.sin(2*np.pi*130.81*t),rate)
            for field in ('instrumental_register','instrumental_source_backbone','regular_rhythm','phrase_harmony_performance'):
                with self.subTest(field=field):
                    shared, vocal, guitar=music()
                    shared['input_binding']={'sources':{'accompaniment':{'path':str(audio),'sha256':sha256(audio),'offset_seconds':0.}}}
                    guitar[field]={'original_grip':{'fingers':{6:1,5:2,4:3}}}
                    parent=tmp/(field+'.json')
                    save_json(parent,{'shared_analysis':shared,'accepted_vocal_project':vocal,'arrangements':{'guitar':guitar}})
                    result,_=apply_flow(shared,vocal,guitar,parent,tmp/'features')
                    self.assertTrue(validate_flow(shared,vocal,result,replay=True)['valid'])
                    self.assertEqual(result[field],guitar[field])
                    altered=deepcopy(result);altered[field]['original_grip']['fingers'][5]=4
                    failure=validate_flow(shared,vocal,altered)
                    self.assertFalse(failure['valid'])
                    self.assertIn('instrumental_flow_original_protection_ledger_changed:'+field,failure['errors'])


if __name__=='__main__':
    unittest.main(verbosity=2)
