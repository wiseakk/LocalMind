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
  let width=1,height=1,timer=null,last=0,frameCount=0,dirty=true,drag=null,parallaxX=0,parallaxY=0,toolUntil=0,toolTimer=null;
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
      return {...n,x:prior?.x??(reduced||low?Math.cos(angle)*ring:0),y:prior?.y??(reduced||low?Math.sin(angle)*ring:0),vx:prior?.vx??0,vy:prior?.vy??0,tx:Math.cos(angle)*ring,ty:Math.sin(angle)*ring,active:prior?.active??0};
    });
    if(!nodes.some(n=>n.id===selected))selected='assistant';
    const options=nodes.map(n=>{const option=document.createElement('option');option.value=n.id;option.textContent=n.label;return option;});
    get('nodeSelect').replaceChildren(...options);get('nodeSelect').value=selected;
    get('graphCount').textContent=nodes.length+' узл. · '+Math.max(0,nodes.length-1)+' связ.';
    inspect();redraw();
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
  function announce(){const m=effective();get('skyPanel').dataset.activity=m;if(get('graphActivity').textContent!==activityNames[m])get('graphActivity').textContent=activityNames[m];}
  function setActivity(value){mode=Object.hasOwn(activityNames,value)?value:'idle';announce();redraw();}
  const scale=()=>Math.max(36,Math.min(width*.38,height*.34,220));
  function screen(n){const s=scale();return [width*.5+n.x*s+parallaxX,height*.47+n.y*s+parallaxY];}
  function physics(now){
    if(reduced||low)return;
    for(let i=1;i<nodes.length;i++){
      const n=nodes[i];if(drag===n)continue;
      n.vx+=(n.tx+Math.sin(now*.00013+i)*.014-n.x)*.009;n.vy+=(n.ty+Math.cos(now*.00011+i)*.014-n.y)*.009;
      for(let j=1;j<i;j++){
        const o=nodes[j],dx=n.x-o.x,dy=n.y-o.y,d2=Math.max(.02,dx*dx+dy*dy);
        if(d2<.3){const f=.00016/d2;n.vx+=dx*f;n.vy+=dy*f;if(drag!==o){o.vx-=dx*f;o.vy-=dy*f;}}
      }
      n.vx*=.85;n.vy*=.85;n.x=Math.max(-1.07,Math.min(1.07,n.x+n.vx));n.y=Math.max(-1.07,Math.min(1.07,n.y+n.vy));
    }
  }
  function draw(now){
    frameCount++;dirty=false;announce();if(!ctx)return;
    physics(now);const m=effective(),active=m!=='idle',pulse=reduced||low?0:Math.sin(now*.0018)*.5+.5;
    const level=amplitude.sample();
    ctx.fillStyle='#121116';ctx.fillRect(0,0,width,height);
    ctx.fillStyle='#9b82bb';
    for(let i=0;i<particles.length;i++){
      const p=particles[i];const drift=reduced||low?0:Math.sin(now*.00007+i)*2;
      ctx.globalAlpha=.17+(i%3)*.09;ctx.beginPath();ctx.arc(p.x*width+drift,p.y*height,p.r,0,TAU);ctx.fill();
    }
    ctx.globalAlpha=1;
    // Orientation rings are decorative, not entities or private memories.
    ctx.strokeStyle='#a881cd12';ctx.lineWidth=1;
    for(const r of [.55,1,1.4]){ctx.beginPath();ctx.ellipse(width*.5,height*.47,scale()*r,scale()*r*.77,-.34,0,TAU);ctx.stroke();}
    const root=nodes[0],rp=screen(root);
    for(let i=1;i<nodes.length;i++){
      const n=nodes[i],p=screen(n),on=n.id===selected||n.active>now;
      ctx.strokeStyle=on?'#b697dd88':active?'#a17cc94d':'#86709d33';ctx.lineWidth=on?1.2:.7;
      ctx.beginPath();ctx.moveTo(rp[0],rp[1]);ctx.quadraticCurveTo((rp[0]+p[0])*.5+10,(rp[1]+p[1])*.5-12,p[0],p[1]);ctx.stroke();
      if(!reduced&&!low&&(m==='generating'||m==='transcribing'||n.active>now)){
        const t=((now*.00023+i*.17)%1),x=rp[0]+(p[0]-rp[0])*t,y=rp[1]+(p[1]-rp[1])*t;
        ctx.fillStyle='#d3b4ef';ctx.beginPath();ctx.arc(x,y,1.2,0,TAU);ctx.fill();
      }
    }
    for(const n of nodes){
      const [x,y]=screen(n),root=n.kind==='assistant',on=n.id===selected||n.active>now;
      const color=n.kind==='device'?'#ce718c':n.kind==='file'?'#c2bbd0':root?'#e1c4ff':'#ae85d7';
      const r=root?7+(active?pulse*1.1:0)+level*10:on?4.5:3;
      if(!low){ctx.shadowColor=color;ctx.shadowBlur=root?24+level*20:on?14:6;}
      ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,r,0,TAU);ctx.fill();ctx.shadowBlur=0;
      if(root||on){ctx.strokeStyle=color+'44';ctx.lineWidth=1;ctx.beginPath();ctx.arc(x,y,r+7+(root?pulse*4:0),0,TAU);ctx.stroke();}
      ctx.font=(root?'500 12px':'10px')+' Onest, sans-serif';ctx.textAlign='center';ctx.fillStyle=root?'#ddc7f5':on?'#e1d5ef':'#a49aaf';
      const label=n.label.length>23?n.label.slice(0,21)+'…':n.label;ctx.fillText(label,x,y+r+(root?25:17),Math.max(80,width*.36));
    }
    ctx.globalAlpha=1;
  }
  function isVisible(){return visible&&!document.hidden&&!closing;}
  function continuous(){return !reduced&&!low;}
  function schedule(){
    if(timer!==null||!ctx||!isVisible())return;
    // Timed frames avoid 60/144Hz idle rAF wakeups. Idle 12fps, active 30fps.
    const interval=low?84:effective()==='idle'?84:34;
    timer=setTimeout(()=>{timer=null;if(!isVisible())return;const now=performance.now();
      if(dirty||continuous()||drag||audioActive()){draw(now);last=now;}
      if(continuous()||drag||audioActive())schedule();
    },Math.max(0,interval-(performance.now()-last)));
  }
  function redraw(){dirty=true;schedule();}
  function resize(){
    const rect=canvas.getBoundingClientRect();width=Math.max(1,rect.width);height=Math.max(1,rect.height);
    const dpr=low?1:Math.min(1.5,window.devicePixelRatio||1);
    // Absolute pixel cap also protects unusually large/high-DPI monitors.
    const factor=Math.min(dpr,Math.sqrt(1600000/(width*height)));
    canvas.width=Math.max(1,Math.floor(width*factor));canvas.height=Math.max(1,Math.floor(height*factor));
    ctx?.setTransform(factor,0,0,factor,0,0);redraw();
  }
  function hit(e){const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;return nodes.find(n=>{const p=screen(n);return Math.hypot(p[0]-x,p[1]-y)<22;});}
  canvas.addEventListener('pointerdown',e=>{const n=hit(e);if(!n)return;select(n.id);drag=n;canvas.setPointerCapture?.(e.pointerId);redraw();});
  canvas.addEventListener('pointermove',e=>{
    const r=canvas.getBoundingClientRect();
    if(drag){const s=scale();drag.x=drag.tx=Math.max(-1.05,Math.min(1.05,(e.clientX-r.left-width*.5)/s));drag.y=drag.ty=Math.max(-1.05,Math.min(1.05,(e.clientY-r.top-height*.47)/s));drag.vx=drag.vy=0;redraw();}
    else if(!low&&!reduced){parallaxX=(e.clientX-r.left-width*.5)*.008;parallaxY=(e.clientY-r.top-height*.5)*.008;redraw();}
  });
  const release=()=>{drag=null;redraw();};canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);canvas.addEventListener('lostpointercapture',release);
  canvas.addEventListener('pointerleave',()=>{parallaxX=parallaxY=0;redraw();});
  get('nodeSelect').addEventListener('change',e=>select(e.target.value));
  function move(dx,dy){const n=nodes.find(n=>n.id===selected);n.x=n.tx=Math.max(-1,Math.min(1,n.x+dx));n.y=n.ty=Math.max(-1,Math.min(1,n.y+dy));n.vx=n.vy=0;redraw();}
  get('nodeSelect').addEventListener('keydown',e=>{const d=e.altKey&&{ArrowUp:[0,-.08],ArrowDown:[0,.08],ArrowLeft:[-.08,0],ArrowRight:[.08,0]}[e.key];if(d){e.preventDefault();move(...d);}});
  get('moveNode').addEventListener('click',()=>move(.12,0));
  get('centerGraph').addEventListener('click',()=>{nodes=[];parallaxX=parallaxY=0;rebuild();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(timer);timer=null;}else redraw();});
  if(window.ResizeObserver)new ResizeObserver(resize).observe(canvas);else window.addEventListener('resize',resize);
  if(window.IntersectionObserver)new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(!visible){clearTimeout(timer);timer=null;}else redraw();}).observe(canvas);
  window.addEventListener('pagehide',()=>{closing=true;clearTimeout(timer);clearTimeout(toolTimer);timer=null;amplitude.stop();amplitude.context?.close().catch(()=>{});amplitude.context=null;});
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
    configure(options){reduced=options.reduced;low=options.low;clearTimeout(timer);timer=null;for(const n of nodes)n.vx=n.vy=0;resize();},
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
    stats(){return {nodes:nodes.length,edges:Math.max(0,nodes.length-1),frames:frameCount,scheduled:timer!==null,reduced,low,visible:isVisible(),mode:effective(),amplitude:amplitude.sample()};}
  };
  rebuild();resize();
})();
