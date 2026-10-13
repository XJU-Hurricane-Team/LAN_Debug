#!/bin/bash
# Debian / Ubuntu：仅设置 Avahi 发布名，不修改系统 hostname、hosts 或网络配置。
# 用法：bash pack/configure-avahi.sh [名称]，例如 robot（自动加 .local）。
set -euo pipefail

CONF=/etc/avahi/avahi-daemon.conf
fail() { echo "[ERROR] $*" >&2; exit 1; }
valid_name() { [[ "$1" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$ ]]; }

[ "$#" -le 1 ] || fail "用法：bash pack/configure-avahi.sh [名称]"
if [ "$(id -u)" -eq 0 ]; then
    SUDO=()
else
    SUDO=(sudo)
fi

# 重复部署默认沿用已配置的名称，否则使用系统短主机名。
DEFAULT_NAME="$(hostname -s)"
if [ -r "$CONF" ]; then
    EXISTING_NAME="$(awk '
        /^[[:space:]]*\[/ { server = ($0 ~ /^[[:space:]]*\[server\][[:space:]]*$/) }
        server && /^[[:space:]]*host-name[[:space:]]*=/ {
            sub(/^[^=]*=[[:space:]]*/, ""); sub(/[[:space:]]*$/, ""); print; exit
        }
    ' "$CONF")"
    DEFAULT_NAME="${EXISTING_NAME:-$DEFAULT_NAME}"
fi
valid_name "$DEFAULT_NAME" || DEFAULT_NAME=lan-debug

if [ "$#" -eq 1 ]; then
    MDNS_NAME="${1%.local}"
    valid_name "$MDNS_NAME" || fail "名称需为 1–63 个英文字母、数字或连字符，首尾不能是连字符。"
else
    while true; do
        read -r -p "局域网访问名称（例如 robot → robot.local）[$DEFAULT_NAME]: " MDNS_NAME \
            || fail "未读到名称；非交互运行请通过参数指定。"
        MDNS_NAME="${MDNS_NAME:-$DEFAULT_NAME}"
        MDNS_NAME="${MDNS_NAME%.local}"
        valid_name "$MDNS_NAME" && break
        echo "名称需为 1–63 个英文字母、数字或连字符，首尾不能是连字符。"
    done
fi

if ! command -v avahi-daemon >/dev/null 2>&1; then
    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" apt-get install -y avahi-daemon
fi
[ -r "$CONF" ] || fail "无法读取 $CONF"

TMP_CONF="$(mktemp)"
trap 'rm -f "$TMP_CONF"' EXIT
# 保留原文件的注释和其他配置；只修改 [server] 下的 host-name。
awk -v name="$MDNS_NAME" '
    /^[[:space:]]*\[/ {
        if (server && !written) { print "host-name=" name; written = 1 }
        server = ($0 ~ /^[[:space:]]*\[server\][[:space:]]*$/)
        if (server) found = 1
    }
    server && /^[[:space:]]*host-name[[:space:]]*=/ {
        if (!written) print "host-name=" name
        written = 1; next
    }
    { print }
    END {
        if (!found) print "\n[server]"
        if (!written) print "host-name=" name
    }
' "$CONF" > "$TMP_CONF"

# 不覆盖已有的特殊域名/机器 ID 命名设置，以免显示错误的访问地址。
awk '
    /^[[:space:]]*\[/ { server = ($0 ~ /^[[:space:]]*\[server\][[:space:]]*$/) }
    server && /^[[:space:]]*domain-name[[:space:]]*=/ {
        sub(/^[^=]*=[[:space:]]*/, ""); sub(/[[:space:]]*$/, "")
        if ($0 != "local") exit 1
    }
    server && /^[[:space:]]*host-name-from-machine-id[[:space:]]*=[[:space:]]*yes[[:space:]]*$/ { exit 1 }
' "$CONF" || fail "已有自定义 domain-name 或机器 ID 命名配置，请先检查 $CONF；未修改配置。"

if ! cmp -s "$CONF" "$TMP_CONF"; then
    BACKUP="${CONF}.bak.$(date +%Y%m%d%H%M%S).$$"
    "${SUDO[@]}" cp -p "$CONF" "$BACKUP"
    "${SUDO[@]}" install -m 0644 "$TMP_CONF" "$CONF"
    echo "已备份原配置：$BACKUP"
fi
"${SUDO[@]}" systemctl enable avahi-daemon.service
"${SUDO[@]}" systemctl restart avahi-daemon.service
"${SUDO[@]}" systemctl is-active --quiet avahi-daemon.service \
    || fail "Avahi 未启动，请检查：sudo journalctl -u avahi-daemon -b"

cat <<EOF

Avahi 已启动，配置的访问地址：http://${MDNS_NAME}.local:8000
客户端需在同一局域网，并允许 mDNS（UDP 5353）；名称冲突时 Avahi 可能自动改名，请查看服务日志。
Windows Clash Verge：在“系统代理”的绕过列表中保留原有项，追加 *.local。
若列表不可编辑，检查是否需要关闭“始终使用默认绕过”，保存后确认设置生效。
<local> 仅匹配不含点的短主机名；仅加 DOMAIN-SUFFIX,local,DIRECT 不能替代系统代理绕过。
以上适用于系统代理默认模式；PAC / TUN 模式需另行检查其绕过、DNS 与路由配置。
EOF
