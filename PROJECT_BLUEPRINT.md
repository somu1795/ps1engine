# 🧩 PROJECT BLUEPRINT: PS1 Cloud Engine

This document is a compact representation of the "DNA" of the PS1 Engine. It is designed to be ingested by an AI or developer to recreate, modify, or scale the codebase while maintaining all custom stability and performance optimizations.

---

## 🚀 1. The Core Objective
Build a high-density, multi-user PS1 streaming platform capable of hosting 40+ simultaneous sessions on a single 50-core machine.

### Key Pillars
| Pillar | How | Config Variable |
|---|---|---|
| **Instant Play** | Zero-config for users; server-side rendering & streaming | `RESOLUTION_SCALE`, `STREAM_BITRATE` |
| **Resource Boundary** | Strict CPU/Memory capping per player | `CPUS_PER_SESSION`, `MEM_LIMIT_PER_SESSION` |
| **Safety Valve** | Host CPU/RAM monitoring blocks overload | `MAX_HOST_CPU_PERCENT`, `MAX_HOST_MEM_PERCENT` |
| **Rate Limiting** | Per-client launch spam protection | `RATE_LIMIT_SESSIONS_PER_MIN` |
| **Hardware Agnostic** | Software rendering at scale 1; no GPU required | `RESOLUTION_SCALE` |
| **Self-Healing** | Watchdog auto-cleanup of idle sessions | `IDLE_TIMEOUT_MINS` |

---

## 🛠️ 2. The Tech Stack
- **Edge Proxy**: Traefik v3.0 (SSL Termination, Basic Auth, Dynamic Discovery).
- **Orchestrator**: FastAPI (Python 3.11) + Docker SDK.
- **Container Base**: LinuxServer DuckStation (LSIO) + Selkies (WebRTC streaming).
- **Cleanup**: Custom Python Watchdog service.
- **Frontend**: Vanilla JS (SPA) + Modern CSS (Vibrant Dark Mode).

---

## 🏗️ 3. Critical Network Hierarchy (Traefik)
- **Domain Logic**: Uses `${DOMAIN_LOCAL}` and `${DOMAIN_REMOTE}` from **`.env`** (not `config.env`).
- **Priority 100 (Games)**: Direct paths to session containers (`/{id}/`).
- **Priority 40 (Admin API)**: Protected by Basic Auth via `.credentials`.
- **Priority 30 (Public API)**: Open endpoints for ROM lists, art, and session orchestration.
- **Priority 20 (Traefik Dashboard)**: At `/dashboard/`, protected by Basic Auth.
- **Priority 1 (UI)**: Catch-all SPA frontend.
- **SSL**: Global HTTP→HTTPS redirection enforced at Entrypoint level.

> **Note**: Traefik Dashboard is at `https://${DOMAIN_REMOTE}/dashboard/` — port 8080 is not exposed.

---

## ⚙️ 4. Configuration Split

### `.env` — Host-Level (Docker Compose)
```ini
DOMAIN_LOCAL=ps1.lan                # LAN domain for Traefik routing
DOMAIN_REMOTE=ps1.yourdomain.com    # WAN domain for Traefik routing + main.py DOMAIN
HOST_ROM_DIR=/path/to/ROMs/PSX      # Absolute host path to PS1 ROMs
HOST_SNES_ROM_DIR=/path/to/SNES     # Host path to SNES ROMs
HOST_GBA_ROM_DIR=./userdata/gba     # Host path to GBA ROMs
HOST_BIOS_DIR=/path/to/BIOS         # Host path to PS1 BIOS files
HOST_CACHE_DIR=/tmp/ps1cache        # Host path for ROM extraction cache
```

