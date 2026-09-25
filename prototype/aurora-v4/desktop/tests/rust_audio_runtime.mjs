// Opt-in Release/WebView2 + built-in Vulkan LLM + actual Edge/Rust Audio smoke.
// Synthetic conversations and disposable authoritative settings only.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { spawn, execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdir, mkdtemp, writeFile, readFile, readdir } from "node:fs/promises";
import { createServer } from "node:net";
import { once } from "node:events";
import { tmpdir } from "node:os";
const { chromium } = createRequire(import.meta.url)("playwright");
const exec = promisify(execFile);
const repo = fileURLToPath(new URL("../../../..", import.meta.url));
const exe = fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe", import.meta.url));
const output = `${repo}/tests/output/b3-rust-audio`;
await mkdir(output, {recursive:true});
const sandbox = await mkdtemp(`${output}/run-`);
const ps = async code => (await exec("powershell.exe", ["-NoProfile","-Command",code], {windowsHide:true})).stdout.trim();
const processes = async () => JSON.parse(await ps("ConvertTo-Json -Compress -InputObject @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in @('LM Studio','ollama','llama-server','aurora-v4-desktop') } | Select-Object ProcessName,Id)"));
assert.equal((await processes()).length,0,"Close existing user runtimes before isolated smoke.");
await mkdir(`${sandbox}/app/config`, {recursive:true});
await writeFile(`${sandbox}/app/config/settings.json`, JSON.stringify({
  ollama:{host:"http://127.0.0.1:1"}, persona:{enabled:false}, knowledge:{enabled:false}, rag:{pipeline_enabled:false},
  voice:{enabled:false,tts:{provider:"edge_tts",timeout_seconds:20,remote_cosyvoice:{url:"http://127.0.0.1:1"}}}
}));
const portServer=createServer();portServer.listen(0,"127.0.0.1");await once(portServer,"listening");
const port=portServer.address().port;await new Promise(r=>portServer.close(r));
const env={...process.env,AURORA_USER_DATA_DIR:`${sandbox}/app`,WEBVIEW2_USER_DATA_FOLDER:`${sandbox}/webview`,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port}`};
delete env.AURORA_V4_BACKEND;delete env.AURORA_V4_CHAT_PROVIDER;
const priorRoots=new Set((await readdir(tmpdir())).filter(n=>n.startsWith("aurora-v4-audio-")));
const audioRoots=async()=> (await readdir(tmpdir())).filter(n=>n.startsWith("aurora-v4-audio-")&&!priorRoots.has(n));
const resourceSamples=[];
async function resources() {
  const pids=[child.pid,...owned.filter(p=>p.Name.toLowerCase()==="python.exe").map(p=>p.ProcessId)];
  resourceSamples.push(JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-Process -Id ${pids.join(",")} | Select-Object Id,HandleCount,@{n="Threads";e={$_.Threads.Count}})`)));
  const roots=await audioRoots();assert.equal(roots.length,1);
  assert.equal((await readdir(`${tmpdir()}/${roots[0]}`)).length,0,"Per-turn audio must be deleted after idle");
}
const report={release:true,externalServicesClosed:true,provider:"edge_tts",turns:[],manualAudio:"NOT MANUALLY VERIFIED"};
let child,browser,page,stderr="",owned=[];
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(predicate,timeout=90000) {
  const end=Date.now()+timeout;
  while(Date.now()<end){const v=await predicate();if(v)return v;await delay(50);}
  throw new Error("Smoke deadline exceeded");
}
const snapshot=()=>page.evaluate(()=>window.__TAURI_INTERNALS__.invoke("backend_snapshot"));
const marks=()=>page.evaluate(()=>performance.getEntriesByName("aurora-terminal").map(x=>x.detail));
async function launch() {
  child=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","pipe","pipe"]});
  child.stderr.on("data",d=>{stderr+=d.toString();});
  browser=await wait(async()=>{try{return await chromium.connectOverCDP(`http://127.0.0.1:${port}`);}catch{return null;}},30000);
  page=browser.contexts()[0].pages()[0];
  page.setDefaultTimeout(15000);
  await page.waitForSelector("#open-settings");
  const ready=await wait(async()=>{const s=await snapshot();return s.state==="READY"&&s.info.diagnostics?.local_model?.state==="READY"?s:null;});
  report.localModel=ready.info.diagnostics.local_model;
  owned=JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "ParentProcessId = ${child.pid}" | Select-Object Name,ProcessId)`));
  assert.ok(owned.some(p=>p.Name.toLowerCase()==="llama-server.exe"));
  assert.ok(owned.some(p=>p.Name.toLowerCase()==="python.exe"));
  await wait(async()=>(await snapshot()).voice);
}
async function settings(patch) {
  await page.locator("#open-settings").click();
  await page.waitForSelector('[data-setting-key="voice.enabled"]');
  await page.waitForSelector('#settings-reload:not([disabled])');
  for(const [key,value] of Object.entries(patch)) {
    const input=page.locator(`[data-setting-key="${key}"]`);
    if(typeof value==="boolean")await input.setChecked(value);
    else if(key==="voice.tts.provider")await input.selectOption(value);
    else await input.fill(String(value));
  }
  await page.locator("#settings-save").click();
  await wait(async()=>{
    const status=await page.locator('#settings-status').textContent();
    if(status.includes('未能保存')||status.includes('校验')||status.includes('其他位置'))throw new Error(`Settings save failed: ${status}`);
    return status.startsWith('已保存')||status.startsWith('设置已同步');
  },10000);
  // Persistence may precede the response and descriptor refresh. Do not reopen
  // the panel with the previous save still in flight and edit stale controls.
  await page.waitForSelector('#settings-reload:not([disabled])');
  // Opening the JSON repeatedly during Windows atomic replace can itself cause
  // a sharing violation. Read only after the authoritative save acknowledgement.
  const cfg=JSON.parse(await readFile(`${sandbox}/app/config/settings.json`,"utf8"));
  assert.ok(Object.entries(patch).every(([k,v])=>k.split('.').reduce((o,p)=>o?.[p],cfg)===v));
  await page.locator("#close-settings").click();
}
async function begin(text) {
  const previous=(await marks()).at(-1)?.generationId??null;
  await page.locator("#prompt-input").fill(text);await page.locator("#send-button").click();
  return previous;
}
async function terminal(previous) {
  const result=await wait(async()=>{const m=(await marks()).at(-1);return m&&m.generationId!==previous?m:null;});
  report.turns.push(result);return result;
}
async function turn(text) {
  const result=await terminal(await begin(text));assert.equal(result.status,"completed");return result;
}
async function speaking(generationId) {
  return wait(async()=>{
    const v=(await snapshot()).voice;
    if(v?.generation_id===generationId&&v.state==="error")throw new Error(`Real provider failed: ${v.error_code}`);
    return v?.generation_id===generationId&&v.state==="speaking"?v:null;
  });
}
async function shutdown() {
  if(child.exitCode===null&&child.signalCode===null) {
    await page.evaluate(()=>window.__TAURI_INTERNALS__.invoke("window_action",{action:"close"})).catch(()=>{});
    await wait(()=>child.exitCode!==null||child.signalCode!==null,15000);
  }
  await browser?.close().catch(()=>{});
  await wait(async()=>{
    const ids=owned.map(p=>p.ProcessId);
    return JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Id -in @(${ids.join(',')}) })`)).length===0;
  },10000);
}
try {
  await launch();
  await page.locator("#new-conversation").click();
  await page.waitForSelector(".conversation.active");
  const disabled=await turn("请只回复：语音关闭测试。");
  assert.ok(disabled.delta_count>1);assert.equal((await snapshot()).voice.state,"idle");
  report.disabled=true;
  await settings({"voice.enabled":true});
  const normal=await turn("请写一段一百字左右的中文日常问候，不使用列表，不使用表情。");
  await speaking(normal.generationId);report.playbackStarted=true;
  await page.screenshot({path:`${output}/speaking.png`});
  const stopAt=performance.now();await page.locator("#voice-stop").click();
  await wait(async()=>(await snapshot()).voice.state==="idle",10000);
  report.stopToIdleMs=performance.now()-stopAt;report.stop=true;
  const recovery=await turn("请只回复：语音恢复成功。");
  await speaking(recovery.generationId);
  await wait(async()=>(await snapshot()).voice.state==="idle");report.recovery=true;
  await resources();
  for(let n=0;n<4;n++) {
    const repeated=await turn("请只回复：连续播放检查正常。");await speaking(repeated.generationId);
    await wait(async()=>(await snapshot()).voice.state==="idle");await resources();
  }
  report.resourceSamples=resourceSamples;
  for(let p=0;p<2;p++) {
    assert.ok(resourceSamples.at(-1)[p].Threads<=resourceSamples[0][p].Threads+8);
    assert.ok(resourceSamples.at(-1)[p].HandleCount<=resourceSamples[0][p].HandleCount+64);
  }
  report.boundedResources=true;
  const old=await begin("请连续写一百条长建议，每条三句话，不要省略。");
  await page.waitForFunction(()=>performance.getEntriesByName("aurora-first-frontend-delta").length>0);
  await page.locator("#stop-button").click();
  const cancelled=await terminal(old);assert.equal(cancelled.status,"cancelled");
  assert.equal((await snapshot()).voice.state,"idle");report.chatCancelNoVoice=true;
  await settings({"voice.enabled":false});
  await turn("只回复：关闭后仍然正常。");
  assert.equal((await snapshot()).voice.state,"idle");report.disableAfterStop=true;
  await settings({"voice.enabled":true,"voice.tts.provider":"remote_cosyvoice"});
  const failedVoice=await turn("只回复：语音失败不影响聊天。");
  const failure=await wait(async()=>{const v=(await snapshot()).voice;return v?.generation_id===failedVoice.generationId&&v.state==="error"?v:null;});
  assert.equal(failure.error_code,"VOICE_UNAVAILABLE");report.failureIsolation=true;
  const historyFile=(await readdir(`${sandbox}/app/conversations`)).find(f=>f.endsWith('.json'));
  const persisted=JSON.parse(await readFile(`${sandbox}/app/conversations/${historyFile}`,"utf8"));
  assert.ok(persisted.messages.some(m=>m.role==="assistant"&&m.content.includes("语音失败不影响聊天")));
  report.persistence=true;
  await settings({"voice.tts.provider":"fake"});
  const badAudio=await turn("请只回复：音频失败不影响聊天。");
  const decodeFailure=await wait(async()=>{const v=(await snapshot()).voice;return v?.generation_id===badAudio.generationId&&v.state==="error"?v:null;});
  assert.equal(decodeFailure.error_code,"PLAYBACK_FAILED");
  const savedAfterError=JSON.parse(await readFile(`${sandbox}/app/conversations/${historyFile}`,"utf8"));
  assert.ok(savedAfterError.messages.some(m=>m.role==="assistant"&&m.content.includes("音频失败不影响聊天")));
  report.decoderFailureIsolation=true;
  await settings({"voice.tts.provider":"edge_tts"});
  const last=await turn("请写一段一百字左右的中文散文，不使用列表。");
  await speaking(last.generationId);
  await shutdown();report.closeDuringPlayback=true;report.noOrphans=true;
  await launch();
  assert.equal((await snapshot()).voice.enabled,true);assert.equal((await snapshot()).voice.provider,"edge_tts");
  report.settingsRestored=true;await shutdown();
  assert.ok(!stderr.includes("event=voice_schedule_failed"));
  assert.equal((await audioRoots()).length,0);report.audioRootsCleaned=true;
  assert.ok((stderr.match(/event=rust_audio_started backend=rodio/g)||[]).length>=7);
  assert.ok(stderr.includes("error_code=AUDIO_DECODE_FAILED"));
  assert.ok(stderr.includes("event=audio_handoff backend=rust python_audio_loaded=False"));
  assert.ok(!stderr.includes("python_audio_loaded=True"));
  assert.ok(stderr.includes("event=sidecar_shutdown forced=false"));
  assert.ok(!stderr.includes("event=sidecar_shutdown forced=true"),"Normal close must not rely on killing Python");
  report.gracefulShutdown=true;
  assert.equal((stderr.match(/event=rust_audio_worker_started/g)||[]).length,(stderr.match(/event=rust_audio_worker_exited/g)||[]).length);
  report.rustPlayback=true;report.status="passed";
} catch(error) {
  report.status="failed";report.error=String(error);
  if(page)report.lastSnapshot=await snapshot().catch(()=>null);
  if(page)report.settingsStatus=await page.locator('#settings-status').textContent().catch(()=>null);
  throw error;
} finally {
  if(child&&child.exitCode===null&&child.signalCode===null) {
    await shutdown().catch(()=>child.kill());
  }
  await browser?.close().catch(()=>{});
  report.audioLog=stderr.split(/\r?\n/).filter(l=>/event=rust_audio/.test(l));
  report.voiceLog=stderr.split(/\r?\n/).filter(l=>/event=voice_state/.test(l));
  report.shutdownLog=stderr.split(/\r?\n/).filter(l=>/event=sidecar_shutdown/.test(l));
  await writeFile(`${output}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
