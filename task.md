# DuckStation Cloud Gaming Backend

## Planning
- [x] Create Implementation Plan <!-- id: 0 -->
- [x] Review and Approve Architecture <!-- id: 1 -->
- [x] Update Plan for Frontend <!-- id: 9 -->

## Implementation
- [x] Create `requirements.txt` <!-- id: 2 -->
- [x] Create `Dockerfile.duckstation` <!-- id: 3 -->
- [x] Create `docker-compose.yml` <!-- id: 4 -->
- [x] Create `main.py` (Orchestrator Logic) <!-- id: 5 -->
- [x] Update `main.py` (Add ROMs endpoint & Static Files) <!-- id: 10 -->
- [x] Create `watchdog.py` (Monitoring Logic) <!-- id: 6 -->
- [x] Create `.env` template <!-- id: 7 -->
- [x] Create `static/index.html` <!-- id: 11 -->
- [x] Create `static/style.css` <!-- id: 12 -->
- [x] Create `static/script.js` <!-- id: 13 -->
- [x] Create `start.sh` (Convenience Script) <!-- id: 14 -->
- [x] Create `install_docker.sh` (Environment Setup) <!-- id: 15 -->
- [x] Fix Python Environment (venv) <!-- id: 16 -->
- [x] Fix Frontend Redirect Logic <!-- id: 17 -->
- [x] Fix Traefik Path Strip Middleware <!-- id: 18 -->
- [x] Update `start.sh` for Background Execution <!-- id: 19 -->
- [x] Create `stop.sh` <!-- id: 20 -->
- [x] Create `logs.sh` <!-- id: 21 -->
- [x] Fix Log Buffering <!-- id: 22 -->
- [x] Debug Traefik 404 Error (HTTPS Scheme Fix) <!-- id: 23 -->
- [x] Fix Traefik Bad Gateway (Revert to HTTP) <!-- id: 24 -->
- [x] Fix Bad Gateway (Add Startup Delay) <!-- id: 25 -->
- [x] Debug Black Screen (DuckStation Startup) <!-- id: 26 -->
- [x] Fix DuckStation Path <!-- id: 27 -->
- [x] Configure BIOS Path <!-- id: 28 -->
- [x] Configure ROM Path <!-- id: 29 -->
- [x] Fix Docker Permissions <!-- id: 30 -->
- [x] Configure DuckStation Settings (Bypass Wizard) <!-- id: 31 -->
- [x] Configure GameList Path <!-- id: 32 -->
- [x] Fix Config Path (Local/Share) <!-- id: 33 -->
- [x] Fix Autostart Script (Shebang) <!-- id: 35 -->
- [x] Fix Config Persistence (Read-Only) <!-- id: 36 -->
- [x] Fix Zombie Container Cleanup <!-- id: 37 -->
- [x] Debug Game Launch Failure (Recursive ZIP extraction) <!-- id: 34 -->


## Final Polish
- [x] Restore Audio Backend <!-- id: 38 -->
- [x] Enable Hardware Rendering (Vulkan) <!-- id: 39 -->
- [x] Document Debugging Journey <!-- id: 40 -->
- [x] Externalize Configuration (duckstation.env) <!-- id: 41 -->
- [x] Document Controls and Capacity <!-- id: 42 -->
- [x] Implement Game Isolation (Mount Single ZIP) <!-- id: 43 -->
- [x] Implement Debug Mode (Full Library Access) <!-- id: 44 -->
- [x] Update start.sh for Always Rebuild <!-- id: 45 -->
- [x] Fix Resolution Regression (Completed: Identified Hardware Constraint) <!-- id: 46 -->

- [x] Fix Connectivity Issue (Traefik Restart) <!-- id: 47 -->
- [x] Performance Analysis (OpenGL 2x vs 4x) <!-- id: 48 -->
- [x] Optimize Stream Bandwidth (KasmVNC Tweaks) <!-- id: 49 -->
- [x] Debug DuckStation Hang (Fixed with 1280x1024 Display + VSync Off) <!-- id: 50 -->
- [x] Bandwidth vs Quality Optimization (Restoring <1mbps) <!-- id: 51 -->
- [x] Documentation Fix (Mermaid Syntax Repair) <!-- id: 52 -->
- [x] Debug Bitrate Caps and Locate VNC Configs (Fixed SELKIES_VIDEO_BITRATE) <!-- id: 53 -->
- [x] Unify Configuration into Single config.env <!-- id: 54 -->
- [x] Fix All Race Conditions (7 issues) <!-- id: 55 -->
- [x] Optimize Graphics Config for Software Renderer <!-- id: 56 -->
- [x] Implement Shared ROM Cache (Eliminate Redundant Unzipping) <!-- id: 57 -->
- [x] Implement Graphics Profiles (Automatic tune based on RESOLUTION_SCALE) <!-- id: 58 -->
- [x] Implement Enhanced Cache Verification (Size + Count Match) <!-- id: 59 -->
- [x] Make ROM Cache Persistent (Remove clear-on-restart) <!-- id: 60 -->
- [x] Refine Container Lifecycle & Multi-User Handling <!-- id: 61 -->
    - [x] Make Container exit when DuckStation stops <!-- id: 62 -->
    - [x] Implement Client Identification (Frontend client_id) <!-- id: 63 -->
    - [x] Limit one container per user (Label-based matching) <!-- id: 64 -->
    - [x] Add session resumption/switching logic <!-- id: 65 -->
    - [x] Fix black screen on resumption (Emulator liveness check) <!-- id: 66 -->
    - [x] Fix Input regression (Remove destructive tmpfs) <!-- id: 67 -->
    - [x] Fix Traefik Sync Race Condition (Verify route before redirect) <!-- id: 68 -->

## Verification
- [x] Verify Code Structure <!-- id: 8 -->

## Config Variables Introduced Per Milestone
| Milestone | Variables |
|---|---|
| Initial Scaffold | `NETWORK_NAME`, `IMAGE_NAME` |
| API & Static Files | `RESOLUTION_SCALE`, `STREAM_BITRATE`, `STREAM_FRAMERATE` |
| Watchdog | `IDLE_TIMEOUT_MINS` |
| Debug Mode | `ENABLE_DEBUG_MODE` |
| Performance Tuning | `CPUS_PER_SESSION`, `MEM_LIMIT_PER_SESSION`, `MAX_HOST_CPU_PERCENT`, `MAX_HOST_MEM_PERCENT`, `RATE_LIMIT_SESSIONS_PER_MIN` |
| Cache System | `ROM_CACHE_MAX_MB` |
| Audio Fix | `AUDIO_BACKEND` |
| Unified Config | All variables consolidated into `config.env` |
