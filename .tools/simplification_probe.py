# 主旋律简化版：只读统计已有量化字音组，为简化阈值提供证据。
from pathlib import Path
import json,itertools,collections
p=json.loads(Path('test_outputs/score_runs/20261005_192901_116/score/project.json').read_text(encoding='utf-8'))
notes=p['quantized_notes']; normal=[n for n in notes if n['end_tick']>n['start_tick']]
groups=[]
for key,items in itertools.groupby(normal,key=lambda n:n['lyric_index']):
    items=list(items); weights=collections.Counter()
    for n in items: weights[n['pitch_midi']]+=n['end_tick']-n['start_tick']
    groups.append({'index':key,'char':p['lyrics']['characters'][key]['text'] if key is not None else None,'notes':len(items),'pitches':dict(weights),'total_ticks':sum(weights.values())})
print(json.dumps({'pieces':len(notes),'normal_pieces':len(normal),'grace':len(notes)-len(normal),'unassigned_pieces':sum(n['lyric_index'] is None for n in normal),'groups':len(groups),'multinote_groups':sum(g['notes']>1 for g in groups),'first_multinote':[g for g in groups if g['notes']>1][:14]},ensure_ascii=False))
