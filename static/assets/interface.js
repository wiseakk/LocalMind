/* Navigation, accessible native dialogs, and persistent appearance preferences. */
(() => {
  'use strict';
  const byId=id=>document.getElementById(id);
  const tabs=[...document.querySelectorAll('[data-settings]')];
  function select(tab,focus=false) {
    for(const item of tabs){const active=item===tab;item.setAttribute('aria-selected',String(active));item.tabIndex=active?0:-1;byId('settings-'+item.dataset.settings).hidden=!active;}
    if(focus)tab.focus();
  }
  tabs.forEach((tab,index)=>{
    tab.addEventListener('click',()=>select(tab));
    tab.addEventListener('keydown',e=>{
      let n=index;
      if(e.key==='ArrowRight'||e.key==='ArrowDown')n=(index+1)%tabs.length;
      else if(e.key==='ArrowLeft'||e.key==='ArrowUp')n=(index+tabs.length-1)%tabs.length;
      else if(e.key==='Home')n=0;else if(e.key==='End')n=tabs.length-1;else return;
      e.preventDefault();select(tabs[n],true);
    });
  });
  byId('manageCapabilities').addEventListener('click',()=>{byId('settingsDialog').close();byId('appsOpen').click();});
  const media=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const theme=byId('theme');
  function readPreference(key){try{return localStorage.getItem(key)}catch(_){return null}}
  function savePreference(key,value){try{localStorage.setItem(key,value)}catch(_){/* Session still works. */}}
  theme.value=document.documentElement.dataset.theme==='light'?'light':'dark';
  function setTheme(){
    const value=theme.value==='light'?'light':'dark';
    document.documentElement.dataset.theme=value;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content',value==='light'?'#f4f4f7':'#18181c');
  }
  theme.addEventListener('change',()=>{setTheme();savePreference('localmind.theme.v1',theme.value);});
  setTheme();
  for(const id of ['reduceMotion','lowPerformance'])byId(id).checked=readPreference('localmind.'+id+'.v1')==='true';
  function appearance(){
    const reduced=Boolean(media?.matches||byId('reduceMotion').checked),low=byId('lowPerformance').checked;
    document.documentElement.dataset.reducedMotion=String(reduced);document.documentElement.dataset.lowPerformance=String(low);
    window.localmindScene?.configure({reduced,low});
  }
  media?.addEventListener('change',appearance);
  for(const id of ['reduceMotion','lowPerformance'])byId(id).addEventListener('change',()=>{savePreference('localmind.'+id+'.v1',String(byId(id).checked));appearance();});
  appearance();
  let applying=false,preferenceWrites=Promise.resolve();
  const changedChoices=new Set();
  const preferenceNames={theme:'theme',reduceMotion:'reduce_motion',lowPerformance:'low_performance',voiceProfile:'voice_profile',ttsVoice:'tts_voice',speak:'speak'};
  async function saveChoice(id){
    if(applying)return;
    const input=byId(id),value=input.type==='checkbox'?input.checked:input.value;
    changedChoices.add(id);
    preferenceWrites=preferenceWrites.catch(()=>{}).then(async()=>{
      try{
        const r=await fetch('/api/setup/preferences',{method:'POST',headers:{'Content-Type':'application/json','X-LocalMind-Key':byId('key').value},body:JSON.stringify({[preferenceNames[id]]:value})});
        if(!r.ok){const d=await r.json();throw Error(typeof d.detail==='string'?d.detail:'Настройку не удалось сохранить');}
      }catch(e){byId('composerState').textContent='Не удалось сохранить настройку: '+e.message;}
    });
    return preferenceWrites;
  }
  for(const id of Object.keys(preferenceNames))byId(id)?.addEventListener('change',()=>saveChoice(id));
  window.addEventListener('localmind-preferences',event=>{
    applying=true;
    try{
      for(const [id,name] of Object.entries(preferenceNames)){
        if(changedChoices.has(id))continue;
        let value=event.detail[name];if(value===undefined)continue;
        if(id==='voiceProfile'&&value==='balanced')value='cpu-fast';
        const input=byId(id);if(input.type==='checkbox')input.checked=value;else input.value=value;
        input.dispatchEvent(new Event('change'));
      }
    }finally{applying=false;}
  });
  const panel=byId('skyPanel');
  let graphOpener=byId('graphToggle'),previousMode='ambient';
  function syncGraphAccess(){
    const open=panel.classList.contains('graph-focused');
    panel.inert=false;
    window.localmindScene?.setVisible(!panel.hidden);
    document.querySelector('.dialogue-column').inert=open;
    for(const id of ['graphNav','graphToggle'])byId(id).setAttribute('aria-expanded',String(open));
  }
  function setGraph(open,restore=false){
    const wasOpen=panel.classList.contains('graph-focused');
    if(open&&!wasOpen){if(byId('constellationMode').value!=='map')previousMode=byId('constellationMode').value;window.localmindScene?.setMode('map');byId('constellationMode').value='map';}
    if(!open&&wasOpen){window.localmindScene?.setMode(previousMode);byId('constellationMode').value=previousMode;}
    panel.classList.toggle('graph-focused',open);
    document.body.classList.toggle('map-open',open);
    byId('graphNav').classList.toggle('selected',open);
    byId('chatNav').classList.toggle('selected',!open);
    if(open){byId('graphNav').setAttribute('aria-current','location');byId('chatNav').removeAttribute('aria-current');}
    else{byId('graphNav').removeAttribute('aria-current');byId('chatNav').setAttribute('aria-current','page');}
    syncGraphAccess();
    if(open)byId('nodeSelect').focus({preventScroll:true});
    else if(restore)(byId('sidebar').inert&&byId('sidebar').contains(graphOpener)?byId('graphToggle'):graphOpener).focus({preventScroll:true});
    window.localmindScene?.redraw();
  }
  for(const id of ['graphNav','graphToggle'])byId(id).addEventListener('click',()=>{
    graphOpener=byId(id);setGraph(!panel.classList.contains('graph-focused'));closeSidebar();
  });
  byId('closeGraph').addEventListener('click',()=>setGraph(false,true));
  byId('chatNav').addEventListener('click',()=>setGraph(false));
  byId('constellationMode').addEventListener('change',()=>{
    if(byId('constellationMode').value==='map')setGraph(true);
    else if(panel.classList.contains('graph-focused')){previousMode=byId('constellationMode').value;setGraph(false,true);}
    else previousMode=byId('constellationMode').value;
  });
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&!document.querySelector('dialog[open]')&&panel.classList.contains('graph-focused')){e.preventDefault();setGraph(false,true);}
  });
  syncGraphAccess();
  for(const id of ['settingsOpen','appsOpen','filesOpen','devicesOpen','helpOpen'])byId(id)?.addEventListener('click',closeSidebar);
  // Native <dialog> handles focus containment, Escape and focus return. Explicitly
  // restore its opener too, including when the opener lives in the mobile rail.
  for(const [id,opener] of [['settingsDialog','settingsOpen'],['appsDialog','appsOpen'],['filesDialog','filesOpen'],['devicesDialog','devicesOpen'],['helpDialog','helpOpen']]){
    byId(id).addEventListener('close',()=>{
      const target=id==='settingsDialog'&&window.localmindSettingsOpener||byId(opener);
      if(id==='settingsDialog')window.localmindSettingsOpener=null;
      if(!document.querySelector('dialog[open]'))(window.matchMedia?.('(max-width:760px)').matches?byId('sidebarToggle'):target).focus();
    });
  }
  byId('helpOpen')?.addEventListener('click',()=>byId('helpDialog').showModal());
  document.fonts?.ready.then(()=>window.localmindScene?.redraw());
})();
