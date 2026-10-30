/* Presentation history must never restore server authority or replay actions. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const scripts=['marked.umd.js','purify.min.js','katex.min.js','localmind-rich.js','icons.js','constellation.js','attachments.js','speech.js','app.js','interface.js'];
function setup(options={}){
  const dom=new JSDOM(fs.readFileSync('static/index.html','utf8'),{url:'http://127.0.0.1:8765',runScripts:'dangerously',pretendToBeVisual:true});
  const w=dom.window;w.TextDecoder=TextDecoder;w.Response=Response;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  const requests=[];
  if(options.saved)w.localStorage.setItem('localmind.blacksite.history.v1',options.saved);
  w.fetch=async(url,init={})=>{
    requests.push({url,...init});
    const special=await options.fetch?.(url,init);if(special)return special;
    if(url==='/api/chat/stream')return new Response(JSON.stringify({type:'final',data:{answer:'Ответ без повторного действия',conversation_id:'session-'+requests.filter(r=>r.url==='/api/chat/stream').length,engine:'test',action_results:[]}})+'\n');
    return Response.json({server_instance:'test',conversation_id:'session-created',demo:true,model:'test',devices:[],apps:[],sources:[],voice:{}});
  };
  for(const name of scripts){const script=w.document.createElement('script');script.textContent=fs.readFileSync('static/assets/'+name,'utf8');w.document.head.append(script);}
  return {dom,w,d:w.document,requests};
}
async function run(name,fn){await fn();console.log('PASS '+name);}
(async()=>{
  await run('history preserves independent drafts/messages without replay and new turns isolate context',async()=>{
    const {dom,w,d,requests}=setup();try{
      await pause(10);await w.sendText('Первый разговор');
      d.querySelector('#message').value='Черновик один';
      await w.newConversation();
      assert.equal(d.querySelectorAll('.bubble').length,0);
      assert.equal(w.localmindSession.get().conversation_id,null);
      assert.ok(!d.querySelector('#nodeSelect').textContent.includes('Память сессии'));
      d.querySelector('#message').value='Черновик два';
      d.querySelector('#historyOpen').click();
      d.querySelectorAll('.history-entry>button:first-child')[1].click();await pause(10);
      assert.equal(d.querySelector('#message').value,'Черновик один');
      assert.equal(d.querySelectorAll('.bubble.me').length,1);
      assert.equal(requests.filter(r=>r.url==='/api/chat/stream').length,1);
      assert.equal(w.localmindSession.get().conversation_id,'session-1');
      d.querySelector('#historyOpen').click();d.querySelectorAll('.history-entry>button:first-child')[0].click();await pause(10);
      assert.equal(d.querySelector('#message').value,'Черновик два');
      await w.sendText('Второй разговор');
      const body=JSON.parse(requests.filter(r=>r.url==='/api/chat/stream')[1].body);
      assert.equal(body.conversation_id,null);assert.deepEqual(body.history,[]);
      assert.equal(w.localStorage.getItem('localmind.blacksite.history.v1'),null);
    }finally{dom.window.close();}
  });
  await run('expired server sessions become read-only archives and never submit archived context',async()=>{
    let expired=false;
    const {dom,w,d,requests}=setup({fetch:async(url)=>expired&&url==='/api/conversations/session-1'?Response.json({detail:'expired'},{status:409}):null});
    try{
      await pause(10);await w.sendText('Сохранённый текст');await w.newConversation();expired=true;
      d.querySelector('#historyOpen').click();d.querySelectorAll('.history-entry>button:first-child')[1].click();await pause(10);
      assert.equal(d.querySelector('#message').readOnly,true);assert.match(d.querySelector('#conversationTitle').textContent,/АРХИВ/);
      assert.ok(!d.querySelector('#nodeSelect').textContent.includes('Память сессии'));
      await w.sendText('Не выполнять');assert.equal(requests.filter(r=>r.url==='/api/chat/stream').length,1);
      assert.equal(w.localmindSession.get().conversation_id,null);
    }finally{dom.window.close();}
  });
  await run('explicit persistence saves text only, restores archives, and treats titles as text',async()=>{
    const first=setup();let stored;
    try{
      await pause(10);first.d.querySelector('#key').value='do-not-store-key';await first.w.sendText('Личный текст');
      first.d.querySelector('#persistHistory').click();stored=first.w.localStorage.getItem('localmind.blacksite.history.v1');
      assert.ok(stored.includes('Личный текст'));assert.ok(!stored.includes('do-not-store-key'));assert.ok(!stored.includes('session-1'));
      first.d.querySelector('#persistHistory').click();assert.equal(first.w.localStorage.getItem('localmind.blacksite.history.v1'),null);
    }finally{first.dom.window.close();}
    const second=setup({saved:stored});try{
      await pause(10);second.d.querySelector('#historyOpen').click();second.d.querySelectorAll('.history-entry>button:first-child')[0].click();await pause(10);
      assert.equal(second.d.querySelector('#message').readOnly,true);assert.match(second.d.querySelector('#composerState').textContent,/Архив/);
      assert.equal(second.requests.filter(r=>r.url==='/api/chat/stream').length,0);
      second.d.querySelector('#historyOpen').click();second.d.querySelector('.history-entry .text-button').click();second.d.querySelector('#renameInput').value='<img src=x onerror=alert(1)>';
      second.d.querySelector('#renameForm').dispatchEvent(new second.w.Event('submit',{cancelable:true}));
      assert.equal(second.d.querySelector('#historyList img'),null);assert.ok(second.d.querySelector('#historyList').textContent.includes('<img'));
    }finally{second.dom.window.close();}
  });
  await run('Map restores prior mode and draft; voice mode never activates microphone',async()=>{
    const {dom,w,d}=setup();let microphones=0;
    Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia:()=>{microphones++;throw Error('unexpected');}}});
    try{
      await pause(10);d.querySelector('#message').value='Не терять';
      d.querySelector('#constellationMode').value='focus';d.querySelector('#constellationMode').dispatchEvent(new w.Event('change'));
      d.querySelector('#graphToggle').click();assert.ok(d.body.classList.contains('map-open'));assert.equal(d.querySelector('.dialogue-column').inert,true);
      d.querySelector('#closeGraph').click();assert.equal(d.querySelector('#constellationMode').value,'focus');assert.equal(d.querySelector('#message').value,'Не терять');assert.equal(d.querySelector('.dialogue-column').inert,false);
      d.querySelector('#voiceMode').click();assert.equal(d.querySelector('#speak').checked,true);assert.equal(microphones,0);
      for(const id of ['pauseAudio','stopAudio','interruptReply'])assert.equal(d.querySelector('#'+id).type,'button');
    }finally{dom.window.close();}
  });
  await run('initial image-only draft uploads locally and survives conversation switching',async()=>{
    const {dom,w,d,requests}=setup({fetch:async(url,init)=>url==='/api/attachments'?Response.json({
      id:'image-upload',name:'initial.png',size:100,kind:'image',width:1,height:1,characters:0,truncated:false,
      state:'ready',conversation_id:init.body.get('conversation_id'),server_instance:init.body.get('server_instance')
    }):null});
    try{
      await pause(10);w.HTMLCanvasElement.prototype.getContext=()=>({drawImage(){}});w.createImageBitmap=async()=>({close(){}});
      const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGPojjn/HwAF4gK2//l6AAAAAABJRU5ErkJggg==','base64');
      w.localmindAttachments.add([new w.File([png],'initial.png',{type:'image/png'})]);await pause(20);
      assert.equal(w.localmindAttachments.snapshot()[0].state,'ready');await w.newConversation();
      assert.equal(w.localmindAttachments.snapshot().length,0);
      d.querySelector('#historyOpen').click();d.querySelectorAll('.history-entry>button:first-child')[1].click();await pause(10);
      assert.equal(w.localmindAttachments.snapshot()[0].state,'ready');
      assert.equal(requests.filter(r=>r.url==='/api/attachments').length,1);
      d.querySelector('#constellationMode').value='files';d.querySelector('#constellationMode').dispatchEvent(new w.Event('change'));
      assert.ok(d.querySelector('#nodeSelect').textContent.includes('Вложение'));
    }finally{dom.window.close();}
  });
  await run('delete waits for server reset while all send and switch paths remain locked',async()=>{
    let release;
    const {dom,w,d,requests}=setup({fetch:async url=>url==='/api/conversations/reset'?new Promise(resolve=>{release=()=>resolve(Response.json({ok:true}));}):null});
    try{
      await pause(10);await w.sendText('Удаляемый разговор');d.querySelector('#historyOpen').click();
      d.querySelector('.history-entry button:last-child').click();await pause(1);
      assert.equal(d.querySelector('#send').disabled,true);await w.sendText('Не отправлять');await w.newConversation();
      assert.equal(requests.filter(r=>r.url==='/api/chat/stream').length,1);
      release();await pause(10);assert.equal(d.querySelector('#send').disabled,false);assert.equal(d.querySelectorAll('.bubble').length,0);
      assert.equal(w.localmindSession.get().conversation_id,null);
    }finally{dom.window.close();}
  });
  await run('result chips show resolved target and observed state without upgrading REAL acceptance',async()=>{
    const {dom,w,d}=setup();try{
      await pause(10);const el=w.bubble('Result','assistant');
      w.renderStatus(el,{action_results:[{success:true,action:'set_light',resolved_target:'desk_light',execution_status:'observed',observed_state:'on',mode:'DEMO'}]});
      assert.match(el.querySelector('.action-chip').textContent,/desk_light/);assert.match(el.querySelector('.action-chip').textContent,/включено/);
      w.renderStatus(el,{action_results:[{success:true,action:'set_light',resolved_target:'desk_light',execution_status:'request_accepted',observed_state:null,mode:'REAL'}]});
      assert.match(el.querySelector('.action-chip').textContent,/состояние пока не подтверждено/);assert.ok(!el.querySelector('.action-chip').textContent.includes('Наблюдение:'));
    }finally{dom.window.close();}
  });
})().catch(error=>{console.error(error);process.exitCode=1;});
