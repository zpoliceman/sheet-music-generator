"""朋友身份、会话与上传记录；所有写入限定在HTML/runtime。"""
from contextlib import contextmanager
import hashlib
import json
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

HTML_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = HTML_ROOT / 'runtime'
SESSION_SECONDS = 7 * 24 * 3600

def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def runtime_path(path):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(RUNTIME_ROOT.resolve()):
        raise ValueError('运行数据必须位于HTML/runtime。')
    return resolved

class Store:
    def __init__(self, root):
        self.root = runtime_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / 'portal.sqlite3'
        self.upload_root = self.root / 'uploads'
        self.upload_root.mkdir(exist_ok=True)
        (self.upload_root / '.incoming').mkdir(exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS people (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                    code_hash TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, person_id TEXT NOT NULL,
                    csrf TEXT NOT NULL, expires REAL NOT NULL,
                    FOREIGN KEY(person_id) REFERENCES people(id)
                );
                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY, person_id TEXT NOT NULL,
                    title TEXT NOT NULL, created REAL NOT NULL,
                    metadata TEXT NOT NULL,
                    FOREIGN KEY(person_id) REFERENCES people(id)
                );
                CREATE INDEX IF NOT EXISTS uploads_person ON uploads(person_id, created);
                CREATE TABLE IF NOT EXISTS score_projects (
                    id TEXT PRIMARY KEY, person_id TEXT NOT NULL, title TEXT NOT NULL,
                    project_path TEXT NOT NULL, created REAL NOT NULL,
                    FOREIGN KEY(person_id) REFERENCES people(id)
                );
            ''')
            exists = db.execute("SELECT id FROM people WHERE role='owner'").fetchone()
            if not exists:
                code = 'OWNER-' + secrets.token_urlsafe(24)
                db.execute('INSERT INTO people(id,name,role,code_hash,created) VALUES(?,?,?,?,?)',
                           (uuid.uuid4().hex, '我的工作台', 'owner', digest(code), time.time()))
                access = self.root / '管理员访问码.txt'
                access.write_text('统一制谱网页的管理员访问码\n\n' + code + '\n\n仅在本机查看此文件。登录网页后，可在“邀请朋友”中创建每人独立的访问码。不要把管理员码当作朋友码分享。\n', encoding='utf-8')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def login(self, code):
        with self.connection() as db:
            row = db.execute('SELECT id,name,role FROM people WHERE code_hash=? AND enabled=1', (digest(code.strip()),)).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(40)
            csrf = secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(token), row['id'], csrf, time.time() + SESSION_SECONDS))
            return token, {**dict(row), 'csrf': csrf}

    def session(self, token):
        if not token:
            return None
        with self.connection() as db:
            row = db.execute('''SELECT p.id,p.name,p.role,s.csrf FROM sessions s JOIN people p ON p.id=s.person_id
                WHERE s.token_hash=? AND s.expires>? AND p.enabled=1''', (digest(token), time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.connection() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token or ''),))

    def create_friend(self, name):
        name = name.strip()
        if not 1 <= len(name) <= 40 or any(ord(c) < 32 for c in name):
            raise ValueError('请填写1至40个字符的朋友称呼。')
        identity = uuid.uuid4().hex
        code = 'MUSIC-' + secrets.token_urlsafe(24)
        with self.connection() as db:
            db.execute('INSERT INTO people(id,name,role,code_hash,created) VALUES(?,?,?,?,?)',
                       (identity, name, 'friend', digest(code), time.time()))
        return {'id': identity, 'name': name, 'code': code}

    def friends(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT id,name,enabled,created FROM people WHERE role='friend' ORDER BY created DESC")]

    def revoke(self, identity):
        with self.connection() as db:
            db.execute("UPDATE people SET enabled=0 WHERE id=? AND role='friend'", (identity,))
            db.execute("DELETE FROM sessions WHERE person_id IN (SELECT id FROM people WHERE id=? AND role='friend' AND enabled=0)", (identity,))

    def publish(self, person_id, metadata):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM uploads WHERE person_id=?', (person_id,)).fetchone()[0] >= 50:
                raise ValueError('已达到本次试用的50套素材上限。')
            if not db.execute('SELECT id FROM people WHERE id=? AND enabled=1', (person_id,)).fetchone():
                raise PermissionError('访问码已停用，请重新登录。')
            db.execute('INSERT INTO uploads VALUES(?,?,?,?,?)', (metadata['id'], person_id, metadata['title'], metadata['created'], json.dumps(metadata, ensure_ascii=False)))

    def uploads(self, person_id):
        with self.connection() as db:
            return [json.loads(row['metadata']) for row in db.execute('SELECT metadata FROM uploads WHERE person_id=? ORDER BY created DESC LIMIT 200', (person_id,))]

    def upload(self, person_id, identity):
        if not re.fullmatch('[a-f0-9]{32}', identity):
            return None
        with self.connection() as db:
            row = db.execute('SELECT metadata FROM uploads WHERE person_id=? AND id=?', (person_id, identity)).fetchone()
            return json.loads(row['metadata']) if row else None

    def usage(self, person_id):
        uploads = self.uploads(person_id)
        return {'count': len(uploads), 'bytes': sum(row['audio']['bytes'] + row['lyrics']['bytes'] for row in uploads)}

    def register_score(self, person_id, project_path, title):
        """供后续制谱工作进程登记本人新成品；网页不接受任意磁盘路径。"""
        path=runtime_path(project_path)
        if path.name!='project.json' or not path.is_file():raise ValueError('请登记已经完成的曲谱工程。')
        identity=uuid.uuid4().hex
        with self.connection() as db:
            db.execute('INSERT INTO score_projects VALUES(?,?,?,?,?)',(identity,person_id,title,str(path.relative_to(HTML_ROOT)),time.time()))
        return identity

    def score_projects(self, person_id):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT id,title,project_path,created FROM score_projects WHERE person_id=? ORDER BY created DESC',(person_id,))]
