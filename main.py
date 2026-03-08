import uuid
import secrets
import docker
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel
import os
import requests
import re
import glob
import time
import shutil
import subprocess
import urllib.parse
import asyncio
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ps1engine")
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from collections import defaultdict
import fcntl
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

# Load unified config
CONFIG_ENV_PATH = os.getenv("CONFIG_ENV_PATH", "config.env")
load_dotenv(CONFIG_ENV_PATH)
ENABLE_DEBUG_MODE = os.getenv("ENABLE_DEBUG_MODE", "false").lower() == "true"

client = docker.from_env()

# --- Logging Silence ---
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(path in msg for path in ["/api/admin/sessions", "/api/active-sessions/"])

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

# --- Background Metrics Cache ---
metrics_cache = {} # session_id -> metrics dict
host_metrics = {"cpu": 0.0, "ram": 0.0}

# ---------------------------------------------------------------------------
# Platform Registry
# Describes every platform the engine knows about. Actual availability at
# runtime is controlled by ENABLED_PLATFORMS in config.env — no code changes
# needed to enable or disable a platform.
# ---------------------------------------------------------------------------
PLATFORM_REGISTRY: dict[str, dict] = {
    "ps1": {
        "display_name": "PlayStation 1",
        "engine": "docker",      # Spawns a dedicated DuckStation container
        "wasm_core": None,
        "rom_dir_attr": "ROM_DIR",
        "extensions": ["*.zip"],
    },
    "snes": {
        "display_name": "Super Nintendo",
        "engine": "wasm",        # Runs entirely in the browser (no container)
        "wasm_core": "snes",
        "rom_dir_attr": "SNES_ROM_DIR",
        "extensions": ["*.zip"],
    },
    "gba": {
        "display_name": "Game Boy Advance",
        "engine": "wasm",
        "wasm_core": "gba",
        "rom_dir_attr": "GBA_ROM_DIR",
        "extensions": ["*.zip"],
    },
}

# Runtime availability set — populated by load_app_config()
ENABLED_PLATFORMS: set[str] = set(PLATFORM_REGISTRY.keys())

# --- Background Metrics Collector ---
def _collect_container_metrics(container):
    """Aggregated status check to minimize Docker exec overhead."""
    try:
        if not container.name.startswith("duckstation-"): 
            return None
            
        session_id = container.name.replace("duckstation-", "")
        
        container.reload()
        if container.status != "running":
            return (session_id, {"status": "stopped", "reason": "Container not running"})

        # Aggregated heartbeat check
        cmd = ("pgrep -f duckstation-qt >/dev/null && echo -n 'P_OK|' || echo -n 'P_ERR|'; "
               "pgrep -x duckstation-qt >/dev/null && echo -n 'W_OK|' || echo -n 'W_ERR|'; "
               "cat /tmp/session_status 2>/dev/null || echo 'initializing'")
        
        hb_check = container.exec_run(f"sh -c \"{cmd}\"")
        
        is_proc_alive = False
        is_window_mapped = False
        status_marker = "initializing"
        
        if hb_check.exit_code == 0:
            raw_out = hb_check.output.decode('utf-8', errors='replace').strip()
            parts = raw_out.split('|')
            if len(parts) >= 3:
                is_proc_alive = (parts[0] == "P_OK")
                is_window_mapped = (parts[1] == "W_OK")
                status_marker = parts[2].strip().lower()
                if not status_marker: status_marker = "initializing"
        else:
            logger.debug(f"Heartbeat cmd failed for {session_id} (code {hb_check.exit_code})")

        # Resource Stats (Non-blocking if possible, but stream=False is already pretty fast)
        cpu_percent = 0.0
        mem_usage = 0.0
        try:
            stats = container.stats(stream=False)
            try:
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
                if system_delta > 0:
                    raw_percent = (cpu_delta / system_delta) * stats['cpu_stats'].get('online_cpus', 1) * 100.0
                    cpu_percent = (raw_percent / (CPUS_PER_SESSION or 1))
            except: pass
            mem_usage = round(stats['memory_stats'].get('usage', 0) / (1024 * 1024), 1)
        except Exception as stats_e:
            logger.debug(f"Stats fetch failed for {session_id}: {stats_e}")

        # Normalize status
        if "running_game" in status_marker: normalized_status = "running_game"
        elif "waiting" in status_marker: normalized_status = status_marker
        else: normalized_status = status_marker

        if normalized_status in ["stopped", "error"]:
            logger.info(f"Game exited, container {container.name} status is {normalized_status}. Terminating auto-session.")
            try:
                container.remove(force=True)
                return (session_id, {"status": "stopped", "reason": "Self-terminated after game exit", "metrics": {"container_status": "exited"}})
            except Exception as e:
                logger.error(f"Error self-terminating container {container.name}: {e}")

        return (session_id, {
            "session_id": session_id,
            "status": normalized_status,
            "memory_mb": mem_usage,
            "cpu_percent": round(cpu_percent, 2),
            "metrics": {
                "process_alive": is_proc_alive,
                "window_mapped": is_window_mapped,
                "cpu_usage_percent": round(cpu_percent, 2),
                "container_status": container.status
            }
        })
    except Exception as e:
        logger.error(f"FATAL Metrics collection failure for {container.name}: {e}", exc_info=True)
        return None

