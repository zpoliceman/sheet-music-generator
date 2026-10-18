"""渴首次吉他编配：新增组合升级的真实输入阶段绑定与原工程保护反例。"""
from copy import deepcopy
from pathlib import Path
import sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
from test_accompaniment import fixture
from accompaniment_arrange import arrange_requested
from generate_accompaniment import source_revision_input
from score_export import read_json, save_json, sha256


class InstrumentalRevisionInputTests(unittest.TestCase):
    # 渴首次吉他编配：新增组合升级已改变和声／音符时，骨干来源必须绑定当前实际阶段而非早期工程。
    def test_changed_stage_is_bound_without_overwriting_original(self):
        shared,vocal=fixture();shared['input_binding']['requested_instruments']=['guitar']
        arrangements=arrange_requested(shared,vocal,0)
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            tmp=Path(tmp); original=tmp/'accepted.json'
            save_json(original,{'shared_analysis':shared,'accepted_vocal_project':vocal,'arrangements':arrangements})
            original_sha=sha256(original)
            fresh_shared=deepcopy(shared);fresh_shared['harmony'][0]['name']='本阶段和声'
            fresh_arrangements=deepcopy(arrangements);fresh_arrangements['guitar']['notes'][0]['velocity']=72
            source=source_revision_input(fresh_shared,vocal,fresh_arrangements,original,tmp)
            self.assertNotEqual(source,original)
            snapshot=read_json(source)
            self.assertEqual(snapshot['shared_analysis'],fresh_shared)
            # 渴首次吉他编配：修改，旧整字典断言受JSON调弦整数键转换影响；真实音乐与指型参数分项核验。
            # self.assertEqual(snapshot['arrangements'],fresh_arrangements)
            self.assertEqual(snapshot['arrangements']['guitar']['notes'],fresh_arrangements['guitar']['notes'])
            self.assertEqual(snapshot['arrangements']['guitar']['configuration']['capo_fret'],fresh_arrangements['guitar']['configuration']['capo_fret'])
            self.assertEqual(sha256(original),original_sha)
            self.assertEqual(source_revision_input(fresh_shared,vocal,fresh_arrangements,original,tmp),source)
            # 渴首次吉他编配：新增来源缓存被改写时不得重新覆盖并伪装为合法同一来源。
            snapshot['arrangements']['guitar']['notes'][0]['velocity']=1;save_json(source,snapshot)
            with self.assertRaisesRegex(ValueError,'不能覆盖器乐骨干修订'):source_revision_input(fresh_shared,vocal,fresh_arrangements,original,tmp)

    # 渴首次吉他编配：新增未改变音乐的纯器乐升级继续绑定原工程，JSON整数键往返不制造伪变更。
    def test_identical_music_keeps_original_input_even_with_integer_string_keys(self):
        shared,vocal=fixture();shared['input_binding']['requested_instruments']=['guitar'];arrangements=arrange_requested(shared,vocal,0)
        arrangements['guitar']['grip_fingerings']={'example':{6:1,5:2}}
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            original=Path(tmp)/'original.json'
            save_json(original,{'schema_version':1,'shared_analysis':shared,'accepted_vocal_project':vocal,'arrangements':arrangements})
            self.assertEqual(source_revision_input(shared,vocal,arrangements,original,tmp),original.resolve())
            self.assertEqual([p.name for p in Path(tmp).iterdir()],['original.json'])


if __name__=='__main__':
    unittest.main(verbosity=2)
