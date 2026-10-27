# 维护范围与版本更新

## 哪些 Issues 在这里修

页面、坐标轴交互、激光器操作界面、连续观察及守护流程属于 `src/rp_weiyuan/`。在本仓库修复并验证，再提交应用版本。关闭运行中的平台，拉取代码，运行 `update.cmd` 即可应用，不要求每次制作安装包。

RP 网络发现、百兆恢复、底层寄存器/串口协议和通用分析属于公共库。公共库唯一可编辑源码位于 `D:/measurement-workbench/workspace/a221_workbench/`；按其 `docs/CHANGE_REQUEST.md` 记录复现、接口及影响，完成相关验证后再交付新版 wheel。不要修改本机 site-packages、解包旧 wheel 后打补丁，或把原工作台路径加入 PYTHONPATH。

## 固定公共依赖

当前使用 `a221-workbench==0.2.34`，wheel SHA256 为：

```
a5e748f4ed84a654341ca5084f2d4f46454452f2906da9b8d8aeca508aa476bc
```

配套原始源码归档位于 `dependencies/upstream/a221-workbench-0.2.34-source.zip`；来源提交记录在 `dependencies/PROVENANCE.json`。本产品只使用自己的 `rp_weiyuan` 界面和已安装的公共驱动。

升级公共库时，同时调整 `pyproject.toml` 的精确依赖、`dependencies/requirements.lock`、对应 wheel、`dependencies/manifest.json` 中的包版本与文件 SHA256，以及来源记录。删除旧 wheel，避免离线目录中混入多个版本。先在独立验证目录确认安装、关键功能与数值口径，再提交。

0.3.8 起，运行环境身份仅取包版本和 wheel 校验值，源码归档、许可、驱动资源和下载地址变化不再触发重建。普通应用更新复用环境；仅 a221-workbench 更新时，通过 pip --no-index --no-deps 替换该包。其他基础包变化、首次安装和 repair 才创建新环境。安装资源校验仍覆盖整个清单。

本机 wheel-cache 只保留当前公共驱动的原始 wheel，使用 SHA256 验证，供下一次更新失败时恢复安装。更新期间临时保留新旧包，通过 pip 安装原始 wheel，不修改驱动源码。旧安装若缺少恢复用的旧 wheel，则做一次新环境迁移。更新前写 pending-update.json；替换驱动和离线验证成功后才切换版本并移除事务文件。失败立即恢复，进程意外中断则下次运行先恢复；验证成功后不保留前一版本，不提供 rollback 入口。

成功验证后，仅保留 current 引用的环境、快照和 wheel 缓存，并移除旧安装的 previous.json。只清理安装目录下匹配命名规则的直接子目录，跳过符号链接、junction 和仍被占用的文件。配置、实验数据、日志、凭据不属于清理范围；不操作真实设备。新版功能问题通过 GitHub Issues 跟踪并发布修复。

运行快照在应用数据目录，是安装副本，不是另一份需要手工维护的源码。

## GitHub 内容

仓库跟踪源码、配置模板、入口、文档及固定离线资源。个人 `config.json`、环境、数据、缓存、日志及 UART 凭据不提交。根目录 `.gitattributes` 禁止转换 `dependencies/` 内固定资源的换行，防止破坏签名文件和校验值。

离线依赖资源随 [higs1129/RP-Weiyuan-Photonics](https://github.com/higs1129/RP-Weiyuan-Photonics) 仓库一起维护，因此完整 Git 克隆和同版本的 GitHub 源码 ZIP 都有安装所需资源。默认分支为 main；首个独立版本为 v0.3.0。发布 Release 时，GitHub 自动生成的 Source code (zip) 即包含受 Git 管理的全部离线资源，不必每次另造安装包；不加入个人配置、运行环境或 dist 构建副本。

## 本次迁移

应用版本为 0.3.0，来源工作台提交 `425b09974716733f908b84a2688a07795d772bff`。应用从 `weiyuan_console`、专用守护与扫频组合代码迁出；原工作台的公共设备、任务、通用微源锁定和其他测量流程保持。未改变模型、标定、电压标度、PID 参数或默认设备动作。

开发验证只使用离线数据、拦截后的浏览器 API 和未连接设备的本地 HTTP 服务；不自动执行真实测量。
