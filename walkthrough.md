# PS1 Engine User Guide & Walkthrough

## 🚀 Initial Setup

### 1. Copy Environment Templates
```bash
cp .env.example .env              # Host-level variables (domains, host paths)
cp config.env.example config.env  # Engine runtime settings (resolution, limits)
```

### 2. Configure `.env` (Host Paths & Domains)
Edit `.env` with your actual paths and domains:
```ini
DOMAIN_LOCAL=ps1.lan                # Your LAN domain (for local access)
DOMAIN_REMOTE=ps1.yourdomain.com    # Your WAN domain (for remote access)
HOST_ROM_DIR=/path/to/ROMs/PSX      # Absolute host path to PS1 ROMs (.zip)
HOST_SNES_ROM_DIR=/path/to/SNES     # Host path to SNES ROMs (.zip)
HOST_GBA_ROM_DIR=./userdata/gba     # Host path to GBA ROMs (.zip)
HOST_BIOS_DIR=/path/to/BIOS         # Host path to PS1 BIOS files (.bin)
HOST_CACHE_DIR=/tmp/ps1cache        # Host path for extracted ROM cache
```

### 3. Configure `config.env` (Engine Settings)
Adjust runtime parameters:
```ini
RESOLUTION_SCALE=1              # 1=Software, 2=Vulkan Mid, 3+=Vulkan High
CPUS_PER_SESSION=2              # CPU cores per session
MEM_LIMIT_PER_SESSION=2g        # RAM limit per session
AUDIO_BACKEND=Cubeb             # Audio: Cubeb, PulseAudio, ALSA, Null
STREAM_BITRATE=2000             # → SELKIES_VIDEO_BITRATE (sets initial gstreamer bitrate)
STREAM_FRAMERATE=30             # → SELKIES_VIDEO_FRAMERATE (sets initial gstreamer framerate)
ENABLE_DEBUG_MODE=false         # Mount full ROM library for testing
ROM_CACHE_MAX_MB=5000           # Max cache disk usage (MB, 0=disable)
MAX_HOST_CPU_PERCENT=90         # Host CPU threshold before blocking launches
MAX_HOST_MEM_PERCENT=90         # Host RAM threshold before blocking launches
RATE_LIMIT_SESSIONS_PER_MIN=3   # Max launches per user per minute
IDLE_TIMEOUT_MINS=30            # Minutes idle before session killed
NETWORK_NAME=emulator-net       # Docker network name
IMAGE_NAME=custom-duckstation   # Session container image
```

### 4. Generate Admin Credentials
```bash
python3 -c "import hashlib, base64; print('admin:{SHA}' + base64.b64encode(hashlib.sha1('YOUR_PASSWORD'.encode()).digest()).decode())" > .credentials
```

### 5. Set Up SSL Certificates
Place your TLS certificates in the project root:
- `cert.pem` — SSL certificate
- `key.pem` — Private key

### 6. Start / Stop
```bash
./start.sh   # Builds images, starts all services
./stop.sh    # Kills sessions, stops services, cleans locks
```

---

## 🌐 URL Reference
All URLs use the domains from your `.env` file:

| Endpoint | URL |
|---|---|
| **Game Library** | `https://${DOMAIN_REMOTE}/` |
| **Admin Dashboard** | `https://${DOMAIN_REMOTE}/admin` (Basic Auth) |
| **Traefik Dashboard** | `https://${DOMAIN_REMOTE}/dashboard/` (Basic Auth) |
| **Game Session** | `https://${DOMAIN_REMOTE}/{session_id}/` |

> **Note**: Port 8080 is NOT exposed. The Traefik dashboard is served through port 443 at `/dashboard/`.

---

## 🎮 Controls & Input

