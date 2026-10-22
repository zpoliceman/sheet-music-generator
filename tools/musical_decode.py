"""自动音乐解码改造：复核完整声学音段，再软关联歌词；参考谱不参与生成。"""
# 自动音乐解码改造：新增通用音乐解码层，原始分析只读。
from __future__ import annotations
import argparse, bisect, copy, html, math, statistics, time
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from scipy.ndimage import median_filter
import score_export as score
# 字音归属修复：修改版本，原值保留。
# VERSION = 1
# 第四首《日落大道》男声跨歌曲验证：修改音乐层版本，新增不伪造字界的部分稿。
# VERSION = 2
# 第四首《日落大道》男声跨歌曲验证：修改版本，新增实际人声调式及有重复唱句证据的转调。
# VERSION = 3
# 第四首《日落大道》男声跨歌曲验证：修改版本，新增可靠短平台与字内主音选择。
# VERSION = 4
# 第四首《日落大道》男声跨歌曲验证：修改版本，新增字外声段明确无挂词保留。
# VERSION = 5
# 大调约束与强拍先验：修改记谱版本，原值保留。
# VERSION = 6
# 调外音宁缺毋滥：修改版本，原v7保留。
# VERSION = 7
# 连续转调识别与不确定调性保护：修改音乐解码版本，原v8保留。
# VERSION = 8
VERSION = 9
PARAMETERS = {"stable_core_seconds": .075, "center_error_semitones": .32,
              "local_agreement_fraction": .70, "soft_boundary_seconds": .32,
              "ordinary_grid_ticks": 60, "grace_max_quarters": .40}

# 连续转调识别与不确定调性保护：新增平坦音高分布的有限分数，避免NaN伪装成调性证据。
def tonal_profile_correlation(histogram,profile):
    if float(np.std(histogram))<1e-10:return 0.
    value=float(np.corrcoef(histogram,profile)[0,1])
    return value if math.isfinite(value) else 0.

# 自动音乐解码改造：新增人声调性候选，源调/目标调独立保存，不强制吸附音高。
def infer_vocal_key(notes):
    histogram = np.zeros(12)
    for n in notes:
        if not n.get("is_rest") and n.get("pitch_midi", 0) > 0:
            histogram[int(n["pitch_midi"]) % 12] += (n["end_seconds"]-n["start_seconds"])*max(.05,n.get("confidence") or .3)
    if histogram.sum() == 0:
        raise ValueError("无人声音高证据，不能推断调性。")
    profiles = {"major": [6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88],
                "minor": [6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]}
    names = ["C","Db","D","Eb","E","F","F#","G","Ab","A","Bb","B"]
    candidates = []
    # 大调约束与强拍先验：修改初版候选范围，仅推断大调；小调评分仍记录作支持范围提醒。
    # for mode,profile in profiles.items():
    for mode,profile in [("major",profiles["major"])]:
        for pc,name in enumerate(names):
            label=name+":"+mode
            try: score.key_definition(label)
            except ValueError: continue
            # 连续转调识别与不确定调性保护：修改平坦分布评分，原表达式保留。
            # candidates.append({"key":label,"correlation":float(np.corrcoef(histogram,np.roll(profile,pc))[0,1])})
            candidates.append({"key":label,"correlation":tonal_profile_correlation(histogram,np.roll(profile,pc))})
    candidates.sort(key=lambda r:-r["correlation"])
    # 大调约束与强拍先验：新增未支持小调的诊断，不能将大调限定说成所有歌曲均为大调。
    # 连续转调识别与不确定调性保护：修改小调诊断评分的NaN处理，原表达式保留。
    # minor_best=max(float(np.corrcoef(histogram,np.roll(profiles["minor"],pc))[0,1]) for pc in range(12))
    minor_best=max(tonal_profile_correlation(histogram,np.roll(profiles["minor"],pc)) for pc in range(12))
    # 大调约束与强拍先验：保留原返回首行，新增支持范围字段不改变其余证据。
    # return {"selected":candidates[0]["key"],"candidates":candidates[:8],"method":"duration_and_support_weighted_vocal_profile",
    return {"supported_modes":["major"],"unsupported_minor_may_fit_better":minor_best>candidates[0]["correlation"]+.05,
            "selected":candidates[0]["key"],"candidates":candidates[:8],"method":"duration_and_support_weighted_vocal_profile",
            "margin":candidates[0]["correlation"]-candidates[1]["correlation"],"confidence_kind":"uncalibrated_evidence_not_accuracy",
            "modulation_not_modeled":True,"pitch_class_weights":histogram.tolist(),"requires_review":True}

