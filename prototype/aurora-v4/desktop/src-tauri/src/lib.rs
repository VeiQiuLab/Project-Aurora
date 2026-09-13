use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum WindowAction {
    Minimize,
    ToggleMaximize,
    Close,
}

#[tauri::command]
async fn window_action(
    window: tauri::WebviewWindow,
    action: WindowAction,
) -> Result<bool, String> {
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![window_action])
        .run(tauri::generate_context!())
        .expect("Aurora v4 desktop prototype failed");
}
