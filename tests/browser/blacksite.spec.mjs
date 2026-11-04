import {test,expect} from '@playwright/test';

// Browser behavior fixtures only. Actual parser/inference integration is checked in Python.
const INSTANCE='f'.repeat(32),HISTORY_KEY='localmind.blacksite.history.v1';
const artifacts=new WeakMap();
async function setup(page,baseURL){
  const state={external:[],errors:[],requests:[],chat:[],uploads:[],conversations:new Map(),documents:new Map(),imports:new Map(),nextConversation:0,nextDocument:0};
  artifacts.set(page,state);const origin=new URL(baseURL).origin;
  page.on('pageerror',error=>state.errors.push(error.message));
  await page.route('**/*',route=>{
    const url=route.request().url();
    if(/^https?:/.test(url)&&new URL(url).origin!==origin){state.external.push(url);return route.abort('blockedbyclient');}
    return route.continue();
  });
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    state.requests.push({path,method:request.method()});
    const data=()=>request.postDataJSON();
    const json=(value,status=200)=>route.fulfill({status,json:value});
    const create=()=>{
      const id='conv'+String(++state.nextConversation).padStart(28,'0'),date=new Date().toISOString();
      state.conversations.set(id,{conversation_id:id,title:'Новый разговор',created_at:date,updated_at:date,messages:[],draft:'',context:{local_retrieval:false,attachment_ids:[]}});return id;
    };
    if(path==='/api/setup')return json({voice:[{kind:'asr',state:'ready'},{kind:'tts',state:'ready'}],ollama:{state:'ready',active_installed:true}});
    if(path==='/api/info')return json({server_instance:INSTANCE,demo:true,model:'local-fixture',devices:[{id:'desk_light',name:'Desk light',state:false}],voice:{voices:[]}});
    if(path==='/api/apps')return json({apps:[]});
    if(path==='/api/models')return json({models:[{name:'local-fixture'}],default:'local-fixture'});
    if(path==='/api/retrieval/sources')return json({sources:[]});
    if(path==='/api/files')return json({folder:{allowed:false,path:'Server-owned Downloads',fingerprint:'a'.repeat(64)},selected:null});
    if(path==='/api/conversations/import'){
      const body=data();
      if(state.imports.has(body.migration_id))return json({imported:false,conversation_ids:state.imports.get(body.migration_id)});
      const ids=body.items.map(item=>{const id=create();Object.assign(state.conversations.get(id),item,{created_at:null,updated_at:null});return id;});
      state.imports.set(body.migration_id,ids);return json({imported:true,conversation_ids:ids});
    }
    if(path==='/api/conversations'){
      if(request.method()==='POST')return json({conversation_id:create(),server_instance:INSTANCE});
      return json({conversations:[...state.conversations.values()].reverse().map(item=>({...item,message_count:item.messages.length}))});
    }
    if(path.startsWith('/api/conversations/')){
      const id=path.split('/').at(-1),item=state.conversations.get(id);
      if(!item)return json({detail:'Conversation missing'},404);
      if(request.method()==='DELETE'){
        if(data().confirmed!==true)return json({detail:'Confirmation required'},409);
        state.conversations.delete(id);return json({deleted:true});
      }
      if(request.method()==='PATCH')Object.assign(item,data());
      return json({...item,server_instance:INSTANCE,attachments:[...state.documents.values()].filter(doc=>doc.conversation_id===id)});
    }
    if(path==='/api/attachments'){
      const multipart=request.postDataBuffer().toString('utf8');
      const conversation=/name="conversation_id"\r\n\r\n([^\r]+)/.exec(multipart)?.[1];
      if(!state.conversations.has(conversation))return json({detail:'Conversation expired'},409);
      const name=/filename="([^"]+)"/.exec(multipart)?.[1]||'document.txt';
      const id='doc'+String(++state.nextDocument).padStart(29,'0');
      const document={id,name,size:24,characters:24,truncated:false,preview:'ORBIT-842 reference text',state:'ready',conversation_id:conversation,server_instance:INSTANCE};
      state.documents.set(id,document);state.uploads.push({multipart,document});return json(document);
    }
    if(path==='/api/attachments/remove'){state.documents.delete(data().attachment_id);return json({ok:true});}
    if(path==='/api/chat/stream'){
      const body=data();state.chat.push(body);const conversation=body.conversation_id||create();
      const sources=(body.attachment_ids||[]).map(id=>state.documents.get(id)).filter(Boolean).map(({id,name,characters,truncated})=>({id,name,characters,truncated}));
      const result={answer:'Local response: '+body.text,engine:'mock-local',action_results:[],context_sources:sources,conversation_id:conversation,server_instance:INSTANCE,request_id:body.request_id,attachment_state:'included_in_inference'};
      const item=state.conversations.get(conversation);
      item.messages.push({id:body.request_id+'u',role:'user',content:body.text},{id:body.request_id+'a',role:'assistant',content:result.answer});
      if(item.title==='Новый разговор')item.title=body.text.slice(0,60)||'Вложения';
      item.updated_at=new Date().toISOString();
      return route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'status',data:result})+'\n'+JSON.stringify({type:'final',data:result})+'\n'});
    }
    if(path==='/api/tts/cancel'||path==='/api/chat/cancel')return json({ok:true});
    return json({detail:'Unconfigured browser fixture endpoint '+path},503);
  });
  return state;
}
async function ready(page){
  await page.goto('/');await expect(page.locator('#status')).toContainText('\u043f\u043e\u0434\u043a\u043b\u044e\u0447');
  await page.evaluate(()=>{document.querySelector('#speak').checked=false;});
}
async function send(page,text){await page.locator('#message').fill(text);await page.locator('#send').click();await expect(page.locator('#send')).toBeEnabled();await expect(page.locator('.rendered-message').last()).toHaveText('Local response: '+text);}
async function openRail(page,id){if(await page.locator('#sidebarToggle').isVisible())await page.locator('#sidebarToggle').click();await page.locator(id).click();}
test.beforeEach(async({page,baseURL})=>{await setup(page,baseURL);});
test.afterEach(async({page},testInfo)=>{
  const state=artifacts.get(page);await testInfo.attach('local-network-and-errors',{body:JSON.stringify({external:state.external,errors:state.errors}),contentType:'application/json'});
  expect(state.external).toEqual([]);expect(state.errors).toEqual([]);
});

