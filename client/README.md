# LAN_Debug_client 使用方式

此目录维护 LAN_Debug 的命令行客户端，用于通过局域网 J-Link 烧录和调试。
`client/` 是仓库分类目录；真正复制到业务工程的是里面的整个 **`LAN_Debug/` 文件夹**。

## 1. 复制工具

将本仓 `client/LAN_Debug/` 复制到业务工程根目录，结果应为：

```text
你的工程/
├── .eide/
├── .vscode/
├── CubeMX/
├── User/
└── LAN_Debug/
    ├── jlink_flash.py
    ├── remote-jlink.json
    └── vscode/
        ├── launch.json
        └── tasks.json
```

不要把整个 `client/` 复制进去，也不要多套一层 `LAN_Debug/LAN_Debug/`。
旧工程原来使用 `Debug_LAN/` 时，改名为 `LAN_Debug/` 后还要同步更新
`.vscode/tasks.json` 和 EIDE Custom CLI 中的路径。

## 2. 准备环境与连接配置

开发电脑需要 Python 3.10+、SEGGER J-Link 软件；使用 VS Code 调试时还需要
EIDE、Cortex-Debug 和 ARM GDB。服务端运行 `LAN_Debug_server`，J-Link 接在服务端。
Python 脚本本身不需要安装 pip 依赖。

在服务端网页选择对应探针，填写芯片型号，下载配置并保存为
`LAN_Debug/remote-jlink.json`。已有配置可直接编辑：

| 字段 | 填写内容 |
| --- | --- |
| `ServerName` | 服务器实际 `.local` 名称或 IPv4 地址 |
| `Port` | 网页显示的远程 J-Link 端口，不是网页的 `8000` |
| `Device` | 实际芯片型号，例如 `STM32G474VE` |
| `Interface`、`SpeedKHz` | 实际接口与速度，例如 `SWD`、`4000` |
| `JLinkExe` | 可留空自动查找；需要时填开发电脑上的 SEGGER Commander 路径 |

网页端口、远程探针端口和本机 GDB 端口 `2331` 不可混用。
下载配置时保留已有的本机自定义 `JLinkExe` 路径。

## 3. EIDE 远程烧录

EIDE 烧录器选择 `Custom CLI`，命令填写：

```text
python "${ProjectRoot}/LAN_Debug/jlink_flash.py" --program "${programFile}"
```

Linux 使用 `python3`。先编译生成固件，再执行烧录；工具未配置全片擦除，
不要选择全片擦除命令。

## 4. VS Code F5 调试

将 `LAN_Debug/vscode/tasks.json` 和 `launch.json` 的条目合并到工程 `.vscode/`，
保留已有自定义任务。示例按 G4 模板配置，核对芯片、ELF、SVD 和本机工具路径。

编译后选择 **`Debug: JLINK LAN`** 并按 F5。前置任务自动启动本机 GDB Server；
它从 `LAN_Debug/remote-jlink.json` 读取远程连接。F5 会下载 ELF、复位并运行到
`main`，不会自动编译；调试前结束占用同一探针的网页 RTT 或其他调试会话。

前置任务等待调试器接入期间不主动停核；真正调试仍按配置执行 halt/load/reset。
启动后 30 秒内没有 GDB 客户端接入会退出并释放探针，包括 VS Code 在前置任务
就绪后取消调试的情况。看到超时提示后重新按 F5；已接入的调试会话不受此期限限制。

## 5. 检查与详细说明

在业务工程根目录运行以下命令，Linux 使用 `python3`：

```text
python LAN_Debug/jlink_flash.py --program Build/Debug/你的固件.hex --dry-run
python LAN_Debug/jlink_flash.py --gdb-server --dry-run
```

`--dry-run` 不执行烧录或启动 GDB Server，但仍会检查配置、解析服务器地址并查找本机工具。
它通过不代表真实硬件链路已通过。

- [完整说明：mDNS、工具路径、双板调试及排错](LAN_Debug/README.md)
- [服务端使用说明](../server/README.md)
- [服务端旧版卸载与升级](../server/UPGRADE.md)
