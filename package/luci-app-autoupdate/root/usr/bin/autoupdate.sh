#!/bin/sh
# shellcheck shell=ash
#
# OpenWrt Firmware Auto Update Script
# Check and update firmware from GitHub Release
# Falls back to a temporary local proxy only after direct access fails.
#

# shellcheck source=/dev/null
. /lib/functions.sh

LOG_FILE="/var/log/autoupdate.log"
LOCK_FILE="/var/lock/autoupdate.lock"
TEMP_DIR="/tmp/autoupdate-work"
DOWNLOAD_DIR="/tmp/autoupdate"
FIRMWARE_FILE=""
PROXY_STARTED=0
PROXY_SERVICE_STARTED=""
LOCAL_PROXY_PORT=1080
FORCE_AUTO_INSTALL=0

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
	config_get UPDATE_BASE_URL config update_base_url ""
	config_get GITHUB_TOKEN config github_token ""
	config_get PROXY_SERVICE config proxy_service "auto"
	config_get PROXY_PORT config proxy_port "1080"
	config_get CHECK_INTERVAL config check_interval "daily"
	config_get LAST_SEEN_VERSION config last_seen_version ""
	config_get LAST_CHECK config last_check 0
	config_get RELEASE_TAG_PREFIX config release_tag_prefix "OpenWRT.org_Kernel_"
	config_get DEVICE_PATTERN config device_pattern "mi-router-4"
	config_get AUTO_INSTALL_CONFIG config auto_install 0

	LOCAL_PROXY_PORT="$PROXY_PORT"
	AUTO_INSTALL="$AUTO_INSTALL_CONFIG"
	if [ "$FORCE_AUTO_INSTALL" = "1" ]; then
		AUTO_INSTALL=1
	fi
}

# ── 代理管理 ──────────────────────────────────────────────

proxy_available() {
	netstat -tln 2>/dev/null | grep -q ":${LOCAL_PROXY_PORT} "
}

start_service_proxy() {
	local service="$1"
	local init_script=""

	case "$service" in
		ssr-plus|shadowsocksr)
			if [ -f "/etc/init.d/ssr-plus" ]; then
				init_script="/etc/init.d/ssr-plus"
			elif [ -f "/etc/init.d/shadowsocksr" ]; then
				init_script="/etc/init.d/shadowsocksr"
			fi
			;;
		openclash)
			[ -f "/etc/init.d/openclash" ] && init_script="/etc/init.d/openclash"
			;;
	esac

	[ -n "$init_script" ] || return 1

	log "启动临时代理服务: $service"
	"$init_script" start 2>/dev/null
	PROXY_SERVICE_STARTED="$service"
	return 0
}

# 启动或复用本机 SOCKS5 代理（仅在直连失败后调用）
start_proxy() {
	log "尝试启动代理..."

	if proxy_available; then
		log "代理端口 ${LOCAL_PROXY_PORT} 已在监听，直接使用"
		PROXY_STARTED=0
		return 0
	fi

	case "$PROXY_SERVICE" in
		shadowsocksr|ssr-plus)
			start_service_proxy "ssr-plus" || return 1
			;;
		openclash)
			start_service_proxy "openclash" || return 1
			;;
		auto|*)
			start_service_proxy "ssr-plus" || start_service_proxy "openclash" || return 1
			;;
	esac

	local retry=8
	while [ $retry -gt 0 ]; do
		if proxy_available; then
			log "代理可用: socks5://127.0.0.1:${LOCAL_PROXY_PORT}"
			PROXY_STARTED=1
			return 0
		fi
		retry=$((retry - 1))
		sleep 2
	done

	log "代理启动失败"
	if [ -n "$PROXY_SERVICE_STARTED" ]; then
		PROXY_STARTED=1
		stop_proxy
	fi
	return 1
}

# 停止临时代理（只停止本脚本启动的服务）
stop_proxy() {
	if [ "$PROXY_STARTED" = "1" ]; then
		log "停止临时代理..."
		case "$PROXY_SERVICE_STARTED" in
			openclash)
				[ -f "/etc/init.d/openclash" ] && /etc/init.d/openclash stop 2>/dev/null
				;;
			ssr-plus|shadowsocksr|*)
				if [ -f "/etc/init.d/ssr-plus" ]; then
					/etc/init.d/ssr-plus stop 2>/dev/null
				elif [ -f "/etc/init.d/shadowsocksr" ]; then
					/etc/init.d/shadowsocksr stop 2>/dev/null
				fi
				;;
		esac
		PROXY_STARTED=0
		PROXY_SERVICE_STARTED=""
	fi
}

# ── 网络请求 ──────────────────────────────────────────────

curl_download() {
	local mode="$1"
	local url="$2"
	local output="$3"

	rm -f "$output"
	if [ "$mode" = "proxy" ]; then
		curl -fsSL --connect-timeout 30 --max-time 120 \
			--socks5-hostname "127.0.0.1:${LOCAL_PROXY_PORT}" \
			-o "$output" "$url"
	else
		curl -fsSL --connect-timeout 30 --max-time 120 \
			-o "$output" "$url"
	fi
}

