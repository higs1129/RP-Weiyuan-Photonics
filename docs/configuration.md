# 配置与设备说明

安装、更新和回退以项目根目录 README.md 为准。配置保存在根目录 config.json，不提交 Git。

## 配置 JSON

```json
{
  "rp_host": "RP-f0fb33",
  "input_ranges": {"in1": "HV", "in2": "LV"},
  "rf_chain": {
    "input": "in2",
    "bias_tee_enabled": true,
    "bias_tee_insertion_loss_db": 0,
    "amplifier_enabled": true,
    "amplifier_gain_db": 23,
    "highz_correction_db": 6.020599913279624,
    "load_ohm": 50
  }
}
```

以上示例表示实际接了 Bias-T 和 23 dB 放大器。随包默认两者均为 false，避免在未确认接线时误扣增益；将对应字段改为 true 即启用。23 是 dB，不是 23 倍线性增益。JSON 使用 true/false，不加引号，不写注释。

| 字段 | 作用 |
|---|---|
| rp_host | RP 名称或 IPv4；用于发现、板卡身份核对及 PyRPL 连接 |
| input_ranges.in1 / in2 | 实际跳线量程，填写 `HV` / `LV`，不确定时填 `null`；用户本次确认 IN1 HV、IN2 LV |
| rf_chain.input | 当前固定 IN2，须为 `in2`；锁定探测仍为 IN1 |
| bias_tee_enabled | 记录物理接线；Bias-T 是外部器件，没有 RP 软件开关 |
| bias_tee_insertion_loss_db | Bias-T 已知插入损耗，默认 0（未标定，不假定损耗） |
| amplifier_enabled | 是否在 IN2 信号链使用放大器 |
| amplifier_gain_db | 放大器功率增益 dB，默认 23；仅启用时生效 |
| highz_correction_db | 保留现有高阻到匹配负载校正 6.0206 dB；按真实端接选择，已匹配且不需要此校正时设 0 |
| load_ohm | 功率换算参考负载，默认 50 Ω，不改变 RP 的实际硬件阻抗 |
| rp_console_port | 默认 null 自动查找 CON；多个串口时可填 `COM5` 等 |
| uart_device | 默认 null 自动选择 RP UART；仅清楚实际接线时指定 RP 上的设备路径 |
| uart_url | 默认 null，通过 RP 自动准备转发服务 |
| pyrpl_python | 完整包保持 null，由安装器设置正确的运行环境 |
| installation.python_path | 默认 null 自动检测；可指定 Python 3.10 x64 的 python.exe，不接受目录或错误版本 |
| installation.allow_downloads | true 允许补下载缺失的官方资源；false 完全禁止补下载 |

修改 JSON 后关闭并重新打开软件，在暂停采集、退出锁定守护后连接设备。不要在另一窗口仍控制相同 RP 时重复连接。连接页会显示实际配置与同步结果。

净外部增益 = 启用的放大器增益 − 启用的 Bias-T 插入损耗。

频谱功率显示 = 原始电压平方换算的功率 − 高阻校正 − 净外部增益。

这些参数写入同一个 PyRPL Spectrum Analyzer 的 `external_gain_db`、高阻校正与负载设置，网页与 PyRPL 的 dBm / dBm/Hz 使用同一换算。连接时核对读回；采集前检查，连续采集还核对每帧携带的校正参数，若被其他窗口改动则停止并提示。完整频谱导出保留实际校正参数及 rf_chain。原始电压、V²、示波器通道、PID、ASG、锁点和激光器温度电流不随这几个 RF 字段改变。此配置不代表放大器频响标定，也不代表避免过载的自动量程；宽带增益不平坦时需要另做频率相关标定。

量程配置是用户对实际跳线的记录，不是硬件自动检测，也不会通过软件切换跳线。安装和启动校验取值；连接页的“输入量程配置与跳线核对”显示两通道配置，完整帧导出携带 `input_ranges`、`input_range_source` 和 `voltage_basis`。HV 通道观察时提示电压仍为 PyRPL 原始标度；本版没有增加 HV 的实际端口电压换算，锁点、PID 和原始数组不随该字段改变。若将 IN2 改为 HV，频谱电压和功率也没有自动加入对应的衰减补偿，不能据此直接当作端口绝对功率。硬件调整后应更新配置并重新启动。参见 [Red Pitaya 官方跳线量程说明](https://redpitaya.readthedocs.io/en/latest/appsFeatures/applications/oscSigGen/osc.html)。

## 新 RP / 新电脑

- 网络使用同一局域网。名称解析、MAC 搜索及之前的百兆持久化恢复代码均已打包；网络不通时仍可能需要 CON 数据线首次恢复。软件不能补救电源、网线、SD 系统或不匹配的板卡硬件问题。
- 连接成功时不展示网络诊断；失败后在仪器连接页显示原因、CON 已读到的 RP 实际 IP/速率、可见网卡的地址/掩码/DHCP 模式及核对建议，详细信息默认折叠。有线、Wi-Fi、VPN 同时存在时按本机源地址分别检查匹配网段的路径。不会自动改电脑 IP、网关或 DNS；同网段和 TCP 可达也不等于板卡身份已验证。
- 同一 RP 换电脑时，若本机自动生成的 UART token 不匹配，显式连接流程通过已认证 SSH 读取本项目托管服务的凭据，并验证正在运行的 PID、MAC 和认证端点后仅更新本机 token。不重启该服务、不覆盖 RP 凭据，配对本身不发激光器串口指令。明确填写的 `uart_token` 或环境变量 `WEIYUAN_UART_TOKEN` 不自动覆盖；非本项目托管、身份不符或不支持认证核对的服务会报错并保留原状。
- 如果连接 CON 后没有串口，双击 `install-con-driver.cmd`，接受 Windows 驱动安装的 UAC 提示。该入口仅安装包内 FTDI 官方签名驱动；正常网络通信不依赖 CON 一直插着。驱动来源见 dependencies/PROVENANCE.json，原始文件及目录完整保留。
- 微源串口的转发服务和启动设置由显式连接流程在 RP 上检查并准备。PC 的软件包与 RP SD 卡上的系统、网络设置是两层内容，包不是 SD 系统镜像。新板仍需兼容系统、正确 TX/RX 接线和 SSH 可用。
- 支持当前项目已验证的 RP/PyRPL 硬件组合。不同 RP 型号、固件或输入量程不能仅改主机名就保证兼容。
