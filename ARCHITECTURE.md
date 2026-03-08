# 🎮 PS1 Engine Technical Documentation

This document provides a comprehensive overview of the PS1 Engine architecture, backend API, and core workflows.

> [!NOTE]
> **Quick Facts**: The Orchestrator (`main.py`) is the only backend binary. **Traefik is the sole public-facing port** — nothing else is exposed. Config is split across two files: `.env` (Docker Compose, host-level) and `config.env` (runtime tuning, read by the app). After any config change, restart with `./start.sh`.

---

## 🏗️ System Architecture

The engine is built on a **fully containerized microservices architecture** managed by Docker Compose.

### Core Services (`docker-compose.yml`)
| Service | Container | Image | Role |
|---|---|---|---|
| **Traefik Proxy** | `traefik` | `traefik:v3.0` | Edge gateway — HTTP (80), HTTPS (443), SSL termination, dynamic routing |
| **Orchestrator** | `ps1-orchestrator` | Built from `Dockerfile.orchestrator` | FastAPI API server — session management, ROM cache, cover art |
| **Watchdog** | `ps1-watchdog` | Built from `Dockerfile.orchestrator` | Background reaper — kills idle sessions after `IDLE_TIMEOUT_MINS` |
| **DuckStation Sessions** | `duckstation-{id}` | `custom-duckstation` (built from `Dockerfile.duckstation`) | Per-user emulator containers, resource-capped |

---

## ⚙️ Configuration Management

The system uses a **two-file configuration strategy** to separate host-level Docker settings from runtime engine tuning.

> [!IMPORTANT]
> **`.env`** and **`config.env`** serve different purposes. Do not conflate them.

### 1. `.env` — Host-Level Docker Compose Variables
These are consumed by `docker-compose.yml` for bind mounts, Traefik routing rules, and container environment injection. They are **never** loaded directly by `main.py` — they arrive via Docker's `env_file:` directive or `environment:` block.

| Variable | Default | Description | Consumed By |
|---|---|---|---|
| `DOMAIN_LOCAL` | `ps1.lan` | LAN domain for Traefik routing rules | `docker-compose.yml` Traefik labels |
| `DOMAIN_REMOTE` | `ps1.yourdomain.com` | WAN domain for Traefik routing rules; also read by `main.py` as `DOMAIN` | `docker-compose.yml` Traefik labels, `load_app_config()` |
| `HOST_ROM_DIR` | `/path/to/ROMs/PSX` | Absolute host path to PS1 ROMs | `docker-compose.yml` bind mount, `load_app_config()` |
| `HOST_SNES_ROM_DIR` | `./userdata/snes` | Host path to SNES ROMs | `docker-compose.yml` bind mount |
| `HOST_GBA_ROM_DIR` | `./userdata/gba` | Host path to GBA ROMs | `docker-compose.yml` bind mount |
| `HOST_BIOS_DIR` | `/path/to/ROMs/BIOS` | Host path to PS1 BIOS files | `docker-compose.yml` bind mount, `load_app_config()` |
| `HOST_CACHE_DIR` | `/tmp/ps1cache` | Host path for extracted ROM cache | `docker-compose.yml` bind mount, `load_app_config()` |

### 2. `config.env` — Runtime Engine Settings
Loaded by the Orchestrator (`load_app_config()`) and Watchdog (startup) via `python-dotenv`. Changes require a service restart (`./start.sh`).

