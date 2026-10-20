#!/bin/bash
# 只移除旧 systemd 服务；默认预览，--apply 才执行。
set -euo pipefail

APPLY=false
case "${1:-}" in
    "") ;;
    --apply) APPLY=true ;;
    -h|--help)
        echo "用法：bash pack/uninstall-legacy.sh [--apply]"
        echo "默认只检查。执行：sudo bash pack/uninstall-legacy.sh --apply"
        echo "保留旧部署目录、.venv、配置、日志、J-Link、Avahi 和系统依赖。"
        exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { echo "参数过多" >&2; exit 2; }

UNIT=lan-debug-server.service
UNIT_FILE="/etc/systemd/system/$UNIT"
DROPINS="${UNIT_FILE}.d"
RUNTIME_DIR="/run/systemd/system/${UNIT}.d"
OVERRIDE="$RUNTIME_DIR/zzz-LAN_Debug-uninstall.conf"
fail() { echo "错误：$*" >&2; exit 1; }

STATE="$(systemctl show "$UNIT" -p LoadState --value)"
if [ "$STATE" = not-found ] && [ ! -e "$UNIT_FILE" ] && [ ! -L "$UNIT_FILE" ] && [ ! -e "$DROPINS" ]; then
    echo "未安装旧服务 $UNIT，无需卸载。"
    exit 0
fi
[ "$STATE" = loaded ] || fail "旧服务状态为 $STATE，请先检查 systemctl cat $UNIT。"
FRAGMENT="$(systemctl show "$UNIT" -p FragmentPath --value)"
[ "$FRAGMENT" = "$UNIT_FILE" ] && [ -f "$UNIT_FILE" ] && [ ! -L "$UNIT_FILE" ] ||
    fail "旧服务不是标准安装文件 $UNIT_FILE；实际为 $FRAGMENT，请人工核对。"
[ ! -L "$DROPINS" ] || fail "旧服务覆盖目录是符号链接，请人工核对：$DROPINS"
OLD_DIR="$(systemctl show "$UNIT" -p WorkingDirectory --value)"
[[ "$OLD_DIR" = /* ]] && [ "$OLD_DIR" != / ] &&
    [ -f "$OLD_DIR/app.py" ] && [ -f "$OLD_DIR/bash.sh" ] ||
    fail "无法确认旧部署目录：$OLD_DIR。为避免遗漏配置，请先检查服务路径。"

echo "旧服务：$UNIT"
echo "旧目录：$OLD_DIR（完整保留）"
echo "执行时将备份服务配置、port.json 和 log/ 到 /var/backups/LAN_Debug/，停用并移除旧服务。"
echo "新服务 LAN_Debug_server、J-Link、Avahi 和系统依赖均保留。"
$APPLY || { echo "当前仅预览；确认后使用 sudo bash pack/uninstall-legacy.sh --apply。"; exit 0; }
[ "$(id -u)" -eq 0 ] || fail "--apply 需要 sudo。"
if systemctl is-active --quiet LAN_Debug_server.service; then
    fail "新服务正在运行，请在切换到新服务之前卸载旧版，避免同时操作探针。"
fi
[ ! -e "$OVERRIDE" ] && [ ! -L "$OVERRIDE" ] || fail "临时覆盖文件已存在：$OVERRIDE"

umask 077
mkdir -p "/var/backups/LAN_Debug"
BACKUP="$(mktemp -d "/var/backups/LAN_Debug/legacy-XXXXXXXX")"
cp -a -- "$UNIT_FILE" "$BACKUP/"
if [ -d "$DROPINS" ]; then cp -a -- "$DROPINS" "$BACKUP/"; fi
systemctl cat "$UNIT" > "$BACKUP/effective-service.txt"
printf '%s\n' "$OLD_DIR" > "$BACKUP/old-directory.txt"
# 先完成数据备份再停止；停止后再同步一次，收齐停止期间的写入。
backup_data() {
    if [ -e "$OLD_DIR/port.json" ]; then cp -a -- "$OLD_DIR/port.json" "$BACKUP/"; fi
    if [ -d "$OLD_DIR/log" ]; then
        mkdir -p "$BACKUP/log"
        cp -a -- "$OLD_DIR/log/." "$BACKUP/log/"
    fi
}
backup_data
echo "备份位置：$BACKUP"

# 旧单元的 ExecStopPost 使用全局 pkill。临时移除这些命令，
# 由 systemd 仅终止旧服务 cgroup，避免误伤其他 J-Link 会话。
cleanup() {
    rm -f -- "$OVERRIDE"
    rmdir -- "$RUNTIME_DIR" 2>/dev/null || true
    systemctl daemon-reload
}
mkdir -p "$RUNTIME_DIR"
trap cleanup EXIT
cat > "$OVERRIDE" <<'EOF'
[Service]
ExecStop=
ExecStopPost=
KillMode=control-group
EOF
systemctl daemon-reload
[ -z "$(systemctl show "$UNIT" -p ExecStop --value)" ] &&
    [ -z "$(systemctl show "$UNIT" -p ExecStopPost --value)" ] &&
    [ "$(systemctl show "$UNIT" -p KillMode --value)" = control-group ] ||
    fail "安全停止覆盖未生效，未停止服务。"
systemctl stop "$UNIT"
backup_data
systemctl disable "$UNIT"
rm -- "$UNIT_FILE"
# 已备份的旧服务覆盖配置移至备份中；不触碰其他服务。
if [ -d "$DROPINS" ]; then mv -- "$DROPINS" "$BACKUP/removed-dropins"; fi
cleanup
trap - EXIT
echo "旧服务已卸载。配置、日志和旧运行目录保留，备份位于：$BACKUP"
echo "后续迁移及回退步骤见 server/UPGRADE.md。"
