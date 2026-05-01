#!/bin/sh
#
# OpenWrt Firmware Auto Update Script
# Check and update firmware from GitHub Release
# Supports temporary proxy via SSR-Plus subscription
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
	if [ "$PROXY_STARTED" = "1" ]; then
		stop_proxy
	fi
	rm -rf "$TEMP_DIR"
	rm -f "$LOCK_FILE"
}

check_lock() {
	if [ -f "$LOCK_FILE" ]; then
		local pid
		pid="$(cat "$LOCK_FILE" 2>/dev/null)"
		if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
			log "Another instance is running (PID=$pid), exit."
			exit 1
		fi
		# Stale lock file
		rm -f "$LOCK_FILE"
	fi
	echo $$ > "$LOCK_FILE"
	trap cleanup EXIT
}

get_config() {
	config_load autoupdate
	config_get ENABLED config enabled 0
	config_get GITHUB_REPO config github_repo ""
	config_get WORKFLOW_NAME config workflow_name ""
	config_get GITHUB_TOKEN config github_token ""
	config_get SUBSCRIPTION_URL config subscription_url ""
	config_get PROXY_PORT config proxy_port "1080"
	config_get CHECK_INTERVAL config check_interval "daily"
	config_get CURRENT_VERSION config current_version ""
	config_get AUTO_INSTALL config auto_install 0

	LOCAL_PROXY_PORT="$PROXY_PORT"
}

# ── 代理管理 ──────────────────────────────────────────────

# 启动 SSR-Plus 代理（临时）
start_proxy() {
	log "尝试启动代理..."

	# 1) 检查 SSR-Plus 是否已经在运行 — 直接复用
	if netstat -tln 2>/dev/null | grep -q ":${LOCAL_PROXY_PORT} "; then
		log "代理端口 ${LOCAL_PROXY_PORT} 已在监听，直接使用"
		PROXY_STARTED=0
		return 0
	fi

	# 2) 如果没配置订阅 URL，跳过代理
	if [ -z "$SUBSCRIPTION_URL" ]; then
		log "订阅URL未配置，跳过代理"
		return 1
	fi

	# 3) 通过 LuCI/ubus 启动 SSR-Plus（最可靠的方式）
	if [ -f "/etc/init.d/ssr-plus" ]; then
		log "启动 SSR-Plus 服务..."
		/etc/init.d/ssr-plus start 2>/dev/null
		sleep 3
	elif [ -f "/etc/init.d/shadowsocksr" ]; then
		log "启动 shadowsocksr 服务..."
		/etc/init.d/shadowsocksr start 2>/dev/null
		sleep 3
	fi

	# 4) 验证 SOCKS5 端口
	local retry=5
	while [ $retry -gt 0 ]; do
		if netstat -tln 2>/dev/null | grep -q ":${LOCAL_PROXY_PORT} "; then
			log "代理启动成功: socks5://127.0.0.1:${LOCAL_PROXY_PORT}"
			PROXY_STARTED=1
			return 0
		fi
		retry=$((retry - 1))
		sleep 2
	done

	log "代理启动失败，将直接访问"
	return 1
}

# 停止临时代理（只停止我们启动的）
stop_proxy() {
	if [ "$PROXY_STARTED" = "1" ]; then
		log "停止临时代理..."
		if [ -f "/etc/init.d/ssr-plus" ]; then
			/etc/init.d/ssr-plus stop 2>/dev/null
		elif [ -f "/etc/init.d/shadowsocksr" ]; then
			/etc/init.d/shadowsocksr stop 2>/dev/null
		fi
		PROXY_STARTED=0
	fi
}

# ── 网络请求 ──────────────────────────────────────────────