| Variable | Default | Description | Consumed By |
|---|---|---|---|
| `RESOLUTION_SCALE` | `1` | Rendering profile: 1=Software (efficient), 2=Vulkan Mid, 3+=Vulkan High | `start_session()` → injected into container env |
| `CPUS_PER_SESSION` | `2.0` | CPU cores per session (Docker `nano_cpus`) | `load_app_config()`, `start_session()` |
| `MEM_LIMIT_PER_SESSION` | `2g` | RAM limit per container | `load_app_config()`, `start_session()` |
| `AUDIO_BACKEND` | `Cubeb` | Audio backend: Cubeb, PulseAudio, ALSA, Null | `start_session()` → injected into container env |
| `STREAM_BITRATE` | `2000` | Video bitrate in kbps. Injected as `SELKIES_VIDEO_BITRATE` — sets the initial bitrate directly on the selkies-gstreamer process. LSIO also offers `SELKIES_H264_CRF` for web UI quality control; both coexist. | `start_session()` → injected into container env |
| `STREAM_FRAMERATE` | `30` | Max FPS. Injected as `SELKIES_VIDEO_FRAMERATE` — sets the initial framerate on the selkies-gstreamer process. LSIO also offers `SELKIES_FRAMERATE` for web UI slider; both coexist. | `start_session()` → injected into container env |
| `STREAM_QUALITY` | `50` | Encoder quality (1-100). Mapped to `SELKIES_H264_CRF` (CRF 50-5, lower=better). | `start_session()` → injected into container env |
| `SHOW_FPS` | `false` | Show FPS counters in emulator. Injected into container; consumed by `custom_autostart.sh` `[Display] ShowFPS`. | `start_session()` → injected into container env |
| `ENABLE_DEBUG_MODE` | `false` | When `true`, shows DEBUG_MODE_FULL_ACCESS card; mounts full `/roms` | `load_app_config()`, `start_session()` |
| `ROM_CACHE_MAX_MB` | `5000` | Max disk space for extracted ROM cache in MB (0=disabled) | `load_app_config()`, `get_or_extract_rom_set()` |
| `MAX_HOST_CPU_PERCENT` | `90` | Host CPU load (%) threshold before blocking new sessions | `load_app_config()`, `check_host_resources()` |
| `MAX_HOST_MEM_PERCENT` | `90` | Host RAM usage (%) threshold before blocking new sessions | `load_app_config()`, `check_host_resources()` |
| `RATE_LIMIT_SESSIONS_PER_MIN` | `3` | Max session launch requests per client per minute | `load_app_config()`, `is_rate_limited()` |
| `IDLE_TIMEOUT_MINS` | `30` | Minutes of inactivity before watchdog kills a session | `watchdog_loop()` |
| `NETWORK_NAME` | `emulator-net` | Docker network name for spawned containers | `load_app_config()`, `start_session()` |
| `IMAGE_NAME` | `custom-duckstation` | Docker image for session containers | `load_app_config()`, `start_session()` |

### 3. Container-Internal Defaults (overridable via `docker-compose.yml` `environment:`)
These variables are read by the Orchestrator at runtime via `os.getenv()` but are **not** exposed in `config.env`. Set them in the `environment:` block of `docker-compose.yml` if you need to override the defaults.

| Variable | Default | Description |
|---|---|---|
| `COVERS_DIR` | `/app/userdata/covers` | Path inside the orchestrator container where cover art images are cached. Read by `load_app_config()`. |

> [!WARNING]
> `watchdog.py` **hardcodes** `emulator-net` and `custom-duckstation` in its container filter rather than reading `NETWORK_NAME`/`IMAGE_NAME` from config. Only `IDLE_TIMEOUT_MINS` is dynamically loaded. **If you change `NETWORK_NAME` or `IMAGE_NAME` in `config.env`, you MUST also manually update the corresponding string literals in `watchdog_loop()` until this is resolved.**

---

## 🛰️ Network & Routing Architecture

### 1. The Edge Proxy: Traefik
Traefik is the **only service exposed** to host ports 80 (HTTP) and 443 (HTTPS).
- **SSL Termination**: Handles all HTTPS via certs in `traefik_dynamic.yml`.
- **Dynamic Discovery**: Monitors Docker socket for new container labels.
- **Path-Based Multiplexing**:
  - `/` or `/api/*` → **Orchestrator**
  - `/{session_id}/*` → **Game Session** container
  - `/dashboard/` → **Traefik Dashboard** (admin-auth protected)
  - `/admin` or `/api/admin/*` → **Admin API** (admin-auth protected)

