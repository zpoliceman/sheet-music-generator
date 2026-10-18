"""简谱按拍分组优化：使用已知节奏验证分拍、各层减时线及音乐数据保持。"""
# 简谱按拍分组优化：新增独立已知答案测试，避免拿真实歌曲的未确认音乐判断作测试真值。
import copy
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import score_export as score


def event(identity, tick, duration, kind="eighth", dots=0, grace=False, pitch=60, measure=1, text=None):
    return {"id": identity, "measure": measure, "offset_ticks": tick,
            "start_tick": (measure - 1) * 1920 + tick, "duration_ticks": duration,
            "type": kind, "dots": dots, "grace": grace, "pitch_midi": pitch,
            "piece_id": identity, "ties": [], "lyric_index": None,
            "lyric": {"text": text, "character_index": 0} if text else None}


def project(events, meter=(4, 4)):
    return {"title": "自拟节奏", "events": events, "timing": {"meter": list(meter)},
            "notation": {"key": score.key_definition("C:major"), "jianpu_reference_midi": 60},
            "statistics": {"measure_count": max(e["measure"] for e in events)},
            "audio_analysis": {"tempo": {"bpm": 120}}, "overrides": {"tempo": None},
            "lyric_mapping": {"mapped_characters": 0, "character_count": 0}}


