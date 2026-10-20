# LAN_Debug

战队LAN调试基础设施。`client/LAN_Debug/`维护LAN_Debug_client命令行工具源码，`server/`维护Linux远程J-Link、网页RTT和串口TCP转发。桌面客户端由相邻`embedded_helper`维护，固件logger归STM32-Template；同一工具不与旧来源并行开发。

## 命名与目录

统一基础名称为 `LAN_Debug`；组件名称为 `LAN_Debug_server`、`LAN_Debug_client`，server/client 只作后缀。仓库以 `server/`、`client/` 分类，客户端可复制目录固定为 `client/LAN_Debug/`。新命令和配置路径不得使用旧名称；下文来源记录、既有 Release 标识及旧服务卸载入口保留历史名称用于追溯和迁移。

已有 Linux 部署见[升级、卸载与回退说明](server/UPGRADE.md)。

## 源码来源与边界

| 目录 | 初始来源 | 分支 | 来源提交 |
| --- | --- | --- | --- |
| `server/` | LAN-Debug（原LAN-Debug-Server） | `main` | `35bf8bd2e307d0dcae227bcd7b06d357213639ec` |
| `client/` | STM32-Template的`Debug_LAN/` | `temp` | `b39113c36c198ef25412050ec043fd03caa20fdc` |

这些提交是来源基线，不是当前部署或验收结论。当前业务实现由本仓维护；完整引入过程留在Git，不另建历史副本。未纳入来源仓库的Git元数据、日志、虚拟环境、缓存及机器配置。`client/LAN_Debug/remote-jlink.json`仍为来源示例，使用前核对实际设备。

本仓不携带SEGGER安装包，`server/pack/`保留部署脚本。已安装`/opt/SEGGER/JLink/JLinkExe`时沿用现有SDK，首次安装才要求匹配架构的官方`.deb`，需按适用许可自行准备。查询、服务启动、日志清理、进程终止及网页写配置的副作用仍存在，具体以源码为准，不能当成纯只读入口。

## 使用入口与兼容

- [命令行客户端](client/README.md)：将本仓`client/LAN_Debug/`整个文件夹复制到业务工程根目录，工具目录统一为`LAN_Debug/`；已安装版本化工具继续按工程锁使用。
- [Linux服务端](server/README.md)：服务工作目录为本仓`server/`，部署命令从该目录执行，不从仓库根执行旧的`pack/`路径。
- `embedded_helper`当前仍通过SDK直连本地/远程J-Link读取变量；远程变量与服务端网页RTT手动互斥，不共享一个采集服务。

源码接管不代表Release下载已迁移。helper现有可信工具目录和下载仍兼容STM32-Template的`debug-lan-v0.1.0-alpha.1/alpha.2`；旧包、工程锁和接口需继续兼容。新发布渠道与包来源迁移另行核验，不仅修改README或仓库名。

## 后续待讨论方向

以下是方向，尚未作为已实现能力或本轮必做：

- 远端r1唯一采集和保存；本地由helper采集/保存，采用统一日志schema。
- RTT为日志主通道，串口仅承担高门槛告警；38400链路不承诺日志主通道吞吐。
- 标注经helper/API写入，网页只读；离线显式promote，不自动双写合并。
- 数据拟分`raw/`、`index/index.jsonl`、`run/`，原始轮次封存不可变，索引只追加并带`sv`；板级日志与程序日志不放在同一目录。
- 删除数据、终止进程、探针占用、API权限及版本兼容先明确契约，再实施。

板侧主机可见契约当前仍位于来源仓库被忽略的`Docs/`，尚未入库；后续实施前需补齐可追溯契约，这不表示板端实现已迁入本仓。

服务端SemVer拟以`server/VERSION`为唯一来源，统一脚本更新，`/status`读取同源并配套CHANGELOG；目前尚未创建这些入口。服务端、工具和helper产品版本各自独立；`contractVersion`与日志`sv`是后续接口/数据版本，不能冒充当前已存在的契约。参考helper的VERSION与版本脚本是设计依据，不继承其版本号。

## 验证与待验收

本仓尚未引入统一Harness。来源项目的离线/硬件通过不自动成为本仓结果；分别记录本仓离线验证、上下游一致性和硬件验收。

本仓服务尚未部署。2026-10-20使用client隔离副本、Windows J-Link 9.42与robocon-r1-debug的SN20250010/STM32G474VE实测：VS Code前置任务就绪后取消调试，连续三次留下Python/GDB Server及19011连接；启动参数同时提前停核。修复后未接入GDB的等待上限为30秒，等待阶段不主动停核，三次取消均退出且SDK重连确认MCU运行。正常源码调试继续有效；运行中的窗口崩溃三轮（旧版一轮、修复版两轮）均释放本次调试进程。19项客户端离线测试通过，其中真实子进程覆盖未接入超时回收与已接入不误超时。不能据此认定此前需重启主机的历史故障唯一原因；服务端进程与日志尚未取得。原始证据位于相邻embedded_helper的test-results/c07-c05-20261020。r1内存/文件系统开销及磁盘空间待实测。部署、服务启动、探针/烧录/复位操作按具体任务授权，不因本文列出命令而执行。待验收应使用明确版本的最终包、真实GUI/服务、设备和可追溯日志。