fetch_url() {
	local url="$1"
	local output="$2"
	local retry=3

	while [ $retry -gt 0 ]; do
		local curl_args="-sL --connect-timeout 30 --max-time 120"

		if [ "$PROXY_STARTED" = "1" ] || netstat -tln 2>/dev/null | grep -q ":${LOCAL_PROXY_PORT} "; then
			log "使用代理下载: socks5://127.0.0.1:${LOCAL_PROXY_PORT}"
			curl $curl_args --socks5-hostname "127.0.0.1:${LOCAL_PROXY_PORT}" \
				-o "$output" "$url"
		else
			log "直接下载（无代理）"
			curl $curl_args -o "$output" "$url"
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

# GitHub API 请求（带可选 Token 认证）
github_api() {
	local url="$1"
	local output="$2"

	local curl_args="-sL --connect-timeout 30 --max-time 60"

	if [ -n "$GITHUB_TOKEN" ]; then
		curl_args="$curl_args -H \"Authorization: token $GITHUB_TOKEN\""
	fi

	if [ "$PROXY_STARTED" = "1" ] || netstat -tln 2>/dev/null | grep -q ":${LOCAL_PROXY_PORT} "; then
		curl $curl_args --socks5-hostname "127.0.0.1:${LOCAL_PROXY_PORT}" \
			-o "$output" "$url"
	else
		curl $curl_args -o "$output" "$url"
	fi
}

# ── 版本检查 ──────────────────────────────────────────────

get_current_version() {
	# 从 /etc/openwrt_release 获取当前固件版本标识
	if [ -f /etc/openwrt_release ]; then
		. /etc/openwrt_release
		echo "${OPENWRT_BOARD:-unknown}@${OPENWRT_ARCH:-unknown}"
	fi
}

get_latest_release() {
	local api_url="https://api.github.com/repos/${GITHUB_REPO}/releases"
	local releases_json="$TEMP_DIR/releases.json"

	log "获取最新Release: $api_url"

	if ! github_api "$api_url" "$releases_json"; then
		log "获取Release列表失败"
		return 1
	fi

	# 使用 jsonfilter 解析（OpenWrt 自带）
	local first_tag
	first_tag=$(jsonfilter -e '@[0].tag_name' "$releases_json" 2>/dev/null)

	if [ -z "$first_tag" ]; then
		log "未找到Release（可能API速率限制，请配置github_token）"
		return 1
	fi

	LATEST_VERSION="$first_tag"
	log "最新版本: $LATEST_VERSION"
	return 0
}

check_new_version() {
	if [ -z "$CURRENT_VERSION" ]; then
		# 首次运行，记录当前版本并提示更新
		log "首次运行，记录版本: $LATEST_VERSION"
		uci set autoupdate.config.current_version="$LATEST_VERSION"
		uci commit autoupdate
		return 1
	fi

	if [ "$LATEST_VERSION" = "$CURRENT_VERSION" ]; then
		log "已是最新版本: $LATEST_VERSION"
		return 1
	fi

	log "发现新版本: $LATEST_VERSION (当前: $CURRENT_VERSION)"
	return 0
}

find_firmware_file() {
	local api_url="https://api.github.com/repos/${GITHUB_REPO}/releases/tags/${LATEST_VERSION}"
	local assets_json="$TEMP_DIR/assets.json"

	if ! github_api "$api_url" "$assets_json"; then
		log "获取Release资源列表失败"
		return 1
	fi

	# 用 jsonfilter 查找匹配的固件文件
	# 优先匹配包含工作流名或 mi-router-4 的 .bin/.img 文件
	local asset_name=""
	local asset_url=""
	local idx=0

	while true; do
		asset_name=$(jsonfilter -e "@.assets[$idx].name" "$assets_json" 2>/dev/null) || break
		[ -z "$asset_name" ] && break

		case "$asset_name" in
			*.bin|*.img|*.sysupgrade*)
				# 匹配 Mi Router 4 相关固件
				case "$asset_name" in
					*mi-router-4*|*mi_router_4*|*xiaomi*r4*|*"$WORKFLOW_NAME"*)
						asset_url=$(jsonfilter -e "@.assets[$idx].browser_download_url" "$assets_json" 2>/dev/null)
						break
						;;
				esac
				;;
		esac
		idx=$((idx + 1))
	done

	# 没精确匹配，取第一个 .sysupgrade. 或 .bin 文件
	if [ -z "$asset_url" ]; then
		idx=0
		while true; do
			asset_name=$(jsonfilter -e "@.assets[$idx].name" "$assets_json" 2>/dev/null) || break
			[ -z "$asset_name" ] && break

			case "$asset_name" in
				*sysupgrade*|*.bin)
					asset_url=$(jsonfilter -e "@.assets[$idx].browser_download_url" "$assets_json" 2>/dev/null)
					break
					;;
			esac
			idx=$((idx + 1))
		done
	fi

	if [ -z "$asset_url" ]; then
		log "Release中没有匹配的固件文件"
		return 1
	fi

	FIRMWARE_NAME="$asset_name"
	FIRMWARE_URL="$asset_url"
	log "固件: $FIRMWARE_NAME"
	log "URL: $FIRMWARE_URL"
	return 0
}

