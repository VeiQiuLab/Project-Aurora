//! Single-thread-affine native host. No AI, audio, network or user settings owner.
use serde::Deserialize;
use std::{
    io::{self, Write},
    path::PathBuf,
};

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct Command {
    revision: u64,
    state: String,
    visible: bool,
    x: Option<i32>,
    y: Option<i32>,
    shutdown: bool,
}
impl Command {
    fn valid(&self) -> bool {
        self.revision <= 9_007_199_254_740_991
            && matches!(
                self.state.as_str(),
                "idle" | "thinking" | "speaking" | "error"
            )
            && self.x.is_some() == self.y.is_some()
            && self
                .x
                .into_iter()
                .chain(self.y)
                .all(|p| (-32768..=32767).contains(&p))
    }
    fn state_number(&self) -> i32 {
        match self.state.as_str() {
            "thinking" => 1,
            "speaking" => 2,
            "error" => 3,
            _ => 0,
        }
    }
}
fn ingest(buffer: &mut Vec<u8>, chunk: &[u8], current: &mut Command) -> Result<(), &'static str> {
    // The supervisor coalesces state. Bound the pipe parser independently.
    if buffer.len() + chunk.len() > 4096 {
        return Err("COMMAND_LIMIT");
    }
    buffer.extend_from_slice(chunk);
    while let Some(end) = buffer.iter().position(|b| *b == b'\n') {
        let line: Vec<_> = buffer.drain(..=end).collect();
        let next: Command = serde_json::from_slice(&line).map_err(|_| "INVALID_COMMAND")?;
        if !next.valid() {
            return Err("INVALID_COMMAND");
        }
        if next.revision > current.revision {
            *current = next;
        }
    }
    Ok(())
}
fn emit(value: serde_json::Value) -> Result<(), &'static str> {
    let mut out = io::stdout().lock();
    writeln!(out, "{value}")
        .and_then(|_| out.flush())
        .map_err(|_| "TRANSPORT_LOST")
}

