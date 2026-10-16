// Both the home cards and persistent header use the same evidence and freshness.
export function connectionStatus(info,cache,name){
 const row=info.connection_health?.[name],connected=name==='rp'?info.connected:info.laser_connected;
 const checked=row?.checked_at?new Date(row.checked_at*1000).toLocaleString():null;
 const stamp=checked?'最近检查：'+checked:'尚无检查记录';
 if(cache.checkingConnections)return {state:'checking',label:'连接中',stamp,detail:'正在执行手动连接'};
 if(cache.connectionMonitorError)return {state:'checking',label:'状态未确认',stamp,detail:cache.connectionMonitorError};
 if(row?.ok===false)return {state:'error',label:'检查失败',stamp,detail:row.error};
 if(!connected)return {state:'unknown',label:'尚未连接',stamp,detail:row?.deferred||''};
 if(cache.connectionMonitorDeferred||row?.deferred)return {state:'checking',label:'待检查',stamp,detail:cache.connectionMonitorDeferred||row.deferred};
 if(row?.ok===true&&Date.now()/1000-row.checked_at<=90)return {state:'ok',label:'连接正常',stamp,detail:'最近只读检查通过'};
 return {state:'checking',label:'待检查',stamp,detail:row?.checked_at?'上次检查已超过 90 秒':'等待首次只读检查'};
}

export function monitorConnections({info,cache,isBusy}){
 let pending=false,disposed=false,lastAttempt=0;
 function update(){
  for(const name of ['rp','laser']){
   const state=connectionStatus(info,cache,name),el=document.querySelector('#'+name+'ConnectionIndicator');
   el.querySelector('.connection-lamp').dataset.state=state.state;
   el.querySelector('[data-label]').textContent=(name==='rp'?'RP':'微源')+' · '+state.label;
   el.title=state.stamp+(state.detail?'；'+state.detail:'');
   el.setAttribute('aria-label',el.textContent+'；'+el.title);
   const header=document.querySelector('#'+name+'State');
   if(header){header.textContent=(name==='rp'?'RP':'激光器')+' · '+state.label;header.title=el.title;}
  }
 }
 async function check(){
  if(disposed||pending||document.hidden)return;
  if(Date.now()-lastAttempt<60000)return;
  lastAttempt=Date.now();
  if(isBusy()||cache.checkingConnections){
   cache.connectionMonitorDeferred='当前操作尚未完成，本轮检查延后';
   window.dispatchEvent(new Event('connection-state'));return;
  }
  pending=true;
  try{
   const response=await fetch('/api/connection/check',{method:'POST',headers:{'Content-Type':'application/json','X-Instrument-Console':'1'},body:'{}',signal:AbortSignal.timeout(9000)});
   const result=await response.json();
   if(!response.ok||!result.ok)throw new Error(result.error||'后台检查无响应');
   if(disposed)return;
   info.connection_health=result.connection_health;
   cache.connectionMonitorError=null;cache.connectionMonitorDeferred=null;
  }catch(e){if(!disposed)cache.connectionMonitorError='自动检查未完成：'+e.message;}
  finally{pending=false;if(!disposed)window.dispatchEvent(new Event('connection-state'));}
 }
 function visible(){if(!document.hidden){update();check();}}
 window.addEventListener('connection-state',update);
 document.addEventListener('visibilitychange',visible);
 const timer=setInterval(check,60000),ageTimer=setInterval(()=>window.dispatchEvent(new Event('connection-state')),5000);
 update();check();
 return ()=>{disposed=true;clearInterval(timer);clearInterval(ageTimer);window.removeEventListener('connection-state',update);document.removeEventListener('visibilitychange',visible);};
}
