# PS1 Engine Future Enhancements

This list tracks planned features for scaling to 50+ concurrent users and improving user experience.

## 💾 [CRITICAL] Persistence & Progression
- [ ] **Persistent Save States**: Mount a per-user directory (e.g., `./userdata/saves/{client_id}/states`) into the container so users don't lose progress when a session ends.
- [ ] **Memory Card Sync**: Implement persistent memory card files (`.mcd`) that follow the user across different games.
- [ ] **Save Management UI**: Create a basic interface to download/upload save files so users can take their progress to local emulators.

## 🛑 Improved UX: Session Cancellation & Recovery
- [x] **Cancel Button**: Add a "Cancel" button to the loading overlay.
- [x] **Race-Proof Cleanup**: Ensure "Ghost Sessions" are killed if a user cancels during a slow extraction.
- [x] **Auto-Resume**: Detect and instantly "re-pop" a user back into their active game session if they refresh the page.

## 🏗️ Enterprise Scaling (Concurrency Control)
- [ ] **Python Task Queue**: Replace the direct "Click-to-Spawn" logic with an `asyncio.Queue` based worker system.
- [ ] **Concurrency Governance**: Add `MAX_CONCURRENT_LAUNCHES` to prevent IO/CPU spikes during mass login events.
- [x] **Milestone UI**: Professional progress feedback (Extracting → Booting → Ready).
- [x] **Decoupled Stats**: Move heavy `container.stats()` calls to a 15s cycle, keep light "Alive" check at 4s.
- [ ] **Adaptive Jitter**: Add random delays to updates to prevent "Thundering Herd" API spikes.
- [x] **Passive Heartbeat**: Switch to shared file timestamps for status to reach Zero Docker API overhead.

## 🔒 Hardening & Security
- [x] **API Rate Limiting**: Limit how many sessions a single client can request per minute (`RATE_LIMIT_SESSIONS_PER_MIN`).
- [x] **Host Resource Monitoring**: Safety valve that prevents new sessions if Host CPU/RAM > thresholds (`MAX_HOST_CPU_PERCENT`, `MAX_HOST_MEM_PERCENT`).
- [x] **Project-Local Data**: Moved all cache and temp files out of system `/tmp` to `./userdata`.
- [x] **Internal Health Checks**: Add a Docker "Healthcheck" to the orchestrator to monitor background tasks.
- [x] **Container Hardening**: 11 env vars lock down desktop, sudo, terminals, keybinds in each session.

## 🎨 UI/UX Polish
- [x] **Native Gamepad Support**: Verified working via Selkies WebRTC Input Bridge.
- [ ] **Search & Filter**: Add a search bar to the library for faster game navigation.

## ⚡ Hardware Support
- [ ] **GPU Passthrough**: Support Nvidia/AMD GPU passthrough for hardware-accelerated hosts.

## 🔧 Config Gaps (found during audit)
- [x] **`STREAM_QUALITY`**: Wired to `SELKIES_H264_CRF` (quality 1-100 → CRF 50-5).
- [x] **`SHOW_FPS`**: Injected into container env, consumed by `custom_autostart.sh` `[Display] ShowFPS`.
- [ ] **Watchdog Hardcoding**: `watchdog.py` hardcodes `emulator-net` and `custom-duckstation` instead of reading `NETWORK_NAME`/`IMAGE_NAME` from config.
- [ ] **`SELKIES_FRAMERATE` (optional)**: `main.py` uses the upstream `SELKIES_VIDEO_FRAMERATE` which works directly on the gstreamer process. Optionally also inject LSIO's `SELKIES_FRAMERATE` to lock the web UI slider (e.g., `"30"` or `"30|locked"`).
- [ ] **`SELKIES_H264_CRF` (optional)**: `main.py` uses the upstream `SELKIES_VIDEO_BITRATE` for initial bitrate. Optionally also wire `STREAM_QUALITY` → `SELKIES_H264_CRF` to control the LSIO web UI quality slider.

