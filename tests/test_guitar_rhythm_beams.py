"""六线谱同拍节奏连线：明确节奏真值及错误横梁反例。"""
# 六线谱同拍节奏连线：新增按独立已知节奏检查线数和分组，不用真实歌曲候选当真值。
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from guitar_rhythm_beams import rhythm_events,draw_rhythm,prepare_rhythm,validate_rhythm
NS='{http://www.w3.org/2000/svg}'


# 六线谱同拍节奏连线：新增最小已知起音夹具；可见音符x独立写入SVG供端点回读。
def sample(pattern,meter=(4,4)):
    bar=meter[0]*480*4//meter[1]
    notes=[{'id':f'n{i}','start_tick':tick,'end_tick':tick+duration} for i,(tick,duration) in enumerate(pattern)]
    arrangement={'notes':notes};prepare_rhythm({'timing':{'meter':meter},'statistics':{'bar_ticks':bar}},arrangement)
    events=rhythm_events(notes,meter,bar);root=ET.Element(NS+'svg')
    x_at=lambda tick:40+(tick%bar)*.1+(tick//bar)*240
    for note in notes:
        group=ET.SubElement(root,NS+'g',{'id':note['id'],'data-string':'1','data-start-tick':str(note['start_tick'])})
        ET.SubElement(group,NS+'text',{'x':str(x_at(note['start_tick'])),'y':'226'}).text='0'
    for node in draw_rhythm(events,x_at):root.append(node)
    return root,arrangement


def beams(root,kind='beam'):
    return [(int(n.get('data-level')),round(float(n.get('x1')),3),round(float(n.get('x2')),3))
            for n in root.iter(NS+'line') if n.get('class')=='tab-rhythm-'+kind]


class GuitarRhythmBeamTests(unittest.TestCase):
    def valid(self,root,arrangement):
        result=validate_rhythm([{'guitar':ET.tostring(root,encoding='unicode')}],arrangement)
        self.assertTrue(result['valid'],result)
        return result

    # 六线谱同拍节奏连线：新增明确八分、十六分、混合和附点的可见线条真值。
    def test_two_eighths_share_one_line(self):
        root,a=sample([(0,240),(240,240)])
        self.assertEqual(beams(root),[(1,40.,64.)]);self.assertEqual(beams(root,'hook'),[]);self.valid(root,a)

    def test_four_sixteenths_share_two_lines(self):
        root,a=sample([(0,120),(120,120),(240,120),(360,120)])
        self.assertEqual(beams(root),[(1,40.,76.),(2,40.,76.)]);self.valid(root,a)

    def test_mixed_eighth_and_two_sixteenths(self):
        root,a=sample([(0,240),(240,120),(360,120)])
        self.assertEqual(beams(root),[(1,40.,76.),(2,64.,76.)]);self.valid(root,a)

    def test_isolated_second_level_is_a_short_hook(self):
        root,a=sample([(0,120),(120,240),(360,120)])
        self.assertEqual(beams(root),[(1,40.,76.)])
        self.assertEqual([(level,x) for level,x,_ in beams(root,'hook')],[(2,40.),(2,76.)]);self.valid(root,a)

    def test_dotted_eighth_and_sixteenth(self):
        root,a=sample([(0,360),(360,120)])
        self.assertEqual(beams(root),[(1,40.,76.)])
        self.assertEqual(len([n for n in root.iter(NS+'circle') if n.get('class')=='tab-rhythm-dot']),1)
        self.assertEqual(beams(root,'hook')[0][:2],(2,76.));self.valid(root,a)

    def test_actual_rest_gap_breaks_beam(self):
        root,a=sample([(0,240),(360,240)])
        self.assertEqual(beams(root),[]);self.assertEqual(len(beams(root,'hook')),2);self.valid(root,a)

    def test_quarter_has_no_eighth_beam(self):
        root,a=sample([(0,480),(240,240)])
        self.assertEqual(beams(root),[]);self.assertEqual(len(beams(root,'hook')),1);self.valid(root,a)

    def test_neither_beat_nor_measure_boundary_is_crossed(self):
        for pattern in [[(240,240),(480,240)],[(1680,240),(1920,240)]]:
            root,a=sample(pattern)
            self.assertEqual(beams(root),[]);self.assertEqual(len(beams(root,'hook')),2);self.valid(root,a)

    def test_simultaneous_strings_share_shortest_attack_stem(self):
        root,a=sample([(0,480),(0,120),(120,120)])
        stems=[n for n in root.iter(NS+'line') if n.get('class')=='tab-rhythm-stem']
        self.assertEqual(len(stems),2);self.assertEqual(beams(root),[(1,40.,52.),(2,40.,52.)]);self.valid(root,a)

    def test_six_eighth_meter_groups_three_eighths(self):
        root,a=sample([(0,240),(240,240),(480,240),(720,240)],(6,8))
        self.assertEqual(beams(root),[(1,40.,88.)]);self.assertEqual(len(beams(root,'hook')),1);self.valid(root,a)

    # 六线谱同拍节奏连线：新增可见横梁被破坏时的独立反例。
    def invalid(self,root,a):
        result=validate_rhythm([{'guitar':ET.tostring(root,encoding='unicode')}],a)
        self.assertFalse(result['valid'],result)

    def test_missing_second_line_is_rejected(self):
        root,a=sample([(0,120),(120,120),(240,120),(360,120)])
        parent=next(n for n in root.iter(NS+'g') if n.get('class')=='tab-rhythm-beams')
        parent.remove(next(n for n in parent if n.get('data-level')=='2'));self.invalid(root,a)

    def test_line_joined_across_beats_is_rejected(self):
        root,a=sample([(240,240),(480,240)])
        parent=next(n for n in root.iter(NS+'g') if n.get('class')=='tab-rhythm-beams')
        for node in list(parent):parent.remove(node)
        ET.SubElement(parent,NS+'line',{'class':'tab-rhythm-beam','data-level':'1','x1':'64','x2':'88','y1':'352','y2':'352'})
        self.invalid(root,a)

    def test_sloping_line_is_rejected(self):
        root,a=sample([(0,240),(240,240)])
        next(n for n in root.iter(NS+'line') if n.get('class')=='tab-rhythm-beam').set('y2','346');self.invalid(root,a)

    def test_visible_line_height_overrides_hidden_level(self):
        root,a=sample([(0,240),(240,240)])
        line=next(n for n in root.iter(NS+'line') if n.get('class')=='tab-rhythm-beam')
        line.set('y1','346');line.set('y2','346');self.invalid(root,a)

    def test_stem_not_aligned_with_attack_is_rejected(self):
        root,a=sample([(0,240),(240,240)])
        stem=next(n for n in root.iter(NS+'line') if n.get('class')=='tab-rhythm-stem')
        stem.set('x1','41');stem.set('x2','41');self.invalid(root,a)

    def test_missing_visible_dot_is_rejected(self):
        root,a=sample([(0,360),(360,120)])
        group=next(n for n in root.iter(NS+'g') if n.get('class')=='tab-rhythm-event')
        group.remove(next(n for n in group if n.get('class')=='tab-rhythm-dot'));self.invalid(root,a)


if __name__=='__main__':unittest.main()
