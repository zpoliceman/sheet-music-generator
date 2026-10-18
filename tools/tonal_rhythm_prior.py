"""大调约束与强拍先验：只调整可读记谱，保留原始声学及音素时间。"""
# 大调约束与强拍先验：新增通用证据约束；不读取歌曲名、小节答案或参考谱。
from __future__ import annotations
import copy
import hashlib
import math
from collections import defaultdict

MAJOR_INTERVALS = frozenset((0, 2, 4, 5, 7, 9, 11))
# 调外音宁缺毋滥：新增严格例外门槛和保守记谱策略；原参数仍供历史比较。
PARAMETERS = {"chromatic_policy":"precision_first", "chromatic_minimum_seconds":.20, "chromatic_minimum_quarters":.50,
              "chromatic_plateau_fraction":.75,"chromatic_model_support":.85,"chromatic_independent_support":.85,
              "chromatic_center_error_semitones":.20,"major_only": True, "chromatic_core_seconds": .10,
              "chromatic_support": .80, "phrase_gap_quarters": .50,
              "maximum_onset_shift_quarters": .35, "nucleus_near_beat_quarters": .16,
              "downbeat_bonus_squared_quarters": .085, "third_beat_bonus_squared_quarters": .045}

# 大调约束与强拍先验：新增每个音按所属实际调式段判断，避免末段转调被吸附回首调。
def source_key_at(note, native_key, sections):
    key = native_key
    for section in sections:
        index = note.get("lyric_index")
        eligible = index >= section["first_character_index"] if index is not None else note["start_seconds"] >= section["start_seconds"]
        if eligible:
            key = section["source_key"]
    return key

# 大调约束与强拍先验：新增完整的派生前音段记录，合并后仍可找回各自的音高和时值。
def remember(note):
    note.setdefault("source_pitch_midi", note["pitch_midi"])
    note.setdefault("performance_segments", [{"piece_id": note["id"], "source_note_id": note["source_note_id"],
        "pitch_midi": note["pitch_midi"], "start_seconds": note["start_seconds"], "end_seconds": note["end_seconds"]}])

