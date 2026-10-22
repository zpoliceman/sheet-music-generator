/* 多区间右手配置与网页完整成品：新增区间、命名配置、真实局部预览和当前页完整成品。 */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const state={catalogue:[],project:null,projectId:'',ranges:[],activeId:'',durations:null,
    configurations:[],configuration:null,sequence:0,timer:null,controller:null,preview:null,saving:false,
    marks:[],frame:0,full:null,savedPlan:''};
  // 初始默认完整谱与歌词对照：新增轻量来源地址及对照谱状态，与修改快照分别保存。
  state.projects=[];
  state.reference={projectId:'',url:null,ready:false,measure:null};
  window.guitarPrintContext=()=>({project_id:state.projectId,version:state.full?.version||null,needs_save:state.full?JSON.stringify(plan())!==state.savedPlan:!!state.preview?.music_changed,saving:state.saving});
  const notifyPrint=()=>window.dispatchEvent(new Event('guitar-print-context'));
  const labels={120:'十六分',240:'八分',360:'附点八分',480:'四分',720:'附点四分',960:'二分',1440:'附点二分',1920:'全音符'};
  // 右手选择后主谱实时可见更新：保留旧隐藏在下方的状态，主谱旁同步显示实际结果／失败。
  // const message=(text,error=false)=>{$('status').textContent=text;$('status').dataset.error=String(error);};
  const message=(text,error=false)=>{
    $('status').textContent=text;$('status').dataset.error=String(error);
    $('visible-status').textContent=error?'当前选择未应用：'+text:text;$('visible-status').dataset.error=String(error);
    if(error)$('default-score-panel').dataset.busy='false';
  };
  const active=()=>state.ranges.find(row=>row.id===state.activeId);
  const pattern=()=>state.catalogue.find(row=>row.id===$('pattern').value);
  const newId=()=> 'r'+crypto.randomUUID().replaceAll('-','').slice(0,16);
  const offset=()=>state.project?.display_measure_offset||0;
  const maximum=()=>state.project.measure_count-offset();
  const clone=value=>JSON.parse(JSON.stringify(value));
  // 右手候选悬停六线谱预览：新增只读候选组件，原select的change事件仍是应用音乐的入口。
  const patternPicker=window.GuitarPatternPicker.attach($('pattern'));

  // 多区间右手配置与网页完整成品：新增来源加载及无活动行时的编辑状态，保持快选防串。
  function loading(value){
    for(const id of ['family','pattern','note-value','bass-mode','silence','preview-measure','reset','add-range','new-configuration','configuration','configuration-name'])$(id).disabled=value;
    $('load-configuration').disabled=value||!$('configuration').value;
  }
  loading(true);
  async function api(path,body,signal){
    const response=await fetch(path,{method:body?'POST':'GET',signal,
      headers:body?{'Content-Type':'application/json','X-Editor-Token':window.EDITOR_TOKEN}:{},body:body?JSON.stringify(body):undefined});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'请求失败');return result;
  }
  function choice(){
    return !$('pattern').value?null:{pattern_id:$('pattern').value,note_value:$('note-value').value,
      bass_mode:$('bass-mode').value,silence:$('silence').value,durations:state.durations?[...state.durations]:null};
  }
  function plan(){return {version:1,ranges:clone(state.ranges)};}
  function invalidate(){
    state.sequence++;state.preview=null;$('save').disabled=true;$('play').disabled=true;
    // 多区间右手配置与网页完整成品：新增范围变化时清除旧的应用结论。
    $('applied-summary').textContent='等待当前设置的预览结果…';
    $('audio').pause();$('audio').removeAttribute('src');$('audio').load();cancelAnimationFrame(state.frame);
    for(const mark of state.marks)mark.remove();state.marks=[];
    state.controller?.abort();clearTimeout(state.timer);
    // 右手选择后主谱实时可见更新：新增等待状态，避免旧主谱在编译期间被误认为当前选择已生效。
    $('default-score-panel').dataset.busy='true';
  }
  function markDirty(){
    notifyPrint();
    const dirty=!!state.savedPlan&&JSON.stringify(plan())!==state.savedPlan;
    $('save-note').textContent=dirty?'有未保存的调整；下方仍为上次保存的完整版本。':'使用各条区间的设置另存整曲；原谱保留。';
    $('save-note').dataset.dirty=String(dirty);
    if(state.full)$('full-note').textContent=dirty?'当前选择尚未保存；这里显示上次保存的完整曲谱与整曲音频。':'已保存此套配置；下方为全部小节及完整原曲时长的试听。';
  }
  function availablePatterns(){
    const previous=$('pattern').value;$('pattern').replaceChildren(new Option('保持原有演奏',''));
    for(const p of state.catalogue)if($('family').value==='all'||p.family===$('family').value)$('pattern').add(new Option(p.name,p.id));
    if(previous&&![...$('pattern').options].some(o=>o.value===previous)){
      const p=state.catalogue.find(p=>p.id===previous);if(p)$('pattern').add(new Option('当前 · '+p.name,p.id));
    }
    $('pattern').value=previous;
    // 右手候选悬停六线谱预览：分类或配置更新后同步候选列表，不触发歌曲重编配。
    patternPicker.refresh(state.catalogue);
  }
  function setChoice(value){
    $('family').value='all';availablePatterns();$('pattern').value=value?.pattern_id||'';
    $('note-value').value=value?.note_value||'original';$('bass-mode').value=value?.bass_mode||'adaptive';
    $('silence').value=value?.silence||'ring';state.durations=value?.durations?[...value.durations]:null;drawGrid();
    for(const id of ['family','pattern','note-value','bass-mode','silence'])$(id).disabled=!active();
  }
  function drawGrid(){
    // 右手候选悬停六线谱预览：程序载入配置、切换分类或清空时同步按钮上的实际选择。
    patternPicker.sync();
    const selected=pattern(),grid=$('beat-grid');grid.replaceChildren();$('grid-error').textContent='';
    for(const option of $('note-value').options)option.disabled=!!selected&&!selected.uniform&&option.value!=='original';
    if(!selected){$('cycle').textContent='沿用原演奏';$('pattern-note').textContent='未选择时沿用当前曲谱。';return true;}
    if(!selected.uniform&&$('note-value').value!=='original')$('note-value').value='original';
    // 扫弦延音简化与右手候选扩充：保留旧时值提示，新增具体音序与演奏说明，便于辨认扩充的候选。
    // $('pattern-note').textContent=selected.uniform?'可统一选择时值，也可逐格修改。':'此型含混合时值，可逐格修改。';
    $('pattern-note').textContent=(selected.description?selected.description+' ':'')+(selected.uniform?'可统一选择时值，也可逐格修改。':'此型含混合时值，可逐格修改。');
    const uniform={quarter:480,eighth:240,sixteenth:120}[$('note-value').value];
    const spans=state.durations||selected.events.map(e=>uniform||e.action_span_ticks);let tick=0;
    selected.events.forEach((event,index)=>{
      const cell=document.createElement('div');cell.className='beat-cell'+(tick%480===0?' strong':'');
      const position=document.createElement('small');position.textContent=`${Math.floor(tick/1920)+1}小节 · ${Math.floor(tick%1920/480)+1}${tick%480?'+'+String((tick%480)/480):''}拍`;
      const text=document.createElement('strong');text.textContent=({DA:'下',DL:'下低',UH:'上高','-':'延'})[event.token]||event.token;
      const select=document.createElement('select');select.setAttribute('aria-label',`第${index+1}格时值`);
      for(const value of [120,240,480,960,1920])select.add(new Option(labels[value],String(value)));
      if(![120,240,480,960,1920].includes(spans[index]))select.add(new Option(labels[spans[index]]||`${spans[index]/480}拍`,String(spans[index])));
      select.value=String(spans[index]);select.addEventListener('change',()=>{
        state.durations=[...spans];state.durations[index]=Number(select.value);$('note-value').value='original';changed();
      });cell.append(position,text,select);grid.append(cell);tick+=spans[index];
    });
    $('cycle').textContent=`${tick/480}拍循环${tick>=1920?' · '+tick/1920+'小节':''}`;
    if(tick>7680||(tick%1920!==0&&1920%tick!==0)){
      $('grid-error').textContent=`当前共${tick/480}拍。请调整为完整4/4小节或能在一小节内重复的长度。`;return false;
    }return true;
  }

  // 多区间右手配置与网页完整成品：新增闭区间行及前端校验；服务端独立再次校验实际范围。
  function summary(row){
    const p=state.catalogue.find(p=>p.id===row.choice?.pattern_id);
    return {name:p?.name||'保持原有演奏',detail:row.choice?.durations?'逐格自定时值':({quarter:'每格四分',eighth:'每格八分',sixteenth:'每格十六分',original:'候选原节奏'})[row.choice?.note_value]||'尚未选择右手型'};
  }
  function updateRows(){
    for(const element of $('ranges').children){
      const row=state.ranges.find(row=>row.id===element.dataset.rangeId);if(!row)continue;
      element.classList.toggle('active',row.id===state.activeId);const text=summary(row);
      // 多区间右手配置与网页完整成品：新增每条配置的实际应用数量，真实器乐保留一眼可见。
      if(row.choice&&state.preview){const count=state.preview.arranged_measures.filter(m=>row.start_measure+offset()<=m&&m<=row.end_measure+offset()).length;
        text.detail+=` · 应用${count}/${row.end_measure-row.start_measure+1}小节`;}
      element.querySelector('strong').textContent=text.name;element.querySelector('small').textContent=text.detail;
      element.querySelector('.range-edit').setAttribute('aria-pressed',String(row.id===state.activeId));
    }
    const row=active();$('active-range').textContent=row?`正在编辑：第${row.start_measure??'…'}–${row.end_measure??'…'}小节`:'添加一条小节区间开始编辑';
  }
  function renderRanges(){
    $('ranges').replaceChildren();
    for(const row of state.ranges){
      const element=document.createElement('div');element.className='range-row';element.dataset.rangeId=row.id;
      for(const [field,label] of [['start_measure','起始小节'],['end_measure','结束小节']]){
        if(field==='end_measure'){const to=document.createElement('span');to.className='range-to';to.textContent='至';element.append(to);}
        const wrapper=document.createElement('label');wrapper.textContent=label;
        const input=document.createElement('input');input.type='number';input.min=String(1-offset());input.max=String(maximum());input.step='1';
        input.value=row[field]??'';input.dataset.field=field;input.setAttribute('aria-label',label);
        input.addEventListener('focus',()=>{if(state.activeId!==row.id)activate(row.id,false);});
        input.addEventListener('input',()=>{row[field]=input.value===''?null:Number(input.value);changed(false);});wrapper.append(input);element.append(wrapper);
      }
      const edit=document.createElement('button');edit.className='range-edit';edit.type='button';edit.append(document.createElement('strong'),document.createElement('small'));
      edit.addEventListener('click',()=>activate(row.id,true));
      const remove=document.createElement('button');remove.className='range-remove';remove.textContent='移除';remove.setAttribute('aria-label','移除这条区间');
      remove.addEventListener('click',()=>{state.ranges=state.ranges.filter(r=>r.id!==row.id);
        if(state.activeId===row.id)state.activeId=state.ranges[0]?.id||'';renderRanges();setChoice(active()?.choice);changed(false);});
      element.append(edit,remove);$('ranges').append(element);
    }
    if(!state.ranges.length){const note=document.createElement('p');note.className='help';note.textContent='尚无区间，当前保持原奏。';$('ranges').append(note);}
    updateRows();
  }
  function rangeError(){
    if(!state.project)return '正在读取曲谱';
    const sorted=[...state.ranges].sort((a,b)=>a.start_measure-b.start_measure);
    for(let i=0;i<sorted.length;i++){
      const row=sorted[i];if(!Number.isInteger(row.start_measure)||!Number.isInteger(row.end_measure)||row.start_measure<1-offset()||row.end_measure>maximum()||row.start_measure>row.end_measure)
        return `范围应在第${1-offset()}–${maximum()}小节内，起始不能大于结束。`;
      if(i&&row.start_measure<=sorted[i-1].end_measure)return `第${sorted[i-1].start_measure}–${sorted[i-1].end_measure}小节与第${row.start_measure}–${row.end_measure}小节重叠，请调整。`;
    }return '';
  }
  function previewAt(row){
    if(!row||!Number.isInteger(row.start_measure))return;
    const target=row.start_measure+offset();
    const eligible=state.project.eligible_measures.find(m=>m>=target&&m<=row.end_measure+offset());
    $('preview-measure').value=String(eligible||target);
    // 初始默认完整谱与歌词对照：新增按用户选区首小节定位原谱，重复换型时不打断手工滚动阅读。
    pointDefault(row.start_measure+offset());
  }
  function activate(id,move){
    state.activeId=id;setChoice(active()?.choice);updateRows();if(move)previewAt(active());
    invalidate();schedule();
  }
  function changed(store=true){
    if(store&&active())active().choice=choice();invalidate();const valid=drawGrid();updateRows();markDirty();
    // 多区间右手配置与网页完整成品：新增调整时自动定位当前区间，避免仍预览此前另一条范围。
    previewAt(active());
    $('range-error').textContent=rangeError();if(!valid){message('请调整循环拍数',true);return;}schedule();
  }
  function schedule(){
    const error=rangeError();$('range-error').textContent=error;if(error){message('请先调整小节范围',true);return;}
    message('正在更新谱面与试听…');const sequence=state.sequence;state.timer=setTimeout(()=>refresh(sequence),260);
  }
  async function refresh(sequence){
    state.controller=new AbortController();
    try{
      const result=await api('/api/preview',{project_id:state.projectId,plan:plan(),first_measure:Number($('preview-measure').value)||null},state.controller.signal);
      if(sequence!==state.sequence)return;
      state.preview=result;notifyPrint();$('preview').innerHTML=result.svg;$('audio').src=result.audio_url;$('play').disabled=false;
      $('save').disabled=!result.music_changed||state.saving;
      $('preview-range').textContent=`第${result.display_first_measure}–${result.display_last_measure}小节 · ${result.duration_seconds.toFixed(1)}秒`;
      const requested=new Set(state.ranges.filter(r=>r.choice).flatMap(r=>Array.from({length:r.end_measure-r.start_measure+1},(_,i)=>r.start_measure+i+offset())));
      const kept=[...requested].filter(m=>!result.arranged_measures.includes(m)).map(m=>m-offset());
      $('scope-result').textContent=`已应用${result.arranged_measures.length}个小节。`+(kept.length?`所选范围内保留原奏：第${kept.join('、')}小节（器乐、真实停顿、过渡或跨界延音）。`:'所选完整演唱小节均已应用。');
      // 多区间右手配置与网页完整成品：新增将实际生效和例外同步到范围表下方。
      $('applied-summary').textContent=result.music_changed?$('scope-result').textContent:'未选择右手型，所有小节沿用原奏。';updateRows();
      // 右手选择后主谱实时可见更新：保留旧仅局部提示，实际将整份当前谱画到眼前的主谱区。
      // message(result.music_changed?'局部预览已更新；保存后生成完整曲谱与音频':'沿用当前曲谱');
      const shown=paintVisibleScore(result);
      message(shown?visibleScoreMessage(result):'正在加载当前主谱…');
    }catch(error){if(error.name!=='AbortError'&&sequence===state.sequence)message(error.message,true);}
  }

  // 多区间右手配置与网页完整成品：新增配置载入／复制及实际完整页面展示，不拼接另一套音乐。
  function populateConfigurations(selected=''){
    $('configuration').replaceChildren(new Option('新配置',''));
    for(const item of state.configurations){const option=new Option(item.name+(item.compatible?'':'（原谱已改变）'),item.id);option.disabled=!item.compatible;$('configuration').add(option);}
    $('configuration').value=selected;$('load-configuration').disabled=!selected;
  }
  function clearFull(){
    $('full-result').hidden=true;$('full-score').src='about:blank';$('saved-link').hidden=true;state.full=null;state.savedPlan='';notifyPrint();
  }
  // 初始默认完整谱与歌词对照：新增读取已有完整谱，首次打开与切歌即展示，不依赖选型／保存。
  function showDefault(identity,source){
    const url=source?.original_full_url||null;
    if(state.reference.projectId===identity&&state.reference.url===url)return;
    state.reference={projectId:identity,url,ready:false,measure:null};
    $('default-score').src=url||'about:blank';$('default-score-panel').dataset.projectId=identity;
    $('default-measure').replaceChildren();$('default-measure').disabled=true;
    $('default-score-link').hidden=!url;if(url)$('default-score-link').href=url;
    $('default-score-status').dataset.error=String(!url);
    $('default-score-status').textContent=url?'正在显示默认完整谱与歌词…':'此工程尚无已导出的默认曲谱。';
  }
  // 右手选择后主谱实时可见更新：新增同一主谱的当前音符／完整歌词替换，原谱只保存在内存供撤销。
  function visibleScoreMessage(result){
    const names=[...new Set(state.ranges.filter(r=>r.choice).map(r=>state.catalogue.find(p=>p.id===r.choice.pattern_id)?.name).filter(Boolean))];
    return result.music_changed?`主谱已更新：${names.join('、')} · 已应用${result.arranged_measures.length}小节；可直接试听，保存后另存整曲。`:'当前为默认演奏；选择手型后主谱会直接更新。';
  }
  function paintVisibleScore(result=state.preview){
    const reference=state.reference;
    if(!result||!reference.ready||reference.projectId!==state.projectId)return false;
    const doc=$('default-score').contentDocument,main=doc.querySelector('main');
    if(!main)return false;
    if(result.music_changed&&typeof result.score_html!=='string')throw new Error('主谱数据尚未更新，请刷新页面后重试');
    const key=result.music_changed?result.preview_id:'original';
    if(main.dataset.livePreview!==key){
      const template=doc.createElement('template');template.innerHTML=result.music_changed?result.score_html:reference.originalRows;
      for(const row of main.querySelectorAll('.score-row'))row.remove();main.append(template.content);
      main.dataset.livePreview=key;
    }
    reference.currentChanged=result.music_changed;
    $('default-score-panel').dataset.busy='false';
    pointDefault(reference.measure||result.first_measure,true);
    return true;
  }
  function pointDefault(number,force=false){
    const reference=state.reference;
    if(!Number.isInteger(number)||number<1)return;
    if(reference.measure===number&&!force)return;
    reference.measure=number;
    if(!reference.ready||!state.project)return;
    const doc=$('default-score').contentDocument,display=number-offset();
    const rows=[...doc.querySelectorAll('.score-row')];
    let row=doc.querySelector(`.score-row [data-source-measure="${number}"]`)?.closest('.score-row');
    if(!row)row=rows.find(element=>{
      const heading=element.querySelector('header')?.textContent||'';
      const match=heading.match(/第\s*(-?\d+)(?:\s*[–—－-]\s*(-?\d+))?\s*小节/);
      return match?Number(match[1])<=display&&display<=Number(match[2]||match[1]):display===0&&heading.includes('弱起');
    });
    for(const previous of doc.querySelectorAll('.default-score-target'))previous.classList.remove('default-score-target');
    if(row){
      row.classList.add('default-score-target');
      const view=$('default-score').contentWindow;view.scrollTo({top:Math.max(0,row.getBoundingClientRect().top+view.scrollY-8),behavior:'instant'});
    }
    $('default-measure').value=String(number);
    // 右手选择后主谱实时可见更新：保留旧固定原谱标签，按实际显示说明当前状态。
    // $('default-score-status').textContent=`默认原谱 · 第${display}小节${row?'':'（可在谱内滚动查看）'}`;
    $('default-score-status').textContent=`${reference.currentChanged?'当前编配':'默认演奏'} · 第${display}小节${row?'':'（可在谱内滚动查看）'}`;
  }
  $('default-score').addEventListener('load',()=>{
    // 初始默认完整谱与歌词对照：新增只在当前同源谱面里隐藏导航／播放器，原文件及歌词SVG不改。
    const reference=state.reference,doc=$('default-score').contentDocument;
    if(!reference.url||reference.projectId!==state.projectId||doc?.location.href!==new URL(reference.url,location.href).href)return;
    if(!doc.querySelector('.score-row svg')){
      $('default-score-status').textContent='默认曲谱未能显示，可单独打开原谱。';$('default-score-status').dataset.error='true';return;
    }
    const style=doc.createElement('style');style.id='default-score-display';
    style.textContent='body{margin:0;background:#fafcf8}main{padding:8px;max-width:none}main>:not(.score-row):not(style):not(script){display:none!important}.score-row{margin:0 0 14px;padding:10px}.score-row header button{display:none!important}.default-score-target{outline:2px solid #5d9f83;outline-offset:-2px}';
    // 初始默认完整谱与歌词对照：新增隐藏对照行内的编辑跳转，保留外部“单独打开原谱”入口。
    style.textContent+='.score-row header a{display:none!important}';
    // 右手选择后主谱实时可见更新：新增原行快照用于清空／恢复，不通过重载覆盖正在编辑的新主谱。
    reference.originalRows=[...doc.querySelectorAll('.score-row')].map(row=>row.outerHTML).join('');
    doc.head.append(style);reference.ready=true;$('default-score-status').textContent='默认完整谱已显示，可滚动查看歌词与小节。';
    if(reference.measure!==null)pointDefault(reference.measure,true);
    if(state.preview&&paintVisibleScore())message(visibleScoreMessage(state.preview));
  });
  $('default-measure').addEventListener('change',()=>pointDefault(Number($('default-measure').value),true));
  function showFull(result,name){
    $('audio').pause();state.full=result;$('full-result').hidden=false;$('full-title').textContent=(name?name+' · ':'')+'完整曲谱与整曲试听';
    $('full-score').src=result.score_url;$('reading-link').href=result.reading_url;$('saved-link').href=result.url;$('saved-link').hidden=false;markDirty();
  }
  function resizeScore(){
    try{const main=$('full-score').contentDocument?.querySelector('main');if(main)$('full-score').style.height=Math.max(950,Math.ceil(main.getBoundingClientRect().height)+64)+'px';}catch(_error){/* 同源完整成品加载后重试。 */}
  }
  let scoreObserver;
  $('full-score').addEventListener('load',()=>{
    scoreObserver?.disconnect();const doc=$('full-score').contentDocument,main=doc?.querySelector('main');if(!main)return;
    resizeScore();scoreObserver=new ResizeObserver(resizeScore);scoreObserver.observe(main);doc.fonts?.ready.then(resizeScore);
    for(const audio of doc.querySelectorAll('audio'))audio.addEventListener('play',()=>{$('audio').pause();});
  });
  function newConfiguration(){
    invalidate();state.configuration=null;$('configuration-name').value='';$('configuration').value='';$('load-configuration').disabled=true;
    const measures=state.project.eligible_measures;
    state.ranges=measures.length?[{id:newId(),start_measure:measures[0]-offset(),end_measure:measures.at(-1)-offset(),choice:null}]:[];
    state.activeId=state.ranges[0]?.id||'';clearFull();renderRanges();setChoice(null);previewAt(active());changed(false);
  }
  async function loadProject(){
    invalidate();loading(true);clearFull();state.projectId=$('project').value;state.project=null;state.ranges=[];state.activeId='';renderRanges();setChoice(null);
    state.configurations=[];state.configuration=null;populateConfigurations();$('configuration-name').value='';
    // 初始默认完整谱与歌词对照：新增先从轻量列表显示原谱，完整来源校验仍按原编辑流程执行。
    showDefault(state.projectId,state.projects.find(project=>project.id===state.projectId));
    message('正在读取曲谱…');const sequence=state.sequence,identity=state.projectId;
    try{
      const info=await api('/api/project?id='+encodeURIComponent(identity));if(sequence!==state.sequence)return;state.project=info;
      // 初始默认完整谱与歌词对照：新增真实小节表完成后的定位选项，快切歌曲的旧响应不能覆盖新谱。
      showDefault(identity,info);$('default-measure').replaceChildren();
      for(let m=1;m<=info.measure_count;m++)$('default-measure').add(new Option(m===1&&offset()?'弱起预备':`第${m-offset()}小节`,String(m)));
      $('default-measure').disabled=!state.reference.url;
      $('preview-measure').replaceChildren();for(let m=1;m<=info.measure_count;m++)$('preview-measure').add(new Option(m===1&&offset()?'弱起预备':`第${m-offset()}小节`,String(m)));
      $('source-note').textContent=`${offset()?'弱起预备＋第1':'第1'}–${maximum()}小节 · ${info.eligible_measures.length}个可选演唱小节`;$('original-link').href=info.original_url;
      const saved=await api('/api/configurations?project_id='+encodeURIComponent(identity));if(sequence!==state.sequence)return;
      state.configurations=saved.configurations;populateConfigurations();loading(false);newConfiguration();
    }catch(error){if(sequence===state.sequence)message(error.message,true);}
  }
  $('configuration').addEventListener('change',()=>{$('load-configuration').disabled=!$('configuration').value;});
  $('load-configuration').addEventListener('click',()=>{
    const item=state.configurations.find(item=>item.id===$('configuration').value);if(!item?.compatible)return;
    invalidate();state.configuration=item;$('configuration-name').value=item.name;
    // 多区间右手配置与网页完整成品：新增旧段落快照的兼容载入，不静默丢掉已有右手选择。
    state.ranges=item.plan.ranges?clone(item.plan.ranges):state.project.sections.map(section=>({id:newId(),start_measure:section.measures[0]-offset(),end_measure:section.measures.at(-1)-offset(),choice:item.plan.sections?.find(s=>s.section_id===section.id)?.choice??item.plan.default??null}));
    state.activeId=state.ranges[0]?.id||'';renderRanges();setChoice(active()?.choice);previewAt(active());state.savedPlan=JSON.stringify(plan());
    if(item.result)showFull(item.result,item.name);changed(false);$('configuration-note').textContent='已载入此套配置。保留名称会更新本套配置；修改名称会另存为另一套。每次生成的曲谱版本都会保留。';
  });
  $('new-configuration').addEventListener('click',newConfiguration);
  $('configuration-name').addEventListener('input',markDirty);
  $('add-range').addEventListener('click',()=>{
    const last=Math.max(0,...state.ranges.map(r=>r.end_measure||0));const start=Math.min(maximum(),last+1);
    const row={id:newId(),start_measure:start,end_measure:Math.min(maximum(),start+3),choice:null};state.ranges.push(row);state.activeId=row.id;
    renderRanges();setChoice(null);previewAt(row);changed(false);
  });
  // 右手选择后主谱实时可见更新：保留旧仅筛选的分类行为，切换类别后实际选用本类首型并编译。
  // $('project').addEventListener('change',loadProject);$('family').addEventListener('change',availablePatterns);
  $('project').addEventListener('change',loadProject);
  $('family').addEventListener('change',()=>{
    const family=$('family').value;availablePatterns();
    if(family==='all')return;
    if(pattern()?.family===family&&active()?.choice)return;
    const next=state.catalogue.find(p=>p.family===family);if(!next)return;
    $('pattern').value=next.id;state.durations=null;$('note-value').value='original';changed();
  });
  $('pattern').addEventListener('change',()=>{state.durations=null;$('note-value').value='original';changed();});
  // 右手选择后主谱实时可见更新：保留未选型时只改空参数的旧行为；先选时值会采用首个均匀分解型。
  // $('note-value').addEventListener('change',()=>{state.durations=null;changed();});
  $('note-value').addEventListener('change',()=>{
    // 右手选择后主谱实时可见更新：保留初稿默认分解选择，当前分类下优先选本类均匀型，避免选中不存在的选项。
    // if(!$('pattern').value){const next=state.catalogue.find(p=>p.family==='arpeggio'&&p.uniform);if(next)$('pattern').value=next.id;}
    if(!$('pattern').value){
      const family=$('family').value;
      const next=state.catalogue.find(p=>p.uniform&&p.family===(family==='all'?'arpeggio':family))||state.catalogue.find(p=>p.family==='arpeggio'&&p.uniform);
      if(next){if(![...$('pattern').options].some(o=>o.value===next.id)){$('family').value='all';availablePatterns();}$('pattern').value=next.id;}
    }
    state.durations=null;changed();
  });
  $('bass-mode').addEventListener('change',()=>changed());$('silence').addEventListener('change',()=>changed());
  // 初始默认完整谱与歌词对照：保留旧局部定位，新增同步默认谱上下文。
  // $('preview-measure').addEventListener('change',()=>{invalidate();schedule();});
  $('preview-measure').addEventListener('change',()=>{pointDefault(Number($('preview-measure').value));invalidate();schedule();});
  $('reset').addEventListener('click',()=>{state.ranges=[];state.activeId='';renderRanges();setChoice(null);changed(false);});
  $('play').addEventListener('click',async()=>{try{$('audio').currentTime=0;await $('audio').play();}catch(_error){message('请点击音频控件开始试听',true);}});

  // 多区间右手配置与网页完整成品：新增保留原真实源秒数游标，短试听与完整成品播放互斥。
  function animate(){
    for(const mark of state.marks)mark.remove();state.marks=[];const audio=$('audio'),preview=state.preview;if(!preview||audio.paused)return;
    const seconds=preview.origin_seconds+audio.currentTime,points=preview.beat_positions;let left=points[0],right=points.at(-1);
    for(let i=0;i<points.length-1;i++)if(points[i].seconds<=seconds&&seconds<points[i+1].seconds){left=points[i];right=points[i+1];break;}
    if(left&&right){const mark=document.createElementNS('http://www.w3.org/2000/svg','rect');mark.setAttribute('class','playhead');
      mark.setAttribute('x',String(left.x+(right.x-left.x)*Math.max(0,Math.min(1,(seconds-left.seconds)/(right.seconds-left.seconds||1)))-5));
      mark.setAttribute('y','145');mark.setAttribute('width','10');mark.setAttribute('height','350');$('preview').querySelector('svg')?.append(mark);state.marks.push(mark);}
    $('audio-time').textContent=`原曲 ${seconds.toFixed(1)}秒`;state.frame=requestAnimationFrame(animate);
  }
  $('audio').addEventListener('play',()=>{for(const audio of $('full-score').contentDocument?.querySelectorAll('audio')||[])audio.pause();animate();});
  $('audio').addEventListener('pause',()=>cancelAnimationFrame(state.frame));
  $('save').addEventListener('click',async()=>{
    if(!state.preview||state.saving)return;
    const previewId=state.preview.preview_id,projectId=state.projectId,submittedPlan=JSON.stringify(plan()),name=$('configuration-name').value.trim();
    const configuration={name,id:state.configuration?.name===name?state.configuration.id:null};
    state.saving=true;notifyPrint();$('save').disabled=true;message('正在校验并生成完整曲谱与整曲音频…');
    // 多区间右手配置与网页完整成品：新增保存期间固定配置身份，区间仍可调整，完成后不会覆盖另一个配置名。
    for(const id of ['project','configuration','configuration-name','load-configuration','new-configuration'])$(id).disabled=true;
    try{
      const job=await api('/api/save',{preview_id:previewId,configuration});let result;
      do{await new Promise(resolve=>setTimeout(resolve,700));result=await api('/api/save?id='+encodeURIComponent(job.job_id));}while(result.status==='running');
      if(result.status!=='complete')throw new Error(result.error||'保存未完成');
      if(projectId!==state.projectId)return;
      state.configuration={...result.configuration,compatible:true};state.configurations=state.configurations.filter(item=>item.id!==result.configuration.id);state.configurations.unshift(state.configuration);
      populateConfigurations(result.configuration.id);$('configuration-name').value=result.configuration.name;state.savedPlan=submittedPlan;
      showFull(result,result.configuration.name);$('configuration-note').textContent='配置已保存。保留名称会更新本套配置；修改名称会另存另一套。历史曲谱版本保持。';
      message(state.preview?.preview_id===previewId?'已保存；完整曲谱与整曲试听已在下方生成':'已保存提交时的版本；当前调整尚未保存');
    // 多区间右手配置与网页完整成品：保留旧收尾，完成或失败都恢复命名配置操作。
    // }catch(error){if(projectId===state.projectId)message(error.message,true);}finally{state.saving=false;notifyPrint();$('save').disabled=!state.preview?.music_changed;}
    }catch(error){if(projectId===state.projectId)message(error.message,true);}finally{
      state.saving=false;notifyPrint();$('save').disabled=!state.preview?.music_changed;
      for(const id of ['project','configuration','configuration-name','new-configuration'])$(id).disabled=false;
      $('load-configuration').disabled=!$('configuration').value;
    }
  });
  (async()=>{try{
    const [catalogue,projects]=await Promise.all([api('/api/catalogue'),api('/api/projects')]);state.catalogue=catalogue.patterns;availablePatterns();
    // 扫弦延音简化与右手候选扩充：新增实际候选数量，分类数由当前库计算，旧候选选择和配置标识保持。
    for(const option of $('family').options){
      const count=option.value==='all'?state.catalogue.length:state.catalogue.filter(p=>p.family===option.value).length;
      option.textContent=({all:'全部',arpeggio:'分解',pinch:'合拨',strum:'扫弦'})[option.value]+`（${count}种）`;
    }
    // 初始默认完整谱与歌词对照：新增保存列表中的原谱地址，仅用于只读显示。
    state.projects=projects.projects;
    for(const project of projects.projects)$('project').add(new Option(project.title,project.id));
    if(!projects.projects.length)throw new Error('没有可编辑的曲谱，请指定已有工程');await loadProject();
  }catch(error){message(error.message,true);}})();
})();
