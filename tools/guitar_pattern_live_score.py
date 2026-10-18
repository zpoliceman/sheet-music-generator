"""右手选择后主谱实时可见更新：完整当前谱使用实际编译音符及统一渲染。"""
# 右手选择后主谱实时可见更新：新增展示适配，不重识别音乐，不改写认可谱及已保存版本。
import xml.etree.ElementTree as ET


def render_live_score(project):
    # 右手选择后主谱实时可见更新：新增与整曲出口相同的小节分行／SVG，保证歌词和全部未选范围一起显示。
    from accompaniment_analysis import SongClock
    from export_timing_revision import render_row
    from guitar_repeat_readability import reading_line_end
    from guitar_variable_repeat import measure_timeline
    rows = measure_timeline(project)
    blocks = [rows[:1]] if rows[0]['pickup'] else []
    regular = rows[1:] if rows[0]['pickup'] else rows
    cursor = 0
    while cursor < len(regular):
        last = reading_line_end(project['arrangements']['guitar'], regular[cursor]['number'], regular[-1]['number'])
        finish = cursor+last-regular[cursor]['number']+1
        blocks.append(regular[cursor:finish]);cursor = finish
    clock, output = SongClock(project['accepted_vocal_project']), []
    offset = int(rows[0]['pickup'])
    for block in blocks:
        first, last = block[0]['number'], block[-1]['number']
        svg = render_row(project, block, guitar=True)
        width = ET.fromstring(svg).get('width')
        label = '弱起' if first == last == 1 and offset else f'第{first-offset}–{last-offset}小节'
        output.append(f'<section class="score-row guitar-score-row" data-first-measure="{first}" data-last-measure="{last}" '
                      f'style="overflow-x:auto;--score-native-width:{width}"><header>{label} · '
                      f'{clock.seconds(block[0]["start_tick"]):.2f}秒</header>{svg}</section>')
    return ''.join(output)