# 大调约束与强拍先验：新增局部平台证据复核；稳定调外音是例外，不机械删除半音。
# 调外音宁缺毋滥：替换旧宽松保留策略，原函数完整注释保留。
# def regularize_major(pieces, native_key, sections, evidence):
#     output = copy.deepcopy(pieces); reviews = []
#     for note in output:
#         remember(note)
#     for i, note in enumerate(output):
#         if note.get("lyric_index") is None:
#             continue
#         key = source_key_at(note, native_key, sections)
#         if key["mode"] != "major" or (note["pitch_midi"] - key["tonic_pc"]) % 12 in MAJOR_INTERVALS:
#             continue
#         # 大调约束与强拍先验：修正真实曲目空平台分支，独立复核只在平台存在时调用；原式保留。
#         # cores = evidence.independent(evidence.cores(note["start_seconds"], note["end_seconds"]))
#         raw_cores = evidence.cores(note["start_seconds"], note["end_seconds"])
#         cores = evidence.independent(raw_cores) if raw_cores else []
#         same = [c for c in cores if c["pitch_midi"] == note["pitch_midi"]
#                 and c["end_seconds"] - c["start_seconds"] >= PARAMETERS["chromatic_core_seconds"]
#                 and c["support"] >= PARAMETERS["chromatic_support"]]
#         # 大调约束与强拍先验：新增稳定声学平台加模型或独立波形支持的例外；短倚音也可保留。
#         explicit = [c for c in same if (c.get("independent_agreement") or 0) >= .70
#                     or (note.get("confidence") or 0) >= .70]
#         record = {"piece_id": note["id"], "character_index": note["lyric_index"], "key": key["label"],
#                   "start_seconds": note["start_seconds"], "end_seconds": note["end_seconds"],
#                   "performance_pitch_midi": note["pitch_midi"], "platforms": cores,
#                   "confidence_is_accuracy": False}
#         if explicit:
#             note["chromatic_status"] = "stable_exception_retained"
#             reviews.append(dict(record, type="stable_chromatic_exception_retained"))
#             continue
#         neighbours = [n for n in output[max(0, i-1):i+2] if n is not note
#                       and n.get("lyric_index") == note["lyric_index"]
#                       and (n["pitch_midi"] - key["tonic_pc"]) % 12 in MAJOR_INTERVALS
#                       and (n.get("confidence") or 0) >= .65 and n.get("stable_duration_seconds", 0) >= .10]
#         candidates = []
#         for core in cores:
#             supported_context = any(n["pitch_midi"] == core["pitch_midi"] for n in neighbours)
#             if ((core["pitch_midi"] - key["tonic_pc"]) % 12 in MAJOR_INTERVALS
#                 and abs(core["pitch_midi"] - note["pitch_midi"]) <= 2
#                 and core["support"] >= .85 and core["end_seconds"] - core["start_seconds"] >= .10
#                 and ((core.get("independent_agreement") or 0) >= .60 or supported_context)):
#                 candidates.append(core)
#         # 大调约束与强拍先验：新增只纠正低支持标签，或明确偏离其调外标签的连续平台；没有证据则留待复核。
#         if candidates and ((note.get("confidence") or 0) < .60 or not same):
#             best = max(candidates, key=lambda c:(c["end_seconds"]-c["start_seconds"])*c["support"])
#             note["pitch_midi"] = best["pitch_midi"]
#             note["notation_adjustment"] = dict(reason="major_prior_with_stable_in_scale_platform",
#                 old_pitch_midi=record["performance_pitch_midi"], new_pitch_midi=note["pitch_midi"],
#                 platform=best, context_supported=any(n["pitch_midi"] == best["pitch_midi"] for n in neighbours))
#             reviews.append(dict(record, type="tonal_prior_adjusted", notation_adjustment=note["notation_adjustment"]))
#         else:
#             note["chromatic_status"] = "ambiguous_retained_for_review"
#             reviews.append(dict(record, type="ambiguous_chromatic_retained_for_review"))
#     return output, reviews

# 调外音宁缺毋滥：新增严格独立音门槛，短平台或单模型高支持都不能独自批准调外音。
def strict_chromatic_evidence(note, cores, period):
    duration = note["end_seconds"] - note["start_seconds"]
    minimum = max(.20, .50*period)
    accepted = [c for c in cores if c["pitch_midi"] == note["pitch_midi"]
                and c["end_seconds"] - c["start_seconds"] + 1e-9 >= minimum
                and (c["end_seconds"] - c["start_seconds"])/duration + 1e-9 >= .75
                and c["support"] >= .90
                and abs(c["median_midi"] - c["pitch_midi"]) <= .20
                and (c.get("independent_agreement") or 0) >= .85
                and (note.get("confidence") or 0) >= .85]
    return accepted

# 调外音宁缺毋滥：新增稳健连续音高中位数；剔除远离原标签的八度/漏检异常，但不声称是准确概率。
def local_pitch_center(note, evidence):
    import numpy as np
    values=evidence.midi[(evidence.times>=note["start_seconds"]) & (evidence.times<note["end_seconds"])]
    usable=values[np.isfinite(values) & (np.abs(values-note["pitch_midi"])<=2.)]
    return float(np.median(usable)) if len(usable) else float(note["pitch_midi"])

