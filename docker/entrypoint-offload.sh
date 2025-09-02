#!/usr/bin/env bash
set -euo pipefail
echo "[offload-entrypoint] Starting Hubitat Offload RPC daemon"
mkdir -p /home/admin/cfg /home/admin/cache
ln -sf /home/admin/src/hubitat-utils/offload-proc/motion-poll.py /usr/local/bin/motion-poll.py
ln -sf /home/admin/src/third-party/dnsleaktest/dnsleaktest.sh /usr/local/bin/dnsleaktest.sh || true
chmod +x /usr/local/bin/dnsleaktest.sh || true

RPC_ADDR=${RPC_ADDR:-0.0.0.0}
RPC_PORT=${RPC_PORT:-4226}
PROCESSES=${PROCESSES:-3}

term_handler() { echo "[offload-entrypoint] Caught signal, shutting down"; pkill -P $$ || true; wait || true; exit 0; }
trap term_handler SIGTERM SIGINT

set -x
python3 /home/admin/src/hubitat-utils/offload-proc/hubitat-offload-daemon.py \
  --rpc-addr "$RPC_ADDR" \
  --rpc-port "$RPC_PORT" \
  --processes "$PROCESSES"
set +x