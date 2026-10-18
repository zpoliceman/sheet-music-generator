"""节奏符号说明与声部对齐：使用实际六线谱绘图函数生成读谱图例。"""
# 节奏符号说明与声部对齐：新增4/4拍符号说明，左右短钩不表示扫弦方向。
import xml.etree.ElementTree as ET
from guitar_rhythm_beams import rhythm_events, draw_rhythm

NS = '{http://www.w3.org/2000/svg}'
EXAMPLES = [
    ('单竖线', '四分音符 · 1拍', [(0, 480)], [145], '没有短横线，也没有附点'),
    ('一条短横钩', '八分音符 · 每个半拍', [(0, 240), (720, 240)], [112, 190], '朝左或朝右，时值相同'),
    ('两条短横钩', '十六分音符 · 四分之一拍', [(0, 120)], [145], '数横线层数，不数朝向'),
    ('两根竖线相连', '两个八分音符 · 合计1拍', [(0, 240), (240, 240)], [112, 190], '每个音各半拍，分别拨弦'),
    ('两层横线相连', '四个十六分音符 · 合计1拍', [(0, 120), (120, 120), (240, 120), (360, 120)], [75, 122, 169, 216], '每个音各四分之一拍'),
    ('单竖线加实心点', '附点四分音符 · 1.5拍', [(0, 720)], [145], '1拍 + 半拍 = 1.5拍'),
    ('一条横线加实心点', '附点八分 + 十六分 · 合计1拍', [(0, 360), (360, 120)], [112, 190], '前音0.75拍，后音0.25拍'),
    ('下方空心小圆', '二分音符 · 2拍', [(0, 960)], [145], '长音提示，与右侧实心附点不同'),
]


# 节奏符号说明与声部对齐：新增原生SVG图例，复用真实符干/横梁/附点形状，不借用异样符号。
def rhythm_guide_svg():
    root = ET.Element(NS + 'svg', {'width': '1160', 'height': '368', 'viewBox': '0 0 1160 368',
                                   'role': 'img', 'aria-label': '4/4拍六线谱节奏符号与拍数图例'})
    ET.SubElement(root, NS + 'rect', {'width': '1160', 'height': '368', 'fill': 'white'})
    title = ET.SubElement(root, NS + 'title'); title.text = '4/4拍：四分音符为一拍；x示意起音位置'

    def text(parent, x, y, value, size=17, color='#263d54'):
        node = ET.SubElement(parent, NS + 'text', {'x': str(x), 'y': str(y), 'font-size': str(size),
                             'font-family': 'Microsoft YaHei, SimHei, sans-serif', 'fill': color,
                             'text-anchor': 'middle', 'dominant-baseline': 'middle'})
        node.text = value

    for index, (name, beats, pattern, centers, caption) in enumerate(EXAMPLES):
        panel = ET.SubElement(root, NS + 'g', {'class': 'rhythm-legend-example',
                              'transform': f'translate({index % 4 * 290},{index // 4 * 182})'})
        ET.SubElement(panel, NS + 'rect', {'x': '6', 'y': '6', 'width': '278', 'height': '170',
                      'rx': '10', 'fill': '#f8fafc', 'stroke': '#dbe4ed'})
        text(panel, 145, 27, name, 20); text(panel, 145, 53, beats, 15, '#205a98')
        notes = [{'id': f'legend{index}_n{i}', 'start_tick': tick, 'end_tick': tick + duration}
                 for i, (tick, duration) in enumerate(pattern)]
        x_at = dict(zip([p[0] for p in pattern], centers))
        for center in centers: text(panel, center, 80, 'x', 20)
        symbols = ET.SubElement(panel, NS + 'g', {'transform': 'translate(0,-238)'})
        for node in draw_rhythm(rhythm_events(notes, (4, 4), 1920), x_at.__getitem__):
            for descendant in node.iter():
                if descendant.get('id'): descendant.set('id', f'legend{index}-' + descendant.get('id'))
            symbols.append(node)
        text(panel, 145, 151, caption, 14, '#62757c')
    return ET.tostring(root, encoding='unicode')


# 节奏符号说明与声部对齐：新增详细读谱正文，附点时值取决于本身横线层数。
def rhythm_guide_content():
    return '<p>以下按4/4拍说明：四分音符为1拍。一小节合计4拍。图例截取六线谱下方的节奏部分，x示意每次拨弦的位置。</p>' + rhythm_guide_svg() + (
        '<p><b>单竖线</b>是符干；没有横线或附点时，本谱通常表示四分音符，即1拍。'
        '<b>一条短横钩</b>表示八分音符，即半拍；<b>两条</b>表示十六分音符，即四分之一拍。'
        '短横钩向左或向右只用于安排空间，含义相同。扫弦方向另用↓和↑表示。</p>'
        '<p><b>横线连起的竖线</b>仍表示分别起音；不是把它们合成一个长音。'
        '同一拍中，两个八分音符用一层横线相连，每个半拍；四个十六分音符用两层，每个四分之一拍。'
        '八分与十六分混合时，一层横线覆盖该组，第二层只覆盖十六分音符；不能把整组都读成同一时值。</p>'
        '<p><b>右侧实心点</b>叫附点，增加原时值的一半：四分加点为1.5拍，八分加点为0.75拍，'
        '十六分加点为0.375拍。图中的附点八分加十六分为0.75 + 0.25 = 1拍。'
        '这与简谱数字上方或下方表示八度的点不同，也与符干下方的空心长音提示不同。</p>'
        '<p><b>沿弦的细横线</b>表示让之前的音继续响，与弦下粗节奏横线分开读。'
        '同一竖列有数根弦的x或品数时，同时合拨，共用一个节奏符干；如果各弦持续长度不同，'
        # 规整分解节奏与延音显示：修改，旧最短持续值说明保留；明确普通伴奏按右手拍格读。
        # '共用符干显示本次新起音中较短音的基本时值，较长延音继续看弦上的细线。</p>'
        '普通分解的共用符干显示右手拨弦拍格，低音可以在下一次高音拨弦时继续响；'
        '独奏及特征填句按各自时值读，实际延音继续看弦上的细线。'
        '小节开头括号内品数和细线表示上一小节的音继续响，无需重新拨弦。</p>'
        '<p><b>上下声部对齐</b>：简谱主音、休止、长音横线与六线谱按同一记谱拍点定位；'
        '同一时刻起音落在同一竖列。简谱的小号倚音按惯例写在主音左前方，不额外增加拍数；'
        '不同时间的起音按自己的拍点读，不把每拍的第一个音强行对齐。</p>'
    )
