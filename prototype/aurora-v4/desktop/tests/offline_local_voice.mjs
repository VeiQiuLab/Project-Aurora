// Real Release WebView/native-runtime gate. No sidecar/provider substitution.
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {spawn,execFile} from "node:child_process";
import {promisify} from "node:util";
import {mkdir,mkdtemp,writeFile,readFile,readdir,link} from "node:fs/promises";
import {createServer} from "node:net";
import {once} from "node:events";
import {createHash} from "node:crypto";
const {chromium}=createRequire(import.meta.url)("playwright");
const exec=promisify(execFile);
const repo=fileURLToPath(new URL("../../../..",import.meta.url));
const exe=fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe",import.meta.url));
const ps=async code=>(await exec("powershell.exe",["-NoProfile","-Command",code],{windowsHide:true})).stdout.trim();
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,ms=120000){const end=Date.now()+ms;while(Date.now()<end){const value=await fn();if(value)return value;await delay(25);}throw Error("Offline gate deadline");}
assert.equal(Number(await ps("@(Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -in @('LM Studio','ollama','llama-server','aurora-v4-desktop','aurora-live2d-host','aurora-local-voice-host')}).Count")),0,"Do not overlap or terminate user runtimes");
assert.ok(process.env.AURORA_LIVE2D_CONFIG,"Existing private Live2D configuration required");
await mkdir(repo+"/tests/output/v47b3b-offline",{recursive:true});
const output=await mkdtemp(repo+"/tests/output/v47b3b-offline/run-");
await mkdir(output+"/app/config",{recursive:true});await mkdir(output+"/frames");
const disabled=process.argv.includes("--voice-disabled");
const short=process.argv.includes("--short");
const abrupt=process.argv.includes("--abrupt");
const negative=["runtime","model","lexicon","corrupt"].find(name=>process.argv.includes("--missing-"+name));
const tempParent=process.env.LOCALAPPDATA+"/Aurora/cache/local-voice";
const tempBefore=await readdir(tempParent).catch(()=>[]);
await writeFile(output+"/app/config/settings.json",JSON.stringify({
  ollama:{host:"http://127.0.0.1:1"},persona:{enabled:false},knowledge:{enabled:false},rag:{pipeline_enabled:false},
  voice:{enabled:false,tts:{provider:"local_sherpa_melo",timeout_seconds:30,remote_cosyvoice:{url:"http://127.0.0.1:1"}}},
  live2d:{enabled:true,visible:true,x:64,y:64}
}));
const server=createServer();server.listen(0,"127.0.0.1");await once(server,"listening");const port=server.address().port;await new Promise(r=>server.close(r));
const env={...process.env,AURORA_USER_DATA_DIR:output+"/app",WEBVIEW2_USER_DATA_FOLDER:output+"/webview",
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port}`,AURORA_LIVE2D_EVIDENCE_DIR:output+"/frames"};
for(const name of ["AURORA_V4_BACKEND","AURORA_V4_CHAT_PROVIDER","AURORA_V4_SIDECAR_DIR","AURORA_BENCH_HANDOFF",
  "AURORA_LOCAL_VOICE_DISABLE","AURORA_LOCAL_VOICE_ENDPOINT","AURORA_LOCAL_VOICE_TOKEN"])delete env[name];
if(disabled)env.AURORA_LOCAL_VOICE_DISABLE="1";
if(negative==="runtime")env.AURORA_LOCAL_VOICE_RUNTIME=output+"/missing-runtime";
if(negative){
  env.AURORA_LOCAL_VOICE_MODEL=output+"/negative-model";
  if(["lexicon","corrupt"].includes(negative)){
    await mkdir(env.AURORA_LOCAL_VOICE_MODEL);
    for(const file of ["model.onnx","tokens.txt","lexicon.txt","date.fst","number.fst"]){
      if(negative==="lexicon"&&file==="lexicon.txt")continue;
      if(negative==="corrupt"&&file==="model.onnx")await writeFile(env.AURORA_LOCAL_VOICE_MODEL+"/"+file,"corrupt fixture");
      else await link(process.env.LOCALAPPDATA+"/Aurora/models/melo-zh-en-v2/"+file,env.AURORA_LOCAL_VOICE_MODEL+"/"+file);
    }
  }
}
let desktop,browser,page,stderr="";const owned=new Map();
const report={status:"running",release:true,productionSidecar:true,fallback:"unsupported/off",disabled,abrupt,negative,tempBefore,
  releaseSha256:createHash("sha256").update(await readFile(exe)).digest("hex"),
  manualListening:"NOT MANUALLY VERIFIED",chats:[],benchmarks:[],soak:[],resources:[],playbacks:[]};
const invoke=(cmd,args)=>page.evaluate(({cmd,args})=>window.__TAURI_INTERNALS__.invoke(cmd,args),{cmd,args});
const snapshot=()=>invoke("backend_snapshot");const runtime=()=>invoke("local_voice_snapshot");const character=()=>invoke("live2d_snapshot");
async function processes(){
  const rows=JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "ParentProcessId = ${desktop.pid}" | Select-Object ProcessId,Name,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})`));
  rows.forEach(row=>owned.set(`${row.ProcessId}:${row.Created}`,row));return rows;
}
async function settings(patch){
  await page.locator("#open-settings").click();await page.waitForSelector("#settings-reload:not([disabled])");
  for(const [key,value] of Object.entries(patch)){
    const field=page.locator(`[data-setting-key="${key}"]`);
    if(typeof value==="boolean")await field.setChecked(value);else if(key==="voice.tts.provider")await field.selectOption(value);else await field.fill(String(value));
  }
  await page.locator("#settings-save").click();await wait(async()=>/^(已保存|设置已同步)/.test(await page.locator("#settings-status").textContent()),15000);
  await page.waitForSelector("#settings-reload:not([disabled])");await page.locator("#close-settings").click();
}
async function chat(label,text="请用四十个汉字介绍安静阅读的好处，不用列表。"){
  await page.locator("#new-conversation").click();await page.waitForSelector(".conversation.active");
  const old=await page.evaluate(()=>performance.getEntriesByName("aurora-terminal").at(-1)?.detail?.generationId);
  await page.locator("#prompt-input").fill(text);const start=performance.now();await page.locator("#send-button").click();
  const terminal=await wait(async()=>{const x=await page.evaluate(()=>performance.getEntriesByName("aurora-terminal").at(-1)?.detail);return x&&x.generationId!==old?x:null;});
  assert.equal(terminal.status,"completed");const row={label,requestMs:start,terminalMs:performance.now(),...terminal};report.chats.push(row);return row;
}
const texts=["你好，这是本机中文语音合成测试。",
  "今天我们在本机验证中文语音，模型保持常驻，不依赖远端电脑，也不使用网络语音服务。接下来检查播放是否完整。",
  "今天我们在本机验证完整的中文语音生成流程。文字首先进入本地语音模型，生成的音频随后交给播放层。整个过程不依赖远端电脑，也不调用网络语音服务。我们还需要检查模型常驻、停止后的恢复，以及与本地聊天模型共同运行时的资源占用。"];