test('history switches messages and drafts, renames, deletes and never replays requests',async({page})=>{
  const state=artifacts.get(page);await ready(page);await send(page,'First orbit');
  await page.locator('#message').fill('Draft one');await page.locator('#newChat').click();await expect(page.locator('#thread .bubble')).toHaveCount(0);
  await send(page,'Second orbit');await page.locator('#message').fill('Draft two');
  await page.locator('.history-entry').filter({hasText:'First orbit'}).locator('button').first().click();
  await expect(page.locator('#message')).toHaveValue('Draft one');await expect(page.locator('#thread')).toContainText('Local response: First orbit');await expect(page.locator('#thread')).not.toContainText('Second orbit');
  const first=page.locator('.history-entry').filter({hasText:'First orbit'});await first.locator('.text-button').first().click();
  await page.locator('#renameInput').fill('Research notebook');await page.locator('#renameForm button[type=submit]').click();await expect(page.locator('#conversationTitle')).toHaveText('Research notebook');
  await page.locator('.history-entry').filter({hasText:'Second orbit'}).locator('button').first().click();await expect(page.locator('#message')).toHaveValue('Draft two');
  page.once('dialog',dialog=>dialog.accept());await page.locator('.history-entry').filter({hasText:'Research notebook'}).locator('.text-button').last().click();await expect(page.locator('.history-entry')).toHaveCount(1);
  expect(state.chat).toHaveLength(2);
});

test('three server journals restore across UI reload and continue independently without localStorage history',async({page})=>{
  const state=artifacts.get(page);await ready(page);const ids=[];
  for(let index=1;index<=3;index++){
    if(index>1)await page.locator('#newChat').click();
    await send(page,'Journal '+index);ids.push(state.chat.at(-1).conversation_id);
    await page.locator('#message').fill('Draft '+index);await page.evaluate(()=>saveConversation());
  }
  expect(await page.evaluate(key=>localStorage.getItem(key),HISTORY_KEY)).toBeNull();
  await page.reload();await expect(page.locator('#status')).toContainText('\u043f\u043e\u0434\u043a\u043b\u044e\u0447');
  for(let index=1;index<=3;index++){
    await page.locator(`[data-conversation-id="${ids[index-1]}"]`).locator('button').first().click();
    await expect(page.locator('#message')).toHaveValue('Draft '+index);await expect(page.locator('#message')).toBeEditable();
    await expect(page.locator('#thread .bubble.me')).toHaveCount(1);expect(state.chat).toHaveLength(index+2);
    await send(page,'Continue '+index);expect(state.chat.at(-1).conversation_id).toBe(ids[index-1]);
    expect(state.conversations.get(ids[index-1]).messages).toHaveLength(4);
  }
  expect(state.conversations.size).toBe(3);
});

