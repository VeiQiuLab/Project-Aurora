// Real frontend with controlled IPC: UI/error/ownership checks, not native proof.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
const {chromium}=createRequire(import.meta.url)("playwright");
const server=await createServer({root:fileURLToPath(new URL("..",import.meta.url)),server:{host:"127.0.0.1",port:0}});
await server.listen(); const browser=await chromium.launch({channel:"msedge",headless:true});
let checks=0;
try {
  const page=await browser.newPage(); const errors=[]; page.on("pageerror",e=>errors.push(String(e)));
  await page.addInitScript(()=>{
    let next=0;window.calls=[];window.events={};window.callbacks={};
    window.__TAURI_INTERNALS__={metadata:{currentWindow:{label:"main"},currentWebview:{label:"main"}},
      transformCallback:fn=>{const id=++next;window.callbacks[id]=fn;return id;},unregisterCallback:()=>{},
      invoke:async(cmd,args)=>{
        window.calls.push({cmd,args});
        if(cmd==="plugin:event|listen"){window.events[args.event]=args.handler;return ++next;}
        if(cmd==="plugin:window|is_visible"||cmd==="plugin:window|is_focused")return true;
        if(cmd==="plugin:window|is_maximized")return false;
        if(cmd==="backend_subscribe"){window.gateway=args.channel;return {state:"READY",info:{mode:"production",chat_enabled:true,diagnostics:{settings_status:"loaded",ollama:{reachable:false,model_available:false},local_model:{state:"READY",reachable:true,model_available:true,configured_model:"Qwen3.5-4B"}}},metrics:{desktopStartupMs:0,spawnToBootstrapMs:null,bootstrapToReadyMs:0,commandToFirstDeltaMs:null,cancelToTerminalMs:null,crashToDisconnectedMs:null,restartToReadyMs:null}};}
        if(cmd==="desktop_workflow_snapshot")return {trayReady:true,shortcutReady:true,error:""};
        if(cmd==="live2d_snapshot")return {status:"ready",enabled:true,visible:true};
        if(cmd==="local_voice_snapshot")return {state:"READY"};
        return null;
      }};
    window.send=e=>window.gateway.onmessage(e);
    window.respond=(collection,records,total=records.length,source="primary")=>{
      const call=window.calls.filter(c=>c.cmd==="memory_read"&&c.args.collection===collection).at(-1);
      window.send({type:"memory_snapshot",requestId:call.args.requestId,snapshot:{collection,operation:call.args.recordId?"detail":"list",records,total,offset:call.args.offset,source}});
    };
  });
  await page.goto(server.resolvedUrls.local[0]);
  await page.waitForFunction(()=>window.calls.some(c=>c.cmd==="conversation_list"));
  await page.evaluate(()=>window.send({type:"conversation_list",requestId:"conversation-list-1",conversations:[{conversation_id:"a",title:"会话",message_count:0}]}));
  await page.evaluate(()=>window.send({type:"conversation_loaded",requestId:"conversation-get-1",conversation:{conversation_id:"a",title:"会话",message_count:0,messages:[]}}));
  await page.locator("#prompt-input").fill("未发送草稿");
  await page.locator("#open-settings").click();
  assert.equal(await page.locator("#settings-pane").isVisible(),true);
  assert.equal(await page.evaluate(()=>window.calls.some(c=>c.cmd==="memory_read")),false);checks++;
  await page.locator("#memory-section summary").click();
  await page.waitForFunction(()=>window.calls.filter(c=>c.cmd==="memory_read").length===2);
  assert.equal(await page.locator("#memory-saved").getAttribute("data-state"),"loading");
  assert.match(await page.locator("#memory-pending").textContent(),/正在读取/);checks++;
  const record={inspection_id:"a".repeat(64),content:'<img src=x onerror="window.injected=true"> 喜欢阅读',preview:true,fields:{id:"real-1",type:"preference",enabled:false,metadata:{state:"archived"}}};
  await page.evaluate(record=>{window.respond("saved",[record]);window.respond("pending",[]);},record);
  assert.equal(await page.locator("#memory-saved").getAttribute("data-state"),"ready");
  assert.equal(await page.locator("#memory-pending").getAttribute("data-state"),"empty");
  assert.match(await page.locator("#memory-pending").textContent(),/没有待审核候选/);
  assert.match(await page.locator("#memory-saved").textContent(),/已归档 · 已停用/);
  assert.equal(await page.locator("#memory-saved img").count(),0);checks++;
  await page.locator("#memory-saved .memory-record").click();
  const full={...record,content:record.content+"\n"+"完整详情。".repeat(80),preview:false,fields:{...record.fields,metadata:{state:"archived",confidence:.9,source_detail:{conversation_id:"source-id"}}}};
  await page.evaluate(full=>window.respond("saved",[full]),full);
  assert.equal(await page.locator("#memory-saved .memory-body").textContent(),full.content);
  assert.match(await page.locator("#memory-saved .memory-metadata").textContent(),/source-id/);checks++;
  await page.getByRole("button",{name:"重新读取详情",exact:true}).click();
  await page.evaluate(()=>{const id=window.calls.filter(c=>c.cmd==="memory_read"&&c.args.collection==="saved").at(-1).args.requestId;window.send({type:"memory_error",requestId:id,code:"MEMORY_NOT_FOUND"});});
  assert.equal(await page.locator("#memory-saved").getAttribute("data-state"),"error");
  assert.match(await page.locator("#memory-saved").textContent(),/发生变化/);
  assert.equal(await page.locator("#memory-saved .memory-body").count(),0);checks++;
  await page.getByRole("button",{name:"返回列表",exact:true}).click();
  await page.evaluate(()=>{const id=window.calls.filter(c=>c.cmd==="memory_read"&&c.args.collection==="saved").at(-1).args.requestId;window.send({type:"memory_error",requestId:id,code:"MEMORY_READ_FAILED"});});
  assert.match(await page.locator("#memory-saved").textContent(),/读取失败/);
  await page.locator("#memory-saved").getByRole("button",{name:"重试",exact:true}).click();
  await page.evaluate(()=>window.respond("saved",[],0,"missing"));
  assert.match(await page.locator("#memory-saved").textContent(),/还没有已保存的记忆/);checks++;
  await page.locator("#memory-pending").getByRole("button",{name:"刷新列表",exact:true}).click();
  const candidate={inspection_id:"b".repeat(64),content:"尚未批准的偏好",preview:true,fields:{status:"pending",type:"preference"}};
  await page.evaluate(candidate=>window.respond("pending",[candidate],1,"backup"),candidate);
  assert.match(await page.locator("#memory-pending").textContent(),/原文件未修复/);
  await page.locator("#memory-pending .memory-record").click();
  await page.evaluate(candidate=>window.respond("pending",[{...candidate,preview:false,fields:{...candidate.fields,risk:{level:"low"},explanation:"候选说明"}}]),candidate);
  assert.match(await page.locator("#memory-pending .memory-metadata").textContent(),/候选说明/);
  assert.match(await page.locator("#memory-pending").textContent(),/尚未成为正式记忆/);checks++;
  await page.locator("#memory-saved").getByRole("button",{name:"刷新列表",exact:true}).click();
  const records=Array.from({length:20},(_,i)=>({...record,inspection_id:String(i+10).padStart(64,"0"),content:`记忆 ${i}`}));
  await page.evaluate(records=>window.respond("saved",records,21),records);
  await page.locator("#memory-saved").getByRole("button",{name:"下一页",exact:true}).click();
  await page.evaluate(record=>window.respond("saved",[record],21),record);
  assert.match(await page.locator("#memory-saved").textContent(),/21–21/);checks++;
  await page.locator("#memory-saved").getByRole("button",{name:"刷新列表",exact:true}).click();
  const stale=await page.evaluate(()=>window.calls.filter(c=>c.cmd==="memory_read"&&c.args.collection==="saved").at(-1).args.requestId);
  await page.locator("#close-settings").click();
  assert.equal(await page.locator("#prompt-input").inputValue(),"未发送草稿");
  await page.locator("#open-settings").click();
  await page.evaluate(({stale,record})=>window.send({type:"memory_snapshot",requestId:stale,snapshot:{collection:"saved",operation:"list",records:[record],total:1,offset:0,source:"primary"}}),{stale,record});
  assert.equal(await page.locator("#memory-saved").getAttribute("data-state"),"loading");
  await page.evaluate(()=>{window.respond("saved",[]);window.respond("pending",[]);});
  await page.locator("#close-settings").click();
  assert.equal(await page.locator("#send-button").isDisabled(),false);checks++;
  assert.equal(await page.evaluate(()=>window.calls.some(c=>/approve|reject|delete|chat_start|voice_stop|settings_update/.test(c.cmd))),false);
  assert.deepEqual(errors,[]);checks++;
  console.log(`PASS: ${checks} memory UI scenarios; loading/empty/ready/error, both details, retry, pagination, stale response, safe text, settings/draft/chat isolation and no writes`);
} finally {await browser.close();await server.close();}