async function speak(label,index=0,natural=false){
  const before=await runtime();const terminal=await chat(label,"请原样回复下面文字，不添加解释或引号：\n"+texts[index]);
  if(label==="warm_109_0")await resource("during_synthesis");
  await wait(async()=>{const state=(await snapshot()).voice;if(state?.state==="error")throw Error(state.error_code);return state?.generation_id===terminal.generationId&&state.state==="speaking";},15000);
  const ready=performance.now(),diag=await runtime(),mouths=[];
  assert.ok(diag.completed_requests>before.completed_requests);assert.ok(diag.audio_seconds>0);
  await wait(async()=>{const c=await character();mouths.push(c.mouth);return c.mouth>.05;},6000);
  if(natural){await wait(async()=>(await snapshot()).voice.state==="idle",60000);}
  else {const stop=performance.now();await page.locator("#voice-stop").click();await wait(async()=>(await snapshot()).voice.state==="idle",5000);report.playbacks.push({label,stopMs:performance.now()-stop});}
  await wait(async()=>(await character()).mouth===0,5000);
  const row={label,expectedChars:[...texts[index]].length,actualChars:diag.text_chars,synthesisMs:diag.synthesis_ms,
    audioSeconds:diag.audio_seconds,rtf:diag.synthesis_ms/1000/diag.audio_seconds,terminalToAudioReadyMs:ready-terminal.terminalMs,
    runtime:diag,character:await character(),maxMouth:Math.max(...mouths),natural};
  assert.equal(row.actualChars,row.expectedChars);assert.ok(row.rtf<1);
  if(label.startsWith("warm_16_"))assert.ok(row.terminalToAudioReadyMs<2000);
  report.benchmarks.push(row);
  console.log(JSON.stringify({label,chars:row.actualChars,ms:row.synthesisMs,rtf:row.rtf,terminalToReady:row.terminalToAudioReadyMs}));return row;
}
async function resource(label){
  let code=await readFile(new URL("./live2d_resources.ps1",import.meta.url),"utf8");
  code=code.replace("$taskSeconds = $taskClock.Elapsed.TotalSeconds","$taskEndCpu = @{}\n$taskProcesses | ForEach-Object { $taskEndCpu[$_.Id] = $_.TotalProcessorTime.TotalSeconds }\n$taskSeconds = $taskClock.Elapsed.TotalSeconds")
    .replace("($_.TotalProcessorTime.TotalSeconds - $taskStart[$taskPid])","($taskEndCpu[$taskPid] - $taskStart[$taskPid])");
  report.resources.push({label,sample:JSON.parse(await ps(`& { ${code} } -TargetProcessId ${desktop.pid}`)),runtime:await runtime(),character:await character()});
}
try{
  const start=performance.now();desktop=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","ignore","pipe"]});desktop.stderr.on("data",data=>stderr+=data);
  browser=await wait(async()=>{try{return await chromium.connectOverCDP(`http://127.0.0.1:${port}`);}catch{return null;}},30000);
  page=await wait(()=>browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().startsWith("http://tauri.localhost")),15000);
  page.setDefaultTimeout(15000);await page.waitForSelector("#send-button",{timeout:30000});report.firstScreenMs=performance.now()-start;
  await wait(async()=>(await snapshot()).info.chat_enabled);report.chatReadyMs=performance.now()-start;
  if(!disabled&&!negative){await wait(async()=>{const s=await runtime();if(s.state==="DEGRADED"||s.state==="FAILED")throw Error(s.error_code);return s.state==="READY";},35000);report.voiceReadyMs=performance.now()-start;}
  await wait(async()=>{const c=await character();return c.status==="ready"&&c.visible&&c.fps>0;});await processes();
  report.initial={backend:await snapshot(),runtime:await runtime(),character:await character()};
  await page.screenshot({path:output+"/desktop.png"});
  for(let i=0;i<(abrupt||negative?1:5);i++)await chat((disabled?"disabled":"resident")+"_baseline_"+i);
  await resource("resident_idle");
  if(negative){
    const expected={runtime:"VOICE_RUNTIME_MISSING",model:"VOICE_MODEL_MISSING",lexicon:"VOICE_LEXICON_MISSING",corrupt:"VOICE_ASSET_HASH_MISMATCH"}[negative];
    await wait(async()=>(await runtime()).state==="DEGRADED",35000);assert.equal((await runtime()).error_code,expected);
    await settings({"voice.enabled":true});await chat("missing_assets_chat");
    await wait(async()=>(await snapshot()).voice.state==="error",5000);assert.equal((await snapshot()).voice.error_code,"VOICE_UNAVAILABLE");
    assert.equal((await character()).mouth,0);report.negativeResult={runtime:await runtime(),backend:await snapshot(),character:await character()};
  }
  if(abrupt&&!disabled&&!negative){await settings({"voice.enabled":true});await speak("abrupt_owner_playback",0);}
  if(!disabled&&!negative&&!abrupt){
    await settings({"voice.enabled":true});
    await speak("first_synthesis",0,true);await speak("second_round",0,true);
    for(const index of [0,1,2])for(let i=0;i<5;i++)await speak(`warm_${[16,52,109][index]}_${i}`,index);
    const before=await runtime();const terminal=await chat("stop_synthesis","请原样回复下面文字，不添加解释或引号：\n"+texts[2]);
    await wait(async()=>{const state=(await snapshot()).voice;return state?.generation_id===terminal.generationId&&state.state==="preparing";},3000);
    const stopped=performance.now();await page.locator("#voice-stop").click();await wait(async()=>(await snapshot()).voice.state==="idle",5000);
    report.stopSynthesisMs=performance.now()-stopped;
    for(let i=0;i<70;i++){const state=(await snapshot()).voice;assert.notEqual(state.state,"speaking");assert.equal((await character()).mouth,0);await delay(100);}
    report.stale={before,after:await runtime()};assert.equal(report.stale.after.completed_requests,before.completed_requests);
    assert.ok(report.stale.after.discarded_requests>before.discarded_requests);
    await speak("after_cancel_recovery");
    await settings({"voice.enabled":false});
    const hosts=(await processes()).filter(p=>p.Name==="aurora-local-voice-host.exe");assert.equal(hosts.length,1);
    const crashedAt=performance.now();await ps(`Stop-Process -Id ${hosts[0].ProcessId}`);
    await chat("chat_survives_voice_crash");
    await wait(async()=>(await runtime()).state==="READY",35000);report.recoveryMs=performance.now()-crashedAt;
    await processes();await settings({"voice.enabled":true});await speak("voice_after_crash",0,true);
    await resource("before_soak");
    if(!short)for(const [index,count] of [[0,50],[1,10],[2,5]])for(let i=0;i<count;i++)report.soak.push(await speak(`soak_${[16,52,109][index]}_${i}`,index));
    await resource("after_soak");await settings({"voice.enabled":false});
    for(let i=0;i<5;i++)await chat("post_tts_"+i);
  }
  await processes();await resource("post_tts");report.status="passed";
}catch(error){report.status="failed";report.error=String(error);throw error;}
finally{
  if(desktop?.exitCode===null){if(abrupt||!page)desktop.kill();else await invoke("window_action",{action:"close"}).catch(()=>{});await wait(()=>desktop.exitCode!==null,15000).catch(()=>desktop.kill());}
  await browser?.close().catch(()=>{});await delay(1000);
  const rows=JSON.parse(await ps("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object ProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})"));
  report.tempAfter=await readdir(tempParent).catch(()=>[]);
  report.remainingOwned=rows.filter(row=>owned.has(`${row.ProcessId}:${row.Created}`));
  report.edgeRequests=(stderr.match(/event=voice_provider_request provider=edge_tts/g)||[]).length;
  report.remoteRequests=(stderr.match(/event=voice_provider_request provider=remote_cosyvoice/g)||[]).length;
  report.localRequests=(stderr.match(/event=voice_provider_request provider=local_sherpa_melo/g)||[]).length;
  report.gpuFrames=[];for(const file of await readdir(output+"/frames"))if(file.endsWith(".json"))report.gpuFrames.push(JSON.parse(await readFile(output+"/frames/"+file,"utf8")));
  const validationErrors=[];
  if(report.remainingOwned.length)validationErrors.push("owned process residue");
  if(report.edgeRequests||report.remoteRequests)validationErrors.push("unexpected network provider call");
  if(!disabled&&report.status==="passed"&&!report.localRequests)validationErrors.push("missing Local request evidence");
  if(!disabled&&!negative&&report.status==="passed"&&(!report.gpuFrames.some(frame=>frame.actual_mouth>.05)||!report.gpuFrames.some(frame=>frame.actual_mouth===0)))validationErrors.push("missing actual GPU mouth/reset evidence");
  if(!abrupt&&report.tempAfter.length)validationErrors.push("voice session temp residue");
  if(validationErrors.length){report.status="failed";report.error=validationErrors.join(", ");}
  await writeFile(output+"/report.json",JSON.stringify(report,null,2));await writeFile(output+"/desktop.log",stderr);
  console.log(JSON.stringify({status:report.status,output,remainingOwned:report.remainingOwned,edge:report.edgeRequests,remote:report.remoteRequests,error:report.error}));
  assert.equal(validationErrors.length,0,report.error);
  assert.equal(report.remainingOwned.length,0);assert.equal(report.edgeRequests,0);assert.equal(report.remoteRequests,0);
  if(!disabled&&report.status==="passed")assert.ok(report.localRequests>0);
}
