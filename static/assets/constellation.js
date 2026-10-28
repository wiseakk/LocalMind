/* Bounded Canvas 2D graph. Entities are observations, never inferred thoughts. */
(() => {
  'use strict';
  const get=id=>document.getElementById(id),canvas=get('constellation');
  // jsdom does not implement Canvas; the accessible graph remains fully usable.
  const ctx=typeof window.CanvasRenderingContext2D==='function'?canvas.getContext('2d',{alpha:false}):null;
  const MAX_NODES=36,TAU=Math.PI*2;
  const kinds={assistant:'АССИСТЕНТ',conversation:'ДИАЛОГ',app:'ПРИЛОЖЕНИЕ',device:'УСТРОЙСТВО',file:'ВЛОЖЕНИЕ',source:'СПРАВОЧНИК',tool:'РЕЗУЛЬТАТ'};
  const activityNames={idle:'Спокойная орбита',listening:'Слушаю · входной звук',transcribing:'Распознавание · ожидаем текст',generating:'Формируется ответ',speaking:'Озвучка · выходной звук',tool:'Получен результат действия'};
  let nodes=[],selected='assistant',mode='idle',reduced=false,low=false,visible=true,closing=false;
  let panelVisible=true;
  let width=1,height=1,timer=null,last=0,frameCount=0,dirty=true,drag=null,parallaxX=0,parallaxY=0,toolUntil=0,toolTimer=null;
  let factor=1,quality=1.5,background=null,starfield=null,cacheDirty=true,announced=null;
  let settling=true,settleTime=0,stableSteps=0,accumulator=0,geometryScale=36;
  let drawMean=0,qualityFrames=0,diagnostics=null,overlayLast=0,sampleIndex=0,sampleCount=0;
  const intervals=new Float32Array(180),costs=new Float32Array(180),glows=new Map();
  function wakePhysics(){settling=true;settleTime=0;stableSteps=0;}
  const particles=Array.from({length:52},(_,i)=>({x:((i*73+19)%251)/251,y:((i*117+7)%257)/257,r:i%7===0?1.15:.55}));
  const observation={apps:[],devices:[],files:[],sources:[],conversation:false,tools:[]};
  const escapedLabel=(value,fallback)=>typeof value==='string'?value.slice(0,80):fallback;
  function rebuild(){
    const items=[{id:'assistant',kind:'assistant',label:'LocalMind',detail:'Связи с каталогом, устройствами и текущим диалогом. Это не рассуждения модели. Постоянная память не подключена.'}];
    if(observation.conversation)items.push({id:'conversation',kind:'conversation',label:'Текущий диалог',detail:'Контекст только этой сессии. История не сохраняется на диск.'});
    for(const app of observation.apps)items.push({id:'app:'+app.id,kind:'app',label:escapedLabel(app.name,'Приложение'),detail:app.allowed?'Обнаружено в каталоге. Разрешение запуска выдано пользователем.':'Обнаружено в каталоге. Обнаружение не предоставляет разрешение запуска.'});
    for(const [i,device] of observation.devices.entries())items.push({id:'device:'+String(device.id??i),kind:'device',label:escapedLabel(device.name,'Устройство'),detail:device.demo?'DEMO · симуляция. Физическое устройство не переключается.':'Настроенная цель Home Assistant; состояние не опрошено.'});
    for(const file of observation.files)items.push({id:'file:'+file.id,kind:'file',label:file.label,detail:'Выбранный локальный файл. Содержимое не передано модели. Индексация — только демонстрация интерфейса.'});
    for(const source of observation.sources)items.push({id:'source:'+source.id,kind:'source',label:'Разрешённый справочник',detail:'Настроенный TXT/MD источник. Разрешено чтение; используется только при включённой локальной справке.'});
    for(const tool of observation.tools)items.push(tool);
    const old=new Map(nodes.map(n=>[n.id,n]));
    nodes=items.slice(0,MAX_NODES).map((n,i)=>{
      const prior=old.get(n.id),angle=i*2.39996;
      const ring=i===0?0:(.55+((i*7)%5)*.11);
      return {...n,x:prior?.x??(reduced||low?Math.cos(angle)*ring:0),y:prior?.y??(reduced||low?Math.sin(angle)*ring:0),vx:prior?.vx??0,vy:prior?.vy??0,tx:Math.cos(angle)*ring,ty:Math.sin(angle)*ring,active:prior?.active??0,sx:0,sy:0,index:i,labelCache:null};
    });
    if(!nodes.some(n=>n.id===selected))selected='assistant';
    const options=nodes.map(n=>{const option=document.createElement('option');option.value=n.id;option.textContent=n.label;return option;});
    get('nodeSelect').replaceChildren(...options);get('nodeSelect').value=selected;
    get('graphCount').textContent=nodes.length+' узл. · '+Math.max(0,nodes.length-1)+' связ.';
    wakePhysics();inspect();redraw();
  }
  function inspect(){
    const n=nodes.find(n=>n.id===selected)||nodes[0];
    get('nodeTitle').textContent=n.label;get('nodeType').textContent=kinds[n.kind];
    get('nodeDetail').textContent=n.detail+(n.kind!=='assistant'?' Связь: LocalMind → '+n.label+'.':'');
    get('nodeSelect').value=n.id;dirty=true;
  }
  function select(id){selected=id;inspect();redraw();}
  function audioActive(){const c=amplitude.current;return Boolean(c&&(c.kind==='listening'||(!c.source.paused&&!c.source.ended)));}
  function effective(){return audioActive()&&amplitude.current.kind==='speaking'?'speaking':mode==='idle'&&performance.now()<toolUntil?'tool':mode;}
  function announce(m=effective()){if(m===announced)return;announced=m;get('skyPanel').dataset.activity=m;get('graphActivity').textContent=activityNames[m];}
  function setActivity(value){mode=Object.hasOwn(activityNames,value)?value:'idle';announce();redraw();}
  const scale=()=>geometryScale;
  function physics(dt){
    if(reduced||low||!settling)return;
    // Fixed 60Hz solver, at most three substeps after a delayed display frame.
    accumulator=Math.min(50,accumulator+dt);
    while(accumulator>=1000/60){
      accumulator-=1000/60;let energy=0;
    for(let i=1;i<nodes.length;i++){
      const n=nodes[i];if(drag===n)continue;
      n.vx+=(n.tx-n.x)*.009;n.vy+=(n.ty-n.y)*.009;
      for(let j=1;j<i;j++){
        const o=nodes[j],dx=n.x-o.x,dy=n.y-o.y,d2=Math.max(.02,dx*dx+dy*dy);
        if(d2<.3){const f=.00016/d2;n.vx+=dx*f;n.vy+=dy*f;if(drag!==o){o.vx-=dx*f;o.vy-=dy*f;}}
      }
      n.vx*=.85;n.vy*=.85;n.x=Math.max(-1.07,Math.min(1.07,n.x+n.vx));n.y=Math.max(-1.07,Math.min(1.07,n.y+n.vy));
      energy+=n.vx*n.vx+n.vy*n.vy;
    }
      settleTime+=1000/60;stableSteps=energy<.000001?stableSteps+1:0;
      if(!drag&&(stableSteps>20||settleTime>5000)){settling=false;for(const n of nodes)n.vx=n.vy=0;break;}
    }
  }
  function layer(w,h,opaque=false){
    const image=document.createElement('canvas');image.width=Math.max(1,Math.ceil(w*factor));image.height=Math.max(1,Math.ceil(h*factor));
    const context=image.getContext('2d',{alpha:!opaque});context.setTransform(factor,0,0,factor,0,0);return {image,context,w,h};
  }
  function buildLayers(){
    background=layer(width,height,true);const b=background.context;
    b.fillStyle='#121116';b.fillRect(0,0,width,height);b.strokeStyle='#a881cd12';b.lineWidth=1;
    for(const r of [.55,1,1.4]){b.beginPath();b.ellipse(width*.5,height*.47,scale()*r,scale()*r*.77,-.34,0,TAU);b.stroke();}
    starfield=layer(width+8,height);const s=starfield.context;s.fillStyle='#9b82bb';
    for(let i=0;i<particles.length;i++){const p=particles[i];s.globalAlpha=.17+(i%3)*.09;s.beginPath();s.arc(p.x*width+4,p.y*height,p.r,0,TAU);s.fill();}
    glows.clear();for(const n of nodes)n.labelCache=null;cacheDirty=false;
  }
  function labelFor(n,on){
    if(!n.labelCache){
      const root=n.kind==='assistant',label=n.label.length>23?n.label.slice(0,21)+'…':n.label;
      const font=(root?'500 12px':'10px')+' Onest, sans-serif';
      ctx.font=font;const w=Math.ceil(Math.min(Math.max(80,width*.36),ctx.measureText(label).width)+4),h=root?20:17;
      n.labelCache=[false,true].map(active=>{
        const l=layer(w,h);l.context.font=font;l.context.textAlign='center';l.context.fillStyle=root?'#ddc7f5':active?'#e1d5ef':'#a49aaf';
        l.context.fillText(label,w/2,h-5,w-4);return l;
      });
    }
    return n.labelCache[on?1:0];
  }
  function glowFor(color,root,on){
    const blur=root?24:on?14:6,key=color+':'+blur;
    if(!glows.has(key)){
      // Rasterize the same blur once, never blur the full live canvas per node.
      const r=root?7:on?4.5:3,size=blur*4+24,g=layer(size,size),c=g.context;
      c.shadowColor=color;c.shadowBlur=blur*factor;c.fillStyle=color;c.beginPath();c.arc(size/2,size/2,r,0,TAU);c.fill();
      glows.set(key,g);
    }
    return glows.get(key);
  }
  function draw(now,dt){
    frameCount++;dirty=false;const m=effective();announce(m);if(!ctx)return;
    physics(dt);if(cacheDirty)buildLayers();
    const active=m!=='idle',pulse=reduced||low?0:Math.sin(now*.0018)*.5+.5;
    const level=amplitude.sample();
    ctx.drawImage(background.image,0,0,width,height);
    ctx.drawImage(starfield.image,-4+(reduced||low?0:Math.sin(now*.00007)*2),0,width+8,height);
    for(const n of nodes){
      const drift=!reduced&&!low&&drag!==n&&n.index!==0;
      n.sx=width*.5+(n.x+(drift?Math.sin(now*.00013+n.index)*.014:0))*geometryScale+parallaxX;
      n.sy=height*.47+(n.y+(drift?Math.cos(now*.00011+n.index)*.014:0))*geometryScale+parallaxY;
    }
    const root=nodes[0];
    for(let i=1;i<nodes.length;i++){
      const n=nodes[i],on=n.id===selected||n.active>now;
      ctx.strokeStyle=on?'#b697dd88':active?'#a17cc94d':'#86709d33';ctx.lineWidth=on?1.2:.7;
      ctx.beginPath();ctx.moveTo(root.sx,root.sy);ctx.quadraticCurveTo((root.sx+n.sx)*.5+10,(root.sy+n.sy)*.5-12,n.sx,n.sy);ctx.stroke();
      if(!reduced&&!low&&(m==='generating'||m==='transcribing'||n.active>now)){
        const t=((now*.00023+i*.17)%1),x=root.sx+(n.sx-root.sx)*t,y=root.sy+(n.sy-root.sy)*t;
        ctx.fillStyle='#d3b4ef';ctx.beginPath();ctx.arc(x,y,1.2,0,TAU);ctx.fill();
      }
    }
    for(const n of nodes){
      const x=n.sx,y=n.sy,root=n.kind==='assistant',on=n.id===selected||n.active>now;
      const color=n.kind==='device'?'#ce718c':n.kind==='file'?'#c2bbd0':root?'#e1c4ff':'#ae85d7';
      const r=root?7+(active?pulse*1.1:0)+level*10:on?4.5:3;
      if(!low){const g=glowFor(color,root,on),s=root?1+level*.65:1;ctx.drawImage(g.image,x-g.w*s/2,y-g.h*s/2,g.w*s,g.h*s);}
      ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,r,0,TAU);ctx.fill();
      if(root||on){ctx.strokeStyle=color+'44';ctx.lineWidth=1;ctx.beginPath();ctx.arc(x,y,r+7+(root?pulse*4:0),0,TAU);ctx.stroke();}
      const label=labelFor(n,on);ctx.drawImage(label.image,x-label.w/2,y+r+(root?25:17)-label.h+5,label.w,label.h);
    }
    ctx.globalAlpha=1;
  }
  function isVisible(){return visible&&panelVisible&&!document.hidden&&!closing;}
  function continuous(){return !reduced&&!low;}
  function stopFrames(){if(timer!==null)cancelAnimationFrame(timer);timer=null;last=0;accumulator=0;sampleCount=sampleIndex=0;if(diagnostics)diagnostics.textContent='Canvas · приостановлено';}
  function timing(){
    const count=sampleCount,sorted=Array.from(intervals.subarray(0,count)).sort((a,b)=>a-b);
    let total=0,drawTotal=0;for(let i=0;i<count;i++){total+=intervals[i];drawTotal+=costs[i];}
    return {fps:total?1000*count/total:0,p95FrameMs:count?sorted[Math.min(count-1,Math.floor(count*.95))]:0,meanDrawMs:count?drawTotal/count:0};
  }
  function schedule(){
    if(timer!==null||!ctx||!isVisible())return;
    timer=requestAnimationFrame(now=>{timer=null;if(!isVisible())return;
      const dt=last?Math.min(50,now-last):1000/60;
      // Explicit economy mode throttles live audio only; normal mode follows
      // the display, including high-refresh displays. Quiet modes draw on demand.
      if(low&&!dirty&&last&&now-last<84){schedule();return;}
      if(dirty||continuous()||drag||audioActive()){
        const start=performance.now();draw(now,dt);const cost=performance.now()-start;
        if(last){intervals[sampleIndex]=now-last;costs[sampleIndex]=cost;sampleIndex=(sampleIndex+1)%intervals.length;sampleCount=Math.min(intervals.length,sampleCount+1);}
        last=now;drawMean=drawMean*.95+cost*.05;qualityFrames++;
        // Hysteresis avoids reallocations on isolated streaming/GC frames.
        if(!low&&qualityFrames>120&&drawMean>5&&quality>1){quality=Math.max(1,quality-.25);qualityFrames=0;resize();}
        else if(!low&&qualityFrames>600&&drawMean<2&&quality<1.5){quality=Math.min(1.5,quality+.25);qualityFrames=0;resize();}
        if(diagnostics&&now-overlayLast>500){const t=timing();diagnostics.textContent=`${t.fps.toFixed(1)} FPS · p95 ${t.p95FrameMs.toFixed(1)} ms · draw ${t.meanDrawMs.toFixed(2)} ms · DPR ${factor.toFixed(2)}`;overlayLast=now;}
      }
      if(continuous()||drag||audioActive())schedule();
      else{last=0;sampleCount=sampleIndex=0;if(diagnostics)diagnostics.textContent='Canvas · по запросу';}
    });
  }
  function redraw(){dirty=true;schedule();}
  function resize(){
    const rect=canvas.getBoundingClientRect();
    const w=Math.max(1,canvas.clientWidth||rect.width),h=Math.max(1,canvas.clientHeight||rect.height);
    const dpr=low?1:Math.min(quality,(window.devicePixelRatio||1)*Math.max(1,rect.width/w));
    // Absolute pixel cap also protects unusually large/high-DPI monitors.
    const nextFactor=Math.min(dpr,Math.sqrt(1600000/(w*h)));
    if(w!==width||h!==height||Math.abs(nextFactor-factor)>.01||!background){
      width=w;height=h;factor=nextFactor;geometryScale=Math.max(36,Math.min(width*.38,height*.34,220));
      canvas.width=Math.max(1,Math.floor(width*factor));canvas.height=Math.max(1,Math.floor(height*factor));
      ctx?.setTransform(factor,0,0,factor,0,0);cacheDirty=true;
    }redraw();
  }
  function hit(e){const r=canvas.getBoundingClientRect(),x=(e.clientX-r.left)*width/r.width,y=(e.clientY-r.top)*height/r.height;return nodes.find(n=>Math.hypot(n.sx-x,n.sy-y)<22);}
  canvas.addEventListener('pointerdown',e=>{const n=hit(e);if(!n)return;select(n.id);drag=n;canvas.setPointerCapture?.(e.pointerId);redraw();});
  canvas.addEventListener('pointermove',e=>{
    const r=canvas.getBoundingClientRect();
    const x=(e.clientX-r.left)*width/r.width,y=(e.clientY-r.top)*height/r.height;
    if(drag){const s=scale();drag.x=drag.tx=Math.max(-1.05,Math.min(1.05,(x-width*.5)/s));drag.y=drag.ty=Math.max(-1.05,Math.min(1.05,(y-height*.47)/s));drag.vx=drag.vy=0;wakePhysics();redraw();}
    else if(!low&&!reduced){parallaxX=(x-width*.5)*.008;parallaxY=(y-height*.5)*.008;redraw();}
  });
  const release=()=>{drag=null;wakePhysics();redraw();};canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);canvas.addEventListener('lostpointercapture',release);
  canvas.addEventListener('pointerleave',()=>{parallaxX=parallaxY=0;redraw();});
  get('nodeSelect').addEventListener('change',e=>select(e.target.value));
  function move(dx,dy){const n=nodes.find(n=>n.id===selected);n.x=n.tx=Math.max(-1,Math.min(1,n.x+dx));n.y=n.ty=Math.max(-1,Math.min(1,n.y+dy));n.vx=n.vy=0;wakePhysics();redraw();}
  get('nodeSelect').addEventListener('keydown',e=>{const d=e.altKey&&{ArrowUp:[0,-.08],ArrowDown:[0,.08],ArrowLeft:[-.08,0],ArrowRight:[.08,0]}[e.key];if(d){e.preventDefault();move(...d);}});
  get('moveNode').addEventListener('click',()=>move(.12,0));
  get('centerGraph').addEventListener('click',()=>{nodes=[];parallaxX=parallaxY=0;rebuild();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopFrames();else redraw();});
  if(window.ResizeObserver)new ResizeObserver(resize).observe(canvas);else window.addEventListener('resize',resize);
  if(window.IntersectionObserver)new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(!visible)stopFrames();else redraw();}).observe(canvas);
  window.addEventListener('pagehide',()=>{closing=true;stopFrames();clearTimeout(toolTimer);amplitude.stop();amplitude.context?.close().catch(()=>{});amplitude.context=null;});
  window.addEventListener('pageshow',()=>{closing=false;redraw();});
  // Audio samples come exclusively from the active capture/playback source.
  const amplitude={context:null,current:null,buffer:new Uint8Array(256),
    unlock(){const Context=window.AudioContext||window.webkitAudioContext;if(!Context)return null;
      try{this.context??=new Context();this.context.resume().catch(()=>{});return this.context;}catch(_){return null;}
    },
    start(source,kind){
      this.stop();
      const audioContext=this.unlock();if(!audioContext)return ()=>{};
      let input,analyser;
      try{
        const ctx=audioContext;
        // Do not route a playing element into a suspended context: ordinary
        // local playback must remain audible if browser policy blocks analysis.
        if(kind==='speaking'&&ctx.state&&ctx.state!=='running')return ()=>{};
        input=kind==='listening'?ctx.createMediaStreamSource(source):ctx.createMediaElementSource(source);
        // Preserve audible playback even if the optional analyser cannot attach.
        if(kind==='speaking')input.connect(ctx.destination);
        analyser=ctx.createAnalyser();analyser.fftSize=256;input.connect(analyser);
        const changed=()=>{announce();redraw();};
        for(const event of ['play','pause','ended'])source.addEventListener?.(event,changed);
        const current={input,analyser,kind,source,changed};this.current=current;announce();redraw();
        return ()=>{if(this.current===current)this.stop();};
      }catch(_){analyser?.disconnect();if(kind==='listening')input?.disconnect();return ()=>{input?.disconnect();};}
    },
    sample(){const c=this.current;if(!c||c.source.paused||document.hidden)return 0;
      c.analyser.getByteTimeDomainData(this.buffer);let sum=0;for(const b of this.buffer){const x=(b-128)/128;sum+=x*x;}return Math.min(1,Math.sqrt(sum/this.buffer.length)*3);
    },
    stop(){if(this.current){const c=this.current;for(const event of ['play','pause','ended'])c.source.removeEventListener?.(event,c.changed);c.input.disconnect();c.analyser.disconnect();this.current=null;}announce();redraw();}
  };
  window.LocalMindAudio=amplitude;
  window.localmindScene={setActivity,redraw,
    setVisible(value){if(panelVisible===Boolean(value))return;panelVisible=Boolean(value);if(panelVisible)redraw();else stopFrames();},
    configure(options){reduced=options.reduced;low=options.low;stopFrames();for(const n of nodes)n.vx=n.vy=0;wakePhysics();resize();},
    setDiagnostics(enabled){
      if(enabled&&!diagnostics){diagnostics=document.createElement('output');diagnostics.className='canvas-diagnostics';diagnostics.setAttribute('aria-hidden','true');canvas.parentElement.append(diagnostics);}
      else if(!enabled&&diagnostics){diagnostics.remove();diagnostics=null;}overlayLast=0;redraw();
    },
    observeInfo(info){observation.devices=(info.devices||[]).slice(0,8).map(d=>({...d,demo:info.demo}));rebuild();},
    observeApps(apps){observation.apps=apps.slice(0,10);rebuild();},
    observeConversation(){observation.conversation=true;rebuild();},
    setFiles(files){observation.files=files.slice(0,8);rebuild();},
    setSources(sources){observation.sources=sources.filter(s=>s.allowed&&s.available).slice(0,5);rebuild();},
    toolResults(results){for(const result of (results||[]).slice(0,8)){
      // Only a completed authoritative result can light a target; no live start event exists.
      const target=String(result.resolved_target||'');
      let n=nodes.find(n=>n.id==='app:'+target||n.id==='device:'+target);
      if(!n){const id='tool:'+String(result.action||'action');let tool=observation.tools.find(t=>t.id===id);
        if(!tool&&observation.tools.length<3){tool={id,kind:'tool',label:'Результат действия',detail:'Сервер вернул результат. '+(result.success?'Проверка завершена.':'Действие не выполнено.')};observation.tools.push(tool);rebuild();}n=nodes.find(n=>n.id===id);
      }
      if(n?.kind==='tool'){const detail='Сервер вернул результат. '+(result.success?'Проверка завершена.':'Действие не выполнено.');n.detail=detail;const stored=observation.tools.find(t=>t.id===n.id);if(stored)stored.detail=detail;if(selected===n.id)inspect();}
      if(n)n.active=performance.now()+2000;
    }if(results?.length){toolUntil=performance.now()+2000;clearTimeout(toolTimer);toolTimer=setTimeout(()=>{toolUntil=0;redraw();},2000);redraw();}},
    reset(){observation.conversation=false;observation.files=[];observation.tools=[];toolUntil=0;clearTimeout(toolTimer);mode='idle';selected='assistant';rebuild();},
    // Small diagnostic snapshot, without filenames, paths or document content.
    stats(){return {nodes:nodes.length,edges:Math.max(0,nodes.length-1),frames:frameCount,scheduled:timer!==null,reduced,low,visible:isVisible(),mode:effective(),amplitude:amplitude.sample(),dpr:factor,pixels:canvas.width*canvas.height,settling,...timing()};}
  };
  document.fonts?.addEventListener('loadingdone',()=>{for(const n of nodes)n.labelCache=null;redraw();});
  document.fonts?.ready.then(()=>{for(const n of nodes)n.labelCache=null;redraw();});
  rebuild();resize();
})();
