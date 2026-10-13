import json
import socket
import os
import atexit
from flask import Flask, render_template, jsonify, request, send_from_directory
from JSerialPort import get_serial
from JLinkServer import get_jlink
from server_identity import get_server_identity
from JRTTClient import (
    g_rtt_clients,
    get_or_start_rtt,
    stop_rtt,
    stop_all_rtt,
    clear_all_session_logs,
)

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log')
PORT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'port.json')

# 端口配置, 存在 json 文件中
port_config = {}


def save_port_config():
    try:
        with open(PORT_JSON, 'w', encoding='utf-8') as f:
            json.dump(port_config, f, ensure_ascii=False)
    except Exception as exc:
        print(f'save_port_config failed: {exc}')


# 获取本地IP地址
def get_local_ip():
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        if s:
            s.close()
    return ip


app = Flask(__name__, static_folder='static')


@app.route('/')
def index():
    return render_template('index.html', server_identity=get_server_identity())


# 当前连接到的 JLink 配置
connected_jlink = {}


def _decorate_with_device(payload: dict):
    """把 port_config 里持久化的 device 合并到响应里。"""
    for sn, info in payload.items():
        if sn == 'ip' or not isinstance(info, dict):
            continue
        info['device'] = port_config.get(sn, {}).get('device', '')
    return payload


@app.route('/get_jlink_list')
def get_jlink_list():
    get_jlink(port_config, connected_jlink)
    get_serial(port_config, connected_jlink)
    save_port_config()
    connected_jlink['ip'] = get_local_ip()
    _decorate_with_device(connected_jlink)
    # 同时附带每个 SN 当前 RTT 是否在跑，前端用来同步开始/停止按钮状态
    for sn, info in connected_jlink.items():
        if sn == 'ip' or not isinstance(info, dict):
            continue
        client = g_rtt_clients.get(sn)
        info['rtt_active'] = bool(client and client.active)
    return jsonify(connected_jlink)


@app.route('/set_device', methods=['GET', 'POST'])
def set_device():
    sn = request.values.get('sn', '')
    device = request.values.get('device', '').strip()

    if not sn:
        return jsonify({'error': 'sn required'}), 400
    if sn not in port_config and sn not in connected_jlink:
        return jsonify({'error': 'unknown sn'}), 404

    port_config.setdefault(sn, {})
    port_config[sn]['device'] = device
    save_port_config()
    return jsonify({'status': 'ok', 'sn': sn, 'device': device})


@app.route('/start_rtt')
def start_rtt():
    sn = request.args.get('sn', '')
    device_arg = request.args.get('device', '').strip()

    if not sn or sn not in connected_jlink or 'server' not in connected_jlink[sn]:
        return jsonify({'error': 'JLink not found'}), 404

    # device 优先用前端这次传入的，其次回落到 port.json 里持久化的
    device = device_arg or port_config.get(sn, {}).get('device', '').strip()
    if not device:
        return jsonify({'error': 'device required'}), 400

    # 把这次的 device 写回 port_config，作为下次默认值
    port_config.setdefault(sn, {})
    if port_config[sn].get('device') != device:
        port_config[sn]['device'] = device
        save_port_config()

    try:
        client = get_or_start_rtt(
            sn,
            device=device,
            remote_port=connected_jlink[sn]['server'],
            rtt_port=connected_jlink[sn].get('rtt'),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'status': 'started',
        'rtt_port': client.rtt_port,
        'active': client.active,
        'device': client.device,
    })


@app.route('/stop_rtt')
def stop_rtt_route():
    sn = request.args.get('sn', '')
    stop_rtt(sn)
    return jsonify({'status': 'stopped'})


@app.route('/get_rtt_data')
def get_rtt_data():
    sn = request.args.get('sn', '')
    since = request.args.get('since', 0, type=int)
    client = g_rtt_clients.get(sn)
    if not client:
        return jsonify({'lines': [], 'index': 0, 'active': False})
    lines, idx = client.get_lines(since)
    return jsonify({'lines': lines, 'index': idx, 'active': client.active})


@app.route('/clear_rtt_data')
def clear_rtt_data():
    """只清空内存 buffer。会话日志文件 (log/rtt_<sn>.log) 不会被动到。"""
    sn = request.args.get('sn', '')
    client = g_rtt_clients.get(sn)
    if not client:
        return jsonify({'status': 'cleared', 'active': False})

    client.clear_lines()
    return jsonify({'status': 'cleared', 'active': client.active})


@app.route('/download_rtt_log')
def download_rtt_log():
    sn = request.args.get('sn', '')
    # 只允许字母/数字/下划线的 SN，防止路径穿越
    if not sn or not all(c.isalnum() or c == '_' for c in sn):
        return jsonify({'error': 'invalid sn'}), 400

    filename = f'rtt_{sn}.log'
    file_path = os.path.join(LOG_DIR, filename)
    if not os.path.isfile(file_path):
        return jsonify({'error': 'log not found'}), 404

    return send_from_directory(
        LOG_DIR,
        filename,
        as_attachment=True,
        download_name=filename,
        mimetype='text/plain; charset=utf-8',
    )


# ============================================================
# 启动初始化
# ============================================================

if not os.path.exists(PORT_JSON):
    with open(PORT_JSON, 'w', encoding='utf-8') as f:
        f.write('{}')

with open(PORT_JSON, 'r', encoding='utf-8') as f:
    port_config = json.load(f)

# 进程启动时清零所有持久会话日志，开启新一轮记录
os.makedirs(LOG_DIR, exist_ok=True)
clear_all_session_logs()

get_jlink(port_config, connected_jlink)
get_serial(port_config, connected_jlink)
save_port_config()

atexit.register(stop_all_rtt)

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, use_reloader=False)
