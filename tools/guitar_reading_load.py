"""完整乐句与实际时长复用：从真实展开页和阅读页衡量书写收益与新增版面负担。"""
# 完整乐句与实际时长复用：新增显示层只读验收，不改变工程／时轴；面积不是音乐准确性的评分。
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def page_metrics(path):
    # 完整乐句与实际时长复用：新增回读实际整行SVG，叠词和完整变奏的宽高全部计入。
    rows=re.findall(r'<section class="score-row[^>]*>(.*?)</section>',Path(path).read_text('utf8'),re.S)
    roots=[]
    for row in rows:
        match=re.search(r'(<(?:\w+:)?svg\b.*</(?:\w+:)?svg>)',row,re.S)
        if not match: raise ValueError('实际阅读行缺少完整SVG')
        roots.append(ET.fromstring(match.group(1)))
    if not roots: raise ValueError('实际阅读页没有谱行')
    return {'rows':len(roots),'native_area':sum(float(s.get('width'))*float(s.get('height')) for s in roots),
        'native_height_sum':sum(float(s.get('height')) for s in roots),
        'tab_attacks':sum(bool(n.get('data-string')) for s in roots for n in s.iter())}


def assess_printed_reading_load(folder, plan):
    # 完整乐句与实际时长复用：新增独立面积检查；先按整谱归一化，再扣除新增面积，不能只报候选省了几小节。
    # 这是阅读启发式：多遍歌词可能使面积略增，只有增加比例低于省掉的重复TAB比例才接受。
    result={'version':1,'scope':'actual_tab_saving_and_svg_area_not_whole_music_certification',
        'policy':'saved_tab_fraction_must_exceed_added_native_area_fraction','errors':[]}
    try:
        folder=Path(folder)
        full=page_metrics(folder/'score_full.html'); reading=page_metrics(folder/'score.html')
        saved=(full['tab_attacks']-reading['tab_attacks'])/max(1,full['tab_attacks'])
        extra=max(0.,reading['native_area']/full['native_area']-1.)
        result.update(full=full,reading=reading,saved_tab_fraction=saved,extra_area_fraction=extra,
                      actual_reading_gain=saved-extra)
        if plan['repeat_groups'] and saved-extra<=0:
            result['errors'].append('actual_layout_cost_exceeds_saved_tab')
    except (ValueError, OSError, ET.ParseError, TypeError, ZeroDivisionError) as exc:
        result['errors'].append('actual_reading_comparison_unavailable:'+str(exc))
    result['valid']=not result['errors']
    return result
