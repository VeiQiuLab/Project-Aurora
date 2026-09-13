use std::{
    path::PathBuf,
    process::Stdio,
    sync::{Arc, Mutex as StdMutex},
    time::Instant,
};

use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tauri::ipc::Channel;
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, BufReader},
    process::{Child, Command},
    sync::{Mutex, mpsc},
    time::{Duration, timeout},
};
use tokio_tungstenite::{
    connect_async,
    tungstenite::{
        Message,
        client::IntoClientRequest,
        http::{HeaderValue, header::AUTHORIZATION},
    },
};
use uuid::Uuid;

use crate::{
    protocol::{
        BOOTSTRAP_MAX_BYTES, BackendSnapshot, BackendState, BootstrapReady, CancelTarget,
        ChatStartResult, FrontendEvent, PROTOCOL, PrototypeMetrics, VERSION, chat_cancel,
        chat_request, health, hello, object, require_string, shutdown, validate_hello_ack,
        validate_sidecar_event,
    },
    registry::{RequestOwner, RequestRegistry},
};

const STARTUP_TIMEOUT: Duration = Duration::from_secs(10);
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(5);
const SHUTDOWN_GRACE: Duration = Duration::from_millis(300);
const WRITER_CAPACITY: usize = 32;

#[derive(Debug)]
struct SidecarLaunch {
    python: PathBuf,
    script: PathBuf,
    working_directory: PathBuf,
    python_path: PathBuf,
}

#[derive(Debug)]
struct BackendData {
    state: BackendState,
    epoch: u64,
    child: Option<Arc<Mutex<Child>>>,
    job: Option<JobGuard>,
    writer: Option<mpsc::Sender<Message>>,
    sidecar_instance_id: Option<String>,
    registry: RequestRegistry,
    session_id: String,
    negotiated_chat_input_max_bytes: usize,
    metrics: PrototypeMetrics,
    request_started: std::collections::HashMap<(String, String), Instant>,
    cancel_started: std::collections::HashMap<(String, String), Instant>,
    crash_requested_at: Option<Instant>,
    restart_started_at: Option<Instant>,
}

impl BackendData {
    fn new() -> Self {
        Self {
            state: BackendState::Stopped,
            epoch: 0,
            child: None,
            job: None,
            writer: None,
            sidecar_instance_id: None,
            registry: RequestRegistry::default(),
            session_id: format!("session-{}", Uuid::new_v4().simple()),
            negotiated_chat_input_max_bytes: 0,
            metrics: PrototypeMetrics::default(),
            request_started: Default::default(),
            cancel_started: Default::default(),
            crash_requested_at: None,
            restart_started_at: None,
        }
    }
}

#[derive(Clone)]
pub struct BackendManager {
    inner: Arc<Mutex<BackendData>>,
    frontend: Arc<StdMutex<Option<Channel<FrontendEvent>>>>,
    desktop_started: Instant,
}

