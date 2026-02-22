import docker
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load config
load_dotenv(os.getenv("CONFIG_ENV_PATH", "config.env"))

# Initialize Docker client
client = docker.from_env()

# Dictionary to track inactivity start times: {container_id: datetime}
inactive_containers = {}

def check_activity(container):
    """
    Checks if there are active connections on port 3000 inside the container.
    Returns True if active, False otherwise.
    """
    try:
        # Use ss (always available) instead of netstat
        exit_code, output = container.exec_run("sh -c 'ss -tan | grep :3000 | grep ESTAB'")
        return exit_code == 0
    except Exception as e:
        print(f"Error checking activity for {container.name}: {e}")
        return False

def watchdog_loop():
    print("Starting Watchdog Service...")
    while True:
        try:
            # Only scan DuckStation containers, not Traefik or other infra
            containers = client.containers.list(
                filters={"network": "emulator-net", "ancestor": "custom-duckstation"}
            )
            current_time = datetime.now()
            running_ids = set()

            for container in containers:
                running_ids.add(container.id)

                # NEW: Grace period check (Ignore very new containers)
                # Parse Docker format: 2024-03-21T12:34:56.123456789Z
                created_str = container.attrs['Created'][:19]
                created_dt = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%S")
                uptime_seconds = (datetime.utcnow() - created_dt).total_seconds()
                
                if uptime_seconds < 120: # 2 minute grace period
                    continue

                is_active = check_activity(container)
                
                if is_active:
                    # If active, remove from inactivity tracker if present
                    if container.id in inactive_containers:
                        print(f"Container {container.name} is active. Resetting timer.")
                        del inactive_containers[container.id]
                else:
                    # If inactive, start tracking or check duration
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
                                # Remove from tracker
                                del inactive_containers[container.id]
                                # Also remove from running_ids locally to avoid cleaning up below (redundant but safe)
                                if container.id in running_ids:
                                    running_ids.remove(container.id)
                            except Exception as e:
                                print(f"Error removing {container.name}: {e}")

            # Cleanup tracker for containers that are no longer running (e.g. manually stopped)
            # Use list(inactive_containers.keys()) to avoid modification during iteration
            for cid in list(inactive_containers.keys()):
                if cid not in running_ids:
                    del inactive_containers[cid]

        except Exception as e:
            print(f"Watchdog main loop error: {e}")
        
        # Sleep for 60 seconds
        time.sleep(60)

if __name__ == "__main__":
    watchdog_loop()
