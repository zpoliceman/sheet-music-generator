"""字音归属修复：新增发音/音高不一致、同音换字、缓存身份与坐标反例。"""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import phoneme_evidence as phones
import word_note_alignment as align

# 字音归属修复：新增可独立知道挂词答案的发音时间夹具。
def character(index, start, end, nucleus_start=None):
    nucleus_start = start if nucleus_start is None else nucleus_start
    segments = []
    if nucleus_start > start:
        segments.append({'phoneme': 'zh/l', 'role': 'voiced_initial', 'start_seconds': start, 'end_seconds': nucleus_start})
    segments.append({'phoneme': 'zh/a', 'role': 'nucleus', 'start_seconds': nucleus_start, 'end_seconds': end})
    return {'index': index, 'text': '春风'[index % 2], 'line_index': 0,
            'start_seconds': start, 'end_seconds': end, 'phonemes': segments}


def note(index, start, end, pitch=60, confidence=.9):
    return {'id': str(index), 'source_note_id': str(index), 'start_seconds': start,
            'end_seconds': end, 'pitch_midi': pitch, 'confidence': confidence}


class WordOwnershipTests(unittest.TestCase):
    # 字音归属修复：新增长声母跨字反例，前字尾音不能因后字声母已开始就被抢走。
    def test_previous_nucleus_outweighs_next_consonant(self):
        chars = [character(0, 0, .38), character(1, .38, .9, .54)]
        notes = [note(0, 0, .22), note(1, .22, .50, 62), note(2, .50, .9, 64)]
        pieces, _, _ = align.align_notes(notes, {'characters': chars})
        self.assertEqual([p['lyric_index'] for p in pieces], [0, 0, 1])
        self.assertEqual([p['pitch_midi'] for p in pieces], [60, 62, 64])

    # 字音归属修复：新增一个字多次变音，不能把音高转折都当作换字。
    def test_melisma_keeps_all_four_notes_on_one_character(self):
        chars = [character(0, 0, .8, .08), character(1, .8, 1.2, .90)]
        notes = [note(i, i*.2, (i+1)*.2, pitch) for i, pitch in enumerate([62, 64, 62, 60])]
        notes.append(note(4, .8, 1.2, 67))
        out, _, _ = align.align_notes(notes, {'characters': chars})
        self.assertEqual([p['lyric_index'] for p in out], [0, 0, 0, 0, 1])

    # 字音归属修复：新增相同音高不同歌词，必须按真实核音范围重分而不新增音高。
    def test_same_pitch_syllables_split_without_new_pitch(self):
        chars = [character(0, 0, .18), character(1, .18, .36)]
        out, _, _ = align.align_notes([note(0, 0, .36)], {'characters': chars})
        self.assertEqual([p['lyric_index'] for p in out], [0, 1])
        self.assertEqual([p['pitch_midi'] for p in out], [60, 60])
        self.assertEqual([(p['start_seconds'], p['end_seconds']) for p in out], [(0, .18), (.18, .36)])

    # 字音归属修复：新增声学置信度变化不应转移字音归属，避免混用角色分数。
    def test_confidence_does_not_change_word_ownership(self):
        chars = [character(0, 0, .6), character(1, .6, 1)]
        notes = [note(0, 0, .2), note(1, .2, .6, 62), note(2, .6, 1, 64)]
        for values in [(1, .1, .8), (.1, 1, .1)]:
            adjusted = [dict(n, confidence=v) for n, v in zip(notes, values)]
            out, _, _ = align.align_notes(adjusted, {'characters': chars})
            self.assertEqual([p['lyric_index'] for p in out], [0, 0, 1])

    # 字音归属修复：新增原字界轻微扰动，已有音素证据不能被粗粒度字界覆盖。
    def test_coarse_character_boundary_shift_keeps_phoneme_result(self):
        chars = [character(0, 0, .5), character(1, .5, 1)]
        for delta in [-.08, .08]:
            changed = copy.deepcopy(chars)
            for c in changed:
                c['start_seconds'] += delta; c['end_seconds'] += delta
            out, _, _ = align.align_notes([note(0, 0, .5), note(1, .5, 1, 62)], {'characters': changed})
            self.assertEqual([p['lyric_index'] for p in out], [0, 1])

    # 字音归属修复：新增整条时间轴平移和音高移调，挂词不能依赖绝对时间或调性。
    def test_global_time_and_pitch_translation_equivariance(self):
        chars = [character(0, 0, .5, .1), character(1, .5, 1, .6)]
        notes = [note(0, 0, .2), note(1, .2, .5, 62), note(2, .5, 1, 64)]
        for offset, shift in [(0, 0), (123.45, 7)]:
            cs, ns = copy.deepcopy(chars), copy.deepcopy(notes)
            for c in cs:
                c['start_seconds'] += offset; c['end_seconds'] += offset
                for p in c['phonemes']:
                    p['start_seconds'] += offset; p['end_seconds'] += offset
            for n in ns:
                n['start_seconds'] += offset; n['end_seconds'] += offset; n['pitch_midi'] += shift
            out, _, _ = align.align_notes(ns, {'characters': cs})
            self.assertEqual([p['lyric_index'] for p in out], [0, 0, 1])

    # 字音归属修复：新增两种全句路径相近的真实歧义，必须保留候选而不假报高准确率。
    def test_ambiguous_boundary_reports_global_alternative(self):
        chars = [character(0, 0, .5), character(1, .5, 1)]
        notes = [note(0, 0, .35), note(1, .35, .65, 62), note(2, .65, 1, 64)]
        out, _, issues = align.align_notes(notes, {'characters': chars})
        self.assertTrue(any(p['word_alignment']['requires_review'] for p in out))
        self.assertTrue(issues)
        self.assertTrue(any(x['alternatives'] for x in issues))

    # 字音归属修复：新增当前路径不含糊但80ms字界偏差会改变归属的反例。
    def test_phoneme_time_sensitivity_is_automatically_flagged(self):
        chars = [character(0, 0, .5), character(1, .5, 1)]
        notes = [note(0, 0, .35), note(1, .35, .55, 62), note(2, .55, 1, 64)]
        out, _, issues = align.align_notes(notes, {'characters': chars})
        middle = next(n for n in out if n['id']=='1')
        self.assertTrue(middle['word_alignment']['boundary_sensitive'])
        self.assertTrue(any(i['type']=='word_ownership_boundary_sensitive' for i in issues))

    # 字音归属修复：新增无声学输入或同字节不同时间偏移不能静默挂谱。
    def test_no_notes_and_mismatched_source_fail(self):
        with self.assertRaisesRegex(ValueError, '声学'):
            align.align_notes([], {'characters':[character(0,0,.5)]})
        with self.assertRaisesRegex(ValueError, '来源'):
            align.align_notes([note(0,0,.5)], {'characters':[character(0,0,.5)],'source':{'sha256':'a'}},
                              {'source':{'sha256':'b'}})

    # 字音归属修复：新增无音素后端需标记近似，不能伪称用到了发音证据。
    def test_missing_phonemes_is_explicit_fallback_and_inputs_immutable(self):
        chars = [character(0, 0, .5), character(1, .5, 1)]
        for c in chars: c.pop('phonemes')
        notes = [note(0, 0, .5), note(1, .5, 1, 62)]
        before = copy.deepcopy((notes, chars))
        out, _, issues = align.align_notes(notes, {'characters': chars})
        self.assertTrue(all(p['word_alignment']['method'].endswith('fallback') for p in out))
        self.assertEqual((notes, chars), before)
        self.assertEqual(len(issues), 2)

    # 字音归属修复：新增逆序音素与重叠音段拒绝，不能靠事后改索引掩盖坏数据。
    def test_invalid_phonemes_and_overlap_fail(self):
        chars = [character(0, 0, .5)]
        chars[0]['phonemes'].append({'role':'nucleus','start_seconds':.1,'end_seconds':.2})
        with self.assertRaisesRegex(ValueError, '音素'):
            align.align_notes([note(0, 0, .5)], {'characters': chars})
        with self.assertRaisesRegex(ValueError, '重叠'):
            align.align_notes([note(0, 0, .6), note(1, .5, 1)], {'characters':[character(0,0,1)]})


