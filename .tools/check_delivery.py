# 兼容性与样曲验证：新增最终交付核对，仅检查已有证据和文件。
from pathlib import Path
import json
root = Path.cwd()
for name in ('reports/first_sample.md', 'README.md', 'AGENTS.md', 'progress.md', 'todo.md', 'run_models.ps1', 'run_validation.ps1'):
    path = root / name
    assert path.is_file() and path.stat().st_size > 0, name
inventory = json.loads((root / 'reports/audio_inventory.json').read_text(encoding='utf-8-sig'))
assert inventory['total'] == inventory['verified'] == 10
assert all(row['source_unchanged'] for row in inventory['records'])
run = json.loads((root / 'reports/integrated_pipeline.full.json').read_text(encoding='utf-8-sig'))
summary = json.loads(Path(run['run']['transcription_summary']).read_text(encoding='utf-8'))
assert summary['source']['duration_seconds'] == 209.76
assert summary['counts']['segments'] == 7 and summary['counts']['pitch_frames'] == 39330
for name, artifact in summary['artifacts'].items():
    assert Path(artifact).is_file() and Path(artifact).stat().st_size > 0, name
midi = Path(summary['artifacts']['vocal_draft.mid']).read_bytes()
assert midi.startswith(b'MThd') and b'MTrk' in midi
print('final delivery evidence: OK; 10 source hashes unchanged; full-song coverage and MIDI present')
