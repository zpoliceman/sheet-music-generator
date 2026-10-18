"""歌词对齐与真实制谱：对关键音乐与时间语义做独立回归。"""
# 歌词对齐与真实制谱：新增标准库测试入口，临时产物限定到负责的scores目录。
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import score_export as score
from notation_smoke import inspect_xml

# 歌词对齐与真实制谱：新增小型已知答案材料，避免用真实歌曲不确定结果当测试真值。
def note(identity, start, end, pitch=60):
    return {"id": identity, "start_seconds": start, "end_seconds": end,
            "pitch_midi": pitch, "is_rest": False}

def char(index, text, start, end, method="tifa_texts_tier"):
    return {"index": index, "text": text, "start_seconds": start,
            "end_seconds": end, "method": method, "warnings": []}

def project_from(notes, chars=(), seconds=4):
    mapping = score.TempoMap([{"seconds": 0, "quarter": 0}, {"seconds": 0.5, "quarter": 1}])
    timing = {"score_start_quarter": 0, "meter": [4, 4]}
    pieces, characters, issues = score.match_lyrics(notes, {"characters": list(chars)})
    events, quantized, stats = score.quantize(pieces, mapping, timing, seconds, 4)
    lyric_mapping = score.attach_lyrics(events, characters)
    return {"title": "自拟测试", "inputs": {"notes_path": "synthetic-test"},
            "notation": {"key": score.key_definition("C:major"), "jianpu_reference_midi": 60},
            "timing": timing, "events": events, "quantized_notes": quantized,
            "statistics": stats, "tempo_events": score.tempo_events(mapping, timing, stats["total_ticks"]),
            "lyric_mapping": lyric_mapping, "alignment_issues": issues}

