/* Explicit, versioned first run. Availability never decides completion. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const steps=['Добро пожаловать','Микрофон и распознавание','Голос','Нейросеть','Подготовка','Готово'];
  const labels={ready:'Готово',dependency_missing:'Компоненты отсутствуют — восстановите установку',
    model_missing:'Модель ещё не загружена',path_invalid:'Проверьте каталог ресурсов',resource_corrupt:'Файлы требуют восстановления',
    library_incompatible:'Восстановите компоненты приложения',gpu_error:'Проверьте запуск на CPU',unverified:'Файлы найдены — нужна проверка'};
  const dialog=document.createElement('dialog');dialog.id='setupDialog';dialog.setAttribute('aria-labelledby','setupTitle');
  const heading=document.createElement('h2');heading.id='setupTitle';
  const progress=document.createElement('ol');progress.className='setup-progress';progress.setAttribute('aria-label','Этапы настройки');
  const content=document.createElement('div');content.className='setup-content';
  const error=document.createElement('p');error.className='error';error.setAttribute('role','alert');error.hidden=true;
  const footer=document.createElement('div');footer.className='setup-actions';
  const back=button('Назад',()=>{step--;render();});back.id='setupBack';
  const next=button('Далее',async()=>{if(step===5)await finish();else{step++;render();if(step===4)poll();}});next.id='setupNext';
  const later=button('Настроить позже',()=>finish(true));later.className='text-button';
  footer.append(back,later,next);dialog.append(progress,heading,content,error,footer);document.body.append(dialog);
  let step=0,data=null,timer=null,loading=null,saving=false,profile='cpu-fast',skipASR=false,skipTTS=false;
  const bytes=value=>typeof value==='number'?(value/1073741824).toFixed(1)+' ГиБ':'неизвестно';
  async function modelApi(path,body){
    const r=await fetch('/api/models'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},...(body?{body:JSON.stringify(body)}:{})});
    const value=await r.json();if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'Модель недоступна');return value;
  }
  function button(text,action){const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=text;b.onclick=action;return b;}
  function paragraph(text,root=content){const p=document.createElement('p');p.textContent=text;root.append(p);return p;}
  function showError(e){error.hidden=false;error.textContent=e.message||String(e);}
  async function api(path,body){
    const r=await fetch('/api/setup'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},...(body?{body:JSON.stringify(body)}:{})});
    const value=await r.json();if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'Настройка недоступна');return value;
  }
  function resource(kind){return data?.voice?.find(v=>v.kind===kind&&(kind!=='asr'||v.profile===profile));}
  function resources(){return [{kind:'asr',profile,skip:skipASR},{kind:'tts',skip:skipTTS}];}
  function checkbox(text,checked,change){const label=document.createElement('label');label.className='check';const input=document.createElement('input');input.type='checkbox';input.checked=checked;input.onchange=()=>change(input.checked);label.append(input,text);content.append(label);}
  function resourceCard(kind){
    const row=resource(kind),card=document.createElement('article');card.className='model-card';
    paragraph((kind==='asr'?'Распознавание речи · '+(row?.model||(profile==='gpu-quality'?'medium':'small')):'Озвучка · Silero xenia')+' — '+(labels[row?.state]||'Проверяем ресурсы'),card);
    if(row?.state!=='ready'){
      const b=button(row?.state==='unverified'?'Проверить модель':'Подготовить '+(kind==='asr'?'распознавание':'озвучку'),async()=>{
        b.disabled=true;error.hidden=true;
        try{await api('/voice',{kind,...(kind==='asr'?{profile}:{})});paragraph('Задача запущена. Независимый прогресс и отмена — в «Загрузках».',card);}
        catch(e){showError(e);}finally{b.disabled=false;}
      });card.append(b);
    }
    content.append(card);
  }
  function render(){
    clearTimeout(timer);timer=null;heading.textContent=steps[step];content.replaceChildren();progress.replaceChildren();
    steps.forEach((name,index)=>{const item=document.createElement('li');item.textContent=String(index+1);item.title=name;item.setAttribute('aria-label',name);if(index===step)item.setAttribute('aria-current','step');item.classList.toggle('complete',index<step);progress.append(item);});
    back.disabled=step===0||saving;next.disabled=saving||!data;next.textContent=step===5?'Завершить настройку':'Далее';later.hidden=step===5;
    if(step===0){
      paragraph('LocalMind — ваше личное пространство для мыслей и голоса. Проверим уже установленные модели и подготовим недостающее с вашего согласия. Загрузка требует интернета, распознавание и ответы работают локально.');
      const h=data?.hardware;
      if(h)paragraph('CPU: '+(h.cpu||'неизвестно')+' · RAM: '+bytes(h.ram_total)+' · доступно: '+bytes(h.ram_available)+' · GPU: '+(h.gpus?.map(g=>g.name+' '+bytes(g.vram_total)).join(', ')||'не обнаружен, доступен CPU')+' · свободно для моделей: '+bytes(data.model_disk?.free));
    }
    if(step===1){
      paragraph('Микрофон включается только по кнопке записи. Windows спросит разрешение при первом использовании; проверьте текст перед отправкой. Аудиозаписи не сохраняются.');
      const label=document.createElement('label');label.textContent='Распознавание русской речи';const select=document.createElement('select');select.id='setupProfile';
      for(const [id,name] of [['cpu-fast','Small · CPU'],['gpu-quality','Medium · GPU или CPU']]){const o=document.createElement('option');o.value=id;o.textContent=name;select.append(o);}
      select.value=profile==='balanced'?'cpu-fast':profile;select.onchange=()=>{profile=select.value;render();};label.append(select);content.append(label);
      resourceCard('asr');checkbox(' Подготовить распознавание позже',skipASR,v=>{skipASR=v;});
      if(profile==='gpu-quality')paragraph('При выборе Medium загрузка Small не требуется. Недоступность CUDA не отменяет возможность запуска на CPU.');
    }
    if(step===2){resourceCard('tts');checkbox(' Подготовить голос позже',skipTTS,v=>{skipTTS=v;});paragraph('Silero xenia работает на CPU. Уже проверенный голос повторно не загружается.');}
    if(step===3){
      const ollama=data?.ollama;
      paragraph(ollama?.state==='ready'?(ollama.active_verified?'Нейросеть проверена и готова: '+ollama.active:'Движок работает. Выберите модель и проверьте её коротким запросом.'):(ollama?.message||'Проверяем встроенный движок…'));
      if(data.engine)paragraph(data.engine.message);
      const storage=data.model_storage;
      if(storage?.choice_required||storage?.switch_available&&storage.candidates?.some(s=>s.count>0&&!s.selected)){
        paragraph('Найдены локальные хранилища. Можно использовать готовые модели без копирования и повторной загрузки. Совместимость проверим коротким локальным запросом.');
        for(const store of storage.candidates||[]){
          const card=document.createElement('article');card.className='model-card';
          paragraph(store.source+' · '+store.path,card);
          paragraph(store.count?'Найдены: '+store.models.join(', '):'Пустой каталог — модели можно скачать позже',card);
          const use=button(store.selected?'Выбрано':store.count?'Использовать эти модели':'Использовать отдельный каталог LocalMind',async()=>{
            use.disabled=true;error.hidden=true;
            try{await api('/runtime/storage',{store_id:store.id,fingerprint:store.fingerprint});await load();}
            catch(e){showError(e);use.disabled=false;}
          });use.disabled=Boolean(store.selected);card.append(use);content.append(card);
        }
      }
      if(ollama?.saved_model&&!ollama.active_installed)paragraph('Сохранённая модель '+ollama.saved_model+' отсутствует в работающем движке.');
      if(ollama?.installed?.length)paragraph('Установлены: '+ollama.installed.join(', '));
      for(const name of ollama?.installed||[])content.append(button('Проверить и использовать '+name,async()=>{
        const buttons=[...content.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
        try{error.hidden=true;paragraph('Проверяем реальный ответ '+name+'. Первый запуск большой модели может занять до 3 минут.');await modelApi('/select',{model:name});await load();}
        catch(e){showError(e);buttons.forEach(b=>b.disabled=false);}
      }));
      if(ollama?.state!=='ready'&&!storage?.choice_required)content.append(button('Повторить запуск движка',async()=>{try{await api('/runtime/retry',{});await load();}catch(e){showError(e);}}));
      content.append(button('Обновить состояние',()=>load()));
      const catalog=button('Выбрать и скачать локальную модель',async()=>{
        catalog.disabled=true;
        try{
          const response=await modelApi('/catalog?context=4096');
          for(const row of response.models||[]){
            const card=document.createElement('article');card.className='model-card';
            paragraph(row.name+' · '+bytes(row.size)+(row.size_is_estimate?' (оценка)':'')+' · лицензия '+row.license,card);
            paragraph('RAM: от '+bytes(row.memory?.ram_minimum)+' · рекомендация '+bytes(row.memory?.ram_recommended)+' · свободно на диске '+bytes(row.disk?.free)+'. '+row.warning,card);
            const label=document.createElement('label');label.className='check';const accept=document.createElement('input');accept.type='checkbox';
            label.append(accept,' Я принимаю лицензию '+row.license+' и разрешаю эту загрузку');card.append(label);
            const pull=button('Скачать выбранную модель',async()=>{
              pull.disabled=true;
              try{await modelApi('/downloads',{source:row.source,identity:row.id,quantization:row.quantization,context:4096,accept_license:accept.checked,fingerprint:row.fingerprint});poll();}
              catch(e){showError(e);pull.disabled=false;}
            });pull.disabled=true;accept.onchange=()=>{pull.disabled=row.compatibility==='blocked'||!accept.checked;};card.append(pull);content.append(card);
          }
        }catch(e){showError(e);catalog.disabled=false;}
      });catalog.disabled=ollama?.state!=='ready';content.append(catalog);
      const jobs=document.createElement('div');jobs.id='setupModelJobs';jobs.setAttribute('aria-live','polite');content.append(jobs);poll();
      if(data?.offline_model)offlineCard();
    }
    if(step===4){
      paragraph('Загрузки разных ресурсов выполняются параллельно. Проверки моделей идут по очереди. Уже готовые файлы сохраняются.');
      const start=button('Подготовить выбранные ресурсы',async()=>{
        start.disabled=true;error.hidden=true;
        const results=await Promise.allSettled(resources().filter(r=>!r.skip&&resource(r.kind)?.state!=='ready').map(r=>api('/voice',{kind:r.kind,...(r.kind==='asr'?{profile:r.profile}:{})})));
        const failed=results.filter(r=>r.status==='rejected');if(failed.length)showError(Error(failed.map(r=>r.reason.message).join(' · ')));
        start.disabled=false;poll();
      });content.append(start);
      const jobs=document.createElement('div');jobs.id='setupJobs';jobs.setAttribute('aria-live','polite');content.append(jobs);
      content.append(button('Обновить статус',async()=>{try{data=await api('');await poll();}catch(e){showError(e);}}));
      paragraph('Можно продолжить, пока идёт подготовка, или завершить настройку без необязательных ресурсов. Ошибочную задачу можно повторить отдельно.');
    }
    if(step===5){
      paragraph(data?.ollama?.active_verified?'Нейросеть проверена реальным ответом и готова.': 'Настройки сохранены. Нейросеть ещё не проверена: вернитесь к этапу «Нейросеть» или подготовьте её позже через помощь.');
      paragraph('Беседы сохраняются локально автоматически. Для первого запроса нажмите микрофон или напишите сообщение.');
    }
  }
  function offlineCard(){
    const card=document.createElement('article');card.className='model-card';
    paragraph((data.offline_model.display_name||'Резервная модель')+' · '+data.offline_model.license,card);
    const label=document.createElement('label');label.className='check';const accept=document.createElement('input');accept.type='checkbox';label.append(accept,' Я принимаю лицензию и разрешаю импорт модели');card.append(label);
    const diskLabel=document.createElement('label');diskLabel.className='check expert-only';const disk=document.createElement('input');disk.type='checkbox';diskLabel.append(disk,' Разрешаю импорт без проверки свободного места');
    if(data.offline_disk?.free==null){paragraph('Свободное место Ollama неизвестно. Проверьте хранилище в дополнительных настройках.',card);card.append(diskLabel);}
    const b=button('Установить модель из комплекта',async()=>{b.disabled=true;try{await api('/offline-model',{accept_license:accept.checked,acknowledge_unknown_disk:disk.checked&&document.documentElement.dataset.expert==='true'});paragraph('Импорт начат. Активная нейросеть не изменится.',card);}catch(e){showError(e);}finally{b.disabled=false;}});card.append(b);content.append(card);
  }
  async function poll(){
    clearTimeout(timer);if(!dialog.open||![3,4].includes(step)||document.hidden)return;
    if(loading)return loading;
    loading=(async()=>{
      try{const r=await fetch('/api/downloads',{headers:{'X-LocalMind-Key':$('key').value}});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Загрузки недоступны');
        if(dialog.open&&[3,4].includes(step))window.localmindDownloads?.renderInto($(step===3?'setupModelJobs':'setupJobs'),d.jobs||[]);
        if(step===3&&(['checking','verifying','starting','recovering'].includes(data?.engine?.state)||
            data?.engine?.state==='ready'&&data?.ollama?.state!=='ready'))await load();
      }catch(e){showError(e);}
      finally{loading=null;if(dialog.open&&[3,4].includes(step)&&!document.hidden)timer=setTimeout(poll,1500);}
    })();return loading;
  }
  async function finish(skip=false){
    if(saving)return;saving=true;next.disabled=true;later.disabled=true;error.hidden=true;
    try{
      await api('/preferences',{voice_profile:profile});
      const result=await api('/onboarding',{completed:true,profile,skip_asr:skip||skipASR,skip_tts:skip||skipTTS});
      $('voiceProfile').value=profile==='balanced'?'cpu-fast':profile;$('voiceProfile').dispatchEvent(new Event('change'));
      data={...data,...result};dialog.close();window.dispatchEvent(new CustomEvent('localmind-setup-completed',{detail:result}));
    }catch(e){showError(e);}finally{saving=false;next.disabled=false;later.disabled=false;}
  }
  async function load(first=false){
    error.hidden=true;
    try{
      data=await api('');const prefs=data.preferences||{};
      if(first)window.dispatchEvent(new CustomEvent('localmind-preferences',{detail:prefs}));
      profile=data.onboarding?.profile||prefs.voice_profile||'cpu-fast';
      const found=row=>['ready','unverified'].includes(row.state);
      if(!data.onboarding?.profile&&!prefs.voice_profile&&data.voice?.some(v=>v.kind==='asr'&&v.model==='medium'&&found(v))&&!data.voice?.some(v=>v.kind==='asr'&&v.model==='small'&&found(v)))profile='gpu-quality';
      skipASR=Boolean(data.onboarding?.skip_asr);skipTTS=Boolean(data.onboarding?.skip_tts);
      if(first&&data.model_storage?.choice_required)step=3;
      render();
      if(first&&(data.onboarding?.completed===false||data.model_storage?.choice_required)&&!document.querySelector('dialog[open]')){dialog.showModal();poll();}
      if(first&&data.onboarding?.completed&&!data.model_storage?.choice_required)window.dispatchEvent(new CustomEvent('localmind-setup-completed',{detail:data}));
    }catch(e){showError(e);if(first&&!document.querySelector('dialog[open]')){render();dialog.showModal();content.append(button('Повторить проверку',()=>load()));}}
  }
  function open(){step=0;if(!dialog.open)dialog.showModal();load();}
  for(const id of ['repeatSetup','helpSetup'])$(id)?.addEventListener('click',()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());open();});
  const repair=button('Подготовить голос / восстановить',open);repair.id='repairVoice';$('settings-voice').append(repair);
  dialog.addEventListener('close',()=>{clearTimeout(timer);timer=null;});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else poll();});
  window.localmindSetup={open,refresh:load};load(true);
})();
