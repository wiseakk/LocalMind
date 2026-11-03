/* Product navigation checks, distinct from real browser layout/voice gates. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const dom=new JSDOM(fs.readFileSync('static/index.html','utf8'),{url:'http://127.0.0.1:8765',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,d=w.document;
w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
w.fetch=async url=>Response.json(url==='/api/setup'?{voice:[{kind:'asr',state:'model_missing'},{kind:'tts',state:'model_missing'}],ollama:{state:'ready',active_installed:true}}:url==='/api/home'?{configured:false}:url==='/api/permissions/personal'?{enabled:false,roots:[],server_instance:'test'}:{jobs:[]});
w.localmindModels={refresh:()=>{}};
w.closeSidebar=()=>{};
for(const file of ['interface.js','home.js','access.js','product.js','downloads.js','setup.js'])w.eval(fs.readFileSync('static/assets/'+file,'utf8'));
(async()=>{
  try{
    await new Promise(r=>setTimeout(r,5));
    assert.deepEqual([...d.querySelectorAll('.rail-nav>button')].map(b=>b.id),['chatNav','modelsOpen','devicesOpen','downloadsOpen']);
    assert.ok(!d.querySelector('.rail-nav #historyOpen'));
    assert.equal(d.querySelector('#skyPanel').hidden,true);
    assert.equal(d.querySelector('#imageAttach').hidden,true);
    assert.equal(d.querySelector('#pauseAudio').hidden,true);
    assert.ok(d.querySelector('#settings-capabilities #manageCapabilities'));
    d.querySelector('#setupDialog').close();
    d.querySelector('#modelsOpen').click();
    assert.equal(d.querySelector('#modelsDialog').open,true);
    assert.ok(d.querySelector('#modelsDialog #modelSelect'));
    d.querySelector('#modelsDialog').close();
    d.querySelector('#downloadsOpen').click();
    assert.equal(d.querySelector('#downloadsDialog').open,true);
    d.querySelector('#downloadsDialog').close();
    const tabs=[...d.querySelectorAll('[data-settings]')];
    assert.deepEqual(tabs.map(b=>b.textContent),['Голос и микрофон','Нейросеть','Доступ к компьютеру','Общие','Дополнительно']);
    tabs[0].dispatchEvent(new w.KeyboardEvent('keydown',{key:'End',cancelable:true}));
    assert.equal(d.querySelector('#settings-advanced').hidden,false);
    w.dispatchEvent(new w.CustomEvent('localmind-playback',{detail:{active:true}}));
    assert.equal(d.querySelector('#pauseAudio').hidden,false);
    w.dispatchEvent(new w.CustomEvent('localmind-playback',{detail:{active:false}}));
    assert.equal(d.querySelector('#stopAudio').hidden,true);
    assert.ok(d.querySelector('#settings-advanced #key'));
    assert.equal(d.querySelector('#desktopAccessMode').value,'normal');
    assert.ok(d.querySelector('#homeStatus'));
    console.log('PASS product navigation, settings keyboard order, setup repair, downloads and active playback controls');
  }finally{w.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
