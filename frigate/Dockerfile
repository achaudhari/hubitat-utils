# Dockerfile for Frigate Manager
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install netcat and Python dependencies from system packages
RUN apt-get update \
    && apt-get install -y netcat-openbsd \
    && pip install --no-cache-dir pyyaml paho-mqtt \
    && rm -rf /var/lib/apt/lists/*

# Run the manager
CMD ["python3", "-u", "frigate_manager.py", "-c", "/etc/frigate-mgr.yml"]
