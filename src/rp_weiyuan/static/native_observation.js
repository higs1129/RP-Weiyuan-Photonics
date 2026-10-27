import {mountExcitation} from './excitation.js';

export function mount(root,context,page){
 const {api,info,cache,status}=context,scope=page==='time',kind=scope?'scope':'spectrum';
 let disposed=false,timer,plan=null,pending=false,opened=false,last=null;
 const queue=fn=>{const p=(cache.acquisitionHandoff||Promise.resolve()).catch(()=>{}).then(fn);cache.acquisitionHandoff=p;return p;};
 root.innerHTML=`<div class="page-heading"><h2>${scope?'时域观察':'频域观察'}</h2><p>PyRPL 原生${scope?'示波器':'频谱仪'}</p></div>
 <div class="native-layout"><div class="card"><h3>${scope?'Scope · ASG1 / IN2':'Spectrum · IN2'}</h3>
 <p>${scope?'CH1 显示 ASG1 内部波形，CH2 显示 IN2 响应。选择 ASG1 同步触发后，可以等待单次或周期 burst。':'使用当前 RP 后台的 PyRPL 频谱仪，观察 IN2；频率范围、平均和窗口函数均可在原生窗口中调整。'}</p>
 <div class="fields">${scope?'<label>采集时长 / s<input id="nativeDuration" type="number" min="0.000001" max="8.589934592" step="any" value="0.016777216"></label><label>触发方式<select id="nativeTrigger"><option value="asg1">ASG1 内部同步</option><option value="immediately">立刻 / 自由采集</option></select></label>':'<label>Span / Hz<input id="nativeSpan" type="number" min="1" max="125000000" value="100000"></label><label>平均次数<input id="nativeAverage" type="number" min="1" max="100" step="1" value="1"></label>'}</div>
 <div class="toolbar"><button id="nativeOpen" class="primary">打开 ${scope?'Scope':'Spectrum'} 并连续观察</button><button id="nativeApply">应用观察设置</button></div>
 <div class="toolbar"><button id="nativeSingle">单次${scope?'等待触发':'采集'}</button><button id="nativeStop">暂停观察</button><button id="nativeClose">关闭观察窗口</button></div>
 <p id="nativeStatus" role="status">尚未打开原生窗口；网页不再采集和绘制本页波形。</p>
 ${scope?'<p>测时：冻结一帧，将 A 游标放到 ASG1 的参考位置，B 游标放到 IN2 对应响应位置，读取 Δt = tB − tA。含 DAC、ADC 和线缆等延迟，未校准为 OUT1 实际发出至 IN2 到达的纯传播时间。</p>':''}
 <p class="muted">锁模、重锁期间暂时让出采集资源，窗口保留上次画面；锁定恢复后还原原生参数和运行状态。网页与原生窗口共用同一个 PyRPL 实例。</p></div>
 ${scope?'<div class="card" id="nativeExcitation"></div>':''}</div>`;
 const $=id=>root.querySelector('#'+id);
 function message(s,error=false){if(!disposed){$('nativeStatus').textContent=s;$('nativeStatus').className=error?'error':'';}}
 function values(){
  for(const el of root.querySelectorAll('.native-layout > .card:first-child .fields input'))if(!el.reportValidity())throw new Error('请检查观察参数');
  return scope?{duration:Number($('nativeDuration').value),trigger_source:$('nativeTrigger').value}:{span:Number($('nativeSpan').value),trace_average:Number($('nativeAverage').value)};
 }
 function setDuration(value){if(scope)$('nativeDuration').value=value;}
 async function state(){
  last=await api('observation/state',{}, {quiet:true});opened=last.kind===kind;return last;
 }
 async function open(run='continuous',apply=false){
  if(!info.connected)throw new Error('请先连接 RP');
  if(info.lock?.active&&info.lock.state!=='locked')throw new Error('正在锁模/重锁，请等待观察恢复');
  let settings={};
  if(apply||!opened){if(plan){const p=await plan();if(p)setDuration(p.duration);}settings=values();}
  if(disposed)return;
  last=await api('observation/open',{kind,settings,run},{quiet:true});opened=true;
  message('已打开原生窗口；波形直接在 PyRPL 中显示。');
 }
 async function action(fn){if(pending||disposed)return;pending=true;try{await queue(fn);}catch(e){message(e.message,true);status(e.message,true);}finally{pending=false;}}
 $('nativeOpen').onclick=()=>action(()=>open());
 $('nativeApply').onclick=()=>action(()=>open('continuous',true));
 $('nativeSingle').onclick=()=>action(()=>open('single'));
 $('nativeStop').onclick=()=>action(()=>api('observation/run',{run:'stop'},{quiet:true}));
 $('nativeClose').onclick=()=>action(async()=>{await api('observation/close',{}, {quiet:true});opened=false;message('观察窗口已关闭');});
 const cleanupExcitation=scope?mountExcitation($('nativeExcitation'),context,{
  native:true,registerPlan:fn=>{plan=fn;},duration:()=>Number($('nativeDuration').value),setDuration,
  prepareExcitation:async(config,capturePlan,singleCapture)=>{
   await queue(async()=>{
    let current=await state();
    if(current.suspended)throw new Error('正在重锁，尚未发送激励');
    const running=current.kind==='scope'&&current.running.startsWith('running');
    const changed=capturePlan&&Math.abs((current.duration||0)-capturePlan.duration)>capturePlan.duration*1e-6;
    if(singleCapture||current.kind!=='scope'||changed){
     if(capturePlan)setDuration(capturePlan.duration);
     last=await api('observation/open',{kind:'scope',settings:{duration:config.duration,...(singleCapture?{trigger_source:'asg1'}:{})},run:singleCapture?'single':running?'continuous':'stop'},{quiet:true});
     opened=true;
    }
    current=await state();
    if(singleCapture||(running&&config.mode==='burst'&&current.trigger_source==='asg1')){
     const deadline=performance.now()+10000;
     while(!disposed&&performance.now()<deadline){
      current=await state();
      if(current.suspended||current.kind!=='scope')throw new Error('观察已中断，尚未发送激励');
      if(current.armed){await new Promise(r=>setTimeout(r,100));return;}
      await new Promise(r=>setTimeout(r,50));
     }
     throw new Error('未确认 Scope 已等待触发，尚未发送 burst');
    }
   });
  }
 }):()=>{};
 if(scope)root.querySelector('.excitation').open=true;
 async function poll(){
  if(disposed)return;
  if(info.connected&&!pending){try{
   if(info.lock?.active&&info.lock.state!=='locked')message('锁模/重锁中 · 暂停原生观察，保留上次画面');
   else{const s=await queue(state);message(s.error||s.suspended?'观察暂停 · '+(s.error||'正在重新获取锁点'):s.kind===kind?`PyRPL ${scope?'Scope':'Spectrum'} · ${s.running.startsWith('running')?'运行中':s.running.startsWith('paused')?'已暂停':'已停止 / 单次已完成'}`:'原生观察窗口未打开',Boolean(s.error));}
  }catch(e){message(e.message,true);}}
  if(!disposed)timer=setTimeout(poll,1500);
 }
 queue(()=>{}).then(poll);
 return ()=>{disposed=true;clearTimeout(timer);cleanupExcitation();queue(()=>info.connected?api('observation/close',{}, {quiet:true}):null).catch(e=>status(e.message,true));};
}