async def metrics_collector():
    """Background task to update session metrics without blocking the main event loop."""
    logger.info("🚀 Background Metrics Collector Started")
    loop = asyncio.get_event_loop()
    
    while True:
        try:
            # 1. Non-blocking list of candidate containers
            containers = await loop.run_in_executor(None, lambda: client.containers.list(filters={"label": "traefik.enable=true"}))
            
            if containers:
                logger.info(f"📊 Heartbeat: Checking {len(containers)} containers...")
            
            # 2. Collect metrics IN PARALLEL
            tasks = [loop.run_in_executor(None, _collect_container_metrics, c) for c in containers]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            running_ids = []
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    logger.error(f"❌ Worker error for container {containers[i].name}: {res}")
                    continue
                if res:
                    sid, data = res
                    metrics_cache[sid] = data
                    running_ids.append(sid)
            
            # 3. Precise Cleanup
            old_keys = list(metrics_cache.keys())
            for sid in old_keys:
                if sid not in running_ids:
                    logger.info(f"🧹 Cleaning up stale session {sid} from cache")
                    del metrics_cache[sid]

            # Global Host Metrics (Fast enough to keep, but still run in executor)
            def _get_host_metrics():
                try:
                    load1, _, _ = os.getloadavg()
                    host_metrics["cpu"] = round((load1 / (os.cpu_count() or 1)) * 100, 1)
                    with open('/proc/meminfo', 'r') as f:
                        m_lines = f.readlines()
                        m_total_line = next((l for l in m_lines if l.startswith('MemTotal:')), None)
                        m_avail_line = next((l for l in m_lines if l.startswith('MemAvailable:')), None)
                        if m_total_line and m_avail_line:
                            m_total = int(m_total_line.split()[1])
                            m_avail = int(m_avail_line.split()[1])
                            host_metrics["ram"] = round((1 - (m_avail / m_total)) * 100, 1)
                except: pass
            
            await loop.run_in_executor(None, _get_host_metrics)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Metrics collection loop error: {e}")
        
        await asyncio.sleep(4) # Slight increase in sleep to further reduce load


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(metrics_collector())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Shared Configuration Loader ---
def load_app_config():
    """Reloads configuration from config.env and updates global variables."""
    # We use global keyword to update the module-level variables
    global ROM_DIR, BIOS_DIR, NETWORK_NAME, IMAGE_NAME, ROM_CACHE_DIR, DOMAIN
    global SNES_ROM_DIR, GBA_ROM_DIR
    global CPUS_PER_SESSION, ROM_CACHE_MAX_MB, COVERS_DIR, MEM_LIMIT_PER_SESSION
    global MAX_HOST_CPU_PERCENT, MAX_HOST_MEM_PERCENT, RATE_LIMIT_SESSIONS_PER_MIN
    global ENABLE_DEBUG_MODE
    global HOST_ROM_DIR, HOST_BIOS_DIR, HOST_CACHE_DIR
    global ENABLED_PLATFORMS

    load_dotenv(CONFIG_ENV_PATH, override=True)
    
    ENABLE_DEBUG_MODE = os.getenv("ENABLE_DEBUG_MODE", "false").lower() == "true"
    ROM_DIR = os.getenv("ROM_DIR", "/roms")
    SNES_ROM_DIR = os.getenv("SNES_ROM_DIR", "/roms_snes")
    GBA_ROM_DIR = os.getenv("GBA_ROM_DIR", "/roms_gba")
    BIOS_DIR = os.getenv("BIOS_DIR", "/bios")
    NETWORK_NAME = os.getenv("NETWORK_NAME", "emulator-net")
    IMAGE_NAME = os.getenv("IMAGE_NAME", "custom-duckstation")
    ROM_CACHE_DIR = os.getenv("ROM_CACHE_DIR", "/cache")
    DOMAIN = os.getenv("DOMAIN_REMOTE", "localhost")
    CPUS_PER_SESSION = float(os.getenv("CPUS_PER_SESSION", "2.0"))
    ROM_CACHE_MAX_MB = int(os.getenv("ROM_CACHE_MAX_MB", "5000"))
    COVERS_DIR = os.getenv("COVERS_DIR", "/app/userdata/covers")
    MEM_LIMIT_PER_SESSION = os.getenv("MEM_LIMIT_PER_SESSION", "2g")
    MAX_HOST_CPU_PERCENT = int(os.getenv("MAX_HOST_CPU_PERCENT", "90"))
    MAX_HOST_MEM_PERCENT = int(os.getenv("MAX_HOST_MEM_PERCENT", "90"))
    RATE_LIMIT_SESSIONS_PER_MIN = int(os.getenv("RATE_LIMIT_SESSIONS_PER_MIN", "3"))

    # Path Translation (What Docker Host actually sees)
    HOST_ROM_DIR = os.getenv("HOST_ROM_DIR", ROM_DIR)
    HOST_BIOS_DIR = os.getenv("HOST_BIOS_DIR", BIOS_DIR)
    HOST_CACHE_DIR = os.getenv("HOST_CACHE_DIR", ROM_CACHE_DIR)

    # Platform Availability
    raw_platforms = os.getenv("ENABLED_PLATFORMS", ",".join(PLATFORM_REGISTRY.keys()))
    ENABLED_PLATFORMS = {
        p.strip().lower() for p in raw_platforms.split(",")
        if p.strip().lower() in PLATFORM_REGISTRY
    }
    if not ENABLED_PLATFORMS:
        logger.warning("ENABLED_PLATFORMS is empty or invalid — defaulting to all platforms.")
        ENABLED_PLATFORMS = set(PLATFORM_REGISTRY.keys())
    logger.info(f"Enabled platforms: {sorted(ENABLED_PLATFORMS)}")

