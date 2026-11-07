/* Durable download rendering and actions; these are DOM tests, not real pulls. */
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
(async()=>{
  const dom=new JSDOM(fs.readFileSync('static/index.html','utf8'),{runScripts:'dangerously',pretendToBeVisual:true,url:'http://127.0.0.1:8765'});
  const w=dom.window,d=w.document,calls=[];
  let jobs=[{id:'one',kind:'llm',model:'<img src=x>',status:'downloading',completed:50,total:100,destination:'C:/Модели с пробелами'},
    {id:'two',kind:'llm',model:'test',status:'cancelling'},
    {id:'three',kind:'llm',model:'test',status:'succeeded',completed:100,total:100},
    {id:'four',kind:'llm',model:'test',status:'cancelled_unverified'}];
  const confirmations=[];
  w.fetch=async(url,options)=>{
    calls.push(url);
    if(url==='/api/setup/voice')confirmations.push(JSON.parse(options.body));
    if(url.endsWith('/dismiss'))jobs=jobs.map(job=>job.id==='three'?{...job,dismissed:true}:job);
    return Response.json(url==='/api/downloads'?{jobs}:{});
  };
  try{
    w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
    w.eval(fs.readFileSync('static/assets/downloads.js','utf8'));
    w.localmindDownloads.open();await tick();
    await w.localmindDownloads.refresh();
    const card=id=>d.querySelector(`[data-download-id="${id}"]`);
    assert.equal(card('one').querySelector('progress').value,50);
    assert.match(card('one').textContent,/C:\/Модели с пробелами/);
    assert.equal(card('one').querySelectorAll('img').length,0);
    assert.equal(card('two').querySelector('progress').hasAttribute('value'),false,'unknown size is indeterminate');
    assert.match(card('two').textContent,/Отмена запрошена/);
    assert.equal(card('two').querySelector('button').disabled,true);
    assert.equal([...card('three').querySelectorAll('button')].some(button=>button.textContent==='Повторить'),false);
    assert.match(card('four').textContent,/остановка Ollama не подтверждена/);
    card('three').querySelector('button').click();await tick();await tick();
    assert.equal(card('three'),null);
    assert.ok(calls.includes('/api/downloads/three/dismiss'));
    assert.equal(calls.some(url=>url.includes('delete')||url.includes('select')),false);
    const other=d.createElement('div');w.localmindDownloads.renderInto(other,jobs);
    assert.match(other.textContent,/Отмена запрошена/,'catalog uses identical renderer');
    const fingerprint='f'.repeat(64);
    jobs.push({id:'hf',kind:'asr',model:'Whisper medium',profile:'gpu-quality',asr_source:'huggingface',
      status:'failed',asr_mirror:{type:'direct_https',fingerprint,bytes:1500000000}});
    jobs.push({id:'direct',kind:'asr',model:'Whisper medium',asr_source:'direct_https',
      status:'downloading',completed:750000000,total:1500000000});
    await w.localmindDownloads.refresh();
    assert.match(card('direct').textContent,/HTTPS-зеркало/);
    assert.match(card('direct').textContent,/50%/);
    assert.equal(card('direct').querySelector('progress').value,750000000);
    assert.deepEqual(confirmations,[]);
    [...card('hf').querySelectorAll('button')].find(button=>button.textContent.startsWith('Скачать с HTTPS-зеркала')).click();
    await tick();
    assert.deepEqual(confirmations,[{kind:'asr',profile:'gpu-quality',source:'direct_https',fingerprint}]);
    console.log('PASS downloads: real byte progress, unknown total, destination, truthful cancellation, durable dismiss action, shared renderer');
  }finally{w.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
