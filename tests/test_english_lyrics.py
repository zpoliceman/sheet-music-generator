"""中文版本冻结与英文融合验证：验证单词身份、真实音节、同音重发及中文路径不变的反例。"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from lyrics_tokens import text_units, tifa_pfml, lyric_match_key, asr_language_for_text
from lyrics_quality import check_multilingual_reference, check_mandarin_reference
from lyrics_align import reference_characters, reject_unreliable_candidates
from lyrics_align_phrases import match_lines
from english_lyrics import observed_english_syllables, align_multilingual_notes
from phoneme_evidence import character_phonemes, enrich
from musical_decode import classify, coalesce_same_character
from tonal_rhythm_prior import merge_same_word
from word_note_alignment import align_notes
from g2pflow import parse_pfml

# 中文版本冻结与英文融合验证：合成时间只用于算法反例，实曲验收另用真实TIFA输出。
def word(index=0, text='never'):
    states = [{'word_owner': 1, 'text': text, 'phoneme': 'en/' + p,
               'start_seconds': a, 'end_seconds': b}
              for p, a, b in [('n', 0, .06), ('eh', .06, .30), ('v', .30, .35), ('er', .35, .70)]]
    return {'index': index, 'text': text, 'unit_kind': 'english_word', 'language': 'en', 'line_index': 0,
            'start_seconds': 0., 'end_seconds': .70, 'phonemes': character_phonemes(states, 0)}


def note(index, a, b, pitch=60):
    return {'id': str(index), 'source_note_id': str(index), 'start_seconds': a, 'end_seconds': b,
            'pitch_midi': pitch, 'confidence': .90, 'performance_segments': []}


class EnglishLyricsTests(unittest.TestCase):
    def test_mixed_text_preserves_words_case_contractions_and_humming(self):
        units = text_units("我叫Bruce Lee，It's fly；You’ll Hu。")
        self.assertEqual([u['text'] for u in units], ['我', '叫', 'Bruce', 'Lee', "It's", 'fly', 'You’ll', 'Hu'])
        self.assertEqual([u['kind'] for u in units][-2:], ['english_word', 'vocalization'])

    def test_pfml_keeps_english_word_boundary_with_dictionary_pronunciation(self):
        plan = parse_pfml(tifa_pfml("我You’ll Hu"))
        english = next(p for p in plan.parts if getattr(p, 'language', None) == 'en')
        self.assertTrue(english.fixed)
        self.assertEqual(english.text, "You'll")

    def test_matching_changes_only_english_case_and_apostrophe_shape(self):
        self.assertEqual(lyric_match_key('Bruce'), 'bruce')
        self.assertEqual(lyric_match_key('You’ll'), "you'll")
        self.assertNotEqual(lyric_match_key('遇'), lyric_match_key('语'))
        self.assertNotEqual(lyric_match_key('Bruce'), lyric_match_key('Bruise'))

    def test_asr_uses_expected_language_for_pure_and_mixed_lyrics(self):
        self.assertEqual(asr_language_for_text('春风Hu'), 'zh')
        self.assertEqual(asr_language_for_text('We were all meant to fly'), 'en')
        self.assertEqual(asr_language_for_text('我是 Bruce Lee'), 'auto')

    def test_multilingual_preflight_retains_mandarin_backend_contract(self):
        ref = {'reference_kind': 'user_supplied', 'lines': ['我是 Bruce Lee']}
        self.assertFalse(check_mandarin_reference(ref)['valid_for_mandarin_tifa'])
        self.assertTrue(check_multilingual_reference(ref)['valid_for_multilingual_tifa'])
        self.assertFalse(check_multilingual_reference({**ref, 'lines': ['hello 123']})['valid_for_multilingual_tifa'])

    def test_invalid_asr_time_is_not_ignored_when_english_is_supported(self):
        ref = {'reference_kind': 'asr_unverified', 'lines': ['We can fly']}
        anchor = {'source': {'duration_seconds': 5.}, 'result': {'segments': [{'text': 'We can fly', 'start': 4., 'end': 3.}]}}
        self.assertFalse(check_multilingual_reference(ref, anchor)['valid_for_multilingual_tifa'])

    def test_english_anchor_matching_is_case_and_punctuation_insensitive(self):
        lines = ["There's a light inside", 'of all of us']
        segments = [{'text': 'THERE IS A LIGHT INSIDE OF ALL OF US', 'start': 2., 'end': 7.}]
        mapping, _, _ = match_lines(lines, segments)
        self.assertEqual(mapping[0]['segments'], [0])
        self.assertEqual(mapping[1]['segments'], [0])
        self.assertEqual(lines, ["There's a light inside", 'of all of us'])

    def test_english_consonants_are_not_vowel_nuclei(self):
        self.assertEqual([p['role'] for p in word()['phonemes']], ['voiced_initial', 'nucleus', 'voiced_initial', 'nucleus'])

    def test_diphthong_is_a_single_syllable(self):
        char = word(text='fly')
        char['phonemes'] = character_phonemes([{'phoneme': 'en/ay', 'start_seconds': 0., 'end_seconds': .7}], 0)
        self.assertEqual(len(observed_english_syllables(char)), 1)

    def test_two_syllables_come_from_actual_vowels_not_letters(self):
        syllables = observed_english_syllables(word())
        self.assertEqual(len(syllables), 2)
        self.assertEqual([s['nucleus_phoneme'] for s in syllables], ['en/eh', 'en/er'])
        self.assertIn(syllables[0]['end_seconds'], [.30, .35])
        self.assertTrue(all(not s['spelling_split_invented'] for s in syllables))

    def test_missing_vowels_cannot_invent_english_syllables(self):
        char = word();char['phonemes'] = char['phonemes'][:1]
        with self.assertRaises(ValueError):observed_english_syllables(char)
        char.update(warnings=[], method='tifa_texts_tier')
        result = reject_unreliable_candidates([char], {'reference_kind': 'user_supplied', 'lines': ['never']}, {})
        self.assertIsNone(result[0]['start_seconds'])

    def test_same_pitch_two_syllables_keep_two_main_attacks(self):
        out, chars, _ = align_multilingual_notes([note(0, 0., .70)], {'characters': [word(index=8)]})
        self.assertEqual([p['lyric_index'] for p in out], [8, 8])
        self.assertEqual([p['english_syllable_index'] for p in out], [0, 1])
        self.assertEqual([p['pitch_midi'] for p in out], [60, 60])
        self.assertEqual(len(coalesce_same_character(out)), 2)
        self.assertEqual(len(merge_same_word(out)), 2)
        class Mapping:
            def seconds_to_quarters(self, t):return t * 2
        classified, _ = classify(out, Mapping(), chars)
        self.assertTrue(all(p['role'] == 'main' and not p['grace'] for p in classified))

    def test_one_syllable_melisma_does_not_turn_into_multiple_syllables(self):
        char = word(text='fly');char['phonemes'] = character_phonemes([{'phoneme': 'en/ay', 'start_seconds': 0., 'end_seconds': .7}], 0)
        out, _, _ = align_multilingual_notes([note(0, 0., .35, 60), note(1, .35, .7, 62)], {'characters': [char]})
        self.assertEqual([p['english_syllable_index'] for p in out], [0, 0])
        self.assertEqual([p['lyric_index'] for p in out], [0, 0])

    def test_chinese_joint_alignment_is_exactly_unchanged(self):
        char = {'index': 4, 'text': '春', 'start_seconds': 0., 'end_seconds': .7,
                'phonemes': [{'phoneme': 'zh/un', 'role': 'nucleus', 'start_seconds': 0., 'end_seconds': .7}]}
        ns = [note(0, 0., .35), note(1, .35, .7, 62)]
        data = {'characters': [char]};before = copy.deepcopy(data)
        self.assertEqual(align_multilingual_notes(ns, data), align_notes(ns, data))
        self.assertEqual(data, before)

    def test_syllable_mapping_still_checks_acoustic_source_identity(self):
        with self.assertRaises(ValueError):
            align_multilingual_notes([note(0, 0., .7)], {'source': {'sha256': 'a'}, 'characters': [word()]}, {'source': {'sha256': 'b'}})

    def test_raw_phoneme_owner_is_normalized_without_loosening_word_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);crop = root / 'vocals.wav';crop.write_bytes(b'provenance-fixture')
            source = {'path': str(crop), 'sha256': hashlib.sha256(crop.read_bytes()).hexdigest(), 'offset_seconds': 0.}
            raw_file = root / 'raw.json'
            raw = {'source': source, 'results': [{'texts': ['bruce'], 'phoneme_states': [
                {'word_owner': 1, 'text': 'bruce', 'phoneme': 'en/uw', 'start_seconds': .1, 'end_seconds': .7}]}]}
            raw_file.write_text(json.dumps(raw), encoding='utf-8')
            chars = reference_characters({'lines': ['Bruce']})
            chars[0].update(group_id='tifa_word_1', phoneme_source={'word_owner': 1}, start_seconds=.1, end_seconds=.7)
            lyric = {'source': source, 'cache_key': {'text_sha256': 'same'}, 'characters': chars}
            report = {'source': source, 'cache_key': lyric['cache_key'], 'raw_alignment': str(raw_file)}
            self.assertEqual(enrich(lyric, report)['characters'][0]['text'], 'Bruce')
            wrong = copy.deepcopy(lyric);wrong['characters'][0]['text'] = 'Bruise'
            with self.assertRaises(ValueError):enrich(wrong, report)

# 中文版本冻结与英文融合验证：连续英文与中文断句不能互相污染，长窗合并严格有上限。
class EnglishWindowTests(unittest.TestCase):
    def job(self, index, start, end):
        return {'job_id': index, 'line_indices': [index], 'start_seconds': start, 'end_seconds': end,
                'status': 'candidate_window', 'warnings': [], 'matches': [], 'reference_text': 'placeholder'}

    def test_overlapping_english_windows_use_one_real_joint_crop(self):
        from english_lyrics import merge_english_phrase_windows
        plan = {'jobs': [self.job(0, 1., 5.), self.job(1, 4.6, 9.)]}
        original = copy.deepcopy(plan)
        merged = merge_english_phrase_windows(plan, {'lines': ['Spread your wings', 'across the universe']})
        self.assertEqual(len(merged['jobs']), 1)
        self.assertEqual(merged['jobs'][0]['reference_text'], 'Spread your wings\nacross the universe')
        self.assertEqual((merged['jobs'][0]['start_seconds'], merged['jobs'][0]['end_seconds']), (1., 9.))
        self.assertEqual(plan, original)

    def test_silent_gap_and_chinese_anchors_remain_separate(self):
        from english_lyrics import merge_english_phrase_windows
        for lines, next_start in [(['We can fly', 'We can shine'], 8.), (['听见冬天', '未来有人'], 4.6)]:
            plan = {'jobs': [self.job(0, 1., 5.), self.job(1, next_start, 12.)]}
            merged = merge_english_phrase_windows(plan, {'lines': lines})
            self.assertEqual(merged['jobs'], plan['jobs'])

    def test_joint_window_has_a_duration_bound(self):
        from english_lyrics import merge_english_phrase_windows
        plan = {'jobs': [self.job(0, 1., 15.), self.job(1, 14., 28.)]}
        self.assertEqual(len(merge_english_phrase_windows(plan, {'lines': ['We can fly', 'We can shine']})['jobs']), 2)

    def test_failed_or_unsupported_windows_are_never_invented_as_joint_audio(self):
        from english_lyrics import merge_english_phrase_windows
        plan = {'jobs': [self.job(0, 1., 5.), self.job(1, 4., 9.)]}
        plan['jobs'][1]['status'] = 'unassigned_no_voice'
        self.assertEqual(len(merge_english_phrase_windows(plan, {'lines': ['We can fly', 'We can shine']})['jobs']), 2)


# 中文版本冻结与英文融合验证：单词索引必须贯穿调性、缓存与排版模块。
class EnglishDownstreamTests(unittest.TestCase):
    def test_repeated_phrase_transposition_uses_word_indices(self):
        from vocal_tonality import repeated_phrase_shift
        texts = ['We were all meant to fly', 'Spread your wings across the universe'] * 2
        chars = reference_characters({'lines': texts})
        previous=[];current=[]
        for c in chars:
            target = previous if c['line_index'] < 2 else current
            pitch = 60 + (c['index'] % 6) + (0 if c['line_index'] < 2 else 2)
            target.append({'lyric_index': c['index'], 'pitch_midi': pitch, 'start_seconds': c['index'], 'end_seconds': c['index'] + .5, 'confidence': .9})
        result = repeated_phrase_shift(previous, current, chars, 2)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['paired_characters'], 12)

    def test_old_letter_cache_cannot_claim_whole_word_alignment(self):
        from phoneme_evidence import validate_reference_units
        ref={'lines': ['Bruce Lee']}
        new={'characters':reference_characters(ref)}
        validate_reference_units(new, ref)
        old={'characters':[{'index': i, 'text': c, 'unit_kind':'character'} for i,c in enumerate('BruceLee')]}
        with self.assertRaises(ValueError):validate_reference_units(old, ref)

    def test_english_spacing_fits_real_font_and_chinese_spacing_is_unchanged(self):
        from score_export import lyric_half_width
        from PIL import ImageFont
        font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 20)
        text='remember'
        self.assertGreaterEqual(lyric_half_width(text)*2, font.getlength(text) + 4)
        self.assertLess(lyric_half_width(text), len(text)*10)
        self.assertEqual(lyric_half_width('遇见'), 20)
        self.assertEqual(lyric_half_width('Hu'), 20)


# 中文版本冻结与英文融合验证：语种切换首词恢复需真实邻窗，并保留无法定位时的诚实降级。
class EnglishMissingWindowTests(unittest.TestCase):
    def fixture(self, middle='bruce lee', end=8.):
        lines=['永远是你', middle, 'bruce lee']
        jobs=[{'job_id':0,'line_indices':[0],'status':'candidate_window','start_seconds':1.,'end_seconds':6.,'matches':[],'warnings':[]},
              {'job_id':1,'line_indices':[1],'status':'unassigned_no_voiced_window','warnings':['no_reliable_audio_window']},
              {'job_id':2,'line_indices':[2],'status':'candidate_window','start_seconds':5.6,'end_seconds':end,'matches':[],'warnings':[]}]
        return {'jobs':jobs},{'lines':lines}

    def test_missing_english_at_language_switch_is_repredicted_jointly(self):
        from english_lyrics import recover_missing_english_windows
        plan,ref=self.fixture();original=copy.deepcopy(plan)
        result=recover_missing_english_windows(plan,ref)
        self.assertEqual(len(result['jobs']),1)
        self.assertEqual(result['jobs'][0]['line_indices'],[0,1,2])
        self.assertEqual(result['jobs'][0]['reference_text'],'永远是你\nbruce lee\nbruce lee')
        self.assertEqual((result['jobs'][0]['start_seconds'],result['jobs'][0]['end_seconds']),(1.,8.))
        self.assertEqual(plan,original)

    def test_chinese_gap_and_overlong_neighbor_windows_do_not_trigger_english_recovery(self):
        from english_lyrics import recover_missing_english_windows
        for middle,end in [('中文缺字',8.),('bruce lee',30.)]:
            plan,ref=self.fixture(middle,end)
            self.assertEqual(recover_missing_english_windows(plan,ref)['jobs'],plan['jobs'])

    def test_english_review_display_spaces_words_without_changing_units(self):
        from lyrics_tokens import readable_lyric_units
        chars=reference_characters({'lines':['我是Bruce Lee']});before=copy.deepcopy(chars)
        self.assertEqual(readable_lyric_units(chars),'我是 Bruce Lee')
        self.assertEqual(chars,before)
        self.assertEqual(readable_lyric_units(reference_characters({'lines':['我Hu你']})),'我Hu你')


# 中文版本冻结与英文融合验证：短元音警告只能增加审阅证据，不能替用户改动旋律或造词。
class EnglishBoundaryQualityTests(unittest.TestCase):
    def test_short_vowel_at_language_switch_retains_main_note_and_warns(self):
        chinese={'index':0,'text':'你','unit_kind':'character','line_index':0,'start_seconds':0.,'end_seconds':.5,
                 'phonemes':[{'phoneme':'zh/i','role':'nucleus','start_seconds':0.,'end_seconds':.5}]}
        english={'index':1,'text':'Bruce','unit_kind':'english_word','line_index':1,'start_seconds':.5,'end_seconds':.6,
                 'phonemes':[{'phoneme':'en/uw','role':'nucleus','start_seconds':.53,'end_seconds':.55}]}
        output, chars, issues=align_multilingual_notes([note(0,0.,.5),note(1,.5,.6,62)],{'characters':[chinese,english]})
        self.assertEqual([n['pitch_midi'] for n in output],[60,62])
        self.assertTrue(output[-1]['anchor'])
        self.assertTrue(any(i.get('measured_vowel_seconds',1.)<.055 for i in issues))
        self.assertEqual(chars[-1]['start_seconds'],.5)


# 中文版本冻结与英文融合验证：七次同句、六个ASR锚点时不得把缺失次数任意固定在首句。
class EnglishRepeatedOccurrenceTests(unittest.TestCase):
    def test_repeated_phrase_with_missing_middle_occurrence_uses_whole_audio_run(self):
        from english_lyrics import joint_repeated_english_windows
        lines=['永远是你']+['We can fly']*4
        jobs=[{'job_id':0,'line_indices':[0],'status':'candidate_window','start_seconds':1.,'end_seconds':8.,'warnings':[],'matches':[]},
              {'job_id':1,'line_indices':[1],'status':'unassigned_no_voiced_window','warnings':['asr_missing_line']}]
        for i,(a,b) in enumerate([(8.,9.),(11.,12.),(17.,18.)],2):
            jobs.append({'job_id':i,'line_indices':[i],'status':'candidate_window','start_seconds':a,'end_seconds':b,'warnings':[],'matches':[]})
        plan={'jobs':jobs};before=copy.deepcopy(plan)
        out=joint_repeated_english_windows(plan,{'lines':lines})
        self.assertEqual(len(out['jobs']),2)
        self.assertEqual(out['jobs'][1]['line_indices'],[1,2,3,4])
        self.assertEqual(out['jobs'][1]['reference_text'],'We can fly\nWe can fly\nWe can fly\nWe can fly')
        self.assertEqual((out['jobs'][1]['start_seconds'],out['jobs'][1]['end_seconds']),(8.,18.))
        self.assertEqual(plan,before)

    def test_different_lyrics_and_unanchored_runs_do_not_invent_repetition_windows(self):
        from english_lyrics import joint_repeated_english_windows
        jobs=[{'job_id':i,'line_indices':[i],'status':'candidate_window','start_seconds':i*3.,'end_seconds':i*3.+1.,'warnings':[],'matches':[]} for i in range(2)]
        plan={'jobs':jobs}
        self.assertEqual(joint_repeated_english_windows(plan,{'lines':['We can fly','We can shine']})['jobs'],jobs)
        no_anchor=copy.deepcopy(plan)
        for j in no_anchor['jobs']:j['status']='unassigned_no_voiced_window'
        self.assertEqual(joint_repeated_english_windows(no_anchor,{'lines':['We can fly']*2})['jobs'],no_anchor['jobs'])


if __name__ == '__main__':
    unittest.main()
