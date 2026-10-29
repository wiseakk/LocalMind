import {test,expect} from '@playwright/test';

const info={server_instance:'constellation-test',demo:true,model:'qwen3:4b',devices:[{id:'desk_light',name:'Настольная лампа',state:false}],voice:{voices:[]}};
test.beforeEach(async({page,baseURL})=>{
  const origin=new URL(baseURL).origin;page.externalAttempts=[];page.uiErrors=[];
  page.on('pageerror',e=>page.uiErrors.push(e.message));
  await page.route('**/*',route=>{
    const url=route.request().url();
    if(/^https?:/.test(url)&&new URL(url).origin!==origin){page.externalAttempts.push(url);return route.abort('blockedbyclient');}
    return route.continue();
  });
  await page.route('**/api/info',r=>r.fulfill({json:info}));
  await page.route('**/api/apps',r=>r.fulfill({json:{apps:[{id:'editor',name:'Редактор',allowed:false,fingerprint:'observed',target:'C:/Test/Editor.exe'}]}}));
  await page.route('**/api/models',r=>r.fulfill({json:{models:[],default:'qwen3:4b'}}));
  await page.route('**/api/retrieval/sources',r=>r.fulfill({json:{sources:[]}}));
});
test.afterEach(async({page},testInfo)=>{
  await testInfo.attach('network',{body:JSON.stringify({external:page.externalAttempts,errors:page.uiErrors}),contentType:'application/json'});
  expect(page.externalAttempts).toEqual([]);expect(page.uiErrors).toEqual([]);
});

test('all interface fonts and assets load locally with external HTTP blocked',async({page})=>{
  const failed=[];page.on('response',r=>{if(r.status()>=400&&!r.url().includes('/api/'))failed.push(r.url());});
  await page.goto('/');
  await page.evaluate(()=>Promise.all([document.fonts.load('14px Onest','Русский текст'),document.fonts.load('32px Unbounded','Своя орбита')]));
  expect(await page.evaluate(()=>document.fonts.check('14px Onest')&&document.fonts.check('32px Unbounded'))).toBe(true);
  expect(failed).toEqual([]);await expect(page.locator('#mode')).toBeVisible();
});

test('graph selection, pointer drag, recenter and keyboard movement',async({page})=>{
  await page.goto('/');await expect(page.locator('#nodeSelect option')).toHaveCount(1);
  await page.evaluate(()=>localmindScene.observeConversation('editor desk_light'));
  await page.locator('#graphToggle').click();
  await expect(page.locator('#nodeSelect option')).toHaveCount(6);
  await page.locator('#nodeSelect').selectOption('app:editor');await expect(page.locator('#nodeDetail')).toContainText('не предоставляет');
  await page.locator('#nodeSelect').press('Alt+ArrowRight');await page.locator('#moveNode').click();
  const box=await page.locator('#constellation').boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height*.47);await page.mouse.down();await page.mouse.move(box.x+box.width*.62,box.y+box.height*.4,{steps:8});await page.mouse.up();
  await expect(page.locator('#nodeTitle')).toHaveText('LocalMind');await page.locator('#centerGraph').click();
  expect(await page.evaluate(()=>localmindScene.stats().nodes)).toBe(6);
  await page.screenshot({path:'test-results/constellation-desktop.png',fullPage:true});
});

test('motion controls suspend idle work, respect OS preference and retain readable content',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>localmindScene.stats().reduced)).toBe(true);
  await page.waitForTimeout(150);const frames=await page.evaluate(()=>localmindScene.stats().frames);await page.waitForTimeout(250);
  expect(await page.evaluate(()=>localmindScene.stats().frames)).toBe(frames);
  await page.locator('#settingsOpen').click();await page.locator('#tab-appearance').click();await page.locator('#lowPerformance').check();
  expect(await page.evaluate(()=>localmindScene.stats().low)).toBe(true);await page.keyboard.press('Escape');
  await expect(page.locator('h1')).toBeVisible();await expect(page.locator('#message')).toBeInViewport();
});