impl BackendManager {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(BackendData::new())),
            frontend: Arc::new(StdMutex::new(None)),
            desktop_started: Instant::now(),
        }
    }

    pub async fn register_channel(&self, channel: Channel<FrontendEvent>) -> BackendSnapshot {
        *self
            .frontend
            .lock()
            .expect("frontend channel lock poisoned") = Some(channel);
        let mut data = self.inner.lock().await;
        data.metrics.desktop_startup_ms = elapsed_ms(self.desktop_started);
        let snapshot = BackendSnapshot {
            state: data.state,
            metrics: data.metrics.clone(),
        };
        drop(data);
        self.emit(FrontendEvent::BackendState {
            state: snapshot.state,
            metrics: snapshot.metrics.clone(),
        });
        snapshot
    }

    pub async fn snapshot(&self) -> BackendSnapshot {
        let mut data = self.inner.lock().await;
        data.metrics.desktop_startup_ms = elapsed_ms(self.desktop_started);
        BackendSnapshot {
            state: data.state,
            metrics: data.metrics.clone(),
        }
    }

    pub async fn start(&self, restarting: bool) -> Result<(), String> {
        {
            let mut data = self.inner.lock().await;
            if matches!(
                data.state,
                BackendState::Starting | BackendState::Handshaking | BackendState::Ready
            ) {
                return Ok(());
            }
            data.epoch += 1;
            if restarting {
                data.restart_started_at = Some(Instant::now());
                data.state = BackendState::Restarting;
            } else {
                data.state = BackendState::Starting;
            }
        }
        self.emit_state().await;

        let result = self.start_once().await;
        if let Err(error) = &result {
            eprintln!("[aurora-v4] event=sidecar_start_failed error={error}");
            let mut data = self.inner.lock().await;
            data.state = BackendState::Disconnected;
            data.writer = None;
            data.child = None;
            data.job = None;
            data.sidecar_instance_id = None;
            drop(data);
            self.emit_state().await;
        }
        result
    }

    async fn start_once(&self) -> Result<(), String> {
        let spawn_started = Instant::now();
        let launch = find_sidecar_launch()?;
        let token = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
        let mut command = Command::new(&launch.python);
        command
            .arg("-u")
            .arg(&launch.script)
            .current_dir(&launch.working_directory)
            .env("AURORA_IPC_TOKEN", &token)
            .env("AURORA_IPC_PROTOCOL", PROTOCOL)
            .env("AURORA_IPC_SUPPORTED_VERSIONS", VERSION.to_string())
            .env("AURORA_MOCK_DELTA_DELAY_MS", "45")
            .env("PYTHONNOUSERSITE", "1")
            .env("PYTHONPATH", &launch.python_path)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.as_std_mut().creation_flags(0x0800_0000);
        }
        let mut child = command.spawn().map_err(|error| error.to_string())?;
        let child_pid = child
            .id()
            .ok_or_else(|| "sidecar child has no PID".to_string())?;
        let job = match JobGuard::assign(child_pid) {
            Ok(job) => job,
            Err(error) => {
                let _ = child.start_kill();
                return Err(error);
            }
        };
        eprintln!("[aurora-v4] event=sidecar_spawn pid={child_pid}");

        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "sidecar stdout unavailable".to_string())?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| "sidecar stderr unavailable".to_string())?;
        tokio::spawn(drain_stderr(stderr));

        let mut bootstrap_bytes = Vec::new();
        let mut limited_stdout = BufReader::new(stdout).take(BOOTSTRAP_MAX_BYTES + 1);
        let bytes_read = timeout(
            STARTUP_TIMEOUT,
            limited_stdout.read_until(b'\n', &mut bootstrap_bytes),
        )
        .await
        .map_err(|_| "sidecar bootstrap timed out".to_string())?
        .map_err(|error| error.to_string())?;
        if bytes_read == 0
            || bytes_read as u64 > BOOTSTRAP_MAX_BYTES
            || !bootstrap_bytes.ends_with(b"\n")
        {
            return Err("sidecar bootstrap line is empty, too large, or incomplete".into());
        }
        let bootstrap: BootstrapReady =
            serde_json::from_slice(&bootstrap_bytes).map_err(|error| error.to_string())?;
        bootstrap.validate()?;
        eprintln!(
            "[aurora-v4] event=sidecar_bootstrap child_pid={} runtime_pid={}",
            child_pid, bootstrap.pid
        );
        let bootstrap_received = Instant::now();
        {
            let mut data = self.inner.lock().await;
            data.metrics.spawn_to_bootstrap_ms = Some(elapsed_ms(spawn_started));
            data.state = BackendState::Handshaking;
        }
        self.emit_state().await;

        let mut request = format!("ws://127.0.0.1:{}", bootstrap.port)
            .into_client_request()
            .map_err(|error| error.to_string())?;
        request.headers_mut().insert(
            AUTHORIZATION,
            HeaderValue::from_str(&format!("Bearer {token}")).map_err(|error| error.to_string())?,
        );
        let (mut socket, _) = timeout(HANDSHAKE_TIMEOUT, connect_async(request))
            .await
            .map_err(|_| "sidecar WebSocket connect timed out".to_string())?
            .map_err(|error| error.to_string())?;
        let hello_id = format!("hello-{}", Uuid::new_v4().simple());
        socket
            .send(Message::Text(hello(&hello_id).to_string().into()))
            .await
            .map_err(|error| error.to_string())?;
        let ack = timeout(HANDSHAKE_TIMEOUT, socket.next())
            .await
            .map_err(|_| "sidecar hello_ack timed out".to_string())?
            .ok_or_else(|| "sidecar closed during handshake".to_string())?
            .map_err(|error| error.to_string())?;
        let ack_text = ack
            .to_text()
            .map_err(|_| "sidecar hello_ack must be JSON text".to_string())?;
        let ack_value: Value = serde_json::from_str(ack_text).map_err(|error| error.to_string())?;
        let sidecar_instance_id = validate_hello_ack(&ack_value, &hello_id)?;
        if sidecar_instance_id != bootstrap.sidecar_instance_id {
            return Err("sidecar_instance_id changed during handshake".into());
        }
        let negotiated_limit = object(&ack_value, "payload")?
            .get("limits")
            .and_then(Value::as_object)
            .and_then(|limits| limits.get("chat_input_max_bytes"))
            .and_then(Value::as_u64)
            .and_then(|limit| usize::try_from(limit).ok())
            .ok_or_else(|| "invalid chat_input_max_bytes".to_string())?;

        let (mut socket_writer, mut socket_reader) = socket.split();
        let (writer, mut messages) = mpsc::channel::<Message>(WRITER_CAPACITY);
        let epoch;
        let child = Arc::new(Mutex::new(child));
        {
            let mut data = self.inner.lock().await;
            epoch = data.epoch;
            data.metrics.bootstrap_to_ready_ms = Some(elapsed_ms(bootstrap_received));
            if let Some(restart_started) = data.restart_started_at.take() {
                data.metrics.restart_to_ready_ms = Some(elapsed_ms(restart_started));
            }
            data.child = Some(child);
            data.job = Some(job);
            data.writer = Some(writer.clone());
            data.sidecar_instance_id = Some(sidecar_instance_id);
            data.negotiated_chat_input_max_bytes = negotiated_limit;
            data.state = BackendState::Ready;
        }
        self.emit_state().await;
        eprintln!("[aurora-v4] event=sidecar_ready");

        let writer_manager = self.clone();
        tokio::spawn(async move {
            while let Some(message) = messages.recv().await {
                if socket_writer.send(message).await.is_err() {
                    break;
                }
            }
            let _ = socket_writer.close().await;
            writer_manager.connection_lost(epoch).await;
        });

        let reader_manager = self.clone();
        tokio::spawn(async move {
            while let Some(item) = socket_reader.next().await {
                match item {
                    Ok(Message::Text(text)) => {
                        if let Err(error) = reader_manager.handle_wire(epoch, text.as_str()).await {
                            if error == "STALE_CONNECTION" {
                                break;
                            }
                            eprintln!("[aurora-v4] event=protocol_warning code={error}");
                            reader_manager.emit(FrontendEvent::ProtocolWarning { code: error });
                        }
                    }
                    Ok(Message::Close(_)) | Err(_) => break,
                    Ok(Message::Binary(_)) => {
                        reader_manager.emit(FrontendEvent::ProtocolWarning {
                            code: "UNEXPECTED_BINARY_FRAME".into(),
                        });
                    }
                    _ => {}
                }
            }
            reader_manager.connection_lost(epoch).await;
        });

        self.send_value(health(&format!("health-{}", Uuid::new_v4().simple())))
            .await
    }

    pub async fn chat_start(&self, input: String) -> Result<ChatStartResult, String> {
        if input.trim().is_empty() {
            return Err("Message cannot be empty.".into());
        }
        let (result, writer) = {
            let mut data = self.inner.lock().await;
            if data.state != BackendState::Ready {
                return Err("Backend is not ready.".into());
            }
            if input.len() > data.negotiated_chat_input_max_bytes {
                return Err("Message exceeds the negotiated limit.".into());
            }
            let result = ChatStartResult {
                request_id: format!("request-{}", Uuid::new_v4().simple()),
                session_id: data.session_id.clone(),
                generation_id: format!("generation-{}", Uuid::new_v4().simple()),
            };
            let owner = RequestOwner {
                request_id: result.request_id.clone(),
                session_id: result.session_id.clone(),
                generation_id: result.generation_id.clone(),
            };
            data.registry.start(owner)?;
            data.request_started.insert(
                (result.session_id.clone(), result.generation_id.clone()),
                Instant::now(),
            );
            data.metrics.command_to_first_delta_ms = None;
            let writer = data
                .writer
                .clone()
                .ok_or_else(|| "Backend transport unavailable.".to_string())?;
            (result, writer)
        };
        let message = chat_request(
            &result.request_id,
            &result.session_id,
            &result.generation_id,
            &input,
        );
        writer
            .send(Message::Text(message.to_string().into()))
            .await
            .map_err(|_| "Backend transport closed.".to_string())?;
        eprintln!(
            "[aurora-v4] event=chat_start request={} generation={}",
            short_id(&result.request_id),
            short_id(&result.generation_id)
        );
        Ok(result)
    }

    pub async fn chat_cancel(&self, target: CancelTarget) -> Result<bool, String> {
        let writer = {
            let mut data = self.inner.lock().await;
            let owner = RequestOwner {
                request_id: target.request_id.clone(),
                session_id: target.session_id.clone(),
                generation_id: target.generation_id.clone(),
            };
            if !data.registry.request_cancel(&owner)? {
                return Ok(false);
            }
            data.cancel_started.insert(
                (target.session_id.clone(), target.generation_id.clone()),
                Instant::now(),
            );
            data.metrics.cancel_to_terminal_ms = None;
            data.writer
                .clone()
                .ok_or_else(|| "Backend transport unavailable.".to_string())?
        };
        let request_id = format!("cancel-{}", Uuid::new_v4().simple());
        writer
            .send(Message::Text(
                chat_cancel(&request_id, &target).to_string().into(),
            ))
            .await
            .map_err(|_| "Backend transport closed.".to_string())?;
        eprintln!(
            "[aurora-v4] event=chat_cancel request={} generation={}",
            short_id(&target.request_id),
            short_id(&target.generation_id)
        );
        Ok(true)
    }

    pub async fn crash(&self) -> Result<(), String> {
        let child = {
            let mut data = self.inner.lock().await;
            if data.state != BackendState::Ready {
                return Err("Backend is not ready.".into());
            }
            data.crash_requested_at = Some(Instant::now());
            data.metrics.crash_to_disconnected_ms = None;
            data.child
                .clone()
                .ok_or_else(|| "Sidecar process unavailable.".to_string())?
        };
        child
            .lock()
            .await
            .start_kill()
            .map_err(|error| error.to_string())
    }

    pub async fn restart(&self) -> Result<(), String> {
        eprintln!("[aurora-v4] event=sidecar_restart_requested");
        self.shutdown().await?;
        self.start(true).await
    }

    pub async fn shutdown(&self) -> Result<(), String> {
        let (writer, child, job, should_emit) = {
            let mut data = self.inner.lock().await;
            if data.state == BackendState::Stopped {
                return Ok(());
            }
            data.state = BackendState::Stopping;
            data.epoch += 1;
            let writer = data.writer.take();
            let child = data.child.take();
            let job = data.job.take();
            data.sidecar_instance_id = None;
            (writer, child, job, true)
        };
        if should_emit {
            self.emit_state().await;
        }
        if let Some(writer) = writer {
            let request_id = format!("shutdown-{}", Uuid::new_v4().simple());
            let _ = writer
                .send(Message::Text(shutdown(&request_id).to_string().into()))
                .await;
            tokio::time::sleep(SHUTDOWN_GRACE).await;
        }
        if let Some(child) = child {
            let mut child = child.lock().await;
            if child
                .try_wait()
                .map_err(|error| error.to_string())?
                .is_none()
            {
                let _ = child.start_kill();
                let _ = timeout(Duration::from_secs(3), child.wait()).await;
            }
        }
        drop(job);
        let mut data = self.inner.lock().await;
        data.state = BackendState::Stopped;
        drop(data);
        self.emit_state().await;
        Ok(())
    }

    async fn send_value(&self, value: Value) -> Result<(), String> {
        let writer = self
            .inner
            .lock()
            .await
            .writer
            .clone()
            .ok_or_else(|| "Backend transport unavailable.".to_string())?;
        writer
            .send(Message::Text(value.to_string().into()))
            .await
            .map_err(|_| "Backend transport closed.".to_string())
    }

    async fn handle_wire(&self, epoch: u64, text: &str) -> Result<(), String> {
        let value: Value = serde_json::from_str(text).map_err(|_| "MALFORMED_JSON".to_string())?;
        let message_type = validate_sidecar_event(&value)?;
        let current_epoch = self.inner.lock().await.epoch;
        if epoch != current_epoch {
            return Err("STALE_CONNECTION".into());
        }
        match message_type {
            "chat.accepted" => {
                let owner = owner_from(&value)?;
                self.inner.lock().await.registry.accept(&owner)?;
                self.emit(FrontendEvent::ChatAccepted {
                    request_id: owner.request_id,
                    generation_id: owner.generation_id,
                });
            }
            "chat.delta" => {
                let owner = owner_from(&value)?;
                let seq = value
                    .get("seq")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| "INVALID_SEQUENCE".to_string())?;
                let delta = object(&value, "payload")?
                    .get("delta")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "INVALID_DELTA".to_string())?
                    .to_owned();
                let mut data = self.inner.lock().await;
                data.registry.delta(&owner, seq)?;
                if data.metrics.command_to_first_delta_ms.is_none()
                    && let Some(started) = data
                        .request_started
                        .get(&(owner.session_id.clone(), owner.generation_id.clone()))
                {
                    data.metrics.command_to_first_delta_ms = Some(elapsed_ms(*started));
                }
                drop(data);
                self.emit(FrontendEvent::ChatDelta {
                    request_id: owner.request_id,
                    generation_id: owner.generation_id,
                    seq,
                    delta,
                });
            }
            "chat.completed" => {
                let owner = owner_from(&value)?;
                let payload = object(&value, "payload")?;
                let terminal_state = payload
                    .get("terminal_state")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "INVALID_TERMINAL_STATE".to_string())?
                    .to_owned();
                let error_code = payload
                    .get("error")
                    .and_then(Value::as_object)
                    .and_then(|error| error.get("code"))
                    .and_then(Value::as_str)
                    .map(str::to_owned);
                let mut data = self.inner.lock().await;
                if !data.registry.terminal(&owner, &terminal_state)? {
                    return Err("DUPLICATE_TERMINAL".into());
                }
                if terminal_state == "cancelled"
                    && let Some(started) = data
                        .cancel_started
                        .remove(&(owner.session_id.clone(), owner.generation_id.clone()))
                {
                    data.metrics.cancel_to_terminal_ms = Some(elapsed_ms(started));
                }
                data.request_started
                    .remove(&(owner.session_id.clone(), owner.generation_id.clone()));
                let cancel_latency = data.metrics.cancel_to_terminal_ms;
                drop(data);
                eprintln!(
                    "[aurora-v4] event=chat_terminal request={} generation={} state={} cancel_latency_ms={}",
                    short_id(&owner.request_id),
                    short_id(&owner.generation_id),
                    terminal_state,
                    cancel_latency
                        .map(|value| format!("{value:.1}"))
                        .unwrap_or_else(|| "none".into())
                );
                self.emit(FrontendEvent::ChatTerminal {
                    request_id: owner.request_id,
                    generation_id: owner.generation_id,
                    terminal_state,
                    error_code,
                });
                self.emit_state().await;
            }
            "chat.cancel.ack" => {
                let generation_id = require_string(&value, "generation_id", None)?.to_owned();
                let outcome = object(&value, "payload")?
                    .get("outcome")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "INVALID_CANCEL_ACK".to_string())?
                    .to_owned();
                self.emit(FrontendEvent::CancelAck {
                    generation_id,
                    outcome,
                });
            }
            "error" | "backend.warning" => {
                let code = object(&value, "payload")?
                    .get("code")
                    .and_then(Value::as_str)
                    .unwrap_or("BACKEND_WARNING")
                    .to_owned();
                self.emit(FrontendEvent::ProtocolWarning { code });
            }
            _ => {}
        }
        Ok(())
    }

    async fn connection_lost(&self, epoch: u64) {
        let terminal_events = {
            let mut data = self.inner.lock().await;
            if epoch != data.epoch
                || matches!(
                    data.state,
                    BackendState::Disconnected | BackendState::Stopping | BackendState::Stopped
                )
            {
                return;
            }
            if let Some(started) = data.crash_requested_at.take() {
                data.metrics.crash_to_disconnected_ms = Some(elapsed_ms(started));
            }
            data.state = BackendState::Disconnected;
            data.writer = None;
            data.sidecar_instance_id = None;
            data.registry.backend_lost()
        };
        for owner in terminal_events {
            self.emit(FrontendEvent::ChatTerminal {
                request_id: owner.request_id,
                generation_id: owner.generation_id,
                terminal_state: "backend_lost".into(),
                error_code: Some("BACKEND_LOST".into()),
            });
        }
        self.emit_state().await;
        eprintln!("[aurora-v4] event=sidecar_disconnected");
    }

    async fn emit_state(&self) {
        let snapshot = self.snapshot().await;
        self.emit(FrontendEvent::BackendState {
            state: snapshot.state,
            metrics: snapshot.metrics,
        });
    }

    fn emit(&self, event: FrontendEvent) {
        let channel = self
            .frontend
            .lock()
            .expect("frontend channel lock poisoned")
            .clone();
        if let Some(channel) = channel {
            let _ = channel.send(event);
        }
    }
}

