//! Sole lifecycle owner of the isolated native voice worker. Private pipes to
//! C++; authenticated dynamic loopback broker to Python. No secrets serialize.
use crate::sidecar::JobGuard;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    io::Read,
    path::{Path, PathBuf},
    process::Stdio,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::Instant,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    net::{TcpListener, TcpStream},
    process::{Child, ChildStdin, Command},
    sync::{Mutex, Semaphore, oneshot},
    time::{Duration, sleep, timeout},
};
use uuid::Uuid;

const MAX_WAV: usize = 64 * 1024 * 1024;
const MODEL: &str = "melo-zh-en-v2";
const ASSETS: &[(&str, &str)] = &[
    (
        "model.onnx",
        "bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d",
    ),
    (
        "tokens.txt",
        "d18664a7e12bd7ea1022ddaf951e534e136815016c5a809d6b64156bffb4369d",
    ),
    (
        "lexicon.txt",
        "7236884b02435ac5d10cf69b4be40a61b45aa676b5300f0e412f185748fee528",
    ),
    (
        "date.fst",
        "eb8aa079ae3cb81d8f4404992f39d61a0cb990947512b5b8d1e54d1f6980e718",
    ),
    (
        "number.fst",
        "743f402181fcfebf76cc2f0546b71fa26476e626fbe4e460fb7b4c3a7a8bd5bd",
    ),
];
const DLLS: &[(&str, &str)] = &[
    (
        "aurora-local-voice-host.exe",
        "9b901a02cd178565bec0efb5aa84c7d3152748857b05a30054f8c168e0c81fc4",
    ),
    (
        "sherpa-onnx-c-api.dll",
        "bb146780c7b946755810f28a5fb7dcf6321ae0d6bf18f7b507461a79c3396a3b",
    ),
    (
        "onnxruntime.dll",
        "422d776ab0e3218260f7f628fcb84606aaa5c21116f720c8619a6da5e0b2e0f9",
    ),
    (
        "onnxruntime_providers_shared.dll",
        "0190137dee4933261c065c5d030c3568a68c7aa43cad942b4726a07011738bc2",
    ),
];
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn verify(root: &Path, assets: &[(&str, &str)]) -> Result<(), String> {
    for (name, expected) in assets {
        let mut file = std::fs::File::open(root.join(name)).map_err(|_| match *name {
            "model.onnx" => "VOICE_MODEL_MISSING",
            "lexicon.txt" => "VOICE_LEXICON_MISSING",
            "tokens.txt" => "VOICE_TOKENS_MISSING",
            _ => "VOICE_ASSET_MISSING",
        })?;
        let mut hash = Sha256::new();
        let mut buffer = [0u8; 65536];
        loop {
            let n = file.read(&mut buffer).map_err(|_| "VOICE_ASSET_INVALID")?;
            if n == 0 {
                break;
            }
            hash.update(&buffer[..n]);
        }
        if hex(&hash.finalize()) != *expected {
            return Err("VOICE_ASSET_HASH_MISMATCH".into());
        }
    }
    Ok(())
}
#[derive(Clone)]
struct Config {
    executable: PathBuf,
    model: PathBuf,
}
impl Config {
    fn discover() -> Result<Self, String> {
        let base = PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or("VOICE_RUNTIME_MISSING")?)
            .join("Aurora");
        let runtime = std::env::var_os("AURORA_LOCAL_VOICE_RUNTIME")
            .map(PathBuf::from)
            .unwrap_or(base.join("runtime/voice/sherpa-melo-v1"));
        let model = std::env::var_os("AURORA_LOCAL_VOICE_MODEL")
            .map(PathBuf::from)
            .unwrap_or(base.join("models/melo-zh-en-v2"));
        if !runtime.is_absolute() || !model.is_absolute() {
            return Err("VOICE_ASSET_INVALID".into());
        }
        let executable = runtime.join("aurora-local-voice-host.exe");
        if !executable.is_file() {
            return Err("VOICE_RUNTIME_MISSING".into());
        }
        verify(&runtime, DLLS)?;
        verify(&model, ASSETS)?;
        Ok(Self { executable, model })
    }
}
#[derive(Clone, Serialize, Debug)]
pub struct Snapshot {
    pub state: String,
    pub model: String,
    pub runtime_version: String,
    pub ready_ms: Option<f64>,
    pub synthesis_ms: Option<f64>,
    pub audio_seconds: Option<f64>,
    pub text_chars: Option<u64>,
    pub last_failure_class: String,
    pub restart_count: u32,
    pub error_code: String,
    pub num_threads: u32,
    pub private_bytes: Option<u64>,
    pub handles: Option<u64>,
    pub threads: Option<u64>,
    pub completed_requests: u64,
    pub discarded_requests: u64,
}
impl Default for Snapshot {
    fn default() -> Self {
        Self {
            state: "STOPPED".into(),
            model: MODEL.into(),
            runtime_version: String::new(),
            ready_ms: None,
            synthesis_ms: None,
            audio_seconds: None,
            text_chars: None,
            last_failure_class: String::new(),
            restart_count: 0,
            error_code: String::new(),
            num_threads: 4,
            private_bytes: None,
            handles: None,
            threads: None,
            completed_requests: 0,
            discarded_requests: 0,
        }
    }
}
#[derive(Clone)]
pub struct Handoff {
    pub endpoint: String,
    pub token: String,
}
type Receipt = Result<Vec<u8>, String>;
type Observer = Arc<dyn Fn(Snapshot) + Send + Sync>;
const OWNER_MARKER: &[u8] = b"aurora-local-voice-v1";
fn plain(path: &Path, directory: bool) -> bool {
    let Ok(metadata) = std::fs::symlink_metadata(path) else {
        return false;
    };
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return false;
        }
    }
    !metadata.file_type().is_symlink()
        && if directory {
            metadata.is_dir()
        } else {
            metadata.is_file()
        }
}
fn lease(path: &Path, create: bool) -> std::io::Result<std::fs::File> {
    let mut options = std::fs::OpenOptions::new();
    options.read(true).write(true).create_new(create);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(0);
    }
    options.open(path)
}
fn reap_orphans(parent: &Path) {
    let Ok(entries) = std::fs::read_dir(parent) else {
        return;
    };
    for entry in entries.flatten().take(1024) {
        let root = entry.path();
        if !entry.file_name().to_string_lossy().starts_with("session-") || !plain(&root, true) {
            continue;
        }
        if !plain(&root.join("owner"), false)
            || std::fs::read(root.join("owner")).ok().as_deref() != Some(OWNER_MARKER)
        {
            continue;
        }
        if !plain(&root.join("lease"), false) {
            continue;
        }
        let Ok(guard) = lease(&root.join("lease"), false) else {
            continue;
        };
        let Ok(files) = std::fs::read_dir(&root) else {
            continue;
        };
        let files: Vec<_> = files.flatten().map(|file| file.path()).collect();
        // Never recurse. Unexpected content or links invalidate our cleanup claim.
        if !files.iter().all(|path| {
            plain(path, false)
                && path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .is_some_and(|name| {
                        matches!(name, "owner" | "lease")
                            || name.strip_suffix(".wav").is_some_and(|stem| {
                                stem.len() == 64 && stem.bytes().all(|b| b.is_ascii_hexdigit())
                            })
                    })
        }) {
            continue;
        }
        for path in files
            .iter()
            .filter(|path| path.file_name().is_some_and(|name| name != "lease"))
        {
            let _ = std::fs::remove_file(path);
        }
        drop(guard);
        let _ = std::fs::remove_file(root.join("lease"));
        let _ = std::fs::remove_dir(root);
    }
}
fn owned_root() -> Result<(tempfile::TempDir, std::fs::File), String> {
    let parent = PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or("VOICE_TEMP_FAILED")?)
        .join("Aurora/cache/local-voice");
    std::fs::create_dir_all(&parent).map_err(|_| "VOICE_TEMP_FAILED")?;
    if !plain(&parent, true) {
        return Err("VOICE_TEMP_FAILED".into());
    }
    reap_orphans(&parent);
    let root = tempfile::Builder::new()
        .prefix("session-")
        .tempdir_in(parent)
        .map_err(|_| "VOICE_TEMP_FAILED")?;
    std::fs::write(root.path().join("owner"), OWNER_MARKER).map_err(|_| "VOICE_TEMP_FAILED")?;
    let guard = lease(&root.path().join("lease"), true).map_err(|_| "VOICE_TEMP_FAILED")?;
    Ok((root, guard))
}
struct Data {
    snapshot: Snapshot,
    child: Option<Child>,
    writer: Option<ChildStdin>,
    job: Option<JobGuard>,
    root: Option<tempfile::TempDir>,
    lease: Option<std::fs::File>,
    pending: HashMap<String, oneshot::Sender<Receipt>>,
    epoch: u64,
    observer: Option<Observer>,
}
impl Default for Data {
    fn default() -> Self {
        Self {
            snapshot: Default::default(),
            child: None,
            writer: None,
            job: None,
            root: None,
            lease: None,
            pending: Default::default(),
            epoch: 0,
            observer: None,
        }
    }
}
#[derive(Clone, Default)]
pub struct LocalVoiceSupervisor {
    data: Arc<Mutex<Data>>,
    stopped: Arc<AtomicBool>,
    lifecycle: Arc<Mutex<()>>,
    session: Arc<AtomicU64>,
}
impl LocalVoiceSupervisor {
    pub async fn snapshot(&self) -> Snapshot {
        self.data.lock().await.snapshot.clone()
    }
    pub async fn observe(&self, observer: impl Fn(Snapshot) + Send + Sync + 'static) {
        self.data.lock().await.observer = Some(Arc::new(observer));
    }
    async fn publish(&self) {
        let data = self.data.lock().await;
        if let Some(observer) = &data.observer {
            observer(data.snapshot.clone());
        }
    }
    async fn startup_failed(&self, code: &str) {
        self.stopped.store(true, Ordering::SeqCst);
        let mut data = self.data.lock().await;
        data.snapshot.state = "DEGRADED".into();
        data.snapshot.error_code = code.into();
        data.snapshot.last_failure_class = code.into();
        drop(data);
        self.publish().await;
    }
    pub async fn start(&self) -> Result<Handoff, String> {
        let _guard = self.lifecycle.lock().await;
        if self.data.lock().await.snapshot.state != "STOPPED" {
            return Err("VOICE_ALREADY_STARTED".into());
        }
        let session = self.session.fetch_add(1, Ordering::SeqCst) + 1;
        self.stopped.store(false, Ordering::SeqCst);
        let listener = match TcpListener::bind("127.0.0.1:0").await {
            Ok(listener) => listener,
            Err(_) => {
                self.startup_failed("VOICE_IPC_FAILED").await;
                return Err("VOICE_IPC_FAILED".into());
            }
        };
        let handoff = Handoff {
            endpoint: format!(
                "http://{}",
                listener.local_addr().map_err(|_| "VOICE_IPC_FAILED")?
            ),
            token: format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple()),
        };
        {
            let mut data = self.data.lock().await;
            data.snapshot = Snapshot::default();
            data.snapshot.state = "STARTING".into();
        }
        let owned = tokio::task::spawn_blocking(owned_root)
            .await
            .map_err(|_| "VOICE_TEMP_FAILED".to_string())
            .and_then(|result| result);
        let (root, guard) = match owned {
            Ok(owned) => owned,
            Err(code) => {
                self.startup_failed(&code).await;
                return Err(code);
            }
        };
        {
            let mut data = self.data.lock().await;
            data.root = Some(root);
            data.lease = Some(guard);
        }
        let owner = self.clone();
        let token = handoff.token.clone();
        tokio::spawn(async move {
            owner.serve(listener, token, session).await;
        });
        let owner = self.clone();
        tokio::spawn(async move {
            owner.monitor(session).await;
        });
        Ok(handoff)
    }
    async fn spawn(&self, session: u64) -> Result<(), String> {
        self.data.lock().await.snapshot.state = "STARTING".into();
        self.publish().await;
        let config = tokio::task::spawn_blocking(Config::discover)
            .await
            .map_err(|_| "VOICE_DISCOVERY_FAILED")??;
        if self.stopped.load(Ordering::SeqCst) || self.session.load(Ordering::SeqCst) != session {
            return Err("VOICE_STOPPED".into());
        }
        let mut data = self.data.lock().await;
        data.epoch += 1;
        let epoch = data.epoch;
        let root = data.root.as_ref().ok_or("VOICE_STOPPED")?.path().to_owned();
        let mut command = Command::new(&config.executable);
        command
            .current_dir(config.executable.parent().ok_or("VOICE_RUNTIME_MISSING")?)
            .arg(&config.model)
            .arg(root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        #[cfg(windows)]
        command.creation_flags(0x0800_0000);
        let mut child = command.spawn().map_err(|_| "VOICE_SPAWN_FAILED")?;
        let job = JobGuard::assign(child.id().ok_or("VOICE_SPAWN_FAILED")?)?;
        let stdout = child.stdout.take().ok_or("VOICE_SPAWN_FAILED")?;
        let stderr = child.stderr.take().ok_or("VOICE_SPAWN_FAILED")?;
        data.writer = child.stdin.take();
        data.child = Some(child);
        data.job = Some(job);
        data.snapshot.error_code.clear();
        drop(data);
        // Consume and discard raw runtime errors (can contain private paths/text).
        tokio::spawn(async move {
            let mut reader = BufReader::new(stderr);
            let mut buffer = Vec::new();
            loop {
                buffer.clear();
                if tokio::io::AsyncReadExt::take(&mut reader, 16384)
                    .read_until(b'\n', &mut buffer)
                    .await
                    .unwrap_or(0)
                    == 0
                {
                    break;
                }
            }
        });
        let owner = self.clone();
        tokio::spawn(async move {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = Vec::new();
                let n = tokio::io::AsyncReadExt::take(&mut reader, 8193)
                    .read_until(b'\n', &mut line)
                    .await
                    .unwrap_or(0);
                if n == 0 || n > 8192 {
                    break;
                }
                let Ok(message) = serde_json::from_slice::<Value>(&line) else {
                    break;
                };
                owner.message(epoch, message).await;
            }
        });
        Ok(())
    }
    async fn message(&self, epoch: u64, message: Value) {
        let mut data = self.data.lock().await;
        if epoch != data.epoch || self.stopped.load(Ordering::SeqCst) {
            return;
        }
        match message["type"].as_str() {
            Some("loading") => data.snapshot.state = "LOADING_MODEL".into(),
            Some("ready")
                if message["model"] == MODEL
                    && message["num_threads"] == 4
                    && message["version"] == "aurora-local-voice-1" =>
            {
                data.snapshot.state = "READY".into();
                data.snapshot.ready_ms = message["ready_ms"].as_f64();
                data.snapshot.runtime_version =
                    "aurora-local-voice-1 / sherpa-1.13.8 / ort-1.28.2".into();
                eprintln!(
                    "[aurora-voice] state=READY ready_ms={:?}",
                    data.snapshot.ready_ms
                );
            }
            Some("result") => {
                let Some(key) = message["key"].as_str().filter(|k| {
                    !k.is_empty() && k.len() <= 320 && k.bytes().all(|b| b.is_ascii_hexdigit())
                }) else {
                    return;
                };
                let path = data
                    .root
                    .as_ref()
                    .map(|root| root.path().join(format!("{key}.wav")));
                let sender = data.pending.remove(key);
                let error = message["error"].as_str().unwrap_or("SYNTHESIS_FAILED");
                let receipt = if error.is_empty() && sender.is_some() {
                    path.as_ref()
                        .and_then(|p| {
                            std::fs::metadata(p)
                                .ok()
                                .filter(|m| m.len() <= MAX_WAV as u64 && m.len() > 44)
                                .and_then(|_| std::fs::read(p).ok())
                        })
                        .ok_or("VOICE_ARTIFACT_FAILED".into())
                } else {
                    Err(if error == "BUSY" {
                        "VOICE_BUSY"
                    } else {
                        "SYNTHESIS_FAILED"
                    }
                    .into())
                };
                if let Some(path) = path {
                    let _ = std::fs::remove_file(path);
                }
                data.snapshot.synthesis_ms = message["synthesis_ms"].as_f64();
                data.snapshot.audio_seconds = message["audio_seconds"].as_f64();
                data.snapshot.text_chars = message["text_chars"].as_u64();
                if !error.is_empty() {
                    data.snapshot.last_failure_class = match error {
                        "BUSY" => "VOICE_BUSY",
                        "CANCELLED" => "VOICE_CANCELLED",
                        _ => "SYNTHESIS_FAILED",
                    }
                    .into();
                }
                if let Some(sender) = sender {
                    if receipt.is_ok() {
                        data.snapshot.completed_requests += 1;
                    }
                    let _ = sender.send(receipt);
                } else {
                    data.snapshot.discarded_requests += 1;
                }
            }
            _ => {}
        }
        if let Some(value) = message["private_bytes"].as_u64() {
            data.snapshot.private_bytes = Some(value);
        }
        if let Some(value) = message["handles"].as_u64() {
            data.snapshot.handles = Some(value);
        }
        if let Some(value) = message["threads"].as_u64() {
            data.snapshot.threads = Some(value);
        }
        drop(data);
        self.publish().await;
    }
    async fn monitor(&self, session: u64) {
        let _guard = self.lifecycle.lock().await;
        if self.stopped.load(Ordering::SeqCst) || self.session.load(Ordering::SeqCst) != session {
            return;
        }
        let mut failure = self.spawn(session).await.err();
        if let Some(code) = failure.as_ref() {
            let mut data = self.data.lock().await;
            data.snapshot.state = "DEGRADED".into();
            data.snapshot.error_code = code.clone();
            data.snapshot.last_failure_class = code.clone();
            drop(data);
            self.publish().await;
            return;
        }
        drop(_guard);
        let mut startup = Instant::now();
        let mut last_health = Instant::now();
        loop {
            sleep(Duration::from_millis(200)).await;
            if self.stopped.load(Ordering::SeqCst) || self.session.load(Ordering::SeqCst) != session
            {
                break;
            }
            {
                let mut data = self.data.lock().await;
                if data
                    .child
                    .as_mut()
                    .is_none_or(|child| child.try_wait().ok().flatten().is_some())
                {
                    failure = Some("VOICE_HOST_EXITED".into());
                } else if data.snapshot.state != "READY"
                    && startup.elapsed() > Duration::from_secs(30)
                {
                    failure = Some("VOICE_LOAD_TIMEOUT".into());
                }
            }
            if last_health.elapsed() > Duration::from_secs(5) {
                let mut data = self.data.lock().await;
                if let Some(writer) = &mut data.writer {
                    let _ =
                        timeout(Duration::from_millis(200), writer.write_all(b"health\n")).await;
                }
                last_health = Instant::now();
            }
            if let Some(code) = failure.take() {
                let _guard = self.lifecycle.lock().await;
                if self.stopped.load(Ordering::SeqCst)
                    || self.session.load(Ordering::SeqCst) != session
                {
                    break;
                }
                self.stop_child().await;
                let attempts = {
                    let mut data = self.data.lock().await;
                    data.snapshot.state = "DEGRADED".into();
                    data.snapshot.last_failure_class = code.clone();
                    data.snapshot.error_code = code;
                    data.snapshot.restart_count
                };
                self.publish().await;
                if attempts >= 2 {
                    self.data.lock().await.snapshot.state = "FAILED".into();
                    self.publish().await;
                    break;
                }
                sleep(Duration::from_secs(1 + u64::from(attempts) * 2)).await;
                if self.stopped.load(Ordering::SeqCst)
                    || self.session.load(Ordering::SeqCst) != session
                {
                    break;
                }
                self.data.lock().await.snapshot.restart_count += 1;
                failure = self.spawn(session).await.err();
                startup = Instant::now();
            }
        }
    }
    async fn stop_child(&self) {
        let mut data = self.data.lock().await;
        data.epoch += 1;
        for (_, sender) in data.pending.drain() {
            let _ = sender.send(Err("VOICE_UNAVAILABLE".into()));
        }
        if let Some(writer) = &mut data.writer {
            let _ = timeout(Duration::from_millis(200), writer.write_all(b"shutdown\n")).await;
        }
        data.writer = None;
        if let Some(mut child) = data.child.take() {
            if timeout(Duration::from_secs(3), child.wait()).await.is_err() {
                let _ = child.start_kill();
                let _ = timeout(Duration::from_secs(2), child.wait()).await;
            }
        }
        data.job = None;
        if let Some(root) = &data.root {
            // Only direct regular WAVs inside our exact owned TempDir.
            if let Ok(entries) = std::fs::read_dir(root.path()) {
                for entry in entries.flatten() {
                    if entry.file_type().is_ok_and(|kind| kind.is_file())
                        && entry.path().extension().is_some_and(|ext| ext == "wav")
                    {
                        let _ = std::fs::remove_file(entry.path());
                    }
                }
            }
        }
    }
    pub async fn shutdown(&self) {
        self.stopped.store(true, Ordering::SeqCst);
        self.session.fetch_add(1, Ordering::SeqCst);
        let _guard = self.lifecycle.lock().await;
        self.data.lock().await.snapshot.state = "STOPPING".into();
        self.publish().await;
        self.stop_child().await;
        let mut data = self.data.lock().await;
        data.lease = None;
        data.root = None;
        data.snapshot.state = "STOPPED".into();
        drop(data);
        self.publish().await;
    }
    async fn cancel(&self, key: &str) {
        let mut data = self.data.lock().await;
        if let Some(sender) = data.pending.remove(key) {
            let _ = sender.send(Err("VOICE_CANCELLED".into()));
        }
        if let Some(writer) = &mut data.writer {
            let _ = timeout(
                Duration::from_millis(200),
                writer.write_all(format!("cancel\t{key}\n").as_bytes()),
            )
            .await;
        }
    }
    async fn synthesize(&self, request: Request) -> Receipt {
        let key = request.key()?;
        let (sender, receiver) = oneshot::channel();
        {
            let mut data = self.data.lock().await;
            if data.snapshot.state != "READY" || self.stopped.load(Ordering::SeqCst) {
                return Err("VOICE_UNAVAILABLE".into());
            }
            // Native worker is deliberately single-flight; no unbounded queue.
            if !data.pending.is_empty() {
                return Err("VOICE_BUSY".into());
            }
            let command = format!(
                "synthesize\t{key}\t{}\t{}\n",
                hex(request.text.as_bytes()),
                request.speed
            );
            let writer = data.writer.as_mut().ok_or("VOICE_UNAVAILABLE")?;
            timeout(Duration::from_secs(1), writer.write_all(command.as_bytes()))
                .await
                .map_err(|_| "VOICE_UNAVAILABLE")?
                .map_err(|_| "VOICE_UNAVAILABLE")?;
            data.pending.insert(key.clone(), sender);
        }
        match timeout(Duration::from_secs_f64(request.timeout_seconds), receiver).await {
            Ok(Ok(result)) => result,
            _ => {
                self.cancel(&key).await;
                Err("VOICE_TIMEOUT".into())
            }
        }
    }
    async fn serve(&self, listener: TcpListener, token: String, session: u64) {
        let slots = Arc::new(Semaphore::new(8));
        while !self.stopped.load(Ordering::SeqCst) && self.session.load(Ordering::SeqCst) == session
        {
            if let Ok(Ok((stream, _))) =
                timeout(Duration::from_millis(250), listener.accept()).await
            {
                let Ok(permit) = slots.clone().try_acquire_owned() else {
                    drop(stream);
                    continue;
                };
                let owner = self.clone();
                let token = token.clone();
                tokio::spawn(async move {
                    let _permit = permit;
                    let _ = owner.http(stream, &token, session).await;
                });
            }
        }
    }
    async fn http(&self, mut stream: TcpStream, token: &str, session: u64) -> Result<(), String> {
        let input = timeout(Duration::from_secs(2), read_http(&mut stream))
            .await
            .map_err(|_| "VOICE_IPC_TIMEOUT")??;
        let (path, authorization, body) = input;
        if self.stopped.load(Ordering::SeqCst) || self.session.load(Ordering::SeqCst) != session {
            return Err("VOICE_STOPPED".into());
        }
        let (status, kind, result) = if authorization != format!("Bearer {token}") {
            (401, "application/json", b"{}".to_vec())
        } else if path == "/health" {
            (
                200,
                "application/json",
                serde_json::to_vec(&self.snapshot().await).unwrap_or_default(),
            )
        } else if path == "/cancel" {
            if let Ok(request) = serde_json::from_slice::<Identity>(&body) {
                if let Ok(key) = request.key() {
                    self.cancel(&key).await;
                    (200, "application/json", b"{}".to_vec())
                } else {
                    (400, "application/json", b"{}".to_vec())
                }
            } else {
                (400, "application/json", b"{}".to_vec())
            }
        } else if path == "/synthesize" {
            if let Ok(request) = serde_json::from_slice::<Request>(&body) {
                match self.synthesize(request).await {
                    Ok(wav) => (200, "audio/wav", wav),
                    Err(code) => {
                        let status = match code.as_str() {
                            "VOICE_TIMEOUT" => 408,
                            "VOICE_UNAVAILABLE" => 503,
                            "VOICE_BUSY" => 409,
                            "VOICE_CANCELLED" => 410,
                            _ => 400,
                        };
                        (
                            status,
                            "application/json",
                            serde_json::to_vec(&json!({"error":code})).unwrap_or_default(),
                        )
                    }
                }
            } else {
                (400, "application/json", b"{}".to_vec())
            }
        } else {
            (404, "application/json", b"{}".to_vec())
        };
        let header = format!(
            "HTTP/1.1 {status} Response\r\nContent-Type: {kind}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            result.len()
        );
        timeout(Duration::from_secs(3), async {
            stream.write_all(header.as_bytes()).await?;
            stream.write_all(&result).await?;
            stream.shutdown().await
        })
        .await
        .map_err(|_| "VOICE_IPC_TIMEOUT")?
        .map_err(|_| "VOICE_IPC_CLOSED".into())
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Identity {
    generation_id: String,
    revision: u64,
}
impl Identity {
    fn key(&self) -> Result<String, String> {
        if self.generation_id.is_empty()
            || self.generation_id.len() > 128
            || self.revision == 0
            || self.revision > 9_007_199_254_740_991
        {
            return Err("INVALID_REQUEST".into());
        }
        Ok(hex(&Sha256::digest(
            format!("{}:{}", self.generation_id, self.revision).as_bytes(),
        )))
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    generation_id: String,
    revision: u64,
    text: String,
    timeout_seconds: f64,
    speaker: String,
    speed: f32,
}
impl Request {
    fn key(&self) -> Result<String, String> {
        if self.text.trim().is_empty()
            || self.text.len() > 8000
            || self.text.contains('\0')
            || self.speaker != "melo-fixed-0"
            || !self.timeout_seconds.is_finite()
            || self.timeout_seconds <= 0.
            || self.timeout_seconds > 120.
            || !self.speed.is_finite()
            || !(0.5..=2.).contains(&self.speed)
        {
            return Err("INVALID_REQUEST".into());
        }
        Identity {
            generation_id: self.generation_id.clone(),
            revision: self.revision,
        }
        .key()
    }
}
async fn read_http(stream: &mut TcpStream) -> Result<(String, String, Vec<u8>), String> {
    let mut raw = Vec::new();
    let mut byte = [0];
    while !raw.ends_with(b"\r\n\r\n") {
        if raw.len() >= 8192 {
            return Err("INVALID_HTTP".into());
        }
        stream
            .read_exact(&mut byte)
            .await
            .map_err(|_| "INVALID_HTTP")?;
        raw.push(byte[0]);
    }
    let header = std::str::from_utf8(&raw).map_err(|_| "INVALID_HTTP")?;
    let mut lines = header.split("\r\n");
    let parts = lines
        .next()
        .unwrap_or("")
        .split_whitespace()
        .collect::<Vec<_>>();
    if parts.len() != 3 || parts[0] != "POST" || parts[2] != "HTTP/1.1" {
        return Err("INVALID_HTTP".into());
    }
    let path = parts[1].to_string();
    let mut authorization = String::new();
    let mut length = None;
    for line in lines.filter(|line| !line.is_empty()) {
        let (name, value) = line.split_once(':').ok_or("INVALID_HTTP")?;
        if name.eq_ignore_ascii_case("authorization") {
            if !authorization.is_empty() {
                return Err("INVALID_HTTP".into());
            }
            authorization = value.trim().to_string();
        }
        if name.eq_ignore_ascii_case("transfer-encoding") {
            return Err("INVALID_HTTP".into());
        }
        if name.eq_ignore_ascii_case("content-length") {
            if length.is_some() {
                return Err("INVALID_HTTP".into());
            }
            length = Some(value.trim().parse::<usize>().map_err(|_| "INVALID_HTTP")?);
        }
    }
    let length = length.ok_or("INVALID_HTTP")?;
    if length > 32768 {
        return Err("INVALID_HTTP".into());
    }
    let mut body = vec![0; length];
    stream
        .read_exact(&mut body)
        .await
        .map_err(|_| "INVALID_HTTP")?;
    Ok((path, authorization, body))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn identity_and_contract_reject_paths_and_bad_options() {
        let request: Request =
            serde_json::from_value(json!({"generation_id":"g","revision":1,"text":"你好",
            "timeout_seconds":30,"speaker":"melo-fixed-0","speed":1}))
            .unwrap();
        assert_eq!(request.key().unwrap().len(), 64);
        assert_ne!(
            request.key().unwrap(),
            Identity {
                generation_id: "g".into(),
                revision: 2
            }
            .key()
            .unwrap()
        );
        assert!(
            Identity {
                generation_id: "".into(),
                revision: 1
            }
            .key()
            .is_err()
        );
        assert!(
            Identity {
                generation_id: "g".into(),
                revision: 0
            }
            .key()
            .is_err()
        );
        assert!(serde_json::from_value::<Request>(json!({"path":"C:/outside.wav"})).is_err());
        let mut invalid = request;
        invalid.speed = f32::NAN;
        assert!(invalid.key().is_err());
    }
    #[test]
    fn hash_gate_rejects_missing_and_changed_assets() {
        let root = tempfile::tempdir().unwrap();
        assert_eq!(
            verify(root.path(), ASSETS).unwrap_err(),
            "VOICE_MODEL_MISSING"
        );
        std::fs::write(root.path().join("model.onnx"), b"corrupt").unwrap();
        assert_eq!(
            verify(root.path(), ASSETS).unwrap_err(),
            "VOICE_ASSET_HASH_MISMATCH"
        );
    }
    #[test]
    fn public_diagnostics_have_no_private_launch_information() {
        let value = serde_json::to_value(Snapshot::default()).unwrap();
        for key in [
            "token",
            "endpoint",
            "pid",
            "path",
            "executable",
            "model_path",
        ] {
            assert!(value.get(key).is_none());
        }
    }
    #[test]
    fn orphan_cleanup_respects_live_leases_markers_and_unknown_content() {
        let parent = tempfile::tempdir().unwrap();
        for name in ["session-dead", "session-live", "session-unknown", "unowned"] {
            let root = parent.path().join(name);
            std::fs::create_dir(&root).unwrap();
            std::fs::write(root.join("owner"), OWNER_MARKER).unwrap();
            std::fs::write(root.join("lease"), b"").unwrap();
        }
        std::fs::write(
            parent.path().join("session-unknown/private.txt"),
            b"preserve",
        )
        .unwrap();
        let live = lease(&parent.path().join("session-live/lease"), false).unwrap();
        reap_orphans(parent.path());
        assert!(!parent.path().join("session-dead").exists());
        #[cfg(windows)]
        assert!(parent.path().join("session-live").exists());
        assert!(parent.path().join("session-unknown/private.txt").exists());
        assert!(parent.path().join("unowned").exists());
        drop(live);
    }
    #[tokio::test]
    async fn early_startup_failure_is_degraded_and_shutdown_is_safe() {
        let owner = LocalVoiceSupervisor::default();
        owner.startup_failed("VOICE_TEMP_FAILED").await;
        let snapshot = owner.snapshot().await;
        assert_eq!(snapshot.state, "DEGRADED");
        assert_eq!(snapshot.last_failure_class, "VOICE_TEMP_FAILED");
        assert!(owner.stopped.load(Ordering::SeqCst));
        owner.shutdown().await;
        assert_eq!(owner.snapshot().await.state, "STOPPED");
    }
    #[tokio::test]
    async fn shutdown_before_monitor_cannot_resurrect_runtime() {
        let owner = LocalVoiceSupervisor::default();
        let _ = owner.start().await.unwrap();
        owner.shutdown().await;
        sleep(Duration::from_millis(300)).await;
        assert_eq!(owner.snapshot().await.state, "STOPPED");
        assert!(owner.data.lock().await.child.is_none());
    }
    fn request(revision: u64, text: &str) -> Request {
        Request {
            generation_id: "real-voice-gate".into(),
            revision,
            text: text.into(),
            timeout_seconds: 30.,
            speaker: "melo-fixed-0".into(),
            speed: 1.,
        }
    }
    async fn ready(owner: &LocalVoiceSupervisor) {
        let deadline = Instant::now();
        loop {
            let snapshot = owner.snapshot().await;
            assert!(
                !matches!(snapshot.state.as_str(), "FAILED" | "DEGRADED"),
                "{snapshot:?}"
            );
            if snapshot.state == "READY" {
                return;
            }
            assert!(deadline.elapsed() < Duration::from_secs(35));
            sleep(Duration::from_millis(25)).await;
        }
    }
    #[tokio::test]
    #[ignore = "Explicit production asset/runtime gate; requires audited local assets"]
    async fn real_host_cancel_crash_bounded_restart_and_cleanup() {
        let owner = LocalVoiceSupervisor::default();
        owner.start().await.unwrap();
        ready(&owner).await;
        let root = owner
            .data
            .lock()
            .await
            .root
            .as_ref()
            .unwrap()
            .path()
            .to_owned();
        let wav = owner
            .synthesize(request(1, "你好，今天过得怎么样？"))
            .await
            .unwrap();
        assert_eq!(&wav[..4], b"RIFF");
        let stale = request(
            2,
            "安静阅读可以让我们集中注意力，理解新的知识，培养思考习惯，感受文字的美好，同时也能在忙碌生活中找到一段平静的时光。",
        );
        let key = stale.key().unwrap();
        let worker = owner.clone();
        let task = tokio::spawn(async move { worker.synthesize(stale).await });
        sleep(Duration::from_millis(100)).await;
        assert_eq!(
            owner
                .synthesize(request(7, "并发请求被拒绝。"))
                .await
                .unwrap_err(),
            "VOICE_BUSY"
        );
        owner.cancel(&key).await;
        assert_eq!(task.await.unwrap().unwrap_err(), "VOICE_CANCELLED");
        sleep(Duration::from_secs(5)).await;
        assert_eq!(
            std::fs::read_dir(&root)
                .unwrap()
                .filter_map(Result::ok)
                .filter(|e| e.path().extension().is_some_and(|ext| ext == "wav"))
                .count(),
            0
        );
        assert!(
            owner
                .synthesize(request(3, "你好，再次合成成功。"))
                .await
                .is_ok()
        );
        let mut expired = request(
            8,
            "安静阅读可以让我们集中注意力，理解新的知识，培养思考习惯，感受文字的美好，同时也能在忙碌生活中找到一段平静的时光。",
        );
        expired.timeout_seconds = 0.05;
        assert_eq!(
            owner.synthesize(expired).await.unwrap_err(),
            "VOICE_TIMEOUT"
        );
        sleep(Duration::from_secs(5)).await;
        assert_eq!(
            std::fs::read_dir(&root)
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry.path().extension().is_some_and(|ext| ext == "wav"))
                .count(),
            0
        );
        for attempt in 0..3 {
            owner
                .data
                .lock()
                .await
                .child
                .as_mut()
                .unwrap()
                .start_kill()
                .unwrap();
            let deadline = Instant::now();
            loop {
                let snapshot = owner.snapshot().await;
                if attempt < 2 && snapshot.restart_count == attempt + 1 && snapshot.state == "READY"
                {
                    break;
                }
                if attempt == 2 && snapshot.state == "FAILED" {
                    break;
                }
                assert!(deadline.elapsed() < Duration::from_secs(35), "{snapshot:?}");
                sleep(Duration::from_millis(50)).await;
            }
            if attempt < 2 {
                assert!(
                    owner
                        .synthesize(request(4 + u64::from(attempt), "恢复后可以朗读。"))
                        .await
                        .is_ok()
                );
            }
        }
        assert_eq!(owner.snapshot().await.restart_count, 2);
        owner.shutdown().await;
        assert!(!root.exists());
        assert!(owner.data.lock().await.child.is_none());
    }
}
