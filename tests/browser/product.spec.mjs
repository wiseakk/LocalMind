import {test,expect} from '@playwright/test';

// Stateful browser fixtures. Real SQLite/process recovery is tested in Python.
async function product(page,baseURL,{completed=false,ready=false,asrSources=false,mirrorType='yandex_disk'}={}){
  const state={onboarding:{completed},tour:{completed:false,skipped:completed},preferences:{},voice:[
    {kind:'asr',profile:'cpu-fast',model:'small',state:'model_missing'},
    {kind:'asr',profile:'balanced',model:'small',state:'model_missing'},
    {kind:'asr',profile:'gpu-quality',model:'medium',state:ready?'ready':'model_missing'},
    {kind:'tts',model:'Silero xenia',state:ready?'ready':'model_missing'}],
    ollama:{state:'ready',active_installed:true,active:'gemma4:12b',installed:['gemma4:12b']}};
  const jobs=[],mutations=[],chats=new Map();let serial=0,stream=null;
  if(asrSources){
    for(const row of state.voice.filter(row=>row.kind==='asr')){
      row.download_bytes=486000000;
      row.mirror_configured=true;
      row.mirror_type=mirrorType;
    }
  }
  const origin=new URL(baseURL).origin;
  await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    const body=()=>request.postDataJSON(),json=data=>route.fulfill({json:data});
    if(path==='/api/setup/asr-import'&&asrSources){
      const query=new URL(request.url()).searchParams;
      mutations.push({path,mode:query.get('mode'),profile:query.get('profile'),bytes:request.postDataBuffer()?.length});
      const job={id:String(++serial).padStart(32,'0'),kind:'asr',profile:'cpu-fast',model:'Whisper small',
        asr_source:'local',status:'verifying',completed:10,total:10};
      jobs.push(job);return json(job);
    }
    if(request.method()==='POST')mutations.push({path,body:body()});
    if(path==='/api/setup')return json(state);
    for(const section of ['onboarding','tour','preferences'])if(path==='/api/setup/'+section){
      if(request.method()==='POST')Object.assign(state[section],body());return json(state);
    }
    if(path==='/api/setup/voice'){
      const resource=body(),job={id:String(++serial).padStart(32,'0'),...resource,
        model:resource.kind==='asr'?'Whisper small':'Silero xenia',destination:'C:/Fixture/models/'+resource.kind,
        status:'downloading',completed:resource.kind==='asr'?25:60,total:100};
      if(asrSources&&resource.kind==='asr'){
        if(['yandex','direct_https'].includes(resource.source))Object.assign(job,{asr_source:resource.source,
          updated_at:Date.now()/1000,bytes_per_second:4194304});
        else Object.assign(job,{asr_source:'huggingface',status:'failed',error:'Hugging Face недоступен.',
          asr_mirror:{type:mirrorType,fingerprint:'a'.repeat(64),bytes:486000000}});
      }
      jobs.push(job);return json(job);
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
  await expect(page.locator('#setupTitle')).toHaveText('Добро пожаловать');
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
  await page.locator('#tourPopover').getByRole('button',{name:'Далее',exact:true}).press('Escape');
  await expect(page.locator('#tourPopover')).not.toBeVisible();
});

test('direct HTTPS is offered after Hugging Face fails and retries the same job source',async({page,baseURL})=>{
  const {jobs,mutations}=await product(page,baseURL,{asrSources:true,mirrorType:'direct_https'});
  const wizard=page.locator('#setupDialog');
  await page.goto('/');
  await page.locator('#setupNext').click();
  await expect(wizard.getByText(/прямое HTTPS-зеркало/)).toBeVisible();
  const offer=wizard.getByRole('button',{name:/Скачать с HTTPS-зеркала/});
  await expect(offer).toHaveCount(0);
  await wizard.getByRole('button',{name:'Скачать Whisper',exact:true}).click();
  await expect(offer).toBeVisible();
  expect(jobs).toHaveLength(1);
  await offer.click();
  const card=wizard.locator('[data-download-id]').filter({hasText:'Источник: HTTPS-зеркало'});
  await expect(card.locator('progress')).toHaveJSProperty('value',25);
  expect(mutations.filter(entry=>entry.body?.source==='direct_https')).toHaveLength(1);
  await card.getByRole('button',{name:'Отменить',exact:true}).click();
  await expect(card).toContainText('Отменено');
  await card.getByRole('button',{name:'Повторить',exact:true}).click();
  await expect(card).toContainText('Подготовка');
  expect(mutations.some(entry=>entry.path==='/api/downloads/'+jobs[1].id+'/retry')).toBe(true);
});

