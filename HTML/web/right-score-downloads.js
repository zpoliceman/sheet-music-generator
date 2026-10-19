(() => {
  const mode=document.getElementById('print-source-mode');let contextKey='',lastVersion=null;
  const request=async(path,body)=>{const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Editor-Token':window.EDITOR_TOKEN}:{},body:body?JSON.stringify(body):undefined});const data=await response.json();if(!response.ok)throw new Error(data.error||'导出请求未完成');return data;};
  const getSource=()=>{
    const c=window.guitarPrintContext?.();if(!c?.project_id)return null;
    if(c.saving)return {error:'整曲正在保存，完成后即可下载。'};
    if(mode.value==='saved')return !c.version?{error:'请先保存并生成整曲。'}:c.needs_save?{error:'当前调整尚未保存，请先点击“保存并生成整曲”。'}:{project_id:c.project_id,version:c.version};
    return {project_id:c.project_id};
  };
  const downloads=new window.ScoreDownloads(document.getElementById('right-score-downloads'),{request,getSource});
  function sync(){
    const c=window.guitarPrintContext?.();mode.options[1].disabled=!c?.version;
    if(c?.version&&c.version!==lastVersion)mode.value='saved';
    if(!c?.version)mode.value='original';lastVersion=c?.version||null;
    // 局部预览是否有变化，不会改变默认原谱；按实际导出来源决定是否取消下载。
    const key=JSON.stringify(getSource());if(key!==contextKey){contextKey=key;downloads.reset();}else downloads.sync();
  }
  window.addEventListener('guitar-print-context',sync);mode.addEventListener('change',()=>{contextKey=JSON.stringify(getSource());downloads.reset();});sync();
})();
