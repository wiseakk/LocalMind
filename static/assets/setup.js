/* Explicit, versioned first run. Availability never decides completion. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const steps=['Добро пожаловать','Микрофон и распознавание','Голос','Нейросеть','Подготовка','Завершение'];
  const labels={ready:'Готово',dependency_missing:'Компоненты отсутствуют — восстановите установку',
    model_missing:'Модель ещё не загружена',path_invalid:'Проверьте каталог ресурсов',resource_corrupt:'Файлы требуют восстановления',
    library_incompatible:'Восстановите компоненты приложения',gpu_error:'Проверьте запуск на CPU',unverified:'Файлы найдены — нужна проверка'};
  const dialog=document.createElement('dialog');dialog.id='setupDialog';dialog.setAttribute('aria-labelledby','setupTitle');
  const heading=document.createElement('h2');heading.id='setupTitle';
  const progress=document.createElement('ol');progress.className='setup-progress';progress.setAttribute('aria-label','Этапы настройки');
  const content=document.createElement('div');content.className='setup-content';
  const error=document.createElement('p');error.className='error';error.setAttribute('role','alert');error.hidden=true;
  const footer=document.createElement('div');footer.className='setup-actions';
  const back=button('Назад',()=>move(-1));back.id='setupBack';
  const next=button('Далее',()=>step===steps.length-1?finish():move(1));next.id='setupNext';
  const later=button('Настроить позже',pauseSetup);later.className='text-button';
  footer.append(back,later,next);dialog.append(progress,heading,content,error,footer);document.body.append(dialog);
  let step=0,data=null,timer=null,loading=null,saving=false,profile='cpu-fast',skipASR=false,skipTTS=false;
  let initialized=false,pendingProgress=Promise.resolve();
  let activeImport=null;
  const reportedAsrJobs=new Set();
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
  function resourceStatus(kind){
    return labels[resource(kind)?.state]||(data?'Состояние ресурса не подтверждено':'Проверяем ресурсы');
  }
  function resources(){return [{kind:'asr',profile,skip:skipASR},{kind:'tts',skip:skipTTS}];}
  function progressValues(){return {step,profile,skip_asr:skipASR,skip_tts:skipTTS};}
  function saveProgress(){
    if(!initialized||data.onboarding?.completed)return pendingProgress;
    const snapshot=progressValues();
    pendingProgress=pendingProgress.catch(()=>{}).then(()=>api('/onboarding',snapshot));
    pendingProgress.catch(showError);
    return pendingProgress;
  }
  function move(delta){
    step+=delta;
    saveProgress();
    render();
    poll();
  }
  async function pauseSetup(){
    if(saving)return;
    saving=true;render();error.hidden=true;
    try{await saveProgress();dialog.close();}
    catch(e){showError(e);}
    finally{saving=false;render();}
  }
  function checkbox(text,checked,change){const label=document.createElement('label');label.className='check';const input=document.createElement('input');input.type='checkbox';input.checked=checked;input.onchange=()=>change(input.checked);label.append(input,text);content.append(label);}
  function resourceCard(kind,root=content,selected=profile){
    const row=kind==='asr'?data?.voice?.find(v=>v.kind==='asr'&&v.profile===selected):resource(kind);
    const card=document.createElement('article');card.className='model-card';
    paragraph((kind==='asr'?'Распознавание речи · '+(row?.model||(selected==='gpu-quality'?'medium':'small')):'Озвучка · Silero xenia')+
      ' — '+(labels[row?.state]||'Состояние ресурса не подтверждено'),card);
    if(kind==='asr'&&row?.state!=='ready'){
      if(row?.download_bytes)paragraph('Hugging Face · '+(row.download_bytes/1048576).toFixed(1)+' МиБ. '+
        (row.mirror_configured?'При ошибке сети можно выбрать зеркало Яндекс Диска.':'Зеркало Яндекс Диска не настроено.'),card);
      if(row&&row.state!=='dependency_missing')addAsrImport(card,row,selected,root===content);
    }
    if(row?.state!=='ready'){
      const b=button(row?.state==='unverified'?'Проверить модель':kind==='asr'?'Скачать Whisper':'Подготовить озвучку',async()=>{
        b.disabled=true;error.hidden=true;
        try{
          await api('/voice',{kind,...(kind==='asr'?{profile:selected}:{})});
          poll();
          paragraph('Задача запущена. Прогресс и отмена доступны в «Загрузках».',card);
        }catch(e){paragraph(e.message,card);}finally{b.disabled=false;}
      });b.disabled=row?.state==='dependency_missing';card.append(b);
    }
    root.append(card);
  }
  function addAsrImport(card,row,selected,inWizard){
    for(const mode of ['zip','directory']){
      const input=document.createElement('input');input.type='file';input.hidden=true;
      if(mode==='zip')input.accept='.zip,application/zip';
      else input.setAttribute('webkitdirectory','');
      const choose=button(mode==='zip'?'Импортировать из файла':'Импортировать из папки',()=>input.click());
      choose.dataset.asrPicker='';choose.disabled=activeImport!==null;
      input.onchange=()=>{
        const files=Array.from(input.files);input.value='';
        if(!files.length)return;
        if(mode==='zip'){
          importAsr(card,files[0],mode,selected);
          return;
        }
        const parts=(row.import_files||[]).map(asset=>files.filter(file=>file.name===asset.name&&file.size===asset.bytes));
        if(!parts.length||parts.some(matches=>matches.length!==1)||
           new Set(parts.map(([file])=>file.webkitRelativePath.split('/').slice(0,-1).join('/'))).size!==1){
          paragraph('В выбранной папке нужен полный комплект файлов этой версии Whisper.',card);
          return;
        }
        importAsr(card,new Blob(parts.map(([file])=>file)),mode,selected);
      };
      card.append(input,choose);
    }
    if(activeImport&&(inWizard||!dialog.open))card.append(activeImport);
  }
  function importAsr(card,blob,mode,selected){
    if(activeImport)return;
    const xhr=new XMLHttpRequest();
    const started=performance.now();
    const panel=document.createElement('div');
    const status=paragraph('Передаём выбранные файлы локальному приложению…',panel);
    const meter=document.createElement('progress');
    meter.setAttribute('aria-label','Передача файлов Whisper');meter.max=blob.size;meter.value=0;
    const cancel=button('Отмена импорта',()=>xhr.abort());
    panel.append(meter,cancel);card.append(panel);activeImport=panel;
    document.querySelectorAll('[data-asr-picker]').forEach(control=>control.disabled=true);
    xhr.open('POST','/api/setup/asr-import?'+new URLSearchParams({profile:selected,mode}));
    xhr.setRequestHeader('X-LocalMind-Key',$('key').value);
    xhr.setRequestHeader('Content-Type','application/octet-stream');
    xhr.responseType='json';xhr.timeout=610000;
    xhr.upload.onprogress=event=>{
      meter.value=event.loaded;
      const seconds=(performance.now()-started)/1000;
      const rate=seconds>=1?' · '+(event.loaded/1048576/seconds).toFixed(1)+' МиБ/с':'';
      status.textContent='Локальный импорт · '+Math.floor(100*event.loaded/blob.size)+'%'+rate;
    };
    xhr.upload.onload=()=>{
      cancel.disabled=true;
      status.textContent='Файлы переданы. Ожидаем задачу проверки…';
    };
    xhr.onload=()=>{
      if(xhr.status>=200&&xhr.status<300){
        status.textContent='Файлы получены. Проверяем модель Whisper.';
        poll();
      }else status.textContent=xhr.response?.detail||'Не удалось передать файлы.';
    };
    xhr.onerror=xhr.ontimeout=()=>{status.textContent='Передача файлов прервана. Выберите файл или папку снова.';};
    xhr.onabort=()=>{
      status.textContent='Передача остановлена. Если проверка уже началась, отмените её в списке задач.';
      poll();
    };
    xhr.onloadend=()=>{
      cancel.remove();meter.remove();activeImport=null;
      document.querySelectorAll('[data-asr-picker]').forEach(control=>control.disabled=false);
    };
    xhr.send(blob);
  }
  function render(){
    clearTimeout(timer);timer=null;heading.textContent=steps[step];content.replaceChildren();progress.replaceChildren();
    steps.forEach((name,index)=>{const item=document.createElement('li');item.textContent=String(index+1);item.title=name;item.setAttribute('aria-label',name);if(index===step)item.setAttribute('aria-current','step');item.classList.toggle('complete',index<step);progress.append(item);});
    back.disabled=step===0||saving;next.disabled=saving||!data;next.textContent=step===5?'Завершить настройку':'Далее';later.disabled=saving;later.hidden=step===5;
    if(step===0){
      paragraph('LocalMind — ваше личное пространство для мыслей и голоса. Проверим уже установленные модели и подготовим недостающее с вашего согласия. Загрузка требует интернета, распознавание и ответы работают локально.');
      const h=data?.hardware;
      if(h)paragraph('CPU: '+(h.cpu||'неизвестно')+' · RAM: '+bytes(h.ram_total)+' · доступно: '+bytes(h.ram_available)+' · GPU: '+(h.gpus?.map(g=>g.name+' '+bytes(g.vram_total)).join(', ')||'не обнаружен, доступен CPU')+' · свободно для моделей: '+bytes(data.model_disk?.free));
    }
    if(step===1){
      paragraph('Микрофон включается только по кнопке записи. Windows спросит разрешение при первом использовании; проверьте текст перед отправкой. Аудиозаписи не сохраняются.');
      const label=document.createElement('label');label.textContent='Распознавание русской речи';const select=document.createElement('select');select.id='setupProfile';
      for(const [id,name] of [['cpu-fast','Small · CPU'],['gpu-quality','Medium · GPU или CPU']]){const o=document.createElement('option');o.value=id;o.textContent=name;select.append(o);}
      select.value=profile==='balanced'?'cpu-fast':profile;select.onchange=()=>{profile=select.value;saveProgress();render();};label.append(select);content.append(label);
      resourceCard('asr');checkbox(' Подготовить распознавание позже',skipASR,v=>{skipASR=v;saveProgress();});
      const jobs=document.createElement('div');jobs.id='setupAsrJobs';jobs.setAttribute('aria-live','polite');content.append(jobs);
      poll();
      if(profile==='gpu-quality')paragraph('При выборе Medium загрузка Small не требуется. Недоступность CUDA не отменяет возможность запуска на CPU.');
    }
    if(step===2){resourceCard('tts');checkbox(' Подготовить голос позже',skipTTS,v=>{skipTTS=v;saveProgress();});paragraph('Silero xenia работает на CPU. Уже проверенный голос повторно не загружается.');}
    if(step===3){
      const ollama=data?.ollama;
      paragraph('Движок Ollama входит в установщик LocalMind. Отдельно скачивать или устанавливать Ollama не нужно.');
      paragraph(ollama?.state==='ready'?(ollama.active_verified?'Нейросеть проверена и готова: '+ollama.active:'Движок работает. Выберите модель и проверьте её коротким запросом.'):(ollama?.message||'Проверяем встроенный движок…'));
      if(data?.engine)paragraph(data.engine.message);
      const storage=data?.model_storage;
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
      paragraph(data?.ollama?.active_verified?'Нейросеть проверена реальным ответом и готова.':'Нейросеть ещё не проверена. Вернитесь к этапу «Нейросеть» или подготовьте её позже через помощь.');
      paragraph('Распознавание речи — '+resourceStatus('asr')+'. Озвучка — '+resourceStatus('tts')+'.');
      paragraph('Беседы сохраняются локально автоматически. Голосовой ввод доступен после подготовки распознавания.');
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
    clearTimeout(timer);if(!downloadTarget()||document.hidden)return;
    if(loading)return loading;
    loading=(async()=>{
      try{const r=await fetch('/api/downloads',{headers:{'X-LocalMind-Key':$('key').value}});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Загрузки недоступны');
        const target=downloadTarget();
        if(!target)return;
        const jobs=(d.jobs||[]).filter(job=>!target.profile||job.kind==='asr'&&
          (job.profile==='gpu-quality')===(target.profile==='gpu-quality'));
        window.localmindDownloads?.renderInto(target.root,jobs);
        const finished=jobs.filter(job=>job.kind==='asr'&&job.status==='succeeded'&&!reportedAsrJobs.has(job.id));
        if(finished.length&&!activeImport){
          finished.forEach(job=>reportedAsrJobs.add(job.id));
          await load();
        }else if(dialog.open&&step===3&&(['checking','verifying','starting','recovering'].includes(data?.engine?.state)||
            data?.engine?.state==='ready'&&data?.ollama?.state!=='ready'))await load();
      }catch(e){showError(e);}
      finally{loading=null;if(downloadTarget()&&!document.hidden)timer=setTimeout(poll,1500);}
    })();return loading;
  }
  function downloadTarget(){
    if(dialog.open){
      if(step===1)return {root:$('setupAsrJobs'),profile};
      if(step===3)return {root:$('setupModelJobs')};
      if(step===4)return {root:$('setupJobs')};
    }
    if($('settingsDialog').open&&!$('settings-voice').hidden&&!$('downloadsDialog')?.open)
      return {root:voiceSettingsJobs,profile:$('voiceProfile').value||'cpu-fast'};
    return null;
  }
  async function finish(){
    if(saving)return;saving=true;render();error.hidden=true;
    try{
      await pendingProgress.catch(()=>{});
      await api('/preferences',{voice_profile:profile});
      const result=await api('/onboarding',{...progressValues(),completed:true});
      $('voiceProfile').value=profile==='balanced'?'cpu-fast':profile;$('voiceProfile').dispatchEvent(new Event('change'));
      data={...data,...result};dialog.close();window.dispatchEvent(new CustomEvent('localmind-setup-completed',{detail:result}));
    }catch(e){showError(e);}finally{saving=false;render();}
  }
  async function load(first=false){
    error.hidden=true;
    try{
      data=await api('');const prefs=data.preferences||{};
      if(first)window.dispatchEvent(new CustomEvent('localmind-preferences',{detail:prefs}));
      if(!initialized){
        const onboarding=data.onboarding||{};
        profile=onboarding.profile||prefs.voice_profile||'cpu-fast';
        const found=row=>['ready','unverified'].includes(row.state);
        if(!onboarding.profile&&!prefs.voice_profile&&data.voice?.some(v=>v.kind==='asr'&&v.model==='medium'&&found(v))&&!data.voice?.some(v=>v.kind==='asr'&&v.model==='small'&&found(v)))profile='gpu-quality';
        skipASR=Boolean(onboarding.skip_asr);skipTTS=Boolean(onboarding.skip_tts);
        if(!onboarding.completed&&Number.isInteger(onboarding.step)&&onboarding.step>=0&&onboarding.step<steps.length)step=onboarding.step;
        initialized=true;
      }
      render();
      renderVoiceSettings();
      if(first&&data.onboarding?.completed===false&&!document.querySelector('dialog[open]')){dialog.showModal();poll();}
      if(first&&data.onboarding?.completed)window.dispatchEvent(new CustomEvent('localmind-setup-completed',{detail:data}));
      poll();
    }catch(e){showError(e);if(first&&!document.querySelector('dialog[open]')){render();dialog.showModal();content.append(button('Повторить проверку',()=>load()));}}
  }
  function open(){
    if(data?.onboarding?.completed)step=0;
    if(!dialog.open)dialog.showModal();
    render();
    load();
  }
  for(const id of ['repeatSetup','helpSetup'])$(id)?.addEventListener('click',()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());open();});
  const repair=button('Подготовить голос / восстановить',open);repair.id='repairVoice';$('settings-voice').append(repair);
  const voiceSettings=document.createElement('div');
  const voiceSettingsJobs=document.createElement('div');voiceSettingsJobs.setAttribute('aria-live','polite');
  $('settings-voice').append(voiceSettings,voiceSettingsJobs);
  function renderVoiceSettings(){
    voiceSettings.replaceChildren();
    if(data?.voice?.length)resourceCard('asr',voiceSettings,$('voiceProfile').value||'cpu-fast');
  }
  $('voiceProfile').addEventListener('change',()=>{renderVoiceSettings();poll();});
  let voiceSettingsVisible=false;
  const settingsObserver=new MutationObserver(()=>{
    const visible=$('settingsDialog').open&&!$('settings-voice').hidden;
    if(visible===voiceSettingsVisible)return;
    voiceSettingsVisible=visible;
    if(visible)load();else poll();
  });
  settingsObserver.observe($('settingsDialog'),{attributes:true,attributeFilter:['open']});
  settingsObserver.observe($('settings-voice'),{attributes:true,attributeFilter:['hidden']});
  $('downloadsDialog')?.addEventListener('close',poll);
  window.addEventListener('localmind-downloads-changed',poll);
  dialog.addEventListener('cancel',event=>{event.preventDefault();pauseSetup();});
  dialog.addEventListener('close',()=>{clearTimeout(timer);timer=null;});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else poll();});
  window.localmindSetup={open,refresh:load};load(true);
})();