class ScoreExportTests(unittest.TestCase):
    # 歌词对齐与真实制谱：新增有速度变化的秒/拍往返与外推真值。
    def test_variable_tempo_and_extrapolation(self):
        mapping = score.TempoMap([{"seconds": 0, "quarter": 0},
                                  {"seconds": 0.5, "quarter": 1},
                                  {"seconds": 1.25, "quarter": 2}])
        self.assertAlmostEqual(mapping.seconds_to_quarters(0.875), 1.5)
        self.assertAlmostEqual(mapping.quarters_to_seconds(3), 2.0)
        self.assertAlmostEqual(mapping.tempo_at(1.5), 80)
        for seconds in [-1, 0, 0.3, 0.875, 1.25, 3]:
            self.assertAlmostEqual(mapping.quarters_to_seconds(mapping.seconds_to_quarters(seconds)), seconds)

    # 歌词对齐与真实制谱：新增拒绝倒序tempo map，防止无声时间轴损坏。
    def test_reject_nonmonotonic_tempo(self):
        with self.assertRaises(ValueError):
            score.TempoMap([{"seconds": 1, "quarter": 0}, {"seconds": 0, "quarter": 1}])

    # 歌词对齐与真实制谱：新增跨小节一个发声音的延音及每小节总时值核查。
    def test_cross_bar_tie_and_lyrics(self):
        project = project_from([note("long", 1.75, 2.375)], [char(0, "风", 1.75, 2.375)])
        xml = score.build_musicxml(project)
        result = inspect_xml(xml)
        self.assertTrue(result["valid"], result["errors"])
        sounded = [event for event in project["events"] if event["pitch_midi"] is not None]
        self.assertEqual([event["measure"] for event in sounded], [1, 2])
        self.assertEqual([event["duration_ticks"] for event in sounded], [240, 360])
        self.assertEqual(sounded[0]["ties"], ["start"])
        self.assertEqual(sounded[1]["ties"], ["stop"])
        self.assertEqual(sounded[0]["lyric"]["text"], "风")
        self.assertEqual(sounded[1]["lyric"]["extend"], "stop")
        self.assertTrue(score.validate_score(project, xml)["valid"])

    # 歌词对齐与真实制谱：新增真实字边界拆分同音必须保留来源且不连成延音。
    def test_two_characters_same_pitch_with_forced_boundaries(self):
        original = [note("one", 0, 1)]
        saved = copy.deepcopy(original)
        project = project_from(original, [char(0, "春", 0, 0.5), char(1, "风", 0.5, 1)])
        sounded = [event for event in project["events"] if event["pitch_midi"] is not None]
        self.assertEqual([event["lyric"]["text"] for event in sounded], ["春", "风"])
        self.assertTrue(all(event["ties"] == [] for event in sounded))
        self.assertEqual({event["source_note_id"] for event in project["quantized_notes"]}, {"one"})
        self.assertEqual(original, saved)
        self.assertEqual(project["alignment_issues"][0]["type"], "same_pitch_split_by_forced_character_boundary")

    # 歌词对齐与真实制谱：新增近似分字不可冒充强制对齐，不把不同字拼进一个音。
    def test_approximate_alignment_conflict_is_visible(self):
        project = project_from([note("one", 0, 1)],
                               [char(0, "春", 0, 0.5, "whisper_word_character_split"),
                                char(1, "风", 0.5, 1, "whisper_word_character_split")])
        self.assertEqual(len(project["quantized_notes"]), 1)
        self.assertEqual(project["lyric_mapping"]["mapped_characters"], 1)
        self.assertEqual(len(project["lyric_mapping"]["unmapped_character_indices"]), 1)
        self.assertTrue(project["alignment_issues"][0]["unresolved"])

    # 歌词对齐与真实制谱：新增未对齐/零时长字符不能强塞到乐谱的核查。
    def test_missing_and_zero_duration_characters(self):
        project = project_from([note("one", 0, 1)],
                               [char(0, "幻", None, None), char(1, "觉", 0.5, 0.5)])
        self.assertEqual(project["lyric_mapping"]["mapped_characters"], 0)
        self.assertEqual(project["lyric_mapping"]["unmapped_character_indices"], [0, 1])
        self.assertTrue(inspect_xml(score.build_musicxml(project))["valid"])

    # 歌词对齐与真实制谱：新增短音保留为待审倚音，既不丢弃也不凭空延长占拍。
    def test_collapsed_note_preserved_without_lyric(self):
        project = project_from([note("short", 1.03, 1.05)], [char(0, "啊", 1.03, 1.05)])
        self.assertEqual(project["statistics"]["grace_notes_from_collapsed_grid"], 1)
        grace = [event for event in project["events"] if event["grace"]]
        self.assertEqual(len(grace), 1)
        self.assertEqual(grace[0]["duration_ticks"], 0)
        self.assertEqual(project["lyric_mapping"]["mapped_characters"], 0)
        self.assertTrue(score.validate_score(project, score.build_musicxml(project))["valid"])

    # 歌词对齐与真实制谱：新增派生音符仍重叠时显式失败，拒绝假装单声部通过。
    def test_overlap_rejected(self):
        with self.assertRaises(ValueError):
            project_from([note("a", 0, 1), note("b", 0.9, 2)])

    # 歌词对齐与真实制谱：新增升降调简谱级数及八度可逆性核查。
    def test_jianpu_key_and_octave(self):
        key = score.key_definition("Ab:major")
        self.assertEqual(key["fifths"], -4)
        self.assertEqual(score.jianpu_pitch(68, key, 68), ("1", 0, ""))
        self.assertEqual(score.jianpu_pitch(80, key, 68), ("1", 1, ""))
        self.assertEqual(score.jianpu_pitch(67, key, 68), ("7", -1, ""))
        self.assertEqual(score.key_definition("F:minor")["jianpu_one"], "Ab")

    # 歌词对齐与真实制谱：新增小节第二拍变速必须影响声音，不能全部移到小节起点。
    def test_musicxml_mid_measure_tempo_affects_sound(self):
        project = project_from([note("long", 0, 2)])
        project["tempo_events"] = [{"tick": 0, "bpm": 120}, {"tick": 480, "bpm": 80}]
        xml = score.build_musicxml(project)
        offsets = xml.findall("part/measure/direction/offset")
        self.assertEqual(len(offsets), 1)
        self.assertEqual(offsets[0].text, "480")
        self.assertEqual(offsets[0].get("sound"), "yes")

    # 歌词对齐与真实制谱：新增 MIDI真实解析，验证延音不重复起音和中文XML可读。
    def test_midi_single_attack_for_cross_bar_tie(self):
        import mido
        project = project_from([note("long", 1.75, 2.375)], [char(0, "风", 1.75, 2.375)])
        directory = ROOT / "test_outputs" / "scores"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="score_test_", dir=directory) as temporary:
            temp = Path(temporary).resolve()
            self.assertTrue(temp.is_relative_to(directory.resolve()))
            midi_path = temp / "test.mid"
            score.write_midi(midi_path, project)
            midi = mido.MidiFile(midi_path)
            attacks = [message for message in midi if message.type == "note_on" and message.velocity]
            self.assertEqual(len(attacks), 1)
            self.assertEqual(attacks[0].note, 60)
            # 歌词对齐与真实制谱：新增结束休止也计入MIDI整体时长的独立期望。
            self.assertAlmostEqual(midi.length, 4.0)
            self.assertIn("风", __import__("xml.etree.ElementTree", fromlist=["tostring"]).tostring(score.build_musicxml(project), encoding="unicode"))

if __name__ == "__main__":
    unittest.main(verbosity=2)

