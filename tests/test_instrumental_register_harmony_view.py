"""器乐乐句和声视图统一通用修复：原分析与最终和声不同的分句／来源复核反例。"""
# 器乐乐句和声视图统一通用修复：新增自拟重复器乐，不含任何歌曲固定答案。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parent)]
from test_guitar_instrumental_register import music
from guitar_instrumental_register import arrange_instrumental_register, validate_instrumental_register, melodic_phrases, editable_notes
from phrase_harmony_plan import POLICY, shared_fingerprint, vocal_fingerprint, arrangement_view


# 器乐乐句和声视图统一通用修复：新增原分析换根音而最终伴奏保留共同根音的合法来源夹具。
def fixture():
    shared, vocal, guitar = music(repeat=True)
    original = deepcopy(shared['harmony'][0])
    one = {**original, 'id': 'source_one', 'start_tick': 0, 'end_tick': 960, 'root_pc': 0, 'bass_pc': 0}
    two = {**original, 'id': 'source_two', 'start_tick': 960, 'end_tick': 1920, 'root_pc': 7, 'bass_pc': 7}
    shared['harmony'] = [one, two] + deepcopy(shared['harmony'][1:])
    shared['arranged_harmony'] = deepcopy(shared['harmony']); shared['arranged_harmony'][1].update(root_pc=0, bass_pc=0)
    for n in guitar['notes']:
        if n['start_tick'] < 1920: n['chord_id'] = 'source_one' if n['start_tick'] < 960 else 'source_two'
        # 器乐乐句和声视图统一通用修复：新增取消夹具固有休止，只有实际和声变化才能在此分句。
        if n['id'] == 'm2': n['end_tick'] = 960
    shared['phrase_harmony_plan'] = {'version': POLICY['version'], 'source_shared_sha256': shared_fingerprint(shared),
                                    'source_vocal_sha256': vocal_fingerprint(vocal)}
    return shared, vocal, guitar


class InstrumentalRegisterHarmonyViewTests(unittest.TestCase):
    # 器乐乐句和声视图统一通用修复：新增实际计划与旧分析分句数不同的有效工程，不能被旧视图误拒绝。
    def test_validation_uses_same_final_harmony_as_planning(self):
        shared, vocal, guitar = fixture(); before = deepcopy(shared)
        editable = editable_notes(shared, guitar)
        self.assertNotEqual(len(melodic_phrases(shared, guitar['notes'], editable)),
                            len(melodic_phrases(arrangement_view(shared, vocal), guitar['notes'], editable)))
        result, _ = arrange_instrumental_register(shared, vocal, guitar)
        check = validate_instrumental_register(shared, vocal, result)
        self.assertTrue(check['valid'], check['errors'])
        self.assertEqual(shared, before)

    # 器乐乐句和声视图统一通用修复：新增用实际视图后仍必须拒绝被篡改的句域账本。
    def test_changed_phrase_plan_is_still_rejected(self):
        shared, vocal, guitar = fixture()
        result, _ = arrange_instrumental_register(shared, vocal, guitar)
        result['instrumental_register']['report']['phrase_plan']['source_phrase_count'] += 1
        check = validate_instrumental_register(shared, vocal, result)
        self.assertFalse(check['valid']); self.assertIn('instrumental_register_phrase_plan_changed', check['errors'])


# 器乐乐句和声视图统一通用修复：新增标准测试入口。
if __name__ == '__main__': unittest.main()
