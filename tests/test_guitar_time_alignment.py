"""节奏符号说明与声部对齐：已知时间、真实SVG中心及故意偏移的反例。"""
# 节奏符号说明与声部对齐：新增独立自拟音乐，覆盖倚音、休止、长音横线及多弦起音。
import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / 'tools'))
from test_score_export import project_from, note
from accompaniment_export import vocal_row, tick_x
from guitar_time_alignment import prepare_alignment, layout_shared_time, annotate_vocal_glyphs, validate_time_alignment
from guitar_rhythm_guide import rhythm_guide_svg
NS = '{http://www.w3.org/2000/svg}'


# 节奏符号说明与声部对齐：新增使用实际简谱渲染但已知独立拍点的夹具，不使用雨天自动音序作真值。
def sample(grace=False, markers=False):
    vocal = project_from([note('a', 0, .25, 60), note('b', .25, .5, 62), note('c', 1, 2, 65)], seconds=2)
    # 节奏符号说明与声部对齐：新增实际渲染标题所需的已知120BPM，不依赖音频模型输出。
    vocal['audio_analysis'] = {'tempo': {'bpm': 120}}; vocal['overrides'] = {'tempo': 120}
    if grace:
        anchor = next(e for e in vocal['events'] if e['offset_ticks'] == 240 and e['pitch_midi'] is not None)
        small = {**anchor, 'id': 'test_grace', 'piece_id': 'grace_piece', 'pitch_midi': 64,
                 'duration_ticks': 0, 'grace': True, 'anchor_id': anchor['piece_id'], 'lyric_index': None}
        small.pop('lyric', None); at = vocal['events'].index(anchor); vocal['events'].insert(at, small)
    arrangement = {'notes': [{'id': f'tab_{i}', 'start_tick': tick, 'end_tick': tick + 120, 'string': 1}
                             for i, tick in enumerate([0, 240, 360, 480, 960, 1440])]}
    arrangement['notes'].append({'id': 'tab_pinch', 'start_tick': 240, 'end_tick': 480, 'string': 2})
    if markers: arrangement['_row_diagram_markers'] = [{'draw_tick': 0}, {'draw_tick': 300}]
    shared = {'sections': [{'kind': 'vocal', 'start_tick': 0, 'end_tick': 1920}],
              'measure_textures': [{'section': 'vocal'}]}
    prepare_alignment(arrangement); scene = vocal_row(vocal, 1, 1)
    old_center = scene.measure_boxes[1]['beats'][0]['glyphs'][0]['x']
    # 节奏符号说明与声部对齐：修改，旧末尾追加装饰保留；按真实绘制顺序紧随所属字形插入。
    # scene.dot(old_center + 15, 118); scene.text(old_center - 16, 118, '#', 22)
    at = next(i for i, item in enumerate(scene.items) if item[0] == 'text' and item[1] == old_center and item[4] == 28)
    scene.items[at+1:at+1] = [('dot', old_center + 15, 118, 2.5, '#14243b'),
                             ('text', old_center - 16, 118, '#', 22, '#14243b', 'middle', 'normal')]
    layout_shared_time(scene, arrangement, 1920); scene.height = 395; root = ET.fromstring(scene.svg())
    annotate_vocal_glyphs(root, scene); root.set('data-first-measure', '1'); root.set('data-last-measure', '1')
    for n in arrangement['notes']:
        group = ET.SubElement(root, NS + 'g', {'id': n['id'], 'data-string': str(n['string']),
                                              'data-start-tick': str(n['start_tick'])})
        ET.SubElement(group, NS + 'text', {'x': str(tick_x(scene.measure_boxes[1], n['start_tick'])),
                                          'y': str(226 + (n['string'] - 1) * 17)}).text = 'x'
    return root, arrangement, vocal, shared, scene


def glyphs(root):
    return [g for g in root.iter(NS + 'g') if g.get('class') == 'vocal-time-glyph']


