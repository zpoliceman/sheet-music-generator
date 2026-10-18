"""中文版本冻结与英文融合验证：共用 TIFA 前端与联合匹配，仅英语按实测元音拆分内部音节。"""
from __future__ import annotations
import copy
from pathlib import Path

# 中文版本冻结与英文融合验证：这些符号对应已缓存 TIFA 英语词表；双元音仍是一个音节核。
VERSION = 1
ENGLISH_VOWELS = frozenset('aa ae ah ao aw ax ay eh er ey ih iy ow oy uh uw'.split())
ENGLISH_VOICED_CONSONANTS = frozenset('b d dh dx g jh l m n ng r v w y z zh _r'.split())


def multilingual_g2p_config(model_dir: Path, languages):
    # 中文版本冻结与英文融合验证：中文配置保持原有顺序；需要英语时才加载字典及 LSTM 模型。
    zh = str(model_dir / 'dictionaries/ds-zh-pinyin-lite.txt')
    converters = [{'id': 'chinese-pinyin', 'kwargs': {'dict_path': zh}}]
    if 'en' in languages:
        english_dict = model_dir / 'dictionaries/ds_cmudict-07b.txt'
        assets = model_dir / 'assets/LstmG2p-Eng'
        for required in [english_dict, assets / 'encoder.onnx', assets / 'decoder.onnx']:
            if not required.is_file():
                raise FileNotFoundError(f'英语发音资源不存在：{required}')
        converters.append({'id': 'lstm', 'language': 'en', 'kwargs': {
            'dict_path': str(english_dict), 'model_path': str(assets), 'beam_size': 16}})
    converters.append({'id': 'dictionary', 'language': 'zh', 'kwargs': {'dict_path': zh}})
    return {'preprocessors': [{'id': 'filter-punctuation'}, {'id': 'strip-whitespace'}, {'id': 'lowercase'}],
            'converters': converters}


def observed_english_syllables(character):
    # 中文版本冻结与英文融合验证：音节来自真实元音时间，不用字母均分，也不把双元音拆成两拍。
    phones = [copy.deepcopy(p) for p in character.get('phonemes', [])
              if not p.get('skipped') and p['end_seconds'] > p['start_seconds']]
    nuclei = [(i, p) for i, p in enumerate(phones) if p.get('role') == 'nucleus'
              and p.get('phoneme', '').startswith('en/')]
    if not nuclei:
        raise ValueError(f"英文单词 {character['text']} 缺少真实元音证据，不能猜测音节。")
    cuts = [character['start_seconds']]
    for (left_index, left), (right_index, right) in zip(nuclei, nuclei[1:]):
        midpoint = (left['end_seconds'] + right['start_seconds']) / 2
        # 中文版本冻结与英文融合验证：选两个元音之间最近的实际音素边界，避免切开一个音素。
        candidates = {left['end_seconds'], right['start_seconds']}
        candidates.update(p['start_seconds'] for p in phones[left_index + 1:right_index + 1])
        cut = min(candidates, key=lambda t: (abs(t - midpoint), t))
        if not cuts[-1] < cut < character['end_seconds']:
            raise ValueError('英文元音或音节边界逆序。')
        cuts.append(cut)
    cuts.append(character['end_seconds'])
    result = []
    for index, ((_, nucleus), start, end) in enumerate(zip(nuclei, cuts, cuts[1:])):
        members = [p for p in phones if start - 1e-6 <= (p['start_seconds'] + p['end_seconds']) / 2 <= end + 1e-6]
        result.append({'index': index, 'start_seconds': start, 'end_seconds': end,
                       'nucleus_start_seconds': nucleus['start_seconds'], 'nucleus_end_seconds': nucleus['end_seconds'],
                       'nucleus_phoneme': nucleus['phoneme'], 'phonemes': members,
                       'boundary_source': 'actual_tifa_english_phonemes', 'spelling_split_invented': False})
    return result


