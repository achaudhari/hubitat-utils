#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Starting Hubitat offload + event daemons"

# Ensure expected runtime directories exist
mkdir -p /home/admin/cfg /home/admin/cache
chown -R admin:admin /home/admin/cfg /home/admin/cache || true

# Symlinks (created at build, but recreate just in case of volume overlay)
ln -sf /home/admin/src/hubitat-utils/offload-proc/motion-poll.py /usr/local/bin/motion-poll.py
ln -sf /home/admin/src/third-party/dnsleaktest/dnsleaktest.sh /usr/local/bin/dnsleaktest.sh
chmod +x /usr/local/bin/dnsleaktest.sh || true

EVENT_CFG_JSON=${EVENT_CFG_JSON:-/home/admin/cfg/event-daemon.json}
RPC_ADDR=${RPC_ADDR:-0.0.0.0}
RPC_PORT=${RPC_PORT:-4226}
POLL_INTERVAL=${POLL_INTERVAL:-5.0}
PROCESSES=${PROCESSES:-3}

if [[ ! -f "$EVENT_CFG_JSON" ]]; then
  echo "[entrypoint][warn] Event daemon config not found at $EVENT_CFG_JSON"
fi

# Function to handle shutdown
term_handler() {
  echo "[entrypoint] Caught termination signal, stopping daemons..."
  pkill -P $$ || true
  wait || true
  echo "[entrypoint] All processes stopped"
  exit 0
}
trap term_handler SIGTERM SIGINT

set -x
python3 /home/admin/src/hubitat-utils/offload-proc/hubitat-offload-daemon.py \
  --rpc-addr "$RPC_ADDR" \
  --rpc-port "$RPC_PORT" \
  --processes "$PROCESSES" &
OFFLOAD_PID=$!

python3 /home/admin/src/hubitat-utils/offload-proc/hubitat-event-daemon.py \
  --cfg-json "$EVENT_CFG_JSON" \
  --poll-interval "$POLL_INTERVAL" &
EVENT_PID=$!
set +x

echo "[entrypoint] Offload PID: $OFFLOAD_PID  Event PID: $EVENT_PID"

wait -n || true
echo "[entrypoint] One of the daemons exited. Shutting down..."
term_handler