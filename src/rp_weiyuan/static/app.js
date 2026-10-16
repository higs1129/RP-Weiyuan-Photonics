import {mount as connection} from './connection.js';
import {mount as acquisition} from './acquisition.js';
import {mount as initialization} from './initialization.js';
import {monitorConnections} from './connection_status.js';

const info=await fetch('/api/info').then(r=>r.json());
const message=document.querySelector('#message');
const connectionTools=document.querySelector('#connectionTools');
document.querySelector('#mode').textContent=info.simulated?'模拟设备 · 无实测数据':'真实设备';
document.querySelector('#host').value=info.host;
if(info.connected){document.querySelector('#connect').textContent='连接并启动';message.textContent='当前会话已连接 '+info.host;}
const busy=new Set();
const cache={};
let liveRequests=Promise.resolve();
function status(text,error=false){message.textContent=text;message.className=error?'error':'';}
async function api(action,body={},options={}){
 if(action.startsWith('live/')&&!options.queued){
  const pending=liveRequests.catch(()=>{}).then(()=>api(action,body,{...options,queued:true}));
  liveRequests=pending;return pending;
 }
 if(action.startsWith('excitation/')){
  const r=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Instrument-Console':'1'},body:JSON.stringify(body)});
  const data=await r.json();if(!r.ok||!data.ok)throw new Error(data.error||'激励操作失败');return data;
 }
 const lane=action==='stop'||['live/pause','live/release'].includes(action)?'stop':action.startsWith('laser/')?'laser':action.startsWith('live/')?'live':'rp';
 if(busy.has(lane))throw new Error('请等待当前操作完成');
 busy.add(lane);
 if(!options.quiet)status('正在执行…');
 try{
  const r=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Instrument-Console':'1'},body:JSON.stringify(body)});
  const data=await r.json();
  if(!r.ok||!data.ok)throw new Error(data.error||JSON.stringify(data));
  if(!options.quiet)status('操作完成 · '+new Date().toLocaleTimeString());
  return data;
 }catch(e){if(!options.quiet)status(e.message,true);throw e;}finally{busy.delete(lane);}
}
const context={api,info,cache,status,connectDevices:()=>connectDevices()};
async function refresh(){
 Object.assign(info,await fetch('/api/info').then(r=>r.json()));
 document.querySelector('#rpState').textContent='RP · '+(info.connected?'已连接'+(info.rp_address?' · '+info.rp_address:''):'未连接');
 document.querySelector('#rpState').title=info.bridge_url?'当前控制后台：'+info.bridge_url:'';
 document.querySelector('#laserState').textContent='激光器 · '+(info.laser_connected?'已读回':'未连接');
 document.querySelector('#laserState').title=info.laser_error||'';
 document.querySelector('#pyrpl').disabled=info.simulated;
 document.querySelector('#hidePyrpl').disabled=info.simulated;
 document.querySelector('#uartSetup').hidden=info.simulated||!['','#connection'].includes(location.hash);
 window.dispatchEvent(new Event('connection-state'));
}
await refresh();
async function connectDevices(restart=false){
 if(cache.checkingConnections)return;
 cache.checkingConnections=true;cache.connectionError=null;
 document.querySelector('#connect').disabled=true;
 document.querySelector('#restartRp').disabled=true;
 window.dispatchEvent(new Event('connection-state'));
 let polling=false;
 const progress=setInterval(async()=>{
  if(polling)return;polling=true;
  try{
   const response=await fetch('/api/connection/status',{signal:AbortSignal.timeout(3000)});
   if(response.ok){const step=await response.json();if(cache.checkingConnections)status(step.stage);}
  }catch{}finally{polling=false;}
 },1000);
 try{
 const host=document.querySelector('#host').value.trim();
 const result=await api(restart?'rp/restart':'connect',{host});
 document.querySelector('#connect').textContent='连接并启动';
 if(result.laser?.ok)cache.laser={status:result.laser.status,time:new Date().toLocaleTimeString()};
 const notes=[];
 if(result.setup?.restart?.ok)notes.push('失效 PyRPL 后台已自动重建，RP 输出已关闭；需要扫频时点击“恢复扫频”');
 if(result.setup?.network?.recovered)notes.push(result.setup.network.persistent?'已恢复百兆网络并保存开机设置':'已临时恢复百兆网络');
 if(result.setup?.network?.warning)notes.push(result.setup.network.warning);
 if(result.setup?.uart?.warning)notes.push(result.setup.uart.warning);
 if(result.setup?.uart?.persistent)notes.push('串口服务已设为开机启动');
 if(result.setup?.uart?.credential_synced)notes.push('已核验并同步 RP 现有串口凭据');
 if(restart){
  const forced=result.old?.forced_pids?.length?'旧后台未正常退出，已定向结束；':'';
  status(forced+'新 PyRPL 后台已就绪，RP 输出已确认关闭。需要扫频时点击“恢复扫频”。'+(notes.length?notes.join('；'):''));
 }else{
  status((result.laser?.ok?'RP 与激光器通信正常；已进入调试模式，TEC / LD 已开启':'RP 已连接；激光器通信或启动未完成：'+result.laser?.error)+(notes.length?'。'+notes.join('；'):''),!result.laser?.ok);
 }
}catch(e){cache.connectionError=e.message;}finally{
 clearInterval(progress);
 cache.checkingConnections=false;cache.connectionCheckedAt=new Date().toLocaleString();
 cache.connectionMonitorError=null;cache.connectionMonitorDeferred=null;
 document.querySelector('#connect').disabled=false;
 document.querySelector('#restartRp').disabled=false;
 try{await refresh();}catch(e){status('无法读取仪器台状态：'+e.message,true);}
 window.dispatchEvent(new Event('connection-state'));
}}
document.querySelector('#connect').onclick=()=>connectDevices();
document.querySelector('#restartRp').onclick=()=>connectDevices(true);
document.querySelector('#pyrpl').onclick=async()=>{try{
 await api('pyrpl/show');status('已打开 PyRPL · 与仪器台共享同一台 RP');
}catch{}finally{await refresh();}};
document.querySelector('#hidePyrpl').onclick=async()=>{try{await api('pyrpl/hide');status('已隐藏 PyRPL，设备连接保持');}catch{}};
window.addEventListener('instrument-status',refresh);
document.querySelector('#inspectUart').onclick=async()=>{try{
 const result=await api('uart/inspect',{host:document.querySelector('#host').value.trim()});
 const select=document.querySelector('#uartDevice');select.replaceChildren(new Option('请选择实际接线端口',''));
 for(const row of result.devices){const option=new Option(row.device+(row.console?' · 系统控制台':row.owner_pids.length?' · 已占用':''),row.device);option.disabled=row.console||row.owner_pids.length>0;select.append(option);}
 document.querySelector('#uartResult').textContent=JSON.stringify(result,null,2);
}catch{}};
document.querySelector('#deployUart').onclick=async()=>{try{
 const device=document.querySelector('#uartDevice').value;if(!device){status('请选择与实际接线对应的 UART',true);return;}
 const result=await api('uart/deploy',{host:document.querySelector('#host').value.trim(),device});
 document.querySelector('#uartResult').textContent=JSON.stringify(result,null,2);
 status('UART 服务已启动；点击“验证激光器读回”确认完整通信');
}catch{}};
document.querySelector('#verifyLaser').onclick=async()=>{try{
 const result=await api('laser/status');cache.laser={status:result.status,time:new Date().toLocaleTimeString()};
 document.querySelector('#uartResult').textContent=JSON.stringify(result.status,null,2);status('已收到激光器真实状态读回');render();
}catch{}finally{await refresh();}};
let cleanup;
function render(){
 cleanup?.();cleanup=undefined;
 const key=location.hash.slice(1)||'connection';
 if(key==='laser'){location.replace('#connection');return;}
 const aliases={scope:'time',spectrum:'frequency',asg:'initialize',pid:'initialize',methods:'initialize'};
 if(aliases[key]){location.replace('#'+aliases[key]);return;}
 if(!['connection','initialize','time','frequency'].includes(key)){location.hash='connection';return;}
 document.body.dataset.page=key;
 document.querySelector('#uartSetup').hidden=info.simulated||key!=='connection';
 document.querySelectorAll('nav a').forEach(a=>a.setAttribute('aria-current',a.hash==='#'+key?'page':'false'));
 const panel=document.querySelector('#panel'),view=document.createElement('div');
 // Keep the same controls and handlers when their page is unmounted.
 panel.before(connectionTools);connectionTools.hidden=true;
 panel.replaceChildren(view);
 if(key==='connection'){
  cleanup=connection(view,context);
  view.querySelector('#connectionToolsSlot').append(connectionTools);connectionTools.hidden=false;
 }
 else if(key==='initialize')cleanup=initialization(view,context);
 else cleanup=acquisition(view,context,key);
 window.scrollTo({top:0,left:0,behavior:'instant'});
}
document.addEventListener('click',event=>{
 const link=event.target.closest('a[href^="#"]');
 if(!link||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
 if(!['#connection','#initialize','#time','#frequency'].includes(link.hash))return;
 event.preventDefault();
 if(location.hash===link.hash)window.scrollTo({top:0,left:0,behavior:'instant'});
 else location.hash=link.hash;
});
window.addEventListener('hashchange',render);render();

async function pollLock(){
 try{
  const response=await fetch('/api/lock/status',{signal:AbortSignal.timeout(4000)});
  if(!response.ok)throw new Error('状态服务无响应');
  info.lock=(await response.json()).lock;info.lockOffline=false;
  const s=info.lock,t=s.telemetry;
  document.querySelector('#lockState').textContent=s.message;
  document.querySelector('#lockBar').dataset.state=s.state;
  document.querySelector('#lockLamp').dataset.state=s.state==='locked'?'ok':['error','unknown','lost'].includes(s.state)?'error':s.active?'checking':'unknown';
  document.querySelector('#lockReading').textContent=t?`IN1 ${t.in1_v.toFixed(4)} V · OUT2 ${t.out2_v.toFixed(3)} V · ${Math.max(0,(Date.now()/1000-t.sampled_at)).toFixed(1)} 秒前`:'';
 }catch{
  info.lockOffline=true;
  document.querySelector('#lockState').textContent='后台连接中断 · 锁定状态未确认';
  document.querySelector('#lockLamp').dataset.state='error';
 }
 window.dispatchEvent(new Event('lock-state'));
 setTimeout(pollLock,info.lockOffline?2000:500);
}
pollLock();
const stopConnectionMonitor=monitorConnections({info,cache,isBusy:()=>busy.has('rp')||busy.has('laser')});
window.addEventListener('pagehide',stopConnectionMonitor,{once:true});
