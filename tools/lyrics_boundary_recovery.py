"""连续转调识别与不确定调性保护：相邻句窗字界冲突需真实联合对齐，不人为顺排时间。"""
# 连续转调识别与不确定调性保护：新增有界真实重预测；原预测与来源记录均保留。
import copy,gc,math,time
from pathlib import Path
from lyrics_transcribe import file_sha256,save_json

def conflicting_groups(chars):
    # 连续转调识别与不确定调性保护：检测跨预测窗逆序/重复占声，词内共享范围不触发。
    timed=sorted((c for c in chars if c.get('start_seconds') is not None and c.get('end_seconds') is not None),key=lambda c:c['index']);pairs=[]
    for before,after in zip(timed,timed[1:]):
        a,b=before.get('phrase_job_id'),after.get('phrase_job_id')
        if a is None or b is None or a==b:continue
        if after['start_seconds']<before['start_seconds']-1e-7 or before['end_seconds']-after['start_seconds']>.08:pairs.append({a,b})
    groups=[]
    for pair in pairs:
        connected=[g for g in groups if g.intersection(pair)]
        for group in connected:pair.update(group);groups.remove(group)
        groups.append(pair)
    return [sorted(g) for g in groups]

def joint_window(plan,ids,reference,new_id):
    # 连续转调识别与不确定调性保护：只合并真实支持的相邻窗，原文保持，不跨未支持语言或无窗口段。
    jobs={j['job_id']:j for j in plan['jobs']};span=[j for j in plan['jobs'] if min(ids)<=j['job_id']<=max(ids)]
    if not span or any(j['status']!='candidate_window' for j in span):raise ValueError('冲突字界跨未支持句窗，需复核，不能伪造联合时间。')
    lines=sorted({i for j in span for i in j['line_indices']})
    return {'job_id':new_id,'line_indices':lines,'reference_text':'\n'.join(reference['lines'][i] for i in lines),'start_seconds':min(j['start_seconds'] for j in span),'end_seconds':max(j['end_seconds'] for j in span),'status':'candidate_window','warnings':['cross_phrase_boundary_realignment'],'original_job_ids':[j['job_id'] for j in span],'window_method':'real_tifa_joint_boundary_recovery'}

def recover_boundaries(chars,plan,reference,output,phrase_reports,aligner,rejector):
    # 连续转调识别与不确定调性保护：最多四组一次重预测，缓存保留真实裁剪哈希/音素文件。
    groups=conflicting_groups(chars)
    if len(groups)>4:raise ValueError('跨句字界冲突超过有界恢复范围，需要复核。')
    if not groups:return chars,phrase_reports,{'status':'not_needed','groups':[]}
    import soundfile as sf
    import torch
    result=copy.deepcopy(chars);reports=list(phrase_reports);source=reference['source'];info=sf.info(source['path']);offset=source.get('offset_seconds',0.);recovery=[]
    if file_sha256(Path(source['path']))!=source['sha256']:raise ValueError('联合字界恢复的原音频SHA失配。')
    for ids in groups:
        new_id=max((d['job_id'] for d in reports),default=-1)+1;job=joint_window(plan,ids,reference,new_id);phase=time.perf_counter()
        first=max(0,math.floor((job['start_seconds']-offset)*info.samplerate));last=min(info.frames,math.ceil((job['end_seconds']-offset)*info.samplerate));crop=output/'crops'/f'boundary_{new_id:03d}.wav';crop.parent.mkdir(parents=True,exist_ok=True)
        audio,rate=sf.read(source['path'],start=first,stop=last,dtype='float32',always_2d=True);sf.write(crop,audio,rate,subtype='FLOAT')
        local={**reference,'text':job['reference_text'],'lines':[reference['lines'][i] for i in job['line_indices']],'source':{'path':str(crop),'sha256':file_sha256(crop),'sample_rate':rate,'channels':info.channels,'duration_seconds':len(audio)/rate,'offset_seconds':first/rate+offset}}
        detail={'job_id':new_id,'line_indices':job['line_indices'],'timings':{'crop_decode_write_seconds':time.perf_counter()-phase},'crop':local['source'],'original_source':source,'anchor_evidence':job,'reference_kind':reference['reference_kind']};phrase_output=output/'phrases'/f'boundary_{new_id:03d}'
        values=rejector(aligner(local,phrase_output,detail),local,detail);destinations=[c for c in result if c['line_index'] in job['line_indices']]
        if [c['text'] for c in destinations]!=[c['text'] for c in values]:raise ValueError('联合重预测原文序列不一致。')
        for dest,value in zip(destinations,values):
            identity,line=dest['index'],dest['line_index'];dest.update(value);dest.update(index=identity,line_index=line,phrase_job_id=new_id,group_id=f"boundary_{new_id:03d}_{value.get('group_id')}",alignment_scope='joint_phrase_boundary_recovery',warnings=list(dict.fromkeys(value['warnings']+job['warnings'])))
            if dest['start_seconds'] is not None:dest['method']='tifa_joint_phrase_texts_tier'
        detail.update(status='real_tifa_prediction_completed',total_characters=len(values),characters_with_time=sum(v['start_seconds'] is not None for v in values),wall_seconds=time.perf_counter()-phase,boundary_recovery=True)
        save_json(phrase_output/'report.json',detail);reports.append(detail);recovery.append({'original_job_ids':ids,'new_job_id':new_id,'line_indices':job['line_indices'],'characters_with_time':detail['characters_with_time']});save_json(output/'phrase_reports.partial.json',{'source':source,'phrases':reports})
        gc.collect();torch.cuda.empty_cache()
    remaining=conflicting_groups(result)
    if remaining:raise ValueError('真实联合预测后仍有跨句冲突，不能人为顺排字界。')
    return result,reports,{'status':'real_tifa_joint_predictions_completed','groups':recovery,'source_times_manually_shifted':False}
