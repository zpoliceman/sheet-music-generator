"""两个网页共用的另存导出队列；原工程只读，结果按来源和访问者分目录保存。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import RLock
import hashlib,json,os,re,shutil,subprocess,sys,time,uuid
from urllib.parse import unquote
HTML=Path(__file__).resolve().parents[1];ROOT=HTML.parent
LAYOUT_ID='guitar-accompaniment-v1'

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,data):
    temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(path)

def local_library():
    index=ROOT/'results/accompaniment/index.html';result={}
    if not index.is_file():return result
    for link in re.findall(r'href="([^"]+)"',index.read_text(encoding='utf-8').split('<details>')[0]):
        path=((index.parent/unquote(link)).parent/'project.json').resolve()
        if not path.is_relative_to(ROOT/'results/accompaniment') or not path.is_file() or not(path.parent/'guitar/repeat_plan.json').is_file():continue
        identity=hashlib.sha256(path.relative_to(ROOT).as_posix().encode()).hexdigest()[:16]
        result[identity]={'path':path,'title':path.parent.name.split('_v')[0],'id':identity}
    return result

class ExportQueue:
    def __init__(self,namespace,base=None):
        if not re.fullmatch(r'[a-z0-9_-]+',namespace):raise ValueError('导出命名空间无效。')
        self.base=Path(base or HTML/'runtime/print_jobs'/namespace).resolve()
        if not self.base.is_relative_to(HTML/'runtime'):raise ValueError('导出必须保存在HTML/runtime。')
        self.base.mkdir(parents=True,exist_ok=True);self.lock=RLock();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='score_print');self.active={}
        for p in self.base.glob('*/*/job.json'):
            try:
                d=read(p)
                if d.get('status') in ('queued','running'):d.update(status='failed',error='上次导出已中断，请重新生成。');write(p,d)
            except (OSError,ValueError):continue
    def owner_root(self,owner):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',owner):raise ValueError('导出访问身份无效。')
        return self.base/owner
    def get(self,owner,identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[a-f0-9]{32}',identity):raise ValueError('导出任务不存在。')
        p=self.owner_root(owner)/identity/'job.json'
        if not p.is_file():raise ValueError('导出任务不存在。')
        return read(p)
    def public(self,job):
        result={k:job[k] for k in ('job_id','status','title','created','pages','error','layout_id') if k in job}
        if job['status']=='complete':
            result['downloads']={kind:f"/api/print/jobs/{job['job_id']}/files/{kind}" for kind in ('pdf','jpg')}
            result['images']=[f"/api/print/jobs/{job['job_id']}/pages/{i}.jpg" for i in range(1,job['pages']+1)]
        return result
    def start(self,owner,source):
        source=Path(source).resolve()
        if source.name!='project.json' or not source.is_relative_to(ROOT) or not source.is_file():raise ValueError('曲谱来源不存在。')
        parent=source.parent
        if not(parent/'guitar/repeat_plan.json').is_file():raise ValueError('此工程尚未完成吉他阅读谱导出。')
        code=b''.join(p.read_bytes() for p in sorted((HTML/'printing').glob('*.py')))+(HTML/'scripts/prepare_print_source.py').read_bytes()
        files=[source,parent/'guitar/repeat_plan.json',*sorted((parent/'guitar/rows').glob('repeat_*.svg'))]
        binding={str(p):sha(p) for p in files};fingerprint=hashlib.sha256((json.dumps(binding,sort_keys=True)+hashlib.sha256(code).hexdigest()).encode()).hexdigest()
        owner_root=self.owner_root(owner);owner_root.mkdir(exist_ok=True)
        with self.lock:
            for path in sorted(owner_root.glob('*/job.json'),reverse=True):
                previous=read(path)
                if previous.get('fingerprint')==fingerprint and previous['status'] in ('queued','running','complete'):
                    if previous['status']!='complete' or all((path.parent/'files'/name).is_file() and sha(path.parent/'files'/name)==value for name,value in previous.get('output_hashes',{}).items()):return self.public(previous)
            if owner in self.active:raise ValueError('已有一份曲谱正在导出，请等它结束后再提交。')
            identity=uuid.uuid4().hex;folder=owner_root/identity;folder.mkdir()
            title=parent.name.split('_v')[0]
            job={'job_id':identity,'status':'queued','title':title,'created':time.time(),'layout_id':LAYOUT_ID,'fingerprint':fingerprint,'source':str(source),'source_hashes':binding}
            write(folder/'job.json',job);self.active[owner]=identity;self.pool.submit(self.run,owner,job,folder)
            return self.public(job)
    def run(self,owner,job,folder):
        try:
            job['status']='running';write(folder/'job.json',job)
            env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1','TEMP':str(folder),'TMP':str(folder)}
            source=Path(job['source']).parent
            plan=read(source/'guitar/repeat_plan.json')
            if not plan.get('actual_measure_timeline') or not(source/'guitar/rows/repeat_001.svg').is_file():
                python=ROOT/'.venv-gpu/Scripts/python.exe'
                if not python.is_file():raise ValueError('此旧版工程需要主项目的Python环境进行只读排版适配。')
                prepared=folder/'source'
                self.command([str(python),'-B','-X','utf8',str(HTML/'scripts/prepare_print_source.py'),'--source',str(source),'--output',str(prepared)],folder/'prepare.log',env)
                source=prepared
            python=HTML/'.venv/Scripts/python.exe'
            if not python.is_file():raise ValueError('请先在HTML目录运行准备环境.ps1。')
            self.command([str(python),'-B','-X','utf8','-m','printing.engine','--source',str(source),'--output',str(folder/'files')],folder/'export.log',env)
            result=read(folder/'files/verification.json')
            assert result['passed']
            for p,digest in job['source_hashes'].items():
                if sha(Path(p))!=digest:raise ValueError('导出期间原谱发生改变，请重新生成。')
            outputs={k:result[n] for k,n in (('pdf','output_pdf'),('jpg','jpg_zip'))}
            images=[p.relative_to(folder/'files').as_posix() for p in sorted((folder/'files/JPG').glob('*.jpg'))]
            job.update(status='complete',title=read(source/'project.json')['accepted_vocal_project']['title'],pages=result['pages'],outputs=outputs,images=images,output_hashes={name:sha(folder/'files'/name) for name in [*outputs.values(),*images]})
            write(folder/'job.json',job)
        except Exception as error:
            (folder/'failure.txt').write_text(str(error),encoding='utf-8')
            message=str(error)
            if isinstance(error,subprocess.CalledProcessError):
                lines=(folder/'export.log').read_text(encoding='utf-8',errors='replace').splitlines() if(folder/'export.log').is_file() else []
                message=(lines[-1] if lines else '曲谱导出未完成。').split(': ',1)[-1]
            message=message.replace(str(ROOT),'本地工程').replace(str(HTML),'网页目录')
            job.update(status='failed',error=message[-400:]);write(folder/'job.json',job)
        finally:
            with self.lock:self.active.pop(owner,None)
    def command(self,args,log,env):
        with log.open('w',encoding='utf-8') as stream:
            subprocess.run(args,cwd=HTML,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    def file(self,owner,identity,kind=None,page=None):
        job=self.get(owner,identity)
        if job['status']!='complete':raise ValueError('曲谱尚未生成完成。')
        if page is not None:
            if not isinstance(page,int) or not 1<=page<=len(job['images']):raise ValueError('谱页不存在。')
            name=job['images'][page-1]
        else:
            if kind not in ('pdf','jpg'):raise ValueError('下载格式不存在。')
            name=job['outputs'][kind]
        folder=self.owner_root(owner)/identity/'files';path=(folder/name).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or sha(path)!=job['output_hashes'][name]:raise ValueError('导出文件不完整，请重新生成。')
        return path
