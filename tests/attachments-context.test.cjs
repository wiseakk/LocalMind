const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const tick=()=>new Promise(r=>setTimeout(r,0));
function fixture(request){
  const dom=new JSDOM(`<div id="attachmentList"></div><div id="attachmentNotice" hidden></div><input id="showFilenames" type="checkbox"><button id="attach"></button><input id="fileInput" type="file"><button id="imageAttach"></button><input id="imageInput" type="file"><div id="dropZone"></div><textarea id="message"></textarea><div id="filesList"></div><dialog id="attachmentPreview"><h2 id="previewTitle"></h2><canvas id="previewCanvas"></canvas><p id="previewNote"></p><button id="previewClose"></button></dialog>`,{runScripts:'dangerously',url:'http://127.0.0.1:8765'});
  const w=dom.window;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.fetch=request;
  w.eval(fs.readFileSync('static/assets/attachments.js','utf8'));
  const a=w.localmindAttachments;
  a.configure({getSession:async()=>({conversation_id:'one',server_instance:'server'}),request});
  return {dom,w,a,d:w.document};
}
const ready=(id='doc')=>({id,name:'note.md',size:5,characters:5,preview:'<script>untrusted</script>',truncated:false,state:'ready',conversation_id:'one',server_instance:'server'});
async function run(name,fn){await fn();console.log('PASS '+name);}
(async()=>{
  await run('documents enter context only after server identity and inference acknowledgement',async()=>{
    let resolve;const calls=[];
    const {dom,w,a,d}=fixture(async(url,options)=>{calls.push({url,options});return new Promise(r=>{resolve=r;});});
    try{
      a.add([new w.File(['hello'],'note.md',{type:'text/markdown'})]);
      await tick();assert.equal(a.hasPending(),true);assert.deepEqual([...a.contextIds()],[]);
      assert.equal(calls[0].url,'/api/attachments');assert.equal(calls[0].options.body.get('conversation_id'),'one');assert.equal(calls[0].options.body.get('server_instance'),'server');
      resolve(Response.json(ready()));await tick();await tick();
      assert.equal(a.hasPending(),false);assert.equal(a.snapshot()[0].state,'ready');assert.deepEqual([...a.contextIds()],['doc']);assert.equal(a.snapshot()[0].hasFile,false);
      a.acknowledge([{id:'other'}]);assert.equal(a.snapshot()[0].state,'ready');a.acknowledge([{id:'doc'}]);assert.equal(a.snapshot()[0].state,'added');
      d.querySelector('.preview-button').click();assert.equal(d.querySelector('#previewText').textContent,'<script>untrusted</script>');assert.equal(d.querySelector('#previewText script'),null);assert.equal(d.querySelector('#attachmentPreview').open,true);
    }finally{dom.window.close();}
  });
  await run('removal during parsing cleans late server result without resurrecting context',async()=>{
    let resolve;const removed=[];
    const {dom,w,a,d}=fixture(async(url,options)=>url.endsWith('/remove')?(removed.push(JSON.parse(options.body)),Response.json({ok:true})):new Promise(r=>{resolve=r;}));
    try{
      a.add([new w.File(['hello'],'note.md')]);await tick();d.querySelector('.attachment .icon-button').click();assert.equal(a.snapshot().length,0);
      resolve(Response.json(ready('late')));await tick();await tick();assert.equal(a.snapshot().length,0);assert.equal(d.querySelectorAll('.attachment').length,0);assert.equal(removed[0].attachment_id,'late');assert.deepEqual([...a.contextIds()],[]);
    }finally{dom.window.close();}
  });
  await run('conversation switching isolates and restores pending document results',async()=>{
    let resolve;const {dom,w,a}=fixture(async()=>new Promise(r=>{resolve=r;}));
    try{
      a.add([new w.File(['hello'],'note.md')]);await tick();a.setConversation('two');resolve(Response.json(ready()));await tick();await tick();
      assert.equal(a.snapshot().length,0);assert.deepEqual([...a.contextIds()],[]);a.setConversation('one');assert.equal(a.snapshot()[0].state,'ready');assert.deepEqual([...a.contextIds()],['doc']);
    }finally{dom.window.close();}
  });
  await run('new draft UUID migrates to server identity without cancelling the upload',async()=>{
    const {dom,w,a}=fixture(async()=>Response.json(ready()));
    try{
      a.setConversation('local-draft-uuid');
      a.configure({getSession:async()=>{a.adoptConversation('one');return {conversation_id:'one',server_instance:'server'};},request:async()=>Response.json(ready())});
      a.add([new w.File(['hello'],'note.md')]);await tick();await tick();
      assert.equal(a.snapshot()[0].state,'ready');assert.deepEqual([...a.contextIds()],['doc']);
      a.setConversation('other');assert.equal(a.snapshot().length,0);a.setConversation('one');assert.deepEqual([...a.contextIds()],['doc']);
    }finally{dom.window.close();}
  });
  await run('messages-first server identity preserves image-only draft rows',async()=>{
    const {dom,w,a}=fixture(async()=>{throw Error('images must not upload');});
    try{
      w.HTMLCanvasElement.prototype.getContext=()=>({drawImage(){}});w.createImageBitmap=async()=>({close(){}});
      const bytes=new Uint8Array(24),view=new DataView(bytes.buffer);view.setUint32(0,0x89504e47);view.setUint32(4,0x0d0a1a0a);view.setUint32(16,2);view.setUint32(20,2);
      a.add([new w.File([bytes],'preview.png',{type:'image/png'})]);await new Promise(r=>setTimeout(r,25));assert.equal(a.snapshot()[0].state,'image');
      a.adoptConversation('messages-first-server');assert.equal(a.snapshot().length,1);
      a.setConversation('other');a.setConversation('messages-first-server');assert.equal(a.snapshot()[0].state,'image');assert.deepEqual([...a.contextIds()],[]);
    }finally{dom.window.close();}
  });
  await run('foreign server identity and parser errors never become context',async()=>{
    const {dom,w,a}=fixture(async()=>Response.json({...ready(),server_instance:'foreign'}));
    try{a.add([new w.File(['hello'],'note.md')]);await tick();await tick();assert.equal(a.snapshot()[0].state,'error');assert.deepEqual([...a.contextIds()],[]);}finally{dom.window.close();}
    const second=fixture(async()=>Response.json({detail:'Сканированный PDF: текст отсутствует'},{status:422}));
    try{second.a.add([new second.w.File(['pdf'],'scan.pdf')]);await tick();await tick();assert.equal(second.a.snapshot()[0].state,'error');assert.ok(second.d.querySelector('.attachment-state').textContent.includes('Сканированный'));}finally{second.dom.window.close();}
  });
  await run('count/size validation precedes network and privacy labels treat filenames as text',async()=>{
    let calls=0;const {dom,w,a,d}=fixture(async()=>{calls++;return Response.json(ready());});
    try{
      a.add(Array.from({length:9},()=>new w.File(['x'],'x.txt')));assert.equal(a.snapshot().length,0);assert.equal(calls,0);
      const file=new w.File(['x'],'large.pdf');Object.defineProperty(file,'size',{value:10*1024*1024+1});a.add([file]);await tick();assert.equal(a.snapshot()[0].state,'error');assert.equal(calls,0);a.reset();
      a.add([new w.File(['x'],'<img onerror=alert(1)>\u202esecret.txt')]);await tick();await tick();assert.ok(!d.querySelector('#attachmentList').textContent.includes('secret'));
      d.querySelector('#showFilenames').checked=true;d.querySelector('#showFilenames').dispatchEvent(new w.Event('change'));assert.ok(d.querySelector('.attachment-name').textContent.includes('<img'));assert.equal(d.querySelector('#attachmentList img'),null);assert.ok(!d.querySelector('.attachment-name').textContent.includes('\u202e'));
    }finally{dom.window.close();}
  });
  await run('oversized image is rejected before decode and images never upload',async()=>{
    let uploads=0,decodes=0;const {dom,w,a}=fixture(async()=>{uploads++;return Response.json(ready());});
    try{
      w.createImageBitmap=async()=>{decodes++;throw Error('unexpected decode');};const bytes=new Uint8Array(24),view=new DataView(bytes.buffer);view.setUint32(0,0x89504e47);view.setUint32(4,0x0d0a1a0a);view.setUint32(16,8193);view.setUint32(20,2);
      a.add([new w.File([bytes],'huge.png',{type:'image/png'})]);await new Promise(r=>setTimeout(r,25));assert.equal(a.snapshot()[0].state,'error');assert.equal(decodes,0);assert.equal(uploads,0);
    }finally{dom.window.close();}
  });
})().catch(error=>{console.error(error);process.exitCode=1;});
