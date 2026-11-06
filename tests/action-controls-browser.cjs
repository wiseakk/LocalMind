/* Isolated rendering with real app.js handlers and synthetic Modrinth windows. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('@playwright/test');
(async()=>{
  const artifacts=path.resolve('.test-artifacts/action-controls');fs.mkdirSync(artifacts,{recursive:true});
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage();await page.route('**/*',route=>route.abort());
    const html=fs.readFileSync('static/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
    await page.route('http://127.0.0.1:8765/',route=>route.fulfill({contentType:'text/html',body:html}));
    await page.goto('http://127.0.0.1:8765/');
    for(const css of ['app.css','desktop.css'])await page.addStyleTag({content:fs.readFileSync('static/assets/'+css,'utf8')});
    await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important}'});
    await page.evaluate(()=>{
      window.LocalMindSpeech=class{start(){}cancel(){}feed(){}};
      window.renderLocalMindMessage=(el,text)=>{el.textContent=text;};
      window.fetch=async(url,options={})=>Response.json(url==='/api/info'?{server_instance:'a'.repeat(32),demo:true,devices:[],voice:{profiles:[],voices:[]}}:
        url==='/api/conversations'?(options.method==='POST'?{conversation_id:'c'.repeat(32),server_instance:'a'.repeat(32)}:{conversations:[]}):{});
    });
    await page.addScriptTag({content:fs.readFileSync('static/assets/app.js','utf8')});
    await page.waitForFunction(()=>window.localmindSession?.get().server_instance);
    await page.evaluate(async()=>{
      await window.localmindSession.ensure();document.querySelector('#welcome').hidden=true;
      const el=bubble('Выберите окно или подтвердите отдельную операцию.', 'assistant');
      renderStatus(el,{conversation_id:'c'.repeat(32),server_instance:'a'.repeat(32),action_results:[
        {action:'apps.focus',success:false,execution_status:'ambiguous',status_text:'Несколько окон Modrinth App.',data:{windows:[1,2,3].map(index=>({
          application:'Modrinth App',title:'Очень длинное название профиля '.repeat(8)+index,window_id:'win-'+String(index).repeat(32)}))}},
        {action:'files.prepare_mutation',success:false,execution_status:'confirmation_required',status_text:'Требуется подтверждение.',data:{
          confirmation_id:'p'.repeat(43),operation:'delete',path:'C:\\Fixture\\'+('LongFolder'.repeat(18))+'\\delete me.txt',
          requires_explicit_confirmation:true,expires_in_seconds:120}}
      ]});
    });
    const reports=[];
    for(const width of [1280,1024,731,550,390,320]){
      await page.setViewportSize({width,height:1100});
      const report=await page.evaluate(()=>{
        const rects=[...document.querySelectorAll('.window-choice,.confirmation-actions button')].map(el=>{
          const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,overflow:el.scrollWidth-el.clientWidth};});
        return {width:innerWidth,rects,overflow:document.documentElement.scrollWidth-innerWidth};
      });
      assert.equal(report.rects.length,5);assert.ok(report.overflow<=1,JSON.stringify(report));
      for(const rect of report.rects){assert.ok(rect.left>=0&&rect.right<=width+1&&rect.height>=44&&rect.overflow<=1,JSON.stringify(report));}
      for(let i=1;i<3;i++)assert.ok(report.rects[i].top>=report.rects[i-1].bottom+6,JSON.stringify(report));
      const [approve,cancel]=report.rects.slice(3);
      assert.ok(cancel.left>=approve.right||cancel.top>=approve.bottom,'confirmation buttons must not overlap');
      reports.push(report);
      if([1280,390].includes(width))await page.screenshot({path:path.join(artifacts,`width-${width}.png`),fullPage:true});
    }
    fs.writeFileSync(path.join(artifacts,'geometry.json'),JSON.stringify(reports,null,2));
    console.log('PASS action controls browser: 6 viewports, no overlapping windows/confirmation buttons');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
