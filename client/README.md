# 远程 J-Link 工具

这是以 G4 模板为可选远程烧录与调试工具包。G4 模板默认使用本地 USB J-Link，需要局域网远程烧录或调试时，按下面步骤接入。示例芯片及 ELF 路径按 G4 配置；用于其他芯片工程时需同步调整并验证。

## 必做

### 1. 准备环境

- 开发电脑：Python 3.10+、SEGGER J-Link SDK、EIDE、Cortex-Debug 和 ARM GDB。脚本无需安装 pip 依赖。
- 小电脑/香橙派：运行 LAN-Debug-Server 和 Avahi，接好 J-Link 与目标板。
- 两端网络互通，开发电脑能解析服务器的 `.local` 名称。

#### Linux 的 Avahi / mDNS 准备

以下命令适用于使用 systemd 的 Debian / Ubuntu（含相应的香橙派系统），其他发行版按其包管理器和服务管理方式安装。

**接 J-Link 的小电脑 / 香橙派**：安装并启动 Avahi，用于发布本机的 `.local` 名称；LAN-Debug-Server 和 J-Link 软件仍需单独部署。

```bash
sudo apt update
sudo apt install avahi-daemon avahi-utils
sudo systemctl enable --now avahi-daemon
systemctl is-active avahi-daemon
hostnamectl --static
```

`remote-jlink.json` 的 `ServerName` 应填写服务器实际发布的名称。Avahi 默认使用系统主机名（也可在其配置中覆盖），并非安装后就自动叫 `robocon-r1-debug.local`；该值只是本工具的示例。

**运行 EIDE / Python 的 Linux 开发电脑**：先执行下面的 `getent` 检查。如果系统已能解析该名称，可沿用现有配置；否则可以使用 Avahi + NSS 路线：

```bash
sudo apt update
sudo apt install avahi-daemon avahi-utils libnss-mdns
sudo systemctl enable --now avahi-daemon
```

在开发电脑上检查，将示例名称换成实际服务器名称：

```bash
avahi-resolve-host-name -4 robocon-r1-debug.local
getent ahostsv4 robocon-r1-debug.local
```

两者应返回服务器的实际局域网 IPv4。`avahi-utils` 提供诊断工具，`libnss-mdns` 让使用系统名称解析的程序能够查询 mDNS；只在服务器安装 Avahi，不代表 Linux 客户端已经支持 `.local`。Python 脚本使用系统解析，因此不能只凭 `avahi-resolve-host-name` 成功就判断接入完成。

若 Avahi 查询成功而 `getent` 失败，检查客户端 `/etc/nsswitch.conf` 的 `hosts:` 行是否接入 `mdns4_minimal` 或 `mdns4`，按发行版配置保留已有解析项，不直接覆盖整行。若两者都失败，检查服务器发布名称、Avahi 服务及网络是否允许 mDNS（UDP 5353 组播），以及热点是否启用了客户端隔离。使用明确 IPv4 时无需 mDNS，但地址变化后需更新 JSON。

