import {connectionStatus} from './connection_status.js';
export function mount(root,{info,cache}){
 root.innerHTML=`<div class="connection-heading"><div class="page-heading"><h2>仪器连接</h2><p class="muted">连接设备后，进入测量初始化。</p></div><img class="home-brand" src="brand/iop-apc.png" width="520" height="130" alt="中国科学院物理研究所与应用物理中心标识"></div>
 <div id="connectionToolsSlot"></div><div class="connection-cards">
 <article class="card connection-card"><div class="connection-card-title"><h3>Red Pitaya</h3><span id="rpLamp" class="connection-lamp" aria-hidden="true"></span></div><strong id="rpConnectionStatus" role="status"></strong><p id="rpConnectionAddress" class="muted"></p><small id="rpChecked"></small></article>
 <article class="card connection-card"><div class="connection-card-title"><h3>微源激光器</h3><span id="laserLamp" class="connection-lamp" aria-hidden="true"></span></div><strong id="laserConnectionStatus" role="status"></strong><p class="muted">通过 RP 的 TX / RX 串口通信</p><small id="laserChecked"></small><p id="laserConnectionError" class="error"></p></article>
 </div><section id="connectionFailure" class="card" hidden aria-live="polite"><h3>连接检查未通过</h3><p id="failureSummary"></p><p id="failureBoard"></p><ul id="failureAdvice"></ul><details><summary>网络与服务诊断详情</summary><pre id="failureDetails" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></details></section><p class="muted">连接并启动：进入调试模式，依次开启 TEC 温控和 LD 电流输出。</p>
 <p id="rfChainSummary" class="muted"></p><details><summary>输入量程配置与跳线核对</summary><p id="inputRangeSummary"></p><p class="muted">这里显示 config.json 的用户配置，不是跳线自动检测结果。请按 RP 的实际跳线核对；软件不切换硬件量程，当前电压沿用 PyRPL 原始标度，未进行 HV 端口电压换算。</p></details><a class="next-step" href="#initialize">进入测量初始化 →</a>
 <details><summary>连接说明与状态灯含义</summary><p class="muted">填写新 RP 的标签名称；首次联网失败时，用 USB 数据线连接 RP 的 CON 口。</p><p class="muted">每分钟只读检查一次；采集、锁定或设备操作忙时延后。绿色：最近检查正常 · 红色：检查失败 · 黄色：待检查或结果过期 · 灰色：尚未连接。激光器通信正常不代表 TEC 或 LD 输出已开启。</p>
 <p class="muted">温度、电流沿用已读回且在允许范围内的设定；未满足范围时使用 35 ℃ / 260 mA。进入“测量初始化”调节温度、电流并锁定模式。</p></details>`;
 const $=id=>root.querySelector('#'+id);
 function update(){
  for(const prefix of ['rp','laser']){
   const current=connectionStatus(info,cache,prefix);
   $(prefix+'Lamp').dataset.state=current.state;
   $(prefix+'ConnectionStatus').textContent=current.label+(info.simulated?'（模拟）':'');
   $(prefix+'Checked').textContent=current.stamp;
   $(prefix+'ConnectionStatus').title=current.detail;
  }
  $('rpConnectionAddress').textContent=info.host+(info.rp_address?' · '+info.rp_address:'');
  const rf=info.rf_chain, correction=info.rf_correction_expected;
  $('inputRangeSummary').textContent=`IN1：${info.input_ranges?.in1||'待核对'} · IN2：${info.input_ranges?.in2||'待核对'}（用户配置）`;
  $('rfChainSummary').textContent=rf&&correction?`IN2 频谱链路 · Bias-T ${rf.bias_tee_enabled?'已使用':'未使用'} · 放大器 ${rf.amplifier_enabled?`${rf.amplifier_gain_db??23} dB`:'未使用'} · 净增益 ${correction.external_gain_db.toFixed(2)} dB · ${info.rf_correction_readback?'PyRPL 已核对':'连接后同步'}`:'';
  const laser=connectionStatus(info,cache,'laser');
  $('laserConnectionError').textContent=laser.detail;
  $('laserConnectionError').className=laser.state==='error'?'error':'muted';
  const rp=connectionStatus(info,cache,'rp');
  const failed=!cache.checkingConnections&&(rp.state==='error'||laser.state==='error'||(cache.connectionError&&!info.connected));
  $('connectionFailure').hidden=!failed;
  if(failed){
   const report=info.connection_diagnostics||{};
   $('failureSummary').textContent=report.summary||rp.detail||laser.detail||cache.connectionError||'请重新检查连接';
   const board=report.board;
   $('failureBoard').textContent=board?`RP ${(board.addresses||[]).join('、')||'无 IPv4 地址'} · ${board.speed>0?board.speed+' Mbps':'速率未确认'} · ${board.carrier==='1'?'物理链路正常':'无物理链路'}`:'';
   $('failureAdvice').replaceChildren(...(report.advice||['确认供电和接线后重试连接；保持 CON 数据线连接可获取板端信息。']).map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
   const lines=(report.interfaces||[]).map(row=>`${row.name}：${row.address}/${row.prefix} · ${row.dhcp?'自动获取':'固定 IP'} · ${row.state} · ${row.rp_same_subnet?'与 RP 同网段':'与 RP 网段不匹配或尚未确认'}`);
   for(const check of report.checks||[])lines.push(`${check.interface} / ${check.source} → ${check.target}：MAC ${check.mac_matches?'匹配':'未匹配'}，SSH ${check.ssh_reachable?'可达':'不可达'}`);
   if(report.detail)lines.push(report.detail);
   if(report.local_error)lines.push(report.local_error);
   $('failureDetails').textContent=lines.join('\n')||rp.detail||laser.detail||'未取得更多诊断信息';
  }
 }
 window.addEventListener('connection-state',update);update();
 return ()=>window.removeEventListener('connection-state',update);
}
