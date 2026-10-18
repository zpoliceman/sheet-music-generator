# 歌词对齐与真实制谱：新增以同源ASR句窗为候选、真实逐句TIFA预测的独立质量对照。
from __future__ import annotations

import argparse
import gc
import hashlib
from functools import lru_cache  # 歌词对齐与真实制谱：新增已有G2P引擎及短文本拼音缓存。
import json
import math
import re  # 中文版本冻结与英文融合验证：新增中英文分段匹配所需正则。
from pathlib import Path
from workspace_location import local_path
import time
import traceback
import unicodedata

from lyrics_transcribe import ROOT, file_sha256, read_json, save_json
from lyrics_align import reference_characters, reject_unreliable_candidates, tifa_align
# 第二首跨歌曲验证：新增普通话对齐前文本/时间异常检查。
# 中文版本冻结与英文融合验证：注释保留被替换的原实现。
# from lyrics_quality import check_mandarin_reference
# 中文版本冻结与英文融合验证：新增中英文兼容实现。
from lyrics_quality import check_multilingual_reference
# 连续转调识别与不确定调性保护：新增混合语言逐窗范围隔离。
from lyrics_partial_support import unsupported_lines, supported_plan, mark_unsupported_characters
# 第二首跨歌曲验证：新增哼唱边界保护，未识别哼唱不能被后一句吞窗。
from lyrics_tokens import text_units


# 歌词对齐与真实制谱：新增字符及拼音编辑距离；只选择录音窗口，不改用户权威文本。
def normalize(text):
    # 第二首跨歌曲验证：修改，原只去标点保留；简繁体仅在匹配副本中统一，用户原文和谱面不改。
    # return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith(('P', 'S')))
    literal = ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith(('P', 'S')))
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # return ''.join(pinyin_converter()._engine.simplify(list(literal)))
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    return ''.join(pinyin_converter()._engine.simplify(list(literal))).casefold()


def edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, row[j] + 1, row[j-1] + (ca != cb)))
        row = current
    return row[-1]


# 歌词对齐与真实制谱：修改；保留原可选库方案，复用已安装的官方G2P中文引擎，避免新依赖。
# def text_cost(a, b):
#     from pypinyin import lazy_pinyin
@lru_cache(maxsize=1)
def pinyin_converter():
    from g2pflow.converters.chinese import PinyinConverter
    return PinyinConverter(str(ROOT/'.cache/tifa/model/TIFA-1.0-ST/dictionaries/ds-zh-pinyin-lite.txt'))


# 歌词对齐与真实制谱：新增拼音序列缓存，仅用于句文本匹配。
# 中文版本冻结与英文融合验证：注释保留被替换的原实现。
# @lru_cache(maxsize=512)
# def pinyin_tokens(text):
    # return tuple(v[0] for v in pinyin_converter().text_to_scripts(list(text)))
# 中文版本冻结与英文融合验证：新增中英文兼容实现。
@lru_cache(maxsize=512)
def pinyin_tokens(text):
    # 中文版本冻结与英文融合验证：英文不能送入汉语拼音转换器；中文同音匹配仍保留。
    output = []
    for part in re.findall(r'[\u3400-\u9fff]+|.', text, flags=re.S):
        if all('\u3400' <= c <= '\u9fff' for c in part):
            output.extend(v[0] for v in pinyin_converter().text_to_scripts(list(part)))
        else:
            output.append('literal:' + part.casefold())
    return tuple(output)


def text_cost(a, b):
    a, b = normalize(a), normalize(b)
    char_cost = edit_distance(a, b) / max(len(a), len(b), 1)
    # 歌词对齐与真实制谱：修改；原外部拼音调用保留，改用同模型G2P引擎。
    # pa, pb = lazy_pinyin(a), lazy_pinyin(b)
    pa, pb = pinyin_tokens(a), pinyin_tokens(b)
    phone_cost = edit_distance(pa, pb) / max(len(pa), len(pb), 1)
    return {'character_edit_ratio': char_cost, 'pinyin_edit_ratio': phone_cost,
            'weighted_edit_ratio': .5 * char_cost + .5 * phone_cost}


