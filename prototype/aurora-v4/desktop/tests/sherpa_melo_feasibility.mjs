// Opt-in V4-7B.2 experiment. Existing Release/Audio/Cubism are unchanged.
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {spawn,execFile} from "node:child_process";
import {promisify} from "node:util";
import {mkdir,mkdtemp,writeFile,readFile,rename} from "node:fs/promises";
import {createServer} from "node:net";
import {once} from "node:events";
import {createInterface} from "node:readline";
import {createHash} from "node:crypto";
const {chromium}=createRequire(import.meta.url)("playwright");
const exec=promisify(execFile);
const repo=fileURLToPath(new URL("../../../..",import.meta.url));
const exe=fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe",import.meta.url));
for(const k of ["AURORA_BENCH_PYTHON","AURORA_SHERPA_HOST","AURORA_SHERPA_RUNTIME","AURORA_MELO_MODEL","AURORA_LIVE2D_CONFIG"])assert.ok(process.env[k],k);
const mode=process.env.AURORA_MELO_MODE??"matrix";
assert.ok(["matrix","playback","resident-only"].includes(mode));
const ps=async code=>(await exec("powershell.exe",["-NoProfile","-Command",code],{windowsHide:true})).stdout.trim();
assert.equal(Number(await ps("@(Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -in @('LM Studio','ollama','llama-server','aurora-v4-desktop','aurora-live2d-host','benchmark_sherpa_melo')}).Count")),0,"Do not overlap experiments or kill user runtimes");
await mkdir(repo+"/tests/output/v47b2-coexist",{recursive:true});
const output=await mkdtemp(repo+"/tests/output/v47b2-coexist/run-");
await mkdir(output+"/app/config",{recursive:true});await mkdir(output+"/handoff");
await writeFile(output+"/app/config/settings.json",JSON.stringify({voice:{enabled:false},live2d:{enabled:true,visible:true},persona:{enabled:false},knowledge:{enabled:false},rag:{pipeline_enabled:false}}));
const listener=createServer();listener.listen(0,"127.0.0.1");await once(listener,"listening");const port=listener.address().port;await new Promise(r=>listener.close(r));
const env={...process.env,AURORA_USER_DATA_DIR:output+"/app",WEBVIEW2_USER_DATA_FOLDER:output+"/webview",WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port}`,
  AURORA_V4_SIDECAR_DIR:repo+"/scripts/voice_feasibility_sidecar",AURORA_BENCH_HANDOFF:output+"/handoff",AURORA_BENCH_STRICT:mode!=="playback"?"true":"false"};
delete env.AURORA_V4_BACKEND;delete env.AURORA_V4_CHAT_PROVIDER;
let desktop,probe,browser,page,stderr="",probeLog="",owned=[],ready,results=[],probeOutput;
const report={status:"running",mode,strictNoBackgroundInference:mode!=="playback",productionModified:false,output,measurements:[],voiceRequests:[],resources:[],playbacks:[]};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,ms=120000){const end=Date.now()+ms;while(Date.now()<end){const v=await fn();if(v)return v;await delay(25);}throw Error("Benchmark deadline");}
const invoke=(cmd,args)=>page.evaluate(({cmd,args})=>window.__TAURI_INTERNALS__.invoke(cmd,args),{cmd,args});
const character=()=>invoke("live2d_snapshot");
const snapshot=()=>invoke("backend_snapshot");
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
async function chat(label,prompt="请用四十个汉字介绍安静阅读的好处，不用列表。"){
  await page.locator("#new-conversation").click();await page.waitForSelector(".conversation.active");
  const old=await page.evaluate(()=>performance.getEntriesByName("aurora-terminal").at(-1)?.detail?.generationId);
  await page.locator("#prompt-input").fill(prompt);const requestMs=performance.now();await page.locator("#send-button").click();
  const terminal=await wait(async()=>{const x=await page.evaluate(()=>performance.getEntriesByName("aurora-terminal").at(-1)?.detail);return x&&x.generationId!==old?x:null;});
  assert.equal(terminal.status,"completed");const row={label,requestMs,terminalObservedMs:performance.now(),...terminal};report.measurements.push(row);return row;
}
async function startProbe(threads,label){
  ready=null;results=[];probeOutput=output+"/"+label;
  probe=spawn(process.env.AURORA_BENCH_PYTHON,["-B",repo+"/scripts/probe_sherpa_melo.py","--host",process.env.AURORA_SHERPA_HOST,"--runtime",process.env.AURORA_SHERPA_RUNTIME,"--model",process.env.AURORA_MELO_MODEL,"--output",probeOutput,"--threads",String(threads),"--commands"],
    {cwd:repo,env:{...process.env,PYTHONUTF8:"1"},windowsHide:true,stdio:["pipe","pipe","pipe"]});
  probe.stderr.on("data",d=>probeLog+=d);
  createInterface({input:probe.stdout}).on("line",line=>{probeLog+=line+"\n";if(line.startsWith("READY "))ready=JSON.parse(line.slice(6));else try{const r=JSON.parse(line);if(Number.isInteger(r.index))results.push(r);}catch{}});
  await wait(()=>{if(probe.exitCode!==null)throw Error("Probe initialization failed");return ready;},30000);
  (report.starts??=[]).push(ready);
}
async function finishProbe(){
  if(probe?.exitCode===null){probe.stdin.write('{"quit":true}\n');await wait(()=>probe.exitCode!==null,15000);assert.equal(probe.exitCode,0);}
}
async function synthesize(label,textIndex=0,text){
  const index=results.length,start=performance.now();probe.stdin.write(JSON.stringify({label,text_index:textIndex,text})+"\n");
  await wait(()=>{if(probe.exitCode!==null)throw Error("Native synthesis failed");return results.length>index;});
  const row={...results[index],requestMs:start,audioReadyObservedMs:performance.now(),character:await character()};
  report.voiceRequests.push(row);console.log(JSON.stringify({label,chars:row.text_chars,seconds:row.synthesis_seconds,rtf:row.rtf,threads:ready.num_threads}));return row;
}
async function resource(label){
  const path=fileURLToPath(new URL("./live2d_resources.ps1",import.meta.url));
  const code=(await readFile(path,"utf8")).replace("$taskSeconds = $taskClock.Elapsed.TotalSeconds",
    "$taskEndCpu = @{}\n$taskProcesses | ForEach-Object { $taskEndCpu[$_.Id] = $_.TotalProcessorTime.TotalSeconds }\n$taskSeconds = $taskClock.Elapsed.TotalSeconds")
    .replace("($_.TotalProcessorTime.TotalSeconds - $taskStart[$taskPid])","($taskEndCpu[$taskPid] - $taskStart[$taskPid])");
  const [desktopSample,nativeSample]=await Promise.all([ps(`& { ${code} } -TargetProcessId ${desktop.pid}`),ps(`& { ${code} } -TargetProcessId ${ready.ready.pid}`)]);
  report.resources.push({label,desktop:JSON.parse(desktopSample),native:JSON.parse(nativeSample),character:await character()});
}
async function playback(){
  const threads=Number(process.env.AURORA_MELO_THREADS??4);await startProbe(threads,"production-input");
  await synthesize("first");await settings({"voice.enabled":true,"voice.tts.provider":"fake","voice.tts.timeout_seconds":120});
  let previous;
  async function oncePlayback(i,stop=false){
    const terminal=await chat("playback_chat_"+i,stop?"请用一百二十个汉字介绍安静阅读，不用标题。":"请只回复：你好，这是本机中文语音合成测试。不要增加其他内容。");
    const input=await wait(async()=>{
      const v=(await snapshot()).voice;if(v?.state==="error")throw Error(v.error_code);
      try{const x=JSON.parse(await readFile(output+"/handoff/request.json","utf8"));return x.request_id!==previous?x:null;}catch{return null;}
    },10000);previous=input.request_id;
    const speech=await synthesize("playback_"+i,0,input.text);
    assert.ok(speech.requestMs>=terminal.terminalObservedMs);
    const sha256=createHash("sha256").update(await readFile(speech.wav)).digest("hex");
    await writeFile(output+"/handoff/receipt.tmp",JSON.stringify({request_id:input.request_id,wav:speech.wav,sha256}));
    await rename(output+"/handoff/receipt.tmp",output+"/handoff/receipt.json");
    await wait(async()=>{const v=(await snapshot()).voice;if(v.state==="error")throw Error(v.error_code);return v.generation_id===terminal.generationId&&v.state==="speaking";},10000);
    const started=performance.now(),amplitudes=[];
    if(stop){
      await wait(async()=>{const c=await character();amplitudes.push(c.mouth);return c.mouth>.05;},5000);
      const cancelledAt=performance.now();await page.locator("#voice-stop").click();
      await wait(async()=>(await snapshot()).voice.state==="idle",5000);
      await wait(async()=>(await character()).mouth===0,5000);
      report.stop={stopToIdleAndMouthResetMs:performance.now()-cancelledAt,mouth:(await character()).mouth,discardedRemainder:true};
    }else await wait(async()=>{
      const c=await character();amplitudes.push(c.mouth);const v=(await snapshot()).voice;
      if(v.state==="error")throw Error(v.error_code);return v.state==="idle";
    },60000);
    await wait(async()=>(await character()).mouth===0,3000);assert.ok(amplitudes.some(v=>v>.05));
    report.playbacks.push({generationId:terminal.generationId,terminalObservedMs:terminal.terminalObservedMs,
      audioReadyObservedMs:speech.audioReadyObservedMs,terminalToAudioReadyMs:speech.audioReadyObservedMs-terminal.terminalObservedMs,
      text_chars:input.text.length,sha256,wav:speech.wav,speakingIntervalMs:performance.now()-started,
      maxMouth:Math.max(...amplitudes),finalMouth:(await character()).mouth,stopped:stop});
  }
  for(let i=0;i<5;i++)await oncePlayback(i);
  await oncePlayback("stop",true);await oncePlayback("recovery");
  await settings({"voice.enabled":false});await finishProbe();
}
try{
  desktop=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","ignore","pipe"]});desktop.stderr.on("data",d=>stderr+=d);
  browser=await wait(async()=>{try{return await chromium.connectOverCDP(`http://127.0.0.1:${port}`);}catch{return null;}},30000);
  page=browser.contexts()[0].pages()[0];page.setDefaultTimeout(15000);await page.waitForSelector("#send-button");
  await wait(async()=>(await snapshot()).info?.diagnostics?.local_model?.state==="READY");
  await wait(async()=>(await character()).status==="ready");
  owned=JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "ParentProcessId = ${desktop.pid}" | Select-Object ProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})`));
  await chat("warmup");for(let i=0;i<5;i++)await chat("llm_only_"+i);
  if(mode==="playback")await playback();
  else if(mode==="resident-only"){
    await settings({"live2d.enabled":false});await wait(async()=>(await character()).status==="disabled",5000);
    assert.equal(Number(await ps("@(Get-Process aurora-live2d-host -ErrorAction SilentlyContinue).Count")),0);
    report.noLive2dHost=true;await startProbe(4,"no-live2d");await synthesize("resident_only_cold");
    for(const textIndex of [0,2,3])for(let i=0;i<5;i++){
      const label=`no_live2d_${textIndex}_${i}`;await chat(label+"_before");await synthesize(label,textIndex);await chat(label+"_recovery");
    }
    await resource("no_live2d");await finishProbe();
  }
  else{
    for(const threads of [1,4,16]){
      await startProbe(threads,"threads-"+threads);await synthesize(`cold_${threads}`);
      for(const textIndex of [0,2,3])for(let i=0;i<5;i++){
        const label=`resident_${threads}_${textIndex}_${i}`;await chat(label+"_before");await synthesize(label,textIndex);await chat(label+"_recovery");
      }
      if(threads===4){
        for(let i=0;i<20;i++)await synthesize("coexist_soak_"+i);
        for(let i=0;i<5;i++)await synthesize("coexist_long_"+i,3);
        const pending=synthesize("diagnostic_long",3);await resource("during_cpu_synthesis");await pending;
        await chat("after_soak_recovery");
      }
      await resource("resident_threads_"+threads);await finishProbe();
    }
    // Same 4B resident, no active Live2D rendering. Selected low thread count.
    await settings({"live2d.visible":false});await wait(async()=>(await character()).visible===false,5000);
    await startProbe(4,"hidden");await synthesize("hidden_cold");
    for(let i=0;i<5;i++){await chat("hidden_before_"+i);await synthesize("hidden_"+i);await chat("hidden_recovery_"+i);}
    await resource("hidden");await finishProbe();
    await settings({"live2d.visible":true});await wait(async()=>(await character()).visible===true,5000);
  }
  await chat("after_voice");report.status="passed";
}catch(error){report.status="failed";report.error=String(error);throw error;}
finally{
  await finishProbe().catch(()=>{});
  if(probe?.exitCode===null)probe.kill();
  if(desktop?.exitCode===null){await invoke("window_action",{action:"close"}).catch(()=>{});await wait(()=>desktop.exitCode!==null,15000).catch(()=>desktop.kill());}
  await browser?.close().catch(()=>{});
  const rows=JSON.parse(await ps("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object ProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})"));
  report.remainingOwned=rows.filter(p=>owned.some(o=>o.ProcessId===p.ProcessId&&o.Created===p.Created));
  await writeFile(output+"/report.json",JSON.stringify(report,null,2));await writeFile(output+"/desktop.log",stderr);await writeFile(output+"/probe.log",probeLog);
  console.log(JSON.stringify({status:report.status,output,remainingOwned:report.remainingOwned,error:report.error}));
}
