/* DOM checks complement the separate browser suite; no visual claims. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html=fs.readFileSync('static/index.html','utf8').replace(/^\uFEFF/,'');
const scripts=['marked.umd.js','purify.min.js','katex.min.js','localmind-rich.js','icons.js','constellation.js','attachments.js','speech.js','models.js','app.js','interface.js'];
let passed=0;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
function makeDom(fetcher,setup) {
  const dom=new JSDOM(html,{url:'http://127.0.0.1:8765',runScripts:'dangerously',pretendToBeVisual:true});
  const w=dom.window;
  w.TextDecoder=TextDecoder;w.TextEncoder=TextEncoder;w.Response=Response;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
  w.HTMLDialogElement.prototype.close=function(){this.open=false};
  w.fetch=fetcher || (async()=>Response.json({server_instance:'test',demo:true,model:'test',devices:[],voice:{voices:[]}}));
  setup?.(w);
  for(const s of scripts){const script=w.document.createElement('script');script.textContent=fs.readFileSync('static/assets/'+s,'utf8');w.document.head.append(script)}
  return dom;
}
async function run(name,fn){await fn();passed++;console.log('PASS '+name)}
// Controlled rAF and Canvas submission spy: lifecycle/cache tests, not GPU/FPS evidence.
function makeCanvasDom(){
  return makeDom(null,w=>{
    const frames=new Map(),contexts=new WeakMap();let id=0;
    const probe=w.canvasProbe={text:0,measure:0,blur:0,layers:0,queries:[],arcs:[]};
    const quietTimers=new Map(),nativeTimeout=w.setTimeout.bind(w),nativeClear=w.clearTimeout.bind(w);let quietId=0;
    w.setTimeout=(callback,delay,...args)=>{if(delay!==1000)return nativeTimeout(callback,delay,...args);const key=--quietId;quietTimers.set(key,()=>callback(...args));return key;};
    w.clearTimeout=key=>{if(!quietTimers.delete(key))nativeClear(key);};
    probe.quietPending=()=>quietTimers.size;
    probe.checkResolution=()=>{const callbacks=[...quietTimers.values()];quietTimers.clear();callbacks.forEach(fn=>fn());assert.ok(quietTimers.size<=1,'one quiet resolution check');};
    Object.defineProperty(w.document.querySelector('.stage'),'clientWidth',{value:1200});
    w.requestAnimationFrame=callback=>{frames.set(++id,callback);return id};
    w.cancelAnimationFrame=id=>frames.delete(id);
    probe.step=now=>{probe.arcs=[];const callbacks=[...frames.values()];frames.clear();callbacks.forEach(fn=>fn(now));assert.ok(frames.size<=1,'one animation chain')};
    probe.pending=()=>frames.size;
    w.CanvasRenderingContext2D=function(){};
    w.HTMLCanvasElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:500,height:400});
    w.HTMLCanvasElement.prototype.getContext=function(){
      if(!contexts.has(this)){
        probe.layers++;const main=this.id==='constellation';
        contexts.set(this,new Proxy({
          measureText:text=>{probe.measure++;return {width:text.length*6}},
          fillText:()=>probe.text++,arc:(x,y,r)=>{if(main)probe.arcs.push({x,y,r})}
        },{get:(target,key)=>key in target?target[key]:()=>{},set:(target,key,value)=>{if(key==='shadowBlur'&&value)probe.blur++;target[key]=value;return true}}));
      }return contexts.get(this);
    };
    w.matchMedia=media=>{const query=new w.EventTarget();query.media=media;query.matches=false;probe.queries.push(query);return query};
    w.document.fonts=new w.EventTarget();w.document.fonts.ready=Promise.resolve();
  });
}
(async()=>{
  await run('Silero defaults and explicit voice preferences survive reload without switching engines',async()=>{
    for(const saved of [null,'ru_RU-denis-medium','silero-v5_6-ru','chatterbox-v3-ru','../../unknown']){
      const dom=makeDom(null,w=>{if(saved)w.localStorage.setItem('localmind.ttsVoice.v1',saved)});
      try{
        const w=dom.window,select=w.document.getElementById('ttsVoice');
        assert.equal(select.value,saved&& !saved.startsWith('../')?saved:'silero-v5_6-ru');
        select.value='ru_RU-denis-medium';select.dispatchEvent(new w.Event('change'));
        assert.equal(w.localStorage.getItem('localmind.ttsVoice.v1'),'ru_RU-denis-medium');
      }finally{dom.window.close()}
    }
  });
  await run('stream deltas and length cuts keep complete and partial English names intact',async()=>{
    for(const [head,tail,name] of [['World of W','arcraft','World of Warcraft'],['Arthas M','enethil','Arthas Menethil'],['The Frozen Throne','','The Frozen Throne']]){
      const dom=makeDom();
      try{
        const w=dom.window,calls=[];
        const speech=new w.LocalMindSpeech({request:text=>{calls.push(text);return new Promise(()=>{})},
          enabled:()=>true,voice:()=> 'silero-v5_6-ru',report:()=>{}});
        speech.start();speech.feed('слово '.repeat(39)+head);speech.feed(tail,true);
        assert.equal(calls.length,1);assert.equal(calls[0],'слово '.repeat(39).trim());
        assert.equal(speech.session.texts.map(item=>item.text).join(' '),name);
        speech.cancel();
      }finally{dom.window.close()}
    }
  });
  await run('every title delta split near the length boundary preserves entities and final flushing',async()=>{
    const dom=makeDom();
    try{
      const w=dom.window;
      const names=['Warcraft II','Warcraft III','Diablo Immortal','Diablo IV','Blizzard Entertainment',
        'warcraft iii','DIABLO IMMORTAL','Blizzard   Entertainment','StarCraft II','StarCraft III',
        'Zephyr XLII','Command & Conquer','Command&Conquer','C&C','R & D','труд & отдых',
        '1977 году','2014 году','2002 году','3.14','3,14','192.168.1.1','v2026.1','2026-10-31',
        'Apple II','Node.js','Python 3.14','Python   3.14','Версия Node.js 24.19.0',
        'Версия   Node.js   24.19.0','Версия Python v3.14','Версия ПО 31.10.2026',
        '1997 и 2002 годах','1997, 2000 и 2003 годах','1997, 2000, и 2003 году',
        '1997   и   2002   годах','2000 или 2003 годах'];
      for(const name of names)for(let start=216;start<=244;start++)for(let split=0;split<=name.length;split++){
        const prefix='слово '.repeat(Math.floor(start/6))+'а'.repeat(start%6)+' ';
        const original=prefix+name+'. Затем продолжаем разговор.';
        const speech=new w.LocalMindSpeech({request:()=>{throw Error('queue-only test')},enabled:()=>true,
          voice:()=> 'silero-v5_6-ru',report:message=>{throw Error(message)}});
        speech.pump=()=>{};speech.start();
        speech.feed(prefix+name.slice(0,split));
        speech.feed(name.slice(split)+'. Затем продолжаем разговор.',true);
        const chunks=speech.session.texts.map(item=>item.text);
        assert.ok(chunks.some(text=>text.includes(name)),`${name}: start=${start}, delta split=${split}`);
        assert.equal(chunks.join(' ').replace(/\s+/g,' ').trim(),original.replace(/\s+/g,' ').trim());
        assert.equal(speech.session.buffer.trim(),'');assert.equal(speech.session.done,true);
        const count=chunks.length;speech.feed('duplicate',true);assert.equal(speech.session.texts.length,count);
        speech.cancel();
      }
      // A final incomplete prefix must be flushed instead of waiting forever.
      for(const name of names){
        const speech=new w.LocalMindSpeech({enabled:()=>true,report:message=>{throw Error(message)}});
        speech.pump=()=>{};speech.start();speech.feed('слово '.repeat(39)+name.slice(0,5),true);
        assert.equal(speech.session.texts.map(item=>item.text).join(' '),('слово '.repeat(39).trim()+' '+name.slice(0,5)).trim());
        assert.equal(speech.session.buffer.trim(),'');speech.cancel();
      }
    }finally{dom.window.close()}
  });
  await run('contextual expressions survive character deltas and keep displayed text unchanged',async()=>{
    const answer='Apple II. В 1977 году. Вышли в 1997 и 2002 годах. В 2026 году. Python 3.14. Версия Node.js 24.19.0. Число пи примерно равно 3.14. IP-адрес 192.168.1.1.';
    const tts=[];
    const dom=makeDom(async(url,options)=>{
      if(url==='/api/info')return Response.json({server_instance:'test',demo:true,devices:[],voice:{}});
      if(url==='/api/tts'){tts.push(JSON.parse(options.body).text);return new Response(new Blob(['RIFFmock']));}
      if(url==='/api/tts/cancel')return Response.json({ok:true});
      if(url==='/api/chat/stream'){
        const events=[{type:'status',data:{action_results:[]}},
          ...Array.from(answer,(text,index)=>({type:'delta',sequence:index+1,text})),
          {type:'final',data:{answer,engine:'ollama',action_results:[]}}];
        return new Response(events.map(event=>JSON.stringify(event)).join('\n')+'\n');
      }
      throw Error('unexpected '+url);
    });
    const w=dom.window,d=w.document;
    w.URL.createObjectURL=()=> 'blob:contextual';w.URL.revokeObjectURL=()=>{};
    w.Audio=class {async play(){setTimeout(()=>this.onended?.(),0)}pause(){}};
    try{
      await pause(10);d.querySelector('#speak').checked=true;
      await w.sendText('Прочитай примеры');
      for(let i=0;i<100&&tts.length<7;i++)await pause(5);
      assert.deepEqual(tts,['Apple II. В 1977 году.','Вышли в 1997 и 2002 годах.',
        'В 2026 году.','Python 3.14.','Версия Node.js 24.19.0.',
        'Число пи примерно равно 3.14.','IP-адрес 192.168.1.1.']);
      assert.equal(d.querySelector('.rendered-message').textContent.trim(),answer);
      assert.ok(!d.querySelector('.rendered-message').textContent.includes('Пайтон'));
    }finally{w.stopSpeech();dom.window.close()}
  });
  await run('mismatched info and conversation instances reject valid PNG before any upload',async()=>{
    const calls=[];
    const dom=makeDom(async(url,options)=>{
      calls.push(url);
      if(url==='/api/conversations')return Response.json({conversation_id:'c'.repeat(32),server_instance:'live-instance'});
      return Response.json({server_instance:'constellation-test',demo:true,model:'test',devices:[],voice:{voices:[]}});
    });
    try{
      const w=dom.window;await pause(20);
      const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGPojjn/HwAF4gK2//l6AAAAAABJRU5ErkJggg==','base64');
      w.localmindAttachments.add([new w.File([png],'dot.png',{type:'image/png'})]);
      for(let i=0;i<100&&w.localmindAttachments.hasPending();i++)await pause(10);
      assert.equal(w.localmindAttachments.snapshot()[0].state,'error');
      assert.equal(calls.filter(url=>url==='/api/conversations').length,1);
      assert.equal(calls.filter(url=>url==='/api/attachments').length,0);
      assert.deepEqual([...w.localmindAttachments.contextIds()],[]);
      assert.ok(w.document.querySelector('.attachment-state').textContent.includes('Сервер перезапущен'));
    }finally{dom.window.close()}
  });
  await run('repeated graph observations preserve options, cached text, drag targets and settled physics',async()=>{
    const dom=makeCanvasDom(),w=dom.window,d=w.document,probe=w.canvasProbe,scene=w.localmindScene;
    try{
      await pause(10);
      const apps=Array.from({length:10},(_,i)=>({id:String(i),name:'Узел '+i,allowed:false}));
      scene.observeApps(apps);scene.observeConversation(apps.map(a=>a.name).join(", ")+" lamp");
      scene.observeInfo({demo:true,devices:[{id:'lamp',name:'Лампа'}]});scene.setFiles([{id:'fixture',label:'Вложение 1'}]);
      assert.equal(scene.stats().nodes,16);
      for(let now=1;now<6000;now+=1000/60)probe.step(now);
      assert.equal(scene.stats().settling,false);
      const option=d.querySelector('#nodeSelect option[value="app:0"]');
      const before={text:probe.text,measure:probe.measure,blur:probe.blur,layers:probe.layers};
      for(let i=0;i<30;i++){scene.observeApps(apps.map(app=>({...app})));scene.observeConversation();}
      probe.step(6010);
      assert.equal(scene.stats().settling,false);assert.equal(d.querySelector('#nodeSelect option[value="app:0"]'),option);
      assert.deepEqual({text:probe.text,measure:probe.measure,blur:probe.blur,layers:probe.layers},before);
      const select=d.querySelector('#nodeSelect');select.value='app:0';select.dispatchEvent(new w.Event('change'));
      scene.observeApps(apps.map((app,i)=>({...app,allowed:i===0})));
      probe.step(6020);assert.ok(d.querySelector('#nodeDetail').textContent.includes('выдано пользователем'));
      assert.equal(probe.text,before.text);assert.equal(scene.stats().settling,false);
      scene.observeApps(apps.map((app,i)=>({...app,name:i===0?'Новое имя':app.name})));
      probe.step(6030);assert.equal(probe.text,before.text+2);assert.equal(probe.measure,before.measure+1);
      assert.equal(d.querySelector('#nodeTitle').textContent,'Новое имя');
      scene.configure({reduced:true,low:false});probe.step(6040);
      const canvas=d.querySelector('#constellation');
      canvas.dispatchEvent(new w.MouseEvent('pointerdown',{clientX:250,clientY:188}));
      scene.observeConversation();
      canvas.dispatchEvent(new w.MouseEvent('pointermove',{clientX:300,clientY:220}));probe.step(6050);
      assert.deepEqual({...probe.arcs.find(p=>p.r===7)},{x:300,y:220,r:7});
      canvas.dispatchEvent(new w.Event('lostpointercapture'));
      canvas.dispatchEvent(new w.MouseEvent('pointermove',{clientX:330,clientY:240}));probe.step(6060);
      assert.deepEqual({...probe.arcs.find(p=>p.r===7)},{x:300,y:220,r:7});
      d.querySelector('#centerGraph').click();probe.step(6070);
      assert.deepEqual({...probe.arcs.find(p=>p.r===7)},{x:250,y:188,r:7});
      let sorts=0;const sort=w.Array.prototype.sort;w.Array.prototype.sort=function(...args){sorts++;return sort.apply(this,args)};
      assert.equal(scene.stats({timings:false}).fps,undefined);assert.equal(sorts,0);
      scene.stats();assert.equal(sorts,1);
      scene.reset();probe.step(6080);
      select.value='app:0';select.dispatchEvent(new w.Event('change'));scene.setActivity('generating');
      scene.reset();probe.step(6090);
      assert.equal(d.querySelector('#nodeTitle').textContent,'LocalMind');assert.equal(select.value,'assistant');
      assert.equal(d.querySelector('#skyPanel').dataset.activity,'idle');assert.equal(probe.pending(),0);
    }finally{dom.window.close()}
  });
  await run('constellation separates catalog membership from references, modes and acknowledged context',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document,scene=w.localmindScene;
    try{
      await pause(10);
      scene.observeApps([{id:'editor',name:'Редактор',allowed:false},{id:'unrelated',name:'Другое',allowed:true}]);
      scene.observeInfo({demo:false,devices:[{id:'lamp',name:'Лампа',state:false}]});
      scene.setSources([{id:'private',allowed:true,available:true,filename:'private.txt'}]);
      assert.equal(scene.stats().nodes,1);
      scene.observeConversation('Объясни RSA');scene.observeConversation('Открой editor');
      assert.equal(d.querySelectorAll('#nodeSelect option[value="app:editor"]').length,1);
      assert.equal(d.querySelectorAll('#nodeSelect option[value="app:unrelated"]').length,0);
      assert.equal(d.querySelectorAll('#nodeSelect option[value="device:lamp"]').length,0);
      assert.equal(d.querySelectorAll('#nodeSelect option[value^="source:"]').length,0);
      assert.equal(d.querySelectorAll('#nodeSelect option[value^="topic:"]').length,2);
      scene.setMode('focus');assert.equal(d.querySelectorAll('#nodeSelect option[value^="topic:"]').length,1);
      scene.setMode('devices');assert.equal(scene.stats().nodes,2);
      const select=d.querySelector('#nodeSelect');select.value='device:lamp';select.dispatchEvent(new w.Event('change'));
      assert.ok(d.querySelector('#nodeDetail').textContent.includes('не подтверждает физическое состояние'));
      scene.setFiles([{id:'doc',label:'Документ',state:'ready'},{id:'picture',label:'Изображение',state:'image'}]);
      scene.setMode('files');assert.equal(scene.stats().nodes,3);
      select.value='file:doc';select.dispatchEvent(new w.Event('change'));assert.ok(d.querySelector('#nodeDetail').textContent.includes('ещё не добавлен'));
      scene.setFiles([{id:'doc',label:'Документ',state:'added'}]);assert.ok(d.querySelector('#nodeDetail').textContent.includes('Сервер подтвердил'));
      scene.observeSources([{source_id:'reference',filename:'hidden.txt',line_start:2,line_end:5}]);
      assert.equal(d.querySelectorAll('#nodeSelect option[value="source:reference"]').length,1);
      assert.ok(!select.textContent.includes('hidden.txt'));
      scene.setMode('map');assert.equal(scene.stats().displayMode,'map');
      scene.toolResults([{action:'set_light',resolved_target:'lamp',mode:'REAL',success:true,execution_status:'request_accepted',observed_state:null}]);
      select.value='tool:set_light:lamp';select.dispatchEvent(new w.Event('change'));
      assert.ok(d.querySelector('#nodeDetail').textContent.includes('физическое состояние не подтверждено'));
      scene.setMode('ambient');assert.equal(scene.stats().displayMode,'ambient');
      assert.ok(scene.stats().edges<=35);scene.reset();assert.equal(scene.stats().nodes,1);
    }finally{dom.window.close()}
  });
  await run('DPR-only transitions re-arm resolution detection and rebuild once within pixel limits',async()=>{
    const dom=makeCanvasDom(),w=dom.window,d=w.document,probe=w.canvasProbe,scene=w.localmindScene;
    try{
      await pause(10);probe.step(10);
      const canvas=d.querySelector('#constellation'),query=()=>probe.queries.filter(q=>q.media.startsWith('(resolution:')).at(-1);
      const original=query();Object.defineProperty(w,'devicePixelRatio',{configurable:true,value:1.4});original.dispatchEvent(new w.Event('change'));probe.step(20);
      assert.equal(canvas.width,700);assert.equal(scene.stats().dpr,1.4);assert.notEqual(query(),original);
      const layers=probe.layers;original.dispatchEvent(new w.Event('change'));probe.step(30);assert.equal(probe.layers,layers);
      const previous=query();Object.defineProperty(w,'devicePixelRatio',{configurable:true,value:2});previous.dispatchEvent(new w.Event('change'));probe.step(40);
      assert.equal(scene.stats().dpr,1.5);assert.ok(scene.stats().pixels<=1600000);
      scene.configure({reduced:false,low:true});probe.step(50);assert.equal(scene.stats().dpr,1);
      const economical=probe.layers;w.dispatchEvent(new w.Event('resize'));probe.step(60);assert.equal(probe.layers,economical);
      scene.configure({reduced:false,low:true});assert.equal(probe.pending(),0);
      d.fonts.dispatchEvent(new w.Event('loadingdone'));probe.step(70);assert.ok(probe.layers>economical);
    }finally{dom.window.close()}
  });
  await run('DPR changes without browser events use existing frames or one quiet check and suspend on hide',async()=>{
    const dom=makeCanvasDom(),w=dom.window,d=w.document,probe=w.canvasProbe,scene=w.localmindScene;
    try{
      await pause(10);
      const canvas=d.querySelector('#constellation');
      Object.defineProperty(canvas,'clientWidth',{value:1440});Object.defineProperty(canvas,'clientHeight',{value:948});
      w.dispatchEvent(new w.Event('resize'));probe.step(10);
      const expected=dpr=>Math.min(1.5,dpr,Math.sqrt(1600000/(1440*948)));
      let now=20;
      for(const dpr of [1.4,2,1.25,1,2,1]){
        Object.defineProperty(w,'devicePixelRatio',{configurable:true,value:dpr});probe.step(now++);
        assert.equal(scene.stats().dpr,expected(dpr));assert.ok(scene.stats().pixels<=1600000);
        assert.equal(probe.quietPending(),0);assert.equal(probe.pending(),1);
      }
      scene.configure({reduced:true,low:false});probe.step(now++);
      assert.equal(probe.pending(),0);assert.equal(probe.quietPending(),1);
      const frames=scene.stats().frames,layers=probe.layers;
      for(let i=0;i<5;i++)probe.checkResolution();
      assert.equal(scene.stats().frames,frames);assert.equal(probe.layers,layers);assert.equal(probe.pending(),0);
      Object.defineProperty(w,'devicePixelRatio',{configurable:true,value:1.4});probe.checkResolution();probe.step(now++);
      assert.equal(scene.stats().dpr,expected(1.4));assert.equal(probe.pending(),0);
      for(let i=0;i<3;i++){
        w.dispatchEvent(new w.Event('pagehide'));assert.equal(probe.quietPending(),0);
        const queries=probe.queries.length;probe.queries.at(-1).dispatchEvent(new w.Event('change'));
        assert.equal(probe.queries.length,queries,'pagehide detached resolution listener');
        w.dispatchEvent(new w.Event('pageshow'));probe.step(now++);assert.equal(probe.quietPending(),1);
      }
      scene.setVisible(false);assert.equal(probe.quietPending(),0);scene.setVisible(true);probe.step(now++);
      Object.defineProperty(d,'hidden',{configurable:true,value:true});d.dispatchEvent(new w.Event('visibilitychange'));
      assert.equal(probe.quietPending(),0);assert.equal(probe.pending(),0);
      Object.defineProperty(w,'devicePixelRatio',{configurable:true,value:1});
      Object.defineProperty(d,'hidden',{configurable:true,value:false});d.dispatchEvent(new w.Event('visibilitychange'));probe.step(now++);
      assert.equal(scene.stats().dpr,1);assert.equal(probe.quietPending(),1);
      scene.configure({reduced:false,low:false});assert.equal(probe.quietPending(),0);
    }finally{dom.window.close()}
  });
  await run('Canvas hide/resume resets time, keeps one rAF chain and refreshes DPR on restore',async()=>{
    const dom=makeCanvasDom(),w=dom.window,d=w.document,probe=w.canvasProbe,scene=w.localmindScene;
    try{
      await pause(10);probe.step(10);
      Object.defineProperty(d,'hidden',{configurable:true,value:true});d.dispatchEvent(new w.Event('visibilitychange'));
      const frames=scene.stats().frames;assert.equal(probe.pending(),0);probe.step(100000);assert.equal(scene.stats().frames,frames);
      Object.defineProperty(d,'hidden',{configurable:true,value:false});d.dispatchEvent(new w.Event('visibilitychange'));scene.redraw();scene.redraw();
      assert.equal(probe.pending(),1);probe.step(100010);assert.equal(scene.stats().frames,frames+1);
      scene.setVisible(false);assert.equal(probe.pending(),0);scene.setVisible(true);probe.step(100020);
      w.dispatchEvent(new w.Event('pagehide'));assert.equal(probe.pending(),0);
      Object.defineProperty(w,'devicePixelRatio',{configurable:true,value:1.25});w.dispatchEvent(new w.Event('pageshow'));probe.step(200000);
      assert.equal(scene.stats().dpr,1.25);assert.equal(probe.pending(),1);
    }finally{dom.window.close()}
  });
  await run('offline Markdown, code, tables, math, currency and XSS',async()=>{
    const dom=makeDom();const w=dom.window;
    try{
      const target=w.document.createElement('div');
      w.renderLocalMindMessage(target,'# Тест\n\n- Один\n- Два\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```js\nconst price="$5";\n```\n\n\\(x^2\\)\n\n\\[y=2\\]\n\n$$z=3$$\n\n$5 и $10\n\n<img src="https://example.com/pixel" onerror="window.xss=1"><script>window.xss=1</script>[bad](javascript:alert(1))');
      assert.equal(target.querySelectorAll('.katex').length,3);
      assert.equal(target.querySelectorAll('table').length,1);assert.equal(target.querySelectorAll('li').length,2);
      assert.equal(target.querySelectorAll('img,script,[onerror]').length,0);
      assert.ok(target.textContent.includes('$5 и $10'));assert.ok(target.querySelector('pre code').textContent.includes('$5'));
      assert.equal(target.querySelector('a').getAttribute('href'),null);assert.equal(w.xss,undefined);
      w.DOMPurify=null;w.renderLocalMindMessage(target,'<img onerror="alert(1)">');assert.equal(target.children.length,0);assert.ok(target.textContent.startsWith('<img'));
    }finally{dom.window.close()}
  });
  await run('voice draft waits for review; duplicate submit once; status before delayed commentary',async()=>{
    let requests=0,release;
    const dom=makeDom(async(url)=>{
      if(url==='/api/info')return Response.json({server_instance:'test',demo:true,model:'test',devices:[],voice:{}});
      if(url==='/api/chat/stream'){
        requests++;
        const data={answer:'ДЕМО: лампа включена.',status:'ДЕМО: лампа включена.',engine:'rules',action_ms:1,llm_ms:500,action_results:[{success:true,status_text:'ДЕМО: лампа включена.',mode:'DEMO',duration_ms:1}],actions:['лампа']};
        return new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode(JSON.stringify({type:'status',data})+'\n'));release=()=>{c.enqueue(new TextEncoder().encode(JSON.stringify({type:'final',data:{...data,answer:'В симуляции лампа включена.'}})+'\n'));c.close()}}}));
      }
      throw Error('unexpected '+url);
    });
    const w=dom.window,d=w.document;
    try{
      await pause(10);w.stageTranscript({text:'Включи лмпу'});assert.equal(d.querySelectorAll('.bubble.me').length,0);assert.equal(requests,0);
      assert.equal(d.querySelector('#message').value,'Включи лмпу');d.querySelector('#message').value='Включи лампу';
      d.querySelector('#form').dispatchEvent(new w.Event('submit',{cancelable:true}));
      d.querySelector('#form').dispatchEvent(new w.Event('submit',{cancelable:true}));await pause(20);
      assert.equal(requests,1);assert.equal(d.querySelectorAll('.bubble.me').length,1);assert.ok(d.querySelector('.action-chip').textContent.includes('ДЕМО'));
      assert.ok(d.querySelector('.pending'));assert.equal(d.querySelector('#send').disabled,true);
      release();await pause(30);assert.equal(d.querySelector('.pending'),null);assert.equal(d.querySelector('#send').disabled,false);
      assert.ok(d.querySelector('.meta').textContent.includes('LLM 500'));
    }finally{dom.window.close()}
  });
  await run('mic startup is single-flight; recorder start failure resets controls',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document;let resolveStream,calls=0,stops=0;
    Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia(){calls++;return new Promise(r=>{resolveStream=r})}}});
    class Recorder {static isTypeSupported(){return true} constructor(){this.state='inactive'}start(){throw Error('test start failed')}}
    w.MediaRecorder=Recorder;
    try{
      d.querySelector('#mic').click();d.querySelector('#mic').click();assert.equal(calls,1);
      resolveStream({getTracks:()=>[{stop:()=>stops++}]});await pause(20);
      assert.equal(stops,1);assert.equal(d.querySelector('#send').disabled,false);assert.equal(d.querySelector('#mic').disabled,false);
      assert.equal(d.querySelector('#mic').getAttribute('aria-pressed'),'false');assert.equal(d.querySelector('#mic').classList.contains('active'),false);
      assert.ok(d.querySelector('#errorText').textContent.includes('test start failed'));
    }finally{dom.window.close()}
  });
  await run('model controls snapshot settings; live Markdown deltas and collapsed diagnostics',async()=>{
    let submitted,release;
    const dom=makeDom(async(url,options)=>{
      if(url==='/api/info')return Response.json({server_instance:'test',demo:true,model:'qwen3:4b',devices:[],voice:{}});
      if(url==='/api/models')return Response.json({models:[{name:'qwen3:4b'},{name:'qwen3:8b'}],default:'qwen3:4b'});
      if(url==='/api/chat/stream'){
        submitted=JSON.parse(options.body);
        return new Response(new ReadableStream({start(c){
          c.enqueue(new TextEncoder().encode(JSON.stringify({type:'status',data:{action_results:[]}})+'\n'));
          c.enqueue(new TextEncoder().encode(JSON.stringify({type:'delta',sequence:1,text:'**Начало** ответа с формулой \\(x^2\\). '})+'\n'));
          release=()=>{c.enqueue(new TextEncoder().encode(JSON.stringify({type:'final',data:{answer:'**Начало** ответа с формулой \\(x^2\\). Конец.',engine:'ollama',action_results:[]}})+'\n'));c.close()};
        }}));
      }
      throw Error('unexpected '+url);
    });
    const w=dom.window,d=w.document;
    try{
      await pause(10);d.querySelector('#settingsOpen').click();await pause(10);
      const observedModel=d.querySelector('#model').textContent;
      d.querySelector('#modelSelect').value='qwen3:8b';d.querySelector('#modelSelect').dispatchEvent(new w.Event('change'));
      assert.equal(d.querySelector('#model').textContent,observedModel,'selection must not fabricate response identity');
      d.querySelector('#reasoning').value='on';
      d.querySelector('#responseTokens').value='1536';d.querySelector('#settingsDialog').close();
      const sending=w.sendText('Объясни формулу');await pause(20);
      assert.equal(submitted.model,null);assert.equal(submitted.reasoning,'on');assert.equal(submitted.response_tokens,1536);
      assert.ok(d.querySelector('.rendered-message strong'));assert.equal(d.querySelectorAll('.rendered-message .katex').length,1);
      assert.equal(d.querySelector('.pending'),null);assert.equal(d.querySelector('#send').disabled,true);
      d.querySelector('#modelSelect').value='qwen3:4b';release();await sending;
      assert.equal(submitted.model,null);assert.equal(d.querySelector('.message-diagnostics').open,false);
      assert.ok(d.querySelector('.rendered-message').textContent.includes('Конец.'));
    }finally{dom.window.close()}
  });
  await run('interrupted text stream replays by sequence without duplicate text or submits',async()=>{
    let calls=0,ids=[];
    const dom=makeDom(async(url,options)=>{
      if(url==='/api/info')return Response.json({server_instance:'test',demo:true,model:'qwen3:4b',devices:[],voice:{}});
      if(url==='/api/chat/stream'){
        calls++;ids.push(JSON.parse(options.body).request_id);
        const events=[{type:'status',data:{action_results:[]}},{type:'delta',sequence:1,text:'Первая часть. '}];
        if(calls===2)events.push({type:'delta',sequence:2,text:'Продолжение.'},{type:'final',data:{answer:'Первая часть. Продолжение.',engine:'ollama',action_results:[]}});
        return new Response(events.map(e=>JSON.stringify(e)).join('\n')+'\n');
      }
      throw Error('unexpected '+url);
    });
    try{
      await pause(10);await dom.window.sendText('Привет');
      const d=dom.window.document;
      assert.equal(calls,2);assert.equal(ids[0],ids[1]);assert.equal(d.querySelectorAll('.bubble.me').length,1);
      assert.equal(d.querySelector('.rendered-message').textContent.trim(),'Первая часть. Продолжение.');
    }finally{dom.window.close()}
  });
  await run('mute cancels playback after an in-flight TTS request',async()=>{
    let audioCreated=0,resolveVoice;
    const dom=makeDom(async url=>url==='/api/tts'?new Promise(r=>{resolveVoice=r}):Response.json({server_instance:'test',devices:[],voice:{}}));
    const w=dom.window,d=w.document;w.Audio=function(){audioCreated++};
    try{
      d.querySelector('#speak').checked=true;w.playSpeech('Не удалось выполнить действие.');
      d.querySelector('#speak').checked=false;d.querySelector('#speak').dispatchEvent(new w.Event('change'));
      resolveVoice(new Response(new Blob(['RIFFmock'])));await pause(20);assert.equal(audioCreated,0);
    }finally{dom.window.close()}
  });
  await run('speech starts before final; pause preserves order; replay does not repeat speech',async()=>{
    let release,tts=[];const audios=[];
    const dom=makeDom(async(url,options)=>{
      if(url==='/api/info')return Response.json({server_instance:'test',devices:[],voice:{}});
      if(url==='/api/tts'){tts.push(JSON.parse(options.body));return new Response(new Blob(['RIFFmock']));}
      if(url==='/api/tts/cancel')return Response.json({ok:true});
      if(url==='/api/chat/stream')return new Response(new ReadableStream({start(c){
        c.enqueue(new TextEncoder().encode(JSON.stringify({type:'status',data:{action_results:[]}})+'\n'));
        c.enqueue(new TextEncoder().encode(JSON.stringify({type:'delta',sequence:1,text:'Первое предложение достаточно длинное. '})+'\n'));
        release=()=>{
          // A replayed transport sequence must not feed the speech queue twice.
          c.enqueue(new TextEncoder().encode(JSON.stringify({type:'delta',sequence:1,text:'Первое предложение достаточно длинное. '})+'\n'));
          c.enqueue(new TextEncoder().encode(JSON.stringify({type:'delta',sequence:2,text:'Второе предложение тоже длинное.'})+'\n'));
          c.enqueue(new TextEncoder().encode(JSON.stringify({type:'final',data:{answer:'Первое предложение достаточно длинное. Второе предложение тоже длинное.',engine:'ollama',action_results:[]}})+'\n'));c.close();
        };
      }}));
      throw Error('unexpected '+url);
    });
    const w=dom.window,d=w.document;w.URL.createObjectURL=()=>`blob:local-${audios.length}`;w.URL.revokeObjectURL=()=>{};
    w.Audio=class {constructor(){this.plays=0;this.pauses=0;audios.push(this)}async play(){this.plays++}pause(){this.pauses++}};
    try{
      await pause(10);d.querySelector('#speak').checked=true;
      const sending=w.sendText('Расскажи что-нибудь');await pause(30);
      assert.equal(tts.length,1);assert.equal(audios.length,1);assert.equal(audios[0].plays,1);
      assert.equal(d.querySelector('#send').disabled,true);assert.ok(w.localmindVoiceMetrics.first_playback_ms!==null);
      d.querySelector('#pauseAudio').click();assert.equal(audios[0].pauses,1);release();await sending;
      assert.equal(tts.length,1);d.querySelector('#pauseAudio').click();await pause(10);assert.equal(audios[0].plays,2);
      audios[0].onended();await pause(20);assert.equal(tts.length,2);assert.equal(audios.length,2);
      assert.ok(tts[0].text.startsWith('Первое'));assert.ok(tts[1].text.startsWith('Второе'));
      assert.equal(tts[0].generation_id,tts[1].generation_id);
      d.querySelector('#stopAudio').click();assert.equal(audios[1].pauses,1);
    }finally{dom.window.close()}
  });
  await run('compound document status defers speech so the extracted summary reaches TTS',async()=>{
    const tts=[];
    const actions=[{success:true,action:'files.read_selected_file',status_text:'Текст извлечён.'}];
    const dom=makeDom(async(url,options)=>{
      if(url==='/api/info')return Response.json({server_instance:'test',devices:[],voice:{}});
      if(url==='/api/tts'){tts.push(JSON.parse(options.body).text);return new Response(new Blob(['RIFFmock']));}
      if(url==='/api/tts/cancel')return Response.json({ok:true});
      if(url==='/api/chat/stream')return new Response(new ReadableStream({start(c){
        const events=[
          {type:'status',data:{answer:'Выбран Spisok_rabot.pdf',speech_text:'Найден PDF-файл: Список работ.',speech_deferred:true,action_results:actions}},
          {type:'delta',sequence:1,text:'Извлечённый бюджет составляет семьсот тридцать девять рублей.'},
          {type:'final',data:{answer:'Извлечённый бюджет составляет семьсот тридцать девять рублей.',engine:'ollama',action_results:actions}}
        ];
        for(const event of events)c.enqueue(new TextEncoder().encode(JSON.stringify(event)+'\n'));
        c.close();
      }}));
      throw Error('unexpected '+url);
    });
    const w=dom.window,d=w.document;w.URL.createObjectURL=()=> 'blob:compound';w.URL.revokeObjectURL=()=>{};
    w.Audio=class {async play(){}pause(){}};
    try{
      await pause(10);d.querySelector('#speak').checked=true;
      await w.sendText('Найди последний PDF, затем прочитай его');await pause(30);
      assert.equal(tts.length,1);assert.ok(tts[0].includes('Извлечённый бюджет'));
      assert.ok(!tts[0].includes('Spisok')&&!tts[0].includes('Найден'));
    }finally{w.stopSpeech();dom.window.close()}
  });
  await run('interruption rejects late old audio and aborts its synthesis fetch',async()=>{
    const requests=[],audios=[];
    const dom=makeDom(async(url,options)=>{
      if(url==='/api/tts')return new Promise(resolve=>requests.push({body:JSON.parse(options.body),signal:options.signal,resolve}));
      return Response.json({server_instance:'test',devices:[],voice:{}});
    });
    const w=dom.window,d=w.document;w.URL.createObjectURL=()=>`blob:${audios.length}`;w.URL.revokeObjectURL=()=>{};
    w.Audio=class {constructor(){audios.push(this)}async play(){}pause(){}};
    try{
      d.querySelector('#speak').checked=true;w.playSpeech('Предыдущая фраза.');await pause(5);
      w.playSpeech('Новая фраза.');await pause(5);assert.equal(requests.length,2);assert.equal(requests[0].signal.aborted,true);
      requests[0].resolve(new Response(new Blob(['old'])));await pause(5);assert.equal(audios.length,0);
      requests[1].resolve(new Response(new Blob(['new'])));await pause(10);assert.equal(audios.length,1);
      assert.notEqual(requests[0].body.generation_id,requests[1].body.generation_id);
    }finally{w.stopSpeech();dom.window.close()}
  });
  await run('attachment upload is local, server acknowledged and privacy labels are safe',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document,requests=[];
    try{
      await pause(10);
      w.localmindAttachments.configure({getSession:async()=>{w.localmindAttachments.adoptConversation('attach-session');return {conversation_id:'attach-session',server_instance:'test'};},request:async(url,options)=>{requests.push({url,options});return Response.json({id:'document-one',conversation_id:'attach-session',server_instance:'test',state:'ready',characters:17,preview:'local-only-secret'});}});
      const hostile='<img src=x onerror=alert(1)>\u202esecret.txt';
      w.localmindAttachments.add([new w.File(['local-only-secret'],hostile,{type:''}),new w.File(['x'],'bad.exe',{type:'application/octet-stream'}),new w.File(['x'],'mismatch.pdf',{type:'text/plain'}),new w.File([],'empty.md',{type:'text/markdown'})]);
      await pause(10);
      assert.deepEqual(Array.from(w.localmindAttachments.snapshot(),e=>e.state),['ready','error','error','error']);
      assert.equal(d.querySelectorAll('.attachment.error').length,3);
      assert.ok(!d.querySelector('#attachmentList').textContent.includes('secret'));
      assert.ok(!d.querySelector('#nodeSelect').textContent.includes('secret'));
      assert.ok(d.querySelector('#attachmentNotice').textContent.includes('\u043b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u043c \u0441\u0435\u0440\u0432\u0435\u0440\u043e\u043c'));
      assert.equal(requests.length,1);assert.equal(requests[0].url,'/api/attachments');
      assert.deepEqual(Array.from(w.localmindAttachments.contextIds()),['document-one']);
      assert.equal(w.localmindAttachments.acknowledge([{id:'document-one'}]),false);assert.equal(w.localmindAttachments.snapshot()[0].state,'ready');
      d.querySelector('#showFilenames').checked=true;d.querySelector('#showFilenames').dispatchEvent(new w.Event('change'));
      assert.ok(d.querySelector('.attachment-name').textContent.includes('<img'));
      assert.ok(!d.querySelector('.attachment-name').textContent.includes('\u202e'));
      assert.equal(d.querySelectorAll('#attachmentList img,#attachmentList [onerror]').length,0);
      assert.equal(w.xss,undefined);
      d.querySelector('#showFilenames').checked=false;d.querySelector('#showFilenames').dispatchEvent(new w.Event('change'));
      assert.ok(!d.querySelector('#nodeSelect').textContent.includes('secret'));
    }finally{dom.window.close()}
  });
  await run('attachment count, per-file and aggregate limits precede image reads',async()=>{
    let reads=0;const dom=makeDom(null,w=>{const original=w.FileReader.prototype.readAsArrayBuffer;w.FileReader.prototype.readAsArrayBuffer=function(blob){reads++;return original.call(this,blob)}});
    const w=dom.window,d=w.document,make=(name,size)=>{const f=new w.File(['x'],name,{type:name.endsWith('.png')?'image/png':'text/plain'});Object.defineProperty(f,'size',{value:size});return f;};
    try{
      w.localmindAttachments.configure({getSession:async()=>{w.localmindAttachments.adoptConversation('limit-session');return {conversation_id:'limit-session',server_instance:'test'};},request:async()=>Response.json({id:'limit-doc',conversation_id:'limit-session',server_instance:'test',state:'ready',characters:1,preview:'x'})});
      w.localmindAttachments.add(Array.from({length:9},(_,i)=>make(i+'.png',1)));assert.equal(w.localmindAttachments.snapshot().length,0);assert.equal(reads,0);
      w.localmindAttachments.add([make('large.png',10*1024*1024+1)]);await pause(10);
      assert.equal(w.localmindAttachments.snapshot()[0].state,'error');assert.equal(reads,0);
      w.localmindAttachments.reset();
      w.localmindAttachments.add(Array.from({length:5},(_,i)=>make(i+'.txt',10*1024*1024)));assert.equal(w.localmindAttachments.snapshot().length,0);assert.equal(reads,0);
      assert.ok(d.querySelector('#attachmentNotice').textContent.includes('40 МБ'));
      w.localmindAttachments.add([make('boundary.txt',10*1024*1024)]);await pause(10);assert.equal(w.localmindAttachments.snapshot()[0].state,'ready');
    }finally{dom.window.close()}
  });
  await run('malformed and oversized raster headers are refused before decoding',async()=>{
    let decodes=0;const dom=makeDom(null,w=>{w.createImageBitmap=async()=>{decodes++;throw Error('decode should not run')}}),w=dom.window;
    try{
      const header=new Uint8Array(24),view=new DataView(header.buffer);view.setUint32(0,0x89504e47);view.setUint32(4,0x0d0a1a0a);view.setUint32(16,8193);view.setUint32(20,8193);
      w.localmindAttachments.add([new w.File(['not a PNG'],'broken.png',{type:'image/png'}),new w.File([header],'huge.png',{type:'image/png'})]);await pause(30);
      assert.deepEqual(Array.from(w.localmindAttachments.snapshot(),e=>e.state),['error','error']);assert.equal(decodes,0);
    }finally{dom.window.close()}
  });
  await run('reset during asynchronous image decode closes bitmap and never resurrects preview',async()=>{
    let resolveBitmap,closed=0;const dom=makeDom(null,w=>{w.createImageBitmap=()=>new Promise(r=>{resolveBitmap=r})}),w=dom.window,d=w.document;
    try{
      const header=new Uint8Array(24),view=new DataView(header.buffer);view.setUint32(0,0x89504e47);view.setUint32(4,0x0d0a1a0a);view.setUint32(16,2);view.setUint32(20,2);
      w.localmindAttachments.add([new w.File([header],'private.png',{type:'image/png'})]);
      for(let i=0;i<20&&!resolveBitmap;i++)await pause(5);assert.equal(typeof resolveBitmap,'function');
      w.localmindAttachments.reset();resolveBitmap({close(){closed++}});await pause(10);
      assert.equal(closed,1);assert.equal(w.localmindAttachments.snapshot().length,0);assert.equal(d.querySelectorAll('.attachment').length,0);assert.equal(d.querySelector('#attachmentNotice').hidden,true);
      assert.ok(!d.querySelector('#nodeSelect').textContent.includes('Вложение'));
    }finally{dom.window.close()}
  });
  await run('document preview shows actual extracted text and removal revokes future context',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document;
    try{
      w.localmindAttachments.configure({getSession:async()=>{w.localmindAttachments.adoptConversation('preview-session');return {conversation_id:'preview-session',server_instance:'test'};},request:async()=>Response.json({id:'preview-doc',conversation_id:'preview-session',server_instance:'test',state:'ready',characters:1,preview:'x'})});
      w.localmindAttachments.add([new w.File(['x'],'note.md',{type:'text/markdown'})]);await pause(10);
      d.querySelector('.preview-button').click();assert.equal(w.localmindAttachments.snapshot()[0].state,'ready');
      assert.equal(d.querySelector('#previewText').textContent,'x');
      assert.equal(d.querySelector('#attachmentPreview').open,true);
      d.querySelector('.attachment .icon-button').click();
      assert.equal(d.querySelectorAll('.attachment').length,0);assert.equal(w.localmindAttachments.snapshot().length,0);
      assert.deepEqual(Array.from(w.localmindAttachments.contextIds()),[]);
    }finally{dom.window.close()}
  });
  await run('file paste/drop/select use local processing and ordinary text paste is not intercepted',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document;
    try{
      const input=d.querySelector('#fileInput'),file=new w.File(['a'],'paste.txt',{type:'text/plain'});
      Object.defineProperty(input,'files',{value:[file],configurable:true});input.dispatchEvent(new w.Event('change'));await pause(5);assert.equal(w.localmindAttachments.snapshot().length,1);assert.equal(input.value,'');
      const paste=new w.Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(paste,'clipboardData',{value:{files:[file]}});d.querySelector('#message').dispatchEvent(paste);assert.equal(paste.defaultPrevented,true);
      const text=new w.Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(text,'clipboardData',{value:{files:[],getData:()=>'<text>'}});d.querySelector('#message').dispatchEvent(text);assert.equal(text.defaultPrevented,false);
      const drop=new w.Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(drop,'dataTransfer',{value:{types:['Files'],files:[file]}});d.querySelector('#dropZone').dispatchEvent(drop);await pause(5);
      assert.equal(drop.defaultPrevented,true);assert.equal(w.localmindAttachments.snapshot().length,3);
      w.localmindAttachments.reset();assert.equal(d.querySelectorAll('.attachment').length,0);
    }finally{dom.window.close()}
  });
  await run('graph stays bounded and exposes keyboard inspection without leaking source filenames',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document;
    try{
      await pause(10);const scene=w.localmindScene;
      scene.observeApps(Array.from({length:100},(_,i)=>({id:'app'+i,name:'App '+i,allowed:false})));
      scene.observeInfo({demo:true,devices:Array.from({length:100},(_,i)=>({id:'dev'+i,name:'Device '+i}))});scene.observeConversation("app0");
      scene.setFiles(Array.from({length:100},(_,i)=>({id:'f'+i,label:'Вложение '+i})));
      scene.setSources(Array.from({length:100},(_,i)=>({id:'s'+i,label:'private source '+i,path:'private.txt',available:true,allowed:true})));
      scene.toolResults(Array.from({length:100},(_,i)=>({action:'action'+i,success:true})));
      assert.ok(scene.stats().nodes<=36);assert.equal(scene.stats().edges,scene.stats().nodes-1);
      assert.ok(!d.querySelector('#nodeSelect').textContent.includes('private'));
      const select=d.querySelector('#nodeSelect');select.value='app:app0';select.dispatchEvent(new w.Event('change'));
      assert.equal(d.querySelector('#nodeTitle').textContent,'App 0');assert.ok(d.querySelector('#nodeDetail').textContent.includes('не предоставляет разрешение'));
      const plain=new w.KeyboardEvent('keydown',{key:'ArrowDown',cancelable:true});select.dispatchEvent(plain);assert.equal(plain.defaultPrevented,false);
      const key=new w.KeyboardEvent('keydown',{key:'ArrowRight',altKey:true,cancelable:true});select.dispatchEvent(key);assert.equal(key.defaultPrevented,true);d.querySelector('#moveNode').click();
      d.querySelector('#centerGraph').click();assert.equal(d.querySelector('#nodeTitle').textContent,'App 0');
      scene.reset();assert.ok(!d.querySelector('#nodeSelect').textContent.includes('Вложение'));assert.ok(!d.querySelector('#nodeSelect').textContent.includes('Текущий диалог'));
      assert.equal(d.querySelector('#nodeTitle').textContent,'LocalMind');
    }finally{dom.window.close()}
  });
  await run('settings tabs follow keyboard selection; motion modes configure JavaScript state',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document;
    try{
      const tabs=[...d.querySelectorAll('[data-settings]')];tabs[0].dispatchEvent(new w.KeyboardEvent('keydown',{key:'End',cancelable:true}));
      assert.equal(tabs[3].getAttribute('aria-selected'),'true');assert.equal(d.querySelector('#settings-capabilities').hidden,false);assert.equal(d.querySelector('#settings-model').hidden,true);
      tabs[3].dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',cancelable:true}));assert.equal(tabs[0].getAttribute('aria-selected'),'true');
      d.querySelector('#reduceMotion').click();d.querySelector('#lowPerformance').click();
      assert.equal(w.localmindScene.stats().reduced,true);assert.equal(w.localmindScene.stats().low,true);assert.equal(d.documentElement.dataset.reducedMotion,'true');assert.equal(d.documentElement.dataset.lowPerformance,'true');
    }finally{dom.window.close()}
  });
  await run('discovery does not grant permissions; stale fingerprint denial rolls back; revocation is explicit',async()=>{
    const mutations=[];let allowed=false,reject=true;
    const dom=makeDom(async(url,options={})=>{
      if(url==='/api/apps')return Response.json({apps:[{id:'editor',name:'Editor',target:'C:/Editor.exe',allowed,fingerprint:'exact-fingerprint'}]});
      if(url==='/api/apps/permission'){const body=JSON.parse(options.body);mutations.push(body);if(reject)return Response.json({detail:'stale fingerprint'},{status:409});allowed=body.allowed;return Response.json({ok:true});}
      return Response.json({server_instance:'test',demo:true,model:'test',devices:[],voice:{},sources:[]});
    }),w=dom.window,d=w.document;
    try{
      await pause(10);assert.equal(mutations.length,0);let checkbox=d.querySelector('#appsList input');checkbox.click();await pause(10);
      assert.equal(checkbox.checked,false);assert.equal(checkbox.disabled,false);assert.equal(mutations[0].fingerprint,'exact-fingerprint');assert.ok(d.querySelector('#errorText').textContent.includes('stale fingerprint'));
      reject=false;checkbox.click();await pause(10);assert.equal(checkbox.checked,true);assert.equal(allowed,true);
      checkbox.click();await pause(10);assert.equal(allowed,false);assert.equal(mutations[2].allowed,false);
    }finally{dom.window.close()}
  });
  await run('microphone denial leaves text input usable and no false listening activity',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document;
    Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia:async()=>{throw Error('permission denied')}}});w.MediaRecorder=class {};
    try{
      d.querySelector('#mic').click();await pause(10);assert.equal(d.querySelector('#mic').disabled,false);assert.equal(d.querySelector('#send').disabled,false);assert.equal(w.localmindScene.stats().mode,'idle');assert.ok(d.querySelector('#errorText').textContent.includes('permission denied'));
    }finally{dom.window.close()}
  });
  await run('reset while microphone permission is pending releases tracks and restores controls',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document;let resolveStream,stops=0;
    Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia:()=>new Promise(r=>{resolveStream=r})}});w.MediaRecorder=class {};
    try{
      d.querySelector('#mic').click();d.querySelector('#resetConversation').click();resolveStream({getTracks:()=>[{stop:()=>stops++}]});await pause(10);
      assert.equal(stops,1);assert.equal(d.querySelector('#mic').disabled,false);assert.equal(d.querySelector('#send').disabled,false);assert.equal(d.querySelector('#draftReview').hidden,true);
    }finally{dom.window.close()}
  });
  await run('late successful transcription after reset cannot restore a discarded draft',async()=>{
    let resolveTranscript,clock=0,stops=0;
    const dom=makeDom(async(url)=>url==='/api/transcribe'?new Promise(r=>{resolveTranscript=r}):Response.json({server_instance:'test',devices:[],apps:[],voice:{}}));
    const w=dom.window,d=w.document;
    w.performance.now=()=>clock;
    Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia:async()=>({getTracks:()=>[{stop:()=>stops++}]})}});
    w.MediaRecorder=class {static isTypeSupported(){return true}constructor(){this.state='inactive'}start(){this.state='recording'}stop(){this.state='inactive';this.ondataavailable({data:new w.Blob(['x'.repeat(2048)])});this.onstop()}};
    try{
      d.querySelector('#mic').click();await pause(5);clock=500;d.querySelector('#mic').click();await pause(5);assert.equal(typeof resolveTranscript,'function');
      d.querySelector('#resetConversation').click();resolveTranscript(Response.json({text:'Discard this old transcript'}));await pause(10);
      assert.equal(stops,1);assert.equal(d.querySelector('#message').value,'');assert.equal(d.querySelector('#draftReview').hidden,true);assert.equal(d.querySelector('#send').disabled,false);assert.equal(w.localmindScene.stats().mode,'idle');
    }finally{dom.window.close()}
  });
  await run('Canvas scheduling stops in economical mode and when hidden',async()=>{
    const dom=makeDom(null,w=>{
      // jsdom has no layout: model a visible desktop stage explicitly.
      Object.defineProperty(w.document.querySelector('.stage'),'clientWidth',{value:1200});
      const ctx=new Proxy({measureText:text=>({width:text.length*6})},{get:(target,key)=>key in target?target[key]:()=>{}});
      w.CanvasRenderingContext2D=function(){};w.HTMLCanvasElement.prototype.getContext=()=>ctx;
      w.HTMLCanvasElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:500,height:400});
    }),w=dom.window,d=w.document;
    try{
      const scene=w.localmindScene;await pause(110);assert.ok(scene.stats().frames>0);
      scene.configure({low:true,reduced:false});await pause(110);const economical=scene.stats().frames;await pause(190);assert.equal(scene.stats().frames,economical);assert.equal(scene.stats().scheduled,false);
      scene.configure({low:false,reduced:true});await pause(110);const quiet=scene.stats().frames;await pause(190);assert.equal(scene.stats().frames,quiet);
      scene.configure({low:false,reduced:false});Object.defineProperty(d,'hidden',{configurable:true,value:true});d.dispatchEvent(new w.Event('visibilitychange'));const hidden=scene.stats().frames;await pause(110);assert.equal(scene.stats().frames,hidden);assert.equal(scene.stats().scheduled,false);
    }finally{dom.window.close()}
  });
  await run('REAL badge and lamp suggestion identify physical device commands',async()=>{
    const dom=makeDom(async()=>Response.json({server_instance:'test',demo:false,model:'test',devices:[{id:'desk_light',name:'Lamp'}],apps:[],voice:{}})),w=dom.window,d=w.document;
    try{
      await pause(10);assert.equal(d.querySelector('#mode').textContent,'REAL · HA');assert.equal(d.querySelector('#mode').closest('.topbar')!==null,true);assert.ok(d.querySelector('#lampSuggestionCaption').textContent.includes('реальное устройство'));assert.ok(!d.querySelector('#lampSuggestionCaption').textContent.includes('DEMO'));
    }finally{dom.window.close()}
  });
  await run('audio amplitude uses analyser samples; pause clears speaking state; release disconnects',async()=>{
    let byte=128,disconnects=0;const dom=makeDom(null,w=>{
      const input=()=>({connect(){},disconnect(){disconnects++}});
      w.AudioContext=class {constructor(){this.state='running';this.destination={}}resume(){return Promise.resolve()}createMediaElementSource(){return input()}createMediaStreamSource(){return input()}createAnalyser(){return {disconnect(){},getByteTimeDomainData(buffer){buffer.fill(byte)}}}};
    }),w=dom.window;
    try{
      const source=new w.EventTarget();source.paused=false;const release=w.LocalMindAudio.start(source,'speaking');
      assert.equal(w.localmindScene.stats().mode,'speaking');assert.equal(w.localmindScene.stats().amplitude,0);
      byte=160;assert.ok(w.localmindScene.stats().amplitude>0);source.paused=true;source.dispatchEvent(new w.Event('pause'));
      assert.equal(w.localmindScene.stats().mode,'idle');assert.equal(w.localmindScene.stats().amplitude,0);
      source.paused=false;source.dispatchEvent(new w.Event('play'));assert.equal(w.localmindScene.stats().mode,'speaking');
      release();assert.equal(disconnects,1);assert.equal(w.LocalMindAudio.current,null);assert.equal(w.localmindScene.stats().mode,'idle');
    }finally{dom.window.close()}
  });
  await run('PDF folder-read and exact-file-open grants remain separate and stale denial rolls back',async()=>{
    const mutations=[];let folderAllowed=false,reject=true;
    const dom=makeDom(async(url,options={})=>{
      if(url==='/api/files')return Response.json({folder:{allowed:folderAllowed,path:'C:/Downloads',fingerprint:'folder-fingerprint'},selected:{filename:'report.pdf',path:'C:/Downloads/report.pdf',modified_at:'test',file_id:'file-identity',open_allowed:false}});
      if(url==='/api/files/folder-permission'){const body=JSON.parse(options.body);mutations.push({url,body});if(reject)return Response.json({detail:'folder fingerprint stale'},{status:409});folderAllowed=body.allowed;return Response.json({ok:true});}
      if(url==='/api/files/open-permission'){mutations.push({url,body:JSON.parse(options.body)});return Response.json({ok:true});}
      return Response.json({server_instance:'test',demo:true,model:'test',devices:[],apps:[],voice:{}});
    }),w=dom.window,d=w.document;
    try{
      await w.loadFilePermissions();assert.equal(mutations.length,0);let inputs=d.querySelectorAll('#filePermissions input');
      inputs[0].click();await pause(10);assert.equal(inputs[0].checked,false);assert.equal(mutations[0].body.fingerprint,'folder-fingerprint');assert.equal(mutations[0].body.allowed,true);
      reject=false;inputs[0].click();await pause(10);inputs=d.querySelectorAll('#filePermissions input');assert.equal(inputs[0].checked,true);assert.equal(inputs[1].checked,false);
      inputs[1].click();await pause(10);assert.equal(mutations[2].url,'/api/files/open-permission');assert.equal(mutations[2].body.file_id,'file-identity');assert.equal(mutations[2].body.allowed,true);
      inputs[0].click();await pause(10);assert.equal(folderAllowed,false);assert.equal(mutations[3].body.allowed,false);
    }finally{dom.window.close()}
  });
  await run('unavailable model and voice remain explicit without cloud substitution',async()=>{
    const urls=[],dom=makeDom(async(url)=>{urls.push(url);if(url==='/api/models')return Response.json({models:[],default:'missing-model'});return Response.json({server_instance:'test',demo:true,model:'missing-model',devices:[],apps:[],sources:[],voice:{voices:[{id:'ru_RU-denis-medium',ready:false}]}});}),w=dom.window,d=w.document;
    try{
      await pause(10);await w.loadModels();assert.equal(d.querySelector('#modelSelect').value,'');assert.ok(d.querySelector('#modelSelect').textContent.includes('недоступна'));assert.ok(d.querySelector('#voiceStatus').textContent.includes('требует установки'));assert.ok(d.querySelector('#voiceStatus').textContent.includes('Облачная озвучка не используется'));
      assert.ok(urls.every(url=>url.startsWith('/api/')));
    }finally{dom.window.close()}
  });
  await run('reset aborts pending transcription and a late failure cannot reopen an old error',async()=>{
    let rejectTranscript,transcriptSignal,clock=0;
    const dom=makeDom(async(url,options={})=>{
      if(url==='/api/transcribe'){transcriptSignal=options.signal;return new Promise((_,reject)=>{rejectTranscript=reject});}
      return Response.json({server_instance:'test',devices:[],apps:[],voice:{}});
    }),w=dom.window,d=w.document;
    w.performance.now=()=>clock;
    Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}]})}});
    w.MediaRecorder=class {static isTypeSupported(){return true}constructor(){this.state='inactive'}start(){this.state='recording'}stop(){this.state='inactive';this.ondataavailable({data:new w.Blob(['x'.repeat(2048)])});this.onstop()}};
    try{
      d.querySelector('#mic').click();await pause(5);clock=500;d.querySelector('#mic').click();await pause(5);
      assert.equal(typeof rejectTranscript,'function');assert.equal(transcriptSignal.aborted,false);
      d.querySelector('#resetConversation').click();assert.equal(transcriptSignal.aborted,true);
      rejectTranscript(Error('late obsolete STT failure'));await pause(10);
      assert.equal(d.querySelector('#errorDialog').open,false);assert.equal(d.querySelector('#errorText').textContent,'');assert.equal(d.querySelector('#message').value,'');assert.equal(d.querySelector('#draftReview').hidden,true);assert.equal(d.querySelector('#send').disabled,false);assert.equal(d.querySelector('#mic').disabled,false);assert.equal(w.localmindScene.stats().mode,'idle');
    }finally{dom.window.close()}
  });
  await run('server reset blocks every send path until success and starts the next turn without old context',async()=>{
    const chatBodies=[];let resolveReset,resetCalls=0;
    const dom=makeDom(async(url,options={})=>{
      if(url==='/api/chat/stream'){
        chatBodies.push(JSON.parse(options.body));
        return new Response(JSON.stringify({type:'final',data:{answer:'Ответ',conversation_id:'conversation-'+chatBodies.length,engine:'test',action_results:[]}})+'\n');
      }
      if(url==='/api/conversations/reset'){resetCalls++;return new Promise(resolve=>{resolveReset=resolve});}
      return Response.json({server_instance:'test',demo:true,model:'test',devices:[],apps:[],voice:{}});
    }),w=dom.window,d=w.document;
    try{
      await pause(10);await w.sendText('Первый ход');assert.equal(chatBodies.length,1);
      d.querySelector('#resetConversation').click();assert.equal(resetCalls,1);assert.equal(d.querySelector('#send').disabled,true);assert.equal(d.querySelector('#mic').disabled,true);
      d.querySelector('#message').value='Не выполнять во время сброса';
      d.querySelector('#form').dispatchEvent(new w.Event('submit',{cancelable:true}));
      d.querySelector('#message').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',cancelable:true}));
      d.querySelector('[data-example]').click();await w.sendText('Тоже не выполнять');d.querySelector('#resetConversation').click();
      assert.equal(chatBodies.length,1);assert.equal(resetCalls,1);
      resolveReset(Response.json({ok:true}));await pause(10);assert.equal(d.querySelector('#send').disabled,false);assert.equal(d.querySelector('#mic').disabled,false);assert.equal(d.querySelectorAll('.bubble.me').length,0);
      await w.sendText('Новый ход');assert.equal(chatBodies.length,2);assert.equal(chatBodies[1].conversation_id,null);assert.equal(chatBodies[1].history.length,0);assert.notEqual(chatBodies[0].request_id,chatBodies[1].request_id);assert.equal(d.querySelectorAll('.bubble.me').length,1);
    }finally{dom.window.close()}
  });
  await run('overlapping application catalog reads cannot overwrite a completed grant',async()=>{
    for(const readFinishesFirst of [true,false]){
      let reads=0,allowed=false,resolveGrant,resolveStaleRead;
      const catalog=()=>({apps:[{id:'editor',name:'Editor',target:'C:/Editor.exe',allowed,fingerprint:'exact-fingerprint'}]});
      const dom=makeDom(async(url,options={})=>{
        if(url==='/api/apps'){
          reads++;if(reads===2)return new Promise(resolve=>{resolveStaleRead=()=>resolve(Response.json({apps:[{...catalog().apps[0],allowed:false}]}));});
          return Response.json(catalog());
        }
        if(url==='/api/apps/permission')return new Promise(resolve=>{resolveGrant=()=>{allowed=JSON.parse(options.body).allowed;resolve(Response.json({ok:true}));};});
        return Response.json({server_instance:'test',devices:[],apps:[],voice:{}});
      }),w=dom.window,d=w.document;
      try{
        await pause(10);d.querySelector('#appsList input').click();assert.equal(typeof resolveGrant,'function');
        const reading=w.loadApps();assert.equal(typeof resolveStaleRead,'function');
        if(readFinishesFirst){resolveStaleRead();await reading;resolveGrant();await pause(15);}
        else{resolveGrant();await pause(15);resolveStaleRead();await reading;}
        assert.equal(allowed,true);assert.equal(reads,3);assert.equal(d.querySelector('#appsList input').checked,true);assert.equal(d.querySelector('#appsList input').disabled,false);assert.equal(d.querySelector('#rescan').disabled,false);
        w.localmindScene.observeConversation('editor');const select=d.querySelector('#nodeSelect');select.value='app:editor';select.dispatchEvent(new w.Event('change'));assert.ok(d.querySelector('#nodeDetail').textContent.includes('Разрешение запуска выдано пользователем'));
      }finally{dom.window.close()}
    }
  });
  console.log(`${passed} DOM behavior checks passed (not browser visual QA).`);
})().catch(e=>{console.error(e);process.exitCode=1});
