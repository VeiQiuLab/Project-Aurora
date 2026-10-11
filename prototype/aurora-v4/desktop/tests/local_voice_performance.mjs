// V4-7B.1 experiment only. Existing Release and separately owned offline probe.
// No production Local provider/Supervisor and no transport streaming are added.
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {spawn,execFile} from "node:child_process";
import {promisify} from "node:util";
import {mkdir,mkdtemp,writeFile,readFile} from "node:fs/promises";
import {createServer} from "node:net";
import {once} from "node:events";
import {createInterface} from "node:readline";
import {createHash} from "node:crypto";
const {chromium}=createRequire(import.meta.url)("playwright");
const exec=promisify(execFile);
const repo=fileURLToPath(new URL("../../../..",import.meta.url));
const exe=fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe",import.meta.url));
for(const k of ["AURORA_PROBE_PYTHON","AURORA_PROBE_SOURCE","AURORA_PROBE_MODEL","AURORA_PROBE_PROMPT","AURORA_LIVE2D_CONFIG"])assert.ok(process.env[k],k);
const scheduling=process.env.AURORA_BENCH_SCHEDULE??"serial";
assert.ok(["serial","concurrent","resident"].includes(scheduling));
const variant=process.env.AURORA_BENCH_VARIANT??"base";
assert.ok(["base","half","f0cpu","halff0","fp32"].includes(variant));
const internalStream=process.env.AURORA_BENCH_STREAM==="true";
const shortOnly=process.env.AURORA_BENCH_SHORT==="true";
const playback=process.env.AURORA_BENCH_PLAYBACK==="true";
const strict=process.env.AURORA_BENCH_STRICT==="true";
assert.ok(!strict||!playback,"Strict isolation must not masquerade as production playback semantics");
const profile=process.env.AURORA_BENCH_PROFILE!=="false";
const sampleDuringSynthesis=process.env.AURORA_BENCH_SAMPLE!=="false";
const ps=async code=>(await exec("powershell.exe",["-NoProfile","-Command",code],{windowsHide:true})).stdout.trim();
assert.equal(Number(await ps("@(Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -in @('LM Studio','ollama','llama-server','aurora-v4-desktop','aurora-live2d-host')}).Count")),0,"Do not kill user runtimes");
const output=repo+"/tests/output/v47b1-coexist";
await mkdir(output,{recursive:true});const sandbox=await mkdtemp(output+"/run-");
await mkdir(sandbox+"/app/config",{recursive:true});
await writeFile(sandbox+"/app/config/settings.json",JSON.stringify({voice:{enabled:false},live2d:{enabled:true,visible:true},persona:{enabled:false},knowledge:{enabled:false},rag:{pipeline_enabled:false}}));
const listener=createServer();listener.listen(0,"127.0.0.1");await once(listener,"listening");const port=listener.address().port;await new Promise(r=>listener.close(r));
const env={...process.env,AURORA_USER_DATA_DIR:sandbox+"/app",WEBVIEW2_USER_DATA_FOLDER:sandbox+"/webview",WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port}`};
delete env.AURORA_V4_BACKEND;delete env.AURORA_V4_CHAT_PROVIDER;
delete env.AURORA_V4_SIDECAR_DIR;delete env.AURORA_BENCH_HANDOFF;
if(playback||strict){
  await mkdir(sandbox+"/handoff");
  env.AURORA_V4_SIDECAR_DIR=repo+"/scripts/voice_feasibility_sidecar";
  env.AURORA_BENCH_HANDOFF=sandbox+"/handoff";
}
let desktop,probe,browser,page,stderr="",probeLog="",ready=false,voiceResults=[],owned=[];
const report={status:"running",scheduling,variant,internalStream,profile,sampleDuringSynthesis,strictNoBackgroundInference:strict,automaticVoiceStartup:false,edgeUsed:false,measurements:[],resources:[],voiceRequests:[],characters:[],output:sandbox};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,ms=180000){const end=Date.now()+ms;while(Date.now()<end){const v=await fn();if(v)return v;await delay(50);}throw Error("Benchmark deadline");}
const invoke=(cmd,args)=>page.evaluate(({cmd,args})=>window.__TAURI_INTERNALS__.invoke(cmd,args),{cmd,args});
const character=()=>invoke("live2d_snapshot");
async function sample(label){
  const path=fileURLToPath(new URL("./live2d_resources.ps1",import.meta.url));
  const code=(await readFile(path,"utf8")).replace("$taskSeconds = $taskClock.Elapsed.TotalSeconds",
    "$taskEndCpu = @{}\n$taskProcesses | ForEach-Object { $taskEndCpu[$_.Id] = $_.TotalProcessorTime.TotalSeconds }\n$taskSeconds = $taskClock.Elapsed.TotalSeconds")
    .replace("($_.TotalProcessorTime.TotalSeconds - $taskStart[$taskPid])", "($taskEndCpu[$taskPid] - $taskStart[$taskPid])")
    .replace("handles = $_.HandleCount", "peakWorkingSetBytes = $_.PeakWorkingSet64\n        sharedGpuBytes = if ($taskMemory.Count) { ($taskMemory | Measure-Object SharedUsage -Sum).Sum } else { $null }\n        handles = $_.HandleCount");
  const desktopResources=JSON.parse(await ps(`& { ${code} } -TargetProcessId ${desktop.pid}`));
  const voiceResources=probe?.exitCode===null?JSON.parse(await ps(`& { ${code} } -TargetProcessId ${probe.pid}`)):null;
  report.resources.push({label,desktop:desktopResources,voice:voiceResources});
  report.characters.push({label,...await character()});
}
async function begin(long=false,prompt){
  await page.locator("#new-conversation").click();await page.waitForSelector(".conversation.active");
  const previous=await page.evaluate(()=>performance.getEntriesByName("aurora-terminal").at(-1)?.detail?.generationId);
  await page.locator("#prompt-input").fill(prompt??(long?"请用六百个汉字详细介绍安静阅读的好处、日常实践和环境布置，分三个自然段，不用列表，不用标题。":"请用四十个汉字介绍安静阅读的好处，不用列表。"));
  const requested=performance.now();await page.locator("#send-button").click();return {previous,requested};
}
async function terminal(start,mode){
  const result=await wait(async()=>{const last=await page.evaluate(()=>performance.getEntriesByName("aurora-terminal").at(-1)?.detail);return last&&last.generationId!==start.previous?last:null;});
  assert.equal(result.status,"completed");report.measurements.push({mode,requestMs:start.requested,completedMs:performance.now(),...result});
  console.log(JSON.stringify({mode,first_content_ms:result.production?.request_to_first_content_ms,tokens_per_second:result.production?.eval_count*1000/result.production?.eval_duration_ms}));
  return result;
}
async function turn(mode){await terminal(await begin(),mode);}
async function synthesize(label,textIndex,seed,text,stream=internalStream){
  const index=voiceResults.length;const start=performance.now();
  probe.stdin.write(JSON.stringify({label,text_index:textIndex,seed,stream,text})+"\n");
  await wait(()=>{if(probe.exitCode!==null)throw Error("Probe exited");return voiceResults.length>index;});
  const result=voiceResults[index];report.voiceRequests.push({...result,requestMs:start,completedMs:performance.now()});
  console.log(JSON.stringify({label,chars:result.text_chars,seconds:result.synthesis_seconds,rtf:result.rtf,stages:result.stages}));return result;
}
async function settings(patch){
  await page.locator("#open-settings").click();await page.waitForSelector("#settings-reload:not([disabled])");
  for(const [key,value] of Object.entries(patch)){
    const field=page.locator(`[data-setting-key="${key}"]`);
    if(typeof value==="boolean")await field.setChecked(value);
    else if(key==="voice.tts.provider")await field.selectOption(value);
    else await field.fill(String(value));
  }
  await page.locator("#settings-save").click();
  await wait(async()=>/^(已保存|设置已同步)/.test(await page.locator("#settings-status").textContent()),15000);
  await page.waitForSelector("#settings-reload:not([disabled])");await page.locator("#close-settings").click();
}
async function visibility(visible){
  await settings({"live2d.visible":visible});
  await wait(async()=>(await character()).visible===visible,15000);await delay(1200);
}
async function productionPlayback(){
  // Only input synthesis is test-injected. Actual completed assistant text,
  // VoiceExecution, private IPC, Rust Audio and Cubism amplitude are real.
  await settings({"voice.enabled":true,"voice.tts.provider":"fake","voice.tts.timeout_seconds":120});
  let previous;
  for(let i=0;i<3;i++){
    const result=await terminal(await begin(false,"请只回复：你好，这是本机中文语音合成测试。不要增加其他内容。"),"production_playback_chat_"+i);
    const chatTerminalObserved=performance.now();
    const request=await wait(async()=>{
      const v=(await invoke("backend_snapshot")).voice;
      if(v?.state==="error")throw Error("Benchmark handoff: "+v.error_code);
      try{const r=JSON.parse(await readFile(sandbox+"/handoff/request.json","utf8"));return r.request_id!==previous?r:null;}catch{return null;}
    },10000);
    previous=request.request_id;
    const synthesisStart=performance.now();assert.ok(synthesisStart>=chatTerminalObserved);
    const speech=await synthesize("production_playback_"+i,0,1986+i,request.text);
    const bytes=await readFile(speech.wav);const sha256=createHash("sha256").update(bytes).digest("hex");
    await writeFile(sandbox+"/handoff/receipt.tmp",JSON.stringify({request_id:request.request_id,wav:speech.wav,sha256}));
    const {rename}=await import("node:fs/promises");await rename(sandbox+"/handoff/receipt.tmp",sandbox+"/handoff/receipt.json");
    const snapshot=()=>invoke("backend_snapshot");
    await wait(async()=>{const v=(await snapshot()).voice;if(v?.state==="error")throw Error(v.error_code);return v?.generation_id===result.generationId&&v.state==="speaking";},15000);
    const playbackStarted=performance.now(),amplitudes=[];
    await wait(async()=>{
      const c=await character();amplitudes.push({time:performance.now(),mouth:c.mouth,fps:c.fps});
      return (await snapshot()).voice.state==="idle";
    },60000);
    const playbackEnded=performance.now();assert.ok(amplitudes.some(a=>a.mouth>0.05),"Real decoded Audio amplitude must reach Cubism");
    assert.equal((await character()).mouth,0);
    (report.playbacks??=[]).push({generationId:result.generationId,chatTerminalObserved,synthesisStart,playbackStarted,playbackEnded,
      wav:speech.wav,sha256,text_chars:request.text.length,amplitudes,fixture:"request-matched WAV input only; not production Local provider"});
  }
  await settings({"voice.enabled":false});
}
try{
  desktop=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","ignore","pipe"]});desktop.stderr.on("data",d=>stderr+=d);
  browser=await wait(async()=>{try{return await chromium.connectOverCDP(`http://127.0.0.1:${port}`);}catch{return null;}},30000);
  page=browser.contexts()[0].pages()[0];page.setDefaultTimeout(15000);await page.waitForSelector("#send-button");
  await wait(async()=>(await invoke("backend_snapshot")).info?.diagnostics?.local_model?.state==="READY");
  await wait(async()=>(await character()).status==="ready");
  owned=JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "ParentProcessId = ${desktop.pid}" | Select-Object ProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})`));
  await turn("warmup");for(let i=0;i<3;i++)await turn("llm_only");await sample("llm_only");
  if(process.env.AURORA_BENCH_LLM_HIDDEN==="true"){
    await visibility(false);for(let i=0;i<3;i++)await turn("llm_only_hidden");await sample("llm_only_hidden");await visibility(true);
  }
  const options=[];if(variant.includes("half"))options.push("--weight-half");if(variant.includes("f0"))options.push("--f0-cpu");if(variant==="fp32")options.push("--fp32");if(profile)options.push("--profile-stages");
  if(process.env.AURORA_BENCH_THREADS)options.push("--threads",process.env.AURORA_BENCH_THREADS);
  if(process.env.AURORA_BENCH_HOST_SYNC==="true")options.push("--count-host-sync");
  probe=spawn(process.env.AURORA_PROBE_PYTHON,["-B",repo+"/scripts/probe_local_cosyvoice.py","--source",process.env.AURORA_PROBE_SOURCE,"--model",process.env.AURORA_PROBE_MODEL,"--prompt",process.env.AURORA_PROBE_PROMPT,"--output",sandbox+"/voice","--backend","rocm","--commands","--deadline","1800",...options],{cwd:repo,windowsHide:true,env:{...process.env,PYTHONUTF8:"1",PYTHONDONTWRITEBYTECODE:"1"},stdio:["pipe","pipe","pipe"]});
  probe.stderr.on("data",d=>probeLog+=d);
  createInterface({input:probe.stdout}).on("line",line=>{probeLog+=line+"\n";if(line.startsWith("READY ")){ready=true;report.voiceReady=JSON.parse(line.slice(6));}try{const v=JSON.parse(line);if(Number.isInteger(v.index))voiceResults.push(v);}catch{}});
  await wait(()=>{if(probe.exitCode!==null)throw Error("Probe exited during load");return ready;},120000);
  for(let i=0;i<3;i++)await turn("voice_idle");await sample("voice_idle");
  await synthesize("cold_resident",0,1986);await sample("cold_resident");
  for(const textIndex of (process.env.AURORA_BENCH_PLAYBACK_ONLY==="true"?[]:shortOnly?[0]:[0,2,3])){
    for(let i=0;i<3;i++){
      const label=`${scheduling}_${textIndex}_${i}`;
      if(scheduling==="serial")await turn(label+"_chat_before");
      if(scheduling==="concurrent"){
        const chatStart=await begin(true);await wait(async()=>(await character()).state==="thinking",10000);
        const speech=synthesize(label,textIndex,1986+i);if(sampleDuringSynthesis)await sample(label);await terminal(chatStart,label+"_chat_overlap");await speech;
      }else{const speech=synthesize(label,textIndex,1986+i);if(sampleDuringSynthesis)await sample(label);await speech;}
      await turn(label+"_recovery");
    }
  }
  if(process.env.AURORA_BENCH_HIDDEN==="true"){
    await visibility(false);for(let i=0;i<3;i++){await synthesize("hidden_"+i,0,1986+i);await turn("hidden_recovery_"+i);}await sample("hidden");
    await visibility(true);for(let i=0;i<3;i++){await synthesize("visible_again_"+i,0,1986+i);await turn("visible_recovery_"+i);}await sample("visible_again");
  }
  if(process.env.AURORA_BENCH_EXTRA_STREAM==="true"){
    // Upstream's token_hop_len changes across stream requests; retain real
    // persistent behavior instead of resetting it to cherry-pick first chunks.
    for(let i=0;i<3;i++){
      await turn("internal_stream_chat_"+i);await synthesize("internal_stream_"+i,0,1986+i,undefined,true);
      await turn("internal_stream_recovery_"+i);
    }
  }
  if(playback)await productionPlayback();
  probe.stdin.write('{"quit":true}\n');await wait(()=>probe.exitCode!==null,20000);assert.equal(probe.exitCode,0);
  report.voice=JSON.parse(await readFile(sandbox+"/voice/report.json","utf8"));await turn("after_voice");report.status="measurements_completed";
}catch(e){report.status="failed";report.error=String(e);throw e;}
finally{
  if(probe?.exitCode===null){probe.kill();await wait(()=>probe.exitCode!==null||probe.signalCode!==null,10000);}
  if(desktop?.exitCode===null){await invoke("window_action",{action:"close"}).catch(()=>{});await wait(()=>desktop.exitCode!==null,15000).catch(()=>desktop.kill());}
  await browser?.close().catch(()=>{});
  const rows=JSON.parse(await ps("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object ProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})"));
  report.remainingOwned=rows.filter(p=>owned.some(o=>o.ProcessId===p.ProcessId&&o.Created===p.Created));
  await writeFile(sandbox+"/report.json",JSON.stringify(report,null,2));await writeFile(sandbox+"/desktop.log",stderr);await writeFile(sandbox+"/probe.log",probeLog);
  console.log(JSON.stringify({status:report.status,error:report.error,output:sandbox,remainingOwned:report.remainingOwned}));
}