# Initial load
load_app_config()

# --- Safety & Monitoring ---
rate_limit_data = defaultdict(list)

def is_rate_limited(client_id: str) -> bool:
    if not client_id: return False
    now = time.time()
    # Clean up old timestamps (older than 60s)
    rate_limit_data[client_id] = [t for t in rate_limit_data[client_id] if now - t < 60]
    if len(rate_limit_data[client_id]) >= RATE_LIMIT_SESSIONS_PER_MIN:
        return True
    rate_limit_data[client_id].append(now)
    return False

def check_host_resources():
    """Checks if the host system has enough CPU and RAM to start a new session."""
    # 1. CPU Load (1min average / core count)
    try:
        load1, _, _ = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        load_percent = (load1 / cpu_count) * 100
        if load_percent > MAX_HOST_CPU_PERCENT:
            return False, f"Server CPU load too high ({load_percent:.1f}%)"
    except: pass

    # 2. RAM Usage (parsing /proc/meminfo)
    try:
        with open('/proc/meminfo', 'r') as f:
            lines = f.readlines()
            mem_total = int(next(l for l in lines if l.startswith('MemTotal:')).split()[1])
            mem_avail = int(next(l for l in lines if l.startswith('MemAvailable:')).split()[1])
            mem_usage = (1 - (mem_avail / mem_total)) * 100
            if mem_usage > MAX_HOST_MEM_PERCENT:
                return False, f"Server memory usage too high ({mem_usage:.1f}%)"
    except: pass
    
    return True, "OK"

# --- Initialization Checks ---
def verify_paths():
    """
    Stricter path validation to ensure the engine doesn't start with 'Ghost' empty mounts.
    """
    load_app_config()
    
    # 1. Check ROM_DIR (Mandatory populated)
    if not os.path.exists(ROM_DIR):
        logger.error(f"❌ CRITICAL ERROR: ROM_DIR '{ROM_DIR}' does not exist!")
        logger.error("   If this is a network mount, please ensure it is connected before starting.")
        sys.exit(1)
    
    # Removed zip file check as per user request to not fail when a path simply has no zip files

    # 2. Check BIOS_DIR (Mandatory populated)
    if not os.path.exists(BIOS_DIR):
        logger.error(f"❌ CRITICAL ERROR: BIOS_DIR '{BIOS_DIR}' does not exist!")
        sys.exit(1)
    
    bios_files = glob.glob(os.path.join(BIOS_DIR, "*.bin"))
    if not bios_files:
         logger.warning(f"⚠️  WARNING: No .bin BIOS files found in {BIOS_DIR}. Games will likely fail to boot.")

    # 3. Check/Create Cache & Covers (Safe to create if missing)
    for name, path in {"ROM_CACHE_DIR": ROM_CACHE_DIR, "COVERS_DIR": COVERS_DIR}.items():
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
                logger.info(f"📁 Created local directory: {path}")
            except Exception as e:
                logger.error(f"❌ ERROR: Could not create {name} at {path}: {e}")
                sys.exit(1)

    for name, path in {"SNES_ROM_DIR": SNES_ROM_DIR, "GBA_ROM_DIR": GBA_ROM_DIR}.items():
        if not os.path.exists(path):
            try: os.makedirs(path, exist_ok=True)
            except: pass

verify_paths()

# --- ROM Cache Helpers ---
def _safe_cache_key(filename: str) -> str:
    name = os.path.splitext(filename)[0]
    return re.sub(r'[^a-zA-Z0-9]+', '_', name).strip('_').lower()

def _get_cache_size_mb() -> int:
    total_size = 0
    for root, dirs, files in os.walk(ROM_CACHE_DIR):
        for f in files: total_size += os.path.getsize(os.path.join(root, f))
    return int(total_size / (1024 * 1024))

def _identify_disc_set(filename: str) -> str:
    """Checks if filename is part of a multi-disc set. Returns the base name."""
    # Match patterns like: "Metal Gear Solid (Disc 1).zip" -> "Metal Gear Solid"
    match = re.search(r"(.*?)\s*\(Disc\s*\d+\)", filename, re.IGNORECASE)
    if match: return match.group(1).strip()
    return filename

