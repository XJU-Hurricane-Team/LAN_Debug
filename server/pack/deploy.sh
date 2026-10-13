#!/bin/bash
# ============================================================
# LAN Debug Server  -  一键部署脚本
# ------------------------------------------------------------
# 用途：在一台干净的 Linux 设备（树莓派 / 任意 arm64 主机）上把
#       Python 虚拟环境、JLink 驱动、systemd 自启动服务一次性配好。
#
# 用法：
#   1. 把整个项目 clone 或 scp 到目标机器上
#   2. cd 到项目根目录
#   3. bash pack/deploy.sh
#
# 注意：
#   - 必须用普通用户跑（脚本内部需要 sudo 时会自己提权）
#   - 默认安装的是 arm64 版 JLink 驱动；非 arm64 机器请替换 pack/ 下的 .deb
# ============================================================

set -euo pipefail

# ---------- 基础信息 ----------
PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$PACK_DIR")"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
SERVICE_NAME="lan-debug-server"
SERVICE_TEMPLATE="$PACK_DIR/${SERVICE_NAME}.service"
SERVICE_TARGET="/etc/systemd/system/${SERVICE_NAME}.service"

CURRENT_USER="$USER"
CURRENT_GROUP="$(id -gn)"
CURRENT_HOME="$HOME"
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"

# 把系统架构映射到 SEGGER JLink 包文件名里的架构 tag
#   dpkg arm64  / uname aarch64  -> arm64
#   dpkg amd64  / uname x86_64   -> x86_64
#   dpkg armhf  / uname armv7l   -> arm    (32-bit ARM)
#   dpkg i386   / uname i686     -> i386
case "$ARCH" in
    arm64|aarch64)    JLINK_ARCH_TAG="arm64"  ;;
    amd64|x86_64)     JLINK_ARCH_TAG="x86_64" ;;
    armhf|armv7l)     JLINK_ARCH_TAG="arm"    ;;
    i386|i686)        JLINK_ARCH_TAG="i386"   ;;
    *)                JLINK_ARCH_TAG=""       ;;
esac

# 优先按架构匹配；多个版本则取版本号最高的（V941 优于 V940）
JLINK_DEB=""
if [ -n "$JLINK_ARCH_TAG" ]; then
    JLINK_DEB="$(ls -1 "$PACK_DIR"/JLink_Linux_*_"${JLINK_ARCH_TAG}".deb 2>/dev/null | sort -V | tail -n 1 || true)"
fi

# ---------- 颜色输出 ----------
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

