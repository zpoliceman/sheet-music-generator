"""空弦沿用指型X表示：空弦、松手、横按及旧版兼容的已知反例。"""
# 空弦沿用指型X表示：新增按独立C指型与横按真值核对实际音高，不改变既有歌曲。
import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from test_chord_diagrams import known_score
import accompaniment_export as export
from guitar_chord_diagrams import left_hand_fret
NS='{http://www.w3.org/2000/svg}'


# 空弦沿用指型X表示：新增高把位C指型，五弦虽通常不拨仍受八品横按覆盖。
def barre_score():
    shared,vocal,g=known_score();chart=g['fingering_diagrams'][0]
    chart.update({'frets':{'6':8,'4':10,'3':9,'2':8,'1':8},'position':8,'barre':[1,6,8]})
    base=copy.deepcopy(g['notes'][0]);g['notes']=[]
    for identity,fret,tick in [('release_barre',0,0),('covered_barre',8,480)]:
        g['notes'].append({**base,'id':identity,'string':5,'fret':fret,'pitch_midi':45+fret,
                           'start_tick':tick,'end_tick':tick+240,'finger':0 if fret==0 else 1,'hand_position':8})
    g['hand_positions']=[{'tick':0,'position':8}]
    return shared,vocal,g


def render(shared,vocal,g,first=1,last=2):
    return ET.fromstring(export.guitar_row(shared,vocal,g,first,last))


def text(root,identity):
    return next(n for n in root.iter(NS+'g') if n.get('id')==identity).find(NS+'text')


def check(root,g):
    return export.validate_tab([{'guitar':ET.tostring(root,encoding='unicode')}],g)


class OpenStringXTests(unittest.TestCase):
    # 空弦沿用指型X表示：新增无需变指的两类空弦以及必须松指/新增按指的区别。
    def test_marked_open_string_is_x_and_decodes_as_open_pitch(self):
        s,v,g=known_score();root=render(s,v,g)
        self.assertEqual(text(root,'open_e').text,'x');r=check(root,g)
        self.assertTrue(r['valid'],r);self.assertEqual(r['open_string_x_count'],1);self.assertEqual(r['open_string_count'],1)
        self.assertEqual(r['displayed_zero_count'],0)

    def test_unplayed_unfretted_string_is_also_open_x(self):
        s,v,g=known_score();base=g['notes'][0]
        g['notes'].append({**base,'id':'unused_open','string':6,'fret':0,'pitch_midi':40,
                           'start_tick':1200,'end_tick':1440,'finger':0})
        root=render(s,v,g)
        self.assertEqual(text(root,'unused_open').text,'x');self.assertTrue(check(root,g)['valid'])

    def test_releasing_existing_finger_stays_zero(self):
        s,v,g=known_score();g['fingering_diagrams'][0]['frets']['1']=2
        root=render(s,v,g);self.assertEqual(text(root,'open_e').text,'0')
        r=check(root,g);self.assertTrue(r['valid'],r);self.assertEqual(r['displayed_zero_count'],1)

    def test_adding_finger_stays_actual_fret_number(self):
        s,v,g=known_score();root=render(s,v,g)
        self.assertEqual(text(root,'extra_f').text,'1');self.assertTrue(check(root,g)['valid'])

    def test_barre_covered_unmarked_string_is_pressed(self):
        s,v,g=barre_score();root=render(s,v,g,1,1)
        self.assertEqual(left_hand_fret(g['fingering_diagrams'][0],5),8)
        self.assertEqual(text(root,'release_barre').text,'0');self.assertEqual(text(root,'covered_barre').text,'x')
        r=check(root,g);self.assertTrue(r['valid'],r);self.assertEqual(r['open_string_x_count'],0)

    # 空弦沿用指型X表示：新增可见横按、空弦x和松手0损坏反例。
    def test_open_x_numeric_zero_without_hand_change_is_rejected(self):
        s,v,g=known_score();root=render(s,v,g);text(root,'open_e').text='0'
        self.assertFalse(check(root,g)['valid'])

    def test_release_zero_changed_to_x_is_rejected(self):
        s,v,g=barre_score();root=render(s,v,g,1,1);text(root,'release_barre').text='x'
        self.assertFalse(check(root,g)['valid'])

    def test_missing_visible_barre_is_rejected(self):
        s,v,g=barre_score();root=render(s,v,g,1,1)
        chart=next(n for n in root.iter(NS+'g') if n.get('class')=='chord-diagram')
        chart.remove(next(n for n in chart if n.get('class')=='barre'))
        self.assertFalse(check(root,g)['valid'])

    def test_visible_barre_moved_to_wrong_fret_is_rejected(self):
        s,v,g=barre_score();root=render(s,v,g,1,1)
        line=next(n for n in root.iter(NS+'line') if n.get('class')=='barre')
        line.set('y1',str(float(line.get('y1'))+13));line.set('y2',str(float(line.get('y2'))+13))
        self.assertFalse(check(root,g)['valid'])

    def test_legacy_numeric_open_string_rule_is_still_valid(self):
        s,v,g=known_score();root=render(s,v,g)
        g['tab_display']={'mode':'chord_grip_x','open_string':'0'};text(root,'open_e').text='0'
        r=check(root,g);self.assertTrue(r['valid'],r);self.assertEqual(r['x_count'],3)


if __name__=='__main__':unittest.main()
