/* Optional Home Assistant is separate from the explicitly labelled demo lamp. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id),dialog=$('devicesDialog');
  $('devicesTitle').textContent='Умный дом';
  const panel=document.createElement('section');panel.className='side-section';
  const title=document.createElement('h3');title.textContent='Подключить Home Assistant';
  const note=document.createElement('p');note.textContent='Без контроллера доступна только демонстрационная лампа. Реальные устройства никогда не заменяются симуляцией при ошибке.';
  const addressLabel=document.createElement('label'),address=document.createElement('input');address.type='url';address.placeholder='http://192.168.1.20:8123';addressLabel.append('Локальный IP контроллера',address);
  const tokenLabel=document.createElement('label'),token=document.createElement('input');token.type='password';token.autocomplete='off';tokenLabel.append('Токен долгосрочного доступа Home Assistant',token);
  const security=document.createElement('p');security.className='mini';security.textContent='Токен сохраняется через Windows DPAPI для вашей учётной записи. Он передаётся только указанному локальному контроллеру. HTTP в локальной сети не шифрует передачу; для защищённой сети используйте HTTPS с действительным сертификатом.';
  const connect=document.createElement('button');connect.className='secondary';connect.textContent='Подключить и сохранить';
  const discover=document.createElement('button');discover.className='secondary';discover.textContent='Найти устройства';
  const demo=document.createElement('button');demo.className='secondary';demo.textContent='Отключить контроллер · Demo Mode';
  const status=document.createElement('p');status.setAttribute('role','status');status.id='homeStatus';
  const devices=document.createElement('div');devices.id='discoveredDevices';
  panel.append(title,note,addressLabel,tokenLabel,security,connect,discover,demo,status,devices);dialog.append(panel);
  async function api(path,body){const r=await fetch('/api/home'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-LocalMind-Key':$('key').value},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(data.detail||'Подключение недоступно');return data;}
  async function refresh(){try{const data=await api('');address.value=data.origin||'';status.textContent=data.configured?'РЕАЛЬНЫЙ КОНТРОЛЛЕР · '+(data.problem||'подключение сохранено; разрешите устройства отдельно'):data.mode==='REAL'?'Реальный режим задан прежней конфигурацией. Подключите контроллер здесь для управления доступом.':'DEMO MODE · симуляция без оборудования';discover.disabled=!data.configured;demo.disabled=!data.configured;}catch(e){status.textContent=e.message;}}
  connect.onclick=async()=>{connect.disabled=true;status.textContent='Проверяем контроллер…';try{await api('/connect',{origin:address.value,token:token.value});token.value='';devices.replaceChildren();await refresh();}catch(e){status.textContent=e.message;token.value='';}finally{connect.disabled=false;}};
  demo.onclick=async()=>{demo.disabled=true;try{await api('/disconnect',{});devices.replaceChildren();await refresh();}catch(e){status.textContent=e.message;demo.disabled=false;}};
  discover.onclick=async()=>{
    discover.disabled=true;status.textContent='Ищем light и switch на контроллере…';
    try{const data=await api('/devices');devices.replaceChildren();status.textContent='Найдено устройств: '+data.devices.length+'. Обнаружение не даёт разрешения.';
      for(const row of data.devices){const card=document.createElement('div');card.className='model-card';const heading=document.createElement('p');heading.textContent=row.name+' · '+row.domain+' · '+({on:'Включено',off:'Выключено',unavailable:'Не отвечает',unknown:'Состояние неизвестно'}[row.state]||'Состояние неизвестно');
        const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=row.allowed;label.className='check';label.append(check,' Разрешить управление этим устройством');
        check.onchange=async()=>{check.disabled=true;try{await api('/permission',{device_id:row.id,allowed:check.checked,name:row.name});status.textContent=check.checked?'Устройство разрешено':'Разрешение отозвано';}catch(e){check.checked=!check.checked;status.textContent=e.message;}finally{check.disabled=false;}};card.append(heading,label);devices.append(card);}
    }catch(e){status.textContent=e.message;}finally{discover.disabled=false;}
  };
  $('devicesOpen').addEventListener('click',refresh);
})();