def find_disc_siblings(filename: str) -> list[str]:
    """Finds all .zip siblings belonging to the same disc set."""
    base_name = _identify_disc_set(filename)
    if base_name == filename: return [filename]
    
    siblings = []
    for f in os.listdir(ROM_DIR):
        if f.lower().endswith(".zip") and base_name.lower() in f.lower():
            siblings.append(f)
    siblings.sort()
    return siblings

def get_or_extract_rom_set(filenames: list[str]) -> str | None:
    """Extracts a set of ROMs (multiple discs) into a single cache dir. Caller must handle locking."""
    if ROM_CACHE_MAX_MB <= 0: return None
    
    # Use the base name of the first file as the cache key
    cache_key = _safe_cache_key(_identify_disc_set(filenames[0]))
    cache_dir = os.path.join(ROM_CACHE_DIR, cache_key)
    done_marker = os.path.join(cache_dir, ".extracted_all")
    _ensure_cache_dir()
    lock_file_path = os.path.join(ROM_CACHE_DIR, f"{cache_key}.lock")

    try:
        if os.path.isfile(done_marker):
            # Integrity check: verify at least one game file exists, not just the marker.
            game_files = (
                glob.glob(os.path.join(cache_dir, "**/*.cue"), recursive=True) +
                glob.glob(os.path.join(cache_dir, "**/*.iso"), recursive=True) +
                glob.glob(os.path.join(cache_dir, "**/*.bin"), recursive=True)
            )
            if game_files:
                return cache_dir
            logger.warning(f"Cache dir {cache_dir} has marker but no game files. Re-extracting.")
            os.remove(done_marker)
        
        shutil.rmtree(cache_dir, ignore_errors=True)
        os.makedirs(cache_dir, exist_ok=True)
        
        def _extract_single(fname):
            zip_path = os.path.join(ROM_DIR, fname)
            logger.info(f"Extracting part of set: {fname}...")
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(cache_dir)
        
        # Extract all discs in parallel (each disc has uniquely named files)
        with ThreadPoolExecutor(max_workers=min(len(filenames), 4)) as executor:
            list(executor.map(_extract_single, filenames))
        
        subprocess.run(["chmod", "-R", "755", cache_dir], timeout=10)
        open(done_marker, 'w').close()
        return cache_dir
    except Exception as e:
        logger.error(f"Extraction error: {e}", exc_info=True)
        return None

def _ensure_cache_dir():
    os.makedirs(ROM_CACHE_DIR, exist_ok=True)

# Removed single get_or_extract_rom in favor of set handler above

class SessionRequest(BaseModel):
    game_filename: str
    client_id: str | None = None
    platform: str = "ps1"

class StopRequest(BaseModel):
    client_id: str