### `config.env` — Runtime Engine Settings
```ini
RESOLUTION_SCALE=1              # 1=Software, 2=Vulkan Mid, 3+=Vulkan High
CPUS_PER_SESSION=2              # CPU cores per session
MEM_LIMIT_PER_SESSION=2g        # RAM limit per session
AUDIO_BACKEND=Cubeb             # Audio: Cubeb, PulseAudio, ALSA, Null
STREAM_BITRATE=2000             # → SELKIES_VIDEO_BITRATE (sets initial gstreamer bitrate)
STREAM_FRAMERATE=30             # → SELKIES_VIDEO_FRAMERATE (sets initial gstreamer framerate)
STREAM_QUALITY=50               # → SELKIES_H264_CRF (quality 1-100 mapped to CRF 50-5)
SHOW_FPS=false                  # → DuckStation [Display] ShowFPS overlay
ENABLE_DEBUG_MODE=false         # Mount full ROM library for testing
ROM_CACHE_MAX_MB=5000           # Max cache disk usage (MB, 0=disable)
MAX_HOST_CPU_PERCENT=90         # Host CPU threshold (%)
MAX_HOST_MEM_PERCENT=90         # Host RAM threshold (%)
RATE_LIMIT_SESSIONS_PER_MIN=3   # Launch rate limit per client
IDLE_TIMEOUT_MINS=30            # Watchdog idle timeout (minutes)
NETWORK_NAME=emulator-net       # Docker network name
IMAGE_NAME=custom-duckstation   # Session container image
```

---

## 🧠 5. The "Secret Sauce" (Custom Workarounds)

### 🔒 ROM Extraction Lock
- **Problem**: Concurrent users crashing the system by extracting the same game.
- **Fix**: Python `fcntl.flock` (Advisory Locking). Queues users and locks per-ROM.

### 🕳️ Update Blackholing
- **Problem**: DuckStation hanging 30s checking for updates.
- **Fix**: Docker `extra_hosts` mapping `github.com` → `0.0.0.0`.

### 🛡️ glibc DNS Fix (IPv6)
- **Problem**: DNS lookups crashing in containers.
- **Fix**: `precedence ::ffff:0:0/96 100` in `Dockerfile.duckstation`.

### 🚦 Frontend Readiness Polling
- **Problem**: Users redirected to 404 while emulator boots.
- **Fix**: Frontend polls `/api/session-status/` and only redirects on `running_game`.

### ⏱️ Watchdog Grace Period
- **Problem**: Watchdog killing sessions before boot completes.
- **Fix**: 120-second minimum uptime before idle monitoring begins.

### 💿 Multi-Disc De-duplication
- **Problem**: Library cluttered with "Disc 1/2/3".
- **Fix**: Backend groups siblings, generates virtual M3U playlists for live disc swapping.

### 🖼️ Smart Box Art Fetcher
- **Problem**: Manually finding posters for hundreds of games.
- **Fix**: Automatic Libretro-compatible proxy-fetcher with host-side caching.

### 🔒 Container Security Hardening
- **Problem**: Users could escape the emulator via desktop tools.
- **Fix**: 11 hardening env vars injected at container launch (`HARDEN_DESKTOP`, `DISABLE_SUDO`, `DISABLE_TERMINALS`, etc.).

### ⚡ Background Metrics Buffering
- **Problem**: Synchronous Docker stats checks blocking at scale.
- **Fix**: Background collector updates `metrics_cache` every 4s. Status API returns instantly.

### 🖥️ PTY-Based Emulator Launch
- **Problem**: DuckStation hangs in headless environments.
- **Fix**: Python `pty.openpty()` allocates a pseudo-terminal for interactive emulation.

---

## 📂 6. File System Overview
| File | Purpose |
|---|---|
| `main.py` | The brain — session logic, Docker management, all APIs |
| `watchdog.py` | The reaper — kills idle containers (>IDLE_TIMEOUT_MINS) |
| `custom_autostart.sh` | In-container bootstrap — X wait, config gen, PTY launch |
| `config.env` | Runtime settings (resolution, limits, timeouts) |
| `.env` | Host Docker Compose variables (domains, host paths) |
| `docker-compose.yml` | Service definitions, Traefik labels, bind mounts |
| `static/` | Frontend SPA, admin dashboard, JS/CSS |
| `.credentials` | Hashed admin password for Traefik Basic Auth |
| `traefik_dynamic.yml` | TLS certs and admin-auth middleware |
| `start.sh` | Build & launch (builds image, starts compose) |
| `stop.sh` | Teardown (kills sessions, stops compose, cleans locks) |

---

## 🎯 7. AI Ingestion Summary
When recreating this project, prioritize:
1. **Traefik Priority Hierarchy** — the routing rules and their priorities
2. **Python File Locking** (`fcntl`) — concurrent extraction safety
3. **Container Security Hardening** — the 11+ env vars that lock down each session
4. **PTY Launch** — the `pty.openpty()` workaround for headless DuckStation

These components transform a simple emulator wrapper into a production-grade multi-user cloud engine.
