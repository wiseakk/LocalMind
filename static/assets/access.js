/* Access policy is changed only by this explicit authenticated settings screen. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id),dialog=$('accessDialog');
  const operations={search:'Поиск',read:'Чтение',open:'Открытие документа',create:'Создание',overwrite:'Перезапись',move:'Перемещение',delete:'Удаление'};
  for(const [value,text] of Object.entries(operations)){
    const label=document.createElement('label');label.className='check';
    const input=document.createElement('input');input.type='checkbox';input.value=value;input.name='accessOperation';
    label.append(input,text);$('accessOperations').append(label);
  }
  let policy=null,draft=null,sequence=0,opener=null,reading=0;
  const mode=()=>document.querySelector('input[name="accessMode"]:checked').value;
  const credentials=()=>({revision:policy?.revision,server_instance:policy?.server_instance});
  async function api(path,body){
    const r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},...(body?{body:JSON.stringify(body)}:{})});
    const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Не удалось выполнить запрос. Обновите экран и повторите.');return data;
  }
  function clearDraft(){sequence++;draft=null;$('accessRulePreview').hidden=true;$('applyAccessRule').disabled=true;}
  function sync(){
    $('fullAccessConsent').hidden=mode()!=='full_user';
    for(const input of document.querySelectorAll('input[name="accessMode"]'))input.closest('label').classList.toggle('selected',input.checked);
    $('accessScopeNote').textContent=mode()==='full_user'?'Ваш профиль и пользовательские папки доступны автоматически. Чтобы исключить папку, добавьте правило запрета: удаления строки недостаточно. Дополнительные области должны принадлежать вам; весь диск не разрешается.':'Разрешение распространяется на дочерние папки. Ссылки и системные области исключены.';
  }
  function showPolicy(data){
    policy=data;clearDraft();
    const selected=document.querySelector('input[name="accessMode"][value="'+(data.mode==='full_user'?'full_user':'restricted')+'"]');selected.checked=true;
    $('approvedRoots').value=(data.roots||[]).map(r=>r.path).join('\n');$('accessConsent').checked=false;
    for(const input of document.querySelectorAll('[name="accessOperation"]'))input.checked=(data.operations||[]).includes(input.value);
    $('accessCurrent').textContent='Сохранённый режим: '+(data.mode==='full_user'?'Полный пользовательский доступ':'Ограниченный доступ')+(data.error?' · '+data.error:'')+(data.audit_warning?' · '+data.audit_warning:'');
    $('accessExcluded').textContent=Array.isArray(data.excluded)?data.excluded.join(' · '):(data.excluded||'Системные области, чужие профили, секреты, ключи и настройки LocalMind исключены.');
    $('accessScopes').textContent=(data.roots||[]).length?'Сохранённые области: '+data.roots.map(r=>r.path+(r.operations?' ('+r.operations.map(op=>operations[op]||op).join(', ')+')':'')).join(' · '):'Выбранных папок нет.';
    $('accessRuleScope').replaceChildren(new Option('Уточнить при необходимости',''));
    for(const root of data.roots||[])$('accessRuleScope').append(new Option(root.path,root.path));
    $('accessRules').replaceChildren();
    for(const rule of data.rules||[]){
      const row=document.createElement('div'),p=document.createElement('p');
      p.textContent=rule.description||rule.interpretation||rule.text||[rule.effect,rule.target||rule.path||rule.app,Array.isArray(rule.operations)?rule.operations.join(', '):rule.operation].filter(Boolean).join(' · ');row.append(p);
      if(rule.id){
        const remove=document.createElement('button');remove.className='text-button';remove.type='button';remove.textContent='Удалить правило';
        const confirm=document.createElement('button');confirm.className='secondary';confirm.type='button';confirm.hidden=true;confirm.textContent='Подтвердить удаление правила';
        remove.onclick=()=>{confirm.hidden=!confirm.hidden;};
        confirm.onclick=async()=>{
          confirm.disabled=true;clearDraft();
          try{const updated=await api('access-policy/remove-rule',{rule_id:rule.id,...credentials()});showPolicy(updated);$('accessStatus').textContent='Правило удалено и политика сохранена.';}
          catch(e){$('accessStatus').textContent=e.message;confirm.disabled=false;}
        };
        row.append(remove,confirm);
      }
      $('accessRules').append(row);
    }
    if(!(data.rules||[]).length)$('accessRules').textContent='Правил пока нет.';
    sync();renderLog(data.access_log||[]);
  }
  function renderLog(rows){
    const log=$('actionJournal');log.replaceChildren();
    rows=[...new Map(rows.map(row=>[JSON.stringify([row.at,row.operation||row.tool,row.target,row.decision,row.policy_revision]),row])).values()];
    for(const row of rows.slice(-200).reverse()){
      const p=document.createElement('p');p.className='access-log-entry';
      p.textContent=[row.at,row.operation||row.tool,row.target,row.decision,row.reason||row.denial_reason,row.rule||row.rule_id,row.revision||row.policy_revision,row.execution_status,row.observed_state].filter(x=>x!==undefined&&x!==null&&x!=='').join(' · ');log.append(p);
    }
    if(!rows.length)log.textContent='Действий пока нет.';
  }
  async function refresh(){
    const current=++reading;$('saveAccess').disabled=true;
    try{const data=await api('access-policy');if(current!==reading)return;showPolicy(data);$('accessStatus').textContent='';}
    catch(e){if(current===reading){policy=null;$('accessStatus').textContent=e.message;}}
    finally{if(current===reading)$('saveAccess').disabled=!policy;}
  }
  function open(event){
    opener=event.currentTarget;if($('settingsDialog').open)$('settingsDialog').close();
    dialog.showModal();window.closeSidebar?.();refresh();
  }
  $('capabilitiesOpen').addEventListener('click',open);$('openAccessSettings').addEventListener('click',open);
  $('accessClose').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{clearDraft();reading++;(window.matchMedia?.('(max-width:760px)').matches?$('sidebarToggle'):(opener?.id==='openAccessSettings'?$('settingsOpen'):opener||$('capabilitiesOpen'))).focus();});
  $('accessForm').addEventListener('input',()=>{clearDraft();sync();});
  $('accessRuleText').addEventListener('input',clearDraft);$('accessRuleScope').addEventListener('change',clearDraft);
  $('key').addEventListener('change',()=>{clearDraft();if(dialog.open)refresh();});
  $('accessForm').addEventListener('submit',async event=>{
    event.preventDefault();if(!policy)return;
    if(mode()==='full_user'&&!$('accessConsent').checked){$('accessStatus').textContent='Подтвердите явный выбор полного пользовательского доступа.';return;}
    clearDraft();$('saveAccess').disabled=true;
    try{
      const data=await api('access-policy',{mode:mode(),roots:$('approvedRoots').value.split('\n').map(x=>x.trim()).filter(Boolean),operations:[...document.querySelectorAll('[name="accessOperation"]:checked')].map(x=>x.value),...credentials()});
      showPolicy(data);$('accessStatus').textContent='Режим и области сохранены. Старые выбранные цели и подтверждения отозваны.';
    }catch(e){$('accessStatus').textContent=e.message;}finally{$('saveAccess').disabled=!policy;}
  });
  $('accessApps').onclick=()=>{dialog.close();window.localmindAppsOpener=$('capabilitiesOpen');$('appsOpen').click();};
  $('previewAccessRule').onclick=async()=>{
    if(!policy){$('accessStatus').textContent='Сначала загрузите сохранённую политику.';return;}
    clearDraft();const request=sequence;$('previewAccessRule').disabled=true;
    try{
      const scope=$('accessRuleScope').value,body={text:$('accessRuleText').value,...credentials(),...(scope?{scope}:{})};
      const data=await api('access-policy/preview',body);if(request!==sequence)return;
      const clarification=Array.isArray(data.clarification)?data.clarification.join(' '):data.clarification;
      $('accessRuleInterpretation').textContent=clarification||data.interpretation||'Уточните формулировку правила.';
      $('accessRulePreview').hidden=false;draft=clarification?null:data.draft_id;$('applyAccessRule').disabled=!draft;
    }catch(e){if(request===sequence){$('accessRuleInterpretation').textContent=e.message;$('accessRulePreview').hidden=false;}}
    finally{$('previewAccessRule').disabled=false;}
  };
  $('cancelAccessRule').onclick=()=>{clearDraft();$('accessStatus').textContent='Черновик отменён. Разрешения не изменились.';};
  $('applyAccessRule').onclick=async()=>{
    if(!draft||!policy)return;const selectedDraft=draft;draft=null;$('applyAccessRule').disabled=true;
    try{const data=await api('access-policy/apply',{draft_id:selectedDraft,...credentials()});showPolicy(data);$('accessRuleText').value='';$('accessStatus').textContent='Правило применено и сохранено.';}
    catch(e){clearDraft();$('accessStatus').textContent=e.message;}
  };
  $('refreshAccessLog').onclick=async()=>{try{const [data,actions]=await Promise.all([api('access-policy'),api('actions')]);renderLog([...(data.access_log||[]),...(actions.actions||[])].sort((a,b)=>String(a.at).localeCompare(String(b.at))));}catch(e){$('actionJournal').textContent=e.message;}};
  sync();
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
