/* Controlled timers and HTTP doubles; no real downloads or microphone claim. */
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};

async function check(kind){
  const dom=new JSDOM(fs.readFileSync('static/index.html','utf8'),{url:'http://127.0.0.1:8765',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,d=w.document,timers=new Map();let timerId=0,hidden=false,calls=0,activeRequests=0,maxRequests=0,jobs=[],resolvePending=null,defer=false;
  const endpoint=kind==='downloads'?'/api/downloads':'/api/models/downloads';
  w.setTimeout=callback=>{timers.set(++timerId,callback);return timerId;};w.clearTimeout=id=>timers.delete(id);
  Object.defineProperty(d,'hidden',{get:()=>hidden});
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  w.fetch=async(url,options={})=>{
    if(url===endpoint&&options.method!=='POST'){
      calls++;maxRequests=Math.max(maxRequests,++activeRequests);
      const snapshot=jobs.slice();if(defer)await new Promise(resolve=>{resolvePending=resolve;});
      activeRequests--;return Response.json({jobs:snapshot});
    }
    if(url==='/api/models')return Response.json({active:'test',models:[]});
    if(url.endsWith('/hardware'))return Response.json({gpus:[]});
    return Response.json({jobs:[]});
  };
  if(kind==='models')w.eval(fs.readFileSync('static/assets/downloads.js','utf8'));
  w.eval(fs.readFileSync(`static/assets/${kind}.js`,'utf8'));
  if(kind==='models'){
    w.closeSidebar=()=>{};
    d.getElementById('settingsOpen').onclick=()=>d.getElementById('settingsDialog').showModal();
    w.eval(fs.readFileSync('static/assets/interface.js','utf8'));
    w.eval(fs.readFileSync('static/assets/product.js','utf8'));
  }
  const dialog=d.getElementById(kind==='models'?'settingsDialog':'downloadsDialog'),opener=d.getElementById(kind+'Open');
  const refresh=()=>kind==='downloads'?w.localmindDownloads.refresh():[...d.querySelectorAll('#modelCatalog button')].find(b=>b.textContent==='Обновить загрузки').click();
  const visibility=value=>{hidden=value;d.dispatchEvent(new w.Event('visibilitychange'));};
  const fire=async()=>{const callbacks=[...timers.values()];timers.clear();callbacks.forEach(fn=>fn());await settle();assert.ok(timers.size<=1,'one timer');};
  try{
    await settle();assert.equal(calls,0,'no startup polling');
    opener.click();await settle();assert.equal(calls,1,'refresh once on opening');assert.equal(timers.size,0,'idle stops');
    for(const status of ['queued','starting','downloading','verifying','cancelling']){
      jobs=[{id:'job',model:'model',status}];refresh();await settle();assert.equal(timers.size,1,status+' is active');
      const before=calls;await fire();assert.equal(calls,before+1);
      jobs=[{id:'job',model:'model',status:'succeeded'}];await fire();assert.equal(timers.size,0,'terminal stops');
    }
    for(const status of ['failed','interrupted','cancelled','cancelled_unverified']){
      jobs=[{id:'job',model:'model',status}];refresh();await settle();assert.equal(timers.size,0,status+' stops');
    }
    jobs=[{id:'job',model:'model',status:'downloading'}];refresh();await settle();
    visibility(true);await settle();assert.equal(timers.size,0,'hidden stops');
    let before=calls;await fire();assert.equal(calls,before);
    visibility(false);await settle();assert.equal(calls,before+1,'visible refreshes once');assert.equal(timers.size,1);
    if(kind==='models'){
      before=calls;w.localmindDownloads.open();await settle();
      assert.equal(timers.size,0,'covered model dialog stops polling while the shared queue is open');
      await fire();assert.equal(calls,before);
      d.getElementById('downloadsDialog').close();await settle();
      assert.equal(calls,before+1,'uncovered model dialog resumes once');assert.equal(timers.size,1);
    }
    dialog.close();await settle();before=calls;await fire();assert.equal(calls,before,'closed does not poll');
    opener.click();await settle();assert.equal(calls,before+1,'reopening refreshes');
    // Cancel/retry is explicit and must refresh and schedule if still active.
    const action=kind==='downloads'?d.querySelector('#downloadsList button'):d.querySelector('#modelDownloads button');
    before=calls;action.click();await settle();assert.equal(calls,before+1,'explicit action refreshes');
    dialog.close();await settle();defer=true;opener.click();await settle();assert.equal(activeRequests,1);
    refresh();refresh();await settle();assert.equal(activeRequests,1,'refresh coalesces while pending');
    dialog.close();await settle();resolvePending();defer=false;await settle();
    assert.equal(timers.size,0,'completion after closure cannot restart timer');
    // Reopen while the previous request is still pending: one fresh request after
    // completion, no overlapping HTTP and no stale timer resurrected by the old generation.
    defer=true;opener.click();await settle();dialog.close();await settle();opener.click();await settle();
    assert.equal(activeRequests,1);before=calls;defer=false;resolvePending();await settle();
    assert.equal(calls,before+1);assert.equal(timers.size,1);assert.equal(maxRequests,1,'no overlapping requests');
    dialog.close();await settle();assert.equal(timers.size,0);
    console.log(`PASS ${kind}: idle, active states, terminal, hidden, closed, action, reopen and pending races`);
  }finally{w.close();}
}
(async()=>{await check('downloads');await check('models');})().catch(error=>{console.error(error);process.exitCode=1;});