step()  { echo -e "\n${BOLD}${GREEN}==> $*${NC}"; }
info()  { echo -e "    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ---------- 前置检查 ----------
if [ "$(id -u)" -eq 0 ]; then
    fail "请用普通用户执行（不要 sudo bash deploy.sh）。脚本内部会按需 sudo。"
fi

[ -f "$SERVICE_TEMPLATE" ] || fail "找不到 service 模板: $SERVICE_TEMPLATE"
[ -f "$PROJECT_DIR/requirements.txt" ] || fail "找不到 requirements.txt（你确定脚本放在 项目/pack/ 下吗？）"
[ -f "$PROJECT_DIR/bash.sh" ] || fail "找不到 bash.sh"
[ -f "$PACK_DIR/configure-avahi.sh" ] || fail "找不到 configure-avahi.sh"

if [ -z "$JLINK_DEB" ]; then
    available="$(ls -1 "$PACK_DIR"/JLink_Linux_*.deb 2>/dev/null | xargs -n1 basename 2>/dev/null)"
    available="${available:-(无)}"
    fail "找不到匹配当前架构的 JLink 安装包。
        系统架构 : $ARCH${JLINK_ARCH_TAG:+  -> 期望文件名: JLink_Linux_*_${JLINK_ARCH_TAG}.deb}
        pack/ 下现有:
$(echo "$available" | sed 's/^/            /')
        请把对应架构的 JLink 包放进 pack/ 后重试。"
fi

# ---------- 信息确认 ----------
cat <<EOF

${BOLD}LAN Debug Server  -  一键部署${NC}
--------------------------------------------
  项目目录   : $PROJECT_DIR
  运行用户   : $CURRENT_USER
  运行用户组 : $CURRENT_GROUP
  用户家目录 : $CURRENT_HOME
  系统架构   : $ARCH  (匹配 tag: ${JLINK_ARCH_TAG:-未知})
  JLink 包   : $(basename "$JLINK_DEB")
  service    : $SERVICE_TARGET
--------------------------------------------
EOF

read -p "确认开始部署? [y/N] " -n 1 -r; echo
[[ "$REPLY" =~ ^[Yy]$ ]] || { info "已取消。"; exit 0; }

step "配置 Avahi 局域网访问名称"
bash "$PACK_DIR/configure-avahi.sh"

# ============================================================
# 1. 系统依赖
# ============================================================
step "[1/6] 安装系统依赖"
sudo apt-get update
sudo apt-get install -y \
    python3 python3-venv python3-pip \
    bsdextrautils util-linux \
    iproute2 psmisc procps \
    libusb-1.0-0 \
    udev

# `script` 命令必须在 —— service 用它套 PTY，没它装不上
if ! command -v script >/dev/null 2>&1; then
    fail "依赖 'script' 命令（util-linux 提供）安装失败，请手动 apt install bsdextrautils"
fi

# ============================================================
# 2. JLink 驱动
# ============================================================
step "[2/6] 安装 JLink 驱动"
if [ -x /opt/SEGGER/JLink/JLinkExe ]; then
    info "已检测到 /opt/SEGGER/JLink/JLinkExe，跳过驱动安装"
else
    info "安装 $(basename "$JLINK_DEB") ..."
    sudo dpkg -i "$JLINK_DEB" || sudo apt-get install -y -f
    [ -x /opt/SEGGER/JLink/JLinkExe ] || fail "JLink 安装后仍找不到 /opt/SEGGER/JLink/JLinkExe"
fi

# udev 规则：让普通用户能直接访问 J-Link USB 设备（不用每次 sudo）
JLINK_UDEV=/etc/udev/rules.d/99-jlink.rules
if [ ! -f "$JLINK_UDEV" ]; then
    info "写入 J-Link udev 规则到 $JLINK_UDEV"
    sudo tee "$JLINK_UDEV" >/dev/null <<'RULES'
# SEGGER J-Link
SUBSYSTEM=="usb", ATTRS{idVendor}=="1366", MODE="0666", GROUP="plugdev"
RULES
    sudo udevadm control --reload-rules
    sudo udevadm trigger
fi

# ============================================================
# 3. 用户组（USB / 串口权限）
# ============================================================
step "[3/6] 把 $CURRENT_USER 加入 plugdev / dialout 组"
sudo usermod -aG plugdev,dialout "$CURRENT_USER"
info "（组变更要重新登录或重启后才在交互 shell 里生效，但 systemd service 立即生效）"

# ============================================================
# 4. Python 虚拟环境 + 依赖
# ============================================================
step "[4/6] 创建 Python 虚拟环境并安装依赖"
cd "$PROJECT_DIR"

if [ ! -d .venv ]; then
    info "创建 .venv ..."
    python3 -m venv .venv
else
    info ".venv 已存在，复用"
fi

# 用绝对路径，不依赖 source activate
"$PROJECT_DIR/.venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install -r requirements.txt

# ============================================================
# 5. 运行时文件
# ============================================================
step "[5/6] 初始化 log 目录和 port.json"
mkdir -p "$PROJECT_DIR/log"
[ -f "$PROJECT_DIR/port.json" ] || echo "{}" > "$PROJECT_DIR/port.json"
chmod +x "$PROJECT_DIR/bash.sh"

# ============================================================
# 6. systemd service
# ============================================================
step "[6/6] 安装 systemd service"

# 用 sed 把模板里硬编码的 pickingchip / 路径替换成当前实际值。
# 替换顺序很关键：先长后短，先路径后用户名，避免误伤。
#   1) 先替换最长的 项目目录 路径
#   2) 再替换 /home/pickingchip 家目录前缀（Environment 里的 HOME / PATH 等）
#   3) 然后逐行处理 User= / Group= / Environment="USER=..."
#      —— 注意 Environment="USER=pickingchip" 行尾是引号，不能靠 $ 或空格锚定
TMP_SERVICE="$(mktemp)"
trap 'rm -f "$TMP_SERVICE"' EXIT

sed \
    -e "s|/home/pickingchip/LAN-Debug-Server|${PROJECT_DIR}|g" \
    -e "s|/home/pickingchip|${CURRENT_HOME}|g" \
    -e "s|^User=pickingchip|User=${CURRENT_USER}|" \
    -e "s|^Group=pickingchip|Group=${CURRENT_GROUP}|" \
    -e "s|USER=pickingchip|USER=${CURRENT_USER}|g" \
    "$SERVICE_TEMPLATE" > "$TMP_SERVICE"

info "生成的 service 文件预览（关键几行）："
grep -E "^(User|Group|WorkingDirectory|Environment=\"HOME|Environment=\"USER|ExecStart=)" "$TMP_SERVICE" | sed 's/^/    /'

sudo install -m 0644 "$TMP_SERVICE" "$SERVICE_TARGET"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

# 等 3 秒看启动状态
sleep 3
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    info "service 状态：${GREEN}active${NC}"
else
    warn "service 不是 active 状态，检查："
    sudo systemctl status "$SERVICE_NAME" --no-pager | head -20
fi

# ============================================================
# 完成
# ============================================================
LOCAL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
LOCAL_IP="${LOCAL_IP:-<本机IP>}"

cat <<EOF

${GREEN}${BOLD}========== 部署完成 ==========${NC}

  Web UI         : ${BOLD}http://${LOCAL_IP}:8000${NC}

  常用命令：
    查看状态     : sudo systemctl status ${SERVICE_NAME}
    查看实时日志 : sudo journalctl -u ${SERVICE_NAME} -f
    重启服务     : sudo systemctl restart ${SERVICE_NAME}
    停止服务     : sudo systemctl stop ${SERVICE_NAME}
    禁用自启     : sudo systemctl disable ${SERVICE_NAME}

  下次开机会自动启动。如果浏览器打不开，先看 journalctl 排错。
  也可使用上面配置的 http://名称.local:8000；Windows Clash Verge 系统代理绕过列表请追加 *.local（保留原有项）。

EOF
