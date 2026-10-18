"""第四首《日落大道》男声跨歌曲验证：新增长缺锚窗局部ASR恢复，原文/原锚点只读。"""
from pathlib import Path
from workspace_location import local_path
import copy,math,time
MAX_WINDOW_SECONDS=24.; MAX_RETRY_CROPS=4; OVERLAP_SECONDS=4.

# 第四首《日落大道》男声跨歌曲验证：新增从长缺锚窗尾部逐块检查，限制GPU重试次数。
# 第四首《日落大道》男声跨歌曲验证：修改加入最长声学空隙后的重裁剪，旧签名保留。
# def retry_windows(job):
def retry_windows(job,analysis=None):
    if job.get('status')!='candidate_window' or not {'asr_missing_line','low_text_anchor_support'}.intersection(job.get('warnings',[])):
        return []
    start,end=job.get('start_seconds'),job.get('end_seconds')
    if start is None or end is None or end-start<=MAX_WINDOW_SECONDS:return []
    # 第四首《日落大道》男声跨歌曲验证：修改原只逐块后退的重试，保留旧代码；文本失败时尝试独立声学定位。
    # windows=[];right=end
    # while right>start and len(windows)<MAX_RETRY_CROPS:
    #     left=max(start,right-MAX_WINDOW_SECONDS);windows.append((left,right))
    #     if left==start:break
    #     right=left+OVERLAP_SECONDS
    # return windows
    windows=[(max(start,end-MAX_WINDOW_SECONDS),end)]
    notes=sorted((n for n in (analysis or {}).get('notes',[]) if not n.get('is_rest',False)
                  and n['end_seconds']>start and n['start_seconds']<end
                  and n.get('quality',{}).get('voiced_fraction',0)>=.3),key=lambda n:n['start_seconds'])
    # 第四首《日落大道》男声跨歌曲验证：新增相对响度筛选只用于重试窗定位；间奏低声残余不截短真实停顿，原音符不删。
    rms=sorted(n.get('quality',{}).get('rms_dbfs') for n in notes if n.get('quality',{}).get('rms_dbfs') is not None)
    floor=rms[int(.8*(len(rms)-1))]-18. if rms else -math.inf
    notes=[n for n in notes if n.get('quality',{}).get('rms_dbfs',floor)>=floor]
    gaps=[(b['start_seconds']-a['end_seconds'],b['start_seconds']) for a,b in zip(notes,notes[1:])]
    if gaps and max(gaps)[0]>=3.:
        # 第四首《日落大道》男声跨歌曲验证：修改预留3秒发声前上下文；原间奏残余误定位行保留。
        # onset=max(gaps)[1];left=max(start,onset-4.);right=min(end,left+MAX_WINDOW_SECONDS)
        onset=max(gaps)[1];left=max(start,onset-3.);right=min(end,left+MAX_WINDOW_SECONDS)
        if right>left and all(abs(left-a)>.1 or abs(right-b)>.1 for a,b in windows):windows.append((left,right))
    right=windows[0][0]+OVERLAP_SECONDS
    while right>start and len(windows)<MAX_RETRY_CROPS:
        left=max(start,right-MAX_WINDOW_SECONDS)
        if all(abs(left-a)>.1 or abs(right-b)>.1 for a,b in windows):windows.append((left,right))
        if left==start:break
        right=left+OVERLAP_SECONDS
    return windows

# 第四首《日落大道》男声跨歌曲验证：新增文本和密度闸门，局部幻觉不可仅靠有声残余入库。
def validate_segment(segment,lines,text_cost,boundary_support):
    if not segment.get('text','').strip():return False
    start,end=segment.get('start'),segment.get('end')
    if not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or not math.isfinite(start+end) or end<=start:return False
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # if len(segment['text'].strip())/(end-start)>20:return False
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    from lyrics_tokens import text_units
    if len(text_units(segment['text']))/(end-start)>20:return False
    for line in lines:
        if text_cost(line,segment['text'])['weighted_edit_ratio']<=.30:
            # 第四首《日落大道》男声跨歌曲验证：修改边界支持参数为元组，lru_cache不能接收列表；旧行保留。
            # head,tail=boundary_support([line],segment['text'])
            head,tail=boundary_support((line,),segment['text'])
            if head>=.65 and tail>=.65:return True
    return False

# 第四首《日落大道》男声跨歌曲验证：新增裁剪坐标到统一全曲坐标转换，全部字时戳只来自模型。
def globalize_segment(segment,crop_offset,source_offset):
    item=copy.deepcopy(segment);shift=crop_offset-source_offset
    item['start']+=shift;item['end']+=shift
    for word in item.get('words',[]):
        word['start']+=shift;word['end']+=shift
    return item

# 第四首《日落大道》男声跨歌曲验证：新增已存在时间锚保护，不让局部识别重写已识别演唱。
def duplicate_segment(segment,existing,text_cost):
    for previous in existing:
        overlap=min(segment['end'],previous['end'])-max(segment['start'],previous['start'])
        if overlap>0 and overlap/min(segment['end']-segment['start'],previous['end']-previous['start'])>.5 and text_cost(segment['text'],previous['text'])['weighted_edit_ratio']<=.3:return True
    return False

