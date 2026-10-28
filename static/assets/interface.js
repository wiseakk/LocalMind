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
  const panel=byId('skyPanel'),stage=document.querySelector('.stage');
  let compact=false,graphOpener=byId('graphToggle');
  function syncGraphAccess(){
    compact=stage.clientWidth<=1100;
    const open=panel.classList.contains('graph-focused');
    panel.inert=compact&&!open;
    window.localmindScene?.setVisible(!compact||open);
    for(const id of ['graphNav','graphToggle'])byId(id).setAttribute('aria-expanded',String(!compact||open));
  }
  function setGraph(open,restore=false){
    panel.classList.toggle('graph-focused',open);
    byId('graphNav').classList.toggle('selected',open);
    byId('chatNav').classList.toggle('selected',!open);
    if(open){byId('graphNav').setAttribute('aria-current','location');byId('chatNav').removeAttribute('aria-current');}
    else{byId('graphNav').removeAttribute('aria-current');byId('chatNav').setAttribute('aria-current','page');}
    syncGraphAccess();
    if(open)byId('nodeSelect').focus({preventScroll:true});
    else if(restore)(compact?byId('graphToggle'):graphOpener).focus({preventScroll:true});
    window.localmindScene?.redraw();
  }
  for(const id of ['graphNav','graphToggle'])byId(id).addEventListener('click',()=>{
    graphOpener=byId(id);setGraph(!panel.classList.contains('graph-focused'));closeSidebar();
  });
  byId('closeGraph').addEventListener('click',()=>setGraph(false,true));
  byId('chatNav').addEventListener('click',()=>setGraph(false));
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&!document.querySelector('dialog[open]')&&compact&&panel.classList.contains('graph-focused'))setGraph(false,true);
  });
  if(window.ResizeObserver)new ResizeObserver(syncGraphAccess).observe(stage);
  syncGraphAccess();
  for(const id of ['settingsOpen','appsOpen'])byId(id).addEventListener('click',closeSidebar);
  // Native <dialog> handles focus containment, Escape and focus return. Explicitly
  // restore its opener too, including when the opener lives in the mobile rail.
  for(const [id,opener] of [['settingsDialog','settingsOpen'],['appsDialog','appsOpen']]){
    byId(id).addEventListener('close',()=>{
      if(!document.querySelector('dialog[open]'))(window.matchMedia?.('(max-width:760px)').matches?byId('sidebarToggle'):byId(opener)).focus();
    });
  }
  document.fonts?.ready.then(()=>window.localmindScene?.redraw());
})();
