# 歌词对齐与真实制谱：新增实际复核报告链接与混源拒绝验证，原文件不改动。
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
import json
import subprocess
# 歌词对齐与真实制谱：新增对子进程UTF-8编码的显式控制。
import os
import sys
root = Path.cwd()
score = root/'test_outputs/score_runs/20261005_190412_930/score'
class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'audio': self.links.append(values['src'])
        if tag == 'a': self.links.append(values['href'])
text = (score/'review.html').read_text(encoding='utf-8')
parsed = Links(); parsed.feed(text)
assert len(parsed.links) == 3
assert all((score/unquote(link)).resolve().is_file() for link in parsed.links)
assert 'MusicXML文件' in text
assert '歌词由用户提供，字音时间尚待核查' in text
assert 'ALIGNMENT' not in text and 'LYRICCOUNT' not in text
fixture = root/'.tools/review_guard'; fixture.mkdir(parents=True, exist_ok=True)
lyric_source = root/'test_outputs/score_runs/20261005_190412_930/lyrics/characters.json'
bad = deepcopy(json.loads(lyric_source.read_text(encoding='utf-8')))
bad['source']['sha256'] = '0'*64
bad_path = fixture/'mixed_source.characters.json'
bad_path.write_text(json.dumps(bad,ensure_ascii=False), encoding='utf-8')
# 歌词对齐与真实制谱：原调用注释保留，修复Windows默认CP936与验证器UTF-8解码不一致。
# result = subprocess.run([sys.executable,'-B',str(root/'tools/review_bundle.py'),'--analysis',str(root/'test_outputs/score_runs/20261005_190412_930/refined/analysis.json'),'--lyrics',str(bad_path),'--score-dir',str(score),'--output',str(fixture/'must_not_exist.html')],capture_output=True,text=True,encoding='utf-8')
result = subprocess.run([sys.executable,'-B',str(root/'tools/review_bundle.py'),'--analysis',str(root/'test_outputs/score_runs/20261005_190412_930/refined/analysis.json'),'--lyrics',str(bad_path),'--score-dir',str(score),'--output',str(fixture/'must_not_exist.html')],capture_output=True,text=True,encoding='utf-8',env=dict(os.environ,PYTHONIOENCODING="utf-8"))
assert result.returncode != 0 and 'SHA不一致' in result.stderr
assert not (fixture/'must_not_exist.html').exists()
report = {'task':'歌词对齐与真实制谱','scope':'actual_generated_report_and_wrong_source_negative_check','link_targets_exist':True,'musicxml_label_preserved':True,'user_reference_wording':True,'template_resolved':True,'wrong_source_rejected':True,'playback_gui_tested':False}
(root/'reports/review_bundle_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
