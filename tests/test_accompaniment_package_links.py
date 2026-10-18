"""器乐合理分句与十二品硬限制：异深目录保留包及器乐休止参考视图的实际反例。"""
# 器乐合理分句与十二品硬限制：新增路径测试只用自拟素材，音乐／音频字节必须保持。
from copy import deepcopy
from html.parser import HTMLParser
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET
import contextlib
import io
from types import SimpleNamespace
from unittest.mock import patch

# 器乐合理分句与十二品硬限制：新增独立运行测试的工具路径，不能依赖其它测试先导入。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from accompaniment_package_links import rebase_copied_html
from test_guitar_time_alignment import sample, NS
from guitar_time_alignment import validate_time_alignment
from verify_accompaniment_delivery import delivery_time_alignment


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls.extend(value for key, value in attrs if key in ('href', 'src') or tag == 'option' and key == 'value')


class PackageLinksTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / 'test_outputs/accompaniment_runs/20261013_instrumental_phrase_register_fix/unit_temp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'accepted/package'
        (self.source / 'piano').mkdir(parents=True)
        (self.source / 'audio').mkdir()
        (self.source / 'index.html').write_text('index', encoding='utf-8')
        (self.source / 'audio/vocal.js').write_text('original audio', encoding='utf-8')
        (self.source / 'piano/accompaniment.mid').write_bytes(b'unchanged MIDI bytes')
        self.track = self.root / 'track folder/中文.wav'
        self.track.parent.mkdir()
        self.track.write_bytes(b'unchanged sound bytes')
        relative = quote(Path(os.path.relpath(self.track, self.source / 'piano')).as_posix())
        self.content = ('<a href="../index.html">谱</a><script src="../audio/vocal.js"></script>'
            '<option value="' + relative + '?a=1&amp;b=2#sound">原曲</option>'
            '<a href="https://example.org/music?q=1&amp;b=2">外链</a><a href="#bar">定位</a>'
            '<input value="0.35"><p>6品与18品</p>')
        (self.source / 'piano/score.html').write_text(self.content, encoding='utf-8')

    def tearDown(self):
        self.temporary.cleanup()

    def test_deeper_directory_keeps_external_source_and_internal_resources(self):
        output = self.root / 'temporary/deeper/new/package'
        shutil.copytree(self.source, output)
        changed = rebase_copied_html(self.source, output)
        self.assertEqual(changed, ['piano/score.html'])
        parser = Links()
        parser.feed((output / 'piano/score.html').read_text(encoding='utf-8'))
        local = [urlsplit(url) for url in parser.urls if urlsplit(url).path and not urlsplit(url).scheme]
        targets = [(output / 'piano' / unquote(url.path)).resolve() for url in local]
        self.assertEqual(targets, [(output / 'index.html').resolve(),
                                 (output / 'audio/vocal.js').resolve(), self.track.resolve()])
        self.assertEqual((local[-1].query, local[-1].fragment), ('a=1&b=2', 'sound'))
        self.assertEqual((output / 'piano/accompaniment.mid').read_bytes(), b'unchanged MIDI bytes')
        self.assertEqual(self.track.read_bytes(), b'unchanged sound bytes')
        self.assertEqual((self.source / 'piano/score.html').read_text(encoding='utf-8'), self.content)

    def test_same_depth_can_keep_all_original_html_bytes(self):
        output = self.root / 'accepted/other_package'
        shutil.copytree(self.source, output)
        self.assertEqual(rebase_copied_html(self.source, output), [])
        self.assertEqual((output / 'piano/score.html').read_text(encoding='utf-8'), self.content)

    def test_relocation_is_idempotent_and_preserves_remote_links_and_text(self):
        output = self.root / 'new/deep/package'
        shutil.copytree(self.source, output)
        rebase_copied_html(self.source, output)
        first = (output / 'piano/score.html').read_bytes()
        self.assertEqual(rebase_copied_html(self.source, output), [])
        self.assertEqual((output / 'piano/score.html').read_bytes(), first)
        self.assertIn(b'https://example.org/music?q=1&amp;b=2', first)
        self.assertIn('6品与18品', first.decode('utf-8'))

    def test_missing_original_link_is_not_hidden_and_source_cannot_be_overwritten(self):
        with self.assertRaisesRegex(ValueError, '不能改写原HTML'):
            rebase_copied_html(self.source, self.source)
        (self.source / 'piano/missing.html').write_text('<a href="missing.wav">missing</a>', encoding='utf-8')
        output = self.root / 'different/deep/package'
        shutil.copytree(self.source, output)
        rebase_copied_html(self.source, output)
        self.assertEqual((output / 'piano/missing.html').read_text(encoding='utf-8'), '<a href="missing.wav">missing</a>')

    # 器乐合理分句与十二品硬限制：新增真实纯重导复制／SHA保护边界，音源重合成与任意HTML改写都禁止。
    def run_repeat_link_case(self, tamper=False):
        from test_accompaniment_project_upgrade import fixture
        from accompaniment_project_upgrade import ensure_project_features
        from guitar_repeat_edition import generate_repeat_edition
        from score_export import save_json
        shared, vocal, arrangements, parent = fixture(self.root)
        arrangements, report = ensure_project_features(shared, vocal, arrangements, parent, self.root)
        source = self.root / 'repeat_source'
        (source / 'guitar').mkdir(parents=True)
        save_json(source / 'project.json', {'shared_analysis': shared, 'accepted_vocal_project': vocal,
                                         'arrangements': arrangements})
        save_json(source / 'validation.json', {'valid': True})
        save_json(source / 'manifest.json', {'files': []})
        (source / 'index.html').write_text('<nav></nav>', encoding='utf-8')
        (source / 'guitar/score.html').write_text('accepted score', encoding='utf-8')
        url = quote(Path(os.path.relpath(self.track, source)).as_posix())
        (source / 'review.html').write_text('<audio src="' + url + '"></audio>', encoding='utf-8')
        report['changed'] = False
        report['migrations'] = []
        actual = {n['id']: n for n in arrangements['guitar']['notes']}
        output = self.root / 'deep/repeated/package'

        def draw(*args):
            if tamper:
                (output / 'review.html').write_text('<p>unauthorized rewrite</p>', encoding='utf-8')
            # 吉他编配规则闭环修复：新增链接复制夹具的显式计划文件；实际音乐验收在独立测试中读真文件。
            save_json(output / 'guitar/repeat_plan.json', {'expanded_bars': 2, 'printed_bars': 2})
            return {'valid': True, 'plan': {'expanded_bars': 2, 'printed_bars': 2}}

        args = SimpleNamespace(edited_project=source / 'project.json', output=output,
                               analysis_dir=self.root, report=None)
        with patch('source_meter_entry.require_calibrated_source', return_value={'status': 'test_verified'}), \
             patch('generate_accompaniment.validate_output_path', return_value=output), \
             patch('generate_accompaniment.load_edited_project', return_value=(shared, vocal, arrangements)), \
             patch('generate_accompaniment.write_collection_index'), \
             patch('accompaniment_project_upgrade.ensure_project_features', return_value=(arrangements, report)), \
             patch('accompaniment_export.export_all', side_effect=AssertionError('music regenerated')), \
             patch('guitar_repeat_edition.ET.parse', return_value=SimpleNamespace(getroot=lambda: None)), \
             patch('accompaniment_export.parse_musicxml_notes', return_value=(actual, {'valid': True})), \
             patch('accompaniment_export.validate_midi', return_value={'valid': True}), \
             patch('guitar_readability_acceptance.assess_guitar_readability', return_value={'valid': True, 'errors': []}) as contract, \
             patch('guitar_readability_acceptance.require_guitar_readability', return_value=True) as gate, \
             patch('guitar_repeat_edition.write_repeat_score', side_effect=draw), contextlib.redirect_stdout(io.StringIO()):
            result = generate_repeat_edition(args)
        # 吉他编配规则闭环修复：新增链接入口仍调用实际验收的断言，不以路径保护代替音乐门槛。
        contract.assert_called_once(); gate.assert_called_once()
        parser = Links()
        parser.feed((output / 'review.html').read_text(encoding='utf-8'))
        self.assertEqual((output / unquote(parser.urls[0])).resolve(), self.track.resolve())
        self.assertEqual((source / 'review.html').read_text(encoding='utf-8'), '<audio src="' + url + '"></audio>')
        return result

    def test_real_repeat_copy_accepts_only_deterministic_url_relocation(self):
        result = self.run_repeat_link_case()
        self.assertIn('review.html', result['repeat_edition_preservation']['relocated_html_files'])
        self.assertTrue(result['repeat_edition_preservation']['all_vocal_and_arrangement_objects_unchanged'])

    def test_extra_html_edit_after_relocation_still_fails_sha_guard(self):
        with self.assertRaisesRegex(ValueError, '改变了已认可音乐'):
            self.run_repeat_link_case(tamper=True)


