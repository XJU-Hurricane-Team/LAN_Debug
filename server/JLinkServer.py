from enum import Enum
from configurations import *
from subprocess import Popen, PIPE
import os
import fcntl
import re

# 安全拼接 JLink 工具路径
_JLINK = lambda name: os.path.join(JLINK_PATH, name)


class ServerStatus(Enum):
    CLOSED = 0
    OPENED = 1


def non_block_read(output):
    fd = output.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)


def _resolve_rtt_port(server_port):
    return RTT_TELNET_PORT_START + max(0, server_port - JLINK_SERVER_PORT_START - 1)


class JLinkServer:
    def __init__(self, sn):
        self.sn = sn
        self.port = 0
        self.state = ServerStatus.CLOSED
        self.proc = None

    def start(self, port):
        self.port = port
        # 切换到 log/ 目录，让 JLinkRemoteServer 的日志文件生成在 log/ 下
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log')
        os.makedirs(log_dir, exist_ok=True)
        self.proc = Popen(
            args=[_JLINK(JLINK_REMOTE_SERVER_EXEC), '-select', f'USB={self.sn}', '-port', f'{self.port}'],
            stdin=PIPE, stdout=PIPE, stderr=PIPE, encoding='utf8',
            cwd=log_dir
        )
        non_block_read(self.proc.stdout)
        non_block_read(self.proc.stderr)
        self.state = ServerStatus.OPENED

    def stop(self):
        self.proc.kill()
        self.state = ServerStatus.CLOSED

    def read_log_line(self):
        if self.state == ServerStatus.OPENED:
            return self.proc.stdout.readline()
        else:
            return ''

    def read_err_line(self):
        if self.state == ServerStatus.OPENED:
            return self.proc.stderr.readline()
        else:
            return ''


g_jlink_server_list: list[JLinkServer] = []


# 获取Jlink服务器列表
def get_jlink(port_config, connected_jlink):
    global g_jlink_server_list
    proc = Popen(
        args=[_JLINK(JLINK_COMMANDER_EXEC), '-NoGui', '1', '-ExitOnError', '1'],
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
        shell=True,
        encoding='utf-8'
    )

    proc.stdin.write('ShowEmuList USB\nq')
    out, err = proc.communicate()

    jlink_filter_re = re.compile(r'J-Link\[(\d+)].*?Serial number: (\d+)')
    jlink_list = jlink_filter_re.findall(out)

    port = JLINK_SERVER_PORT_START
    for sn in port_config.keys():
        # 找到最大的端口号, 新的基础上在此+1
        if 'server' not in port_config[sn]:
            continue
        port_config[sn].setdefault('rtt', _resolve_rtt_port(port_config[sn]['server']))

        if port < port_config[sn]['server']:
            port = port_config[sn]['server']

    connected_jlink_sn_list = []

    # 添加新的 jlink
    for jlink_sn in jlink_list:
        exist = False
        sn = jlink_sn[1]
        connected_jlink_sn_list.append(sn)
        for jlink in g_jlink_server_list:
            if jlink.sn == sn:
                exist = True
                break

        if exist:
            # 即使 JLink 已存在于 g_jlink_server_list，也要确保 connected_jlink 中有 server 信息
            if sn not in connected_jlink:
                connected_jlink[sn] = {}
            if 'server' not in connected_jlink[sn]:
                # 从 port_config 或 g_jlink_server_list 找回端口
                if sn in port_config and 'server' in port_config[sn]:
                    connected_jlink[sn]['server'] = port_config[sn]['server']
                else:
                    for srv in g_jlink_server_list:
                        if srv.sn == sn:
                            connected_jlink[sn]['server'] = srv.port
                            break
            if sn in port_config:
                connected_jlink[sn]['rtt'] = port_config[sn].get('rtt', _resolve_rtt_port(connected_jlink[sn]['server']))
                port_config[sn]['rtt'] = connected_jlink[sn]['rtt']
            continue

        new_server = JLinkServer(sn)

        port += 1
        if sn not in port_config:
            port_config[sn] = {
                'server': port,
                'serial': JLINK_SERIAL_PORT_START + (port - JLINK_SERVER_PORT_START),
                'rtt': _resolve_rtt_port(port),
            }
        elif 'server' not in port_config[sn]:
            port_config[sn]['server'] = port
            port_config[sn]['rtt'] = _resolve_rtt_port(port)
        else:
            port = port_config[sn]['server']
            port_config[sn].setdefault('rtt', _resolve_rtt_port(port))

        new_server.start(port)

        g_jlink_server_list.append(new_server)

        if sn not in connected_jlink:
            connected_jlink[sn] = {}
        connected_jlink[sn]['server'] = port
        connected_jlink[sn]['rtt'] = port_config[sn]['rtt']

    # 移除拔掉的 JLINK
    for jlink_server in g_jlink_server_list:
        if jlink_server.sn in connected_jlink_sn_list:
            continue

        jlink_server.stop()
        g_jlink_server_list.remove(jlink_server)

        if jlink_server.sn in connected_jlink.keys():
            del connected_jlink[jlink_server.sn]