# 歌词对齐与真实制谱：新增单调全局句序列匹配，可跳过识别幻觉或用户漏识别句。
# 第二首跨歌曲验证：新增合并窗口的首尾行拼音覆盖；中间识别错字不能把边缘整句吞掉。
@lru_cache(maxsize=4096)
def boundary_line_support(lines, asr_text):
    reference = pinyin_tokens(normalize(''.join(lines)))
    observed = pinyin_tokens(normalize(asr_text))
    table = [[0]*(len(observed)+1) for _ in range(len(reference)+1)]
    for i,a in enumerate(reference,1):
        for j,b in enumerate(observed,1):
            table[i][j] = table[i-1][j-1]+1 if a==b else max(table[i-1][j],table[i][j-1])
    matches = set(); i,j=len(reference),len(observed)
    while i and j:
        if reference[i-1]==observed[j-1]:
            matches.add(i-1);i-=1;j-=1
        elif table[i-1][j]>=table[i][j-1]:i-=1
        else:j-=1
    first = len(pinyin_tokens(normalize(lines[0])))
    last = len(pinyin_tokens(normalize(lines[-1])))
    return (sum(i<first for i in matches)/max(1,first),
            sum(i>=len(reference)-last for i in matches)/max(1,last))


def match_lines(lines, segments):
    n, m = len(lines), len(segments)
    costs = [[float('inf')] * (m + 1) for _ in range(n + 1)]
    prev = {}
    costs[0][0] = 0.
    def relax(i, j, value, parent, action):
        if value < costs[i][j]:
            costs[i][j] = value
            prev[i, j] = (parent, action)
    for i in range(n + 1):
        for j in range(m + 1):
            base = costs[i][j]
            if i < n:
                relax(i+1, j, base + .75, (i, j), {'kind': 'missing_line', 'line': i})
            if j < m:
                relax(i, j+1, base + .55, (i, j), {'kind': 'skipped_asr', 'segment': j})
    # 第二首跨歌曲验证：修改，原一行匹配多识别段逻辑注释保留。
    # if i < n:
    # for count in range(1, min(3, m-j)+1):
    # # 歌词对齐与真实制谱：新增长静音间隔禁止合并，防止漏识别主歌被前句吞窗。
    # if any(segments[q+1]['start']-segments[q]['end'] > 2. for q in range(j, j+count-1)):
    # continue
    # text = ''.join(s['text'] for s in segments[j:j+count])
    # evidence = text_cost(lines[i], text)
    # # 歌词对齐与真实制谱：修改；原合并代价保留，加大重复识别片段合并惩罚。
    # # penalty = evidence['weighted_edit_ratio'] + .10*(count-1)
    # penalty = evidence['weighted_edit_ratio'] + .30*(count-1)
    # # 歌词对齐与真实制谱：修改；多段合并仅准许充分文本支持，原宽门限保留。
    # # if evidence['weighted_edit_ratio'] <= .62:
    # if evidence['weighted_edit_ratio'] <= (.62 if count == 1 else .35):
    # relax(i+1, j+count, base + penalty, (i, j),
    # {'kind': 'match', 'line': i, 'segments': list(range(j, j+count)),
    # 'asr_text': text, **evidence})
            if i < n:
                # 第二首跨歌曲验证：新增1至4歌词行对应1至3ASR段；换行本身不能产生缺词。
                for line_count in range(1, min(4, n-i)+1):
                    reference_text = ''.join(lines[i:i+line_count])
                    # 第二首跨歌曲验证：新增哼唱作为独立窗口边界；避免用长后句稀释漏识别短哼唱的编辑代价。
                    if line_count > 1 and any(unit['kind']=='vocalization' for unit in text_units(reference_text)):
                        continue
                    for count in range(1, min(3, m-j)+1):
                        if any(segments[q+1]['start']-segments[q]['end'] > 2. for q in range(j,j+count-1)):
                            continue
                        text = ''.join(s['text'] for s in segments[j:j+count])
                        evidence = text_cost(reference_text, text)
                        penalty = evidence['weighted_edit_ratio'] + .30*(count-1) + .10*(line_count-1)
                        # 第二首跨歌曲验证：修改，原宽合并门限注释保留，任何合并都需充分文本支持。
                        # if evidence['weighted_edit_ratio'] <= (.62 if count == 1 else .35):
                        if evidence['weighted_edit_ratio'] <= (.62 if count == 1 and line_count == 1 else .35):
                            # 第二首跨歌曲验证：新增首尾行至少60%拼音支持；避免把抚平了等短整句塞到下一句窗口。
                            if line_count > 1 and min(boundary_line_support(tuple(lines[i:i+line_count]), text)) < .60:
                                continue
                            relax(i+line_count, j+count, base+penalty, (i,j),
                                  {'kind':'match','line':i,'lines':list(range(i,i+line_count)),
                                   'segments':list(range(j,j+count)),'asr_text':text,**evidence})
    actions = []
    state = (n, m)
    while state != (0, 0):
        state, action = prev[state]
        actions.append(action)
    actions.reverse()
    # 第二首跨歌曲验证：修改，原单行字典注释保留，新映射覆盖同窗各歌词行。
    # mapping = {a['line']: a for a in actions if a['kind'] != 'skipped_asr'}
    mapping = {}
    for action in actions:
        if action['kind'] == 'match':
            for index in action.get('lines', [action['line']]):
                mapping[index] = action
        elif action['kind'] == 'missing_line':
            mapping[action['line']] = action
    return mapping, actions, costs[n][m]


