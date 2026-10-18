"""相似长段复用与默认阅读修复：真实变奏、误折叠和实际印刷反例。"""
# 相似长段复用与默认阅读修复：新增完全自拟材料，不以歌名或实际秒数作为算法答案。
from copy import deepcopy
from pathlib import Path
import sys,tempfile,unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
from test_guitar_variable_repeat import project_fixture
from guitar_variable_repeat import build_repeat_plan,validate_repeat_plan,measure_timeline
from guitar_repeat_variants import printed_music_sources,block_variants,validate_variant_tabs
from export_timing_revision import write_variable_repeat_score
from accompaniment_export import html_page
from guitar_readability_acceptance import _actual_repeat_print
NS='{http://www.w3.org/2000/svg}'


def fixture(variants=(5,)):
    # 相似长段复用与默认阅读修复：新增两遍12小节四分B321，同一主题仅指定第二遍上声部真实变奏。
    p=project_fixture(variable=False,length=12,gap=16);g=p['arrangements']['guitar'];count=p['accepted_vocal_project']['statistics']['measure_count']
    g['section_patterns']={'arranged_measures':list(range(1,count+1))}
    for note in g['notes']:
        note.update(section='vocal',end_tick=note['start_tick']+480)
        if note['start_tick']//1920+1 in [29+i for i in variants] and note['string']==1:
            note.update(pitch_midi=note['pitch_midi']+3,fret=note['fret']+3)
    return p


def write_fixture(p,folder):
    # 相似长段复用与默认阅读修复：新增真实HTML／SVG输出供独立解码，不以策略标签替代图元。
    (folder/'rows').mkdir()
    # 完整乐句与实际时长复用：修改测试底稿为真实完整谱行，使新增实际书写量／面积验收有独立对照。
    # (folder/'score.html').write_text(html_page('自拟复用','<nav></nav><section class="score-row">完整原顺序</section>'),encoding='utf-8')
    from export_timing_revision import render_row
    timeline=measure_timeline(p)
    body=''.join('<section class="score-row">'+render_row(p,timeline[i:i+4],True)+'</section>' for i in range(0,len(timeline),4))
    (folder/'score.html').write_text(html_page('自拟复用','<nav></nav>'+body),encoding='utf-8')
    result=write_variable_repeat_score(p,folder)
    import json
    plan=json.loads((folder/'repeat_plan.json').read_text('utf8'))
    return result,plan


