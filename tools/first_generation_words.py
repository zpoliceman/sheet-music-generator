"""首拍与首尾局部补证：已验首次拍轴后的局部字音对齐，不重识别原音高。"""
# 首拍与首尾局部补证：新增显式来源派生层；仅问题句和无锚尾行可变化，原拍轴及其余词音不变。
from copy import deepcopy
import math
from pathlib import Path
from workspace_location import local_path
import numpy as np
import soundfile as sf
from score_export import read_json,save_json,sha256
from source_meter_selection import fingerprint

POLICY={'version':1,'only_unmapped_character_jobs':True,'padding_quarters':1.,
        'missing_terminal_anchor_not_forced_into_other_text':True,'whole_pitch_or_chord_decoder_called':False,
        'old_tifa_rejection_policy_retained':True,'normal_publication_allowed':False}
# 首拍与首尾局部补证：修改显式第二版仅令同内容拍轴决定可复制到新工作目录；原v1精确来源重放保留。
LEGACY_POLICY=deepcopy(POLICY)
POLICY={**POLICY,'version':2,'clock_decision_content_identity_not_copy_location':True}


def base_fingerprint(voice,version=2):
    # 首拍与首尾局部补证：新增位置无关来源身份，仍绑定决定SHA及完整实际人声；移动目录不能掩盖拍轴变化。
    value=deepcopy(voice)
    if version==2:value.get('first_source_meter_correction',{}).pop('decision_path',None)
    return fingerprint(value)


def local_jobs(voice,plan,anchor,reference):
    # 首拍与首尾局部补证：新增仅处理含未挂字的旧句窗；没有ASR锚点的尾行不再把整段器乐塞入强制对齐。
    chars=voice['lyrics']['characters'];missing=set(voice['lyric_mapping']['unmapped_character_indices'])
    bad_lines={c['line_index'] for c in chars if c['index'] in missing};segments=anchor['result']['segments']
    period=60./voice['timing']['steady_tempo_bpm'];jobs=[]
    for old in plan['jobs']:
        if not bad_lines.intersection(old['line_indices']):continue
        matched=sorted({line for row in old.get('matches',[]) for line in row.get('lines',[row['line']])})
        if not matched:continue
        indices=sorted({i for row in old['matches'] for i in row['segments']})
        start=max(0.,min(segments[i]['start'] for i in indices)-period*POLICY['padding_quarters'])
        end=min(reference['source']['duration_seconds'],max(segments[i]['end'] for i in indices)+period*POLICY['padding_quarters'])
        jobs.append({'line_indices':matched,'unanchored_terminal_lines':[i for i in old['line_indices'] if i>matched[-1]],
            'start_seconds':start,'end_seconds':end,'text':'\n'.join(reference['lines'][i] for i in matched),
            'source_asr_segment_indices':indices,'parent_job_id':old['job_id']})
    return jobs


