import docker
import os
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

# Load config
load_dotenv(os.getenv("CONFIG_ENV_PATH", "config.env"))

# Initialize Docker client
client = docker.from_env()

# Dictionary to track inactivity start times: {container_id: datetime}
inactive_containers = {}

def check_activity(container):
    """
    Checks if the session is active. Uses two signals:
    1. Established TCP connections on port 3000 (Selkies signalling).
    2. /tmp/session_status == RUNNING_GAME (covers UDP-only WebRTC streams where
       no TCP ESTAB connection exists but the emulator is actively streaming).
    Returns True if either signal indicates activity.
    """
    try:
        # Signal 1: TCP connections on the Selkies signalling port
        exit_code, _ = container.exec_run("sh -c 'ss -tan | grep :3000 | grep ESTAB'")
        if exit_code == 0:
            return True
        # Signal 2: Session status file written by launch_duck.py
        exit_code2, output2 = container.exec_run("sh -c 'cat /tmp/session_status 2>/dev/null'")
        if exit_code2 == 0 and output2:
            status = output2.decode("utf-8", errors="replace").strip()
            return status == "RUNNING_GAME"
        return False
    except Exception as e:
        print(f"Error checking activity for {container.name}: {e}")
        return False

def _check_single_container(container):
    """Worker function: returns (container, is_active, skip_reason) tuple. No dict mutations."""
    try:
        created_str = container.attrs['Created'][:19]
        created_dt = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        uptime_seconds = (datetime.now(timezone.utc) - created_dt).total_seconds()
        
        if uptime_seconds < 120:
            return (container, None, "grace_period")
        
        is_active = check_activity(container)
        return (container, is_active, None)
    except Exception as e:
        print(f"Error checking container {container.name}: {e}")
        return (container, False, None)

def watchdog_loop():
    print("Starting Watchdog Service...")
    while True:
        try:
            # Only scan DuckStation containers, not Traefik or other infra
            containers = client.containers.list(
                filters={"network": "emulator-net", "ancestor": "custom-duckstation"}
            )
            current_time = datetime.now(timezone.utc)
            running_ids = set()

            # Check all containers in parallel (each check involves a Docker exec round-trip)
            with ThreadPoolExecutor(max_workers=min(len(containers), 8) if containers else 1) as executor:
                results = list(executor.map(_check_single_container, containers))

            # Process results sequentially in main thread (safe dict mutations)
            for container, is_active, skip_reason in results:
                running_ids.add(container.id)

                if skip_reason == "grace_period":
                    continue

                if is_active:
                    if container.id in inactive_containers:
                        print(f"Container {container.name} is active. Resetting timer.")
                        del inactive_containers[container.id]
                else:
                    if container.id not in inactive_containers:
                        inactive_containers[container.id] = current_time
                        print(f"Container {container.name} inactive. Timer started.")
                    else:
                        elapsed = current_time - inactive_containers[container.id]
                        idle_limit = int(os.getenv("IDLE_TIMEOUT_MINS", "30"))
                        if elapsed > timedelta(minutes=idle_limit):
                            print(f"Container {container.name} inactive for > {idle_limit}m. Terminating.")
                            try:
                                container.remove(force=True)
                                print(f"Container {container.name} removed.")
                                del inactive_containers[container.id]
                                if container.id in running_ids:
                                    running_ids.remove(container.id)
                            except Exception as e:
                                print(f"Error removing {container.name}: {e}")

            # Cleanup tracker for containers that are no longer running
            for cid in list(inactive_containers.keys()):
                if cid not in running_ids:
                    del inactive_containers[cid]

        except Exception as e:
            print(f"Watchdog main loop error: {e}")
        
        # Sleep for 60 seconds
        time.sleep(60)

if __name__ == "__main__":
    watchdog_loop()
