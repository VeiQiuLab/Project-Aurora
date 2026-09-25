// Opt-in real Release, real Cubism model, Vulkan LLM and Edge/Rust Audio.
// All settings/history are disposable. No SDK/model assets are written.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { spawn, execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdir, mkdtemp, writeFile, readFile, readdir } from "node:fs/promises";
import { createServer } from "node:net";
import { once } from "node:events";
const {chromium}=createRequire(import.meta.url)("playwright");
const exec=promisify(execFile);
const repo=fileURLToPath(new URL("../../../..",import.meta.url));
const exe=fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe",import.meta.url));
assert.ok(process.env.AURORA_LIVE2D_CONFIG,"Provide private AURORA_LIVE2D_CONFIG");
const lifecycleOnly=process.argv.includes("--lifecycle-only");
const output=repo+"/tests/output/"+(lifecycleOnly?"live2d-desktop-lifecycle":"live2d-desktop");
await mkdir(output,{recursive:true});
const sandbox=await mkdtemp(output+"/run-");
const ps=async code=>(await exec("powershell.exe",["-NoProfile","-Command",code],{windowsHide:true})).stdout.trim();
assert.equal(Number(await ps("@(Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -in @('LM Studio','ollama','llama-server','aurora-v4-desktop','aurora-live2d-host')}).Count")),0,"Close user runtimes first; never terminate user instances.");
await mkdir(sandbox+"/app/config",{recursive:true});
await writeFile(sandbox+"/app/config/settings.json",JSON.stringify({
  ollama:{host:"http://127.0.0.1:1"},persona:{enabled:false},knowledge:{enabled:false},rag:{pipeline_enabled:false},
  voice:{enabled:false,tts:{provider:"edge_tts",timeout_seconds:20,remote_cosyvoice:{url:"http://127.0.0.1:1"}}},
  live2d:{enabled:false,visible:true,x:64,y:64}
}));
const portServer=createServer();portServer.listen(0,"127.0.0.1");await once(portServer,"listening");
const port=portServer.address().port;await new Promise(r=>portServer.close(r));
const env={...process.env,AURORA_USER_DATA_DIR:sandbox+"/app",WEBVIEW2_USER_DATA_FOLDER:sandbox+"/webview",WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port}`};
delete env.AURORA_V4_BACKEND;delete env.AURORA_V4_CHAT_PROVIDER;
const report={release:true,externalServicesClosed:true,route:"NEW MINIMAL NATIVE HOST",measurements:[],manual:"NOT MANUALLY VERIFIED",remoteRealPlayback:"NOT TESTED IN THIS STAGE"};
let child,browser,page,stderr="",owned=new Map();
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,ms=90000){const end=Date.now()+ms;while(Date.now()<end){const v=await fn();if(v)return v;await delay(50);}throw Error("Smoke deadline exceeded");}
const invoke=(cmd,args)=>page.evaluate(({cmd,args})=>window.__TAURI_INTERNALS__.invoke(cmd,args),{cmd,args});
const snapshot=()=>invoke("backend_snapshot");
const character=()=>invoke("live2d_snapshot");
const characterReady=()=>wait(async()=>{const c=await character();if(c.status==="error")throw Error(c.error_code);return c.status==="ready";},30000);
const marks=()=>page.evaluate(()=>performance.getEntriesByName("aurora-terminal").map(x=>x.detail));
async function children(){
  const rows=JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "ParentProcessId = ${child.pid}" | Select-Object Name,ProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})`));
  rows.forEach(p=>owned.set(`${p.ProcessId}:${p.Created}`,p));return rows;
}
async function remainingOwned(){
  // Windows reuses PIDs, including during the restart in this same smoke.
  // Match process identity, not an accumulated set of numeric PIDs alone.
  const rows=JSON.parse(await ps("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object Name,ProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})"));
  return rows.filter(p=>owned.has(`${p.ProcessId}:${p.Created}`));
}
async function launch(){
  child=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","pipe","pipe"]});
  child.stderr.on("data",d=>stderr+=d.toString());
  browser=await wait(async()=>{try{return await chromium.connectOverCDP(`http://127.0.0.1:${port}`);}catch{return null;}},30000);
  page=browser.contexts()[0].pages()[0];page.setDefaultTimeout(15000);
  await page.waitForSelector("#open-settings");
  const s=await wait(async()=>{const s=await snapshot();return s.state==="READY"&&s.info.diagnostics?.local_model?.state==="READY"?s:null;});
  report.localModel=s.info.diagnostics.local_model;
  await children();
}
async function settings(patch){
  await page.locator("#open-settings").click();
  await page.waitForSelector('[data-setting-key="live2d.enabled"]');
  await page.waitForSelector("#settings-reload:not([disabled])");
  for(const [key,value] of Object.entries(patch)){
    const input=page.locator(`[data-setting-key="${key}"]`);
    if(typeof value==="boolean")await input.setChecked(value);
    else if(key==="voice.tts.provider")await input.selectOption(value);
    else await input.fill(String(value));
  }
  await page.locator("#settings-save").click();
  await wait(async()=>{const s=await page.locator("#settings-status").textContent();if(/未能保存|校验|其他位置/.test(s))throw Error(s);return s.startsWith("已保存")||s.startsWith("设置已同步");},10000);
  await page.waitForSelector("#settings-reload:not([disabled])");
  const saved=JSON.parse(await readFile(sandbox+"/app/config/settings.json","utf8"));
  assert.ok(Object.entries(patch).every(([k,v])=>k.split(".").reduce((o,p)=>o?.[p],saved)===v));
  await page.locator("#close-settings").click();
}
async function turn(){
  await page.locator("#new-conversation").click();await page.waitForSelector(".conversation.active");
  const prior=(await marks()).at(-1)?.generationId;
  await page.locator("#prompt-input").fill("请用四十个汉字左右介绍安静阅读的好处，不用列表，不用标题。");
  await page.locator("#send-button").click();
  const states=new Set();
  const result=await wait(async()=>{
    states.add((await character()).state);
    const m=(await marks()).at(-1);return m&&m.generationId!==prior?m:null;
  });
  assert.equal(result.status,"completed");assert.ok(result.delta_count>1);
  return {...result,characterStates:[...states]};
}
async function sample(){
  const script=fileURLToPath(new URL("./live2d_resources.ps1",import.meta.url));
  const code=await readFile(script,"utf8");
  return JSON.parse(await ps(`& { ${code} } -TargetProcessId ${child.pid}`));
}
async function speaking(g){
  await wait(async()=>{const v=(await snapshot()).voice;if(v?.generation_id===g&&v.state==="error")throw Error(v.error_code);return v?.generation_id===g&&v.state==="speaking";});
}
async function stopVoice(){
  await page.locator("#voice-stop").click();
  await wait(async()=>(await snapshot()).voice.state==="idle",10000);
}
async function shutdown(){
  await children();
  if(child.exitCode===null&&child.signalCode===null){
    await invoke("window_action",{action:"close"}).catch(()=>{});
    await wait(()=>child.exitCode!==null||child.signalCode!==null,15000);
  }
  await browser?.close().catch(()=>{});
  await wait(async()=>{
    report.remainingOwnedProcesses=await remainingOwned();
    return report.remainingOwnedProcesses.length===0;
  },10000);
}
try{
  await launch();
  assert.equal((await character()).status,"disabled");
  assert.ok(!(await children()).some(p=>p.Name==="aurora-live2d-host.exe"));
  report.disabledNoHost=true;
  await turn(); // warm-up excluded from comparisons
  for(const mode of (lifecycleOnly?["speaking"]:["disabled","visible_idle","speaking"])){
    if(mode==="visible_idle"||lifecycleOnly){
      await settings({"live2d.enabled":true});
      await characterReady();
      await children();
    }
    if(mode==="speaking")await settings({"voice.enabled":true});
    for(let n=0;n<(lifecycleOnly?1:3);n++){
      const t=await turn();
      if(mode==="speaking"){await speaking(t.generationId);await wait(async()=>(await character()).state==="speaking");}
      const resources=lifecycleOnly?null:await sample(),state=await character();
      report.measurements.push({mode,round:n,turn:t,character:state,resources});
      console.log(`Measured ${mode} round ${n + 1}`);
      if(mode==="speaking"){
        await stopVoice();await wait(async()=>(await character()).state==="idle");report.voiceStopIdle=true;
      }
    }
  }
  assert.ok(report.measurements.some(m=>m.mode!=="disabled"&&m.turn.characterStates.includes("thinking")));
  report.thinking=true;report.speaking=true;
  await settings({"live2d.visible":false,"live2d.x":120,"live2d.y":80});
  await wait(async()=>{const c=await character();return c.status==="ready"&&!c.visible&&c.fps===0;},10000);
  const hidden=await turn();await speaking(hidden.generationId);await stopVoice();report.hiddenVoice=true;
  await settings({"live2d.visible":true});
  await wait(async()=>{const c=await character();return c.visible&&c.fps>0;},10000);
  const host=(await children()).find(p=>p.Name==="aurora-live2d-host.exe");assert.ok(host);
  // Kill only the verified child created by this smoke; inject native crash.
  await ps(`Stop-Process -Id ${host.ProcessId} -Force`);
  await wait(async()=>(await character()).status==="error",10000);
  const recovery=await turn();await speaking(recovery.generationId);await stopVoice();
  assert.equal((await snapshot()).info.diagnostics.local_model.state,"READY");
  assert.equal((await character()).status,"error");report.rendererCrashIsolation=true;
  await settings({"live2d.enabled":false});await wait(async()=>(await character()).status==="disabled");
  await settings({"live2d.enabled":true});await characterReady();await children();
  await settings({"voice.tts.provider":"remote_cosyvoice"});
  const remote=await turn();await wait(async()=>{const v=(await snapshot()).voice;return v?.generation_id===remote.generationId&&v.state==="error";});
  report.remoteUnavailableIsolated=true;
  await settings({"voice.tts.provider":"edge_tts"});
  const last=await turn();await speaking(last.generationId);
  await shutdown();report.closeDuringPlayback=true;report.noOwnedChildren=true;
  await launch();await characterReady();
  report.persistedEnableRestored=true;await shutdown();
  const conversations=await readdir(sandbox+"/app/conversations");
  assert.ok(conversations.some(p=>p.endsWith(".json")));report.persistence=true;
  assert.ok(stderr.includes("event=rust_audio_started backend=rodio"));
  assert.ok(stderr.includes("python_audio_loaded=False"));
  assert.ok(!stderr.includes("event=sidecar_shutdown forced=true"));
  report.rustAudio=true;report.status="passed";
}catch(e){report.status="failed";report.error=String(e);report.lastCharacter=await character().catch(()=>null);throw e;}
finally{
  if(child?.exitCode===null&&child?.signalCode===null)await shutdown().catch(()=>child.kill());
  await browser?.close().catch(()=>{});
  await writeFile(output+"/report.json",JSON.stringify(report,null,2));
  await writeFile(output+"/stderr.log",stderr);
  console.log(JSON.stringify(report,null,2));
}
