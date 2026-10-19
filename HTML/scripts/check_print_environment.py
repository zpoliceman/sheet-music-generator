"""检查默认吉他打印需要的独立依赖；不加载音乐模型。"""
import importlib.util,json
from pathlib import Path

def main():
    modules={'Playwright':'playwright','Pillow':'PIL','pypdf':'pypdf','PDFium':'pypdfium2'}
    missing=[name for name,module in modules.items() if importlib.util.find_spec(module) is None]
    chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not chrome.is_file():missing.append('Google Chrome（默认安装位置）')
    font=Path('C:/Windows/Fonts/msyh.ttc')
    if not font.is_file():missing.append('微软雅黑字体')
    print(json.dumps({'printing_ready':not missing,'missing':missing},ensure_ascii=False))
    if missing:raise SystemExit('默认吉他打印缺少：'+'、'.join(missing)+'。请参照HTML/README.md准备环境。')
if __name__=='__main__':main()