@app.post("/api/start-session")
async def start_session(request: SessionRequest):
    loop = asyncio.get_event_loop()
    # 1. Rate Limiting (Prevent spamming the start button)
    if is_rate_limited(request.client_id):
        raise HTTPException(status_code=429, detail="Too many launch requests. Please wait a minute.")

    # 2. Platform Availability Check
    if request.platform not in ENABLED_PLATFORMS:
        raise HTTPException(
            status_code=403,
            detail=f"Platform '{request.platform}' is not available on this server. "
                   f"Available: {sorted(ENABLED_PLATFORMS)}"
        )

    # 2. Host Health Check (Safety Valve)
    is_healthy, reason = check_host_resources()
    if not is_healthy:
        raise HTTPException(status_code=503, detail=f"Server overloaded: {reason}")

    if request.client_id:
        existing_containers = await loop.run_in_executor(None, lambda: client.containers.list(filters={"label": f"owner={request.client_id}"}))
        if existing_containers:
            existing = existing_containers[0]
            logger.info(f"Found existing container {existing.name} for client {request.client_id}")
            env = existing.attrs['Config']['Env']
            current_game_rom = next((s for s in env if s.startswith("GAME_ROM=")), "").split("=", 1)[1]
            
            clean_filename = os.path.splitext(request.game_filename)[0]
            if clean_filename.lower() in current_game_rom.lower():
                logger.info(f"Existing container {existing.name} matches game. Reusing.")
                try:
                    # Check if actually alive
                    hb = await loop.run_in_executor(None, _collect_container_metrics, existing)
                    if hb and hb[1].get("status") != "stopped":
                        session_id = existing.name.replace("duckstation-", "")
                        vnc_pw = next((s for s in env if s.startswith("VNC_PW=")), "").split("=", 1)[1]
                        return {"session_id": session_id, "url_path": f"/{session_id}/", "username": "player", "password": vnc_pw}
                    else:
                        logger.warning(f"Existing container {existing.name} found but status is dead. Removing.")
                        existing.remove(force=True)
                except Exception as e:
                    logger.warning(f"Error checking existing container: {e}. Removing.")
                    try: existing.remove(force=True)
                    except: pass
            else:
                logger.info(f"Existing container {existing.name} is for a different game. Removing to switch.")
                try:
                    existing.remove(force=True)
                    for _ in range(20):
                        try:
                            client.containers.get(existing.id)
                            await asyncio.sleep(0.5)
                        except docker.errors.NotFound: 
                            logger.info("Old container removal confirmed.")
                            break
                except Exception as e:
                    logger.error(f"Error removing old container: {e}")

    session_id = str(uuid.uuid4())[:8]

    # Universal Enforce 1: If it's a WASM platform, immediately return static route after killing container
    if request.platform != "ps1":
        logger.info(f"Creating WASM session for {request.platform}: {request.game_filename}")
        encoded_rom = urllib.parse.quote(request.game_filename)
        return {
            "session_id": session_id, 
            "url_path": f"/emulator.html?core={request.platform}&rom=/rom-files/{request.platform}/{encoded_rom}", 
            "username": "player", 
            "password": "",
            "platform": request.platform
        }

    logger.info(f"Creating new Docker session {session_id} for game {request.game_filename}")
    password = secrets.token_urlsafe(8)
    mounts = []
    scale = int(os.getenv("RESOLUTION_SCALE", "1"))
    stream_quality = int(os.getenv("STREAM_QUALITY", "50"))
    h264_crf = 50 - int((stream_quality / 100) * 45)  # quality 1-100 → CRF 50-5 (lower CRF = better)
    if scale <= 1:
        renderer, filtering, pgxp_geo, pgxp_tex, true_color, display_w, display_h = "Software", "0", "false", "false", "false", 1024, 768
    elif scale == 2:
        renderer, filtering, pgxp_geo, pgxp_tex, true_color, display_w, display_h = "Vulkan", "1", "true", "true", "true", 1024, 768
    else:
        renderer, filtering, pgxp_geo, pgxp_tex, true_color, display_w, display_h = "Vulkan", "3", "true", "true", "true", 1280, 1024

    logger.debug(f"Preparing container config for session {session_id}")
    env_vars = {
        "VNC_PW": password, "PUID": "1000", "PGID": "1000", "TZ": "Etc/UTC", "LIBGL_ALWAYS_SOFTWARE": "1",
        "RENDERER": renderer, "RESOLUTION_SCALE": str(scale), "TEXTURE_FILTERING": filtering, "TRUE_COLOR": true_color,
        "PGXP_GEOMETRY": pgxp_geo, "PGXP_TEXTURE": pgxp_tex, "VSYNC": "false", "AUDIO_BACKEND": os.getenv("AUDIO_BACKEND", "Cubeb"),
        "SELKIES_MANUAL_WIDTH": str(display_w), "SELKIES_MANUAL_HEIGHT": str(display_h),
        "MAX_RES": f"{display_w}x{display_h}",
        "SELKIES_VIDEO_BITRATE": os.getenv("STREAM_BITRATE", "2000"), "SELKIES_VIDEO_FRAMERATE": os.getenv("STREAM_FRAMERATE", "30"),
        "SELKIES_H264_CRF": str(h264_crf),
        "SELKIES_AUDIO_BITRATE": "320000",
        "SHOW_FPS": os.getenv("SHOW_FPS", "false"),
        "GAME_NAME": _identify_disc_set(request.game_filename).replace(".zip", "").replace(".ZIP", ""),
        # Security & Hardening Overrides
        "HARDEN_DESKTOP": "true", "DISABLE_OPEN_TOOLS": "true", "DISABLE_SUDO": "true", 
        "DISABLE_TERMINALS": "true", "DISABLE_CLOSE_BUTTON": "true", "DISABLE_MOUSE_BUTTONS": "true",
        "HARDEN_KEYBINDS": "true", "SELKIES_COMMAND_ENABLED": "False", 
        "SELKIES_UI_SIDEBAR_SHOW_FILES": "False", "SELKIES_UI_SIDEBAR_SHOW_APPS": "False",
        "SELKIES_FILE_TRANSFERS": ""
    }


    if request.game_filename == "DEBUG_MODE_FULL_ACCESS":
        if not ENABLE_DEBUG_MODE: raise HTTPException(status_code=403, detail="Debug Mode disabled")
        mounts.append(docker.types.Mount(target="/roms", source=HOST_ROM_DIR, type="bind", read_only=True))
        env_vars["GAME_ROM"] = ""
    else:
        if not request.game_filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip supported")
        safe_name = os.path.basename(request.game_filename)
        if safe_name != request.game_filename or ".." in request.game_filename:
            raise HTTPException(status_code=400, detail="Invalid filename: path traversal detected")

        # --- Smart Multi-Disc Detection & Extraction ---
        disc_siblings = await loop.run_in_executor(None, find_disc_siblings, request.game_filename)
        
        # Use simple global lock to prevent race conditions during extraction and startup
        cache_key = _safe_cache_key(_identify_disc_set(disc_siblings[0]))
        lock_file_path = os.path.join(ROM_CACHE_DIR, f"{cache_key}.lock")
        os.makedirs(ROM_CACHE_DIR, exist_ok=True)

        # Signal extraction progress immediately so the polling client sees feedback
        metrics_cache[session_id] = {"session_id": session_id, "status": "extracting_rom", "message": "Extracting ROM to cache..."}

        with open(lock_file_path, 'w') as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                # RE-CHECK: Now that we have the lock, check if another thread already started the container
                if request.client_id:
                    existing = await loop.run_in_executor(None, lambda: client.containers.list(filters={"label": f"owner={request.client_id}"}))
                    if existing:
                        c = existing[0]
                        env = c.attrs['Config']['Env']
                        vnc_pw = next((s for s in env if s.startswith("VNC_PW=")), "").split("=", 1)[1]
                        return {"session_id": c.name.replace("duckstation-", ""), "url_path": f"/{c.name.replace('duckstation-', '')}/", "username": "player", "password": vnc_pw}

                cached_dir = await loop.run_in_executor(None, get_or_extract_rom_set, disc_siblings)
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
        
        if cached_dir:
            host_cached_dir = os.path.join(HOST_CACHE_DIR, cache_key)
            mounts.append(docker.types.Mount(target="/roms", source=host_cached_dir, type="bind", read_only=True))
            
            # Find all cues in the set
            cues = glob.glob(os.path.join(cached_dir, "**/*.cue"), recursive=True)
            cues.sort() # Disc 1 should come first
            
            if len(cues) > 1:
                # Generate M3U playlist for live disc swapping
                m3u_path = os.path.join(cached_dir, "playlist.m3u")
                with open(m3u_path, "w") as f:
                    for cue in cues:
                        f.write(os.path.relpath(cue, cached_dir) + "\n")
                
                env_vars["GAME_ROM"] = "/roms/playlist.m3u"
                env_vars["ROM_PRECACHED"] = "true"
                logger.info(f"Multi-disc set detected: {len(cues)} discs bound via playlist.m3u")
            elif cues:
                env_vars["GAME_ROM"] = f"/roms/{os.path.relpath(cues[0], cached_dir)}"
                env_vars["ROM_PRECACHED"] = "true"
            else:
                # Fallback to iso or bin if no cue
                other = glob.glob(os.path.join(cached_dir, "**/*.iso"), recursive=True) or glob.glob(os.path.join(cached_dir, "**/*.bin"), recursive=True)
                if other:
                    env_vars["GAME_ROM"] = f"/roms/{os.path.relpath(other[0], cached_dir)}"
                    env_vars["ROM_PRECACHED"] = "true"
                else: env_vars["GAME_ROM"] = ""
        else:
            host_rom_path = os.path.join(HOST_ROM_DIR, request.game_filename)
            mounts.append(docker.types.Mount(target="/roms/game.zip", source=host_rom_path, type="bind", read_only=True))
            env_vars["GAME_ROM"] = "/roms/game.zip"

    mounts.extend([
        docker.types.Mount(target="/config/.local/share/duckstation/bios", source=HOST_BIOS_DIR, type="bind", read_only=True),
        docker.types.Mount(target="/dev/uinput", source="/dev/uinput", type="bind", read_only=False)
    ])
    
    try:
        def _run_container():
            logger.info(f"Triggering docker run for {session_id}")
            c = client.containers.run(
                image=IMAGE_NAME, detach=True, network=NETWORK_NAME, name=f"duckstation-{session_id}",
                extra_hosts={"api.github.com": "0.0.0.0", "github.com": "0.0.0.0"},
                environment=env_vars, mounts=mounts, nano_cpus=int(CPUS_PER_SESSION * 1e9),
                mem_limit=MEM_LIMIT_PER_SESSION, shm_size="1gb",
                labels={
                    "traefik.enable": "true", "owner": request.client_id if request.client_id else "anonymous",
                    f"traefik.http.routers.{session_id}.rule": f"PathPrefix(`/{session_id}/`)",
                    f"traefik.http.services.{session_id}.loadbalancer.server.port": "3000",
                    f"traefik.http.routers.{session_id}.entrypoints": "web,websecure",
                    f"traefik.http.routers.{session_id}.tls": "true",
                    f"traefik.http.middlewares.{session_id}-strip.stripprefix.prefixes": f"/{session_id}/",
                    f"traefik.http.routers.{session_id}.middlewares": f"{session_id}-strip",
                    f"traefik.http.routers.{session_id}.priority": "100"
                },
                devices=["/dev/uinput:/dev/uinput:rwm", "/dev/dri:/dev/dri:rwm"] if os.path.exists("/dev/dri") else ["/dev/uinput:/dev/uinput:rwm"]
            )
            logger.info(f"Container created successfully: {c.id[:12]}")
            return c
        
        container = await loop.run_in_executor(None, _run_container)
        return {"session_id": session_id, "url_path": f"/{session_id}/", "username": "player", "password": password}
    except Exception as e:
        logging.error(f"FATAL start_session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/session-status/{session_id}")
