"""歌词对齐与真实制谱：校正版回导的结构、身份及原始数据保护回归。"""
# 歌词对齐与真实制谱：新增标准库测试依赖，临时文件限定在独占correction_check目录。
import copy
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import import_score as importer

# 歌词对齐与真实制谱：新增独立已知一小节真值，不把真实自动结果用作音乐正确性真值。
def fixture():
    root = ET.fromstring('''<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Test</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>480</divisions><key><fifths>0</fifths><mode>major</mode></key><time><beats>4</beats><beat-type>4</beat-type></time></attributes><direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome></direction-type><sound tempo="120"/></direction><note id="n1"><pitch><step>C</step><octave>4</octave></pitch><duration>480</duration><voice>1</voice><type>quarter</type><lyric number="1"><syllabic>single</syllabic><text>春</text></lyric></note><note id="n2"><pitch><step>D</step><octave>4</octave></pitch><duration>480</duration><voice>1</voice><type>quarter</type><lyric number="1"><syllabic>single</syllabic><text>风</text></lyric></note><note id="n3"><rest/><duration>960</duration><voice>1</voice><type>half</type></note></measure></part></score-partwise>''')
    events = [dict(id="n1", measure=1, offset_ticks=0, start_tick=0, duration_ticks=480, pitch_midi=60,
                   grace=False, ties=[], piece_id="raw1", lyric={"text":"春", "extend":None}),
              dict(id="n2", measure=1, offset_ticks=480, start_tick=480, duration_ticks=480, pitch_midi=62,
                   grace=False, ties=[], piece_id="raw2", lyric={"text":"风", "extend":None}),
              dict(id="n3", measure=1, offset_ticks=960, start_tick=960, duration_ticks=960, pitch_midi=None,
                   grace=False, ties=[], piece_id=None)]
    return root, events


