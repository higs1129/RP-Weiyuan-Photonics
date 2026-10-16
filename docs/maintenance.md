# 维护范围与版本更新

## 哪些 Issues 在这里修

页面、坐标轴交互、激光器操作界面、连续观察及守护流程属于 `src/rp_weiyuan/`。在本仓库修复并验证，再提交应用版本。关闭运行中的平台，拉取代码，运行 `update.cmd` 即可应用，不要求每次制作安装包。

RP 网络发现、百兆恢复、底层寄存器/串口协议和通用分析属于公共库。公共库唯一可编辑源码位于 `D:/measurement-workbench/workspace/a221_workbench/`；按其 `docs/CHANGE_REQUEST.md` 记录复现、接口及影响，完成相关验证后再交付新版 wheel。不要修改本机 site-packages、解包旧 wheel 后打补丁，或把原工作台路径加入 PYTHONPATH。

## 固定公共依赖

当前使用 `a221-workbench==0.2.24`，wheel SHA256 为：

```
681c63a14998f80f42f957590b1d11b91f058e3af10dc0397be5701d4f756c15
```

它来自已验证的 0.2.24 离线发布，配套原始源码归档位于 `dependencies/upstream/a221-workbench-0.2.24-source.zip`。该历史 wheel 和源码归档仍包含当时的旧界面；它们仅作不可变依赖和来源记录，本产品启动只导入自己的 `rp_weiyuan` 界面。

升级公共库时，同时调整 `pyproject.toml` 的精确依赖、`dependencies/requirements.lock`、对应 wheel、`dependencies/manifest.json` 中的包版本与文件 SHA256，以及来源记录。删除旧 wheel，避免离线目录中混入多个版本。先在独立验证目录确认安装、关键功能与数值口径，再提交。

普通应用更新只生成新的本机运行快照，依赖清单不变则复用 Python 环境。依赖升级或 `repair.cmd` 才创建新环境。验证失败不会更新 `current.json`。`rollback.cmd` 恢复前一个应用快照及匹配环境；配置和已写入硬件的设置不回退。

运行快照在应用数据目录，是安装副本，不是另一份需要手工维护的源码。

## GitHub 内容

仓库跟踪源码、配置模板、入口、文档及固定离线资源。个人 `config.json`、环境、数据、缓存、日志及 UART 凭据不提交。根目录 `.gitattributes` 禁止转换 `dependencies/` 内固定资源的换行，防止破坏签名文件和校验值。

本次离线依赖资源随仓库一起维护，因此完整 Git 克隆和同版本的 GitHub 源码 ZIP 都有安装所需资源。正式发布前需确认新账号和仓库位置；目前未创建远程仓库。后续 Release 可以附完整目录压缩包，但不应加入个人配置，也不需要把运行环境或 `dist/` 构建副本提交到源码仓库。

## 本次迁移

应用版本为 0.3.0，来源工作台提交 `425b09974716733f908b84a2688a07795d772bff`。应用从 `weiyuan_console`、专用守护与扫频组合代码迁出；原工作台的公共设备、任务、通用微源锁定和其他测量流程保持。未改变模型、标定、电压标度、PID 参数或默认设备动作。

开发验证只使用离线数据、拦截后的浏览器 API 和未连接设备的本地 HTTP 服务；不自动执行真实测量。