依据：[Ubuntu avahi-daemon 软件包](https://packages.ubuntu.com/jammy/avahi-daemon)、[Avahi nss-mdns 官方说明](https://github.com/avahi/nss-mdns)。以上为安装和检查步骤，Linux 实机链路仍需验证。

### 2. 复制工具和配置

1. 将整个 `Debug_LAN/` 复制到实际工程根目录，与 `.eide/`、`.vscode/`、`CubeMX/`、`User/` 同级。在本仓库 G4 模板中使用时，工程根目录是 `g4_template/`。
2. 将 `Debug_LAN/vscode/launch.json` 和 `tasks.json` 合并到工程 `.vscode/`。没有自定义配置时可直接复制覆盖；已有配置时，分别合并 `configurations` 和 `tasks` 数组。

`remote-jlink.json` 和 `jlink_flash.py` 保留在 `Debug_LAN/`。只复制工具目录不会启用调试配置。

### 3. 核对参数

默认配置如下，与实际设备一致时无需修改：

| 文件 | 默认值 | 按需修改 |
|---|---|---|
| `Debug_LAN/remote-jlink.json` | `ServerName: robocon-r1-debug.local`、`Port: 19011` | 服务器名称和网页中对应探针的远程 J-Link 端口；也可使用实际 IPv4 |
| `Debug_LAN/remote-jlink.json` | `Device: STM32G474VE`、`Interface: SWD`、`SpeedKHz: 8000` | 实际芯片、接口和速度；连接不稳定可降至 `4000` 或 `1000` |
| `.vscode/launch.json` | `Build/Debug/g4_template.elf` | 工程改名后修改两个调试条目的 `executable`；更换芯片时核对 `device` 和 `svdFile` |
| VS Code 用户设置 JSON | ARM GDB 和 J-Link 工具路径 | 核对当前开发电脑上的真实目录，见下方“工具路径” |

JSON 的 `Port` 是远程探针端口，不是网页端口 `8000`，也不是本机 GDB 端口 `2331`。修改 JSON 不会自动同步 `launch.json`。使用 `.local` 名称时，脚本每次解析当前 IP，无需手填动态地址。

### 4. 编译并启动调试

1. 先编译工程，并停止占用同一探针的 RTT 或其他调试会话。
2. 按 **Ctrl+Shift+D** 打开 VS Code“运行和调试”，选择 **`Debug: JLINK LAN`**，点击启动按钮或按 **F5**。

前置任务会自动启动 GDB Server，无需手动运行任务，但不会自动编译。F5 会下载 ELF、复位并运行到 `main`。前置任务失败时先排错，不要选择“仍然调试”。

若 EIDE 3.27.2 提示“当前类型 'Custom' 不受支持”，将 EIDE 烧录器切回 `JLink`，再选择固定的 `Debug: JLINK LAN`。该配置仍走远程链路；EIDE 的一键调试按钮不会自动选择它。

### EIDE 单独远程烧录

需要使用 EIDE 的烧录按钮时，将烧录器设为 `Custom CLI`，命令填写：

```text
python "${ProjectRoot}/Debug_LAN/jlink_flash.py" --program "${programFile}"
```

Linux 将 `python` 改为 `python3`。不要选择全片擦除，本工具未配置该命令。F5 自身会下载 ELF，无需先配置单独烧录。

| 使用方式 | J-Link 插在哪 | EIDE 单独烧录 | VS Code F5 配置 |
|---|---|---|---|
| 本地 USB | 开发电脑 | `JLink`（附加命令为空） | `Debug: JLINK` |
| 远程局域网 | 小电脑/香橙派 | `Custom CLI` | `Debug: JLINK LAN` |

烧录器与 F5 配置分别选择。为绕过 Custom 调试提示而切回 `JLink` 后，EIDE 烧录按钮使用本地配置；要单独远程烧录，需切回 `Custom CLI`。

## 常见问题

### 工具路径

Windows 在 VS Code **用户设置 JSON** 中填写开发电脑上的实际路径，已配置且有效时无需修改；个人路径不要提交到工程：

```json
{
    "cortex-debug.armToolchainPath.windows": "D:/实际工具目录/gcc_arm/bin",
    "EIDE.JLink.InstallDirectory": "D:/实际工具目录/jlink",
    "cortex-debug.JLinkGDBServerPath.windows": "D:/实际工具目录/jlink/JLinkGDBServerCL.exe"
}
```

GCC 目录应包含 `arm-none-eabi-gdb.exe`；J-Link 使用包含 Commander、GDB Server 和配套库的完整 SEGGER 工具包。上述 J-Link 设置用于 EIDE 本地烧录和 Cortex-Debug 本地调试；Linux 默认从 PATH 查找工具。

远程脚本会自动查找 EIDE、SEGGER 标准安装目录，以及 Windows 的 `%LOCALAPPDATA%/stm32cube/bundles/jlink-gdbserver/*/bin`。脚本不读取 VS Code 用户设置；仍找不到工具时，在 `remote-jlink.json` 的 `JLinkExe` 中填写**开发电脑**上同一工具包的 `JLink.exe`（Linux 为 `JLinkExe`）路径。网页下载的配置通常将该字段留空，按需补填或保留已有本机路径。

从便携版迁移到安装版、移动工具目录或更换电脑后，重新核对上述路径并重新加载 VS Code，避免旧路径失效或误调用 Java 的同名 `jlink`。

### 双板调试

分别创建两个工程，各自复制工具并填写对应探针端口、芯片和 ELF 路径。依次调试可共用本机 GDB 端口 `2331`，先结束上一会话。

同时调试需要两路独立 J-Link，并用两个 VS Code 窗口打开工程。第二工程额外修改：

- 在远程任务的 `args` 中增加 `"--gdb-port", "2341"`。
- 将 LAN 调试配置的 `gdbTarget` 改为 `127.0.0.1:2341`。

第一工程使用本机端口 `2331`–`2333`，第二工程使用 `2341`–`2343`，这些端口均需空闲。仅修改 JSON 的 `Port` 不会改变本机 GDB 端口。

### 排错与检查

- **下拉框没有 LAN 配置**：确认已将示例合并到实际工程的 `.vscode/`。
- **一直等待 preLaunchTask**：若输出停在 `Waiting for GDB connection...`，更新工程中的 `jlink_flash.py`；旧版脚本可能因该提示没有换行而无法报告就绪。
- **新版 SDK 就绪提示**：V9.42 可能先输出 `Connected to target`，客户端也接受此提示，不再只等待旧提示。
- **退出码为 0 但目标停止**：实测远程 SDK 收尾可能打印 `ERROR: Communication timed out` 后仍退出 0，客户端已将其判为失败。停止对应 RTT，核对目标运行状态及本次断点，恢复运行后用新心跳确认；不要因此直接重烧固件。
- **本机端口被占用**：结束上一调试会话或对应后台任务。正常断开后 Server 自动退出；启动后取消且尚未连接时，手动终止 `JLINK LAN` 任务。

在工程根目录执行以下检查，Linux 使用 `python3`：

```text
python Debug_LAN/jlink_flash.py --program Build/Debug/工程名.hex --dry-run
python Debug_LAN/jlink_flash.py --gdb-server --dry-run
python -B -m unittest discover -s Debug_LAN/tests -v
```