curl_api() {
	local mode="$1"
	local url="$2"
	local output="$3"

	rm -f "$output"
	if [ "$mode" = "proxy" ]; then
		if [ -n "$GITHUB_TOKEN" ]; then
			curl -fsSL --connect-timeout 30 --max-time 60 \
				-H "Authorization: Bearer $GITHUB_TOKEN" \
				-H "Accept: application/vnd.github+json" \
				--socks5-hostname "127.0.0.1:${LOCAL_PROXY_PORT}" \
				-o "$output" "$url"
		else
			curl -fsSL --connect-timeout 30 --max-time 60 \
				-H "Accept: application/vnd.github+json" \
				--socks5-hostname "127.0.0.1:${LOCAL_PROXY_PORT}" \
				-o "$output" "$url"
		fi
	else
		if [ -n "$GITHUB_TOKEN" ]; then
			curl -fsSL --connect-timeout 30 --max-time 60 \
				-H "Authorization: Bearer $GITHUB_TOKEN" \
				-H "Accept: application/vnd.github+json" \
				-o "$output" "$url"
		else
			curl -fsSL --connect-timeout 30 --max-time 60 \
				-H "Accept: application/vnd.github+json" \
				-o "$output" "$url"
		fi
	fi
}

fetch_url() {
	local url="$1"
	local output="$2"

	log "直连下载: $url"
	if curl_download direct "$url" "$output" && [ -s "$output" ]; then
		return 0
	fi

	log "直连下载失败，准备使用代理重试"
	if start_proxy && curl_download proxy "$url" "$output" && [ -s "$output" ]; then
		return 0
	fi

	rm -f "$output"
	return 1
}

# GitHub API 请求（带可选 Token 认证）
github_api() {
	local url="$1"
	local output="$2"

	log "直连请求 API: $url"
	if curl_api direct "$url" "$output" && [ -s "$output" ]; then
		return 0
	fi

	log "直连 API 请求失败，准备使用代理重试"
	if start_proxy && curl_api proxy "$url" "$output" && [ -s "$output" ]; then
		return 0
	fi

	rm -f "$output"
	return 1
}

# ── 版本检查 ──────────────────────────────────────────────

get_current_version() {
	if [ -s /etc/autoupdate-version ]; then
		sed -n '1{s/[[:space:]]*$//;p;q;}' /etc/autoupdate-version
		return 0
	fi

	if [ -f /etc/openwrt_release ]; then
		# shellcheck source=/dev/null
		. /etc/openwrt_release
		echo "${OPENWRT_BOARD:-unknown}@${OPENWRT_ARCH:-unknown}"
	fi
}

api_base_url() {
	local base

	if [ -n "$UPDATE_BASE_URL" ]; then
		base="${UPDATE_BASE_URL%/}"
	else
		base="https://api.github.com/repos/${GITHUB_REPO}"
	fi

	case "$base" in
		*/releases)
			echo "${base%/releases}"
			;;
		*)
			echo "$base"
			;;
	esac
}

get_latest_release() {
	local api_url
	local releases_json="$TEMP_DIR/releases.json"

	api_url="$(api_base_url)/releases"
	log "获取最新Release: $api_url"

	if ! github_api "$api_url" "$releases_json"; then
		log "获取Release列表失败"
		return 1
	fi

	local tag=""
	local idx=0
	while true; do
		tag=$(jsonfilter -i "$releases_json" -e "@[$idx].tag_name" 2>/dev/null) || break
		[ -z "$tag" ] && break
		case "$tag" in
			"$RELEASE_TAG_PREFIX"*)
				LATEST_VERSION="$tag"
				break
				;;
		esac
		idx=$((idx + 1))
	done

	if [ -z "$LATEST_VERSION" ]; then
		log "未找到前缀为 ${RELEASE_TAG_PREFIX} 的 Release"
		return 1
	fi

	log "最新版本: $LATEST_VERSION"
	return 0
}

check_new_version() {
	CURRENT_VERSION="$(get_current_version)"

	if [ -n "$CURRENT_VERSION" ] && [ "$LATEST_VERSION" = "$CURRENT_VERSION" ]; then
		log "当前固件已是最新版本: $CURRENT_VERSION"
		uci set autoupdate.config.last_seen_version="$LATEST_VERSION"
		uci commit autoupdate
		return 1
	fi

	if [ "$FORCE_AUTO_INSTALL" != "1" ] && [ "$LATEST_VERSION" = "$LAST_SEEN_VERSION" ]; then
		log "该版本已处理: $LATEST_VERSION"
		return 1
	fi

	log "发现新版本: $LATEST_VERSION (当前: ${CURRENT_VERSION:-未知}, 上次处理: ${LAST_SEEN_VERSION:-无})"
	return 0
}

