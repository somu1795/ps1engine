#!/bin/bash

# Immediate status update for Orchestrator
echo "INITIALIZING" > /tmp/session_status

# Ensure DISPLAY is set
export DISPLAY=:1
export LANG=en_US.UTF-8
export LANGUAGE=en_US.UTF-8
export TERM=xterm
export HOME=/config

# Wait for X server to be ready
echo "Waiting for X server..." > /config/autostart.log
for i in $(seq 1 30); do
    echo "WAITING_FOR_X" > /tmp/session_status
    if xdpyinfo -display :1 >/dev/null 2>&1; then
        echo "X server ready after ${i}s" >> /config/autostart.log
        echo "INITIALIZING" > /tmp/session_status
        break
    fi
    sleep 1
done

# Disable screensaver/DPMS just in case
xset s off >/dev/null 2>&1
xset -dpms >/dev/null 2>&1

# Cleanup stale lock files
rm -f /config/.local/share/duckstation/duckstation.lock
rm -f /tmp/duckstation.lock
rm -f /tmp/game/*

# Ensure configuration directories exist
mkdir -p /config/.local/share/duckstation
mkdir -p /config/.config/duckstation

# Set defaults if not present (these now prioritize Docker environment variables)
: ${RENDERER:=Software}
: ${RESOLUTION_SCALE:=1}
: ${TEXTURE_FILTERING:=Bilinear}
: ${TRUE_COLOR:=true}
: ${PGXP_GEOMETRY:=false}
: ${PGXP_TEXTURE:=false}
: ${VSYNC:=false}
: ${AUDIO_BACKEND:=Cubeb}
: ${SHOW_FPS:=false}

echo "[$(date)] Applying Config: Renderer=${RENDERER}, Scale=${RESOLUTION_SCALE}, Filter=${TEXTURE_FILTERING}, VSync=${VSYNC}" >> /config/autostart.log

# Determine Game List Path based on Mode
# If GAME_ROM is set (Isolated Mode), point to temp extraction dir
# If not set (Debug Mode), point to full library mount
GAME_LIST_PATH="/roms"
if [ -n "$GAME_ROM" ]; then
    GAME_LIST_PATH="/tmp/game"
fi

# Write settings.ini
cat > /config/.local/share/duckstation/settings.ini << SETTINGS
[Main]
SetupWizardIncomplete = false
StartFullscreen = true
ConfirmPowerOff = false
CheckForUpdates = false
SyncToHost = ${VSYNC}
SettingsVersion = 3

[AutoUpdater]
CheckForUpdates = false

[BIOS]
SearchDirectory = /config/.local/share/duckstation/bios

[GameList]
RecursivePaths = ${GAME_LIST_PATH}

[GPU]
Renderer = ${RENDERER}
ResolutionScale = ${RESOLUTION_SCALE}
TextureFiltering = ${TEXTURE_FILTERING}
TrueColor = ${TRUE_COLOR}
PGXPGeometryCorrection = ${PGXP_GEOMETRY}
PGXPTextureCorrection = ${PGXP_TEXTURE}
VSync = ${VSYNC}

[Audio]
Backend = ${AUDIO_BACKEND}

[Display]
ShowFPS = ${SHOW_FPS}

[Logging]
LogLevel = Debug
LogToConsole = true
LogToFile = true

[InputSources]
SDL = true
SDLControllerEnhancedMode = false

[Pad1]
Type = AnalogController
Up = Keyboard/UpArrow
Up = SDL-0/DPadUp
Right = Keyboard/RightArrow
Right = SDL-0/DPadRight
Down = Keyboard/DownArrow
Down = SDL-0/DPadDown
Left = Keyboard/LeftArrow
Left = SDL-0/DPadLeft
Triangle = Keyboard/I
Triangle = SDL-0/Y
Circle = Keyboard/L
Circle = SDL-0/B
Cross = Keyboard/K
Cross = SDL-0/A
Square = Keyboard/J
Square = SDL-0/X
Select = Keyboard/Backspace
Select = SDL-0/Back
Start = Keyboard/Enter
Start = SDL-0/Start
L1 = Keyboard/Q
L1 = SDL-0/LeftShoulder
R1 = Keyboard/E
R1 = SDL-0/RightShoulder
L2 = Keyboard/1
L2 = SDL-0/+LeftTrigger
R2 = Keyboard/3
R2 = SDL-0/+RightTrigger
L3 = Keyboard/2
L3 = SDL-0/LeftStick
R3 = Keyboard/4
R3 = SDL-0/RightStick
LLeft = Keyboard/A
LLeft = SDL-0/-LeftX
LRight = Keyboard/D
LRight = SDL-0/+LeftX
LDown = Keyboard/S
LDown = SDL-0/+LeftY
LUp = Keyboard/W
LUp = SDL-0/-LeftY
RLeft = Keyboard/F
RLeft = SDL-0/-RightX
RRight = Keyboard/H
RRight = SDL-0/+RightX
RDown = Keyboard/G
RDown = SDL-0/+RightY
RUp = Keyboard/T
RUp = SDL-0/-RightY

[Pad2]
Type = None

[Hotkeys]
FastForward = Keyboard/Tab
TogglePause = Keyboard/Space
Screenshot = Keyboard/F10
ToggleFullscreen = Keyboard/F11
OpenPauseMenu = Keyboard/Escape
SETTINGS

# Copy and Fix permissions
cp /config/.local/share/duckstation/settings.ini /config/.config/duckstation/settings.ini
chown -R 1000:1000 /config/.local/share/duckstation
chown -R 1000:1000 /config/.config/duckstation

LAUNCH_TARGET=""

if [ -n "$GAME_ROM" ]; then
    if [ "${ROM_PRECACHED}" = "true" ]; then
        # Pre-cached: files already extracted on host, mounted directly to /roms
        echo "[$(date)] Using precached ROM: $GAME_ROM" >> /config/autostart.log
        LAUNCH_TARGET="$GAME_ROM"
        GAME_LIST_PATH="/roms"
    else
        # Not cached: extract ZIP inside container (original behavior)
        case "$GAME_ROM" in
            *.zip|*.ZIP)
                echo "Detected ZIP file, extracting..." >> /config/autostart.log
                mkdir -p /tmp/game
                unzip -o "$GAME_ROM" -d /tmp/game >> /config/autostart.log 2>&1
                
                CUE_FILE=$(find /tmp/game -type f -iname "*.cue" | head -n 1)
                ISO_FILE=$(find /tmp/game -type f -iname "*.iso" | head -n 1)
                BIN_FILE=$(find /tmp/game -type f -iname "*.bin" | head -n 1)
                
                if [ -n "$CUE_FILE" ]; then
                    LAUNCH_TARGET="$CUE_FILE"
                elif [ -n "$ISO_FILE" ]; then
                    LAUNCH_TARGET="$ISO_FILE"
                elif [ -n "$BIN_FILE" ]; then
                    LAUNCH_TARGET="$BIN_FILE"
                fi
                ;;
            *)
                 LAUNCH_TARGET="$GAME_ROM"
                 ;;
        esac
    fi
fi

chmod -R 777 /tmp/game 2>/dev/null
rm -f /config/duckstation.log

# Create Python PTY Launcher
cat > /defaults/launch_duck.py << 'EOF'
import os
import sys
import time
import subprocess
import pty
import select

log_file = open("/config/autostart.log", "a")
sys.stdout = log_file
sys.stderr = log_file

print(f"\n--- Python PTY Launcher Starting [Time: {time.time()}] ---")
print("STATUS: INITIALIZING")
game_path = sys.argv[1] if len(sys.argv) > 1 else None
binary = "/opt/duckstation/usr/bin/duckstation-qt"

print(f"Target Game: {game_path}")

cmd = [binary, "-earlyconsole", "-batch", "-fullscreen", "-fastboot"]
if game_path:
    # Pass path as last argument without dash
    cmd.append(game_path)

print(f"Executing in PTY: {cmd}")
with open("/tmp/session_status", "w") as f: f.write("RUNNING_GAME")
sys.stdout.flush()

# Create PTY
master_fd, slave_fd = pty.openpty()

# Launch process attached to PTY slave
proc = subprocess.Popen(
    cmd,
    stdin=slave_fd,
    stdout=slave_fd,
    stderr=slave_fd,
    close_fds=True
)

os.close(slave_fd)  # Close slave in parent

print(f"Process started with PID: {proc.pid}")

# Read output from master_fd and log it
try:
    while True:
        r, w, e = select.select([master_fd], [], [], 1.0)
        if master_fd in r:
            try:
                data = os.read(master_fd, 1024)
            except OSError:
                break # PTY closed
            
            if not data:
                break
                
            # Log output (decode if possible, else repr)
            try:
                line = data.decode('utf-8', errors='replace')
                sys.stdout.write(line)
            except:
                sys.stdout.write(str(data))
            sys.stdout.flush()
        
        # Check if process exited
        if proc.poll() is not None:
            break
except Exception as e:
    print(f"Error reading PTY: {e}")

print(f"Process exited with code {proc.returncode}")
if proc.returncode != 0:
    with open("/tmp/session_status", "w") as f: f.write("ERROR")
else:
    with open("/tmp/session_status", "w") as f: f.write("STOPPED")
EOF

echo "Starting Python PTY launcher via nohup..." >> /config/autostart.log

(
    # Wait for window manager to be ready
    for i in $(seq 1 15); do
        echo "WAITING_FOR_WM" > /tmp/session_status
        if pgrep -x openbox > /dev/null 2>&1; then
            echo "INITIALIZING" > /tmp/session_status
            break
        fi
        sleep 1
    done
    if [ -n "$LAUNCH_TARGET" ]; then
        python3 /defaults/launch_duck.py "$LAUNCH_TARGET" >> /config/autostart.log 2>&1
    else
        python3 /defaults/launch_duck.py >> /config/autostart.log 2>&1
    fi
    echo "[$(date)] DuckStation stopped, killing container..." >> /config/autostart.log
    sudo kill 1
) &

exit 0