### 2. Routing Priority Hierarchy
| Priority | Router | Auth? | Description | Why this priority? |
|:---|:---|:---|:---|:---|
| **100** | `duckstation-{id}` | Session Password | Game stream. Injected dynamically via Docker labels at container creation. | Must beat all static routes so game sessions are always reachable. |
| **40** | `orchestrator-admin` | **YES** (Basic Auth) | Admin APIs (`/api/admin/`) and Dashboard (`/admin`). | Higher than public API to ensure admin paths can never be shadowed. |
| **30** | `orchestrator-api` | No | Public APIs: ROM list, start/stop session, art, status. | Explicit `/api/` prefix routes above the catch-all. |
| **20** | `traefik-dashboard` | **YES** (Basic Auth) | Traefik internal dashboard at `/dashboard/`. | Lowest named route; below all application routes. |
| **1** | `orchestrator-secure` | No | Catch-all — serves the SPA frontend. | Priority 1 ensures it only fires if nothing else matched. |

### 3. URL Reference
All public URLs use the domains defined in `.env`:

| Endpoint | URL |
|---|---|
| **Frontend (SPA)** | `https://${DOMAIN_REMOTE}/` |
| **Public API** | `https://${DOMAIN_REMOTE}/api/roms`, `/api/start-session`, etc. |
| **Admin Dashboard** | `https://${DOMAIN_REMOTE}/admin` |
| **Admin API** | `https://${DOMAIN_REMOTE}/api/admin/sessions` |
| **Traefik Dashboard** | `https://${DOMAIN_REMOTE}/dashboard/` (Basic Auth) |
| **Game Session** | `https://${DOMAIN_REMOTE}/{session_id}/` |

> [!WARNING]
> Port 8080 is **not exposed** in `docker-compose.yml`. The Traefik dashboard is accessed through the main HTTPS port (443) at `/dashboard/`, protected by admin-auth middleware.

---

## 📡 Backend API Reference

### Game Management
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/roms` | No | De-duplicated game list. Multi-disc sets merged. Returns `{ps1: [], snes: [], gba: []}`. |
| `GET` | `/api/rom-art/{game_id}` | No | Serves game poster. Auto-fetches from Libretro Thumbnails if missing. Cached 30 days. |
| `POST` | `/api/start-session` | No | Payload: `{"game_filename": "Game.zip", "client_id": "uuid", "platform": "ps1"}`. Spawns or reuses container. |
| `GET` | `/api/session-status/{session_id}?client_id=X` | Owner only | Returns metrics from in-memory cache. Verifies ownership. |
| `GET` | `/api/active-sessions/{client_id}` | No | Lists all sessions owned by a client. |
| `POST` | `/api/stop-session/{session_id}` | Owner only | Payload: `{"client_id": "uuid"}`. Force-removes the container. |

### Admin API (Basic Auth via Traefik)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/admin/sessions` | Lists all running sessions with CPU/RAM metrics and host stats. |
| `POST` | `/api/admin/stop-session/{session_id}` | Force-stops any session regardless of owner. |
| `GET` | `/admin` | Serves the admin dashboard HTML page. |

### WASM Platforms (SNES, GBA)
When `platform` is not `ps1`, the Orchestrator **does not spawn a Docker container**. Instead, it immediately returns a static URL pointing to the browser-based emulator:
```
/emulator.html?core={platform}&rom=/rom-files/{platform}/{encoded_rom}
```
- The ROM files are served directly by FastAPI's `StaticFiles` mount — PS1 uses extracted containers, but SNES/GBA ROMs are served as static files via `/rom-files/snes/` and `/rom-files/gba/` respectively (see `main.py` end of file for mount declarations).
- Supported platforms: `snes`, `gba`.
- No resource limits, watchdog, or session tracking apply — the entire emulator runs in the user's browser (WebAssembly).

---

## 🎨 Frontend & Full Lifecycle Workflow

