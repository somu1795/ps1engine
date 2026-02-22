# 🧩 PROJECT BLUEPRINT: Extreme PS1 Cloud Engine

This document is a compact representation of the "DNA" of the PS1 Engine. It is designed to be ingested by an AI to recreate, modify, or scale the codebase while maintaining all custom stability and performance optimizations.

---

## 🚀 1. The Core Objective
Build a high-density, multi-user PS1 streaming platform capable of hosting 40+ simultaneous sessions on a single 50-core machine.

### Key Pillars:
- **Instant Play**: Zero-configuration for users; all logic happens server-side.
- **Resource Boundary**: Strict CPU/Memory capping per player (2.0 Cores, 2GB RAM).
- **Safety Valve**: Host CPU/RAM monitoring prevents server-wide crashes.
- **Rate Limiting**: Protects against launch spam and bot activity.
- **Hardware Agnostic**: Uses software-native rendering; no GPU required.
- **Self-Healing**: Automatic cleanup of inactive sessions and BIOS verification.

---

## 🛠️ 2. The Tech Stack
- **Edge Proxy**: Traefik v3.0 (SSL Termination, Basic Auth, Dynamic Discovery).
- **Orchestrator**: FastAPI (Python 3.11) + Docker SDK.
- **Container Base**: LinuxServer DuckStation (LSIO) + Selkies (WebCodecs).
- **Cleanup**: Custom Python Watchdog service.
- **Frontend**: Vanilla JS (SPA) + Modern CSS (Vibrant Dark Mode).

---

## 🏗️ 3. Critical Network Hierarchy (Traefik)
- **Domain Logic**: Uses `${DOMAIN_LOCAL}` and `${DOMAIN_REMOTE}` for environment-agnostic routing.
- **Priority 100 (Games)**: Direct paths to session containers (`/{id}/`).
- **Priority 40 (Admin API)**: Protected by Basic Auth via `.credentials`.
- **Priority 30 (Public API)**: Open endpoints for ROM lists, art, and session orchestration.
- **Priority 1 (UI)**: Catch-all SPA frontend.
- **SSL**: Global HTTP to HTTPS redirection enforced at Entrypoint level.

---

## 🧠 4. The "Secret Sauce" (Custom Workarounds)
These features resolve upstream bugs and race conditions found during development:

### 🔒 ROM Extraction Lock
- **Problem**: Concurrent users crashing the system by extracting the same game.
- **Fix**: Python `fcntl.flock` (Advisory Locking). Queues users for extraction and verifies hash/size integrity on every hit.

### 🕳️ Update Blackholing
- **Problem**: DuckStation hanging for 30s checking for updates.
- **Fix**: Docker `extra_hosts` mapping `github.com` and `api.github.com` to `0.0.0.0`.

### 🛡️ glibc DNS Fix (IPv6)
- **Problem**: DNS lookups crashing in containers.
- **Fix**: `sysctls: {"net.ipv6.conf.all.disable_ipv6": 1}`.

### 🚦 Frontend Readiness Polling
- **Problem**: Users being redirected to a 404/Bad Gateway while the emulator is still booting.
- **Fix**: The frontend now stays on the "Loading" screen and polls the `/api/session-status/` endpoint. It only redirects once the game state moves to `running_game`, or alerts the user if an error is detected.

### ⏱️ Watchdog Grace Period
- **Problem**: Watchdog killing sessions before the user finishes loading.
- **Fix**: 120-second minimum uptime check before IDLE monitoring begins.

### 💿 Multi-Disc De-duplication
- **Problem**: Library cluttered with "Part 1/2/3" of the same game.
- **Fix**: Backend groups siblings and generates virtual M3U playlists on-the-fly for live disc swapping.

### 🖼️ Smart Box Art Fetcher
- **Problem**: Manually finding posters for hundreds of games.
- **Fix**: Automatic proxy-fetcher that pulls from Libretro DB, caches locally on the host, and enforces 30-day browser caching.

### 🔒 Security & Portability Audit
- **Problem**: Host metrics and paths leaking to containers or public strings.
- **Fix**: Scrubbed all host paths from `main.py`. Moved all data to `./userdata`. Implemented domain-agnostic routing.
- **Safety Valve**: Added CPU/RAM monitoring in `main.py` that blocks sessions if host load > 90%.

### ⚡ Background Metrics Buffering
- **Problem**: Synchronous Docker status checks blocking the server at scale (1.0s lag per poll).
- **Fix**: A background collector updates an in-memory `metrics_cache` every 3 seconds. The Status API now returns instantly (0.0s lag).

---

## 📊 5. Resource Management Strategy
- **Base Resolution**: 1x Native (Software Rendering).
- **CPU Cap**: `nano_cpus` set via `CPUS_PER_SESSION` (recommend 1.25 for 40 player density).
- **Caching**: Host-side RAID or fast SSD cache with a size-limited cleanup policy.
- **Isolation**: Each user is assigned a `clientId` in LocalStorage, preventing them from seeing or killing other users' games.

---

## 📂 6. File System Overview
- `/main.py`: The brain. Session logic, Docker management, and API.
- `/watchdog.py`: The reaper. Cleans up idle containers (>30m).
- `/static/`: The face. UI components, Admin Dashboard, and user scripts.
- `/config.env`: The heart. Global settings (Bitrate, Scale, Timing).
- `/docker-compose.yml`: The skeleton. Defines the core service relationship.

---

## 🎯 7. AI Ingestion Summary
When recreating this project, prioritize the **Traefik Priority Hierarchy** and **Python File Locking** logic above all else. These two components are what transform a simple emulator wrapper into a production-grade multi-user cloud engine.