download_firmware() {
	local output="$TEMP_DIR/firmware.bin"

	log "下载固件: $FIRMWARE_NAME"

	if ! fetch_url "$FIRMWARE_URL" "$output"; then
		log "固件下载失败"
		return 1
	fi

	# 验证文件大小 (> 3MB for sysupgrade images)
	local size
	size=$(wc -c < "$output" 2>/dev/null)
	if [ -z "$size" ] || [ "$size" -lt 3000000 ]; then
		log "下载的文件太小，可能已损坏: ${size:-0} bytes"
		rm -f "$output"
		return 1
	fi

	log "固件下载成功: ${size} bytes"
	FIRMWARE_FILE="$output"
	return 0
}

install_firmware() {
	log "准备安装固件..."

	# 更新版本记录（不管是否自动安装都记录，避免重复下载）
	uci set autoupdate.config.current_version="$LATEST_VERSION"
	uci commit autoupdate

	if [ "$AUTO_INSTALL" != "1" ]; then
		log "自动安装已禁用"
		log "固件已下载到: $FIRMWARE_FILE"
		log "手动安装: sysupgrade -n $FIRMWARE_FILE"
		return 0
	fi

	log "开始刷写固件..."
	sysupgrade -n "$FIRMWARE_FILE"

	# 不应该到达这里
	log "固件刷写失败！"
	return 1
}

# ── 主逻辑 ────────────────────────────────────────────────

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

	# 尝试启动代理（仅在配置了订阅URL时）
	if [ -n "$SUBSCRIPTION_URL" ]; then
		start_proxy || log "代理启动失败，将直接访问"
	fi

	# 检查更新
	if ! get_latest_release; then
		cleanup
		return 1
	fi

	if ! check_new_version; then
		cleanup
		return 0
	fi

	if ! find_firmware_file; then
		cleanup
		return 1
	fi

	if ! download_firmware; then
		cleanup
		return 1
	fi

	install_firmware || true

	log "========== 更新检查完成 =========="
	cleanup
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
		AUTO_INSTALL=1 check_update
		;;
	proxy-test)
		get_config
		if [ -n "$SUBSCRIPTION_URL" ]; then
			start_proxy
			if [ "$PROXY_STARTED" = "1" ] || netstat -tln 2>/dev/null | grep -q ":${LOCAL_PROXY_PORT} "; then
				log "代理测试..."
				if curl --socks5-hostname "127.0.0.1:${LOCAL_PROXY_PORT}" \
					-s -o /dev/null -w "%{http_code}" --max-time 15 \
					"https://github.com" 2>/dev/null | grep -q "200"; then
					log "GitHub 访问成功"
					echo "OK: GitHub accessible via proxy"
				else
					log "GitHub 访问失败"
					echo "FAIL: Cannot access GitHub via proxy"
				fi
				stop_proxy
			else
				echo "FAIL: Proxy not available"
			fi
		else
			echo "SKIP: No subscription URL configured"
		fi
		;;
	version)
		get_config
		echo "Current: ${CURRENT_VERSION:-unknown}"
		;;
	*)
		echo "Usage: $0 {check|install|proxy-test|version}"
		echo "  check      - Check for updates (download if found)"
		echo "  install    - Check and auto-install updates"
		echo "  proxy-test - Test proxy connectivity"
		echo "  version    - Show current version"
		exit 1
		;;
esac