find_firmware_file() {
	local api_url
	local assets_json="$TEMP_DIR/assets.json"

	api_url="$(api_base_url)/releases/tags/${LATEST_VERSION}"
	if ! github_api "$api_url" "$assets_json"; then
		log "获取Release资源列表失败"
		return 1
	fi

	local asset_name=""
	local asset_url=""
	local idx=0

	while true; do
		asset_name=$(jsonfilter -i "$assets_json" -e "@.assets[$idx].name" 2>/dev/null) || break
		[ -z "$asset_name" ] && break

		case "$asset_name" in
			*"$DEVICE_PATTERN"*sysupgrade*.bin)
				asset_url=$(jsonfilter -i "$assets_json" -e "@.assets[$idx].browser_download_url" 2>/dev/null)
				break
				;;
		esac
		idx=$((idx + 1))
	done

	if [ -z "$asset_url" ]; then
		log "Release 中没有同时匹配 ${DEVICE_PATTERN} 和 sysupgrade 的 .bin 文件"
		return 1
	fi

	FIRMWARE_NAME="$asset_name"
	FIRMWARE_URL="$asset_url"
	log "固件: $FIRMWARE_NAME"
	log "URL: $FIRMWARE_URL"
	return 0
}

download_firmware() {
	local output="$DOWNLOAD_DIR/$FIRMWARE_NAME"

	log "下载固件: $FIRMWARE_NAME"
	mkdir -p "$DOWNLOAD_DIR"

	if ! fetch_url "$FIRMWARE_URL" "$output"; then
		log "固件下载失败"
		return 1
	fi

	# Xiaomi Mi Router 4 的完整 sysupgrade 明显大于单独 kernel1；
	# 8MB 下限用于拦截下载错误页、initramfs 和 kernel 分区镜像。
	local size
	size=$(wc -c < "$output" 2>/dev/null)
	if [ -z "$size" ] || [ "$size" -lt 8388608 ]; then
		log "下载的文件太小，可能已损坏: ${size:-0} bytes"
		rm -f "$output"
		return 1
	fi

	if ! sysupgrade -T "$output" >> "$LOG_FILE" 2>&1; then
		log "sysupgrade -T 校验失败，拒绝使用该固件"
		rm -f "$output"
		return 1
	fi

	log "固件下载成功: ${size} bytes"
	FIRMWARE_FILE="$output"
	return 0
}

install_firmware() {
	log "准备安装固件..."

	if [ "$AUTO_INSTALL" != "1" ]; then
		uci set autoupdate.config.last_seen_version="$LATEST_VERSION"
		uci commit autoupdate
		log "自动安装已禁用"
		log "固件已下载到: $FIRMWARE_FILE"
		log "手动安装: sysupgrade $FIRMWARE_FILE"
		return 0
	fi

	if ! sysupgrade -T "$FIRMWARE_FILE" >> "$LOG_FILE" 2>&1; then
		log "刷写前 sysupgrade -T 二次校验失败，已中止"
		return 1
	fi

	uci set autoupdate.config.last_seen_version="$LATEST_VERSION"
	uci commit autoupdate
	log "开始刷写固件..."
	sysupgrade "$FIRMWARE_FILE"

	# 不应该到达这里
	log "固件刷写失败！"
	return 1
}

# ── 主逻辑 ────────────────────────────────────────────────

scheduled_check_due() {
	local now
	local interval_seconds

	now=$(date +%s)
	case "$CHECK_INTERVAL" in
		6hours|hourly)
			interval_seconds=21600
			;;
		weekly)
			interval_seconds=604800
			;;
		daily|*)
			interval_seconds=86400
			;;
	esac

	case "$LAST_CHECK" in
		''|*[!0-9]*) LAST_CHECK=0 ;;
	esac

	if [ $((now - LAST_CHECK)) -lt "$interval_seconds" ]; then
		log "未到检查间隔，跳过本次定时检查"
		return 1
	fi

	uci set autoupdate.config.last_check="$now"
	uci commit autoupdate
	return 0
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

	if ! install_firmware; then
		cleanup
		return 1
	fi

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
	scheduled)
		check_lock
		get_config
		if scheduled_check_due; then
			check_update
		fi
		;;
	install)
		check_lock
		FORCE_AUTO_INSTALL=1
		check_update
		;;
	proxy-test)
		get_config
		start_proxy
		if proxy_available; then
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
		;;
	version)
		get_config
		echo "Current: $(get_current_version)"
		echo "Last seen release: ${LAST_SEEN_VERSION:-none}"
		;;
	*)
		echo "Usage: $0 {check|scheduled|install|proxy-test|version}"
		echo "  check      - Check for updates (download if found)"
		echo "  scheduled  - Check only when configured interval is due"
		echo "  install    - Check and auto-install updates"
		echo "  proxy-test - Test proxy connectivity"
		echo "  version    - Show current version"
		exit 1
		;;
esac
