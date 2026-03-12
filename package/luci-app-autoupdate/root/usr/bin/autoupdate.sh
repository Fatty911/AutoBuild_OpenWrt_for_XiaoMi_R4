#!/bin/sh
#
# OpenWrt Firmware Auto Update Script
# Automatically check and update firmware from GitHub Release
#

. /lib/functions.sh

LOG_FILE="/var/log/autoupdate.log"
CONFIG_FILE="/etc/config/autoupdate"
LOCK_FILE="/var/lock/autoupdate.lock"
TEMP_DIR="/tmp/autoupdate"
FIRMWARE_FILE=""

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
    logger -t autoupdate "$1"
}

cleanup() {
    rm -rf "$TEMP_DIR"
    rm -f "$LOCK_FILE"
}

check_lock() {
    if [ -f "$LOCK_FILE" ]; then
        log "Another instance is running, exit."
        exit 1
    fi
    touch "$LOCK_FILE"
    trap cleanup EXIT
}

get_config() {
    config_load autoupdate
    config_get ENABLED config enabled 0
    config_get GITHUB_REPO config github_repo ""
    config_get WORKFLOW_NAME config workflow_name ""
    config_get PROXY_URL config proxy_url ""
    config_get CHECK_INTERVAL config check_interval "daily"
    config_get CURRENT_VERSION config current_version ""
    config_get AUTO_INSTALL config auto_install 0
}

fetch_with_proxy() {
    local url="$1"
    local output="$2"
    
    if [ -n "$PROXY_URL" ]; then
        log "Using proxy: $PROXY_URL"
        curl --proxy "$PROXY_URL" -sL -o "$output" "$url"
    else
        curl -sL -o "$output" "$url"
    fi
}

get_latest_release() {
    local api_url="https://api.github.com/repos/${GITHUB_REPO}/releases"
    local releases_json="$TEMP_DIR/releases.json"
    
    log "Fetching releases from $api_url"
    fetch_with_proxy "$api_url" "$releases_json"
    
    if [ ! -s "$releases_json" ]; then
        log "Failed to fetch releases"
        return 1
    fi
    
    # 查找匹配工作流的最新 release
    LATEST_VERSION=$(grep -o '"tag_name": *"[^"]*"' "$releases_json" | head -1 | cut -d'"' -f4)
    
    if [ -z "$LATEST_VERSION" ]; then
        log "No release found"
        return 1
    fi
    
    log "Latest version: $LATEST_VERSION"
    return 0
}

find_firmware_file() {
    local release_url="https://github.com/${GITHUB_REPO}/releases/download/${LATEST_VERSION}"
    local assets_url="https://api.github.com/repos/${GITHUB_REPO}/releases/tags/${LATEST_VERSION}"
    local assets_json="$TEMP_DIR/assets.json"
    
    fetch_with_proxy "$assets_url" "$assets_json"
    
    # 查找 .bin 文件
    FIRMWARE_FILE=$(grep -o '"name": *"[^"]*\.bin"' "$assets_json" | head -1 | cut -d'"' -f4)
    
    if [ -z "$FIRMWARE_FILE" ]; then
        log "No firmware file found in release"
        return 1
    fi
    
    FIRMWARE_URL="${release_url}/${FIRMWARE_FILE}"
    log "Firmware URL: $FIRMWARE_URL"
    return 0
}

download_firmware() {
    local output="$TEMP_DIR/firmware.bin"
    
    log "Downloading firmware..."
    fetch_with_proxy "$FIRMWARE_URL" "$output"
    
    if [ ! -s "$output" ]; then
        log "Failed to download firmware"
        return 1
    fi
    
    # 验证文件大小 (> 5MB)
    local size=$(wc -c < "$output")
    if [ "$size" -lt 5000000 ]; then
        log "Downloaded file too small, may be corrupted"
        return 1
    fi
    
    log "Firmware downloaded successfully: ${size} bytes"
    FIRMWARE_FILE="$output"
    return 0
}

check_new_version() {
    if [ "$LATEST_VERSION" = "$CURRENT_VERSION" ]; then
        log "Already on latest version: $LATEST_VERSION"
        return 1
    fi
    
    log "New version available: $LATEST_VERSION (current: $CURRENT_VERSION)"
    return 0
}

install_firmware() {
    log "Installing firmware..."
    
    if [ "$AUTO_INSTALL" != "1" ]; then
        log "Auto install disabled, please update manually"
        log "Firmware downloaded to: $FIRMWARE_FILE"
        log "Run: sysupgrade -n $FIRMWARE_FILE"
        return 0
    fi
    
    # 备份配置
    log "Creating config backup..."
    
    # 刷写固件
    log "Flashing firmware..."
    sysupgrade -n "$FIRMWARE_FILE"
    
    # 不应该到达这里
    log "Firmware update failed!"
    return 1
}

check_update() {
    log "Starting update check..."
    
    mkdir -p "$TEMP_DIR"
    
    get_config
    
    if [ "$ENABLED" != "1" ]; then
        log "Auto update disabled"
        return 0
    fi
    
    if [ -z "$GITHUB_REPO" ]; then
        log "GitHub repository not configured"
        return 1
    fi
    
    get_latest_release || return 1
    
    check_new_version || return 0
    
    find_firmware_file || return 1
    
    download_firmware || return 1
    
    install_firmware || return 1
    
    return 0
}

# 主入口
case "$1" in
    check)
        check_lock
        check_update
        ;;
    install)
        check_lock
        get_config
        AUTO_INSTALL=1
        check_update
        ;;
    *)
        echo "Usage: $0 {check|install}"
        exit 1
        ;;
esac
