import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_identity import get_server_identity


class ServerIdentityTests(unittest.TestCase):
    def config_path(self, content):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'avahi-daemon.conf'
        path.write_text(content, encoding='utf-8')
        return path

    @patch('server_identity._avahi_call', side_effect=['i 2', 's "robot-2.local"'])
    def test_runtime_name_wins_over_config_after_collision(self, call):
        path = self.config_path('[server]\nhost-name=robot\n')
        self.assertEqual(get_server_identity(path),
                         {'name': 'robot-2.local', 'source': 'avahi-runtime'})

    @patch('server_identity._avahi_call', side_effect=FileNotFoundError)
    def test_config_is_only_a_fallback(self, call):
        path = self.config_path('[server]\nhost-name=robot\n')
        self.assertEqual(get_server_identity(path),
                         {'name': 'robot.local', 'source': 'avahi-config'})

    @patch('server_identity._avahi_call', side_effect=['i 1'])
    def test_registering_is_not_published(self, call):
        path = self.config_path('[server]\nhost-name=robot\n')
        self.assertEqual(get_server_identity(path)['source'], 'avahi-config')

    @patch('server_identity._avahi_call', side_effect=subprocess.TimeoutExpired('busctl', 1))
    def test_machine_id_name_is_not_guessed(self, call):
        path = self.config_path('[server]\nhost-name=robot\nhost-name-from-machine-id=yes\n')
        self.assertEqual(get_server_identity(path)['name'], '')

    @patch('server_identity._avahi_call', side_effect=FileNotFoundError)
    @patch('server_identity.socket.gethostname', return_value='system-host')
    def test_default_host_and_custom_domain(self, hostname, call):
        path = self.config_path('[server]\ndomain-name=example.test\n')
        self.assertEqual(get_server_identity(path)['name'], 'system-host.example.test')

    @patch('server_identity._avahi_call', side_effect=['i 2', 's "http://wrong.local"'])
    def test_invalid_runtime_and_config_names_are_rejected(self, call):
        path = self.config_path('[server]\nhost-name=bad/name\n')
        self.assertEqual(get_server_identity(path)['source'], 'unavailable')

    @patch('server_identity._avahi_call', side_effect=FileNotFoundError)
    def test_missing_config_does_not_invent_a_name(self, call):
        path = self.config_path('')
        self.assertEqual(get_server_identity(path)['name'], '')


if __name__ == '__main__':
    unittest.main()
