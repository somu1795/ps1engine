# PS1 Engine Future Enhancements

This list tracks planned features for scaling to 50+ concurrent users and improving user experience.

## 💾 [CRITICAL] Persistence & Progression
- [ ] **Persistent Save States**: Mount a per-user directory (e.g., `./userdata/saves/{client_id}/states`) into the container so users don't lose progress when a session ends.
- [ ] **Memory Card Sync**: Implement persistent memory card files (`.mcd`) that follow the user across different games.
- [ ] **Save Management UI**: Create a basic interface to download/upload save files so users can take their progress to local emulators.

## 🛑 Improved UX: Session Cancellation & Recovery
- [x] **Cancel Button**: Add a "Cancel" button to the loading overlay.
- [x] **Race-Proof Cleanup**: Ensure "Ghost Sessions" are killed if a user cancels during a slow extraction.
- [x] **Auto-Resume**: Detect and instantly "re-pop" a user back into their active game session if they refersh the page.

## 🏗️ Enterprise Scaling (Concurrency Control)
- [ ] **Python Task Queue**: Replace the direct "Click-to-Spawn" logic with an `asyncio.Queue` based worker system.
- [ ] **Concurrency Governance**: Add `MAX_CONCURRENT_LAUNCHES` to prevent IO/CPU spikes during mass login events.
- [x] **Milestone UI**: Professional progress feedback (Extracting -> Booting -> Ready).
- [x] **Decoupled Stats**: Move heavy `container.stats()` calls to a 15s cycle, keep light "Alive" check at 4s.
- [ ] **Adaptive Jitter**: Add random delays to updates to prevent "Thundering Herd" API spikes.
- [x] **Passive Heartbeat**: Switch to shared file timestamps for status to reach Zero Docker API overhead.


## 🔒 Hardening & Security
- [x] **API Rate Limiting**: Limit how many sessions a single client can request per minute.
- [x] **Host Resource Monitoring**: Safety valve that prevents new sessions if Host CPU/RAM > 90%.
- [x] **Project-Local Data**: Moved all cache and temp files out of system `/tmp` to `./userdata`.
- [x] **Internal Health Checks**: Add a Docker "Healthcheck" to the orchestrator to monitor background tasks.

## 🎨 UI/UX Polish
- [x] **Native Gamepad Support**: Verified working via Selkies WebRTC Input Bridge.
- [ ] **Search & Filter**: Add a search bar to the library for faster game navigation.

## ⚡ Hardware Support
- [ ] **GPU Passthrough**: Support Nvidia/AMD GPU passthrough for hardware-accelerated hosts.
