/* One durable queue for LLM, ASR and TTS. User-visible state never invents readiness. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const names={starting:'Подготовка',queued:'В очереди',downloading:'Загружается',verifying:'Проверяем модель',succeeded:'Готово',
    failed:'Ошибка',interrupted:'Прервано перезапуском',cancelled:'Отменено',cancelling:'Отмена…',cancelled_unverified:'Поток закрыт · остановка Ollama не подтверждена'};
  const dialog=document.createElement('dialog');dialog.id='downloadsDialog';dialog.setAttribute('aria-labelledby','downloadsTitle');
  const heading=document.createElement('div');heading.className='dialog-heading';
  const title=document.createElement('h2');title.id='downloadsTitle';title.textContent='Загрузки';
  const close=document.createElement('button');close.className='secondary';close.textContent='Закрыть';close.onclick=()=>dialog.close();heading.append(title,close);
  const note=document.createElement('p');note.className='mini';note.textContent='Модели нейросети и голоса. Установка не меняет активную нейросеть.';
  const list=document.createElement('div');list.id='downloadsList';list.setAttribute('aria-live','polite');
  dialog.append(heading,note,list);document.body.append(dialog);
  const diagnosticButton=document.createElement('button');diagnosticButton.className='secondary expert-only';diagnosticButton.textContent='Диагностика загрузок';
  const diagnostics=document.createElement('pre');diagnostics.className='expert-only';
  diagnosticButton.onclick=async()=>{try{diagnostics.textContent=JSON.stringify((await api('/diagnostics')).diagnostics,null,2);}catch(e){diagnostics.textContent=e.message;}};
  dialog.append(diagnosticButton,diagnostics);
  let timer=null;
  async function api(path,body){const r=await fetch('/api/downloads'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(d.detail||'Список недоступен');return d;}
  const size=value=>typeof value==='number'?(value/1048576).toFixed(1)+' МБ':'объём неизвестен';
  async function refresh(){
    try{
      const data=await api('');list.replaceChildren();
      if(!data.jobs.length)list.textContent='Загрузок пока нет. Выберите модель или подготовьте голос.';
      for(const job of data.jobs.slice().reverse()){
        const card=document.createElement('article');card.className='model-card';
        const title=document.createElement('h3');title.textContent=job.model;
        const text=document.createElement('p');text.textContent=(names[job.status]||'Состояние неизвестно')+(job.error?' · '+job.error:'');card.append(title,text);
        if(job.total>0){const progress=document.createElement('progress');progress.max=job.total;progress.value=job.completed||0;progress.setAttribute('aria-label','Загружено');const amount=document.createElement('p');amount.textContent=size(job.completed)+' / '+size(job.total);card.append(progress,amount);}
        const active=['starting','downloading','verifying','cancelling','queued'].includes(job.status);
        const button=document.createElement('button');button.className='secondary';button.textContent=active?'Отменить':'Повторить';button.disabled=job.status==='cancelling';
        button.onclick=async()=>{button.disabled=true;try{await api('/'+encodeURIComponent(job.id)+(active?'/cancel':'/retry'),{});await refresh();}catch(e){text.textContent=e.message;button.disabled=false;}};card.append(button);
        if(job.diagnostic){const detail=document.createElement('details');detail.className='expert-detail';const summary=document.createElement('summary');summary.textContent='Техническая причина';const pre=document.createElement('pre');pre.textContent=JSON.stringify(job.diagnostic,null,2);detail.append(summary,pre);card.append(detail);}
        list.append(card);
      }
    }catch(e){list.textContent=e.message;}
    clearTimeout(timer);if(dialog.open)timer=setTimeout(refresh,1500);
  }
  $('downloadsOpen').onclick=()=>{dialog.showModal();refresh();window.closeSidebar?.();};
  dialog.addEventListener('close',()=>{clearTimeout(timer);$('downloadsOpen').focus();});
  window.localmindDownloads={refresh};
})();