# 调外音宁缺毋滥：新增可读记谱的调内候选评分；缺证据只留候选到复核层，主谱不输出不确定半音。
def conservative_scale_choice(note, original, position, key, evidence):
    center=local_pitch_center(note,evidence)
    choices=[p for p in range(note["pitch_midi"]-2,note["pitch_midi"]+3)
             if (p-key["tonic_pc"])%12 in MAJOR_INTERVALS]
    neighbours=[]
    for n in original[max(0,position-1):position+2]:
        if n["id"] == note["id"] or (n["pitch_midi"]-key["tonic_pc"])%12 not in MAJOR_INTERVALS:
            continue
        adjacent=min(abs(n["end_seconds"]-note["start_seconds"]),abs(note["end_seconds"]-n["start_seconds"]))<=.03
        if adjacent and (n.get("confidence") or 0)>=.65 and n.get("stable_duration_seconds",0)>=.10:
            neighbours.append(n)
    ranked=[]
    for pitch in choices:
        same_word=any(n.get("lyric_index")==note.get("lyric_index") and n["pitch_midi"]==pitch for n in neighbours)
        neighbouring=any(n["pitch_midi"]==pitch for n in neighbours)
        cost=(pitch-center)**2-(.30 if same_word else .10 if neighbouring else 0)
        ranked.append({"pitch_midi":pitch,"cost":cost,"same_word_anchor":same_word,"adjacent_anchor":neighbouring})
    best=min(ranked,key=lambda r:(r["cost"],r["pitch_midi"]))
    return best["pitch_midi"],{"method":"precision_first_major_notation_prior","measured_center_midi":center,
                              "candidates":ranked,"is_inferred_not_measured_pitch":True}

# 调外音宁缺毋滥：新增两调内锚点之间的短滑音桥；归入同字的起/止音并建立连奏，不跨字合并。
def diatonic_glide_bridge(note, original, position, key, period):
    if not 0<position<len(original)-1:
        return None
    left,right=original[position-1],original[position+1]
    if note["end_seconds"]-note["start_seconds"] > .55*period or note.get("stable_duration_seconds",0)>.075:
        return None
    if not min(left["pitch_midi"],right["pitch_midi"])<note["pitch_midi"]<max(left["pitch_midi"],right["pitch_midi"]):
        return None
    if (abs(left["end_seconds"]-note["start_seconds"])>.03
        or abs(note["end_seconds"]-right["start_seconds"])>.03
        or any((n["pitch_midi"]-key["tonic_pc"])%12 not in MAJOR_INTERVALS
               # 调外音宁缺毋滥：修改调内端点支持，至少一端强支持；原条件保留。
               # or (n.get("confidence") or 0)<.65 or n.get("stable_duration_seconds",0)<.10 for n in (left,right))):
               or (n.get("confidence") or 0)<.50 or n.get("stable_duration_seconds",0)<.10 for n in (left,right))
        or max(left.get("confidence") or 0,right.get("confidence") or 0)<.75):
        return None
    if note.get("lyric_index") is not None and left.get("lyric_index")==note["lyric_index"]:
        return {"pitch_midi":left["pitch_midi"],"legato_target_piece_id":right["id"],"anchor":"preceding_same_word"}
    if note.get("lyric_index") is not None and right.get("lyric_index")==note["lyric_index"]:
        return {"pitch_midi":right["pitch_midi"],"legato_source_piece_id":left["id"],"anchor":"following_same_word"}
    return None

