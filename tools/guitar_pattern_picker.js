/* 右手候选悬停六线谱预览：使用原候选数据绘制只读示意，确认选择时仍交给原编辑器应用。 */
(function (global) {
  'use strict';
  const escape = text => String(text).replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  const families = {arpeggio:'分解', pinch:'合拨', strum:'扫弦'};
  const NS = 'http://www.w3.org/2000/svg';

  // 右手候选悬停六线谱预览：以常用C和弦说明弦组，六弦不弹，B和B2分别示例为五弦和四弦。
  function exampleStrings(token) {
    if (token === 'DA') return [5,4,3,2,1];
    if (token === 'DL') return [5,4,3];
    if (token === 'UH') return [1,2,3];
    if (token === '-' || token === '空') return [];
    return token.split('+').map(string => string === 'B' ? 5 : string === 'B2' ? 4 : Number(string));
  }

  function patternExample(pattern) {
    // 右手候选悬停六线谱预览：原节奏完整展示一小节，不读取歌曲、不修改选择、不请求编配。
    const top = 101, distance = 18, left = 62, right = 670;
    const x = tick => left + tick / 1920 * (right - left);
    const y = string => top + (string - 1) * distance;
    let svg = `<svg xmlns="${NS}" viewBox="0 0 710 290" role="img" aria-label="${escape(pattern.name)}，C和弦原节奏六线谱示意" data-example-pattern="${escape(pattern.id)}">`;
    svg += `<title>${escape(pattern.name)}：4/4拍，候选原节奏</title><rect width="710" height="290" fill="#fff"/>`;
    // 右手候选悬停六线谱预览：新增真实C指型图，为六线谱上的x提供明确的按弦依据。
    svg += '<g class="example-chord" stroke="#294b45" stroke-width="1.2"><text x="47" y="17" text-anchor="middle" stroke="none" font-size="17" font-weight="600">C</text>';
    for (let string = 0; string < 6; string++) svg += `<line x1="${22+string*10}" x2="${22+string*10}" y1="32" y2="80"/>`;
    for (let fret = 0; fret <= 3; fret++) svg += `<line x1="22" x2="72" y1="${32+fret*16}" y2="${32+fret*16}" stroke-width="${fret===0?3:1}"/>`;
    for (const [string, fret] of [[5,3],[4,2],[2,1]]) svg += `<circle cx="${22+(6-string)*10}" cy="${24+fret*16}" r="4.2" fill="#193e37" stroke="none"/>`;
    for (const string of [1,3]) svg += `<circle cx="${22+(6-string)*10}" cy="25" r="2.8" fill="white"/>`;
    svg += '<text x="22" y="28" text-anchor="middle" stroke="none" font-size="11">×</text></g>';
    svg += '<text x="102" y="32" fill="#375c51" font-size="17">4/4 · 一小节原节奏</text><text x="102" y="57" fill="#6b7e75" font-size="15">B＝5弦，B2＝4弦；x按左侧C指型拨弦</text>';
    for (let string = 1; string <= 6; string++) svg += `<g class="example-string" data-string="${string}"><text x="27" y="${y(string)+5}" font-size="15" fill="#6b7e75">${string}</text><line x1="46" x2="690" y1="${y(string)}" y2="${y(string)}" stroke="#9caea5" stroke-width="1"/></g>`;
    svg += `<line x1="46" x2="46" y1="${top}" y2="${y(6)}" stroke="#425e54"/><line x1="690" x2="690" y1="${top}" y2="${y(6)}" stroke="#425e54"/>`;
    for (let beat = 0; beat < 4; beat++) {
      const at = x(beat*480);
      svg += `<text class="example-beat" x="${at}" y="276" text-anchor="middle" fill="#6b7e75" font-size="15">${beat+1}</text>`;
      if (beat) svg += `<line x1="${at}" x2="${at}" y1="91" y2="249" stroke="#cbd7ce" stroke-dasharray="3 5" opacity=".6"/>`;
    }
    const events = pattern.events.map(event => ({...event, strings:exampleStrings(event.token)}));
    for (const event of events) {
      const at = x(event.onset_tick), strings = event.strings;
      svg += `<g class="example-action" data-token="${escape(event.token)}" data-kind="${escape(event.action)}" data-tick="${event.onset_tick}" data-duration="${event.action_span_ticks}" data-strings="${strings.join(',')}">`;
      if (event.action === 'strum') {
        // 右手候选悬停六线谱预览：沿用主谱规则，下扫箭头向上，上扫箭头向下，端点跨实际示例弦组。
        const high = y(Math.min(...strings)), low = y(Math.max(...strings));
        const up = event.token !== 'UH', tail = up ? low : high, tip = up ? high : low;
        const back = tip + (up ? 7 : -7);
        svg += `<line class="strum-shaft" x1="${at}" x2="${at}" y1="${tail}" y2="${tip}" stroke="#204f42" stroke-width="2.3"/><polyline class="strum-head" points="${at-5},${back} ${at},${tip} ${at+5},${back}" fill="none" stroke="#204f42" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>`;
      } else if (strings.length) {
        for (const string of strings) svg += `<rect x="${at-7}" y="${y(string)-9}" width="14" height="18" fill="white"/><text class="example-note" data-string="${string}" x="${at}" y="${y(string)+5}" text-anchor="middle" font-size="21" fill="#204f42">x</text>`;
        if (event.action === 'pinch') svg += `<text x="${at}" y="86" text-anchor="middle" font-size="13" fill="#4b7566">合</text>`;
      } else {
        svg += `<rect x="${at-11}" y="136" width="22" height="23" fill="white"/><text x="${at}" y="153" text-anchor="middle" font-size="17" fill="#788c80">${event.token === '空' ? '空' : '延'}</text>`;
      }
      // 右手候选悬停六线谱预览：保留初拟每动作一根节奏竖线，长音改在下方按拍拆分，实际拨弦仍只画一次。
      // svg += `<line class="example-stem" x1="${at}" x2="${at}" y1="204" y2="238" stroke="${strings.length?'#375b4e':'#8d9f93'}" stroke-width="1.4"${strings.length?'':' stroke-dasharray="3 3"'}/>`;
      if (event.action_span_ticks > 480) {
        const end=x(event.onset_tick+event.action_span_ticks)-8;
        svg += `<path class="example-long-hold" d="M ${at+7} 91 Q ${(at+7+end)/2} 81 ${end} 91" fill="none" stroke="#6f8b7a" stroke-width="1.2"/><text x="${(at+7+end)/2}" y="83" text-anchor="middle" font-size="12" fill="#6f8b7a">${event.action_span_ticks/480}拍延续</text>`;
      }
      svg += '</g>';
    }
    // 右手候选悬停六线谱预览：长动作按每拍分组记时值，后续竖线是持续时值，不新增x或扫弦箭头。
    const rhythms=[];
    for(const event of events){
      let tick=event.onset_tick, end=tick+event.action_span_ticks;
      while(tick<end){
        const span=Math.min(end-tick,480-tick%480);
        rhythms.push({onset_tick:tick,action_span_ticks:span});
        const at=x(tick), continued=tick!==event.onset_tick, quiet=!event.strings.length;
        svg += `<line class="example-stem" data-tick="${tick}" data-duration="${span}" data-continuation="${continued}" x1="${at}" x2="${at}" y1="204" y2="238" stroke="${continued||quiet?'#8d9f93':'#375b4e'}" stroke-width="1.4"${quiet?' stroke-dasharray="3 3"' : ''}/>`;
        tick+=span;
      }
    }
    // 右手候选悬停六线谱预览：按实际起点与动作时值在每拍内连梁，混合八分／十六分保留第二道短梁。
    // 右手候选悬停六线谱预览：保留初拟直接按动作连梁的循环，改为按拆分后的实际拍格连梁。
    // for (let index = 0; index < events.length; index++) {
    //   const event = events[index];
    for (let index = 0; index < rhythms.length; index++) {
      const event = rhythms[index];
      if (event.action_span_ticks >= 480) continue;
      // 右手候选悬停六线谱预览：保留原动作相邻查询，改查完整节奏片段的相邻项。
      // const next = events[index+1], previous = events[index-1], at = x(event.onset_tick);
      const next = rhythms[index+1], previous = rhythms[index-1], at = x(event.onset_tick);
      const joined = next && next.action_span_ticks < 480 && Math.floor(next.onset_tick/480) === Math.floor(event.onset_tick/480);
      const joinedBefore = previous && previous.action_span_ticks < 480 && Math.floor(previous.onset_tick/480) === Math.floor(event.onset_tick/480);
      if (joined || !joinedBefore) svg += `<line class="example-beam" x1="${at}" x2="${joined?x(next.onset_tick):at+12}" y1="238" y2="238" stroke="#375b4e" stroke-width="3"/>`;
      if (event.action_span_ticks === 120) {
        const nextSixteenth = joined && next.action_span_ticks === 120;
        const previousSixteenth = joinedBefore && previous.action_span_ticks === 120;
        if (nextSixteenth || !previousSixteenth) svg += `<line class="example-beam-sixteenth" x1="${at}" x2="${nextSixteenth?x(next.onset_tick):at+(joinedBefore?-12:12)}" y1="245" y2="245" stroke="#375b4e" stroke-width="3"/>`;
      }
    }
    svg += '</svg>';
    return svg;
  }

  function attach(select) {
    // 右手候选悬停六线谱预览：保留原select为唯一实际选择值，列表悬停仅操作独立的示意面板。
    const $ = id => document.getElementById(id);
    const trigger = $('pattern-trigger'), popup = $('pattern-popup'), list = $('pattern-options');
    const cache = new Map();
    let catalogue = [], candidate = '', lastPointer = 'mouse';
    document.body.append(popup);
    const options = () => [...list.querySelectorAll('[role="option"]')];
    function preview(id) {
      candidate = id;
      const pattern = catalogue.find(row => row.id === id);
      $('pattern-example-name').textContent = pattern?.name || '保持原有演奏';
      $('pattern-example-family').textContent = pattern ? families[pattern.family]+' · 原节奏' : '沿用原谱';
      // 右手候选悬停六线谱预览：保留直接显示内部动作代号的初稿，改为用户能直接阅读的扫弦和延续名称。
      // $('pattern-example-description').textContent = pattern?.description || (pattern ? pattern.events.map(e=>e.token).join(' · ') : '此项会让当前区间继续使用原有演奏。');
      $('pattern-example-description').textContent = pattern?.description || (pattern ? pattern.events.map(e=>({DA:'下扫',DL:'下扫低弦',UH:'上扫高弦','-':'延续','空':'空扫'})[e.token]||e.token).join(' · ') : '此项会让当前区间继续使用原有演奏。');
      if (pattern && !cache.has(id)) cache.set(id, patternExample(pattern));
      $('pattern-example-drawing').innerHTML = pattern ? cache.get(id) : '<p class="pattern-empty">当前曲谱保持原来的右手演奏。</p>';
      $('pattern-example-help').textContent = pattern ? 'C和弦示意；实际低音随和弦适配。空／延处不重新拨弦，前音自然延续。选中后可调整时值与消音。' : '鼠标移到候选名称即可先看六线谱，点击名称或下方按钮才应用。';
      $('pattern-apply').textContent = pattern ? '应用此手型' : '保持原有演奏';
      for (const option of options()) option.classList.toggle('is-previewing', option.dataset.patternId === id);
    }
    function sync() {
      trigger.disabled = select.disabled;
      trigger.querySelector('span').textContent = select.selectedOptions[0]?.textContent || '保持原有演奏';
      for (const option of options()) option.setAttribute('aria-selected', String(option.dataset.patternId === select.value));
      if (select.disabled && !popup.hidden) close(false);
    }
    function position() {
      if (popup.hidden) return;
      const anchor = trigger.getBoundingClientRect(), margin = 12;
      const width = Math.min(820, innerWidth-2*margin);
      popup.style.width = width+'px';
      popup.style.maxHeight = Math.min(550, innerHeight-2*margin)+'px';
      const height = popup.getBoundingClientRect().height;
      const below = innerHeight-anchor.bottom-margin, above = anchor.top-margin;
      const top = below >= height || below >= above ? anchor.bottom+6 : anchor.top-height-6;
      popup.style.top = Math.max(margin, Math.min(innerHeight-height-margin, top))+'px';
      popup.style.left = Math.max(margin, Math.min(innerWidth-width-margin, anchor.left))+'px';
    }
    function close(focus = true) {
      popup.hidden = true; trigger.setAttribute('aria-expanded','false');
      if (focus) trigger.focus({preventScroll:true});
    }
    function focusOption(option) {
      if (!option) return;
      option.focus({preventScroll:true}); option.scrollIntoView({block:'nearest'}); preview(option.dataset.patternId);
    }
    function open() {
      if (select.disabled) return;
      popup.hidden = false; trigger.setAttribute('aria-expanded','true'); preview(select.value); position();
      focusOption(options().find(option => option.dataset.patternId === select.value) || options()[0]);
    }
    function commit() {
      if (select.disabled) return;
      const changed = select.value !== candidate;
      select.value = candidate; close(); sync();
      if (changed) select.dispatchEvent(new Event('change',{bubbles:true}));
    }
    function refresh(patterns) {
      catalogue = patterns; list.replaceChildren();
      for (const native of select.options) {
        const pattern = catalogue.find(row => row.id === native.value);
        const option = document.createElement('button'); option.type='button'; option.role='option'; option.tabIndex=-1;
        option.dataset.patternId = native.value; option.textContent = native.textContent;
        if (pattern) { const family=document.createElement('small');family.textContent=families[pattern.family];option.append(family); }
        option.addEventListener('pointerenter', event => { if(event.pointerType!=='touch') preview(native.value); });
        option.addEventListener('focus', () => preview(native.value));
        option.addEventListener('pointerdown', event => {lastPointer=event.pointerType;preview(native.value);});
        option.addEventListener('click', event => {preview(native.value);if(event.detail && lastPointer==='touch')return;commit();});
        list.append(option);
      }
      sync(); if(!popup.hidden){preview(select.value);position();}
    }
    trigger.addEventListener('click', () => popup.hidden ? open() : close());
    trigger.addEventListener('keydown', event => {if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();open();}});
    popup.addEventListener('keydown', event => {
      const all=options(), current=all.indexOf(document.activeElement);
      if(event.key==='Escape'){event.preventDefault();close();}
      else if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
        event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?all.length-1:Math.max(0,Math.min(all.length-1,current+(event.key==='ArrowDown'?1:-1)));focusOption(all[index]);
      } else if((event.key==='Enter'||event.key===' ') && current>=0){event.preventDefault();preview(all[current].dataset.patternId);commit();}
    });
    $('pattern-apply').addEventListener('click',commit);
    $('pattern-close').addEventListener('click',()=>close());
    document.addEventListener('pointerdown',event=>{if(!popup.hidden&&!popup.contains(event.target)&&!trigger.contains(event.target))close(false);});
    document.addEventListener('focusin',event=>{if(!popup.hidden&&!popup.contains(event.target)&&event.target!==trigger)close(false);});
    global.addEventListener('resize',position);
    global.addEventListener('scroll',()=>{if(!popup.hidden){const anchor=trigger.getBoundingClientRect();if(anchor.bottom<0||anchor.top>innerHeight)close(false);else position();}},true);
    new MutationObserver(sync).observe(select,{attributes:true,attributeFilter:['disabled']});
    select.addEventListener('change',sync); sync();
    return {refresh,sync,close};
  }

  // 右手候选悬停六线谱预览：导出纯绘图函数供实际候选读回检查，浏览器使用同一实现。
  const api = {attach,patternExample,exampleStrings};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  else global.GuitarPatternPicker=api;
})(typeof window !== 'undefined' ? window : globalThis);