def get_session_status(session_id: str, client_id: str):
    try:
        container = client.containers.get(f"duckstation-{session_id}")
        if container.labels.get("owner") != client_id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this session")
        
        if session_id in metrics_cache: return metrics_cache[session_id]
        return {"session_id": session_id, "status": "initializing", "message": "Collecting metrics..."}
    except docker.errors.NotFound:
        return {"session_id": session_id, "status": "not_found"}
    except HTTPException: raise
    except Exception as e:
        return {"session_id": session_id, "status": "error", "message": str(e)}

@app.get("/api/active-sessions/{client_id}")
def get_active_sessions(client_id: str):
    try:
        containers = client.containers.list(filters={"label": f"owner={client_id}"})
        sessions = []
        for c in containers:
            session_id = c.name.replace("duckstation-", "")
            env = c.attrs['Config']['Env']
            game_name = next((s for s in env if s.startswith("GAME_NAME=")), "").split("=", 1)[1]
            if not game_name:
                game_path = next((s for s in env if s.startswith("GAME_ROM=")), "").split("=", 1)[1]
                game_name = os.path.basename(game_path)
            sessions.append({"session_id": session_id, "game_name": game_name, "url_path": f"/{session_id}/", "status": c.status})
        return sessions
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stop-session/{session_id}")
async def stop_session(session_id: str, request: StopRequest):
    client_id = request.client_id
    if not client_id: raise HTTPException(status_code=400, detail="client_id required")
    loop = asyncio.get_event_loop()
    try:
        container = await loop.run_in_executor(None, lambda: client.containers.get(f"duckstation-{session_id}"))
        if container.labels.get("owner") != client_id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this session")

        await loop.run_in_executor(None, lambda: container.remove(force=True))

        # Wait for actual removal without blocking the event loop
        for _ in range(10):
            try:
                await loop.run_in_executor(None, lambda: client.containers.get(f"duckstation-{session_id}"))
                await asyncio.sleep(0.5)
            except docker.errors.NotFound:
                break
        return {"status": "success"}
    except docker.errors.NotFound:
        return {"status": "already_gone"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"FATAL stop_session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/sessions")
