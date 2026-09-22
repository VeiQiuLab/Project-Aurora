//! Desktop-owned loopback runtime. Private launch data never implements Serialize/Debug.
use crate::sidecar::JobGuard;
use serde::{Deserialize, Serialize};
use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::Stdio,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Instant,
};
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    process::{Child, Command},
    sync::Mutex,
    time::{Duration, sleep, timeout},
};
use uuid::Uuid;

pub const RUNTIME_DIRECTORY: &str = "Aurora/runtime/llama-b10964-vulkan";

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RuntimeState {
    Stopped,
    Starting,
    LoadingModel,
    Ready,
    Degraded,
    Failed,
    Stopping,
}

#[derive(Clone)]
pub struct Handoff {
    pub endpoint: String,
    pub token: String,
    pub model: String,
}
impl Handoff {
    fn new(model: String) -> Result<Self, String> {
        let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|_| "LOCAL_PORT_FAILED")?;
        let port = listener
            .local_addr()
            .map_err(|_| "LOCAL_PORT_FAILED")?
            .port();
        Ok(Self {
            endpoint: format!("http://127.0.0.1:{port}"),
            token: format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple()),
            model,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalDiagnostics {
    pub provider: String,
    pub backend: String,
    pub state: String,
    pub configured_model: String,
    pub reachable: bool,
    pub model_available: bool,
    pub error_code: String,
    pub probe_duration_ms: f64,
}
impl LocalDiagnostics {
    pub fn validate(&self) -> Result<(), String> {
        if self.provider != "builtin_local"
            || self.backend != "vulkan"
            || !matches!(
                self.state.as_str(),
                "STOPPED"
                    | "STARTING"
                    | "LOADING_MODEL"
                    | "READY"
                    | "DEGRADED"
                    | "FAILED"
                    | "STOPPING"
            )
            || !matches!(self.error_code.as_str(), "" | "LOCAL_MODEL_UNAVAILABLE")
            || self.configured_model.len() > 200
            || self.configured_model.is_empty()
            || !self
                .configured_model
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || "_.-".contains(c))
            || !self.probe_duration_ms.is_finite()
            || self.probe_duration_ms < 0.0
        {
            return Err("INVALID_LOCAL_MODEL_DIAGNOSTICS".into());
        }
        Ok(())
    }
}

#[derive(Clone)]
pub struct ModelConfig {
    pub executable: PathBuf,
    pub model: PathBuf,
    pub context: u32,
}

fn gguf_model(path: &Path) -> Result<(), String> {
    if !path.is_absolute() || path.extension().and_then(|s| s.to_str()) != Some("gguf") {
        return Err("INVALID_MODEL_PATH".into());
    }
    let mut file = std::fs::File::open(path).map_err(|_| "MODEL_NOT_FOUND")?;
    let mut header = [0u8; 24];
    file.read_exact(&mut header).map_err(|_| "INVALID_GGUF")?;
    if &header[..4] != b"GGUF" || u32::from_le_bytes(header[4..8].try_into().unwrap()) != 3 {
        return Err("INVALID_GGUF".into());
    }
    Ok(())
}

// Bounded to the LM Studio model root, never a drive scan. Ignore symlink/reparse dirs.
fn candidates(root: &Path, depth: usize, output: &mut Vec<PathBuf>) -> Result<(), String> {
    if !root.is_absolute() || root.parent().is_none() {
        return Err("INVALID_MODEL_DIRECTORY".into());
    }
    let mut budget = 4096;
    scan_candidates(root, depth, output, &mut budget)
}
fn scan_candidates(
    root: &Path,
    depth: usize,
    output: &mut Vec<PathBuf>,
    budget: &mut usize,
) -> Result<(), String> {
    if depth > 4 {
        return Ok(());
    }
    let entries = std::fs::read_dir(root).map_err(|_| "MODEL_DIRECTORY_UNAVAILABLE")?;
    for entry in entries {
        if *budget == 0 {
            return Err("MODEL_DIRECTORY_LIMIT".into());
        }
        *budget -= 1;
        let entry = entry.map_err(|_| "MODEL_DIRECTORY_UNAVAILABLE")?;
        let kind = entry
            .file_type()
            .map_err(|_| "MODEL_DIRECTORY_UNAVAILABLE")?;
        if kind.is_symlink() {
            continue;
        }
        if kind.is_dir() {
            scan_candidates(&entry.path(), depth + 1, output, budget)?;
        } else if kind.is_file() {
            let name = entry.file_name().to_string_lossy().to_lowercase();
            if name.ends_with(".gguf") && !name.starts_with("mmproj") {
                output.push(entry.path());
            }
        }
    }
    Ok(())
}

impl ModelConfig {
    pub fn discover() -> Result<Self, String> {
        let local = std::env::var_os("LOCALAPPDATA").ok_or("LOCAL_APPDATA_UNAVAILABLE")?;
        let executable = std::env::var_os("AURORA_LLAMA_SERVER")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(local)
                    .join(RUNTIME_DIRECTORY)
                    .join("llama-server.exe")
            });
        if !executable.is_absolute() || !executable.is_file() {
            return Err("RUNTIME_NOT_INSTALLED".into());
        }
        let model = if let Some(path) = std::env::var_os("AURORA_LOCAL_MODEL_PATH") {
            PathBuf::from(path)
        } else {
            let user =
                PathBuf::from(std::env::var_os("USERPROFILE").ok_or("MODEL_NOT_CONFIGURED")?);
            let settings: serde_json::Value = std::fs::read(user.join(".lmstudio/settings.json"))
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .unwrap_or_default();
            let root = settings["downloadsFolder"]
                .as_str()
                .map(PathBuf::from)
                .unwrap_or(user.join(".lmstudio/models"));
            if !root.is_absolute() {
                return Err("INVALID_MODEL_DIRECTORY".into());
            }
            let mut found = Vec::new();
            candidates(&root, 0, &mut found)?;
            if found.len() != 1 {
                return Err("MODEL_SELECTION_REQUIRED".into());
            }
            found.remove(0)
        };
        gguf_model(&model)?;
        Ok(Self {
            executable,
            model,
            context: 4096,
        })
    }
    fn identity(&self) -> String {
        self.model
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("aurora-local")
            .chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || "_.-".contains(c) {
                    c
                } else {
                    '_'
                }
            })
            .take(200)
            .collect()
    }
}

