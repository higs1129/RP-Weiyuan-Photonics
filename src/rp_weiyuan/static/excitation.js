// Output is enabled only by an explicit click, never by page entry or live start.
export function mountExcitation(root,{api,cache,status,info},view){
 root.innerHTML=`<details class="excitation"><summary>输出激励 · ASG1 → OUT1（可选）</summary>
 <div class="fields"><label>输出模式<select id="exMode"><option value="burst">单次 burst</option><option value="periodic_burst">周期 burst</option><option value="continuous">连续波</option></select></label>
 <label>波形<select id="exWave"><option value="sin">正弦波</option><option value="square">方波（50%）</option><option value="triangle">三角波</option><option value="sawtooth">上升锯齿波</option><option value="custom">自定义波表（JSON）</option></select></label>
 <label>包内波形频率 / Hz<input id="exFreq" type="number" min="1" max="1000000" step="any" value="1000" required></label>
 <label>峰值幅度 / V<input id="exAmp" type="number" min="0.0002" max="1" step="any" value="0.1" required></label>
 <label>偏置 / V<input id="exOffset" type="number" min="-1" max="1" step="any" value="0" required></label>
 <label id="exCyclesLabel">每包周期数<input id="exCycles" type="number" min="1" max="100000" step="1" value="5" required></label>
 <label id="exPeriodLabel" hidden>整包重复周期 / s<input id="exPeriod" type="number" min="0.000002" max="3600" step="any" value="0.1" required><small>相邻两包起点间隔，须大于每包周期数 ÷ 波形频率</small></label>
 <label id="exFileLabel" hidden>单周期归一化波表<input id="exFile" type="file" accept=".json,application/json"><small>2–16384 个 [-1,1] 数值，周期线性插值到 16384 点</small></label></div>
 <label id="exObserveLabel"><input type="checkbox" id="exObserve">发送时同步采集一帧（可选，先等待触发）</label>
 <label id="exAutoLabel"><input type="checkbox" id="exAuto" checked>按 burst 自动匹配采集时长（观察较慢响应时可取消并手动加长）</label>
 <p id="exPlan" class="muted">burst 采集时长按频率和每包周期数自动匹配；触发前后留有余量。</p>
 <div class="toolbar"><button id="exStart" class="primary">发出 burst</button><button id="exStop" disabled>停止激励</button><span id="exState" role="status">未开启输出</span></div>
 <p class="muted">激励与观察独立控制：需要观察响应时，选择下方 ASG1 内部同步触发并运行采集。单次 burst 每点击一次发一包；周期 burst 持续自动发包，点停止结束。同步观察按触发刷新；自由采集可看多包变化，均不保证无间断记录每一包。幅度为 PyRPL 峰值（Vpp = 2 × 幅度），未补偿外部负载。离开或隐藏页面停止激励；丢失心跳后约 10 秒停止连续输出。</p></details>`;
 const $=id=>root.querySelector('#'+id);
 let disposed=false,token=null,busy=false,heartbeat=null,samples=null;
 const fields=['exMode','exWave','exFreq','exAmp','exOffset','exCycles','exPeriod'];
 for(const id of fields)if(cache.excitation?.[id]!==undefined)$(id).value=cache.excitation[id];
 $('exAuto').checked=cache.burstAutoDuration!==false;
 let planTicket=0;
 async function plan(){
  const ticket=++planTicket;
  if($('exMode').value==='continuous'||!$('exAuto').checked){$('exPlan').textContent='使用采集设置中的手动时长';return null;}
  const result=await api('excitation/plan',{frequency:Number($('exFreq').value),cycles:Number($('exCycles').value)},{quiet:true});
  if(disposed||ticket!==planTicket)return null;
  $('exPlan').textContent=`自动采集 ${(result.duration*1e6).toPrecision(6)} μs · ${(result.sample_rate_hz/1e6).toPrecision(5)} MSa/s · 每周期 ${result.samples_per_cycle.toFixed(1)} 点${result.warning?' · '+result.warning:''}`;
  return result;
 }
 view.registerPlan(plan);
 function update(){
  $('exCyclesLabel').hidden=$('exMode').value==='continuous';$('exPeriodLabel').hidden=$('exMode').value!=='periodic_burst';$('exFileLabel').hidden=$('exWave').value!=='custom';
  $('exObserveLabel').hidden=$('exMode').value!=='burst';
  $('exAutoLabel').hidden=$('exMode').value==='continuous';
  $('exStart').textContent=$('exMode').value==='burst'?($('exObserve').checked?'发送 burst 并同步采集':'发出 burst'):$('exMode').value==='periodic_burst'?'开始周期 burst':'开启连续激励';
  $('exStart').disabled=busy||Boolean(token);$('exStop').disabled=!token;
  for(const id of [...fields,'exFile','exObserve','exAuto'])$(id).disabled=busy||Boolean(token);
 }
 for(const id of fields)$(id).onchange=()=>{cache.excitation=Object.fromEntries(fields.map(k=>[k,$(k).value]));update();plan().catch(e=>{$('exPlan').textContent=e.message;});};
 $('exObserve').onchange=update;
 $('exAuto').onchange=()=>{cache.burstAutoDuration=$('exAuto').checked;plan().catch(e=>{$('exPlan').textContent=e.message;});};
 $('exFile').onchange=async()=>{
  samples=null;
  try{const file=$('exFile').files[0];if(!file)return;if(file.size>400000)throw new Error('波表文件过大');
   const values=JSON.parse(await file.text());
   if(!Array.isArray(values)||values.length<2||values.length>16384||values.some(x=>typeof x!=='number'||!Number.isFinite(x)||Math.abs(x)>1))throw new Error('需要 2–16384 个 [-1,1] 数值组成的 JSON 数组');
   samples=values;$('exState').textContent=`已读取 ${values.length} 点波表；尚未输出`;
  }catch(e){$('exState').textContent=e.message;}
 };
 function text(value){if(!disposed)$('exState').textContent=value;}
 async function stop(){
  clearInterval(heartbeat);const id=token;if(!id)return;
  try{await api('excitation/stop',{run_id:id},{quiet:true});if(token===id)token=null;text('激励已停止');}
  catch(e){text('未确认输出关闭：'+e.message);status('未确认激励关闭：'+e.message,true);}
  finally{if(!disposed)update();}
 }
 $('exStop').onclick=stop;
 $('exStart').onclick=async()=>{
  if(busy||token||disposed)return;
  if(!info.connected||!info.excitation_supported){
   const message=!info.connected?'请先连接 RP；尚未发送激励。':'设备后台仍是旧版，尚未发送激励。请暂停采集、停止守护，然后在“仪器连接”点击“重启 RP 后台”（不是关闭网页后重开）。';
   text(message);status(message,true);return;
  }
  if($('exMode').value==='periodic_burst'&&!info.periodic_burst_supported){text('当前后台不支持周期 burst，请停止采集和守护后重启 RP 后台');return;}
  for(const id of fields)if(!$(id).closest('label').hidden&&!$(id).reportValidity())return;
  const config={mode:$('exMode').value,waveform:$('exWave').value,frequency:Number($('exFreq').value),amplitude:Number($('exAmp').value),offset:Number($('exOffset').value),cycles:Number($('exCycles').value),burst_period:Number($('exPeriod').value),duration:view.duration(),observe:$('exMode').value==='burst'&&$('exObserve').checked};
  if(Math.abs(config.offset)+config.amplitude>1){text('|偏置| + 峰值幅度不能超过 1 V');return;}
  if(config.mode==='periodic_burst'&&config.burst_period-config.cycles/config.frequency<1e-6){text('整包重复周期须大于包内时长，并至少留出 1 μs 间隔');return;}
  if(config.waveform==='custom'){if(!samples){text('请先选择有效波表文件');return;}config.samples=samples;}
  const id=crypto.randomUUID().replaceAll('-','');token=id;busy=true;update();text(config.observe?'正在暂停旧采集并准备同步采集…':'正在准备激励…');
  try{
   const capturePlan=await plan();
   if(config.mode!=='continuous'&&$('exAuto').checked){
    if(!capturePlan)throw new Error('激励参数已变化，请重试');
    config.auto_duration=true;config.duration=capturePlan.duration;
   }
   if(config.observe){await view.halt();view.setDuration(config.duration);}
   else if(capturePlan)await view.prepareBurst(capturePlan,config.mode==='burst');
   if(disposed||token!==id||document.hidden)return;
   // Heartbeat also keeps a deliberately cancelled/expired run from restarting.
   const result=await api('excitation/run',{run_id:id,settings:config},{quiet:true});
   if(disposed||token!==id||document.hidden){await api('excitation/stop',{run_id:id},{quiet:true});return;}
   if(result.capture){token=null;view.show(result);text('burst 完成 · 输出已关闭；t=0 为内部事件，未校准 OUT1 起点');}
   else{
    text(`${config.mode==='burst'?'已发出 burst':config.mode==='periodic_burst'?'周期 burst 输出中':'连续输出中'} · 实际频率 ${Number(result.actual.frequency).toPrecision(6)} Hz${config.mode==='periodic_burst'?` · 配置重复周期 ${Number(result.actual.nominal_burst_period).toPrecision(6)} s`:''}`);
    heartbeat=setInterval(async()=>{try{const state=await api('excitation/keepalive',{run_id:id},{quiet:true});if(!state.active&&token===id){clearInterval(heartbeat);token=null;text('burst 已结束 · 输出已关闭');if(!disposed)update();}}catch(e){text(e.message);stop();}},config.mode==='burst'?300:2000);
   }
  }catch(e){await stop();text(e.message);}
  finally{busy=false;if(!disposed)update();}
 };
 const controller=new AbortController();
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();},{signal:controller.signal});
 window.addEventListener('pagehide',()=>{if(token)fetch('/api/excitation/stop',{method:'POST',headers:{'Content-Type':'application/json','X-Instrument-Console':'1'},body:JSON.stringify({run_id:token}),keepalive:true}).catch(()=>{});},{signal:controller.signal});
 update();
 return ()=>{disposed=true;controller.abort();clearInterval(heartbeat);const pending=stop();cache.acquisitionHandoff=Promise.all([cache.acquisitionHandoff,pending]);};
}