# 调外音宁缺毋滥：修改通用调外音处理；所有打印声段均采用保守记谱，但原波形、调性取证和字归属不改变。
# 连续转调识别与不确定调性保护：替换无调性保护的强吸附，原函数完整注释保留。
# def regularize_major(pieces, native_key, sections, evidence, timing=None):
#     original=copy.deepcopy(pieces);output=copy.deepcopy(pieces);reviews=[]
#     period=60/timing["steady_tempo_bpm"] if timing else .50
#     for note in output:
#         remember(note)
#     for i,note in enumerate(output):
#         key=source_key_at(note,native_key,sections)
#         if key["mode"]!="major" or (note["pitch_midi"]-key["tonic_pc"])%12 in MAJOR_INTERVALS:
#             continue
#         raw_cores=evidence.cores(note["start_seconds"],note["end_seconds"])
#         cores=evidence.independent(raw_cores) if raw_cores else []
#         explicit=strict_chromatic_evidence(note,cores,period)
#         record={"piece_id":note["id"],"character_index":note.get("lyric_index"),"key":key["label"],
#                 "start_seconds":note["start_seconds"],"end_seconds":note["end_seconds"],
#                 "performance_pitch_midi":note["pitch_midi"],"platforms":cores,
#                 "strict_exception_minimum_seconds":max(.20,.50*period),"confidence_is_accuracy":False}
#         if explicit:
#             note["chromatic_status"]="stable_exception_retained"
#             reviews.append(dict(record,type="stable_chromatic_exception_retained"))
#             continue
#         bridge=diatonic_glide_bridge(note,original,i,key,period)
#         neighbours=[n for n in original[max(0,i-1):i+2] if n["id"]!=note["id"]
#                     and n.get("lyric_index")==note.get("lyric_index")
#                     and (n["pitch_midi"]-key["tonic_pc"])%12 in MAJOR_INTERVALS
#                     and (n.get("confidence") or 0)>=.65 and n.get("stable_duration_seconds",0)>=.10]
#         in_scale=[c for c in cores if (c["pitch_midi"]-key["tonic_pc"])%12 in MAJOR_INTERVALS
#                   and abs(c["pitch_midi"]-note["pitch_midi"])<=2 and c["support"]>=.85
#                   and c["end_seconds"]-c["start_seconds"]>=.10
#                   and ((c.get("independent_agreement") or 0)>=.60 or any(n["pitch_midi"]==c["pitch_midi"] for n in neighbours))]
#         if bridge:
#             pitch=bridge["pitch_midi"];decision={"reason":"diatonic_glide_bridge",**bridge}
#             for field in ("legato_target_piece_id","legato_source_piece_id"):
#                 if field in bridge:note[field]=bridge[field]
#         elif in_scale:
#             best=max(in_scale,key=lambda c:(c["end_seconds"]-c["start_seconds"])*c["support"])
#             pitch=best["pitch_midi"];decision={"reason":"major_prior_with_stable_in_scale_platform","platform":best}
#         else:
#             pitch,decision=conservative_scale_choice(note,original,i,key,evidence)
#             decision["reason"]="unproven_chromatic_omitted_from_readable_score"
#         note["pitch_midi"]=pitch
#         note["chromatic_status"]="omitted_from_score_preserved_in_review"
#         note["notation_adjustment"]={"old_pitch_midi":record["performance_pitch_midi"],"new_pitch_midi":pitch,**decision}
#         reviews.append(dict(record,type="tonal_prior_adjusted",notation_adjustment=note["notation_adjustment"]))
#     return output,reviews

