/* First run and repair use declared resources. No terminal or implicit downloads. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const labels = {ready:'Готово · пробный запуск пройден',dependency_missing:'Компоненты отсутствуют — восстановите установку',
    model_missing:'Модель ещё не загружена',path_invalid:'Ресурсы недоступны по выбранному пути',
    resource_corrupt:'Файлы повреждены — подготовьте повторно',library_incompatible:'Библиотеки несовместимы — восстановите установку',
    gpu_error:'GPU недоступен — используйте профиль CPU',unverified:'Требуется проверка пробным запуском'};
  const dialog=document.createElement('dialog'); dialog.id='setupDialog'; dialog.setAttribute('aria-labelledby','setupTitle');
  const heading=document.createElement('h2');heading.id='setupTitle';heading.textContent='Добро пожаловать в LocalMind';
  const note=document.createElement('p');note.textContent='Подготовим русскую речь и проверим локальную нейросеть. Загрузка требует интернета; затем голос работает локально. Существующая модель сохранится.';
  const content=document.createElement('div');content.setAttribute('aria-live','polite');
  const update=document.createElement('button');update.className='secondary';update.textContent='Проверить снова';
  const later=document.createElement('button');later.className='secondary';later.textContent='Продолжить в приложении';later.onclick=()=>dialog.close();
  dialog.append(heading,note,content,update,later);document.body.append(dialog);
  async function api(path,body){
    const r=await fetch('/api/setup'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},...(body?{body:JSON.stringify(body)}:{})});
    const d=await r.json();if(!r.ok)throw Error(d.detail||'Настройка недоступна');return d;
  }
  async function refresh(first=false){
    try{
      const state=await api('');content.replaceChildren();
      for(const row of state.voice){
        const card=document.createElement('div');card.className='model-card';
        const text=document.createElement('p');text.textContent=(row.kind==='asr'?'Распознавание речи · '+row.model:'Озвучка · Silero xenia')+' — '+(labels[row.state]||row.state);card.append(text);
        if(!['ready','dependency_missing'].includes(row.state)){
          const button=document.createElement('button');button.className='secondary';button.textContent='Подготовить '+(row.kind==='asr'?'распознавание':'озвучку');
          button.onclick=async()=>{button.disabled=true;try{await api('/voice',{kind:row.kind,...(row.profile?{profile:row.profile}:{})});text.textContent='Подготовка началась. Прогресс — в разделе «Загрузки». Потребуется несколько минут.';}catch(e){text.textContent=e.message;}finally{button.disabled=false;}};card.append(button);
        }content.append(card);
      }
      const llm=document.createElement('p');llm.textContent=state.ollama.state==='ready'?(state.ollama.active_installed?'Нейросеть готова: '+state.ollama.active:'Выберите и установите нейросеть в разделе «Модели».'):'Ollama не отвечает. Запустите его или повторите установку LocalMind с компонентом Ollama.';content.append(llm);
      if(state.offline_model){
        const card=document.createElement('div');card.className='model-card';
        const text=document.createElement('p');text.textContent=(state.offline_model.display_name||'Лёгкая резервная/тестовая модель · Qwen 2.5 0.5B')+' · '+state.offline_model.license+'. Для проверки и работы без основной модели. Активный выбор не изменится.';
        const label=document.createElement('label');label.className='check';const accept=document.createElement('input');accept.type='checkbox';label.append(accept,' Я проверил(а) лицензию и разрешаю локальный импорт этой модели');
        const install=document.createElement('button');install.className='secondary';install.textContent='Установить модель из комплекта';
        const diskLabel=document.createElement('label');diskLabel.className='check expert-only';
        const diskAccept=document.createElement('input');diskAccept.type='checkbox';diskLabel.append(diskAccept,' Если диск Ollama неизвестен: разрешаю импорт без проверки места');
        const diskNote=document.createElement('p');diskNote.className='mini';
        const free=state.offline_disk?.free;
        diskNote.textContent=free==null?'Место на диске Ollama неизвестно. Проверьте хранилище в дополнительных настройках.':
          'Свободно '+(free/1073741824).toFixed(2)+' GiB · требуется около '+((state.offline_model.bytes*1.1+1073741824)/1073741824).toFixed(2)+' GiB';
        install.onclick=async()=>{install.disabled=true;try{await api('/offline-model',{accept_license:accept.checked,acknowledge_unknown_disk:diskAccept.checked&&document.documentElement.dataset.expert==='true'});text.textContent='Импорт начат. Следите за прогрессом в «Загрузках», затем выберите модель в «Моделях».';window.localmindDownloads?.open();}catch(e){text.textContent=e.message;}finally{install.disabled=false;}};
        card.append(text,label,diskNote);if(free==null)card.append(diskLabel);card.append(install);content.append(card);
      }
      if(first&&(state.voice.some(v=>v.required!==false&&v.state!=='ready')||state.ollama.state!=='ready'||!state.ollama.active_installed))dialog.showModal();
    }catch(e){content.textContent=e.message;}
  }
  update.onclick=()=>refresh();
  const repair=document.createElement('button');repair.className='secondary';repair.textContent='Подготовить голос / восстановить';repair.id='repairVoice';
  repair.onclick=()=>{refresh();dialog.showModal();};$('settings-voice').append(repair);
  refresh(true);
})();
