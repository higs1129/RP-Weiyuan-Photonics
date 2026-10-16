// One SVG per visible acquisition view. Display reduction never changes exported arrays.
export function validRange(range){return Array.isArray(range)&&range.length===2&&range.every(Number.isFinite)&&range[0]<range[1]&&Number.isFinite(range[1]-range[0]);}
export function plot(root,capture,options={}){
 const scope=capture.kind==='scope',t=capture.bridge_result.trace;
 const x=scope?t.t:t.frequency_hz,series=scope?(options.channel?[t[options.channel]]:[t.ch1,t.ch2]):[t.input1_dbm_per_hz];
 const label=options.label||'CH1 · CH2';
 const reference=options.reference;
 let xmin=x[0],xmax=x.at(-1);if(xmin===xmax)xmax=xmin+1;
 if(validRange(options.axes?.x))[xmin,xmax]=options.axes.x;
 // Reduce the visible window, keeping adjacent samples to clip crossing lines.
 let first=x.findIndex(v=>v>=xmin);if(first<0)first=x.length-1;
 let last=x.findIndex(v=>v>xmax);if(last<0)last=x.length-1;
 first=Math.max(0,first-1);last=Math.min(x.length-1,last);
 let indices;
 if((scope&&!capture.preview)||last-first<2048)indices=Array.from({length:last-first+1},(_,i)=>first+i);
 else{
  const keep=new Set([first,last]),step=Math.ceil((last-first+1)/450);
  for(let start=first;start<=last;start+=step)for(const y of series){
   let min=start,max=start;for(let i=start+1;i<Math.min(last+1,start+step);i++){if(y[i]<y[min])min=i;if(y[i]>y[max])max=i;}
   keep.add(min);keep.add(max);
  }
  indices=[...keep].sort((a,b)=>a-b);
 }
 const points=series.map(y=>indices.map(i=>y[i]));
 let lo=Infinity,hi=-Infinity;for(const y of series)for(const v of y){lo=Math.min(lo,v);hi=Math.max(hi,v);}if(lo===hi){lo-=1;hi+=1;}const pad=(hi-lo)*.08;lo-=pad;hi+=pad;
 if(validRange(options.axes?.y))[lo,hi]=options.axes.y;
 const width=Math.max(260,root.clientWidth),height=Math.max(220,root.clientHeight||345),left=60,right=width-18,top=40,bottom=height-65;
 const X=v=>left+((v-xmin)/(xmax-xmin))*(right-left),Y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
 const format=(v,span)=>Number(v.toPrecision(Math.min(12,Math.max(4,Math.ceil(Math.log10(Math.max(Math.abs(v),span)/span))+3)))).toString();
 const clipId=root.id+'-trace-clip';
 let svg=`<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${scope?label+' 时域波形，时间单位秒，纵轴伏特':'IN2 频谱，横轴赫兹，纵轴 dBm/Hz'}"><rect width="100%" height="${height}" fill="white"/>`;
 svg+=`<defs><clipPath id="${clipId}"><rect x="${left}" y="${top}" width="${right-left}" height="${bottom-top}"/></clipPath></defs>`;
 const ticks=width<500?3:5;
 for(let i=0;i<=ticks;i++){let yy=lo+(hi-lo)*i/ticks,xx=xmin+(xmax-xmin)*i/ticks;svg+=`<line x1="${left}" x2="${right}" y1="${Y(yy)}" y2="${Y(yy)}" stroke="#e1e8e3"/><text x="${left-8}" y="${Y(yy)+4}" text-anchor="end" fill="#617467" font-size="12">${format(yy,hi-lo)}</text><text x="${X(xx)}" y="${bottom+24}" text-anchor="${i===ticks?'end':'middle'}" fill="#617467" font-size="12">${format(xx,xmax-xmin)}</text>`;}
 svg+=`<g clip-path="url(#${clipId})">`;
 const colors=['#25634b','#ac732a'];points.forEach((ys,j)=>{const path=ys.map((y,i)=>`${i?'L':'M'}${X(x[indices[i]]).toFixed(2)},${Y(y).toFixed(2)}`).join(' ');svg+=`<path d="${path}" fill="none" stroke="${colors[j]}" stroke-width="1.7"/>`;});
 if(scope&&reference)for(const [name,value,color] of [['基线',reference.baseline_v,'#76867f'],['目标',reference.target_v,'#b37514']]){
  if(value>=lo&&value<=hi)svg+=`<line x1="${left}" x2="${right}" y1="${Y(value)}" y2="${Y(value)}" stroke="${color}" stroke-dasharray="6 4"/><text x="${right-5}" y="${Y(value)-5}" text-anchor="end" fill="${color}" font-size="12">${name} ${format(value,hi-lo)} V</text>`;
 }
 svg+=`</g><text x="${left}" y="24" fill="#25634b" font-size="13">${scope?label+' / V':'IN2 / dBm/Hz'}</text><text x="${right}" y="${height-12}" text-anchor="end" fill="#617467" font-size="12">${scope?'时间 / s':'频率 / Hz'}</text></svg>`;root.innerHTML=svg;
 return {x:[xmin,xmax],y:[lo,hi],width,left,right,top,bottom,height};
}
