"""4/4可选右手与实时谱面试听：只监听本机的选型、局部预览和另存服务。"""
# 4/4可选右手与实时谱面试听：新增本机适配，共用Python编译／导出；不写正常曲谱入口。
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import parse_qs, unquote, urlsplit
import argparse
import hashlib
import html
import json
import mimetypes
import re
import secrets
import time
import uuid
import webbrowser
import xml.etree.ElementTree as ET

from score_export import read_json, save_json, sha256
from workspace_location import project_identity, same_workspace
from source_timing_acceptance import require_isolated_output
from guitar_pattern_selection import (catalogue, compile_selection, describe_source, fingerprint,
    measure_timeline, has_selection, normalize_plan)
from revise_guitar_selection import validate_parent, verify_sources, bind_selection, revise_selection
# 多区间右手配置与网页完整成品：保留旧页面入口，改用区间配置界面，保存／导出仍共用原入口。
# from guitar_pattern_selection_ui import editor_page
from guitar_pattern_ranges_ui import editor_page
# 多区间右手配置与网页完整成品：保留初稿导入，新增启动器找回上次保存目录。
# from guitar_pattern_configurations import ConfigurationStore, full_result
from guitar_pattern_configurations import ConfigurationStore, full_result, editor_workspace, remember_workspace

ROOT = Path(__file__).resolve().parents[1]


def current_projects(extra=()):
    # 4/4可选右手与实时谱面试听：新增从实际正常索引读取当前工程，历史目录和其它歌曲不自动冒充当前版。
    index = ROOT/'results/accompaniment/index.html'
    paths = []
    if index.is_file():
        text = index.read_text(encoding='utf-8').split('<details>')[0]
        for link in re.findall(r'href="([^"]+)"', text):
            path = (index.parent/unquote(link)).parent/'project.json'
            if path.is_file():
                paths.append(path.resolve())
    paths += [Path(p).resolve() for p in extra]
    result = {}
    for path in dict.fromkeys(paths):
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('编辑工程必须位于本工作区并且存在')
        data = read_json(path)
        if 'guitar' not in data.get('arrangements', {}):
            continue
        # 工作目录改名兼容：保留旧绝对路径编号的计算规则，由独立身份种子保证迁移前后相同。
        # identity = hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:16]
        identity = project_identity(path, ROOT)
        result[identity] = {'path':path, 'title':data['accepted_vocal_project']['title']}
    return result


