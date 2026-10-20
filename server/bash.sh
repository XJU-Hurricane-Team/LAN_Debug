#!/bin/bash
set -euo pipefail

SERVER_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$SERVER_DIR"

if [ ! -x .venv/bin/python ]; then
    echo "缺少 LAN_Debug_server 运行环境：$SERVER_DIR/.venv，请先执行 pack/deploy.sh。" >&2
    exit 1
fi
mkdir -p log
echo "正在启动 LAN_Debug_server：$SERVER_DIR"
# systemd 管理本服务的进程组；不按进程名或端口清理其他会话。
exec "$SERVER_DIR/.venv/bin/python" -m gunicorn -c gunicorncfg.py app:app