test('documents use local upload, extracted preview, acknowledgement and safe removal',async({page})=>{
  const mutations=[],uploaded=[];let serial=0;
  const conversation='c'.repeat(32),instance=info.server_instance;
  page.on('request',r=>{if(r.method()==='POST')mutations.push(new URL(r.url()).pathname);});
  await page.route('**/api/conversations',r=>r.fulfill({json:{conversation_id:conversation,server_instance:instance}}));
  await page.route('**/api/attachments',r=>{
    const id=String(++serial).padStart(32,'a');uploaded.push(id);
    return r.fulfill({json:{id,name:'private.txt',size:5,characters:5,truncated:false,preview:'local',state:'ready',conversation_id:conversation,server_instance:instance}});
  });
  await page.route('**/api/attachments/remove',r=>r.fulfill({json:{ok:true}}));
  await page.route('**/api/chat/stream',r=>{
    const body=r.request().postDataJSON(),result={answer:'Document fixture answer',engine:'mock',action_results:[],conversation_id:conversation,context_sources:body.attachment_ids.map(id=>({id,name:'private.txt',characters:5,truncated:false}))};
    return r.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'status',data:result})+'\n'+JSON.stringify({type:'final',data:result})+'\n'});
  });
  await page.route('**/api/tts/cancel',r=>r.fulfill({json:{ok:true}}));
  await page.goto('/');await expect(page.locator('#status')).toHaveText('\u0421\u0435\u0440\u0432\u0435\u0440 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0451\u043d');
  await page.locator('#fileInput').setInputFiles([{name:'<private>.txt',mimeType:'text/plain',buffer:Buffer.from('local')},{name:'invalid.exe',mimeType:'application/octet-stream',buffer:Buffer.from('invalid')}]);
  await expect(page.locator('.attachment')).toHaveCount(2);await expect(page.locator('.attachment.error')).toHaveCount(1);
  await expect(page.locator('.attachment').first()).toHaveAttribute('data-state','ready');
  await expect(page.locator('#attachmentList')).not.toContainText('<private>');
  expect(uploaded).toHaveLength(1);expect(await page.evaluate(()=>localmindAttachments.contextIds())).toEqual(uploaded);
  await page.evaluate(()=>{document.querySelector('#speak').checked=false;});
  await page.locator('#message').fill('Describe the attachment');await page.locator('#send').click();await expect(page.locator('#send')).toBeEnabled();
  await expect(page.locator('.attachment').first()).toHaveAttribute('data-state','added');
  await page.locator('#settingsOpen').click();await page.locator('#tab-appearance').click();await page.locator('#showFilenames').check();await page.keyboard.press('Escape');
  await expect(page.locator('.attachment-name').first()).toHaveText('<private>.txt');expect(await page.locator('.attachment-name img').count()).toBe(0);
  await page.locator('.preview-button').first().click();await expect(page.locator('#attachmentPreview')).toBeVisible();await expect(page.locator('#previewText')).toHaveText('local');
  await page.locator('#previewClose').click();await page.locator('.attachment').first().locator('.icon-button').click();await expect(page.locator('.attachment')).toHaveCount(1);
  expect(await page.evaluate(()=>localmindAttachments.contextIds())).toEqual([]);
  await page.evaluate(()=>{
    const transfer=new DataTransfer();transfer.items.add(new File(['drop'],'drop.md',{type:'text/markdown'}));
    document.querySelector('#dropZone').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
    const paste=new DataTransfer();paste.items.add(new File(['paste'],'paste.csv',{type:'text/csv'}));
    document.querySelector('#message').dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:paste}));
  });
  await expect(page.locator('.attachment')).toHaveCount(3);
  await expect.poll(()=>uploaded.length).toBe(3);await expect.poll(()=>page.evaluate(()=>localmindAttachments.hasPending())).toBe(false);
  expect(mutations.every(path=>['/api/conversations','/api/attachments','/api/attachments/remove','/api/chat/stream','/api/tts/cancel'].includes(path))).toBe(true);
});

test('valid raster decodes to Canvas and malformed raster never becomes ready',async({page})=>{
  await page.goto('/');
  await page.locator('#fileInput').setInputFiles([
    {name:'dot.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGPojjn/HwAF4gK2//l6AAAAAABJRU5ErkJggg==','base64')},
    {name:'bad.webp',mimeType:'image/webp',buffer:Buffer.from('not a webp')}
  ]);
  await expect(page.locator('.attachment canvas')).toHaveCount(1);await expect(page.locator('.attachment.error')).toHaveCount(1);
  expect(await page.locator('.attachment img').count()).toBe(0);
});

test('oversized aggregate and count batches are rejected without adding rows',async({page})=>{
  await page.goto('/');
  await page.evaluate(()=>localmindAttachments.add(Array.from({length:9},()=>new File(['x'],'x.txt'))));
  await expect(page.locator('.attachment')).toHaveCount(0);await expect(page.locator('#attachmentNotice')).toContainText('8');
  await page.evaluate(()=>localmindAttachments.add(Array.from({length:5},()=>new File([new Uint8Array(9*1024*1024)],'x.txt'))));
  await expect(page.locator('.attachment')).toHaveCount(0);await expect(page.locator('#attachmentNotice')).toContainText('40');
});