# 连续转调识别与不确定调性保护：新增带局部不确定段保护的调外音处理。
def regularize_major(pieces, native_key, sections, evidence, timing=None, uncertain_regions=None):
    original=copy.deepcopy(pieces);output=copy.deepcopy(pieces);reviews=[]
    # 连续转调识别与不确定调性保护：新增调性不确定区域，未确认前保留声学音高。
    regions=uncertain_regions or [];guarded={}
    period=60/timing["steady_tempo_bpm"] if timing else .50
    for note in output:
        remember(note)
    for i,note in enumerate(output):
        # 连续转调识别与不确定调性保护：新增逐音保护，挂词按原索引，字外声段按原时间判断。
        index=note.get('lyric_index')
        # 连续转调识别与不确定调性保护：修改字外音为实际时间重叠，跨区域长音也需保留；原代码保留。
        # region=next((r for r in regions if (r['first_character_index']<=index<=r['last_character_index'] if index is not None else r['start_seconds']<=note['start_seconds']<r['end_seconds'])),None)
        region=next((r for r in regions if (r['first_character_index']<=index<=r['last_character_index'] if index is not None else note['start_seconds']<r['end_seconds'] and note['end_seconds']>r['start_seconds'])),None)
        if region:
            note['tonality_guard']={'region_id':region['id'],'reason':region['reason'],'candidate_key':region['candidate_key']}
            note['chromatic_status']='tonality_uncertain_pitch_preserved'
            guarded.setdefault(region['id'],[]).append(note['id'])
            continue
        key=source_key_at(note,native_key,sections)
        if key["mode"]!="major" or (note["pitch_midi"]-key["tonic_pc"])%12 in MAJOR_INTERVALS:
            continue
        raw_cores=evidence.cores(note["start_seconds"],note["end_seconds"])
        cores=evidence.independent(raw_cores) if raw_cores else []
        explicit=strict_chromatic_evidence(note,cores,period)
        record={"piece_id":note["id"],"character_index":note.get("lyric_index"),"key":key["label"],
                "start_seconds":note["start_seconds"],"end_seconds":note["end_seconds"],
                "performance_pitch_midi":note["pitch_midi"],"platforms":cores,
                "strict_exception_minimum_seconds":max(.20,.50*period),"confidence_is_accuracy":False}
        if explicit:
            note["chromatic_status"]="stable_exception_retained"
            reviews.append(dict(record,type="stable_chromatic_exception_retained"))
            continue
        bridge=diatonic_glide_bridge(note,original,i,key,period)
        neighbours=[n for n in original[max(0,i-1):i+2] if n["id"]!=note["id"]
                    and n.get("lyric_index")==note.get("lyric_index")
                    and (n["pitch_midi"]-key["tonic_pc"])%12 in MAJOR_INTERVALS
                    and (n.get("confidence") or 0)>=.65 and n.get("stable_duration_seconds",0)>=.10]
        in_scale=[c for c in cores if (c["pitch_midi"]-key["tonic_pc"])%12 in MAJOR_INTERVALS
                  and abs(c["pitch_midi"]-note["pitch_midi"])<=2 and c["support"]>=.85
                  and c["end_seconds"]-c["start_seconds"]>=.10
                  and ((c.get("independent_agreement") or 0)>=.60 or any(n["pitch_midi"]==c["pitch_midi"] for n in neighbours))]
        if bridge:
            pitch=bridge["pitch_midi"];decision={"reason":"diatonic_glide_bridge",**bridge}
            for field in ("legato_target_piece_id","legato_source_piece_id"):
                if field in bridge:note[field]=bridge[field]
        elif in_scale:
            best=max(in_scale,key=lambda c:(c["end_seconds"]-c["start_seconds"])*c["support"])
            pitch=best["pitch_midi"];decision={"reason":"major_prior_with_stable_in_scale_platform","platform":best}
        else:
            pitch,decision=conservative_scale_choice(note,original,i,key,evidence)
            decision["reason"]="unproven_chromatic_omitted_from_readable_score"
        note["pitch_midi"]=pitch
        note["chromatic_status"]="omitted_from_score_preserved_in_review"
        note["notation_adjustment"]={"old_pitch_midi":record["performance_pitch_midi"],"new_pitch_midi":pitch,**decision}
        reviews.append(dict(record,type="tonal_prior_adjusted",notation_adjustment=note["notation_adjustment"]))
    # 连续转调识别与不确定调性保护：新增按区域汇总复核，避免将保音提示计作纠音。
    for region in regions:
        if region['id'] in guarded:
            reviews.append({'type':'tonality_uncertain_region','region_id':region['id'],'start_seconds':region['start_seconds'],'end_seconds':region['end_seconds'],'character_index':region['first_character_index'],'reason':region['reason'],'candidate_key':region['candidate_key'],'preserved_piece_ids':guarded[region['id']],'preserved_note_count':len(guarded[region['id']]),'forced_scale_correction':False})
    return output,reviews

# 大调约束与强拍先验：新增同字相邻同音归并，保留全部来源段；绝不跨字或跨原声停顿。
def merge_same_word(pieces):
    result = []
    for original in pieces:
        note = copy.deepcopy(original)
        if (result and note.get("lyric_index") is not None
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # and result[-1].get("lyric_index") == note["lyric_index"]
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            and result[-1].get("lyric_index") == note["lyric_index"]
            and result[-1].get("english_syllable_index") == note.get("english_syllable_index")
            and result[-1]["pitch_midi"] == note["pitch_midi"]
            and abs(result[-1]["end_seconds"] - note["start_seconds"]) <= .015):
            previous = result[-1]
            a = previous["end_seconds"] - previous["start_seconds"]; b = note["end_seconds"] - note["start_seconds"]
            previous["end_seconds"] = note["end_seconds"]
            previous["confidence"] = ((previous.get("confidence") or .3)*a + (note.get("confidence") or .3)*b)/(a+b)
            previous["anchor"] = previous.get("anchor") or note.get("anchor")
            previous["stable_duration_seconds"] = previous.get("stable_duration_seconds", 0) + note.get("stable_duration_seconds", 0)
            previous["independent_pitch_support"] = max(previous.get("independent_pitch_support") or 0, note.get("independent_pitch_support") or 0)
            previous["performance_segments"] += note["performance_segments"]
            # 调外音宁缺毋滥：新增滑音桥连奏来源转移，合并后仍指向真实相邻调内音。
            for field in ("legato_target_piece_id","legato_source_piece_id"):
                if note.get(field):previous[field]=note[field]

            previous.setdefault("notation_adjustments", []).extend(note.get("notation_adjustments", []) + ([note["notation_adjustment"]] if note.get("notation_adjustment") else []))
            previous["source_note_ids"] = list(dict.fromkeys(n["source_note_id"] for n in previous["performance_segments"]))
        else:
            result.append(note)
    return result