struct Data {
    state: RuntimeState,
    epoch: u64,
    child: Option<Child>,
    job: Option<JobGuard>,
    handoff: Option<Handoff>,
    error: String,
}
impl Default for Data {
    fn default() -> Self {
        Self {
            state: RuntimeState::Stopped,
            epoch: 0,
            child: None,
            job: None,
            handoff: None,
            error: String::new(),
        }
    }
}
#[derive(Clone, Default)]
pub struct LocalModelSupervisor {
    inner: Arc<Mutex<Data>>,
}

impl LocalModelSupervisor {
    pub async fn start(&self, cancelled: Arc<AtomicBool>) -> Result<Handoff, String> {
        if cancelled.load(Ordering::SeqCst) {
            return Err("LOCAL_STARTUP_SUPERSEDED".into());
        }
        let config = ModelConfig::discover();
        self.start_owned(config, cancelled).await
    }
    #[cfg(test)]
    pub async fn start_config(
        &self,
        config: Result<ModelConfig, String>,
    ) -> Result<Handoff, String> {
        self.start_owned(config, Arc::new(AtomicBool::new(false)))
            .await
    }
    async fn start_owned(
        &self,
        config: Result<ModelConfig, String>,
        cancelled: Arc<AtomicBool>,
    ) -> Result<Handoff, String> {
        let started = Instant::now();
        let (epoch, handoff) = {
            let mut data = self.inner.lock().await;
            if cancelled.load(Ordering::SeqCst) {
                return Err("LOCAL_STARTUP_SUPERSEDED".into());
            }
            if data.state != RuntimeState::Stopped {
                return Err("LOCAL_RUNTIME_ALREADY_STARTED".into());
            }
            data.epoch += 1;
            data.state = RuntimeState::Starting;
            let handoff = Handoff::new(
                config
                    .as_ref()
                    .map(|c| c.identity())
                    .unwrap_or("aurora-local".into()),
            )?;
            data.handoff = Some(handoff.clone());
            (data.epoch, handoff)
        };
        let result = self.spawn(config, &handoff, epoch, &cancelled).await;
        if let Err(code) = result {
            self.fail(epoch, &code).await;
            // Start Python even when the model fails: Settings/history remain available.
            return Ok(handoff);
        }
        loop {
            {
                let mut data = self.inner.lock().await;
                if data.epoch != epoch || cancelled.load(Ordering::SeqCst) {
                    return Err("LOCAL_STARTUP_SUPERSEDED".into());
                }
                if data
                    .child
                    .as_mut()
                    .is_none_or(|p| p.try_wait().ok().flatten().is_some())
                {
                    drop(data);
                    self.fail(epoch, "LOCAL_PROCESS_EXITED").await;
                    return Ok(handoff);
                }
            }
            let private = handoff.clone();
            let ready = tokio::task::spawn_blocking(move || runtime_ready(&private))
                .await
                .unwrap_or(false);
            if ready {
                let mut data = self.inner.lock().await;
                if data.epoch != epoch || cancelled.load(Ordering::SeqCst) {
                    return Err("LOCAL_STARTUP_SUPERSEDED".into());
                }
                data.state = RuntimeState::Ready;
                eprintln!(
                    "[aurora-local] state=READY backend=vulkan context=4096 load_ms={:.1}",
                    started.elapsed().as_secs_f64() * 1000.0
                );
                return Ok(handoff);
            }
            if started.elapsed() > Duration::from_secs(120) {
                self.fail(epoch, "LOCAL_LOAD_TIMEOUT").await;
                return Ok(handoff);
            }
            sleep(Duration::from_millis(100)).await;
        }
    }
    async fn spawn(
        &self,
        config: Result<ModelConfig, String>,
        handoff: &Handoff,
        epoch: u64,
        cancelled: &AtomicBool,
    ) -> Result<(), String> {
        let config = config?;
        let port = handoff
            .endpoint
            .rsplit(':')
            .next()
            .ok_or("LOCAL_PORT_FAILED")?;
        let mut command = Command::new(&config.executable);
        command.current_dir(config.executable.parent().ok_or("RUNTIME_NOT_INSTALLED")?);
        #[cfg(test)]
        let fixture = std::env::current_exe().ok().as_ref() == Some(&config.executable);
        #[cfg(not(test))]
        let fixture = false;
        if fixture {
            command
                .args([
                    "--exact",
                    "local_model::tests::fixture_runtime_child",
                    "--nocapture",
                ])
                .env("AURORA_TEST_RUNTIME_PORT", port)
                .env("AURORA_TEST_RUNTIME_MODEL", &handoff.model);
        } else {
            command
                .arg("--model")
                .arg(&config.model)
                .args(["--host", "127.0.0.1", "--port", port])
                .args([
                    "--ctx-size",
                    &config.context.to_string(),
                    "--parallel",
                    "1",
                    "--device",
                    "Vulkan0",
                    "--gpu-layers",
                    "auto",
                    "--fit",
                    "on",
                ])
                .args([
                    "--reasoning",
                    "off",
                    "--no-webui",
                    "--log-colors",
                    "off",
                    "--log-verbosity",
                    "4",
                    "--alias",
                    &handoff.model,
                ]);
        }
        command
            .env("LLAMA_API_KEY", &handoff.token)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        #[cfg(windows)]
        {
            command.creation_flags(0x0800_0000);
        }
        let mut data = self.inner.lock().await;
        if data.epoch != epoch || cancelled.load(Ordering::SeqCst) {
            return Err("LOCAL_STARTUP_SUPERSEDED".into());
        }
        let mut child = command.spawn().map_err(|_| "LOCAL_SPAWN_FAILED")?;
        let job = JobGuard::assign(child.id().ok_or("LOCAL_SPAWN_FAILED")?)?;
        if let Some(out) = child.stdout.take() {
            tokio::spawn(drain(out));
        }
        if let Some(err) = child.stderr.take() {
            tokio::spawn(drain(err));
        }
        data.child = Some(child);
        data.job = Some(job);
        data.state = RuntimeState::LoadingModel;
        eprintln!("[aurora-local] state=LOADING_MODEL backend=vulkan");
        Ok(())
    }
    async fn fail(&self, epoch: u64, code: &str) {
        let mut data = self.inner.lock().await;
        if data.epoch != epoch {
            return;
        }
        if let Some(mut child) = data.child.take() {
            let _ = child.start_kill();
            let _ = timeout(Duration::from_secs(3), child.wait()).await;
        }
        data.job = None;
        data.state = RuntimeState::Failed;
        data.error = code.to_owned();
        eprintln!("[aurora-local] state=FAILED code={code}");
    }
    pub async fn exited(&self) -> bool {
        let mut data = self.inner.lock().await;
        if data.state != RuntimeState::Ready {
            return false;
        }
        let exited = data
            .child
            .as_mut()
            .is_none_or(|c| c.try_wait().ok().flatten().is_some());
        if exited {
            data.child = None;
            data.job = None;
            data.state = RuntimeState::Failed;
            data.error = "LOCAL_PROCESS_EXITED".into();
        }
        exited
    }
    pub async fn shutdown(&self) {
        let mut data = self.inner.lock().await;
        data.epoch += 1;
        data.state = RuntimeState::Stopping;
        if let Some(mut child) = data.child.take() {
            let _ = child.start_kill();
            let _ = timeout(Duration::from_secs(3), child.wait()).await;
        }
        data.job = None;
        data.handoff = None;
        data.state = RuntimeState::Stopped;
    }
}

