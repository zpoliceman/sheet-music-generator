"""器乐合理分句与十二品硬限制：另存保留包时重定位本地HTML链接，音乐与音频原字节保留。"""
# 器乐合理分句与十二品硬限制：新增通用目录搬迁处理，只改路径，不修改任何歌曲／音符或播放数据。
import html
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

ATTRIBUTES = re.compile(r'(?P<prefix>\b(?:href|src|value)\s*=\s*)(?P<quote>[\'\"])(?P<url>.*?)(?P=quote)', re.I)


def rebase_copied_html(source_package, output_package, relative_paths=None):
    source, output = Path(source_package).resolve(), Path(output_package).resolve()
    if source == output:
        raise ValueError('保留包另存不能改写原HTML。')
    paths = relative_paths if relative_paths is not None else [p.relative_to(source) for p in source.rglob('*.html')]
    changed = []
    for relative in paths:
        old, new = source / relative, output / relative
        if not old.is_file() or not new.is_file():
            continue
        content = old.read_text(encoding='utf-8')

        def replace(match):
            parts = urlsplit(html.unescape(match['url']))
            if parts.scheme or parts.netloc or not parts.path:
                return match[0]
            target = (old.parent / unquote(parts.path)).resolve()
            if not target.exists() or match['prefix'].lower().startswith('value') and not target.is_file():
                return match[0]
            if target.is_relative_to(source):
                target = output / target.relative_to(source)
            try:
                path = quote(Path(os.path.relpath(target, new.parent)).as_posix(), safe='/')
            except ValueError:
                path = target.as_uri()
            url = urlunsplit(('', '', path, parts.query, parts.fragment)) if not path.startswith('file:') else path
            return match['prefix'] + match['quote'] + html.escape(url, quote=True) + match['quote']

        rebased = ATTRIBUTES.sub(replace, content)
        if new.read_text(encoding='utf-8') != rebased:
            new.write_text(rebased, encoding='utf-8')
            changed.append(Path(relative).as_posix())
    return changed
