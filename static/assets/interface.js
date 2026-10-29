/* Navigation, accessible native dialogs, and session-only appearance preferences. */
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
      if(e.key==='ArrowRight')n=(index+1)%tabs.length;
      else if(e.key==='ArrowLeft')n=(index+tabs.length-1)%tabs.length;
      else if(e.key==='Home')n=0;else if(e.key==='End')n=tabs.length-1;else return;
      e.preventDefault();select(tabs[n],true);
    });
  });
  byId('manageCapabilities').addEventListener('click',()=>{byId('settingsDialog').close();byId('appsOpen').click();});
  const media=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  function appearance(){
    const reduced=Boolean(media?.matches||byId('reduceMotion').checked),low=byId('lowPerformance').checked;
    document.documentElement.dataset.reducedMotion=String(reduced);document.documentElement.dataset.lowPerformance=String(low);
    window.localmindScene?.configure({reduced,low});
  }
  media?.addEventListener('change',appearance);
  byId('reduceMotion').addEventListener('change',appearance);byId('lowPerformance').addEventListener('change',appearance);appearance();
  const panel=byId('skyPanel');
  let graphOpener=byId('graphToggle'),previousMode='ambient';
  function syncGraphAccess(){
    const open=panel.classList.contains('graph-focused');
    panel.inert=false;
    window.localmindScene?.setVisible(true);
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
  for(const id of ['settingsOpen','appsOpen','historyOpen','filesOpen','devicesOpen'])byId(id).addEventListener('click',closeSidebar);
  // Native <dialog> handles focus containment, Escape and focus return. Explicitly
  // restore its opener too, including when the opener lives in the mobile rail.
  for(const [id,opener] of [['settingsDialog','settingsOpen'],['appsDialog','appsOpen'],['historyDialog','historyOpen'],['filesDialog','filesOpen'],['devicesDialog','devicesOpen']]){
    byId(id).addEventListener('close',()=>{
      if(!document.querySelector('dialog[open]'))(window.matchMedia?.('(max-width:760px)').matches?byId('sidebarToggle'):byId(opener)).focus();
    });
  }
  document.fonts?.ready.then(()=>window.localmindScene?.redraw());
})();
