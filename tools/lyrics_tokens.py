"""第二首跨歌曲验证：保留原文，将明确的哼唱拼音标记视为一个歌词单位。"""
from __future__ import annotations
# 第二首跨歌曲验证：新增单位化与官方PFML输入，不将英文词伪造为汉字。
import html
import re
import unicodedata


VOCALIZATIONS = {"hu": [["h", "u"], ["u"]]}

# 第四首《日落大道》男声跨歌曲验证：新增常见歌唱读音候选，保留“的”原字，由模型选择de或di音素。
# 第四首《日落大道》男声跨歌曲验证：真实读音实验未恢复的字，停用默认扩展，保留实验定义供诊断。
# SINGING_READINGS = {"的": [["d", "e"], ["d", "i"]]}


# 中文版本冻结与英文融合验证：注释保留被替换的原实现。
# def text_units(text):
    # # 第二首跨歌曲验证：新增有限哼唱标记；未知英文仍逐字保留并由后端支持检查拒绝。
    # values = []
    # for part in re.findall(r"[A-Za-z]+|.", text, flags=re.S):
        # if part.lower() in VOCALIZATIONS:
            # values.append({"text": part, "kind": "vocalization", "pronunciation_candidates": VOCALIZATIONS[part.lower()]})
        # else:
            # # 第四首《日落大道》男声跨歌曲验证：修改字符单位携带可选歌唱读音，显示文字和数量不变；旧实现保留。
            # # values.extend({"text": c, "kind": "character"} for c in part
            # # if not c.isspace() and not unicodedata.category(c).startswith(("P", "S")))
            # for c in part:
                # if not c.isspace() and not unicodedata.category(c).startswith(("P", "S")):
                    # unit = {"text": c, "kind": "character"}
                    # # 第四首《日落大道》男声跨歌曲验证：回退未获益的读音字段，原实验代码保留。
                    # # if c in SINGING_READINGS:
                    # # unit["pronunciation_candidates"] = SINGING_READINGS[c]
                    # values.append(unit)
    # return values
# 中文版本冻结与英文融合验证：新增中英文兼容实现。
def text_units(text):
    # 中文版本冻结与英文融合验证：中文逐字、英文整词；内部撇号属于英文缩写，原文不改写。
    values = []
    for part in re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)*|.", text, flags=re.S):
        if part.lower() in VOCALIZATIONS:
            values.append({"text": part, "kind": "vocalization", "pronunciation_candidates": VOCALIZATIONS[part.lower()]})
        elif re.fullmatch(r"[A-Za-z]+(?:['’][A-Za-z]+)*", part):
            values.append({"text": part, "kind": "english_word", "language": "en"})
        elif not part.isspace() and not unicodedata.category(part).startswith(("P", "S")):
            values.append({"text": part, "kind": "character"})
    return values


# 第四首《日落大道》男声跨歌曲验证：修改PFML逐字显式候选，不把汉字换成同音代理；原函数注释保留。
# def tifa_pfml(text):
#     # 第二首跨歌曲验证：新增Hu的有声母/无声母候选交给模型选择，所有标签原样保留。
#     output = []
#     for part in re.findall(r"[A-Za-z]+|[^A-Za-z]+", text):
#         if part.lower() not in VOCALIZATIONS:
#             output.append(html.escape(part, quote=False))
#             continue
#         readings = ''.join('<reading>' + ''.join('<phoneme>' + p + '</phoneme>' for p in phones) + '</reading>'
#                            for phones in VOCALIZATIONS[part.lower()])
#         output.append('<word text="' + html.escape(part, quote=True) + '" language="zh">' + readings + '</word>')
#     return ''.join(output)

