#!/bin/bash

echo "🛑 Stopping DuckStation Backend Services..."

# 1. Stop all DuckStation session containers
echo "🧹 Cleaning up DuckStation containers..."
CONTAINERS=$(docker ps -a -q --filter "name=duckstation-")
if [ -n "$CONTAINERS" ]; then
    docker rm -f $CONTAINERS
    echo "   ✅ Removed DuckStation container(s)."
fi

# 2. Stop core infrastructure services
echo "🌐 Stopping Core Infrastructure..."
docker-compose down --remove-orphans

# 3. Cleanup PID files and ROM locks
rm -f orchestrator.pid watchdog.pid
rm -f /tmp/ps1cache/*.lock 2>/dev/null
rm -rf /tmp/ps1cache/*.extracted 2>/dev/null # Optional: remove partial extractions

echo "👋 Services stopped."
