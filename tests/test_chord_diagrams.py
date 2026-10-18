"""和弦指型与X六线谱：已知按法、可见几何与真实音高的独立反例。"""
# 和弦指型与X六线谱：新增针对读谱转换的语义测试，不以真实歌曲候选当音乐真值。
import copy
import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from test_accompaniment import fixture
import accompaniment_arrange as arrange
import accompaniment_export as export
from guitar_chord_diagrams import prepare_diagrams,draw_diagram,read_diagram,visible_diagrams
NS='{http://www.w3.org/2000/svg}'


# 和弦指型与X六线谱：新增明确C/D按法、已按音、非和弦音、空弦及同音异弦夹具。
def known_score():
    shared,vocal=fixture()
    def diagram(identity,frets,name,begin,end,position=1):
        grip=arrange.grip_info(frets)
        return {'id':identity,'chord_id':'h0' if begin==0 else 'h1','frets':{str(s):f for s,f in frets.items()},
                'position':position,'shape_name':name,'sounding_name':name,'capo':0,'barre':grip['barre'],
                'simplified':False,'start_tick':begin,'end_tick':end,'reason':'chord_change'}
    diagrams=[diagram('c',{5:3,4:2,3:0,2:1,1:0},'C',0,1920),
              diagram('d',{4:0,3:2,2:3,1:2},'D',1920,3840)]
    notes=[]
    for identity,string,fret,tick in [('bass',5,3,0),('held_c',2,1,240),('extra_f',1,1,480),
                                      ('open_e',1,0,720),('other_c',3,5,960),('d_third',1,2,1920)]:
        notes.append({'id':identity,'string':string,'fret':fret,'pitch_midi':arrange.TUNING[string]+fret,
                      'start_tick':tick,'end_tick':tick+180,'role':'bass' if identity=='bass' else 'instrumental_melody',
                      'finger':0 if fret==0 else 1,'hand_position':1})
    guitar={'instrument':'guitar','configuration':{'capo_fret':0},'notes':notes,'attack_events':[],
            'fingering_diagrams':diagrams,'hand_positions':[{'tick':0,'position':1}]}
    return shared,vocal,guitar


