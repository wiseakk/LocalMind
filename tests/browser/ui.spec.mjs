import { test, expect } from '@playwright/test';

const externalAttempts=new WeakMap();
test.beforeEach(async({page,baseURL})=>{
  await page.route('**/api/setup',route=>route.fulfill({json:{voice:[{kind:'asr',state:'ready'},{kind:'tts',state:'ready'}],ollama:{state:'ready',active_installed:true}}}));
  const attempts=[];externalAttempts.set(page,attempts);const origin=new URL(baseURL).origin;
  await page.route('**/*',route=>{
    const url=route.request().url();
    if(/^https?:/.test(url)&&new URL(url).origin!==origin){attempts.push(url);return route.abort('blockedbyclient');}
    return route.continue();
  });
});
test.afterEach(async({page},testInfo)=>{
  const attempts=externalAttempts.get(page)||[];
  await testInfo.attach('external-request-attempts',{body:JSON.stringify(attempts),contentType:'application/json'});
  expect(attempts).toEqual([]);
});

async function fakeInfo(page) {
  await page.route('**/api/info',route=>route.fulfill({json:{server_instance:'test-instance',demo:true,model:'qwen3:4b',devices:[{name:'Настольная лампа',state:false}],voice:{voices:[]}}}));
}

test('offline rendering, math, XSS and external-resource refusal',async({page,baseURL})=>{
  await fakeInfo(page);const external=[];
  page.on('request',r=>{if(new URL(r.url()).origin!==new URL(baseURL).origin) external.push(r.url())});
  await page.goto('/');
  await page.evaluate(()=>{
    const target=document.createElement('div');target.id='render-fixture';document.querySelector('#thread').append(target);
    renderLocalMindMessage(target,'# Заголовок\n\n- Один\n- Два\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```js\nconst price="$5";\n```\n\n\\(x^2\\)\n\n\\[y=2\\]\n\n$$z=3$$\n\n$5 и $10\n\n<img src="https://example.com/pixel" onerror="window.xss=1"><script>window.xss=1</script>[bad](javascript:alert(1))');
  });
  await expect(page.locator('#render-fixture .katex')).toHaveCount(3);
  await expect(page.locator('#render-fixture table')).toHaveCount(1);
  await expect(page.locator('#render-fixture li')).toHaveCount(2);
  await expect(page.locator('#render-fixture pre code')).toContainText('const price="$5";');
  await expect(page.locator('#render-fixture')).toContainText('$5 и $10');
  expect(await page.locator('#render-fixture img, #render-fixture script').count()).toBe(0);
  expect(await page.evaluate(()=>window.xss)).toBeUndefined();expect(external).toEqual([]);
});

test('transcript remains an editable draft until explicit submit; repeated enter sends once',async({page})=>{
  await fakeInfo(page);await page.goto('/');let calls=0;
  await page.route('**/api/chat/stream',async route=>{calls++;
    await new Promise(r=>setTimeout(r,300));
    const data={answer:'Ответ',engine:'rules',actions:[],action_results:[],action_ms:0,llm_ms:0};
    await route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'status',data})+'\n'+JSON.stringify({type:'final',data})+'\n'});
  });
  await page.evaluate(()=>stageTranscript({text:'Открой блакнот'}));
  await expect(page.locator('#message')).toHaveValue('Открой блакнот');
  await expect(page.locator('.bubble.me')).toHaveCount(0);expect(calls).toBe(0);
  await page.locator('#message').fill('Открой блокнот');
  await page.locator('#message').press('Enter');await page.locator('#message').press('Enter');
  await expect(page.locator('.bubble.me')).toHaveCount(1);
  await expect(page.locator('#send')).toBeEnabled();expect(calls).toBe(1);
});

