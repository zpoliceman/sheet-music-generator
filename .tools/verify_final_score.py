# 歌词对齐与真实制谱：新增最终产物清单核查，读取现有证据不改变音乐数据。
from pathlib import Path
from urllib.parse import unquote
from html.parser import HTMLParser
import hashlib,json,xml.etree.ElementTree as ET
root=Path.cwd(); run_id='20261005_192901_116'
folder=root/'test_outputs/score_runs'/run_id; score=folder/'score'; reports=root/'reports/score_runs'/run_id
load=lambda p: json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
run=load(reports/'run.json'); project=load(score/'project.json'); report=load(reports/'score_export.json'); chars=load(folder/'lyrics/characters.json')
assert run['status']=='draft_generated_requires_musical_review'
assert run['alignment_reused'] and chars['reference_kind']=='user_supplied'
assert sha(run['source_analysis']).upper()==run['source_analysis_sha256']
assert sha(run['input_audio']).upper()==run['input_audio_sha256']
assert chars['source']['sha256']==sha(chars['source']['path'])
assert report['lyric_mapping']['mapped_characters']==report['lyric_mapping']['character_count']==237
assert report['validation']['valid'] and report['statistics']['measure_count']==82
assert report['statistics']['total_ticks']==82*1920
xml=ET.parse(score/'vocal_draft.musicxml').getroot(); assert len(xml.findall('part/measure'))==82
xml_text=[lyric.text for lyric in xml.findall('.//note/lyric/text')]
assert ''.join(xml_text)==''.join(c['text'] for c in chars['characters'])
assert len(chars['characters'])==237
assert sum(bool(c['warnings']) for c in chars['characters'])==69
assert (score/'vocal_draft.mid').read_bytes().startswith(b'MThd')
svg=ET.parse(score/'jianpu.svg').getroot()
assert float(svg.attrib['width'])>0 and float(svg.attrib['height'])>0
class Links(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='audio': self.links.append(a['src'])
        if tag=='a': self.links.append(a['href'])
html_text=(score/'review.html').read_text(encoding='utf-8'); parsed=Links(); parsed.feed(html_text)
assert len(parsed.links)==3 and all((score/unquote(link)).resolve().is_file() for link in parsed.links)
assert 'MusicXML文件' in html_text and '歌词由用户提供' in html_text
artifacts={p.name:{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in score.iterdir() if p.is_file()}
result={'task':'歌词对齐与真实制谱','run_id':run_id,'status':'draft_artifacts_checked_not_musically_verified','source_hashes_unchanged':True,'lyric_sequence_exact_user_237_characters':True,'measure_count':82,'quarter_beats':report['statistics']['total_ticks']/480,'lyric_warning_characters':69,'review_links_valid':True,'png_visual_checked':'spacing_compare_from_same_project; final image awaiting root view','gui_editor_roundtrip':'not_tested','artifacts':artifacts}
(root/'reports/final_score_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='artifacts'},ensure_ascii=False))
