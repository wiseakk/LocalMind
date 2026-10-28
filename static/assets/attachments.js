/* Browser-memory attachment prototype. No upload, ingestion, storage or model context. */
(() => {
  'use strict';
  const get=id=>document.getElementById(id),list=get('attachmentList'),notice=get('attachmentNotice');
  const LIMITS=Object.freeze({count:8,file:10*1024*1024,total:40*1024*1024,imagePixels:16000000});
  const types={pdf:['application/pdf'],txt:['text/plain'],md:['text/plain','text/markdown','text/x-markdown'],docx:['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],csv:['text/csv','application/csv','text/plain','application/vnd.ms-excel'],png:['image/png'],jpg:['image/jpeg'],jpeg:['image/jpeg'],webp:['image/webp']};
  let entries=[],serial=0,epoch=0;
  const labels={preparing:'Подготовка в браузере…',ready:'Готово локально · не в контексте ИИ',indexing:'Превью: индексация · без чтения текста',processing:'Превью: обработка · без вызова модели',error:'Ошибка',removing:'Удаление…'};
  const cleanName=name=>name.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g,'').slice(0,160);
  const live=entry=>entry.epoch===epoch&&entries.includes(entry)&&entry.state!=='removing';
  const label=entry=>get('showFilenames').checked?cleanName(entry.file?.name||entry.name):'Вложение '+entry.number+' · '+entry.ext.toUpperCase();
  function say(text){notice.hidden=false;notice.textContent=text;}
  function sync(){window.localmindScene?.setFiles(entries.filter(e=>e.state!=='error'&&e.state!=='removing').map(e=>({id:e.id,label:label(e)})));}
  function status(entry,state,error){if(!live(entry))return;entry.state=state;entry.row.dataset.state=state;entry.row.classList.toggle('error',state==='error');entry.status.textContent=error||labels[state];entry.demo.hidden=state!=='ready';sync();}
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
  async function prepare(entry){
    try{
      if(['png','jpg','jpeg','webp'].includes(entry.ext)){
        const bytes=await read(entry.file.slice(0,65536));if(!live(entry))return;
        const [w,h]=dimensions(bytes,entry.ext);
        if(!w||!h||w*h>LIMITS.imagePixels||w>8192||h>8192)throw Error('Изображение: максимум 16 Мп и 8192 px по стороне');
        if(typeof createImageBitmap!=='function')throw Error('Предпросмотр изображения недоступен в этом браузере');
        const bitmap=await createImageBitmap(entry.file,{resizeWidth:96,resizeHeight:96,resizeQuality:'low'});
        try{
          if(!live(entry))return;
          const preview=document.createElement('canvas');preview.width=96;preview.height=96;preview.setAttribute('aria-label','Предпросмотр выбранного изображения');preview.setAttribute('role','img');
          preview.getContext('2d').drawImage(bitmap,0,0,96,96);entry.row.prepend(preview);
        }finally{bitmap.close();}
      }else{
        // Yield once for responsive preparation. Document bytes are never parsed.
        await Promise.resolve();
      }
      status(entry,'ready');
    }catch(e){status(entry,'error','Не готово: '+e.message);entry.file=null;}
  }
  function remove(entry){
    if(!live(entry))return;
    for(const timer of entry.timers)clearTimeout(timer);
    entry.state='removing';entry.row.dataset.state='removing';entry.status.textContent=labels.removing;entry.row.classList.add('removing');
    entry.file=null;entry.name='';entry.row.querySelector('canvas')?.remove();entry.row.querySelectorAll('button').forEach(b=>b.disabled=true);sync();
    const id=setTimeout(()=>{entry.row.remove();entries=entries.filter(e=>e!==entry);if(!entries.length){notice.hidden=true;notice.textContent='';}},document.documentElement.dataset.reducedMotion==='true'?0:150);entry.timers.push(id);
  }
  function add(files){
    // All batch limits are evaluated before any read/decode. Reject the entire
    // batch on count/aggregate overflow; mixed type errors can be removed one by one.
    const incoming=Array.from(files),active=entries.filter(e=>e.state!=='removing');
    if(incoming.length+active.length>LIMITS.count){say('Не более 8 вложений. Удалите лишние и повторите.');return;}
    const total=incoming.reduce((s,f)=>s+f.size,0)+active.reduce((s,e)=>s+(e.file?.size||0),0);
    if(total>LIMITS.total){say('Общий размер — не более 40 МБ. Файлы не прочитаны.');return;}
    for(const file of incoming){
      const ext=file.name.split('.').pop().toLowerCase();let error='';
      if(!Object.hasOwn(types,ext))error='Этот тип не поддерживается';
      else if(!file.size)error='Пустой файл';
      else if(file.size>LIMITS.file)error='Размер — не более 10 МБ на файл';
      else if(file.type&&!types[ext].includes(file.type.toLowerCase()))error='Тип MIME не совпадает с расширением';
      const entry={id:'attachment-'+(++serial),number:serial,file:error?null:file,name:file.name,ext:ext.slice(0,8),state:'preparing',epoch,timers:[]};
      const row=document.createElement('div');row.className='attachment';row.dataset.id=entry.id;entry.row=row;
      const icon=document.createElement('span');window.localmindIcon?.(icon,'file');
      const info=document.createElement('div');info.className='attachment-info';
      const title=document.createElement('span');title.className='attachment-name';title.textContent=label(entry);entry.title=title;
      const progress=document.createElement('span');progress.className='attachment-state';entry.status=progress;
      const demo=document.createElement('button');demo.type='button';demo.className='preview-button';demo.textContent='Превью обработки';demo.hidden=true;entry.demo=demo;
      demo.addEventListener('click',()=>{
        if(entry.state!=='ready')return;status(entry,'indexing');
        entry.timers.push(setTimeout(()=>status(entry,'processing'),650));
        entry.timers.push(setTimeout(()=>status(entry,'ready'),1400));
      });
      const close=document.createElement('button');close.type='button';close.className='icon-button';close.setAttribute('aria-label','Удалить вложение '+entry.number);window.localmindIcon?.(close,'close');close.addEventListener('click',()=>remove(entry));
      info.append(title,progress,demo);row.append(icon,info,close);list.append(row);entries.push(entry);
      if(error)status(entry,'error',error);else{status(entry,'preparing');prepare(entry);}
    }
    if(incoming.length)say('Только в памяти вкладки · файлы НЕ переданы модели. PDF/TXT/MD/DOCX/CSV/PNG/JPG/WEBP · 8 файлов, 10 МБ каждый, 40 МБ всего.');
  }
  get('attach').addEventListener('click',()=>get('fileInput').click());
  get('fileInput').addEventListener('change',e=>{add(e.target.files);e.target.value='';});
  const zone=get('dropZone');let dragDepth=0;
  function fileDrag(e){return Array.from(e.dataTransfer?.types||[]).includes('Files');}
  zone.addEventListener('dragenter',e=>{if(fileDrag(e)){e.preventDefault();dragDepth++;zone.classList.add('drop-active');}});
  zone.addEventListener('dragover',e=>{if(fileDrag(e)){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
  zone.addEventListener('dragleave',()=>{if(--dragDepth<=0){dragDepth=0;zone.classList.remove('drop-active');}});
  zone.addEventListener('drop',e=>{if(fileDrag(e)){e.preventDefault();dragDepth=0;zone.classList.remove('drop-active');add(e.dataTransfer.files);}});
  // Prevent dropping a file outside the composer from navigating away from chat.
  document.addEventListener('dragover',e=>{if(fileDrag(e))e.preventDefault();});
  document.addEventListener('drop',e=>{if(fileDrag(e))e.preventDefault();});
  get('message').addEventListener('paste',e=>{
    if(e.clipboardData?.files.length){e.preventDefault();add(e.clipboardData.files);}
    // Ordinary text paste retains the browser's native editable behavior.
  });
  get('showFilenames').addEventListener('change',()=>{for(const e of entries)e.title.textContent=label(e);sync();});
  function reset(){epoch++;for(const e of entries){e.file=null;e.name='';e.timers.forEach(clearTimeout);e.row.remove();}entries=[];get('fileInput').value='';notice.hidden=true;notice.textContent='';zone.classList.remove('drop-active');dragDepth=0;sync();}
  window.addEventListener('pagehide',reset);
  window.localmindAttachments={add,reset,limits:LIMITS,snapshot:()=>entries.map(e=>({id:e.id,state:e.state,hasFile:Boolean(e.file)}))};
})();
