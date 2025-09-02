#!/usr/bin/env bash
set -euo pipefail
echo "[event-entrypoint] Starting Hubitat Event daemon"
mkdir -p /home/admin/cfg /home/admin/cache
# ln -sf /home/admin/src/hubitat-utils/offload-proc/motion-poll.py /usr/local/bin/motion-poll.py

EVENT_CFG_JSON=${EVENT_CFG_JSON:-/home/admin/cfg/event-daemon.json}
POLL_INTERVAL=${POLL_INTERVAL:-5.0}

if [[ ! -f "$EVENT_CFG_JSON" ]]; then
  echo "[event-entrypoint][warn] Config missing at $EVENT_CFG_JSON" >&2
fi

term_handler() { echo "[event-entrypoint] Caught signal, shutting down"; pkill -P $$ || true; wait || true; exit 0; }
trap term_handler SIGTERM SIGINT

set -x
python3 /home/admin/src/hubitat-utils/offload-proc/hubitat-event-daemon.py \
  --cfg-json "$EVENT_CFG_JSON" \
  --poll-interval "$POLL_INTERVAL"
set +x