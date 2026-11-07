/* First-party UI: execution status and generated commentary stay separate. */
'use strict';
const $ = id => document.getElementById(id);
const history = [];
let busy = false, recording = null, recordingStartedAt = 0, recordingTimer = null;
let voiceBusy = false;
let sttProfiles=[],sttDefaultApplied=false;
// RC1's balanced identifier remains valid on the server and in saved settings.
// Both legacy fast profiles now use small; the UI presents one fast mode.
const visibleSTTProfile=id=>id==='balanced'?'cpu-fast':id;
let serverInstance = null;
let conversationId = null;
let inFlight = null;
let pageClosing = false;
let voiceEpoch = 0;
let resetting = false;
let appsRevision = 0;
let transcriptController = null;
// Runtime-only confirmations never survive navigation/restart or become chat text.
const fileConfirmations = new Map();
const headers = () => ({'X-LocalMind-Key': $('key').value});
const jsonHeaders = () => ({...headers(), 'Content-Type':'application/json'});
function state(text) { $('composerState').textContent = text; }
function scrollEnd() { $('conversation').scrollTop = $('conversation').scrollHeight; }
function showError(message) { $('errorText').textContent = message; if (!$('errorDialog').open) $('errorDialog').showModal(); }
async function checked(response) {
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === 'string') message = data.detail;
      else if (Array.isArray(data.detail)) {
        const details = data.detail.slice(0, 5).filter(item => item && typeof item.msg === 'string').map(item => {
          const location = (Array.isArray(item.loc) ? item.loc : []).slice(0, 6)
            .filter(part => typeof part === 'string' || typeof part === 'number').map(part => String(part).slice(0, 60)).join('.');
          return (location ? location + ': ' : '') + item.msg.slice(0, 240);
        });
        if (details.length) message = details.join('; ');
      }
    } catch (_) { /* bounded generic error */ }
    const error=Error(message);error.status=response.status;throw error;
  }
  return response;
}
function bubble(text, who) {
  const el = document.createElement('div'); el.className = 'bubble ' + who;
  if (who === 'assistant') {
    const label = document.createElement('div'); label.className = 'assistant-label';
    const mark=document.createElement('span');window.localmindIcon?.(mark,'constellation');label.append(mark,document.createTextNode('LOCALMIND'));
    const content = document.createElement('div'); content.className = 'rendered-message'; renderLocalMindMessage(content, text);
    el.append(label, content);
  } else el.textContent = text;
  $('thread').append(el); scrollEnd(); return el;
}
function renderSentAttachments(el,attachments){
  if(el.querySelector('.sent-attachments'))return;
  const group=document.createElement('div');group.className='sent-attachments';
  for(const attachment of attachments || []){
    const card=document.createElement('figure');card.className='sent-attachment';
    if(attachment.kind==='image'&&attachment.thumbnail){
      // Canvas keeps img-src 'none': decode our own bounded PNG snapshot without
      // a URL load, remote image request or widening the Markdown image policy.
      const canvas=document.createElement('canvas');canvas.width=192;canvas.height=192;canvas.setAttribute('role','img');canvas.setAttribute('aria-label',attachment.label);card.append(canvas);
      const bytes=Uint8Array.from(atob(attachment.thumbnail.split(',')[1]),c=>c.charCodeAt(0));
      void createImageBitmap(new Blob([bytes],{type:'image/png'})).then(bitmap=>{try{canvas.getContext('2d').drawImage(bitmap,0,0,192,192);canvas.dataset.rendered='true';}finally{bitmap.close();}}).catch(()=>{canvas.remove();});
    }
    const caption=document.createElement('figcaption');caption.textContent=attachment.label;card.append(caption);group.append(card);
  }
  if(group.childNodes.length)el.append(group);
}
function pending(el) {
  const p = document.createElement('div'); p.className = 'pending'; p.setAttribute('role','status');
  for (let i=0;i<3;i++) p.append(document.createElement('i'));
  const label = document.createElement('span'); label.textContent = 'Формулирую ответ…'; p.append(label); el.append(p);
}
function syncActionControls() {
  for(const button of document.querySelectorAll('[data-pc-action]')) {
    const item=fileConfirmations.get(button.dataset.confirmationId);
    const stale=button.dataset.actionOwner!==conversationId || button.dataset.actionInstance!==serverInstance;
    button.disabled=busy || resetting || stale || Boolean(button.dataset.confirmationId&&(!item||item.phase!=='pending'||Date.now()>=item.expiresAt));
  }
}
function renderFileConfirmation(chip, result, value) {
  const data=result.data;
  if(result.action!=='files.prepare_mutation'||result.execution_status!=='confirmation_required'||
     !data?.requires_explicit_confirmation||typeof data.confirmation_id!=='string')return;
  const owner=value.conversation_id||conversationId,instance=value.server_instance||serverInstance;
  const key=data.confirmation_id;
  let item=fileConfirmations.get(key);
  if(!item){
    item={owner,instance,phase:'pending',expiresAt:Date.now()+Math.max(0,Number(data.expires_in_seconds)||0)*1000};
    fileConfirmations.set(key,item);
    if(fileConfirmations.size>128)fileConfirmations.delete(fileConfirmations.keys().next().value);
  }
  const box=document.createElement('section');box.className='file-confirmation';box.setAttribute('aria-label','Подтверждение операции с файлом');
  const title=document.createElement('strong');
  const names={delete:'Удаление',overwrite:'Перезапись',create:'Создание',move:'Перемещение'};
  title.textContent=(names[data.operation]||'Изменение файла')+' требует отдельного подтверждения';
  const target=document.createElement('p');target.className='confirmation-target';target.textContent=data.path+(data.destination?' → '+data.destination:'');
  const note=document.createElement('p');note.className='confirmation-result';note.setAttribute('role','status');
  note.textContent=item.message||`Проверьте точный путь. Подтверждение действует ${data.expires_in_seconds} с. Сообщение в чате не подтверждает операцию.`;
  box.append(title,target);
  if(data.content){const content=document.createElement('pre');content.textContent=data.content;box.append(content);}
  const actions=document.createElement('div');actions.className='confirmation-actions';
  for(const [approved,label] of [[true,data.operation==='delete'?'Подтвердить удаление':'Подтвердить операцию'],[false,'Отменить']]){
    const button=document.createElement('button');button.type='button';button.className=approved?'secondary':'text-button';button.textContent=label;
    button.dataset.pcAction='confirmation';button.dataset.confirmationId=key;
    button.dataset.actionOwner=owner;button.dataset.actionInstance=instance;
    button.addEventListener('click',async()=>{
      if(busy||resetting||item.phase!=='pending')return;
      if(owner!==conversationId||instance!==serverInstance||Date.now()>=item.expiresAt){
        item.phase='expired';item.message='Подтверждение истекло или разговор/сервер изменился. Запросите операцию заново.';
        note.textContent=item.message;syncActionControls();return;
      }
      item.phase='sending';lock(true);note.textContent=approved?'Проверяем и выполняем подтверждённую операцию…':'Отменяем операцию…';
      try{
        // Exactly one explicit request. Never retry an ambiguous mutation response.
        const response=await checked(await fetch('/api/files/confirm',{method:'POST',headers:jsonHeaders(),
          body:JSON.stringify({conversation_id:owner,server_instance:instance,confirmation_id:key,approved})}));
        const outcome=await response.json();item.phase='settled';
        item.message=outcome.status_text||outcome.error||'Результат операции не подтверждён.';
        chip.classList.toggle('error',!outcome.success&&outcome.execution_status!=='cancelled');
      }catch(error){item.phase='unknown';item.message='Результат не подтверждён: '+error.message+'. Проверьте файл перед новым запросом.';}
      finally{note.textContent=item.message;lock(false);state(item.message);}
    });
    actions.append(button);
  }
  box.append(actions,note);chip.append(box);
}
function renderStatus(el, value) {
  window.localmindScene?.toolResults(value.action_results);
  el.querySelectorAll('.action-chip').forEach(x=>x.remove());
  el.querySelectorAll('.file-result-details').forEach(x=>x.remove());
  for (const result of value.action_results || []) {
    const chip = document.createElement('div'); chip.className = 'action-chip' + (result.success ? '' : ' error');
    const states = {process_created:'Запуск начат; ожидаем окно', already_running:result.observed_state==='visible_window'?'Окно приложения уже открыто':'Приложение уже работает в фоне', launch_pending:'Приложение ещё запускается', observed:'Состояние подтверждено', request_accepted:'Команда принята; состояние пока не подтверждено'};
    const resolved=result.resolved_target || result.requested_target || result.target;
    const fileTool=result.action?.startsWith('files.');
    const target=fileTool
      ? result.data?.directory_name || result.data?.filename || (/^(?:[a-z]:[/\\]|\/)/i.test(resolved||'')?resolved:'Файлы')
      : resolved || result.data?.application || (result.action?.startsWith('devices.')?'Устройство':'Действие');
    const observed={on:'включено',off:'выключено',visible_window:'видимое окно',running:'процесс работает',unknown:'неизвестно',directory_entries:'содержимое папки проверено'};
    const actual=result.observed_state&&result.execution_status!=='request_accepted'?' · Наблюдение: '+(observed[result.observed_state] || result.observed_state):'';
    chip.textContent = (result.mode==='DEMO'?'ДЕМО · симуляция · ':'') + target + ' · ' + (result.success ? states[result.execution_status] || result.status_text || 'Проверка завершена' : result.error || result.status_text || 'Действие не выполнено')+actual;
    el.insertBefore(chip, el.querySelector('.rendered-message')); 
    if(result.success&&fileTool&&result.data?.filename){
      const details=document.createElement('details');details.className='file-result-details';
      const summary=document.createElement('summary');summary.textContent='Метаданные выбранного файла'+(result.data.files?.length>1?' и другие совпадения':'');
      const exact=document.createElement('pre');const {files,file_id,...selected}=result.data;exact.textContent=JSON.stringify(selected,null,2);details.append(summary,exact);
      for(const {file_id,...match} of (files || []).slice(1)){const row=document.createElement('pre');row.textContent=JSON.stringify(match,null,2);details.append(row);}
      el.append(details);
    }
    if(result.execution_status==='permission_required') {
      const permission=document.createElement('button');permission.className='text-button';permission.textContent='Проверить разрешения файлов';
      permission.addEventListener('click',()=>{$('appsDialog').showModal();loadFilePermissions()});chip.append(permission);
    }
    renderFileConfirmation(chip,result,value);
    const choices=document.createElement('div');choices.className='window-choices';choices.setAttribute('role','group');choices.setAttribute('aria-label','Выбор конкретного окна');
    for(const window of result.data?.windows || []) {
      const choose=document.createElement('button');choose.type='button';choose.className='window-choice secondary';choose.textContent=`Выбрать: ${window.application} — ${window.title}`;
      choose.setAttribute('aria-pressed','false');choose.dataset.pcAction='window';
      const owner=value.conversation_id||conversationId,instance=value.server_instance||serverInstance;
      choose.dataset.actionOwner=owner;choose.dataset.actionInstance=instance;
      choose.addEventListener('click',async()=>{if(busy||resetting)return;try{
        if(owner!==conversationId||instance!==serverInstance)return;
        lock(true);
        await checked(await fetch('/api/windows/select',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({conversation_id:owner,window_id:window.window_id})}));
        for(const button of choices.querySelectorAll('button'))button.setAttribute('aria-pressed',String(button===choose));
        state('Окно выбрано. Можно сказать «покажи это окно».');
      }catch(e){showError(e.message)}finally{lock(false)}});choices.append(choose);
    }
    if(choices.childNodes.length)chip.append(choices);
  }
  syncActionControls();
  if ((value.action_results || []).length) state('Готовлю ответ…');
  $('trace').textContent = JSON.stringify(value, null, 2); scrollEnd();
}
function lock(value) {
  busy = value; $('send').disabled = value; $('mic').disabled = value || voiceBusy;
  $('attach').disabled=value;$('imageAttach').disabled=value;
  window.localmindScene?.setActivity(value?'generating':'idle');
  if($('interruptReply'))$('interruptReply').disabled=!value;
  document.querySelectorAll('[data-example]').forEach(b=>b.disabled=value);
  syncActionControls();
}
async function sendText(value) {
  if (busy || voiceBusy || recording || resetting) return;
  const text = value.trim(); if (!text && !window.localmindAttachments?.contextIds().length) return;
  if (!serverInstance) { showError('Сначала восстановите подключение к серверу.'); return; }
  if(window.localmindAttachments?.hasPending()){state('Дождитесь подготовки документов или удалите их.');return;}
  const ids=window.localmindAttachments?.contextIds() || [];
  const previous=currentConversation.retryTurn;
  const retry=previous&&previous.request.text===text&&previous.request.server_instance===serverInstance&&JSON.stringify(previous.request.attachment_ids)===JSON.stringify(ids)?previous:null;
  if(retry&&Date.now()-retry.created>120000){state('Срок безопасного повтора истёк. Проверь результат действия вручную; начни новый разговор.');return;}
  lock(true);
  $('message').value=text;
  // Establish the durable ID before a turn is accepted. A dropped first response
  // must not leave an orphaned conversation or cause autosave to create a second.
  try{await ensureConversation();captureConversation();await persistConversation(currentConversation);}
  catch(error){if(!$('message').value)$('message').value=text;lock(false);showError(error.message);return;}
  stopSpeech(); $('welcome').hidden = true; $('draftReview').hidden = true;
  window.localmindScene?.observeConversation(text,history);
  if(!currentConversation.messages.length&&currentConversation.title==='Новый разговор')currentConversation.title=text.slice(0,60)||'Вложения';
  const userMessage=retry?.userMessage || {role:'user',content:text};if(!retry)currentConversation.messages.push(userMessage);
  updateConversationTitle();
  const userBubble=retry?.userBubble || bubble(text, 'me'); $('message').value = '';
  const el=retry?.el || bubble('', 'assistant');
  if(retry){const index=currentConversation.messages.indexOf(retry.errorMessage);if(index>=0)currentConversation.messages.splice(index,1);el.querySelector('.rendered-message').textContent='';}
  pending(el); state('Готовлю ответ…');
  // A retry after transport loss keeps this ID, so the server never repeats the action.
  const request = retry?.request || {request_id: crypto.randomUUID(), server_instance:serverInstance, conversation_id:conversationId, text, history: history.slice(-8), actions_authorized:true,
    attachment_ids:ids,local_retrieval:Boolean($('useLocalSources')?.checked),
    response_length:$('responseLength').value, compose_actions:$('composeActions').checked,
    model:null, reasoning:$('reasoning').value, temperature:Number($('temperature').value),
    context_tokens:Number($('contextTokens').value),response_tokens:Number($('responseTokens').value),keep_alive_seconds:Number($('keepAlive').value)};
  const attachmentSnapshot=window.localmindAttachments?.beginSubmission(request)||[];
  const turn={request_id:request.request_id,server_instance:request.server_instance,cancelled:false,controller:null};inFlight=turn;
  let finalValue = null;
  let deltaText = '', lastSequence = 0;
  let actionSpoken = false;
  const sentAt = performance.now();
  const wallSentAt = Date.now();
  speech.start();
  try {
    for (let attempt=0;attempt<2;attempt++) {
      const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),90000);
      turn.controller=controller;
      try {
        const response = await checked(await fetch('/api/chat/stream', {method:'POST', headers:jsonHeaders(), body:JSON.stringify(request),signal:controller.signal}));
        const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer='';
        function event(line) {
          if (!line.trim()) return;
          const item = JSON.parse(line);
          if (item.type === 'error') throw Error(item.detail || 'Ошибка обработки');
          if (item.type === 'status') {
            if(item.data.conversation_id){conversationId=item.data.conversation_id;window.localmindAttachments?.adoptConversation(conversationId);}
            renderStatus(el, item.data);
            if(!actionSpoken && !item.data.speech_deferred && item.data.action_results?.length && item.data.answer) {
              actionSpoken=true;speech.feed(item.data.speech_text || item.data.answer,true);
            }
          }
          if (item.type === 'delta' && Number.isInteger(item.sequence) && item.sequence > lastSequence && typeof item.text === 'string') {
            if (deltaText.length + item.text.length > 8192) throw Error('Ответ превышает допустимую длину');
            lastSequence = item.sequence; deltaText += item.text;
            el.classList.add('streaming');
            if(!actionSpoken)speech.feed(item.text);
            el.querySelector('.pending')?.remove();
            renderLocalMindMessage(el.querySelector('.rendered-message'), deltaText); state('Отвечаю…'); scrollEnd();
          }
          if (item.type === 'final') { window.localmindModels?.observe(item.data); finalValue = item.data; if(item.data.conversation_id){conversationId=item.data.conversation_id;window.localmindAttachments?.adoptConversation(conversationId);} renderStatus(el, item.data);
            if(window.localmindAttachments?.acknowledge(item.data,request)){userMessage.attachments=attachmentSnapshot;renderSentAttachments(userBubble,attachmentSnapshot);}
          }
        }
        while (true) {
          const {value:chunk,done} = await reader.read();
          buffer += decoder.decode(chunk || new Uint8Array(), {stream:!done});
          if (buffer.length>131072) throw Error('Повреждённый или слишком большой поток ответа');
          let newline; while ((newline = buffer.indexOf('\n')) >= 0) { event(buffer.slice(0,newline)); buffer=buffer.slice(newline+1); }
          if (done) { if (buffer) event(buffer); break; }
        }
        if (!finalValue) throw Error('Соединение прервано. Результат запрашивается с тем же ID.');
        break;
      } catch (error) {
        // Never retry after sleep/stalled transport could outlive server deduplication.
        if (turn.cancelled || attempt || Math.max(performance.now()-sentAt,Date.now()-wallSentAt) > 120000) throw error;
        state('Восстанавливаем ответ без повторного действия…');
      } finally {clearTimeout(timeout);controller.abort();}
    }
    el.querySelector('.pending')?.remove(); renderLocalMindMessage(el.querySelector('.rendered-message'), finalValue.display_text ?? finalValue.answer);
    if(finalValue.context_budget?.truncated){const notice=document.createElement('small');notice.className='meta';notice.textContent='Контекст сокращён: часть старой истории или источников не включена.';el.append(notice);}
    for(const source of finalValue.sources || []) {
      const provenance=document.createElement('small');provenance.className='meta';provenance.textContent=`Локальная справка: ${source.filename}, строки ${source.line_start}–${source.line_end}`;el.append(provenance);
    }
    const diagnostics = document.createElement('details'); diagnostics.className='message-diagnostics';
    const summary = document.createElement('summary'); summary.textContent='Диагностика ответа';
    const meta = document.createElement('pre'); meta.className='meta';
    meta.textContent=`${finalValue.engine} · действие ${finalValue.action_ms || 0} мс · LLM ${finalValue.llm_ms || 0} мс`;
    const raw = document.createElement('pre'); raw.textContent=JSON.stringify(finalValue,null,2);
    diagnostics.append(summary,meta,raw); el.append(diagnostics); history.push({role:'user',content:text},{role:'assistant',content:finalValue.answer});
    if (history.length > 16) history.splice(0,history.length-16);
    currentConversation.messages.push({role:'assistant',content:finalValue.answer});
    currentConversation.retryTurn=null;
    currentConversation.serverId=conversationId;currentConversation.instance=serverInstance;
    currentConversation.updated_at=new Date().toISOString();
    currentConversation.results=(finalValue.action_results || []).slice(-8);
    currentConversation.sources=(finalValue.sources || []).slice(-5);
    window.localmindScene?.observeSources(finalValue.sources || []);
    state('Готов к разговору');
    if(!actionSpoken) speech.feed(deltaText ? '' : finalValue.speech_text ?? finalValue.answer,true);
    await refresh();
  } catch (error) {
    stopSpeech();
    el.querySelector('.pending')?.remove();
    el.querySelector('.rendered-message').textContent=turn.cancelled?'Ответ прерван.':'Ответ недоступен: '+error.message;
    state(turn.cancelled?'Ответ прерван; выполненное действие не отменяется.':'Ошибка получения ответа. Проверьте состояние действия перед новой отправкой.');
    const errorMessage={role:'assistant',content:el.querySelector('.rendered-message').textContent};currentConversation.messages.push(errorMessage);
    currentConversation.retryTurn=turn.cancelled?null:{request,userMessage,userBubble,el,errorMessage,created:retry?.created || wallSentAt};
    if(!$('message').value)$('message').value=text;
    await refresh();
  } finally {
    window.localmindAttachments?.releaseSubmission(request.request_id);el.classList.remove('streaming');inFlight=null;
    await saveConversation().catch(()=>{});lock(false);renderHistory();$('message').focus();scrollEnd();
  }
}
async function refresh() {
  try {
    const info = await (await checked(await fetch('/api/info', {headers:headers()}))).json();
    const restarted=serverInstance&&serverInstance!==info.server_instance;
    serverInstance=info.server_instance;
    syncActionControls();
    if(restarted){
      // IDs and messages survive a restart. Runtime grants and retry envelopes do
      // not: the next request receives the new server instance explicitly.
      currentConversation.retryTurn=null;currentConversation.results=[];currentConversation.sources=[];
      for(const item of conversations){item.instance=null;item.view=null;}
      state('Сервер перезапущен. История сохранена; разрешения проверяются заново.');
    }
    if(!historyLoaded)await loadConversations();
    window.localmindScene?.observeInfo(info);
    $('status').textContent='Сервер подключён'; $('connectionDot').classList.add('online'); $('model').textContent=window.localmindModels?.lastModel || 'Модель ещё не использовалась';
    $('mode').textContent=info.demo?'DEMO':'REAL · HA';
    $('mode').classList.toggle('real',!info.demo);
    $('lampSuggestionCaption').textContent=info.demo?'Настольная лампа · DEMO / симуляция':'Настольная лампа · реальное устройство HA';
    $('demoNote').textContent=info.demo?'Симуляция — физические устройства не переключаются.':'REAL — запросы к разрешённым устройствам Home Assistant.';
    $('devices').replaceChildren();
    for (const d of info.devices || []) {
      const row=document.createElement('div'); row.className='device';
      const name=document.createElement('span');name.textContent=d.name;
      const status=document.createElement('span'); status.className='device-state';
      status.textContent=info.demo?(d.state?'● Включена':'○ Выключена'):'HA · состояние не опрошено'; row.append(name,status); $('devices').append(row);
    }
    renderDevices(info);
    const voice=info.voice || {};
    sttProfiles=voice.profiles||[];
    if(!sttDefaultApplied){
      try{const saved=localStorage.getItem('localmind.sttProfile.v1');if(sttProfiles.some(p=>p.id===saved))$('voiceProfile').value=visibleSTTProfile(saved);else if(voice.default_profile)$('voiceProfile').value=visibleSTTProfile(voice.default_profile);}catch(_){if(voice.default_profile)$('voiceProfile').value=visibleSTTProfile(voice.default_profile);}
      sttDefaultApplied=true;
    }
    for(const option of $('voiceProfile').options){
      const profile=voice.profiles?.find(p=>p.id===option.value);
      option.disabled=false;
      option.dataset.baseLabel??=option.textContent;
      option.textContent=option.dataset.baseLabel+(profile?.ready===true?'':' · требуется подготовка');
    }
    showSTTProfile();
    const selectedVoice=voice.voices?.find(v=>v.id===($('ttsVoice').value || 'silero-v5_6-ru'));
    $('voiceStatus').textContent=selectedVoice?.ready ? 'Ресурсы выбранного голоса найдены. Синтез выполняется локально; облачная замена отключена.' : 'Выбранный голос пока недоступен. Нажмите «Подготовить голос / восстановить». Основной голос — Silero xenia. Облачная озвучка не используется.';
    if (voice.setup) $('voiceStatus').textContent += '\n'+voice.setup;
  } catch (error) { $('status').textContent=error.message; $('connectionDot').classList.remove('online'); }
}
async function loadModels() { await window.localmindModels?.refresh(); }
const speech = new LocalMindSpeech({
  request:async(text,voice,signal,generation_id)=>{
    // A cancelled native worker needs a short bounded teardown. Retrying speech
    // has no PC side effect; keep the generation token so retirement still wins.
    for(let attempt=0;attempt<12;attempt++){
      if(signal.aborted)throw Error('Озвучка прервана');
      const response=await fetch('/api/tts',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({text,voice,generation_id}),signal});
      if(response.status!==429 || attempt===11)return checked(response);
      await new Promise(resolve=>setTimeout(resolve,200));
    }
  },
  cancelRequest:async(generation_id)=>fetch('/api/tts/cancel',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({generation_id})}),
  enabled:()=>$('speak').checked,
  voice:()=>$('ttsVoice')?.value || 'silero-v5_6-ru',
  report:message=>{state(message);$('voiceStatus').textContent=message;}
});
function stopSpeech() {speech.cancel();$('pauseAudio').setAttribute('aria-pressed','false');window.localmindIcon?.($('pauseAudio'),'pause');}
function playSpeech(text) {speech.start();speech.feed(text,true);}
async function loadApps(refreshCatalog=false) {
  const revision=++appsRevision;
  $('appsList').textContent='Проверяем установленные приложения…'; $('rescan').disabled=true;
  try {
    const url=refreshCatalog?'/api/apps/refresh':'/api/apps';
    const data=await (await checked(await fetch(url,{method:refreshCatalog?'POST':'GET',headers:headers()}))).json();
    if(revision!==appsRevision)return;
    const apps=data.apps; $('appsCount').textContent=apps.length; $('appsList').replaceChildren();
    window.localmindScene?.observeApps(apps);
    if (!apps.length) $('appsList').textContent='Безопасные приложения не обнаружены. Доступны проверенные встроенные приложения.';
    for(const app of apps) {
      const row=document.createElement('div');row.className='app-entry';
      const title=document.createElement('strong');title.textContent=app.name;
      const path=document.createElement('small');path.textContent=app.target;
      const permissions=document.createElement('div');permissions.className='app-permissions';
      for(const [operation,text] of [['launch','Запуск'],['focus','Фокус окна'],['close','Безопасное закрытие']]){
        const label=document.createElement('label');label.className='check';
        const check=document.createElement('input');check.type='checkbox';check.checked=Boolean(app.permissions?.[operation]??(operation==='launch'&&app.allowed));
        check.setAttribute('aria-label',text+': '+app.name);label.append(check,text);permissions.append(label);
        check.addEventListener('change',async()=>{
            check.disabled=true;const grantRevision=++appsRevision,requested=check.checked;
          try{
            const data=await(await checked(await fetch('/api/apps/permission',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({app_id:app.id,allowed:requested,fingerprint:app.fingerprint,operation})}))).json();
            const effective=data.apps?.find(row=>row.id===app.id);
            if(effective){app.permissions=effective.permissions;app.allowed=effective.allowed;check.checked=Boolean(effective.permissions?.[operation]);if(requested&&!check.checked)showError('Действие остаётся запрещено контроллером. Проверьте правила и защищённые области в «Возможностях LocalMind».');}
            else{app.permissions={...app.permissions,[operation]:check.checked};if(operation==='launch')app.allowed=check.checked;}
            if(grantRevision===appsRevision)window.localmindScene?.observeApps(apps);else await loadApps();
          }catch(error){check.checked=!check.checked;showError(error.message)}finally{check.disabled=false;$('rescan').disabled=false;}
        });
      }
      const choose=document.createElement('button');choose.className='text-button';choose.textContent='Подставить точное название';
      choose.addEventListener('click',()=>{$('message').value='Открой '+app.id;$('appsDialog').close();$('message').focus()});
      row.append(title,path,permissions,choose);$('appsList').append(row);
    }
  } catch(error) {if(revision===appsRevision)$('appsList').textContent=error.message;} finally{if(revision===appsRevision)$('rescan').disabled=false;}
}
function stageTranscript(r) {
  if(r.final===false)return; // Provisional text never replaces an editable final draft.
  $('message').value=r.text; $('rawTranscript').textContent='Исходная расшифровка: '+r.text;
  const warnings={quiet_input:'Тихий вход: приблизь микрофон или проверь уровень.',clipping:'Перегрузка микрофона: уменьши уровень входа.'};
  const feedback=(r.levels?.warnings || []).map(w=>warnings[w]).filter(Boolean);
  if(r.quality?.review_recommended)feedback.push('Распознавание требует особенно внимательной проверки.');
  if(r.quality)feedback.push('Процент точности не измерен. Это финальная расшифровка записи, не прямой эфир.');
  if(feedback.length)$('rawTranscript').textContent+='\n'+feedback.join(' ');
  $('draftReview').hidden=false; state('Текст НЕ отправлен. Проверьте и исправьте расшифровку.'); $('message').focus();
}
function showSTTProfile(){
  const profile=sttProfiles.find(p=>p.id===$('voiceProfile').value);
  if($('sttProfileDescription'))$('sttProfileDescription').textContent=profile?.description||'';
  const measured=profile?.measurement;
  const mib=value=>Number.isFinite(value)?(value/1048576).toFixed(0)+' МиБ':'неизвестно';
  if($('sttProfileMeasurement'))$('sttProfileMeasurement').textContent=measured?`Последний замер worker (${measured.device}/${measured.compute_type}): RAM ${mib(measured.resources?.rss_bytes)}, VRAM ${mib(measured.resources?.vram_bytes)}, inference ${measured.inference_ms??'—'} мс. ${measured.resources?.gpu||measured.resources?.cpu||'Оборудование неизвестно'}. Замер после запроса, не пик; включает весь worker.`:'RAM, VRAM и задержка: ещё не измерены на этом компьютере.';
}
$('voiceProfile').addEventListener('change',()=>{try{localStorage.setItem('localmind.sttProfile.v1',$('voiceProfile').value);}catch(_){}showSTTProfile();});
$('mic').addEventListener('click',async()=>{
  if (recording) {recording.stop(); return;}
  if (busy || voiceBusy || resetting) return;
  if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder){showError('Для микрофона нужен localhost и браузер с MediaRecorder. Текстовый ввод доступен.');return}
  stopSpeech();window.LocalMindAudio?.unlock();let stream,releaseAmplitude=()=>{};
  const captureEpoch=voiceEpoch;
  voiceBusy=true; $('mic').disabled=true; $('send').disabled=true;
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:true});
    if(pageClosing||captureEpoch!==voiceEpoch){stream.getTracks().forEach(t=>t.stop());voiceBusy=false;$('mic').disabled=busy||resetting;$('send').disabled=busy||resetting;return}
    const type=['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg'].find(t=>MediaRecorder.isTypeSupported(t));
    if(!type)throw Error('Нет поддерживаемого аудиоформата');
    const mr=new MediaRecorder(stream,{mimeType:type}),chunks=[];let bytes=0;
    const settings=stream.getAudioTracks?.()[0]?.getSettings?.()||{};
    // Only technical capture settings: no device IDs, labels or retained audio.
    const capture={container_codec:mr.mimeType||type,requested_constraints:'audio:true (browser defaults)',...Object.fromEntries(['sampleRate','channelCount','echoCancellation','noiseSuppression','autoGainControl','latency'].filter(k=>settings[k]!==undefined).map(k=>[k,settings[k]]))};
    recording=mr;recordingStartedAt=performance.now();$('mic').classList.add('active');window.localmindIcon?.($('mic'),'stop');$('mic').setAttribute('aria-pressed','true');$('mic').setAttribute('aria-label','Остановить запись');$('send').disabled=true;
    voiceBusy=false;$('mic').disabled=false;
    state('Слушаю… Нажмите ■, чтобы закончить. Максимум 30 секунд.');
    mr.ondataavailable=e=>{if(e.data.size){bytes+=e.data.size;chunks.push(e.data);if(bytes>8*1024*1024 && mr.state==='recording')mr.stop()}};
    mr.onstop=async()=>{
      clearTimeout(recordingTimer);recording=null;releaseAmplitude();stream.getTracks().forEach(t=>t.stop());$('mic').classList.remove('active');window.localmindIcon?.($('mic'),'mic');$('mic').setAttribute('aria-pressed','false');$('mic').setAttribute('aria-label','Записать голос');
      voiceBusy=true;$('mic').disabled=true;
      const controller=new AbortController();transcriptController=controller;
      const timeout=setTimeout(()=>controller.abort(),90000);
      try {
        if(pageClosing||captureEpoch!==voiceEpoch)return;
        if(bytes>8*1024*1024)throw Error('Аудио превышает 8 МБ');
        if(bytes<1024 || performance.now()-recordingStartedAt<400)throw Error('Запись слишком короткая. Проверьте микрофон.');
        const ext=type.includes('mp4')?'mp4':type.includes('ogg')?'ogg':'webm';
        const form=new FormData();form.append('audio',new Blob(chunks,{type}),`voice.${ext}`);form.append('profile',$('voiceProfile').value);
        state('Обрабатываю русскую речь на компьютере…');window.localmindScene?.setActivity('transcribing');
        const r=await(await checked(await fetch('/api/transcribe',{method:'POST',headers:headers(),body:form,signal:controller.signal}))).json();
        if(pageClosing||captureEpoch!==voiceEpoch)return;
        stageTranscript(r); $('trace').textContent=JSON.stringify({stt:r,capture},null,2);
        if(r.resources){const profile=sttProfiles.find(p=>p.id===r.profile);if(profile)profile.measurement=r;showSTTProfile();}
      }catch(error){if(!pageClosing&&captureEpoch===voiceEpoch){state('Распознавание недоступно. Используйте текстовый ввод.');showError(error.message)}}
      finally{clearTimeout(timeout);if(transcriptController===controller)transcriptController=null;voiceBusy=false;$('mic').disabled=busy||resetting;$('send').disabled=busy||resetting;window.localmindScene?.setActivity(busy?'generating':'idle');}
    };
    mr.onerror=()=>{if(mr.state!=='inactive')mr.stop();state('Ошибка записи микрофона')};
    mr.start(500);window.localmindScene?.setActivity('listening');releaseAmplitude=window.LocalMindAudio?.start(stream,'listening')||(()=>{});recordingTimer=setTimeout(()=>{if(mr.state==='recording')mr.stop()},30000);
  } catch(error) {
    releaseAmplitude();window.localmindScene?.setActivity('idle');stream?.getTracks().forEach(t=>t.stop());clearTimeout(recordingTimer);recording=null;voiceBusy=false;
    $('mic').classList.remove('active');window.localmindIcon?.($('mic'),'mic');$('mic').setAttribute('aria-pressed','false');$('mic').setAttribute('aria-label','Записать голос');
    $('mic').disabled=busy||resetting;$('send').disabled=busy||resetting;if(!pageClosing&&captureEpoch===voiceEpoch)showError('Микрофон: '+error.message);
  }
});
$('form').addEventListener('submit',e=>{e.preventDefault();sendText($('message').value)});
$('message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendText($('message').value)}});
for(const b of document.querySelectorAll('[data-example]'))b.addEventListener('click',()=>sendText(b.dataset.example));
for(const b of document.querySelectorAll('[data-close]'))b.addEventListener('click',()=>$(b.dataset.close).close());
$('settingsOpen').addEventListener('click',()=>{$('settingsDialog').showModal();refresh();loadModels();loadLocalSources()});
$('appsOpen').addEventListener('click',()=>{$('appsDialog').showModal();loadApps();loadFilePermissions()});
$('rescan').addEventListener('click',()=>loadApps(true));
$('key').addEventListener('change',()=>{refresh();loadApps();});
$('speak').addEventListener('change',()=>{if(!$('speak').checked)stopSpeech()});
// Persist only an explicit, declared voice choice; never infer from installation.
const VOICE_KEY='localmind.ttsVoice.v1';
try {
  const savedVoice=localStorage.getItem(VOICE_KEY);
  if(Array.from($('ttsVoice').options).some(option=>option.value===savedVoice))$('ttsVoice').value=savedVoice;
} catch(_) { /* Voice selection still works when storage is disabled. */ }
$('ttsVoice').addEventListener('change',()=>{
  stopSpeech();
  try{localStorage.setItem(VOICE_KEY,$('ttsVoice').value);}catch(_){ /* optional preference */ }
  refresh();
});
$('stopAudio').addEventListener('click',()=>{stopSpeech();state('Озвучка остановлена')});
$('pauseAudio').addEventListener('click',()=>{const paused=speech.pause();$('pauseAudio').setAttribute('aria-pressed',String(Boolean(paused)));window.localmindIcon?.($('pauseAudio'),paused?'play':'pause');window.localmindScene?.redraw();});
$('discardDraft').addEventListener('click',()=>{$('draftReview').hidden=true;$('message').value='';state('Готов к разговору')});
function closeSidebar(){$('sidebar').classList.remove('open');$('sidebarToggle').setAttribute('aria-expanded','false');updateSidebarAccess()}
const mobileLayout=window.matchMedia?.('(max-width:760px)');
function updateSidebarAccess(){$('sidebar').inert=Boolean(mobileLayout?.matches&&!$('sidebar').classList.contains('open'))}
$('sidebarToggle').addEventListener('click',()=>{const open=$('sidebar').classList.toggle('open');$('sidebarToggle').setAttribute('aria-expanded',String(open));updateSidebarAccess()});
mobileLayout?.addEventListener('change',updateSidebarAccess);updateSidebarAccess();
$('chatNav').addEventListener('click',()=>{closeSidebar();$('message').focus()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]')){closeSidebar();if(mobileLayout?.matches)$('sidebarToggle').focus()}});
$('diagnostics').addEventListener('click',async()=>{$('diagnostics').disabled=true;try{$('diagnosticResult').textContent=JSON.stringify(await(await checked(await fetch('/api/diagnostics',{headers:headers()}))).json(),null,2)}catch(e){$('diagnosticResult').textContent=e.message}finally{$('diagnostics').disabled=false}});
window.addEventListener('pagehide',()=>{pageClosing=true;voiceEpoch++;transcriptController?.abort();stopSpeech();if(recording?.state==='recording')recording.stop()});
window.addEventListener('pageshow',()=>{pageClosing=false;if(!busy&&!voiceBusy&&!recording){$('send').disabled=false;$('mic').disabled=false}});
refresh();

// Permissions show server-resolved paths; no model/user path field is accepted.
const fileControls=document.createElement('section');
fileControls.id='filePermissions';fileControls.className='notice';
$('appsDialog').append(fileControls);
async function loadFilePermissions() {
  fileControls.textContent='Проверяем доступ к Загрузкам…';
  try {
    const suffix=conversationId?'?conversation_id='+encodeURIComponent(conversationId):'';
    const data=await(await checked(await fetch('/api/files'+suffix,{headers:headers()}))).json();
    fileControls.replaceChildren();
    const label=document.createElement('label');label.className='check';
    const allow=document.createElement('input');allow.type='checkbox';allow.checked=data.folder.allowed;
    const title=document.createElement('span');title.textContent='Разрешить чтение PDF в Загрузках (без вложенных папок)';label.append(allow,title);
    const path=document.createElement('p');path.textContent=data.folder.path;
    allow.addEventListener('change',async()=>{allow.disabled=true;try{
      await checked(await fetch('/api/files/folder-permission',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({allowed:allow.checked,fingerprint:data.folder.fingerprint})}));
      await loadFilePermissions();
    }catch(e){showError(e.message);allow.checked=!allow.checked}finally{allow.disabled=false}});
    fileControls.append(label,path);
    if(data.selected) {
      const selected=data.selected;
      const detail=document.createElement('p');detail.textContent=`${selected.filename} · изменён ${selected.modified_at} · ${selected.path}`;
      const openLabel=document.createElement('label');openLabel.className='check';
      const open=document.createElement('input');open.type='checkbox';open.checked=selected.open_allowed;
      const caption=document.createElement('span');caption.textContent='Разрешить Windows открыть именно этот PDF';openLabel.append(open,caption);
      open.addEventListener('change',async()=>{open.disabled=true;try{
        await checked(await fetch('/api/files/open-permission',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({conversation_id:conversationId,file_id:selected.file_id,allowed:open.checked})}));
      }catch(e){open.checked=!open.checked;showError(e.message)}finally{open.disabled=false}});
      fileControls.append(detail,openLabel);
    }
  }catch(e){fileControls.textContent=e.message;}
}
const resetConversation=document.createElement('button');resetConversation.className='secondary';
resetConversation.id='resetConversation';resetConversation.textContent='Начать новый разговор';
resetConversation.addEventListener('click',()=>newConversation(true));
$('sessionControls').append(resetConversation);
const retrievalLabel=document.createElement('label');retrievalLabel.className='check';
const retrievalCheck=document.createElement('input');retrievalCheck.type='checkbox';retrievalCheck.id='useLocalSources';
const retrievalText=document.createElement('span');retrievalText.textContent='Использовать разрешённые локальные справочники';retrievalLabel.append(retrievalCheck,retrievalText);
const sourcesControl=document.createElement('section');$('sourceSettings').append(retrievalLabel,sourcesControl);
async function loadLocalSources() {
  try {
    const data=await(await checked(await fetch('/api/retrieval/sources',{headers:headers()}))).json();sourcesControl.replaceChildren();
    window.localmindScene?.setSources(data.sources);
    if(!data.sources.length)sourcesControl.textContent='Добавьте свои UTF-8 .txt/.md источники в config/retrieval_sources.json. См. docs/NEXT_EVALUATION.md.';
    for(const source of data.sources) {
      const label=document.createElement('label');label.className='check';
      const check=document.createElement('input');check.type='checkbox';check.checked=source.allowed;check.disabled=!source.available;
      const text=document.createElement('span');text.textContent=source.label+' · '+(source.path || 'недоступен');label.append(check,text);sourcesControl.append(label);
      check.addEventListener('change',async()=>{check.disabled=true;try{
        await checked(await fetch('/api/retrieval/permission',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({source_id:source.id,allowed:check.checked,fingerprint:source.fingerprint})}));
        source.allowed=check.checked;window.localmindScene?.setSources(data.sources);
      }catch(e){check.checked=!check.checked;showError(e.message)}finally{check.disabled=false}});
    }
  }catch(e){sourcesControl.textContent=e.message;}
}
const interruptReply=document.createElement('button');interruptReply.id='interruptReply';interruptReply.className='text-button';
interruptReply.type='button';
interruptReply.textContent='Прервать ответ';interruptReply.disabled=true;
interruptReply.addEventListener('click',async()=>{
  const turn=inFlight;if(!turn)return;
  turn.cancelled=true;turn.controller?.abort();stopSpeech();
  try{await checked(await fetch('/api/chat/cancel',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({request_id:turn.request_id,server_instance:turn.server_instance})}));}
  catch(e){state('Текст и звук остановлены; серверный результат проверь в диагностике.');}
});
$('stopAudio').before(interruptReply);
// Read-only discovery never grants a capability or launches an application.
loadApps();

