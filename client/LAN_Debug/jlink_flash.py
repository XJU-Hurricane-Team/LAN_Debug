#!/usr/bin/env python3
"""Resolve a LAN endpoint, then invoke SEGGER Commander or GDB Server.

Python 3.10+, standard library only. --dry-run never starts Commander.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading


def resolve_ipv4(host: str) -> str:
    try:
        results = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"Cannot resolve IPv4 for {host}: {exc}") from exc
    addresses = set()
    for result in results:
        address = ipaddress.IPv4Address(result[4][0])
        if not address.is_loopback and not address.is_unspecified and not address.is_multicast:
            addresses.add(str(address))
    if len(addresses) != 1:
        raise ValueError(f"Expected one usable IPv4 for {host}, found {sorted(addresses)}. Check OS mDNS/network configuration.")
    return addresses.pop()


def read_config(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Configuration must be a JSON object")
    for key in ("ServerName", "Device", "Interface"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"Missing or invalid {key}")
        data[key] = data[key].strip()
        if any(c in data[key] for c in ('\r', '\n', '"')):
            raise ValueError(f"Invalid characters in {key}")
    if data["Interface"] not in ("SWD", "JTAG", "cJTAG", "FINE"):
        raise ValueError("Interface must be SWD, JTAG, cJTAG or FINE")
    for key, maximum in (("Port", 65535), ("SpeedKHz", 100000)):
        if type(data.get(key)) is not int or not 1 <= data[key] <= maximum:
            raise ValueError(f"{key} must be an integer between 1 and {maximum}")
    if not isinstance(data.get("JLinkExe", ""), str):
        raise ValueError("JLinkExe must be a string")
    return data


def is_segger(path: Path, windows: bool) -> bool:
    if not path.is_file():
        return False
    if windows:
        return path.name.lower() == "jlink.exe" and (path.parent / "JLinkARM.dll").is_file()
    return (path.name == "JLinkExe" and os.access(path, os.X_OK)
            and any(path.parent.glob("libjlinkarm.so*")))


def find_jlink(explicit: str = "", *, windows: bool | None = None) -> Path:
    windows = os.name == "nt" if windows is None else windows
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if not is_segger(candidate, windows):
            raise ValueError(f"Not a SEGGER Commander installation: {candidate}. Check its companion JLinkARM library.")
        return candidate
    name = "JLink.exe" if windows else "JLinkExe"
    candidates = []
    portable = os.environ.get("VSCODE_PORTABLE")
    if portable:
        candidates.append(Path(portable) / "user-data/.eide/tools/jlink" / name)
    candidates.append(Path.home() / ".eide/tools/jlink" / name)
    if windows:
        for key in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(key):
                candidates.extend(sorted((Path(os.environ[key]) / "SEGGER").glob(f"JLink*/{name}"), reverse=True))
        # STM32Cube installs complete SEGGER SDK bundles outside Program Files.
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            bundle_root = Path(local_app_data) / "stm32cube/bundles/jlink-gdbserver"
            candidates.extend(sorted(bundle_root.glob(f"*/bin/{name}"), reverse=True))
    else:
        candidates.append(Path("/opt/SEGGER/JLink") / name)
    from_path = shutil.which(name)
    if from_path:
        candidates.append(Path(from_path).resolve())
    for candidate in candidates:
        candidate = candidate.resolve()
        if is_segger(candidate, windows):
            return candidate
    raise ValueError("SEGGER Commander not found. Set JLinkExe in the configuration or pass --jlink-path. Java's jlink is not supported.")


def command_text(program: Path) -> str:
    if program.suffix.lower() not in (".hex", ".s19", ".srec") or not program.is_file():
        raise ValueError("Program must be an existing .hex, .s19 or .srec file")
    if any(c in str(program) for c in ('"', '\r', '\n')):
        raise ValueError("Program path cannot contain a quote or newline")
    return f'r\nhalt\nloadfile "{program}"\nr\ngo\nexit\n'


def run_flash(config: dict, program: Path, jlink: Path, address: str, *, dry_run: bool = False) -> int:
    script = command_text(program)
    args = [str(jlink), "-IP", f'{address}:{config["Port"]}',
            "-Device", config["Device"], "-If", config["Interface"],
            "-Speed", str(config["SpeedKHz"]), "-AutoConnect", "1", "-ExitOnError", "1"]
    print(f'Endpoint: {config["ServerName"]} -> {address}:{config["Port"]}', flush=True)
    print(f"Commander: {jlink}\nProgram: {program}", flush=True)
    if dry_run:
        print("DRY RUN: no Commander process, probe connection, reset or flash.\n" + script, flush=True)
        return 0
    script_path = None
    try:
        # Commander on Windows reads system ANSI command files; Linux uses UTF-8.
        with tempfile.NamedTemporaryFile(mode="w", encoding="mbcs" if os.name == "nt" else "utf-8",
                                         suffix=".jlink", delete=False) as stream:
            script_path = Path(stream.name)
            stream.write(script)
        return subprocess.run(args + ["-CommandFile", str(script_path)], check=False).returncode
    finally:
        if script_path is not None:
            script_path.unlink(missing_ok=True)


def find_gdb_server(commander: Path) -> Path:
    name = "JLinkGDBServerCL.exe" if os.name == "nt" else "JLinkGDBServerCLExe"
    server = commander.parent / name
    if not server.is_file() or (os.name != "nt" and not os.access(server, os.X_OK)):
        raise ValueError(f"GDB Server not found in the selected SDK: {server}")
    return server


def gdb_arguments(config: dict, server: Path, address: str, port: int) -> list[str]:
    if not 1 <= port <= 65533:
        raise ValueError("GDB port must be between 1 and 65533 (two adjacent auxiliary ports are required)")
    return [str(server), "-select", f'IP={address}:{config["Port"]}',
            "-device", config["Device"], "-if", config["Interface"],
            "-speed", str(config["SpeedKHz"]), "-endian", "little",
            "-port", str(port), "-swoport", str(port + 1), "-telnetport", str(port + 2),
            "-localhostonly", "1", "-singlerun", "-nogui", "-halt"]


def check_gdb_ports(port: int) -> None:
    # Bind without connecting to someone else's debugger; release before SDK start.
    sockets = []
    try:
        for number in range(port, port + 3):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(listener)
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", number))
    finally:
        for listener in sockets:
            listener.close()


def run_gdb(config: dict, server: Path, address: str, port: int, *, dry_run: bool = False) -> int:
    args = gdb_arguments(config, server, address, port)
    print(f'Endpoint: {config["ServerName"]} -> {address}:{config["Port"]}', flush=True)
    print(f"GDB Server: {server}\nGDB target: 127.0.0.1:{port}", flush=True)
    if dry_run:
        print("DRY RUN: no GDB Server process or probe connection.\n" + repr(args), flush=True)
        return 0
    check_gdb_ports(port)
    print("[remote-jlink] GDB STARTING", flush=True)
    ready = threading.Event()
    timed_out = threading.Event()
    communication_error = threading.Event()
    child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", bufsize=1)

    def startup_timeout():
        if not ready.is_set() and child.poll() is None:
            timed_out.set()
            child.terminate()

    timer = threading.Timer(30, startup_timeout)
    timer.daemon = True
    timer.start()
    try:
        assert child.stdout is not None
        pending = ""
        # V8.50 prints its ready prompt without a newline; line iteration blocks
        # until GDB connects, while VS Code is still waiting for this signal.
        for character in iter(lambda: child.stdout.read(1), ""):
            pending += character
            if "ERROR: Communication timed out" in pending:
                communication_error.set()
            # V9.42 may finish startup at "Connected to target" without the old prompt.
            if (not ready.is_set() and not timed_out.is_set()
                    and ("Waiting for GDB connection" in pending or "Connected to target" in pending)):
                print(pending, flush=True)
                pending = ""
                ready.set()
                timer.cancel()
                print("[remote-jlink] GDB READY", flush=True)
            elif character == "\n":
                print(pending, end="", flush=True)
                pending = ""
        if pending:
            print(pending, end="", flush=True)
        code = child.wait()
        if communication_error.is_set() and code == 0:
            raise ValueError("GDB Server reported a communication timeout despite exit code 0; inspect target state")
        if timed_out.is_set():
            raise ValueError("GDB Server startup timed out; inspect the SDK output above")
        if not ready.is_set() and code == 0:
            raise ValueError("GDB Server exited without becoming ready")
        return code
    finally:
        timer.cancel()
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if child.stdout is not None:
            child.stdout.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().with_name("remote-jlink.json"))
    parser.add_argument("--program", type=Path)
    parser.add_argument("--gdb-server", action="store_true", help="Run the local GDB Server for the VS Code debug task")
    parser.add_argument("--gdb-port", type=int, default=2331)
    parser.add_argument("--jlink-path", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        config_path = args.config.expanduser().resolve()
        config = read_config(config_path)
        if not args.gdb_server:
            if args.program is None:
                parser.error("--program is required for flashing")
            program = args.program.expanduser().resolve()
            command_text(program)
        configured_path = args.jlink_path or config.get("JLinkExe", "")
        if configured_path and not Path(configured_path).expanduser().is_absolute():
            configured_path = str(config_path.parent / configured_path)
        jlink = find_jlink(configured_path)
        address = resolve_ipv4(config["ServerName"])
        if args.gdb_server:
            return run_gdb(config, find_gdb_server(jlink), address, args.gdb_port, dry_run=args.dry_run)
        return run_flash(config, program, jlink, address, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
