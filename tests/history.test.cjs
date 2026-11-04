/* Durable conversation UI: server journals, safe restart, migration and failures. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {webcrypto}=require('node:crypto');
const {JSDOM}=require('jsdom');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const scripts=['marked.umd.js','purify.min.js','katex.min.js','localmind-rich.js','icons.js','constellation.js','attachments.js','speech.js','app.js','interface.js'];
function fakeServer(){
  const records=new Map(),imports=new Map(),turns=new Map();let serial=0;
  const server={records,instance:'a'.repeat(32)};
  function create(){
    const id=(++serial).toString(16).padStart(32,'0'),date=new Date().toISOString();
    records.set(id,{conversation_id:id,title:'Новый разговор',created_at:date,updated_at:date,draft:'',context:{local_retrieval:false,attachment_ids:[]},messages:[],attachments:[]});return id;
  }
  server.request=async(url,init={})=>{
    const method=init.method||'GET',body=typeof init.body==='string'?JSON.parse(init.body):{};
    if(url==='/api/conversations/import'){
      if(imports.has(body.migration_id))return Response.json({imported:false,conversation_ids:imports.get(body.migration_id)});
      const ids=body.items.map(item=>{const id=create();Object.assign(records.get(id),item,{created_at:null,updated_at:null});return id;});
      imports.set(body.migration_id,ids);return Response.json({imported:true,conversation_ids:ids});
    }
    if(url==='/api/conversations'){
      if(method==='POST'){const id=create();return Response.json({conversation_id:id,server_instance:server.instance});}
      return Response.json({conversations:[...records.values()].map(item=>({...item,message_count:item.messages.length})).reverse()});
    }
    if(url.startsWith('/api/conversations/')){
      const id=url.split('/').at(-1),item=records.get(id);
      if(!item)return Response.json({detail:'Беседа отсутствует'},{status:404});
      if(method==='DELETE'){
        if(!body.confirmed)return Response.json({detail:'Подтвердите удаление'},{status:409});
        records.delete(id);return Response.json({deleted:true});
      }
      if(method==='PATCH')Object.assign(item,body);
      return Response.json({...item,server_instance:server.instance});
    }
    if(url==='/api/chat/stream'){
      if(!turns.has(body.request_id)){
        const id=body.conversation_id||create(),item=records.get(id);
        const answer='Ответ: '+body.text;
        item.messages.push({id:body.request_id+'u',role:'user',content:body.text},{id:body.request_id+'a',role:'assistant',content:answer});
        if(item.title==='Новый разговор')item.title=body.text.slice(0,60)||'Вложения';
        item.updated_at=new Date().toISOString();
        turns.set(body.request_id,{answer,engine:'test',request_id:body.request_id,server_instance:server.instance,conversation_id:id,action_results:[],attachment_state:'included_in_inference',context_sources:body.attachment_ids.map(id=>({id}))});
      }
      return new Response(JSON.stringify({type:'final',data:turns.get(body.request_id)})+'\n');
    }
    if(url==='/api/attachments')return Response.json({id:'png-one',conversation_id:init.body.get('conversation_id'),server_instance:server.instance,state:'ready',kind:'image'});
    return Response.json({server_instance:server.instance,demo:true,model:'test',devices:[],apps:[],sources:[],voice:{}});
  };
  return server;
}
function setup(options={}){
  const dom=new JSDOM(fs.readFileSync('static/index.html','utf8'),{url:'http://127.0.0.1:8765',runScripts:'dangerously',pretendToBeVisual:true});
  const w=dom.window;w.TextDecoder=TextDecoder;w.TextEncoder=TextEncoder;w.Response=Response;
  Object.defineProperty(w.crypto,'subtle',{value:webcrypto.subtle});
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};w.confirm=()=>true;
  const requests=[],server=options.server||fakeServer();
  if(options.saved)w.localStorage.setItem('localmind.blacksite.history.v1',options.saved);
  w.fetch=async(url,init={})=>{
    requests.push({url,...init});
    const special=await options.fetch?.(url,init,server);if(special)return special;
    return server.request(url,init);
  };
  for(const name of scripts){const script=w.document.createElement('script');script.textContent=fs.readFileSync('static/assets/'+name,'utf8');w.document.head.append(script);}
  return {dom,w,d:w.document,requests,server};
}
async function run(name,fn){await fn();console.log('PASS '+name);}
async function choose(context,id){
  const row=context.d.querySelector(`[data-conversation-id="${id}"]`);assert.ok(row,'conversation appears in sidebar');
  row.querySelector('button').click();await pause(25);
}
(async()=>{
  await run('three separate server conversations reopen after full UI restart and each can continue',async()=>{
    const server=fakeServer(),ids=[];const first=setup({server});
    try{
      await pause(20);
      for(let i=1;i<=3;i++){
        if(i>1)await first.w.newConversation();
        await first.w.sendText('Беседа '+i);ids.push(first.w.localmindSession.get().conversation_id);
        first.d.querySelector('#message').value='Черновик '+i;
        first.d.querySelector('#useLocalSources').checked=i===2;
        await first.w.saveConversation();
      }
      assert.equal(new Set(ids).size,3);assert.equal(server.records.size,3);
      assert.equal(first.w.localStorage.getItem('localmind.blacksite.history.v1'),null);
    }finally{first.dom.window.close();}
    server.instance='b'.repeat(32);
    const second=setup({server});
    try{
      await pause(30);
      for(let i=1;i<=3;i++){
        await choose(second,ids[i-1]);
        assert.equal(second.w.localmindSession.get().conversation_id,ids[i-1]);
        assert.equal(second.d.querySelector('#message').value,'Черновик '+i);
        assert.equal(second.d.querySelector('#useLocalSources').checked,i===2);
        assert.equal(second.d.querySelectorAll('.bubble.me').length,1);
        assert.equal(second.d.querySelector('#message').readOnly,false);
        assert.equal(second.requests.filter(request=>request.url==='/api/chat/stream').length,i-1,'switching itself does not replay a request');
        await second.w.sendText('Продолжение '+i);
        assert.equal(server.records.get(ids[i-1]).messages.length,4);
      }
      const turns=second.requests.filter(request=>request.url==='/api/chat/stream').map(request=>JSON.parse(request.body));
      assert.deepEqual(turns.map(turn=>turn.conversation_id),ids);
      assert.ok(turns.every(turn=>turn.server_instance===server.instance));
    }finally{second.dom.window.close();}
  });
  for(const text of ['', 'Describe this PNG'])await run('transport retry keeps request identity and one attachment submission: '+(text||'image only'),async()=>{
    let uploads=0,attempts=0;const ids=[];
    const context=setup({fetch:async(url,init,server)=>{
      if(url==='/api/attachments')uploads++;
      if(url==='/api/chat/stream'){
        ids.push(JSON.parse(init.body).request_id);attempts++;
        if(attempts<=2){await server.request(url,init);throw Error('transport lost after acceptance');}
      }
    }}),{dom,w,d}=context;
    try{
      w.createImageBitmap=async()=>({close(){}});w.HTMLCanvasElement.prototype.getContext=()=>({drawImage(){}});
      w.HTMLCanvasElement.prototype.toDataURL=()=> 'data:image/png;base64,iVBORw0KGgo=';
      await pause(20);d.querySelector('#speak').checked=false;
      const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGPojjn/HwAF4gK2//l6AAAAAABJRU5ErkJggg==','base64');
      w.localmindAttachments.add([new w.File([png],'fixture.png',{type:'image/png'})]);
      for(let i=0;i<50&&w.localmindAttachments.hasPending();i++)await pause(5);
      await w.sendText(text);assert.equal(attempts,2);assert.equal(d.querySelectorAll('.bubble.me').length,1);
      assert.deepEqual([...w.localmindAttachments.contextIds()],['png-one']);
      await w.sendText(text);assert.equal(attempts,3);assert.equal(new Set(ids).size,1);assert.equal(uploads,1);
      assert.equal(d.querySelectorAll('.bubble.me').length,1);assert.equal(d.querySelectorAll('.sent-attachment canvas').length,1);
      assert.deepEqual([...w.localmindAttachments.contextIds()],[]);
      const id=w.localmindSession.get().conversation_id;await w.newConversation();await choose(context,id);
      assert.equal(d.querySelectorAll('.sent-attachment canvas').length,1);
      assert.deepEqual([...w.localmindAttachments.contextIds()],[]);
    }finally{dom.window.close();}
  });
  await run('a lost first text response retains one durable conversation and one accepted turn',async()=>{
    let attempts=0;const context=setup({fetch:async(url,init,server)=>{
      if(url==='/api/chat/stream'&&++attempts<=2){await server.request(url,init);throw Error('lost committed response');}
    }});
    try{
      await pause(20);await context.w.sendText('Первый вопрос');await context.w.sendText('Первый вопрос');
      assert.equal(context.server.records.size,1);assert.equal([...context.server.records.values()][0].messages.length,2);
      assert.equal(new Set(context.requests.filter(request=>request.url==='/api/chat/stream').map(request=>JSON.parse(request.body).request_id)).size,1);
    }finally{context.dom.window.close();}
  });
  await run('autosaves serialize older and newer drafts so delayed writes cannot overwrite newer text',async()=>{
    let release,held=false;const context=setup({fetch:async(url,init,server)=>{
      if(held&&init.method==='PATCH'){held=false;return new Promise(resolve=>{release=async()=>resolve(await server.request(url,init));});}
    }});
    try{
      await pause(20);await context.w.sendText('Разговор');held=true;
      context.d.querySelector('#message').value='Старый черновик';const first=context.w.saveConversation();await pause(1);
      context.d.querySelector('#message').value='Новый черновик';const second=context.w.saveConversation();
      await release();await Promise.all([first,second]);
      assert.equal([...context.server.records.values()][0].draft,'Новый черновик');
    }finally{context.dom.window.close();}
  });
  await run('legacy import commits before original copy is removed; reopening imported text permits continuation',async()=>{
    const original=JSON.stringify([{title:'<img src=x onerror=alert(1)>',draft:'Черновик',messages:[{role:'user',content:'Старый вопрос'},{role:'assistant',content:'Старый ответ'}]}]);
    const context=setup({saved:original});const {dom,w,d,server,requests}=context;
    try{
      await pause(35);assert.equal(w.localStorage.getItem('localmind.blacksite.history.v1'),null);
      assert.equal(server.records.size,1);assert.equal(d.querySelector('#historyList img'),null);
      assert.ok(d.querySelector('#historyList').textContent.includes('<img'));
      assert.ok(d.querySelector('#historyList').textContent.includes('Без даты'));
      assert.equal(d.querySelector('#message').value,'Черновик');assert.equal(d.querySelector('#message').readOnly,false);
      const body=JSON.parse(requests.find(request=>request.url==='/api/conversations/import').body);
      assert.match(body.migration_id,/^[a-f0-9]{64}$/);assert.equal(body.items[0].messages.length,2);
      await w.sendText('Продолжить');assert.equal([...server.records.values()][0].messages.length,4);
    }finally{dom.window.close();}
  });
  await run('invalid legacy data and failed import keep the untouched original',async()=>{
    for(const original of ['{bad',JSON.stringify([{title:'Good',messages:[{role:'system',content:'Bad'}]}]),JSON.stringify([{title:'Valid',messages:[]}])]){
      const context=setup({saved:original,fetch:async url=>url==='/api/conversations/import'?Response.json({detail:'Диск заполнен'},{status:409}):null});
      try{await pause(30);assert.equal(context.w.localStorage.getItem('localmind.blacksite.history.v1'),original);assert.match(context.d.querySelector('#historyStorage').textContent,/Исходная копия сохранена/);assert.equal(context.server.records.size,0);}
      finally{context.dom.window.close();}
    }
  });
  await run('rename is server saved text and delete requires explicit confirmation',async()=>{
    const context=setup(),{dom,w,d,server,requests}=context;
    try{
      await pause(20);await w.sendText('Переименовать');
      d.querySelector('.history-entry .text-button').click();d.querySelector('#renameInput').value='<svg onload=alert(1)>Имя';
      d.querySelector('#renameForm').dispatchEvent(new w.Event('submit',{cancelable:true}));await pause(20);
      assert.equal(d.querySelector('#historyList svg[onload]'),null);assert.equal([...server.records.values()][0].title,'<svg onload=alert(1)>Имя');
      w.confirm=()=>false;d.querySelector('.history-entry button:last-child').click();await pause(10);
      assert.equal(server.records.size,1);assert.equal(requests.filter(request=>request.method==='DELETE').length,0);
      w.confirm=()=>true;d.querySelector('.history-entry button:last-child').click();await pause(20);
      assert.equal(server.records.size,0);assert.equal(d.querySelectorAll('.bubble').length,0);
      assert.deepEqual(JSON.parse(requests.find(request=>request.method==='DELETE').body),{confirmed:true});
    }finally{dom.window.close();}
  });
  await run('write failure is visible and switching cannot silently discard an unsaved draft',async()=>{
    let fail=false;const context=setup({fetch:async(url,init)=>fail&&init.method==='PATCH'?Response.json({detail:'Диск заполнен'},{status:409}):null});
    const {dom,w,d}=context;
    try{
      await pause(20);await w.sendText('Сохранённое');d.querySelector('#message').value='Не терять';fail=true;
      await w.newConversation();assert.equal(d.querySelector('#message').value,'Не терять');assert.match(d.querySelector('#historyStorage').textContent,/Не удалось сохранить/);
      fail=false;d.querySelector('#errorDialog').close();await w.newConversation();assert.equal(d.querySelector('#message').value,'');
    }finally{dom.window.close();}
  });
  await run('delete holds send and switch paths until persistence completes without recreating the deleted row',async()=>{
    let release;const context=setup({fetch:async(url,init,server)=>init.method==='DELETE'?new Promise(resolve=>{release=async()=>resolve(await server.request(url,init));}):null});
    const {dom,w,d,server,requests}=context;
    try{
      await pause(20);await w.sendText('Удаляемый разговор');d.querySelector('.history-entry button:last-child').click();await pause(5);
      assert.equal(d.querySelector('#send').disabled,true);await w.sendText('Не отправлять');await w.newConversation();
      assert.equal(requests.filter(request=>request.url==='/api/chat/stream').length,1);
      await release();await pause(25);assert.equal(d.querySelector('#send').disabled,false);assert.equal(server.records.size,0);
      await w.saveConversation();assert.equal(server.records.size,0,'deleted conversation is never autosaved back');
    }finally{dom.window.close();}
  });
  await run('starting a new chat during active recording waits for capture disposal and preserves the old journal',async()=>{
    const context=setup(),{dom,w,d,server}=context;let stops=0;
    Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia:async()=>({getTracks:()=>[{stop:()=>stops++}],getAudioTracks:()=>[]})}});
    w.MediaRecorder=class {
      static isTypeSupported(){return true;}
      constructor(){this.state='inactive';this.mimeType='audio/webm';}
      start(){this.state='recording';}
      stop(){this.state='inactive';w.setTimeout(()=>this.onstop?.(),0);}
    };
    try{
      await pause(20);await w.sendText('Не удалять');d.querySelector('#mic').click();await pause(10);
      assert.equal(d.querySelector('#mic').getAttribute('aria-pressed'),'true');
      await w.newConversation(true);
      assert.equal(stops,1);assert.equal(d.querySelectorAll('.bubble').length,0);assert.equal(server.records.size,1);
      assert.equal([...server.records.values()][0].messages.length,2);assert.equal(d.querySelector('#send').disabled,false);
      assert.equal(d.querySelector('#mic').getAttribute('aria-pressed'),'false');
    }finally{dom.window.close();}
  });
  await run('restoring history does not restore runtime action controls or activate the microphone',async()=>{
    const context=setup(),{dom,w,d}=context;let microphones=0;
    Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia:()=>{microphones++;throw Error('unexpected');}}});
    try{
      await pause(20);await w.sendText('Текст');const id=w.localmindSession.get().conversation_id;
      const el=d.querySelector('.bubble.assistant');
      w.renderStatus(el,{action_results:[{success:true,action:'windows.list',data:{windows:[{application:'App',title:'Sensitive',window_id:'win-old'}]}}]});
      assert.ok(el.querySelector('.action-chip button'));
      await w.newConversation();await choose(context,id);
      assert.equal(d.querySelector('.action-chip button'),null);assert.equal(microphones,0);
    }finally{dom.window.close();}
  });
})().catch(error=>{console.error(error);process.exitCode=1;});