### End-To-End Sequence Diagram
```mermaid
sequenceDiagram
    participant Browser
    participant Traefik as Traefik Proxy
    participant API as Orchestrator (FastAPI)
    participant Docker as Docker Daemon
    participant Container as Game Container

    Browser->>Traefik: GET / (Load Library)
    Traefik->>API: Route to backend
    API-->>Browser: Return index.html & script.js
    
    Browser->>API: POST /api/start-session {game, client_id}
    API->>API: Rate limit check
    API->>API: Host resource check (CPU/RAM)
    API->>API: Extract ROM to cache (fcntl advisory lock)
    API->>Docker: Spawn container (bind /dev/uinput, /dev/dri)
    Docker-->>API: Container ID returned
    API-->>Browser: Return {session_id, url_path, password}

    loop Milestone Polling (Every 1.5s)
        Browser->>API: GET /api/session-status/{id}?client_id=X
        API-->>Browser: status: 'waiting_for_x', 'waiting_for_wm', 'initializing'...
    end

    Note over Browser, Container: Status becomes 'running_game'
    
    Browser->>Traefik: iframe connects to /{id}/ (WSS/HTTP)
    Traefik->>Container: Reverse proxy to container port 3000
    Container-->>Browser: Stream Video & Audio via Selkies WebRTC

    loop Background Heartbeat (Every 4s, parallel across all sessions)
        API->>Docker: metrics_collector checks all containers via asyncio.gather
        API->>API: Updates metrics_cache dict
    end
```

### Frontend Step-By-Step
1. **Identification**: Generates a persistent `clientId` (UUID) in `localStorage`.
2. **Library Loading**: Renders a poster gallery with cover art from `/api/rom-art/`.
3. **Launching**: User clicks a card → `POST /api/start-session` → loading overlay shown.
4. **Polling**: Frontend polls `/api/session-status/` for milestone updates (WAITING_FOR_X → WAITING_FOR_WM → INITIALIZING → RUNNING_GAME).
5. **Theater Mode**: Once `running_game`, an `<iframe>` loads `/{session_id}/` for the Selkies stream.
6. **Heartbeat**: Background interval checks session status; auto-exits if container dies.

---

## 🔒 Container Security Hardening

Every game session container is launched with these security environment variables (set in `start_session()`):

| Variable | Value | Purpose |
|---|---|---|
| `HARDEN_DESKTOP` | `true` | Locks down the desktop environment |
| `DISABLE_OPEN_TOOLS` | `true` | Prevents opening system tools |
| `DISABLE_SUDO` | `true` | Removes sudo access |
| `DISABLE_TERMINALS` | `true` | Blocks terminal access |
| `DISABLE_CLOSE_BUTTON` | `true` | Prevents closing the emulator window |
| `DISABLE_MOUSE_BUTTONS` | `true` | Disables right-click context menus |
| `HARDEN_KEYBINDS` | `true` | Prevents system keybind escapes |
| `SELKIES_COMMAND_ENABLED` | `False` | Disables Selkies command execution |
| `SELKIES_UI_SIDEBAR_SHOW_FILES` | `False` | Hides file browser in Selkies UI |
| `SELKIES_UI_SIDEBAR_SHOW_APPS` | `False` | Hides app launcher in Selkies UI |
| `SELKIES_FILE_TRANSFERS` | `""` | Disables file transfer capability |

Additionally, DNS "blackholing" is applied via `extra_hosts`:
- `api.github.com` → `0.0.0.0`
- `github.com` → `0.0.0.0`

This prevents DuckStation from hanging on update checks.

> [!WARNING]
> `SELKIES_MICROPHONE_ENABLED` is **not overridden**, meaning it defaults to `True` (microphone passthrough is enabled). On a shared multi-user platform this has privacy implications. Consider explicitly injecting `"SELKIES_MICROPHONE_ENABLED": "False"` in `start_session()` if microphone access is not required.

> [!NOTE]
> The FastAPI app uses a **fully open CORS policy** (`allow_origins=["*"]`). This is intentional and safe **only because Traefik is the sole public entry point** and the Orchestrator listens exclusively on the internal Docker network. If you deploy the Orchestrator without Traefik, you must restrict `allow_origins` to your actual domain.

---

## 📡 Selkies Streaming Variables (LSIO Base Image)

