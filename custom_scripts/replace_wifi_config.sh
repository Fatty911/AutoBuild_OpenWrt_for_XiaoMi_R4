#!/bin/bash
WIFI_SSID="${WIFI_SSID:-OpenWrt}"
WIFI_PASSWORD="${WIFI_PASSWORD:-password}"
if [ ! -f "$1" ]; then
  echo "replace_wifi_config: $1 not found, skipping"
  exit 0
fi
sed -i "s/\${WIFI_SSID}/$WIFI_SSID/g" "$1"
sed -i "s/\${WIFI_PASSWORD}/$WIFI_PASSWORD/g" "$1"
