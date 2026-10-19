"""第一阶段统一网页：邀请访问、素材上传和本人文件读取。"""
import asyncio
from collections import defaultdict, deque
import json
import hashlib
import logging
import secrets
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException
from .storage import HTML_ROOT, Store
from printing.jobs import ExportQueue,local_library
from starlette.concurrency import run_in_threadpool
from .uploads import AUDIO_LIMIT, BODY_LIMIT, LYRICS_LIMIT, InvalidUpload, find_ffprobe, receive_upload

COOKIE = 'music_portal_session'

class BodyTooLarge(MultiPartException):
    pass

class RequestBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {key.decode('latin1').lower(): value.decode('latin1') for key, value in scope.get('headers', [])}
        limit = BODY_LIMIT if scope['path'] == '/api/uploads' else 8192
        if scope['method'] in ('POST', 'PUT', 'PATCH'):
            try:
                declared = int(headers.get('content-length', '0'))
            except ValueError:
                return await JSONResponse({'error': '请求大小无效。'}, 400)(scope, receive, send)
            if declared < 0 or declared > limit:
                return await JSONResponse({'error': '提交内容过大。音源上限80MB，歌词上限256KB。'}, 413)(scope, receive, send)
        consumed = 0
        request_complete = scope['method'] not in ('POST', 'PUT', 'PATCH')
        response_started = False
        async def limited_receive():
            nonlocal consumed, request_complete
            message = await receive()
            if message['type'] == 'http.disconnect' and scope['path'] == '/api/uploads' and not request_complete and not response_started:
                raise MultiPartException('上传连接已中断，请重新提交。')
            if message['type'] == 'http.request':
                consumed += len(message.get('body', b''))
                request_complete = not message.get('more_body', False)
                if consumed > limit and scope['method'] in ('POST', 'PUT', 'PATCH'):
                    scope['portal_body_too_large'] = True
                    raise BodyTooLarge('提交内容过大。')
            return message
        async def secured_send(message):
            nonlocal response_started
            if message['type'] == 'http.response.start':
                response_started = True
                response_headers = list(message.get('headers', []))
                response_headers += [(b'x-content-type-options', b'nosniff'), (b'x-frame-options', b'DENY'),
                    (b'referrer-policy', b'no-referrer'), (b'cache-control', b'no-store'),
                    (b'content-security-policy', b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
                message['headers'] = response_headers
            await send(message)
        return await self.app(scope, limited_receive, secured_send)

class LoginGate:
    def __init__(self):
        self.failures = defaultdict(deque)

    def allowed(self, key):
        now = time.monotonic()
        recent = self.failures[key]
        while recent and recent[0] < now - 600:
            recent.popleft()
        return len(recent) < 12

    def failed(self, key):
        self.failures[key].append(time.monotonic())


def create_app(data_dir=None):
    store = Store(data_dir or HTML_ROOT / 'runtime' / 'app')
    temporary = store.root / 'tmp'
    temporary.mkdir(exist_ok=True)
    tempfile.tempdir = str(temporary)
    app = FastAPI(title='弦页 · 歌曲素材工作台', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestBoundary)
    app.state.store = store
    app.state.upload_slots = asyncio.Semaphore(2)
    app.state.gate = LoginGate()
    app.state.exports = ExportQueue('portal',store.root/'print_jobs')
    web = HTML_ROOT / 'web'

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        status = 413 if request.scope.get('portal_body_too_large') else error.status_code
        detail = str(error.detail)
        if status == 404:
            detail = '页面或素材不存在。'
        return JSONResponse({'error': detail}, status)

    @app.exception_handler(MultiPartException)
    async def multipart_error(request, error):
        return JSONResponse({'error': str(error)}, 413 if request.scope.get('portal_body_too_large') else 400)

    @app.exception_handler(InvalidUpload)
    async def invalid_upload(request, error):
        return JSONResponse({'error': str(error)}, error.status)

    @app.exception_handler(Exception)
    async def server_error(request, error):
        logging.exception('素材网站未完成请求')
        return JSONResponse({'error': '网站暂时无法完成这次操作，请稍后重试。'}, 500)

    def origin_check(request):
        origin = request.headers.get('origin')
        if origin and (urlsplit(origin).netloc.lower() != request.headers.get('host', '').lower() or urlsplit(origin).scheme not in ('http', 'https')):
            raise HTTPException(403, '请从当前网站页面提交。')

    def person_for(request, write=False, owner=False):
        person = store.session(request.cookies.get(COOKIE))
        if not person:
            raise HTTPException(401, '请先输入访问码登录。')
        if owner and person['role'] != 'owner':
            raise HTTPException(403, '只有网站主人可以管理邀请。')
        if write:
            origin_check(request)
            submitted = request.headers.get('x-csrf-token', '')
            if not submitted or not submitted.isascii() or not secrets.compare_digest(submitted, person['csrf']):
                raise HTTPException(403, '页面验证已失效，请刷新后重新操作。')
        return person

    async def json_body(request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, '请从网页提交这项操作。')
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, '提交内容无法读取。') from None
        if not isinstance(body, dict):
            raise HTTPException(400, '提交内容格式不正确。')
        return body

    @app.get('/')
    async def home():
        return FileResponse(web / 'index.html', media_type='text/html')

    @app.get('/app.js')
    async def javascript():
        return FileResponse(web / 'app.js', media_type='application/javascript')

    @app.get('/style.css')
    async def stylesheet():
        return FileResponse(web / 'style.css', media_type='text/css')

    @app.get('/score-downloads.js')
    async def score_download_script():
        return FileResponse(web/'score-downloads.js',media_type='application/javascript')

    @app.get('/score-downloads.css')
    async def score_download_style():
        return FileResponse(web/'score-downloads.css',media_type='text/css')

    def sources_for(person):
        sources=local_library() if person['role']=='owner' else {}
        for row in store.score_projects(person['id']):
            path=(HTML_ROOT/row['project_path']).resolve()
            if path.is_relative_to(HTML_ROOT/'runtime') and path.is_file():sources[row['id']]={'id':row['id'],'title':row['title'],'path':path}
        return sources

    @app.get('/api/scores')
    async def scores(request: Request):
        person=person_for(request)
        return {'scores':[{'id':row['id'],'title':row['title']} for row in sources_for(person).values()],
                'local_library_visible':person['role']=='owner','layout':'guitar-accompaniment-v1'}

    @app.post('/api/print/jobs',status_code=202)
    async def create_print(request: Request):
        person=person_for(request,write=True);body=await json_body(request)
        identity=body.get('project_id')
        if not isinstance(identity,str):raise HTTPException(400,'请选择一份曲谱。')
        source=sources_for(person).get(identity)
        if not source:raise HTTPException(404,'曲谱不存在，或不属于当前访问码。')
        try:job=await run_in_threadpool(app.state.exports.start,person['id'],source['path'])
        except ValueError as error:raise HTTPException(400,str(error)) from None
        return {'job':job}

    @app.get('/api/print/jobs/{identity}')
    async def print_status(identity: str,request: Request):
        person=person_for(request)
        try:return {'job':app.state.exports.public(app.state.exports.get(person['id'],identity))}
        except ValueError:raise HTTPException(404,'导出任务不存在。') from None

    @app.get('/api/print/jobs/{identity}/files/{kind}')
    async def print_download(identity: str,kind: str,request: Request):
        person=person_for(request)
        try:path=app.state.exports.file(person['id'],identity,kind)
        except ValueError:raise HTTPException(404,'下载文件不存在或尚未完成。') from None
        return FileResponse(path,filename=path.name,media_type='application/pdf' if kind=='pdf' else 'application/zip')

    @app.get('/api/print/jobs/{identity}/pages/{number}.jpg')
    async def print_page(identity: str,number: int,request: Request):
        person=person_for(request)
        try:path=app.state.exports.file(person['id'],identity,page=number)
        except ValueError:raise HTTPException(404,'谱页不存在。') from None
        return FileResponse(path,media_type='image/jpeg')

    @app.get('/api/health')
    async def health():
        return {'application': 'sheet_music_upload_portal', 'version': '0.1.0', 'stage': 'uploads',
                'instance': hashlib.sha256(str(HTML_ROOT.resolve()).casefold().encode()).hexdigest()[:16],
                'uploads_available': find_ffprobe() is not None, 'generation_available': False,'printing_available':True,'print_layout':'guitar-accompaniment-v1'}

    @app.get('/api/session')
    async def session(request: Request):
        person = person_for(request)
        return {'person': person, 'limits': {'audio_bytes': AUDIO_LIMIT, 'lyrics_bytes': LYRICS_LIMIT, 'songs': 50}, 'generation_available': False}

    @app.post('/api/session')
    async def login(request: Request):
        origin_check(request)
        key = request.client.host if request.client else 'unknown'
        if not app.state.gate.allowed(key):
            raise HTTPException(429, '访问码尝试次数较多，请10分钟后再试。')
        body = await json_body(request)
        code = body.get('code')
        if not isinstance(code, str) or not 8 <= len(code) <= 160:
            app.state.gate.failed(key)
            raise HTTPException(401, '访问码不正确或已经停用。')
        result = store.login(code)
        if not result:
            app.state.gate.failed(key)
            raise HTTPException(401, '访问码不正确或已经停用。')
        token, person = result
        response = JSONResponse({'person': person})
        response.set_cookie(COOKIE, token, max_age=7 * 24 * 3600, httponly=True, secure=request.url.scheme == 'https', samesite='strict')
        return response

    @app.post('/api/logout')
    async def logout(request: Request):
        person_for(request, write=True)
        store.logout(request.cookies.get(COOKIE))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE)
        return response

    @app.get('/api/uploads')
    async def uploads(request: Request):
        person = person_for(request)
        return {'uploads': store.uploads(person['id']), 'usage': store.usage(person['id'])}

    @app.post('/api/uploads', status_code=201)
    async def upload(request: Request):
        person = person_for(request, write=True)
        if not request.headers.get('content-type', '').startswith('multipart/form-data'):
            raise HTTPException(415, '请同时上传音源和歌词文件。')
        async with app.state.upload_slots:
            async with request.form(max_files=2, max_fields=0, max_part_size=LYRICS_LIMIT) as form:
                result = await receive_upload(store, person, form)
        return {'upload': result, 'message': '素材已保存。整首制谱将在下一阶段接入。'}

    @app.get('/api/uploads/{identity}')
    async def upload_info(identity: str, request: Request):
        person = person_for(request)
        result = store.upload(person['id'], identity)
        if not result:
            raise HTTPException(404)
        return {'upload': result}

    @app.get('/api/uploads/{identity}/files/{kind}')
    async def download(identity: str, kind: str, request: Request):
        person = person_for(request)
        row = store.upload(person['id'], identity)
        if not row or kind not in ('audio', 'lyrics', 'normalized'):
            raise HTTPException(404)
        base = store.upload_root / person['id'] / identity
        if kind == 'audio':
            path = base / ('audio.' + row['audio']['format'].lower())
            name = row['audio']['name']
            media = 'audio/mpeg' if row['audio']['format'] == 'MP3' else 'application/octet-stream'
        elif kind == 'lyrics':
            path, name, media = base / 'lyrics.original.txt', row['lyrics']['name'], 'application/octet-stream'
        else:
            path, name, media = base / 'lyrics.txt', row['title'] + '_歌词_UTF8.txt', 'text/plain; charset=utf-8'
        if not path.resolve().is_relative_to(store.upload_root.resolve()) or not path.is_file():
            raise HTTPException(404)
        disposition = 'inline' if kind == 'audio' and request.query_params.get('inline') == '1' else 'attachment'
        return FileResponse(path, filename=name, media_type=media, content_disposition_type=disposition)

    @app.get('/api/admin/invites')
    async def invites(request: Request):
        person_for(request, owner=True)
        return {'friends': store.friends()}

    @app.post('/api/admin/invites')
    async def invite(request: Request):
        person_for(request, write=True, owner=True)
        body = await json_body(request)
        name = body.get('name', '')
        if not isinstance(name, str):
            raise HTTPException(400, '请填写朋友称呼。')
        try:
            return {'friend': store.create_friend(name)}
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.post('/api/admin/invites/{identity}/revoke')
    async def revoke(identity: str, request: Request):
        person_for(request, write=True, owner=True)
        store.revoke(identity)
        return {'ok': True}

    @app.get('/api/admin/sharing')
    async def sharing(request: Request):
        person_for(request, owner=True)
        path = store.root / 'sharing.json'
        result = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        url = result.get('url', '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith(('.trycloudflare.com', '.ngrok-free.app', '.ngrok-free.dev')):
            url = ''
        return {'url': url, 'temporary': True, 'note': '电脑、网页服务和分享进程保持运行时可用。'}

    return app
