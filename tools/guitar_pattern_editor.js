/* 4/4可选右手与实时谱面试听：新增选择、逐格时值、最新请求、试听定位及绑定预览另存。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {catalogue:[], project:null, projectId:'', overrides:new Map(), current:null, durations:null,
    sequence:0, timer:null, controller:null, preview:null, saving:false, marks:[], frame:0};
  const token = window.EDITOR_TOKEN;
  // 4/4可选右手与实时谱面试听：新增曲谱来源加载期间禁用编辑，避免早期选择使范围信息变成过期结果。
  function loading(value){
    for(const id of ['scope','family','pattern','note-value','bass-mode','silence','preview-measure','reset'])$(id).disabled=value;
  }
  loading(true);
  const labels = {120:'十六分',240:'八分',360:'附点八分',480:'四分',720:'附点四分',960:'二分',1440:'附点二分',1920:'全音符'};
  const message = (text, error=false) => { $('status').textContent=text; $('status').dataset.error=String(error); };
  async function api(path, body, signal) {
    const response = await fetch(path, {method:body ? 'POST':'GET', signal,
      headers:body ? {'Content-Type':'application/json','X-Editor-Token':token}:{}, body:body ? JSON.stringify(body):undefined});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '请求失败');
    return data;
  }
  function pattern() { return state.catalogue.find(p=>p.id===$('pattern').value); }
  function choice() {
    if (!$('pattern').value) return null;
    return {pattern_id:$('pattern').value,note_value:$('note-value').value,bass_mode:$('bass-mode').value,
      silence:$('silence').value, durations:state.durations ? [...state.durations]:null};
  }
  function storeChoice() { state.overrides.set($('scope').value, choice()); }
  function plan() {
    return {version:1, default:state.overrides.get('all') || null,
      sections:[...state.overrides].filter(([key])=>key!=='all').map(([section_id,value])=>({section_id,choice:value}))};
  }
  function invalidate() {
    state.sequence++; state.preview=null; $('save').disabled=true; $('play').disabled=true;
    $('audio').pause(); $('audio').removeAttribute('src'); $('audio').load();
    $('saved-link').hidden=true; cancelAnimationFrame(state.frame);
    for (const mark of state.marks) mark.remove(); state.marks=[];
    if (state.controller) state.controller.abort();
    clearTimeout(state.timer);
  }
  function availablePatterns() {
    const previous=$('pattern').value;
    $('pattern').replaceChildren(new Option('保持原有演奏',''));
    const family=$('family').value;
    for (const p of state.catalogue) if(family==='all'||p.family===family)
      $('pattern').add(new Option(p.name,p.id));
    // 4/4可选右手与实时谱面试听：新增筛选列表时保留当前选择，筛选本身不撤销已选音乐。
    if(previous&&![...$('pattern').options].some(o=>o.value===previous)){
      const current=state.catalogue.find(p=>p.id===previous);if(current)$('pattern').add(new Option('当前 · '+current.name,current.id));
    }
    if ([...$('pattern').options].some(o=>o.value===previous)) $('pattern').value=previous;
  }
  function setChoice(value) {
    $('family').value='all';availablePatterns();
    $('pattern').value=value?.pattern_id||''; $('note-value').value=value?.note_value||'original';
    $('bass-mode').value=value?.bass_mode||'adaptive';$('silence').value=value?.silence||'ring';
    state.durations=value?.durations?[...value.durations]:null;drawGrid();
  }
  function drawGrid() {
    const selected=pattern();const grid=$('beat-grid');grid.replaceChildren();$('grid-error').textContent='';
    for(const option of $('note-value').options) option.disabled=!!selected&&!selected.uniform&&option.value!=='original';
    if(!selected){$('cycle').textContent='沿用原演奏';$('pattern-note').textContent='未选择时沿用当前曲谱。';return true;}
    if(!selected.uniform&&$('note-value').value!=='original')$('note-value').value='original';
    $('pattern-note').textContent=selected.uniform?'可以统一切换时值，也可逐格修改。':'此型包含混合时值；可逐格修改。';
    const uniform={quarter:480,eighth:240,sixteenth:120}[$('note-value').value];
    const spans=state.durations||selected.events.map(e=>uniform||e.action_span_ticks);
    let tick=0;
    selected.events.forEach((e,index)=>{
      const cell=document.createElement('div');cell.className='beat-cell'+(tick%480===0?' strong':'');
      const position=document.createElement('small');
      position.textContent=`${Math.floor(tick/1920)+1}小节 · ${Math.floor(tick%1920/480)+1}${tick%480?'+'+String((tick%480)/480):''}拍`;
      const text=document.createElement('strong');text.textContent=({DA:'下',DL:'下低',UH:'上高','-':'延'})[e.token]||e.token;
      const select=document.createElement('select');select.setAttribute('aria-label',`第${index+1}格时值`);
      for(const value of [120,240,480,960,1920])select.add(new Option(labels[value],String(value)));
      if(![120,240,480,960,1920].includes(spans[index]))select.add(new Option(labels[spans[index]]||`${spans[index]/480}拍`,String(spans[index])));
      select.value=String(spans[index]);select.addEventListener('change',()=>{
        state.durations=[...spans];state.durations[index]=Number(select.value);$('note-value').value='original';changed();
      });cell.append(position,text,select);grid.append(cell);tick+=spans[index];
    });
    $('cycle').textContent=`${tick/480}拍循环${tick>=1920?' · '+tick/1920+'小节':''}`;
    if(tick>7680||(tick%1920!==0&&1920%tick!==0)){
      $('grid-error').textContent=`当前共${tick/480}拍。请把循环调整为完整4/4小节或能在一小节内重复的长度。`;return false;
    }return true;
  }
  function changed() {
    invalidate();const valid=drawGrid();storeChoice();
    if(!valid){message('请调整循环拍数',true);return;}
    message('正在更新谱面与试听…');const sequence=state.sequence;
    state.timer=setTimeout(()=>refresh(sequence),220);
  }
  async function refresh(sequence) {
    state.controller=new AbortController();
    try{
      const result=await api('/api/preview',{project_id:state.projectId,plan:plan(),
        first_measure:Number($('preview-measure').value)||null,request_id:sequence},state.controller.signal);
      if(sequence!==state.sequence)return;
      state.preview=result; $('preview').innerHTML=result.svg;
      $('audio').src=result.audio_url;$('play').disabled=false;
      $('save').disabled=!result.music_changed||state.saving;
      $('preview-range').textContent=`第${result.display_first_measure}–${result.display_last_measure}小节 · ${result.duration_seconds.toFixed(1)}秒`;
      $('scope-result').textContent=`已应用${result.arranged_measures.length}个小节。保留${result.exceptions.length}个器乐、停顿或过渡小节。`;
      message(result.music_changed?'谱面与试听已更新':'沿用当前曲谱');
    }catch(error){if(error.name!=='AbortError'&&sequence===state.sequence)message(error.message,true);}
  }
  async function loadProject() {
    invalidate();loading(true);state.projectId=$('project').value;state.overrides.clear();setChoice(null);
    message('正在读取曲谱…');const sequence=state.sequence;
    try{
      const info=await api('/api/project?id='+encodeURIComponent(state.projectId));if(sequence!==state.sequence)return;
      state.project=info;$('scope').replaceChildren(new Option('全部演唱段','all'));
      for(const [i,s] of info.sections.entries())$('scope').add(new Option(`演唱段${i+1} · 第${s.measures[0]-info.display_measure_offset}–${s.measures.at(-1)-info.display_measure_offset}小节`,s.id));
      $('preview-measure').replaceChildren();for(const m of info.eligible_measures)$('preview-measure').add(new Option(`第${m-info.display_measure_offset}小节`,String(m)));
      $('source-note').textContent=`${info.measure_count}小节 · ${info.eligible_measures.length}个可选演唱小节`;
      $('original-link').href=info.original_url;setChoice(null);loading(false);await refresh(sequence);
    }catch(error){if(sequence===state.sequence)message(error.message,true);}
  }
  $('project').addEventListener('change',loadProject);
  $('scope').addEventListener('change',()=>{
    const value=state.overrides.has($('scope').value)?state.overrides.get($('scope').value):state.overrides.get('all');
    setChoice(value);const section=state.project.sections.find(s=>s.id===$('scope').value);
    if(section?.editable_measures.length)$('preview-measure').value=String(section.editable_measures[0]);
    invalidate();message('正在更新谱面与试听…');refresh(state.sequence);
  });
  $('family').addEventListener('change',()=>{availablePatterns();});
  $('pattern').addEventListener('change',()=>{state.durations=null;$('note-value').value='original';changed();});
  $('note-value').addEventListener('change',()=>{state.durations=null;changed();});
  $('bass-mode').addEventListener('change',changed);$('silence').addEventListener('change',changed);
  $('preview-measure').addEventListener('change',()=>{invalidate();message('正在更新谱面与试听…');refresh(state.sequence);});
  $('reset').addEventListener('click',()=>{state.overrides.clear();$('scope').value='all';setChoice(null);changed();});
  $('play').addEventListener('click',async()=>{try{$('audio').currentTime=0;await $('audio').play();}catch(error){message('请点击音频控件开始试听',true);}});
  function animate(){
    for(const mark of state.marks)mark.remove();state.marks=[];
    const audio=$('audio'),p=state.preview;
    if(!p||audio.paused)return;
    const seconds=p.origin_seconds+audio.currentTime;
    const points=p.beat_positions;let left=points[0],right=points.at(-1);
    for(let i=0;i<points.length-1;i++)if(points[i].seconds<=seconds&&seconds<points[i+1].seconds){left=points[i];right=points[i+1];break;}
    if(left&&right){
      const mark=document.createElementNS('http://www.w3.org/2000/svg','rect');mark.setAttribute('class','playhead');
      mark.setAttribute('x',String(left.x+(right.x-left.x)*Math.max(0,Math.min(1,(seconds-left.seconds)/(right.seconds-left.seconds||1)))-5));
      mark.setAttribute('y','145');mark.setAttribute('width','10');mark.setAttribute('height','350');
      $('preview').querySelector('svg')?.append(mark);state.marks.push(mark);
    }
    $('audio-time').textContent=`原曲 ${seconds.toFixed(1)}秒`;state.frame=requestAnimationFrame(animate);
  }
  $('audio').addEventListener('play',animate);$('audio').addEventListener('pause',()=>{cancelAnimationFrame(state.frame);});
  $('save').addEventListener('click',async()=>{
    if(!state.preview||state.saving)return;
    const previewId=state.preview.preview_id;state.saving=true;$('save').disabled=true;message('正在校验并另存完整版本…');
    try{
      const job=await api('/api/save',{preview_id:previewId});
      let result;
      do{await new Promise(resolve=>setTimeout(resolve,650));result=await api('/api/save?id='+encodeURIComponent(job.job_id));}while(result.status==='running');
      if(result.status!=='complete')throw new Error(result.error||'另存未完成');
      $('saved-link').href=result.url;$('saved-link').hidden=false;
      message(state.preview?.preview_id===previewId?'已另存当前版本':'已另存刚才提交的版本；当前选择尚未保存');
    }catch(error){message(error.message,true);}finally{state.saving=false;$('save').disabled=!state.preview?.music_changed;}
  });
  (async()=>{try{
    const [catalogue,projects]=await Promise.all([api('/api/catalogue'),api('/api/projects')]);
    state.catalogue=catalogue.patterns;availablePatterns();
    for(const project of projects.projects)$('project').add(new Option(project.title,project.id));
    if(!projects.projects.length)throw new Error('没有可编辑的曲谱，请用启动参数指定已有工程');
    await loadProject();
  }catch(error){message(error.message,true);}})();
})();