class ChordDiagramTests(unittest.TestCase):
    # 和弦指型与X六线谱：新增标准F横按及高把位图的几何真值。
    def test_black_dots_and_barre_without_finger_numbers(self):
        _,_,g=known_score();chart=copy.deepcopy(g['fingering_diagrams'][0])
        frets={6:1,5:3,4:3,3:2,2:1,1:1};chart.update({'frets':{str(s):f for s,f in frets.items()},'shape_name':'F','barre':[1,6,1]})
        chart.update({'display_id':'f','draw_tick':0,'display_end_tick':1920})
        node=draw_diagram(chart,100);decoded=read_diagram(node)
        self.assertEqual(decoded['frets'],frets)
        dots=[n for n in node if n.get('class')=='pressed-string']
        self.assertEqual(len(dots),6);self.assertTrue(all(n.get('fill')=='#000' for n in dots))
        self.assertEqual(len([n for n in node if n.get('class')=='barre']),1)
        self.assertFalse(any((n.text or '').isdigit() for n in node if n.tag==NS+'text'))

    def test_high_position_first_row_has_exact_fret(self):
        _,_,g=known_score();chart=copy.deepcopy(g['fingering_diagrams'][1])
        frets={6:7,5:9,4:9,3:8,2:7,1:7}
        chart.update({'frets':{str(s):f for s,f in frets.items()},'position':7,'barre':[1,6,7],
                      'display_id':'high','draw_tick':0,'display_end_tick':1920})
        node=draw_diagram(chart,100)
        self.assertEqual(next(n.text for n in node if n.get('class')=='position-label'),'7品')
        self.assertEqual(read_diagram(node)['frets'],frets)

    def test_x_requires_same_string_and_same_fret(self):
        s,v,g=known_score();root=ET.fromstring(export.guitar_row(s,v,g,1,2))
        labels={n.get('id'):n.find(NS+'text').text for n in root.iter(NS+'g') if n.get('data-string')}
        # 空弦沿用指型X表示：修改，原空弦0期望保留；已未按住的空弦也沿用指型为x。
        # self.assertEqual(labels,{'bass':'x','held_c':'x','extra_f':'1','open_e':'0','other_c':'5','d_third':'x'})
        self.assertEqual(labels,{'bass':'x','held_c':'x','extra_f':'1','open_e':'x','other_c':'5','d_third':'x'})
        check=export.validate_tab([{'guitar':ET.tostring(root,encoding='unicode')}],g)
        # 空弦沿用指型X表示：修改，原3个x保留为注释；新增一个无需改变左手的空弦x。
        # self.assertTrue(check['valid'],check);self.assertEqual(check['x_count'],3)
        self.assertTrue(check['valid'],check);self.assertEqual(check['x_count'],4)

    # 和弦指型与X六线谱：新增有效音高外的图/文字/时间/弦线篡改反例。
    def changed(self,mutate):
        s,v,g=known_score();root=ET.fromstring(export.guitar_row(s,v,g,1,2));mutate(root)
        return export.validate_tab([{'guitar':ET.tostring(root,encoding='unicode')}],g)

    def test_wrong_visible_black_dot_is_rejected(self):
        def mutate(root):
            dot=next(n for n in root.iter(NS+'circle') if n.get('class')=='pressed-string')
            dot.set('cy',str(float(dot.get('cy'))+13))
        self.assertFalse(self.changed(mutate)['valid'])

    def test_wrong_visible_position_label_is_rejected(self):
        def mutate(root):next(n for n in root.iter(NS+'text') if n.get('class')=='position-label').text='2品'
        self.assertFalse(self.changed(mutate)['valid'])

    # 空弦沿用指型X表示：修改，旧版未按空弦不可x的反例保留；改查真正需新增按指的音。
    # def test_x_on_unpressed_string_is_rejected(self):
    #     def mutate(root):next(n for n in root.iter(NS+'g') if n.get('id')=='open_e').find(NS+'text').text='x'
    def test_x_cannot_replace_note_needing_added_finger(self):
        def mutate(root):next(n for n in root.iter(NS+'g') if n.get('id')=='extra_f').find(NS+'text').text='x'
        self.assertFalse(self.changed(mutate)['valid'])

    def test_x_on_same_pitch_other_string_is_rejected(self):
        def mutate(root):next(n for n in root.iter(NS+'g') if n.get('id')=='other_c').find(NS+'text').text='x'
        self.assertFalse(self.changed(mutate)['valid'])

    def test_note_moved_to_wrong_visible_string_is_rejected(self):
        def mutate(root):
            node=next(n for n in root.iter(NS+'g') if n.get('id')=='held_c').find(NS+'text')
            node.set('y',str(float(node.get('y'))+17))
        self.assertFalse(self.changed(mutate)['valid'])

    def test_x_with_another_time_segment_is_rejected(self):
        def mutate(root):
            ids=[n.get('id') for n in root.iter(NS+'g') if n.get('class')=='chord-diagram']
            next(n for n in root.iter(NS+'g') if n.get('id')=='held_c').set('data-diagram-id',ids[-1])
        self.assertFalse(self.changed(mutate)['valid'])

    def test_pressed_chord_note_numeric_label_is_rejected(self):
        def mutate(root):next(n for n in root.iter(NS+'g') if n.get('id')=='held_c').find(NS+'text').text='1'
        self.assertFalse(self.changed(mutate)['valid'])

    # 和弦指型与X六线谱：新增整行图缺失、漏绑和空弦符号损坏反例。
    def test_all_diagrams_removed_returns_invalid(self):
        def mutate(root):
            for node in list(root):
                if node.get('class')=='chord-diagram':root.remove(node)
        self.assertFalse(self.changed(mutate)['valid'])

    def test_numeric_chord_note_cannot_hide_its_diagram_binding(self):
        def mutate(root):
            group=next(n for n in root.iter(NS+'g') if n.get('id')=='held_c')
            group.find(NS+'text').text='1';group.attrib.pop('data-diagram-id')
        self.assertFalse(self.changed(mutate)['valid'])

    def test_unknown_string_status_is_rejected(self):
        def mutate(root):next(n for n in root.iter(NS+'text') if n.get('class')=='string-status').text='?'
        self.assertFalse(self.changed(mutate)['valid'])

    def test_preparation_keeps_sound_and_held_notes_playable(self):
        shared,vocal=fixture();g=arrange.arrange_guitar(shared,vocal,1);before=copy.deepcopy(g['notes'])
        plan=prepare_diagrams(shared,g);self.assertEqual(before,g['notes']);self.assertTrue(plan)
        for chart in plan:
            for tick in {chart['start_tick'],*[n['start_tick'] for n in g['notes'] if chart['start_tick']<=n['start_tick']<chart['end_tick']]}:
                effective={int(s):f for s,f in chart['frets'].items()}
                effective.update({n['string']:n['fret'] for n in g['notes'] if n['start_tick']<=tick<n['end_tick']})
                self.assertIsNotNone(arrange.grip_info(effective))

    def test_row_start_repeats_current_diagram(self):
        s,_,g=known_score();g['fingering_diagrams'][0]['end_tick']=3840;g['fingering_diagrams']=g['fingering_diagrams'][:1]
        shown=visible_diagrams(s,g,2,2)
        self.assertEqual(len(shown),1);self.assertEqual(shown[0]['draw_tick'],1920);self.assertEqual(shown[0]['id'],'c')


if __name__=='__main__':unittest.main()
