import {chromium} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';

// CSS zoom is a stress test: viewport units/media queries keep their unzoomed
// dimensions. Reduced viewports separately exercise browser-zoom reflow.
const browser=await chromium.launch();
const results=[];
await mkdir('.test-artifacts/layout',{recursive:true});
try {
  for(const zoom of [1,1.25,1.4]) {
    for(const technique of ['css','viewport']) {
      const page=await browser.newPage({viewport:{width:Math.round(1440/(technique==='viewport'?zoom:1)),height:Math.round(1000/(technique==='viewport'?zoom:1))}});
      await page.goto(process.env.LOCALMIND_TEST_URL||'http://127.0.0.1:8765');
      await page.evaluate(z=>document.documentElement.style.zoom=z,technique==='css'?zoom:1);
      await page.evaluate(()=>document.fonts.ready);
      await page.waitForTimeout(300);
      const layout=await page.evaluate(()=>{
        const selectors=['html','body','.workspace','.main','.stage','.dialogue-column','#conversation','.composer-area','#message','#mic','#skyPanel'];
        return {viewport:{width:innerWidth,height:innerHeight},elements:selectors.map(selector=>{
          const el=document.querySelector(selector),s=getComputedStyle(el),r=el.getBoundingClientRect();
          return {selector,rect:r.toJSON(),height:s.height,minHeight:s.minHeight,overflowX:s.overflowX,overflowY:s.overflowY,display:s.display,flex:s.flex,grid:s.gridTemplateRows,zoom:s.zoom,clientHeight:el.clientHeight,scrollHeight:el.scrollHeight};
        })};
      });
      results.push({zoom,technique,...layout});
      await page.screenshot({path:`.test-artifacts/layout/${technique}-${zoom}.png`});
      for(const selector of ['#message','#mic']) {
        const {rect}=layout.elements.find(e=>e.selector===selector);
        assert(rect.top>=0&&rect.bottom<=layout.viewport.height,`${technique} ${zoom}: ${selector} fully visible`);
      }
      const composerBefore=await page.locator('#message').boundingBox();
      await page.evaluate(()=>{
        const text=document.createElement('p');text.textContent='Проверка независимой прокрутки. '.repeat(1000);
        document.querySelector('#thread').append(text);
        document.querySelector('#conversation').scrollTop=100000;
      });
      assert.deepEqual(await page.locator('#message').boundingBox(),composerBefore,'Conversation scroll must not move composer');
      if(await page.locator('#graphToggle').isVisible()) {
        assert(await page.locator('#skyPanel').evaluate(e=>e.inert),'Closed drawer must leave keyboard navigation');
        await page.locator('#graphToggle').click();
        await page.locator('#nodeSelect').selectOption('assistant');
        assert(await page.locator('#graphToggle').getAttribute('aria-expanded')==='true');
        await page.screenshot({path:`.test-artifacts/layout/drawer-${technique}-${zoom}.png`});
        await page.keyboard.press('Escape');
        assert(await page.locator('#graphToggle').evaluate(e=>e===document.activeElement),'Escape restores drawer opener');
      }
      await page.close();
    }
  }
  for(const viewport of [{width:390,height:600},{width:844,height:390},{width:760,height:560}]) {
    const page=await browser.newPage({viewport});await page.goto(process.env.LOCALMIND_TEST_URL||'http://127.0.0.1:8765');
    for(const selector of ['#message','#mic']) {
      const r=await page.locator(selector).boundingBox();
      assert(r.y>=0&&r.y+r.height<=viewport.height,`${JSON.stringify(viewport)}: ${selector} visible`);
    }
    await page.screenshot({path:`.test-artifacts/layout/compact-${viewport.width}.png`});await page.close();
  }
  await writeFile(process.env.LAYOUT_REPORT||'.test-artifacts/layout/report.json',JSON.stringify(results,null,2));
  console.log(JSON.stringify(results.map(({zoom,technique,elements})=>({zoom,technique,rects:elements.filter(e=>['.workspace','#message','#mic'].includes(e.selector))})),null,2));
} finally {await browser.close();}
