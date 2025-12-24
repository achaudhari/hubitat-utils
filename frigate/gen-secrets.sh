#!/bin/bash

# Get the directory of this script
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" &> /dev/null && pwd)"
if [ ! -f ${SCRIPT_DIR}/mosquitto/config/mosquitto_passwd ]; then
    echo "Generating MQTT secret..."
    MQTT_USER=frigate-mqtt
    MQTT_PASS=$(openssl rand -base64 24)

    docker run -it --rm \
        -v "${SCRIPT_DIR}/mosquitto/config:/mosquitto/config" \
        docker.io/eclipse-mosquitto:2.0 \
        mosquitto_passwd -c -b /mosquitto/config/mosquitto_passwd ${MQTT_USER} ${MQTT_PASS}

    echo "=========================================="
    echo "MQTT User : ${MQTT_USER}"
    echo "Password  : ${MQTT_PASS}"
    echo "=========================================="
    echo ""
    echo "Add the following line to the docker .env file:"
    echo "FRIGATE_MQTT_PASSWORD=${MQTT_PASS}"
    echo ""
    echo "WARNING: This information will not be shown again. Save it."
else
    echo "MQTT secret already exists... Skipping"
fi

echo ""
echo "=========================================="
echo "Frigate Authentication:"
echo "=========================================="
echo "Frigate will generate admin credentials on first startup."
echo "Look at docker logs frigate after first startup"
echo "==========================================="