# 大调约束与强拍先验：新增强拍只是有限加分；必须有句间停顿、辅音/元音边界及微小时差证据。
def strong_beat_candidate(group, previous_end, character, mapping, timing):
    if timing["meter"] != [4, 4] or not character or character.get("start_seconds") is None:
        return None
    start = group[0]["start_seconds"]; period = 60/timing["steady_tempo_bpm"]
    if previous_end is not None and start-previous_end < PARAMETERS["phrase_gap_quarters"]*period:
        return None
    nuclei = [p["start_seconds"] for p in character.get("phonemes", [])
              if p.get("role") == "nucleus" and not p.get("skipped") and p.get("start_seconds") is not None]
    if not nuclei:
        return None
    nucleus = min(nuclei)
    q = mapping.seconds_to_quarters(start) - timing["score_start_quarter"]
    char_start = character["start_seconds"]; uncertainty_start = min(start, char_start)
    options = []
    for strong, bonus, kind in ((round(q/4)*4, PARAMETERS["downbeat_bonus_squared_quarters"], "downbeat"),
                               (round((q-2)/4)*4+2, PARAMETERS["third_beat_bonus_squared_quarters"], "third_beat")):
        seconds = mapping.quarters_to_seconds(strong + timing["score_start_quarter"])
        shift = abs(strong-q)
        if (shift > PARAMETERS["maximum_onset_shift_quarters"]
            or abs(seconds-nucleus)/period > PARAMETERS["nucleus_near_beat_quarters"]
            or not uncertainty_start-.04 <= seconds <= nucleus+.04):
            continue
        # 大调约束与强拍先验：新增与原拍格误差比较，轻量加分不压倒明确的弱拍证据。
        half = round(q*2)/2; quarter = round(q*4)/4
        normal = half if abs(q-half) <= .16 else quarter if abs(q-quarter) <= .09 else round(q*8)/8
        cost = (strong-q)**2-bonus
        if cost <= (normal-q)**2 and abs(strong-normal) > 1e-6:
            options.append((cost, {"quarter": strong, "kind": kind, "source_start_seconds": start,
                "notation_start_seconds": seconds, "nucleus_start_seconds": nucleus,
                "preceding_vocal_end_seconds": previous_end, "maximum_shift_quarters": PARAMETERS["maximum_onset_shift_quarters"],
                "prior_bonus": bonus, "method": "ambiguous_phrase_onset_soft_strong_beat_prior",
                "confidence_is_accuracy": False}))
    return min(options, key=lambda o:o[0])[1] if options else None

