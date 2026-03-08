#!/bin/bash

# Ensure we are in the directory of the script
cd "$(dirname "$0")"

echo "🚀 Starting DuckStation Cloud Gaming Backend Setup..."

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker could not be found."
    echo "   Please run: sudo ./install_docker.sh"
    exit 1
fi

# Check for config.env
if [ ! -f "config.env" ]; then
    echo "❌ config.env not found! Creating from template..."
    if [ -f "config.env.example" ]; then
        cp config.env.example config.env
    else
        echo "❌ No template found. Please create config.env manually."
        exit 1
    fi
fi

echo "🔍 Validating docker-compose.yml..."
if ! docker compose config --quiet 2>/dev/null; then
    echo "❌ docker-compose.yml has errors. Run 'docker compose config' for details."
    exit 1
fi

# 1. Build the custom DuckStation image
echo "📦 Building custom DuckStation image (version: ${DUCKSTATION_VERSION:-latest})..."
docker build \
    --build-arg DUCKSTATION_VERSION=${DUCKSTATION_VERSION:-latest} \
    -t custom-duckstation \
    -f Dockerfile.duckstation .

if [ $? -ne 0 ]; then
    echo "❌ DuckStation build failed."
    exit 1
fi

# Load environment variables from .env if it exists
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# 2. Build and Start Infrastructure
echo "🌐 Starting Services via Docker Compose..."

# Ensure relevant local directories exist
mkdir -p ./userdata/covers
mkdir -p "${ROM_CACHE_DIR:-./userdata/cache}"

echo "📁 Cache path identified as: ${ROM_CACHE_DIR:-./userdata/cache}"

docker-compose up -d --build

if [ $? -ne 0 ]; then
    echo "❌ Docker Compose failed to start."
    exit 1
fi

# Wait for Traefik and Orchestrator
echo "   Waiting for services..."
sleep 5

echo ""
echo "🎉 System is running!"
echo "   - Remote domain: https://${DOMAIN_REMOTE:-your-domain.com}"
echo "   - Local domain:  https://${DOMAIN_LOCAL:-localhost}"
echo "   - Traefik Dash:  https://${DOMAIN_REMOTE:-your-domain.com}/dashboard/"
echo ""
echo "   To stop services, run: ./stop.sh"
echo "   To view logs, run: docker-compose logs -f"
echo ""

# Run smoke test to verify the stack is healthy
if [ -f "./smoke_test.sh" ]; then
    chmod +x ./smoke_test.sh
    echo "🧪 Running smoke test (waiting 30s for services to stabilize)..."
    sleep 30
    ./smoke_test.sh || echo "⚠️  Smoke test had failures — check logs above."
fi