def admin_list_sessions():
    try:
        containers = client.containers.list(filters={"label": "traefik.enable=true"})
        sessions = []
        for c in containers:
            if not c.name.startswith("duckstation-"): continue
            session_id = c.name.replace("duckstation-", "")
            env = c.attrs['Config']['Env']
            game_name = next((s for s in env if s.startswith("GAME_NAME=")), "").split("=", 1)[1]
            if not game_name:
                game_path = next((s for s in env if s.startswith("GAME_ROM=")), "").split("=", 1)[1]
                game_name = os.path.basename(game_path)
            owner = c.labels.get("owner", "anonymous")
            # Use cached metrics if available
            cached = metrics_cache.get(session_id, {})
            sessions.append({
                "session_id": session_id, 
                "game_name": game_name, 
                "owner": owner, 
                "status": c.status,
                "cpu_percent": cached.get("cpu_percent", 0),
                "memory_mb": cached.get("memory_mb", 0)
            })
        return {
            "sessions": sessions,
            "host": host_metrics
        }
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/stop-session/{session_id}")
async def admin_stop_session(session_id: str):
    loop = asyncio.get_event_loop()
    try:
        container = await loop.run_in_executor(None, lambda: client.containers.get(f"duckstation-{session_id}"))
        await loop.run_in_executor(None, lambda: container.remove(force=True))
        # Wait for removal without blocking
        for _ in range(10):
            try:
                await loop.run_in_executor(None, lambda: client.containers.get(f"duckstation-{session_id}"))
                await asyncio.sleep(0.5)
            except docker.errors.NotFound:
                break
        return {"status": "success"}
    except docker.errors.NotFound:
        return {"status": "already_gone"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/rom-art/{game_id}")
async def get_rom_art(game_id: str):
    local_path = os.path.join(COVERS_DIR, f"{game_id}.png")
    # 30 days cache = 30 * 24 * 60 * 60
    cache_headers = {"Cache-Control": "public, max-age=2592000"}
    
    if os.path.exists(local_path):
        return FileResponse(local_path, headers=cache_headers)
    
    def _fetch_cover():
        """Blocking cover art lookup + download, run in executor to avoid blocking event loop."""
        target_name = None
        platform = "ps1"
        
        # 1. Try PS1
        all_zips = glob.glob(os.path.join(ROM_DIR, "*.zip"))
        for f in all_zips:
            if _safe_cache_key(_identify_disc_set(os.path.basename(f))) == game_id:
                target_name = _identify_disc_set(os.path.basename(f)).replace(".zip", "").replace(".ZIP", "")
                platform = "ps1"
                break
                
        # 2. Try SNES
        if not target_name:
            for f in glob.glob(os.path.join(SNES_ROM_DIR, "*.zip")):
                name = os.path.basename(f)
                s_name = os.path.splitext(name)[0]
                if _safe_cache_key(s_name) == game_id:
                    target_name = s_name
                    platform = "snes"
                    break
                    
        # 3. Try GBA
        if not target_name:
            for f in glob.glob(os.path.join(GBA_ROM_DIR, "*.zip")):
                name = os.path.basename(f)
                g_name = os.path.splitext(name)[0]
                if _safe_cache_key(g_name) == game_id:
                    target_name = g_name
                    platform = "gba"
                    break
        
        if not target_name:
            return None
            
        # Libretro replacement rules: &*/:<>?\| -> _
        libretro_name = target_name
        for char in "&*/:<>?\\|":
            libretro_name = libretro_name.replace(char, "_")
        
        repo_map = {
            "ps1": "Sony_-_PlayStation",
            "snes": "Nintendo_-_Super_Nintendo_Entertainment_System",
            "gba": "Nintendo_-_Game_Boy_Advance"
        }
        repo = repo_map[platform]
        
        remote_url = f"https://raw.githubusercontent.com/libretro-thumbnails/{repo}/master/Named_Boxarts/{libretro_name}.png"
        
        resp = requests.get(remote_url, timeout=5, stream=True)
        if resp.status_code == 200:
            with open(local_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return local_path
        return None
    
    # Run blocking I/O in executor to avoid blocking the event loop
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _fetch_cover)
        if result:
            return FileResponse(local_path, headers=cache_headers)
    except Exception as e:
        logger.warning(f"Cover fetch error for {game_id}: {e}")

    # Fallback to a styled SVG placeholder
    clean_name = game_id.replace('_', ' ').upper()
    if len(clean_name) > 25: clean_name = clean_name[:22] + '...'
    
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400" viewBox="0 0 300 400">
        <rect width="100%" height="100%" fill="#1e1e2e"/>
        <text x="50%" y="50%" font-family="sans-serif" font-size="18" fill="#cdd6f4" text-anchor="middle" dominant-baseline="middle" font-weight="bold">
            {clean_name}
        </text>
    </svg>"""
    return Response(content=svg, media_type="image/svg+xml", headers=cache_headers)

@app.get("/admin")
def get_admin_page():
    return FileResponse("static/admin.html")

@app.get("/api/roms")
async def list_roms():
    debug_enabled = ENABLE_DEBUG_MODE
    loop = asyncio.get_event_loop()

    # Only glob directories for enabled platforms (avoids I/O on disabled ones)
    glob_futures: dict[str, asyncio.Future] = {}
    if "ps1" in ENABLED_PLATFORMS:
        glob_futures["ps1"] = loop.run_in_executor(None, lambda: glob.glob(os.path.join(ROM_DIR, "*.zip")))
    if "snes" in ENABLED_PLATFORMS:
        glob_futures["snes"] = loop.run_in_executor(None, lambda: glob.glob(os.path.join(SNES_ROM_DIR, "*.zip")))
    if "gba" in ENABLED_PLATFORMS:
        glob_futures["gba"] = loop.run_in_executor(None, lambda: glob.glob(os.path.join(GBA_ROM_DIR, "*.zip")))

    glob_results: dict[str, list] = {}
    if glob_futures:
        keys = list(glob_futures.keys())
        values = await asyncio.gather(*glob_futures.values())
        glob_results = dict(zip(keys, values))

    all_zips   = glob_results.get("ps1",  [])
    snes_zips  = glob_results.get("snes", [])
    gba_zips   = glob_results.get("gba",  [])

    seen_sets = set()
    rom_data = []

    for f_path in sorted(all_zips):
        filename = os.path.basename(f_path)
        base_name = _identify_disc_set(filename)
        clean_name = base_name.replace(".zip", "").replace(".ZIP", "")

        if clean_name in seen_sets:
            continue

        seen_sets.add(clean_name)
        game_id = _safe_cache_key(base_name)

        rom_data.append({
            "filename": filename,
            "display_name": clean_name,
            "game_id": game_id,
            "poster_url": f"/api/rom-art/{game_id}",
            "platform": "ps1"
        })

    snes_roms, gba_roms = [], []
    for f_path in snes_zips:
        if f_path.lower().endswith('.zip'):
            name = os.path.basename(f_path)
            s_name = os.path.splitext(name)[0]
            snes_roms.append({"filename": name, "display_name": s_name, "game_id": _safe_cache_key(s_name), "poster_url": f"/api/rom-art/{_safe_cache_key(s_name)}", "platform": "snes"})

    for f_path in gba_zips:
        if f_path.lower().endswith('.zip'):
            name = os.path.basename(f_path)
            g_name = os.path.splitext(name)[0]
            gba_roms.append({"filename": name, "display_name": g_name, "game_id": _safe_cache_key(g_name), "poster_url": f"/api/rom-art/{_safe_cache_key(g_name)}", "platform": "gba"})

    if debug_enabled:
        rom_data.insert(0, {
            "filename": "DEBUG_MODE_FULL_ACCESS",
            "display_name": "DEBUG_MODE_FULL_ACCESS",
            "game_id": "debug",
            "poster_url": "",
            "platform": "ps1"
        })

    return {
        "ps1":  rom_data,
        "snes": sorted(snes_roms, key=lambda x: x['display_name']),
        "gba":  sorted(gba_roms,  key=lambda x: x['display_name']),
        # Frontend can check this to know which tabs/sections to render
        "enabled_platforms": sorted(ENABLED_PLATFORMS),
    }

# Initialize static mounts safely outside
if os.path.exists(SNES_ROM_DIR):
    app.mount("/rom-files/snes", StaticFiles(directory=SNES_ROM_DIR), name="roms_snes")
if os.path.exists(GBA_ROM_DIR):
    app.mount("/rom-files/gba", StaticFiles(directory=GBA_ROM_DIR), name="roms_gba")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