test('microphone denial retains usable text controls',async({page})=>{
  await page.addInitScript(()=>Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:async()=>{throw new DOMException('denied','NotAllowedError');}}}));
  await page.goto('/');await page.locator('#mic').click();await expect(page.locator('#errorDialog')).toBeVisible();
  await page.keyboard.press('Escape');await expect(page.locator('#send')).toBeEnabled();await expect(page.locator('#mic')).toBeEnabled();
  expect(await page.evaluate(()=>localmindScene.stats().mode)).toBe('idle');
});

test('phone graph/navigation, settings keyboard and screenshot',async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.goto('/');
  await expect(page.locator('#mic')).toBeInViewport();await expect(page.locator('#mode')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.locator('#sidebarToggle').click();await page.locator('#graphNav').click();await expect(page.locator('#nodeSelect')).toBeInViewport();
  await page.screenshot({path:'test-results/constellation-phone-graph.png',fullPage:true});
  await page.locator('#sidebarToggle').click();await page.locator('#settingsOpen').click();await page.locator('#tab-model').focus();
  await page.keyboard.press('End');await expect(page.locator('#tab-capabilities')).toHaveAttribute('aria-selected','true');
  await page.keyboard.press('Escape');await expect(page.locator('#sidebarToggle')).toBeFocused();
  await page.locator('#sidebarToggle').click();await page.locator('#chatNav').click();await expect(page.locator('#message')).toBeInViewport();
  await page.screenshot({path:'test-results/constellation-phone.png',fullPage:true});
});

test('real browser zoom keyboard changes layout and preserves composer',async({page,headless})=>{
  test.skip(headless,'Browser chrome zoom requires headed Chromium; CSS scale stress runs separately.');
  await page.goto('/');const start=await page.evaluate(()=>innerWidth);
  await page.keyboard.press('Control+Equal');await page.keyboard.press('Control+Equal');
  await expect.poll(()=>page.evaluate(()=>innerWidth)).toBeLessThan(start);
  await expect(page.locator('#mic')).toBeInViewport();await expect(page.locator('#message')).toBeInViewport();
  await page.keyboard.press('Control+0');
});

test('generation interaction trace (mock stream; no local LLM benchmark)',async({page,context})=>{
  await context.tracing.start({screenshots:true,snapshots:true});
  await page.route('**/api/chat/stream',async route=>{
    await new Promise(resolve=>setTimeout(resolve,800));
    await route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'delta',sequence:1,text:'Локальный тест интерфейса.'})+'\n'+JSON.stringify({type:'final',data:{answer:'Локальный тест интерфейса.',engine:'mock',action_results:[]}})+'\n'});
  });
  await page.goto('/');await page.locator('#message').fill('Проверка');await page.locator('#send').click();
  await expect(page.locator('#graphActivity')).toHaveText('Формируется ответ');await page.locator('#graphToggle').click();await page.locator('#centerGraph').click();
  await expect(page.locator('#send')).toBeEnabled();await context.tracing.stop({path:'test-results/constellation-mock-generation-trace.zip'});
});

test('optional real Ollama generation performance trace',async({page,context},testInfo)=>{
  test.skip(process.env.LOCALMIND_REAL_GENERATION!=='1','Requires explicitly provisioned local Ollama; no model downloads.');
  test.setTimeout(180000);
  await page.unroute('**/api/info');await page.goto('/');
  await expect(page.locator('#status')).toHaveText('Сервер подключён');
  const cdp=await context.newCDPSession(page);
  await cdp.send('Tracing.start',{categories:'devtools.timeline,blink.user_timing',transferMode:'ReturnAsStream'});
  await page.locator('#message').fill('Объясни за три предложения, как работает радуга.');await page.locator('#send').click();
  await page.locator('#graphToggle').click();await page.locator('#centerGraph').click();await expect(page.locator('#send')).toBeEnabled({timeout:125000});
  const completed=new Promise(resolve=>cdp.once('Tracing.tracingComplete',resolve));await cdp.send('Tracing.end');
  const {stream}=await completed;let trace='';
  while(true){const chunk=await cdp.send('IO.read',{handle:stream});trace+=chunk.data;if(chunk.eof)break;}
  await cdp.send('IO.close',{handle:stream});
  await testInfo.attach('real-local-generation-timeline',{body:trace,contentType:'application/json'});
  await page.screenshot({path:'test-results/constellation-real-generation.png',fullPage:true});
  await expect(page.locator('.rendered-message')).not.toContainText('Ответ недоступен');
});