class GuitarRepeatVariantTests(unittest.TestCase):
    def test_adjacent_variants_share_band_without_overlap_and_clipping_is_rejected(self):
        # 完整乐句与实际时长复用：新增相邻真实变奏并排及恶意裁切反例，避免节省小节却放大空白。
        p=fixture((4,5))
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);result,plan=write_fixture(p,folder)
            self.assertTrue(result['explicit_variants']['valid'])
            rows=[];paired=False
            for path in sorted((folder/'rows').glob('repeat_*.svg')):
                root=ET.parse(path).getroot()
                variants=[node for node in root.iter() if node.get('data-repeat-variant-pass')]
                if len(variants)==2:
                    paired=True
                    self.assertEqual(variants[0].get('y'),variants[1].get('y'))
                    first,second=sorted(variants,key=lambda node:float(node.get('x')))
                    self.assertLessEqual(float(first.get('x'))+float(first.get('width'))-15,float(second.get('x'))+15)
                    first.set('y',str(float(root.get('height'))))
                rows.append({'guitar':ET.tostring(root,encoding='unicode')})
            self.assertTrue(paired)
            check=validate_variant_tabs(p,plan,rows)
            self.assertFalse(check['valid'])
            self.assertIn('variant_clipped_or_invalid_band',check['errors'])

    def test_first_or_last_bar_variant_keeps_a_complete_long_theme(self):
        # 相似长段复用与默认阅读修复：新增句首／句末变奏的独立反例，不能只允许中间差异。
        for offset in (0,11):
            p=fixture((offset,));plan=build_repeat_plan(p)
            self.assertEqual(plan['shared_span_bars'],12)
            self.assertEqual(plan['variant_printed_bars'],1)
            self.assertTrue(validate_repeat_plan(plan,p)['valid'])
            variant=plan['repeat_groups'][0]['variant_bars'][0]
            self.assertEqual(variant['canonical_measure'],1+offset)
            self.assertEqual(variant['source_measure'],29+offset)

    def test_long_theme_with_one_real_variant_folds_without_changing_music(self):
        original=fixture();before=deepcopy(original);plan=build_repeat_plan(original)
        self.assertEqual(plan['shared_span_bars'],12);self.assertEqual(plan['saved_bars'],11)
        self.assertEqual(plan['variant_printed_bars'],1);self.assertEqual(len(plan['jumps']),1)
        self.assertTrue(validate_repeat_plan(plan,original)['valid'])
        sources=printed_music_sources(plan);self.assertEqual([v['performed_measure'] for v in sources],list(range(1,len(sources)+1)))
        self.assertEqual(sources[33]['printed_source_measure'],34)
        self.assertEqual(sources[32]['printed_source_measure'],5)
        self.assertEqual(original,before)

    def test_too_many_different_bars_are_not_folded_as_same_pattern(self):
        plan=build_repeat_plan(fixture((1,3,5,7,9)))
        self.assertEqual(plan['saved_bars'],0)

    def test_instrumental_or_irregular_variant_does_not_enter_near_match(self):
        for change in ('instrumental','rhythm'):
            p=fixture();note=next(n for n in p['arrangements']['guitar']['notes'] if n['start_tick']//1920==33 and n['string']==1)
            if change=='instrumental':note.update(role='instrumental_melody',section='interlude')
            else:note['end_tick']-=120
            self.assertEqual(build_repeat_plan(p)['saved_bars'],0)

    def test_variant_mapping_cannot_be_removed_to_hide_actual_difference(self):
        p=fixture();plan=build_repeat_plan(p);plan['repeat_groups'][0]['variant_bars']=[]
        result=validate_repeat_plan(plan,p)
        self.assertFalse(result['valid']);self.assertTrue(any('实际音乐' in e for e in result['errors']))

    def test_real_visible_variant_tab_and_full_page_notice_are_exported(self):
        p=fixture();before=deepcopy(p)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);result,plan=write_fixture(p,folder)
            self.assertTrue(result['explicit_variants']['valid']);self.assertEqual(result['explicit_variants']['actual_variant_bars'],1)
            actual=_actual_repeat_print(p,folder,plan);self.assertTrue(actual['valid'],actual['errors'])
            self.assertIn('当前是完整展开对照版',(folder/'score_full.html').read_text('utf8'))
            self.assertIn('打开复用阅读谱',(folder/'score_full.html').read_text('utf8'))
            self.assertIn('替换上方',(folder/'score.html').read_text('utf8'))
        self.assertEqual(p,before)

    def test_removing_actual_variant_tab_from_both_files_and_page_fails(self):
        p=fixture()
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);_,plan=write_fixture(p,folder)
            for path in (folder/'rows').glob('repeat_*.svg'):
                old=path.read_text('utf8');root=ET.fromstring(old);parents={c:q for q in root.iter() for c in q}
                nodes=[n for n in root.iter() if n.get('data-repeat-variant-pass')]
                if not nodes:continue
                for node in nodes:parents[node].remove(node)
                new=ET.tostring(root,encoding='unicode');path.write_text(new,encoding='utf8')
                page=(folder/'score.html').read_text('utf8').replace(old,new);(folder/'score.html').write_text(page,encoding='utf8')
            actual=_actual_repeat_print(p,folder,plan)
            self.assertFalse(actual['valid']);self.assertTrue(any('variant' in e or 'tab' in e for e in actual['errors']))

    def test_changing_visible_variant_caption_or_source_is_rejected(self):
        p=fixture()
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);_,plan=write_fixture(p,folder);rows=[]
            for path in sorted((folder/'rows').glob('repeat_*.svg')):
                root=ET.parse(path).getroot()
                for node in root.iter():
                    if node.get('data-variant-caption-source'):node.text='错误地追加一小节'
                rows.append({'guitar':ET.tostring(root,encoding='unicode')})
            actual=validate_variant_tabs(p,plan,rows)
            self.assertFalse(actual['valid']);self.assertIn('variant_visible_replacement_caption_missing_or_changed',actual['errors'])

    def test_variant_cannot_be_shifted_to_the_wrong_lyric_column(self):
        # 相似长段复用与默认阅读修复：新增实际横向错列反例；音符和来源元数据保持也必须拒绝。
        p=fixture()
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);_,plan=write_fixture(p,folder);rows=[]
            for path in sorted((folder/'rows').glob('repeat_*.svg')):
                root=ET.parse(path).getroot()
                for node in root.iter():
                    if node.get('data-repeat-variant-pass'):node.set('x',str(float(node.get('x'))+100))
                rows.append({'guitar':ET.tostring(root,encoding='unicode')})
            actual=validate_variant_tabs(p,plan,rows)
            self.assertFalse(actual['valid']);self.assertIn('variant_not_below_its_shared_measure',actual['errors'])


if __name__=='__main__':
    # 相似长段复用与默认阅读修复：新增直接执行保护。
    unittest.main()
