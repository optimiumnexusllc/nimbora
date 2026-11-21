//! NIMBORA Softphone native shell (Windows, macOS, Linux, Android, iOS).
//!
//! The whole phone (SIP over WebSocket, WebRTC audio, UI) lives in the web
//! app; this shell adds what a browser tab cannot: an installed app with its
//! own icon and window, a single instance, and `nimbora-softphone://` pairing
//! links opened straight from the console's QR code.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[allow(unused_mut)]
    let mut builder = tauri::Builder::default();

    // A second launch (for instance from a pairing link) focuses the running
    // phone instead of opening another one; the deep-link plugin forwards
    // the link to it.
    #[cfg(desktop)]
    {
        use tauri::Manager;
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }));
    }

    builder
        .plugin(tauri_plugin_deep_link::init())
        .setup(|_app| {
            // Windows and Linux register the URL scheme at runtime (macOS,
            // iOS and Android declare it in the bundle).
            #[cfg(any(windows, target_os = "linux"))]
            {
                use tauri_plugin_deep_link::DeepLinkExt;
                _app.deep_link().register_all()?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running NIMBORA Softphone");
}