The DuckStation container is based on [docker-baseimage-selkies](https://github.com/linuxserver/docker-baseimage-selkies). Below are the **streaming-related** Selkies env vars available for injection. Variables marked ✅ are currently set by `start_session()`; ⬜ are available but unused.

### Video & Encoding
| Variable | Default | Type | Status | Description |
|---|---|---|---|---|
| `SELKIES_ENCODER` | `x264enc,x264enc-striped,jpeg` | Enum | ⬜ | Comma-separated encoder list. First = default. |
| `SELKIES_FRAMERATE` | `8-120` | Range | ⬜ | FPS range for LSIO web UI slider. **Not injected** — `SELKIES_VIDEO_FRAMERATE` (upstream) is used instead to set gstreamer directly. |
| `SELKIES_H264_CRF` | `5-50` | Range | ✅ | H.264 Constant Rate Factor. **Wired to `STREAM_QUALITY`** (quality 1–100 → CRF 50–5, lower = higher quality). |
| `SELKIES_JPEG_QUALITY` | `1-100` | Range | ⬜ | JPEG encoder quality (when using `jpeg` encoder). |
| `SELKIES_H264_FULLCOLOR` | `False` | Bool | ⬜ | Full color range for H.264. |
| `SELKIES_H264_STREAMING_MODE` | `False` | Bool | ⬜ | Streaming optimization mode. |
| `SELKIES_USE_CPU` | `False` | Bool | ⬜ | Force CPU encoding. |
| `SELKIES_USE_PAINT_OVER_QUALITY` | `True` | Bool | ⬜ | Use paint-over quality optimization. |
| `SELKIES_MANUAL_WIDTH` | `0` | Int | ✅ | Lock resolution width. |
| `SELKIES_MANUAL_HEIGHT` | `0` | Int | ✅ | Lock resolution height. |
| `SELKIES_VIDEO_BITRATE` | — | Int | ✅ | Upstream selkies-gstreamer var. Sets initial bitrate directly on the process. Works alongside LSIO's `SELKIES_H264_CRF`. |
| `SELKIES_VIDEO_FRAMERATE` | — | Int | ✅ | Upstream selkies-gstreamer var. Sets initial framerate directly on the process. Works alongside LSIO's `SELKIES_FRAMERATE`. |

### Audio
| Variable | Default | Status | Description |
|---|---|---|---|
| `SELKIES_AUDIO_ENABLED` | `True` | ⬜ | Enable/disable audio streaming. |
| `SELKIES_AUDIO_BITRATE` | `320000` | ✅ | Audio bitrate in bps. |
| `SELKIES_MICROPHONE_ENABLED` | `True` | ⬜ | Enable microphone passthrough. **Defaults to enabled — see security note above.** |

### UI Controls
| Variable | Default | Status | Description |
|---|---|---|---|
| `SELKIES_UI_SHOW_SIDEBAR` | `True` | ⬜ | Show/hide the settings sidebar. |
| `SELKIES_UI_SIDEBAR_SHOW_VIDEO_SETTINGS` | `True` | ⬜ | Show video settings in sidebar. |
| `SELKIES_UI_SIDEBAR_SHOW_AUDIO_SETTINGS` | `True` | ⬜ | Show audio settings in sidebar. |
| `SELKIES_UI_SIDEBAR_SHOW_STATS` | `True` | ⬜ | Show stream stats in sidebar. |
| `SELKIES_UI_SIDEBAR_SHOW_GAMEPADS` | `True` | ⬜ | Show gamepad config in sidebar. |
| `SELKIES_UI_SIDEBAR_SHOW_FILES` | `True` | ✅ (`False`) | File browser (disabled for security). |
| `SELKIES_UI_SIDEBAR_SHOW_APPS` | `True` | ✅ (`False`) | App launcher (disabled for security). |
| `SELKIES_COMMAND_ENABLED` | `True` | ✅ (`False`) | Remote command execution (disabled). |
| `SELKIES_FILE_TRANSFERS` | `upload,download` | ✅ (`""`) | File transfer (disabled). |
| `SELKIES_GAMEPAD_ENABLED` | `True` | ⬜ | Gamepad input passthrough. |
| `SELKIES_CLIPBOARD_ENABLED` | `True` | ⬜ | Clipboard passthrough. |

> **ℹ️ Note**: `start_session()` injects `SELKIES_VIDEO_BITRATE` and `SELKIES_VIDEO_FRAMERATE` (upstream selkies-gstreamer vars) which set the **initial stream defaults** directly on the gstreamer process. LSIO also offers `SELKIES_H264_CRF` and `SELKIES_FRAMERATE` which control the **web UI sliders**. Both mechanisms coexist — the upstream vars work, while the LSIO vars could optionally be added to let users adjust quality via the Selkies sidebar.

---

## 🔍 Container Bootstrap: `custom_autostart.sh`

Inside each DuckStation container, the `custom_autostart.sh` script orchestrates the startup sequence:

1. **X Server Wait** — Polls `xdpyinfo` up to 30s, writing `WAITING_FOR_X` to `/tmp/session_status`.
2. **Window Manager Wait** — Polls for `openbox` process up to 15s, writing `WAITING_FOR_WM`.
3. **DuckStation Config** — Generates `settings.ini` from Docker env vars (`RENDERER`, `RESOLUTION_SCALE`, `TEXTURE_FILTERING`, `VSYNC`, `AUDIO_BACKEND`, `SHOW_FPS`, etc.).
4. **ROM Handling** — If `ROM_PRECACHED=true`, mounts the pre-extracted directory. Otherwise, unzips the mounted `.zip` in-container.
5. **PTY Launch** — Uses a Python script with `pty.openpty()` to trick DuckStation into thinking it's in an interactive terminal, preventing headless hangs.
6. **Lifecycle** — When DuckStation exits, the PTY launcher writes `STOPPED` to `/tmp/session_status`. The background heartbeat collector in the Orchestrator detects this state and safely terminates the container via the Docker API.

Status markers written to `/tmp/session_status`:

```
INITIALIZING (pre-launch)
  → WAITING_FOR_X
  → WAITING_FOR_WM
  → INITIALIZING (post-WM, pre-game — script resets status before launching DuckStation)
  → RUNNING_GAME
  → STOPPED | ERROR
```

> [!NOTE]
> The second `INITIALIZING` is intentional — the script resets the status marker after the WM is confirmed ready, immediately before handing off to the emulator. This is not a typo.

### Game Context Environment Variables
These env vars are injected per-session by `start_session()` and are the primary communication channel between the Orchestrator and `custom_autostart.sh`:

| Variable | Example Value | Purpose |
|---|---|---|
| `GAME_ROM` | `/roms/Metal Gear Solid (Disc 1).cue` | Full in-container path to the ROM or playlist. Empty string in debug mode. |
| `GAME_NAME` | `Metal Gear Solid` | Human-readable game name (multi-disc base name), used for logging. |
| `ROM_PRECACHED` | `true` | When set, tells `custom_autostart.sh` to skip in-container extraction and use the pre-mounted host cache directory. |

---

## 🛠️ Engine Workarounds & Stability Features

### 1. PTY-Based Emulator Launch (Headless Evasion)
DuckStation hangs in non-interactive environments. The `launch_duck.py` script allocates a pseudo-terminal via `pty` to simulate an interactive session.

### 2. Persistent ROM Cache System
- **Flow**: Extraction happens once on the host. Subsequent sessions mount pre-extracted files.
- **Disk Safety**: Enforces `ROM_CACHE_MAX_MB` limit (default 5GB).
- **Locking**: Uses `fcntl.flock` advisory locks to prevent concurrent extraction corruption.
- **Multi-disc parallel extraction**: Uses `ThreadPoolExecutor` to extract all disc ZIPs in parallel (each disc has uniquely named files, so no collision risk).

### 3. Update Check Blackholing
Docker `extra_hosts` maps `github.com` and `api.github.com` to `0.0.0.0`, instantly failing update checks.

### 4. glibc DNS Lookup Crash (IPv6)
`Dockerfile.duckstation` appends `precedence ::ffff:0:0/96 100` to `/etc/gai.conf` to prefer IPv4.

### 5. Concurrent Extraction Locking
Linux advisory file locking (`fcntl`) with per-ROM `.lock` files prevents parallel extraction corruption.

### 6. Watchdog Grace Period
A 120-second grace period ensures containers aren't killed before they finish booting. Activity checks run in parallel via `ThreadPoolExecutor`; all dict mutations happen sequentially in the main thread to prevent race conditions.

### 7. Multi-Disc Set Detection
Games with "(Disc X)" in the filename are grouped. A virtual `playlist.m3u` is generated for live disc swapping.

### 8. Smart Art Fetcher & Cache
`/api/rom-art` converts game names to Libretro-compatible slugs, downloads official box art via `run_in_executor` (non-blocking), and caches locally. Browser cache: 30 days.

### 9. Container Recycling Loops
Verification loop waits up to 10s for container removal before spawning a replacement.

### 10. Orchestrator-Driven Session Termination
When DuckStation exits, the PTY launcher writes `STOPPED` to `/tmp/session_status`. The orchestrator's background heartbeat detects this and terminates the container via the Docker API. This replaced the previous `sudo kill 1` approach which broke when `DISABLE_SUDO=true` was added for security hardening.

### 11. Xvfb Resolution Clamping
The `MAX_RES`, `SELKIES_MANUAL_WIDTH`, and `SELKIES_MANUAL_HEIGHT` env vars are injected to clamp the X11 virtual framebuffer to the game's actual streaming resolution (e.g., `1024x768`) instead of the base image default of `15360x8640`. This reduces Xvfb memory from ~500MB to ~70MB per session.

### 12. Parallel ROM Listing
The `/api/roms` endpoint runs `glob.glob()` for PS1, SNES, and GBA directories in parallel via `asyncio.gather` + `run_in_executor`, reducing wall time on network mounts (CIFS/NFS).

---

## 🛡️ Admin Dashboard & Security

### Authentication
- **Method**: Traefik Basic Auth middleware via `.credentials` file.
- **Format**: `{SHA}` hashed password.
- **Generate**: `htpasswd -nbB admin NEW_PASSWORD > .credentials` *(requires `apache2-utils`: `sudo apt install apache2-utils`)*
  - Alternative (no system deps): `python3 -c "import bcrypt; print('admin:' + bcrypt.hashpw(b'NEW_PASSWORD', bcrypt.gensalt()).decode())" > .credentials` *(requires `pip install bcrypt`)*
- **Apply**: Restart traefik and orchestrator after changing.

### Dashboard Capabilities
- Live CPU/Memory per session
- Global host CPU/RAM utilization
- Force-stop any session

---

## 🏎️ Scaling & Resource Limits

### Session Containers
| Limit | Config Variable | Default | How Enforced |
|---|---|---|---|
| CPU per session | `CPUS_PER_SESSION` | `2.0` | Docker `nano_cpus` |
| RAM per session | `MEM_LIMIT_PER_SESSION` | `2g` | Docker `mem_limit` |
| Shared memory per session | (hardcoded) | `1gb` | Docker `shm_size`; required for X11/Selkies stack. At 40 sessions this is 40GB of shm — ensure host has sufficient memory. |
| Host CPU gate | `MAX_HOST_CPU_PERCENT` | `90` | Checked before every launch |
| Host RAM gate | `MAX_HOST_MEM_PERCENT` | `90` | Checked before every launch |
| Launch rate | `RATE_LIMIT_SESSIONS_PER_MIN` | `3` | Per-client sliding window |
| Resolution profile | `RESOLUTION_SCALE` | `1` | Software (1) vs Vulkan (2+) |
| Stream bandwidth | `STREAM_BITRATE` | `2000` | Selkies `SELKIES_VIDEO_BITRATE` |

### Infrastructure Containers (`docker-compose.yml`)
| Container | Memory Limit | Typical Usage |
|---|---|---|
| Traefik | `256m` | ~50MB |
| Orchestrator | `512m` | ~40MB |
| Watchdog | `128m` | ~20MB |

---

## 📂 File System Overview

### Application Files
| File | Purpose |
|---|---|
| `main.py` | Orchestrator — session logic, Docker management, all API endpoints |
| `watchdog.py` | Session reaper — kills idle containers |
| `custom_autostart.sh` | In-container bootstrap — X wait, config generation, PTY launch |
| `config.env` | Runtime engine settings (resolution, limits, timeouts) |
| `.env` | Host-level Docker Compose variables (domains, host paths) |
| `docker-compose.yml` | Service definitions, Traefik labels, bind mounts |
| `traefik_dynamic.yml` | TLS certificates and admin-auth middleware definition |
| `.credentials` | Hashed admin password for Basic Auth |
| `Dockerfile.duckstation` | Builds game container (adds unzip, IPv6 fix, custom autostart) |
| `Dockerfile.orchestrator` | Builds API server (Python 3.11, FastAPI, Docker SDK) |
| `start.sh` | Build & launch script (builds image, starts compose) |
| `stop.sh` | Teardown script (kills sessions, stops compose, cleans locks) |
| `static/` | Frontend SPA (HTML, CSS, JS), admin dashboard |
| `LICENSE` | AGPL-3.0 license |
| `tests/` | Unit and regression tests |

### Operational & Reference Documents
| File | Purpose |
|---|---|
| `ARCHITECTURE.md` | This document — full technical reference |
| `PROJECT_BLUEPRINT.md` | Compact AI/developer onboarding summary ("DNA" of the engine) |
| `walkthrough.md` | Step-by-step operational walkthrough |
| `TODO.md` | Planned features, known gaps, and open issues |
| `.env.example` | Template for `.env` with all keys documented |
| `config.env.example` | Template for `config.env` with all keys documented |
| `install_docker.sh` | Helper script for Docker installation on fresh hosts |

---

## 🧪 Testing

The engine includes a comprehensive regression test suite located in `tests/test_engine.py`.

### Execution
You can run the full test suite using pytest:
```bash
pytest tests/test_engine.py -v --tb=short
```

### Architecture & Coverage
The test suite uses the `pytest` framework and heavily relies on `unittest.mock` to validate logic *without* needing a live Docker daemon or heavy containers. It specifically mocks `docker.from_env()`.

**Key Test Coverage Areas:**
1. **Configuration Cascade**: Verifies fallback defaults and parsing logic for `.env` and `config.env` overrides.
2. **Rate Limiting**: Tests the sliding window implementation.
3. **Multi-Disc Detection**: Validates Regex patterns matching sibling discs `(Disc 1)`, `(Disc 2)`, etc.
4. **Graphics Selection**: Checks the resolution scale-to-renderer mapping (`Software` vs `Vulkan`).
5. **Security Hardening**: Asserts that critical security variables (e.g. `DISABLE_SUDO`, `HARDEN_DESKTOP`) are present.
6. **Watchdog**: Verifies grace period logic and API status matching.

---

## 🔧 Known Technical Debt

| Issue | Location | Details |
|---|---|---|
| Watchdog hardcodes network/image names | `watchdog_loop()` | `NETWORK_NAME` and `IMAGE_NAME` from `config.env` are ignored; strings are duplicated in code. |
| `asyncio.get_event_loop()` deprecation | `start_session()`, `get_rom_art()`, `list_roms()` | Deprecated in Python 3.10+. Should migrate to `asyncio.get_running_loop()` inside async functions. |
| No `MAX_CONCURRENT_LAUNCHES` | `start_session()` | Mass simultaneous logins can cause CPU/IO spikes during parallel extraction. A task queue (`asyncio.Queue`) would decouple launch requests from extraction workers. |
| Adaptive jitter missing | `metrics_collector()` | All sessions report simultaneously, creating periodic mini-spikes. Random sleep jitter per session would distribute load. |
| Persistent save states | `start_session()` | No per-user save directory is mounted. Progress is lost when a session ends. |
