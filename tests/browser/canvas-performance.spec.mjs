import {test,expect} from '@playwright/test';

test('Canvas caches text and glows, exposes opt-in timing and suspends the closed drawer',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/');
  await page.evaluate(()=>document.fonts.ready);
  await expect(page.locator('.canvas-diagnostics')).toHaveCount(0);
  await page.evaluate(()=>{
    localmindScene.observeApps(Array.from({length:10},(_,i)=>({id:String(i),name:'Узел '+i})));
    localmindScene.observeConversation();
  });
  await page.waitForTimeout(200);
  await page.evaluate(()=>{
    const proto=CanvasRenderingContext2D.prototype;
    window.textCalls=0;window.blurCalls=0;
    const fill=proto.fillText;proto.fillText=function(...args){window.textCalls++;return fill.apply(this,args)};
    const blur=Object.getOwnPropertyDescriptor(proto,'shadowBlur');
    Object.defineProperty(proto,'shadowBlur',{...blur,set(value){if(value)window.blurCalls++;blur.set.call(this,value)}});
    window.initialFrames=localmindScene.stats().frames;
  });
  await expect.poll(()=>page.evaluate(()=>localmindScene.stats().frames-window.initialFrames)).toBeGreaterThan(5);
  expect(await page.evaluate(()=>({text:window.textCalls,blur:window.blurCalls}))).toEqual({text:0,blur:0});
  const stats=await page.evaluate(()=>{localmindScene.setDiagnostics(true);return localmindScene.stats()});
  expect(stats.dpr).toBeLessThanOrEqual(1.5);expect(stats.pixels).toBeLessThanOrEqual(1600000);
  await expect(page.locator('.canvas-diagnostics')).toContainText('FPS');
  await page.setViewportSize({width:1000,height:700});
  await expect.poll(()=>page.evaluate(()=>localmindScene.stats().visible)).toBe(false);
  const stopped=await page.evaluate(()=>localmindScene.stats().frames);await page.waitForTimeout(150);
  expect(await page.evaluate(()=>localmindScene.stats().frames)).toBe(stopped);
  await expect(page.locator('.canvas-diagnostics')).toContainText('приостановлено');
  await page.locator('#graphToggle').click();
  await expect.poll(()=>page.evaluate(()=>localmindScene.stats().frames)).toBeGreaterThan(stopped);
  await page.evaluate(()=>localmindScene.setDiagnostics(false));await expect(page.locator('.canvas-diagnostics')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('Canvas reacts to dragging at CSS zoom while streaming leaves the draft editable',async({page})=>{
  let finish;const pending=new Promise(resolve=>finish=resolve);
  await page.route('**/api/chat/stream',async r=>{await pending;await r.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'final',data:{answer:'Тестовый ответ',engine:'mock',action_results:[]}})+'\n'})});
  await page.goto('/');await page.evaluate(()=>document.documentElement.style.zoom=1.4);
  await page.locator('#message').fill('Проверка');await page.locator('#message').press('Enter');
  await expect(page.locator('#send')).toBeDisabled();
  await page.locator('#message').pressSequentially('Новый черновик');await expect(page.locator('#message')).toHaveValue('Новый черновик');
  await page.locator('#graphToggle').click();
  await page.evaluate(()=>{
    const ctx=document.querySelector('#constellation').getContext('2d'),arc=ctx.arc;
    ctx.arc=function(x,y,r,...rest){if(r>=7&&r<9)window.rootPosition={x,y};return arc.call(this,x,y,r,...rest)};
  });
  await expect.poll(()=>page.evaluate(()=>Boolean(window.rootPosition))).toBe(true);
  const before=await page.evaluate(()=>window.rootPosition);
  const b=await page.locator('#constellation').boundingBox();
  await page.mouse.move(b.x+b.width*.5,b.y+b.height*.47);await page.mouse.down();
  await page.mouse.move(b.x+b.width*.65,b.y+b.height*.55,{steps:12});await page.mouse.up();
  await expect.poll(()=>page.evaluate(p=>Math.hypot(rootPosition.x-p.x,rootPosition.y-p.y),before)).toBeGreaterThan(20);
  await expect(page.locator('#nodeTitle')).toHaveText('LocalMind');
  await page.locator('#centerGraph').click();finish();await expect(page.locator('#send')).toBeEnabled();await page.keyboard.press('Escape');
  await expect(page.locator('#message')).toHaveValue('Новый черновик');
});
