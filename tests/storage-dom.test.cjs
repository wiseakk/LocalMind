/* Durable preferences and reviewed storage actions through the actual UI code. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const dom=new JSDOM(fs.readFileSync('static/index.html','utf8'),{url:'http://127.0.0.1:8765',runScripts:'outside-only'});
const w=dom.window,d=w.document,calls=[];
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
const button=text=>[...d.querySelectorAll('#settings-advanced button')].find(n=>n.textContent===text);
w.fetch=async(url,options)=>{
  const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
  if(url==='/api/setup/storage')return Response.json({localmind:{data_root:'C:\\Data',notice:'restart',environment_override:false},ollama:{path:'D:\\Ollama',source:'actual server environment'}});
  if(url==='/api/setup/generation')return Response.json(body||{active:'gemma4:12b',generation:{temperature:0.4,reasoning:'auto',context_tokens:8192,response_tokens:1536,keep_alive_seconds:900}});
  if(url==='/api/setup/memory')return Response.json({policy:{keep_alive_seconds:300,cleanup_temporary:true,unload_previous:false},notice:'Shared server preserved'});
  if(url==='/api/setup/storage/plan')return Response.json({id:'reviewed',source:'C:\\Data',destination:body.destination,bytes:100,required_bytes:100,free_bytes:100000000});
  if(url==='/api/setup/storage/apply')return Response.json({state:'copied_verified',restart_required:true});
  throw Error(url);
};
w.eval(fs.readFileSync('static/assets/storage.js','utf8'));
(async()=>{
  try{
    await tick();
    assert.equal(calls.filter(c=>c.body).length,0,'initialization must not mutate settings');
    assert.equal(d.getElementById('contextTokens').value,'8192');
    assert.equal(d.getElementById('reasoning').value,'auto');
    assert.equal(d.getElementById('temperature').value,'0.4');
    assert.equal(d.getElementById('keepAlive').value,'900');
    d.getElementById('responseTokens').value='768';d.getElementById('responseTokens').dispatchEvent(new w.Event('change'));await tick();
    let saved=calls.findLast(c=>c.url==='/api/setup/generation'&&c.body).body;
    assert.equal(saved.model,'gemma4:12b');assert.equal(saved.context_tokens,8192);assert.equal(saved.temperature,0.4);
    w.dispatchEvent(new w.CustomEvent('localmind-model-selected',{detail:{model:'other:4b',temperature:0.2,reasoning:'off',context_tokens:4096,response_tokens:256,keep_alive_seconds:123}}));
    assert.equal(d.getElementById('keepAlive').value,'123','custom retention duration remains representable');
    d.getElementById('reasoning').dispatchEvent(new w.Event('change'));await tick();
    saved=calls.findLast(c=>c.url==='/api/setup/generation'&&c.body).body;
    assert.equal(saved.model,'other:4b');assert.equal(saved.keep_alive_seconds,123);
    assert.equal(saved.temperature,0.2);
    button('Проверить план переноса').click();await tick();
    const apply=button('Подтвердить копирование');assert.equal(apply.hidden,false);
    apply.click();await tick();assert.ok(!calls.some(c=>c.url.endsWith('/storage/apply')),'unchecked consent must not copy');
    const consent=[...d.querySelectorAll('#settings-advanced label')].find(n=>n.textContent.includes('Копировать данные')).querySelector('input');
    assert.equal(consent.checked,false);consent.checked=true;
    apply.click();await tick();
    assert.deepEqual(calls.findLast(c=>c.url.endsWith('/storage/apply')).body,{plan_id:'reviewed',consent:true});
    assert.equal(apply.hidden,true);assert.equal(consent.checked,false);
    console.log('PASS storage: read-only initialization, cross-model settings, custom retention and explicit reviewed copy consent');
  }finally{w.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