test('real DEMO endpoint displays authoritative status with composer disabled',async({page})=>{
  await page.goto('/');
  // Real endpoint uses a disabled composer so deterministic server integration is exercised.
  await page.locator('#modelsOpen').click();await page.locator('#composeActions').uncheck();await page.keyboard.press('Escape');
  await page.locator('#message').fill('Включи лампу');await page.locator('#message').press('Enter');
  await expect(page.locator('.action-chip')).toContainText('ДЕМО');
  await expect(page.locator('#send')).toBeEnabled();
});

for(const zoom of [1,1.25,1.4,1.5])test(`desktop CSS scale stress ${zoom*100}% and keyboard dialogs`,async({page})=>{
  await fakeInfo(page);await page.goto('/');
  await page.evaluate(z=>document.documentElement.style.zoom=z,zoom);
  await expect(page.locator('#message')).toBeInViewport();await expect(page.locator('#mic')).toBeInViewport();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.locator('#settingsOpen').focus();await page.keyboard.press('Enter');await expect(page.locator('#settingsDialog')).toBeVisible();
  for(let i=0;i<15;i++)await page.keyboard.press('Tab');
  expect(await page.evaluate(()=>document.querySelector('#settingsDialog').contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Escape');await expect(page.locator('#settingsDialog')).not.toBeVisible();
  await page.screenshot({path:`test-results/desktop-${zoom}.png`,fullPage:true});
});

test('clause speech enters playback before final and interruption discards queued audio',async({page})=>{
  await fakeInfo(page);await page.goto('/');
  await page.evaluate(()=>{
    const original=window.fetch;window.voiceCalls=[];window.played=[];window.paused=[];
    window.Audio=class {constructor(url){this.url=url}async play(){window.played.push(this)}pause(){window.paused.push(this)}};
    window.fetch=async(url,options)=>{
      if(url==='/api/tts'){window.voiceCalls.push(JSON.parse(options.body));return new Response(new Blob(['mock local WAV']));}
      if(url==='/api/tts/cancel')return Response.json({ok:true});
      if(url==='/api/chat/stream')return new Response(new ReadableStream({start(controller){
        controller.enqueue(new TextEncoder().encode(JSON.stringify({type:'status',data:{action_results:[]}})+'\n'));
        controller.enqueue(new TextEncoder().encode(JSON.stringify({type:'delta',sequence:1,text:'Первая фраза уже готова для речи. '})+'\n'));
        window.finishVoiceReply=()=>{
          controller.enqueue(new TextEncoder().encode(JSON.stringify({type:'delta',sequence:2,text:'Вторая фраза продолжает ответ.'})+'\n'));
          controller.enqueue(new TextEncoder().encode(JSON.stringify({type:'final',data:{answer:'Первая фраза уже готова для речи. Вторая фраза продолжает ответ.',engine:'test',action_results:[]}})+'\n'));controller.close();
        };
      }}));
      return original(url,options);
    };
    document.querySelector('#speak').checked=true;sendText('Объясни это');
  });
  await expect.poll(()=>page.evaluate(()=>window.played.length)).toBe(1);
  await expect(page.locator('#send')).toBeDisabled();
  expect(await page.evaluate(()=>window.voiceCalls.length)).toBe(1);
  await page.locator('#stopAudio').click();await page.evaluate(()=>window.finishVoiceReply());
  await expect(page.locator('#send')).toBeEnabled();
  expect(await page.evaluate(()=>window.played.length)).toBe(1);
  expect(await page.evaluate(()=>window.paused.length)).toBe(1);
});

test('phone layout and reduced motion',async({page})=>{
  await fakeInfo(page);await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/');
  await expect(page.locator('#mic')).toBeInViewport();
  expect(await page.locator('.welcome').evaluate(e=>getComputedStyle(e).animationName)).toBe('none');
  await page.locator('#sidebarToggle').click();await expect(page.locator('#settingsOpen')).toBeInViewport();
  await page.locator('#settingsOpen').click();await expect(page.locator('#settingsDialog')).toBeVisible();
  await page.keyboard.press('Escape');await page.screenshot({path:'test-results/phone.png',fullPage:true});
});
