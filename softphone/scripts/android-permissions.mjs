// After `tauri android init`: let the WebView use the microphone and show
// incoming-call notifications. Idempotent.
import { readFileSync, writeFileSync } from "node:fs";

const path = "src-tauri/gen/android/app/src/main/AndroidManifest.xml";
const permissions = [
    "android.permission.RECORD_AUDIO",
    "android.permission.MODIFY_AUDIO_SETTINGS",
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.WAKE_LOCK",
];
let manifest = readFileSync(path, "utf8");
const missing = permissions.filter((p) => !manifest.includes(`"${p}"`));
if (missing.length) {
    const lines = missing.map((p) => `    <uses-permission android:name="${p}" />`).join("\n");
    manifest = manifest.replace(/<application/, `${lines}\n    <application`);
    writeFileSync(path, manifest);
}
console.log(missing.length ? `Added: ${missing.join(", ")}` : "Permissions already present");
