/* Only this explicit settings form changes broad access. Model output cannot. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id),panel=$('settings-capabilities');
  const section=document.createElement('section');section.className='side-section';
  const heading=document.createElement('h3');heading.textContent='Доступ к компьютеру';
  const explanation=document.createElement('p');explanation.textContent='Обычный режим: Блокнот, Калькулятор и отдельно разрешённые приложения. Расширенный: обнаруженные безопасные приложения и обычные документы только в выбранных папках. Секреты, системные файлы и произвольные команды запрещены.';
  const label=document.createElement('label'),mode=document.createElement('select');mode.id='desktopAccessMode';
  for(const [value,text] of [['normal','Обычный'],['extended','Расширенный']]){const o=document.createElement('option');o.value=value;o.textContent=text;mode.append(o);}label.append('Режим доступа',mode);
  const rootsLabel=document.createElement('label'),roots=document.createElement('textarea');roots.id='approvedRoots';roots.rows=3;roots.placeholder='Одна папка на строку';rootsLabel.append('Папки для расширенного доступа',roots);
  const consentLabel=document.createElement('label');consentLabel.className='check';const consent=document.createElement('input');consent.type='checkbox';consentLabel.append(consent,' Я владелец компьютера и разрешаю расширенный доступ к указанным папкам');
  const save=document.createElement('button');save.className='secondary';save.textContent='Сохранить доступ';
  const status=document.createElement('p');status.setAttribute('role','status');
  const logButton=document.createElement('button');logButton.className='secondary';logButton.textContent='Журнал действий';
  const log=document.createElement('div');log.id='actionJournal';
  section.append(heading,explanation,label,rootsLabel,consentLabel,save,status,logButton,log);panel.prepend(section);
  let instance='';
  async function api(path,body){const r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(data.detail||'Операция недоступна');return data;}
  function sync(){rootsLabel.hidden=mode.value!=='extended';consentLabel.hidden=mode.value!=='extended';}
  mode.onchange=sync;sync();
  async function refresh(){try{const data=await api('permissions/personal');instance=data.server_instance;mode.value=data.enabled?'extended':'normal';roots.value=(data.roots||[]).map(r=>r.path).join('\n');consent.checked=false;sync();}catch(e){status.textContent=e.message;}}
  save.onclick=async()=>{
    if(mode.value==='extended'&&!consent.checked){status.textContent='Подтвердите согласие владельца перед включением расширенного доступа.';return;}
    save.disabled=true;
    try{await api('permissions/personal',{enabled:mode.value==='extended',roots:roots.value.split('\n').map(x=>x.trim()).filter(Boolean),portable_roots:[],server_instance:instance});status.textContent='Доступ сохранён';consent.checked=false;}catch(e){status.textContent=e.message;}finally{save.disabled=false;}
  };
  logButton.onclick=async()=>{try{const data=await api('actions');log.replaceChildren();for(const row of data.actions.slice().reverse()){const p=document.createElement('p');p.textContent=[row.at,row.tool,row.target,row.decision,row.execution_status,row.observed_state].filter(Boolean).join(' · ');log.append(p);}if(!data.actions.length)log.textContent='Действий пока нет.';}catch(e){log.textContent=e.message;}};
  $('settingsOpen').addEventListener('click',refresh);
  const confirmations=new Set();
  window.addEventListener('localmind-action-result',event=>{
    const value=event.detail,operation=value.pending_operation;
    if(!operation?.confirmation_id||confirmations.has(operation.confirmation_id))return;
    confirmations.add(operation.confirmation_id);
    const dialog=document.createElement('dialog');dialog.setAttribute('aria-label','Подтверждение изменения файла');
    const title=document.createElement('h2');title.textContent='Подтвердите точную операцию';
    const text=document.createElement('p');text.textContent=operation.operation+' · '+operation.path+(operation.destination?' → '+operation.destination:'');
    const content=document.createElement('pre');content.textContent=operation.content||'';
    const note=document.createElement('p');note.textContent='Изменение/удаление может быть необратимым. Проверьте имя и содержимое. Разрешение действует только для этой операции и истекает через две минуты.';
    const result=document.createElement('p');result.setAttribute('role','status');
    for(const [approved,label] of [[true,'Подтвердить операцию'],[false,'Отменить']]){
      const button=document.createElement('button');button.className='secondary';button.textContent=label;
      button.onclick=async()=>{dialog.querySelectorAll('button').forEach(b=>b.disabled=true);try{const data=await api('files/confirm',{conversation_id:value.conversation_id,confirmation_id:operation.confirmation_id,approved,server_instance:value.server_instance});result.textContent=data.status_text||'Результат недоступен';}catch(e){result.textContent=e.message;}const close=document.createElement('button');close.className='secondary';close.textContent='Закрыть';close.onclick=()=>{dialog.close();dialog.remove();};dialog.append(close);};dialog.append(button);
    }
    dialog.prepend(title,text,note,content,result);document.body.append(dialog);dialog.showModal();
  });
})();
