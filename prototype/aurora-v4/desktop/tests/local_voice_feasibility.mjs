// Gate 3 only: existing Release + separately owned offline probe, not a
// LocalVoiceSupervisor implementation or an automatic-runtime acceptance claim.
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {spawn,execFile} from "node:child_process";
import {promisify} from "node:util";
import {mkdir,mkdtemp,writeFile,readFile} from "node:fs/promises";
import {createServer} from "node:net";
import {once} from "node:events";
import {createInterface} from "node:readline";
const {chromium}=createRequire(import.meta.url)("playwright");
const exec=promisify(execFile);
const repo=fileURLToPath(new URL("../../../..",import.meta.url));
const exe=fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe",import.meta.url));
for(const k of ["AURORA_PROBE_PYTHON","AURORA_PROBE_SOURCE","AURORA_PROBE_MODEL","AURORA_PROBE_PROMPT","AURORA_LIVE2D_CONFIG"])assert.ok(process.env[k],k);
const ps=async code=>(await exec("powershell.exe",["-NoProfile","-Command",code],{windowsHide:true})).stdout.trim();
assert.equal(Number(await ps("@(Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -in @('LM Studio','ollama','llama-server','aurora-v4-desktop','aurora-live2d-host')}).Count")),0,"Close user runtimes first; never kill them");
const output=repo+"/tests/output/local-voice-coexist";
await mkdir(output,{recursive:true});const sandbox=await mkdtemp(output+"/run-");
await mkdir(sandbox+"/app/config",{recursive:true});
await writeFile(sandbox+"/app/config/settings.json",JSON.stringify({voice:{enabled:false},live2d:{enabled:true,visible:true},persona:{enabled:false},knowledge:{enabled:false},rag:{pipeline_enabled:false}}));
const listener=createServer();listener.listen(0,"127.0.0.1");await once(listener,"listening");const port=listener.address().port;await new Promise(r=>listener.close(r));
const env={...process.env,AURORA_USER_DATA_DIR:sandbox+"/app",WEBVIEW2_USER_DATA_FOLDER:sandbox+"/webview",WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port}`};
delete env.AURORA_V4_BACKEND;delete env.AURORA_V4_CHAT_PROVIDER;
let desktop,probe,browser,page,stderr="",probeLog="",ready=false,measurements=[],owned=[];
const report={status:"running",automaticVoiceStartup:false,edgeUsed:false,measurements:[],resources:[],output:sandbox};
const samples=Number(process.env.AURORA_PROBE_SAMPLES??4);assert.ok([1,2,3,4].includes(samples));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,ms=90000){const end=Date.now()+ms;while(Date.now()<end){const v=await fn();if(v)return v;await sleep(50);}throw Error("Feasibility deadline");}
const invoke=(cmd,args)=>page.evaluate(({cmd,args})=>window.__TAURI_INTERNALS__.invoke(cmd,args),{cmd,args});
async function sample(label){
  const path=fileURLToPath(new URL("./live2d_resources.ps1",import.meta.url));
  // Capture CPU before later GPU queries; Process.TotalProcessorTime is a lazy
  // property and reading it after those queries inflates the earlier interval.
  const code=(await readFile(path,"utf8")).replace("$taskSeconds = $taskClock.Elapsed.TotalSeconds",
    "$taskEndCpu = @{}\n$taskProcesses | ForEach-Object { $taskEndCpu[$_.Id] = $_.TotalProcessorTime.TotalSeconds }\n$taskSeconds = $taskClock.Elapsed.TotalSeconds")
    .replace("($_.TotalProcessorTime.TotalSeconds - $taskStart[$taskPid])", "($taskEndCpu[$taskPid] - $taskStart[$taskPid])");
  const desktopResources=JSON.parse(await ps(`& { ${code} } -TargetProcessId ${desktop.pid}`));
  let voiceResources=null;
  if(probe&&probe.exitCode===null)voiceResources=JSON.parse(await ps(`& { ${code} } -TargetProcessId ${probe.pid}`));
  report.resources.push({label,desktop:desktopResources,voice:voiceResources});
}
async function turn(mode){
  await page.locator("#new-conversation").click();await page.waitForSelector(".conversation.active");
  const marks=()=>page.evaluate(()=>performance.getEntriesByName("aurora-terminal").map(x=>x.detail));
  const before=(await marks()).at(-1)?.generationId;
  await page.locator("#prompt-input").fill("请用四十个汉字介绍安静阅读的好处，不用列表。");
  await page.locator("#send-button").click();
  const result=await wait(async()=>{const last=(await marks()).at(-1);return last&&last.generationId!==before?last:null;});
  assert.equal(result.status,"completed");report.measurements.push({mode,...result});
  console.log(JSON.stringify({mode,first_content_ms:result.production?.request_to_first_content_ms,
    tokens_per_second:result.production?.eval_count*1000/result.production?.eval_duration_ms}));
}
try{
  desktop=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","ignore","pipe"]});
  desktop.stderr.on("data",d=>stderr+=d);
  browser=await wait(async()=>{try{return await chromium.connectOverCDP(`http://127.0.0.1:${port}`);}catch{return null;}},30000);
  page=browser.contexts()[0].pages()[0];page.setDefaultTimeout(15000);await page.waitForSelector("#send-button");
  await wait(async()=>(await invoke("backend_snapshot")).info?.diagnostics?.local_model?.state==="READY");
  await wait(async()=>(await invoke("live2d_snapshot")).status==="ready");
  owned=JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "ParentProcessId = ${desktop.pid}" | Select-Object ProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})`));
  await turn("warmup");for(let i=0;i<3;i++)await turn("llm_only");await sample("llm_only");
  const threadArgs=process.env.AURORA_PROBE_THREADS?["--threads",process.env.AURORA_PROBE_THREADS]:[];
  probe=spawn(process.env.AURORA_PROBE_PYTHON,["-B",repo+"/scripts/probe_local_cosyvoice.py","--source",process.env.AURORA_PROBE_SOURCE,"--model",process.env.AURORA_PROBE_MODEL,"--prompt",process.env.AURORA_PROBE_PROMPT,"--output",sandbox+"/voice","--backend",process.env.AURORA_PROBE_BACKEND??"rocm",...threadArgs,"--samples",String(samples),"--controlled","--deadline","360"],{cwd:repo,windowsHide:true,env:{...process.env,PYTHONUTF8:"1",PYTHONDONTWRITEBYTECODE:"1"},stdio:["pipe","pipe","pipe"]});
  probe.stderr.on("data",d=>probeLog+=d);
  createInterface({input:probe.stdout}).on("line",line=>{
    probeLog+=line+"\n";
    if(line.startsWith("READY ")){ready=true;report.voiceReady=JSON.parse(line.slice(6));}
    try{const v=JSON.parse(line);if(Number.isInteger(v.index))measurements.push(v);}catch{}
  });
  await wait(()=>{if(probe.exitCode!==null)throw Error("Voice probe exited before ready");return ready;},120000);
  for(let i=0;i<3;i++)await turn("voice_idle");await sample("voice_idle");
  for(let i=0;i<samples;i++){
    probe.stdin.write("go\n");
    await turn("voice_synthesis_"+i);await sample("voice_synthesis_"+i);
    await wait(()=>{if(probe.exitCode!==null&&measurements.length<=i)throw Error("Voice probe failed");return measurements.length>i;},180000);
  }
  await wait(()=>probe.exitCode!==null,20000);assert.equal(probe.exitCode,0);
  report.voice=JSON.parse(await readFile(sandbox+"/voice/report.json","utf8"));
  assert.equal(report.voice.status,"passed");await turn("after_voice");report.status="passed";
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