class RestReferenceDisplayTests(unittest.TestCase):
    # 器乐合理分句与十二品硬限制：新增真实SVG隐藏反例，参考背景移除与人声原快照保护同时验证。
    def fixture(self):
        root, arrangement, vocal, shared, _ = sample()
        # 器乐合理分句与十二品硬限制：新增已知120BPM源拍秒，使参考休止使用真实时钟而非仅排版夹具。
        vocal['timing']['knots'] = [{'seconds': 0, 'quarter': 0}, {'seconds': .5, 'quarter': 1}]
        vocal['timing']['steady_tempo_bpm'] = 120
        # 器乐合理分句与十二品硬限制：新增完整无歌词输入，源快照保留而参考图可按批准休止隐藏。
        vocal['lyrics'] = {'characters': []}
        shared['sections'] = [{'kind': 'intro', 'start_tick': 0, 'end_tick': 1920}]
        shared['measure_textures'] = [{'section': 'intro'}]
        arrangement['notation_regions'] = [{'start_tick': 0, 'end_tick': 1920, 'section': 'intro'}]
        arrangement['instrumental_expression'] = {'settings': {'suppress_unlyric_reference_notes': True,
            'rest_intervals': [{'start_seconds': 0, 'end_seconds': 2}]}}
        root.set('data-instrumental-tab-only', 'true')
        parents = {child: node for node in root.iter() for child in node}
        for node in list(root.iter(NS + 'g')):
            if node.get('class') == 'vocal-time-glyph':
                parents[node].remove(node)
        rows = [{'guitar': ET.tostring(root, encoding='unicode')}]
        return rows, arrangement, vocal, shared

    def test_approved_unlyric_rest_uses_display_reference_without_mutating_source(self):
        rows, arrangement, vocal, shared = self.fixture()
        original = deepcopy(vocal)
        self.assertFalse(validate_time_alignment(rows, arrangement, vocal, shared)['valid'])
        checked = delivery_time_alignment(rows, arrangement, vocal, shared)
        self.assertTrue(checked['valid'], checked)
        self.assertEqual(vocal, original)

    def test_real_lyric_note_cannot_be_hidden_by_reference_rest(self):
        rows, arrangement, vocal, shared = self.fixture()
        vocal['quantized_notes'][0]['lyric_index'] = 0
        self.assertFalse(delivery_time_alignment(rows, arrangement, vocal, shared)['valid'])


if __name__ == '__main__':
    unittest.main()
