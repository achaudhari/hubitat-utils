# Unified Dockerfile for Hubitat Services (Offload and Event Daemons)
# Base image: Debian 13 (trixie) for aarch64
FROM debian:trixie-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# Install system dependencies, create user, install Python packages, and configure directories
# Note: Using Debian packages where possible to ensure aarch64 compatibility
RUN apt-get update && apt-get install -y \
    msmtp \
    msmtp-mta \
    openssh-client \
    sudo \
    procps \
    net-tools \
    iproute2 \
    iputils-ping \
    curl \
    ca-certificates \
    openssl \
    wget \
    gnupg \
    # Python & packages from Debian repos
    python3 \
    python3-typing-extensions \
    python3-waitress \
    python3-werkzeug \
    python3-requests \
    python3-dominate \
    python3-pytz \
    python3-jsonrpc \
    python3-influxdb \
    # python3-numpy \
    # python3-opencv \
    # python3-paho-mqtt \
    # python3-pil \
    # python3-aiohttp \
    && apt-get clean \
    && apt-get autoremove \
    && rm -rf /var/lib/apt/lists/*

# Create admin user with sudo access for reboot/shutdown
RUN useradd -m -s /bin/bash admin \
    # Create required directories \
    && mkdir -p /etc/hauto /opt/hauto /var/hauto \
    && chown -R admin:admin /etc/hauto /opt/hauto /var/hauto \
    && chmod -R 755 /etc/hauto /opt/hauto /var/hauto

# Default to admin
USER admin

# Set entrypoint
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