# 歌词对齐与真实制谱：新增音符有声范围证据；缺锚连续句合并真实预测，不均分时间。
# 第三首《我不难过》跨歌曲验证：新增ASR跨歌词行边界检测，只在相邻语音窗有明确尾句/首句证据时合并。
def merge_shared_boundaries(jobs, reference, anchor, notes):
    merged = []
    for job in jobs:
        previous = merged[-1] if merged else None
        evidence = None
        if previous and previous['status'] == job['status'] == 'candidate_window':
            lines = previous['line_indices'] + job['line_indices']
            eligible = (max(previous['line_indices']) + 1 == min(job['line_indices'])
                        and len(lines) <= 4 and job['start_seconds'] <= previous['end_seconds'] + 1.
                        and job['end_seconds'] - previous['start_seconds'] <= 24.)
            # 第三首《我不难过》跨歌曲验证：新增哼唱行隔离，Hu等独立声乐行不得被自动合并吞掉。
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # eligible &= all(all(unit['kind'] == 'character' for unit in text_units(reference['lines'][i]))
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            eligible &= all(all(unit['kind'] in ('character', 'english_word') for unit in text_units(reference['lines'][i]))
                            for i in lines)
            segment_indices = sorted({i for match in job['matches'] for i in match.get('segments', [])})
            if eligible and segment_indices:
                observed = normalize(anchor['segments'][segment_indices[0]]['text'])
                tail = normalize(reference['lines'][previous['line_indices'][-1]])
                head = normalize(reference['lines'][job['line_indices'][0]])
                head_size = min(4, len(head))
                # 第三首《我不难过》跨歌曲验证：新增首句已经在段头时不合并，避免相同短句/重复段误吞。
                if head_size >= 3 and text_cost(head[:head_size], observed[:head_size])['weighted_edit_ratio'] > .25:
                    for size in range(min(8, len(tail), len(observed) - head_size), 2, -1):
                        tail_cost = text_cost(tail[-size:], observed[:size])['weighted_edit_ratio']
                        head_cost = text_cost(head[:head_size], observed[size:size + head_size])['weighted_edit_ratio']
                        if tail_cost <= .25 and head_cost <= .25:
                            evidence = {'tail_units': size, 'tail_edit_ratio': tail_cost,
                                        'next_head_edit_ratio': head_cost, 'asr_segment_index': segment_indices[0],
                                        'reference_tail': tail[-size:], 'observed_prefix': observed[:size]}
                            break
        if evidence:
            original_ids = previous.get('merged_job_ids', [previous['job_id']]) + [job['job_id']]
            previous.update(line_indices=lines,
                reference_text='\n'.join(reference['lines'][i] for i in lines),
                start_seconds=min(previous['start_seconds'], job['start_seconds']),
                end_seconds=max(previous['end_seconds'], job['end_seconds']),
                matches=previous['matches'] + job['matches'],
                warnings=list(dict.fromkeys(previous['warnings'] + job['warnings'] + ['asr_cross_line_boundary_merged'])),
                window_method='asr_shared_boundary_joint_tifa', merged_job_ids=original_ids)
            previous.setdefault('shared_boundary_evidence', []).append(evidence)
            relevant = [n for n in notes if n['end_seconds'] > previous['start_seconds'] and n['start_seconds'] < previous['end_seconds']]
            previous['melody_evidence'] = {
                'first_pitched_onset_seconds': min((n['start_seconds'] for n in relevant), default=None),
                'last_pitched_end_seconds': max((n['end_seconds'] for n in relevant), default=None),
                'pitched_note_count': len(relevant),
                'pitched_duration_seconds': sum(max(0., min(n['end_seconds'], previous['end_seconds']) - max(n['start_seconds'], previous['start_seconds'])) for n in relevant)}
        else:
            # 第三首《我不难过》跨歌曲验证：新增深拷贝避免改变原候选窗和缓存诊断。
            import copy
            merged.append(copy.deepcopy(job))
    for identity, job in enumerate(merged):
        job['job_id'] = identity
    return merged


