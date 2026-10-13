import errno
import threading
import socket
import re

import serial

from configurations import JLINK_SERIAL_PORT_START

import serial.tools.list_ports


class JSerialPort:
    def __init__(self, device, sn):
        self.device = device
        self.sn = sn
        self.lock = threading.Lock()
        self.serial = None
        self._tx_thread = None
        self._rx_thread = None
        self._thread = None
        self.client_socket = None
        self.socket_port = 0
        self._socket_server = None
        self._stop_event = threading.Event()
        # socket 线程关闭锁

    def _serial_tx(self):
        """接收客户端数据并写入串口"""
        try:
            while True:
                tcp_data = self.client_socket.recv(1024)
                if not tcp_data:
                    print("Graceful disconnect. ")
                    break
                with self.lock:
                    self.serial.write(tcp_data)
                    print(f"Send {len(tcp_data)} byte(s) data to device. ")
        except(ConnectionResetError, BrokenPipeError):
            print("Connection reset by peer. ")
        finally:
            self.client_socket.close()

    def _serial_rx(self):
        """从串口读取数据并转发给客户端"""
        try:
            while True:
                data = self.serial.readline()
                if not data:
                    continue
                # print(f"Forwarding {len(data)} bytes")
                try:
                    with self.lock:
                        self.client_socket.sendall(data)
                except (ConnectionResetError, BrokenPipeError, OSError) as e:
                    print(f"Send failed: {str(e)}")
                    break
        except Exception as e:  # 捕获所有其他异常
            print(f"Unexpected error: {str(e)}")
        finally:
            with self.lock:  # 加锁关闭socket
                if not getattr(self.client_socket, '_closed'):  # 防止重复关闭
                    self.client_socket.close()

    def _serial_thread(self, baudrate):
        self._socket_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket_server.bind(('0.0.0.0', self.socket_port))
        self._socket_server.listen(5)
        print(f"JLink SN: {self.sn}, Listening on {{0.0.0.0}}:{self.socket_port}")

        try:
            while not self._stop_event.is_set():
                try:
                    self.client_socket, client_address = self._socket_server.accept()
                    print(f"Accepted connection from {client_address}")
                    self.serial = serial.Serial(self.device, baudrate=baudrate, timeout=1)

                    # 在新线程中处理数据
                    self._tx_thread = threading.Thread(target=self._serial_tx)
                    self._rx_thread = threading.Thread(target=self._serial_rx)

                    self._tx_thread.start()
                    self._rx_thread.start()
                except socket.timeout:
                    continue
                except IOError as e:
                    if e.errno == errno.EBADR:
                        break
                    elif self._stop_event.is_set():
                        break
                    print(f"JLink serial {self.sn}, Unexpected error: {str(e)}")

        finally:
            with self.lock:  # 加锁关闭socket
                if self._socket_server is not None:
                    self._socket_server.close()
            print(f"JLink {self.sn} disconnected, socket stopped. ")

    def start(self, socket_port, baudrate=115200):
        self.socket_port = socket_port
        self._thread = threading.Thread(target=self._serial_thread, args=(baudrate,))
        self._thread.start()

    def stop(self):
        if self.serial is not None:
            self.serial.close()
        self._stop_event.set()

        with self.lock:
            if self._socket_server is not None:
                try:
                    self._socket_server.shutdown(socket.SHUT_RDWR)
                except socket.error:
                    pass
                self._socket_server.close()
            # 建立虚拟连接接触阻塞
            try:
                dummy = socket.create_connection(('localhost', self.socket_port), timeout=0.1)
                dummy.close()
            except:
                pass


g_jlink_serial_list: list[JSerialPort] = []


def get_serial(port_config, connected_jlink):
    global g_jlink_serial_list

    serial_list = list(serial.tools.list_ports.comports())

    if len(serial_list) <= 0:
        return

    port = JLINK_SERIAL_PORT_START
    for sn in port_config.keys():
        # 找到最大的端口号, 新的基础上在此+1
        if 'serial' not in port_config[sn]:
            continue

        if port < port_config[sn]['serial']:
            port = port_config[sn]['serial']

    connected_jlink_sn_list = []

    # 添加新的串口
    for comport in serial_list:
        exist = False
        hwid = comport.hwid
        result = re.search(r'SER=(\d+)', hwid)
        if not result:
            continue

        # 去掉前导0
        sn = str(int(result.group(1)))
        connected_jlink_sn_list.append(sn)

        for jlink_serial in g_jlink_serial_list:
            if jlink_serial.sn == sn:
                exist = True
                break

        if exist:
            continue

        new_serial = JSerialPort(comport.device, sn)

        port += 1
        if sn not in port_config:
            # 只设置 serial，server 交给 get_jlink 负责
            port_config[sn] = {'serial': port}
        elif 'serial' not in port_config[sn]:
            port_config[sn]['serial'] = port
        else:
            port = port_config[sn]['serial']

        new_serial.start(port)

        g_jlink_serial_list.append(new_serial)

        if sn not in connected_jlink:
            connected_jlink[sn] = {}
        connected_jlink[sn]['serial'] = port
        # 从 port_config 补全 server 信息（如果 get_jlink 未先设置）
        if 'server' not in connected_jlink[sn] and sn in port_config and 'server' in port_config[sn]:
            connected_jlink[sn]['server'] = port_config[sn]['server']

    # 移除拔掉的 JLINK
    for j_serial in g_jlink_serial_list:
        if j_serial.sn in connected_jlink_sn_list:
            continue

        j_serial.stop()
        g_jlink_serial_list.remove(j_serial)

        if j_serial.sn in connected_jlink.keys():
            del connected_jlink[j_serial.sn]
