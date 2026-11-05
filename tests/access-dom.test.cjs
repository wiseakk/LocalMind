/* Policy preview is a draft; settings cannot silently grant full access. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const pause=()=>new Promise(resolve=>setTimeout(resolve,5));
const html=fs.readFileSync('static/index.html','utf8');
const source=fs.readFileSync('static/assets/access.js','utf8');
function setup(handler){
  const dom=new JSDOM(html,{url:'http://127.0.0.1:8765',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  w.fetch=handler;w.eval(source);return dom;
}
const initial={mode:'restricted',revision:'revision-one',server_instance:'instance-one',operations:['search','read'],roots:[{id:'docs',path:'C:\\Test\\Documents'}],rules:[],excluded:'Секреты и системные области',access_log:[]};
(async()=>{
  const requests=[];let nextPreview={draft_id:'draft-one',interpretation:'Запретить чтение <img src=x>.'},resolvePreview;
  const dom=setup(async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
    if(url==='/api/access-policy/preview')return resolvePreview?new Promise(resolve=>resolvePreview.resolve=resolve):Response.json(nextPreview);
    if(url==='/api/access-policy/apply')return Response.json({...initial,revision:'revision-two',rules:[{text:'Не трогай папку Загрузки'}]});
    if(url==='/api/access-policy'&&body)return Response.json({...initial,mode:body.mode,revision:'saved'});
    if(url==='/api/actions')return Response.json({actions:[{at:'2026-11-04',tool:'files.read',decision:'denied',denial_reason:'<script>secret</script>',policy_revision:'revision-two'}]});
    return Response.json(initial);
  }),w=dom.window,d=w.document;
  try{
    d.querySelector('#capabilitiesOpen').click();await pause();
    assert.equal(d.querySelector('#accessDialog').open,true);
    assert.equal(requests.filter(r=>r.body).length,0,'opening settings grants nothing');
    assert.equal(d.querySelectorAll('[name="accessOperation"]:checked').length,2);
    assert.equal(d.querySelector('#accessRuleScope').options[1].value,'C:\\Test\\Documents');
    d.querySelector('[name="accessMode"][value="full_user"]').click();
    d.querySelector('#saveAccess').click();await pause();
    assert.equal(requests.filter(r=>r.body).length,0,'full access requires new explicit consent');
    d.querySelector('#accessConsent').click();d.querySelector('#saveAccess').click();await pause();
    const saved=requests.find(r=>r.url==='/api/access-policy'&&r.body).body;
    assert.equal(saved.mode,'full_user');assert.equal(saved.revision,'revision-one');assert.equal(saved.server_instance,'instance-one');
    assert.deepEqual(saved.operations,['search','read']);assert.equal(d.querySelector('#accessConsent').checked,false);
    d.querySelector('#accessRuleText').value='Не трогай папку Загрузки';
    d.querySelector('#previewAccessRule').click();await pause();
    assert.equal(d.querySelector('#applyAccessRule').disabled,false);
    assert.equal(d.querySelector('#accessRuleInterpretation img'),null,'server interpretation renders as text');
    assert.equal(requests.filter(r=>r.url.endsWith('/apply')).length,0,'preview does not apply');
    d.querySelector('#cancelAccessRule').click();d.querySelector('#applyAccessRule').click();await pause();
    assert.equal(requests.filter(r=>r.url.endsWith('/apply')).length,0,'cancel removes the draft');
    d.querySelector('#previewAccessRule').click();await pause();
    d.querySelector('#accessRuleText').dispatchEvent(new w.Event('input'));assert.equal(d.querySelector('#applyAccessRule').disabled,true,'editing invalidates draft');
    nextPreview={draft_id:null,clarification:'Выберите область документов.'};d.querySelector('#previewAccessRule').click();await pause();
    assert.equal(d.querySelector('#applyAccessRule').disabled,true);assert.match(d.querySelector('#accessRuleInterpretation').textContent,/Выберите/);
    resolvePreview={};d.querySelector('#previewAccessRule').click();await pause();d.querySelector('#cancelAccessRule').click();
    resolvePreview.resolve(Response.json({draft_id:'late',interpretation:'Устаревшее правило'}));await pause();resolvePreview=null;
    assert.equal(d.querySelector('#applyAccessRule').disabled,true);assert.equal(d.querySelector('#accessRulePreview').hidden,true,'late response cannot restore canceled draft');
    nextPreview={draft_id:'draft-final',interpretation:'Запретить все операции в Загрузках.'};
    d.querySelector('#previewAccessRule').click();await pause();d.querySelector('#applyAccessRule').click();await pause();
    assert.equal(requests.filter(r=>r.url.endsWith('/apply')).length,1);assert.match(d.querySelector('#accessRules').textContent,/Загрузки/);
    assert.match(d.querySelector('#accessStatus').textContent,/сохранено/);
    d.querySelector('#refreshAccessLog').click();await pause();assert.match(d.querySelector('#actionJournal').textContent,/revision-two/);assert.equal(d.querySelector('#actionJournal script'),null);
    d.querySelector('#accessClose').click();assert.equal(d.activeElement.id,'capabilitiesOpen');
    assert.ok(!/\?{3,}|\ufffd/.test(source+html),'Russian labels survive source encoding');
    console.log('PASS access UI explicit mode choice, preview/apply/cancel, ambiguity, stale drafts and escaped audit');
  }finally{w.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
