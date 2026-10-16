# RP*微源光子测控平台

独立的 Windows 测控应用，连接 Red Pitaya 与微源激光器。当前应用版本 **0.3.0**，公共设备库固定为 **a221-workbench 0.2.24**，PyRPL 固定为 **0.9.8.0**。名称中的 `*` 用于界面，文件夹使用 `RP-Weiyuan-Photonics`。

## 使用

1. 完整下载或复制本目录到 Windows 10 / 11 x64 电脑。
2. 双击 `setup.cmd`，完成独立环境的安装和离线验证。首次会从模板生成 `config.json`。
3. 修改 `config.json` 中的 RP 名称、IN1/IN2 实际跳线量程、Bias-T 与放大器参数。
4. 双击 `launch.cmd`。在页面点击“连接并启动”才会准备仪器，并按已有流程启动 TEC / LD；安装和打开页面本身不连接设备。

默认 IN1=HV、IN2=LV；放大器增益默认 23 dB，但放大器和 Bias-T 默认禁用，需按实际接线填写。量程为人工接线记录，未增加 HV 电压换算。详见 [配置与设备说明](docs/configuration.md)。

本目录含 Python 安装程序、37 个固定依赖包、CON 驱动与许可资料，可离线安装。已安装的 Python 3.10 x64 仅用于创建新环境，不覆盖它的包。缺失且有官方来源的资源允许按校验清单补下载；可在配置中关闭下载。

## 修改和更新

应用代码只在 `src/rp_weiyuan/` 修改。通过 Git 拉取更新后，关闭平台再运行 `update.cmd`，随后运行 `launch.cmd`；也可以直接重新运行 `launch.cmd`。启动器检查源码变化，验证新版本，成功后才切换。`update.cmd` 应用已经下载到本地的代码，本身不会执行 Git 拉取。

固定公共依赖没有变化时复用环境，不必重新打包安装包。个人 `config.json` 不被 Git 管理，更新不会覆盖它。若公共驱动需要改动，应在原工作台修复并发布新版库，然后在这里明确升级依赖；修改原工作台源码不会自动改变本程序。

| 入口 | 功能 |
|---|---|
| `diagnose.cmd` | 检查依赖、源码、Qt 和串口枚举，不联系仪器 |
| `repair.cmd` | 重建独立环境，验证成功才切换 |
| `rollback.cmd` | 恢复前一个验证成功的源码快照及对应环境，保留配置 |
| `install-con-driver.cmd` | 显式安装随附 CON 驱动，Windows 可能提示 UAC |
| `network-diagnose.cmd` | 用户主动运行的网络与 CON 只读诊断 |
| `pair-uart.cmd` | 用户主动运行的既有托管 UART 服务凭据配对 |

回退后 `launch.cmd` 保持回退版本；`update.cmd` 再次应用当前目录源码。回退软件不撤销设备上的设置。

## 目录与隔离

- `src/rp_weiyuan/`：界面、激光器操作组合、连续观察和守护锁定。
- `tools/`：安装、更新和诊断代码。
- `dependencies/`：固定 wheel、Python 安装程序、驱动、许可和来源；不在这里修改公共实现。
- `config.example.json`：可公开的配置模板；`config.json` 是自己电脑的配置。
- `docs/`：配置、维护、迁移与验证记录。

独立环境、运行快照、日志、数据、凭据位于 `%LOCALAPPDATA%\RP-Weiyuan-Photonics\standalone`。可用绝对路径环境变量 `RP_WEIYUAN_HOME` 指定专用目录。新项目不复用旧控制台的环境或运行缓存；需要迁移时只复制自己的配置，不复制虚拟环境。共享库只从本项目虚拟环境导入。

GitHub 仓库应收录本目录内受 Git 管理的源码、模板、文档及固定资源，排除个人配置和运行数据。Release 可发布同一版本的完整目录压缩包；用户获得的功能相同。尚未创建远程仓库或上传。