class GuitarTimeAlignmentTests(unittest.TestCase):
    def check(self, root, a, v, s):
        return validate_time_alignment([{'guitar': ET.tostring(root, encoding='unicode')}], a, v, s)

    # 节奏符号说明与声部对齐：新增可见中心相等、装饰间距和独立时间的正例。
    def test_known_simultaneous_notes_rests_dashes_and_pinch_align(self):
        root, a, v, s, _ = sample(); result = self.check(root, a, v, s)
        self.assertTrue(result['valid'], result); self.assertEqual(result['maximum_center_error_pixels'], 0)
        self.assertEqual(result['simultaneous_vocal_tab_columns'], 5)

    def test_grace_has_space_before_main_and_main_aligns_tab(self):
        root, a, v, s, _ = sample(grace=True); result = self.check(root, a, v, s)
        self.assertTrue(result['valid'], result); self.assertEqual(result['grace_glyphs'], 1)
        small = next(g for g in glyphs(root) if g.get('data-grace') == 'true')
        main = next(g for g in glyphs(root) if g.get('data-grace') == 'false' and g.get('data-start-tick') == '240')
        self.assertGreaterEqual(float(main.find(NS + 'text').get('x')) - float(small.find(NS + 'text').get('x')), 29)

    def test_local_dot_and_accidental_offsets_do_not_stretch(self):
        root, _, _, _, _ = sample(markers=True)
        main = next(g for g in glyphs(root) if g.get('data-start-tick') == '0')
        x = float(main.find(NS + 'text').get('x'))
        dot = next(c for c in root.iter(NS + 'circle') if c.get('cy') == '118')
        accidental = next(t for t in root.iter(NS + 'text') if t.text == '#')
        self.assertAlmostEqual(float(dot.get('cx')) - x, 15, places=6)
        self.assertAlmostEqual(float(accidental.get('x')) - x, -16, places=6)

    def test_diagram_space_keeps_shared_centers_and_order(self):
        root, a, v, s, scene = sample(grace=True, markers=True)
        self.assertTrue(self.check(root, a, v, s)['valid'])
        self.assertLess(tick_x(scene.measure_boxes[1], 240), tick_x(scene.measure_boxes[1], 360))
        self.assertGreater(scene.measure_boxes[1]['width'], 344)

    def test_layout_does_not_mutate_music(self):
        root, a, v, s, _ = sample(grace=True); before = copy.deepcopy((a['notes'], v))
        scene = vocal_row(v, 1, 1); layout_shared_time(scene, a, 1920)
        self.assertEqual(before, (a['notes'], v)); self.assertTrue(self.check(root, a, v, s)['valid'])

    # 节奏符号说明与声部对齐：新增实际移动字形/整声部/横线/倚音和伪造时间的反例。
    def test_shifted_visible_note_is_rejected(self):
        root, a, v, s, _ = sample(); text = glyphs(root)[0].find(NS + 'text')
        text.set('x', str(float(text.get('x')) + 8)); self.assertFalse(self.check(root, a, v, s)['valid'])

    def test_parent_voice_transform_is_rejected(self):
        root, a, v, s, _ = sample()
        next(g for g in root.iter(NS + 'g') if g.get('id') == 'vocal-measure-1').set('transform', 'translate(7,0)')
        self.assertFalse(self.check(root, a, v, s)['valid'])

    def test_shifted_long_note_dash_is_rejected(self):
        root, a, v, s, _ = sample(); dash = next(g for g in glyphs(root) if g.get('data-part') == '1')
        text = dash.find(NS + 'text'); text.set('x', str(float(text.get('x')) - 6))
        self.assertFalse(self.check(root, a, v, s)['valid'])

    def test_collapsed_grace_is_rejected(self):
        root, a, v, s, _ = sample(grace=True)
        small = next(g for g in glyphs(root) if g.get('data-grace') == 'true')
        main = next(g for g in glyphs(root) if g.get('data-grace') == 'false' and g.get('data-start-tick') == '240')
        small.find(NS + 'text').set('x', main.find(NS + 'text').get('x'))
        self.assertFalse(self.check(root, a, v, s)['valid'])

    def test_missing_time_binding_is_rejected(self):
        root, a, v, s, _ = sample(); glyphs(root)[0].set('class', 'unbound-vocal')
        self.assertFalse(self.check(root, a, v, s)['valid'])

    def test_forged_note_time_is_rejected(self):
        root, a, v, s, _ = sample(); glyphs(root)[0].set('data-start-tick', '240')
        self.assertFalse(self.check(root, a, v, s)['valid'])

    def test_rhythm_guide_uses_actual_shapes_and_both_hook_directions(self):
        root = ET.fromstring(rhythm_guide_svg())
        self.assertEqual(len([g for g in root.iter(NS + 'g') if g.get('class') == 'rhythm-legend-example']), 8)
        panel = [g for g in root.iter(NS + 'g') if g.get('class') == 'rhythm-legend-example'][1]
        hooks = [n for n in panel.iter(NS + 'line') if n.get('class') == 'tab-rhythm-hook']
        self.assertEqual(len(hooks), 2)
        self.assertGreater(float(hooks[0].get('x2')), float(hooks[0].get('x1')))
        self.assertLess(float(hooks[1].get('x2')), float(hooks[1].get('x1')))


if __name__ == '__main__': unittest.main()