# 大调约束与强拍先验：新增模糊句首的起音手势归并与强拍标记；可靠转音/倚音不被归并。
def phrase_onsets(pieces, characters, mapping, timing):
    output = copy.deepcopy(pieces); by_char = defaultdict(list); reviews = []
    for n in output:
        if n.get("lyric_index") is not None:
            by_char[n["lyric_index"]].append(n)
    lookup = {c["index"]: c for c in characters}
    removed = set(); previous_end = None
    for index, group in sorted(by_char.items(), key=lambda item:item[1][0]["start_seconds"]):
        candidate = strong_beat_candidate(group, previous_end, lookup.get(index), mapping, timing)
        # 大调约束与强拍先验：新增明确的前导转音保护；有独立稳定平台的不同音不能仅凭后字元音搬到强拍。
        if candidate and len(group) >= 2:
            lead = group[0]; duration = lead["end_seconds"] - lead["start_seconds"]
            stable_lead = (lead.get("stable_duration_seconds",0) >= .10
                           # 大调约束与强拍先验：修正半数边界浮点误差，原除法保留；时长容差仅一纳秒。
                           # and lead.get("stable_duration_seconds",0)/duration >= .50
                           and lead.get("stable_duration_seconds",0)+1e-9 >= .50*duration
                           and (lead.get("independent_pitch_support") or 0) >= .70)
            if stable_lead and lead["pitch_midi"] != group[1]["pitch_midi"]:
                candidate = None
        if candidate:
            first = group[0]; chosen = first
            if len(group) >= 2:
                following = group[1]
                # 大调约束与强拍先验：新增只归并同源、低支持且无独立平台的句首滑入；稳定短主音继续保护。
                unstable = ((first.get("confidence") or 0) < .50 and first.get("stable_duration_seconds", 0) == 0
                            and (first.get("independent_pitch_support") or 0) < .20)
                reliable = (following.get("stable_duration_seconds", 0) >= .10
                            and (following.get("independent_pitch_support") or 0) >= .80)
                if (unstable and reliable and first["source_note_id"] == following["source_note_id"]
                    and abs(first["pitch_midi"] - following["pitch_midi"]) <= 2
                    and abs(first["end_seconds"] - following["start_seconds"]) <= .015
                    and first["end_seconds"] - first["start_seconds"] <= .90*60/timing["steady_tempo_bpm"]):
                    following["performance_segments"] = first["performance_segments"] + following["performance_segments"]
                    following["start_seconds"] = first["start_seconds"]
                    following["notation_onset_gesture"] = {"reason": "unstable_consonant_and_scoop_not_independent_note",
                        "absorbed_piece_id": first["id"], "performance_pitch_midi": first["pitch_midi"],
                        "notation_pitch_midi": following["pitch_midi"]}
                    removed.add(first["id"]); chosen = following
                    reviews.append(dict(type="unstable_onset_gesture_absorbed", character_index=index,
                        start_seconds=first["start_seconds"], end_seconds=following["end_seconds"],
                        performance_segments=following["performance_segments"], evidence=following["notation_onset_gesture"]))
            chosen["notation_onset_prior"] = candidate
            reviews.append(dict(type="phrase_strong_beat_prior_applied", character_index=index,
                piece_id=chosen["id"], start_seconds=chosen["start_seconds"], end_seconds=chosen["end_seconds"], evidence=candidate))
        previous_end = max(n["end_seconds"] for n in group)
    return [n for n in output if n["id"] not in removed], reviews

# 大调约束与强拍先验：新增用户确认的吞字标记；严格匹配同源原文，仅附加状态、不造时间。
def annotate_confirmed_elision(characters, annotations, source):
    output = copy.deepcopy(characters)
    if not annotations:
        return output
    if annotations.get("source_sha256") != source["sha256"]:
        raise ValueError("吞字确认来自不同人声，不能复用。")
    digest = hashlib.sha256("".join(c["text"] for c in output).encode("utf-8")).hexdigest()
    if annotations.get("canonical_text_sha256") != digest:
        raise ValueError("吞字确认原文或字序不匹配。")
    for item in annotations.get("characters", []):
        index = item["index"]
        if not 0 <= index < len(output) or output[index]["text"] != item["text"]:
            raise ValueError("吞字确认字索引不匹配。")
        if item.get("status") != "user_confirmed_elided" or item.get("confirmed_by") != "user":
            raise ValueError("只接受明确用户确认的吞字状态。")
        if output[index].get("start_seconds") is not None or output[index].get("end_seconds") is not None:
            raise ValueError("已定位的字不能标成未发声吞字。")
        output[index]["human_review"] = copy.deepcopy(item)
    return output
