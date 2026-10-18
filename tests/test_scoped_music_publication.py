"""两曲简谱吉他确认发布：授权范围、冻结音乐和索引门槛反例。"""
# 两曲简谱吉他确认发布：新增通用临时材料，不依赖曲名或原曲人工答案。
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from score_export import save_json,read_json,sha256
from scoped_music_publication import validate_manifest,published_text

class ScopedPublicationTests(unittest.TestCase):
    def setUp(self):
        # 两曲简谱吉他确认发布：新增来源和不可混同的钢琴未决夹具。
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.folder=self.base/'released';self.folder.mkdir();self.source=self.base/'source.json';self.approval=self.base/'approval.json'
        project={'bar_boundary_revision':{'changes':[{'id':'boundary'}]},'music_acceptance':{'status':'needs_review','unresolved':['piano_deferred']}}
        save_json(self.source,project);save_json(self.folder/'project.json',project)
        for name in ('index.html','vocal/score.html','guitar/score.html','guitar/score_full.html'):
            p=self.folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('<p>frozen</p>','utf8')
        self.review={'publication_authorized':True,'instruments':['vocal','guitar'],'accepted_cards':['boundary'],
            'source_candidates':{'case':{'project':str(self.source),'sha256':sha256(self.source)}}}
        save_json(self.approval,self.review)
        self.manifest={'version':1,'instruments':['vocal','guitar'],'source_project':str(self.source),'source_project_sha256':sha256(self.source),
            'approval':str(self.approval),'approval_sha256':sha256(self.approval),'music_acceptance':{'status':'passed','unresolved':[],
            'published_instruments':['vocal','guitar'],'clock_and_downbeat':True,'lyric_ownership_and_full_duration':True,
            'accompaniment_original_audio':True,'confirmed_music_regression':True,'playability_and_export':True},
            'files':{p.relative_to(self.folder).as_posix():sha256(p) for p in self.folder.rglob('*') if p.is_file()}}
        self.save()
    def save(self):save_json(self.folder/'publication.json',self.manifest)
    def test_scope_accepts_vocal_guitar_without_clearing_deferred_piano(self):
        m,p=validate_manifest(self.folder)
        self.assertEqual(m['instruments'],['vocal','guitar']);self.assertEqual(p['music_acceptance']['unresolved'],['piano_deferred'])
    def test_changed_score_cannot_reuse_acceptance(self):
        (self.folder/'guitar/score.html').write_text('changed','utf8')
        with self.assertRaises(ValueError):validate_manifest(self.folder)
    def test_unapproved_boundary_or_scope_rejected(self):
        for values in ({'publication_authorized':False},{'accepted_cards':[]},{'instruments':['vocal','guitar','piano']}):
            review={**self.review,**values};save_json(self.approval,review);self.manifest['approval_sha256']=sha256(self.approval);self.save()
            with self.assertRaises(ValueError):validate_manifest(self.folder)
    def test_extra_piano_cannot_piggyback_on_guitar_approval(self):
        (self.folder/'piano').mkdir()
        with self.assertRaises(ValueError):validate_manifest(self.folder)
    def test_index_rechecks_scoped_manifest_and_keeps_old_index_on_rejection(self):
        from generate_accompaniment import write_collection_index
        index=self.base/'index.html';index.write_text('original','utf8')
        with patch('scoped_music_publication.require_scoped_publication',side_effect=ValueError('changed')):
            with self.assertRaises(ValueError):write_collection_index(self.base,self.folder/'index.html')
        self.assertEqual(index.read_text('utf8'),'original')
        with patch('scoped_music_publication.require_scoped_publication',return_value={'valid':True}) as check:
            write_collection_index(self.base,self.folder/'index.html');check.assert_called_once()
        self.assertIn('released/index.html',index.read_text('utf8'))
    def test_status_text_does_not_touch_svg_or_timing_script(self):
        music='<svg><path d="M 0 0"/></svg><script>window.beats=[1,2]</script>'
        output=published_text('隔离候选 · 本版尚未通过整曲音乐验收。'+music)
        self.assertTrue(output.endswith(music));self.assertNotIn('尚未',output)

    def prepare_all_instruments(self):
        # 三曲确认发布与右手选择交接：新增独立完整成品夹具，精确绑定用户所批准的每一份文件。
        import shutil
        candidate=self.base/'candidate';candidate.mkdir()
        for p in self.folder.rglob('*'):
            if p.is_file() and p.name!='publication.json':
                target=candidate/p.relative_to(self.folder);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        for kind in ('vocal','guitar','piano'):
            for filename in ('score.html','score.musicxml','score.mxl','score.mid','preview.wav'):
                p=candidate/kind/filename;p.parent.mkdir(parents=True,exist_ok=True)
                if not p.exists():p.write_text('frozen-'+kind+'-'+filename,'utf8')
                target=self.folder/p.relative_to(candidate);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        self.source=candidate/'project.json'
        self.review['instruments']=['vocal','guitar','piano']
        self.review['source_candidates']={'case':{'project':str(self.source),'sha256':sha256(self.source),
            'files':{p.relative_to(candidate).as_posix():sha256(p) for p in candidate.rglob('*') if p.is_file()}}}
        save_json(self.approval,self.review)
        self.manifest.update(version=2,instruments=self.review['instruments'],source_project=str(self.source),
            source_project_sha256=sha256(self.source),approval_sha256=sha256(self.approval))
        self.manifest['music_acceptance']['published_instruments']=self.review['instruments']
        self.refresh_files()

    def refresh_files(self):
        # 三曲确认发布与右手选择交接：新增自报摘要更新，用于验证不能仅重写摘要就绕过认可来源。
        self.manifest['files']={p.relative_to(self.folder).as_posix():sha256(p) for p in self.folder.rglob('*') if p.is_file() and p.name!='publication.json'}
        self.save()

    def test_explicit_all_instruments_authorization_preserves_historical_project(self):
        # 三曲确认发布与右手选择交接：新增三项明确授权正例；不修改冻结工程原来的待听审记录。
        self.prepare_all_instruments();manifest,project=validate_manifest(self.folder)
        self.assertEqual(manifest['instruments'],['vocal','guitar','piano'])
        self.assertEqual(project['music_acceptance']['unresolved'],['piano_deferred'])

    def test_all_instruments_cannot_use_previous_guitar_only_authorization(self):
        # 三曲确认发布与右手选择交接：新增旧范围授权不能顺带批准钢琴，v1也不能自行扩范围。
        self.prepare_all_instruments();self.review['instruments']=['vocal','guitar']
        save_json(self.approval,self.review);self.manifest['approval_sha256']=sha256(self.approval);self.save()
        with self.assertRaises(ValueError):validate_manifest(self.folder)
        self.manifest['version']=1;self.save()
        with self.assertRaises(ValueError):validate_manifest(self.folder)

    def test_piano_changes_rejected_even_if_manifest_is_rehashed(self):
        # 三曲确认发布与右手选择交接：新增真实发布文件改变后，自报摘要不能取代已认可成品保护。
        self.prepare_all_instruments();(self.folder/'piano/preview.wav').write_bytes(b'changed');self.refresh_files()
        with self.assertRaises(ValueError):validate_manifest(self.folder)

    def test_missing_piano_or_changed_approved_source_rejected(self):
        # 三曲确认发布与右手选择交接：新增必需钢琴文件缺失及认可来源改变均拒绝，不能只检查工程JSON。
        self.prepare_all_instruments();original=(self.folder/'piano/score.mid').read_bytes()
        (self.folder/'piano/score.mid').unlink();self.refresh_files()
        with self.assertRaises(ValueError):validate_manifest(self.folder)
        (self.folder/'piano/score.mid').write_bytes(original);self.refresh_files()
        (self.source.parent/'piano/preview.wav').write_bytes(b'changed')
        with self.assertRaises(ValueError):validate_manifest(self.folder)

if __name__=='__main__':unittest.main()
