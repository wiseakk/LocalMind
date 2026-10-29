// Pure reducers shared by the local benchmark and its synthetic evidence tests.
export const percentile95=values=>values.length?[...values].sort((a,b)=>a-b)[Math.min(values.length-1,Math.floor(values.length*.95))]:null;

export function summarizeTrace(events){
  // Restrict totals to the measured window, excluding trace setup/teardown.
  const start=events.find(e=>e.name==='constellation-bench-start')?.ts;
  const end=events.find(e=>e.name==='constellation-bench-end')?.ts;
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start)throw new Error('Missing or invalid measured trace window');
  const totals={};
  for(const name of ['Layout','UpdateLayoutTree','Paint','FunctionCall','RasterTask','MinorGC','MajorGC']){
    const matching=events.filter(e=>e.name===name&&e.dur>0&&e.ts<end&&e.ts+e.dur>start);
    totals[name]={count:matching.length,ms:matching.reduce((sum,e)=>sum+Math.max(0,Math.min(end,e.ts+e.dur)-Math.max(start,e.ts))/1000,0)};
  }
  const inWindow=events.filter(e=>e.ts>=start&&e.ts<=end),frameEvents={};
  for(const name of ['BeginFrame','DrawFrame','DroppedFrame','FramePresented','PipelineReporter'])frameEvents[name]=inWindow.filter(e=>e.name===name).length;
  // Raw event counts are not presented FPS: several surfaces/threads may emit
  // events for one display frame. Inspect the DevTools Frames track as well.
  return {windowMs:(end-start)/1000,totals,frameEvents};
}

// This self-contained function also runs inside page.evaluate. Counting rAF
// callbacks separately avoids treating callbacks as delivered Canvas draws.
export function sampleCanvasFrames({duration,inference}){
  return new Promise(resolve=>{
    const scene=window.localmindScene,start=performance.now();
    const streaming=inference?document.querySelector('.bubble.streaming'):null;
    const first=scene.stats({timings:false}).frames,intervals=[];
    let previous=first,last=null,callbacks=0;
    performance.mark('constellation-bench-start');
    function sample(now){
      const stats=scene.stats({timings:false});callbacks++;
      const ended=inference&&(!streaming?.isConnected||!streaming.classList.contains('streaming')||streaming.querySelector('.message-diagnostics'));
      if(stats.frames!==previous){if(last!==null)intervals.push(now-last);last=now;previous=stats.frames;}
      if(now-start<duration&&!ended)requestAnimationFrame(sample);
      else{
        performance.mark('constellation-bench-end');
        resolve({startEpochMs:performance.timeOrigin+start,elapsed:now-start,canvasFrames:stats.frames-first,rafCallbacks:callbacks,intervals,endedWithResponse:Boolean(ended),stats:scene.stats()});
      }
    }
    requestAnimationFrame(sample);
  });
}