def align_multilingual_notes(notes, lyrics, analysis=None):
    # 中文版本冻结与英文融合验证：纯中文直接调用冻结版联合算法；英语内部音节共用同一单调匹配。
    from word_note_alignment import align_notes
    canonical = copy.deepcopy(lyrics.get('characters', []))
    if not any(c.get('unit_kind') == 'english_word' for c in canonical):
        return align_notes(notes, lyrics, analysis)
    flat = []
    identities = {}
    for character in sorted(canonical, key=lambda c: c['index']):
        if character.get('unit_kind') == 'english_word':
            character['english_syllables'] = observed_english_syllables(character)
            parts = character['english_syllables']
        else:
            parts = [None]
        for syllable in parts:
            item = copy.deepcopy(character)
            item['index'] = len(flat)
            identities[item['index']] = (character['index'], syllable)
            if syllable is not None:
                item.update(start_seconds=syllable['start_seconds'], end_seconds=syllable['end_seconds'],
                            phonemes=syllable['phonemes'])
            flat.append(item)
    internal = {**lyrics, 'characters': flat}
    pieces, _, issues = align_notes(notes, internal, analysis)

    def restore_indices(record):
        # 中文版本冻结与英文融合验证：内部音节索引不能泄露为公开歌词字序，复核候选也需还原身份。
        if isinstance(record, list):
            return [restore_indices(r) for r in record]
        if not isinstance(record, dict):
            return record
        output = {k: restore_indices(v) for k, v in record.items()}
        if 'character_index' in output and output['character_index'] is not None:
            original, syllable = identities[output['character_index']]
            output['character_index'] = original
            if syllable is not None:
                output['english_syllable_index'] = syllable['index']
        return output

    for piece in pieces:
        if piece.get('lyric_index') is not None:
            original, syllable = identities[piece['lyric_index']]
            piece['lyric_index'] = original
            if syllable is not None:
                piece['english_syllable_index'] = syllable['index']
                piece['english_syllable_evidence'] = {k: v for k, v in syllable.items() if k != 'phonemes'}
        if 'word_alignment' in piece:
            piece['word_alignment'] = restore_indices(piece['word_alignment'])
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # return pieces, canonical, restore_indices(issues)
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    restored_issues = restore_indices(issues)
    ordered = sorted(canonical, key=lambda c: c['index'])
    for previous, character in zip(ordered, ordered[1:]):
        # 中文版本冻结与英文融合验证：语种切换首词的元音过短只提示复核，不删除主音或挪动模型时间。
        if (character.get('unit_kind') != 'english_word' or previous.get('unit_kind') == 'english_word'
            or character['index'] != previous['index'] + 1 or len(character['text']) < 3):
            continue
        vowel_seconds = sum(p['end_seconds'] - p['start_seconds'] for p in character.get('phonemes', [])
                            if p.get('role') == 'nucleus' and not p.get('skipped'))
        if vowel_seconds < .055:
            for piece in pieces:
                if piece.get('lyric_index') != character['index']:
                    continue
                piece.setdefault('word_alignment', {}).update(requires_review=True,
                    boundary_signal='short_english_nucleus_at_language_switch', measured_vowel_seconds=vowel_seconds)
                restored_issues.append({'type': 'word_ownership_uncertain', 'piece_id': piece['id'],
                    'character_index': character['index'], 'alternatives': [], 'phonemes_available': True,
                    'start_seconds': piece['start_seconds'], 'end_seconds': piece['end_seconds'],
                    'source_note_id': piece.get('source_note_id', piece['id']), 'requires_review': True,
                    'reason': '中文切到英文的首词元音边界偏短；需对照原声确认，当前没有删除音符或修改音素时间。',
                    'measured_vowel_seconds': vowel_seconds})
    return pieces, canonical, restored_issues

# 中文版本冻结与英文融合验证：英文连唱跨行不等于停顿，合并相交句窗后做一次真实联合预测。
def merge_english_phrase_windows(plan, reference, max_window_seconds=24.):
    from lyrics_tokens import languages_for_text
    result = copy.deepcopy(plan)
    jobs = []
    for job in result['jobs']:
        current_text = '\n'.join(reference['lines'][i] for i in job['line_indices'])
        current_english = languages_for_text(current_text) == ['en']
        previous = jobs[-1] if jobs else None
        previous_english = previous is not None and languages_for_text('\n'.join(reference['lines'][i] for i in previous['line_indices'])) == ['en']
        if (previous is not None and current_english and previous_english
            and job['status'] == previous['status'] == 'candidate_window'
            and job['start_seconds'] <= previous['end_seconds']
            and max(job['end_seconds'], previous['end_seconds']) - previous['start_seconds'] <= max_window_seconds):
            previous.setdefault('original_job_ids', [previous['job_id']]).extend(job.get('original_job_ids', [job['job_id']]))
            previous['line_indices'] = sorted(set(previous['line_indices'] + job['line_indices']))
            previous['end_seconds'] = max(previous['end_seconds'], job['end_seconds'])
            previous['reference_text'] = '\n'.join(reference['lines'][i] for i in previous['line_indices'])
            previous['matches'] = previous.get('matches', []) + job.get('matches', [])
            previous['warnings'] = list(dict.fromkeys(previous.get('warnings', []) + job.get('warnings', []) + ['english_continuous_phrase_joint_window']))
            previous['window_method'] = 'english_overlapping_anchored_windows_joint_tifa'
        else:
            jobs.append(job)
    result['jobs'] = jobs
    result['english_window_policy'] = {'max_window_seconds': max_window_seconds,
        'merged_jobs': sum(len(j.get('original_job_ids', [j['job_id']])) - 1 for j in jobs),
        'audio_times_manually_shifted': False, 'only_overlapping_english_windows': True}
    return result

