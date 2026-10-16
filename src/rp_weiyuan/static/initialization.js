import {mount as acquisition} from './acquisition.js';
import {mount as laser} from './laser.js';

export function mount(root,context){
 const {api,info,cache,status}=context;
 const defaults=info.lock_defaults;
 cache.lockSettings??={...defaults,...info.lock?.settings};cache.sweepSettings??={frequency_hz:50,amplitude_v:1,duration_s:defaults.duration_s};
 root.innerHTML=`<div class="page-heading"><h2>测量初始化</h2><p class="muted">CH1 / IN1 · OUT2 扫频或反馈</p></div>
 <div class="card lock-controls"><div class="toolbar"><label>锁定比例<input id="fraction" type="number" min="0.01" max="0.99" step="0.01" required></label><button id="lock" class="primary">锁定当前模式</button><button id="sweep">恢复扫频</button><span id="lockLocal" role="status"></span></div>
 <div id="reference" class="reference-readout">先恢复扫频，观察完整凹陷，再点击锁定。</div>
 </div><div class="measurement-workspace"><div id="acquisitionView"></div>
 <details class="live-laser laser-side"><summary>调节激光器 · 温度与电流</summary><p id="laserLockState" class="muted" role="status"></p><div id="laserControls"></div></details></div>
 <div class="card lock-controls advanced-lock">
 <details><summary>锁定与守护参数</summary><p class="muted">锁定比例：0 是凹陷底部，1 是非共振基线。使用当前模式，保持激光器设定电流。</p><div class="fields" id="lockFields"></div><p class="muted">I 带反馈符号，单位 Hz；ival 是积分器初始电压。失锁后按锁定前的扫频设置重新采集模式，更新基线、谷底和锁点，再按当前比例与 PID 参数捕获；没有有效模式时等待重扫。切换页面后守护继续运行。</p></details>
 <details><summary>扫频参数</summary><div class="fields" id="sweepFields"></div></details></div>`;
 const $=id=>root.querySelector('#'+id);
 const fields=[['p','P',-100,100,'any'],['i','I / Hz',-1e6,1e6,'any'],['ival','初始 ival / V',-1,1,.01],
  ['min_voltage','OUT2 下限 / V',-1,0,.01],['max_voltage','OUT2 上限 / V',0,1,.01],
  ['loss_hold_s','持续失锁判定 / s',.1,10,.1],['stable_hold_s','稳定确认 / s',.1,10,.1],
  ['capture_timeout_s','每次捕获等待 / s',1,60,1],['retry_interval_s','重试间隔 / s',.2,60,.1],
  ['poll_interval_s','IN1 检查间隔 / s',.05,1,.05],['target_tolerance_v','锁定误差上限 / V',.0005,.2,.001],
  ['min_contrast_v','最低共振深度 / V',.001,1,.001],
  ['baseline_tolerance','基线接近比例',.01,.3,.01]];
 function fill(container,entries,values){
  for(const [key,label,min,max,step] of entries){
   const el=document.createElement('label');el.textContent=label;
   const input=document.createElement('input');Object.assign(input,{type:'number',min,max,step:'any',value:values[key],required:true});input.dataset.key=key;
   el.append(input);container.append(el);
  }
 }
 fill($('lockFields'),fields,cache.lockSettings);
 fill($('sweepFields'),[['frequency_hz','频率 / Hz',1,10000,'any'],['amplitude_v','幅度 / V',.001,1,.01],['duration_s','参考采集时长 / s',.001,2,'any']],cache.sweepSettings);
 $('fraction').value=cache.lockSettings.fraction;
 let disposed=false,pending=false;
 function update(){
  const s=info.lock;
  $('laserLockState').textContent=info.lockOffline?'锁定状态未确认':s?.message||'尚未锁定';
  $('lock').disabled=pending||!info.connected||s?.active||info.lockOffline;
  $('sweep').disabled=pending||!info.connected;
  for(const el of root.querySelectorAll('.lock-controls input'))el.disabled=pending||Boolean(s?.active);
  $('lockLocal').textContent=s?.attempts?`捕获 ${s.attempts} 次`:'守护未运行';
  const r=s?.reference;
  $('reference').textContent=r?`基线 ${r.baseline_v.toFixed(4)} V → 底部 ${r.minimum_v.toFixed(4)} V · 目标 ${r.target_v.toFixed(4)} V · 失锁阈值 ${r.loss_threshold_v.toFixed(4)} V`:s?.active?'尚无有效锁点 · '+s.message:'先恢复扫频，观察完整凹陷，再点击锁定。';
 }
 function readSettings(){
  for(const input of root.querySelectorAll('.lock-controls input'))if(!input.reportValidity())throw new Error('请检查锁定与扫频参数');
  for(const input of $('lockFields').querySelectorAll('input'))cache.lockSettings[input.dataset.key]=Number(input.value);
  for(const input of $('sweepFields').querySelectorAll('input'))cache.sweepSettings[input.dataset.key]=Number(input.value);
  cache.lockSettings.fraction=Number($('fraction').value);
  cache.lockSettings.duration_s=cache.sweepSettings.duration_s;
 }
 async function action(name){
  try{
   readSettings();pending=true;update();
   // The server stops/waits for the old acquisition before taking a reference.
   window.dispatchEvent(new Event('measurement-transition'));
   const result=await api(name,name==='lock'?{settings:cache.lockSettings}:cache.sweepSettings);
   Object.assign(info,{lock:result.lock});
   status(name==='lock'?'已开始捕获；锁定确认后持续守护 IN1。':'已停止守护并恢复扫频。');
  }catch(e){status(e.message,true);}finally{pending=false;if(!disposed)update();}
 }
 $('lock').onclick=()=>action('lock');$('sweep').onclick=()=>action('fine-sweep');
 const cleanAcquisition=acquisition($('acquisitionView'),context,'initialize');
 const cleanLaser=laser($('laserControls'),context);$('laserControls').classList.add('compact-laser');
 const laserPanel=root.querySelector('.laser-side');
 cache.laserPanelOpen??=matchMedia('(min-width:1100px)').matches;
 laserPanel.open=cache.laserPanelOpen;
 laserPanel.addEventListener('toggle',()=>{if(!disposed)cache.laserPanelOpen=laserPanel.open;});
 window.addEventListener('lock-state',update);window.addEventListener('connection-state',update);update();
 return ()=>{disposed=true;cleanAcquisition();cleanLaser();window.removeEventListener('lock-state',update);window.removeEventListener('connection-state',update);};
}