// Server-owned history is durable. Reading it never replays actions or grants.
const HISTORY_KEY='localmind.blacksite.history.v1';
const conversations=[];
function emptyConversation(){return {id:crypto.randomUUID(),title:'Новый разговор',draft:'',messages:[],serverId:null,instance:null,view:null,transcript:'',context:{local_retrieval:false,attachment_ids:[]}};}
let currentConversation=emptyConversation(),renaming=null,sessionCreation=null;
let historyLoaded=false,historyLoading=null,draftTimer=null;
conversations.push(currentConversation);
function historyStatus(text){if($('historyStorage'))$('historyStorage').textContent=text;}
function updateConversationTitle(){
  $('conversationTitle').textContent=currentConversation.title;
  $('message').readOnly=false;
  $('send').disabled=busy||resetting||voiceBusy||Boolean(recording);
  $('mic').disabled=busy||resetting||voiceBusy;
  $('attach').disabled=busy||resetting;
  $('imageAttach').disabled=busy||resetting;
}
async function conversationAPI(path='',method='GET',body,options={}){
  const response=await checked(await fetch('/api/conversations'+path,{method,headers:jsonHeaders(),...(body===undefined?{}:{body:JSON.stringify(body)}),...options}));
  return response.json();
}
function captureConversation(){
  currentConversation.draft=$('message').value;
  currentConversation.serverId=conversationId;
  currentConversation.instance=serverInstance;
  currentConversation.transcript=$('draftReview').hidden?'':$('rawTranscript').textContent;
  currentConversation.context={local_retrieval:Boolean($('useLocalSources')?.checked),attachment_ids:window.localmindAttachments?.contextIds()||[]};
}
async function ensureConversation(item=currentConversation){
  if(item.serverId)return item.serverId;
  if(item.creation)return item.creation;
  const instance=serverInstance;
  item.creation=conversationAPI('','POST',{}).then(data=>{
    if(instance!==serverInstance||data.server_instance!==instance||typeof data.conversation_id!=='string')throw Error('Сервер перезапущен. Повторите запрос без автоматического выполнения действия.');
    item.serverId=data.conversation_id;item.instance=instance;item.created_at=data.created_at||new Date().toISOString();
    if(item===currentConversation){conversationId=item.serverId;window.localmindAttachments?.adoptConversation(conversationId);}
    return item.serverId;
  }).finally(()=>{item.creation=null;});
  return item.creation;
}
function saveConversation(options={}){
  clearTimeout(draftTimer);draftTimer=null;
  // The submitted draft was committed before stream admission. A late pagehide
  // must not queue an empty autosave behind the server's turn lease.
  if(inFlight)return Promise.resolve();
  captureConversation();
  return persistConversation(currentConversation,options);
}
function persistConversation(item,options={}){
  if(item.deleted||(!item.serverId&&!item.draft&&!item.messages.length))return Promise.resolve();
  const snapshot={draft:item.draft,context:{...item.context,attachment_ids:[...(item.context?.attachment_ids||[])]}};
  item.saveChain=(item.saveChain||Promise.resolve()).catch(()=>{}).then(async()=>{
    if(item.deleted)return;
    await ensureConversation(item);
    await conversationAPI('/'+encodeURIComponent(item.serverId),'PATCH',snapshot,{keepalive:Boolean(options.keepalive)});
    item.saveError=null;historyStatus('История автоматически сохраняется на этом компьютере. Звук и ключи не сохраняются.');
  }).catch(error=>{
    item.saveError=error;historyStatus('Не удалось сохранить изменения: '+error.message+'. Проверьте свободное место и подключение.');
    throw error;
  });
  // Register a rejection handler even when this autosave originates in an event.
  item.saveChain.catch(()=>{});
  return item.saveChain;
}
async function importLegacyHistory(){
  let original;
  try{original=localStorage.getItem(HISTORY_KEY);}catch(error){historyStatus('Не удалось прочитать старую историю. Сохранённая копия не изменена.');return;}
  if(!original)return;
  try{
    if(original.length>3000000)throw Error('Старая история превышает допустимый размер');
    const parsed=JSON.parse(original);
    if(!Array.isArray(parsed)||parsed.length>40)throw Error('Неверный формат старой истории');
    const items=parsed.map(raw=>{
      if(!raw||typeof raw.title!=='string'||raw.title.length>80||!Array.isArray(raw.messages)||raw.messages.length>80)throw Error('Повреждена запись старой истории');
      if(raw.draft!==undefined&&(typeof raw.draft!=='string'||raw.draft.length>2000))throw Error('Повреждён черновик старой истории');
      return {title:raw.title,draft:raw.draft||'',messages:raw.messages.map(message=>{
        if(!message||!['user','assistant'].includes(message.role)||typeof message.content!=='string'||message.content.length>8192)throw Error('Повреждено сообщение старой истории');
        return {role:message.role,content:message.content};
      })};
    });
    const bytes=new TextEncoder().encode(original);
    if(bytes.length>3000000)throw Error('Старая история превышает допустимый размер');
    const hash=await crypto.subtle.digest('SHA-256',bytes);
    const migration_id=Array.from(new Uint8Array(hash),value=>value.toString(16).padStart(2,'0')).join('');
    await conversationAPI('/import','POST',{migration_id,items});
    // Remove only the copy we actually committed; another tab may have changed it.
    if(localStorage.getItem(HISTORY_KEY)===original)localStorage.removeItem(HISTORY_KEY);
    historyStatus('Старая история перенесена в постоянное хранилище. Неизвестные даты не назначались.');
  }catch(error){historyStatus('Старую историю не удалось перенести: '+error.message+'. Исходная копия сохранена.');}
}
async function loadConversations(){
  if(historyLoading)return historyLoading;
  historyLoading=(async()=>{
    await importLegacyHistory();
    const data=await conversationAPI();
    const rows=Array.isArray(data.conversations)?data.conversations:[];
    const existing=new Map(conversations.filter(item=>item.serverId).map(item=>[item.serverId,item]));
    for(const raw of rows){
      if(typeof raw.conversation_id!=='string')continue;
      let item=existing.get(raw.conversation_id);
      if(!item){item=emptyConversation();item.serverId=raw.conversation_id;conversations.push(item);}
      Object.assign(item,{title:raw.title,created_at:raw.created_at,updated_at:raw.updated_at,message_count:raw.message_count});
    }
    historyLoaded=true;renderHistory();
    const latest=rows[0]&&conversations.find(item=>item.serverId===rows[0].conversation_id);
    if(latest&&!busy&&!resetting&&!currentConversation.messages.length&&!$('message').value){
      const blank=currentConversation;
      if(await selectConversation(latest)){const position=conversations.indexOf(blank);if(position>=0&&!blank.serverId)conversations.splice(position,1);renderHistory();}
    }
  })().finally(()=>{historyLoading=null;});
  return historyLoading;
}
function canSwitch(){
  if(busy||voiceBusy||recording||resetting||sessionCreation){state('Завершите или прервите текущий ответ / запись перед сменой разговора.');return false;}
  return true;
}
function transitionControls(value){resetting=value;updateConversationTitle();syncActionControls();}
function applyContext(item){if($('useLocalSources'))$('useLocalSources').checked=Boolean(item.context?.local_retrieval);}
async function selectConversation(item,ownedTransaction=false){
  if(!ownedTransaction&&!canSwitch())return false;
  transitionControls(true);
  try{
    await saveConversation();
    let restored=null;
    if(item.serverId){
      if(item.saveChain)await item.saveChain;
      restored=await conversationAPI('/'+encodeURIComponent(item.serverId));
      // Never use old rendered DOM containing live action/window selectors after
      // reopening. Only server journal text is restored, through safe Markdown.
      const previous=item.messages;
      item.messages=(Array.isArray(restored.messages)?restored.messages:[]).map((message,index)=>{
        const old=previous[index];
        return old?.role===message.role&&old.content===message.content&&old.attachments?{...message,attachments:old.attachments}:message;
      });
      item.title=restored.title||item.title;item.draft=restored.draft||'';item.context=restored.context||{};
      item.created_at=restored.created_at;item.updated_at=restored.updated_at;item.instance=serverInstance;
      item.results=[];item.sources=[];item.retryTurn=null;
    }
    voiceEpoch++;transcriptController?.abort();stopSpeech();
    currentConversation=item;conversationId=item.serverId;
    history.splice(0,history.length,...item.messages.slice(-16).map(message=>({role:message.role,content:message.content})));
    window.localmindScene?.reset();
    window.localmindAttachments?.setConversation(item.serverId||item.id);
    if(restored)window.localmindAttachments?.restore?.(restored.attachments||[],{conversation_id:item.serverId,server_instance:serverInstance},item.context.attachment_ids||[]);
    window.localmindScene?.observeConversation('',item.messages);
    $('thread').replaceChildren();
    for(const message of item.messages){const el=bubble(message.content,message.role==='user'?'me':'assistant');if(message.role==='user')renderSentAttachments(el,message.attachments);}
    $('welcome').hidden=item.messages.length>0;$('message').value=item.draft;applyContext(item);
    $('draftReview').hidden=!item.transcript;$('rawTranscript').textContent=item.transcript||'';
    updateConversationTitle();renderHistory();state('Готов к разговору');return true;
  }catch(error){showError(error.message);return false;}
  finally{if(!ownedTransaction)transitionControls(false);}
}
async function newConversation(discardCapture=false){
  let ownedTransition=false;
  if(discardCapture){
    if(busy||resetting||sessionCreation)return;
    transitionControls(true);ownedTransition=true;
    voiceEpoch++;transcriptController?.abort();stopSpeech();
    if(recording?.state==='recording'){
      const capture=recording,stopped=capture.onstop;
      await new Promise(resolve=>{
        capture.onstop=async event=>{try{await stopped?.call(capture,event);}finally{resolve();}};
        capture.stop();
      });
    }
    voiceBusy=false;
  }else if(!canSwitch())return;
  const previous=currentConversation,item=emptyConversation();conversations.push(item);
  try{
    if(await selectConversation(item,ownedTransition)){
      if(!previous.serverId&&!previous.messages.length&&!previous.draft){const index=conversations.indexOf(previous);if(index>=0)conversations.splice(index,1);renderHistory();}
      $('historyDialog')?.close();$('settingsDialog').close();closeSidebar();$('message').focus();
    }else conversations.splice(conversations.indexOf(item),1);
  }finally{if(ownedTransition)transitionControls(false);}
}
function conversationDate(value){return new Date(typeof value==='number'?value*1000:value||NaN);}
function historyPeriod(item){
  if(!item.updated_at&&!item.created_at)return 'Без даты';
  const date=conversationDate(item.updated_at||item.created_at),today=new Date();
  if(!Number.isFinite(date.getTime()))return 'Без даты';
  const midnight=new Date(today.getFullYear(),today.getMonth(),today.getDate()).getTime();
  if(date.getTime()>=midnight)return 'Сегодня';
  if(date.getTime()>=midnight-86400000)return 'Вчера';
  if(date.getTime()>=midnight-6*86400000)return 'Последние 7 дней';
  return 'Ранее';
}
function renderHistory(){
  const list=$('historyList');if(!list)return;
  list.replaceChildren();let previousGroup=null;
  const ordered=conversations.filter(item=>item.serverId||item===currentConversation).slice().sort((a,b)=>(conversationDate(b.updated_at).getTime()||0)-(conversationDate(a.updated_at).getTime()||0));
  for(const item of ordered){
    const group=historyPeriod(item);
    if(group!==previousGroup){const heading=document.createElement('h3');heading.className='history-period';heading.textContent=group;list.append(heading);previousGroup=group;}
    const row=document.createElement('div');row.className='history-entry'+(item===currentConversation?' active':'');row.dataset.conversationId=item.serverId||item.id;
    const choose=document.createElement('button');choose.type='button';choose.textContent=item.title;
    choose.setAttribute('aria-current',item===currentConversation?'true':'false');
    const detail=document.createElement('small');
    const timestamp=item.updated_at||item.created_at;
    detail.textContent=timestamp?conversationDate(timestamp).toLocaleDateString('ru-RU',{day:'numeric',month:'short'}):'Дата неизвестна';
    choose.append(detail);choose.addEventListener('click',async()=>{if(await selectConversation(item)){closeSidebar();$('message').focus();}});
    const rename=document.createElement('button');rename.type='button';rename.className='text-button';rename.textContent='Имя';rename.setAttribute('aria-label','Переименовать '+item.title);
    rename.addEventListener('click',()=>{if(!canSwitch())return;renaming=item;$('renameInput').value=item.title;$('renameDialog').showModal();$('renameInput').focus();});
    const remove=document.createElement('button');remove.type='button';remove.className='text-button';remove.textContent='Удалить';remove.setAttribute('aria-label','Удалить '+item.title);
    remove.addEventListener('click',()=>deleteConversation(item));
    row.append(choose,rename,remove);list.append(row);
  }
}
async function deleteConversation(item){
  if(!canSwitch()||!window.confirm('Удалить беседу «'+item.title+'» и её сообщения? Это действие нельзя отменить.'))return;
  transitionControls(true);
  try{
    await saveConversation();if(item.saveChain)await item.saveChain;
    if(item.serverId)await conversationAPI('/'+encodeURIComponent(item.serverId),'DELETE',{confirmed:true});
    item.deleted=true;
    if(item===currentConversation){
      const replacement=conversations.find(other=>other!==item&&!other.deleted)||emptyConversation();
      if(!conversations.includes(replacement))conversations.push(replacement);
      // The deleted conversation must never be autosaved/recreated while switching.
      if(!await selectConversation(replacement,true)){
        currentConversation=emptyConversation();conversations.push(currentConversation);conversationId=null;history.length=0;
        $('thread').replaceChildren();$('message').value='';$('welcome').hidden=false;
      }
    }
    const position=conversations.indexOf(item);if(position>=0)conversations.splice(position,1);
    window.localmindAttachments?.clearConversation(item.serverId||item.id);
    renderHistory();historyStatus('Беседа удалена.');
  }catch(error){showError(error.message);}
  finally{transitionControls(false);}
}
$('message').addEventListener('input',()=>{
  currentConversation.draft=$('message').value;clearTimeout(draftTimer);
  draftTimer=setTimeout(()=>saveConversation().catch(()=>{}),350);
});
$('message').addEventListener('change',()=>saveConversation().catch(()=>{}));
$('historyOpen')?.addEventListener('click',()=>{renderHistory();$('historyDialog')?.showModal();});
$('historyNew')?.addEventListener('click',()=>newConversation());$('newChat').addEventListener('click',()=>newConversation());
$('renameForm').addEventListener('submit',async event=>{
  event.preventDefault();const title=$('renameInput').value.trim();const item=renaming;
  if(!item||!title||!canSwitch())return;
  transitionControls(true);
  try{
    await saveConversation();await ensureConversation(item);
    await conversationAPI('/'+encodeURIComponent(item.serverId),'PATCH',{title});
    item.title=title;updateConversationTitle();renderHistory();$('renameDialog').close();
  }catch(error){showError(error.message);}
  finally{transitionControls(false);}
});
$('useLocalSources')?.addEventListener('change',()=>saveConversation().catch(()=>{}));
window.addEventListener('localmind:attachments',()=>{
  if(!historyLoaded||resetting||busy)return;
  clearTimeout(draftTimer);draftTimer=setTimeout(()=>saveConversation().catch(()=>{}),350);
});
window.localmindSession={
  headers,
  get:()=>({conversation_id:conversationId,server_instance:serverInstance}),
  ensure:async()=>{
    if(busy||resetting)throw Error('Дождитесь завершения текущего ответа или смены разговора.');
    if(!serverInstance)throw Error('Нет подключения к локальному серверу.');
    if(!sessionCreation)sessionCreation=ensureConversation().then(()=>({conversation_id:conversationId,server_instance:serverInstance})).finally(()=>{sessionCreation=null;});
    return sessionCreation;
  }
};
function renderDevices(info){
  $('deviceDrawerList').replaceChildren();$('deviceDrawerNote').textContent=info.demo?'DEMO · симуляция. Физические устройства не переключаются.':'REAL · Home Assistant. Состояние физического устройства не опрошено.';
  for(const device of info.devices || []){
    const row=document.createElement('div');row.className='device';
    const name=document.createElement('span');name.textContent=device.name;
    const status=document.createElement('span');status.className='device-state';status.textContent=info.demo?'DEMO · '+(device.state?'Включено':'Выключено'):'REAL · состояние неизвестно';
    row.append(name,status);
    if(device.id==='desk_light'){
      const actions=document.createElement('div');actions.className='device-actions';
      for(const [caption,command] of [['Включить','Включи настольную лампу'],['Выключить','Выключи настольную лампу']]){
        const button=document.createElement('button');button.className='secondary';button.textContent=caption;button.addEventListener('click',()=>{
          if(!canSwitch())return;
          $('message').value=command;currentConversation.draft=command;$('devicesDialog').close();$('message').focus();state('Команда подготовлена. Проверьте и нажмите «Отправить».');
        });actions.append(button);
      }
      row.append(actions);
    }
    $('deviceDrawerList').append(row);
  }
  if(!info.devices?.length)$('deviceDrawerList').textContent='Настроенных устройств нет.';
}
for(const [button,dialog] of [['filesOpen','filesDialog'],['devicesOpen','devicesDialog']])$(button).addEventListener('click',()=>{$(dialog).showModal();if(button==='devicesOpen')refresh();});
$('drawerAttach').addEventListener('click',()=>{$('filesDialog').close();$('fileInput').click();});
$('model').addEventListener('click',()=>$('settingsOpen').click());
$('voiceMode').addEventListener('click',()=>{
  $('speak').checked=!$('speak').checked;$('voiceMode').setAttribute('aria-pressed',String($('speak').checked));
  if(!$('speak').checked)stopSpeech();
  state($('speak').checked?'Голосовой режим: ответы озвучиваются. Для записи нажмите микрофон.':'Голосовой режим выключен.');
});
$('speak').addEventListener('change',()=>$('voiceMode').setAttribute('aria-pressed',String($('speak').checked)));
window.addEventListener('pagehide',()=>saveConversation({keepalive:true}).catch(()=>{}));
window.localmindAttachments?.adoptConversation(currentConversation.id);
updateConversationTitle();
