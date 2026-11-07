import {test,expect} from '@playwright/test';

test('access screen keeps the close button reachable while the rules scroll at 100–175 percent',async({page})=>{
  const mutations=[];
  let policy={mode:'restricted',revision:'one',server_instance:'fixture',roots:[{id:'docs',path:'C:\\LocalMind-test\\Documents'}],operations:['search','read','open'],rules:[],excluded:'Системные области, чужие профили и секреты исключены.',access_log:[]};
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname,body=request.method()==='POST'?request.postDataJSON():null;
    if(body)mutations.push({path,body});
    const json=data=>route.fulfill({json:data});
    if(path==='/api/access-policy/preview')return json({draft_id:'preview',interpretation:'Запретить все операции в папке Загрузки и её содержимом.'});
    if(path==='/api/access-policy/apply'){policy={...policy,revision:'two',rules:[{text:'Не трогай папку Загрузки'}]};return json(policy);}
    if(path==='/api/access-policy'){if(body)policy={...policy,...body,revision:'saved'};return json(policy);}
    if(path==='/api/setup')return json({onboarding:{completed:true},tour:{completed:true,skipped:true},preferences:{},voice:[],ollama:{state:'unavailable'}});
    if(path==='/api/actions')return json({actions:[]});
    return json({server_instance:'fixture',demo:true,devices:[],voice:{voices:[]},models:[],apps:[],sources:[],folder:{allowed:false},jobs:[],conversations:[]});
  });
  await page.goto('/');await page.locator('#capabilitiesOpen').click();
  const dialog=page.locator('#accessDialog');await expect(dialog).toBeVisible();
  await expect(page.locator('#accessCurrent')).toContainText('Ограниченный доступ');
  expect(mutations.filter(m=>m.path==='/api/access-policy')).toHaveLength(0);
  await page.locator('#accessRuleText').fill('Не трогай папку Загрузки');await page.locator('#previewAccessRule').click();
  await expect(page.locator('#accessRuleInterpretation')).toContainText('Запретить все операции');
  expect(mutations.filter(m=>m.path.endsWith('/apply'))).toHaveLength(0);
  await page.locator('#cancelAccessRule').click();await expect(page.locator('#accessRulePreview')).toBeHidden();
  await page.locator('#previewAccessRule').click();await page.locator('#applyAccessRule').click();
  await expect(page.locator('#accessRules')).toContainText('Не трогай папку Загрузки');
  for(const [width,height] of [[1280,720],[1366,768],[1920,1080],[900,620]])for(const scale of [1,1.25,1.5,1.75]){
    await page.setViewportSize({width,height});
    await page.evaluate(value=>document.body.style.zoom=String(value),scale);
    const bounds=await dialog.boundingBox(),viewport=page.viewportSize();
    expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(viewport.width+1);
    await page.locator('#accessRuleText').scrollIntoViewIfNeeded();await expect(page.locator('#accessRuleText')).toBeInViewport();
    await expect(page.locator('#accessClose')).toBeInViewport({ratio:1});
    await page.locator('#accessClose').click({trial:true});
  }
  await page.evaluate(()=>document.body.style.zoom='1');
  await dialog.press('Escape');await expect(dialog).not.toBeVisible();await expect(page.locator('#capabilitiesOpen')).toBeFocused();
});
