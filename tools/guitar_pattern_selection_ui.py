"""4/4可选右手与实时谱面试听：编辑页面及另存版本的演奏者说明。"""
# 4/4可选右手与实时谱面试听：新增产品页面，只展示演奏和范围选项，不把内部验收字段放进操作流程。
from pathlib import Path
import html
import json


def selection_guide(project):
    # 4/4可选右手与实时谱面试听：新增真实段落循环记忆表，完整谱和折叠谱共用。
    state = project['right_hand_selection']
    from guitar_variable_repeat import measure_timeline
    offset=int(measure_timeline(project)[0]['pickup'])
    rows = []
    for section in state['sections']:
        if not section['arranged_measures']:
            continue
        choice = section['choice']
        cells = ' · '.join(e['token'] for e in choice['template']['events'])
        measures = section['arranged_measures']
        rows.append('<tr><td>第'+str(measures[0]-offset)+'–'+str(measures[-1]-offset)+'小节</td><td>'+html.escape(choice['template']['name'])+
            '</td><td>'+html.escape(cells)+'</td><td>'+format(choice['cycle_ticks']/480,'g')+'拍循环</td></tr>')
    # 扫弦箭头与实际弦组记谱修正：停用相反方向图例，明确TAB箭头方向及实际扫弦范围。
    # return ('<section class="vocal-pattern-guide"><h2>演唱伴奏 · 已选右手型</h2>'
    #     '<p>B＝随当前和弦确定的低音弦；+＝同时合拨；↓／↑＝下扫／上扫；空＝不触弦并保留余音；止＝消音。'
    return ('<section class="vocal-pattern-guide"><h2>演唱伴奏 · 已选右手型</h2>'
        # 扫弦延音简化与右手候选扩充：保留旧单低音图例，新增交替低弦B2的演奏说明。
        # '<p>B＝随当前和弦确定的低音弦；+＝同时合拨；↑＝下扫，↓＝上扫，箭头横跨实际扫到的弦；空＝不触弦并保留余音；止＝消音。'
        '<p>B＝随当前和弦确定的低音弦；B2＝另一条可用低弦；+＝同时合拨；↑＝下扫，↓＝上扫，箭头横跨实际扫到的弦；空＝不触弦并保留余音；止＝消音。'
        # 扫弦延音简化与右手候选扩充：保留旧统一弧线说明，改为扫弦自然余音默认省略、明确延续集中提示。
        # '音符下方弧线表示持续，动作节奏与实际余音分别阅读。</p><table><tr><th>范围</th><th>类型</th><th>循环</th><th>长度</th></tr>'+
        '普通扫弦默认自然延续，不逐弦画延音线；空扫、停拨或较长保持只在TAB上方集中提示。'
        '分解／合拨保留必要的逐弦弧线，动作节奏与实际余音分别阅读。</p><table><tr><th>范围</th><th>类型</th><th>循环</th><th>长度</th></tr>'+
        ''.join(rows)+'</table><p>本版为用户选择的右手改编，沿用原拍轴与和弦。</p></section>')


def saved_index(project, output, source):
    # 4/4可选右手与实时谱面试听：新增另存交付入口，复制的非吉他谱仍按原成品阅读。
    from accompaniment_export import html_page, relative_url
    links = '<p><a href="guitar/score.html">查看修改后的吉他谱与试听</a></p>'
    for name, label in (('vocal','原有人声简谱'),('piano','原有钢琴谱')):
        if (output/name/'score.html').is_file():
            links += '<p><a href="'+name+'/score.html">'+label+'</a></p>'
    body = '<h1>'+html.escape(project['accepted_vocal_project']['title'])+' · 右手演奏型新版本</h1>'
    body += '<p>已另存本次选择。<a id="original-score-link" href="'+html.escape(relative_url(source.parent/'index.html',output))+'">原曲谱</a></p>'
    body += links+selection_guide(project)
    (output/'index.html').write_text(html_page('右手演奏型新版本',body),encoding='utf-8')


def editor_page(token):
    # 4/4可选右手与实时谱面试听：新增本机编辑界面，选择后自动预览，保存绑定当前预览。
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>吉他右手演奏型</title><link rel="stylesheet" href="/editor.css"></head><body><main>
<header><div><p class="eyebrow">吉他弹唱 · 4/4拍</p><h1>选择右手，听见变化</h1><p class="subtitle">在当前和弦与拍子上试奏，满意后另存新版本。</p></div><a id="original-link" target="_blank">查看原谱 ↗</a></header>
<section class="song-panel"><label>当前曲谱<select id="project" aria-label="当前曲谱"></select></label><span id="source-note">正在读取曲谱…</span></section>
<div class="workspace"><aside><label>应用范围<select id="scope" aria-label="应用范围"><option value="all">全部演唱段</option></select></label>
<label>演奏方式<select id="family" aria-label="演奏方式"><option value="all">全部</option><option value="arpeggio">分解</option><option value="pinch">合拨</option><option value="strum">扫弦</option></select></label>
<label>右手型<select id="pattern" aria-label="右手型"><option value="">保持原有演奏</option></select></label><p id="pattern-note" class="help">未选择时沿用当前曲谱。</p>
<label>音符时值<select id="note-value" aria-label="音符时值"><option value="original">候选原节奏</option><option value="quarter">每格四分音符</option><option value="eighth">每格八分音符</option><option value="sixteenth">每格十六分音符</option></select></label>
<label>低音弦<select id="bass-mode" aria-label="低音弦"><option value="adaptive">随当前和弦低音</option><option value="fixed_5">B格固定拨第5弦</option></select></label>
<label>空位的演奏<select id="silence" aria-label="空位的演奏"><option value="ring">不拨／空扫，前音自然延续</option><option value="stop">消音休止</option></select></label>
<button id="reset" class="secondary">恢复本次打开时的演奏</button><p class="help">仅修改完整4/4演唱小节；器乐、真实停顿和过渡小节保留。</p></aside>
<article><section class="rhythm-card"><div class="section-heading"><h2>按拍安排动作</h2><span id="cycle">沿用原演奏</span></div><p class="help">数字为弦号，B为当前低音，+表示合拨；下／上表示扫弦。各格时值可单独修改。</p><div id="beat-grid" class="beat-grid"></div><p id="grid-error" role="alert"></p></section>
<section class="score-card"><div class="section-heading"><h2>当前曲谱预览</h2><span id="status" role="status" aria-live="polite">准备中</span></div>
<div class="preview-controls"><label>从小节预览<select id="preview-measure" aria-label="从小节预览"></select></label><span id="preview-range"></span></div>
<div id="preview" class="score-view" aria-label="曲谱预览"></div><div class="audio-panel"><button id="play" disabled>▶ 试听这段</button><audio id="audio" controls preload="auto"></audio><span id="audio-time"></span></div>
<details><summary>本次应用与保留范围</summary><p id="scope-result"></p></details></section>
<section class="save-panel"><div><strong>保存当前选择</strong><p>生成完整吉他谱和试听，另存新版本。</p></div><button id="save" disabled>另存新版本</button><a id="saved-link" target="_blank" hidden>打开新版本 ↗</a></section>
</article></div></main><script>window.EDITOR_TOKEN='''+json.dumps(token)+''';</script><script src="/editor.js"></script></body></html>'''
