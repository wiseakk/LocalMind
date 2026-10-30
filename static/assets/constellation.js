/* Bounded Canvas 2D graph. Entities are observations, never inferred thoughts. */
(() => {
  'use strict';
  const get=id=>document.getElementById(id),canvas=get('constellation');
  // jsdom does not implement Canvas; the accessible graph remains fully usable.
  const ctx=typeof window.CanvasRenderingContext2D==='function'?canvas.getContext('2d',{alpha:false}):null;
  const MAX_NODES=36,TAU=Math.PI*2;
  const kinds={assistant:'АССИСТЕНТ',memory:'ПАМЯТЬ СЕССИИ',conversation:'ДИАЛОГ',topic:'ТЕМА',app:'ПРИЛОЖЕНИЕ',device:'УСТРОЙСТВО',file:'ДОКУМЕНТ',source:'ИСТОЧНИК',tool:'ДЕЙСТВИЕ'};
  const activityNames={idle:'Спокойная орбита',listening:'Слушаю · входной звук',transcribing:'Распознавание · ожидаем текст',generating:'Формируется ответ',speaking:'Озвучка · выходной звук',tool:'Получен результат действия'};
  let edges=[],displayMode='ambient';
  let nodes=[],selected='assistant',mode='idle',reduced=false,low=false,visible=true,closing=false;
  let panelVisible=true;
  let width=1,height=1,timer=null,last=0,frameCount=0,dirty=true,drag=null,parallaxX=0,parallaxY=0,toolUntil=0,toolTimer=null;
  let factor=1,quality=1.5,background=null,starfield=null,cacheDirty=true,announced=null;
  let sampledDpr=window.devicePixelRatio||1,resolutionTimer=null;
  let settling=true,settleTime=0,stableSteps=0,accumulator=0,geometryScale=36;
  let drawMean=0,qualityFrames=0,diagnostics=null,overlayLast=0,sampleIndex=0,sampleCount=0;
  const intervals=new Float32Array(180),costs=new Float32Array(180),glows=new Map();
  function wakePhysics(){settling=true;settleTime=0;stableSteps=0;}
  const particles=Array.from({length:52},(_,i)=>({x:((i*73+19)%251)/251,y:((i*117+7)%257)/257,r:i%7===0?1.15:.55}));
  const observation={apps:[],devices:[],files:[],sources:[],usedSources:[],conversation:false,topics:[],tools:[]};
  const displayModes=new Set(['ambient','focus','map','devices','files']);
  const mentioned=(text,value)=>typeof value==='string'&&value.length>=3&&text.toLocaleLowerCase().includes(value.toLocaleLowerCase());
  function topicFor(text){let hash=2166136261;for(const char of text)hash=Math.imul(hash^char.charCodeAt(0),16777619);return 'topic:'+(hash>>>0).toString(36);}
  function remember(text){if(typeof text!=='string'||!text.trim())return;const clean=text.trim().slice(0,2000),id=topicFor(clean);if(observation.topics.some(t=>t.id===id))return;observation.topics.push({id,text:clean});observation.topics=observation.topics.slice(-5);}
  function setMode(value){if(!displayModes.has(value)||displayMode===value)return;displayMode=value;get('skyPanel').dataset.displayMode=value;const select=get('constellationMode');if(select)select.value=value;rebuild();redraw();}
  const escapedLabel=(value,fallback)=>typeof value==='string'?value.slice(0,80):fallback;
  function rebuild(){
    const items=[],relationships=[];
    const add=(node,parent,relation)=>{
      if(items.length>=MAX_NODES||items.some(n=>n.id===node.id))return;
      items.push(node);if(parent&&relationships.length<MAX_NODES-1)relationships.push({from:parent,to:node.id,relation});
    };
    add({id:'assistant',kind:'assistant',label:'LocalMind',detail:'Локальный контекст. Связи показывают ссылки в диалоге и результаты сервера; выбор узла не выдаёт разрешений.'});
    const devicesOnly=displayMode==='devices',filesOnly=displayMode==='files';
    if(observation.conversation&&!devicesOnly&&!filesOnly){
      add({id:'memory',kind:'memory',label:'Память сессии',detail:'Контекст текущего разговора в памяти сервера. Это не постоянная память и не разрешение повторять действия.'},'assistant','контекст сессии');
      add({id:'conversation',kind:'conversation',label:'Текущий диалог',detail:'Сообщения активного разговора. Архивная история не восстанавливает разрешения и не запускает действия.'},'memory','активный разговор');
      const topics=displayMode==='focus'?observation.topics.slice(-1):observation.topics;
      for(const topic of topics)add({id:topic.id,kind:'topic',label:topic.text.replace(/\s+/g,' ').slice(0,42),detail:'Тема из сообщения пользователя: '+topic.text.slice(0,160)},'conversation','сообщение пользователя');
    }
    const topics=displayMode==='focus'?observation.topics.slice(-1):observation.topics;
    const reference=(...values)=>{
      const key=values[0];
      const topic=topics.find(t=>t.references?.has(key)||values.some(value=>mentioned(t.text,value)));
      if(topic){topic.references??=new Set();topic.references.add(key);}
      return topic&&items.some(n=>n.id===topic.id)?topic.id:undefined;
    };
    const contextParent=items.some(n=>n.id==='conversation')?'conversation':'assistant';
    if(!devicesOnly)for(const file of observation.files){
      const state=file.state||'ready',inContext=state==='added'||state==='context'||file.added===true;
      add({id:'file:'+file.id,kind:'file',label:escapedLabel(file.label,'Документ'),detail:inContext?'Сервер подтвердил добавление извлечённого текста в контекст. Источник — выбранный документ.':'Выбранный локальный файл. '+(state==='image'||file.image?'Только превью: визуальное понимание не заявлено.':'Текст ещё не добавлен в контекст модели.')},reference('file:'+file.id,file.label)||contextParent,inContext?'добавлен в контекст':'выбран пользователем');
    }
    if(!devicesOnly)for(const source of observation.usedSources){
      add({id:'source:'+source.id,kind:'source',label:'Источник ответа',detail:'Ответ сервера указал локальный источник'+(Number.isInteger(source.line_start)?', строки '+source.line_start+'–'+source.line_end:'')+'. Содержимое — справка, не разрешение действий.'},contextParent,'источник ответа');
    }
    if(!devicesOnly&&!filesOnly)for(const app of observation.apps){
      const parent=reference('app:'+app.id,app.name,app.id),used=observation.tools.find(t=>t.target===app.id);
      if(!parent&&!used)continue;
      add({id:'app:'+app.id,kind:'app',label:escapedLabel(app.name,'Приложение'),detail:app.allowed?'Обнаружено в каталоге. Разрешение запуска выдано пользователем.':'Обнаружено в каталоге. Обнаружение не предоставляет разрешение запуска.'},parent||contextParent,parent?'упомянуто в сообщении':'цель результата');
    }
    if(!filesOnly)for(const [i,device] of observation.devices.entries()){
      const parent=reference('device:'+device.id,device.name,device.id),used=observation.tools.find(t=>t.target===String(device.id));
      if(!devicesOnly&&!parent&&!used)continue;
      const state=device.state===true?'включено':device.state===false?'выключено':'неизвестно';
      add({id:'device:'+String(device.id??i),kind:'device',label:escapedLabel(device.name,'Устройство'),detail:device.demo?'DEMO · симуляция. Состояние симуляции: '+state+'. Физическое устройство не переключается.':'REAL · настроенная цель Home Assistant. Принятая команда не подтверждает физическое состояние.'},parent||contextParent,devicesOnly?'настроено на сервере':parent?'упомянуто в сообщении':'цель результата');
    }
    if(!devicesOnly&&!filesOnly)for(const tool of observation.tools){
      const target=items.find(n=>n.id==='app:'+tool.target||n.id==='device:'+tool.target);
      add(tool,target?.id||reference(tool.requested)||contextParent,'результат сервера');
    }
    const next=items;
    edges=relationships.filter(e=>next.some(n=>n.id===e.from)&&next.some(n=>n.id===e.to));
    const topology=next.length!==nodes.length||next.some((n,i)=>n.id!==nodes[i]?.id);
    const labels=topology||next.some((n,i)=>n.label!==nodes[i].label);
    // Polls and every completed turn repeat observations. Keep live objects,
    // dragged targets, cached labels and the settled solver when nothing changed.
    if(!topology&&next.every((n,i)=>n.kind===nodes[i].kind&&n.label===nodes[i].label&&n.detail===nodes[i].detail))return;
    const old=new Map(nodes.map(n=>[n.id,n]));
    nodes=next.map((n,i)=>{
      const prior=old.get(n.id),angle=i*2.39996;
      const ring=i===0?0:(.55+((i*7)%5)*.11);
      if(prior){
        if(prior.label!==n.label||prior.kind!==n.kind)prior.labelCache=null;
        if(prior.index!==i){prior.tx=Math.cos(angle)*ring;prior.ty=Math.sin(angle)*ring;}
        Object.assign(prior,n,{index:i});return prior;
      }
      return {...n,x:reduced||low?Math.cos(angle)*ring:0,y:reduced||low?Math.sin(angle)*ring:0,vx:0,vy:0,tx:Math.cos(angle)*ring,ty:Math.sin(angle)*ring,active:0,sx:0,sy:0,index:i,labelCache:null};
    });
    if(drag&&!nodes.includes(drag))drag=null;
    if(!nodes.some(n=>n.id===selected))selected='assistant';
    if(labels){
      const options=nodes.map(n=>{const option=document.createElement('option');option.value=n.id;option.textContent=n.label;return option;});
      get('nodeSelect').replaceChildren(...options);get('nodeSelect').value=selected;
    }
    if(topology){get('graphCount').textContent=nodes.length+' узл. · '+edges.length+' связ.';wakePhysics();}
    inspect();redraw();
  }
  function inspect(){
    const n=nodes.find(n=>n.id===selected)||nodes[0];
    get('nodeTitle').textContent=n.label;get('nodeType').textContent=kinds[n.kind];
    const edge=edges.find(e=>e.to===n.id);
    get('nodeDetail').textContent=n.detail+(edge?' Связь: '+edge.relation+'.':'');
    get('nodeSelect').value=n.id;dirty=true;
  }
  function select(id){if(!nodes.some(n=>n.id===id))return;selected=id;inspect();redraw();}
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
    b.fillStyle='#0b0a0e';b.fillRect(0,0,width,height);b.strokeStyle='#a881cd09';b.lineWidth=1;
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
    for(const [i,edge] of edges.entries()){
      const root=nodes.find(n=>n.id===edge.from),n=nodes.find(n=>n.id===edge.to);
      const on=n.id===selected||root.id===selected||n.active>now;
      ctx.strokeStyle=on?'#b697dd77':active?'#a17cc935':'#86709d27';ctx.lineWidth=on?1.1:.65;
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
      // Actual time-domain samples share this renderer's existing frame chain.
      // No waveform or animation is invented while playback is paused/stopped.
      if(root&&audioActive()&&!reduced&&!low){
        ctx.beginPath();ctx.strokeStyle='#d7b8e6aa';ctx.lineWidth=1.2;
        for(let i=0;i<amplitude.buffer.length;i+=4){
          const wx=x-44+i/amplitude.buffer.length*88;
          const wy=y+48+(amplitude.buffer[i]-128)/128*18;
          if(i===0)ctx.moveTo(wx,wy);else ctx.lineTo(wx,wy);
        }
        ctx.stroke();
      }
    }
    ctx.globalAlpha=1;
  }
  function isVisible(){return visible&&panelVisible&&!document.hidden&&!closing;}
  function continuous(){return !reduced&&!low;}
  function stopFrames(){if(timer!==null)cancelAnimationFrame(timer);timer=null;clearTimeout(resolutionTimer);resolutionTimer=null;last=0;accumulator=0;sampleCount=sampleIndex=0;if(diagnostics)diagnostics.textContent='Canvas · приостановлено';}
  function sampleResolution(){if(sampledDpr!==(window.devicePixelRatio||1))resolutionChanged();}
  function watchQuietResolution(){
    // DPR changes (including emulation) may deliver neither resize nor a
    // media-query event. Quiet modes have no frames: check one scalar per second,
    // without drawing or reading layout unless resolution actually changed.
    if(resolutionTimer!==null||!ctx||!isVisible()||continuous())return;
    resolutionTimer=setTimeout(()=>{resolutionTimer=null;if(!isVisible())return;sampleResolution();watchQuietResolution();},1000);
  }
  function timing(){
    const count=sampleCount,sorted=Array.from(intervals.subarray(0,count)).sort((a,b)=>a-b);
    let total=0,drawTotal=0;for(let i=0;i<count;i++){total+=intervals[i];drawTotal+=costs[i];}
    return {fps:total?1000*count/total:0,p95FrameMs:count?sorted[Math.min(count-1,Math.floor(count*.95))]:0,meanDrawMs:count?drawTotal/count:0};
  }
  function schedule(){
    if(timer!==null||!ctx||!isVisible())return;
    timer=requestAnimationFrame(now=>{timer=null;if(!isVisible())return;
      sampleResolution();
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
  function redraw(){dirty=true;watchQuietResolution();schedule();}
  function resize(){
    const rect=canvas.getBoundingClientRect();
    const w=Math.max(1,canvas.clientWidth||rect.width),h=Math.max(1,canvas.clientHeight||rect.height);
    const dpr=low?1:Math.min(quality,(window.devicePixelRatio||1)*Math.max(1,rect.width/w));
    // Absolute pixel cap also protects unusually large/high-DPI monitors.
    const nextFactor=Math.min(dpr,Math.sqrt(1600000/(w*h)));
    if(w!==width||h!==height||Math.abs(nextFactor-factor)>.01||!background){
      width=w;height=h;factor=nextFactor;geometryScale=Math.max(36,Math.min(width*.42,height*.38,420));
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
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopFrames();else resolutionChanged();});
  if(window.ResizeObserver)new ResizeObserver(resize).observe(canvas);
  window.addEventListener('resize',resize);
  // ResizeObserver observes CSS geometry, not backing resolution. A monitor/DPR
  // transition can leave the CSS size unchanged; re-arm after every transition.
  let resolutionQuery=null;
  function watchResolution(){
    resolutionQuery?.removeEventListener('change',resolutionChanged);
    sampledDpr=window.devicePixelRatio||1;
    resolutionQuery=window.matchMedia?.(`(resolution: ${sampledDpr}dppx)`);
    resolutionQuery?.addEventListener('change',resolutionChanged);
  }
  function resolutionChanged(){watchResolution();resize();}
  if(window.IntersectionObserver)new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(!visible)stopFrames();else resolutionChanged();}).observe(canvas);
  window.addEventListener('pagehide',()=>{closing=true;stopFrames();resolutionQuery?.removeEventListener('change',resolutionChanged);clearTimeout(toolTimer);amplitude.stop();amplitude.context?.close().catch(()=>{});amplitude.context=null;});
  window.addEventListener('pageshow',()=>{closing=false;watchResolution();resize();});
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
    setVisible(value){if(panelVisible===Boolean(value))return;panelVisible=Boolean(value);if(panelVisible)resolutionChanged();else stopFrames();},
    configure(options){if(reduced===options.reduced&&low===options.low)return;reduced=options.reduced;low=options.low;stopFrames();for(const n of nodes)n.vx=n.vy=0;wakePhysics();resize();},
    setDiagnostics(enabled){
      if(enabled&&!diagnostics){diagnostics=document.createElement('output');diagnostics.className='canvas-diagnostics';diagnostics.setAttribute('aria-hidden','true');canvas.parentElement.append(diagnostics);}
      else if(!enabled&&diagnostics){diagnostics.remove();diagnostics=null;}overlayLast=0;redraw();
    },
    setMode,
    observeInfo(info){observation.devices=(info.devices||[]).slice(0,8).map(d=>({...d,demo:info.demo}));rebuild();},
    observeApps(apps){observation.apps=apps.slice(0,10);rebuild();},
    observeConversation(text,messages){observation.conversation=true;for(const message of (messages||[]).slice(-10))if(message.role==='user')remember(message.content);remember(text);rebuild();},
    setFiles(files){observation.files=files.slice(0,8);rebuild();},
    setSources(sources){observation.sources=sources.filter(s=>s.allowed&&s.available).slice(0,5);},
    observeSources(sources){observation.usedSources=(sources||[]).slice(0,5).map((s,i)=>({...s,id:String(s.id||s.source_id||i)}));rebuild();},
    toolResults(results){for(const result of (results||[]).slice(0,8)){
      // Only server results create action relationships. Requested target and
      // observed state remain distinct, particularly for REAL request_accepted.
      const target=String(result.resolved_target||''),action=String(result.action||'action');
      const id='tool:'+action+':'+target;
      const accepted=result.execution_status==='request_accepted';
      const detail=(result.mode==='DEMO'?'DEMO · симуляция. ':'')+(result.success?(accepted?'Команда принята; физическое состояние не подтверждено.':'Сервер вернул результат: '+String(result.execution_status||'завершено')+'.'):'Действие не выполнено.')+' Наблюдаемое состояние: '+String(result.observed_state||'не сообщено')+'.';
      let tool=observation.tools.find(t=>t.id===id);
      if(!tool&&observation.tools.length<5){tool={id,kind:'tool',label:escapedLabel(action,'Действие'),detail,target,requested:String(result.requested_target||'')};observation.tools.push(tool);}
      else if(tool)tool.detail=detail;
      rebuild();const n=nodes.find(n=>n.id===id);if(n)n.active=performance.now()+2000;
    }if(results?.length){toolUntil=performance.now()+2000;clearTimeout(toolTimer);toolTimer=setTimeout(()=>{toolUntil=0;redraw();},2000);redraw();}},
    reset(){observation.conversation=false;observation.topics=[];observation.files=[];observation.usedSources=[];observation.tools=[];toolUntil=0;clearTimeout(toolTimer);mode='idle';selected='assistant';rebuild();inspect();announce();redraw();},
    // Small diagnostic snapshot, without filenames, paths or document content.
    stats({timings=true}={}){return {nodes:nodes.length,edges:edges.length,displayMode,frames:frameCount,scheduled:timer!==null,reduced,low,visible:isVisible(),mode:effective(),amplitude:amplitude.sample(),dpr:factor,pixels:canvas.width*canvas.height,settling,...(timings?timing():{})};}
  };
  document.fonts?.addEventListener('loadingdone',()=>{for(const n of nodes)n.labelCache=null;redraw();});
  document.fonts?.ready.then(()=>{for(const n of nodes)n.labelCache=null;redraw();});
  get('constellationMode')?.addEventListener('change',e=>setMode(e.target.value));
  get('skyPanel').dataset.displayMode=displayMode;watchResolution();rebuild();resize();
})();
