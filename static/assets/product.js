/* User mode: four destinations, concise settings, and one attachment entry. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  document.documentElement.dataset.expert='false';
  window.localmindScene?.setVisible(false);
  const advanced=$('settings-advanced');
  for(const id of ['modelTelemetry','diagnostics','diagnosticResult','technical','key']){
    const item=$(id);if(!item)continue;
    if(id==='key'){
      const label=document.querySelector('label[for="key"]');if(label){label.classList.add('expert-only');advanced.append(label);}
    }
    advanced.append(item);item.classList.add('expert-only');
  }
  for(const id of ['temperature','reasoning','contextTokens','responseTokens','keepAlive']){
    const label=$(id)?.closest('label');if(label){advanced.append(label);label.classList.add('expert-only');}
  }
  $('expertMode')?.addEventListener('change',event=>{document.documentElement.dataset.expert=String(event.target.checked);});
  const modelDialog=document.createElement('dialog');modelDialog.id='modelsDialog';modelDialog.setAttribute('aria-labelledby','modelsTitle');
  const head=document.createElement('div');head.className='dialog-heading';
  const title=document.createElement('h2');title.id='modelsTitle';title.textContent='Модели';
  const close=document.createElement('button');close.className='secondary';close.textContent='Закрыть';close.onclick=()=>modelDialog.close();head.append(title,close);modelDialog.append(head);
  const panel=$('settings-model');
  while(panel.firstChild)modelDialog.append(panel.firstChild);
  const explain=document.createElement('p');explain.textContent='Активную модель можно сменить после проверки. Загрузка моделей доступна в разделе «Модели».';
  const open=document.createElement('button');open.className='secondary';open.textContent='Выбрать или установить модель';panel.append(explain,open);
  document.body.append(modelDialog);
  const show=()=>{if($('settingsDialog').open)$('settingsDialog').close();modelDialog.showModal();window.localmindModels?.refresh();window.closeSidebar?.();};
  $('modelsOpen').addEventListener('click',show);open.onclick=show;
  // The old model badge listener opens settings; route it to the dedicated page.
  $('model').addEventListener('click',()=>{if($('settingsDialog').open)$('settingsDialog').close();if(!modelDialog.open)show();});
  modelDialog.addEventListener('close',()=>$('modelsOpen').focus());
  const voice=$('tab-voice');voice?.click();
  // Hidden legacy controls keep existing module references stable, never tab stops.
  for(const id of ['imageAttach','voiceMode','graphToggle','skyPanel'])if($(id))$(id).hidden=true;
  document.querySelector('.voice-divider')?.remove();
  document.querySelector('.prototype-note')?.remove();
  // All pausing/queue state changes originate in speech.js.
  window.addEventListener('localmind-playback',event=>{
    for(const id of ['pauseAudio','stopAudio'])if($(id))$(id).hidden=!event.detail.active;
  });
})();
