#!/bin/bash
WIFI_SSID="${WIFI_SSID:-OpenWrt}"
WIFI_PASSWORD="${WIFI_PASSWORD:-password}"
sed -i "s/\${WIFI_SSID}/$WIFI_SSID/g" "$1"
sed -i "s/\${WIFI_PASSWORD}/$WIFI_PASSWORD/g" "$1"
