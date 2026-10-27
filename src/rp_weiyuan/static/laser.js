// Keep a pending UART request serialized even when its panel is replaced.
let laserQueue=Promise.resolve();

export function mount(root,{api,cache,info}){
 const {temperature:t0,current:i0}=info.laser_initial;
 let disposed=false,reading=false,writing=false;
 root.innerHTML=`<h2>激光器</h2><p class="muted">调节温度和电流，移动工作点寻找模式。</p><div class="card">
 <div class="toolbar laser-toolbar"><button id="read" class="primary">读取一次</button><span id="laserReadState" role="status">单次读取模式</span><span class="timestamp" id="laserTime">尚未读取</span></div>
 <div class="metrics"><div class="metric"><span>TEC 实际温度 / °C</span><strong id="temp">—</strong><small id="tempSetValue">设定读回：—</small></div><div class="metric"><span>LD 实际电流 / mA</span><strong id="current">—</strong><small id="currentSetValue">设定读回：—</small></div><div class="metric"><span>控制模式</span><strong id="modeValue">—</strong></div></div>
 <div class="laser-operating"><span id="tecEnabled">TEC 温控：尚未读取</span><span id="ldEnabled">LD 电流输出：尚未读取</span><div id="laserOperatingNote"></div></div>
 <p class="muted">软件未设置温度、电流上下限。初始工作点：${t0} ℃ / ${i0} mA。设置后立即确认设定值；实际温度、电流及开关通过“读取一次”刷新。</p>
 <p><button id="laserInitialize">应用初始值 · ${t0} ℃ / ${i0} mA</button></p>
 <div class="fields"><label>设定温度 / °C<input id="temperatureInput" type="number" step="0.01" value="${t0}" required></label><button id="setTemp">设置温度</button><label>设定电流 / mA<input id="currentInput" type="number" step="0.01" value="${i0}" required></label><button id="setCurrent">设置电流</button></div>
 <details><summary>完整状态与设定值</summary><pre id="detail">尚未读取</pre></details></div>`;
 const $=id=>root.querySelector('#'+id);
 // Keep unsent values across page navigation; changing the view never sends them.
 cache.laserDraft??={};
 for(const [id,key] of [['temperatureInput','tec_set_temp_c'],['currentInput','ld_set_current_ma']]){
  $(id).value=cache.laserDraft[id]??cache.laser?.status?.[key]??$(id).value;
  $(id).addEventListener('input',()=>{cache.laserDraft[id]=$(id).value;});
 }
 function state(text,error=false){$('laserReadState').textContent=text;$('laserReadState').className=error?'error':'';}
 function buttons(){
  $('read').disabled=reading||writing;
  for(const id of ['laserInitialize','setTemp','setCurrent'])$(id).disabled=writing;
 }
 function show(status){
  cache.laser={status,time:new Date().toLocaleTimeString()};showCached();
 }
 function showCached(){
  const {status:s,time,stale}=cache.laser;
  const number=value=>Number.isFinite(value)?value.toFixed(2):'—';
  $('temp').textContent=number(s.tec_temp_c);$('current').textContent=number(s.ld_current_actual_ma);
  $('modeValue').textContent=s.mode===1?'调试':s.mode===0?'运行':'—';
  $('laserTime').textContent=stale?'实际值 / 开关未刷新'+(time?' · 上次 '+time:''):'最近读回 '+time;
  $('laserTime').classList.toggle('error',Boolean(stale));
  $('tempSetValue').textContent='设定读回：'+number(s.tec_set_temp_c)+' ℃';
  $('currentSetValue').textContent='设定读回：'+number(s.ld_set_current_ma)+' mA';
  const enabled=value=>value===true?'已开启':value===false?'已关闭':'未知';
  $('tecEnabled').textContent=(stale?'上次 ':'')+'TEC 温控：'+enabled(s.tec_enabled);
  $('ldEnabled').textContent=(stale?'上次 ':'')+'LD 电流输出：'+enabled(s.ld_enabled);
  $('laserOperatingNote').textContent=stale?'实际值及 TEC / LD 开关显示的是上次读数，请点击“读取一次”刷新。':s.tec_enabled===false?'TEC 已关闭：可写入温度设定值，但不会自动调温。“运行”是控制模式，不代表温控已开启。':s.ld_enabled===false?'LD 输出已关闭，实际电流不会跟随设定值。':'';
  $('detail').textContent=JSON.stringify(s,null,2);
 }
 function enqueue(action,body){
  const request=laserQueue.then(()=>!disposed?api(action,body,{quiet:true}):null);
  laserQueue=request.catch(()=>{});return request;
 }
 async function read(){
  if(disposed||reading||writing)return;
  reading=true;buttons();state('正在读取…');
  try{
   const result=await enqueue('laser/status',{});
   if(!result||disposed)return;
   show(result.status);state('单次读取完成');
  }catch(e){
   if(!disposed){
    if(cache.laser){cache.laser.stale=true;showCached();}
    state('读取失败，保留上次读回：'+e.message,true);
   }
  }finally{
   reading=false;
   if(!disposed){buttons();window.dispatchEvent(new Event('instrument-status'));}
  }
 }
 async function write(action,body){
  if(disposed||writing)return;
  writing=true;buttons();state(reading?'等待当前读取结束后设置…':'正在设置…');
  try{
   const result=await enqueue(action,body);
   if(!result||disposed)return;
   if(result.status)show(result.status);
   else{
    const old=cache.laser;
    cache.laser={status:{...old?.status,...result.confirmed},time:old?.time,stale:true};showCached();
   }
   const confirmed=result.confirmed;
   const labels=[];
   if(Number.isFinite(confirmed?.tec_set_temp_c))labels.push('温度设定 '+confirmed.tec_set_temp_c.toFixed(2)+' ℃');
   if(Number.isFinite(confirmed?.ld_set_current_ma))labels.push('电流设定 '+confirmed.ld_set_current_ma.toFixed(2)+' mA');
   state(result.warning||(labels.length?labels.join('；')+' 已读回确认；实际值不自动刷新':'设置已读回'),Boolean(result.warning));
  }catch(e){
   if(!disposed){
    if(cache.laser){cache.laser.stale=true;showCached();}
    state('设置未确认：'+e.message,true);
   }
  }finally{
   writing=false;
   if(!disposed){buttons();window.dispatchEvent(new Event('instrument-status'));}
  }
 }
 $('read').onclick=()=>read();
 $('laserInitialize').onclick=()=>write('laser/initialize');
 for(const [button,input,action] of [['setTemp','temperatureInput','temperature'],['setCurrent','currentInput','current']]){
  $(button).onclick=()=>{const el=$(input);if(el.value!==''&&el.reportValidity()&&Number.isFinite(Number(el.value)))write('laser/'+action,{value:Number(el.value)});};
 }
 if(cache.laser)showCached();
 return ()=>{disposed=true;};
}
