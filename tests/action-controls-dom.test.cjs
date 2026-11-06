/* Real chat rendering/handlers, synthetic server; Python tests exercise real I/O. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(predicate){for(let i=0;i<200;i++){if(predicate())return;await pause(5);}throw Error('DOM did not settle');}
const html=fs.readFileSync('static/index.html','utf8');
const source=fs.readFileSync('static/assets/app.js','utf8');
const owner='c'.repeat(32),confirmation='p'.repeat(43);
const target='C:\\Fixture\\<img src=x>\\delete me.txt';
function pendingResult(ttl=120){return {success:false,action:'files.prepare_mutation',execution_status:'confirmation_required',
  resolved_target:confirmation,status_text:'Требуется подтверждение удаления.',data:{confirmation_id:confirmation,
    operation:'delete',path:target,requires_explicit_confirmation:true,expires_in_seconds:ttl}};}
function windowResult(){return {success:false,action:'apps.focus',execution_status:'ambiguous',status_text:'Выберите конкретное окно.',data:{windows:
  [1,2,3].map(index=>({window_id:'win-'+String(index).repeat(32),application:'Modrinth App',title:'Длинный заголовок '.repeat(12)+index+' <img src=x>'}))}};}
async function setup(result,confirmationHandler){
  const dom=new JSDOM(html,{url:'http://127.0.0.1:8765',runScripts:'dangerously',pretendToBeVisual:true});
  const w=dom.window,d=w.document,requests=[];let instance='a'.repeat(32);
  w.TextDecoder=TextDecoder;w.TextEncoder=TextEncoder;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.LocalMindSpeech=class{start(){}cancel(){}feed(){}pause(){}resume(){}};
  w.renderLocalMindMessage=(el,text)=>{el.textContent=text;};
  w.fetch=async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
    if(url==='/api/info')return Response.json({server_instance:instance,devices:[],demo:true,voice:{profiles:[],voices:[]}});
    if(url==='/api/conversations')return Response.json(options.method==='POST'?{conversation_id:owner,server_instance:instance}:{conversations:[]});
    if(url.startsWith('/api/conversations/'))return Response.json({ok:true,messages:[],context:{attachment_ids:[]}});
    if(url==='/api/chat/stream'){
      const data={answer:result.status_text,display_text:result.status_text,engine:'rules',action_results:[result],
        conversation_id:owner,server_instance:instance,...(result.execution_status==='confirmation_required'?{confirmation_required:true,pending_operation:result.data}:{})};
      return new Response(['status','final'].map(type=>JSON.stringify({type,data})).join('\n')+'\n');
    }
    if(url==='/api/files/confirm')return confirmationHandler?confirmationHandler(body):Response.json({success:body.approved,
      execution_status:body.approved?'observed':'cancelled',status_text:body.approved?'Файл удалён.':'Операция отменена.'});
    if(url==='/api/windows/select')return Response.json({success:true});
    return Response.json({});
  };
  for(const css of ['app.css','desktop.css']){const style=d.createElement('style');style.textContent=fs.readFileSync('static/assets/'+css,'utf8');d.head.append(style);}
  const script=d.createElement('script');script.textContent=source;d.head.append(script);
  await until(()=>w.localmindSession?.get().server_instance);
  await w.localmindSession.ensure();
  await w.sendText('Удали файл '+target);
  return {dom,w,d,requests,restart:async()=>{instance='b'.repeat(32);await w.refresh();}};
}
(async()=>{
  for(const approved of [true,false]){
    let complete;
    const env=await setup(pendingResult(),body=>new Promise(resolve=>{complete=()=>resolve(Response.json({success:body.approved,
      execution_status:body.approved?'observed':'cancelled',status_text:body.approved?'Файл удалён.':'Операция отменена.'}));}));
    try{
      const {d,requests,w}=env,buttons=[...d.querySelectorAll('.confirmation-actions button')];
      assert.equal(buttons.length,2,'status/final must not duplicate confirmations');
      assert.equal(d.querySelector('.confirmation-target').textContent,target);
      assert.equal(d.querySelector('.file-confirmation img'),null,'paths are text, never HTML');
      assert.equal(requests.filter(r=>r.url==='/api/files/confirm').length,0,'rendering never confirms');
      const button=buttons[approved?0:1];assert.equal(button.disabled,false);button.click();button.click();
      assert.ok(buttons.every(b=>b.disabled),'disable both while one confirmation is in flight');
      assert.equal(requests.filter(r=>r.url==='/api/files/confirm').length,1,'double click sends once');
      const body=requests.find(r=>r.url==='/api/files/confirm').body;
      assert.deepEqual(body,{conversation_id:owner,server_instance:'a'.repeat(32),confirmation_id:confirmation,approved});
      complete();await until(()=>d.querySelector('.confirmation-result').textContent.includes(approved?'Файл удалён':'отменена'));
      assert.ok(buttons.every(b=>b.disabled),'one-shot controls stay consumed');
      w.renderStatus(d.querySelector('.bubble.assistant'),{action_results:[pendingResult()],conversation_id:owner,server_instance:'a'.repeat(32)});
      assert.ok([...d.querySelectorAll('.confirmation-actions button')].every(b=>b.disabled),'a late status cannot re-enable confirmation');
    }finally{env.w.close();}
  }
  for(const failure of ['expired','restart','navigation','denied','lost-response']){
    const env=await setup(pendingResult(failure==='expired'?0:120),failure==='lost-response'?async()=>{throw Error('transport lost');}:
      failure==='denied'?async()=>Response.json({success:false,execution_status:'denied',status_text:'Право delete отозвано.'}):null);
    try{
      const button=env.d.querySelector('.confirmation-actions button');
      if(failure==='restart')await env.restart();
      if(failure==='navigation')await env.w.newConversation();
      button.click();
      if(failure==='lost-response')await until(()=>env.d.querySelector('.confirmation-result').textContent.includes('Результат не подтверждён'));
      if(failure==='denied')await until(()=>env.d.querySelector('.confirmation-result').textContent.includes('отозвано'));
      assert.equal(env.requests.filter(r=>r.url==='/api/files/confirm').length,['lost-response','denied'].includes(failure)?1:0);
      assert.ok([...env.d.querySelectorAll('.confirmation-actions button')].every(b=>b.disabled));
    }finally{env.w.close();}
  }
  const env=await setup(windowResult());
  try{
    const buttons=[...env.d.querySelectorAll('.window-choice')];assert.equal(buttons.length,3);
    assert.equal(env.w.getComputedStyle(env.d.querySelector('.window-choices')).display,'grid');
    for(const b of buttons){assert.equal(env.w.getComputedStyle(b).whiteSpace,'normal');assert.equal(env.w.getComputedStyle(b).display,'block');}
    assert.equal(env.d.querySelector('.window-choices img'),null);
    buttons[1].click();await until(()=>buttons[1].getAttribute('aria-pressed')==='true');
    assert.deepEqual(env.requests.find(r=>r.url==='/api/windows/select').body,{conversation_id:owner,window_id:'win-'+'2'.repeat(32)});
    assert.equal(buttons[0].getAttribute('aria-pressed'),'false');
  }finally{env.w.close();}
  console.log('PASS action controls: confirm/cancel, exact owner, one shot, expiry, restart, lost response, safe window selection');
})().catch(error=>{console.error(error);process.exitCode=1;});
