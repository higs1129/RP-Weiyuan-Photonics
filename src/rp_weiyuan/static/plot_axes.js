import {validRange} from './plot.js';

// Display state only: no instrument requests or changes to captured arrays.
export function axisControls(root,chart,axes,redraw,{scope=true}={}){
 root.innerHTML=`<summary>坐标轴范围 · <span data-mode>自动</span></summary>
 <div class="fields"><label>横轴下限 / ${scope?'s':'Hz'}<input data-bound="x0" type="number" step="any" placeholder="自动"></label>
 <label>横轴上限 / ${scope?'s':'Hz'}<input data-bound="x1" type="number" step="any" placeholder="自动"></label>
 <label>纵轴下限 / ${scope?'V':'dBm/Hz'}<input data-bound="y0" type="number" step="any" placeholder="自动"></label>
 <label>纵轴上限 / ${scope?'V':'dBm/Hz'}<input data-bound="y1" type="number" step="any" placeholder="自动"></label>
 <button data-apply>应用范围</button><button data-reset>恢复自动范围</button></div>
 <p class="muted">某一轴上下限都留空时自动缩放。左键左右拖动缩放横轴，上下拖动缩放纵轴；Shift + 左键拖动平移。手动范围在连续刷新和本页面切换时保留。触屏请使用上下限输入框。</p>
 <div data-error role="status" class="error"></div>`;
 const fields=Object.fromEntries([...root.querySelectorAll('[data-bound]')].map(el=>[el.dataset.bound,el]));
 const controller=new AbortController(),listen={signal:controller.signal};
 let bounds=null,drag=null;
 function mode(){root.querySelector('[data-mode]').textContent=axes.x&&axes.y?'手动':axes.x?'横轴手动 · 纵轴自动':axes.y?'横轴自动 · 纵轴手动':'自动';}
 function sync(){for(const axis of ['x','y'])for(let i=0;i<2;i++)fields[axis+i].value=axes[axis]?Number(axes[axis][i].toPrecision(12)):'';mode();}
 function commit(x,y){axes.x=x;axes.y=y;sync();root.querySelector('[data-error]').textContent='';redraw();}
 function apply(){
  try{
   const next={};
   for(const axis of ['x','y']){
    const inputs=[fields[axis+'0'],fields[axis+'1']];
    if(inputs.some(el=>!el.validity.valid))throw new Error('请输入有效数字');
    if(inputs.every(el=>el.value.trim()==='')){next[axis]=null;continue;}
    const values=inputs.map(el=>el.value.trim()===''?NaN:Number(el.value));
    if(!validRange(values))throw new Error(`${axis==='x'?'横':'纵'}轴需要填写上下限，且下限小于上限`);
    next[axis]=values;
   }
   commit(next.x,next.y);
  }catch(e){root.querySelector('[data-error]').textContent=e.message;}
 }
 root.querySelector('[data-apply]').addEventListener('click',apply,listen);
 root.querySelector('[data-reset]').addEventListener('click',()=>commit(null,null),listen);
 root.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('input')){e.preventDefault();apply();}},listen);
 chart.addEventListener('pointerdown',e=>{
  if(e.button!==0||e.pointerType==='touch'||!bounds)return;
  const rect=chart.querySelector('svg').getBoundingClientRect();
  const px=(e.clientX-rect.left)*bounds.width/rect.width,py=(e.clientY-rect.top)*bounds.height/rect.height;
  if(px<bounds.left||px>bounds.right||py<bounds.top||py>bounds.bottom)return;
  e.preventDefault();
  drag={id:e.pointerId,x:e.clientX,y:e.clientY,ranges:{x:[...bounds.x],y:[...bounds.y]},
        fx:(px-bounds.left)/(bounds.right-bounds.left),fy:(bounds.bottom-py)/(bounds.bottom-bounds.top),
        width:(bounds.right-bounds.left)*rect.width/bounds.width,height:(bounds.bottom-bounds.top)*rect.height/bounds.height,
        pan:e.shiftKey};
  chart.setPointerCapture(e.pointerId);chart.dataset.dragging='true';
 },listen);
 chart.addEventListener('pointermove',e=>{
  if(!drag||e.pointerId!==drag.id)return;
  e.preventDefault();
  const dx=e.clientX-drag.x,dy=e.clientY-drag.y,next={};
  for(const axis of ['x','y']){
   const [lo,hi]=drag.ranges[axis],span=hi-lo,delta=axis==='x'?dx:dy;
   if(drag.pan){const shift=(axis==='x'?-dx/drag.width:dy/drag.height)*span;next[axis]=[lo+shift,hi+shift];}
   else{
    const anchor=lo+span*(axis==='x'?drag.fx:drag.fy),factor=Math.exp(Math.max(-12,Math.min(12,delta/180)));
    next[axis]=[anchor+(lo-anchor)*factor,anchor+(hi-anchor)*factor];
   }
  }
  if(validRange(next.x)&&validRange(next.y))commit(next.x,next.y);
 },listen);
 function end(e){if(!drag||e.pointerId!==drag.id)return;drag=null;delete chart.dataset.dragging;if(chart.hasPointerCapture(e.pointerId))chart.releasePointerCapture(e.pointerId);}
 for(const name of ['pointerup','pointercancel','lostpointercapture'])chart.addEventListener(name,end,listen);
 sync();
 return {
  update(value){
   bounds=value;
   mode();
   for(const axis of ['x','y'])for(let i=0;i<2;i++)fields[axis+i].placeholder=value?Number(value[axis][i].toPrecision(8)).toString():'自动';
  },
  destroy(){if(drag)end({pointerId:drag.id});controller.abort();}
 };
}
