import assert from 'node:assert/strict';
import {percentile95,summarizeTrace,sampleCanvasFrames} from '../scripts/constellation_metrics.mjs';

assert.equal(percentile95([]),null);
const input=[1,4,2,3];assert.equal(percentile95(input),4);assert.deepEqual(input,[1,4,2,3]);
const trace=summarizeTrace([
  {name:'constellation-bench-start',ts:10000},{name:'constellation-bench-end',ts:20000},
  {name:'Layout',ts:0,dur:5000},{name:'Layout',ts:8000,dur:4000},
  {name:'RasterTask',ts:19000,dur:4000},{name:'FunctionCall',ts:11000,dur:2000},
  {name:'MinorGC',ts:12000,dur:1000},{name:'DrawFrame',ts:12000},
  {name:'DrawFrame',ts:9000},{name:'DroppedFrame',ts:13000}
]);
assert.equal(trace.windowMs,10);
assert.deepEqual(trace.totals.Layout,{count:1,ms:2});
assert.deepEqual(trace.totals.RasterTask,{count:1,ms:1});
assert.deepEqual(trace.totals.MinorGC,{count:1,ms:1});
assert.equal(trace.frameEvents.DrawFrame,1);assert.equal(trace.frameEvents.DroppedFrame,1);
assert.throws(()=>summarizeTrace([]),/trace window/);
assert.throws(()=>summarizeTrace([{name:'constellation-bench-start',ts:20},{name:'constellation-bench-end',ts:10}]),/trace window/);

const originals=Object.fromEntries(['window','document','performance','requestAnimationFrame'].map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
try{
  let now=0,frames=0,finished=false,callbacks=[],timingCalls=0;
  const marks=[];
  globalThis.window={localmindScene:{stats(options){if(options?.timings!==false)timingCalls++;return {frames}}}};
  globalThis.document={querySelector:()=>({isConnected:true,classList:{contains:()=>true},querySelector:()=>finished?{}:null})};
  Object.defineProperty(globalThis,'performance',{configurable:true,value:{now:()=>now,timeOrigin:100000,mark:name=>marks.push({name,now})}});
  globalThis.requestAnimationFrame=fn=>callbacks.push(fn);
  const step=(time,draws)=>{now=time;frames+=draws;const batch=callbacks;callbacks=[];batch.forEach(fn=>fn(now))};
  const idle=sampleCanvasFrames({duration:100,inference:false});
  step(20,1);step(40,0);step(60,1);step(80,0);step(100,1);
  const idleResult=await idle;
  assert.equal(idleResult.rafCallbacks,5);assert.equal(idleResult.canvasFrames,3);
  assert.deepEqual(idleResult.intervals,[40,40]);assert.equal(idleResult.elapsed,100);
  assert.equal(idleResult.endedWithResponse,false);assert.equal(timingCalls,1);
  assert.equal(idleResult.startEpochMs,100000);
  const inference=sampleCanvasFrames({duration:30000,inference:true});
  step(120,1);step(140,1);finished=true;step(160,1);
  const inferenceResult=await inference;
  assert.equal(inferenceResult.elapsed,60);assert.equal(inferenceResult.endedWithResponse,true);
  assert.equal(callbacks.length,0);assert.equal(timingCalls,2);
  assert.deepEqual(marks.map(mark=>mark.name),['constellation-bench-start','constellation-bench-end','constellation-bench-start','constellation-bench-end']);
}finally{
  for(const [key,descriptor] of Object.entries(originals)){
    if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key];
  }
}
console.log('PASS benchmark window clipping, frame/callback separation, no per-frame timing sorts and inference-tail exclusion (synthetic data only)');