class JianpuBeatLayoutTests(unittest.TestCase):
    # 简谱按拍分组优化：新增两八分的共同减时线及四分拍边界真值。
    def test_eighth_pairs_join_within_each_beat(self):
        events = [event(str(i), i * 240, 240) for i in range(8)]
        scene = score.render_jianpu(project(events))
        beams = scene.measure_boxes[1]["beams"]
        self.assertEqual([beam["event_ids"] for beam in beams],
                         [["0", "1"], ["2", "3"], ["4", "5"], ["6", "7"]])
        self.assertEqual([beam["beat"] for beam in beams], [1, 2, 3, 4])
        positions = {item["id"]: item["x"] for item in scene.measure_boxes[1]["events"]}
        for beam in beams:
            self.assertLess(beam["x1"], positions[beam["event_ids"][0]])
            self.assertGreater(beam["x2"], positions[beam["event_ids"][-1]])
            self.assertIn(("line", beam["x1"], beam["y"], beam["x2"], beam["y"], "#14243b", 1.4), scene.items)

    # 简谱按拍分组优化：新增十六分/三十二分/八分混合时各层长度不能串错的真值。
    def test_mixed_subdivisions_have_separate_beam_levels(self):
        events = [event("a", 0, 120, "16th"), event("b", 120, 60, "32nd"),
                  event("c", 180, 60, "32nd"), event("d", 240, 240)]
        beams = score.render_jianpu(project(events)).measure_boxes[1]["beams"]
        self.assertEqual([(beam["level"], beam["event_ids"]) for beam in beams],
                         [(1, ["a", "b", "c", "d"]), (2, ["a", "b", "c"]), (3, ["b", "c"])])
        self.assertLess(beams[0]["y"], beams[1]["y"])
        self.assertLess(beams[1]["y"], beams[2]["y"])

    # 简谱按拍分组优化：新增附点八分加十六分保持独立第二层，不能暗示两个八分的真值。
    def test_dotted_eighth_and_sixteenth(self):
        events = [event("a", 0, 360, dots=1), event("b", 360, 120, "16th")]
        beams = score.render_jianpu(project(events)).measure_boxes[1]["beams"]
        self.assertEqual([(beam["level"], beam["event_ids"]) for beam in beams],
                         [(1, ["a", "b"]), (2, ["b"])])
        self.assertEqual(beams[1]["x2"] - beams[1]["x1"], 18)

    # 简谱按拍分组优化：新增短休止参与拍内线条，长休止/空档不能被短音连线越过。
    def test_short_rest_is_rhythmic_but_gaps_and_quarters_break_beams(self):
        events = [event("rest", 0, 240, pitch=None), event("a", 240, 240),
                  event("quarter", 480, 480, "quarter"), event("b", 960, 120, "16th"),
                  event("c", 1200, 240)]
        beams = score.render_jianpu(project(events)).measure_boxes[1]["beams"]
        self.assertEqual([beam["event_ids"] for beam in beams if beam["level"] == 1],
                         [["rest", "a"], ["b"], ["c"]])

    # 简谱按拍分组优化：新增切分音的起拍分组与跨拍断线，不能为排版重写时值。
    def test_syncopation_breaks_at_next_beat_onset(self):
        events = [event("a", 0, 240), event("b", 240, 360, dots=1),
                  event("c", 600, 120, "16th"), event("d", 720, 240)]
        original = copy.deepcopy(events)
        beams = score.render_jianpu(project(events)).measure_boxes[1]["beams"]
        self.assertEqual([beam["event_ids"] for beam in beams if beam["level"] == 1],
                         [["a", "b"], ["c", "d"]])
        self.assertEqual(events, original)

    # 简谱按拍分组优化：新增零时值倚音只能自成小号线，不能参与普通音的占拍分组。
    def test_graces_are_separate_from_metered_beams(self):
        events = [event("a", 0, 240), event("g1", 240, 0, grace=True),
                  event("g2", 240, 0, grace=True), event("b", 240, 240)]
        beams = score.render_jianpu(project(events)).measure_boxes[1]["beams"]
        self.assertEqual([(beam["grace"], beam["event_ids"]) for beam in beams],
                         [(False, ["a", "b"]), (True, ["g1", "g2"])])
        self.assertLess(beams[1]["y"], beams[0]["y"])

    # 简谱按拍分组优化：新增完整长音的四分拍延长线定位，不改变长音身份及字音数据。
    def test_whole_note_dash_positions_and_input_preserved(self):
        data = project([event("whole", 0, 1920, "whole", text="风")])
        original = copy.deepcopy(data)
        scene = score.render_jianpu(data)
        beats = scene.measure_boxes[1]["beats"]
        self.assertEqual([[glyph["tick"] for glyph in beat["glyphs"]] for beat in beats],
                         [[0], [480], [960], [1440]])
        self.assertEqual([item[3] for item in scene.items if item[0] == "text" and item[3] == "–"], ["–"] * 3)
        self.assertEqual(data, original)

    # 简谱按拍分组优化：新增拍间距离比拍内明显更大的可读性要求，并核查密集字形不重叠。
    def test_spacing_is_compact_inside_beats_and_dense_glyphs_fit(self):
        scene = score.render_jianpu(project([event(str(i), i * 240, 240) for i in range(8)]))
        xs = [item["x"] for item in scene.measure_boxes[1]["events"]]
        self.assertGreaterEqual(xs[2] - xs[1], xs[1] - xs[0] + 20)
        dense = [event(str(i), i * 60, 60, "32nd", pitch=61, text="Hu" if i == 0 else None) for i in range(32)]
        scene = score.render_jianpu(project(dense))
        box = scene.measure_boxes[1]
        for beat in box["beats"]:
            glyphs = beat["glyphs"]
            self.assertGreaterEqual(glyphs[0]["left"], box["x"] + 18)
            self.assertLessEqual(glyphs[-1]["right"], box["x"] + box["width"] - 18)
            for before, after in zip(glyphs, glyphs[1:]):
                self.assertGreaterEqual(after["left"] - before["right"], 8)
        for before, after in zip(box["beats"], box["beats"][1:]):
            self.assertGreaterEqual(after["glyphs"][0]["left"] - before["glyphs"][-1]["right"], 28)

    # 简谱按拍分组优化：新增八度下点与共同减时线不相交的要求。
    def test_low_octave_dots_clear_the_shared_underlines(self):
        scene = score.render_jianpu(project([event("low", 0, 240, pitch=36), event("next", 240, 240)]))
        beam = scene.measure_boxes[1]["beams"][0]
        dots = [item for item in scene.items if item[0] == "dot"]
        self.assertTrue(dots)
        self.assertGreater(beam["y"], max(dot[2] + dot[3] for dot in dots))

    # 简谱按拍分组优化：新增其他拍号及节选必须共用全曲密度，规则不得硬编码两首歌。
    def test_other_meters_and_excerpt_share_the_layout(self):
        scene = score.render_jianpu(project([event(str(i), i * 240, 240) for i in range(6)], (6, 8)))
        self.assertEqual([beam["event_ids"] for beam in scene.measure_boxes[1]["beams"]],
                         [["0", "1", "2"], ["3", "4", "5"]])
        scene = score.render_jianpu(project([event(str(i), i * 240, 240) for i in range(6)], (3, 4)))
        self.assertEqual(len(scene.measure_boxes[1]["beats"]), 3)
        events = [event("whole", 0, 1920, "whole"),
                  *[event(str(i), i * 60, 60, "32nd", measure=2) for i in range(32)]]
        data = project(events); original = copy.deepcopy(data)
        full = score.render_jianpu(data)
        excerpt = score.render_jianpu(data, 1, 1, True)
        self.assertEqual(full.layout, excerpt.layout)
        self.assertEqual(full.measure_boxes[1], excerpt.measure_boxes[1])
        self.assertEqual(data, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