# 第四首《日落大道》男声跨歌曲验证：修改恢复入口接收独立声学分析，旧签名保留。
# def recover_long_gaps(reference,anchor,plan,output,match_lines,text_cost,boundary_support,transcriber=None):
def recover_long_gaps(reference,anchor,plan,output,match_lines,text_cost,boundary_support,transcriber=None,analysis=None):
    from lyrics_transcribe import transcribe,file_sha256,save_json
    import soundfile as sf
    result=copy.deepcopy(anchor);evidence={'status':'not_needed','attempts':[],'added_segments':0,'max_retry_crops':MAX_RETRY_CROPS,'window_seconds':MAX_WINDOW_SECONDS}
    eligible=[job for job in plan['jobs'] if retry_windows(job)]
    if not eligible:return result,evidence
    if file_sha256(Path(reference['source']['path']))!=reference['source']['sha256']:raise ValueError('局部ASR源SHA失配')
    output=Path(output);output.mkdir(parents=True,exist_ok=True);info=sf.info(local_path(reference['source']['path']));source_offset=reference['source'].get('offset_seconds',0.)
    for job in eligible:
        # 第四首《日落大道》男声跨歌曲验证：修改实际重试使用声学空隙，原循环保留。
        # for start,end in retry_windows(job):
        for start,end in retry_windows(job,analysis):
            if len(evidence['attempts'])>=MAX_RETRY_CROPS:break
            attempt={'original_job_id':job['job_id'],'line_indices':job['line_indices'],'start_seconds':start,'end_seconds':end};started=time.perf_counter()
            try:
                first=max(0,math.floor((start-source_offset)*info.samplerate));last=min(info.frames,math.ceil((end-source_offset)*info.samplerate))
                audio,rate=sf.read(local_path(reference['source']['path']),start=first,stop=last,dtype='float32',always_2d=True)
                folder=output/f'crop_{len(evidence["attempts"]):02d}';folder.mkdir(parents=True,exist_ok=True);path=folder/'vocals.wav';sf.write(path,audio,rate,subtype='FLOAT')
                source={'path':str(path.resolve()),'sha256':file_sha256(path),'sample_rate':rate,'channels':info.channels,'duration_seconds':len(audio)/rate,'offset_seconds':first/rate+source_offset}
                # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
                # raw,timings=(transcriber or transcribe)(source,anchor['configuration']['model'],folder,False);attempt.update(source=source,asr_raw=str((folder/'asr_raw.json').resolve()),timings=timings)
                # 中文版本冻结与英文融合验证：新增中英文兼容实现。
                from lyrics_tokens import asr_language_for_text
                language=asr_language_for_text('\n'.join(reference['lines'][i] for i in job['line_indices']))
                if transcriber is None:
                    raw,timings=transcribe(source,anchor['configuration']['model'],folder,False,language=language)
                else:
                    raw,timings=transcriber(source,anchor['configuration']['model'],folder,False)
                attempt.update(source=source,asr_raw=str((folder/'asr_raw.json').resolve()),timings=timings,language=language)
                if raw['source']['sha256']!=source['sha256']:raise ValueError('局部ASR返回源SHA失配')
                added=[]
                for segment in raw['result']['segments']:
                    if not validate_segment(segment,[reference['lines'][i] for i in job['line_indices']],text_cost,boundary_support):continue
                    if segment['start']<0 or segment['end']>source['duration_seconds']+.10:continue
                    item=globalize_segment(segment,source['offset_seconds'],source_offset)
                    if duplicate_segment(item,result['result']['segments']+added,text_cost):continue
                    item['recovery_source']={'crop_sha256':source['sha256'],'raw_file':attempt['asr_raw'],'original_segment_id':item.get('id')};added.append(item)
                result['result']['segments'].extend(added);result['result']['segments'].sort(key=lambda x:(x['start'],x['end']));attempt['added_segments']=len(added);evidence['added_segments']+=len(added)
                mapping,_,_=match_lines(reference['lines'],result['result']['segments'])
                recovered=[i for i in job['line_indices'] if mapping[i].get('kind')=='match' and mapping[i].get('weighted_edit_ratio',1)<=.30 and all(start-.1<=result['result']['segments'][j]['start']+source_offset<=end+.1 for j in mapping[i]['segments'])]
                attempt.update(status='local_asr_completed',recovered_line_indices=recovered)
            except Exception as exc:attempt.update(status='failed',error=f'{type(exc).__name__}: {exc}',recovered_line_indices=[])
            attempt['wall_seconds']=time.perf_counter()-started;evidence['attempts'].append(attempt)
            if set(attempt.get('recovered_line_indices',[]))==set(job['line_indices']):break
    evidence['status']='recovered_new_anchors' if evidence['added_segments'] else 'attempted_no_supported_new_anchors'
    result['local_recovery']=evidence;save_json(output/'asr_recovered.json',result);save_json(output/'recovery.json',evidence)
    return result,evidence
