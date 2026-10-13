"""RTT 接收：基于 JLinkRTTLoggerExe。

设计：
- 每个 JLink 一个 JRTTClient 实例，独立线程后台运行 JLinkRTTLoggerExe。
- JLinkRTTLoggerExe 写入 ``log/rtt_<sn>.tmp``（每次 start 截断），由我们 tail 并：
  1) 推到内存环形 buffer（前端轮询用，限制 MAX_BUFFER 行）
  2) 追加到 ``log/rtt_<sn>.log``（持久会话日志，仅在进程启动时由 clear_all_session_logs 清零）
- 因此前端清空（clear_lines）只清空内存 buffer，不影响会话日志文件。
- 设备型号(device) 由调用方在 start 时传入，每个 JLink 各自管理。
"""

import os
import threading
import time
from subprocess import Popen

from configurations import (
    JLINK_PATH,
    JLINK_RTT_LOGGER_EXEC,
    RTT_CHANNEL,
    RTT_INTERFACE,
    RTT_SPEED,
)


_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log')


def _jlink_exe(name: str) -> str:
    return os.path.join(JLINK_PATH, name)


class JRTTClient:
    MAX_BUFFER = 5000
    TRIM_SIZE = 2000
    RECONNECT_DELAY = 1.0

    def __init__(
        self,
        sn: str,
        rtt_port: int,
        device: str,
        remote_host: str = '127.0.0.1',
        remote_port: int | None = None,
        interface: str = RTT_INTERFACE,
        speed: int = RTT_SPEED,
        channel: int = RTT_CHANNEL,
    ):
        if not device:
            raise ValueError('device is required to construct JRTTClient')

        self.sn = sn
        self.rtt_port = rtt_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.device = device
        self.interface = interface
        self.speed = speed
        self.channel = channel

        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.active = False
        self._client_proc: Popen | None = None
        self._session_writer = None

        self._session_path = os.path.join(_LOG_DIR, f'rtt_{self.sn}.log')
        self._capture_path = os.path.join(_LOG_DIR, f'rtt_{self.sn}.tmp')
        self._control_path = os.path.join(_LOG_DIR, f'rtt_{self.sn}_control.log')

    # ---------- 公共接口 ----------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.device:
            raise ValueError(f'JRTTClient[{self.sn}]: device is not set')
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.active = True

    def stop(self):
        self._stop.set()

        if self._client_proc:
            try:
                self._client_proc.terminate()
                self._client_proc.wait(timeout=2)
            except Exception:
                try:
                    self._client_proc.kill()
                except Exception:
                    pass
            self._client_proc = None

        self.active = False

    def get_lines(self, since: int = 0):
        with self._lock:
            if since >= len(self._lines):
                return [], len(self._lines)
            return self._lines[since:], len(self._lines)

    def clear_lines(self):
        """只清空内存 buffer。会话日志文件不动。"""
        with self._lock:
            self._lines.clear()

    # ---------- 内部 ----------

    def _run(self):
        while not self._stop.is_set():
            try:
                if self.remote_port is not None:
                    self._run_rtt_logger_once()
            except Exception as exc:
                print(f'RTT {self.sn}: Error - {exc}')

            if not self._stop.is_set():
                time.sleep(self.RECONNECT_DELAY)

        self.active = False

    def _run_rtt_logger_once(self):
        os.makedirs(_LOG_DIR, exist_ok=True)
        logger_exe = _jlink_exe(JLINK_RTT_LOGGER_EXEC)

        # JLinkRTTLogger 默认覆盖输出文件，所以让它写到 .tmp，由我们 tail 后追加到会话 log
        try:
            open(self._capture_path, 'w', encoding='utf-8').close()
        except Exception:
            pass

        # 会话日志：追加模式，跨多次 start/stop 累积
        try:
            self._session_writer = open(self._session_path, 'a', encoding='utf-8')
        except Exception:
            self._session_writer = None

        control_log = open(self._control_path, 'a', encoding='utf-8')
        args = [
            logger_exe,
            '-Device', self.device,
            '-If', self.interface,
            '-Speed', str(self.speed),
            '-IP', f'{self.remote_host}:{self.remote_port}',
            '-RTTChannel', str(self.channel),
            self._capture_path,
        ]

        proc = Popen(
            args=args,
            stdout=control_log,
            stderr=control_log,
            text=True,
            cwd=_LOG_DIR,
        )
        self._client_proc = proc

        try:
            self._tail_data_file(proc)
        finally:
            self._client_proc = None
            try:
                control_log.close()
            except Exception:
                pass
            try:
                if self._session_writer:
                    self._session_writer.close()
            except Exception:
                pass
            self._session_writer = None

    def _tail_data_file(self, proc):
        position = 0
        pending = ''

        def emit(text: str):
            text = text.strip('\r\n')
            if not text:
                return
            with self._lock:
                self._lines.append(text)
                if len(self._lines) > self.MAX_BUFFER:
                    self._lines = self._lines[-self.TRIM_SIZE:]
            # 追加到会话日志（持久），独立于内存 buffer
            if self._session_writer:
                try:
                    self._session_writer.write(text + '\n')
                    self._session_writer.flush()
                except Exception:
                    pass

        while not self._stop.is_set():
            try:
                with open(self._capture_path, 'r', encoding='utf-8', errors='replace') as data_file:
                    data_file.seek(position)
                    chunk = data_file.read()
                    position = data_file.tell()
            except FileNotFoundError:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
                continue
            except Exception as exc:
                print(f'RTT {self.sn}: file read error - {exc}')
                break

            if chunk:
                pending += chunk
                while '\n' in pending:
                    line, pending = pending.split('\n', 1)
                    emit(line)
                continue

            if proc.poll() is not None:
                break

            time.sleep(0.1)

        if pending:
            emit(pending)


