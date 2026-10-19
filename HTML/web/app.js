'use strict';
const $ = (id) => document.getElementById(id);
const state = {authRevision:0,person:null, csrf:'', audio:null, lyrics:null, lyricsRequest:0, audioUrl:'', xhr:null, saved:false, rows:[], invite:null, toastTimer:0};
const MB = 1024 * 1024;
const scoreDownloads=new window.ScoreDownloads($('portal-score-downloads'),{request:(path,body)=>api(path,body===undefined?{}:{method:'POST',body}),getSource:()=>state.person&&$('score-project').value?{project_id:$('score-project').value}:null});
async function refreshScores(){const who=state.person?.id;const data=await api('/api/scores');if(who!==state.person?.id)return;const old=$('score-project').value;$('score-project').replaceChildren();for(const row of data.scores)$('score-project').add(new Option(row.title,row.id));if(data.scores.some(r=>r.id===old))$('score-project').value=old;text('score-library-note',data.local_library_visible?'本机曲谱仅管理员可见。下载时另存默认排版，原曲谱保留。':'这里只显示你的已完成曲谱；当前上传仍只保存素材，不会自动制谱。');scoreDownloads.reset();}
$('refresh-scores').addEventListener('click',()=>refreshScores().catch(e=>toast(message(e))));
$('score-project').addEventListener('change',()=>scoreDownloads.reset());
function text(id,value){ $(id).textContent=value; }
function toast(message){text('toast',message);$('toast').hidden=false;clearTimeout(state.toastTimer);state.toastTimer=setTimeout(()=>$('toast').hidden=true,4200);}
function bytes(value){return value>=MB?(value/MB).toFixed(1)+' MB':Math.max(1,Math.round(value/1024))+' KB';}
function date(value){return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value*1000));}
function message(error){return error?.message||'这次操作没有完成，请稍后重试。';}
async function api(path,options={}){
  const csrfAtStart=state.csrf;
  const headers={...(options.headers||{})};
  if(options.method&&options.method!=='GET'&&state.csrf)headers['X-CSRF-Token']=state.csrf;
  let body=options.body;
  if(body!==undefined){headers['Content-Type']='application/json';body=JSON.stringify(body);}
  const response=await fetch(path,{...options,body,headers,credentials:'same-origin',cache:'no-store'});
  const data=await response.json().catch(()=>({}));
  if(!response.ok){const error=new Error(data.error||'网站暂时无法完成操作。');error.status=response.status;if(response.status===401&&state.person&&state.csrf===csrfAtStart)showLogin();throw error;}
  return data;
}
function stopPlayer(id){const player=$(id);player.pause();player.removeAttribute('src');player.load();player.hidden=true;}
function resetInput(){
  state.audio=null;state.lyrics=null;state.lyricsRequest++;state.saved=false;
  if(state.audioUrl){URL.revokeObjectURL(state.audioUrl);state.audioUrl='';}
  $('audio-file').value='';$('lyrics-file').value='';
  text('audio-title','点击选择，或把歌曲拖到这里');text('audio-description','保留你的原始音源');
  text('lyrics-title','选择配套的歌词 TXT');text('lyrics-description','保留换行，歌词内容会在下方预览');
  text('lyrics-preview','');$('lyrics-preview-wrap').hidden=true;
  $('audio-drop').classList.remove('selected');$('lyrics-drop').classList.remove('selected');
  stopPlayer('local-audio');text('upload-error','');text('upload-notice','');
  $('upload-progress-wrap').hidden=true;$('reset-upload').hidden=true;renderSubmit();
}
function renderSubmit(){
  $('upload-submit').disabled=!state.audio||!state.lyrics||!!state.xhr||state.saved;
  $('audio-file').disabled=!!state.xhr;$('lyrics-file').disabled=!!state.xhr;
  $('upload-submit').textContent=state.xhr?'正在上传并保存…':state.saved?'这套素材已经保存':'上传并保存素材 ↑';
}
function showLogin(){
  scoreDownloads.reset();$('score-project').replaceChildren();state.authRevision++;state.person=null;state.csrf='';state.rows=[];state.invite=null;
  text('new-invite-code','');text('new-invite-name','');text('detail-title','');text('detail-info','');
  $('friend-list').replaceChildren();$('share-url').value='';$('new-invite').hidden=true;
  $('workspace').hidden=true;$('welcome').hidden=false;$('logout').hidden=true;$('invite-open').hidden=true;
  $('upload-list').replaceChildren();text('detail-lyrics','');stopPlayer('saved-audio');resetInput();
  for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();
}
async function showWorkspace(person){
  state.person=person;state.csrf=person.csrf;
  $('welcome').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;
  $('invite-open').hidden=person.role!=='owner';text('person-name',person.name);
  $('access-code').value='';text('login-error','');await refreshUploads();await refreshScores();
}
async function chooseAudio(file){
  text('upload-error','');text('upload-notice','');state.saved=false;
  if(!file)return;
  if(!/\.(mp3|ncm)$/i.test(file.name)||file.size===0||file.size>80*MB){
    state.audio=null;$('audio-file').value='';stopPlayer('local-audio');renderSubmit();
    throw new Error('请选择80MB以内、非空的MP3或NCM音源。');
  }
  state.audio=file;
  text('audio-title',file.name);text('audio-description',bytes(file.size)+' · '+(/\.mp3$/i.test(file.name)?'MP3音源':'NCM原文件，制谱时解析'));
  $('audio-drop').classList.add('selected');stopPlayer('local-audio');
  if(state.audioUrl)URL.revokeObjectURL(state.audioUrl);
  state.audioUrl='';
  if(/\.mp3$/i.test(file.name)){state.audioUrl=URL.createObjectURL(file);$('local-audio').src=state.audioUrl;$('local-audio').hidden=false;}
  renderSubmit();
}
async function chooseLyrics(file){
  text('upload-error','');text('upload-notice','');state.saved=false;state.lyrics=null;
  const sequence=++state.lyricsRequest;renderSubmit();
  if(!file)return;
  if(!/\.txt$/i.test(file.name)||file.size===0||file.size>256*1024){$('lyrics-file').value='';throw new Error('请选择256KB以内、非空的TXT歌词。');}
  const data=await file.arrayBuffer();let lyrics,encoding='UTF-8';
  try{lyrics=new TextDecoder('utf-8',{fatal:true}).decode(data);}catch{try{lyrics=new TextDecoder('gb18030',{fatal:true}).decode(data);encoding='GB18030';}catch{throw new Error('歌词编码无法读取，请保存为UTF-8格式的TXT。');}}
  if(sequence!==state.lyricsRequest)return;
  if(!lyrics.trim()||lyrics.includes('\u0000'))throw new Error('歌词为空或不是可读取的文本。');
  state.lyrics=file;text('lyrics-title',file.name);text('lyrics-description',bytes(file.size)+' · 已读取配套歌词');text('lyrics-encoding',encoding);
  text('lyrics-preview',lyrics.slice(0,20000));$('lyrics-preview-wrap').hidden=false;$('lyrics-drop').classList.add('selected');renderSubmit();
}
function wireDrop(zoneId,inputId,handler){
  $(inputId).addEventListener('change',()=>handler($(inputId).files[0]).catch(error=>text('upload-error',message(error))));
  const zone=$(zoneId);
  zone.addEventListener('dragover',event=>{event.preventDefault();if(!state.xhr)zone.classList.add('dragging');});
  zone.addEventListener('dragleave',()=>zone.classList.remove('dragging'));
  zone.addEventListener('drop',event=>{event.preventDefault();zone.classList.remove('dragging');if(state.xhr)return;const files=event.dataTransfer.files;if(files.length!==1){text('upload-error','一次请选择一份文件。');return;}handler(files[0]).catch(error=>text('upload-error',message(error)));});
}
async function refreshUploads(){
  const personAtStart=state.person?.id;
  const data=await api('/api/uploads');if(state.person?.id!==personAtStart)return;state.rows=data.uploads;
  text('upload-count',String(data.uploads.length));$('empty-library').hidden=data.uploads.length>0;
  const fragment=document.createDocumentFragment();
  for(const row of data.uploads){
    const article=document.createElement('article');article.className='upload-row';
    const icon=document.createElement('span');icon.className='file-symbol';icon.textContent='♫';icon.setAttribute('aria-hidden','true');
    const body=document.createElement('div');body.className='upload-row-content';
    const title=document.createElement('strong');title.textContent=row.title;title.title=row.title;
    const details=document.createElement('p');details.textContent=row.audio.format+' · '+bytes(row.audio.bytes)+' · '+row.lyrics.name+' · '+date(row.created);body.append(title,details);
    const status=document.createElement('span');status.className='row-status';status.textContent='素材已保存';
    const view=document.createElement('button');view.className='secondary';view.textContent='查看素材';view.addEventListener('click',()=>openDetail(row));
    article.append(icon,body,status,view);fragment.append(article);
  }
  $('upload-list').replaceChildren(fragment);
}
function fileUrl(row,kind){return '/api/uploads/'+encodeURIComponent(row.id)+'/files/'+kind;}
function openDetail(row){
  text('detail-title',row.title);
  const audioNote=row.audio.duration_seconds?row.audio.duration_seconds.toFixed(1)+'秒':'NCM时长将在解析后显示';
  text('detail-info',row.audio.format+' · '+bytes(row.audio.bytes)+' · '+audioNote+' · '+date(row.created));
  text('detail-lyrics',row.lyrics_preview);$('download-audio').href=fileUrl(row,'audio');$('download-lyrics').href=fileUrl(row,'lyrics');
  stopPlayer('saved-audio');if(row.audio.format==='MP3'){$('saved-audio').src=fileUrl(row,'audio')+'?inline=1';$('saved-audio').hidden=false;}
  $('detail-dialog').showModal();
}
function submitUpload(){
  if(!state.audio||!state.lyrics||state.xhr||state.saved)return;
  text('upload-error','');text('upload-notice','');
  const personAtStart=state.person?.id;
  const xhr=new XMLHttpRequest();state.xhr=xhr;renderSubmit();
  $('upload-progress-wrap').hidden=false;$('upload-progress').value=0;text('upload-percent','0%');text('upload-stage','正在上传音源与歌词');
  xhr.open('POST','/api/uploads');xhr.timeout=15*60*1000;xhr.setRequestHeader('X-CSRF-Token',state.csrf);
  xhr.upload.onprogress=event=>{if(event.lengthComputable){const percent=Math.min(100,Math.round(event.loaded/event.total*100));$('upload-progress').value=percent;text('upload-percent',percent+'%');if(percent===100)text('upload-stage','文件已发送，正在校验并保存');}};
  const finish=()=>{state.xhr=null;$('upload-progress-wrap').hidden=true;renderSubmit();};
  xhr.onload=async()=>{
    if(state.person?.id!==personAtStart){finish();return;}
    let data={};try{data=JSON.parse(xhr.responseText);}catch{}
    if(xhr.status===201){state.saved=true;finish();$('reset-upload').hidden=false;text('upload-notice','素材已保存到下方列表。整首制谱将在下一阶段接入，你可以先查看或下载原文件。');toast('音源与歌词已保存');try{await refreshUploads();}catch(error){text('upload-error',message(error));}}
    else{finish();if(xhr.status===401)showLogin();text('upload-error',data.error||'上传没有完成，请重试。');}
  };
  xhr.onerror=()=>{finish();text('upload-error','连接中断，未能确认保存结果。请刷新素材列表后再重试。');};
  xhr.ontimeout=()=>{finish();text('upload-error','本次上传等待超时，请检查网络并刷新列表确认。');};
  xhr.onabort=()=>{finish();text('upload-error','已取消本次上传。若文件已发送完成，可刷新列表确认是否保存。');};
  const data=new FormData();data.append('audio',state.audio,state.audio.name);data.append('lyrics',state.lyrics,state.lyrics.name);xhr.send(data);
}
async function copy(value){
  try{await navigator.clipboard.writeText(value);toast('已复制');}
  catch{toast('浏览器未允许自动复制，请选中文字手动复制。');}
}
async function refreshInvites(){
  const [sharing,invitations]=await Promise.all([api('/api/admin/sharing'),api('/api/admin/invites')]);
  $('share-url').value=sharing.url||'';$('copy-share').disabled=!sharing.url;
  const fragment=document.createDocumentFragment();
  for(const friend of invitations.friends){
    const row=document.createElement('div');row.className='friend-row';const name=document.createElement('span');name.textContent=friend.name;const status=document.createElement('small');status.textContent=friend.enabled?'可访问':'已停用';row.append(name,status);
    if(friend.enabled){const button=document.createElement('button');button.className='text-button';button.textContent='停用';button.addEventListener('click',async()=>{button.disabled=true;try{await api('/api/admin/invites/'+encodeURIComponent(friend.id)+'/revoke',{method:'POST'});await refreshInvites();toast('该朋友的访问码已停用');}catch(error){button.disabled=false;text('invite-error',message(error));}});row.append(button);}
    fragment.append(row);
  }
  if(!invitations.friends.length){const empty=document.createElement('p');empty.className='help';empty.textContent='还没有邀请朋友。先填写称呼，生成第一份访问码。';fragment.append(empty);}
  $('friend-list').replaceChildren(fragment);
}
$('login-form').addEventListener('submit',async event=>{event.preventDefault();state.authRevision++;text('login-error','');$('login-submit').disabled=true;try{const data=await api('/api/session',{method:'POST',body:{code:$('access-code').value.trim()}});await showWorkspace(data.person);}catch(error){text('login-error',message(error));}finally{$('login-submit').disabled=false;}});
$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST'});showLogin();toast('已退出工作台');}catch(error){toast(message(error));}});
$('upload-form').addEventListener('submit',event=>{event.preventDefault();submitUpload();});
$('reset-upload').addEventListener('click',resetInput);$('cancel-upload').addEventListener('click',()=>state.xhr?.abort());
$('refresh-uploads').addEventListener('click',async()=>{try{await refreshUploads();toast('素材列表已更新');}catch(error){toast(message(error));}});
wireDrop('audio-drop','audio-file',chooseAudio);wireDrop('lyrics-drop','lyrics-file',chooseLyrics);
window.addEventListener('dragover',event=>event.preventDefault());window.addEventListener('drop',event=>event.preventDefault());
for(const button of document.querySelectorAll('[data-close]'))button.addEventListener('click',()=>$(button.dataset.close).close());
$('detail-dialog').addEventListener('close',()=>stopPlayer('saved-audio'));
$('invite-open').addEventListener('click',async()=>{text('invite-error','');$('invite-dialog').showModal();try{await refreshInvites();}catch(error){text('invite-error',message(error));}});
$('copy-share').addEventListener('click',()=>copy($('share-url').value));
$('invite-form').addEventListener('submit',async event=>{event.preventDefault();text('invite-error','');const button=event.currentTarget.querySelector('button');button.disabled=true;try{const data=await api('/api/admin/invites',{method:'POST',body:{name:$('friend-name').value}});state.invite=data.friend;text('new-invite-name',data.friend.name+' 的访问码');text('new-invite-code',data.friend.code);$('new-invite').hidden=false;$('friend-name').value='';await refreshInvites();}catch(error){text('invite-error',message(error));}finally{button.disabled=false;}});
$('copy-invite').addEventListener('click',()=>{if(!state.invite)return;const url=$('share-url').value;copy((url?'弦页网址：'+url+'\n':'')+'访问码：'+state.invite.code+'\n请在网站主人的电脑开机联网时使用。');});
async function health(){try{const data=await api('/api/health');text('connection',data.uploads_available?'网站在线':'音源检查暂不可用');$('connection').classList.toggle('online',data.uploads_available);}catch{text('connection','连接暂时中断');$('connection').classList.remove('online');}}
(async()=>{const revision=state.authRevision;await health();try{const data=await api('/api/session');if(revision===state.authRevision)await showWorkspace(data.person);}catch(error){if(revision===state.authRevision){showLogin();if(error.status!==401)text('login-error','暂时无法连接网站，请稍后重试。');}}setInterval(health,30000);})();