# 中文版本冻结与英文融合验证：语种切换处ASR可把首个英文词吞进上一句，联合前后锚窗恢复而非补造时间。
def recover_missing_english_windows(plan, reference, max_window_seconds=24.):
    from lyrics_tokens import text_units
    result = copy.deepcopy(plan)
    jobs = result['jobs'];output = [];recovered = []
    index = 0
    while index < len(jobs):
        job = jobs[index]
        text = '\n'.join(reference['lines'][i] for i in job['line_indices'])
        is_missing_english = (job['status'].startswith('unassigned_')
                              and any(u['kind'] == 'english_word' for u in text_units(text)))
        if is_missing_english and output and index + 1 < len(jobs):
            previous, following = output[-1], jobs[index + 1]
            if (previous['status'] == following['status'] == 'candidate_window'
                and following['end_seconds'] - previous['start_seconds'] <= max_window_seconds):
                joined = copy.deepcopy(previous)
                joined['line_indices'] = sorted(set(previous['line_indices'] + job['line_indices'] + following['line_indices']))
                joined['reference_text'] = '\n'.join(reference['lines'][i] for i in joined['line_indices'])
                joined['end_seconds'] = max(previous['end_seconds'], following['end_seconds'])
                joined['matches'] = previous.get('matches', []) + following.get('matches', [])
                joined['original_job_ids'] = previous.get('original_job_ids', [previous['job_id']]) + [job['job_id']] + following.get('original_job_ids', [following['job_id']])
                joined['warnings'] = list(dict.fromkeys(previous.get('warnings', []) + job.get('warnings', []) + following.get('warnings', []) + ['missing_english_line_joint_boundary_window']))
                joined['window_method'] = 'missing_english_between_neighbor_anchors_joint_tifa'
                joined['missing_english_line_indices'] = list(job['line_indices'])
                recovered.append({'missing_line_indices': job['line_indices'], 'original_job_ids': joined['original_job_ids'],
                                  'start_seconds': joined['start_seconds'], 'end_seconds': joined['end_seconds']})
                output[-1] = joined;index += 2;continue
        output.append(job);index += 1
    result['jobs'] = output
    result['english_missing_window_recovery'] = {'joint_windows': recovered, 'max_window_seconds': max_window_seconds,
        'times_invented': False, 'acceptance_requires_real_tifa_phonemes': True}
    return result

# 中文版本冻结与英文融合验证：重复短句少识别一次时，逐行匹配无法确定遗漏位置；整组原文交给音频联合判断。
def joint_repeated_english_windows(plan, reference, max_window_seconds=48.):
    from lyrics_tokens import text_units, lyric_match_key
    result = copy.deepcopy(plan)
    jobs = result['jobs'];output = [];groups = [];index = 0

    def repetition_key(job):
        if job['status'] not in ('candidate_window', 'unassigned_no_voiced_window'):
            return None
        keys=[]
        for line in job['line_indices']:
            units=text_units(reference['lines'][line])
            if not units or any(u['kind'] != 'english_word' for u in units):
                return None
            keys.append(tuple(lyric_match_key(u['text']) for u in units))
        return keys[0] if keys and all(key == keys[0] for key in keys) else None

    while index < len(jobs):
        first=jobs[index];key=repetition_key(first);end=index+1
        while key is not None and end < len(jobs) and repetition_key(jobs[end]) == key:
            end+=1
        run=jobs[index:end]
        anchors=[j for j in run if j['status'] == 'candidate_window']
        lines=sorted({i for j in run for i in j['line_indices']})
        if len(lines)>=2 and len(anchors)>=2:
            start=min(j['start_seconds'] for j in anchors);stop=max(j['end_seconds'] for j in anchors)
            if stop-start<=max_window_seconds:
                joined=copy.deepcopy(anchors[0]);joined['job_id']=first['job_id']
                joined.update(line_indices=lines,reference_text='\n'.join(reference['lines'][i] for i in lines),
                    start_seconds=start,end_seconds=stop,original_job_ids=[j['job_id'] for j in run],
                    matches=[m for j in run for m in j.get('matches', [])],
                    warnings=list(dict.fromkeys([w for j in run for w in j.get('warnings', [])]+['repeated_english_occurrences_joint_tifa'])),
                    window_method='repeated_english_run_joint_tifa')
                output.append(joined)
                groups.append({'line_indices':lines,'original_job_ids':joined['original_job_ids'],'start_seconds':start,
                    'end_seconds':stop,'reference_occurrences':len(lines),'individually_anchored_jobs':len(anchors)})
                index=end;continue
        output.append(first);index+=1
    result['jobs']=output
    result['english_repeated_window_policy']={'groups':groups,'max_window_seconds':max_window_seconds,
        'occurrence_times_uniformly_divided':False,'missing_occurrence_position_guessed':False}
    return result
