"""目录改名：确认旧配置身份保持及跨工程服务拒绝。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from workspace_location import project_identity, same_workspace


class WorkspaceLocationTests(unittest.TestCase):
    def test_saved_identity_survives_moving_the_workspace(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)/'renamed'
            root.mkdir()
            (root/'data').mkdir()
            seed = Path(folder)/'previous'
            (root/'data/workspace_identity.json').write_text(json.dumps({'version':1,'identity_root':str(seed)}), encoding='utf-8')
            project = root/'results/song/project.json'
            expected = hashlib.sha256(str(seed/'results/song/project.json').encode('utf-8')).hexdigest()[:16]
            self.assertEqual(project_identity(project, root), expected)
            self.assertNotEqual(project_identity(project, root), hashlib.sha256(str(project.resolve()).encode('utf-8')).hexdigest()[:16])

    def test_new_workspace_without_record_keeps_original_rule(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            project = root/'project.json'
            expected = hashlib.sha256(str(project).encode('utf-8')).hexdigest()[:16]
            self.assertEqual(project_identity(project, root), expected)

    def test_project_outside_workspace_is_rejected(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                project_identity(Path(folder)/'outside.json', Path(folder)/'inside')

    def test_invalid_identity_record_is_rejected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'data').mkdir()
            (root/'data/workspace_identity.json').write_text('{"version":2}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '身份记录无效'):
                project_identity(root/'project.json', root)

    def test_evidence_keeps_its_recorded_path_through_a_directory_link(self):
        # 实际目录联接复现改名问题：同一文件解析到新位置后，旧证据仍须按原名重放。
        from first_generation_source import _bound_decision
        with TemporaryDirectory() as folder:
            root = Path(folder)
            actual = root/'renamed'
            alias = root/'previous'
            actual.mkdir()
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(actual)], check=True, capture_output=True)
            else:
                alias.symlink_to(actual, target_is_directory=True)
            (actual/'evidence.json').write_text('{}', encoding='utf-8')
            (actual/'evidence.npz').write_bytes(b'unchanged-source-evidence')
            evidence = alias/'evidence.json'
            self.assertNotEqual(evidence.absolute(), evidence.resolve())
            binding = {'vocal_project_sha256':'voice', 'sources':{'mix':{'sha256':'mix'}}}
            value = _bound_decision({'status':'passed'}, evidence, binding)
            self.assertEqual(value['evidence_path'], str(evidence.absolute()))
            same = _bound_decision({'status':'passed'}, actual/'evidence.json', binding)
            self.assertEqual(value['evidence_sha256'], same['evidence_sha256'])
            self.assertEqual(value['evidence_array_sha256'], same['evidence_array_sha256'])

    def test_health_requires_this_workspace(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            health = {'application':'guitar_right_hand_editor','workspace_root':str(root)}
            self.assertTrue(same_workspace(health, root))
            self.assertFalse(same_workspace(health, root/'other'))
            self.assertFalse(same_workspace({'application':'guitar_right_hand_editor'}, root))
            self.assertFalse(same_workspace({**health, 'application':'other'}, root))
            self.assertFalse(same_workspace([], root))


if __name__ == '__main__':
    unittest.main()