def plan_jobs(reference, anchor, analysis, padding):
    segments = anchor['result']['segments']
    mapping, actions, cost = match_lines(reference['lines'], segments)
    notes = [n for n in analysis['notes'] if not n.get('is_rest', False)
             and n.get('quality', {}).get('voiced_fraction', 0.) >= .3]
    duration = reference['source']['duration_seconds']
    groups = []
    i = 0
    # 第二首跨歌曲验证：修改，原仅追加一个弱锚的分组保留；连续弱匹配/缺锚共同真实预测。
    #     while i < len(reference['lines']):
    #         if mapping[i]['kind'] == 'match':
    #             # 第二首跨歌曲验证：修改，原一行一个窗口保留，合并同一真实识别段的分行。
    #             # group = [i]
    #             # i += 1
    #             group = mapping[i].get('lines', [i])
    #             i = group[-1] + 1
    #         else:
    #             group = [i]
    #             i += 1
    #             while i < len(reference['lines']) and mapping[i]['kind'] != 'match':
    #                 # 第二首跨歌曲验证：修改，原只追加一个弱锚行保留，整组弱锚一起追加。
    #                 # group.append(i)
    #                 # i += 1
    #                 next_group = mapping[i].get('lines', [i])
    #                 group.extend(next_group)
    #                 i = next_group[-1] + 1
    #             # 歌词对齐与真实制谱：新增缺锚后弱匹配并入同一真实窗口，避免截掉该句开头音节。
    #             if i < len(reference['lines']) and mapping[i].get('weighted_edit_ratio', 0) > .30:
    #                 # 第二首跨歌曲验证：修改，原单行弱锚追加保留，新版追加同窗整组。
    #                 # group.append(i)
    #                 # i += 1
    #                 next_group = mapping[i].get('lines', [i])
    #                 group.extend(next_group)
    #                 i = next_group[-1] + 1
    #         groups.append(group)
    while i < len(reference['lines']):
        action = mapping[i]
        strong = action['kind']=='match' and action.get('weighted_edit_ratio', 1.) <= .30
        if strong:
            group = action.get('lines', [i])
            i = group[-1]+1
        else:
            group = []
            while i < len(reference['lines']):
                action = mapping[i]
                if action['kind']=='match' and action.get('weighted_edit_ratio', 1.) <= .30:
                    break
                block = action.get('lines', [i]) if action['kind']=='match' else [i]
                group.extend(block)
                i = block[-1]+1
        groups.append(group)
    jobs = []
    for group in groups:
        matches = [mapping[i] for i in group if mapping[i]['kind'] == 'match']
        before = next((mapping[i] for i in range(group[0]-1, -1, -1) if mapping[i]['kind']=='match'), None)
        after = next((mapping[i] for i in range(group[-1]+1, len(reference['lines'])) if mapping[i]['kind']=='match'), None)
        anchor_start = min((segments[a['segments'][0]]['start'] for a in matches), default=None)
        anchor_end = max((segments[a['segments'][-1]]['end'] for a in matches), default=None)
        warnings = []
        # 第二首跨歌曲验证：修改，原仅缺行扩窗保留；弱文本锚也从完整有声空隙核查。
        # if len(matches) != len(group):
        #     warnings += ['asr_missing_line', 'multi_line_window', 'anchor_window_unverified']
        needs_gap = len(matches) != len(group) or any(a['weighted_edit_ratio']>.30 for a in matches)
        if needs_gap:
            warnings += ['multi_line_window', 'anchor_window_unverified']
            warnings.append('asr_missing_line' if len(matches)!=len(group) else 'low_text_anchor_support')
            lower = segments[before['segments'][-1]]['end'] if before else 0.
            upper = segments[after['segments'][0]]['start'] if after else duration
            candidate_notes = [n for n in notes if n['start_seconds'] >= lower and n['end_seconds'] <= upper]
            if not candidate_notes:
                jobs.append({'job_id': len(jobs), 'line_indices': group, 'status': 'unassigned_no_voiced_window',
                             'warnings': warnings + ['no_reliable_audio_window'], 'matches': matches})
                continue
            start = min(n['start_seconds'] for n in candidate_notes) - padding
            end = max(n['end_seconds'] for n in candidate_notes) + padding
            # 歌词对齐与真实制谱：新增已知邻接锚边界保留，弱锚只是候选窗口而非逐字真值。
            if anchor_start is not None:
                start = min(start, anchor_start-padding)
                end = max(end, anchor_end+padding)
            start, end = max(lower-padding, start, 0.), min(upper+padding, end, duration)
        else:
            start, end = max(0., anchor_start-padding), min(duration, anchor_end+padding)
            if any(a['weighted_edit_ratio'] > .30 for a in matches):
                warnings += ['low_text_anchor_support', 'anchor_window_unverified']
        relevant = [n for n in notes if n['end_seconds'] > start and n['start_seconds'] < end]
        pitched_duration = sum(max(0., min(n['end_seconds'], end)-max(n['start_seconds'], start)) for n in relevant)
        jobs.append({'job_id': len(jobs), 'line_indices': group, 'status': 'candidate_window',
                     'reference_text': '\n'.join(reference['lines'][i] for i in group),
                     'start_seconds': round(start, 6), 'end_seconds': round(end, 6),
                     'matches': matches, 'warnings': warnings,
                     'melody_evidence': {'first_pitched_onset_seconds': min((n['start_seconds'] for n in relevant), default=None),
                                         'last_pitched_end_seconds': max((n['end_seconds'] for n in relevant), default=None),
                                         'pitched_note_count': len(relevant),
                                         'pitched_duration_seconds': pitched_duration},
                     # 第二首跨歌曲验证：修改，原窗口方法标记保留；弱锚也明确为声学空隙辅助。
                     # 'window_method': 'asr_sequence_and_voiced_gap' if len(matches)!=len(group) else 'asr_sequence_match'})
                     'window_method': 'asr_sequence_and_voiced_gap' if needs_gap else 'asr_sequence_match'})
    # 第三首《我不难过》跨歌曲验证：新增在GPU对齐前合并有证据的跨句界窗口，保留原ASR动作与原文。
    # 第三首《我不难过》跨歌曲验证：修改合并入口，使用已过滤的ASR段；原嵌套结构误读调用保留。
    # jobs = merge_shared_boundaries(jobs, reference, anchor, notes)
    jobs = merge_shared_boundaries(jobs, reference, {"segments": segments}, notes)
    return {'schema_version': 1, 'source': reference['source'], 'reference_kind': reference['reference_kind'],
            'line_count': len(reference['lines']), 'sequence_match_cost': cost,
            'actions': actions, 'jobs': jobs,
            'warnings': ['ASR句窗及音符有声范围仅用于裁剪；逐字边界来自真实TIFA音素状态，不均分、不使用词段中点。']}


