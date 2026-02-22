# PS1 Engine User Guide & Walkthrough

## Quick Start
- **Start Engine:** `./start.sh` (Always rebuilds containers and pulls latest configuration)
- **Stop Engine:** `./stop.sh`

## Configuration
A central configuration file is available at `config.env`. You can edit this file to change resolution, resource limits, and streaming quality.

```ini
RESOLUTION_SCALE=1       # Profile: 1 (Efficient), 2 (Vulkan Mid), 3+ (Vulkan High)
MEM_LIMIT_PER_SESSION=2g # Hard memory cap per user
CPUS_PER_SESSION=2       # CPU core allocation per user
```

## Controls & Input
The emulator is pre-configured with the following keyboard mappings for a standard layout:

| PS1 Button | Keyboard Key | Virtual Controller |
| :--- | :--- | :--- |
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
| **Pause** | `Spacebar` | N/A |

### System Hotkeys
- **Fast Forward**: `Tab`
- **Toggle Pause**: `Space`
- **Open Pause Menu**: `Escape`
- **Toggle Fullscreen**: `F11`
- **Take Screenshot**: `F10`

## Advanced Features

### Game Isolation (Default)
When a game is launched, the system heavily isolates the container. It mounts **only that specific game's ZIP file**. This ensures:
- The emulator only sees the active game you clicked.
- Provides a clean, focused theater experience.
- Prevents container cross-contamination.

### Debug Mode (Full Access)
To access the full ROM library from within DuckStation (helpful for testing system-wide configuration or testing multi-disc .m3u behavior):
1. Edit `config.env` and set `ENABLE_DEBUG_MODE=true`.
2. Restart the orchestrator: `./start.sh`
3. A new hidden game card named **"DEBUG_MODE_FULL_ACCESS"** will dynamically appear in your library.
4. Launching this entry boots DuckStation with the entire `/roms` host directory mounted for unrestricted access.

## Benchmarks & Performance Guide

### Final Server Load Benchmarks (Software 1x)
- **CPU**: ~12% per user
- **Launch Time**: ~1.4s (Cached) / ~5.2s (Uncached)
- **Bandwidth**: <0.1 Mbps
- **Audio**: Auto-play verified (No microphone prompts triggering)

### 🌐 Resolution vs. Bandwidth Matrix
| Internal Scale | Quality | CPU Usage | Bandwidth (Est) | Recommend? |
| :--- | :--- | :--- | :--- | :--- |
| 1x (240p) | ⭐ (Native) | ~10% | <0.1 mbps | Efficient (High Density) |
| **2x (480p)** | ⭐⭐⭐ | **~100%** | **~0.2 mbps** | **Sweet Spot** |
| 4x (960p) | ⭐⭐⭐⭐⭐ | ~600% | ~12.0 mbps | Local Network Only |

**Recommendation:** For 30-40 web users over a 10mbps upstream connection, use **2x Resolution Scale**. It looks modern and sharp while staying extremely efficient.
