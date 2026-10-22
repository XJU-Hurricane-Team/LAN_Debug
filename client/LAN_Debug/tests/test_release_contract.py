"""Release compatibility checks; never connect to hardware."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

CLIENT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_flash', CLIENT / 'jlink_flash.py')
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)


class ReleaseContractTests(unittest.TestCase):
    def test_jsonc_preserves_strings_and_rejects_duplicate_keys(self):
        value = flash.read_jsonc('{/*comment*/ "url":"http://host/a,}", "path":"C:\\\\tools", // note\n "list":[1,],}')
        self.assertEqual(value, {'url':'http://host/a,}', 'path':'C:\\tools', 'list':[1]})
        for text in ['{"Port":1,"Port":2}', '{"nested":{"x":1,"x":2}}']:
            with self.assertRaises(ValueError):
                flash.read_jsonc(text)

    def test_offline_check_does_not_resolve_or_launch_and_enforces_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'remote.json'
            path.write_text(json.dumps(dict(ServerName='example.invalid', Port=19011, Device='STM32G474VE', Interface='SWD', SpeedKHz=4000)), encoding='utf-8')
            with patch.object(flash, 'resolve_ipv4') as dns, patch.object(flash, 'find_jlink') as sdk, redirect_stdout(io.StringIO()):
                self.assertEqual(flash.main(['--check', '--config', str(path)]), 0)
                dns.assert_not_called()
                sdk.assert_not_called()
            path.write_text(' ' * (4 * 1024 * 1024 + 1), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '4 MiB'):
                flash.read_config(path)

    def test_release_zip_is_deterministic_complete_and_contains_example_config_only(self):
        spec = importlib.util.spec_from_file_location('package_client', CLIENT.parents[1] / 'scripts/package_client.py')
        package = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(package)
        import zipfile
        first = package.package_bytes()
        self.assertEqual(first, package.package_bytes())
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(set(archive.namelist()), set(package.FILES))
            self.assertNotIn('remote-jlink.json', archive.namelist())
            self.assertEqual(archive.read('VERSION').decode().strip(), flash.tool_version())


if __name__ == '__main__':
    unittest.main()
