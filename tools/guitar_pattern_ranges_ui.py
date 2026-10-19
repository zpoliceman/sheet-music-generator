"""多区间右手配置与网页完整成品：区间编辑、命名方案和当前页完整谱。"""
# 多区间右手配置与网页完整成品：新增页面，继续使用既有候选与真实谱面／声音接口。
import json


def editor_page(token):
    # 多区间右手配置与网页完整成品：新增多行范围、整套配置载入及实际完整导出内嵌区域。
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>吉他右手演奏型</title><link rel="stylesheet" href="/editor.css"><link rel="stylesheet" href="/ranges.css"></head><body><main>
<header><div><p class="eyebrow">吉他弹唱 · 4/4拍</p><h1>按小节安排右手演奏</h1><p class="subtitle">为不同小节设置演奏方式，保存后在这里阅读整谱、试听整曲。</p></div><a id="original-link" target="_blank" rel="noopener">查看原谱 ↗</a></header>
<section class="song-panel"><label>当前曲谱<select id="project" aria-label="当前曲谱"></select></label><span id="source-note">正在读取曲谱…</span></section>
<section class="configuration-panel" aria-label="配置方案"><div class="configuration-fields">
<label>已保存的配置<select id="configuration" aria-label="已保存的配置"><option value="">新配置</option></select></label>
<button id="load-configuration" class="secondary" disabled>载入配置</button><button id="new-configuration" class="secondary" disabled>新建配置</button>
<label>本套配置名称<input id="configuration-name" maxlength="80" placeholder="例如：主歌分解，副歌扫弦" aria-label="本套配置名称"></label>
</div><p id="configuration-note" class="help">同一首歌可保存多套配置；每次保存都另建曲谱版本。</p></section>
<section class="ranges-panel"><div class="section-heading"><h2>应用小节与演奏配置</h2><button id="add-range" class="secondary" disabled>＋ 添加小节区间</button></div>
<p class="help">按谱面小节号填写，包含起始和结束小节。点击一行编辑其右手型和时值；未选的范围沿用原奏。</p>
<div id="ranges" class="range-list" aria-label="小节区间列表"></div><p id="range-error" role="alert"></p></section>
<!-- 多区间右手配置与网页完整成品：新增始终可见的实际应用／保留说明，避免器乐例外藏在折叠信息中。 -->
<p id="applied-summary" class="application-summary" role="status">尚未选择右手型，沿用原奏。</p>
<div class="workspace"><aside><p id="active-range" class="active-range">选中一条区间</p>
<label>演奏方式<select id="family" aria-label="演奏方式"><option value="all">全部</option><option value="arpeggio">分解</option><option value="pinch">合拨</option><option value="strum">扫弦</option></select></label>
<!-- 右手候选悬停六线谱预览：保留旧下拉框代码，实际值继续由同一select传递，新增可悬停候选入口。 -->
<!-- <label>右手型<select id="pattern" aria-label="右手型"><option value="">保持原有演奏</option></select></label><p id="pattern-note" class="help">未选择时沿用当前曲谱。</p> -->
<div class="pattern-control"><label for="pattern-trigger">右手型</label><select id="pattern" aria-label="右手型" hidden tabindex="-1" aria-hidden="true"><option value="">保持原有演奏</option></select>
<button id="pattern-trigger" class="pattern-trigger" type="button" aria-haspopup="dialog" aria-expanded="false" aria-controls="pattern-popup" disabled><span>保持原有演奏</span><b aria-hidden="true">⌄</b></button><p class="pattern-hint">展开后移到名称上，先看六线谱。</p></div><p id="pattern-note" class="help">未选择时沿用当前曲谱。</p>
<!-- 右手候选悬停六线谱预览：新增候选旁的示意谱，悬停与键盘移动不改歌曲，点击才应用。 -->
<div id="pattern-popup" class="pattern-popup" role="dialog" aria-label="右手候选和六线谱预览" hidden>
<div class="pattern-list-panel"><div class="pattern-list-heading">移到名称上预览，点击名称应用。<br>触屏可先点名称，再点“应用此手型”。</div><div id="pattern-options" class="pattern-options" role="listbox" aria-label="右手候选"></div></div>
<section class="pattern-example" aria-labelledby="pattern-example-name"><div class="pattern-example-top"><span id="pattern-example-family" class="pattern-example-family">候选示意</span><button id="pattern-close" class="pattern-close" type="button" aria-label="关闭候选预览">×</button></div><h3 id="pattern-example-name">保持原有演奏</h3><p id="pattern-example-description" class="pattern-example-description"></p><div id="pattern-example-drawing" class="pattern-example-drawing"></div><p id="pattern-example-help" class="pattern-example-help"></p><button id="pattern-apply" class="pattern-apply" type="button">应用此手型</button></section></div>
<label>音符时值<select id="note-value" aria-label="音符时值"><option value="original">候选原节奏</option><option value="quarter">每格四分音符</option><option value="eighth">每格八分音符</option><option value="sixteenth">每格十六分音符</option></select></label>
<label>低音弦<select id="bass-mode" aria-label="低音弦"><option value="adaptive">随当前和弦低音</option><option value="fixed_5">B格固定拨第5弦</option></select></label>
<label>空位的演奏<select id="silence" aria-label="空位的演奏"><option value="ring">不拨／空扫，前音自然延续</option><option value="stop">消音休止</option></select></label>
<button id="reset" class="secondary">清空区间，恢复原奏</button><p class="help">仅改完整4/4演唱小节；器乐、真实停顿、弱起与短小节保留。重叠区间需要先调整。</p></aside>
<!-- 初始默认完整谱与歌词对照：保留旧工作区首行，新增默认谱；选择手型时原谱持续可见。 -->
<!-- <article><section class="rhythm-card"><div class="section-heading"><h2>这条区间的动作节奏</h2><span id="cycle">沿用原演奏</span></div><p class="help">数字为弦号，B为当前低音，+表示合拨；下／上表示扫弦。各格时值可单独修改。</p><div id="beat-grid" class="beat-grid"></div><p id="grid-error" role="alert"></p></section> -->
<!-- 右手选择后主谱实时可见更新：保留旧固定原谱标题，改为当前编配的主要显示区域。 -->
<!-- <article><section id="default-score-panel" class="score-card default-score-panel" aria-label="默认完整曲谱与歌词"> -->
<!-- <div class="section-heading"><h2>默认完整曲谱与歌词</h2><a id="default-score-link" target="_blank" rel="noopener">单独打开原谱 ↗</a></div> -->
<article><section id="default-score-panel" class="score-card default-score-panel" aria-label="当前曲谱与歌词">
<div class="section-heading"><h2>当前曲谱与歌词</h2><a id="default-score-link" target="_blank" rel="noopener">单独打开原谱对照 ↗</a></div>
<div class="default-score-controls"><label>定位小节<select id="default-measure" aria-label="定位默认谱小节" disabled></select></label><span id="default-score-status" role="status">正在读取默认曲谱…</span></div>
<!-- 右手选择后主谱实时可见更新：保留旧说明和标题，选型后同一主谱直接显示实际变化。 -->
<!-- <p class="help">对照歌词与小节号选择右手型；此处保留默认演奏，调整结果在下方局部预览中显示。可在谱内滚动查看整曲。</p> -->
<!-- <iframe id="default-score" title="默认完整吉他谱、歌词与小节号" src="about:blank"></iframe></section> -->
<p class="help">初始沿用默认演奏；选择手型或时值后，这份谱面会直接更新。完整曲谱可在框内滚动查看。</p>
<p id="visible-status" class="visible-status" role="status" aria-live="polite">正在读取当前曲谱…</p>
<div class="audio-panel current-audio"><button id="play" disabled>▶ 试听当前片段</button><audio id="audio" controls preload="auto"></audio><span id="audio-time"></span></div>
<iframe id="default-score" title="当前完整吉他谱、歌词与小节号" src="about:blank"></iframe></section>
<!-- 扫弦箭头与实际弦组记谱修正：保留旧说明，补充与真实TAB一致的箭头方向及跨度。 -->
<!-- <section class="rhythm-card"><div class="section-heading"><h2>这条区间的动作节奏</h2><span id="cycle">沿用原演奏</span></div><p class="help">数字为弦号，B为当前低音，+表示合拨；下／上表示扫弦。各格时值可单独修改。</p><div id="beat-grid" class="beat-grid"></div><p id="grid-error" role="alert"></p></section> -->
<section class="rhythm-card"><div class="section-heading"><h2>这条区间的动作节奏</h2><span id="cycle">沿用原演奏</span></div><p class="help">数字为弦号，B为当前低音，+表示合拨；下／上表示扫弦。谱中↑为下扫、↓为上扫，箭头跨过扫到的弦。各格时值可单独修改。</p><div id="beat-grid" class="beat-grid"></div><p id="grid-error" role="alert"></p></section>
<!-- 右手选择后主谱实时可见更新：保留旧展开局部区域，主谱旁已有变化与试听，局部放大改为可展开。 -->
<!-- <section class="score-card"><div class="section-heading"><h2>调整中的局部预览</h2><span id="status" role="status" aria-live="polite">准备中</span></div> -->
<details class="score-card local-score-details"><summary>展开局部放大与拍子定位</summary><div class="section-heading"><h2>当前片段</h2><span id="status" role="status" aria-live="polite">准备中</span></div>
<div class="preview-controls"><label>从小节预览<select id="preview-measure" aria-label="从小节预览"></select></label><span id="preview-range"></span></div>
<!-- 右手选择后主谱实时可见更新：保留旧局部播放器，实际播放器已移到主谱旁，避免选择后听不到变化。 -->
<!-- <div id="preview" class="score-view" aria-label="曲谱预览"></div><div class="audio-panel"><button id="play" disabled>▶ 试听这段</button><audio id="audio" controls preload="auto"></audio><span id="audio-time"></span></div> -->
<!-- <details><summary>本次应用与保留范围</summary><p id="scope-result"></p></details></section> -->
<div id="preview" class="score-view" aria-label="曲谱预览"></div>
<details><summary>本次应用与保留范围</summary><p id="scope-result"></p></details></details>
</article></div>
<section class="score-library" aria-label="吉他谱下载"><h2>下载吉他伴奏谱</h2><div class="score-mode-row"><label>导出版本<select id="print-source-mode" aria-label="导出版本"><option value="original">默认原谱</option><option value="saved" disabled>当前已保存版本</option></select></label><span>默认弹唱排版 · 原文件保留</span></div><div id="right-score-downloads"></div></section>
<section class="save-panel"><div><strong>保存配置，生成完整曲谱与音频</strong><p id="save-note">使用各条区间的设置另存整曲；原谱保留。</p></div><button id="save" disabled>保存并生成整曲</button><a id="saved-link" target="_blank" rel="noopener" hidden>单独打开新版本 ↗</a></section>
<section id="full-result" class="full-result" hidden aria-label="完整曲谱和整曲试听"><div class="section-heading"><h2 id="full-title">完整曲谱与整曲试听</h2><a id="reading-link" target="_blank" rel="noopener">打开反复阅读版 ↗</a></div><p id="full-note" role="status"></p>
<iframe id="full-score" title="完整吉他谱、原唱与伴奏播放器" src="about:blank"></iframe></section>
<!-- 右手候选悬停六线谱预览：新增独立样式和组件，原编辑器继续负责真实选择与保存。 -->
<link rel="stylesheet" href="/pattern-picker.css"><script src="/pattern-picker.js"></script>
</main><script>window.EDITOR_TOKEN='''+json.dumps(token)+''';</script><link rel="stylesheet" href="/score-downloads.css"><script src="/score-downloads.js"></script><script src="/ranges.js"></script><script src="/right-score-downloads.js"></script></body></html>'''