# 第四首《日落大道》男声跨歌曲验证：新增统一检测，普通文本不用PFML，明确变体交给模型。
# 中文版本冻结与英文融合验证：注释保留被替换的原实现。
# def requires_tifa_pfml(text):
    # # 第四首《日落大道》男声跨歌曲验证：回退未获益的字符读音自动注入，旧实验条件保留。
    # # return any(unit["kind"] == "vocalization" or unit["text"] in SINGING_READINGS for unit in text_units(text))
    # return any(unit["kind"] == "vocalization" for unit in text_units(text))
# 中文版本冻结与英文融合验证：新增中英文兼容实现。
def requires_tifa_pfml(text):
    # 中文版本冻结与英文融合验证：英文显式固定单词边界，Hu 保留已有汉语哼唱候选。
    return any(unit["kind"] in ("vocalization", "english_word") for unit in text_units(text))


# 中文版本冻结与英文融合验证：注释保留被替换的原实现。
# def tifa_pfml(text):
    # output = []
    # for part in re.findall(r"[A-Za-z]+|.", text, flags=re.S):
        # # 第四首《日落大道》男声跨歌曲验证：恢复仅Hu显式读音，未支持的汉字变体不默认注入。
        # # candidates = VOCALIZATIONS.get(part.lower()) or SINGING_READINGS.get(part)
        # candidates = VOCALIZATIONS.get(part.lower())
        # if not candidates:
            # output.append(html.escape(part, quote=False))
            # continue
        # readings = ''.join('<reading>' + ''.join('<phoneme>' + html.escape(p) + '</phoneme>' for p in phones) + '</reading>' for phones in candidates)
        # output.append('<word text="' + html.escape(part, quote=True) + '" language="zh">' + readings + '</word>')
    # return ''.join(output)
# 中文版本冻结与英文融合验证：新增中英文兼容实现。
def tifa_pfml(text):
    # 中文版本冻结与英文融合验证：PFML 只供发音前端；用户参考文本始终保留。
    output = []
    for part in re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)*|.", text, flags=re.S):
        candidates = VOCALIZATIONS.get(part.lower())
        if candidates:
            readings = ''.join('<reading>' + ''.join('<phoneme>' + html.escape(p) + '</phoneme>' for p in phones) + '</reading>' for phones in candidates)
            output.append('<word text="' + html.escape(part, quote=True) + '" language="zh">' + readings + '</word>')
        elif re.fullmatch(r"[A-Za-z]+(?:['’][A-Za-z]+)*", part):
            output.append('<word text="' + html.escape(part.replace('’', "'"), quote=True) + '" language="en"/>')
        else:
            output.append(html.escape(part, quote=False))
    return ''.join(output)


# 中文版本冻结与英文融合验证：仅英语匹配忽略大小写与撇号字形，中文身份仍严格核对。
def lyric_match_key(text):
    if re.fullmatch(r"[A-Za-z]+(?:['’][A-Za-z]+)*", text):
        return text.replace('’', "'").casefold()
    return text


# 中文版本冻结与英文融合验证：按实际文本选择语种，纯中文流程保持原设置。
def languages_for_text(text):
    units = text_units(text)
    languages = []
    if any(u['kind'] != 'english_word' for u in units):
        languages.append('zh')
    if any(u['kind'] == 'english_word' for u in units):
        languages.append('en')
    return languages or ['zh']


# 中文版本冻结与英文融合验证：ASR 只负责句窗；混合歌词自动识别，单语明确指定。
def asr_language_for_text(text):
    languages = languages_for_text(text)
    return languages[0] if len(languages) == 1 else 'auto'


# 中文版本冻结与英文融合验证：仅用于展示，英文单词之间留空格；中文原字序及规范原文不改动。
def readable_lyric_units(items):
    values = []
    previous_english = False
    for item in items:
        text = item.get('text', '') if isinstance(item, dict) else str(item)
        units = text_units(text)
        english = len(units) == 1 and units[0]['kind'] == 'english_word'
        if values and (english or previous_english):
            values.append(' ')
        values.append(text)
        previous_english = english
    return ''.join(values)