class PhonemeCacheTests(unittest.TestCase):
    # 字音归属修复：新增真实owner/裁剪坐标格式夹具，只测试来源传递，不把夹具当模型效果。
    def fixture(self, directory):
        folder = Path(directory)
        crop = folder / 'crop.wav'; crop.write_bytes(b'cache-identity-fixture')
        source = {'sha256': 'source-audio', 'offset_seconds': 0}
        local = {'path': str(crop), 'sha256': phones.sha256(crop), 'offset_seconds': 10}
        states = [{'word_owner':i+1, 'text':text, 'phoneme':'zh/a', 'start_seconds':i*.5, 'end_seconds':(i+1)*.5} for i,text in enumerate('的的')]
        raw = folder/'raw.json'
        raw.write_text(json.dumps({'source':local,'results':[{'texts':['的','的'],'phoneme_states':states}]}),encoding='utf-8')
        chars = [{'index':i,'text':'的','group_id':f'phrase_0_tifa_word_{i+1}','phrase_job_id':0,'start_seconds':10+i*.5,'end_seconds':10+(i+1)*.5} for i in range(2)]
        lyrics = {'source':source,'cache_key':{'text_sha256':'text-hash'},'characters':chars}
        report = {'source':source,'cache_key':{'text_sha256':'text-hash'},'phrase_reports':[{'job_id':0,'crop':local,'original_source':source,'raw_alignment':str(raw),'model_timestep_seconds':.01}]}
        return lyrics, report, raw, crop

    # 字音归属修复：新增重复汉字必须靠owner识别；裁剪偏移只加一次。
    def test_repeated_character_owner_and_crop_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            lyrics, report, _, _ = self.fixture(directory)
            before = copy.deepcopy((lyrics, report))
            enriched = phones.enrich(lyrics, report)
            self.assertEqual([c['phonemes'][0]['start_seconds'] for c in enriched['characters']], [10, 10.5])
            self.assertEqual(phones.enrich(enriched, report), enriched)
            self.assertEqual((lyrics, report), before)

    # 字音归属修复：新增来源/文本哈希不一致时拒绝，不能挪用另首歌的音素。
    def test_mismatched_source_and_text_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lyrics, report, _, _ = self.fixture(directory)
            for field in ['source', 'cache_key']:
                changed = copy.deepcopy(report)
                changed[field][next(iter(changed[field]))] = 'other'
                with self.assertRaises(ValueError): phones.enrich(lyrics, changed)

    # 字音归属修复：新增裁剪内容变更必须被发现。
    def test_modified_crop_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lyrics, report, _, crop = self.fixture(directory)
            crop.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '字节'): phones.enrich(lyrics, report)

    # 字音归属修复：新增音素的字符身份错误必须拒绝，不能用近似回退掩盖。
    def test_wrong_owner_text_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lyrics, report, raw, _ = self.fixture(directory)
            data = phones.read_json(raw); data['results'][0]['texts'][0] = '错'
            raw.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '身份'): phones.enrich(lyrics, report)

if __name__ == '__main__':
    unittest.main()
