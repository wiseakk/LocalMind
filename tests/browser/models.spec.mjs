import {test,expect} from '@playwright/test';

test('model selection is explicit, identity is authoritative, catalog never starts a pull',async({page,baseURL})=>{
  const calls=[],outside=[],origin=new URL(baseURL).origin;let active='fixture:4b';
  const conversation={conversation_id:'c'.repeat(32),draft:'',context:{attachment_ids:[],local_retrieval:false},messages:[],attachments:[]};
  page.on('pageerror',error=>{throw error;});
  await page.route('**/*',route=>{
    const url=route.request().url();
    if(/^https?:/.test(url)&&new URL(url).origin!==origin){outside.push(url);return route.abort();}
    return route.continue();
  });
  await page.route('**/api/**',route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    const body=request.method()==='POST'?request.postDataJSON():null;
    calls.push({path,body});const json=data=>route.fulfill({json:data});
    if(path==='/api/conversations')return json(request.method()==='POST'?{...conversation,server_instance:'f'.repeat(32)}:{conversations:[]});
    if(path.startsWith('/api/conversations/'))return json({...conversation,server_instance:'f'.repeat(32)});
    if(path==='/api/info')return json({server_instance:'f'.repeat(32),model:active,demo:true,devices:[],voice:{voices:[]}});
    if(path==='/api/models')return json({active,models:['fixture:4b','fixture:8b'].map(name=>({name,selectable:true,details:{family:'qwen3',quantization_level:'Q4_K_M'},capabilities:['completion'],placement:'unknown'}))});
    if(path==='/api/models/hardware')return json({cpu:'CPU fixture',gpus:[],gpu_status:'unavailable'});
    if(path==='/api/models/select'){active=body.model;return json({active,health:{actual_model:active}});}
    if(path==='/api/models/downloads'||path==='/api/models/benchmarks')return json({jobs:[]});
    if(path==='/api/models/catalog')return json({models:[{id:'qwen3:4b-q4_K_M',name:'<script>unsafe</script>',source:'ollama',publisher:'Qwen',source_url:'https://ollama.com/library/qwen3',quantization:'Q4_K_M',compatibility:'estimated',memory:{},disk:{status:'unknown'}}]});
    if(path==='/api/chat/stream')return route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'final',data:{answer:'Привет',actual_model:'response:actual',engine:'ollama',action_results:[],metrics:{tokens_per_second:12},server_instance:'f'.repeat(32)}})+'\n'});
    return json({apps:[],sources:[],folder:{allowed:false},devices:[],jobs:[]});
  });
  await page.goto('/');await expect(page.locator('#status')).toContainText('подключён');
  if(await page.locator('#sidebarToggle').isVisible())await page.locator('#sidebarToggle').click();
  await page.locator('#modelsOpen').click();await expect(page.locator('#modelStatus')).toContainText('fixture:4b');
  expect(calls.filter(c=>c.path.includes('catalog')||c.path.includes('/hub/'))).toHaveLength(0);
  await page.locator('#modelSelect').selectOption('fixture:8b');
  await expect(page.locator('#model')).not.toHaveText('fixture:8b');
  expect(calls.filter(c=>c.path==='/api/models/select')).toHaveLength(0);
  await page.locator('#activateModel').click();await expect(page.locator('#modelStatus')).toContainText('fixture:8b');
  await page.locator('#openRegistry').click();await expect(page.locator('#catalogModels')).toContainText('<script>unsafe</script>');
  await expect(page.locator('#catalogModels script')).toHaveCount(0);
  expect(calls.filter(c=>c.path==='/api/models/downloads'&&c.body)).toHaveLength(0);
  await page.keyboard.press('Escape');
  await page.locator('#message').fill('Привет');await page.locator('#send').click();
  await expect(page.locator('#model')).toHaveText('response:actual');
  expect(calls.find(c=>c.path==='/api/chat/stream').body.model).toBeNull();expect(outside).toEqual([]);
});