# 歌词对齐与真实制谱：新增严格来源/配置缓存绑定与独立分句CLI，不改整曲工具。
def main():
    parser = argparse.ArgumentParser(description='同源ASR句窗中的真实TIFA强制对齐质量对照')
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--asr-anchor', type=Path, required=True)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--padding-seconds', type=float, default=.35)
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    report = {'task': '歌词对齐与真实制谱', 'operation': 'tifa_phrase_alignment', 'timings': {}, 'warnings': []}
    started = time.perf_counter()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        reference, anchor, analysis = read_json(args.reference), read_json(args.asr_anchor), read_json(args.analysis)
        source = reference['source']
        if file_sha256(Path(source['path'])) != source['sha256']:
            raise ValueError('用户参考音频源哈希失配')
        for name, artifact in [('ASR锚点', anchor), ('音符分析', analysis)]:
            if artifact.get('source', {}).get('sha256') != source['sha256']:
                raise ValueError(f'{name}与用户参考不属于同一源SHA256，拒绝复用')
            if artifact['source'].get('offset_seconds', 0.) != source.get('offset_seconds', 0.):
                raise ValueError(f'{name}与用户参考时间偏移不一致')
        if args.padding_seconds < 0 or args.padding_seconds > 2:
            raise ValueError('句窗padding必须在0至2秒之间')
        # 第二首跨歌曲验证：新增先检查再耗费GPU，异常文本原样保留到可读报告。
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # preflight = check_mandarin_reference(reference, anchor)
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        preflight = check_multilingual_reference(reference, anchor)
        save_json(output/'text_preflight.json', preflight)
        report['text_preflight'] = str(output/'text_preflight.json')
        # 连续转调识别与不确定调性保护：仅隔离已知语言限制，旧整曲拒绝条件保留。
        # if not preflight['valid_for_mandarin_tifa']:
        # raise ValueError('歌词文本或识别时间需先复核；详见text_preflight.json，不运行强制对齐。')
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # blocked=unsupported_lines(preflight,reference)
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        if not preflight['valid_for_multilingual_tifa']:
            raise ValueError('歌词语言或ASR时间异常；详见text_preflight.json。')
        blocked=set()
        report['unsupported_language_line_indices']=sorted(blocked)
        model = ROOT / '.cache/tifa/model/TIFA-1.0-ST/model.pt'
        cache_key = {'source_sha256': source['sha256'],
                     'text_sha256': hashlib.sha256(reference['text'].encode('utf-8')).hexdigest(),
                     'asr_anchor_sha256': file_sha256(args.asr_anchor), 'analysis_sha256': file_sha256(args.analysis),
                     'wrapper_sha256': file_sha256(Path(__file__)), 'tifa_wrapper_sha256': file_sha256(ROOT/'tools/lyrics_align.py'),
                     'model_sha256': file_sha256(model), 'padding_seconds': args.padding_seconds}
        # 第二首跨歌曲验证：新增歌词单位模块哈希，缓存不能忽略哼唱解析规则变化。
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # cache_key['lyrics_units_sha256'] = file_sha256(ROOT/'tools/lyrics_tokens.py')
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        cache_key['lyrics_units_sha256'] = file_sha256(ROOT/'tools/lyrics_tokens.py')
        cache_key['english_frontend_sha256'] = file_sha256(ROOT/'tools/english_lyrics.py')
        cache_key['phoneme_evidence_sha256'] = file_sha256(ROOT/'tools/phoneme_evidence.py')
        # 第四首《日落大道》男声跨歌曲验证：新增局部恢复策略哈希，旧缓存不能绕过新边界逻辑。
        cache_key['recovery_wrapper_sha256'] = file_sha256(ROOT/'tools/lyrics_window_recovery.py')
        # 连续转调识别与不确定调性保护：新增隔离策略缓存绑定。
        cache_key['partial_support_sha256'] = file_sha256(ROOT/'tools/lyrics_partial_support.py')
        # 连续转调识别与不确定调性保护：新增真实跨句恢复策略哈希，旧重叠缓存不能绕过。
        cache_key['boundary_recovery_sha256'] = file_sha256(ROOT/'tools/lyrics_boundary_recovery.py')
        target = output / 'characters.json'
        report.update(source=source, reference_kind=reference['reference_kind'], asr_anchor=str(args.asr_anchor.resolve()),
                      asr_model=anchor['configuration']['model'], cache_key=cache_key)
        if target.is_file() and not args.force and read_json(target).get('cache_key') == cache_key:
            report.update(status='cache_hit', output_characters=str(target))
        else:
            # 连续转调识别与不确定调性保护：规划后隔离不支持的完整句窗，原调用保留。
            # plan = plan_jobs(reference, anchor, analysis, args.padding_seconds)
            plan = supported_plan(plan_jobs(reference, anchor, analysis, args.padding_seconds),blocked)
            # 第四首《日落大道》男声跨歌曲验证：新增仅长缺锚窗局部ASR，不关闭整曲静音过滤，计划预览不运行GPU。
            if not args.plan_only:
                from lyrics_window_recovery import recover_long_gaps
                # 第四首《日落大道》男声跨歌曲验证：修改恢复传入同源声学分析，原调用保留。
                # anchor, recovery = recover_long_gaps(reference, anchor, plan, output/'asr_recovery', match_lines, text_cost, boundary_line_support)
                anchor, recovery = recover_long_gaps(reference, anchor, plan, output/'asr_recovery', match_lines, text_cost, boundary_line_support, analysis=analysis)
                report['asr_recovery'] = recovery
                if recovery['added_segments']:
                    # 连续转调识别与不确定调性保护：恢复句窗后仍应用同一后端边界，原调用保留。
                    # plan = plan_jobs(reference, anchor, analysis, args.padding_seconds)
                    plan = supported_plan(plan_jobs(reference, anchor, analysis, args.padding_seconds),blocked)
                    plan['asr_recovered_path'] = str((output/'asr_recovery/asr_recovered.json').resolve())

            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # plan['cache_key'] = cache_key
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # from english_lyrics import merge_english_phrase_windows
            # plan = merge_english_phrase_windows(plan, reference)
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # from english_lyrics import merge_english_phrase_windows, recover_missing_english_windows
            # plan = recover_missing_english_windows(plan, reference)
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            from english_lyrics import merge_english_phrase_windows, recover_missing_english_windows, joint_repeated_english_windows
            plan = joint_repeated_english_windows(plan, reference)
            report['english_repeated_window_policy'] = plan['english_repeated_window_policy']
            plan = recover_missing_english_windows(plan, reference)
            report['english_missing_window_recovery'] = plan['english_missing_window_recovery']
            plan = merge_english_phrase_windows(plan, reference)
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # report['english_window_policy'] = plan['english_window_policy']
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            report['english_window_policy'] = plan['english_window_policy']
            report['unassigned_window_line_indices'] = sorted({i for j in plan['jobs'] if j['status'].startswith('unassigned_') for i in j['line_indices']})
            plan['cache_key'] = cache_key
            save_json(output/'phrase_plan.json', plan)
            report['phrase_plan'] = str(output/'phrase_plan.json')
            if args.plan_only:
                report.update(status='plan_only', jobs=plan['jobs'])
            else:
                import soundfile as sf
                import torch
                # 连续转调识别与不确定调性保护：原字符构造保留，新增明确未支持标记。
                # chars = reference_characters(reference)
                chars = mark_unsupported_characters(reference_characters(reference),plan)
                report["backend_unaligned_line_indices"] = plan.get("backend_unaligned_line_indices",[])
                phrase_reports = []
                for job in plan['jobs']:
                    if job['status'] != 'candidate_window':
                        continue
                    phase = time.perf_counter()
                    info = sf.info(local_path(source['path']))
                    offset = source.get('offset_seconds', 0.)
                    first = max(0, math.floor((job['start_seconds']-offset)*info.samplerate))
                    last = min(info.frames, math.ceil((job['end_seconds']-offset)*info.samplerate))
                    crop = output/'crops'/f"phrase_{job['job_id']:03d}.wav"
                    crop.parent.mkdir(parents=True, exist_ok=True)
                    audio, rate = sf.read(local_path(source['path']), start=first, stop=last, dtype='float32', always_2d=True)
                    sf.write(crop, audio, rate, subtype='FLOAT')
                    local = {**reference, 'text': job['reference_text'],
                             'lines': [reference['lines'][i] for i in job['line_indices']],
                             'source': {'path': str(crop), 'sha256': file_sha256(crop), 'sample_rate': rate,
                                        'channels': info.channels, 'duration_seconds': len(audio)/rate,
                                        'offset_seconds': first/rate+offset}}
                    detail = {'job_id': job['job_id'], 'line_indices': job['line_indices'], 'timings': {},
                              'crop': local['source'], 'original_source': source, 'anchor_evidence': job,
                              'reference_kind': reference['reference_kind']}
                    detail['timings']['crop_decode_write_seconds'] = time.perf_counter()-phase
                    phrase_output = output/'phrases'/f"phrase_{job['job_id']:03d}"
                    print(json.dumps({'event': 'phrase_started', 'job_id': job['job_id'], 'line_indices': job['line_indices'],
                                      'start_seconds': local['source']['offset_seconds'], 'duration_seconds': local['source']['duration_seconds']}, ensure_ascii=False), flush=True)
                    try:
                        values = tifa_align(local, phrase_output, detail)
                        values = reject_unreliable_candidates(values, local, detail)
                        destinations = [c for c in chars if c['line_index'] in job['line_indices']]
                        if [c['text'] for c in destinations] != [c['text'] for c in values]:
                            raise RuntimeError('分句与全曲字符序列不一致')
                        for dest, value in zip(destinations, values):
                            global_index, line_index = dest['index'], dest['line_index']
                            dest.update(value)
                            dest.update(index=global_index, line_index=line_index,
                                        group_id=f"phrase_{job['job_id']:03d}_{value.get('group_id')}",
                                        phrase_job_id=job['job_id'], alignment_scope='phrase_window',
                                        warnings=list(dict.fromkeys(value['warnings']+job['warnings'])))
                            if dest['start_seconds'] is not None:
                                dest['method'] = 'tifa_phrase_texts_tier'
                                # 歌词对齐与真实制谱：新增裁剪边缘诊断，保留实际边界并提示尾音可能截断。
                                clip_end = local['source']['offset_seconds'] + local['source']['duration_seconds']
                                if dest['start_seconds'] - local['source']['offset_seconds'] < .02:
                                    dest['warnings'].append('phrase_crop_left_edge_review_required')
                                if clip_end - dest['end_seconds'] < .02:
                                    dest['warnings'].append('phrase_crop_right_edge_review_required')
                        # 歌词对齐与真实制谱：新增用户权威文本身份及裁剪边缘索引诊断。
                        detail['quality_note'] = '用户原文保持；模型逐字边界尚未人工核验，agreement不是正确率。' if reference['reference_kind']=='user_supplied' else '识别文本及模型边界尚未人工核验。'
                        detail['crop_edge_character_indices'] = [c['index'] for c in destinations if any('phrase_crop_' in w for w in c['warnings'])]
                        detail.update(status='real_tifa_prediction_completed', total_characters=len(values),
                                      characters_with_time=sum(v['start_seconds'] is not None for v in values))
                    except Exception as exc:
                        detail.update(status='failed', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
                        for dest in chars:
                            if dest['line_index'] in job['line_indices']:
                                dest['warnings'] += ['phrase_tifa_failure']
                    detail['wall_seconds'] = time.perf_counter()-phase
                    save_json(phrase_output/'report.json', detail)
                    phrase_reports.append(detail)
                    save_json(output/'phrase_reports.partial.json', {'source': source, 'phrases': phrase_reports})
                    print(json.dumps({'event': 'phrase_completed', 'job_id': job['job_id'], 'status': detail['status'],
                                      'accepted': detail.get('characters_with_time'), 'wall_seconds': detail['wall_seconds']}, ensure_ascii=False), flush=True)
                    gc.collect()
                    torch.cuda.empty_cache()
                # 连续转调识别与不确定调性保护：新增跨句逆序/重复占声的真实联合预测，保留首次预测。
                from lyrics_boundary_recovery import recover_boundaries
                chars,phrase_reports,boundary_recovery=recover_boundaries(chars,plan,reference,output,phrase_reports,tifa_align,reject_unreliable_candidates)
                report['boundary_recovery']=boundary_recovery
                # 连续转调识别与不确定调性保护：区分部分支持，原状态保留。
                # status = 'tifa_phrases_forced_aligned_unverified'
                status = 'tifa_phrases_partial_alignment_unsupported_language' if blocked else 'tifa_phrases_forced_aligned_unverified'
                result = {'schema_version': 1, 'source': source, 'reference_kind': reference['reference_kind'],
                          'alignment_status': status, 'reference_file': str(args.reference.resolve()),
                          'cache_key': cache_key, 'characters': chars, 'phrase_plan': str(output/'phrase_plan.json'),
                          # 第二首跨歌曲验证：修改，自动识别稿不能标成用户原文；旧文案注释保留。
                          # 'warnings': ['歌词来自用户原文；句窗和模型边界仍需人工核验。',
                          'warnings': [('歌词来自用户原文；句窗和模型边界仍需人工核验。' if reference['reference_kind']=='user_supplied' else '歌词为自动识别稿，文本、句窗和模型边界均未人工校正。'),
                                       '缺ASR锚点的连续句使用同一有声窗口真实TIFA预测，没有按行或字均分。',
                                       '原音素候选、零时长拒绝原因及诊断保存在逐句目录；confidence为空，内部agreement不是正确率。']}
                save_json(target, result)
                report.update(status=status, output_characters=str(target), total_characters=len(chars),
                              characters_with_time=sum(c['start_seconds'] is not None for c in chars),
                              characters_with_warnings=sum(bool(c['warnings']) for c in chars),
                              phrase_jobs=len(plan['jobs']), real_tifa_predictions=len(phrase_reports),
                              failed_predictions=sum(d['status']=='failed' for d in phrase_reports),
                              phrase_reports=phrase_reports,
                              peak_gpu_allocated_bytes=max((d.get('peak_gpu_allocated_bytes', 0) for d in phrase_reports), default=0),
                              peak_gpu_reserved_bytes=max((d.get('peak_gpu_reserved_bytes', 0) for d in phrase_reports), default=0))
                report['timings'] = {key: sum(d['timings'].get(key, 0.) for d in phrase_reports)
                                     for key in ('crop_decode_write_seconds', 'model_load_to_gpu_seconds',
                                                 'g2p_decode_resample_seconds', 'predict_diagnostics_export_seconds')}
                report['timings']['weight_download_seconds'] = 0.
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
    report['wall_seconds'] = time.perf_counter()-started
    # 歌词对齐与真实制谱：修改；原无条件写入保留为注释，避免缓存命中覆盖首次推理计时证据。
    # save_json(ROOT/'reports/lyrics_phrase_alignment.json', report)
    # save_json(output/'alignment_report.json', report)
    if report['status'] == 'cache_hit':
        # 歌词对齐与真实制谱：新增本次CPU缓存检查报告，首次模型预测报告保持原字节。
        save_json(ROOT/'reports/lyrics_phrase_alignment.latest.json', report)
        save_json(output/'alignment_report.latest.json', report)
    else:
        # 歌词对齐与真实制谱：新增真实预测或失败报告沿用原路径，保持外部接口兼容。
        save_json(ROOT/'reports/lyrics_phrase_alignment.json', report)
        save_json(output/'alignment_report.json', report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('phrase_reports', 'jobs')}, ensure_ascii=False), flush=True)
    return 1 if report['status']=='failed' or report.get('failed_predictions', 0) else 0


if __name__ == '__main__':
    raise SystemExit(main())
