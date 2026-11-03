// Discovery never starts instruments. Route repair needs a fresh server-side plan + UAC.
export function mount(root,{api,info,status}){
 root.innerHTML=`<details id="networkPanel"><summary>查找 RP 与网络路径诊断（只读）</summary>
 <p class="muted">按上方 RP 标签名称，在已连接的物理网卡中查找；必要时通过 CON 读取。不会启动激光器或修改网络。</p>
 <button id="findRp">查找这台 RP</button><p id="discoverySummary" role="status"></p>
 <pre id="discoveryEvidence" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre>
 <div id="routeOptions" hidden><label>RP 地址 <select id="routeTarget"></select></label>
 <label>接 RP 的物理网卡 <select id="routeInterface"></select></label>
 <button id="previewRoute">预览临时路径修复</button>
 <p class="muted">仅支持电脑和 RP 均有 169.254 地址的情况。请按实际接线选网卡；其他网段先核对 DHCP 或固定 IP 配置。</p></div>
 <div id="routePreview" hidden><p id="routeDescription"></p><button id="applyRoute">确认修复（Windows 管理员授权）</button><button id="cancelRoute">取消</button></div>
 <p id="networkResult" role="status"></p></details>`;
 const $=id=>root.querySelector('#'+id);
 let report=info.network_discovery,plan=null,pending=false,disposed=false,autoOpened=false;
 function dropPlan(){plan=null;$('routePreview').hidden=true;}
 function option(text,value){const node=document.createElement('option');node.textContent=text;node.value=value;return node;}
 function display(){
  $('findRp').disabled=pending||info.connected;
  if(!report)return;
  $('discoverySummary').textContent=report.summary;
  const lines=[];
  for(const candidate of report.candidates||[])lines.push(`${candidate.address} · 来源：${candidate.sources.join('、')}`);
  for(const check of report.checks||[])lines.push(`${check.interface}（${check.source}）→ ${check.target}：${check.reason} · MAC ${check.mac_matches?'匹配':'未确认'} · SSH ${check.ssh_reachable?'可达':'未通过'} · 系统路由网卡 #${check.route_index??'未知'}`);
  for(const row of report.interfaces||[])lines.push(`${row.name} #${row.index}：${row.address}/${row.prefix} · ${row.physical?'物理网卡':'虚拟/隧道网卡'} · ${row.state}`);
  if(report.console_error)lines.push('CON：'+report.console_error);
  for(const port of report.console_ports||[])lines.push(`${port.port}：${port.description} · ${port.console_candidate?'CON 候选':'其他串口'}`);
  lines.push(...(report.advice||[]),...(report.errors||[]));
  $('discoveryEvidence').textContent=lines.join('\n');
  const targets=(report.candidates||[]).filter(c=>c.address.startsWith('169.254.'));
  const interfaces=(report.interfaces||[]).filter(r=>r.physical&&r.state==='Connected'&&r.address.startsWith('169.254.'));
  $('routeOptions').hidden=report.status==='ready'||!targets.length||!interfaces.length||info.connected;
  $('routeTarget').replaceChildren(option('请选择 RP 地址',''),...targets.map(c=>option(c.address,c.address)));
  $('routeInterface').replaceChildren(option('请选择接 RP 的网卡',''),...interfaces.map(r=>option(`${r.name} · ${r.address}/${r.prefix}`,r.index)));
 }
 async function run(work){
  if(pending)return;pending=true;
  for(const button of root.querySelectorAll('button'))button.disabled=true;
  try{await work();}catch(e){if(!disposed){$('networkResult').textContent=e.message;status(e.message,true);}}
  finally{pending=false;if(!disposed){for(const button of root.querySelectorAll('button'))button.disabled=false;$('findRp').disabled=info.connected;}}
 }
 $('findRp').onclick=()=>run(async()=>{
  dropPlan();$('networkResult').textContent='正在按网卡查找并验证；CON 后备检查可能需要稍等…';
  const result=await api('network/discover',{host:document.querySelector('#host').value.trim()},{quiet:true});
  if(disposed)return;
  report=result.diagnostics;info.network_discovery=report;display();
  $('networkResult').textContent=report.status==='ready'?'已确认通信路径。点击“连接并启动”才会启动仪器。':'已完成只读检查；请根据上述路径与 CON 结果处理。';
 });
 $('previewRoute').onclick=()=>run(async()=>{
  dropPlan();
  if(!$('routeTarget').value||!$('routeInterface').value)throw new Error('请先选择 RP 地址和实际接线网卡');
  const result=await api('network/plan',{target:$('routeTarget').value,interface_index:Number($('routeInterface').value)},{quiet:true});
  if(disposed)return;plan=result;$('routeDescription').textContent=result.plan.summary;$('routePreview').hidden=false;
 });
 $('applyRoute').onclick=()=>run(async()=>{
  if(!plan)return;const id=plan.plan_id;dropPlan();
  $('networkResult').textContent='请在 Windows 管理员提示中确认；完成后核验 RP 身份与 SSH…';
  const result=await api('network/apply',{plan_id:id},{quiet:true});
  if(disposed)return;
  $('networkResult').textContent=`${result.address} 经 ${result.interface} 已通过身份与 SSH 验证。可点击“连接并启动”；临时路由在电脑重启后失效。`;
  $('routeOptions').hidden=true;
  info.network_discovery=null;
 });
 $('cancelRoute').onclick=dropPlan;
 $('routeTarget').onchange=$('routeInterface').onchange=dropPlan;
 function update(){
  $('findRp').disabled=pending||info.connected;
  if(info.connected){dropPlan();$('routeOptions').hidden=true;}
  if(info.connection_diagnostics&&!info.connected&&!autoOpened){$('networkPanel').open=true;autoOpened=true;}
 }
 window.addEventListener('connection-state',update);display();update();
 return ()=>{disposed=true;window.removeEventListener('connection-state',update);};
}
