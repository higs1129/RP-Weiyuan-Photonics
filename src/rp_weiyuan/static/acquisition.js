import {plot} from './plot.js';
import {axisControls} from './plot_axes.js';
import {mountExcitation} from './excitation.js';
export function mount(root,context,page){
 const {api,cache,info,status}=context,scope=page!=='frequency',kind=scope?'scope':'spectrum',initial=page==='initialize';
 const plotOptions={channel:initial?'ch1':'ch2',label:initial?'CH1 / IN1':'CH2 / IN2'};
 const queue=fn=>{const next=(cache.acquisitionHandoff||Promise.resolve()).catch(()=>{}).then(fn);cache.acquisitionHandoff=next;return next;};
 let startPending=false,manualPause=false,waitingForTrigger=false;
 let burstPlan=null;
 let disposed=false,runId=null,epoch=0,timer,sequence=0,shown=0,started=0,lastTime=null,active=false;
 root.innerHTML=`${initial?'':`<div class="page-heading"><h2>${scope?'时域观察':'频域观察'}</h2><p class="muted">${scope?'CH2 / IN2 · 电压随时间的变化':'IN2 · PyRPL 基带功率谱密度'}</p></div>`}<div class="card live-card">
 ${page==='time'?'<div id="excitationPanel"></div>':''}
 <div class="toolbar live-toolbar"><button id="run" class="primary">连续运行</button><button id="pause" disabled>暂停</button><button id="capture">单次采集</button><span id="liveState" role="status">未运行</span></div>
 ${page==='time'?'<div class="toolbar time-options"><label>采集触发<select id="timeTrigger"><option value="immediately">立刻 / 自由采集</option><option value="asg1">ASG1 内部同步</option></select></label><label><input type="checkbox" id="showSource">同时显示 ASG1 内部波形（CH1）</label><span class="muted">同步 t=0 未校准为 OUT1 物理起点</span></div>':''}
 <div class="toolbar frame-toolbar"><strong>${scope?'时域波形':'噪声频谱'}</strong><span id="rate">显示 — 帧/秒</span><span id="frameTime" class="timestamp">尚未采集</span><span id="age"></span></div>
 <div id="frameLock" class="frame-lock" role="status"></div>
 <p id="inputRangeNote" class="muted"></p>
 <div id="chart" class="empty">点击连续运行，查看实时变化</div>
 <p class="muted axis-hint">左键拖动缩放坐标轴 · Shift + 左键拖动平移</p>
 <div class="plot-options">
 <details id="plotAxes" class="axis-settings"></details>
 <details class="acquisition-settings"><summary>采集设置</summary><div class="fields">${scope?'<label>采集时长 / s<input id="duration" type="number" min="0.000001" max="8.589934592" step="any" value="0.04"></label>':'<label>Span / Hz<input id="span" type="number" min="1" value="100000"></label><label>平均次数<input id="average" type="number" min="1" max="100" step="1" value="1"></label>'}<label>刷新上限 / 帧每秒<input id="fps" type="number" min="0.5" max="15" step="0.5" value="8"></label></div></details>
 <details><summary>保存完整数据</summary><p class="muted">暂停后保存当前完整帧。自由连续显示保留峰谷；ASG1 同步及单次采集逐点显示，保存保留原始点数；此功能不做无间断长时间记录。</p><label>代码版本 / 源码快照<input id="provenance" class="wide" placeholder="填写本次代码版本依据"></label><p><button id="download" disabled>下载当前完整帧</button></p></details></div>
 <p class="muted" id="frameInfo">示波器与频谱仪共用 RP 采集资源；暂停后可修改设置。</p></div>`;
 const $=id=>root.querySelector('#'+id);
 const observedInput=initial?'in1':'in2';
 $('inputRangeNote').hidden=info.input_ranges?.[observedInput]!=='HV';
 $('inputRangeNote').textContent=`${observedInput.toUpperCase()}：HV（用户配置）· ${scope?'电压沿用 PyRPL 原始标度，未换算为 HV 端口电压':'电压及频谱功率尚未补偿 HV 输入衰减'}`;
 const axes=cache[page+'Axes']??={x:null,y:null};
 const axisUI=axisControls($('plotAxes'),$('chart'),axes,draw,{scope});
 $('provenance').value=info.source_version||'';
 cache[page+'Settings']??={};
 for(const el of root.querySelectorAll('.acquisition-settings input'))if(cache[page+'Settings'][el.id]!==undefined)el.value=cache[page+'Settings'][el.id];
 function state(text,error=false){$('liveState').textContent=text;$('liveState').className=error?'error':active?'live-indicator':'';}
 function buttons(running,pending=false){
  active=running;$('run').disabled=running||pending;$('pause').disabled=!running;$('capture').disabled=running||pending;
  root.querySelectorAll('.acquisition-settings input,.time-options input,.time-options select').forEach(el=>el.disabled=running||pending);
  $('download').disabled=running||!cache[page]||Boolean(cache[page].capture.preview);
 }
 function settings(){
  for(const el of root.querySelectorAll('.acquisition-settings input'))if(!el.value||!el.reportValidity())throw new Error('请检查采集参数');
  const val=id=>$(id).value;
  for(const el of root.querySelectorAll('.acquisition-settings input'))cache[page+'Settings'][el.id]=el.value;
  return scope?{duration:Number(val('duration')),...(page==='time'?{trigger_source:$('timeTrigger').value,show_source:$('showSource').checked}:{})}:{span:Number(val('span')),trace_average:Number(val('average'))};
 }
 function show(data){
  if(disposed||!data.capture)return;
  cache[page]={capture:data.capture,simulated:data.simulated,observed_input:initial?'in1':'in2'};
  const capture=data.capture,b=capture.bridge_result;lastTime=Date.parse(capture.captured_at);
  $('frameTime').textContent='数据时间 '+new Date(lastTime).toLocaleTimeString()+(data.simulated?' · 模拟':'');
  $('chart').className='';draw();
  $('frameInfo').textContent=(scope?`实际时长 ${b.duration} s · ${(b.n/b.duration/1e6).toPrecision(5)} MSa/s`:`实际 Span ${Number(b.span_hz).toPrecision(5)} Hz · RBW ${Number(b.rbw_hz).toPrecision(4)} Hz`)+` · 完整帧 ${b.n} 点`+(capture.preview?' · 显示保留峰谷':scope?' · 全分辨率显示（不抽点）':'');
  if(active){shown++;$('rate').textContent=`显示 ${(shown/Math.max((performance.now()-started)/1000,.1)).toFixed(1)} 帧/秒 · 采集 ${Number(data.acquisition_fps||0).toFixed(1)} 帧/秒`;}
  $('download').disabled=active||Boolean(capture.preview);
 }
 function draw(){
  if(cache[page]){
   const b=cache[page].capture.bridge_result;
   const both=page==='time'&&b.input1==='asg1';
   axisUI.update(plot($('chart'),cache[page].capture,{...plotOptions,...(both?{channel:null,label:'ASG1 内部（绿） · IN2（棕）'}:{}),axes,reference:initial?info.lock?.reference:null}));
  }
 }
 function lockState(){
  const s=info.lock,frame=cache[page]?.capture;
  const blocked=info.lockOffline||s?.state==='error'||(s?.active&&s.state!=='locked');
  const prior=frame?.lock_context&&frame.lock_context.epoch!==s?.epoch;
  $('frameLock').textContent=blocked?'锁定状态未确认 · 暂停接收测量帧，保留上次画面':prior?'上次画面 · 采集时的锁定状态与当前不同':s?.state==='locked'?'锁定中 · IN1 守护独立运行':'未锁定观察';
  $('frameLock').classList.toggle('warning',Boolean(blocked||prior));
  $('chart').classList.toggle('stale-frame',Boolean(blocked||prior));
 }
 async function release(id){if(id)await api('live/release-wait',{run_id:id},{quiet:true});}
 async function halt(){epoch++;clearTimeout(timer);const id=runId;runId=null;if(!disposed)buttons(false,true);await release(id);if(!disposed)buttons(false);}
 async function poll(ticket){
  try{
   const data=await api('live/latest',{run_id:runId,after:sequence},{quiet:true});
   if(disposed||ticket!==epoch)return;
   if(data.capture){sequence=data.sequence;show(data);}
   waitingForTrigger=Boolean(data.running&&data.waiting_for_trigger);
   if(waitingForTrigger)$('rate').textContent=`已接收 ${data.sequence} 帧 · 等待 ASG1 触发，保留当前画面`;
   lockState();
   if(data.running&&data.measurement_gate?.ready===false)state('等待重新锁定 · 暂停接收帧');
   else if(data.running)state(data.waiting_for_trigger?'● 连续运行 · 等待 ASG1 触发':'● 连续运行');
   if(data.error){
    const frozen=await api('live/pause',{run_id:runId},{quiet:true});
    if(disposed||ticket!==epoch)return;buttons(false);show(frozen);state('采集中断：'+data.error,true);return;
   }
   if(!data.running){buttons(false,data.stopping);state(data.stopping?'已暂停 · 等待当前帧结束':'已暂停');if(!data.stopping)return;}
   timer=setTimeout(()=>poll(ticket),100);
  }catch(e){if(disposed||ticket!==epoch)return;state('显示连接中断；后台采集状态未改变：'+e.message,true);timer=setTimeout(()=>poll(ticket),1500);}
 }
 function start(){
  if(startPending||active||disposed)return Promise.resolve();
  if(!info.connected){state('请先在仪器连接中连接 RP');return Promise.resolve();}
  startPending=true;manualPause=false;
  return queue(async()=>{
  if(disposed||manualPause)return;
  let config;try{if(burstPlan){const plan=await burstPlan();if(plan)setDuration(plan.duration);}config=settings();}catch(e){status(e.message,true);return;}
  const ticket=++epoch;buttons(false,true);state('正在启动…');
  try{
   const data=await api('live/start',{kind,view:page,settings:config,fps:Number($('fps').value)},{quiet:true});
   if(disposed||ticket!==epoch){await release(data.run_id);if(!disposed)buttons(false);return;}
   runId=data.run_id;sequence=0;shown=0;started=performance.now();buttons(true);state('● 连续运行');show(data);timer=setTimeout(()=>poll(ticket),100);
  }catch(e){if(!disposed){buttons(false);state(e.message,true);}}
  }).finally(()=>{startPending=false;});
 }
 $('run').onclick=()=>start();
 async function pause(){
  if(!runId)return;const ticket=++epoch;clearTimeout(timer);buttons(false,true);state('暂停中…');
  try{
   const data=await api('live/pause',{run_id:runId},{quiet:true});
   if(disposed||ticket!==epoch)return;
   sequence=data.sequence;show(data);buttons(false,data.stopping);state(data.stopping?'已暂停 · 等待当前帧结束':'已暂停');
   if(data.stopping)timer=setTimeout(()=>poll(ticket),150);
  }catch(e){if(!disposed){buttons(false);state(e.message,true);release(runId).catch(()=>{});runId=null;}}
 }
 $('pause').onclick=()=>{manualPause=true;return pause();};
 $('capture').onclick=async()=>{
  manualPause=true;let config;try{if(burstPlan){const plan=await burstPlan();if(plan)setDuration(plan.duration);}config=settings();}catch(e){status(e.message,true);return;}
  const ticket=++epoch;clearTimeout(timer);buttons(false,true);state('单次采集中…');
  try{const data=await api(kind+'/acquire',{view:page,settings:config},{quiet:true});if(disposed||ticket!==epoch)return;show(data);state('单次采集完成');}
  catch(e){if(!disposed)state(e.message,true);}finally{if(!disposed)buttons(false);}
 };
 $('download').onclick=()=>{
  const source=$('provenance').value.trim();if(!source){status('请填写代码版本或源码快照依据',true);return;}
  if(active||cache[page]?.capture.preview){status('请先暂停，以保存完整帧',true);return;}
  const blob=new Blob([JSON.stringify({...cache[page],provenance:{source_version:source}},null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=page+'-'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 };
 if(cache[page]){show(cache[page]);buttons(false);state('上次画面 · 已暂停');}
 const controller=new AbortController();
 // A folded laser panel changes chart width without a window resize.
 const resizeObserver=new ResizeObserver(draw);resizeObserver.observe($('chart'));
 window.addEventListener('lock-state',()=>{lockState();},{signal:controller.signal});
 window.addEventListener('measurement-transition',()=>{manualPause=true;epoch++;clearTimeout(timer);buttons(false,true);queue(halt).catch(e=>status(e.message,true));state('采集已暂停 · 正在切换锁定/扫频');},{signal:controller.signal});
 window.addEventListener('measurement-resume',()=>{queue(()=>{}).then(()=>{if(!disposed){manualPause=false;start();}});},{signal:controller.signal});
 window.addEventListener('connection-state',()=>{if(!manualPause&&!active)start();},{signal:controller.signal});
 const ageTimer=setInterval(()=>{if(lastTime!==null){const seconds=Math.max(0,(Date.now()-lastTime)/1000);$('age').textContent=`${seconds.toFixed(1)} 秒前`;$('age').className=active&&!waitingForTrigger&&seconds>2?'error':'';}},250);
 lockState();
 function setDuration(duration){if(Number($('duration').value)!==duration)axes.x=null;$('duration').value=duration;cache[page+'Settings'].duration=duration;}
 const cleanExcitation=page==='time'?mountExcitation($('excitationPanel'),context,{
  registerPlan:fn=>{burstPlan=fn;},
  setDuration,
  prepareBurst:async(plan,single)=>{
   const running=active;
   if(running&&Number($('duration').value)!==plan.duration){await queue(halt);setDuration(plan.duration);await start();}
   else setDuration(plan.duration);
   if(running&&!active)throw new Error('采集未能重新启动，尚未发送激励');
   if(running&&single&&$('timeTrigger').value==='asg1'){
    const deadline=performance.now()+8000;
    while(!disposed&&active&&performance.now()<deadline){
     const ready=await api('live/armed',{run_id:runId},{quiet:true});
     if(ready.armed&&ready.trigger_source==='asg1'&&Math.abs(ready.duration-plan.duration)<plan.duration*1e-6){await new Promise(r=>setTimeout(r,100));return;}
     await new Promise(r=>setTimeout(r,50));
    }
    throw new Error('未确认示波器已准备好同步触发，尚未发送 burst');
   }
  },
  halt:()=>{manualPause=true;epoch++;clearTimeout(timer);return queue(halt);},
  duration:()=>Number($('duration').value),
  show:data=>{show(data);buttons(false);state('burst 采集完成 · 输出已关闭');}
 }):()=>{};
 start();
 return ()=>{disposed=true;epoch++;clearTimeout(timer);clearInterval(ageTimer);controller.abort();resizeObserver.disconnect();axisUI.destroy();cleanExcitation();queue(halt).catch(e=>status('切换页面时未确认旧采集停止：'+e.message,true));};
}
