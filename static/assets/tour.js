/* A short optional tour anchored to the actual workspace, not screenshots. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const stops=[['form','Чат и микрофон','Напишите сообщение или нажмите микрофон. Расшифровку можно исправить до отправки.'],
    ['historyList','Ваши беседы','Здесь сохраняются отдельные разговоры. Выберите беседу, чтобы продолжить её.'],
    ['downloadsOpen','Модели и загрузки','Голос и распознавание можно готовить параллельно. У каждой задачи свой прогресс, отмена и повтор.'],
    ['settingsOpen','Настройки','Оформление, голос и доступ к компьютеру собраны здесь. Расширенные права включаются только с вашего согласия.']];
  const box=document.createElement('section');box.id='tourPopover';box.className='tour-popover';box.hidden=true;box.setAttribute('role','dialog');box.setAttribute('aria-labelledby','tourTitle');
  const counter=document.createElement('p');counter.className='mini';const title=document.createElement('h2');title.id='tourTitle';const text=document.createElement('p');
  const actions=document.createElement('div');actions.className='setup-actions';
  const skip=document.createElement('button');skip.className='text-button';skip.textContent='Пропустить';
  const next=document.createElement('button');next.className='secondary';
  const error=document.createElement('p');error.setAttribute('role','alert');
  actions.append(skip,next);box.append(counter,title,text,error,actions);document.body.append(box);
  let index=-1,anchor=null,opener=null,writing=false;
  function clear(){anchor?.classList.remove('tour-target');anchor=null;}
  function position(){
    if(box.hidden||!anchor)return;
    const r=anchor.getBoundingClientRect(),width=Math.min(360,innerWidth-24);
    box.style.width=width+'px';box.style.left=Math.max(12,Math.min(r.right+12,innerWidth-width-12))+'px';
    box.style.top=Math.max(12,Math.min(r.top,innerHeight-box.offsetHeight-12))+'px';
  }
  function render(){
    clear();error.textContent='';box.hidden=false;
    if(index<0){counter.textContent='LocalMind · быстрый старт';title.textContent='Осмотримся?';text.textContent='Четыре короткие подсказки покажут основные области приложения.';next.textContent='Начать тур';box.style.width='min(360px,calc(100vw - 24px))';box.style.left='max(12px,calc(50vw - 180px))';box.style.top='max(12px,calc(50vh - 120px))';}
    else{
      const [id,heading,description]=stops[index];anchor=$(id);
      if($('sidebar').contains(anchor)&&window.matchMedia?.('(max-width:760px)').matches&&!$('sidebar').classList.contains('open'))$('sidebarToggle').click();
      anchor?.classList.add('tour-target');anchor?.scrollIntoView?.({block:'nearest'});
      counter.textContent=(index+1)+' / '+stops.length;title.textContent=heading;text.textContent=description;next.textContent=index===stops.length-1?'Завершить тур':'Далее';position();
    }
    next.focus();
  }
  async function finish(completed){
    if(writing)return;writing=true;next.disabled=skip.disabled=true;
    try{
      const r=await fetch('/api/setup/tour',{method:'POST',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},body:JSON.stringify({completed,skipped:!completed})});
      if(!r.ok)throw Error('Не удалось сохранить состояние тура. Повторите.');
      clear();box.hidden=true;window.closeSidebar?.();opener?.focus();
    }catch(e){error.textContent=e.message;}finally{writing=false;next.disabled=skip.disabled=false;}
  }
  function open(offer=false){document.querySelectorAll('dialog[open]').forEach(d=>d.close());opener=document.activeElement;index=offer?-1:0;render();}
  skip.onclick=()=>finish(false);next.onclick=()=>{if(index===stops.length-1)finish(true);else{index++;render();}};
  box.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();finish(false);}if(event.key==='Tab'){event.preventDefault();(document.activeElement===next?skip:next).focus();}});
  for(const id of ['helpTour','repeatTour'])$(id)?.addEventListener('click',()=>open());
  window.addEventListener('localmind-setup-completed',event=>{const state=event.detail;if(!state.tour?.completed&&!state.tour?.skipped)open(true);});
  window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
})();