// Health is public upstream; authenticated /v1/models additionally proves API/key readiness.
fn get_json(handoff: &Handoff, path: &str) -> Option<serde_json::Value> {
    let address = handoff.endpoint.strip_prefix("http://")?;
    let mut socket = TcpStream::connect_timeout(
        &address.parse().ok()?,
        std::time::Duration::from_millis(400),
    )
    .ok()?;
    socket
        .set_read_timeout(Some(std::time::Duration::from_millis(500)))
        .ok()?;
    socket
        .set_write_timeout(Some(std::time::Duration::from_millis(500)))
        .ok()?;
    write!(socket, "GET {path} HTTP/1.0\r\nHost: {address}\r\nAuthorization: Bearer {}\r\nConnection: close\r\n\r\n", handoff.token).ok()?;
    let mut raw = String::new();
    socket.take(131073).read_to_string(&mut raw).ok()?;
    if raw.len() > 131072 || !raw.starts_with("HTTP/1.1 200") && !raw.starts_with("HTTP/1.0 200") {
        return None;
    }
    serde_json::from_str(raw.split_once("\r\n\r\n")?.1).ok()
}
fn runtime_ready(handoff: &Handoff) -> bool {
    get_json(handoff, "/health").is_some_and(|j| j["status"] == "ok")
        && get_json(handoff, "/v1/models")
            .and_then(|j| j["data"].as_array().cloned())
            .is_some_and(|a| a.iter().any(|m| m["id"] == handoff.model))
}
fn resource_metric(text: &str) -> Option<(&'static str, f64)> {
    let text = text
        .split_once(" I ")
        .map_or(text, |(_, message)| message)
        .trim();
    // Fixed upstream prefixes and numeric values only; no path/prompt/model text.
    let key = if text.starts_with("load_tensors:") && text.contains("Vulkan0 model buffer size") {
        "gpu_model_mib"
    } else if text.starts_with("llama_kv_cache:") && text.contains("KV buffer size") {
        "kv_cache_mib"
    } else if text.starts_with("llama_memory_recurrent:") && text.contains("RS buffer size") {
        "recurrent_state_mib"
    } else if text.starts_with("sched_reserve:") && text.contains("Vulkan0 compute buffer size") {
        "gpu_compute_mib"
    } else {
        return None;
    };
    let value: f64 = text
        .split("buffer size =")
        .nth(1)?
        .split_whitespace()
        .next()?
        .parse()
        .ok()?;
    (value.is_finite() && value >= 0.0).then_some((key, value))
}
async fn drain<T: tokio::io::AsyncRead + Unpin>(stream: T) {
    let mut stream = BufReader::new(stream);
    // Raw output can include prompt/template/path. Classify then discard, never forward it.
    loop {
        let mut line = Vec::new();
        match tokio::io::AsyncReadExt::take(&mut stream, 16384)
            .read_until(b'\n', &mut line)
            .await
        {
            Ok(0) | Err(_) => break,
            Ok(_) => {
                let raw = String::from_utf8_lossy(&line);
                if let Some((key, value)) = resource_metric(raw.trim()) {
                    eprintln!("[aurora-local] metric={key} value={value}");
                }
                let message = raw
                    .split_once(" I ")
                    .map_or(raw.as_ref(), |(_, message)| message)
                    .trim();
                if let Some(counts) = message
                    .strip_prefix("load_tensors: offloaded ")
                    .and_then(|s| s.split_whitespace().next())
                {
                    if let Some((used, total)) = counts
                        .split_once('/')
                        .and_then(|(a, b)| Some((a.parse::<u32>().ok()?, b.parse::<u32>().ok()?)))
                    {
                        eprintln!(
                            "[aurora-local] metric=gpu_offload_layers used={used} total={total}"
                        );
                    }
                }
                let text = raw.to_lowercase();
                let code = if text.contains("out of memory") {
                    Some("OUT_OF_MEMORY")
                } else if text.contains("error") || text.contains("failed") {
                    Some("RUNTIME_ERROR")
                } else {
                    None
                };
                if let Some(code) = code {
                    eprintln!("[aurora-local] event=runtime_stderr code={code}");
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dynamic_private_handoff() {
        let a = Handoff::new("fixture".into()).unwrap();
        let b = Handoff::new("fixture".into()).unwrap();
        assert!(a.endpoint.starts_with("http://127.0.0.1:"));
        assert_eq!(a.token.len(), 64);
        assert_ne!(a.token, b.token);
        assert!(!runtime_ready(&a));
    }
    #[test]
    fn rejects_invalid_model() {
        assert!(gguf_model(Path::new("relative.gguf")).is_err());
    }
    #[test]
    fn bounded_discovery_excludes_projector_and_validates_header() {
        let root = std::env::temp_dir().join(format!("aurora-model-fixture-{}", Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let model = root.join("fixture.gguf");
        let mut header = vec![0u8; 24];
        header[..4].copy_from_slice(b"GGUF");
        header[4] = 3;
        std::fs::write(&model, &header).unwrap();
        std::fs::write(root.join("mmproj-fixture.gguf"), &header).unwrap();
        let mut found = Vec::new();
        candidates(&root, 0, &mut found).unwrap();
        assert_eq!(found, vec![model.clone()]);
        gguf_model(&model).unwrap();
        std::fs::write(&model, b"bad").unwrap();
        assert!(gguf_model(&model).is_err());
        let mut budget = 0;
        assert_eq!(
            scan_candidates(&root, 0, &mut Vec::new(), &mut budget).unwrap_err(),
            "MODEL_DIRECTORY_LIMIT"
        );
        assert!(candidates(Path::new("C:\\"), 0, &mut Vec::new()).is_err());
        std::fs::remove_file(model).unwrap();
        std::fs::remove_file(root.join("mmproj-fixture.gguf")).unwrap();
        std::fs::remove_dir(root).unwrap();
    }
    #[test]
    fn resource_logs_only_export_numeric_allowlisted_fields() {
        assert_eq!(
            resource_metric("load_tensors: Vulkan0 model buffer size = 2400.50 MiB"),
            Some(("gpu_model_mib", 2400.5))
        );
        assert_eq!(
            resource_metric("llama_kv_cache: Vulkan0 KV buffer size = 64.00 MiB"),
            Some(("kv_cache_mib", 64.0))
        );
        assert_eq!(
            resource_metric(
                "0.02.560.863 I llama_kv_cache:    Vulkan0 KV buffer size =   128.00 MiB"
            ),
            Some(("kv_cache_mib", 128.0))
        );
        assert!(resource_metric("prompt secret buffer size = 123 MiB").is_none());
        assert!(resource_metric("load_tensors: Vulkan0 model buffer size = NaN MiB").is_none());
    }
    #[test]
    fn fixture_runtime_child() {
        let Ok(port) = std::env::var("AURORA_TEST_RUNTIME_PORT") else {
            return;
        };
        let model = std::env::var("AURORA_TEST_RUNTIME_MODEL").unwrap();
        if model == "crash" {
            return;
        }
        let token = std::env::var("LLAMA_API_KEY").unwrap();
        let listener = TcpListener::bind(format!("127.0.0.1:{port}")).unwrap();
        for mut socket in listener.incoming().flatten() {
            socket
                .set_read_timeout(Some(std::time::Duration::from_secs(2)))
                .unwrap();
            let mut buf = Vec::new();
            while !buf.ends_with(b"\r\n\r\n") && buf.len() < 8192 {
                let mut byte = [0u8; 1];
                if socket.read(&mut byte).unwrap_or(0) == 0 {
                    break;
                }
                buf.push(byte[0]);
            }
            let request = String::from_utf8_lossy(&buf);
            let (code, body) = if model == "loading" {
                ("503", "{}".to_owned())
            } else if request.starts_with("GET /health ") {
                ("200", "{\"status\":\"ok\"}".to_owned())
            } else if request.contains(&format!("Bearer {token}")) {
                (
                    "200",
                    serde_json::json!({"data":[{"id":model}]}).to_string(),
                )
            } else {
                ("401", "{}".to_owned())
            };
            let _ = write!(
                socket,
                "HTTP/1.1 {code} OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
        }
    }
    fn fixture(model: &str) -> ModelConfig {
        ModelConfig {
            executable: std::env::current_exe().unwrap(),
            model: PathBuf::from(format!("{model}.gguf")),
            context: 4096,
        }
    }
    #[tokio::test]
    async fn cancelled_owner_waiting_for_supervisor_lock_cannot_spawn_or_harm_next() {
        let supervisor = LocalModelSupervisor::default();
        let owner = Arc::new(AtomicBool::new(false));
        let guard = supervisor.inner.lock().await;
        let other = supervisor.clone();
        let old = owner.clone();
        let work =
            tokio::spawn(async move { other.start_owned(Ok(fixture("fixture")), old).await });
        tokio::task::yield_now().await;
        owner.store(true, Ordering::SeqCst);
        drop(guard);
        supervisor.shutdown().await;
        assert!(work.await.unwrap().is_err());
        assert!(supervisor.inner.lock().await.child.is_none());
        let next = supervisor
            .start_config(Ok(fixture("fixture")))
            .await
            .unwrap();
        assert!(
            supervisor
                .start_owned(Ok(fixture("fixture")), owner)
                .await
                .is_err()
        );
        assert!(runtime_ready(&next));
        supervisor.shutdown().await;
    }
    #[tokio::test]
    async fn spawn_auth_ready_crash_restart_shutdown_no_duplicate() {
        let supervisor = LocalModelSupervisor::default();
        let first = supervisor
            .start_config(Ok(fixture("fixture")))
            .await
            .unwrap();
        assert_eq!(supervisor.inner.lock().await.state, RuntimeState::Ready);
        assert!(runtime_ready(&first));
        let mut bad = first.clone();
        bad.token = "wrong".into();
        assert!(!runtime_ready(&bad));
        assert!(
            supervisor
                .start_config(Ok(fixture("fixture")))
                .await
                .is_err()
        );
        {
            let mut data = supervisor.inner.lock().await;
            data.child.as_mut().unwrap().kill().await.unwrap();
        }
        assert!(supervisor.exited().await);
        assert_eq!(supervisor.inner.lock().await.state, RuntimeState::Failed);
        supervisor.shutdown().await;
        let second = supervisor
            .start_config(Ok(fixture("fixture")))
            .await
            .unwrap();
        assert_ne!(first.token, second.token);
        assert!(runtime_ready(&second));
        supervisor.shutdown().await;
        assert!(!runtime_ready(&second));
    }
    #[tokio::test]
    async fn loading_shutdown_cannot_resurrect() {
        let supervisor = LocalModelSupervisor::default();
        let other = supervisor.clone();
        let work = tokio::spawn(async move { other.start_config(Ok(fixture("loading"))).await });
        timeout(Duration::from_secs(5), async {
            loop {
                if supervisor.inner.lock().await.state == RuntimeState::LoadingModel {
                    break;
                }
                sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        supervisor.shutdown().await;
        assert!(work.await.unwrap().is_err());
        assert_eq!(supervisor.inner.lock().await.state, RuntimeState::Stopped);
        assert!(supervisor.inner.lock().await.child.is_none());
    }
    #[tokio::test]
    async fn early_exit_is_failed_not_ready() {
        let supervisor = LocalModelSupervisor::default();
        supervisor.start_config(Ok(fixture("crash"))).await.unwrap();
        assert_eq!(supervisor.inner.lock().await.state, RuntimeState::Failed);
        supervisor.shutdown().await;
    }
    #[cfg(windows)]
    #[test]
    fn job_drop_terminates_owned_process() {
        let mut child = std::process::Command::new("cmd.exe")
            .args(["/c", "ping -n 30 127.0.0.1 >nul"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let job = JobGuard::assign(child.id()).unwrap();
        drop(job);
        let started = Instant::now();
        while child.try_wait().unwrap().is_none() && started.elapsed() < Duration::from_secs(3) {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(child.try_wait().unwrap().is_some());
    }
    #[test]
    fn public_diagnostics_reject_private_fields() {
        let raw = serde_json::json!({"provider":"builtin_local","backend":"vulkan","state":"READY","configured_model":"fixture","reachable":true,"model_available":true,"error_code":"","probe_duration_ms":1.0});
        let d: LocalDiagnostics = serde_json::from_value(raw.clone()).unwrap();
        d.validate().unwrap();
        for key in ["token", "endpoint", "pid", "model_path"] {
            let mut bad = raw.clone();
            bad[key] = "private".into();
            assert!(serde_json::from_value::<LocalDiagnostics>(bad).is_err());
        }
    }
    #[tokio::test]
    async fn failure_still_provides_private_handoff_and_restarts() {
        let supervisor = LocalModelSupervisor::default();
        let old = supervisor
            .start_config(Err("MODEL_NOT_FOUND".into()))
            .await
            .unwrap();
        assert_eq!(supervisor.inner.lock().await.state, RuntimeState::Failed);
        assert!(supervisor.start_config(Err("BAD".into())).await.is_err());
        supervisor.shutdown().await;
        supervisor.shutdown().await;
        let new = supervisor
            .start_config(Err("INVALID_GGUF".into()))
            .await
            .unwrap();
        assert_ne!(old.token, new.token);
        supervisor.shutdown().await;
        assert!(supervisor.inner.lock().await.handoff.is_none());
    }
}
