import {test,expect} from '@playwright/test';

// Stateful browser fixtures. Real SQLite/process recovery is tested in Python.
async function product(page,baseURL,{completed=false,ready=false}={}){
  const state={onboarding:{completed},tour:{completed:false,skipped:completed},preferences:{},voice:[
    {kind:'asr',profile:'cpu-fast',model:'small',state:'model_missing'},
    {kind:'asr',profile:'balanced',model:'small',state:'model_missing'},
    {kind:'asr',profile:'gpu-quality',model:'medium',state:ready?'ready':'model_missing'},
    {kind:'tts',model:'Silero xenia',state:ready?'ready':'model_missing'}],
    ollama:{state:'ready',active_installed:true,active:'gemma4:12b',installed:['gemma4:12b']}};
  const jobs=[],mutations=[],chats=new Map();let serial=0,stream=null;
  const origin=new URL(baseURL).origin;
  await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    const body=()=>request.postDataJSON(),json=data=>route.fulfill({json:data});
    if(request.method()==='POST')mutations.push({path,body:body()});
    if(path==='/api/setup')return json(state);
    for(const section of ['onboarding','tour','preferences'])if(path==='/api/setup/'+section){
      if(request.method()==='POST')Object.assign(state[section],body());return json(state);
    }
    if(path==='/api/setup/voice'){
      const resource=body(),job={id:String(++serial).padStart(32,'0'),...resource,
        model:resource.kind==='asr'?'Whisper small':'Silero xenia',destination:'C:/Fixture/models/'+resource.kind,
        status:'downloading',completed:resource.kind==='asr'?25:60,total:100};jobs.push(job);return json(job);
    }
    if(path==='/api/downloads')return json({jobs});
    if(path.startsWith('/api/downloads/')){
      const job=jobs.find(job=>path.includes(job.id));
      if(path.endsWith('/cancel'))job.status='cancelled';
      if(path.endsWith('/retry'))job.status='starting';return json(job);
    }
    if(path==='/api/info')return json({server_instance:'f'.repeat(32),demo:true,devices:[],voice:{voices:[]}});
    if(path==='/api/conversations'){
      if(request.method()==='POST'){
        const id=String(++serial).padStart(32,'0');chats.set(id,{conversation_id:id,draft:'',messages:[],attachments:[],title:'Новый чат'});
        return json({conversation_id:id,server_instance:'f'.repeat(32)});
      }
      return json({conversations:[...chats.values()]});
    }
    if(path.startsWith('/api/conversations/')){
      const chat=chats.get(path.split('/').at(-1));if(request.method()==='PATCH')Object.assign(chat,body());
      return json({...chat,server_instance:'f'.repeat(32)});
    }
    if(path==='/api/chat/stream'){stream=route;return;}
    if(path==='/api/chat/cancel'){await stream?.abort();return json({cancelled:true});}
    return json({models:[],apps:[],sources:[],folder:{allowed:false},jobs:[]});
  });
  return {state,jobs,mutations,chats};
}

test('first setup finds installed Medium Silero and Gemma; completion and tour survive reload',async({page,baseURL})=>{
  const {state,mutations}=await product(page,baseURL,{ready:true});
  await page.goto('/');await expect(page.locator('#setupDialog')).toBeVisible();expect(mutations).toEqual([]);
  await page.locator('#setupNext').click();await expect(page.locator('#setupProfile')).toHaveValue('gpu-quality');
  await expect(page.locator('#setupDialog .model-card')).toContainText('medium — Готово');
  await page.locator('#setupNext').click();await expect(page.locator('#setupDialog .model-card')).toContainText('Silero xenia — Готово');
  await expect(page.locator('#setupDialog .model-card button')).toHaveCount(0);
  await page.locator('#setupNext').click();await expect(page.locator('.setup-content')).toContainText('gemma4:12b');
  await page.locator('#setupNext').click();await page.locator('#setupNext').click();await page.locator('#setupNext').click();
  await expect(page.locator('#setupDialog')).not.toBeVisible();await expect(page.locator('#tourPopover')).toBeVisible();
  expect(state.onboarding.completed).toBe(true);expect(mutations.some(m=>m.path==='/api/setup/voice')).toBe(false);
  await page.locator('#tourPopover').getByRole('button',{name:'Пропустить'}).click();await expect(page.locator('#tourPopover')).not.toBeVisible();
  state.voice=[];await page.reload();await expect(page.locator('#setupDialog')).not.toBeVisible();await expect(page.locator('#tourPopover')).not.toBeVisible();
  await page.locator('#settingsOpen').click();await page.locator('#tab-advanced').click();
  await page.locator('#repeatTour').click();await expect(page.locator('#tourPopover')).toBeVisible();
  await page.locator('#tourPopover').press('Escape');await expect(page.locator('#tourPopover')).not.toBeVisible();
});

test('Whisper and Silero have independent progress cancellation retry and explicit restart resume',async({page,baseURL})=>{
  const {jobs,mutations}=await product(page,baseURL);
  await page.goto('/');await expect(page.locator('#setupDialog')).toBeVisible();
  for(let i=0;i<4;i++)await page.locator('#setupNext').click();
  await page.getByRole('button',{name:'Подготовить выбранные ресурсы',exact:true}).click();
  await expect.poll(()=>jobs.length).toBe(2);expect(new Set(jobs.map(j=>j.kind)).size).toBe(2);
  await page.getByRole('button',{name:'Настроить позже',exact:true}).click();
  await page.locator('#tourPopover').getByRole('button',{name:'Пропустить'}).click();
  await page.locator('#downloadsOpen').click();const list=page.locator('#downloadsList');
  await expect(list.locator('progress')).toHaveCount(2);
  const asr=list.locator('.model-card').filter({hasText:'Whisper small'});
  const tts=list.locator('.model-card').filter({hasText:'Silero xenia'});
  await asr.getByRole('button',{name:'Отменить',exact:true}).click();await expect(asr).toContainText('Отменено');
  await expect(tts.locator('progress')).toHaveJSProperty('value',60);
  jobs[1].status='interrupted';const before=mutations.length;await page.reload();await page.locator('#downloadsOpen').click();
  await expect(list).toContainText('Прервано перезапуском');expect(mutations).toHaveLength(before);
  await list.locator('.model-card').filter({hasText:'Silero xenia'}).getByRole('button',{name:'Повторить',exact:true}).click();
  await expect(list).toContainText('Подготовка');expect(jobs[0].status).toBe('cancelled');
});

test('cancelled stream retains submitted draft and sends one cancellation without a transport retry',async({page,baseURL})=>{
  const {mutations,chats}=await product(page,baseURL,{completed:true});
  await page.goto('/');await expect(page.locator('#status')).toContainText('подключён');
  await page.locator('#message').fill('Сохранить незавершённый ввод');await page.locator('#send').click();
  await expect.poll(()=>mutations.filter(m=>m.path==='/api/chat/stream').length).toBe(1);
  expect([...chats.values()][0].draft).toBe('Сохранить незавершённый ввод');
  await page.locator('#interruptReply').click();await expect(page.locator('#send')).toBeEnabled();
  await expect(page.locator('#message')).toHaveValue('Сохранить незавершённый ввод');
  expect(mutations.filter(m=>m.path==='/api/chat/stream')).toHaveLength(1);
  expect(mutations.filter(m=>m.path==='/api/chat/cancel')).toHaveLength(1);
});
