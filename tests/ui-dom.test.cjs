/* DOM checks complement the separate browser suite; no visual claims. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html=fs.readFileSync('static/index.html','utf8').replace(/^\uFEFF/,'');
const scripts=['marked.umd.js','purify.min.js','katex.min.js','localmind-rich.js','icons.js','constellation.js','attachments.js','speech.js','app.js','interface.js'];
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
(async()=>{
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
      d.querySelector('#modelSelect').value='qwen3:8b';d.querySelector('#reasoning').value='on';
      d.querySelector('#responseTokens').value='1536';d.querySelector('#settingsDialog').close();
      const sending=w.sendText('Объясни формулу');await pause(20);
      assert.equal(submitted.model,'qwen3:8b');assert.equal(submitted.reasoning,'on');assert.equal(submitted.response_tokens,1536);
      assert.ok(d.querySelector('.rendered-message strong'));assert.equal(d.querySelectorAll('.rendered-message .katex').length,1);
      assert.equal(d.querySelector('.pending'),null);assert.equal(d.querySelector('#send').disabled,true);
      d.querySelector('#modelSelect').value='qwen3:4b';release();await sending;
      assert.equal(submitted.model,'qwen3:8b');assert.equal(d.querySelector('.message-diagnostics').open,false);
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
  await run('attachment preparation keeps bytes local; empty MIME, mixed invalid files and private names',async()=>{
    const requests=[],dom=makeDom(async(url,options)=>{requests.push({url,options});return Response.json({server_instance:'test',demo:true,model:'test',devices:[],apps:[],voice:{}});});
    const w=dom.window,d=w.document;
    try{
      await pause(10);requests.length=0;
      const hostile='<img src=x onerror=alert(1)>\u202esecret.txt';
      w.localmindAttachments.add([new w.File(['local-only-secret'],hostile,{type:''}),new w.File(['x'],'bad.exe',{type:'application/octet-stream'}),new w.File(['x'],'mismatch.pdf',{type:'text/plain'}),new w.File([],'empty.md',{type:'text/markdown'})]);
      await pause(10);
      assert.deepEqual(Array.from(w.localmindAttachments.snapshot(),e=>e.state),['ready','error','error','error']);
      assert.equal(d.querySelectorAll('.attachment.error').length,3);
      assert.ok(!d.querySelector('#attachmentList').textContent.includes('secret'));
      assert.ok(!d.querySelector('#nodeSelect').textContent.includes('secret'));
      assert.ok(d.querySelector('#attachmentNotice').textContent.includes('НЕ переданы модели'));
      assert.equal(requests.length,0);
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
  await run('preview processing is explicit and removal cancels every deferred transition',async()=>{
    const dom=makeDom(),w=dom.window,d=w.document;
    try{
      w.localmindAttachments.add([new w.File(['x'],'note.md',{type:'text/markdown'})]);await pause(10);
      d.querySelector('.preview-button').click();assert.equal(w.localmindAttachments.snapshot()[0].state,'indexing');
      assert.ok(d.querySelector('.attachment-state').textContent.includes('Превью'));
      d.querySelector('.attachment .icon-button').click();assert.equal(w.localmindAttachments.snapshot()[0].hasFile,false);
      await pause(1600);assert.equal(d.querySelectorAll('.attachment').length,0);assert.equal(w.localmindAttachments.snapshot().length,0);
    }finally{dom.window.close()}
  });
  await run('file paste/drop/select stay local and ordinary text paste is not intercepted',async()=>{
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
      scene.observeInfo({demo:true,devices:Array.from({length:100},(_,i)=>({id:'dev'+i,name:'Device '+i}))});scene.observeConversation();
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
        const select=d.querySelector('#nodeSelect');select.value='app:editor';select.dispatchEvent(new w.Event('change'));assert.ok(d.querySelector('#nodeDetail').textContent.includes('Разрешение запуска выдано пользователем'));
      }finally{dom.window.close()}
    }
  });
  console.log(`${passed} DOM behavior checks passed (not browser visual QA).`);
})().catch(e=>{console.error(e);process.exitCode=1});
