"""常用指型与器乐独奏：有来源的离线候选库及真实和弦音校验。"""
# 常用指型与器乐独奏：新增低耦合数据层，编配与图式层共用候选，不依赖网络。
from __future__ import annotations
from functools import lru_cache
import json
from pathlib import Path
from accompaniment_analysis import CHORD_TYPES

LIBRARY_PATH = Path(__file__).resolve().parent / 'data' / 'guitar_common_grips.json'
TUNING = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}


# 常用指型与器乐独奏：新增按绝对品数重算音高，拒绝和弦名错误、外来音或缺性质音的来源数据。
def validate_definition(item):
    frets = item['frets_6_to_1']
    if len(frets) != 6 or any(type(f) is not int or f < -1 or f > 20 for f in frets):
        return False
    pitches = [TUNING[s] + f for s, f in zip(range(6, 0, -1), frets) if f >= 0]
    if not pitches or item['quality'] not in CHORD_TYPES:
        return False
    intervals = CHORD_TYPES[item['quality']]
    expected = {(item['root_pc'] + i) % 12 for i in intervals} | {item['bass_pc']}
    required = {(item['root_pc'] + i) % 12 for i in intervals if i != 7}
    if len(intervals) <= 3:
        required = {(item['root_pc'] + i) % 12 for i in intervals}
    actual = {p % 12 for p in pitches}
    return required <= actual <= expected and min(pitches) % 12 == item['bass_pc']


# 常用指型与器乐独奏：新增缓存及启动时的候选语义核验，原始开源库不直接当音乐真值。
@lru_cache(maxsize=1)
def load_library():
    data = json.loads(LIBRARY_PATH.read_text(encoding='utf-8'))
    entries = data['entries']
    if len({e['id'] for e in entries}) != len(entries) or not all(validate_definition(e) for e in entries):
        raise ValueError('常用指型库存在重复标识或实际和弦音不符。')
    return data


# 常用指型与器乐独奏：新增实际和弦到变调夹相对指型的查询，特殊低音必须匹配。
@lru_cache(maxsize=1024)
def common_grips(root, quality, bass, capo=0):
    shape_root, shape_bass = (root - capo) % 12, (bass - capo) % 12
    found = [e for e in load_library()['entries']
             if (e['root_pc'], e['quality'], e['bass_pc']) == (shape_root, quality, shape_bass)]
    return tuple(sorted(found, key=lambda e: (e['priority'], max(e['frets_6_to_1']), e['id'])))


# 常用指型与器乐独奏：新增只返回可用弦的标准字典，禁用弦仍由图中的×表达。
def fret_map(entry):
    return {s: f for s, f in zip(range(6, 0, -1), entry['frets_6_to_1']) if f >= 0}
