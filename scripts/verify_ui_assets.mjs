/* Static offline-asset audit; browser request blocking is a separate gate. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';

const root=path.resolve('static'),visited=new Set(),assets=[];
function visit(filename){
  filename=path.resolve(filename);assert.ok(filename.startsWith(root+path.sep),'Asset escapes static root');
  if(visited.has(filename))return;visited.add(filename);
  const bytes=fs.readFileSync(filename);assert.ok(bytes.length,'Empty asset: '+filename);
  assets.push({path:path.relative(root,filename).replaceAll('\\','/'),bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')});
  if(!/\.(html|css)$/.test(filename))return;
  const source=bytes.toString('utf8');
  const references=filename.endsWith('.html')?[...source.matchAll(/(?:src|href)="([^"]+)"/g)].map(m=>m[1]):[...source.matchAll(/url\(\s*['"]?([^)'"\s]+)['"]?\s*\)/g)].map(m=>m[1]);
  for(const ref of references){
    if(ref==='/'||ref.startsWith('#'))continue;
    assert.ok(!/^(?:https?:|\/\/|data:)/i.test(ref),'Nonlocal asset: '+ref);
    visit(ref.startsWith('/')?path.join(root,ref.slice(1)):path.join(path.dirname(filename),ref));
  }
}
visit(path.join(root,'index.html'));
for(const name of ['Onest','Unbounded']){
  assert.equal(fs.readFileSync(path.join(root,'assets/fonts/'+name+'.ttf')).readUInt32BE(0),0x00010000);
  assert.ok(fs.readFileSync(path.join(root,'assets/fonts/'+name+'-OFL.txt'),'utf8').includes('SIL OPEN FONT LICENSE'));
}
// CSP remains deliberately strict; Canvas previews need no img/blob allowance.
const server=fs.readFileSync('localmind/server.py','utf8');assert.ok(server.includes("img-src 'none'"));
assets.sort((a,b)=>a.path.localeCompare(b.path));
if(process.argv.includes('--report')){
  fs.mkdirSync('docs/evidence/constellation',{recursive:true});
  fs.writeFileSync('docs/evidence/constellation/local-assets.json',JSON.stringify({kind:'static audit; not browser network evidence',assets},null,2)+'\n');
}
console.log(`${assets.length} local assets resolve; both licensed fonts bundled; restrictive image CSP retained.`);
