import {test,expect} from '@playwright/test';

test('first-run repair and the common download queue are explicit and survive a displayed interruption',async({page,baseURL})=>{
  const origin=new URL(baseURL).origin,mutations=[];let job=null;
  await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  await page.route('**/api/**',route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(request.method()==='POST')mutations.push(path);
    const json=data=>route.fulfill({json:data});
    if(path==='/api/setup')return json({voice:[{kind:'asr',state:'model_missing'},{kind:'tts',state:'model_missing'}],ollama:{state:'ready',active_installed:true}});
    if(path==='/api/setup/voice'){
      expect(request.postDataJSON()).toEqual({kind:'asr'});
      job={id:'a'.repeat(32),kind:'asr',model:'Русская речь · small',status:'downloading',completed:25,total:100};return json(job);
    }
    if(path==='/api/downloads')return json({jobs:job?[job]:[]});
    if(path.endsWith('/cancel')){job.status='cancelled';return json(job);}
    if(path.endsWith('/retry')){job.status='starting';return json(job);}
    if(path==='/api/info')return json({server_instance:'f'.repeat(32),demo:true,model:'gemma4:12b',devices:[],voice:{voices:[]}});
    if(path==='/api/models')return json({models:[],active:'gemma4:12b'});
    return json({apps:[],sources:[],folder:{allowed:false},jobs:[]});
  });
  await page.goto('/');await expect(page.locator('#setupDialog')).toBeVisible();expect(mutations).toEqual([]);
  await page.getByRole('button',{name:'Подготовить распознавание',exact:true}).click();
  expect(mutations).toEqual(['/api/setup/voice']);
  await page.getByRole('button',{name:'Продолжить в приложении'}).click();
  await page.locator('#downloadsOpen').click();await expect(page.locator('#downloadsList progress')).toHaveJSProperty('value',25);
  await page.locator('#downloadsList').getByRole('button',{name:'Отменить',exact:true}).click();
  await expect(page.locator('#downloadsList')).toContainText('Отменено');
  job.status='interrupted';await page.reload();await expect(page.locator('#setupDialog')).toBeVisible();
  await page.getByRole('button',{name:'Продолжить в приложении'}).click();await page.locator('#downloadsOpen').click();
  await expect(page.locator('#downloadsList')).toContainText('Прервано перезапуском');expect(mutations).toHaveLength(2);
  await page.locator('#downloadsList').getByRole('button',{name:'Повторить',exact:true}).click();
  await expect(page.locator('#downloadsList')).toContainText('Подготовка');
  expect(mutations.some(path=>path==='/api/models/select')).toBe(false);
});
