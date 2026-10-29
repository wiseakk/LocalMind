/* First-party UI: execution status and generated commentary stay separate. */
'use strict';
const $ = id => document.getElementById(id);
const history = [];
let busy = false, recording = null, recordingStartedAt = 0, recordingTimer = null;
let voiceBusy = false;
let serverInstance = null;
let conversationId = null;
let inFlight = null;
let pageClosing = false;
let voiceEpoch = 0;
let resetting = false;
let appsRevision = 0;
let transcriptController = null;
const headers = () => ({'X-LocalMind-Key': $('key').value});
const jsonHeaders = () => ({...headers(), 'Content-Type':'application/json'});
function state(text) { $('composerState').textContent = text; }
function scrollEnd() { $('conversation').scrollTop = $('conversation').scrollHeight; }
function showError(message) { $('errorText').textContent = message; if (!$('errorDialog').open) $('errorDialog').showModal(); }
async function checked(response) {
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try { const data = await response.json(); if (typeof data.detail === 'string') message = data.detail; } catch (_) { /* bounded generic error */ }
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
function pending(el) {
  const p = document.createElement('div'); p.className = 'pending'; p.setAttribute('role','status');
  for (let i=0;i<3;i++) p.append(document.createElement('i'));
  const label = document.createElement('span'); label.textContent = 'Формулирую ответ…'; p.append(label); el.append(p);
}
function renderStatus(el, value) {
  window.localmindScene?.toolResults(value.action_results);
  window.localmindAttachments?.acknowledge(value.context_sources || []);
  el.querySelectorAll('.action-chip').forEach(x=>x.remove());
  for (const result of value.action_results || []) {
    const chip = document.createElement('div'); chip.className = 'action-chip' + (result.success ? '' : ' error');
    const states = {process_created:'Запуск начат; ожидаем окно', already_running:result.observed_state==='visible_window'?'Окно приложения уже открыто':'Приложение уже работает в фоне', launch_pending:'Приложение ещё запускается', observed:'Состояние подтверждено', request_accepted:'Команда принята; состояние пока не подтверждено'};
    const target=result.resolved_target || result.requested_target || result.target || result.data?.application || result.data?.device_id || result.action || 'Действие';
    const observed={on:'включено',off:'выключено',visible_window:'видимое окно',running:'процесс работает',unknown:'неизвестно'};
    const actual=result.observed_state&&result.execution_status!=='request_accepted'?' · Наблюдение: '+(observed[result.observed_state] || result.observed_state):'';
    chip.textContent = (result.mode==='DEMO'?'ДЕМО · симуляция · ':'') + target + ' · ' + (result.success ? states[result.execution_status] || result.status_text || 'Проверка завершена' : result.error || 'Действие не выполнено')+actual;
    el.insertBefore(chip, el.querySelector('.rendered-message')); 
    if(result.execution_status==='permission_required') {
      const permission=document.createElement('button');permission.className='text-button';permission.textContent='Проверить разрешения файлов';
      permission.addEventListener('click',()=>{$('appsDialog').showModal();loadFilePermissions()});chip.append(permission);
    }
    for(const window of result.data?.windows || []) {
      const choose=document.createElement('button');choose.className='text-button';choose.textContent=`Выбрать: ${window.application} — ${window.title}`;
      choose.addEventListener('click',async()=>{if(busy)return;try{
        await checked(await fetch('/api/windows/select',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({conversation_id:conversationId,window_id:window.window_id})}));
        state('Окно выбрано. Можно сказать «покажи это окно».');
      }catch(e){showError(e.message)}});chip.append(choose);
    }
  }
  if ((value.action_results || []).length) state('Результат получен. Ожидаем комментарий…');
  $('trace').textContent = JSON.stringify(value, null, 2); scrollEnd();
}
function lock(value) {
  busy = value; $('send').disabled = value||currentConversation.archived; $('mic').disabled = value || voiceBusy||currentConversation.archived;
  $('attach').disabled=value||currentConversation.archived;$('imageAttach').disabled=value||currentConversation.archived;
  window.localmindScene?.setActivity(value?'generating':'idle');
  if($('interruptReply'))$('interruptReply').disabled=!value;
  document.querySelectorAll('[data-example]').forEach(b=>b.disabled=value);
}
async function sendText(value) {
  if (busy || voiceBusy || recording || resetting) return;
  const text = value.trim(); if (!text) return;
  if (!serverInstance) { showError('Сначала восстановите подключение к серверу.'); return; }
  if(currentConversation.archived){state('Архив доступен для чтения. Начните новый разговор.');return;}
  if(window.localmindAttachments?.hasPending()){state('Дождитесь подготовки документов или удалите их.');return;}
  lock(true); stopSpeech(); $('welcome').hidden = true; $('draftReview').hidden = true;
  window.localmindScene?.observeConversation(text,history);
  if(!currentConversation.messages.length&&currentConversation.title==='Новый разговор')currentConversation.title=text.slice(0,60);
  currentConversation.messages.push({role:'user',content:text});
  updateConversationTitle();
  bubble(text, 'me'); $('message').value = '';
  const el = bubble('', 'assistant'); pending(el); state('Проверка намерения и разрешений…');
  // A retry after transport loss keeps this ID, so the server never repeats the action.
  const request = {request_id: crypto.randomUUID(), server_instance:serverInstance, conversation_id:conversationId, text, history: history.slice(-8), actions_authorized:true,
    attachment_ids:window.localmindAttachments?.contextIds() || [],local_retrieval:Boolean($('useLocalSources')?.checked),
    response_length:$('responseLength').value, compose_actions:$('composeActions').checked,
    model:$('modelSelect').value || null, reasoning:$('reasoning').value,
    context_tokens:Number($('contextTokens').value),response_tokens:Number($('responseTokens').value),keep_alive_seconds:Number($('keepAlive').value)};
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
            if(!actionSpoken && item.data.action_results?.length && item.data.answer) {
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
          if (item.type === 'final') { finalValue = item.data; if(item.data.conversation_id){conversationId=item.data.conversation_id;window.localmindAttachments?.adoptConversation(conversationId);} renderStatus(el, item.data); }
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
    el.querySelector('.pending')?.remove(); renderLocalMindMessage(el.querySelector('.rendered-message'), finalValue.answer);
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
    currentConversation.serverId=conversationId;currentConversation.instance=serverInstance;
    currentConversation.results=(finalValue.action_results || []).slice(-8);
    currentConversation.sources=(finalValue.sources || []).slice(-5);
    window.localmindScene?.observeSources(finalValue.sources || []);
    state('Готов к разговору');
    if(!actionSpoken) speech.feed(deltaText ? '' : finalValue.answer,true);
    await refresh();
  } catch (error) {
    stopSpeech();
    el.querySelector('.pending')?.remove();
    el.querySelector('.rendered-message').textContent=turn.cancelled?'Ответ прерван.':'Ответ недоступен: '+error.message;
    state(turn.cancelled?'Ответ прерван; выполненное действие не отменяется.':'Ошибка связи. Полученный результат действия сохранён выше.');
    currentConversation.messages.push({role:'assistant',content:el.querySelector('.rendered-message').textContent});
    if(error.status===409&&conversationId){currentConversation.archived=true;updateConversationTitle();}
    if(!$('message').value)$('message').value=text;
    await refresh();
  } finally { el.classList.remove('streaming');inFlight=null;lock(false);saveConversation(); $('message').focus(); scrollEnd(); }
}
async function refresh() {
  try {
    const info = await (await checked(await fetch('/api/info', {headers:headers()}))).json();
    if(serverInstance && serverInstance!==info.server_instance){
      for(const item of conversations)if(item.serverId)item.archived=true;
      conversationId=null;updateConversationTitle();
    }
    serverInstance=info.server_instance;
    window.localmindScene?.observeInfo(info);
    $('status').textContent='Сервер подключён'; $('connectionDot').classList.add('online'); $('model').textContent=$('modelSelect').value || info.model;
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
    const selectedVoice=voice.voices?.find(v=>v.id===($('ttsVoice').value || 'ru_RU-denis-medium'));
    $('voiceStatus').textContent=selectedVoice?.ready ? 'Ресурсы выбранного голоса найдены. Синтез выполняется локально; облачная замена отключена.' : 'Выбранный голос требует установки. Piper: docs/VOICE.md; Silero/Chatterbox: docs/NEXT_VOICE.md. Облачная озвучка не используется.';
    if (voice.setup) $('voiceStatus').textContent += '\n'+voice.setup;
  } catch (error) { $('status').textContent=error.message; $('connectionDot').classList.remove('online'); }
}
async function loadModels() {
  const select=$('modelSelect'), selected=select.value;
  try {
    const data=await(await checked(await fetch('/api/models',{headers:headers()}))).json();
    select.replaceChildren();
    for(const model of data.models || []) {
      const option=document.createElement('option'); option.value=model.name; option.textContent=model.name; select.append(option);
    }
    const wanted=selected || data.default;
    if ([...select.options].some(o=>o.value===wanted)) select.value=wanted;
    else {
      const missing=document.createElement('option');missing.value='';missing.textContent='Модель по умолчанию недоступна — выберите локальную';missing.selected=true;select.prepend(missing);
    }
    $('modelStatus').textContent='Только установленные локальные модели. Первый ответ включает загрузку; следующие обычно быстрее. При смене предыдущая модель выгружается. Изменения применяются к следующему запросу.';
    $('model').textContent=select.value || data.default;
  } catch(error) {$('modelStatus').textContent=error.message;}
}
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
  voice:()=>$('ttsVoice')?.value || 'ru_RU-denis-medium',
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
      const label=document.createElement('label');label.className='check';const check=document.createElement('input');check.type='checkbox';check.checked=app.allowed;
      const title=document.createElement('span');title.textContent=app.name; label.append(check,title);
      const path=document.createElement('small');path.textContent=app.target;
      const choose=document.createElement('button');choose.className='text-button';choose.textContent='Подставить точное название';
      choose.addEventListener('click',()=>{$('message').value='Открой '+app.id;$('appsDialog').close();$('message').focus()});
      check.addEventListener('change',async()=>{check.disabled=true;const grantRevision=++appsRevision;try{await checked(await fetch('/api/apps/permission',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({app_id:app.id,allowed:check.checked,fingerprint:app.fingerprint})}));app.allowed=check.checked;if(grantRevision===appsRevision)window.localmindScene?.observeApps(apps);else await loadApps();}catch(error){check.checked=!check.checked;showError(error.message)}finally{check.disabled=false;$('rescan').disabled=false;}});
      row.append(label,path,choose);$('appsList').append(row);
    }
  } catch(error) {if(revision===appsRevision)$('appsList').textContent=error.message;} finally{if(revision===appsRevision)$('rescan').disabled=false;}
}
function stageTranscript(r) {
  $('message').value=r.text; $('rawTranscript').textContent='Исходная расшифровка: '+r.text;
  $('draftReview').hidden=false; state('Текст НЕ отправлен. Проверьте и исправьте расшифровку.'); $('message').focus();
}
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
        stageTranscript(r); $('trace').textContent=JSON.stringify({stt:r},null,2);
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
$('modelSelect').addEventListener('change',()=>{$('model').textContent=$('modelSelect').value || 'Локальная модель'});
$('appsOpen').addEventListener('click',()=>{$('appsDialog').showModal();loadApps();loadFilePermissions()});
$('rescan').addEventListener('click',()=>loadApps(true));
$('key').addEventListener('change',()=>{refresh();loadApps();});
$('speak').addEventListener('change',()=>{if(!$('speak').checked)stopSpeech()});
$('ttsVoice').addEventListener('change',()=>{stopSpeech();refresh()});
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
resetConversation.addEventListener('click',async()=>{
  if(busy||resetting||sessionCreation)return;
  resetting=true;resetConversation.disabled=true;$('send').disabled=true;$('mic').disabled=true;
  // Invalidate capture immediately, before awaiting server context reset.
  voiceEpoch++;transcriptController?.abort();if(recording?.state==='recording')recording.stop();stopSpeech();
  try{
    if(conversationId)await checked(await fetch('/api/conversations/reset',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({conversation_id:conversationId})}));
    window.localmindAttachments?.clearConversation(conversationId || currentConversation.id);
    window.localmindAttachments?.setConversation(currentConversation.id);
    conversationId=null;history.length=0;currentConversation.messages=[];currentConversation.draft='';currentConversation.serverId=null;currentConversation.transcript='';currentConversation.archived=false;
    window.localmindScene?.reset();$('draftReview').hidden=true;$('message').value='';$('rawTranscript').textContent='';$('thread').replaceChildren();$('welcome').hidden=false;updateConversationTitle();saveConversation();state('Новый разговор');
  }catch(error){showError(error.message);}
  finally{resetting=false;resetConversation.disabled=false;$('send').disabled=busy||voiceBusy||Boolean(recording);$('mic').disabled=busy||voiceBusy;}
});
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

