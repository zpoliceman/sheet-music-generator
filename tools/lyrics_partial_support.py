"""连续转调识别与不确定调性保护：混合语言歌词安全降级，支持段真实对齐，未支持段不补造时间。"""
# 连续转调识别与不确定调性保护：新增后端范围隔离，不将英文伪装成普通话音素。
import copy

def unsupported_lines(preflight,reference):
    # 连续转调识别与不确定调性保护：仅允许隔离已知语言限制；异常时间和全曲无支持文本仍拒绝。
    issues=preflight.get('issues',[])
    if any(i['type']!='mandarin_backend_unsupported_latin_text' for i in issues):raise ValueError('歌词文本或识别时间需先复核；不能跳过时间异常。')
    lines={i['line_index'] for i in issues}
    if lines and len(lines)==len(reference['lines']):raise ValueError('当前普通话后端不能对齐全英文歌词。')
    return lines

def supported_plan(plan,blocked):
    # 连续转调识别与不确定调性保护：整窗含不支持语言时暂缓，不以均分或剪词冒充逐字边界。
    result=copy.deepcopy(plan);unaligned=set(blocked)
    for job in result['jobs']:
        if blocked.intersection(job['line_indices']):
            job['status']='unassigned_unsupported_language';job['warnings']=list(dict.fromkeys(job.get('warnings',[])+['backend_unsupported_text']))
            unaligned.update(job['line_indices'])
    result['unsupported_language_line_indices']=sorted(blocked)
    result['backend_unaligned_line_indices']=sorted(unaligned)
    return result

def mark_unsupported_characters(chars,plan):
    # 连续转调识别与不确定调性保护：保留完整原文/字序，未定位时间与音素明确为空。
    lines=set(plan.get('backend_unaligned_line_indices',[]))
    for char in chars:
        if char['line_index'] in lines:
            char.update(start_seconds=None,end_seconds=None,method='unsupported_language_unaligned',group_id=None,phonemes=[])
            char['warnings']=list(dict.fromkeys(char.get('warnings',[])+['backend_unsupported_text']))
    return chars
