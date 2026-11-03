/* Owner-only setup. Paths never originate from model output. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const host=$('settings-advanced');if(!host)return;
  const element=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
  const button=(text,fn)=>{const b=element('button',text);b.type='button';b.className='secondary';b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){notice.textContent=e.message;}finally{b.disabled=false;}};return b;};
  const input=(label,value='')=>{const l=element('label',label),n=element('input');n.value=value;l.append(n);return {label:l,input:n};};
  const check=text=>{const l=element('label');l.className='check';const n=element('input');n.type='checkbox';l.append(n,text);return {label:l,input:n};};
  const bytes=n=>typeof n==='number'?(n/1073741824).toFixed(2)+' GiB':'неизвестно';
  async function api(path,body){const r=await fetch('/api/setup'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Настройка недоступна');return d;}
  const section=element('section');section.className='side-section';
  const notice=element('p');notice.setAttribute('role','status');
  const info=element('pre');info.className='mini';
  const destination=input('Новый каталог данных LocalMind');destination.input.placeholder='D:\\LocalMind';
  const accept=check('Копировать данные в указанный каталог. Исходные файлы сохранить. Применить после перезапуска.');
  let planned=null;
  const apply=button('Подтвердить копирование',async()=>{if(!planned||!accept.input.checked)throw Error('Сначала проверьте план и подтвердите копирование.');const d=await api('/storage/apply',{plan_id:planned.id,consent:true});planned=null;apply.hidden=true;accept.input.checked=false;notice.textContent='Копии проверены. Исходные данные сохранены. '+(d.restart_required?'Перезапустите LocalMind; при явном LOCALMIND_DATA_DIR измените его отдельно.':'Ресурсы доступны.');});apply.hidden=true;
  const plan=async source=>{planned=null;apply.hidden=true;accept.input.checked=false;const d=await api('/storage/plan',{destination:source==='ollama_models'?ollama.input.value:destination.input.value,source});planned=d;notice.textContent='Источник: '+d.source+'\nНазначение: '+d.destination+'\nДанные: '+bytes(d.bytes)+', требуется: '+bytes(d.required_bytes)+', свободно: '+bytes(d.free_bytes)+'. Конфликтующие файлы не перезаписываются.';apply.hidden=false;};
  destination.input.oninput=()=>{planned=null;apply.hidden=true;accept.input.checked=false;};
  const ollama=input('Каталог моделей Ollama');
  ollama.input.oninput=()=>{planned=null;apply.hidden=true;accept.input.checked=false;};
  const managedConsent=check('Разрешаю запустить новый локальный Ollama с этим каталогом, если сервер ещё не работает.');
  const external=button('Показать настройку общего Ollama',async()=>{const d=await api('/storage/ollama-instructions',{destination:ollama.input.value});notice.textContent=d.steps.join('\n')+'\n'+d.notice;});
  const start=button('Запустить отдельный Ollama',async()=>{if(!managedConsent.input.checked)throw Error('Подтвердите запуск Ollama.');const d=await api('/storage/ollama-start',{destination:ollama.input.value,consent:true});notice.textContent=d.confirmed?'Сервер и каталог подтверждены: '+d.path:'Каталог не подтверждён.';await refresh();});
  async function refresh(){const d=await api('/storage');info.textContent='LocalMind: '+d.localmind.data_root+'\nOllama: '+(d.ollama.path||'каталог не подтверждён')+'\nИсточник: '+d.ollama.source+'\n'+d.localmind.notice+(d.localmind.environment_override?'\nLOCALMIND_DATA_DIR имеет приоритет над сохранённым выбором.':'');if(!destination.input.value)destination.input.value=d.localmind.data_root;if(!ollama.input.value)ollama.input.value=d.ollama.path||d.ollama.suggested_path;}
  section.append(element('h3','Хранилище данных'),info,button('Проверить пути',refresh),destination.label,button('Проверить план переноса',()=>plan('current')),button('Подготовить копирование старых голосовых ресурсов',()=>plan('legacy_models')),accept.label,apply,ollama.label,button('Проверить копирование существующих моделей Ollama',()=>plan('ollama_models')),external,managedConsent.label,start,notice);host.append(section);
  const retention=element('section');retention.className='expert-only side-section';
  const seconds=input('Хранить после запроса, секунд (0–900)','300');seconds.input.type='number';seconds.input.min='0';seconds.input.max='900';
  const temporary=check('Очищать временные модели после теста, когда отсутствие внешней нагрузки доказано.');
  const previous=check('Выгружать предыдущую модель после успешной смены, когда это безопасно.');
  const memoryInfo=element('pre');memoryInfo.className='mini';
  const generationFields={temperature:'temperature',reasoning:'reasoning',contextTokens:'context_tokens',responseTokens:'response_tokens',keepAlive:'keep_alive_seconds'};
  let preferenceEpoch=0, currentModel=null;
  const generationValues=()=>Object.fromEntries(Object.entries(generationFields).map(([id,key])=>[key,id==='reasoning'?$(id).value:Number($(id).value)]));
  async function saveGeneration(){++preferenceEpoch;if(!currentModel)throw Error('Дождитесь загрузки настроек модели.');await api('/generation',{...generationValues(),model:currentModel});}
  function applyGeneration(config){if(!config)return;for(const [id,key] of Object.entries(generationFields)){if(config[key]!==undefined){$(id).value=String(config[key]);if(id==='keepAlive'&&!$(id).value){const opt=element('option',config[key]+' секунд');opt.value=String(config[key]);$(id).append(opt);$(id).value=opt.value;}}}}
  for(const id of Object.keys(generationFields))$(id)?.addEventListener('change',()=>saveGeneration().catch(e=>{notice.textContent=e.message;}));
  window.addEventListener('localmind-model-selected',e=>{++preferenceEpoch;currentModel=e.detail?.model||currentModel;applyGeneration(e.detail);});
  const unload=input('Имя неактивной модели для выгрузки из памяти');
  const unloadConsent=check('Подтверждаю: другие приложения сейчас не отправляют запросы этой модели.');
  retention.append(element('h3','Удержание моделей в памяти'),seconds.label,temporary.label,previous.label,
    button('Сохранить политику',async()=>{const d=await api('/memory',{keep_alive_seconds:Number(seconds.input.value),cleanup_temporary:temporary.input.checked,unload_previous:previous.input.checked});$('keepAlive').value=String(d.policy.keep_alive_seconds);if(!$('keepAlive').value){const opt=element('option',d.policy.keep_alive_seconds+' секунд');opt.value=String(d.policy.keep_alive_seconds);$('keepAlive').append(opt);$('keepAlive').value=opt.value;}await saveGeneration();memoryInfo.textContent=d.notice;}),
    element('p','Автоматическая выгрузка общего сервера пропускается при неопределённой внешней нагрузке. Выгрузка освобождает память и сохраняет файлы модели.'),unload.label,unloadConsent.label,
    button('Выгрузить и проверить',async()=>{if(!unloadConsent.input.checked)throw Error('Подтвердите отсутствие внешних запросов.');const d=await api('/memory/unload',{model:unload.input.value,confirm_no_external_requests:true});memoryInfo.textContent=d.state==='unloaded_verified'?'Выгружена из памяти; установка сохранена.':d.reason||'Выгрузка не подтверждена.';unloadConsent.input.checked=false;}),memoryInfo);host.append(retention);
  async function initialize(){try{await refresh();const epoch=preferenceEpoch;const g=await api('/generation');if(epoch===preferenceEpoch){currentModel=g.active;applyGeneration(g.generation);}const m=await api('/memory');seconds.input.value=String(m.policy.keep_alive_seconds);temporary.input.checked=m.policy.cleanup_temporary;previous.input.checked=m.policy.unload_previous;memoryInfo.textContent=m.notice;}catch(e){notice.textContent=e.message;}}
  initialize();
})();