# ============================================================
# 全局状态 + 工厂
# ============================================================

g_rtt_clients: dict[str, JRTTClient] = {}


def clear_all_session_logs():
    """进程启动时调用：清零所有 log/rtt_<sn>.log（只清持久会话日志，
    控制日志 _control.log 和其它日志保留）。"""
    if not os.path.isdir(_LOG_DIR):
        return
    for name in os.listdir(_LOG_DIR):
        if (
            name.startswith('rtt_')
            and name.endswith('.log')
            and not name.endswith('_control.log')
        ):
            path = os.path.join(_LOG_DIR, name)
            try:
                open(path, 'w', encoding='utf-8').close()
            except Exception:
                pass


def get_or_start_rtt(
    sn: str,
    device: str,
    remote_port: int | None = None,
    rtt_port: int | None = None,
    remote_host: str = '127.0.0.1',
) -> JRTTClient:
    """启动指定 SN 的 RTT logger；如果已存在但 device/remote_port 变化了，先停后再起。"""
    if not device:
        raise ValueError('device is required to start RTT logger')

    port = rtt_port if rtt_port is not None else remote_port

    existing = g_rtt_clients.get(sn)
    if existing:
        device_changed = existing.device != device
        port_changed = remote_port is not None and existing.remote_port != remote_port
        if device_changed or port_changed:
            existing.stop()
            del g_rtt_clients[sn]
        else:
            existing.remote_host = remote_host
            if remote_port is not None:
                existing.remote_port = remote_port
            if not existing.active:
                existing.start()
            return existing

    client = JRTTClient(
        sn,
        port,
        device=device,
        remote_host=remote_host,
        remote_port=remote_port,
    )
    client.start()
    g_rtt_clients[sn] = client
    return client


def stop_rtt(sn: str):
    if sn in g_rtt_clients:
        g_rtt_clients[sn].stop()
        del g_rtt_clients[sn]


def stop_all_rtt():
    for sn in list(g_rtt_clients.keys()):
        stop_rtt(sn)