def prepare_words(base_path,binding,plan_path,anchor_path,reference_path,output):
    # 首拍与首尾局部补证：新增局部真实Tifa运行；先严格重放拍轴，任何全曲音高／和弦调用均不在此入口。
    from source_meter_entry import require_calibrated_source
    from source_timing_acceptance import require_isolated_output
    from lyrics_align import tifa_align,reject_unreliable_candidates
    voice=read_json(base_path);require_calibrated_source(voice,binding)
    output=require_isolated_output(output,Path(__file__).resolve().parents[1])
    if output.exists():raise ValueError('局部词音补证不覆盖旧版本')
    plan,anchor,reference=[read_json(p) for p in (plan_path,anchor_path,reference_path)]
    source=binding['sources']['vocals']
    if any(v['source']['sha256']!=source['sha256'] for v in (plan,anchor,reference)):
        raise ValueError('局部词音的原唱、参考文本和锚点来源不一致')
    jobs=local_jobs(voice,plan,anchor,reference);output.mkdir(parents=True)
    dependencies=[{'path':str(Path(p).resolve()),'sha256':sha256(p)} for p in (plan_path,anchor_path,reference_path)]
    records=[]
    for i,job in enumerate(jobs):
        folder=output/('job_'+str(i));folder.mkdir()
        with sf.SoundFile(local_path(source['path'])) as stream:
            rate=stream.samplerate;first=max(0,math.floor(job['start_seconds']*rate));last=min(stream.frames,math.ceil(job['end_seconds']*rate))
            stream.seek(first);audio=stream.read(last-first,dtype='float32',always_2d=True)
        crop=folder/'vocals.wav';sf.write(crop,audio,rate,subtype='FLOAT')
        local={**reference,'lines':[reference['lines'][n] for n in job['line_indices']],'text':job['text'],
               'source':{'path':str(crop.resolve()),'sha256':sha256(crop),'offset_seconds':first/rate,
                         'duration_seconds':len(audio)/rate,'sample_rate':rate,'channels':audio.shape[1]}}
        detail={'timings':{},'scope':'local_alignment_not_whole_music_certificate','job':job}
        print('局部字音',job['line_indices'],local['source']['offset_seconds'],len(audio)/rate,flush=True)
        values=tifa_align(local,folder,detail);values=reject_unreliable_candidates(values,local,detail)
        destinations=[c for c in voice['lyrics']['characters'] if c['line_index'] in job['line_indices']]
        if [c['text'] for c in values]!=[c['text'] for c in destinations]:raise ValueError('局部字序不一致')
        for char,old in zip(values,destinations):char.update(index=old['index'],line_index=old['line_index'])
        save_json(folder/'report.json',detail);save_json(folder/'characters.json',values)
        for path in (crop,folder/'tifa/raw_alignment.json',folder/'report.json',folder/'characters.json'):
            dependencies.append({'path':str(path.resolve()),'sha256':sha256(path)})
        records.append({**job,'characters_path':str((folder/'characters.json').resolve()),
                        'raw_alignment_path':str((folder/'tifa/raw_alignment.json').resolve()),'crop':local['source']})
    # 首拍与首尾局部补证：修改词音来源版本只规范化拍轴凭证的复制位置，原式保留。
    # artifact={'version':1,'policy':deepcopy(POLICY),'base_voice_sha256':fingerprint(voice),'vocals_sha256':source['sha256'],
    artifact={'version':2,'policy':deepcopy(POLICY),'base_voice_sha256':base_fingerprint(voice),'vocals_sha256':source['sha256'],
              'dependencies':dependencies,'jobs':records,'full_music_accepted':False}
    path=output/'word_supplement.json';save_json(path,artifact)
    # 歌词自动加载与伴随声部音区保护：修改新产物返回可复用声明，旧v2文件原样保留；两份拍轴都须严格重放，模型不重算。
    # return path
    from first_generation_word_cache import register_cache
    return register_cache(path, base_path, binding, output/'reusable_word_supplement.json')


def validate_words(artifact,binding):
    # 首拍与首尾局部补证：新增验证真实原唱裁片PCM及Tifa原音素，不能靠自填字界／旧缓存标记放行。
    from phoneme_evidence import character_phonemes
    # 首拍与首尾局部补证：修改按实际版本核验，旧v1不会被新版位置规范化策略误判。
    # if artifact.get('version')!=1 or artifact.get('policy')!=POLICY or artifact['vocals_sha256']!=binding['sources']['vocals']['sha256']:
    expected={1:LEGACY_POLICY,2:POLICY}.get(artifact.get('version'))
    if expected is None or artifact.get('policy')!=expected or artifact['vocals_sha256']!=binding['sources']['vocals']['sha256']:
        raise ValueError('局部词音策略或来源不一致')
    for row in artifact['dependencies']:
        if sha256(row['path'])!=row['sha256']:raise ValueError('局部词音原证据文件已变')
    for job in artifact['jobs']:
        source=job['crop'];raw=read_json(job['raw_alignment_path']);values=read_json(job['characters_path'])
        if raw['source']!=source:raise ValueError('局部词音原始模型来源不一致')
        with sf.SoundFile(local_path(binding['sources']['vocals']['path'])) as stream:
            stream.seek(round(source['offset_seconds']*stream.samplerate));audio=stream.read(round(source['duration_seconds']*stream.samplerate),dtype='float32',always_2d=True)
        crop,rate=sf.read(local_path(source['path']),dtype='float32',always_2d=True)
        if rate!=source['sample_rate'] or not np.array_equal(audio,crop):raise ValueError('局部字音裁片不是绑定原唱对应PCM')
        states=raw['results'][0]['phoneme_states']
        for char in values:
            owner=char['phoneme_source']['word_owner'];local=[s for s in states if s['word_owner']==owner]
            # 首拍与首尾局部补证：新增原文本owner一致性校验，不能把同音素文件重新贴上另一字的身份。
            from lyrics_tokens import lyric_match_key
            texts=raw['results'][0]['texts']
            if not 1<=owner<=len(texts) or lyric_match_key(texts[owner-1])!=lyric_match_key(char['text']):
                raise ValueError('局部字符与原模型文本owner不一致')
            if char.get('phonemes',[])!=character_phonemes(local,source['offset_seconds']):raise ValueError('局部字界的音素无法由原始模型重放')
            if char['start_seconds'] is not None:
                valid=[s for s in local if s['end_seconds']>s['start_seconds']]
                if (not valid or len(valid)!=len(local) or char['end_seconds']-char['start_seconds']<.03
                        or abs(char['start_seconds']-min(s['start_seconds'] for s in valid)-source['offset_seconds'])>2e-6
                        or abs(char['end_seconds']-max(s['end_seconds'] for s in valid)-source['offset_seconds'])>2e-6):
                    raise ValueError('局部字符没有通过原最短音素／完整音素门禁')


