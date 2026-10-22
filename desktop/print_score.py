"""桌面导出：复用认可吉他版式，并输出同源人声简谱的PDF和300DPI JPG。"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / 'HTML'
sys.path.insert(0, str(HTML))
from printing.engine import safe_title


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def command(args):
    result = subprocess.run([str(a) for a in args], cwd=HTML,
                            env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.stdout:
        print(result.stdout, end='', flush=True)
    if result.returncode:
        detail = next((line.strip() for line in reversed(result.stdout.splitlines()) if line.strip()), '打印子程序没有返回具体说明。')
        raise ValueError('曲谱导出子程序停止：' + detail)


def vocal_pdf(source, output, prepared):
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    from PIL import Image, ImageStat
    import pypdfium2 as pdfium
    info = read(prepared / 'source.json')
    output.mkdir()
    title = safe_title(info['title'])
    pdf = output / (title + '_简谱.pdf')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        try:
            page = browser.new_page(viewport={'width': 1000, 'height': 1400})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(Path(info['html']).as_uri(), wait_until='load')
            page.evaluate('document.fonts.ready')
            page.emulate_media(media='print')
            # 仅裁去SVG的空白边缘，完整包含文字、连线及音符。
            page.evaluate("""() => {
                for(const svg of document.querySelectorAll('.music-row svg')){
                    const box=svg.getBBox(), old=svg.viewBox.baseVal;
                    const left=Math.min(0,box.x-4), top=Math.min(0,box.y-5);
                    const width=Math.max(old.width,box.x+box.width+4)-left;
                    svg.setAttribute('viewBox',[left,top,width,Math.max(90,box.y+box.height+7-top)].join(' '));
                    svg.removeAttribute('height');
                }
            }""")
            bounds = page.evaluate("""(caption) => {
                const rows=[...document.querySelectorAll('.music-row')],sheets=[];
                function create(){
                    const sheet=document.createElement('article');sheet.className='sheet';
                    const header=document.createElement('header');header.innerHTML=document.querySelector(sheets.length?'#continued-header':'#first-header').innerHTML;
                    const main=document.createElement('main'),footer=document.createElement('footer');footer.textContent=caption+(sheets.length+1);
                    sheet.append(header,main,footer);document.body.append(sheet);sheets.push(sheet);return sheet;
                }
                let sheet=create();
                for(const row of rows){
                    let main=sheet.querySelector('main');main.append(row);
                    if(row.getBoundingClientRect().bottom>sheet.querySelector('footer').getBoundingClientRect().top-6 && main.children.length>1){
                        row.remove();sheet=create();main=sheet.querySelector('main');main.append(row);
                    }
                }
                document.querySelector('#vocal-rows').remove();
                sheets.forEach((s,i)=>s.querySelector('footer').textContent=caption+(i+1)+' / '+sheets.length);
                return sheets.map(s=>{const rows=[...s.querySelectorAll('.music-row')],f=s.querySelector('footer').getBoundingClientRect();
                    return {rows:rows.length,bottom:rows.at(-1).getBoundingClientRect().bottom,footer:f.top,overflow:s.scrollWidth-s.clientWidth};});
            }""",info.get('draft_caption',''))
            rendered_html=page.content()
            (output/'简谱_打印预览.html').write_text(rendered_html,encoding='utf-8')
            if errors or any(row['bottom'] > row['footer'] + .5 or row['overflow'] > 1 for row in bounds):
                raise ValueError('简谱版面超出纸张：' + str(bounds))
            page.pdf(path=str(pdf), prefer_css_page_size=True, print_background=True, tagged=True)
        finally:
            browser.close()
    reader = PdfReader(str(pdf))
    if len(reader.pages) != len(bounds):
        raise ValueError('简谱打印页数不符。')
    text = ''.join(page.extract_text() for page in reader.pages)
    actual = Counter(c for c in text if '\u4e00' <= c <= '\u9fff')
    missing = {c: n - actual[c] for c, n in info['chinese_glyphs'].items() if actual[c] < n}
    if missing:
        raise ValueError('简谱PDF丢失文字：' + str(missing))
    images = output / 'JPG'
    images.mkdir()
    document = pdfium.PdfDocument(str(pdf))
    paths = []
    try:
        for i in range(len(document)):
            page = document[i]
            bitmap = page.render(scale=300 / 72)
            try:
                path = images / (title + '_简谱_' + str(i + 1).zfill(2) + '.jpg')
                bitmap.to_pil().convert('RGB').save(path, format='JPEG', quality=95, optimize=True, dpi=(300, 300))
            finally:
                bitmap.close()
                page.close()
            with Image.open(path) as image:
                if image.width < 2400 or image.height < 3400 or ImageStat.Stat(image.convert('L')).stddev[0] < 5:
                    raise ValueError('JPG页为空白或分辨率不符。')
            paths.append(path)
    finally:
        document.close()
    archive = output / (title + '_简谱_JPG.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
        for path in paths:
            z.write(path, path.name)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None or any(hashlib.sha256(z.read(path.name)).hexdigest() != sha(path) for path in paths):
            raise ValueError('简谱JPG压缩包校验失败。')
    if sha(source) != info['source_sha256']:
        raise ValueError('打印期间源工程发生变化。')
    return {'passed': True, 'pages': len(paths), 'rows': info['rows'], 'all_lyrics_present': True, 'browser_layout': bounds}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_relative_to(ROOT) or not source.is_file() or not output.is_relative_to(HTML / 'runtime'):
        raise ValueError('打印输入或工作目录无效。')
    original_sha = sha(source)
    output.mkdir(parents=True, exist_ok=False)
    original = source.parent
    prepared = output.parent / 'prepared_guitar'
    # 新、旧工程统一通过只读适配，确保印刷需要的时间列和反复语义齐全。
    command([ROOT / '.venv-gpu/Scripts/python.exe', '-B', '-X', 'utf8', HTML / 'scripts/prepare_print_source.py', '--source', original, '--output', prepared])
    command([sys.executable, '-B', '-X', 'utf8', '-m', 'printing.engine', '--source', prepared, '--output', output / '吉他伴奏谱'])
    guitar = read(output / '吉他伴奏谱/verification.json')
    if not guitar['passed']:
        raise ValueError('吉他打印校验没有通过。')
    vocal_source = output.parent / 'prepared_vocal'
    command([ROOT / '.venv-gpu/Scripts/python.exe', '-B', '-X', 'utf8', ROOT / 'desktop/prepare_vocal_print.py', '--source', source, '--output', vocal_source])
    vocal = vocal_pdf(source, output / '简谱', vocal_source)
    if sha(source) != original_sha:
        raise ValueError('导出改变了源工程。')
    files = [{'path': path.relative_to(output).as_posix(), 'sha256': sha(path), 'kind': 'pdf' if path.suffix.lower() == '.pdf' else 'jpg'}
             for path in sorted(output.rglob('*')) if path.is_file() and path.suffix.lower() in ('.pdf', '.jpg', '.zip')]
    report = {'passed': True, 'source': str(source), 'source_sha256': original_sha, 'guitar': {'pages': guitar['pages'], 'layout': guitar['layout_id']}, 'vocal': vocal, 'files': files}
    (output / 'desktop_export.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'guitar_pages': guitar['pages'], 'vocal_pages': vocal['pages']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
