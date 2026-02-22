#!/bin/bash

# Ensure we are running with sudo/root privileges
if [ "$EUID" -ne 0 ]; then 
  echo "Please run as root or with sudo"
  exit 1
fi

echo "🐳 Installing Docker and Dependencies for Debian 13..."

# Update package lists
apt-get update

# Install Docker and Compose
apt-get install -y docker.io docker-compose python3-pip python3-venv curl

# Add current user (if running via sudo) to docker group
if [ -n "$SUDO_USER" ]; then
    usermod -aG docker "$SUDO_USER"
    echo "✅ Added user $SUDO_USER to docker group."
fi

# Enable and start Docker service
systemctl enable --now docker

echo "✅ Docker installation complete."
echo "⚠️  You may need to log out and back in for group changes to take effect."
