// Opt-in actual Windows Release/runtime gate. CDP checks are not manual acceptance.
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {spawn,execFile} from "node:child_process";
import {promisify} from "node:util";
import {mkdir,mkdtemp,writeFile,readFile} from "node:fs/promises";
import {createServer} from "node:net";
import {once} from "node:events";
const {chromium}=createRequire(import.meta.url)("playwright");
const exec=promisify(execFile);
const repo=fileURLToPath(new URL("../../../..",import.meta.url));
const exe=fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe",import.meta.url));
const conflictExe=fileURLToPath(new URL("../src-tauri/target/debug/examples/shortcut_conflict.exe",import.meta.url));
const missing=process.argv.includes("--missing"),conflict=process.argv.includes("--conflict"),native=process.argv.includes("--native");
assert.ok(process.env.AURORA_LIVE2D_CONFIG,"Private audited avatar configuration is required");
const ps=async code=>(await exec("powershell.exe",["-NoProfile","-Command",code],{windowsHide:true})).stdout.trim();
const inventory=async()=>JSON.parse(await ps("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object Name,ProcessId,ParentProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})"));
const initial=await inventory();
assert.equal(initial.filter(p=>["aurora-v4-desktop.exe","llama-server.exe","aurora-local-voice-host.exe","aurora-live2d-host.exe"].includes(p.Name)).length,0,"Close existing runtimes; never terminate user instances");
const root=repo+"/tests/output/v48a";
await mkdir(root,{recursive:true});const directory=await mkdtemp(root+"/runtime-");
await mkdir(directory+"/app/config",{recursive:true});
await writeFile(directory+"/app/config/settings.json",JSON.stringify({ollama:{host:"http://127.0.0.1:1"},persona:{enabled:false},knowledge:{enabled:false},rag:{pipeline_enabled:false},voice:{enabled:true,tts:{provider:"local_sherpa_melo"}},live2d:{enabled:true,visible:true,x:64,y:64}}));
const server=createServer();server.listen(0,"127.0.0.1");await once(server,"listening");const port=server.address().port;await new Promise(r=>server.close(r));
const env={...process.env,AURORA_USER_DATA_DIR:directory+"/app",WEBVIEW2_USER_DATA_FOLDER:directory+"/webview",WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port}`};
delete env.AURORA_V4_BACKEND;delete env.AURORA_V4_CHAT_PROVIDER;
if(missing){env.AURORA_LOCAL_MODEL_PATH=directory+"/absent.gguf";env.AURORA_LOCAL_VOICE_MODEL=directory+"/absent-voice";env.AURORA_LIVE2D_CONFIG=directory+"/absent-avatar.json";}
const report={mode:missing?"missing":conflict?"shortcut-conflict":native?"native-handoff":"healthy",release:true,manual:"PENDING",checks:[],owned:[],remainingOwned:[]};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,ms=90000){const end=Date.now()+ms;while(Date.now()<end){const value=await fn();if(value)return value;await delay(100);}throw Error("workflow runtime timeout");}
let child,browser,page,holder,stderr="";const owned=new Map();
const persist=()=>writeFile(directory+"/report.json",JSON.stringify(report,null,2));
async function collect(){
  const rows=await inventory(),ids=new Set([child.pid]);let changed=true;
  while(changed){changed=false;for(const p of rows)if(ids.has(p.ParentProcessId)&&!ids.has(p.ProcessId)){ids.add(p.ProcessId);changed=true;}}
  const result=rows.filter(p=>ids.has(p.ProcessId));result.forEach(p=>owned.set(`${p.ProcessId}:${p.Created}`,p));report.owned=[...owned.values()];return result;
}
const invoke=(cmd,args)=>page.evaluate(({cmd,args})=>window.__TAURI_INTERNALS__.invoke(cmd,args),{cmd,args});
const snapshot=()=>invoke("backend_snapshot");
try{
  if(conflict){holder=spawn(conflictExe,[],{windowsHide:true,stdio:["pipe","pipe","pipe"]});let text="";holder.stdout.on("data",d=>text+=d);await wait(()=>text.includes("HOTKEY_HELD"),10000);}
  child=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","pipe","pipe"]});child.stderr.on("data",d=>stderr+=d);
  browser=await wait(async()=>{try{return await chromium.connectOverCDP(`http://127.0.0.1:${port}`);}catch{return null;}},30000);
  page=browser.contexts()[0].pages()[0];page.setDefaultTimeout(20000);
  await page.waitForSelector("#window-hide");
  const s=await wait(async()=>{const s=await snapshot();return ["READY","DEGRADED"].includes(s.state)&&s.info.diagnostics?s:null;});
  await collect();report.backend=s;report.voiceRuntime=await invoke("local_voice_snapshot");report.avatar=await invoke("live2d_snapshot");report.workflow=await invoke("desktop_workflow_snapshot");
  assert.equal(report.workflow.trayReady,true);
  assert.equal(report.workflow.shortcutReady,!conflict);
  if(conflict){assert.match(report.workflow.error,/注册失败/);assert.match(await page.locator("#workflow-alert").textContent(),/占用/);report.checks.push("actual OS registration conflict produces visible feedback");}
  if(missing){
    assert.equal(s.info.diagnostics.local_model.model_available,false);
    assert.equal(report.voiceRuntime.state,"DEGRADED");assert.equal(report.avatar.status,"error");
    assert.equal(await page.locator("#send-button").isDisabled(),true);
    await page.locator("#open-settings").click();
    await page.waitForSelector("[data-character-status]");
    assert.match(await page.locator("#settings-model-status").textContent(),/不可用/);
    assert.match(await page.locator("[data-voice-runtime-status]").textContent(),/缺失/);
    assert.match(await page.locator("[data-character-status]").textContent(),/关闭再开启/);
    await page.screenshot({path:directory+"/unavailable.png"});
    report.checks.push("real missing assets isolate Model/Voice/Avatar failure with actionable UI");
  } else {
    assert.equal(s.info.diagnostics.local_model.state,"READY");
    await wait(async()=>(await invoke("live2d_snapshot")).status==="ready");
    assert.equal(report.voiceRuntime.state,"READY");
    await page.waitForSelector("#new-conversation:not([disabled])");
    assert.equal(await page.locator("#send-button").isDisabled(),true);
    await page.locator("#new-conversation").click();
    await page.waitForSelector("#prompt-input:not([disabled])");
    const id=await page.locator(".conversation.active").getAttribute("data-conversation-id");
    await page.locator("#prompt-input").fill("V4-8A 未发送草稿");
    const before=await collect();
    for(let n=0;n<6;n++){
      await invoke("window_action",{action:"hide"});assert.equal(await invoke("plugin:window|is_visible"),false);
      assert.equal((await invoke("live2d_snapshot")).visible,true);
      await invoke("window_action",{action:"show"});assert.equal(await invoke("plugin:window|is_visible"),true);
      await page.waitForFunction(()=>document.activeElement?.id==="prompt-input");
      assert.equal(await page.locator("#prompt-input").inputValue(),"V4-8A 未发送草稿");
      assert.equal(await page.locator(".conversation.active").getAttribute("data-conversation-id"),id);
    }
    const critical=p=>["python.exe","llama-server.exe","aurora-local-voice-host.exe","aurora-live2d-host.exe"].includes(p.Name);
    assert.deepEqual((await collect()).filter(critical).map(p=>`${p.ProcessId}:${p.Created}`).sort(),before.filter(critical).map(p=>`${p.ProcessId}:${p.Created}`).sort());
    report.runtimeCounts=Object.fromEntries(["python.exe","llama-server.exe","aurora-local-voice-host.exe","aurora-live2d-host.exe"].map(name=>[name,before.filter(p=>p.Name===name).length]));
    for(const count of Object.values(report.runtimeCounts))assert.equal(count,1);
    const second=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:"ignore"});await once(second,"exit");
    assert.equal(await page.locator("#prompt-input").inputValue(),"V4-8A 未发送草稿");
    assert.deepEqual((await collect()).filter(critical).map(p=>p.ProcessId).sort(),before.filter(critical).map(p=>p.ProcessId).sort());
    report.checks.push("six actual show/hide cycles retain draft/conversation/avatar without duplicate runtimes","single-instance secondary launch restores existing window without duplicate runtime");
    await page.screenshot({path:directory+"/ready.png"});
  }
  await persist();
  await writeFile(root+"/current-runtime.json",JSON.stringify({pid:child.pid,port,directory,mode:report.mode},null,2));
  if(native){console.log("NATIVE_READY "+JSON.stringify({pid:child.pid,port,directory}));let sampled=0;await wait(async()=>{
    if(Date.now()-sampled>2000){await collect();await persist();sampled=Date.now();}
    return child.exitCode!==null;
  },3600000);}
  else {await invoke("window_action",{action:"close"}).catch(()=>{});await wait(()=>child.exitCode!==null,20000);}
  await wait(async()=>{report.remainingOwned=(await inventory()).filter(p=>owned.has(`${p.ProcessId}:${p.Created}`));return report.remainingOwned.length===0;},15000);
  report.checks.push("Exit leaves zero owned processes, including WebView descendants");report.status="AUTOMATED PASS";
}catch(e){report.status="FAILED";report.error=String(e);throw e;}
finally{
  if(child?.exitCode===null&&page)await invoke("window_action",{action:"close"}).catch(()=>{});
  if(holder){holder.stdin.end("release\n");await wait(()=>holder.exitCode!==null,10000);}
  await browser?.close().catch(()=>{});await writeFile(directory+"/stderr.txt",stderr);await persist();
  console.log(JSON.stringify({status:report.status,checks:report.checks,directory}));
}
