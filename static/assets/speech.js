/* Local, bounded clause synthesis and ordered playback; no browser/cloud voices. */
'use strict';
// Match speech_text.SILERO_NAMES phrases. Keep names together at the length
// boundary, including a partially received name at the end of a text delta.
const speechNames=['World of Warcraft','Arthas Menethil','Reign of Chaos','The Frozen Throne','Heroes of the Storm',
  'Diablo Immortal','Blizzard Entertainment','Visual Studio Code','C++','C#','Node.js',
];
const speechNamePatterns=speechNames.map(name=>new RegExp('^'+name.split(/\s+/).map(word=>word.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('\\s+')+'(?![\\p{L}\\p{N}_])','iu'));
function nameSafeCut(buffer,cut) {
  // Protect syntactic context, not franchises. Do not interpret/pronounce here;
  // the server remains the sole normalization authority. Supersets are safe.
  const contexts=[/[A-Za-z]{2,}\s+[IVXLCDM]+(?![\p{L}\p{N}_+#])/giu,
    /[\p{L}]+\s*&\s*[\p{L}]*/gu,
    // Supersets of the server's software cues; include incomplete values and
    // a pending product after "Версия". Periods inside Node.js stay intact.
    /(?<![\p{L}\p{N}_.])(?:(?:version|верси[яию]|версией)(?:\s+ПО)?(?:\s+[A-Za-z][\w+#]*(?:\.[A-Za-z][\w+#]*)*\.?)?(?:\s+(?:v\s*)?[0-9]*(?:\.[0-9]*)*)?|(?:Python|Node\.js|JavaScript|Windows|LocalMind|Ollama|Docker|Chrome|Firefox|Obsidian|Steam|Linux)\s+(?:v\s*)?[0-9]*(?:\.[0-9]*)*)/giu,
    // Shared noun and partial noun; do not cut at a comma within the year list.
    /(?<![\p{L}\p{N}_.+−-])[1-9][0-9]{3}(?:(?:\s*,\s*(?:(?:и|или)\s+)?|\s+(?:и|или)\s+)[1-9][0-9]{3})*\s+г(?:о(?:д(?:у|а(?:х)?|ом)?)?)?(?![\p{L}\p{N}_])/giu,
    // A delta may end before the next year or before the shared noun arrives.
    /(?<![\p{L}\p{N}_.+−-])[1-9][0-9]{3}(?:(?:\s*,\s*(?:(?:и|или)\s+)?|\s+(?:и|или)\s+)[1-9][0-9]{0,3})*(?:\s*,\s*(?:и|ил(?:и)?)?\s*|\s+(?:и|ил(?:и)?)?)?\s*$/giu,
    /[0-9]+\s+г(?:о(?:д(?:у|а|ом)?)?)?(?![\p{L}\p{N}_])/giu,
    /[^\s]+/gu];
  for(const pattern of contexts)for(const match of buffer.matchAll(pattern)) {
    if(match.index<cut && match.index+match[0].length>cut)cut=match.index;
  }
  // A trailing token may acquire a numeral, ampersand, year suffix or decimal
  // continuation in the next delta. Hold it until context or final flush arrives.
  const pending=/[\p{L}\p{N}_]+(?:[.,-][0-9]+)*\s*$/u.exec(buffer);
  if(pending && pending.index<cut)cut=pending.index;
  // Scan token starts rather than a fixed character window: repeated whitespace
  // can make an entity longer than its canonical spelling. Buffer is bounded.
  for(let start=0;start<cut;start++) {
    if(start && /[\p{L}\p{N}_]/u.test(buffer[start-1]))continue;
    const tail=buffer.slice(start),candidate=tail.toLowerCase().replace(/\s+/g,' ');
    for(let index=0;index<speechNames.length;index++) {
      const match=speechNamePatterns[index].exec(tail);
      if((match && start+match[0].length>cut) ||
          (candidate.length && speechNames[index].toLowerCase().startsWith(candidate)))cut=start;
    }
  }
  return cut;
}
class LocalMindSpeech {
  constructor({request, cancelRequest, enabled, voice, report}) {
    this.request=request;this.enabled=enabled;this.voice=voice;this.report=report;
    this.cancelRequest=cancelRequest;
    this.epoch=0;this.session=null;
  }
  start() {
    this.cancel();
    if(this.enabled())window.LocalMindAudio?.unlock();
    this.session={epoch:this.epoch,token:crypto.randomUUID().replaceAll('-',''),buffer:'',texts:[],audio:[],controller:null,current:null,url:null,
      synthesizing:false,playing:false,paused:false,done:false,sequence:0,started:performance.now(),
      metrics:{first_synthesis_ms:null,first_playback_ms:null,chunks:0,cancelled:false}};
    window.localmindVoiceMetrics=this.session.metrics;
  }
  cancel() {
    this.epoch++;
    const s=this.session;
    if(s){s.metrics.cancelled=true;s.controller?.abort();s.current?.pause();s.releaseAmplitude?.();
      if(s.synthesizing)this.cancelRequest?.(s.token).catch(()=>{});
      if(s.current){s.current.onended=null;s.current.onerror=null;}
      if(s.url)URL.revokeObjectURL(s.url);
      s.texts.length=0;s.audio.length=0;s.buffer='';}
    this.session=null;
    window.dispatchEvent(new CustomEvent('localmind-playback',{detail:{active:false}}));
  }
  valid(s){return this.session===s && s.epoch===this.epoch && this.enabled();}
  feed(text, final=false) {
    if(!this.enabled())return;
    const s=this.session;if(!s || !this.valid(s) || s.done)return;
    s.buffer+=text;
    if(s.buffer.length>8192){this.fail(s,'Слишком длинный текст для озвучки');return;}
    while(s.buffer.trim()) {
      let cut=0;
      // Keep decimal points inside their number. A feasible first sentence can
      // enter synthesis as soon as its following whitespace arrives, before final.
      const end=/(?<!\d)[.!?](?=\s)|[.!?](?!\d)(?=\s)|[;:](?=\s)/g;
      let match;
      while((match=end.exec(s.buffer))){if(match.index>=12){cut=match.index+1;break;}}
      if(!cut && s.buffer.length>=110){const comma=s.buffer.indexOf(', ',60);if(comma>=0)cut=comma+1;}
      if(!cut && s.buffer.length>240){cut=s.buffer.lastIndexOf(' ',240);if(cut<40)cut=240;}
      if(cut)cut=nameSafeCut(s.buffer,cut);
      if(!cut && final)cut=s.buffer.length;
      if(!cut)break;
      const text=s.buffer.slice(0,cut).trim();s.buffer=s.buffer.slice(cut);
      if(text){
        if(s.texts.length>=12){this.fail(s,'Озвучка не успевает за ответом. Текст доступен в чате.');return;}
        s.texts.push({id:++s.sequence,text});
      }
    }
    if(final)s.done=true;
    this.pump(s);
  }
  pause() {
    const s=this.session;if(!s)return;
    s.paused=!s.paused;
    if(s.paused)s.current?.pause();
    else if(s.current){this.resumeAudio(s);}else this.pump(s);
    return s.paused;
  }
  async resumeAudio(s) {
    try{await s.current.play();}catch(error){if(this.valid(s))this.fail(s,'Браузер заблокировал воспроизведение. Включите озвучку и отправьте новый запрос.');}
  }
  fail(s,message){if(this.session!==s)return;s.metrics.error=message;this.cancel();this.report(message);}
  pump(s) {
    if(!this.valid(s)||s.paused)return;
    if(!s.synthesizing && s.texts.length && s.audio.length<2) this.synthesize(s);
    if(!s.playing && s.audio.length)this.play(s);
  }
  async synthesize(s) {
    s.synthesizing=true;
    const chunk=s.texts.shift(),controller=new AbortController();s.controller=controller;
    const timeout=setTimeout(()=>controller.abort(),125000);
    try{
      const response=await this.request(chunk.text,this.voice(),controller.signal,s.token);
      const blob=await response.blob();
      if(!this.valid(s))return;
      if(blob.size>12*1024*1024)throw Error('Слишком большой аудиофрагмент');
      s.audio.push({id:chunk.id,blob});
      if(s.metrics.first_synthesis_ms===null)s.metrics.first_synthesis_ms=performance.now()-s.started;
    }catch(error){if(this.valid(s))this.fail(s,'Озвучка недоступна: '+error.message);}
    finally{clearTimeout(timeout);s.synthesizing=false;if(s.controller===controller)s.controller=null;this.pump(s);}
  }
  async play(s) {
    s.playing=true;
    const chunk=s.audio.shift();s.url=URL.createObjectURL(chunk.blob);
    const audio=new Audio(s.url);s.current=audio;
    s.releaseAmplitude=window.LocalMindAudio?.start(audio,'speaking');
    const complete=()=>{
      if(!this.valid(s))return;
      s.releaseAmplitude?.();s.releaseAmplitude=null;
      URL.revokeObjectURL(s.url);s.url=null;s.current=null;s.playing=false;
      window.dispatchEvent(new CustomEvent('localmind-playback',{detail:{active:false}}));
      this.pump(s);
    };
    audio.onended=complete;
    audio.onerror=()=>this.fail(s,'Не удалось воспроизвести аудиофрагмент.');
    try{
      await audio.play();
      if(!this.valid(s)){audio.pause();return;}
      if(s.paused)audio.pause();
      window.dispatchEvent(new CustomEvent('localmind-playback',{detail:{active:true}}));
      s.metrics.chunks++;
      // Browser play start, not a claim of measured sound at the speaker.
      if(s.metrics.first_playback_ms===null)s.metrics.first_playback_ms=performance.now()-s.started;
      this.pump(s);
    }catch(error){if(this.valid(s))this.fail(s,'Браузер заблокировал озвучку. Включите её и отправьте новый запрос.');}
  }
}
window.LocalMindSpeech=LocalMindSpeech;
