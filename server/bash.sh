#! /bin/bash
cd ~/LAN-Debug-Server || exit

rm -f ./log/gunicorn.pid

# 清理残留进程，避免端口冲突
echo "正在停止旧进程..."
pkill -9 -f 'gunicorn.*app:app' 2>/dev/null
pkill -9 -f 'JLinkRemoteServerCLExe' 2>/dev/null
sleep 1

# 清理端口（如果进程未及时释放）
for port in $(ss -tlnp | grep -oP '0\.0\.0\.0:\K(19\d{3})' 2>/dev/null); do
    fuser -k "${port}/tcp" 2>/dev/null
done

source .venv/bin/activate
echo "正在启动服务..."
gunicorn -c gunicorncfg.py app:app
