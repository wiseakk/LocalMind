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
  // One set of model controls: both navigation entries open the same settings
  // section. Moving its children into another dialog left this tab empty in RC2.
  const show=event=>{
    if(!$('settingsDialog').open)$('settingsOpen').click();
    window.localmindSettingsOpener=event?.currentTarget||$('modelsOpen');
    $('tab-model').click();window.localmindModels?.refresh();window.closeSidebar?.();
  };
  $('modelsOpen').addEventListener('click',show);
  $('model').addEventListener('click',show);
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