test('new-conversation document upload reaches chat as opaque context, with genuine acknowledgement',async({page})=>{
  const state=artifacts.get(page);await ready(page);await page.locator('#newChat').click();
  await page.locator('#fileInput').setInputFiles({name:'research.txt',mimeType:'text/plain',buffer:Buffer.from('ORBIT-842 reference text')});
  await expect(page.locator('.attachment')).toHaveAttribute('data-state','ready');expect(state.uploads).toHaveLength(1);
  expect(state.uploads[0].multipart).toContain('ORBIT-842 reference text');await expect(page.locator('.attachment')).not.toHaveAttribute('data-state','added');
  await page.locator('.preview-button').click();await expect(page.locator('#previewText')).toHaveText('ORBIT-842 reference text');await page.locator('#previewClose').click();
  await send(page,'Describe the reference');expect(state.chat[0].attachment_ids).toEqual([state.uploads[0].document.id]);expect(JSON.stringify(state.chat[0])).not.toContain('ORBIT-842');
  await expect(page.locator('.attachment')).toHaveCount(0);await expect(page.locator('.sent-attachment')).toHaveCount(1);
  await page.locator('#newChat').click();await send(page,'Isolated conversation');expect(state.chat[1].attachment_ids).toEqual([]);
  await page.locator('.history-entry').filter({hasText:'Describe the reference'}).locator('button').first().click();
  await expect(page.locator('.attachment')).toHaveCount(0);await expect(page.locator('.sent-attachment')).toHaveCount(1);expect(await page.evaluate(()=>localmindAttachments.contextIds())).toEqual([]);
  await send(page,'Without the document');expect(state.chat[2].attachment_ids).toEqual([]);
});

for(const text of ['', 'What is in this image?'])test(`PNG sent thumbnail clears composer: ${text || 'image only'}`,async({page})=>{
  const state=artifacts.get(page);await ready(page);
  const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=32;c.height=24;c.getContext('2d').fillRect(0,0,32,24);return c.toDataURL('image/png').split(',')[1];});
  await page.locator('#imageInput').setInputFiles({name:'actual.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
  await expect(page.locator('.attachment')).toHaveAttribute('data-state','ready');
  await send(page,text);await expect(page.locator('#attachmentList .attachment')).toHaveCount(0);
  await expect(page.locator('.bubble.me .sent-attachment canvas')).toBeVisible();
  await expect(page.locator('.sent-attachment canvas')).toHaveAttribute('data-rendered','true');
  expect(await page.locator('.sent-attachment canvas').evaluate(canvas=>canvas.dataset.rendered==='true')).toBe(true);
  expect(state.uploads).toHaveLength(1);expect(state.chat[0].attachment_ids).toHaveLength(1);
  await send(page,'Follow up');expect(state.chat[1].attachment_ids).toEqual([]);
  await page.locator('#newChat').click();await send(page,'Other chat');
  await page.locator('.history-entry').filter({hasText:text||'Вложения'}).locator('button').first().click();
  await expect(page.locator('.sent-attachment canvas')).toBeVisible();await expect(page.locator('#attachmentList .attachment')).toHaveCount(0);
});

test('product navigation dialogs retain keyboard focus and keep the chat draft',async({page})=>{
  await ready(page);await page.locator('#message').fill('Keep this draft');
  for(const [opener,dialog] of [['#settingsOpen','#settingsDialog'],['#modelsOpen','#settingsDialog'],['#downloadsOpen','#downloadsDialog'],['#devicesOpen','#devicesDialog']]){
    await openRail(page,opener);await expect(page.locator(dialog)).toBeVisible();
    for(let i=0;i<12;i++)await page.keyboard.press('Tab');expect(await page.locator(dialog).evaluate(el=>el.contains(document.activeElement))).toBe(true);
    await page.keyboard.press('Escape');await expect(page.locator(dialog)).not.toBeVisible();await expect(page.locator(opener)).toBeFocused();
  }
  await expect(page.locator('#graphToggle')).not.toBeVisible();
  await expect(page.locator('#imageAttach')).not.toBeVisible();
  await expect(page.locator('.rail-nav #historyOpen')).toHaveCount(0);
  await expect(page.locator('#message')).toHaveValue('Keep this draft');
});

for(const viewport of [{name:'desktop',width:1440,height:1000},{name:'mobile',width:390,height:844}])for(const zoom of [1,1.25,1.4,1.5,2])test(`${viewport.name} workspace CSS zoom stress ${zoom*100}%`,async({page},testInfo)=>{
  await page.setViewportSize({width:viewport.width,height:viewport.height});await ready(page);await page.evaluate(z=>document.documentElement.style.zoom=z,zoom);
  await page.evaluate(()=>document.fonts.ready);
  await expect(page.locator('#message')).toBeInViewport();await expect(page.locator('#mic')).toBeInViewport();await expect(page.locator('#send')).toBeInViewport();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(page.locator('#skyPanel')).not.toBeVisible();
  const shot=await page.screenshot({fullPage:true});await testInfo.attach(`${viewport.name}-${zoom}-CSS-zoom-scene`,{body:shot,contentType:'image/png'});
  await openRail(page,'#downloadsOpen');await expect(page.locator('#downloadsDialog')).toBeInViewport();await page.keyboard.press('Escape');
});
