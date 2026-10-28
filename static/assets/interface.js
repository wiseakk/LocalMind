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
  byId('graphNav').addEventListener('click',()=>{
    byId('graphNav').classList.add('selected');byId('graphNav').setAttribute('aria-current','location');byId('chatNav').classList.remove('selected');byId('chatNav').removeAttribute('aria-current');
    byId('skyPanel').classList.add('graph-focused');byId('skyPanel').scrollIntoView?.({block:'start',behavior:document.documentElement.dataset.reducedMotion==='true'?'instant':'smooth'});
    byId('nodeSelect').focus({preventScroll:true});closeSidebar();
  });
  byId('chatNav').addEventListener('click',()=>{byId('chatNav').classList.add('selected');byId('chatNav').setAttribute('aria-current','page');byId('graphNav').classList.remove('selected');byId('graphNav').removeAttribute('aria-current');byId('skyPanel').classList.remove('graph-focused');byId('message').scrollIntoView?.({block:'nearest'});});
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
