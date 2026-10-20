# LAN_Debug 服务端升级、卸载与回退

适用于已经从旧仓库根目录部署 `lan-debug-server.service` 的 Linux 机器。
新服务名称统一为 `LAN_Debug_server`；服务代码位于本仓 `server/`。
以下命令在每台 Linux 服务器上分别执行，先完成一台，再处理另一台。

## 1. 确认旧服务，准备新文件

```bash
systemctl cat lan-debug-server
systemctl show lan-debug-server -p User -p WorkingDirectory -p ExecStart
```

记录每台机器自己的 `WorkingDirectory`、运行用户、局域网访问名称。
将新版完整仓库放到新位置，例如 `~/LAN_Debug`，此时服务代码位于
`~/LAN_Debug/server/`。也可以只复制 `server/` 的内容到独立目录
`~/LAN_Debug_server/`，随后在该目录执行下文命令。

不要把新仓库根目录直接覆盖旧服务根目录。不要复制旧 `.venv` 到新位置：
在新目录重建运行环境。现有 `/opt/SEGGER/JLink`、Avahi、USB 权限可沿用。
安装依赖需要网络；切换前准备好所需依赖或安排维护时间。

## 2. 预览并卸载旧服务

先结束旧服务上的烧录、调试、RTT 和串口会话。以下示例采用完整仓库布局：

```bash
cd ~/LAN_Debug/server
bash pack/uninstall-legacy.sh
sudo bash pack/uninstall-legacy.sh --apply
```

无参数只检查并显示范围；`--apply` 才执行。脚本只处理
`/etc/systemd/system/lan-debug-server.service` 这一旧服务及其覆盖配置：

- 在 `/var/backups/LAN_Debug/legacy-XXXXXXXX/` 备份服务配置、`port.json`、`log/`，
  并记录旧目录。备份失败会中止，不继续移除服务。
- 临时屏蔽旧单元的全局进程清理命令，由 systemd 仅停止旧服务的进程组。
- 禁用开机自启，删除旧服务单元，将其覆盖目录移入备份，重新加载 systemd。
- 保留旧源码目录、`.venv`、原配置和原日志；保留 J-Link、Avahi、
  系统软件包、udev 规则及用户组；不卸载新服务。

正常卸载后重复执行会报告无需卸载。遇到非标准安装路径、符号链接服务单元、
失效工作目录或正在运行的新服务，会停止并说明原因，不猜测删除目标。
脚本不会清理手工启动、脱离旧服务进程组的程序。

保存脚本输出的备份目录。两台机器分别生成各自的备份，不要互相覆盖配置。
现有服务代码启动时会清空部分 RTT 会话日志，因此历史日志只归档，
不要把备份的日志放入新服务 `log/` 后当作永久保存。

## 3. 迁移配置并部署新版

在同一个终端设置这台机器的实际旧目录（以下为示例）：

```bash
OLD_DIR="$HOME/LAN-Debug-Server"
# 新位置首次迁移时执行，-i 会在目标已有配置时询问，避免静默覆盖。
cp -i -- "$OLD_DIR/port.json" ./port.json
```

核对旧 `configurations.py` 是否有自定义 SDK 路径、端口起点、RTT 参数，
逐项合并到新版，不直接用旧源码覆盖新版文件。没有 `port.json` 时先核对
旧目录是否正确；确认原部署确实没有配置后，新部署可创建空配置。

使用原服务运行用户执行：

```bash
bash pack/deploy.sh
```

脚本定位自身所在目录，不依赖终端初始目录或仓库文件夹名称。
它创建新 `.venv`、安装依赖、配置服务并启动 `LAN_Debug_server`。
已安装 `/opt/SEGGER/JLink/JLinkExe` 时无需再次提供 `.deb`；
首次安装 J-Link 时仍需将匹配架构的官方安装包放入 `pack/`。
Avahi 提示中回车沿用已有名称，两台设备各保留自己的名称。

部署会检查旧单元是否仍存在；若存在，先停止并提示执行卸载步骤，
不会同时启用新旧服务。服务模板含占位符，须由部署脚本生成，
不要直接复制模板到 `/etc/systemd/system/`。

## 4. 验证与客户端更新

```bash
systemctl status LAN_Debug_server --no-pager
systemctl show LAN_Debug_server -p User -p WorkingDirectory -p ExecStart
journalctl -u LAN_Debug_server -n 80 --no-pager
```

确认工作目录为新服务目录，旧服务不再启动。打开原来的
`http://你的名称.local:8000/`，核对页面显示 `LAN_Debug_server`，
烧录命令引用 `LAN_Debug/jlink_flash.py`。需要验证探针与 RTT 时，
在没有其他会话占用的情况下单独测试。

业务工程将工具目录统一为 `LAN_Debug/`，同步合并
`client/LAN_Debug/vscode/` 示例中的路径；网页下载的配置保存到
`LAN_Debug/remote-jlink.json`，EIDE Custom CLI 也改用这一目录。
旧目录仅改名而不更新任务，仍会找不到脚本。

## 5. 部署失败时回退

旧源码和运行环境保留在原位置。先停止并禁用新服务（若尚未安装，
跳过此命令），防止两个服务抢占探针或端口：

```bash
sudo systemctl disable --now LAN_Debug_server
```

将 `BACKUP` 改为卸载脚本输出的真实备份目录，恢复旧单元和原有覆盖配置：

```bash
BACKUP="/var/backups/LAN_Debug/legacy-实际备份编号"
sudo cp -a -- "$BACKUP/lan-debug-server.service" /etc/systemd/system/
if sudo test -d "$BACKUP/lan-debug-server.service.d"; then
    sudo cp -a -- "$BACKUP/lan-debug-server.service.d" /etc/systemd/system/
fi
sudo systemctl daemon-reload
sudo systemctl enable --now lan-debug-server
sudo systemctl status lan-debug-server --no-pager
```

回退启动旧版前确认新服务和其他 J-Link 会话已停止：旧版启动脚本仍含
全局进程清理行为。备份内日志保持归档，不恢复进即将启动的日志目录。
新版正常运行并完成验收后，再决定是否手工删除旧源码目录和旧 `.venv`；
卸载脚本不自动删除这些文件。

## 验证范围

仓库离线测试覆盖路径定位、模板替换及卸载预览/备份/失败中止/重复执行，
使用模拟 systemd 和临时文件，不等于两台真实 Linux 服务器的部署验收。
