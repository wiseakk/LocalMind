/* Conversation-scoped, local document context. Uploaded content is reference material only. */
(() => {
  'use strict';
  const get=id=>document.getElementById(id),list=get('attachmentList'),notice=get('attachmentNotice');
  const LIMITS=Object.freeze({count:8,file:10*1024*1024,total:40*1024*1024,imagePixels:16000000});
  const types={pdf:['application/pdf'],txt:['text/plain'],md:['text/plain','text/markdown','text/x-markdown'],json:['application/json','text/plain'],docx:['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],csv:['text/csv','application/csv','text/plain','application/vnd.ms-excel'],png:['image/png'],jpg:['image/jpeg'],jpeg:['image/jpeg'],webp:['image/webp']};
  const images=new Set(['png','jpg','jpeg','webp']),groups=new Map(),submissions=new Map();
  let entries=[],serial=0,conversation='',selection=0,previewEntry=null,requestOverride=null,sessionOverride=null;
  groups.set('',entries);
  const labels={preparing:'Подготовка…',parsing:'Обрабатываем локально…',ready:'Загружено · будет передано со следующим сообщением',added:'Включено в запрос к локальной модели',error:'Не добавлено',removing:'Удалено из будущих запросов'};
  const cleanName=name=>String(name).replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g,'').slice(0,160);
  const live=entry=>entry.alive&&entry.group.includes(entry);
  const label=entry=>get('showFilenames')?.checked?cleanName(entry.name):'Вложение '+entry.number+' · '+entry.ext.toUpperCase();
  const api=(url,options={})=>requestOverride?requestOverride(url,options):fetch(url,{...options,headers:{...window.localmindSession?.headers?.(),...options.headers}});
  function say(text){if(notice){notice.hidden=false;notice.textContent=text;}}
  async function checked(response){if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(typeof detail==='string'?detail:'Локальная обработка недоступна ('+response.status+')');}return response.json();}
  function changed(){
    window.localmindScene?.setFiles(entries.filter(e=>!['error','removing'].includes(e.state)).map(e=>({id:e.serverId||e.id,label:label(e),inContext:e.state==='added',state:e.state})));
    const files=get('filesList');if(files){
      files.replaceChildren();
      if(!entries.length){const empty=document.createElement('p');empty.className='empty-state';empty.textContent='Добавьте документ или изображение в диалог. Файлы обрабатываются на этом компьютере.';files.append(empty);}
      for(const e of entries){const row=document.createElement('div');row.className='file-entry';const info=document.createElement('div');const title=document.createElement('strong');title.textContent=label(e);const detail=document.createElement('small');detail.textContent=e.status.textContent;info.append(title,detail);row.append(info);if(e.demo&&!e.demo.hidden){const open=document.createElement('button');open.type='button';open.className='text-button';open.textContent='Предпросмотр';open.addEventListener('click',()=>preview(e));row.append(open);}const close=document.createElement('button');close.type='button';close.className='text-button';close.textContent='Удалить';close.addEventListener('click',()=>remove(e));row.append(close);files.append(row);}
    }
    window.dispatchEvent(new CustomEvent('localmind:attachments',{detail:{pending:hasPending(),count:entries.length}}));
  }
  function status(entry,state,error){if(!live(entry))return;entry.state=state;entry.row.dataset.state=state;entry.row.classList.toggle('error',state==='error');entry.status.textContent=error||labels[state];if(entry.truncated)entry.status.textContent+=' · текст сокращён до '+entry.characters+' символов';entry.demo.hidden=!['ready','added'].includes(state);if(entry.group===entries)changed();}
  function read(blob){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('Файл не удалось прочитать'));reader.readAsArrayBuffer(blob);});}
  // Inspect dimensions before decoding. Reject unrecognized/oversized raster headers.
  function dimensions(buffer,ext){
    const b=new Uint8Array(buffer),v=new DataView(buffer);
    if(ext==='png'&&b.length>=24&&v.getUint32(0)===0x89504e47&&v.getUint32(4)===0x0d0a1a0a)return [v.getUint32(16),v.getUint32(20)];
    if((ext==='jpg'||ext==='jpeg')&&b[0]===255&&b[1]===216){
      let i=2;while(i+8<b.length){if(b[i++]!==255)break;while(b[i]===255)i++;const marker=b[i++];
        if(marker===217||marker===218)break;if(marker===1||(marker>=208&&marker<=215))continue;
        const len=(b[i]<<8)|b[i+1];if(len<2||i+len>b.length)break;
        if([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(marker))return [(b[i+5]<<8)|b[i+6],(b[i+3]<<8)|b[i+4]];
        i+=len;
      }
    }
    if(ext==='webp'&&b.length>=30&&v.getUint32(0)===0x52494646&&v.getUint32(8)===0x57454250){
      const kind=v.getUint32(12);
      if(kind===0x56503858)return [1+b[24]+(b[25]<<8)+(b[26]<<16),1+b[27]+(b[28]<<8)+(b[29]<<16)];
      if(kind===0x56503820&&b[23]===0x9d&&b[24]===1&&b[25]===0x2a)return [v.getUint16(26,true)&16383,v.getUint16(28,true)&16383];
      if(kind===0x5650384c&&b[20]===0x2f)return [1+((b[21]|b[22]<<8)&16383),1+((b[22]>>6|b[23]<<2|b[24]<<10)&16383)];
    }
    throw Error('Некорректный или неподдерживаемый заголовок изображения');
  }

  async function forgetServer(entry){
    if(!entry.serverId||!entry.session)return;
    try{await api('/api/attachments/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...entry.session,attachment_id:entry.serverId})});}catch{/* A removed ID is never submitted again, even if cleanup is temporarily unavailable. */}
  }
  async function prepare(entry){
    try{
      const token=selection;
      if(images.has(entry.ext)){
        const bytes=await read(entry.file.slice(0,65536));if(!live(entry))return;
        const [w,h]=dimensions(bytes,entry.ext);
        if(!w||!h||w*h>LIMITS.imagePixels||w>8192||h>8192)throw Error('Изображение: максимум 16 Мп и 8192 px по стороне');
        if(typeof createImageBitmap==='function'){
          const bitmap=await createImageBitmap(entry.file,{resizeWidth:192,resizeHeight:192,resizeQuality:'low'});
          try{
          if(!live(entry))return;
          const thumbnail=document.createElement('canvas');thumbnail.width=192;thumbnail.height=192;thumbnail.setAttribute('aria-label','Предпросмотр выбранного изображения');thumbnail.setAttribute('role','img');
          thumbnail.getContext('2d').drawImage(bitmap,0,0,192,192);entry.row.prepend(thumbnail);entry.thumbnail=thumbnail;entry.dimensions=[w,h];
          }finally{bitmap.close();}
        }
        entry.dimensions=[w,h];
      }
      if(token!==selection)throw Error('Диалог изменён до загрузки. Добавьте вложение повторно.');
      const ensure=sessionOverride||window.localmindSession?.ensure;
      if(!ensure)throw Error('Сеанс ещё не готов. Повторите добавление вложения.');
      const session=await ensure();
      if(!live(entry))return;
      if(token!==selection)throw Error('Диалог изменён до загрузки. Добавьте документ повторно.');
      if(!session?.conversation_id||!session.server_instance)throw Error('Нет подтверждения локального сеанса');
      entry.session={conversation_id:session.conversation_id,server_instance:session.server_instance};
      if(!conversation){groups.delete('');conversation=session.conversation_id;groups.set(conversation,entries);}
      if(conversation!==session.conversation_id)throw Error('Диалог изменён до загрузки');
      const form=new FormData();form.append('file',entry.file);form.append('conversation_id',session.conversation_id);form.append('server_instance',session.server_instance);
      status(entry,'parsing');
      const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),120000);
      entry.uploadController=controller;
      let data;
      try{data=await checked(await api('/api/attachments',{method:'POST',body:form,signal:controller.signal}));}finally{clearTimeout(timeout);entry.uploadController=null;}
      if(data.conversation_id!==session.conversation_id||data.server_instance!==session.server_instance||typeof data.id!=='string'||!data.id||data.state!=='ready')throw Error('Сервер вернул неподтверждённое вложение');
      entry.serverId=data.id;
      if(!live(entry)){await forgetServer(entry);return;}
      entry.preview=typeof data.preview==='string'?data.preview.slice(0,6000):'';entry.truncated=Boolean(data.truncated);entry.characters=Number(data.characters)||0;entry.file=null;
      status(entry,'ready');
    }catch(error){if(live(entry)){status(entry,'error','Не добавлено: '+(error.name==='AbortError'?'время обработки истекло':error.message));entry.file=null;}}
  }
  async function preview(entry){
    if(!live(entry))return;
    const dialog=get('attachmentPreview');if(!dialog)return;
    previewEntry=entry;
    get('previewTitle').textContent=label(entry);
    const canvas=get('previewCanvas');let text=get('previewText');
    if(!text){text=document.createElement('pre');text.id='previewText';text.className='document-preview';canvas.after(text);}
    canvas.hidden=!images.has(entry.ext);text.hidden=images.has(entry.ext);
    get('previewNote').textContent=images.has(entry.ext)?'Изображение обработано на локальном сервере. '+(entry.state==='added'?'Включено в запрос к модели.':'Будет передано модели с поддержкой зрения при следующей отправке.'):(entry.truncated?'Текст сокращён. ':'')+'Извлечено '+entry.characters+' символов. Предпросмотр — первые 6 000 символов. '+(entry.state==='added'?'Сервер подтвердил использование в контексте.':'Документ будет использован при следующей отправке.');
    text.textContent=entry.preview||'Текст для предпросмотра отсутствует.';
    dialog.showModal();
    if(images.has(entry.ext)){
      const [w,h]=entry.dimensions,scale=Math.min(1,960/w,720/h);canvas.width=Math.max(1,Math.round(w*scale));canvas.height=Math.max(1,Math.round(h*scale));
      const context=canvas.getContext('2d');context.clearRect(0,0,canvas.width,canvas.height);
      if(entry.thumbnail)context.drawImage(entry.thumbnail,0,0,canvas.width,canvas.height);
      if(entry.file){
        try{const bitmap=await createImageBitmap(entry.file,{resizeWidth:canvas.width,resizeHeight:canvas.height,resizeQuality:'high'});try{if(previewEntry===entry&&live(entry)&&dialog.open)context.drawImage(bitmap,0,0,canvas.width,canvas.height);}finally{bitmap.close();}}catch{if(previewEntry===entry)get('previewNote').textContent+=' Показан уменьшенный предпросмотр.';}
      }
    }
  }
  function closePreview(){previewEntry=null;get('attachmentPreview')?.close();const canvas=get('previewCanvas');if(canvas){canvas.width=1;canvas.height=1;}const text=get('previewText');if(text)text.textContent='';}
  get('previewClose')?.addEventListener('click',closePreview);
  get('attachmentPreview')?.addEventListener('close',()=>{previewEntry=null;});
  function remove(entry){
    if(!live(entry))return;
    entry.alive=false;entry.uploadController?.abort();entry.file=null;entry.preview='';entry.state='removing';entry.row.remove();entry.group.splice(entry.group.indexOf(entry),1);
    if(previewEntry===entry)closePreview();
    void forgetServer(entry);
    if(entry.group===entries){if(!entries.length){notice.hidden=true;notice.textContent='';}changed();}
  }
  function add(files){
    const incoming=Array.from(files),active=entries;
    if(incoming.length+active.length>LIMITS.count){say('Не более 8 вложений. Удалите лишние и повторите.');return;}
    const total=incoming.reduce((s,f)=>s+f.size,0)+active.reduce((s,e)=>s+e.size,0);
    if(total>LIMITS.total){say('Общий размер — не более 40 МБ. Файлы не прочитаны.');return;}
    for(const file of incoming){
      const ext=file.name.split('.').pop().toLowerCase();let error='';
      if(!Object.hasOwn(types,ext))error='Этот тип не поддерживается';
      else if(!file.size)error='Пустой файл';
      else if(file.size>LIMITS.file)error='Размер — не более 10 МБ на файл';
      else if(file.type&&!types[ext].includes(file.type.toLowerCase()))error='Тип MIME не совпадает с расширением';
      const entry={id:'attachment-'+(++serial),number:serial,file:error?null:file,name:file.name,size:error?0:file.size,ext:ext.slice(0,8),state:'preparing',alive:true,group:entries};
      const row=document.createElement('div');row.className='attachment';row.dataset.id=entry.id;entry.row=row;
      const icon=document.createElement('span');window.localmindIcon?.(icon,'file');
      const info=document.createElement('div');info.className='attachment-info';
      const title=document.createElement('span');title.className='attachment-name';title.textContent=label(entry);entry.title=title;
      const progress=document.createElement('span');progress.className='attachment-state';entry.status=progress;
      const open=document.createElement('button');open.type='button';open.className='preview-button';open.textContent='Предпросмотр';open.hidden=true;entry.demo=open;open.addEventListener('click',()=>preview(entry));
      const close=document.createElement('button');close.type='button';close.className='icon-button';close.setAttribute('aria-label','Удалить вложение '+entry.number);window.localmindIcon?.(close,'close');close.addEventListener('click',()=>remove(entry));
      info.append(title,progress,open);row.append(icon,info,close);list.append(row);entries.push(entry);
      if(error)status(entry,'error',error);else{status(entry,'preparing');void prepare(entry);}
    }
    if(incoming.length)say('Документы и изображения обрабатываются локальным сервером и передаются выбранной локальной модели. Без облака · 8 файлов, 10 МБ каждый, 40 МБ всего.');
  }
  get('attach').addEventListener('click',()=>get('fileInput').click());
  get('fileInput').addEventListener('change',e=>{add(e.target.files);e.target.value='';});
  get('imageAttach')?.addEventListener('click',()=>get('imageInput')?.click());
  get('imageInput')?.addEventListener('change',e=>{add(e.target.files);e.target.value='';});
  const zone=get('dropZone');let dragDepth=0;
  function fileDrag(e){return Array.from(e.dataTransfer?.types||[]).includes('Files');}
  zone.addEventListener('dragenter',e=>{if(fileDrag(e)){e.preventDefault();dragDepth++;zone.classList.add('drop-active');}});
  zone.addEventListener('dragover',e=>{if(fileDrag(e)){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
  zone.addEventListener('dragleave',()=>{if(--dragDepth<=0){dragDepth=0;zone.classList.remove('drop-active');}});
  zone.addEventListener('drop',e=>{if(fileDrag(e)){e.preventDefault();dragDepth=0;zone.classList.remove('drop-active');add(e.dataTransfer.files);}});
  document.addEventListener('dragover',e=>{if(fileDrag(e))e.preventDefault();});
  document.addEventListener('drop',e=>{if(fileDrag(e))e.preventDefault();});
  get('message').addEventListener('paste',e=>{if(e.clipboardData?.files.length){e.preventDefault();add(e.clipboardData.files);}});
  get('showFilenames')?.addEventListener('change',()=>{for(const group of groups.values())for(const e of group)e.title.textContent=label(e);changed();});
  // Re-key the active browser draft after the server creates its opaque ID.
  // This does not switch conversations, reset lifecycle tokens or merge contexts.
  function adoptConversation(id){
    if(typeof id!=='string'||!id||id===conversation)return;
    if(groups.has(id)&&groups.get(id)!==entries)return;
    groups.delete(conversation);conversation=id;groups.set(id,entries);
  }
  function setConversation(id){
    const next=id||'';if(next===conversation)return;
    selection++;closePreview();for(const entry of entries)entry.row.remove();
    conversation=next;entries=groups.get(next)||[];groups.set(next,entries);for(const entry of entries)list.append(entry.row);
    if(notice){notice.hidden=!entries.length;notice.textContent=entries.length?'Вложения этого диалога · локальная обработка':'';}changed();
  }
  function restore(documents,session,selectedIds=[]){
    setConversation(session.conversation_id);
    const selected=new Set(selectedIds),existing=new Map(entries.map(e=>[e.serverId,e]));
    for(const doc of documents||[]){
      if(!selected.has(doc.id))continue;
      if(existing.has(doc.id)){existing.get(doc.id).session={...session};continue;}
      const ext=String(doc.name||'document.txt').split('.').pop().toLowerCase().slice(0,8);
      const entry={id:'attachment-'+(++serial),number:serial,serverId:doc.id,file:null,name:doc.name||'Документ',size:doc.size||0,ext,state:'ready',alive:true,group:entries,session:{...session},preview:doc.preview||'',characters:doc.characters,truncated:doc.truncated};
      const row=document.createElement('div');row.className='attachment';row.dataset.id=entry.id;entry.row=row;
      const info=document.createElement('div');info.className='attachment-info';
      entry.title=document.createElement('span');entry.title.className='attachment-name';entry.title.textContent=label(entry);
      entry.status=document.createElement('span');entry.status.className='attachment-state';
      entry.demo=document.createElement('button');entry.demo.type='button';entry.demo.className='preview-button';entry.demo.textContent='Предпросмотр';entry.demo.addEventListener('click',()=>preview(entry));
      const close=document.createElement('button');close.type='button';close.className='text-button';close.textContent='Удалить';close.onclick=()=>remove(entry);
      info.append(entry.title,entry.status,entry.demo);row.append(info,close);entries.push(entry);list.append(row);status(entry,'ready');entry.demo.hidden=!entry.preview||images.has(ext);
    }
    changed();
  }
  function clearConversation(id){const key=id||'';const group=groups.get(key);if(!group)return;for(const entry of [...group])remove(entry);groups.delete(key);if(key===conversation){entries=[];groups.set(key,entries);changed();}}
  function reset(){selection++;closePreview();submissions.clear();for(const group of groups.values())for(const e of [...group])remove(e);groups.clear();conversation='';entries=[];groups.set('',entries);get('fileInput').value='';if(get('imageInput'))get('imageInput').value='';notice.hidden=true;notice.textContent='';zone.classList.remove('drop-active');dragDepth=0;changed();}
  function hasPending(){return entries.some(e=>e.state==='preparing'||e.state==='parsing');}
  function contextIds(){return entries.filter(e=>e.serverId&&e.state==='ready').map(e=>e.serverId);}
  function beginSubmission(request){
    if(submissions.has(request.request_id))return submissions.get(request.request_id).snapshot;
    const chosen=entries.filter(e=>request.attachment_ids.includes(e.serverId)&&e.state==='ready'&&e.session?.conversation_id===request.conversation_id&&e.session?.server_instance===request.server_instance);
    const snapshot=Object.freeze(chosen.map(e=>Object.freeze({id:e.serverId,label:label(e),kind:images.has(e.ext)?'image':'document',thumbnail:e.thumbnail?.toDataURL('image/png')||null})));
    submissions.set(request.request_id,{conversation:request.conversation_id,instance:request.server_instance,chosen,snapshot});
    return snapshot;
  }
  function acknowledge(value,request){
    const sent=submissions.get(request?.request_id);
    if(!sent||value.request_id!==request.request_id||value.server_instance!==sent.instance||value.conversation_id!==sent.conversation||value.attachment_state!=='included_in_inference')return false;
    const ids=new Set((value.context_sources||[]).map(s=>s.id));
    if(!sent.chosen.every(e=>ids.has(e.serverId)))return false;
    for(const e of sent.chosen){
      // Transfer ownership to the submitted message. Do not delete server data:
      // a reconnect replays the original request with exactly these IDs.
      if(!live(e))continue;
      e.alive=false;e.state='sent';e.row.remove();e.group.splice(e.group.indexOf(e),1);e.preview='';
      if(previewEntry===e)closePreview();
    }
    submissions.delete(request.request_id);
    if(!entries.length){notice.hidden=true;notice.textContent='';}changed();return true;
  }
  function releaseSubmission(id){submissions.delete(id);}
  // Leaving the page disposes browser buffers, never deletes durable context.
  window.addEventListener('pagehide',()=>{selection++;for(const group of groups.values())for(const e of group){e.uploadController?.abort();e.file=null;e.preview='';}submissions.clear();});
  window.localmindAttachments={add,reset,restore,setConversation,adoptConversation,clearConversation,contextIds,hasPending,beginSubmission,releaseSubmission,acknowledge,limits:LIMITS,configure:options=>{requestOverride=options?.request||null;sessionOverride=options?.getSession||null;},snapshot:()=>entries.map(e=>({id:e.id,serverId:e.serverId,state:e.state,hasFile:Boolean(e.file)}))};
})();
