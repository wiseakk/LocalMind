/* Optional isolated Chromium geometry check; no server, network or user data. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('@playwright/test');
(async()=>{
  const artifacts=path.resolve('.test-artifacts/access-layout');fs.mkdirSync(artifacts,{recursive:true});
  const browser=await chromium.launch({headless:true});
  try{
    const html=fs.readFileSync('static/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
    const page=await browser.newPage();await page.route('**/*',route=>route.abort());
    await page.setContent(html);
    for(const file of ['static/assets/app.css','static/assets/desktop.css'])await page.addStyleTag({content:fs.readFileSync(file,'utf8')});
    await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important}'});
    await page.evaluate(()=>{
      const dialog=document.querySelector('#accessDialog');dialog.showModal();
      document.querySelector('#accessScopes').textContent='C:\\Users\\Student\\Desktop\\'+'VeryLongFolderName'.repeat(18)+' (чтение, поиск, открытие)';
      document.querySelector('#actionJournal').textContent='C:\\'+'LongAuditPath'.repeat(60);
      for(const name of ['Поиск','Чтение','Открытие документа','Создание','Перезапись','Перемещение','Удаление']){
        const label=document.createElement('label');label.className='check';
        const input=document.createElement('input');input.type='checkbox';label.append(input,name);
        document.querySelector('#accessOperations').append(label);
      }
    });
    const reports=[];
    // Effective CSS viewports also cover a 1024px window at 125% and 140% zoom.
    for(const width of [1280,1024,819,768,731,550,390,320]){
      await page.setViewportSize({width,height:900});
      const geometry=await page.evaluate(()=>{
        const dialog=document.querySelector('#accessDialog'),rect=dialog.getBoundingClientRect();
        const cards=[...document.querySelectorAll('.access-mode')].map(card=>{
          const r=card.getBoundingClientRect(),text=card.querySelector('span').getBoundingClientRect();
          return {height:r.height,width:r.width,textRight:text.right,right:r.right,overflow:card.scrollWidth-card.clientWidth};
        });
        return {width:innerWidth,dialogWidth:rect.width,left:rect.left,right:rect.right,
          overflow:dialog.scrollWidth-dialog.clientWidth,cards,columns:getComputedStyle(document.querySelector('.access-columns')).gridTemplateColumns};
      });
      assert.ok(geometry.left>=0 && geometry.right<=width+1,JSON.stringify(geometry));
      assert.ok(geometry.overflow<=1,JSON.stringify(geometry));
      for(const card of geometry.cards){
        assert.ok(card.textRight<=card.right && card.overflow<=1,JSON.stringify(geometry));
        assert.ok(card.height<230,JSON.stringify(geometry));
      }
      reports.push(geometry);
      if([1280,731,390].includes(width))await page.screenshot({path:path.join(artifacts,`width-${width}.png`)});
    }
    fs.writeFileSync(path.join(artifacts,'geometry.json'),JSON.stringify(reports,null,2));
    console.log('PASS access browser layout: 8 viewports, long paths, card bounds and heights');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
