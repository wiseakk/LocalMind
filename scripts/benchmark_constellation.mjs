import {chromium} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {resolve} from 'node:path';
const exec=promisify(execFile),out=process.env.CONSTELLATION_BENCH_OUT||'.test-artifacts/canvas-after';
const duration=Number(process.env.CONSTELLATION_BENCH_MS||6000);
const zoomMode='native';
if(!Number.isFinite(duration)||duration<1000||duration>60000)throw new Error('Sample duration must be 1000–60000 ms');
const baseline=process.env.CONSTELLATION_BASE_REF;
if(baseline&&!/^[a-f0-9]{7,40}$/.test(baseline))throw new Error('Baseline must be a commit hash');
await mkdir(out,{recursive:true});
// A disposable extension sets genuine tab zoom, including the non-menu 140%
// value. It exists only in this isolated benchmark profile, never the user's.
const extension=resolve(out,'zoom-extension');await mkdir(extension,{recursive:true});
await writeFile(`${extension}/manifest.json`,JSON.stringify({manifest_version:3,name:'LocalMind local zoom benchmark',version:'1.0',permissions:['tabs'],background:{service_worker:'worker.js'}}));
await writeFile(`${extension}/worker.js`,'chrome.runtime.onInstalled.addListener(()=>{});');
const context=await chromium.launchPersistentContext(resolve(out,'browser-profile'),{channel:'chromium',headless:process.env.CONSTELLATION_HEADED!=='1',viewport:{width:1440,height:1000},args:['--use-angle=d3d11',`--disable-extensions-except=${extension}`,`--load-extension=${extension}`]});
const browser=context.browser();
const worker=context.serviceWorkers()[0]||await context.waitForEvent('serviceworker');
const results=[];
try {
  const system=await browser.newBrowserCDPSession();
  const hardware=await system.send('SystemInfo.getInfo');
  await writeFile(`${out}/hardware.json`,JSON.stringify(hardware,null,2));
  for(const zoom of [1,1.25,1.4])for(const workload of ['idle','ollama']){
    const page=await context.newPage();
    await page.setViewportSize({width:1440,height:1000});
    if(baseline)for(const file of ['constellation.js','interface.js']){
      const {stdout}=await exec('git',['show',`${baseline}:static/assets/${file}`]);
      await page.route(`**/assets/${file}`,r=>r.fulfill({contentType:'application/javascript',body:stdout}));
    }
    await page.goto('http://127.0.0.1:8765');
    const actualZoom=await worker.evaluate(async zoom=>{
      const tabs=await chrome.tabs.query({url:'http://127.0.0.1:8765/*'});
      if(tabs.length!==1)throw new Error('Expected exactly one local benchmark tab');
      await chrome.tabs.setZoom(tabs[0].id,zoom);return chrome.tabs.getZoom(tabs[0].id);
    },zoom);
    await page.waitForTimeout(200);
    const viewport=await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,cssZoom:getComputedStyle(document.documentElement).zoom}));
    // Fixed observed-shaped fixture isolates graph size; no application is run.
    await page.evaluate(()=>{
      localmindScene.observeApps(Array.from({length:10},(_,i)=>({id:String(i),name:'Приложение '+i})));
      localmindScene.observeInfo({demo:true,devices:[{id:'lamp',name:'Лампа'}]});
      localmindScene.setFiles([{id:'fixture',label:'Вложение 1'}]);
      localmindScene.observeConversation();
    });
    if(await page.locator('#graphToggle').isVisible())await page.locator('#graphToggle').click();
    await page.waitForTimeout(1500);
    const cdp=await page.context().newCDPSession(page);await cdp.send('Performance.enable');
    if(workload==='ollama'){
      await page.evaluate(()=>{document.querySelector('#responseTokens').value='1536';document.querySelector('#responseLength').value='detailed';});
      await page.locator('#message').fill('Объясни подробно, как устроена радуга. Напиши восемь содержательных абзацев: преломление, дисперсия, отражение в капле, углы, порядок цветов, двойная радуга, эксперименты и история.');
      await page.locator('#message').press('Enter');
      await page.waitForFunction(()=>localmindScene.stats().mode==='generating',{},{timeout:10000});
    }
    await cdp.send('Tracing.start',{categories:'devtools.timeline,blink.user_timing,gpu',transferMode:'ReturnAsStream'});
    const before=(await cdp.send('Performance.getMetrics')).metrics;
    const gpu=[];let sampling=true;
    const samples=(async()=>{while(sampling){
      try{const {stdout}=await exec('nvidia-smi',['--query-gpu=utilization.gpu,utilization.memory,memory.used','--format=csv,noheader,nounits']);gpu.push(stdout.trim());}catch{gpu.push('unavailable');}
      await new Promise(r=>setTimeout(r,1000));
    }})();
    const frames=await page.evaluate(ms=>new Promise(resolve=>{
      const start=performance.now(),first=localmindScene.stats().frames,intervals=[];let last=null,previous=first,inferenceFrames=0;
      function sample(now){const stats=localmindScene.stats();if(stats.frames!==previous){if(last!==null)intervals.push(now-last);last=now;previous=stats.frames;if(stats.mode==='generating')inferenceFrames++;}
        if(now-start<ms)requestAnimationFrame(sample);else resolve({elapsed:now-start,frames:stats.frames-first,intervals,inferenceFrames,stats});
      }requestAnimationFrame(sample);
    }),duration);
    const after=(await cdp.send('Performance.getMetrics')).metrics;
    sampling=false;await samples;
    const complete=new Promise(r=>cdp.once('Tracing.tracingComplete',r));await cdp.send('Tracing.end');const {stream}=await complete;
    let trace='';for(;;){const chunk=await cdp.send('IO.read',{handle:stream});trace+=chunk.data;if(chunk.eof)break;}await cdp.send('IO.close',{handle:stream});
    await writeFile(`${out}/${zoom}-${workload}.trace.json`,trace);
    const metric=(list,name)=>list.find(x=>x.name===name)?.value||0;
    const p95=values=>values.length?[...values].sort((a,b)=>a-b)[Math.min(values.length-1,Math.floor(values.length*.95))]:null;
    const events=JSON.parse(trace).traceEvents;
    const totals={};for(const name of ['Layout','UpdateLayoutTree','Paint','FunctionCall','RasterTask']){const ev=events.filter(e=>e.name===name&&e.dur);totals[name]={count:ev.length,ms:ev.reduce((n,e)=>n+e.dur/1000,0)};}
    const metricElapsed=metric(after,'Timestamp')-metric(before,'Timestamp');
    const result={zoom,actualZoom,zoomMode,viewport,workload,fps:frames.frames/(frames.elapsed/1000),p95FrameMs:p95(frames.intervals),rendererMainCpuPercent:100*(metric(after,'TaskDuration')-metric(before,'TaskDuration'))/metricElapsed,gpuSystemSamples:gpu,inferenceFrames:frames.inferenceFrames,stats:frames.stats,trace:totals};
    results.push(result);console.log(JSON.stringify(result));
    if(workload==='ollama')await page.locator('#send').waitFor({state:'visible'});
    await page.waitForFunction(()=>!document.querySelector('#send').disabled,{},{timeout:125000});
    if(workload==='ollama'){
      const answer=await page.locator('.rendered-message').last().textContent();
      if(!answer||answer.includes('Ответ недоступен'))throw new Error('Actual Ollama response unavailable');
      // The UI retains the final authoritative API payload in diagnostics.
      // Reading it avoids racing the app's deliberate abort of a finished stream.
      result.engine=JSON.parse(await page.locator('.message-diagnostics pre').last().textContent()).engine;
      if(result.engine!=='ollama')throw new Error('Expected actual Ollama engine, got '+result.engine);
    }
    await page.close();
  }
}finally{await writeFile(`${out}/results.json`,JSON.stringify(results,null,2));await context.close();}