class Editor:
    # 4/4可选右手与实时谱面试听：新增来源缓存和快照绑定；用户快选时前端按请求序号丢弃旧结果。
    def __init__(self, workspace, projects):
        self.workspace = require_isolated_output(workspace, ROOT)
        self.workspace.mkdir(parents=True,exist_ok=True)
        self.projects = projects
        self.token = secrets.token_hex(24)
        # 4/4可选右手与实时谱面试听：新增缓存绑定实际规则及候选文件，更新程序后旧谱图／试听不能复用同一URL。
        files=('guitar_pattern_selection.py','guitar_pattern_performance.py','guitar_pattern_preview.py',
               'accompaniment_export.py','export_timing_revision.py','data/guitar_pattern_choices.json')
        # 多区间右手配置与网页完整成品：新增范围规则参与预览指纹，更新后不误用旧缓存。
        files = (*files, 'guitar_pattern_ranges.py')
        # 右手选择后主谱实时可见更新：新增完整当前谱适配器参与规则指纹，不能复用旧显示缓存。
        files = (*files, 'guitar_pattern_live_score.py')
        # 扫弦箭头与实际弦组记谱修正：新增箭头绘制规则参与缓存指纹，旧柱式预览不能被继续复用。
        files = (*files, 'guitar_strum_notation.py')
        self.code_identity=hashlib.sha256(b''.join((Path(__file__).parent/name).read_bytes() for name in files)).hexdigest()
        self.loaded = {}
        self.previews = {}
        self.jobs = {}
        # 多区间右手配置与网页完整成品：新增同曲多套配置磁盘存储，服务重启后继续可载入。
        self.configurations = ConfigurationStore(self.workspace)
        self.lock = RLock()
        self.saver = ThreadPoolExecutor(max_workers=1,thread_name_prefix='right_hand_save')

    def load(self, identity):
        row = self.projects.get(identity)
        if row is None:
            raise ValueError('曲谱不存在')
        path = row['path']
        digest = sha256(path)
        with self.lock:
            cached = self.loaded.get(identity)
            if cached and cached['digest'] == digest:
                return cached
            project = read_json(path)
            validate_parent(project,path)
            bindings = verify_sources(project)
            context = describe_source(project)
            cached = {'project':project,'digest':digest,'path':path,'bindings':bindings,'context':context}
            self.loaded[identity] = cached
            return cached

    def score_links(self, identity):
        # 初始默认完整谱与歌词对照：新增已有成品地址，显示原谱不触发编配／来源分析或修改文件。
        source = self.projects.get(identity)
        if source is None:
            raise ValueError('曲谱不存在')
        folder = source['path'].parent/'guitar'
        page = next((name for name in ('score_full.html', 'score.html') if (folder/name).is_file()), None)
        return {'original_url': '/source/'+identity+'/guitar/score.html',
                'original_full_url': '/source/'+identity+'/guitar/'+page if page else None}

    def info(self, identity):
        # 4/4可选右手与实时谱面试听：新增当前工程真实可编辑范围。
        data = self.load(identity)
        return {**data['context'], 'title':self.projects[identity]['title'],
                'display_measure_offset':int(measure_timeline(data['project'])[0]['pickup']),
                # 初始默认完整谱与歌词对照：保留旧原谱链接字段，新增完整展开谱优先地址。
                # 'original_url':'/source/'+identity+'/guitar/score.html'}
                **self.score_links(identity)}

    def preview(self, body):
        # 4/4可选右手与实时谱面试听：新增局部真实TAB和同轴音频；保存只使用此处核对的快照。
        import numpy as np
        import soundfile as sf
        from accompaniment_analysis import SongClock
        from accompaniment_export import _synthesis_buffer
        from export_timing_revision import render_row
        from accompaniment_arrange import validate_playability
        from guitar_grip_policy import grip_position_path
        started = time.perf_counter()
        identity = body['project_id']
        source = self.load(identity)
        original = source['project']
        raw_plan = body.get('plan')
        revised, audit = compile_selection(original,raw_plan)
        if audit['music_changed']:
            bind_selection(revised,source['path'],source['digest'],source['bindings'])
        rows = measure_timeline(revised)
        candidates = audit['arranged_measures'] or source['context']['eligible_measures']
        first = body.get('first_measure') or (candidates[0] if candidates else 1)
        if type(first) is not int or not 1 <= first <= len(rows):
            raise ValueError('预览小节超出曲谱范围')
        cycles = [s['choice']['cycle_ticks'] for s in revised.get('right_hand_selection',{}).get('sections',[])]
        count = min(4,max(2,max(cycles,default=1920)//1920))
        selected_rows = rows[first-1:first-1+count]
        a, b = selected_rows[0]['start_tick'], selected_rows[-1]['end_tick']
        guitar = revised['arrangements']['guitar']
        # 4/4可选右手与实时谱面试听：新增预览只核本窗口及持续衔接；完整全曲验收在另存执行。
        local = {**guitar, 'notes':[n for n in guitar['notes'] if n['start_tick'] < b and n['end_tick'] > a],
                 'fingering_diagrams':[d for d in guitar.get('fingering_diagrams',[]) if d['start_tick'] < b and d['end_tick'] > a]}
        path = grip_position_path(local,revised['accepted_vocal_project'])
        physical = validate_playability(local,SongClock(revised['accepted_vocal_project']))
        if not path['valid'] or not physical['valid']:
            raise ValueError('这段实际按弦或持续音冲突，请调整右手型或应用范围')
        svg = render_row(revised,selected_rows,guitar=True)
        clock = SongClock(revised['accepted_vocal_project'])
        audio, origin = _synthesis_buffer(guitar,revised['accepted_vocal_project'],start_tick=a,end_tick=b)
        peak = float(np.max(abs(audio))) if len(audio) else 0
        if peak:
            audio *= .86/peak
        if not np.isfinite(audio).all():
            raise ValueError('试听合成出现无效样本')
        preview_id = fingerprint([source['digest'],raw_plan,first,selected_rows[-1]['number'],self.code_identity])[:32]
        folder = self.workspace/'previews'/preview_id
        folder.mkdir(parents=True,exist_ok=True)
        sf.write(folder/'preview.wav',audio,22050,subtype='PCM_16')
        (folder/'preview.svg').write_text(svg,encoding='utf-8')
        # 右手选择后主谱实时可见更新：新增同一编译快照的完整当前谱；未选时继续读取原完整成品。
        full_started = time.perf_counter()
        score_html = None
        if audit['music_changed']:
            from guitar_pattern_live_score import render_live_score
            full_page = folder/'current_score_rows.html'
            if full_page.is_file():
                score_html = full_page.read_text(encoding='utf-8')
            else:
                score_html = render_live_score(revised)
                # 右手选择后主谱实时可见更新：保留初稿直写，快选并发请求只读取已完整落盘的行缓存。
                # full_page.write_text(score_html,encoding='utf-8')
                temporary = folder/('current_score_rows_'+uuid.uuid4().hex+'.tmp')
                temporary.write_text(score_html,encoding='utf-8')
                temporary.replace(full_page)
        full_render_ms = (time.perf_counter()-full_started)*1000
        root = ET.fromstring(svg)
        beat_nodes = [n for n in root.iter() if n.tag.endswith('text') and n.get('y')=='489']
        beat_ticks = [t for row in selected_rows for t in range(row['start_tick'],row['end_tick'],480)]
        points = [{'seconds':clock.seconds(t),'tick':t,'x':float(n.get('x'))} for t,n in zip(beat_ticks,beat_nodes)]
        lines = [n for n in root.iter() if n.get('class')=='tab-string-line']
        if lines:
            points.append({'seconds':clock.seconds(b),'tick':b,'x':max(float(n.get('x2')) for n in lines)})
        snapshot = {'source_id':identity,'source_sha256':source['digest'],'plan':raw_plan,
                    'normalized_plan':normalize_plan(raw_plan,original),'preview_id':preview_id,'code_identity':self.code_identity}
        with self.lock:
            self.previews[preview_id] = snapshot
        response = {'preview_id':preview_id, 'svg':svg,'audio_url':'/preview/'+preview_id+'/preview.wav',
            'first_measure':first,'last_measure':selected_rows[-1]['number'],'origin_seconds':origin,
            'display_first_measure':first-int(rows[0]['pickup']),
            'display_last_measure':selected_rows[-1]['number']-int(rows[0]['pickup']),
            'duration_seconds':len(audio)/22050,'beat_positions':points,'music_changed':audit['music_changed'],
            'arranged_measures':audit['arranged_measures'],'exceptions':audit.get('exceptions',source['context']['exceptions']),
            'elapsed_ms':(time.perf_counter()-started)*1000,
            'validation_scope':'preview_window_playability_full_export_checks_on_save'}
        # 右手选择后主谱实时可见更新：保留原仅局部返回式，新增主谱实际行和明确应用元数据。
        response.update(score_html=score_html, score_measure_count=len(rows), score_note_count=len(guitar['notes']),
                        full_score_render_ms=full_render_ms)
        # save_json(folder/'preview.json',{k:v for k,v in response.items() if k!='svg'})
        save_json(folder/'preview.json',{k:v for k,v in response.items() if k not in ('svg','score_html')})
        save_json(folder/'selection_snapshot.json',snapshot)
        return response

    # 多区间右手配置与网页完整成品：保留旧签名，新参数绑定本次命名配置；旧调用继续可用。
    # def save(self, preview_id):
    def save(self, preview_id, configuration=None):
        # 4/4可选右手与实时谱面试听：新增保存绑定当前预览和父工程摘要；新请求不能改掉进行中的保存。
        snapshot = self.previews.get(preview_id)
        if snapshot is None or snapshot['normalized_plan'] is None:
            raise ValueError('请先选择右手型并等待预览完成')
        source = self.load(snapshot['source_id'])
        if source['digest'] != snapshot['source_sha256']:
            raise ValueError('原工程已改变，请重新预览')
        # 多区间右手配置与网页完整成品：新增保存前验证配置来源，完整导出成功后才更新该配置。
        prepared = self.configurations.prepare(snapshot['source_id'], source['digest'], configuration)
        job_id = uuid.uuid4().hex[:16]
        version = time.strftime('v%Y%m%d_%H%M%S')+'_'+job_id[:6]
        output = self.workspace/'saved'/version
        self.jobs[job_id] = {'status':'running','job_id':job_id}
        def run():
            try:
                result = revise_selection(source['path'],output,snapshot['plan'],self.workspace/'features')
                # 4/4可选右手与实时谱面试听：新增HTTP访问时原谱链接回本机只读路由，离线仍保留相对文件链接。
                page=output/'index.html'
                script='<script>if(location.protocol.startsWith("http")){document.getElementById("original-score-link").href='+json.dumps('/source/'+snapshot['source_id']+'/index.html')+';}</script>'
                page.write_text(page.read_text(encoding='utf-8').replace('</body>',script+'</body>'),encoding='utf-8')
                # 多区间右手配置与网页完整成品：保留仅链接的旧结果，新增当前页完整成品及可复用配置。
                # self.jobs[job_id] = {'status':'complete','job_id':job_id,'url':'/saved/'+version+'/index.html','result':result}
                delivery = full_result(output, version)
                record = self.configurations.save(prepared, snapshot['plan'], delivery)
                save_json(output/'configuration.json', record)
                self.jobs[job_id] = {'status':'complete','job_id':job_id, **delivery,
                                     'configuration':record, 'result':result}
            except Exception as exc:
                self.jobs[job_id] = {'status':'failed','job_id':job_id,'error':str(exc),'output':str(output)}
        self.saver.submit(run)
        return {'job_id':job_id}


def handler_for(editor):
    # 4/4可选右手与实时谱面试听：新增同源本机请求及受限文件服务，避免网页写入任意路径。
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def json(self, value, status=200):
            raw = json.dumps(value,ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            try:self.wfile.write(raw)
            # 初始默认完整谱与歌词对照：保留旧断连处理，快速切歌主动取消请求时也处理Windows中止连接。
            # except (BrokenPipeError,ConnectionResetError):pass
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

        def file(self, path, root):
            path, root = Path(path).resolve(), Path(root).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError('文件不存在')
            size = path.stat().st_size
            begin, end = 0, size-1
            match = re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers.get('Range',''))
            if match:
                begin = int(match[1]); end = min(end,int(match[2]) if match[2] else end)
                if begin > end:
                    self.send_response(416);self.end_headers();return
            self.send_response(206 if match else 200)
            self.send_header('Content-Type',mimetypes.guess_type(path)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(end-begin+1));self.send_header('Accept-Ranges','bytes')
            if match:self.send_header('Content-Range',f'bytes {begin}-{end}/{size}')
            self.end_headers()
            try:
                with path.open('rb') as stream:
                    stream.seek(begin);remaining=end-begin+1
                    while remaining:
                        block=stream.read(min(65536,remaining))
                        if not block:break
                        self.wfile.write(block);remaining-=len(block)
            # 初始默认完整谱与歌词对照：保留旧文件断连处理，读取完整原谱时取消下载属于正常切歌。
            # except (BrokenPipeError,ConnectionResetError):pass
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

        def do_GET(self):
            try:
                request=urlsplit(self.path);path=unquote(request.path);query=parse_qs(request.query)
                if path=='/':
                    raw=editor_page(editor.token).encode('utf-8');self.send_response(200)
                    self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
                    self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
                elif path in ('/editor.js','/editor.css'):
                    self.file(Path(__file__).parent/('guitar_pattern_editor'+Path(path).suffix),Path(__file__).parent)
                # 多区间右手配置与网页完整成品：新增区间界面资源，原页面脚本保持为历史实现。
                elif path in ('/ranges.js', '/ranges.css'):
                    self.file(Path(__file__).parent/('guitar_pattern_ranges'+('_editor.js' if path.endswith('.js') else '.css')),Path(__file__).parent)
                # 右手候选悬停六线谱预览：新增只读候选组件资源，真实选型与保存接口保持原入口。
                elif path in ('/pattern-picker.js', '/pattern-picker.css'):
                    self.file(Path(__file__).parent/('guitar_pattern_picker'+Path(path).suffix),Path(__file__).parent)
                elif path=='/api/catalogue':self.json(catalogue())
                elif path=='/api/health':self.json({'application':'guitar_right_hand_editor','version':1,
                    'workspace_root':str(ROOT), 'workspace':str(editor.workspace)})
                # 初始默认完整谱与歌词对照：保留旧列表，新增轻量原谱地址，使初始谱面不等待完整来源校验。
                # elif path=='/api/projects':self.json({'projects':[{'id':k,'title':v['title']} for k,v in editor.projects.items()]})
                elif path=='/api/projects':self.json({'projects':[{'id':k,'title':v['title'],**editor.score_links(k)} for k,v in editor.projects.items()]})
                elif path=='/api/project':self.json(editor.info(query['id'][0]))
                # 多区间右手配置与网页完整成品：新增读取绑定同曲的命名配置，过期配置明确标记。
                elif path=='/api/configurations':
                    identity=query['project_id'][0]; source=editor.load(identity)
                    self.json({'configurations':editor.configurations.list(identity, source['digest'])})
                elif path=='/api/save':self.json(editor.jobs[query['id'][0]])
                elif path.startswith('/preview/'):
                    parts=path.split('/')
                    if len(parts)!=4 or not re.fullmatch('[a-f0-9]{32}',parts[2]) or parts[3] not in ('preview.wav','preview.svg'):
                        raise ValueError('预览文件不存在')
                    self.file(editor.workspace/'previews'/parts[2]/parts[3],editor.workspace/'previews')
                elif path.startswith('/saved/'):
                    self.file(editor.workspace/path.lstrip('/'),editor.workspace/'saved')
                elif path.startswith('/source/'):
                    parts=path.split('/',3);source=editor.projects.get(parts[2])
                    if not source or len(parts)!=4:raise ValueError('原谱不存在')
                    self.file(source['path'].parent/parts[3],source['path'].parent)
                else:self.json({'error':'页面不存在'},404)
            except (ValueError,KeyError,FileNotFoundError) as exc:self.json({'error':str(exc)},400)
            # 初始默认完整谱与歌词对照：保留旧页面断连处理，切歌取消响应不输出线程异常。
            # except (BrokenPipeError,ConnectionResetError):pass
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

        def do_POST(self):
            try:
                if self.headers.get('X-Editor-Token') != editor.token or self.headers.get_content_type()!='application/json':
                    self.json({'error':'请从本机右手选择页面操作'},403);return
                origin=self.headers.get('Origin')
                if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                    self.json({'error':'请求来源不符'},403);return
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 131072:raise ValueError('请求内容过大或为空')
                body=json.loads(self.rfile.read(length))
                if self.path=='/api/preview':self.json(editor.preview(body))
                # 多区间右手配置与网页完整成品：保留旧仅预览ID的保存请求，增加命名配置快照。
                # elif self.path=='/api/save':self.json(editor.save(body['preview_id']))
                elif self.path=='/api/save':self.json(editor.save(body['preview_id'], body.get('configuration')))
                else:self.json({'error':'操作不存在'},404)
            except Exception as exc:self.json({'error':str(exc)},400)
    return Handler


def main():
    # 4/4可选右手与实时谱面试听：新增可重复启动的本地入口，输出均在隔离编辑目录。
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,action='append',default=[])
    # 多区间右手配置与网页完整成品：保留旧固定默认目录，未指定时从本机记忆找回原配置目录。
    # parser.add_argument('--workspace',type=Path,default=ROOT/'test_outputs/accompaniment_runs/right_hand_editor')
    parser.add_argument('--workspace',type=Path)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    # 4/4可选右手与实时谱面试听：新增再次双击启动器时打开已运行的同一编辑器。
    if args.open and not args.project:
        import urllib.request
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/health',timeout=1) as response:
                health=json.load(response)
            if same_workspace(health, ROOT):
                webbrowser.open(f'http://127.0.0.1:{args.port}/');return
        except (OSError,ValueError):pass
    # 多区间右手配置与网页完整成品：保留旧构造，默认端口沿用上次保存目录，其它测试端口不改变用户记忆。
    # editor=Editor(args.workspace,current_projects(args.project))
    workspace = editor_workspace(ROOT, args.workspace) if args.port==8766 else (args.workspace or ROOT/'test_outputs/accompaniment_runs/right_hand_editor')
    editor=Editor(workspace,current_projects(args.project))
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(editor))
    if args.port==8766: remember_workspace(ROOT, editor.workspace)
    url=f'http://127.0.0.1:{server.server_port}/'
    print(url,flush=True)
    save_json(editor.workspace/'server.json',{'url':url,'projects':len(editor.projects),'workspace':str(editor.workspace)})
    if args.open:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();editor.saver.shutdown(wait=False)


if __name__=='__main__':
    # 4/4可选右手与实时谱面试听：新增直接执行保护。
    main()
