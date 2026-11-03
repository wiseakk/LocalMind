/* Model metadata is always text, never markup or an executable source. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const unknown = value => value ?? 'неизвестно';
  let activeSelection = '';
  const bytes = value => typeof value === 'number' ? `${(value / 1073741824).toFixed(2)} GiB` : 'неизвестно';
  async function api(path, body) {
    const response = await fetch('/api/models' + path, {method: body ? 'POST' : 'GET',
      headers: {'Content-Type': 'application/json', 'X-LocalMind-Key': $('key').value},
      ...(body ? {body: JSON.stringify(body)} : {})});
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Некорректный запрос');
    return data;
  }
  function observe(data) {
    window.localmindModels.lastModel = data.actual_model || (data.metrics || String(data.engine).startsWith('ollama') ? 'Фактическая модель неизвестна' : 'Модель не использовалась');
    $('model').textContent = window.localmindModels.lastModel;
    const m = data.metrics || {};
    $('modelTelemetry').textContent = `Последний ответ: ${window.localmindModels.lastModel}\n` +
      `Токенов/с: ${unknown(m.tokens_per_second)} · загрузка: ${unknown(m.load_ms)} мс\n` +
      `Ollama: ${unknown(m.ollama_ms)} мс · приложение: ${unknown(data.latency_ms)} мс`;
  }
  async function refresh() {
    try {
      const data = await api(''), select = $('modelSelect');
      select.replaceChildren();
      for (const row of data.models || []) {
        const option = document.createElement('option'); option.value = row.name;
        option.textContent = row.name; option.disabled = row.selectable === false;
        select.append(option);
      }
      activeSelection = data.active || data.default || '';
      select.value = activeSelection;
      for (const id of ['benchmarkModelA','benchmarkModelB']) {
        const chooser = $(id); if (!chooser) continue;
        const previous = chooser.value; chooser.replaceChildren();
        const empty = document.createElement('option'); empty.value = ''; empty.textContent = 'Не сравнивать';
        if (id === 'benchmarkModelB') chooser.append(empty);
        for (const row of data.models || []) {
          if (row.selectable === false) continue;
          const option = document.createElement('option'); option.value = row.name; option.textContent = row.name; chooser.append(option);
        }
        chooser.value = previous || (id === 'benchmarkModelA' ? data.active || data.default : '');
      }
      if (!select.value) {
        const missing = document.createElement('option'); missing.value = '';
        missing.textContent = 'Модель недоступна — выберите установленную';
        missing.selected = true; select.prepend(missing);
      }
      $('modelStatus').textContent = `Выбрана сервером: ${data.active || data.default}. Смена только после проверки. Загрузка в каталогах — только по кнопке.`;
      const list = $('installedModels'); list.replaceChildren();
      for (const row of data.models || []) {
        const item = document.createElement('pre'); item.className = 'model-card mini';
        item.textContent = `${row.name}\nСемейство: ${unknown(row.details?.family)} · параметры: ${unknown(row.details?.parameter_size)} · ${unknown(row.details?.quantization_level)}\n` +
          `Размер: ${bytes(row.size)} · возможности: ${(row.capabilities || []).join(', ') || 'неизвестно'}\n` +
          `Контекст max / загружен: ${unknown(row.max_context)} / ${unknown(row.context_length)}\n` +
          `Размещение /api/ps: ${unknown(row.placement)} · VRAM модели: ${bytes(row.size_vram)}${row.warning ? '\n' + row.warning : ''}`;
        const card=document.createElement('article');card.className='model-card';
        const label=document.createElement('p');label.textContent=row.name+' · '+bytes(row.size)+(row.name===activeSelection?' · Активная':'');
        item.classList.add('expert-only');card.append(label,item);list.append(card);
      }
      if (data.last_response) observe(data.last_response);
      await refreshHardware();
    } catch (error) { $('modelStatus').textContent = error.message; }
  }
  async function refreshHardware() {
    let box=$('hardwareTelemetry');
    if(!box){box=document.createElement('pre');box.className='mini model-card expert-only';box.id='hardwareTelemetry';$('installedModels').append(box);}
    try {
      const h = await api('/hardware');
      box.textContent = `CPU: ${unknown(h.cpu)} · ${unknown(h.cpu_percent)}%\nRAM всего / доступно: ${bytes(h.ram_total)} / ${bytes(h.ram_available)}\n` +
        (h.gpus || []).map(g => `${unknown(g.name)}: VRAM всего / занято ${bytes(g.vram_total)} / ${bytes(g.vram_used)} · GPU ${unknown(g.utilization)}%`).join('\n') +
        `\nNVIDIA: ${unknown(h.gpu_status)}. Память устройства включает другие приложения.`;
    } catch (error) {box.textContent='Показатели оборудования недоступны: '+error.message;}
  }
  $('refreshModels').addEventListener('click', refresh);
  $('activateModel').addEventListener('click', async event => {
    event.target.disabled = true; $('modelStatus').textContent = 'Проверяем локальную генерацию…';
    try { await api('/select', {model: $('modelSelect').value}); await refresh(); }
    catch (error) { $('modelSelect').value = activeSelection; $('modelStatus').textContent = error.message + ' Серверный выбор: ' + (activeSelection || 'неизвестно'); }
    finally { event.target.disabled = false; }
  });
  window.localmindModels = {refresh, observe, api, bytes};

  // Discovery is intentional: no Hub/registry request on app startup.
  const root = document.createElement('section'); root.className = 'side-section'; root.id='modelCatalog';
  $('sessionControls').before(root);
  const title = document.createElement('h3'); title.textContent = 'Каталог и загрузки';
  const notice = document.createElement('p'); notice.className = 'mini';
  notice.textContent = 'Поиск и просмотр HF обращаются к Hugging Face. Файлы загружает только локальный Ollama по вашей кнопке. Закрытые/gated модели недоступны. После установки активная модель не меняется.';
  const registry = document.createElement('button'); registry.className = 'secondary';
  registry.textContent = 'Ollama Registry'; registry.id = 'openRegistry';
  const query = document.createElement('input'); query.placeholder = 'Hugging Face: название GGUF';
  query.maxLength = 100; query.setAttribute('aria-label', 'Поиск GGUF на Hugging Face'); query.id = 'hubQuery';
  const search = document.createElement('button'); search.textContent = 'Искать HF'; search.className = 'secondary'; search.id = 'searchHub';
  const output = document.createElement('div'); output.id = 'catalogModels';
  const status = document.createElement('p'); status.className = 'mini'; status.setAttribute('role', 'status'); status.id = 'catalogStatus';
  const jobs = document.createElement('div'); jobs.id = 'modelDownloads';
  const refreshJobs = document.createElement('button'); refreshJobs.textContent = 'Обновить загрузки'; refreshJobs.className = 'secondary';
  root.append(title, notice, registry, query, search, status, output, refreshJobs, jobs);
  function capabilities(value) { return Array.isArray(value) ? value.join(', ') : Object.entries(value || {}).map(([k,v]) => `${k}: ${v}`).join(', '); }
  function cards(rows) {
    output.replaceChildren();
    if (!rows.length) { status.textContent = 'Поддерживаемые варианты GGUF не найдены.'; return; }
    const recommended=rows.find(row=>row.recommended)||rows.find(row=>row.compatibility!=='blocked');
    const visibleRows=document.documentElement.dataset.expert==='true'||!recommended?rows:[recommended];
    for (const row of visibleRows) {
      const card = document.createElement('article'); card.className = 'model-card';
      const cardSummary=document.createElement('p');cardSummary.textContent=bytes(row.size)+' · '+(row.compatibility==='blocked'?row.warning:'Подходящий вариант выбран автоматически');card.append(cardSummary);
      const heading = document.createElement('h4'); heading.textContent = row.name;
      const source = document.createElement('p'); source.className = 'mini';
      // Server constructs source URLs; rendering as text keeps metadata inert.
      source.textContent = `Издатель: ${row.publisher} · Лицензия: ${row.license || 'неизвестно'}`;
      const info = document.createElement('pre'); info.className = 'mini expert-only';
      const m = row.memory || {};
      info.textContent = `Параметры: ${unknown(row.parameters)} · ${row.quantization} · архитектура: ${unknown(row.architecture)}\n` +
        `Загрузка: ${bytes(row.size)}${row.size_is_estimate ? ' (оценка)' : ''} · диск: ${bytes(row.disk?.free)} (${row.disk?.status})\n` +
        `Контекст max: ${unknown(row.max_context)} · рекомендация: ${row.recommended_context}, выбран: ${m.context}\n` +
        `RAM min / rec: ${bytes(m.ram_minimum)} / ${bytes(m.ram_recommended)}\nVRAM min / rec: ${bytes(m.vram_minimum)} / ${bytes(m.vram_recommended)}\n` +
        `KV cache: ${bytes(m.kv_cache)} · runtime: ${bytes(m.runtime_overhead)} · 12GB fit: ${unknown(m.target_12gb_fit)}\n${m.assumptions}\n` +
        `Возможности: ${capabilities(row.capabilities)}\nСовместимость: ${row.compatibility} · Ollama ${unknown(row.ollama_version)}\n${row.warning}\n${row.benchmark_notice}`;
      const consent = document.createElement('label'); consent.className = 'check';
      const accept = document.createElement('input'); accept.type = 'checkbox';
      consent.append(accept, document.createTextNode('Проверил(а) лицензию и разрешаю загрузить этот вариант'));
      const diskConsent = document.createElement('label'); diskConsent.className = 'check';
      const diskAccept = document.createElement('input'); diskAccept.type = 'checkbox';
      diskConsent.append(diskAccept, document.createTextNode('Свободное место не удалось проверить. Разрешаю начать загрузку с этим предупреждением'));
      const pull = document.createElement('button'); pull.className = 'secondary'; pull.textContent = 'Установить';
      pull.disabled = row.compatibility === 'blocked';
      pull.addEventListener('click', async () => {
        pull.disabled = true;
        try {
          await api('/downloads', {source: row.source, identity: row.id, quantization: row.quantization,
            context: Number($('contextTokens').value), accept_license: accept.checked, acknowledge_unknown_disk: diskAccept.checked, fingerprint: row.fingerprint});
          status.textContent = 'Загрузка начата. Активная модель сохранена.'; await loadJobs();
        } catch (error) { status.textContent = error.message; }
        finally { pull.disabled = row.compatibility === 'blocked'; }
      });
      card.append(heading, source, info, consent, diskConsent, pull); output.append(card);
    }
  }
  async function loadJobs() {
    try {
      const data = await api('/downloads'); jobs.replaceChildren();
      for (const job of data.jobs || []) {
        const item = document.createElement('div'); item.className = 'model-card mini';
        const text = document.createElement('pre');
        text.textContent = `${job.model} · ${job.status}\n` + Object.entries(job.layers || {}).map(([digest, layer]) =>
          `${digest.slice(0, 20)}: ${bytes(layer.completed)} / ${bytes(layer.total)} (${(100 * layer.completed / layer.total).toFixed(1)}%)`).join('\n') +
          (job.error ? '\n' + job.error : '') + '\nОтмена закрывает поток; остановка внутри Ollama может быть не подтверждена.';
        item.append(text);
        if (['starting','downloading','verifying'].includes(job.status)) {
          const cancel = document.createElement('button'); cancel.textContent = 'Отменить поток'; cancel.className = 'secondary';
          cancel.addEventListener('click', async () => { try { await api('/downloads/' + job.id + '/cancel', {}); await loadJobs(); } catch (e) { status.textContent = e.message; } });
          item.append(cancel);
        }
        jobs.append(item);
      }
      return (data.jobs || []).some(j => ['starting','downloading','verifying','cancelling'].includes(j.status));
    } catch (e) { status.textContent = e.message; return false; }
  }
  registry.addEventListener('click', async () => {
    try { status.textContent = 'Читаем curated-каталог…'; cards((await api('/catalog?context=' + $('contextTokens').value)).models); status.textContent = 'Совместимость до локальной проверки — оценка.'; }
    catch (e) { status.textContent = e.message; }
  });
  search.addEventListener('click', async () => {
    search.disabled = true; output.replaceChildren(); status.textContent = 'Поиск HF…';
    try {
      const data = await api('/hub/search?query=' + encodeURIComponent(query.value));
      status.textContent = `${data.models.length} репозиториев; выберите для запроса вариантов.`;
      for (const row of data.models) {
        const button = document.createElement('button'); button.className = 'secondary'; button.textContent = row.id + (row.available ? '' : ' · недоступен');
        button.disabled = !row.available;
        button.addEventListener('click', async () => {
          try { status.textContent = 'Читаем GGUF metadata…'; cards((await api('/hub/variants?repo=' + encodeURIComponent(row.id) + '&context=' + $('contextTokens').value)).models); }
          catch (e) { status.textContent = e.message; }
        }); output.append(button);
      }
    } catch (e) { status.textContent = e.message; }
    finally { search.disabled = false; }
  });
  refreshJobs.addEventListener('click', loadJobs);
  // Poll local job status only while settings are visible, never discover or
  // start/retry a download automatically. Stop timers with the dialog.
  let pollTimer;
  async function poll() {
    if (!$('settingsDialog').open || document.hidden) return;
    await loadJobs(); await refreshHardware(); pollTimer = setTimeout(poll, 2500);
  }
  $('settingsOpen').addEventListener('click', () => { clearTimeout(pollTimer); pollTimer = setTimeout(poll, 100); });
  $('settingsDialog').addEventListener('close', () => clearTimeout(pollTimer));

  const benchmarkRoot = document.createElement('section'); benchmarkRoot.className = 'side-section expert-only';
  const benchTitle = document.createElement('h3'); benchTitle.textContent = 'Локальный тест моделей';
  const benchNotice = document.createElement('p'); benchNotice.className = 'mini';
  benchNotice.textContent = '12 фиксированных русских заданий. Строгие проверки формата/ответа, не общая точность. Две модели получают одинаковые prompts, seed, контекст 4096 и бюджет 256; reasoning выключен в запросе. Инструменты и сгенерированный код не исполняются. Во время теста inference занят. Синтетические ответы сохраняются локально отдельно от чата; активная модель не меняется.';
  function chooser(id, caption) {
    const label = document.createElement('label'); label.textContent = caption;
    const select = document.createElement('select'); select.id = id; label.append(select); return label;
  }
  const testButton = document.createElement('button'); testButton.textContent = 'Тестировать / сравнить'; testButton.id = 'testModels'; testButton.className = 'secondary';
  const historyButton = document.createElement('button'); historyButton.textContent = 'Результаты тестов'; historyButton.className = 'secondary';
  const benchStatus = document.createElement('p'); benchStatus.className = 'mini'; benchStatus.id = 'benchmarkStatus'; benchStatus.setAttribute('role','status');
  const results = document.createElement('div'); results.id = 'benchmarkResults';
  benchmarkRoot.append(benchTitle, benchNotice, chooser('benchmarkModelA','Модель для теста'), chooser('benchmarkModelB','Сравнить со второй моделью (необязательно)'), testButton, historyButton, benchStatus, results);
  $('sessionControls').before(benchmarkRoot);
  let benchmarkId = null, benchTimer;
  async function showBenchmark(id) {
    clearTimeout(benchTimer);
    try {
      const job = await api('/benchmarks/' + id); benchmarkId = id;
      benchStatus.textContent = `${job.status} · ${job.progress?.completed ?? '?'} / ${job.progress?.total ?? '?'} · ${job.suite_version}\n${job.suite_hash}\n${job.error || ''}`;
      results.replaceChildren();
      if (job.status !== 'completed') {
        const incomplete = document.createElement('p'); incomplete.className = 'notice';
        incomplete.textContent = 'Полное сравнение не завершено. Частичные результаты не устанавливают победителя.'; results.append(incomplete);
      }
      const modes = new Set((job.models || []).map(model => model.placement?.mode).filter(Boolean));
      if (modes.size > 1 || modes.has('unknown')) {
        const placementNotice = document.createElement('p'); placementNotice.className = 'notice';
        placementNotice.textContent = 'Размещение моделей различается или неизвестно. Скорость не устанавливает победителя; учитывайте CPU/GPU и другие workloads.'; results.append(placementNotice);
      }
      for (const model of job.models || []) {
        const card = document.createElement('article'); card.className = 'model-card';

        const title = document.createElement('h4'); title.textContent = model.requested_model;
        const details = document.createElement('pre'); details.className = 'mini';
        details.textContent = `Digest: ${unknown(model.digest)} · ${unknown(model.quantization)}\nЗавершён: ${model.complete}\n` +
          `Размещение после прогона: ${unknown(model.placement?.mode)} · VRAM: ${bytes(model.placement?.size_vram)} · контекст: ${unknown(model.placement?.context)} · источник: ${unknown(model.placement?.source)}\n${JSON.stringify(job.settings)}\n` +
          Object.entries(model.scores || {}).filter(([name]) => name !== 'performance').map(([name, value]) =>
            `${name}: ${value.total ? `${value.passed} / ${value.total}, измерено ${value.measured}` : 'N/A'} · ${value.method}`).join('\n') +
          '\nПроизводительность отдельно: ' + JSON.stringify(model.scores?.performance) + '\n' + (job.method || '');
        const answers = document.createElement('details'), summary = document.createElement('summary'), text = document.createElement('pre');
        summary.textContent = 'Задания, фактические ответы, ошибки и метрики'; text.className = 'mini'; text.textContent = JSON.stringify(model.results,null,2); answers.append(summary,text);
        const ratingLabel = document.createElement('label'); ratingLabel.textContent = 'Мой ручной рейтинг (отдельно от проверок)';
        const rating = document.createElement('select');
        for (let i=0;i<=5;i++) { const option=document.createElement('option'); option.value=String(i); option.textContent=i?String(i):'Не оценено'; rating.append(option); }
        rating.value = String(job.manual_ratings?.[model.requested_model] || 0);
        rating.disabled = job.status === 'running';
        rating.addEventListener('change', async () => { if (!Number(rating.value)) return; try { await api('/benchmarks/' + id + '/rating',{model:model.requested_model,rating:Number(rating.value)}); benchStatus.textContent='Ручной рейтинг сохранён отдельно.'; } catch(e) { benchStatus.textContent=e.message; } });
        ratingLabel.append(rating); card.append(title,details,answers,ratingLabel); results.append(card);
      }
      if (job.current_model) {
        const partial = document.createElement('details'), summary = document.createElement('summary'), content = document.createElement('pre');
        summary.textContent = 'Текущая модель: частичные результаты'; content.textContent = JSON.stringify(job.current_model,null,2);
        partial.append(summary,content); results.append(partial);
      }
      if (job.status === 'running') {
        const cancel = document.createElement('button'); cancel.textContent='Прервать после текущего задания'; cancel.className='secondary';
        cancel.addEventListener('click', async () => {try {const data=await api('/benchmarks/'+id+'/cancel',{});benchStatus.textContent=data.notice;}catch(e){benchStatus.textContent=e.message;}}); results.append(cancel);
        if ($('settingsDialog').open && !document.hidden) benchTimer=setTimeout(()=>showBenchmark(id),1500);
      }
    } catch(e) { benchStatus.textContent=e.message; }
  }
  testButton.addEventListener('click', async () => {
    testButton.disabled=true;
    try { const models=[$('benchmarkModelA').value,$('benchmarkModelB').value].filter(Boolean); const data=await api('/benchmarks',{models}); await showBenchmark(data.id); }
    catch(e) {benchStatus.textContent=e.message;}
    finally {testButton.disabled=false;}
  });
  async function benchmarkHistory() {
    try {
      const data=await api('/benchmarks'); results.replaceChildren();
      for(const job of data.jobs || []) { const button=document.createElement('button');button.className='secondary';button.textContent=`${job.id.slice(0,8)} · ${(job.requested_models || []).join(' / ')} · ${job.status}`;button.addEventListener('click',()=>showBenchmark(job.id));results.append(button); }
      if(!data.jobs?.length)benchStatus.textContent='Пока нет локальных тестов.';
    }catch(e){benchStatus.textContent=e.message;}
  }
  historyButton.addEventListener('click', benchmarkHistory);
  $('settingsDialog').addEventListener('close',()=>clearTimeout(benchTimer));
  $('settingsOpen').addEventListener('click',()=>{if(benchmarkId)showBenchmark(benchmarkId);});
})();
