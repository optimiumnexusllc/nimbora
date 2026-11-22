import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Tauri serves the build from its own origin; relative paths keep the same
// build working as a desktop app, a mobile app and a PWA under any path.
export default defineConfig({
    base: "./",
    plugins: [react()],
    clearScreen: false,
    server: { port: 5175, strictPort: true },
    envPrefix: ["VITE_", "TAURI_ENV_"],
    build: {
        target: "es2022",
        sourcemap: false,
        chunkSizeWarningLimit: 900,
    },
    test: {
        environment: "jsdom",
        globals: false,
        setupFiles: ["./src/test-setup.ts"],
        testTimeout: 15000,
    },
});
