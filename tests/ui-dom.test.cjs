/* DOM checks complement the separate browser suite; no visual claims. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html=fs.readFileSync('static/index.html','utf8').replace(/^\uFEFF/,'');
const scripts=['marked.umd.js','purify.min.js','katex.min.js','localmind-rich.js','speech.js','app.js'];
let passed=0;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
function makeDom(fetcher) {
  const dom=new JSDOM(html,{url:'http://127.0.0.1:8765',runScripts:'dangerously',pretendToBeVisual:true});
  const w=dom.window;
  w.TextDecoder=TextDecoder;w.TextEncoder=TextEncoder;w.Response=Response;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
  w.HTMLDialogElement.prototype.close=function(){this.open=false};
  w.fetch=fetcher || (async()=>Response.json({server_instance:'test',demo:true,model:'test',devices:[],voice:{voices:[]}}));
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
  console.log(`${passed} DOM behavior checks passed (not browser visual QA).`);
})().catch(e=>{console.error(e);process.exitCode=1});
