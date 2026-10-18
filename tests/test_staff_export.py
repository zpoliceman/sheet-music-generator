"""十一首可编辑五线谱：独立调号拼写、连梁、压缩交换与中文路径真实排版回归。"""
# 十一首可编辑五线谱：新增会改变音乐含义的反例，不以复制实现计算预期。
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import score_export as score
import staff_export as staff
from export_staff_collection import preferred_rows
from test_score_export import project_from, note, char

# 十一首可编辑五线谱：新增独立八分音符句，不引用任何真实歌曲名称或正确音符表。
def known_project():
    return project_from([note('a',0,.25,60),note('b',.25,.5,62),note('c',.5,.75,64),note('d',.75,1,67)],
                        [char(0,'春',0,.25),char(1,'风',.25,.5),char(2,'Fly',.5,.75),char(3,'high',.75,1)])

class StaffExportTests(unittest.TestCase):
    # 十一首可编辑五线谱：新增高升号调等音拼写和实际音高必须同时正确。
    def test_f_sharp_major_leading_note_is_e_sharp(self):
        self.assertEqual(staff.staff_spelling(65,6),('E',1,4))
        self.assertEqual(staff.staff_spelling(60,7),('B',1,3))
        self.assertEqual(staff.staff_spelling(59,-7),('C',-1,4))

    # 十一首可编辑五线谱：新增临时降三级与简谱级数一致，不记成不相关的自然音。
    def test_flat_chromatic_degree_spelling(self):
        self.assertEqual(staff.staff_spelling(59,-4),('C',-1,4))
        # 十一首可编辑五线谱：原错误预期保留；Ab的#1是A，双降反例改为Cb调的降3。
        # self.assertEqual(staff.staff_spelling(69,-4),('B',-2,4))
        self.assertEqual(staff.staff_spelling(69,-4),('A',0,4))
        self.assertEqual(staff.staff_spelling(62,-7),('E',-2,4))

    # 十一首可编辑五线谱：新增两个八分音符同拍连梁，不跨拍合并四个音符。
    def test_beams_respect_beats_and_preserve_lyrics(self):
        p=known_project();original=score.build_musicxml(p)
        out=staff.build_staff_musicxml(original,'独立例子')
        notes=out.findall('part/measure/note')[:4]
        self.assertEqual([n.findtext('beam') for n in notes],['begin','end','begin','end'])
        self.assertEqual([n.findtext('lyric/text') for n in notes],['春','风','Fly','high'])
        self.assertEqual(out.findtext('part/measure/attributes/staff-details/staff-lines'),'5')
        self.assertEqual(staff.musical_signature(original),staff.musical_signature(out))

    # 十一首可编辑五线谱：新增休止符反例，短休止不错误连接两侧符杠。
    def test_rest_breaks_beam(self):
        p=project_from([note('a',0,.25,60),note('b',.375,.5,62)])
        out=staff.build_staff_musicxml(score.build_musicxml(p),'休止')
        self.assertFalse(out.findall('part/measure/note/beam'))

    # 十一首可编辑五线谱：新增输出不能修改传入的XML对象。
    def test_source_tree_is_immutable(self):
        root=score.build_musicxml(known_project());before=ET.tostring(root)
        staff.build_staff_musicxml(root,'排版')
        self.assertEqual(ET.tostring(root),before)

    # 十一首可编辑五线谱：新增跨调号延音使用同一音名，不因E#到F等音而断开。
    def test_tie_spelling_across_modulation(self):
        p=project_from([note('a',1.75,2.25,65)])
        p['notation']['key']=score.key_definition('F#:major')
        p['notation']['key_segments']=[{'start_measure':1,'key':score.key_definition('F#:major'),'jianpu_reference_midi':66},
                                      {'start_measure':2,'key':score.key_definition('G:major'),'jianpu_reference_midi':67}]
        root=staff.build_staff_musicxml(score.build_musicxml(p),'转调延音')
        pitches=[n.find('pitch') for n in root.findall('part/measure/note') if n.find('pitch') is not None]
        self.assertEqual([(n.findtext('step'),n.findtext('alter','0'),n.findtext('octave')) for n in pitches], [('E','1','4'),('E','1','4')])

    # 十一首可编辑五线谱：新增缺失/重复来源ID被拒绝，避免无法证明未丢音。
    def test_duplicate_ids_rejected(self):
        root=score.build_musicxml(known_project())
        notes=root.findall('part/measure/note');notes[1].set('id',notes[0].get('id'))
        with self.assertRaises(ValueError):staff.build_staff_musicxml(root,'重复ID')

    # 十一首可编辑五线谱：新增语义签名必须捕捉错音和漏词。
    def test_signature_catches_pitch_and_lyric_corruption(self):
        root=score.build_musicxml(known_project());baseline=staff.musical_signature(root)
        changed=copy.deepcopy(root);changed.find('part/measure/note/pitch/step').text='D'
        self.assertNotEqual(baseline,staff.musical_signature(changed))
        changed=copy.deepcopy(root);changed.find('part/measure/note/lyric/text').text='错误'
        self.assertNotEqual(baseline,staff.musical_signature(changed))

    # 十一首可编辑五线谱：新增完整标准MXL容器指向真实可编辑XML，解压字节必须相同。
    def test_mxl_container_and_exact_content(self):
        folder=ROOT/'test_outputs/staff_tests';folder.mkdir(parents=True,exist_ok=True)
        data=ET.tostring(score.build_musicxml(known_project()),encoding='utf-8',xml_declaration=True)
        with tempfile.TemporaryDirectory(dir=folder) as name:
            path=Path(name)/'score.mxl';staff.write_mxl(path,data)
            with zipfile.ZipFile(path) as z:
                root=ET.fromstring(z.read('META-INF/container.xml'))
                ref=root.find('{*}rootfiles/{*}rootfile').get('full-path')
                self.assertEqual(z.read(ref),data)
                self.assertIsNone(z.testzip())

    # 十一首可编辑五线谱：新增同曲首选英文版只输出一次，旧版本仍保留。
    def test_preferred_version_selection(self):
        old={'id':'old'};new={'id':'new'};other={'id':'other'}
        m={'songs':[old,new,other],'preferred_song_versions':{'a':'new','b':'other'}}
        self.assertEqual(preferred_rows(m),[new,other])
        self.assertEqual(len(m['songs']),3)
        m['preferred_song_versions']['b']='missing'
        with self.assertRaises(ValueError):preferred_rows(m)

    # 十一首可编辑五线谱：新增升降号与还原号反例，实际pitch正确仍必须有必要显示符号。
    def test_explicit_chromatic_accidental_and_cancellation(self):
        p=project_from([note('a',0,.25,59),note('b',.25,.5,59),note('c',.5,.75,60)])
        p['notation']['key']=score.key_definition('Ab:major')
        out=staff.build_staff_musicxml(score.build_musicxml(p),'升降还原')
        sounded=[n for n in out.findall('part/measure/note') if n.find('pitch') is not None]
        self.assertEqual([n.findtext('accidental') for n in sounded],['flat',None,'natural'])

    # 十一首可编辑五线谱：新增必要变音符号按八度分别计算，下一小节重新生效。
    def test_accidentals_reset_at_measure_and_octave(self):
        p=project_from([note('a',0,.25,59),note('b',.25,.5,71),note('c',2,2.25,59)])
        p['notation']['key']=score.key_definition('Ab:major')
        out=staff.build_staff_musicxml(score.build_musicxml(p),'八度与小节')
        sounded=[n for n in out.findall('part/measure/note') if n.find('pitch') is not None]
        self.assertEqual([n.findtext('accidental') for n in sounded],['flat','flat','flat'])

    # 十一首可编辑五线谱：新增跨小节延音终点不重复临时号，之后新自然音仍给还原提示。
    def test_tied_accidental_and_following_natural(self):
        p=project_from([note('a',1.75,2.25,59),note('b',2.25,2.5,60)])
        p['notation']['key']=score.key_definition('Ab:major')
        out=staff.build_staff_musicxml(score.build_musicxml(p),'延音还原')
        sounded=[n for n in out.findall('part/measure/note') if n.find('pitch') is not None]
        self.assertEqual([n.findtext('accidental') for n in sounded],['flat',None,'natural'])

    # 十一首可编辑五线谱：新增回导转调反例，原有转调不是用户重新编辑的调号。
    def test_reimport_compares_original_modulation_sections(self):
        import import_score as importer
        p=known_project()
        p['notation']['key_segments']=[{'start_measure':1,'key':score.key_definition('C:major'),'jianpu_reference_midi':60},
                                      {'start_measure':2,'key':score.key_definition('D:major'),'jianpu_reference_midi':62}]
        root=staff.build_staff_musicxml(score.build_musicxml(p),'独立转调')
        inspection=importer.inspect_real_score(root)
        self.assertTrue(inspection['valid'])
        self.assertEqual(importer.global_changes(inspection,p,None),[])
        root.findall('part/measure')[1].find('attributes/key/fifths').text='3'
        changed=importer.global_changes(importer.inspect_real_score(root),p,None)
        self.assertEqual(changed,[{'measure':2,'field':'key','before':[2,'major'],'after':[3,'major']}])

    # 十一首可编辑五线谱：新增真实中文路径排版、MXL往返和来源文件保护综合核验。
    def test_actual_renderer_with_chinese_paths_and_mixed_lyrics(self):
        folder=ROOT/'test_outputs/staff_tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='中文五线谱_',dir=folder) as name:
            path=Path(name);p=known_project();p['title']='中文 English'
            root=score.build_musicxml(p);ET.ElementTree(root).write(path/'vocal_draft.musicxml',encoding='utf-8',xml_declaration=True)
            score.save_json(path/'project.json',p);score.write_midi(path/'vocal_draft.mid',p)
            (path/'jianpu.html').write_text('原谱',encoding='utf-8');(path/'jianpu.svg').write_text('<svg/>',encoding='utf-8')
            before={x.name:score.sha256(x) for x in path.iterdir() if x.is_file()}
            result=staff.export_staff_score(path)
            self.assertEqual(result['status'],'passed')
            self.assertGreaterEqual(result['page_count'],1)
            self.assertTrue(result['renderer_import']['all_pitched_source_ids_visible_in_pages'])
            for file,digest in before.items():self.assertEqual(score.sha256(path/file),digest)
            self.assertIn('MusicXML', (path/'staff.html').read_text(encoding='utf-8'))
            # 十一首可编辑五线谱：新增另存目录导航反例，不能把简谱/MIDI链接留成不存在的同目录文件。
            separated=path/'另存目录';staff.export_staff_score(path,separated)
            doc=(separated/'staff.html').read_text(encoding='utf-8')
            self.assertIn('href="../jianpu.html"',doc)
            self.assertIn('href="../vocal_draft.mid"',doc)

if __name__=='__main__':unittest.main(verbosity=2)
