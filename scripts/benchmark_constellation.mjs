import {chromium} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {resolve} from 'node:path';
import {platform,release,arch,cpus,totalmem} from 'node:os';
import {percentile95,summarizeTrace,sampleCanvasFrames} from './constellation_metrics.mjs';
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
let context;
const results=[],configuration={date:new Date().toISOString(),os:{platform:platform(),release:release(),arch:arch(),cpu:cpus()[0]?.model,logicalCpus:cpus().length,memoryBytes:totalmem()},requestedDurationMs:duration,zoomMode,baseline:baseline||null,headed:process.env.CONSTELLATION_HEADED==='1'};
await writeFile(`${out}/configuration.json`,JSON.stringify(configuration,null,2));
try {
  context=await chromium.launchPersistentContext(resolve(out,'browser-profile'),{channel:'chromium',headless:!configuration.headed,viewport:{width:1440,height:1000},args:['--use-angle=d3d11',`--disable-extensions-except=${extension}`,`--load-extension=${extension}`]});
  const browser=context.browser();
  const worker=context.serviceWorkers()[0]||await context.waitForEvent('serviceworker',{timeout:15000});
  const system=await browser.newBrowserCDPSession();
  const hardware=await system.send('SystemInfo.getInfo');
  configuration.browser=await system.send('Browser.getVersion');
  await writeFile(`${out}/configuration.json`,JSON.stringify(configuration,null,2));
  await writeFile(`${out}/hardware.json`,JSON.stringify(hardware,null,2));
  if(hardware.gpu.featureStatus?.gpu_compositing!=='enabled'||hardware.gpu.featureStatus?.['2d_canvas']!=='enabled')throw new Error('Hardware-accelerated Canvas/compositing unavailable; do not report software results as hardware acceptance');
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
    if(Math.abs(actualZoom-zoom)>.0001)throw new Error('Native browser zoom did not match requested zoom');
    await page.waitForTimeout(200);
    const viewport=await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,cssZoom:getComputedStyle(document.documentElement).zoom}));
    if(Number(viewport.cssZoom)!==1)throw new Error('CSS zoom is not native browser zoom');
    await page.waitForFunction(()=>document.querySelector('#status').textContent==='Сервер подключён');
    await page.evaluate(()=>document.fonts.ready);
    // Fixed observed-shaped fixture isolates graph size; no application is run.
    await page.evaluate(()=>{
      localmindScene.observeApps(Array.from({length:10},(_,i)=>({id:String(i),name:'Приложение '+i})));
      localmindScene.observeInfo({demo:true,devices:[{id:'lamp',name:'Лампа'}]});
      localmindScene.setFiles([{id:'fixture',label:'Вложение 1'}]);
      localmindScene.setSources([]);
      localmindScene.observeConversation();
    });
    if(await page.locator('#graphToggle').isVisible())await page.locator('#graphToggle').click();
    await page.waitForTimeout(1500);
    const initial=await page.evaluate(()=>localmindScene.stats());
    if(initial.nodes!==14||!initial.visible||initial.low||initial.reduced)throw new Error('Expected fourteen visible nodes with normal animation');
    await page.screenshot({path:`${out}/${zoom}-${workload}.png`});
    const cdp=await page.context().newCDPSession(page);await cdp.send('Performance.enable');
    let startupMs=null;
    if(workload==='ollama'){
      await page.evaluate(()=>{document.querySelector('#responseTokens').value='1536';document.querySelector('#responseLength').value='detailed';document.querySelector('#speak').checked=false;});
      await page.locator('#message').fill('Объясни подробно, как устроена радуга. Напиши восемь содержательных абзацев: преломление, дисперсия, отражение в капле, углы, порядок цветов, двойная радуга, эксперименты и история.');
      const requested=Date.now();
      await page.locator('#message').press('Enter');
      // Generating mode includes model loading. A real streamed delta adds this
      // class; do not measure startup or an idle tail as active inference.
      await page.locator('.bubble.streaming').waitFor({state:'attached',timeout:125000});
      startupMs=Date.now()-requested;
    }
    await cdp.send('Tracing.start',{categories:'devtools.timeline,blink.user_timing,gpu,cc,viz,disabled-by-default-devtools.timeline.frame',transferMode:'ReturnAsStream'});
    const before=(await cdp.send('Performance.getMetrics')).metrics;
    const gpu=[];let sampling=true;
    const samples=(async()=>{while(sampling){
      const at=Date.now();
      try{const {stdout}=await exec('nvidia-smi',['--query-gpu=utilization.gpu,utilization.memory,memory.used','--format=csv,noheader,nounits'],{timeout:2000});gpu.push({at,wholeDeviceCsv:stdout.trim()});}catch{gpu.push({at,wholeDeviceCsv:'unavailable'});}
      await new Promise(r=>setTimeout(r,1000));
    }})();
    let frames,after,typedDuringGeneration=false;
    try{
      const measuring=page.evaluate(sampleCanvasFrames,{duration,inference:workload==='ollama'})
        .then(async frames=>({frames,after:(await cdp.send('Performance.getMetrics')).metrics}));
      // Attach a rejection handler while keyboard operations are awaited.
      measuring.catch(()=>{});
      if(workload==='ollama'){
        await page.waitForFunction(()=>performance.getEntriesByName('constellation-bench-start').length>0);
        typedDuringGeneration=await page.locator('.bubble.streaming').count()>0;
        await page.locator('#message').pressSequentially('Проверка ввода',{delay:10});
        if(await page.locator('#message').inputValue()!=='Проверка ввода')throw new Error('Draft typing failed during generation');
      }
      ({frames,after}=await measuring);
    }
    finally{sampling=false;}
    await samples;
    const complete=new Promise(r=>cdp.once('Tracing.tracingComplete',r));await cdp.send('Tracing.end');const {stream}=await complete;
    let trace='';for(;;){const chunk=await cdp.send('IO.read',{handle:stream});trace+=chunk.data;if(chunk.eof)break;}await cdp.send('IO.close',{handle:stream});
    await writeFile(`${out}/${zoom}-${workload}.trace.json`,trace);
    const metric=(list,name)=>list.find(x=>x.name===name)?.value||0;
    const events=JSON.parse(trace).traceEvents;
    const traceSummary=summarizeTrace(events);
    const metricElapsed=metric(after,'Timestamp')-metric(before,'Timestamp');
    const result={zoom,actualZoom,zoomMode,viewport,workload,window:workload==='idle'?'idle':'active streamed output, first delta to final response or duration limit',requestedDurationMs:duration,elapsedMs:frames.elapsed,startupMs,endedWithResponse:frames.endedWithResponse,typedDuringGeneration,canvasFrames:frames.canvasFrames,rafCallbacks:frames.rafCallbacks,fps:frames.canvasFrames/(frames.elapsed/1000),p95FrameMs:percentile95(frames.intervals),rendererMainCpuPercent:100*(metric(after,'TaskDuration')-metric(before,'TaskDuration'))/metricElapsed,cpuMetricWindowMs:metricElapsed*1000,gpuSystemSamples:gpu.filter(s=>s.at>=frames.startEpochMs&&s.at<=frames.startEpochMs+frames.elapsed),stats:frames.stats,trace:traceSummary,presentation:'Canvas submissions and rAF callbacks are distinct from displayed frames. Inspect DevTools Frames track; raw trace frame-event counts are not presented FPS.'};
    if(workload==='ollama')await page.locator('#send').waitFor({state:'visible'});
    await page.waitForFunction(()=>!document.querySelector('#send').disabled,{},{timeout:125000});
    if(workload==='ollama'){
      const answer=await page.locator('.rendered-message').last().textContent();
      if(!answer||answer.includes('Ответ недоступен'))throw new Error('Actual Ollama response unavailable');
      // The UI retains the final authoritative API payload in diagnostics.
      // Reading it avoids racing the app's deliberate abort of a finished stream.
      const final=JSON.parse(await page.locator('.message-diagnostics pre').last().textContent());
      result.engine=final.engine;result.model=final.model||null;
      if(result.engine!=='ollama')throw new Error('Expected actual Ollama engine, got '+result.engine);
      if(frames.elapsed<1000||frames.canvasFrames<2)throw new Error('Active inference sample too short; no valid inference performance result');
      if(!typedDuringGeneration)throw new Error('No live generation remained for the typing check');
    }
    results.push(result);console.log(JSON.stringify(result));
    await page.close();
  }
}catch(error){
  await writeFile(`${out}/failure.json`,JSON.stringify({date:new Date().toISOString(),completedCases:results.length,error:String(error),code:error.code||null},null,2));throw error;
}finally{await writeFile(`${out}/results.json`,JSON.stringify(results,null,2));await context?.close();}
