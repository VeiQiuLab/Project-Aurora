mod protocol;
mod registry;
mod sidecar;

use protocol::{BackendSnapshot, CancelTarget, ChatStartResult, FrontendEvent};
use serde::{Deserialize, Serialize};
use sidecar::BackendManager;
use tauri::ipc::Channel;
use tauri::window::{Effect, EffectsBuilder};

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum WindowAction {
    Minimize,
    ToggleMaximize,
    Close,
}

#[tauri::command]
async fn window_action(window: tauri::WebviewWindow, action: WindowAction) -> Result<bool, String> {
    match action {
        WindowAction::Minimize => window.minimize(),
        WindowAction::ToggleMaximize => {
            if window.is_maximized().map_err(|error| error.to_string())? {
                window.unmaximize()
            } else {
                window.maximize()
            }
        }
        WindowAction::Close => window.close(),
    }
    .map_err(|error| error.to_string())?;

    window.is_maximized().map_err(|error| error.to_string())
}

#[tauri::command]
fn set_reduced_effects(window: tauri::WebviewWindow, enabled: bool) -> Result<(), String> {
    if enabled {
        window.set_effects(None)
    } else {
        window.set_effects(EffectsBuilder::new().effect(Effect::MicaDark).build())
    }
    .map_err(|error| error.to_string())
}

#[tauri::command]
async fn backend_subscribe(
    manager: tauri::State<'_, BackendManager>,
    channel: Channel<FrontendEvent>,
) -> Result<BackendSnapshot, String> {
    Ok(manager.register_channel(channel).await)
}

#[tauri::command]
async fn backend_snapshot(
    manager: tauri::State<'_, BackendManager>,
) -> Result<BackendSnapshot, String> {
    Ok(manager.snapshot().await)
}

#[tauri::command]
async fn chat_start(
    manager: tauri::State<'_, BackendManager>,
    input: String,
) -> Result<ChatStartResult, String> {
    manager.chat_start(input).await
}

#[tauri::command]
async fn chat_cancel(
    manager: tauri::State<'_, BackendManager>,
    target: CancelTarget,
) -> Result<bool, String> {
    manager.chat_cancel(target).await
}

#[tauri::command]
async fn crash_backend(manager: tauri::State<'_, BackendManager>) -> Result<(), String> {
    manager.crash().await
}

#[tauri::command]
async fn restart_backend(manager: tauri::State<'_, BackendManager>) -> Result<(), String> {
    manager.restart().await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let manager = BackendManager::new();
    let startup_manager = manager.clone();
    let cleanup_manager = manager.clone();
    let app = tauri::Builder::default()
        .manage(manager)
        .setup(move |_| {
            tauri::async_runtime::spawn(async move {
                let _ = startup_manager.start(false).await;
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            window_action,
            set_reduced_effects,
            backend_subscribe,
            backend_snapshot,
            chat_start,
            chat_cancel,
            crash_backend,
            restart_backend,
        ])
        .build(tauri::generate_context!())
        .expect("Aurora v4 desktop prototype failed to build");

    app.run(move |_app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let _ = tauri::async_runtime::block_on(cleanup_manager.shutdown());
        }
    });
}
