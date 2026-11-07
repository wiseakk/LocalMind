/* One durable queue and renderer for LLM, ASR and TTS. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const activeStates = ['starting','downloading','verifying','cancelling','queued'];
  const retryStates = ['failed','interrupted','cancelled','cancelled_unverified'];
  const names = {starting:'Подготовка',queued:'В очереди',downloading:'Загружается',verifying:'Проверяем модель',
    succeeded:'Установлена',failed:'Ошибка',interrupted:'Прервано перезапуском',cancelled:'Отменено · подтверждено',
    cancelling:'Отмена запрошена',cancelled_unverified:'Поток закрыт · остановка Ollama не подтверждена'};
  const dialog=document.createElement('dialog');dialog.id='downloadsDialog';dialog.setAttribute('aria-labelledby','downloadsTitle');
  const heading=document.createElement('div');heading.className='dialog-heading';
  const title=document.createElement('h2');title.id='downloadsTitle';title.textContent='Загрузки';
  const close=document.createElement('button');close.className='secondary';close.textContent='Закрыть';close.onclick=()=>dialog.close();heading.append(title,close);
  const note=document.createElement('p');note.className='mini';note.textContent='Модели нейросети и голоса. Закрытие этого диалога не прерывает загрузки. Полный выход из приложения останавливает задачи; проверяемые остатки сохраняются для повтора.';
  const list=document.createElement('div');list.id='downloadsList';list.setAttribute('aria-live','polite');
  dialog.append(heading,note,list);document.body.append(dialog);
  const diagnosticButton=document.createElement('button');diagnosticButton.className='secondary expert-only';diagnosticButton.textContent='Диагностика загрузок';
  const diagnostics=document.createElement('pre');diagnostics.className='expert-only';
  diagnosticButton.onclick=async()=>{try{diagnostics.textContent=JSON.stringify((await api('/diagnostics')).diagnostics,null,2);}catch(e){diagnostics.textContent=e.message;}};
  dialog.append(diagnosticButton,diagnostics);
  let timer=null, pending=null, generation=0;
  const visible=()=>dialog.open&&!document.hidden;
  const activeStatus=status=>['queued','starting','downloading','verifying','cancelling'].includes(status);
  function stopPolling(){generation++;clearTimeout(timer);timer=null;}
  async function resumePolling(){
    stopPolling();const current=generation;
    if(pending)await pending;
    if(current===generation&&visible())return refresh();
  }
  async function api(path,body){const r=await fetch('/api/downloads'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(d.detail||'Список недоступен');return d;}
  const size=value=>typeof value==='number'&&Number.isFinite(value)?(value/1048576).toFixed(1)+' МБ':'объём неизвестен';
  function renderInto(root,jobs){
    root.replaceChildren();
    const visible=jobs.filter(job=>!job.dismissed);
    if(!visible.length)root.textContent='Загрузок пока нет. Выберите модель или подготовьте голос.';
    for(const job of visible.slice().reverse()){
      const card=document.createElement('article');card.className='model-card';card.dataset.downloadId=job.id;
      const title=document.createElement('h3');title.textContent=job.display_name||job.model;
      if(job.model==='localmind-offline:1.0'&&!job.display_name)title.textContent='Лёгкая резервная/тестовая модель · Qwen 2.5 0.5B';
      const text=document.createElement('p');text.textContent=(names[job.status]||'Состояние неизвестно')+(job.error?' · '+job.error:'');
      const destination=document.createElement('p');destination.className='mini';destination.textContent='Куда: '+(job.destination||'хранилище Ollama · расположение не подтверждено');
      const progress=document.createElement('progress');progress.setAttribute('aria-label','Подготовлено байтов модели');
      if(job.total>0){progress.max=job.total;progress.value=Math.min(job.completed||0,job.total);}
      if(job.total_source)progress.title=job.total_source;
      const amount=document.createElement('p');amount.className='mini';amount.textContent=size(job.completed||0)+' / '+size(job.total);
      if(job.total>0)amount.textContent+=' · '+Math.floor(100*Math.min(job.completed||0,job.total)/job.total)+'%';
      const recent=job.updated_at&&Date.now()/1000-job.updated_at<5;
      if(job.status==='downloading'&&recent&&job.bytes_per_second>0){
        amount.textContent+=' · '+size(job.bytes_per_second)+'/с';
        if(Number.isFinite(job.eta_seconds)&&job.eta_seconds>=0)amount.textContent+=' · около '+Math.ceil(job.eta_seconds)+' с'+(job.kind==='llm'?' по известным слоям':'');
      }
      card.append(title,text,destination,progress,amount);
      const sources={huggingface:'Hugging Face',yandex:'Яндекс Диск',local:'Локальный импорт'};
      if(sources[job.asr_source]){
        const source=document.createElement('p');source.className='mini';
        source.textContent='Источник: '+sources[job.asr_source];card.append(source);
      }
      const active=activeStates.includes(job.status);
      function action(label,path){
        const button=document.createElement('button');button.className='secondary';button.textContent=label;
        button.onclick=async()=>{button.disabled=true;try{await api('/'+encodeURIComponent(job.id)+'/'+path,{});await resumePolling();window.dispatchEvent(new CustomEvent('localmind-downloads-changed'));}catch(e){text.textContent=e.message;button.disabled=false;}};
        card.append(button);return button;
      }
      if(active)action('Отменить','cancel').disabled=job.status==='cancelling';
      else{
        if(retryStates.includes(job.status)&&job.asr_source!=='local')action('Повторить','retry');
        if(job.status==='failed'&&job.asr_source==='huggingface'&&job.asr_mirror?.fingerprint){
          const alternative=document.createElement('button');alternative.className='secondary';
          alternative.textContent='Скачать с Яндекс Диска'+(job.asr_mirror.bytes?' · '+size(job.asr_mirror.bytes):'');
          alternative.onclick=async()=>{
            alternative.disabled=true;
            try{
              const r=await fetch('/api/setup/voice',{method:'POST',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},
                body:JSON.stringify({kind:'asr',profile:job.profile,source:'yandex',fingerprint:job.asr_mirror.fingerprint})});
              const result=await r.json();
              if(!r.ok)throw Error(result.detail||'Зеркало недоступно');
              await resumePolling();
              window.dispatchEvent(new CustomEvent('localmind-downloads-changed'));
            }catch(e){text.textContent=e.message;alternative.disabled=false;}
          };
          card.append(alternative);
        }
        action('Скрыть запись','dismiss');
      }
      const detail=document.createElement('details');detail.className='expert-only';
      const summary=document.createElement('summary');summary.textContent='Технические сведения';
      const pre=document.createElement('pre');pre.textContent=JSON.stringify({id:job.id,model:job.model,source:job.progress_source,destination_source:job.destination_source,layers:job.layers,diagnostic:job.diagnostic},null,2);
      detail.append(summary,pre);card.append(detail);root.append(card);
    }
    return visible.some(job=>activeStates.includes(job.status));
  }
  async function refresh(){
    if(pending)return pending;
    if(!visible())return;
    clearTimeout(timer);timer=null;
    const current=generation;
    pending=load();
    try{
      const active=await pending;
      if(current===generation&&visible()&&active)timer=setTimeout(refresh,1500);
    }finally{pending=null;}
  }
  async function load(){
    try{return renderInto(list,(await api('')).jobs||[]);}
    catch(e){list.textContent=e.message;return false;}
  }
  function open(){if(!dialog.open)dialog.showModal();resumePolling();window.closeSidebar?.();}
  $('downloadsOpen').onclick=open;
  dialog.addEventListener('close',()=>{stopPolling();$('downloadsOpen').focus();});
  document.addEventListener('visibilitychange',()=>{if(visible())resumePolling();else stopPolling();});
  window.localmindDownloads={refresh,renderInto,open};
})();
