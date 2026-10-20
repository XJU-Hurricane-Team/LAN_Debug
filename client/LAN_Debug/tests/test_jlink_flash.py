import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jlink_flash as flash


def answer(ip):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))


class FlashTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="flash test ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.program = self.root / "firmware with spaces.hex"
        self.program.write_text(":00000001FF\n")
        self.config = dict(ServerName="robot.local", Port=19011, Device="STM32G474VE", Interface="SWD", SpeedKHz=8000)

    def test_resolution_filters_and_deduplicates(self):
        with patch.object(socket, "getaddrinfo", return_value=[answer("127.0.0.1"), answer("192.168.28.24"), answer("192.168.28.24")]):
            self.assertEqual(flash.resolve_ipv4("robot.local"), "192.168.28.24")

    def test_resolution_rejects_missing_ambiguous_and_failed_dns(self):
        for answers in ([], [answer("127.0.0.1")], [answer("0.0.0.0")], [answer("192.168.28.24"), answer("192.168.28.25")]):
            with self.subTest(answers=answers), patch.object(socket, "getaddrinfo", return_value=answers):
                with self.assertRaises(ValueError):
                    flash.resolve_ipv4("robot.local")
        with patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("not found")):
            with self.assertRaises(ValueError):
                flash.resolve_ipv4("robot.local")

    def test_java_rejected_and_portable_segger_found(self):
        java = self.root / "java/JLink.exe"
        java.parent.mkdir()
        java.touch()
        with self.assertRaises(ValueError):
            flash.find_jlink(str(java), windows=True)
        sdk = self.root / "portable/user-data/.eide/tools/jlink"
        sdk.mkdir(parents=True)
        (sdk / "JLink.exe").touch()
        (sdk / "JLinkARM.dll").touch()
        with patch.dict(flash.os.environ, {"VSCODE_PORTABLE": str(self.root / "portable")}):
            self.assertEqual(flash.find_jlink(windows=True), sdk / "JLink.exe")

    def test_linux_sdk_requires_library_and_execution(self):
        exe = self.root / "JLinkExe"
        exe.touch()
        with patch.object(flash.os, "access", return_value=True):
            self.assertFalse(flash.is_segger(exe, False))
            (self.root / "libjlinkarm.so.8").touch()
            self.assertTrue(flash.is_segger(exe, False))
        with patch.object(flash.os, "access", return_value=False):
            self.assertFalse(flash.is_segger(exe, False))

    def test_stm32cube_bundle_discovered_without_eide_or_program_files(self):
        local = self.root / "Local AppData"
        bundles = local / "stm32cube/bundles/jlink-gdbserver"
        sdk = bundles / "9.42.0+st.1/bin"
        sdk.mkdir(parents=True)
        (sdk / "JLink.exe").touch()
        (sdk / "JLinkARM.dll").touch()
        incomplete = bundles / "9.99.0+st.1/bin"
        incomplete.mkdir(parents=True)
        (incomplete / "JLink.exe").touch()
        with patch.dict(flash.os.environ, {"LOCALAPPDATA": str(local)}, clear=True), \
                patch.object(flash.Path, "home", return_value=self.root / "empty home"), \
                patch.object(flash.shutil, "which", return_value=None):
            self.assertEqual(flash.find_jlink(windows=True), sdk / "JLink.exe")

    def test_dry_run_never_launches_commander(self):
        with patch.object(flash.subprocess, "run") as run:
            self.assertEqual(flash.run_flash(self.config, self.program, self.root / "JLink.exe", "192.168.28.24", dry_run=True), 0)
            run.assert_not_called()

    def test_real_run_preserves_exit_code_paths_and_cleans_script(self):
        seen = []
        def invoke(args, **kwargs):
            self.assertEqual(args[2], "192.168.28.24:19011")
            self.assertEqual(args[0], str(self.root / "sdk with spaces/JLink.exe"))
            self.assertEqual(kwargs, {"check": False})
            path = Path(args[-1])
            seen.append(path)
            script = path.read_text(encoding="mbcs" if flash.os.name == "nt" else "utf-8")
            self.assertEqual(script, f'r\nhalt\nloadfile "{self.program}"\nr\ngo\nexit\n')
            return flash.subprocess.CompletedProcess(args, 7)
        with patch.object(flash.subprocess, "run", side_effect=invoke):
            self.assertEqual(flash.run_flash(self.config, self.program, self.root / "sdk with spaces/JLink.exe", "192.168.28.24"), 7)
        self.assertFalse(seen[0].exists())

    def test_cleanup_after_launch_failure(self):
        seen = []
        def fail(args, **kwargs):
            seen.append(Path(args[-1]))
            raise OSError("cannot launch")
        with patch.object(flash.subprocess, "run", side_effect=fail):
            with self.assertRaises(OSError):
                flash.run_flash(self.config, self.program, self.root / "JLink.exe", "192.168.28.24")
        self.assertFalse(seen[0].exists())

    def test_invalid_config_and_firmware_stop(self):
        profile = self.root / "profile.json"
        for value in (0, 65536, True, 19011.5):
            profile.write_text(json.dumps(self.config | {"Port": value}))
            with self.assertRaises(ValueError):
                flash.read_config(profile)
        with patch.object(flash.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                flash.run_flash(self.config, self.root / "missing.hex", self.root / "JLink.exe", "192.168.28.24")
            run.assert_not_called()

    def test_gdb_dry_run_does_not_launch_or_bind(self):
        with patch.object(flash.subprocess, "Popen") as run, patch.object(flash, "check_gdb_ports") as ports:
            self.assertEqual(flash.run_gdb(self.config, self.root / "JLinkGDBServerCL.exe", "192.168.28.24", 2331, dry_run=True), 0)
            run.assert_not_called()
            ports.assert_not_called()

    def test_gdb_ready_signal_and_arguments(self):
        child = MagicMock()
        child.stdout = io.StringIO("Connected to target\nWaiting for GDB connection...\n")
        child.wait.return_value = 0
        child.poll.return_value = 0
        output = io.StringIO()
        with patch.object(flash.subprocess, "Popen", return_value=child) as run, patch.object(flash, "check_gdb_ports"), redirect_stdout(output):
            self.assertEqual(flash.run_gdb(self.config, self.root / "JLinkGDBServerCL.exe", "192.168.28.24", 2331), 0)
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("-select") + 1], "IP=192.168.28.24:19011")
        self.assertEqual(args[args.index("-port") + 1], "2331")
        self.assertEqual(args[args.index("-localhostonly") + 1], "1")
        self.assertIn("-singlerun", args)
        self.assertIn("[remote-jlink] GDB READY", output.getvalue())
        self.assertTrue(child.stdout.closed)

    def test_gdb_ready_prompt_without_newline_unblocks_before_eof(self):
        output = io.StringIO()
        prompt = "Connected to target\nWaiting for GDB connection..."
        test = self

        class PromptStream(io.StringIO):
            def read(self, size=-1):
                if self.tell() == len(prompt):
                    test.assertIn("[remote-jlink] GDB READY", output.getvalue())
                return super().read(size)

        child = MagicMock()
        child.stdout = PromptStream(prompt)
        child.wait.return_value = 0
        child.poll.return_value = 0
        with patch.object(flash.subprocess, "Popen", return_value=child), patch.object(flash, "check_gdb_ports"), redirect_stdout(output):
            self.assertEqual(flash.run_gdb(self.config, self.root / "server", "192.168.28.24", 2331), 0)
        self.assertTrue(child.stdout.closed)

    def test_gdb_early_exit_does_not_claim_ready(self):
        for code in (0, 7):
            child = MagicMock()
            child.stdout = io.StringIO("Target connection failed\n")
            child.wait.return_value = code
            child.poll.return_value = code
            output = io.StringIO()
            with patch.object(flash.subprocess, "Popen", return_value=child), patch.object(flash, "check_gdb_ports"), redirect_stdout(output):
                if code == 0:
                    with self.assertRaises(ValueError):
                        flash.run_gdb(self.config, self.root / "server", "192.168.28.24", 2331)
                else:
                    self.assertEqual(flash.run_gdb(self.config, self.root / "server", "192.168.28.24", 2331), code)
            self.assertNotIn("GDB READY", output.getvalue())

    def test_gdb_v942_connected_without_waiting_prompt(self):
        output = io.StringIO()
        prompt = "Listening on TCP/IP port 2331\nConnected to target\n"
        test = self

        class ConnectedStream(io.StringIO):
            def read(self, size=-1):
                if self.tell() == len(prompt):
                    test.assertIn("[remote-jlink] GDB READY", output.getvalue())
                return super().read(size)

        child = MagicMock()
        child.stdout = ConnectedStream(prompt)
        child.wait.return_value = 0
        child.poll.return_value = 0
        with patch.object(flash.subprocess, "Popen", return_value=child), patch.object(flash, "check_gdb_ports"), redirect_stdout(output):
            self.assertEqual(flash.run_gdb(self.config, self.root / "server", "192.168.28.24", 2331), 0)
        self.assertTrue(child.stdout.closed)

    def test_gdb_missing_sdk_or_invalid_port_stops(self):
        with self.assertRaises(ValueError):
            flash.find_gdb_server(self.root / "JLink.exe")
        for port in (0, 65534):
            with self.assertRaises(ValueError):
                flash.gdb_arguments(self.config, self.root / "server", "192.168.28.24", port)

    def test_gdb_zero_exit_with_communication_timeout_is_failure(self):
        child = MagicMock()
        child.stdout = io.StringIO("Connected to target\nERROR: Communication timed out: Requested 76 bytes, received 0 bytes !\n")
        child.wait.return_value = 0
        child.poll.return_value = 0
        with patch.object(flash.subprocess, "Popen", return_value=child), patch.object(flash, "check_gdb_ports"), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "communication timeout"):
                flash.run_gdb(self.config, self.root / "server", "192.168.28.24", 2331)
        self.assertTrue(child.stdout.closed)

    def test_gdb_occupied_port_stops_before_launch(self):
        with patch.object(flash, "check_gdb_ports", side_effect=OSError("port in use")), patch.object(flash.subprocess, "Popen") as run:
            with self.assertRaises(OSError):
                flash.run_gdb(self.config, self.root / "server", "192.168.28.24", 2331)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
