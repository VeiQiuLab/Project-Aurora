// Real frontend with controlled IPC; native proof is a separate gate.
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";
const {chromium}=createRequire(import.meta.url)("playwright");
const server=await createServer({root:fileURLToPath(new URL("..",import.meta.url)),server:{host:"127.0.0.1",port:0}});
await server.listen(); const browser=await chromium.launch({channel:"msedge",headless:true});
const checks=[];
try {
  const page=await browser.newPage();const errors=[];page.on("pageerror",e=>errors.push(String(e)));
  await page.addInitScript(()=>{
    let next=0;window.calls=[];window.callbacks={};
    window.__TAURI_INTERNALS__={metadata:{currentWindow:{label:"main"},currentWebview:{label:"main"}},
      transformCallback:fn=>{const id=++next;window.callbacks[id]=fn;return id;},unregisterCallback:()=>{},
      invoke:async(cmd,args)=>{
        window.calls.push({cmd,args});
        if(cmd==="plugin:event|listen")return ++next;
        if(cmd==="plugin:window|is_visible"||cmd==="plugin:window|is_focused")return true;
        if(cmd==="plugin:window|is_maximized")return false;
        if(cmd==="backend_subscribe"){window.gateway=args.channel;return {state:"READY",info:{mode:"production",chat_enabled:true,diagnostics:{settings_status:"loaded",ollama:{reachable:false,model_available:false},local_model:{state:"READY",reachable:true,model_available:true,configured_model:"Qwen3.5-4B"}}},metrics:{desktopStartupMs:0,spawnToBootstrapMs:null,bootstrapToReadyMs:0,commandToFirstDeltaMs:null,cancelToTerminalMs:null,crashToDisconnectedMs:null,restartToReadyMs:null}};}
        if(cmd==="desktop_workflow_snapshot")return {trayReady:true,shortcutReady:true,error:""};
        if(cmd==="live2d_snapshot")return {status:"ready",enabled:true,visible:true};
        if(cmd==="local_voice_snapshot")return {state:"READY"};
        return null;
      }};
    window.send=e=>window.gateway.onmessage(e);
    window.respond=(collection,records)=>{
      const call=window.calls.filter(c=>c.cmd==="memory_read"&&c.args.collection===collection).at(-1);
      window.send({type:"memory_snapshot",requestId:call.args.requestId,snapshot:{collection,operation:call.args.recordId?"detail":"list",records,total:records.length,offset:call.args.offset,source:"primary"}});
    };
  });
  await page.goto(server.resolvedUrls.local[0]);
  await page.waitForFunction(()=>window.calls.some(c=>c.cmd==="conversation_list"));
  await page.evaluate(()=>window.send({type:"conversation_list",requestId:"conversation-list-1",conversations:[{conversation_id:"a",title:"会话",message_count:0}]}));
  await page.evaluate(()=>window.send({type:"conversation_loaded",requestId:"conversation-get-1",conversation:{conversation_id:"a",title:"会话",message_count:0,messages:[]}}));
  await page.locator("#prompt-input").fill("未发送草稿");
  await page.locator("#open-settings").click();await page.locator("#memory-section summary").click();
  const saved={inspection_id:"a".repeat(64),content:"Saved isolated fixture",preview:true,fields:{id:"saved-1",type:"fact",metadata:{state:"active"}}};
  const candidate={inspection_id:"b".repeat(64),content:"Pending isolated fixture",preview:true,fields:{id:"candidate-1",type:"fact",status:"pending"}};
  const lists=async()=>page.evaluate(({saved,candidate})=>{window.respond("saved",[saved]);window.respond("pending",[candidate]);},{saved,candidate});
  const detail=async(collection,record)=>{
    await page.locator(`#memory-${collection} .memory-record`).click();
    await page.evaluate(({collection,record})=>window.respond(collection,[{...record,preview:false}]),{collection,record});
  };
  const count=()=>page.evaluate(()=>window.calls.filter(c=>c.cmd==="memory_write").length);
  const latest=()=>page.evaluate(()=>window.calls.filter(c=>c.cmd==="memory_write").at(-1));
  const fail=async code=>page.evaluate(code=>{const call=window.calls.filter(c=>c.cmd==="memory_write").at(-1);window.send({type:"memory_error",requestId:call.args.requestId,code});},code);
  const success=async()=>page.evaluate(()=>{const call=window.calls.filter(c=>c.cmd==="memory_write").at(-1),op=call.args.operation;window.send({type:"memory_operation",requestId:call.args.requestId,result:{operation_id:op.operation_id,action:op.action,id:op.id,status:"completed",saved_id:op.action==="approve"?"new-saved":null}});});
  await page.waitForFunction(()=>window.calls.filter(c=>c.cmd==="memory_read").length>=2);
  await lists();await detail("saved",saved);
  await page.getByRole("button",{name:"删除 / Delete",exact:true}).click();
  assert.equal(await count(),0);assert.match(await page.getByRole("alertdialog").textContent(),/saved-1.*可能无法撤销/);
  await page.getByRole("button",{name:"取消删除",exact:true}).click();assert.equal(await count(),0);
  checks.push("delete first click and cancel cause no write");
  await page.getByRole("button",{name:"删除 / Delete",exact:true}).click();await page.locator("#close-settings").click();
  await page.locator("#open-settings").click();await lists();await detail("saved",saved);
  assert.equal(await page.getByRole("alertdialog").count(),0);assert.equal(await count(),0);
  checks.push("closing settings cancels deletion confirmation");
  await page.getByRole("button",{name:"编辑 / Edit",exact:true}).click();
  await page.getByRole("textbox",{name:"编辑记忆内容",exact:true}).fill("Unsaved user draft");
  await page.getByRole("button",{name:"取消编辑",exact:true}).click();assert.equal(await count(),0);
  assert.equal(await page.locator("#memory-saved .memory-body").textContent(),saved.content);
  checks.push("edit cancellation preserves original");
  await page.getByRole("button",{name:"编辑 / Edit",exact:true}).click();
  await page.getByRole("textbox",{name:"编辑记忆内容",exact:true}).fill("   ");
  await page.getByRole("button",{name:"保存 / Save",exact:true}).click();assert.equal(await count(),0);
  await page.getByRole("textbox",{name:"编辑记忆内容",exact:true}).fill("User draft kept after failure");
  await page.getByRole("button",{name:"保存 / Save",exact:true}).click();
  assert.equal(await count(),1);assert.equal(await page.getByRole("button",{name:"保存 / Save",exact:true}).isDisabled(),true);
  const failed=await latest();assert.equal(failed.args.operation.expected_version,saved.inspection_id);
  await fail("MEMORY_WRITE_FAILED");assert.equal(await page.getByRole("textbox",{name:"编辑记忆内容",exact:true}).inputValue(),"User draft kept after failure");
  await page.getByRole("button",{name:"重试操作",exact:true}).click();
  assert.deepEqual((await latest()).args.operation,failed.args.operation);
  await fail("MEMORY_CONFLICT");assert.match(await page.locator("#memory-saved").textContent(),/记录已被修改/);
  assert.equal(await page.getByRole("textbox",{name:"编辑记忆内容",exact:true}).inputValue(),"User draft kept after failure");
  checks.push("invalid edit, busy guard, retained failure draft, exact idempotent retry and conflict");
  await page.getByRole("button",{name:"重试操作",exact:true}).click();await success();await lists();await detail("saved",saved);
  await page.getByRole("button",{name:"删除 / Delete",exact:true}).click();await page.getByRole("button",{name:"确认删除此记忆",exact:true}).click();
  assert.equal((await latest()).args.operation.confirmed,true);assert.equal((await latest()).args.operation.id,"saved-1");
  await success();await lists();checks.push("explicit second confirmation binds exact delete target");
  await detail("pending",candidate);await page.getByRole("button",{name:"批准 / Approve",exact:true}).click();
  assert.equal((await latest()).args.operation.action,"approve");assert.equal(await page.getByRole("button",{name:"拒绝 / Reject",exact:true}).isDisabled(),true);
  await success();await lists();await detail("pending",candidate);await page.getByRole("button",{name:"拒绝 / Reject",exact:true}).click();
  assert.equal((await latest()).args.operation.action,"reject");await success();await lists();
  checks.push("explicit approve and reject refresh both collections");
  await page.locator("#close-settings").click();assert.equal(await page.locator("#prompt-input").inputValue(),"未发送草稿");
  assert.deepEqual(errors,[]);checks.push("settings closure retains chat draft, no renderer exceptions");
  console.log(JSON.stringify({result:"PASS",count:checks.length,checks}));
} finally {await browser.close();await server.close();}