class ImportTests(unittest.TestCase):
    # 歌词对齐与真实制谱：新增隔离测试目录和固定原始分析，清理前验证绝对路径在指定目录内。
    def setUp(self):
        directory = ROOT / "test_outputs/scores/correction_check"
        directory.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="test_import_", dir=directory)
        self.directory = Path(self.temporary.name).resolve()
        self.assertTrue(self.directory.is_relative_to(directory.resolve()))
        self.root, self.events = fixture()
        self.analysis = {"pitch_frames":{"time_seconds":[0,0.1,0.2],"f0_hz":[261.625,262,0]},
                         "raw_segments":[{"segment":0,"original_times":[0,1]}], "notes":[{"id":"raw1","pitch_midi":60}]}
        self.analysis_path = self.directory / "analysis.json"
        importer.save_json(self.analysis_path, self.analysis)
        self.project = {"schema_version":1,"artifact_kind":"real_audio_automatic_draft",
                        "inputs":{"notes_path":str(self.analysis_path),"notes_sha256":importer.file_sha(self.analysis_path)},
                        "events":self.events,"quantized_notes":[{"id":"raw1","start_seconds":0}],
                        "raw_analysis_preservation":{"original_notes_and_continuous_f0":str(self.analysis_path)},
                        "tempo_events":[{"tick":0,"bpm":120}]}
        self.project_path = self.directory / "project.json"
        self.xml_path = self.directory / "score.musicxml"
        self.output = self.directory / "corrected.json"
        self.report_path = self.directory / "report.json"
        importer.save_json(self.project_path, self.project)
        self.write_xml()

    def tearDown(self):
        self.assertTrue(self.directory.is_relative_to((ROOT / "test_outputs/scores/correction_check").resolve()))
        self.temporary.cleanup()

    def write_xml(self):
        ET.ElementTree(self.root).write(self.xml_path, encoding="utf-8", xml_declaration=True)

    def run_import(self):
        self.write_xml()
        return importer.import_correction(self.xml_path, self.project_path, self.output, self.report_path)

    # 歌词对齐与真实制谱：新增真实schema零修改回导、完整声学归档及源SHA保护。
    def test_unchanged_roundtrip_preserves_everything(self):
        before = {str(path):importer.file_sha(path) for path in (self.xml_path,self.project_path,self.analysis_path)}
        result = self.run_import()
        self.assertEqual(result["status"],"corrected_score_imported")
        self.assertEqual(result["changed_fields"],[])
        saved = importer.read_json(self.output)
        self.assertEqual(saved["events"],self.events)
        self.assertEqual(saved["preserved_analysis"]["content"],self.analysis)
        self.assertTrue(all(importer.file_sha(path)==fingerprint for path,fingerprint in before.items()))
        self.assertEqual(saved["active_notation_layer"],"corrected_score")

    # 歌词对齐与真实制谱：新增恰好一处音高与一处文字改动的差异检测和历史。
    def test_pitch_and_lyric_edits(self):
        self.root.find("part/measure/note/pitch/step").text="E"
        self.root.findall("part/measure/note")[1].find("lyric/text").text="雨"
        result=self.run_import()
        self.assertEqual(sorted(change["field"] for change in result["changed_fields"]),["lyrics","pitch_midi"])
        saved=importer.read_json(self.output)
        self.assertEqual(saved["events"][0]["pitch_midi"],60)
        self.assertEqual(saved["corrected_score"]["events"][0]["pitch_midi"],64)
        self.assertEqual(len(saved["revision_history"]),1)

    # 歌词对齐与真实制谱：新增编辑器丢ID时只生成候选，不伪造源事件绑定。
    def test_missing_id_requires_review(self):
        self.root.find("part/measure/note").attrib.pop("id")
        result=self.run_import()
        self.assertEqual(result["status"],"imported_requires_identity_review")
        self.assertEqual(result["uncertain_event_count"],1)
        event=importer.read_json(self.output)["corrected_score"]["events"][0]
        self.assertEqual(event["source_mapping"]["candidate_event_ids"],["n1"])
        self.assertNotIn("source_event_id",event["source_mapping"])

    # 歌词对齐与真实制谱：新增ID重排不能继续宣称稳定身份映射。
    def test_reordered_ids_require_review(self):
        notes=self.root.findall("part/measure/note")
        notes[0].set("id","n2")
        notes[1].set("id","n1")
        result=self.run_import()
        self.assertEqual(result["uncertain_event_count"],3)
        self.assertIn("known_ids_reordered",[x["type"] for x in result["mapping_issues"]])

    # 歌词对齐与真实制谱：新增重复XML id违反唯一性时拒绝回导。
    def test_duplicate_ids_rejected(self):
        self.root.findall("part/measure/note")[1].set("id","n1")
        result=self.run_import()
        self.assertEqual(result["status"],"rejected_invalid_or_unsupported_score")
        self.assertFalse(self.output.exists())

    # 歌词对齐与真实制谱：新增小节越界与记谱/播放时值不一致的负例。
    def test_bad_measure_rejected(self):
        self.root.find("part/measure/note/duration").text="481"
        result=self.run_import()
        self.assertFalse(result["validation"]["valid"])
        self.assertFalse(self.output.exists())

    # 歌词对齐与真实制谱：新增多声部不误读成顺序单旋律。
    def test_multiple_voice_rejected(self):
        self.root.findall("part/measure/note")[1].find("voice").text="2"
        self.assertFalse(self.run_import()["validation"]["valid"])

    # 歌词对齐与真实制谱：新增损坏跨音延音终点检出。
    def test_broken_tie_rejected(self):
        left,right=self.root.findall("part/measure/note")[:2]
        for note,kind in ((left,"start"),(right,"stop")):
            ET.SubElement(note,"tie",type=kind)
            ET.SubElement(ET.SubElement(note,"notations"),"tied",type=kind)
        self.assertFalse(self.run_import()["validation"]["valid"])

    # 歌词对齐与真实制谱：新增等价divisions缩放不得误报校正。
    def test_scaled_divisions_normalizes(self):
        for element in self.root.findall(".//divisions")+self.root.findall(".//duration"):
            element.text=str(int(element.text)*2)
        result=self.run_import()
        self.assertEqual(result["status"],"corrected_score_imported")
        self.assertEqual(result["changed_fields"],[])

    # 歌词对齐与真实制谱：新增小节内tempo的sound偏移真值，防止只看视觉位置。
    def test_sound_offset_and_default_no(self):
        measure=self.root.find("part/measure")
        direction=ET.Element("direction")
        ET.SubElement(ET.SubElement(direction,"direction-type"),"words").text=""
        offset=ET.SubElement(direction,"offset",sound="yes")
        offset.text="480"
        ET.SubElement(direction,"sound",tempo="90")
        measure.insert(2,direction)
        result=importer.inspect_real_score(self.root)
        self.assertEqual(result["tempo_events"][-1],{"tick":480,"bpm":90.0})
        offset.attrib.clear()
        result=importer.inspect_real_score(self.root)
        self.assertEqual(result["tempo_events"][-1],{"tick":0,"bpm":90.0})
        self.assertTrue(result["warnings"])

    # 歌词对齐与真实制谱：新增原分析发生变化时拒绝错误引用，禁止覆盖输入。
    def test_source_hash_and_output_protection(self):
        with self.assertRaises(ValueError):
            importer.import_correction(self.xml_path,self.project_path,self.project_path)
        importer.save_json(self.analysis_path,{"changed":True})
        with self.assertRaises(ValueError):
            self.run_import()

    # 歌词对齐与真实制谱：新增第二次回导只追加修订且不重写自动层/f0。
    def test_revision_history_accumulates(self):
        self.root.find("part/measure/note/pitch/step").text="E"
        self.run_import()
        second=self.directory / "second.json"
        result=importer.import_correction(self.xml_path,self.output,second)
        self.assertEqual(result["changed_fields"],[])
        saved=importer.read_json(second)
        self.assertEqual(len(saved["revision_history"]),2)
        self.assertEqual(saved["events"],self.events)
        self.assertEqual(saved["preserved_analysis"]["content"],self.analysis)

    # 歌词对齐与真实制谱：新增全局速度修改必须进入修订历史，不伪装成零改动。
    def test_tempo_edit_recorded(self):
        self.root.find("part/measure/direction/sound").set("tempo","90")
        result=self.run_import()
        self.assertEqual([change["field"] for change in result["changed_fields"]],["tempo_events"])

    # 歌词对齐与真实制谱：新增非法音名和微分音应拒绝，而非在计算中静默舍入。
    def test_illegal_pitch_rejected(self):
        self.root.find("part/measure/note/pitch/step").text="H"
        self.assertFalse(self.run_import()["validation"]["valid"])
        self.root.find("part/measure/note/pitch/step").text="C"
        ET.SubElement(self.root.find("part/measure/note/pitch"),"alter").text="0.5"
        self.assertFalse(self.run_import()["validation"]["valid"])

    # 歌词对齐与真实制谱：新增程序化演示必须真正回导且只修改两类字段。
    def test_demonstration(self):
        result=importer.demonstration(self.xml_path,self.project_path,self.directory / "demo",self.report_path)
        self.assertEqual(len(result["changed_fields"]),2)
        self.assertEqual(result["external_editor_roundtrip"],"not_tested")
        self.assertTrue(all(result["demonstration"]["source_hashes_unchanged"].values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