fn owner_from(value: &Value) -> Result<RequestOwner, String> {
    Ok(RequestOwner {
        request_id: require_string(value, "request_id", None)?.to_owned(),
        session_id: require_string(value, "session_id", None)?.to_owned(),
        generation_id: require_string(value, "generation_id", None)?.to_owned(),
    })
}

async fn drain_stderr(stderr: tokio::process::ChildStderr) {
    let mut lines = BufReader::new(stderr).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        eprintln!("[aurora-v4-sidecar] {line}");
    }
}

fn find_sidecar_launch() -> Result<SidecarLaunch, String> {
    let sidecar_root = if let Some(path) = std::env::var_os("AURORA_V4_SIDECAR_DIR") {
        PathBuf::from(path)
    } else {
        let current = std::env::current_dir().map_err(|error| error.to_string())?;
        let executable = std::env::current_exe().map_err(|error| error.to_string())?;
        [
            current.as_path(),
            executable.parent().unwrap_or(executable.as_path()),
        ]
        .into_iter()
        .flat_map(|root| root.ancestors())
        .flat_map(|ancestor| {
            [
                ancestor.join("sidecar"),
                ancestor.join("prototype").join("aurora-v4").join("sidecar"),
            ]
        })
        .find(|candidate| candidate.join("mock_sidecar").join("server.py").is_file())
        .ok_or_else(|| "Aurora v4 mock sidecar directory was not found".to_string())?
    };
    let script = sidecar_root.join("mock_sidecar").join("server.py");
    let venv = sidecar_root.join(".venv");
    let pyvenv = std::fs::read_to_string(venv.join("pyvenv.cfg"))
        .map_err(|_| "Prototype sidecar virtual environment is missing".to_string())?;
    let home = pyvenv
        .lines()
        .find_map(|line| line.strip_prefix("home = "))
        .map(PathBuf::from)
        .ok_or_else(|| "pyvenv.cfg has no Python home".to_string())?;
    let python = home.join("python.exe");
    let python_path = venv.join("Lib").join("site-packages");
    for required in [&script, &python, &python_path] {
        if !required.exists() {
            return Err(format!(
                "Required sidecar path is missing: {}",
                required.display()
            ));
        }
    }
    Ok(SidecarLaunch {
        python,
        script,
        working_directory: sidecar_root,
        python_path,
    })
}

