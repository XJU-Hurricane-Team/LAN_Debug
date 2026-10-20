"""Offline shell tests. All uninstall filesystem targets are redirected to a temp tree."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import re
import sys
import tempfile
import unittest


SERVER = Path(__file__).resolve().parents[1]
BASH = os.environ.get("LAN_DEBUG_TEST_BASH") or shutil.which("bash")


def shell_path(path):
    text = Path(path).resolve().as_posix()
    if os.name == "nt":
        return "/" + text[0].lower() + text[2:]
    return text


@unittest.skipUnless(BASH, "bash is required for shell integration tests")
class DeploymentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="LAN Debug test ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.old = self.root / "old server"
        self.old.mkdir()
        for name, content in {
            "app.py": "# old server\n", "bash.sh": "# old startup\n",
            "port.json": '{"123":{"server":19011}}\n',
        }.items():
            (self.old / name).write_text(content, encoding="utf-8")
        (self.old / "log").mkdir()
        (self.old / "log/rtt_123.log").write_text("keep this session\n")
        self.unit_dir = self.root / "etc"
        self.unit_dir.mkdir()
        self.unit = self.unit_dir / "lan-debug-server.service"
        self.unit.write_text("[Service]\nExecStopPost=/usr/bin/pkill -f JLinkExe\n")
        self.calls = self.root / "calls"
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"], USER="tester",
                        TEST_OLD=shell_path(self.old), TEST_UNIT=shell_path(self.unit),
                        TEST_CALLS=shell_path(self.calls), TEST_BIN=shell_path(self.bin))
        self.write_executable(self.bin / "id", "#!/bin/bash\necho 0\n")
        self.write_executable(self.bin / "systemctl", """#!/bin/bash
set -eu
printf '%s\\n' "$*" >> "$TEST_CALLS"
case "$1" in
  show)
    case "$4" in
      LoadState) if [ -f "$TEST_UNIT" ]; then echo loaded; else echo not-found; fi ;;
      FragmentPath) echo "$TEST_UNIT" ;;
      WorkingDirectory) echo "$TEST_OLD" ;;
      ExecStop|ExecStopPost) if [ "${BAD_OVERRIDE:-0}" = 1 ]; then echo unsafe; fi ;;
      KillMode) echo control-group ;;
    esac ;;
  is-active) exit 3 ;;
  cat) cat "$TEST_UNIT" ;;
  stop) if [ "${FAIL_STOP:-0}" = 1 ]; then exit 1; fi ;;