// History stores presentation only. Server IDs and capability grants are never
// resurrected from disk; restored text is always an explicitly read-only archive.
const HISTORY_KEY='localmind.blacksite.history.v1';
const conversations=[];
function emptyConversation(){return {id:crypto.randomUUID(),title:'Новый разговор',draft:'',messages:[],serverId:null,instance:null,archived:false,view:null,transcript:''};}
let currentConversation=emptyConversation(),renaming=null,sessionCreation=null;
conversations.push(currentConversation);
function updateConversationTitle(){
  $('conversationTitle').textContent=currentConversation.title+(currentConversation.archived?' · АРХИВ':'');
  $('conversationTitle').classList.toggle('archive-notice',currentConversation.archived);
  $('message').readOnly=currentConversation.archived;
  $('send').disabled=currentConversation.archived||busy||resetting||voiceBusy||Boolean(recording);
  $('mic').disabled=currentConversation.archived||busy||resetting||voiceBusy;
  $('attach').disabled=currentConversation.archived||busy||resetting;
  $('imageAttach').disabled=currentConversation.archived||busy||resetting;
}
function saveConversation(){
  currentConversation.draft=$('message').value;
  currentConversation.serverId=conversationId;
  currentConversation.instance=serverInstance;
  currentConversation.transcript=$('draftReview').hidden?'':$('rawTranscript').textContent;
  persistConversations();
}
function persistConversations(){
  if(!$('persistHistory').checked)return;
  try{
    // Deliberate text opt-in, with bounded storage; never keys, blobs or tool data.
    const records=conversations.slice(-40).map(c=>({title:c.title.slice(0,80),draft:c.draft.slice(0,2000),messages:c.messages.slice(-80).map(m=>({role:m.role,content:m.content.slice(0,8192)}))}));
    localStorage.setItem(HISTORY_KEY,JSON.stringify(records));
    $('historyStorage').textContent='Текст истории сохранён в этом браузере. Файлы, ключи и звук не сохраняются.';
  }catch(_){$('historyStorage').textContent='Браузер запретил сохранение или хранилище заполнено. История остаётся в памяти вкладки.';}
}
function canSwitch(){
  if(busy||voiceBusy||recording||resetting||sessionCreation){state('Завершите или прервите текущий ответ / запись перед сменой разговора.');return false;}
  return true;
}
function transitionControls(value){
  resetting=value;updateConversationTitle();
}
async function selectConversation(item,ownedTransaction=false){
  if(!ownedTransaction&&!canSwitch())return false;
  resetting=true;
  transitionControls(true);
  try{
    saveConversation();
    if(item.serverId&&!item.archived){
      if(item.instance!==serverInstance)item.archived=true;
      else try{await checked(await fetch('/api/conversations/'+encodeURIComponent(item.serverId),{headers:headers()}));}
      catch(error){if(error.status===409||error.status===404)item.archived=true;else throw error;}
    }
    voiceEpoch++;transcriptController?.abort();stopSpeech();
    const fragment=document.createDocumentFragment();while($('thread').firstChild)fragment.append($('thread').firstChild);
    currentConversation.view=fragment;currentConversation=item;
    conversationId=item.archived?null:item.serverId;
    history.splice(0,history.length,...(item.archived?[]:item.messages.slice(-16)));
    window.localmindScene?.reset();
    window.localmindAttachments?.setConversation(item.archived?item.id:item.serverId || item.id);
    if(!item.archived&&(item.serverId||item.messages.length))window.localmindScene?.observeConversation('',item.messages);
    if(!item.archived){window.localmindScene?.toolResults(item.results || []);window.localmindScene?.observeSources(item.sources || []);}
    if(item.view){$('thread').append(item.view);item.view=null;}
    else for(const m of item.messages)bubble(m.content,m.role==='user'?'me':'assistant');
    $('welcome').hidden=item.messages.length>0;
    $('message').value=item.draft;
    $('draftReview').hidden=!item.transcript;$('rawTranscript').textContent=item.transcript;
    updateConversationTitle();renderHistory();
    state(item.archived?'Архив · серверная память истекла. Для продолжения начните новый разговор.':'Готов к разговору');
    return true;
  }catch(error){showError(error.message);return false;}
  finally{if(!ownedTransaction)transitionControls(false);}
}
async function newConversation(){
  if(!canSwitch())return;
  if(conversations.length>=40){showError('В истории уже 40 разговоров. Удалите ненужные перед созданием нового.');return;}
  const item=emptyConversation();conversations.push(item);
  if(await selectConversation(item)){
    $('historyDialog').close();$('settingsDialog').close();$('message').focus();persistConversations();
  }else conversations.splice(conversations.indexOf(item),1);
}
function renderHistory(){
  $('historyList').replaceChildren();
  for(const item of [...conversations].reverse()){
    const row=document.createElement('div');row.className='history-entry'+(item===currentConversation?' active':'');
    const choose=document.createElement('button');choose.textContent=item.title;
    const detail=document.createElement('small');detail.textContent=(item.archived?'Архив · только чтение':'Память этой сессии')+' · '+item.messages.length+' сообщений';choose.append(detail);
    choose.addEventListener('click',async()=>{if(await selectConversation(item)){$('historyDialog').close();$('message').focus();}});
    const rename=document.createElement('button');rename.className='text-button';rename.textContent='Имя';rename.setAttribute('aria-label','Переименовать '+item.title);
    rename.addEventListener('click',()=>{renaming=item;$('renameInput').value=item.title;$('renameDialog').showModal();$('renameInput').focus();});
    const remove=document.createElement('button');remove.className='text-button';remove.textContent='Удалить';remove.setAttribute('aria-label','Удалить '+item.title);
    remove.addEventListener('click',async()=>{
      if(!canSwitch())return;
      transitionControls(true);
      try{
      // Clear server context before discarding its ID. Never replay its messages.
      if(item.serverId&&!item.archived&&item.instance===serverInstance){
        try{await checked(await fetch('/api/conversations/reset',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({conversation_id:item.serverId})}));}
        catch(error){if(error.status!==409){showError(error.message);return;}}
      }
      window.localmindAttachments?.clearConversation(item.serverId || item.id);
      if(item===currentConversation){const replacement=conversations.find(c=>c!==item)||emptyConversation();if(!conversations.includes(replacement))conversations.push(replacement);if(!await selectConversation(replacement,true))return;}
      conversations.splice(conversations.indexOf(item),1);renderHistory();persistConversations();
      }finally{transitionControls(false);}
    });
    row.append(choose,rename,remove);$('historyList').append(row);
  }
}
$('message').addEventListener('input',()=>{currentConversation.draft=$('message').value;});
$('message').addEventListener('change',saveConversation);
$('historyOpen').addEventListener('click',()=>{saveConversation();renderHistory();$('historyDialog').showModal();});
$('historyNew').addEventListener('click',newConversation);$('newChat').addEventListener('click',newConversation);
$('renameForm').addEventListener('submit',e=>{e.preventDefault();const title=$('renameInput').value.trim();if(renaming&&title){renaming.title=title;updateConversationTitle();renderHistory();persistConversations();$('renameDialog').close();}});
$('persistHistory').addEventListener('change',()=>{
  if($('persistHistory').checked){saveConversation();}
  else try{localStorage.removeItem(HISTORY_KEY);$('historyStorage').textContent='Локальная копия удалена. История только в памяти вкладки.';}catch(_){$('historyStorage').textContent='Браузер запретил доступ к сохранённой копии.';}
});
$('clearHistory').addEventListener('click',async()=>{
  if(!canSwitch())return;
  transitionControls(true);
  try{
  for(const item of conversations){
    if(item.serverId&&!item.archived&&item.instance===serverInstance){
      try{await checked(await fetch('/api/conversations/reset',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({conversation_id:item.serverId})}));}
      catch(error){if(error.status!==409){showError(error.message);return;}}
      item.archived=true;
    }
  }
  window.localmindAttachments?.reset();
  const item=emptyConversation();conversations.push(item);if(!await selectConversation(item,true))return;conversations.splice(0,conversations.length,item);
  $('persistHistory').checked=false;
  try{localStorage.removeItem(HISTORY_KEY);$('historyStorage').textContent='История и локальная копия удалены.';}catch(_){$('historyStorage').textContent='История вкладки удалена. Браузер запретил доступ к локальной копии.';}
  renderHistory();
  }finally{updateConversationTitle();transitionControls(false);}
});
try{
  const stored=localStorage.getItem(HISTORY_KEY);
  if(stored&&stored.length<=3000000){const parsed=JSON.parse(stored);if(Array.isArray(parsed)){
    for(const raw of parsed.slice(-39)){
      if(typeof raw.title!=='string'||!Array.isArray(raw.messages))continue;
      const item=emptyConversation();item.title=raw.title.slice(0,80);item.draft=typeof raw.draft==='string'?raw.draft.slice(0,2000):'';item.archived=true;
      item.messages=raw.messages.filter(m=>m&&['user','assistant'].includes(m.role)&&typeof m.content==='string').slice(-80).map(m=>({role:m.role,content:m.content.slice(0,8192)}));conversations.push(item);
    }
    $('persistHistory').checked=true;
  }}
}catch(_){$('historyStorage').textContent='Сохранённая история недоступна. Текущая сессия работает в памяти.';}
window.localmindSession={
  headers,
  get:()=>({conversation_id:conversationId,server_instance:serverInstance}),
  ensure:async()=>{
    if(busy||resetting)throw Error('Дождитесь завершения текущего ответа или смены разговора.');
    if(currentConversation.archived)throw Error('Архив доступен только для чтения. Начните новый разговор.');
    if(!serverInstance)throw Error('Нет подключения к локальному серверу.');
    if(conversationId)return {conversation_id:conversationId,server_instance:serverInstance};
    if(!sessionCreation){
      sessionCreation=(async()=>{
        const instance=serverInstance;
        const data=await(await checked(await fetch('/api/conversations',{method:'POST',headers:jsonHeaders(),body:'{}'}))).json();
        if(instance!==serverInstance||data.server_instance!==instance||typeof data.conversation_id!=='string')throw Error('Сервер перезапущен. Повторите добавление документа.');
        conversationId=data.conversation_id;currentConversation.serverId=conversationId;currentConversation.instance=instance;window.localmindAttachments?.adoptConversation(conversationId);
        return {conversation_id:conversationId,server_instance:instance};
      })().finally(()=>{sessionCreation=null;});
    }
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
          if(!canSwitch()||currentConversation.archived)return;
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
window.addEventListener('pagehide',saveConversation);
window.localmindAttachments?.adoptConversation(currentConversation.id);
updateConversationTitle();
