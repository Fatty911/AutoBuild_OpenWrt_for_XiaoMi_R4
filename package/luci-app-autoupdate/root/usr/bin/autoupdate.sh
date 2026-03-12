#!/bin/sh
#
# OpenWrt Firmware Auto Update Script
# Automatically check and update firmware from GitHub Release
# Supports temporary proxy via SSR-Plus/helloworld subscription
#

. /lib/functions.sh

LOG_FILE="/var/log/autoupdate.log"
CONFIG_FILE="/etc/config/autoupdate"
LOCK_FILE="/var/lock/autoupdate.lock"
TEMP_DIR="/tmp/autoupdate"
FIRMWARE_FILE=""
PROXY_STARTED=0
LOCAL_PROXY_PORT=1080

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
    logger -t autoupdate "$1"
}

cleanup() {
    # 清理临时代理
    if [ "$PROXY_STARTED" = "1" ]; then
        stop_proxy
    fi
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
    config_get SUBSCRIPTION_URL config subscription_url ""
    config_get PROXY_PORT config proxy_port "1080"
    config_get CHECK_INTERVAL config check_interval "daily"
    config_get CURRENT_VERSION config current_version ""
    config_get AUTO_INSTALL config auto_install 0
    
    LOCAL_PROXY_PORT="$PROXY_PORT"
}

# 检测并启动SSR-Plus/helloworld代理
start_ssrplus_proxy() {
    log "尝试启动 SSR-Plus/helloworld 代理..."
    
    # 检查SSR-Plus是否安装
    if [ ! -f "/usr/bin/ssr-local" ] && [ ! -f "/usr/share/shadowsocksr/ssr-local" ]; then
        log "SSR-Plus 未安装，跳过代理"
        return 1
    fi
    
    # 检查订阅是否配置
    if [ -z "$SUBSCRIPTION_URL" ]; then
        log "订阅URL未配置，跳过代理"
        return 1
    fi
    
    # 检查SSR-Plus是否已经在运行
    if pgrep -f "ssr-local\|ssr-redir" > /dev/null; then
        log "SSR-Plus 已在运行，无需启动"
        PROXY_STARTED=0
        return 0
    fi
    
    # 更新订阅
    log "更新订阅..."
    if [ -f "/usr/share/shadowsocksr/subscribe.sh" ]; then
        /usr/share/shadowsocksr/subscribe.sh all 2>&1 >> "$LOG_FILE"
    fi
    
    # 检查是否有可用节点
    local node_file="/etc/shadowsocksr/serverconfig_server.json"
    if [ ! -f "$node_file" ] || [ ! -s "$node_file" ]; then
        log "没有可用的订阅节点"
        return 1
    fi
    
    # 启动ssr-local（SOCKS5代理）
    log "启动 SOCKS5 代理端口: $LOCAL_PROXY_PORT"
    
    # 使用第一个节点启动本地代理
    if [ -f "/usr/share/shadowsocksr/ssr-local" ]; then
        /usr/share/shadowsocksr/ssr-local \
            -c /etc/shadowsocksr/serverconfig_server.json \
            -b 127.0.0.1 \
            -l "$LOCAL_PROXY_PORT" \
            -f /var/run/ssr-local.pid \
            -d 2>&1 >> "$LOG_FILE"
    elif [ -f "/usr/bin/ssr-local" ]; then
        /usr/bin/ssr-local \
            -c /etc/shadowsocksr/serverconfig_server.json \
            -b 127.0.0.1 \
            -l "$LOCAL_PROXY_PORT" \
            -f /var/run/ssr-local.pid \
            -d 2>&1 >> "$LOG_FILE"
    fi
    
    sleep 2
    
    # 验证代理是否启动
    if pgrep -f "ssr-local.*$LOCAL_PROXY_PORT" > /dev/null; then
        log "代理启动成功: socks5://127.0.0.1:$LOCAL_PROXY_PORT"
        PROXY_STARTED=1
        return 0
    else
        log "代理启动失败"
        return 1
    fi
}

# 停止临时代理
stop_proxy() {
    if [ "$PROXY_STARTED" = "1" ]; then
        log "停止临时代理..."
        if [ -f "/var/run/ssr-local.pid" ]; then
            kill $(cat /var/run/ssr-local.pid) 2>/dev/null
            rm -f /var/run/ssr-local.pid
        fi
        PROXY_STARTED=0
    fi
}

# 通过LuCI API启动代理（备用方案）
start_luci_proxy() {
    log "尝试通过 LuCI 启动代理..."
    
    # 检查helloworld/SSR-Plus的LuCI接口
    if [ -f "/usr/lib/lua/luci/controller/ssr-plus.lua" ] || \
       [ -f "/usr/lib/lua/luci/controller/helloworld.lua" ]; then
        
        # 通过ubus调用
        ubus call ssr-plus enable 2>/dev/null || \
        ubus call helloworld enable 2>/dev/null || true
        
        sleep 3
        
        # 检查socks5端口
        if netstat -tln | grep -q ":1080 "; then
            log "通过 LuCI 启动代理成功"
            LOCAL_PROXY_PORT=1080
            PROXY_STARTED=1
            return 0
        fi
    fi
    
    return 1
}

fetch_with_proxy() {
    local url="$1"
    local output="$2"
    local retry=3
    
    while [ $retry -gt 0 ]; do
        if [ "$PROXY_STARTED" = "1" ]; then
            log "使用代理下载: socks5://127.0.0.1:$LOCAL_PROXY_PORT"
            curl --socks5-hostname "127.0.0.1:$LOCAL_PROXY_PORT" \
                 --connect-timeout 30 \
                 -sL -o "$output" "$url"
        else
            log "直接下载（无代理）"
            curl --connect-timeout 30 -sL -o "$output" "$url"
        fi
        
        if [ -s "$output" ]; then
            return 0
        fi
        
        log "下载失败，重试... ($retry)"
        retry=$((retry - 1))
        sleep 2
    done
    
    return 1
}

