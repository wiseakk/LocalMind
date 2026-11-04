import {test,expect} from '@playwright/test';

test.beforeEach(async({page})=>{
  await page.route('**/api/setup',route=>route.fulfill({json:{voice:[],ollama:{state:'ready',active_installed:true}}}));
  await page.route('**/api/info',route=>route.fulfill({json:{server_instance:'test',demo:true,devices:[],voice:{default_profile:'balanced',profiles:[
    {id:'cpu-fast',model:'small',ready:true},{id:'balanced',model:'small',ready:true},{id:'gpu-quality',model:'medium',ready:false}
  ]}}}));
});

test('light and dark themes cover dialogs, fields and rich text and survive reload',async({page})=>{
  await page.addInitScript(()=>localStorage.setItem('localmind.sttProfile.v1','balanced'));
  await page.goto('/');await expect(page).toHaveTitle('LocalMind');
  await expect(page.locator('#voiceProfile option')).toHaveCount(2);
  await expect(page.locator('#voiceProfile')).toHaveValue('cpu-fast');
  expect(await page.evaluate(()=>localStorage.getItem('localmind.sttProfile.v1'))).toBe('balanced');
  await page.locator('#settingsOpen').click();await page.locator('#tab-appearance').click();
  for(const theme of ['light','dark','light']){
    await page.locator('#theme').selectOption(theme);
    await expect(page.locator('html')).toHaveAttribute('data-theme',theme);
    const result=await page.evaluate(()=>{
      const sample=document.createElement('div');sample.className='rendered-message';sample.innerHTML='<pre><code>example</code></pre><blockquote>Example</blockquote>';document.body.append(sample);
      const style=selector=>{const s=getComputedStyle(document.querySelector(selector));return {background:s.backgroundColor,color:s.color}};
      const values={dialog:style('#settingsDialog'),field:style('#theme'),code:style('.rendered-message pre code'),quote:style('.rendered-message blockquote')};sample.remove();return values;
    });
    for(const value of Object.values(result))expect(value.background).not.toBe(value.color);
    await page.screenshot({path:`test-results/rc2-${theme}-settings.png`});
  }
  await page.reload();await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await page.locator('#settingsOpen').click();await page.locator('#tab-appearance').click();
  await expect(page.locator('#theme')).toHaveValue('light');
});

test('system reduced motion suppresses transitions and animations',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-reduced-motion','true');
  expect(await page.locator('#mic').evaluate(el=>getComputedStyle(el).transitionDuration)).toBe('0s');
  await page.locator('#settingsOpen').click();
  expect(await page.locator('#settingsDialog').evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
});
