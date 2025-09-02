FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Base OS packages and runtime dependencies (Firefox + geckodriver, networking, email, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ca-certificates \
    curl iputils-ping openssl openssh-client \
    firefox-esr geckodriver \
    msmtp-mta speedtest-cli dnsutils \
    # Firefox runtime libraries
    libgtk-3-0 libdbus-glib-1-2 libasound2 libx11-xcb1 libxtst6 libxrandr2 libxdamage1 libxcomposite1 \
    libxcursor1 libxi6 libxss1 libxfixes3 libnss3 libnspr4 libxkbcommon0 libatk1.0-0 libatk-bridge2.0-0 \
    libdrm2 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 libatspi2.0-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Create expected user and directory layout matching original host (/home/admin/src ...)
RUN useradd -ms /bin/bash admin
WORKDIR /home/admin/src

# Copy dependency file first for better layer caching
COPY requirements.txt ./
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt

# Copy full project (everything) into image
COPY . /home/admin/src
RUN chown -R admin:admin /home/admin/src

# Make helper scripts accessible
RUN ln -s /home/admin/src/hubitat-utils/offload-proc/motion-poll.py /usr/local/bin/motion-poll.py && \
    chmod +x /home/admin/src/third-party/dnsleaktest/dnsleaktest.sh && \
    ln -s /home/admin/src/third-party/dnsleaktest/dnsleaktest.sh /usr/local/bin/dnsleaktest.sh && \
    ln -sf /usr/bin/speedtest-cli /usr/local/bin/speedtest || true

# Provide volume points for configs, cache, ssh keys
VOLUME ["/home/admin/cfg", "/home/admin/cache", "/home/admin/.ssh"]

# Copy and set entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown admin:admin /entrypoint.sh

USER admin
EXPOSE 4226
ENTRYPOINT ["/entrypoint.sh"]

# Environment variable hints (override at runtime)
ENV EVENT_CFG_JSON=/home/admin/cfg/event-daemon.json \
    RPC_ADDR=0.0.0.0 \
    RPC_PORT=4226 \
    POLL_INTERVAL=5.0 \
    PROCESSES=3
