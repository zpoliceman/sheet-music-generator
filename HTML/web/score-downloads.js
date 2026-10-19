/* 默认吉他排版下载：两个网页使用同一组件与同一导出队列。 */
window.ScoreDownloads=class {
  constructor(host,{request,getSource}){
    this.host=host;this.request=request;this.getSource=getSource;this.sequence=0;this.busy=false;
    host.classList.add('score-downloads');
    host.innerHTML='<div class="score-download-controls"><label>下载格式<select class="score-format" aria-label="曲谱下载格式"><option value="pdf">PDF 文档</option><option value="jpg">整套 JPG（压缩包）</option></select></label><button type="button" class="primary score-export">生成并下载</button></div><p class="score-export-status" role="status">使用默认弹唱排版：指型图、六线谱、演唱简谱和歌词。</p><div class="score-export-links" hidden></div><details class="score-pages" hidden><summary>预览完整谱</summary><div></div></details>';
    this.format=host.querySelector('select');this.button=host.querySelector('button');this.status=host.querySelector('[role=status]');this.links=host.querySelector('.score-export-links');this.pages=host.querySelector('details');
    this.button.addEventListener('click',()=>this.start());this.sync();
  }
  sync(){const source=this.getSource();this.button.disabled=this.busy||!source||!!source.error;if(!this.busy)this.status.textContent=source?.error||(!source?'还没有可以导出的曲谱。':'将按默认版式另存，已有曲谱和配置保持。');}
  reset(){this.sequence++;this.busy=false;this.links.replaceChildren();this.links.hidden=true;this.pages.hidden=true;this.pages.querySelector('div').replaceChildren();this.sync();}
  async start(){
    const source=this.getSource();if(!source||source.error){this.sync();return;}
    const payload={...source};delete payload.error;const key=JSON.stringify(payload);const sequence=++this.sequence;const format=this.format.value;
    this.busy=true;this.button.disabled=true;this.status.textContent='正在创建另存任务…';this.links.hidden=true;this.pages.hidden=true;
    try{
      let {job}=await this.request('/api/print/jobs',payload);
      while(job.status==='queued'||job.status==='running'){
        if(sequence!==this.sequence)return;
        this.status.textContent=job.status==='queued'?'正在排队导出…':'正在排版并生成 PDF 和整套 JPG…';
        await new Promise(resolve=>setTimeout(resolve,900));
        ({job}=await this.request('/api/print/jobs/'+encodeURIComponent(job.job_id)));
      }
      if(sequence!==this.sequence)return;
      const now=this.getSource();const current={...now};delete current.error;
      if(JSON.stringify(current)!==key||now?.error)throw new Error('当前曲谱或配置已经改变，请重新生成下载文件。');
      if(job.status!=='complete')throw new Error(job.error||'曲谱导出未完成，请重试。');
      this.status.textContent='已另存 '+job.pages+' 页，原曲谱和配置保持。';this.links.replaceChildren();
      for(const [kind,label] of [['pdf','下载 PDF'],['jpg','下载整套 JPG']]){
        const a=document.createElement('a');a.href=job.downloads[kind];a.textContent=label;a.className='secondary';a.download='';this.links.append(a);
      }
      this.links.hidden=false;const target=this.pages.querySelector('div');target.replaceChildren();
      for(const [i,url] of job.images.entries()){const img=document.createElement('img');img.src=url;img.alt='吉他伴奏谱第'+(i+1)+'页';img.loading='lazy';target.append(img);}
      this.pages.hidden=false;this.pages.querySelector('summary').textContent='预览完整谱（'+job.pages+'页）';
      const a=this.links.querySelectorAll('a')[format==='jpg'?1:0];a.click();
    }catch(error){if(sequence===this.sequence)this.status.textContent=error.message||'导出未完成，请重试。';}
    finally{if(sequence===this.sequence){this.busy=false;this.button.disabled=!this.getSource()||!!this.getSource()?.error;}}
  }
};