esac
""")
        source = (SERVER / "pack/uninstall-legacy.sh").read_text(encoding="utf-8")
        for original, target in [
            ("/etc/systemd/system", self.unit_dir),
            ("/run/systemd/system", self.root / "run"),
            ("/var/backups/LAN_Debug", self.root / "backups"),
        ]:
            source = source.replace(original, shell_path(target))
        self.script = self.root / "uninstall.sh"
        self.write_executable(self.script, source)

    def write_executable(self, path, text):
        path.write_text(text, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def run_shell(self, script, *args, env=None):
        # Git Bash prepends its own tools on Windows; restore mock priority inside Bash.
        return subprocess.run([BASH, "-c", 'export PATH="$TEST_BIN:$PATH"; script="$1"; shift; source "$script" "$@"',
                               "test", shell_path(script), *args], env=env or self.env,
                              cwd=self.root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)

    def test_shell_syntax(self):
        for script in [SERVER / "bash.sh", *sorted((SERVER / "pack").glob("*.sh"))]:
            result = subprocess.run([BASH, "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_preview_does_not_change_service_or_create_backup(self):
        result = self.run_shell(self.script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.unit.exists())
        self.assertFalse((self.root / "backups").exists())
        calls = self.calls.read_text()
        self.assertNotIn("stop ", calls)
        self.assertNotIn("disable ", calls)

    def test_uninstall_preserves_data_backs_up_dropins_and_is_repeatable(self):
        dropins = Path(str(self.unit) + ".d")
        dropins.mkdir()
        (dropins / "custom.conf").write_text("[Service]\nEnvironment=LOCAL=1\n")
        result = self.run_shell(self.script, "--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.unit.exists())
        self.assertFalse(dropins.exists())
        backup, = (self.root / "backups").iterdir()
        self.assertEqual((backup / "port.json").read_bytes(), (self.old / "port.json").read_bytes())
        self.assertEqual((backup / "log/rtt_123.log").read_text(), "keep this session\n")
        self.assertTrue((backup / "lan-debug-server.service").exists())
        self.assertTrue((backup / "lan-debug-server.service.d/custom.conf").exists())
        self.assertTrue((self.old / "bash.sh").exists())
        calls = self.calls.read_text()
        self.assertLess(calls.index("stop lan-debug-server"), calls.index("disable lan-debug-server"))
        self.assertNotIn("stop LAN_Debug_server", calls)
        again = self.run_shell(self.script, "--apply")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(len(list((self.root / "backups").iterdir())), 1)

    def test_invalid_old_directory_aborts_before_mutation(self):
        (self.old / "app.py").unlink()
        result = self.run_shell(self.script, "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.unit.exists())
        self.assertFalse((self.root / "backups").exists())

    def test_deploy_blocks_legacy_service_before_installing(self):
        self.write_executable(self.bin / "id", "#!/bin/bash\nif [ \"$1\" = -u ]; then echo 1000; else echo tester; fi\n")
        self.write_executable(self.bin / "dpkg", "#!/bin/bash\necho amd64\n")
        self.write_executable(self.bin / "sudo", '#!/bin/bash\necho "unexpected sudo" >> "$TEST_CALLS"\nexit 93\n')
        result = self.run_shell(SERVER / "pack/deploy.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uninstall-legacy.sh", result.stderr)
        self.assertNotIn("unexpected sudo", self.calls.read_text())

    def test_unsafe_stop_override_aborts_without_stopping(self):
        result = self.run_shell(self.script, "--apply", env=self.env | {"BAD_OVERRIDE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.unit.exists())
        self.assertNotIn("stop lan-debug-server", self.calls.read_text())
        self.assertFalse(list((self.root / "run").rglob("*.conf")))

    def test_stop_failure_preserves_unit_and_backup(self):
        result = self.run_shell(self.script, "--apply", env=self.env | {"FAIL_STOP": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.unit.exists())
        self.assertTrue(list((self.root / "backups").glob("*/port.json")))
        self.assertNotIn("disable lan-debug-server", self.calls.read_text())

    def test_startup_works_from_unrelated_directory_with_spaces(self):
        server = self.root / "renamed LAN_Debug_server"
        runtime = server / ".venv/bin"
        runtime.mkdir(parents=True)
        self.write_executable(runtime / "python", '#!/bin/bash\npwd\nprintf "%s\\n" "$@"\n')
        shutil.copyfile(SERVER / "bash.sh", server / "bash.sh")
        result = self.run_shell(server / "bash.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/renamed LAN_Debug_server\n", result.stdout)
        self.assertIn("-m\ngunicorn\n-c\ngunicorncfg.py\napp:app", result.stdout)
        self.assertTrue((server / "log").is_dir())

    def test_service_template_rendering_handles_spaces_and_ampersand(self):
        source = (SERVER / "pack/deploy.sh").read_text(encoding="utf-8")
        render = source[source.index("sed_value()"):source.index('info "生成的 service')]
        script = self.root / "render.sh"
        text = """#!/bin/bash
set -eu
PROJECT_DIR='/srv/LAN Debug & tools/server'
CURRENT_HOME='/home/test user'
CURRENT_USER=testuser
CURRENT_GROUP=testgroup
SERVICE_TEMPLATE="$1"
""" + render + '\ncat "$TMP_SERVICE"\n'
        self.write_executable(script, text)
        result = self.run_shell(script, shell_path(SERVER / "pack/LAN_Debug_server.service"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WorkingDirectory=/srv/LAN Debug & tools/server", result.stdout)
        self.assertIn("User=testuser", result.stdout)
        self.assertNotIn("@PROJECT_DIR@", result.stdout)
        self.assertNotIn("pkill", result.stdout)

    def test_web_and_vscode_commands_find_copied_client(self):
        client = SERVER.parent / "client/LAN_Debug"
        project = self.root / "firmware project"
        shutil.copytree(client, project / "LAN_Debug")
        tasks = json.loads((client / "vscode/tasks.json").read_text(encoding="utf-8"))
        task_paths = [arg for task in tasks["tasks"] for arg in task.get("args", [])
                      if arg.endswith("/jlink_flash.py")]
        html = (SERVER / "templates/index.html").read_text(encoding="utf-8")
        web_paths = re.findall(r'"(\$\{ProjectRoot\}/[^"]+/jlink_flash.py)"', html)
        self.assertEqual(len(web_paths), 2)
        self.assertEqual(len(task_paths), 1)
        for entry in task_paths + web_paths:
            relative = entry.split("}/", 1)[1]
            result = subprocess.run([sys.executable, "-B", str(project / relative), "--help"],
                                    cwd=self.root, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