get_latest_release() {
    local api_url="https://api.github.com/repos/${GITHUB_REPO}/releases"
    local releases_json="$TEMP_DIR/releases.json"
    
    log "获取最新Release: $api_url"
    
    if ! fetch_with_proxy "$api_url" "$releases_json"; then
        log "获取Release列表失败"
        return 1
    fi
    
    # 查找匹配工作流的最新 release
    LATEST_VERSION=$(grep -o '"tag_name": *"[^"]*"' "$releases_json" | head -1 | cut -d'"' -f4)
    
    if [ -z "$LATEST_VERSION" ]; then
        log "未找到Release"
        return 1
    fi
    
    log "最新版本: $LATEST_VERSION"
    return 0
}

find_firmware_file() {
    local assets_url="https://api.github.com/repos/${GITHUB_REPO}/releases/tags/${LATEST_VERSION}"
    local assets_json="$TEMP_DIR/assets.json"
    
    if ! fetch_with_proxy "$assets_url" "$assets_json"; then
        log "获取资源列表失败"
        return 1
    fi
    
    # 查找匹配工作流名称的 .bin 文件
    FIRMWARE_FILE=$(grep -o '"name": *"[^"]*\.bin"' "$assets_json" | \
                    grep -i "$WORKFLOW_NAME\|xiaomi.*mi-router-4" | \
                    head -1 | cut -d'"' -f4)
    
    if [ -z "$FIRMWARE_FILE" ]; then
        # 尝试任意 .bin 文件
        FIRMWARE_FILE=$(grep -o '"name": *"[^"]*\.bin"' "$assets_json" | head -1 | cut -d'"' -f4)
    fi
    
    if [ -z "$FIRMWARE_FILE" ]; then
        log "Release中没有固件文件"
        return 1
    fi
    
    FIRMWARE_URL="https://github.com/${GITHUB_REPO}/releases/download/${LATEST_VERSION}/${FIRMWARE_FILE}"
    log "固件URL: $FIRMWARE_URL"
    return 0
}

download_firmware() {
    local output="$TEMP_DIR/firmware.bin"
    
    log "下载固件: $FIRMWARE_FILE"
    
    if ! fetch_with_proxy "$FIRMWARE_URL" "$output"; then
        log "固件下载失败"
        return 1
    fi
    
    # 验证文件大小 (> 5MB)
    local size=$(wc -c < "$output" 2>/dev/null)
    if [ -z "$size" ] || [ "$size" -lt 5000000 ]; then
        log "下载的文件太小，可能已损坏: ${size:-0} bytes"
        return 1
    fi
    
    log "固件下载成功: ${size} bytes"
    FIRMWARE_FILE="$output"
    return 0
}

check_new_version() {
    if [ "$LATEST_VERSION" = "$CURRENT_VERSION" ]; then
        log "已是最新版本: $LATEST_VERSION"
        return 1
    fi
    
    log "发现新版本: $LATEST_VERSION (当前: ${CURRENT_VERSION:-未知})"
    return 0
}

install_firmware() {
    log "准备安装固件..."
    
    if [ "$AUTO_INSTALL" != "1" ]; then
        log "自动安装已禁用"
        log "固件已下载到: $FIRMWARE_FILE"
        log "手动安装命令: sysupgrade -n $FIRMWARE_FILE"
        return 0
    fi
    
    # 备份当前版本信息
    uci set autoupdate.config.current_version="$LATEST_VERSION"
    uci commit autoupdate
    
    log "开始刷写固件..."
    sysupgrade -n "$FIRMWARE_FILE"
    
    # 不应该到达这里
    log "固件刷写失败！"
    return 1
}

check_update() {
    log "========== 开始检查更新 =========="
    
    mkdir -p "$TEMP_DIR"
    
    get_config
    
    if [ "$ENABLED" != "1" ]; then
        log "自动更新已禁用"
        return 0
    fi
    
    if [ -z "$GITHUB_REPO" ]; then
        log "GitHub仓库未配置"
        return 1
    fi
    
    # 尝试启动代理
    if [ -n "$SUBSCRIPTION_URL" ]; then
        start_ssrplus_proxy || start_luci_proxy || log "代理启动失败，将直接访问"
    fi
    
    # 检查更新
    if ! get_latest_release; then
        log "获取版本信息失败"
        return 1
    fi
    
    if ! check_new_version; then
        return 0
    fi
    
    if ! find_firmware_file; then
        return 1
    fi
    
    if ! download_firmware; then
        return 1
    fi
    
    install_firmware || return 1
    
    log "========== 更新检查完成 =========="
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
    proxy-test)
        # 测试代理连接
        get_config
        if [ -n "$SUBSCRIPTION_URL" ]; then
            start_ssrplus_proxy || start_luci_proxy
            if [ "$PROXY_STARTED" = "1" ]; then
                log "代理测试..."
                curl --socks5-hostname "127.0.0.1:$LOCAL_PROXY_PORT" \
                     -s -o /dev/null -w "%{http_code}" \
                     "https://github.com" && log "GitHub访问成功"
                stop_proxy
            fi
        else
            log "订阅URL未配置"
        fi
        ;;
    *)
        echo "用法: $0 {check|install|proxy-test}"
        echo "  check      - 检查更新"
        echo "  install    - 检查并安装更新"
        echo "  proxy-test - 测试代理连接"
        exit 1
        ;;
esac
