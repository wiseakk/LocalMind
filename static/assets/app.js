/* First-party UI: execution status and generated commentary stay separate. */
'use strict';
const $ = id => document.getElementById(id);
const history = [];
let busy = false, recording = null, recordingStartedAt = 0, recordingTimer = null;
let speechAudio = null, speechUrl = null, speechEpoch = 0, voiceBusy = false;
let serverInstance = null;
let pageClosing = false;
const headers = () => ({'X-LocalMind-Key': $('key').value});
const jsonHeaders = () => ({...headers(), 'Content-Type':'application/json'});
function state(text) { $('composerState').textContent = text; }
function scrollEnd() { $('conversation').scrollTop = $('conversation').scrollHeight; }
function showError(message) { $('errorText').textContent = message; if (!$('errorDialog').open) $('errorDialog').showModal(); }
async function checked(response) {
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try { const data = await response.json(); if (typeof data.detail === 'string') message = data.detail; } catch (_) { /* bounded generic error */ }
    throw Error(message);
  }
  return response;
}
function bubble(text, who) {
  const el = document.createElement('div'); el.className = 'bubble ' + who;
  if (who === 'assistant') {
    const label = document.createElement('div'); label.className = 'assistant-label'; label.textContent = '◈  LOCALMIND';
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
  el.querySelectorAll('.action-chip').forEach(x=>x.remove());
  for (const result of value.action_results || []) {
    const chip = document.createElement('div'); chip.className = 'action-chip' + (result.success ? '' : ' error');
    const states = {process_created:'Запуск начат; ожидаем окно', already_running:result.observed_state==='visible_window'?'Окно приложения уже открыто':'Приложение уже работает в фоне', launch_pending:'Приложение ещё запускается', observed:'Состояние подтверждено', request_accepted:'Команда принята; состояние пока не подтверждено'};
    chip.textContent = (result.mode==='DEMO'?'ДЕМО · симуляция · ':'') + (result.success ? states[result.execution_status] || 'Проверка завершена' : 'Действие не выполнено');
    el.insertBefore(chip, el.querySelector('.rendered-message')); 
  }
  if ((value.action_results || []).length) state('Результат получен. Ожидаем комментарий…');
  $('trace').textContent = JSON.stringify(value, null, 2); scrollEnd();
}
function lock(value) {
  busy = value; $('send').disabled = value; $('mic').disabled = value || voiceBusy;
  document.querySelectorAll('[data-example]').forEach(b=>b.disabled=value);
}
async function sendText(value) {
  if (busy || voiceBusy || recording) return;
  const text = value.trim(); if (!text) return;
  if (!serverInstance) { showError('Сначала восстановите подключение к серверу.'); return; }
  lock(true); stopSpeech(); $('welcome').hidden = true; $('draftReview').hidden = true;
  bubble(text, 'me'); $('message').value = '';
  const el = bubble('', 'assistant'); pending(el); state('Проверка намерения и разрешений…');
  // A retry after transport loss keeps this ID, so the server never repeats the action.
  const request = {request_id: crypto.randomUUID(), server_instance:serverInstance, text, history: history.slice(-8), actions_authorized:true,
    response_length:$('responseLength').value, compose_actions:$('composeActions').checked,
    model:$('modelSelect').value || null, reasoning:$('reasoning').value,
    context_tokens:Number($('contextTokens').value),response_tokens:Number($('responseTokens').value),keep_alive_seconds:Number($('keepAlive').value)};
  let finalValue = null;
  let deltaText = '', lastSequence = 0;
  const sentAt = performance.now();
  const wallSentAt = Date.now();
  try {
    for (let attempt=0;attempt<2;attempt++) {
      const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),90000);
      try {
        const response = await checked(await fetch('/api/chat/stream', {method:'POST', headers:jsonHeaders(), body:JSON.stringify(request),signal:controller.signal}));
        const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer='';
        function event(line) {
          if (!line.trim()) return;
          const item = JSON.parse(line);
          if (item.type === 'error') throw Error(item.detail || 'Ошибка обработки');
          if (item.type === 'status') renderStatus(el, item.data);
          if (item.type === 'delta' && Number.isInteger(item.sequence) && item.sequence > lastSequence && typeof item.text === 'string') {
            if (deltaText.length + item.text.length > 8192) throw Error('Ответ превышает допустимую длину');
            lastSequence = item.sequence; deltaText += item.text;
            el.querySelector('.pending')?.remove();
            renderLocalMindMessage(el.querySelector('.rendered-message'), deltaText); state('Отвечаю…'); scrollEnd();
          }
          if (item.type === 'final') { finalValue = item.data; renderStatus(el, item.data); }
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
        if (attempt || Math.max(performance.now()-sentAt,Date.now()-wallSentAt) > 120000) throw error;
        state('Восстанавливаем ответ без повторного действия…');
      } finally {clearTimeout(timeout);controller.abort();}
    }
    el.querySelector('.pending')?.remove(); renderLocalMindMessage(el.querySelector('.rendered-message'), finalValue.answer);
    const diagnostics = document.createElement('details'); diagnostics.className='message-diagnostics';
    const summary = document.createElement('summary'); summary.textContent='Диагностика ответа';
    const meta = document.createElement('pre'); meta.className='meta';
    meta.textContent=`${finalValue.engine} · действие ${finalValue.action_ms || 0} мс · LLM ${finalValue.llm_ms || 0} мс`;
    const raw = document.createElement('pre'); raw.textContent=JSON.stringify(finalValue,null,2);
    diagnostics.append(summary,meta,raw); el.append(diagnostics); history.push({role:'user',content:text},{role:'assistant',content:finalValue.answer});
    if (history.length > 16) history.splice(0,history.length-16);
    state('Готов к разговору');
    if ($('speak').checked) {
      // Only final, server-validated prose reaches speech; never partial streams.
      playSpeech(finalValue.answer);
    }
    await refresh();
  } catch (error) {
    el.querySelector('.pending')?.remove();
    el.querySelector('.rendered-message').textContent='Ответ недоступен: '+error.message;
    state('Ошибка связи. Полученный результат действия сохранён выше.');
    await refresh();
  } finally { lock(false); $('message').focus(); scrollEnd(); }
}
async function refresh() {
  try {
    const info = await (await checked(await fetch('/api/info', {headers:headers()}))).json();
    serverInstance=info.server_instance;
    $('status').textContent='Сервер подключён'; $('connectionDot').classList.add('online'); $('model').textContent=$('modelSelect').value || info.model;
    $('mode').textContent=info.demo?'DEMO':'REAL · HA';
    $('demoNote').textContent=info.demo?'Симуляция — физические устройства не переключаются.':'REAL — запросы к разрешённым устройствам Home Assistant.';
    $('devices').replaceChildren();
    for (const d of info.devices) {
      const row=document.createElement('div'); row.className='device';
      const name=document.createElement('span');name.textContent=d.name;
      const status=document.createElement('span'); status.className='device-state';
      status.textContent=info.demo?(d.state?'● Включена':'○ Выключена'):'HA · состояние не опрошено'; row.append(name,status); $('devices').append(row);
    }
    const voice=info.voice || {};
    $('voiceStatus').textContent=voice.voices?.some(v=>v.ready) ? 'Piper и модель Denis готовы. Русская озвучка выполняется локально.' : 'Локальная озвучка требует Piper и модели Denis. См. docs/VOICE.md. Облачная озвучка не используется.';
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
function stopSpeech() {
  speechEpoch++; if (speechAudio) {speechAudio.pause();speechAudio=null;}
  if (speechUrl) {URL.revokeObjectURL(speechUrl);speechUrl=null;}
}
async function playSpeech(text) {
  stopSpeech(); const epoch=speechEpoch;
  try {
    const response=await checked(await fetch('/api/tts',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({text:text.slice(0,1200)})}));
    const blob=await response.blob(); if(epoch!==speechEpoch || !$('speak').checked) return;
    speechUrl=URL.createObjectURL(blob);speechAudio=new Audio(speechUrl);
    speechAudio.onended=()=>{if(epoch===speechEpoch)stopSpeech()}; await speechAudio.play();
  } catch(error) {if(epoch===speechEpoch) state('Озвучка недоступна: '+error.message);}
}
async function loadApps(refreshCatalog=false) {
  $('appsList').textContent='Проверяем установленные приложения…'; $('rescan').disabled=true;
  try {
    const url=refreshCatalog?'/api/apps/refresh':'/api/apps';
    const data=await (await checked(await fetch(url,{method:refreshCatalog?'POST':'GET',headers:headers()}))).json();
    const apps=data.apps; $('appsCount').textContent=apps.length; $('appsList').replaceChildren();
    if (!apps.length) $('appsList').textContent='Безопасные приложения не обнаружены. Доступны проверенные встроенные приложения.';
    for(const app of apps) {
      const row=document.createElement('div');row.className='app-entry';
      const label=document.createElement('label');label.className='check';const check=document.createElement('input');check.type='checkbox';check.checked=app.allowed;
      const title=document.createElement('span');title.textContent=app.name; label.append(check,title);
      const path=document.createElement('small');path.textContent=app.target;
      const choose=document.createElement('button');choose.className='text-button';choose.textContent='Подставить точное название';
      choose.addEventListener('click',()=>{$('message').value='Открой '+app.id;$('appsDialog').close();$('message').focus()});
      check.addEventListener('change',async()=>{check.disabled=true;try{await checked(await fetch('/api/apps/permission',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({app_id:app.id,allowed:check.checked,fingerprint:app.fingerprint})}));}catch(error){check.checked=!check.checked;showError(error.message)}finally{check.disabled=false}});
      row.append(label,path,choose);$('appsList').append(row);
    }
  } catch(error) {$('appsList').textContent=error.message;} finally{$('rescan').disabled=false;}
}
function stageTranscript(r) {
  $('message').value=r.text; $('rawTranscript').textContent='Исходная расшифровка: '+r.text;
  $('draftReview').hidden=false; state('Текст НЕ отправлен. Проверьте и исправьте расшифровку.'); $('message').focus();
}
$('mic').addEventListener('click',async()=>{
  if (recording) {recording.stop(); return;}
  if (busy || voiceBusy) return;
  if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder){showError('Для микрофона нужен localhost и браузер с MediaRecorder. Текстовый ввод доступен.');return}
  stopSpeech(); let stream;
  voiceBusy=true; $('mic').disabled=true; $('send').disabled=true;
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:true});
    if(pageClosing){stream.getTracks().forEach(t=>t.stop());voiceBusy=false;return}
    const type=['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg'].find(t=>MediaRecorder.isTypeSupported(t));
    if(!type)throw Error('Нет поддерживаемого аудиоформата');
    const mr=new MediaRecorder(stream,{mimeType:type}),chunks=[];let bytes=0;
    recording=mr;recordingStartedAt=performance.now();$('mic').classList.add('active');$('mic').textContent='■';$('mic').setAttribute('aria-pressed','true');$('mic').setAttribute('aria-label','Остановить запись');$('send').disabled=true;
    voiceBusy=false;$('mic').disabled=false;
    state('Слушаю… Нажмите ■, чтобы закончить. Максимум 30 секунд.');
    mr.ondataavailable=e=>{if(e.data.size){bytes+=e.data.size;chunks.push(e.data);if(bytes>8*1024*1024 && mr.state==='recording')mr.stop()}};
    mr.onstop=async()=>{
      clearTimeout(recordingTimer);recording=null;stream.getTracks().forEach(t=>t.stop());$('mic').classList.remove('active');$('mic').textContent='◉';$('mic').setAttribute('aria-pressed','false');$('mic').setAttribute('aria-label','Записать голос');
      voiceBusy=true;$('mic').disabled=true;
      try {
        if(pageClosing)return;
        if(bytes>8*1024*1024)throw Error('Аудио превышает 8 МБ');
        if(bytes<1024 || performance.now()-recordingStartedAt<400)throw Error('Запись слишком короткая. Проверьте микрофон.');
        const ext=type.includes('mp4')?'mp4':type.includes('ogg')?'ogg':'webm';
        const form=new FormData();form.append('audio',new Blob(chunks,{type}),`voice.${ext}`);form.append('profile',$('voiceProfile').value);
        state('Обрабатываю русскую речь на компьютере…');
        const r=await(await checked(await fetch('/api/transcribe',{method:'POST',headers:headers(),body:form}))).json();
        stageTranscript(r); $('trace').textContent=JSON.stringify({stt:r},null,2);
      }catch(error){state('Распознавание недоступно. Используйте текстовый ввод.');showError(error.message)}
      finally{voiceBusy=false;$('mic').disabled=false;$('send').disabled=false;}
    };
    mr.onerror=()=>{if(mr.state!=='inactive')mr.stop();state('Ошибка записи микрофона')};
    mr.start(500);recordingTimer=setTimeout(()=>{if(mr.state==='recording')mr.stop()},30000);
  } catch(error) {
    stream?.getTracks().forEach(t=>t.stop());clearTimeout(recordingTimer);recording=null;voiceBusy=false;
    $('mic').classList.remove('active');$('mic').textContent='◉';$('mic').setAttribute('aria-pressed','false');$('mic').setAttribute('aria-label','Записать голос');
    $('mic').disabled=false;$('send').disabled=false;showError('Микрофон: '+error.message);
  }
});
$('form').addEventListener('submit',e=>{e.preventDefault();sendText($('message').value)});
$('message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendText($('message').value)}});
for(const b of document.querySelectorAll('[data-example]'))b.addEventListener('click',()=>sendText(b.dataset.example));
for(const b of document.querySelectorAll('[data-close]'))b.addEventListener('click',()=>$(b.dataset.close).close());
$('settingsOpen').addEventListener('click',()=>{$('settingsDialog').showModal();refresh();loadModels()});
$('modelSelect').addEventListener('change',()=>{$('model').textContent=$('modelSelect').value || 'Локальная модель'});
$('appsOpen').addEventListener('click',()=>{$('appsDialog').showModal();loadApps()});
$('rescan').addEventListener('click',()=>loadApps(true));
$('key').addEventListener('change',refresh);
$('speak').addEventListener('change',()=>{if(!$('speak').checked)stopSpeech()});
$('stopAudio').addEventListener('click',()=>{stopSpeech();state('Озвучка остановлена')});
$('discardDraft').addEventListener('click',()=>{$('draftReview').hidden=true;$('message').value='';state('Готов к разговору')});
function closeSidebar(){$('sidebar').classList.remove('open');$('sidebarToggle').setAttribute('aria-expanded','false');updateSidebarAccess()}
const mobileLayout=window.matchMedia?.('(max-width:760px)');
function updateSidebarAccess(){$('sidebar').inert=Boolean(mobileLayout?.matches&&!$('sidebar').classList.contains('open'))}
$('sidebarToggle').addEventListener('click',()=>{const open=$('sidebar').classList.toggle('open');$('sidebarToggle').setAttribute('aria-expanded',String(open));updateSidebarAccess()});
mobileLayout?.addEventListener('change',updateSidebarAccess);updateSidebarAccess();
$('chatNav').addEventListener('click',()=>{closeSidebar();$('message').focus()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]')){closeSidebar();if(mobileLayout?.matches)$('sidebarToggle').focus()}});
$('diagnostics').addEventListener('click',async()=>{$('diagnostics').disabled=true;try{$('diagnosticResult').textContent=JSON.stringify(await(await checked(await fetch('/api/diagnostics',{headers:headers()}))).json(),null,2)}catch(e){$('diagnosticResult').textContent=e.message}finally{$('diagnostics').disabled=false}});
window.addEventListener('pagehide',()=>{pageClosing=true;stopSpeech();if(recording?.state==='recording')recording.stop()});
window.addEventListener('pageshow',()=>{pageClosing=false;if(!busy&&!voiceBusy&&!recording){$('send').disabled=false;$('mic').disabled=false}});
refresh();
