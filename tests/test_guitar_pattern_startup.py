"""网页连接恢复与独立启动：检查恢复、复用和失败时的实际启动行为。"""
# 网页连接恢复与独立启动：新增启动状态测试，不生成音乐或修改用户的保存目录。
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import start_guitar_pattern_preview as startup


class PreviewStartupTests(unittest.TestCase):
    # 网页连接恢复与独立启动：验证已有服务直接复用，避免重复进程和端口错误。
    def test_running_editor_is_reused_without_spawning(self):
        with patch.object(startup, 'health_ready', return_value=True), patch.object(startup, 'spawn_server') as spawn:
            result = startup.launch_service()
        self.assertFalse(result['started'])
        self.assertEqual(result['url'], 'http://127.0.0.1:8766/')
        spawn.assert_not_called()

    def test_occupied_port_is_reported_without_spawning(self):
        with patch.object(startup, 'health_ready', return_value=False), patch.object(startup, 'port_occupied', return_value=True), patch.object(startup, 'spawn_server') as spawn:
            with self.assertRaisesRegex(startup.LaunchError, '端口已被其它程序占用'):
                startup.launch_service()
        spawn.assert_not_called()

    def test_editor_becoming_ready_during_port_check_is_reused(self):
        with patch.object(startup, 'health_ready', side_effect=[False, True]), patch.object(startup, 'port_occupied', return_value=True), patch.object(startup, 'spawn_server') as spawn:
            self.assertFalse(startup.launch_service()['started'])
        spawn.assert_not_called()

    # 网页连接恢复与独立启动：验证服务响应之前启动器继续等待，不提前报告页面可用。
    def test_new_service_waits_for_health_before_returning(self):
        process = MagicMock(pid=321)
        process.poll.return_value = None
        with patch.object(startup, 'health_ready', side_effect=[False, False, True]), patch.object(startup, 'port_occupied', return_value=False), patch.object(startup, 'spawn_server', return_value=(process, 0)), patch.object(startup.time, 'sleep') as sleep:
            result = startup.launch_service()
        self.assertTrue(result['started'])
        self.assertEqual(result['pid'], 321)
        sleep.assert_called_once()

    def test_failed_process_reports_only_current_error(self):
        process = MagicMock()
        process.poll.return_value = 1
        with TemporaryDirectory() as folder:
            previous = '上一次的错误\n'.encode('utf-8')
            (Path(folder)/'server.stderr.log').write_bytes(previous + '本次启动错误'.encode('utf-8'))
            with patch.object(startup, 'health_ready', return_value=False), patch.object(startup, 'port_occupied', return_value=False), patch.object(startup, 'spawn_server', return_value=(process, len(previous))):
                with self.assertRaises(startup.LaunchError) as caught:
                    startup.launch_service(logs=folder)
        self.assertIn('本次启动错误', str(caught.exception))
        self.assertNotIn('上一次的错误', str(caught.exception))

    def test_unready_service_times_out_with_log_location(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(startup, 'health_ready', return_value=False), patch.object(startup, 'port_occupied', return_value=False), patch.object(startup, 'spawn_server', return_value=(process, 0)), patch.object(startup.time, 'monotonic', side_effect=[0, 0, 2]), patch.object(startup.time, 'sleep'):
            with self.assertRaisesRegex(startup.LaunchError, '1秒内未就绪'):
                startup.launch_service(timeout=1)
        process.terminate.assert_not_called()

    def test_failed_start_does_not_open_browser(self):
        with patch.object(startup, 'launch_service', side_effect=startup.LaunchError('实际启动失败')), patch.object(startup.webbrowser, 'open') as browser, redirect_stderr(StringIO()) as error:
            self.assertEqual(startup.main([]), 1)
        browser.assert_not_called()
        self.assertIn('实际启动失败', error.getvalue())

    def test_no_open_mode_checks_service_without_opening_browser(self):
        with patch.object(startup, 'launch_service', return_value={'started': False, 'url': 'http://127.0.0.1:8766/'}), patch.object(startup.webbrowser, 'open') as browser, redirect_stdout(StringIO()):
            self.assertEqual(startup.main(['--no-open']), 0)
        browser.assert_not_called()

    # 网页连接恢复与独立启动：验证健康检查只接受本应用，不能将其它网页误认为编辑器。
    def test_health_rejects_other_applications_and_invalid_json(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        with patch.object(startup.urllib.request, 'build_opener', return_value=opener):
            for body in (b'{"application":"another_app"}', b'<html>not ready</html>', b'[]'):
                response.read.return_value = body
                self.assertFalse(startup.health_ready(8766))
            response.read.return_value = startup.json.dumps({'application':'guitar_right_hand_editor','version':1,'workspace_root':str(startup.ROOT)}).encode('utf-8')
            self.assertTrue(startup.health_ready(8766))

    def test_invalid_port_or_wait_time_is_rejected(self):
        for port, timeout in ((0, 30), (65536, 30), (8766, 0)):
            with self.assertRaises(startup.LaunchError):
                startup.launch_service(port=port, timeout=timeout)


if __name__ == '__main__':
    unittest.main()