test('Whisper wizard shows explicit mirror consent, progress, cancellation and local ZIP',async({page,baseURL})=>{
  const {jobs,mutations}=await product(page,baseURL,{asrSources:true});
  const wizard=page.locator('#setupDialog');
  await page.goto('/');
  await expect(page.locator('#setupTitle')).toHaveText('Добро пожаловать');
  await page.locator('#setupNext').click();
  await expect(wizard.getByText(/Hugging Face · .*МиБ/)).toBeVisible();
  await expect(wizard.getByRole('button',{name:/Скачать с Яндекс Диска/})).toHaveCount(0);
  await wizard.getByRole('button',{name:'Скачать Whisper',exact:true}).click();
  await expect(wizard.getByText(/Hugging Face недоступен/)).toBeVisible();
  expect(jobs).toHaveLength(1);
  await wizard.getByRole('button',{name:/Скачать с Яндекс Диска/}).click();
  const mirror=wizard.locator('[data-download-id]').filter({hasText:'Источник: Яндекс Диск'});
  await expect(mirror).toContainText('25%');
  await expect(mirror).toContainText('4.0 МБ/с');
  await expect(mirror.locator('progress')).toHaveJSProperty('value',25);
  expect(mutations.filter(entry=>entry.body?.source==='yandex')).toHaveLength(1);
  await mirror.getByRole('button',{name:'Отменить',exact:true}).click();
  await expect(mirror).toContainText('Отменено');
  await expect(mirror.getByRole('button',{name:'Повторить',exact:true})).toBeVisible();
  await wizard.locator('input[type=file][accept]').setInputFiles({
    name:'small.zip',mimeType:'application/zip',buffer:Buffer.from('fixture bytes'),
  });
  await expect(wizard.locator('[data-download-id]').filter({hasText:'Локальный импорт'})).toContainText('Проверяем модель');
  expect(mutations.find(entry=>entry.path==='/api/setup/asr-import')).toMatchObject({
    mode:'zip',profile:'cpu-fast',bytes:13,
  });
  await wizard.getByRole('button',{name:'Настроить позже',exact:true}).click();
  await page.locator('#settingsOpen').click();
  await page.locator('#tab-voice').click();
  await expect(page.locator('#settings-voice').getByRole('button',{name:'Импортировать из папки'})).toBeVisible();
  await expect(page.locator('#settings-voice [data-download-id]').filter({hasText:'Локальный импорт'})).toContainText('Проверяем модель');
});

test('existing model store leaves first run at welcome and preserves interrupted progress',async({page,baseURL})=>{
  const {state,mutations}=await product(page,baseURL);
  state.engine={state:'storage_choice_required',message:'Выберите каталог'};
  state.ollama={state:'unavailable',installed:[]};
  state.model_storage={choice_required:true,current_path:null,candidates:[{
    source:'Ollama',path:'C:/Fixture/.ollama/models',count:1,models:['gemma4:12b'],
  }]};
  const title=page.locator('#setupTitle');
  const next=page.locator('#setupNext');
  const back=page.locator('#setupBack');
  const current=page.locator('#setupDialog [aria-current=step]');
  await page.goto('/');
  await expect(title).toHaveText('Добро пожаловать');
  await expect(current).toHaveText('1');
  await expect(back).toBeDisabled();
  await next.click();
  await expect(current).toHaveText('2');
  await expect(page.locator('.setup-content')).toContainText('Модель ещё не загружена');
  await page.locator('#setupProfile').selectOption('gpu-quality');
  await page.getByLabel('Подготовить распознавание позже').check();
  await next.click();
  await expect(title).toHaveText('Голос');
  await expect(page.locator('.setup-content')).toContainText('Модель ещё не загружена');
  await page.getByLabel('Подготовить голос позже').check();
  await next.click();
  await expect(current).toHaveText('4');
  await expect(page.locator('.setup-content')).toContainText('Ollama входит в установщик');
  await expect(page.locator('.setup-content')).toContainText('gemma4:12b');
  await expect(page.getByRole('button',{name:'Использовать эти модели'})).toBeVisible();
  await page.getByRole('button',{name:'Настроить позже',exact:true}).click();
  await expect(page.locator('#setupDialog')).not.toBeVisible();
  expect(state.onboarding.completed).toBe(false);
  await page.reload();
  await expect(current).toHaveText('4');
  await back.click();
  await expect(page.getByLabel('Подготовить голос позже')).toBeChecked();
  await back.click();
  await expect(page.locator('#setupProfile')).toHaveValue('gpu-quality');
  await expect(page.getByLabel('Подготовить распознавание позже')).toBeChecked();
  await back.click();
  await expect(current).toHaveText('1');
  await next.click();
  await page.keyboard.press('Escape');
  await expect(page.locator('#setupDialog')).not.toBeVisible();
  await page.locator('#settingsOpen').click();
  await page.locator('#tab-advanced').click();
  await page.locator('#repeatSetup').click();
  await expect(current).toHaveText('2');
  await expect(page.getByLabel('Подготовить распознавание позже')).toBeChecked();
  expect(mutations.filter(m=>m.path!=='/api/setup/onboarding'&&m.path.startsWith('/api/setup/'))).toEqual([]);
});

test('Whisper and Silero have independent progress cancellation retry and explicit restart resume',async({page,baseURL})=>{
  const {jobs,mutations}=await product(page,baseURL);
  await page.goto('/');await expect(page.locator('#setupDialog')).toBeVisible();
  for(let i=0;i<4;i++)await page.locator('#setupNext').click();
  await page.getByRole('button',{name:'Подготовить выбранные ресурсы',exact:true}).click();
  await expect.poll(()=>jobs.length).toBe(2);expect(new Set(jobs.map(j=>j.kind)).size).toBe(2);
  await page.locator('#setupNext').click();
  await page.getByRole('button',{name:'Завершить настройку',exact:true}).click();
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
