# 兼容性与样曲验证：新增真实音频回归检查，只修改项目内临时副本，不触碰用户原件。
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('audio_inventory', PROJECT / 'tools' / 'audio_inventory.py')
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)

# 兼容性与样曲验证：新增覆盖同名换源、缓存损坏、读取失败和片段幂等的集成回归。
class AudioRegressions(unittest.TestCase):
    def test_real_audio_cache_and_samples(self):
        original_root = audio.ROOT
        tools = {name: audio.tool(name) for name in ('ncmdump', 'ffprobe', 'ffmpeg')}
        # 第三首《我不难过》跨歌曲验证：修改夹具路径发现以适配用户目录整理，原真实素材选择保留。
        # originals = [PROJECT / 'test_music' / name for name in ('孙燕姿 - 遇见.ncm', '孙燕姿 - 雨天.ncm')]
        originals = [audio.discover_audio_sources(PROJECT / 'test_music', name)[0]
                     for name in ('孙燕姿 - 遇见.ncm', '孙燕姿 - 雨天.ncm')]
        hashes = [audio.sha256(path) for path in originals]
        temporary = tempfile.TemporaryDirectory(prefix='audio_regression_', dir=PROJECT / '.tools')
        sandbox = Path(temporary.name).resolve()
        self.assertTrue(sandbox.is_relative_to((PROJECT / '.tools').resolve()))
        try:
            audio.ROOT = sandbox
            source = sandbox / 'test_music' / 'probe.ncm'
            source.parent.mkdir(parents=True)
            shutil.copyfile(originals[0], source)
            first = audio.process(source, **tools)
            self.assertEqual(first['status'], 'verified', first)
            self.assertFalse(first['conversion_cached'])
            cached = audio.process(source, **tools)
            self.assertTrue(cached['conversion_cached'])
            self.assertEqual(first['audio_sha256'], cached['audio_sha256'])
            # 兼容性与样曲验证：验证同名素材换内容必重新还原，不能把旧音频算作新源结果。
            shutil.copyfile(originals[1], source)
            replaced = audio.process(source, **tools)
            self.assertEqual(replaced['status'], 'verified', replaced)
            self.assertFalse(replaced['conversion_cached'])
            self.assertNotEqual(first['source_sha256_before'], replaced['source_sha256_before'])
            self.assertNotEqual(first['audio_sha256'], replaced['audio_sha256'])
            self.assertAlmostEqual(replaced['duration_seconds'], 241.867029, places=4)
            # 兼容性与样曲验证：验证损坏产物哈希失配后重新生成，缺失源记录失败且不抛出整批异常。
            Path(replaced['audio']).write_bytes(b'incomplete test cache')
            repaired = audio.process(source, **tools)
            self.assertEqual(repaired['status'], 'verified', repaired)
            self.assertFalse(repaired['conversion_cached'])
            self.assertEqual(replaced['audio_sha256'], repaired['audio_sha256'])
            missing = audio.process(sandbox / 'test_music' / 'missing.ncm', **tools)
            self.assertEqual(missing['status'], 'failed')
            self.assertFalse(missing['source_unchanged'])
            # 兼容性与样曲验证：验证实际帧数、重复提取复用和不同参数独立输出。
            sample = audio.make_sample(repaired, tools['ffmpeg'], 40.0, 0.5)
            repeated = audio.make_sample(repaired, tools['ffmpeg'], 40.0, 0.5)
            self.assertTrue(repeated['extraction_cached'])
            self.assertEqual(sample['sample'], repeated['sample'])
            self.assertEqual(repeated['actual_wav']['frames'], 22050)
            other = audio.make_sample(repaired, tools['ffmpeg'], 41.0, 0.5)
            self.assertNotEqual(sample['sample'], other['sample'])
            self.assertTrue(Path(sample['sample']).exists())
            with self.assertRaises(ValueError):
                audio.make_sample(repaired, tools['ffmpeg'], 300.0, 30.0)
        finally:
            audio.ROOT = original_root
            # 兼容性与样曲验证：清理前再次确认仅限本轮项目内临时目录。
            self.assertTrue(Path(temporary.name).resolve().is_relative_to((PROJECT / '.tools').resolve()))
            temporary.cleanup()
        self.assertEqual(hashes, [audio.sha256(path) for path in originals])

# 第三首《我不难过》跨歌曲验证：新增路径选择边界测试，临时假文件只用于枚举，不参与音频验证。
class AudioSourceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='discovery_', dir=PROJECT / '.tools')
        self.root = Path(self.temporary.name)
        for name in ['flat.ncm', '歌曲/歌声.ncm', '歌曲/原音.FLAC', '歌曲/歌词.txt', '歌曲/吉他谱.pdf']:
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture')
        self.addCleanup(self.temporary.cleanup)

    # 第三首《我不难过》跨歌曲验证：新增顶层和子目录混合素材，歌词/谱子不得当作音源。
    def test_recursive_audio_extensions_only(self):
        actual = audio.discover_audio_sources(self.root)
        self.assertEqual({path.relative_to(self.root).as_posix() for path in actual},
                         {'flat.ncm', '歌曲/歌声.ncm', '歌曲/原音.FLAC'})

    # 第三首《我不难过》跨歌曲验证：新增同一文件的文件名、正斜线、反斜线和绝对路径选择。
    def test_basename_and_explicit_nested_paths(self):
        expected = self.root / '歌曲/歌声.ncm'
        for selection in ['歌声.ncm', '歌曲/歌声.ncm', '歌曲\\歌声.ncm', str(expected)]:
            self.assertEqual(audio.discover_audio_sources(self.root, selection), [expected])

    # 第三首《我不难过》跨歌曲验证：新增同名歧义必须拒绝，明确子路径能够消歧。
    def test_duplicate_basename_requires_explicit_path(self):
        duplicate = self.root/'另一首/歌声.ncm'; duplicate.parent.mkdir(); duplicate.write_bytes(b'other')
        with self.assertRaises(ValueError): audio.discover_audio_sources(self.root, '歌声.ncm')
        self.assertEqual(audio.discover_audio_sources(self.root, '另一首/歌声.ncm'), [duplicate])

    # 第三首《我不难过》跨歌曲验证：新增缺失音源、非音频和越界路径均不能进入模型入口。
    def test_missing_non_audio_and_outside_paths_rejected(self):
        for selection in ['没有.ncm', '歌曲/吉他谱.pdf', '../outside.ncm']:
            with self.assertRaises(ValueError): audio.discover_audio_sources(self.root, selection)


# 兼容性与样曲验证：新增标准库测试入口。
if __name__ == '__main__':
    unittest.main(verbosity=2)
