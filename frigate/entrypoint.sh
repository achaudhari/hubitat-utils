#!/bin/bash
set -e

# Check if template exists
if [ ! -f /config/config.yml.base ]; then
    echo "ERROR: Template file /config/config.yml.base not found!"
    exit 1
fi

echo "Generating config.yml from template..."

# Copy template to output
cp /config/config.yml.base /config/config.yml

# Replace all FRIGATE_* environment variables
for var in $(env | grep '^FRIGATE_' | cut -d= -f1); do
    value="${!var}"
    # Escape special characters for sed
    escaped_value=$(echo "$value" | sed 's/[&/\]/\\&/g')
    echo "Substituting $var"
    sed -i "s/\${$var}/$escaped_value/g" /config/config.yml
done

echo "Config generation complete. File size: $(stat -c%s /config/config.yml) bytes"

# Start Frigate (delegate to original entrypoint)
exec /init
