from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib,json,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import workspace_location as location
from score_export import read_json,sha256
from revise_guitar_selection import verify_sources

class WorkspacePathTests(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)/'new';self.root.mkdir();(self.root/'data').mkdir()
  self.old=Path(self.temp.name)/'old_absent'
  (self.root/'data/workspace_paths.json').write_text(json.dumps({'version':1,'historical_roots':[str(self.old)]}),encoding='utf-8')
 def test_missing_old_root_resolves_without_creating_it(self):
  source=self.root/'source.txt';source.write_text('same audio',encoding='utf-8')
  self.assertEqual(location.local_path(self.old/'source.txt',self.root),source)
  self.assertFalse(self.old.exists())
 def test_json_read_keeps_historical_strings_and_source_digest(self):
  original={'source':str(self.old/'audio.wav'),'title':'sheet_musit_generator'}
  raw=json.dumps(original).encode();(self.root/'project.json').write_bytes(raw)
  with patch.object(location,'__file__',str(self.root/'tools/workspace_location.py')):
   self.assertEqual(read_json(self.old/'project.json'),original)
   self.assertEqual(sha256(self.old/'project.json'),hashlib.sha256(raw).hexdigest())
  self.assertFalse(self.old.exists())
 def test_exact_old_root_only_and_foreign_paths_preserved(self):
  foreign=Path(str(self.old)+'_another')/'file.txt'
  self.assertEqual(location.local_path(foreign,self.root),foreign)
  self.assertEqual(location.local_path('relative.txt',self.root),Path('relative.txt'))
 def test_windows_case_and_slash_variants(self):
  self.assertEqual(location.local_path(str(self.old/'a.txt').upper().replace('\\','/'),self.root),self.root/'A.TXT')
 def test_parent_escape_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'越出'):location.local_path(str(self.old)+'\\..\\outside.txt',self.root)
 def test_file_change_still_fails_source_verification(self):
  source=self.root/'source.wav';source.write_bytes(b'original')
  project={'shared_analysis':{'input_binding':{'sources':{'mix':{'path':str(self.old/'source.wav'),'sha256':hashlib.sha256(b'original').hexdigest()}}}}}
  with patch.object(location,'__file__',str(self.root/'tools/workspace_location.py')):
   self.assertEqual(verify_sources(project)['mix']['path'],str(self.old/'source.wav'))
   source.write_bytes(b'changed')
   with self.assertRaisesRegex(ValueError,'来源已改变'):verify_sources(project)
 def test_invalid_mapping_is_rejected(self):
  location.historical_roots.cache_clear()
  (self.root/'data/workspace_paths.json').write_text('{"version":2}',encoding='utf-8')
  with self.assertRaisesRegex(ValueError,'配置无效'):location.local_path(self.old/'a',self.root)

if __name__=='__main__':unittest.main()
