"""第二首跨歌曲验证：在普通话强制对齐前拦截不支持的文本和不可能的识别时间。"""
from __future__ import annotations

# 第二首跨歌曲验证：新增轻量检查，无GPU推理、不删除字符、不把分数当正确率。
import math
import re
import unicodedata
# 第二首跨歌曲验证：新增哼唱单位接口，有限Hu标记可由真实普通话音素对齐。
from lyrics_tokens import text_units


def lyric_characters(text):
    # 第二首跨歌曲验证：修改，原字母逐字计数保留；Hu按一个单位计数。
    # return [c for c in text if not c.isspace() and not unicodedata.category(c).startswith(("P", "S"))]
    return [unit["text"] for unit in text_units(text)]


def check_mandarin_reference(reference, anchor=None):
    # 第二首跨歌曲验证：新增后端能力检查；实际英文歌词也保留，要求换后端或校正后再对齐。
    issues = []
    for index, line in enumerate(reference["lines"]):
        # 第二首跨歌曲验证：修改，原全英文拒绝条件保留；仅明确哼唱词可通过。
        # if re.search(r"[A-Za-z]", line):
        if any(re.search(r"[A-Za-z]", unit["text"]) and unit["kind"] != "vocalization" for unit in text_units(line)):
            issues.append({"type": "mandarin_backend_unsupported_latin_text", "line_index": index,
                           "text": line, "action": "保留原文；当前普通话TIFA后端不能对齐英文，需人工复核或多语言后端。"})
    if reference.get("reference_kind") == "asr_unverified" and anchor is not None:
        # 第二首跨歌曲验证：新增仅检查实际作为歌词使用的识别段，用户校正文本不受旧锚点幻觉影响。
        expected = {"".join(lyric_characters(line)) for line in reference["lines"]}
        duration = float(anchor["source"]["duration_seconds"])
        for segment in anchor["result"]["segments"]:
            chars = lyric_characters(segment["text"])
            if not chars or "".join(chars) not in expected:
                continue
            start, end = float(segment["start"]), float(segment["end"])
            reasons = []
            if not math.isfinite(start) or not math.isfinite(end) or end <= start or start < 0 or end > duration + .1:
                reasons.append("invalid_asr_segment_time")
            elif len(chars) >= 12 and len(chars) / (end - start) > 20:
                reasons.append("asr_impossible_character_density")
            if reasons:
                issues.append({"type": "asr_text_time_requires_review", "segment_id": segment.get("id"),
                               "start_seconds": start, "end_seconds": end, "text": segment["text"],
                               "character_count": len(chars), "reasons": reasons,
                               "action": "保留原始识别；先复核文本/时间，不强行把它塞进音符。"})
    return {"status": "ready_for_unverified_alignment" if not issues else "text_review_required",
            "valid_for_mandarin_tifa": not issues, "issues": issues,
            "text_changed": False, "musical_accuracy_verified": False,
            "scope": "后端支持范围和明显时间异常检查；通过不代表歌词正确。"}


# 中文版本冻结与英文融合验证：新增多语言预检，保留原普通话专用检查供历史调用。
def check_multilingual_reference(reference, anchor=None):
    report = check_mandarin_reference(reference, anchor)
    issues = [i for i in report['issues'] if i['type'] != 'mandarin_backend_unsupported_latin_text']
    for index, line in enumerate(reference['lines']):
        unsupported = [u['text'] for u in text_units(line) if u['kind'] == 'character'
                       and not ('㐀' <= u['text'] <= '鿿')]
        if unsupported:
            issues.append({'type': 'unsupported_lyrics_script', 'line_index': index,
                           'text': line, 'unsupported_units': unsupported,
                           'action': '保留原文；目前仅实现普通话汉字、哼唱标记和英文单词。'})
    from lyrics_tokens import languages_for_text
    return {**report, 'issues': issues, 'valid_for_multilingual_tifa': not issues,
            'status': 'ready_for_unverified_alignment' if not issues else 'text_review_required',
            'languages': languages_for_text('\n'.join(reference['lines'])),
            'scope': '中英文前端支持及明显时间异常检查；通过不代表音乐准确率。'}