### Keyboard Mapping
| PS1 Button | Keyboard Key | Gamepad (SDL) |
|:---|:---|:---|
| **D-Pad Up** | `Up Arrow` | `DPadUp` |
| **D-Pad Right** | `Right Arrow` | `DPadRight` |
| **D-Pad Down** | `Down Arrow` | `DPadDown` |
| **D-Pad Left** | `Left Arrow` | `DPadLeft` |
| **Triangle** | `I` | `Y` |
| **Circle** | `L` | `B` |
| **Cross (X)** | `K` | `A` |
| **Square** | `J` | `X` |
| **Select** | `Backspace` | `Back` |
| **Start** | `Enter` | `Start` |
| **L1** | `Q` | `Left Shoulder` |
| **R1** | `E` | `Right Shoulder` |
| **L2** | `1` | `Left Trigger` |
| **R2** | `3` | `Right Trigger` |
| **L3** | `2` | `Left Stick` |
| **R3** | `4` | `Right Stick` |

### Analog Sticks (Keyboard)
| Stick | Up | Down | Left | Right |
|---|---|---|---|---|
| **Left Analog** | `W` | `S` | `A` | `D` |
| **Right Analog** | `T` | `G` | `F` | `H` |

### System Hotkeys
| Action | Key |
|---|---|
| **Fast Forward** | `Tab` |
| **Toggle Pause** | `Space` |
| **Open Pause Menu** | `Escape` |
| **Toggle Fullscreen** | `F11` |
| **Take Screenshot** | `F10` |

---

## ⚙️ Advanced Features

### Game Isolation (Default)
Each session mounts **only the selected game's ZIP file** (or its pre-extracted cache). The container cannot access other ROMs.

### Debug Mode (Full Access)
1. Set `ENABLE_DEBUG_MODE=true` in `config.env`.
2. Restart: `./start.sh`
3. A **"DEBUG_MODE_FULL_ACCESS"** card appears in the library.
4. Launching it boots DuckStation with the entire `/roms` directory mounted.

### Multi-Disc Games
Games with "(Disc 1)", "(Disc 2)" etc. are automatically grouped in the library. When launched, a `playlist.m3u` file is generated so you can swap discs via the DuckStation pause menu without restarting the session.

### WASM Platforms (SNES, GBA)
SNES and GBA games run in-browser via WASM emulators (no Docker container needed). The Orchestrator returns a static URL pointing to the browser-based emulator.

---

## 📊 Benchmarks & Performance Guide

### Server Load Benchmarks (Software 1x)
| Metric | Value |
|---|---|
| **CPU per user** | ~12% |
| **Launch Time (Cached)** | ~1.4s |
| **Launch Time (Uncached)** | ~5.2s |
| **Bandwidth per user** | <0.1 Mbps |

### Resolution vs. Bandwidth Matrix
| Internal Scale | Quality | CPU Usage | Bandwidth (Est) | Recommendation |
|:---|:---|:---|:---|:---|
| 1x (240p) | ⭐ (Native) | ~10% | <0.1 mbps | High Density (40+ users) |
| **2x (480p)** | ⭐⭐⭐ | **~100%** | **~0.2 mbps** | **Sweet Spot** |
| 4x (960p) | ⭐⭐⭐⭐⭐ | ~600% | ~12.0 mbps | Local Network Only |

**Recommendation:** For 30-40 web users over a 10mbps upstream, use **2x Resolution Scale** (`RESOLUTION_SCALE=2` in `config.env`).

---

## 📂 File System Overview
| File | Purpose |
|---|---|
| `main.py` | Orchestrator — session logic, Docker management, all APIs |
| `watchdog.py` | Session reaper — cleans idle containers |
| `custom_autostart.sh` | In-container bootstrap script |
| `config.env` | Runtime engine settings |
| `.env` | Host Docker Compose variables (domains, paths) |
| `docker-compose.yml` | Service definitions and Traefik routing |
| `static/` | Frontend SPA, admin dashboard |
| `.credentials` | Admin password (hashed) for Traefik Basic Auth |
| `start.sh` | Build & launch script |
| `stop.sh` | Teardown script |
