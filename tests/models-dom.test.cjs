/* Management behavior checks, not browser screenshots or real downloads. */
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
const html=fs.readFileSync('static/index.html','utf8');
(async()=>{
  const dom=new JSDOM(html,{runScripts:'dangerously',url:'http://127.0.0.1:8765'}),w=dom.window,d=w.document,calls=[];
  const row={id:'Qwen/Test-GGUF',name:'<img src=x onerror=alert(1)>',publisher:'<script>bad()</script>',
    source:'huggingface',source_url:'https://huggingface.co/Qwen/Test-GGUF',quantization:'Q4_K_M',
    compatibility:'estimated',license:'apache-2.0',size:1000000,fingerprint:'a'.repeat(64),memory:{},disk:{status:'unknown'},capabilities:{tools:'unknown'}};
  let missing=false;
  w.fetch=async(url,options)=>{
    calls.push({url,body:options.body&&JSON.parse(options.body)});
    if(url==='/api/models')return Response.json(missing?{active:null,default:null,saved_model:'gemma4:12b',models:[]}:{active:'local:4b',models:[{name:'local:4b',selectable:true,details:{}}]});
    if(url.endsWith('/hardware'))return Response.json({gpus:[]});
    if(url.includes('/catalog?'))return Response.json({models:[row]});
    if(url==='/api/models/downloads'&&options.method==='POST'){
      const body=JSON.parse(options.body);return body.accept_license?Response.json({id:'a'}):Response.json({detail:'Подтвердите лицензию'},{status:409});
    }
    if(url.endsWith('/downloads'))return Response.json({jobs:[]});
    if(url.endsWith('/select'))return Response.json({detail:'Проверка не пройдена; выбор сохранён'},{status:409});
    if(url==='/api/models/benchmarks'&&options.method==='POST')return Response.json({id:'b'.repeat(32)});
    if(url==='/api/models/benchmarks/'+'b'.repeat(32))return Response.json({id:'b'.repeat(32),status:'incomplete',suite_version:'test-version',models:[],progress:{completed:1,total:24}});
    throw Error('Unexpected '+url);
  };
  try{
    w.eval(fs.readFileSync('static/assets/models.js','utf8'));assert.equal(calls.length,0,'no discovery/download on startup');
    await w.localmindModels.refresh();assert.equal(d.querySelector('#modelSelect').value,'local:4b');
    d.querySelector('#activateModel').click();await tick();assert.match(d.querySelector('#modelStatus').textContent,/сохранён/);
    d.querySelector('#openRegistry').click();await tick();assert.equal(d.querySelectorAll('#catalogModels img,#catalogModels script').length,0);
    assert.ok(d.querySelector('#catalogModels').textContent.includes(row.name));
    const card=d.querySelector('#catalogModels article'),pull=card.querySelector('button');
    assert.equal(card.querySelectorAll('input')[0].checked,false,'license is never preaccepted');
    assert.ok(!card.querySelectorAll('input')[1].parentElement.classList.contains('expert-only'));
    pull.click();await tick();assert.match(d.querySelector('#catalogStatus').textContent,/лицензию/);
    card.querySelectorAll('input')[0].checked=true;card.querySelectorAll('input')[1].checked=true;pull.click();await tick();
    const submitted=calls.filter(c=>c.body?.source).at(-1).body;
    assert.equal(submitted.quantization,'Q4_K_M');assert.equal(submitted.identity,'Qwen/Test-GGUF');
    assert.equal(submitted.fingerprint,'a'.repeat(64));
    assert.equal(submitted.acknowledge_unknown_disk,true);assert.equal(d.querySelector('#modelSelect').value,'local:4b');
    w.localmindModels.observe({actual_model:'actual:8b',metrics:{tokens_per_second:12},latency_ms:10});
    assert.equal(d.querySelector('#model').textContent,'actual:8b');
    w.localmindModels.observe({engine:'rules'});assert.match(d.querySelector('#modelTelemetry').textContent,/не использовалась/);
    d.querySelector('#testModels').click();await tick();await tick();
    assert.equal(calls.filter(c=>c.url==='/api/models/benchmarks').at(-1).body.models[0],'local:4b');
    assert.match(d.querySelector('#benchmarkResults').textContent,/Полное сравнение не завершено/);
    missing=true;await w.localmindModels.refresh();
    assert.equal(d.querySelector('#modelSelect').value,'');
    assert.match(d.querySelector('#modelStatus').textContent,/gemma4:12b недоступна/);
    assert.doesNotMatch(d.querySelector('#modelStatus').textContent,/Выбрана сервером/);
    console.log('PASS models: no silent discovery/download, transactional selection error, inert metadata, explicit license/quantization, real identity');
  }finally{w.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
