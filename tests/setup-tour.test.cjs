/* Stateful onboarding/tour tests: no real downloads or native model probes. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const pause=()=>new Promise(resolve=>setTimeout(resolve,10));
function setup(state,options={}){
  const dom=new JSDOM(fs.readFileSync('static/index.html','utf8'),{url:'http://127.0.0.1:8765',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,d=w.document,calls=[];
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  w.fetch=async(url,init={})=>{
    const body=init.body&&JSON.parse(init.body);calls.push({url,body});
    if(options.fail&&body&&url==='/api/setup/onboarding')return Response.json({detail:'Диск заполнен'},{status:409});
    if(body&&url==='/api/setup/voice')return Response.json({id:body.kind,status:'starting'});
    if(body){const section=url.split('/').at(-1);Object.assign(state[section]??={},body);}
    return Response.json(state);
  };
  w.closeSidebar=()=>{};
  for(const file of ['tour.js','setup.js'])w.eval(fs.readFileSync('static/assets/'+file,'utf8'));
  return {dom,w,d,calls};
}
function initial(){return {onboarding:{completed:false},tour:{completed:false,skipped:false},preferences:{},voice:[
  {kind:'asr',profile:'cpu-fast',model:'small',state:'model_missing'},
  {kind:'asr',profile:'balanced',model:'small',state:'model_missing'},
  {kind:'asr',profile:'gpu-quality',model:'medium',state:'unverified'},
  {kind:'tts',model:'Silero xenia',state:'ready'}],ollama:{state:'ready',active_installed:true,active:'gemma4:12b',installed:['gemma4:12b']}};}
(async()=>{
  const state=initial();let c=setup(state);
  try{
    await pause();assert.equal(c.d.querySelector('#setupDialog').open,true);assert.equal(c.calls.filter(c=>c.body).length,0);
    assert.equal(c.d.querySelector('#setupTitle').textContent,'Добро пожаловать');
    c.d.querySelector('#setupNext').click();
    assert.equal(c.d.querySelector('#setupProfile').value,'gpu-quality');
    assert.match(c.d.querySelector('.setup-content').textContent,/medium.*нужна проверка/);
    c.d.querySelector('#setupNext').click();assert.equal(c.d.querySelectorAll('#setupDialog .model-card button').length,0,'ready Silero offers no redundant download');
    c.d.querySelector('#setupNext').click();assert.match(c.d.querySelector('.setup-content').textContent,/gemma4:12b/);
    c.d.querySelector('#setupNext').click();c.d.querySelector('#setupNext').click();c.d.querySelector('#setupNext').click();await pause();
    assert.equal(state.onboarding.completed,true);assert.equal(c.d.querySelector('#setupDialog').open,false);
    assert.equal(c.d.querySelector('#tourPopover').hidden,false);
    c.d.querySelector('#tourPopover .text-button').click();await pause();assert.equal(state.tour.skipped,true);
  }finally{c.w.close();}
  state.voice=[];state.model_storage={choice_required:true};c=setup(state);
  try{
    await pause();assert.equal(c.d.querySelector('#setupDialog').open,false,'missing resources after restart do not reset completion');
    assert.equal(c.d.querySelector('#tourPopover').hidden,true,'skipped tour stays skipped after restart');
    c.d.querySelector('#repeatTour').click();assert.equal(c.d.querySelector('#tourPopover').hidden,false);
    for(let i=0;i<4;i++)c.d.querySelector('#tourPopover .secondary').click();await pause();
    assert.equal(state.tour.completed,true);assert.equal(c.d.querySelector('#tourPopover').hidden,true);
    c.d.querySelector('#repeatSetup').click();await pause();assert.equal(c.d.querySelector('#setupDialog').open,true);
    assert.equal(c.d.querySelector('#setupTitle').textContent,'Добро пожаловать');
  }finally{c.w.close();}
  c=setup(initial(),{fail:true});
  try{
    await pause();c.d.querySelector('#setupDialog .text-button').click();await pause();
    assert.equal(c.d.querySelector('#setupDialog').open,true);assert.match(c.d.querySelector('#setupDialog .error').textContent,/Диск заполнен/);
    assert.equal(c.d.querySelector('#tourPopover').hidden,true);
  }finally{c.w.close();}
  const interrupted=initial();
  c=setup(interrupted);
  try{
    await pause();
    c.d.querySelector('#setupNext').click();
    const select=c.d.querySelector('#setupProfile');
    select.value='cpu-fast';select.dispatchEvent(new c.w.Event('change'));
    c.d.querySelector('#setupDialog input[type=checkbox]').click();
    c.d.querySelector('#setupNext').click();
    c.d.querySelector('#setupDialog input[type=checkbox]').click();
    c.d.querySelector('#setupBack').click();
    await c.w.localmindSetup.refresh();
    assert.equal(c.d.querySelector('#setupProfile').value,'cpu-fast');
    assert.equal(c.d.querySelector('#setupDialog input[type=checkbox]').checked,true);
    c.d.querySelector('#setupNext').click();
    await c.d.querySelector('#setupDialog .text-button').onclick();
    assert.equal(c.d.querySelector('#setupDialog').open,false);
    assert.equal(interrupted.onboarding.completed,false);
  }finally{c.w.close();}
  c=setup(interrupted);
  try{
    await pause();
    assert.equal(c.d.querySelector('#setupDialog').open,true);
    assert.equal(c.d.querySelector('#setupTitle').textContent,'Голос');
    assert.equal(c.d.querySelector('#setupDialog input[type=checkbox]').checked,true);
    c.d.querySelector('#setupBack').click();
    assert.equal(c.d.querySelector('#setupProfile').value,'cpu-fast');
    assert.equal(c.d.querySelector('#setupDialog input[type=checkbox]').checked,true);
    c.d.querySelector('#setupBack').click();
    assert.equal(c.d.querySelector('#setupTitle').textContent,'Добро пожаловать');
  }finally{c.w.close();}
  console.log('PASS onboarding completion, found Medium, ready Silero/Gemma, persisted tour, repeat and failed write');
})().catch(e=>{console.error(e);process.exitCode=1;});
