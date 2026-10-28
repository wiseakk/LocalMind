/* DOM checks complement the separate browser suite; no visual claims. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html=fs.readFileSync('static/index.html','utf8').replace(/^\uFEFF/,'');
const scripts=['marked.umd.js','purify.min.js','katex.min.js','localmind-rich.js','app.js'];
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
  console.log(`${passed} DOM behavior checks passed (not browser visual QA).`);
})().catch(e=>{console.error(e);process.exitCode=1});
