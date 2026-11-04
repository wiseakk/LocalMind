// Companion journal for tests that replace /api/info with a synthetic instance.
// Real server/process durability lives in test_history_process_restart.py.
export async function conversationFixture(page,instance){
  const records=new Map();let serial=0;
  await page.route('**/api/conversations**',route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    const json=value=>route.fulfill({json:value});
    if(path==='/api/conversations'){
      if(request.method()==='POST'){
        const id=String(++serial).padStart(32,'0'),item={conversation_id:id,title:'Новый чат',draft:'',messages:[],context:{attachment_ids:[],local_retrieval:false},attachments:[],server_instance:instance};
        records.set(id,item);return json(item);
      }
      return json({conversations:[...records.values()]});
    }
    const item=records.get(path.split('/').at(-1));
    if(request.method()==='PATCH')Object.assign(item,request.postDataJSON());
    return json(item);
  });
}