fn elapsed_ms(started: Instant) -> f64 {
    started.elapsed().as_secs_f64() * 1000.0
}

fn short_id(value: &str) -> &str {
    value
        .rsplit('-')
        .next()
        .unwrap_or(value)
        .get(..8)
        .unwrap_or(value)
}

#[cfg(windows)]
#[derive(Debug)]
struct JobGuard(windows_sys::Win32::Foundation::HANDLE);

#[cfg(windows)]
unsafe impl Send for JobGuard {}
#[cfg(windows)]
unsafe impl Sync for JobGuard {}

#[cfg(windows)]
impl JobGuard {
    fn assign(pid: u32) -> Result<Self, String> {
        use std::{mem::size_of, ptr::null};
        use windows_sys::Win32::{
            Foundation::{CloseHandle, HANDLE},
            System::{
                JobObjects::{
                    AssignProcessToJobObject, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
                    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
                    SetInformationJobObject,
                },
                Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE},
            },
        };

        unsafe {
            let job: HANDLE =
                windows_sys::Win32::System::JobObjects::CreateJobObjectW(null(), null());
            if job.is_null() {
                return Err("CreateJobObjectW failed".into());
            }
            let mut information: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                &information as *const _ as *const _,
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            ) == 0
            {
                CloseHandle(job);
                return Err("SetInformationJobObject failed".into());
            }
            let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
            if process.is_null() {
                CloseHandle(job);
                return Err("OpenProcess for sidecar failed".into());
            }
            let assigned = AssignProcessToJobObject(job, process);
            CloseHandle(process);
            if assigned == 0 {
                CloseHandle(job);
                return Err("AssignProcessToJobObject failed".into());
            }
            Ok(Self(job))
        }
    }
}