def apply_words(base,artifact,binding):
    # 首拍与首尾局部补证：新增仅局部重挂词，必要同音分字沿原音拆开；其它音符、真实音值、拍轴不改。
    from word_note_alignment import align_notes
    from accompaniment_analysis import SongClock
    from local_lyric_revision import _portion
    from source_timing_revision import rebuild_events
    # 歌词自动加载与伴随声部音区保护：新增明确新版分派；旧v1/v2校验不变，新缓存逐项复核原音素及旧／新完整音乐。
    if artifact.get('artifact_kind') == 'verified_first_generation_word_cache':
        from first_generation_word_cache import apply_cached_words
        return apply_cached_words(base,artifact,binding)
    validate_words(artifact,binding)
    # 首拍与首尾局部补证：修改仅v2允许同内容决定的另存副本；源音符、词音或拍点任何变化仍失败。
    # if fingerprint(base)!=artifact['base_voice_sha256']:raise ValueError('局部字音基准不是已验拍轴的人声')
    if base_fingerprint(base,artifact['version'])!=artifact['base_voice_sha256']:raise ValueError('局部字音基准不是已验拍轴的人声')
    voice=deepcopy(base);chars=voice['lyrics']['characters'];notes=voice['quantized_notes'];clock=SongClock(voice);audit=[]
    for job in artifact['jobs']:
        values=read_json(job['characters_path']);lines=set(job['line_indices']);unsupported=set(job['unanchored_terminal_lines'])
        # 首拍与首尾局部补证：新增局部行／字索引／原文三重一致，原参考歌词不能被字音补证改写。
        expected=[(c['index'],c['line_index'],c['text']) for c in chars if c['line_index'] in lines]
        if [(c['index'],c['line_index'],c['text']) for c in values]!=expected:
            raise ValueError('局部字音不能改变原行、字身份或参考歌词')
        old_owners={c['index'] for c in chars if c['line_index'] in lines|unsupported}
        for char in values:chars[char['index']]=deepcopy(char)
        for char in chars:
            if char['line_index'] in unsupported:
                char.update(start_seconds=None,end_seconds=None,phonemes=[],method='unanchored_terminal_line_not_forced',
                            warnings=list(dict.fromkeys(char.get('warnings',[])+['terminal_text_anchor_missing_review_required'])))
        selected=[n for n in notes if n.get('lyric_index') in old_owners or
                  (n.get('lyric_index') is None and n['start_seconds']>=job['start_seconds'] and n['end_seconds']<=job['end_seconds'])]
        local=[n for n in selected if n['start_seconds']>=job['start_seconds'] and n['end_seconds']<=job['end_seconds']]
        accepted=[c for c in values if c['start_seconds'] is not None]
        pieces,_,issues=align_notes(local,{'characters':accepted})
        replacement={n['id']:[] for n in selected}
        for item in pieces:
            parent=next((n for n in local if item['id']==n['id'] or item['id'].startswith(n['id']+'.syllable')),None)
            if parent is None:raise ValueError('局部重挂丢失原音身份')
            if item['id']==parent['id']:
                value=deepcopy(parent);value['lyric_index']=item['lyric_index'];value['word_alignment']=deepcopy(item.get('word_alignment'))
            else:
                a,b=item['start_seconds'],item['end_seconds']
                left=parent['start_tick'] if a==parent['start_seconds'] else clock.quantize(a,30)
                right=parent['end_tick'] if b==parent['end_seconds'] else clock.quantize(b,30)
                value=_portion(parent,a,b,left,right,item['lyric_index'],clock)
                value['id']=item['id'];value['local_word_parent_id']=parent['id'];value['word_alignment']=deepcopy(item.get('word_alignment'))
                # 首拍与首尾局部补证：新增同音派生播放分段同步其新身份；原声音区间／原始来源身份仍由_portion保留。
                for segment in value.get('performance_segments',[]):segment['piece_id']=value['id']
            replacement[parent['id']].append(value)
        for old in selected:
            if not replacement[old['id']]:replacement[old['id']]=[{**deepcopy(old),'lyric_index':None,
                'word_alignment':{'method':'local_window_unassigned','requires_review':True}}]
            parts=sorted(replacement[old['id']],key=lambda n:n['start_seconds'])
            if (parts[0]['start_seconds']!=old['start_seconds'] or parts[-1]['end_seconds']!=old['end_seconds']
                    or any(a['end_seconds']!=b['start_seconds'] for a,b in zip(parts,parts[1:]))
                    or any(p['pitch_midi']!=old['pitch_midi'] for p in parts)):
                raise ValueError('局部词音改变完整原音高或真实持续区间')
        notes=[part for n in notes for part in replacement.get(n['id'],[n])]
        audit.append({'line_indices':sorted(lines),'unanchored_lines_retained':sorted(unsupported),'issues':issues,
                      'original_note_count':len(selected),'derived_note_count':sum(map(len,replacement.values()))})
    voice['quantized_notes']=notes;rebuild_events(voice,voice['timing']['measure_timeline'])
    # 首拍与首尾局部补证：新增将原跨音连奏的两端转移到同音分字首尾，字音修订不能删掉原旋律表达。
    for event in voice['events']:
        part=next((n for n in notes if n['id']==event.get('piece_id')),None)
        if not part or not part.get('local_word_parent_id'):continue
        parent=next(n for n in base['quantized_notes'] if n['id']==part['local_word_parent_id'])
        slurs=[s for e in base['events'] if e.get('piece_id')==parent['id'] for s in e.get('slurs',[])
               if (s['type']=='start' and event['start_tick']==parent['start_tick']) or
                  (s['type']=='stop' and event['start_tick']+event['duration_ticks']==parent['end_tick'])]
        if slurs:event['slurs']=deepcopy(slurs)
    voice['local_first_word_audit']={'jobs':audit,'unmapped_character_indices':voice['lyric_mapping']['unmapped_character_indices'],
                                   'pitch_chord_and_clock_preserved':True,'full_music_accepted':False}
    return voice


def replay_words(correction,binding):
    # 首拍与首尾局部补证：新增最高层严格重放，词音局部证据不能替代已验拍轴来源。
    from first_generation_source import replay_first_voice
    if correction.get('version')!=1 or sha256(correction['artifact_path'])!=correction['artifact_sha256']:
        raise ValueError('局部字音来源证明已经变化')
    base=replay_first_voice(read_json(binding['vocal_project']),binding,correction['clock_correction'])
    result=apply_words(base,read_json(correction['artifact_path']),binding)
    result['first_source_word_correction']=deepcopy(correction)
    return result


def use_words(voice,binding,path):
    # 首拍与首尾局部补证：新增首次生成只消费显式局部补证文件，不自动修改任何旧工程。
    correction={'version':1,'artifact_path':str(Path(path).resolve()),'artifact_sha256':sha256(path),
                'clock_correction':deepcopy(voice['first_source_meter_correction'])}
    result=apply_words(voice,read_json(path),binding);result['first_source_word_correction']=correction
    return result