# 自动音乐解码改造：新增连续f0平台及独立YIN复核，过渡区不直接作为新主音。
class AcousticEvidence:
    def __init__(self,analysis,verify_audio=True):
        rows=analysis.get("pitch_frames",[])
        self.times=np.array([r["time_seconds"] for r in rows])
        f0=np.array([r["f0_hz"] for r in rows])
        self.midi=np.where(f0>0,69+12*np.log2(np.maximum(f0,1)/440),np.nan)
        self.step=float(analysis["configuration"].get("frame_step_seconds",.005333333333))
        self.audio=None
        if verify_audio:
            import soundfile as sf
            path=Path(analysis["source"]["path"])
            if not path.is_file() or score.sha256(path)!=analysis["source"]["sha256"]:
                raise ValueError("复核人声不存在或SHA不一致。")
            self.audio,self.sr=sf.read(path,dtype="float32",always_2d=True)
            self.audio=self.audio.mean(axis=1)

    def cores(self,start,end):
        mask=(self.times>=start)&(self.times<end)
        times,values=self.times[mask],self.midi[mask]
        if not len(values): return []
        labels=np.rint(median_filter(np.nan_to_num(values,nan=-999),size=5,mode="nearest")).astype(int)
        boundaries=np.r_[0,np.flatnonzero(np.diff(labels))+1,len(labels)]
        cores=[]
        for a,b in zip(boundaries[:-1],boundaries[1:]):
            pitch=int(labels[a]);actual=values[a:b]
            if not 20<=pitch<=100 or (b-a)*self.step<PARAMETERS["stable_core_seconds"]: continue
            median=float(np.nanmedian(actual));support=float(np.mean(np.abs(actual-pitch)<=.45))
            if abs(median-pitch)>PARAMETERS["center_error_semitones"] or support<.75: continue
            core={"start_seconds":float(times[a]),"end_seconds":float(times[b-1]+self.step),"pitch_midi":pitch,"support":support,"median_midi":median}
            if cores and cores[-1]["pitch_midi"]==pitch and core["start_seconds"]-cores[-1]["end_seconds"]<.10:
                cores[-1]["end_seconds"]=core["end_seconds"]
            else: cores.append(core)
        return cores

    def independent(self,cores):
        if self.audio is None: return [{**c,"independent_agreement":None} for c in cores]
        import librosa
        from scipy.signal import resample_poly
        start=max(0,cores[0]["start_seconds"]-.12);end=min(len(self.audio)/self.sr,cores[-1]["end_seconds"]+.12)
        waveform=self.audio[round(start*self.sr):round(end*self.sr)]
        divisor=math.gcd(self.sr,16000)
        waveform=resample_poly(waveform,16000//divisor,self.sr//divisor)
        f0=librosa.yin(waveform,fmin=90,fmax=1000,sr=16000,frame_length=1024,hop_length=64)
        times=start+np.arange(len(f0))*.004;midi=69+12*np.log2(np.maximum(f0,1)/440)
        result=[]
        for core in cores:
            selected=(times>=core["start_seconds"])&(times<core["end_seconds"])
            agreement=float(np.mean(np.abs(midi[selected]-core["pitch_midi"])<.55)) if selected.any() else 0
            result.append({**core,"independent_agreement":agreement})
        return result

# 自动音乐解码改造：新增局部重分段，失败候选保留在复核层。
def acoustic_candidates(analysis,verify_audio=True):
    evidence=AcousticEvidence(analysis,verify_audio);notes=[];reviews=[]
    for raw in analysis["notes"]:
        if raw.get("is_rest") or raw.get("pitch_midi",0)<=0: continue
        note={"id":str(raw["id"]),"source_note_id":str(raw["id"]),"start_seconds":float(raw["start_seconds"]),"end_seconds":float(raw["end_seconds"]),
              "pitch_midi":int(raw["pitch_midi"]),"confidence":raw.get("confidence"),"review_flags":list(raw.get("review_flags",[])),"boundary_source":"refined_acoustic_note"}
        cores=evidence.cores(note["start_seconds"],note["end_seconds"])
        challenged=raw.get("quality",{}).get("pitch_support_fraction",1)<.65 or any(c["pitch_midi"]!=note["pitch_midi"] for c in cores)
        if challenged and cores:
            cores=evidence.independent(cores)
            accepted=[c for c in cores if c["independent_agreement"] is None or c["independent_agreement"]>=PARAMETERS["local_agreement_fraction"]]
            # 自动音乐解码改造：新增保留原音时的独立支持证据，供倚音分类而非长度替代。
            note["independent_pitch_support"]=max((c["independent_agreement"] or 0 for c in cores if c["pitch_midi"]==note["pitch_midi"]),default=0)
            covered=sum(c["end_seconds"]-c["start_seconds"] for c in accepted)/(note["end_seconds"]-note["start_seconds"])
            changed=bool(accepted and covered>=.42 and any(c["pitch_midi"]!=note["pitch_midi"] for c in accepted))
            reviews.append({"type":"local_pitch_recheck","source_note_id":note["id"],"start_seconds":note["start_seconds"],"end_seconds":note["end_seconds"],
                            "original_pitch_midi":note["pitch_midi"],"candidates":cores,"action":"stable_core_resegmented" if changed else "original_retained","requires_review":True})
            if changed:
                cuts=[note["start_seconds"]]+[(a["end_seconds"]+b["start_seconds"])/2 for a,b in zip(accepted,accepted[1:])]+[note["end_seconds"]]
                for i,core in enumerate(accepted):
                    notes.append({**note,"id":note["id"]+f".f0{i}","start_seconds":cuts[i],"end_seconds":cuts[i+1],"pitch_midi":core["pitch_midi"],
                                  "confidence":core["support"],"stable_core":core,"boundary_source":"rmvpe_stable_core_independent_yin"})
                continue
        # 第四首《日落大道》男声跨歌曲验证：新增低支持原音里的可靠短平台保留；不因占原音不到42%就吞掉主音。
        supported=[c for c in cores if c['pitch_midi']!=note['pitch_midi'] and c['end_seconds']-c['start_seconds']>=.10
                   and c.get('independent_agreement') is not None and c['independent_agreement']>=.80 and c['support']>=.85]
        if (raw.get('confidence') or 0)<.50 and raw.get('quality',{}).get('pitch_support_fraction',1)<.50 and supported:
            cursor=note['start_seconds'];subpieces=[]
            for i,core in enumerate(supported):
                if core['start_seconds']>cursor+1e-6:
                    subpieces.append({**note,'id':note['id']+f'.transition{i}','start_seconds':cursor,'end_seconds':core['start_seconds'],
                                      'stable_duration_seconds':0.,'review_flags':note['review_flags']+['low_support_transition_preserved']})
                right=note['end_seconds'] if note['end_seconds']-core['end_seconds']<=.04 else core['end_seconds']
                subpieces.append({**note,'id':note['id']+f'.supported{i}','start_seconds':core['start_seconds'],'end_seconds':right,
                                  'pitch_midi':core['pitch_midi'],'confidence':core['support'],'stable_core':core,
                                  'stable_duration_seconds':core['end_seconds']-core['start_seconds'],
                                  'independent_pitch_support':core['independent_agreement'],'boundary_source':'supported_short_core_transition_preserved'})
                cursor=right
            if cursor<note['end_seconds']-1e-6:
                subpieces.append({**note,'id':note['id']+'.transition_end','start_seconds':cursor,'stable_duration_seconds':0.,
                                  'review_flags':note['review_flags']+['low_support_transition_preserved']})
            notes.extend(subpieces)
            reviews.append({'type':'supported_short_core_preserved','source_note_id':note['id'],'start_seconds':note['start_seconds'],
                            'end_seconds':note['end_seconds'],'original_pitch_midi':note['pitch_midi'],'candidates':supported,
                            'action':'stable_core_and_uncertain_transition_both_preserved','requires_review':True})
            continue
        note["stable_duration_seconds"]=sum(c["end_seconds"]-c["start_seconds"] for c in cores if c["pitch_midi"]==note["pitch_midi"])
        notes.append(note)
    if any(a["end_seconds"]>b["start_seconds"]+1e-5 for a,b in zip(notes,notes[1:])):
        raise ValueError("源声学音符重叠，不能静默量化为单声部。")
    # 自动音乐解码改造：修改，歌词关联前不合并同高原始重发，避免快节奏两字变成一音；旧实现保留。
    # # 自动音乐解码改造：新增同音接缝合并，不跨明显静音。
    # merged=[]
    # for note in notes:
    # if merged and merged[-1]["pitch_midi"]==note["pitch_midi"] and abs(merged[-1]["end_seconds"]-note["start_seconds"])<.015:
    # prev=merged[-1];prev.setdefault("source_note_ids",[prev["source_note_id"]]).append(note["source_note_id"])
    # prev["end_seconds"]=note["end_seconds"]
    # prev["stable_duration_seconds"]=prev.get("stable_duration_seconds",0)+note.get("stable_duration_seconds",0)
    # else: merged.append(note)
    # return merged,reviews
    return notes,reviews

# 自动音乐解码改造：新增单调软关联，整段主音优先；只为完全包含的同音多字生成重起。
# 字音归属修复：修改，旧锚点/贪心分配注释保留，改为音素驱动的全音段联合路径。
# def soft_lyrics(notes,lyric_data):
#     chars=copy.deepcopy(lyric_data.get("characters",[]));chars.sort(key=lambda c:c["index"])
#     if not chars: return [dict(n,lyric_index=None,role="main",anchor=True) for n in notes],chars,[]
#     if any(c.get("start_seconds") is None or c.get("end_seconds") is None for c in chars):
#         raise ValueError("存在未对齐歌词，不能伪造字音。")
#     expanded=[]
#     for note in notes:
#         # 自动音乐解码改造：修改，允许长同音在字界重起而不丢掉前字落音；原实现注释保留。
#         # contained=[c for c in chars if c["start_seconds"]>=note["start_seconds"]-.04 and c["end_seconds"]<=note["end_seconds"]+.04]
#         # 自动音乐解码改造：修改，同音重起必须有真实正长度交叠，避免边界扰动产生零长度重起；原行注释保留。
#         # contained=[c for c in chars if c["start_seconds"]>=note["start_seconds"]-.04 and c["end_seconds"]<=note["end_seconds"]+.04]
#         contained=[c for c in chars if c["start_seconds"]>=note["start_seconds"]-.04 and c["end_seconds"]<=note["end_seconds"]+.04
#                    and min(c["end_seconds"],note["end_seconds"])-max(c["start_seconds"],note["start_seconds"])>=.06]
#         # 自动音乐解码改造：新增长同音横跨字界的重起候选，短平台仍保持完整。
#         if note["end_seconds"]-note["start_seconds"] >= .80:
#             spanning=[c for c in chars if min(c["end_seconds"],note["end_seconds"])-max(c["start_seconds"],note["start_seconds"]) >= .12]
#             if len(spanning)>len(contained):
#                 contained=spanning
#         # 自动音乐解码改造：修改，有正长度逐字证据即可重起，不用400ms门槛删掉快歌同音字；原行保留。
#         # if len(contained)>=2 and note["end_seconds"]-note["start_seconds"]>.40:
#         if len(contained)>=2:
#             cuts=[note["start_seconds"]]+[(a["end_seconds"]+b["start_seconds"])/2 for a,b in zip(contained,contained[1:])]+[note["end_seconds"]]
#             for i in range(len(contained)):
#                 expanded.append(dict(note,id=note["id"]+f".repeat{i}",start_seconds=cuts[i],end_seconds=cuts[i+1],boundary_source="same_pitch_character_reattack"))
#         else: expanded.append(copy.deepcopy(note))
#     notes=expanded;count=len(chars);size=len(notes)
#     if size<count: raise ValueError("候选少于歌词字数，需复核声学分段。")
#     costs=np.full((count,size),np.inf)
#     for ci,char in enumerate(chars):
#         cs,ce=char["start_seconds"],char["end_seconds"];center=(cs+ce)/2
#         for ni,note in enumerate(notes):
#             ns,ne=note["start_seconds"],note["end_seconds"];nc=(ns+ne)/2
#             if max(cs-ne,ns-ce,0)>PARAMETERS["soft_boundary_seconds"]: continue
#             overlap=max(0,min(ce,ne)-max(cs,ns))/max(.06,min(ce-cs,ne-ns))
#             salience=max(.06,note.get("stable_duration_seconds",ne-ns))*max(.15,note.get("confidence") or .3)**2
#             costs[ci,ni]=((nc-center)/(.20+.4*(ce-cs)))**2-.65*overlap-.45*math.log(max(.025,salience)/.2)
#     # 自动音乐解码改造：新增动态规划保护字序和音序，短主音不因先量化而丢失。
#     dp=costs[0].copy();parents=np.full((count,size),-1,dtype=int)
#     for ci in range(1,count):
#         best=np.inf;at=-1;current=np.full(size,np.inf)
#         for ni in range(size):
#             if ni and dp[ni-1]<best: best,at=dp[ni-1],ni-1
#             current[ni]=costs[ci,ni]+best;parents[ci,ni]=at
#         dp=current
#     last=int(np.argmin(dp))
#     if not np.isfinite(dp[last]): raise ValueError("歌词无法单调匹配声学候选，需复核句窗。")
#     anchors=[last]
#     for ci in range(count-1,0,-1): last=int(parents[ci,last]);anchors.append(last)
#     anchors.reverse();anchor_map=dict(zip(anchors,range(count)));issues=[];pieces=[]
#     for ni,note in enumerate(notes):
#         if ni in anchor_map: ci=anchor_map[ni];role="main"
#         else:
#             right=bisect.bisect_left(anchors,ni)
#             possible=[v for v in (right-1,right) if 0<=v<count and np.isfinite(costs[v,ni])]
#             ci=min(possible,key=lambda v:costs[v,ni]) if possible else None
#             role="detail" if ci is not None else "unassigned"
#         piece=dict(note,lyric_index=chars[ci]["index"] if ci is not None else None,role=role,anchor=role=="main")
#         if ci is not None:
#             piece["alignment_cost"]=float(costs[ci,ni])
#             if costs[ci,ni]>1: issues.append({"type":"soft_alignment_uncertain","piece_id":note["id"],"character_index":chars[ci]["index"],"cost":float(costs[ci,ni]),"requires_review":True})
#         piece["line_index"]=chars[ci].get("line_index") if ci is not None else None
#         pieces.append(piece)
#     previous=None
#     for p in pieces:
#         if p["lyric_index"] is not None:
#             if previous is not None and p["lyric_index"]<previous: p["lyric_index"]=previous
#             previous=p["lyric_index"]
#     return pieces,chars,issues
# 

def soft_lyrics(notes,lyric_data,analysis=None):
    # 字音归属修复：新增统一入口，无音素时明确回退并保留复核标记。
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # from word_note_alignment import align_notes
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    from english_lyrics import align_multilingual_notes as align_notes
    # 第四首《日落大道》男声跨歌曲验证：修改只关联有效字，未定位字保留原文/候选时间；旧直接失败入口保留。
    # return align_notes(notes,lyric_data,analysis)
    chars=copy.deepcopy(lyric_data.get("characters",[]))
    valid=[c for c in chars if c.get("start_seconds") is not None and c.get("end_seconds") is not None and c["end_seconds"]>c["start_seconds"]]
    if len(valid)==len(chars):
        return align_notes(notes,lyric_data,analysis)
    if not valid:
        raise ValueError("没有可靠定位的歌词，不能伪造字音。")
    partial=copy.deepcopy(lyric_data);partial["characters"]=valid
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # pieces,_,issues=align_notes(notes,partial,analysis)
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    pieces,aligned,issues=align_notes(notes,partial,analysis)
    syllables_by_index={c["index"]:c["english_syllables"] for c in aligned if "english_syllables" in c}
    for c in chars:
        if c["index"] in syllables_by_index:c["english_syllables"]=syllables_by_index[c["index"]]
    # 第四首《日落大道》男声跨歌曲验证：新增只保留未定位字上下文空隙里的完整音段为无挂词，空隙不作为字界。
    for char in chars:
        if char in valid:
            continue
        before=next((c for c in reversed(valid) if c["index"]<char["index"]),None)
        after=next((c for c in valid if c["index"]>char["index"]),None)
        if before is None or after is None:
            continue
        left,right=before["end_seconds"],after["start_seconds"]
        for piece in pieces:
            if left<=piece["start_seconds"] and piece["end_seconds"]<=right and not any(min(piece["end_seconds"],c["end_seconds"])>max(piece["start_seconds"],c["start_seconds"])+1e-6 for c in valid):
                piece.update(lyric_index=None,line_index=None,anchor=False,role="unassigned")
                piece.setdefault("review_flags",[]).append("unassigned_near_unaligned_lyric")

    for char in chars:
        if char not in valid:
            char.setdefault("warnings",[]).append("unmapped_lyric_retained_without_fabricated_time")
            issues.append({"type":"lyric_unaligned","character_index":char["index"],"text":char["text"],"line_index":char.get("line_index"),
                           "candidate_start_seconds":char.get("candidate_start_seconds"),"candidate_end_seconds":char.get("candidate_end_seconds"),"requires_review":True})
    return pieces,chars,issues

# 第四首《日落大道》男声跨歌曲验证：新增全在真实字界外且有字内替代的音段释放归属，不删音或补时间。
def release_outside_lyric_segments(pieces,characters,issues):
    valid=[c for c in characters if c.get('start_seconds') is not None and c.get('end_seconds') is not None]
    for char in valid:
        group=[n for n in pieces if n.get('lyric_index')==char['index']]
        inside=[n for n in group if min(n['end_seconds'],char['end_seconds'])-max(n['start_seconds'],char['start_seconds'])>=.025]
        if not inside:continue
        for n in group:
            if n in inside:continue
            if any(min(n['end_seconds'],c['end_seconds']+.025)>max(n['start_seconds'],c['start_seconds']-.025) for c in valid):continue
            n.update(lyric_index=None,line_index=None,anchor=False,role='unassigned')
            n.setdefault('review_flags',[]).append('out_of_lyric_interval_retained_unassigned')
            issues.append({'type':'word_ownership_no_overlap_unassigned','character_index':char['index'],
                           'piece_id':n['id'],'start_seconds':n['start_seconds'],'end_seconds':n['end_seconds'],
                           'source_note_id':n.get('source_note_id',n['id']),'alternatives':[],
                           'reason':'字外且同字已有真实交叠音段；不将器乐/弱声候选强塞给字。','requires_review':True})
        kept=[n for n in group if n.get('lyric_index')==char['index']]
        if kept and not any(n.get('anchor') for n in kept):
            min(inside,key=lambda n:n.get('word_alignment',{}).get('cost',0))['anchor']=True
    return pieces,issues

# 自动音乐解码改造：新增字音关联后同字同高连续段归并；跨字同高保留独立重起。
def coalesce_same_character(pieces):
    result=[]
    for original in pieces:
        note=copy.deepcopy(original)
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # if result and note.get("lyric_index") is not None and result[-1].get("lyric_index")==note["lyric_index"] and result[-1]["pitch_midi"]==note["pitch_midi"] and abs(result[-1]["end_seconds"]-note["start_seconds"])<=.015:
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        if result and note.get("lyric_index") is not None and result[-1].get("lyric_index")==note["lyric_index"] and result[-1].get("english_syllable_index")==note.get("english_syllable_index") and result[-1]["pitch_midi"]==note["pitch_midi"] and abs(result[-1]["end_seconds"]-note["start_seconds"])<=.015:
            previous=result[-1]
            left=previous["end_seconds"]-previous["start_seconds"]
            right=note["end_seconds"]-note["start_seconds"]
            previous["confidence"]=((previous.get("confidence") or .3)*left+(note.get("confidence") or .3)*right)/(left+right)
            previous["end_seconds"]=note["end_seconds"]
            previous["anchor"]=previous.get("anchor") or note.get("anchor")
            previous["stable_duration_seconds"]=previous.get("stable_duration_seconds",0)+note.get("stable_duration_seconds",0)
            previous["independent_pitch_support"]=max(previous.get("independent_pitch_support") or 0,note.get("independent_pitch_support") or 0)
            previous.setdefault("source_note_ids",[previous["source_note_id"]]).extend(note.get("source_note_ids",[note["source_note_id"]]))
        else:
            result.append(note)
    return result

# 自动音乐解码改造：新增稳健拍格，尾部异常拍点不继续加速整曲。
def robust_timing(analysis,pieces,characters,tempo=None,meter=None,beat_origin=None):
    beats=np.array(analysis["beat_times_seconds"],dtype=float);indices=np.arange(len(beats),dtype=float)
    keep=indices<max(4,int(.85*len(beats)));slope,intercept=np.polyfit(indices[keep],beats[keep],1)
    for _ in range(3):
        good=keep&(np.abs(beats-(intercept+slope*indices))<.10)
        if good.sum()>=4: slope,intercept=np.polyfit(indices[good],beats[good],1)
    inferred=60/slope;bpm=float(tempo) if tempo else (float(round(inferred)) if abs(inferred-round(inferred))<.45 else inferred)
    if not 20<=bpm<=300: raise ValueError("拍速必须为20–300BPM。")
    period=60/bpm;mains=[n for n in pieces if n.get("anchor")]
    def cost(offset):
        values=[(n["start_seconds"]-offset)/period for n in mains]
        return float(np.mean(np.minimum([abs(q-round(q*2)/2) for q in values],.18))) if values else 0
    fractional=float(min(np.linspace(intercept-period/4,intercept+period/4,101),key=cost))
    numerator,denominator=map(int,(meter or analysis["meter"]["selected"]).split("/"))
    if numerator<=0 or denominator not in (2,4,8,16): raise ValueError("不支持的拍号。")
    bar=numerator*4/denominator
    long_notes=[n for n in mains if n["end_seconds"]-n["start_seconds"]>period*.9]
    ranked=sorted([{"phase":p,"weight":sum((n["end_seconds"]-n["start_seconds"])*math.cos(2*math.pi*((n["start_seconds"]-fractional)/period-p)/bar) for n in long_notes)} for p in range(max(1,round(bar)))],key=lambda r:-r["weight"])
    # 自动音乐解码改造：新增重复弱起句型投票，短首音/长次音提示小节末弱起；需至少三句一致证据。
    phrase_notes={}
    for n in mains:
        if n.get("line_index") is not None:
            phrase_notes.setdefault(n["line_index"],[]).append(n)
    pickups=[]
    for phrase in phrase_notes.values():
        if len(phrase)>=2:
            first,second=phrase[:2]
            d1=(first["end_seconds"]-first["start_seconds"])/period
            d2=(second["end_seconds"]-second["start_seconds"])/period
            if .20<=d1<=.80 and 1.0<=d2<=2.2:
                pickups.append(first["start_seconds"])
    if len(pickups)>=3 and denominator==4:
        total_weight=sum(n["end_seconds"]-n["start_seconds"] for n in long_notes) or 1
        for candidate in ranked:
            candidate["long_note_weight"]=candidate["weight"]/total_weight
            candidate["pickup_weight"]=float(np.mean([math.cos(2*math.pi*((onset-fractional)/period-candidate["phase"]-(bar-1))/bar) for onset in pickups]))
            candidate["weight"]=candidate["long_note_weight"]+candidate["pickup_weight"]
        ranked.sort(key=lambda r:-r["weight"])
    # 自动音乐解码改造：修改，综合重复句弱起与长音候选；原相位选择注释保留。
    # origin=float(beat_origin) if beat_origin is not None else fractional+ranked[0]["phase"]*period
    origin=float(beat_origin) if beat_origin is not None else fractional+ranked[0]["phase"]*period
    mapping=score.TempoMap([{"seconds":origin,"quarter":0},{"seconds":origin+period,"quarter":1}])
    start=math.floor(mapping.seconds_to_quarters(0)/bar)*bar
    timing={"meter":[numerator,denominator],"meter_source":"user_override" if meter else analysis["meter"],"tempo_source":"user_override" if tempo else "robust_inlier_beat_fit",
            "beat_origin_seconds":origin,"beat_origin_source":"user_override" if beat_origin is not None else "vocal_onset_and_long_note_phase_candidate",
            "score_start_quarter":start,"score_start_seconds":mapping.quarters_to_seconds(start),"knots":mapping.knots,
            "pickup_pattern_count":len(pickups),"bar_phase_method":"uncalibrated_repeated_pickup_and_long_note_prior",
            "steady_tempo_bpm":bpm,"unrounded_tempo_bpm":inferred,"bar_phase_candidates":ranked,"requires_confirmation":True,
            "coda_ritardando":"not_inferred_from_unreliable_tail_beats","rejected_beat_count":int(np.sum(np.abs(beats-(intercept+slope*indices))>.10))}
    # 小节划分与拍速层级纠错：修改，原无层级复核返回保留；拟合稳定性不等于四分拍单位正确。
    # return mapping,timing
    from metrical_timing import resolve_timing
    return resolve_timing(analysis,timing,explicit_tempo=tempo is not None)

# 自动音乐解码改造：新增主音/倚音/转音分类；短、弱拍或量化零值均不充分构成倚音。
# 自动音乐解码改造：修改，分类与归并两阶段处理，低置信不构成删除长音的充分条件；原函数注释保留。
# # 第四首《日落大道》男声跨歌曲验证：修改分类入口接收真实字时间，旧签名保留。
# def classify(pieces,mapping):
# def classify(pieces,mapping,characters=None):
#     output=[];reviews=[];groups=[]
#     for p in pieces:
#         if groups and groups[-1][0]["lyric_index"]==p["lyric_index"]: groups[-1].append(copy.deepcopy(p))
#         else: groups.append([copy.deepcopy(p)])
#     for group in groups:
#         mains=[p for p in group if p.get("anchor")]
#         if not mains: output.extend(dict(p,role="main",grace=False) for p in group);continue
#         # 自动音乐解码改造：修改，完整字音组内重新判定主音，不采用旧最长残片规则；原实现注释保留。
#         # anchor=mains[0];anchor_position=group.index(anchor)
#         # 自动音乐解码改造：新增稳定支持优先的主音排名，避免最长过渡段抢主音。
#         anchor=max(group,key=lambda n:max(.1,n.get("confidence") or .3)**2 * math.sqrt(n["end_seconds"]-n["start_seconds"]))
#         anchor_position=group.index(anchor)
#         has_turn_chain=len(group)>=3 and len({n["pitch_midi"] for n in group})>=3
#         for n in group:
#             n["anchor"] = n is anchor
#         for i,p in enumerate(group):
#             duration=mapping.seconds_to_quarters(p["end_seconds"])-mapping.seconds_to_quarters(p["start_seconds"])
#             confidence=p.get("confidence") or 0;p["grace"]=False
#             if p is anchor: p["role"]="main"
#             elif duration<.14 or confidence<.38:
#                 reviews.append({"type":"detail_merged_to_neighbor","candidate":copy.deepcopy(p),"anchor_id":anchor["id"],"requires_review":True})
#                 p["discarded"]=True
#                 # 自动音乐解码改造：新增归并到时间上邻接的保留音，不跨越别的转音。
#                 if i+1<len(group): group[i+1]["start_seconds"]=p["start_seconds"]
#                 elif i: group[i-1]["end_seconds"]=p["end_seconds"]
#             # 自动音乐解码改造：修改，连续多音转音链保留真实时值，不整体缩成倚音；原实现注释保留。
#             # elif i<anchor_position and duration<PARAMETERS["grace_max_quarters"] and abs(p["pitch_midi"]-anchor["pitch_midi"])<=3:
#             elif not has_turn_chain and i<anchor_position and duration<PARAMETERS["grace_max_quarters"] and abs(p["pitch_midi"]-anchor["pitch_midi"])<=3:
#                 p.update(role="grace",grace=True,anchor_id=anchor["id"],grace_steal_from="following")
#             else: p["role"]="turn"
#         kept=[p for p in group if not p.get("discarded")]
#         for a,b in zip(kept,kept[1:]):
#             if a["end_seconds"]>b["start_seconds"]: a["end_seconds"]=b["start_seconds"]
#         output.extend(kept)
#     return output,reviews
# 第四首《日落大道》男声跨歌曲验证：修改分类入口接收真实字时间，旧签名保留。
# def classify(pieces,mapping):
def classify(pieces,mapping,characters=None):
    output=[];reviews=[];groups=[]
    # 第四首《日落大道》男声跨歌曲验证：新增真实字区间索引，不凭相邻字中点生成时间。
    char_map={c["index"]:c for c in characters or []}
    for piece in pieces:
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # if groups and groups[-1][0]["lyric_index"]==piece["lyric_index"]:
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        if groups and groups[-1][0]["lyric_index"]==piece["lyric_index"] and groups[-1][0].get("english_syllable_index")==piece.get("english_syllable_index"):
            groups[-1].append(copy.deepcopy(piece))
        else:
            groups.append([copy.deepcopy(piece)])
    for group in groups:
        if not any(p.get("anchor") for p in group):
            output.extend(dict(p,role="main",grace=False) for p in group)
            continue
        # 第四首《日落大道》男声跨歌曲验证：修改主音候选先要求真实字界内有声音，保留旧只比置信/长度规则。
        # anchor=max(group,key=lambda n:max(.1,n.get('confidence') or .3)**2*math.sqrt(n['end_seconds']-n['start_seconds']))
        candidates=group;char=char_map.get(group[0]['lyric_index'])
        if char and char.get('start_seconds') is not None and char.get('end_seconds') is not None:
            overlapping=[n for n in group if min(n['end_seconds'],char['end_seconds'])-max(n['start_seconds'],char['start_seconds'])>=.025]
            if overlapping:candidates=overlapping
        anchor=max(candidates,key=lambda n:max(.1,n.get('confidence') or .3)**2*math.sqrt(n['end_seconds']-n['start_seconds']))
        anchor_position=group.index(anchor)
        has_turn_chain=len(group)>=3 and len({n["pitch_midi"] for n in group})>=3
        # 自动音乐解码改造：新增先分类，不在判断期间扩大或缩短邻音时间。
        for i,p in enumerate(group):
            seconds=p["end_seconds"]-p["start_seconds"]
            quarters=mapping.seconds_to_quarters(p["end_seconds"])-mapping.seconds_to_quarters(p["start_seconds"])
            confidence=p.get("confidence") or 0
            stable_fraction=p.get("stable_duration_seconds",0)/max(.001,seconds)
            independent=p.get("independent_pitch_support") or 0
            reliable=confidence>=.70 or stable_fraction>=.60 or independent>=.70
            p.update(anchor=p is anchor,grace=False)
            if p is anchor:
                p["role"]="main"
            elif seconds<.075 and quarters<.14 and not reliable:
                p["discarded"]=True
                reviews.append({"type":"detail_merged_to_neighbor","candidate":copy.deepcopy(p),"anchor_id":anchor["id"],"requires_review":True})
            elif not has_turn_chain and i<anchor_position and quarters<PARAMETERS["grace_max_quarters"] and abs(p["pitch_midi"]-anchor["pitch_midi"])<=3 and reliable:
                p.update(role="grace",grace=True,anchor_id=anchor["id"],grace_steal_from="following")
            else:
                p["role"]="turn"
                if not reliable:
                    reviews.append({"type":"uncertain_detail_retained","candidate":copy.deepcopy(p),"requires_review":True})
        # 自动音乐解码改造：新增倚音必须连续依附主音；中间普通音或休止使候选保留普通时值。
        for i,p in enumerate(group):
            if not p.get("grace"):
                continue
            following=group[i+1:anchor_position+1]
            path=group[i:anchor_position+1]
            contiguous=all(b["start_seconds"]-a["end_seconds"]<=.04 for a,b in zip(path,path[1:]))
            if not contiguous or any(n is not anchor and not n.get("grace") and not n.get("discarded") for n in following):
                p.update(grace=False,role="turn")
                reviews.append({"type":"grace_dependency_uncertain_retained_metered","candidate":copy.deepcopy(p),"requires_review":True})
        kept=[p for p in group if not p.get("discarded")]
        # 自动音乐解码改造：新增沿真正邻接的短候选链归并，只修改已保留音段，不能跨休止或吞掉尾部。
        chains=[]
        for p in group:
            if p.get("discarded"):
                if chains and abs(chains[-1][-1]["end_seconds"]-p["start_seconds"])<=.015:
                    chains[-1].append(p)
                else:
                    chains.append([p])
        for chain in chains:
            start,end=chain[0]["start_seconds"],chain[-1]["end_seconds"]
            before=[p for p in kept if abs(p["end_seconds"]-start)<=.015]
            after=[p for p in kept if abs(p["start_seconds"]-end)<=.015]
            if before:
                before[-1]["end_seconds"]=end
            elif after:
                after[0]["start_seconds"]=start
            # 自动音乐解码改造：新增无邻接时保留休止和候选来源，不把空隙填成新音。
        output.extend(kept)
    return output,reviews

# 自动音乐解码改造：新增只按小节边界拆符，不强制在每个四分拍拆持续音。
def split_notation(start,end,bar):
    output=[]
    while start<end:
        limit=min(end-start,bar-start%bar);duration,kind,dots=next(d for d in score.DURATIONS if d[0]<=limit)
        output.append({"start_tick":start,"duration_ticks":duration,"type":kind,"dots":dots});start+=duration
    return output

# 自动音乐解码改造：新增共同边界量化，普通主音最少一个网格；倚音由量化前分类确定。
# 乐句节奏与音值分组：修改，原入口声明注释保留；旧算法仅用于历史工程确定性重建。
# def musical_quantize(pieces,mapping,timing,duration):
def _legacy_musical_quantize(pieces,mapping,timing,duration):
    step=PARAMETERS["ordinary_grid_ticks"];origin=timing["score_start_quarter"]
    bar=round(timing["meter"][0]*score.PPQ*4/timing["meter"][1])
    # 自动音乐解码改造：修改，演唱微小提前滞后不扩散成大量32分时值；原实现注释保留。
    # def tick(seconds): return max(0,round((mapping.seconds_to_quarters(seconds)-origin)*score.PPQ/step)*step)
    def tick(seconds):
        quarter=mapping.seconds_to_quarters(seconds)-origin
        # 自动音乐解码改造：新增分层拍格，优先自然半拍、其次四分之一拍，短主音仍受最短时值保护。
        half=round(quarter*2)/2
        quarter_grid=round(quarter*4)/4
        if abs(quarter-half)<=.16:
            quarter=half
        elif abs(quarter-quarter_grid)<=.09:
            quarter=quarter_grid
        return max(0,round(quarter*score.PPQ/step)*step)
    # 大调约束与强拍先验：新增共享起点表，前音终点与后音强拍起点采用同一候选。
    # 强拍相位与伴奏同步纠错：修改，原不核验先验拍轴的起点表保留；复核后不能继承旧相位的quarter。
    # starts=[max(0,round(p["notation_onset_prior"]["quarter"]*score.PPQ)) if p.get("notation_onset_prior") else tick(p["start_seconds"]) for p in pieces]
    review_id=timing.get('beat_phase',{}).get('review_id')
    starts=[max(0,round(p['notation_onset_prior']['quarter']*score.PPQ))
            if p.get('notation_onset_prior') and (not review_id or p['notation_onset_prior'].get('timing_review_id')==review_id)
            else tick(p['start_seconds']) for p in pieces]
    quantized=[];cursor=0
    for i,p in enumerate(pieces):
        # 大调约束与强拍先验：修改起点，原独立量化保留；游标仍保护非重叠。
        # n=copy.deepcopy(p);begin=max(cursor,tick(n["start_seconds"]))
        n=copy.deepcopy(p);begin=max(cursor,starts[i])
        if n.get("grace"):
            n.update(start_tick=begin,end_tick=begin,collapsed_to_grace=False);quantized.append(n);continue
        end=max(begin+step,tick(n["end_seconds"]))
        # 自动音乐解码改造：修改，句内短辅音间隙由持续音承接，句间明显停顿仍保留；原实现注释保留。
        # if i+1<len(pieces) and not pieces[i+1].get("grace") and pieces[i+1]["start_seconds"]-p["end_seconds"]<.12:
        if i+1<len(pieces) and not pieces[i+1].get("grace") and (
                pieces[i+1]["start_seconds"]-p["end_seconds"]<.12 or
                (p.get("line_index")==pieces[i+1].get("line_index") and p.get("line_index") is not None
                 and pieces[i+1]["start_seconds"]-p["end_seconds"]<.40*60/timing["steady_tempo_bpm"])):
            # 大调约束与强拍先验：修改相邻边界，使用已选强拍起点，原式保留。
            # end=max(begin+step,tick(pieces[i+1]["start_seconds"]))
            end=max(begin+step,starts[i+1])
        n.update(start_tick=begin,end_tick=end,collapsed_to_grace=False);quantized.append(n);cursor=end
    # 自动音乐解码改造：新增倚音从后主音分配播放时间，XML与MIDI共用相同时间比例。
    by_id={n["id"]:n for n in quantized}
    for n in quantized: n["playback_start_tick"],n["playback_end_tick"]=n["start_tick"],n["end_tick"]
    for n in quantized:
        if n.get("grace"):
            anchor=by_id[n["anchor_id"]];n["start_tick"]=n["end_tick"]=anchor["start_tick"]
            # 自动音乐解码改造：修改，倚音百分比分母采用紧随XML音符时值，不能用整段跨小节延音；原实现注释保留。
            # remaining=anchor["end_tick"]-anchor["playback_start_tick"]
            # length=min(max(6,round((n["end_seconds"]-n["start_seconds"])*score.PPQ*timing["steady_tempo_bpm"]/60)),max(6,remaining//3))
            # begin=anchor["playback_start_tick"];n["playback_start_tick"],n["playback_end_tick"]=begin,begin+length
            # anchor["playback_start_tick"]=begin+length;n["grace_steal_percent"]=100*length/(anchor["end_tick"]-anchor["start_tick"])
            first_duration=split_notation(anchor["start_tick"],anchor["end_tick"],bar)[0]["duration_ticks"]
            remaining=anchor["start_tick"]+first_duration-anchor["playback_start_tick"]
            length=min(max(1,round((n["end_seconds"]-n["start_seconds"])*score.PPQ*timing["steady_tempo_bpm"]/60)),max(1,remaining//3))
            begin=anchor["playback_start_tick"]
            n["playback_start_tick"],n["playback_end_tick"]=begin,begin+length
            anchor["playback_start_tick"]=begin+length
            n["grace_steal_percent"]=100*length/first_duration
    total=max(bar,math.ceil(max(cursor,tick(duration))/bar)*bar);events=[];cursor=0
    def rest(a,b): return [dict(part,piece_id=None,pitch_midi=None,grace=False,ties=[],lyric_index=None) for part in split_notation(a,b,bar)]
    for n in quantized:
        begin,end=n["start_tick"],n["end_tick"]
        if begin>cursor: events.extend(rest(cursor,begin));cursor=begin
        if n.get("grace"):
            events.append(dict(start_tick=begin,duration_ticks=0,type="eighth",dots=0,piece_id=n["id"],pitch_midi=n["pitch_midi"],grace=True,ties=[],lyric_index=None,grace_steal_percent=n["grace_steal_percent"],anchor_id=n["anchor_id"]))
        else:
            parts=split_notation(begin,end,bar)
            for i,part in enumerate(parts):
                events.append(dict(part,piece_id=n["id"],pitch_midi=n["pitch_midi"],grace=False,ties=(["stop"] if i else [])+(["start"] if i<len(parts)-1 else []),lyric_index=n["lyric_index"],role=n["role"]))
            cursor=end
        n["quantized_start_seconds"]=mapping.quarters_to_seconds(begin/score.PPQ+origin)
        n["quantized_end_seconds"]=mapping.quarters_to_seconds(end/score.PPQ+origin)
        n["start_error_seconds"]=n["quantized_start_seconds"]-n["start_seconds"]
        n["end_error_seconds"]=n["quantized_end_seconds"]-n["end_seconds"]
    events.extend(rest(cursor,total))
    for i,e in enumerate(events): e.update(id=f"music_n{i+1}",measure=e["start_tick"]//bar+1,offset_ticks=e["start_tick"]%bar)
    by_char={}
    for e in events:
        if e.get("lyric_index") is not None and not e["grace"]: by_char.setdefault(e["lyric_index"],[]).append(e)
    # 自动音乐解码改造：新增不同音转音slur；同音持续仅用tie，倚音独立依附到主音。
    number=0
    for group in by_char.values():
        if len({e["pitch_midi"] for e in group})>1:
            number+=1
            group[0].setdefault("slurs",[]).append({"type":"start","number":number%6+1})
            group[-1].setdefault("slurs",[]).append({"type":"stop","number":number%6+1})
    # 调外音宁缺毋滥：新增跨字滑音桥的真实连奏；同音跨小节仍用tie，不重造中间半音。
    event_lookup={}
    for event in events:
        if event.get("piece_id") and not event.get("grace"):
            event_lookup.setdefault(event["piece_id"],[]).append(event)
    for note in quantized:
        pairs=[]
        if note.get("legato_target_piece_id"):pairs.append((note["id"],note["legato_target_piece_id"]))
        if note.get("legato_source_piece_id"):pairs.append((note["legato_source_piece_id"],note["id"]))
        for left_id,right_id in pairs:
            left=event_lookup.get(left_id,[]);right=event_lookup.get(right_id,[])
            if not left or not right or left[-1]["pitch_midi"]==right[0]["pitch_midi"]:continue
            # 调外音宁缺毋滥：新增同字转音已有默认slur，不额外画滑音桥，避免重叠双弧线。
            if left[-1].get("lyric_index")==right[0].get("lyric_index"):continue
            # 调外音宁缺毋滥：修改独立滑音桥编号池为13到16，原值保留。
            # number+=1;bridge_number=number%6+13
            number+=1;bridge_number=number%4+13
            left[-1].setdefault("slurs",[]).append({"type":"start","number":bridge_number})
            right[0].setdefault("slurs",[]).append({"type":"stop","number":bridge_number})
    for e in events:
        if e["grace"]:
            # 自动音乐解码改造：修改，倚音连线与转音连线使用不同编号池；原实现注释保留。
            # number+=1;e.setdefault("slurs",[]).append({"type":"start","number":number%6+1})
            # anchor=next(x for x in events if x.get("piece_id")==e["anchor_id"])
            # anchor.setdefault("slurs",[]).append({"type":"stop","number":number%6+1})
            number+=1
            grace_number=number%6+7
            e.setdefault("slurs",[]).append({"type":"start","number":grace_number})
            anchor=next(x for x in events if x.get("piece_id")==e["anchor_id"])
            anchor.setdefault("slurs",[]).append({"type":"stop","number":grace_number})
    errors=[abs(n[k]) for n in quantized if not n.get("grace") for k in ("start_error_seconds","end_error_seconds")]
    stats={"raw_pitched_notes":len({p["source_note_id"] for p in pieces}),"lyric_split_pieces":len(pieces),"grace_notes_from_collapsed_grid":0,
           "classified_grace_notes":sum(n.get("grace",False) for n in quantized),"main_notes":sum(n["role"]=="main" for n in quantized),
           "turn_notes":sum(n["role"]=="turn" for n in quantized),"grid_quarters":step/score.PPQ,"measure_count":total//bar,"bar_ticks":bar,"total_ticks":total,
           "quantization_error_seconds":{"median_abs":statistics.median(errors) if errors else 0,"p95_abs":float(np.percentile(errors,95)) if errors else 0,"max_abs":max(errors,default=0)}}
    return events,quantized,stats

# 乐句节奏与音值分组：新增通用入口，带音素字符采用联合乐句求解，旧快照仍可精确回放。
def musical_quantize(pieces,mapping,timing,duration,characters=None):
    if characters is None:
        return _legacy_musical_quantize(pieces,mapping,timing,duration)
    from phrase_rhythm import quantize_phrase
    return quantize_phrase(pieces,characters,mapping,timing,duration)

# 自动音乐解码改造：新增项目解码，参考答案不参与参数或音符生成。
# 大调约束与强拍先验：修改入口增加同源吞字确认，旧签名保留。
# def decode(analysis,lyrics,audio_analysis,target_key=None,tempo=None,meter=None,beat_origin=None,verify_audio=True):
def decode(analysis,lyrics,audio_analysis,target_key=None,tempo=None,meter=None,beat_origin=None,verify_audio=True,review_annotations=None):
    # 第四首《日落大道》男声跨歌曲验证：修改取调顺序，原整条声学轨取调保留；间奏/尾奏不代表人声调式。
    # native=infer_vocal_key(analysis["notes"]);notes,reviews=acoustic_candidates(analysis,verify_audio)
    notes,reviews=acoustic_candidates(analysis,verify_audio)
    # 字音归属修复：修改，传入独立词起音候选，旧调用注释保留。
    # pieces,characters,issues=soft_lyrics(notes,lyrics)
    pieces,characters,issues=soft_lyrics(notes,lyrics,analysis)
    # 第四首《日落大道》男声跨歌曲验证：新增只释放明确字外且有真实替代的候选，原字音音序保留。
    pieces,issues=release_outside_lyric_segments(pieces,characters,issues)
    # 自动音乐解码改造：新增同音归并置于字音关联之后，跨字短重起不丢失。
    pieces=coalesce_same_character(pieces)
    # 第四首《日落大道》男声跨歌曲验证：新增实际挂词声段取调与唱句共同验证转调。
    from vocal_tonality import infer_sections
    native,key_sections=infer_sections(pieces,characters,infer_vocal_key,score.key_definition)
    mapping,timing=robust_timing(audio_analysis,pieces,characters,tempo,meter,beat_origin)
    # 大调约束与强拍先验：新增先固定原声拍格，再约束派生旋律，避免一次纠音带动整曲拍格漂移。
    import tonal_rhythm_prior as priors
    source_key=score.key_definition(native["selected"])
    evidence=AcousticEvidence(analysis,verify_audio)
    # 调外音宁缺毋滥：修改先验接入实际拍速，原调用保留。
    # pieces,tonal_reviews=priors.regularize_major(pieces,source_key,key_sections,evidence);reviews+=tonal_reviews
    # 连续转调识别与不确定调性保护：修改传入局部保护范围，原调用保留。
    # pieces,tonal_reviews=priors.regularize_major(pieces,source_key,key_sections,evidence,timing);reviews+=tonal_reviews
    pieces,tonal_reviews=priors.regularize_major(pieces,source_key,key_sections,evidence,timing,uncertain_regions=native.get("uncertain_regions",[]));reviews+=tonal_reviews
    pieces=priors.merge_same_word(pieces)
    pieces,onset_reviews=priors.phrase_onsets(pieces,characters,mapping,timing);reviews+=onset_reviews
    characters=priors.annotate_confirmed_elision(characters,review_annotations,analysis["source"])
    # 第四首《日落大道》男声跨歌曲验证：修改分类传入真实字界，原调用保留。
    # pieces,detail_reviews=classify(pieces,mapping);reviews+=detail_reviews
    pieces,detail_reviews=classify(pieces,mapping,characters);reviews+=detail_reviews
    # 强拍相位与伴奏同步纠错：新增可靠音素下的整曲字首量化先验；音高、倚音与真实字内转音不重识别。
    if timing.get('beat_phase'):
        # 乐句节奏与音值分组：修改，原绝对元音先验注释保留；音素只在乐句求解中作软证据。
        # from beat_phase_alignment import nucleus_onsets
        # pieces,nucleus_reviews=nucleus_onsets(pieces,characters,mapping,timing)
        # reviews += [dict(type='phoneme_nucleus_onset_quantization',**r) for r in nucleus_reviews]
        # 强拍相位与伴奏同步纠错：新增新生成器同样采用已复核文本，原字与音素所有者仍记在复核层。
        for change in timing['beat_phase'].get('lyric_text_corrections',[]):
            char=next((c for c in characters if c['index']==change['index']),None)
            if char and char['text']==change['old']:
                char['text']=change['new'];char['text_correction']=copy.deepcopy(change)
    source_key=score.key_definition(native["selected"]);key=score.key_definition(target_key or native["selected"])
    if source_key["mode"]!=key["mode"]: raise ValueError("源调与目标调式不同，不能只用整体移调。")
    shift=((key["tonic_pc"]-source_key["tonic_pc"]+6)%12)-6 if target_key else 0
    # 大调约束与强拍先验：修改源音记录，保留调整前演唱音段与记谱源音的区别；原赋值保留。
    # for p in pieces: p["source_pitch_midi"]=p["pitch_midi"];p["pitch_midi"]+=shift
    for p in pieces:
        p.setdefault("source_pitch_midi",p["pitch_midi"]);p["notation_source_pitch_midi"]=p["pitch_midi"];p["pitch_midi"]+=shift
    # 乐句节奏与音值分组：修改，旧逐音入口注释保留；新生成默认完整乐句联合求解。
    # events,quantized,stats=musical_quantize(pieces,mapping,timing,audio_analysis["duration_seconds"])
    events,quantized,stats=musical_quantize(pieces,mapping,timing,audio_analysis["duration_seconds"],characters)
    lyric_mapping=score.attach_lyrics(events,characters)
    # 第四首《日落大道》男声跨歌曲验证：修改拒绝条件，只允许已明确未定位的字缺挂；有效字缺失/逆序仍为错误。
    # if lyric_mapping["unmapped_character_indices"] or lyric_mapping["issues"]: raise ValueError("解码后歌词缺失或逆序。")
    unresolved={c["index"] for c in characters if c.get("start_seconds") is None or c.get("end_seconds") is None or c["end_seconds"]<=c["start_seconds"]}
    if set(lyric_mapping["unmapped_character_indices"]) != unresolved or lyric_mapping["issues"]:
        raise ValueError("有效歌词解码后缺失或逆序。")
    lyric_mapping["unresolved_alignment_indices"] = sorted(unresolved)
    # 大调约束与强拍先验：新增确认状态不改变原未挂数，仅将待人工判断的索引独立表达。
    elided={c["index"] for c in characters if c.get("human_review",{}).get("status")=="user_confirmed_elided"}
    lyric_mapping["confirmed_elided_indices"]=sorted(elided)
    lyric_mapping["unresolved_review_indices"]=sorted(unresolved-elided)
    reference=60+key["jianpu_one_pc"]
    reference+=12*round((statistics.median(n["pitch_midi"] for n in quantized)-reference-5)/12)
    # 第四首《日落大道》男声跨歌曲验证：新增调号区间与实际音高分离；目标调统一移调仍保留相邻段的调距。
    if key_sections:
        first_pc=source_key['jianpu_one_pc']
        for section in key_sections:
            source_section=section['source_key'];new_pc=(source_section['tonic_pc']+shift)%12
            section['key']=score.key_definition(['C','Db','D','Eb','E','F','F#','G','Ab','A','Bb','B'][new_pc]+':'+source_section['mode']) if shift else source_section
            delta=((source_section['jianpu_one_pc']-first_pc+6)%12)-6
            section['jianpu_reference_midi']=reference+delta
            first_note=next(n for n in quantized if n.get('lyric_index')==section['first_character_index'])
            # 强拍相位与伴奏同步纠错：修改，原提前整小节显示新调保留；新调弱起先用临时升降号。
            # section['start_tick']=first_note['start_tick']//stats['bar_ticks']*stats['bar_ticks']
            section['start_tick']=(math.ceil(first_note['start_tick']/stats['bar_ticks']) if timing.get('beat_phase')
                                   else first_note['start_tick']//stats['bar_ticks'])*stats['bar_ticks']
            section['start_measure']=section['start_tick']//stats['bar_ticks']+1
        key_sections[0]['start_tick']=0;key_sections[0]['start_measure']=1
    return {"schema_version":2,"artifact_kind":"musically_decoded_automatic_draft","quality_status":"requires_musical_review",
            # 自动音乐解码改造：新增覆盖记录供统一渲染使用。
            # 小节划分与拍速层级纠错：修改，原把自动选择写成覆盖保留；仅真实命令参数属于人工tempo覆盖。
            # "overrides":{"tempo":timing["steady_tempo_bpm"],"key":target_key,"meter":meter,"beat_origin":beat_origin},
            "overrides":{"tempo":tempo,"key":target_key,"meter":meter,"beat_origin":beat_origin},
            # 字音归属修复：修改，原decoder记录注释保留，新增音素/路径证据范围。
            # "decoder":{"version":VERSION,"parameters":PARAMETERS,"reference_score_used":False},"audio_analysis":audio_analysis,"timing":timing,
            "decoder":{"version":VERSION,"parameters":PARAMETERS,"reference_score_used":False,
                       # 大调约束与强拍先验：新增策略与调整计数，统计不当作准确概率。
                       # 连续转调识别与不确定调性保护：纠音与保音分开计数，原统计保留。
                       # "tonal_rhythm_priors":{"parameters":priors.PARAMETERS,"notation_adjustments":len(tonal_reviews),
                       "tonal_rhythm_priors":{"parameters":priors.PARAMETERS,"notation_adjustments":sum(r["type"]=="tonal_prior_adjusted" for r in tonal_reviews),
                            "uncertain_regions":native.get("uncertain_regions",[]),"guarded_notes":sum(bool(n.get("tonality_guard")) for n in quantized),
                           "pitch_changes":sum(r["type"]=="tonal_prior_adjusted" for r in tonal_reviews),
                           "stable_chromatic_exceptions":sum(r["type"]=="stable_chromatic_exception_retained" for r in tonal_reviews),
                           "onset_decisions":len(onset_reviews),"raw_acoustic_data_unchanged":True},
                       # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
                       # "word_ownership":{"version":2,"method":"joint_monotonic_all_notes",
                       # 中文版本冻结与英文融合验证：新增中英文兼容实现。
                        "english_lyrics":{"version":1,"units":"whole_words_with_observed_vowel_syllables",
                                          "words":sum(c.get("unit_kind")=="english_word" for c in characters),
                                          "observed_syllables":sum(len(c.get("english_syllables",[])) for c in characters)},
                       "word_ownership":{"version":2,"method":"joint_monotonic_all_notes",
                                         "characters_with_phonemes":sum(bool(c.get("phonemes")) for c in characters),
                                         "total_characters":len(characters),"phoneme_provenance":lyrics.get("phoneme_provenance"),
                                         "uncertain_ownership_count":len(issues),"path_margin_is_accuracy":False}},
            "audio_analysis":audio_analysis,"timing":timing,
            "notation":{"key":key,"source_key":source_key,"source_key_evidence":native,"target_key":target_key,"transpose_semitones":shift,
                        # 第四首《日落大道》男声跨歌曲验证：新增独立调号区间元数据，不修改源音高。
                        # 连续转调识别与不确定调性保护：新增可追溯的保护范围元数据。
                        "tonality_uncertain_regions":native.get("uncertain_regions",[]),
                        "key_segments":key_sections,"jianpu_reference_midi":reference,"ppq":score.PPQ,"triplet_detection":"not_implemented; no_tuplet_is_invented",
                        "midi_grace_note_playback":"measured_duration_stolen_from_following_anchor"},
            "lyrics":{"reference_kind":lyrics.get("reference_kind","unknown"),"alignment_status":lyrics.get("alignment_status","unknown"),"characters":characters,"review_required":True},
            "alignment_issues":issues,"review_candidates":reviews,"lyric_mapping":lyric_mapping,"quantized_notes":quantized,"events":events,"statistics":stats,
            "tempo_events":score.tempo_events(mapping,timing,stats["total_ticks"]),"external_editor_roundtrip":"not_tested"}

# 自动音乐解码改造：新增独立MIDI回读，普通音/倚音时序必须与项目一致。
def validate_playback(path,project):
    import mido
    active={};actual=[];tick=0
    for message in mido.MidiFile(path).tracks[0]:
        tick+=message.time
        if message.type=="note_on" and message.velocity>0: active.setdefault(message.note,[]).append(tick)
        elif message.type=="note_off" or (message.type=="note_on" and message.velocity==0):
            if not active.get(message.note): raise ValueError("MIDI终音没有起音。")
            actual.append((active[message.note].pop(0),tick,message.note))
    expected=sorted((n["playback_start_tick"],n["playback_end_tick"],n["pitch_midi"]) for n in project["quantized_notes"])
    if sorted(actual)!=expected or any(active.values()) or tick!=project["statistics"]["total_ticks"]: raise ValueError("MIDI发声与音乐分类项目不一致。")
    if any(a[1]>b[0] for a,b in zip(sorted(actual),sorted(actual)[1:])): raise ValueError("倚音分配造成声部重叠。")
    return {"valid":True,"attacks":len(actual),"grace_allocation_verified":True}

# 自动音乐解码改造：新增独立XML百分比回算，包含延音拆符的分母和依附音检查。
def validate_grace_allocation(xml,project):
    xml_notes=xml.findall("part/measure/note")
    events={e["id"]:e for e in project["events"]}
    pieces={n["id"]:n for n in project["quantized_notes"]}
    errors=[]
    for position,note in enumerate(xml_notes):
        grace=note.find("grace")
        if grace is None:
            continue
        record=pieces[events[note.get("id")]["piece_id"]]
        following=next((n for n in xml_notes[position+1:] if n.find("grace") is None),None)
        if following is None or events[following.get("id")].get("piece_id")!=record["anchor_id"]:
            raise ValueError("XML倚音不紧邻指定主音。")
        allocated=float(grace.get("steal-time-following"))*float(following.findtext("duration")) /100
        sounded=record["playback_end_tick"]-record["playback_start_tick"]
        errors.append(abs(allocated-sounded))
    if max(errors,default=0)>.001:
        raise ValueError("XML与MIDI的倚音时间分配不一致。")
    return {"valid":True,"grace_notes":len(errors),"max_error_ticks":max(errors,default=0),"scope":"xml_time_semantics_not_external_editor_playback"}

# 自动音乐解码改造：新增独立导出，旧版和源缓存不覆盖。
def export(args):
    import json
    started=time.perf_counter();analysis=score.read_json(args.notes);lyrics=score.read_json(args.lyrics)
    if analysis["source"].get("offset_seconds",0)!=0 or lyrics["source"].get("offset_seconds",0)!=0: raise ValueError("需整首零偏移时间轴。")
    if analysis["source"]["sha256"]!=lyrics["source"]["sha256"]: raise ValueError("歌词与人声音符源不一致。")
    audio_analysis=score.analyze_audio(args.audio,getattr(args,"audio_report",None) or score.ROOT/"reports/score_audio_analysis.json")
    if abs(audio_analysis["duration_seconds"]-analysis["source"]["duration_seconds"])>.1: raise ValueError("混音与人声长度不一致。")
    # 大调约束与强拍先验：修改导出读入可选用户确认，原调用保留。
    # project=decode(analysis,lyrics,audio_analysis,args.key,args.tempo,args.meter,args.beat_origin)
    annotation_path=getattr(args,"review_annotations",None)
    annotations=score.read_json(annotation_path) if annotation_path else None
    project=decode(analysis,lyrics,audio_analysis,args.key,args.tempo,args.meter,args.beat_origin,review_annotations=annotations)
    if annotation_path: project["review_annotation_source"]={"path":str(annotation_path.resolve()),"sha256":score.sha256(annotation_path)}
    project["title"]=args.title
    project["inputs"]={"notes_path":str(args.notes.resolve()),"notes_sha256":score.sha256(args.notes),"lyrics_path":str(args.lyrics.resolve()),
                       "lyrics_sha256":score.sha256(args.lyrics),"mix_audio_path":str(args.audio.resolve()),"mix_audio_sha256":audio_analysis["source_sha256"],"transcription_source":analysis["source"]}
    project["raw_analysis_preservation"]={"original_notes_and_continuous_f0":str(args.notes.resolve()),"unchanged_source":True,"time_unit":"original_song_seconds"}
    output=args.output_dir;output.mkdir(parents=True,exist_ok=True)
    xml=score.build_musicxml(project);validation=score.validate_score(project,xml)
    if not validation["valid"]: raise ValueError(str(validation["errors"]))
    validation["xml_midi_grace_allocation"]=validate_grace_allocation(xml,project)
    ET.indent(xml,space="  ");ET.ElementTree(xml).write(output/"vocal_draft.musicxml",encoding="utf-8",xml_declaration=True)
    score.write_midi(output/"vocal_draft.mid",project);validation["midi"]=validate_playback(output/"vocal_draft.mid",project)
    score.save_json(output/"project.json",project);score.save_json(output/"validation.json",validation)
    scene=score.render_jianpu(project);svg=scene.svg();(output/"jianpu.svg").write_text(svg,encoding="utf-8")
    # 第二首跨歌曲验证：修改，原首音选择注释保留；预览从首个真实挂词段开始。
    # first=min(e["measure"] for e in project["events"] if e["pitch_midi"] is not None)
    first=score.first_vocal_measure(project)
    score.render_jianpu(project,max(1,first-1),min(project["statistics"]["measure_count"],first+8),True).png(output/"preview_first_vocal.png")
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(args.title)+' · 音乐解码版</title><style>body{background:#eef2f6;margin:24px;font-family:"Microsoft YaHei",sans-serif}main{background:white;padding:20px;max-width:1440px;margin:auto}svg{width:100%;height:auto}p{line-height:1.8}a{color:#205a98}</style><main><p>音乐解码自动稿 · '+html.escape(score.lyric_notice(project))+'</p><p>小号音为倚音；同音弧线为延音，不同音弧线为转音连奏。<a href="vocal_draft.musicxml">可编辑乐谱</a>　<a href="vocal_draft.mid">试听MIDI</a>　<a href="review.html">疑难复核</a></p>'+svg+'</main></html>'
    # 简谱小节对齐与人工复核汇总：新增默认简谱到按句清单的链接，清单由后续同源复核入口生成。
    document=document.replace('<a href="review.html">疑难复核</a>','<a href="manual_review.html">人工复核清单</a>　<a href="review.html">完整证据</a>',1)
    (output/"jianpu.html").write_text(document,encoding="utf-8")
    review='<html lang="zh-CN"><meta charset="utf-8"><title>声学复核</title><style>body{font-family:"Microsoft YaHei";margin:32px}pre{white-space:pre-wrap}li{margin-bottom:14px}</style><h1>声学与字音复核层</h1><p>自动候选保留在此；音乐准确性仍需核查。</p><ol>'
    for item in project["review_candidates"]+project["alignment_issues"]:
        review+='<li><pre>'+html.escape(json.dumps(item,ensure_ascii=False,indent=2))+'</pre></li>'
    (output/"review.html").write_text(review+'</ol></html>',encoding="utf-8")
    report={"status":"musically_decoded_draft_exported","decoder_version":VERSION,"statistics":project["statistics"],"notation":project["notation"],"validation":validation,
            "lyric_mapping":project["lyric_mapping"],"seconds":time.perf_counter()-started,"inputs":project["inputs"],"output_dir":str(output.resolve()),
            "external_editor_roundtrip":"not_tested","reference_score_used":False}
    # 十一首可编辑五线谱：新增五线谱交换文件与真实分页预览，复用本次旋律/歌词。
    from staff_export import export_staff_score
    report['staff_export'] = export_staff_score(output)
    score.save_json(args.report,report)
    print(json.dumps({k:report[k] for k in ("status","statistics","seconds","output_dir")},ensure_ascii=False));return 0

# 自动音乐解码改造：新增CLI，key是目标调；无key时保留录音实际音高。
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("notes","lyrics","audio","output-dir","report"): parser.add_argument("--"+name,type=Path,required=True)
    # 大调约束与强拍先验：修改CLI说明，源调不变与派生音高纠正分开；原说明保留。
    # parser.add_argument("--title",default="人声乐谱");parser.add_argument("--key",help="输出目标调，例如 G:major；默认源音高")
    parser.add_argument("--title",default="人声乐谱");parser.add_argument("--key",help="输出目标调，例如 G:major；默认源调，记谱可纠正低支持音高")
    # 大调约束与强拍先验：新增来源受校验的用户吞字确认文件参数。
    parser.add_argument("--review-annotations",type=Path)
    parser.add_argument("--audio-report",type=Path,help="本次任务独立音源分析报告")
    parser.add_argument("--tempo",type=float);parser.add_argument("--meter");parser.add_argument("--beat-origin",type=float)
    parser.add_argument("--subdivision",type=int,choices=(2,4,8),default=8,help="旧入口兼容；音乐层保护短主音使用32分最小网格")
    return export(parser.parse_args())

if __name__=="__main__": raise SystemExit(main())
