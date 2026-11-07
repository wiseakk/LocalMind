/* Real wizard code, fake API; real runtime/model evidence lives in integration logs. */
const assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM}=require('jsdom');
const pause=()=>new Promise(resolve=>setTimeout(resolve,15));
(async()=>{
  const dom=new JSDOM(fs.readFileSync('static/index.html','utf8'),{url:'http://127.0.0.1:8765',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,d=w.document,calls=[];
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  const data={onboarding:{completed:false},preferences:{},voice:[],engine:{state:'error',message:'Порт занят'},
    ollama:{state:'unavailable',installed:[],message:'Движок не готов'},hardware:{cpu:'Fixture CPU',ram_total:8*1073741824,gpus:[]},model_disk:{free:10*1073741824}};
  const row={id:'qwen3:4b-q4_K_M',name:'<img src=x> Test',size:2600000000,size_is_estimate:true,license:'Apache-2.0',
    source:'ollama',quantization:'Q4_K_M',fingerprint:'a'.repeat(64),compatibility:'estimated',disk:{free:10*1073741824},memory:{ram_minimum:4*1073741824},warning:'Оценка'};
  w.fetch=async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
    if(url==='/api/setup/runtime/retry'){data.engine={state:'ready',message:'Встроенный движок готов'};data.ollama.state='ready';return Response.json(data.engine);}
    if(url.startsWith('/api/models/catalog'))return Response.json({models:[row]});
    if(url==='/api/models/downloads'){assert.equal(body.accept_license,true);data.ollama.installed=[row.id];return Response.json({id:'job',status:'starting'});}
    if(url==='/api/models/select'){data.ollama.active=row.id;data.ollama.active_verified=true;return Response.json({active:row.id,health:{eval_count:3}});}
    if(url==='/api/downloads')return Response.json({jobs:[]});
    return Response.json(data);
  };
  w.eval(fs.readFileSync('static/assets/setup.js','utf8'));
  try{
    await pause();assert.match(d.querySelector('.setup-content').textContent,/Fixture CPU/);
    for(let i=0;i<3;i++)d.querySelector('#setupNext').click();
    const find=text=>[...d.querySelectorAll('#setupDialog button')].find(b=>b.textContent===text);
    assert.equal(find('Выбрать и скачать локальную модель').disabled,true);
    assert.equal(calls.filter(r=>r.url==='/api/models/downloads').length,0);
    find('Повторить запуск движка').click();await pause();
    find('Выбрать и скачать локальную модель').click();await pause();
    assert.equal(d.querySelector('.model-card img'),null);
    const download=find('Скачать выбранную модель');assert.equal(download.disabled,true);download.click();
    assert.equal(calls.filter(r=>r.url==='/api/models/downloads').length,0);
    const accept=d.querySelector('.model-card input[type="checkbox"]');accept.checked=true;accept.dispatchEvent(new w.Event('change'));
    download.click();await pause();
    assert.equal(calls.filter(r=>r.url==='/api/models/downloads').length,1);
    assert.equal(data.ollama.active_verified,undefined,'download alone is not active readiness');
    find('Обновить состояние').click();await pause();
    find('Проверить и использовать '+row.id).click();await pause();
    assert.equal(data.ollama.active_verified,true);
    assert.match(d.querySelector('.setup-content').textContent,/проверена и готова/);
    console.log('PASS engine wizard: hardware, retry, explicit model/license/size, no silent pull, real-probe readiness contract');
  }finally{w.close();}
  const reuse=new JSDOM(fs.readFileSync('static/index.html','utf8'),{url:'http://127.0.0.1:8765',runScripts:'outside-only',pretendToBeVisual:true});
  const rw=reuse.window,rd=rw.document,reuseCalls=[];
  rw.HTMLDialogElement.prototype.showModal=function(){this.open=true;};rw.HTMLDialogElement.prototype.close=function(){this.open=false;};
  const store={id:'b'.repeat(24),fingerprint:'c'.repeat(64),source:'Ollama',path:'C:\\Users\\fixture\\.ollama\\models',models:['gemma4:12b'],count:1};
  const state={onboarding:{completed:true},voice:[],engine:{state:'storage_choice_required',message:'Выберите каталог'},
    ollama:{state:'unavailable',installed:[]},model_storage:{choice_required:true,switch_available:true,candidates:[store]}};
  let statusReads=0,chosen=false;
  rw.fetch=async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;reuseCalls.push({url,body});
    if(url==='/api/setup/runtime/storage'){
      assert.deepEqual(body,{store_id:store.id,fingerprint:store.fingerprint});
      state.model_storage.choice_required=false;store.selected=true;state.engine.state='ready';
      chosen=true;
      // /tags may fail just before the supervisor reports ready. The wizard
      // must keep refreshing until the API's model inventory has caught up.
      state.ollama={state:'unavailable',installed:[],active_verified:false};
    }
    if(url==='/api/setup'&&chosen&&++statusReads>1)state.ollama={...state.ollama,state:'ready',installed:['gemma4:12b'],saved_model:'gemma4:12b',active_installed:true};
    if(url==='/api/models/select'){
      assert.deepEqual(body,{model:'gemma4:12b'});state.ollama.active='gemma4:12b';state.ollama.active_verified=true;
    }
    if(url==='/api/downloads')return Response.json({jobs:[]});
    return Response.json(state);
  };
  try{
    rw.eval(fs.readFileSync('static/assets/setup.js','utf8'));await pause();
    const find=text=>[...rd.querySelectorAll('#setupDialog button')].find(b=>b.textContent===text);
    assert.equal(rd.querySelector('#setupDialog').open,true,'existing onboarding does not hide storage choice');
    assert.match(rd.querySelector('#setupTitle').textContent,/Нейросеть/);
    assert.equal(reuseCalls.filter(r=>r.url==='/api/setup/runtime/storage').length,0);
    find('Использовать эти модели').click();
    for(let i=0;i<150&&!find('Проверить и использовать gemma4:12b');i++)await pause();
    assert.ok(find('Проверить и использовать gemma4:12b'),'ready engine with stale tags must refresh automatically');
    assert.equal(state.ollama.active_verified,false,'directory discovery alone never verifies weights');
    find('Проверить и использовать gemma4:12b').click();await pause();
    assert.match(rd.querySelector('.setup-content').textContent,/проверена и готова: gemma4:12b/);
    assert.equal(reuseCalls.some(r=>r.url.includes('/downloads')&&r.body),false,'reuse never starts download');
    console.log('PASS existing store: explicit consent, opaque selection, no pull, generation check before ready');
  }finally{rw.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
