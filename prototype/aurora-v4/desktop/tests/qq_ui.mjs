// Real QQ settings component with controlled IPC, separately from native smoke.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createServer} from 'vite';
const {chromium}=createRequire(import.meta.url)('playwright');
const root=fileURLToPath(new URL('..',import.meta.url));
const html=await readFile(root+'/index.html','utf8');
const section=html.slice(html.indexOf('<details id="qq-section"'),html.indexOf('</details>',html.indexOf('<details id="qq-section"'))+10);
const server=await createServer({root,server:{host:'127.0.0.1',port:0}});await server.listen();
const browser=await chromium.launch({channel:'msedge',headless:true});let checks=0;
try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/qq-test',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<html><head><meta charset="utf-8"></head><body>'+section+`<script type="module">
 import {QQPanel} from '/src/qq_panel.ts';
 window.calls=[];window.panel=new QQPanel(async(cmd,args)=>{window.calls.push({cmd,args});
   if(window.deferSnapshot&&args.command.action==='snapshot')return new Promise((resolve,reject)=>{window.rejectOldSnapshot=reject;});
   const snapshot=window.pollSnapshot;
   if(snapshot&&args.command.action==='snapshot')setTimeout(()=>panel.accept({type:'qq_snapshot',requestId:args.requestId,snapshot}),250);
 });
 panel.backend(true);panel.open();
 window.respond=snapshot=>{const args=calls.at(-1).args;panel.accept({type:'qq_snapshot',requestId:args.requestId,snapshot});};
 </script></body></html>`}));
 await page.goto(server.resolvedUrls.local[0]+'qq-test');await page.waitForFunction(()=>!!window.panel);
 await page.locator('#qq-section summary').click();
 const base={status:'disabled',error:'',configured:true,self_id:'',private_ids:[],group_ids:[],trigger:'',messages:[],automatic:false,auto_group_ids:[],auto_status:'off',queued:0};
 await page.evaluate(s=>window.respond(s),base);assert.match(await page.locator('#qq-status').textContent(),/已关闭/);assert.match(await page.locator('#qq-messages').textContent(),/暂无/);checks++;
 // Real 1 Hz polling with delayed IPC while the user types across refreshes.
 await page.evaluate(s=>{
   window.pollSnapshot=s;window.inputDisables=[];
   for(const id of ['qq-private-ids','qq-group-ids','qq-auto-groups']){
     const input=document.getElementById(id);
     new MutationObserver(()=>{if(input.disabled)inputDisables.push(id);}).observe(input,{attributes:true,attributeFilter:['disabled']});
   }
 },base);
 // Synthetic numbers retain realistic typing lengths without publishing live identities.
 for(const [id,number] of [['qq-private-ids','1234567890'],['qq-group-ids','234567890'],['qq-auto-groups','234567890']]){
   const input=page.locator('#'+id);await input.fill('');await input.pressSequentially(number,{delay:160});
   assert.equal(await input.inputValue(),number);assert.ok(await input.evaluate(e=>document.activeElement===e));
   assert.deepEqual(await page.evaluate(()=>inputDisables),[]);checks++;
 }
 assert.ok(await page.evaluate(()=>calls.filter(c=>c.args.command.action==='snapshot').length)>=3);
 await page.evaluate(()=>{window.pollSnapshot=null;panel.close();});
 await page.evaluate(s=>respond(s),base);
 await page.locator('#qq-private-ids').fill('7');await page.locator('#qq-group-ids').fill('');
 await page.evaluate(()=>{window.deferSnapshot=true;});
 await page.locator('#qq-refresh').click();const oldPoll=await page.evaluate(()=>calls.at(-1).args.requestId);
 await page.locator('#qq-connect').click();assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'connect');
 await page.evaluate(()=>{window.deferSnapshot=false;window.rejectOldSnapshot(Error('stale poll failed'));});
 assert.ok(await page.locator('#qq-private-ids').isDisabled());
 await page.evaluate(s=>respond({...s,status:'connected',self_id:'99',private_ids:['7']}),base);
 await page.evaluate(({id,s})=>panel.accept({type:'qq_snapshot',requestId:id,snapshot:s}),{id:oldPoll,s:base});
 assert.match(await page.locator('#qq-status').textContent(),/已连接/);checks++;
 assert.match(await page.locator('#qq-authorization-note').textContent(),/先点.*断开 QQ/);assert.ok(await page.locator('#qq-group-ids').isDisabled());checks++;
 await page.locator('#qq-disconnect').click();await page.evaluate(s=>respond(s),base);
 assert.ok(await page.locator('#qq-group-ids').isEnabled());assert.match(await page.locator('#qq-authorization-note').textContent(),/现在可修改/);checks++;
 await page.evaluate(()=>panel.open());await page.evaluate(s=>respond(s),base);
 await page.locator('#qq-private-ids').fill('7,7');await page.locator('#qq-connect').click();assert.match(await page.locator('#qq-status').textContent(),/不重复/);checks++;
 await page.locator('#qq-private-ids').fill('7');await page.locator('#qq-connect').click();
 assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'connect');
 const m={key:'a'.repeat(64),source:'private',conversation_id:'qq:99:private:7:7',sender_id:'7',message_id:'1',timestamp:1,text:'<img src=x onerror=alert(1)>',supported:true,state:'received',reply:'',revision:0,confirmation:'',sent_message_id:''};
 let snap={...base,status:'connected',self_id:'99',private_ids:['7'],messages:[m]};
 await page.evaluate(s=>respond(s),snap);await page.locator('#qq-messages button').click();assert.equal(await page.locator('#qq-original img').count(),0);assert.match(await page.locator('#qq-source').textContent(),/私聊 7/);checks++;
 await page.locator('#qq-generate').click();assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'generate');
 snap={...snap,messages:[{...m,state:'preview',reply:'generated draft',revision:1}]};await page.evaluate(s=>respond(s),snap);assert.equal(await page.locator('#qq-reply').inputValue(),'generated draft');assert.equal(await page.evaluate(()=>calls.filter(c=>c.args.command.action==='send').length),0);checks++;
 await page.locator('#qq-reply').fill('edited draft');await page.locator('#qq-prepare').click();assert.match(await page.locator('#qq-status').textContent(),/先保存预览/);checks++;
 await page.locator('#qq-edit').click();await page.evaluate(s=>respond({...s,error:'QQ_CONFLICT'}),snap);assert.equal(await page.locator('#qq-reply').inputValue(),'edited draft');checks++;
 await page.locator('#qq-edit').click();snap={...snap,messages:[{...snap.messages[0],reply:'edited draft',revision:2}]};await page.evaluate(s=>respond(s),snap);
 await page.locator('#qq-prepare').click();snap={...snap,messages:[{...snap.messages[0],confirmation:'b'.repeat(64)}]};await page.evaluate(s=>respond(s),snap);await page.locator('#qq-confirmation').waitFor({state:'visible'});assert.equal(await page.locator('#qq-confirm-text').textContent(),'edited draft');checks++;
 await page.locator('#qq-reply').fill('changed after confirmation');assert.ok(await page.locator('#qq-confirmation').isHidden());assert.equal(await page.evaluate(()=>calls.filter(c=>c.args.command.action==='send').length),0);checks++;
 await page.locator('#qq-edit').click();snap={...snap,messages:[{...snap.messages[0],reply:'changed after confirmation',revision:3,confirmation:''}]};await page.evaluate(s=>respond(s),snap);
 await page.locator('#qq-prepare').click();snap={...snap,messages:[{...snap.messages[0],confirmation:'c'.repeat(64)}]};await page.evaluate(s=>respond(s),snap);await page.locator('#qq-confirmation').waitFor({state:'visible'});await page.locator('#qq-confirm-send').click();
 const send=await page.evaluate(()=>calls.at(-1).args.command);assert.deepEqual(send,{action:'send',message_key:m.key,revision:3,confirmation:'c'.repeat(64)});checks++;
 snap={...snap,error:'QQ_SEND_UNKNOWN',messages:[{...snap.messages[0],state:'unknown',confirmation:''}]};await page.evaluate(s=>respond(s),snap);assert.match(await page.locator('#qq-status').textContent(),/禁止重试/);assert.ok(await page.locator('#qq-prepare').isDisabled());checks++;
 await page.locator('#qq-disconnect').click();await page.evaluate(s=>respond(s),base);assert.ok(await page.locator('#qq-preview').isHidden());checks++;
 await page.locator('#qq-connect').click();
 snap={...base,status:'connected',self_id:'99',private_ids:['7'],group_ids:['40']};await page.evaluate(s=>respond(s),snap);
 assert.ok(await page.locator('#qq-enable-auto').isDisabled());await page.locator('#qq-auto-consent').check();
 await page.locator('#qq-auto-groups').fill('41');await page.locator('#qq-enable-auto').click();assert.match(await page.locator('#qq-status').textContent(),/已授权/);checks++;
 await page.locator('#qq-auto-groups').fill('40');await page.locator('#qq-enable-auto').click();
 assert.deepEqual(await page.evaluate(()=>calls.at(-1).args.command),{action:'enable_auto',self_id:'99',group_ids:['40']});
 snap={...snap,automatic:true,auto_group_ids:['40'],auto_status:'ready'};await page.evaluate(s=>respond(s),snap);
 assert.match(await page.locator('#qq-auto-status').textContent(),/Automatic.*40/);assert.ok(await page.locator('#qq-enable-auto').isDisabled());checks++;
 await page.evaluate(()=>panel.close());assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'enable_auto');checks++;
 await page.evaluate(()=>panel.open()); // leaves a snapshot pending: emergency disable must still work
 await page.locator('#qq-disable-auto').click();assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'disable_auto');
 snap={...snap,automatic:false,auto_group_ids:[],auto_status:'off'};await page.evaluate(s=>respond(s),snap);assert.match(await page.locator('#qq-auto-status').textContent(),/Manual/);assert.ok(!await page.locator('#qq-auto-consent').isChecked());checks++;
 assert.match(await page.locator('#qq-archive-status').textContent(),/默认不记录/);assert.ok(await page.locator('#qq-archive-search').isDisabled());checks++;
 await page.locator('#qq-archive-group').fill('40');await page.locator('#qq-archive-consent').check();await page.locator('#qq-archive-enable').click();
 assert.deepEqual(await page.evaluate(()=>calls.at(-1).args.command),{action:'archive_enable',self_id:'99',group_id:'40',consent:true});
 assert.match(await page.locator('#qq-archive-status').textContent(),/正在处理/);checks++;
 const archive={policies:[{account_id:'99',group_id:'40',enabled:1}],error:'',rows:[],account_id:'99',group_id:'40',export_file:'',confirmation:''};
 snap={...snap,archive};await page.evaluate(s=>respond(s),snap);assert.match(await page.locator('#qq-archive-rows').textContent(),/没有符合/);checks++;
 await page.evaluate(()=>{window.archiveOption=document.querySelector('#qq-archive-source option');});
 await page.locator('#qq-refresh').click();await page.evaluate(s=>respond(s),snap);
 assert.ok(await page.evaluate(()=>archiveOption===document.querySelector('#qq-archive-source option')));checks++;
 await page.locator('#qq-archive-sender').fill('7');await page.locator('#qq-archive-query').fill('中文');await page.locator('#qq-archive-search').click();
 assert.deepEqual(await page.evaluate(()=>calls.at(-1).args.command),{action:'archive_query',self_id:'99',group_id:'40',sender_id:'7',query:'中文',after:0,before:9007199254740991,offset:0});checks++;
 const row={key:'a'.repeat(64),platform:'qq',account_id:'99',group_id:'40',sender_id:'7',display_name:'小林',message_id:'1',timestamp:100,message_type:'text',text:'<img src=x onerror=alert(1)> 中文原文',ingested_at:101,truncated:false};
 snap={...snap,archive:{...archive,rows:[row]}};await page.evaluate(s=>respond(s),snap);
 assert.equal(await page.locator('#qq-archive-rows img').count(),0);assert.match(await page.locator('#qq-archive-rows').textContent(),/小林.*QQ 7/);checks++;
 await page.locator('#qq-archive-rows button').filter({hasText:'查看前后文'}).click();assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'archive_around');await page.evaluate(s=>respond(s),snap);checks++;
 await page.locator('#qq-archive-search').click();snap={...snap,archive:{...archive,error:'QQ_ARCHIVE_FAILED',rows:[]}};await page.evaluate(s=>respond(s),snap);assert.match(await page.locator('#qq-archive-status').textContent(),/不能确认已记录/);assert.match(await page.locator('#qq-archive-rows').textContent(),/读取失败/);checks++;
 await page.locator('#qq-archive-search').click();snap={...snap,archive:{...archive,rows:[row]}};await page.evaluate(s=>respond(s),snap);checks++;
 await page.locator('#qq-archive-export').click();assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'archive_export');snap={...snap,archive:{...snap.archive,export_file:'isolated/qq/exports/fixture.jsonl'}};await page.evaluate(s=>respond(s),snap);assert.match(await page.locator('#qq-archive-status').textContent(),/导出已完成/);checks++;
 await page.locator('#qq-archive-delete-sender').click();assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'archive_prepare_delete');snap={...snap,archive:{...snap.archive,confirmation:'d'.repeat(64)}};await page.evaluate(s=>respond(s),snap);assert.ok(await page.locator('#qq-archive-confirmation').isVisible());assert.match(await page.locator('#qq-archive-delete-description').textContent(),/群 40.*发言者 7/);assert.equal(await page.evaluate(()=>calls.filter(c=>c.args.command.action==='archive_delete').length),0);checks++;
 await page.locator('#qq-archive-cancel-delete').click();assert.ok(await page.locator('#qq-archive-confirmation').isHidden());checks++;
 await page.locator('#qq-archive-delete-group').click();snap={...snap,archive:{...snap.archive,confirmation:'e'.repeat(64)}};await page.evaluate(s=>respond(s),snap);await page.locator('#qq-archive-confirm-delete').click();assert.deepEqual(await page.evaluate(()=>calls.at(-1).args.command),{action:'archive_delete',self_id:'99',group_id:'40',scope:'group',target:'',confirmation:'e'.repeat(64)});snap={...snap,archive:{...archive,policies:[{account_id:'99',group_id:'40',enabled:0}]}};await page.evaluate(s=>respond(s),snap);checks++;
 // A slow operation must not prevent disconnecting to change authorization.
 await page.evaluate(()=>panel.close());
 await page.locator('#qq-refresh').click();snap={...snap,messages:[m],automatic:true,auto_group_ids:['40'],auto_status:'ready'};await page.evaluate(s=>respond(s),snap);
 await page.locator('#qq-messages button').click();await page.locator('#qq-generate').click();
 const oldGeneration=await page.evaluate(()=>calls.at(-1).args.requestId);
 assert.ok(await page.locator('#qq-disconnect').isEnabled());await page.locator('#qq-disconnect').click();
 assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'disconnect');assert.ok(!await page.locator('#qq-auto-consent').isChecked());
 assert.match(await page.locator('#qq-status').textContent(),/正在断开/);assert.ok(await page.locator('#qq-group-ids').isDisabled());checks++;
 await page.evaluate(s=>respond(s),base);
 await page.evaluate(({id,s})=>panel.accept({type:'qq_snapshot',requestId:id,snapshot:s}),{id:oldGeneration,s:snap});
 assert.match(await page.locator('#qq-status').textContent(),/已关闭/);assert.ok(await page.locator('#qq-group-ids').isEnabled());assert.match(await page.locator('#qq-auto-status').textContent(),/Manual/);checks++;
 await page.locator('#qq-group-ids').fill('40,41');await page.locator('#qq-connect').click();
 assert.deepEqual((await page.evaluate(()=>calls.at(-1).args.command)).group_ids,['40','41']);
 assert.ok(await page.locator('#qq-disconnect').isEnabled());await page.locator('#qq-disconnect').click();await page.evaluate(s=>respond(s),base);
 assert.equal(await page.locator('#qq-group-ids').inputValue(),'40,41');assert.ok(!await page.locator('#qq-auto-consent').isChecked());checks++;
 await page.locator('#qq-refresh').click();
 await page.evaluate(s=>respond(s),{...snap,automatic:true,natural:false});
 assert.ok(await page.locator('#qq-enable-natural').isDisabled());checks++;
 await page.locator('#qq-natural-consent').check();await page.locator('#qq-enable-natural').click();
 assert.deepEqual(await page.evaluate(()=>calls.at(-1).args.command),{action:'enable_natural',self_id:'99',group_ids:['40']});
 await page.evaluate(s=>respond(s),{...snap,automatic:true,natural:true});
 assert.match(await page.locator('#qq-natural-status').textContent(),/已开启/);checks++;
 await page.locator('#qq-disable-natural').click();
 assert.equal(await page.evaluate(()=>calls.at(-1).args.command.action),'disable_natural');
 await page.evaluate(s=>respond(s),{...snap,automatic:true,natural:false});
 assert.match(await page.locator('#qq-natural-status').textContent(),/已关闭/);assert.match(await page.locator('#qq-auto-status').textContent(),/Automatic/);checks++;
 await page.evaluate(()=>panel.backend(false));assert.ok(await page.locator('#qq-connect').isDisabled());assert.ok(await page.locator('#qq-archive-confirmation').isHidden());assert.deepEqual(errors,[]);checks++;
 console.log(JSON.stringify({result:'PASS',checks,scope:'Controlled browser UI; not Native or real QQ acceptance'}));
}finally{await browser.close();await server.close();}
