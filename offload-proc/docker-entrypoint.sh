#!/bin/bash
set -e

# Docker entrypoint script for Hubitat services
# Handles hubitat-offload, hubitat-event, and roomba services

echo "========================================="
echo "Starting ${SERVICE_NAME} service"
echo "========================================="

case "${SERVICE_NAME}" in
    offload)
        RPC_ADDR=${RPC_ADDR:-0.0.0.0}
        RPC_PORT=${RPC_PORT:-4226}
        PROCESSES=${PROCESSES:-3}
        echo "Starting Hubitat Offload Daemon (RPC Server)..."
        echo "  - RPC Address: ${RPC_ADDR}"
        echo "  - RPC Port: ${RPC_PORT}"
        echo "  - Processes: ${PROCESSES}"
        python3 /opt/hauto/offload-proc/hubitat-offload-daemon.py --rpc-addr ${RPC_ADDR} --rpc-port ${RPC_PORT} --processes ${PROCESSES}
        ;;
    
    event)
        POLL_INTERVAL=${POLL_INTERVAL:-5.0}
        echo "Starting Hubitat Event Daemon (Event Monitor)..."
        echo "  - Config: /etc/hauto/event-config.json"
        echo "  - Poll Interval: ${POLL_INTERVAL}"
        python3 /opt/hauto/offload-proc/hubitat-event-daemon.py --cfg-json /etc/hauto/event-config.json --poll-interval ${POLL_INTERVAL}
        ;;
    
    roomba)
        WEBPORT=${WEBPORT:-8200}
        echo "Starting Roomba980-Python Service..."
        echo "  - Web Port: ${WEBPORT}"
        cd /opt/hauto/roomba
        python3 roomba.py -f /etc/hauto/roomba-config.ini -l /dev/null -wp ${WEBPORT}
        ;;
    
    *)
        echo "ERROR: Unknown SERVICE_NAME '${SERVICE_NAME}'"
        echo "Valid values: offload, event, roomba"
        exit 1
        ;;
esac
