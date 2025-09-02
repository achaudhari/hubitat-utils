Systemd Units for Hubitat Daemons
=================================

This directory contains example systemd service unit files for running the two Python daemons
inside their respective Docker containers (split build). Adjust paths as needed.

Files:
  - hubitat-offload.service : Runs the RPC offload daemon container.
  - hubitat-event.service   : Runs the event polling daemon container.
  - hubitat.target          : Convenience target that starts both services.
  - hubitat-offload.env     : Environment overrides for offload daemon.
  - hubitat-event.env       : Environment overrides for event daemon.

Prerequisites
-------------
1. Docker (or rootless Docker / Podman — see notes below) installed and enabled.
2. Images built locally, e.g.:
       docker build -f Dockerfile.offload -t hubitat-offload:latest .
       docker build -f Dockerfile.event   -t hubitat-event:latest   .
3. Host directories for persistent data:
       sudo mkdir -p /opt/hubitat/cfg /opt/hubitat/cache
       sudo chown -R root:root /opt/hubitat
   Place required config files (event-daemon.json, history-report.json, influxdb.cred, hubitat.secret, MAC OUI CSVs, etc.) into /opt/hubitat/cfg.

Install Units
-------------
sudo cp systemd/hubitat-*.service /etc/systemd/system/
sudo cp systemd/hubitat.target /etc/systemd/system/
sudo cp systemd/hubitat-offload.env /etc/default/hubitat-offload
sudo cp systemd/hubitat-event.env /etc/default/hubitat-event
sudo systemctl daemon-reload
sudo systemctl enable hubitat.target
sudo systemctl start hubitat.target

View Logs
---------
  journalctl -u hubitat-offload -f
  journalctl -u hubitat-event -f

Edit Environment / Config
-------------------------
Edit /etc/default/hubitat-offload or /etc/default/hubitat-event then:
  sudo systemctl restart hubitat-offload
  sudo systemctl restart hubitat-event

Podman Notes
------------
If using Podman rootless: replace /usr/bin/docker with /usr/bin/podman in the service files,
set User=<youruser>, remove --pull args if unsupported, and ensure login session lingering:
  loginctl enable-linger <youruser>

Security Hardening Ideas
------------------------
  - Create a dedicated system user (User=hubitat) with limited privileges.
  - Use --read-only and explicit writable tmpfs mounts if feasible.
  - Restrict capabilities: add --cap-drop=ALL unless specific ones are needed (ping uses raw sockets; instead rely on container's iputils-ping without extra caps because default NET_RAW may be required — test before dropping).
  - Consider network namespace isolation (avoid --network host) if not strictly needed; open explicit ports instead.