#[cfg(windows)]
impl Drop for JobGuard {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.0);
        }
    }
}

#[cfg(not(windows))]
#[derive(Debug)]
struct JobGuard;

#[cfg(not(windows))]
impl JobGuard {
    fn assign(_pid: u32) -> Result<Self, String> {
        Ok(Self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn wait_for(
        manager: &BackendManager,
        predicate: impl Fn(&BackendSnapshot) -> bool,
    ) -> BackendSnapshot {
        timeout(Duration::from_secs(5), async {
            loop {
                let snapshot = manager.snapshot().await;
                if predicate(&snapshot) {
                    return snapshot;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("backend state transition timed out")
    }

    #[test]
    fn sidecar_discovery_uses_relative_prototype_paths() {
        let launch = find_sidecar_launch().unwrap();
        assert!(
            launch
                .script
                .ends_with(std::path::Path::new("mock_sidecar/server.py"))
        );
        assert!(
            launch
                .python_path
                .ends_with(std::path::Path::new("Lib/site-packages"))
        );
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn real_gateway_stream_cancel_crash_restart_and_shutdown() {
        let manager = BackendManager::new();
        manager.start(false).await.unwrap();
        let initial = manager.snapshot().await;
        assert_eq!(initial.state, BackendState::Ready);

        let first = manager
            .chat_start("mock integration request".into())
            .await
            .unwrap();
        let first_delta = wait_for(&manager, |snapshot| {
            snapshot.metrics.command_to_first_delta_ms.is_some()
        })
        .await;
        assert!(
            manager
                .chat_cancel(CancelTarget {
                    request_id: first.request_id,
                    session_id: first.session_id,
                    generation_id: first.generation_id,
                })
                .await
                .unwrap()
        );
        let cancelled = wait_for(&manager, |snapshot| {
            snapshot.metrics.cancel_to_terminal_ms.is_some()
        })
        .await;

        manager
            .chat_start("mock crash isolation request".into())
            .await
            .unwrap();
        manager.crash().await.unwrap();
        let disconnected = wait_for(&manager, |snapshot| {
            snapshot.state == BackendState::Disconnected
        })
        .await;
        assert!(disconnected.metrics.crash_to_disconnected_ms.is_some());

        manager.restart().await.unwrap();
        let restarted = manager.snapshot().await;
        assert_eq!(restarted.state, BackendState::Ready);
        assert!(restarted.metrics.restart_to_ready_ms.is_some());

        eprintln!(
            "[aurora-v4-test] spawn_to_bootstrap_ms={:.1} bootstrap_to_ready_ms={:.1} command_to_first_delta_ms={:.1} cancel_to_terminal_ms={:.1} crash_to_disconnected_ms={:.1} restart_to_ready_ms={:.1}",
            initial.metrics.spawn_to_bootstrap_ms.unwrap(),
            initial.metrics.bootstrap_to_ready_ms.unwrap(),
            first_delta.metrics.command_to_first_delta_ms.unwrap(),
            cancelled.metrics.cancel_to_terminal_ms.unwrap(),
            disconnected.metrics.crash_to_disconnected_ms.unwrap(),
            restarted.metrics.restart_to_ready_ms.unwrap(),
        );

        manager.shutdown().await.unwrap();
        assert_eq!(manager.snapshot().await.state, BackendState::Stopped);
    }
}