#[cfg(windows)]
mod native {
    use super::*;
    use std::{
        ffi::c_void,
        os::windows::ffi::OsStrExt,
        thread,
        time::{Duration, Instant},
    };
    use windows_sys::Win32::{
        Foundation::{FreeLibrary, HMODULE},
        Storage::FileSystem::ReadFile,
        System::{
            Console::{GetStdHandle, STD_INPUT_HANDLE},
            LibraryLoader::{
                GetProcAddress, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR,
                LoadLibraryExW,
            },
            Pipes::PeekNamedPipe,
        },
    };
    type Create = unsafe extern "C" fn(*const u16, *const u16) -> *mut c_void;
    type Frame = unsafe extern "C" fn(*mut c_void, f32, i32, i32, i32, i32) -> i32;
    type Destroy = unsafe extern "C" fn(*mut c_void);
    struct Adapter {
        library: HMODULE,
        handle: *mut c_void,
        frame: Frame,
        destroy: Destroy,
    }
    impl Drop for Adapter {
        fn drop(&mut self) {
            unsafe {
                (self.destroy)(self.handle);
                FreeLibrary(self.library);
            }
        }
    }
    fn wide(path: &std::path::Path) -> Vec<u16> {
        path.as_os_str().encode_wide().chain(Some(0)).collect()
    }
    impl Adapter {
        fn open(model: &std::path::Path, shaders: &std::path::Path) -> Result<Self, &'static str> {
            let dll = std::env::current_exe()
                .map_err(|_| "ADAPTER_UNAVAILABLE")?
                .with_file_name("aurora_live2d.dll");
            unsafe {
                let library = LoadLibraryExW(
                    wide(&dll).as_ptr(),
                    std::ptr::null_mut(),
                    LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS,
                );
                if library.is_null() {
                    return Err("ADAPTER_UNAVAILABLE");
                }
                let create = GetProcAddress(library, c"aurora_create".as_ptr().cast());
                let frame = GetProcAddress(library, c"aurora_frame".as_ptr().cast());
                let destroy = GetProcAddress(library, c"aurora_destroy".as_ptr().cast());
                let (Some(create), Some(frame), Some(destroy)) = (create, frame, destroy) else {
                    FreeLibrary(library);
                    return Err("ADAPTER_ABI");
                };
                let create: Create = std::mem::transmute(create);
                let handle = create(wide(model).as_ptr(), wide(shaders).as_ptr());
                if handle.is_null() {
                    FreeLibrary(library);
                    return Err("RENDERER_INIT_FAILED");
                }
                if let Some(path) = std::env::var_os("AURORA_LIVE2D_CAPTURE_PATH") {
                    if let Some(capture) =
                        GetProcAddress(library, c"aurora_capture_next".as_ptr().cast())
                    {
                        let capture: unsafe extern "C" fn(*mut c_void, *const u16) =
                            std::mem::transmute(capture);
                        capture(handle, wide(&PathBuf::from(path)).as_ptr());
                    }
                }
                Ok(Self {
                    library,
                    handle,
                    frame: std::mem::transmute(frame),
                    destroy: std::mem::transmute(destroy),
                })
            }
        }
    }
    pub fn run() -> Result<(), &'static str> {
        let model =
            PathBuf::from(std::env::var_os("AURORA_LIVE2D_MODEL").ok_or("MODEL_UNCONFIGURED")?);
        let shaders =
            PathBuf::from(std::env::var_os("AURORA_LIVE2D_SHADERS").ok_or("SHADERS_UNCONFIGURED")?);
        let adapter = Adapter::open(&model, &shaders)?;
        emit(serde_json::json!({"type":"ready","protocol":1}))?;
        let input = unsafe { GetStdHandle(STD_INPUT_HANDLE) };
        let mut buffer = Vec::new();
        let mut current = Command {
            revision: 0,
            state: "idle".into(),
            visible: false,
            x: None,
            y: None,
            shutdown: false,
        };
        let mut last = Instant::now();
        let mut metrics = last;
        let mut frames = 0u64;
        let mut applied_revision = 0u64;
        loop {
            let start = Instant::now();
            let mut available = 0u32;
            // Anonymous pipe only. Parent exit/EOF is a shutdown condition, not a
            // detached blocking reader thread. Never read from a console here.
            if unsafe {
                PeekNamedPipe(
                    input,
                    std::ptr::null_mut(),
                    0,
                    std::ptr::null_mut(),
                    &mut available,
                    std::ptr::null_mut(),
                )
            } == 0
            {
                break;
            }
            if available > 0 {
                let mut bytes = [0u8; 1024];
                let mut n = 0;
                if unsafe {
                    ReadFile(
                        input,
                        bytes.as_mut_ptr(),
                        available.min(1024),
                        &mut n,
                        std::ptr::null_mut(),
                    )
                } == 0
                    || n == 0
                {
                    break;
                }
                ingest(&mut buffer, &bytes[..n as usize], &mut current)?;
                if current.shutdown {
                    break;
                }
            }
            let dt = start.duration_since(last).as_secs_f32();
            last = start;
            let outcome = unsafe {
                (adapter.frame)(
                    adapter.handle,
                    dt,
                    current.state_number(),
                    current.visible as i32,
                    current.x.unwrap_or(i32::MIN),
                    current.y.unwrap_or(i32::MIN),
                )
            };
            if outcome < 0 {
                return Err("RENDER_FAILED");
            }
            if outcome > 0 {
                break;
            }
            if current.revision != applied_revision {
                emit(
                    serde_json::json!({"type":"applied","revision":current.revision,"state":current.state,"visible":current.visible}),
                )?;
                applied_revision = current.revision;
            }
            if current.visible {
                frames += 1
            }
            if metrics.elapsed() >= Duration::from_secs(1) {
                emit(
                    serde_json::json!({"type":"metrics","frames":frames,"seconds":metrics.elapsed().as_secs_f64(),"revision":current.revision,"state":current.state,"visible":current.visible}),
                )?;
                metrics = Instant::now();
                frames = 0;
            }
            let budget = Duration::from_millis(if current.visible { 17 } else { 100 });
            thread::sleep(budget.saturating_sub(start.elapsed()));
        }
        drop(adapter);
        emit(serde_json::json!({"type":"closed"}))?;
        Ok(())
    }
}
fn main() {
    #[cfg(windows)]
    let result = native::run();
    #[cfg(not(windows))]
    let result: Result<(), &str> = Err("WINDOWS_REQUIRED");
    if let Err(code) = result {
        let _ = emit(serde_json::json!({"type":"error","code":code}));
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn state() -> Command {
        Command {
            revision: 0,
            state: "idle".into(),
            visible: false,
            x: None,
            y: None,
            shutdown: false,
        }
    }
    #[test]
    fn split_and_stale() {
        let mut s = state();
        let mut b = vec![];
        let line=b"{\"revision\":2,\"state\":\"speaking\",\"visible\":true,\"x\":null,\"y\":null,\"shutdown\":false}\n";
        ingest(&mut b, &line[..20], &mut s).unwrap();
        assert_eq!(s.revision, 0);
        ingest(&mut b, &line[20..], &mut s).unwrap();
        assert_eq!(s.state, "speaking");
        let old = s.clone();
        ingest(&mut b, line, &mut s).unwrap();
        assert_eq!(s, old);
    }
    #[test]
    fn malformed_and_bound() {
        let mut s = state();
        assert!(ingest(&mut vec![], b"{}\n", &mut s).is_err());
        assert!(ingest(&mut vec![], &[b'x'; 4097], &mut s).is_err());
    }
    #[test]
    fn control_validation() {
        let mut s = state();
        s.x = Some(1);
        assert!(!s.valid());
        s.y = Some(2);
        assert!(s.valid());
        s.state = "phonemes".into();
        assert!(!s.valid());
    }
}
