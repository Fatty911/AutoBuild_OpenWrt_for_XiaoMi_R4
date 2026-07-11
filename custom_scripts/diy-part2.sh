#!/bin/bash
#
# Copyright (c) 2019-2020 P3TERX <https://p3terx.com>
#
# This is free software, licensed under the MIT License.
# See /LICENSE for more information.
#
# https://github.com/P3TERX/Actions-OpenWrt
# File name: diy-part2.sh
# Description: OpenWrt DIY script part 2 (After Update feeds)
#

# ========================================
# 网络个性化配置（从环境变量读取）
# Fork 后不设 secrets 时，LAN 仍使用本仓库约定的 192.168.88.1
# ========================================

# --- LAN 管理地址 ---
# 默认 192.168.88.1；LAN_IP Secret 可显式覆盖
LAN_IP="${LAN_IP:-192.168.88.1}"
if [ -n "$LAN_IP" ] && [ "$LAN_IP" != "192.168.1.1" ]; then
    sed -i "s/192.168.1.1/${LAN_IP}/g" package/base-files/files/bin/config_generate
    echo "LAN 地址已设置为: $LAN_IP"
else
    echo "LAN 地址已显式设置为 OpenWrt 默认: 192.168.1.1"
fi

# --- WiFi SSID 和密码 ---
# 通过 UCI defaults 脚本在首次启动时应用
# 不设则保持 OpenWrt 默认（SSID=OpenWrt，无密码）
WIFI_SSID="${WIFI_SSID:-}"
WIFI_PASSWORD="${WIFI_PASSWORD:-}"
WIFI_BLACKLIST="${WIFI_BLACKLIST:-}"

if [ -n "$WIFI_SSID" ] || [ -n "$WIFI_PASSWORD" ] || [ -n "$WIFI_BLACKLIST" ]; then
    echo "生成 WiFi 个性化配置 UCI defaults 脚本..."
    mkdir -p package/base-files/files/etc/uci-defaults

    # 生成配置值文件（构建时写入，首次启动时由 UCI defaults 脚本读取）
    mkdir -p package/base-files/files/etc
    {
        echo "WIFI_SSID=$WIFI_SSID"
        echo "WIFI_PASSWORD=$WIFI_PASSWORD"
        echo "WIFI_BLACKLIST=$WIFI_BLACKLIST"
    } > package/base-files/files/etc/wifi-custom.conf

    # 生成 UCI defaults 脚本（静态内容，读取配置文件）
    cat > package/base-files/files/etc/uci-defaults/zzz-wifi-custom << 'SCRIPT_END'
#!/bin/sh

# WiFi 个性化配置（首次启动时执行）
# 读取 /etc/wifi-custom.conf 中的配置值

CONFIG_FILE="/etc/wifi-custom.conf"
[ -f "$CONFIG_FILE" ] || exit 0

. "$CONFIG_FILE"

# SSID
if [ -n "$WIFI_SSID" ]; then
    uci set wireless.default_radio0.ssid="$WIFI_SSID"
    uci set wireless.default_radio1.ssid="$WIFI_SSID"
fi

# 密码
if [ -n "$WIFI_PASSWORD" ]; then
    uci set wireless.default_radio0.encryption='psk2'
    uci set wireless.default_radio0.key="$WIFI_PASSWORD"
    uci set wireless.default_radio1.encryption='psk2'
    uci set wireless.default_radio1.key="$WIFI_PASSWORD"
fi

# MAC 黑名单（deny 模式，逗号分隔的 MAC 地址）
if [ -n "$WIFI_BLACKLIST" ]; then
    uci set wireless.default_radio0.macfilter='deny'
    uci set wireless.default_radio1.macfilter='deny'
    OLD_IFS="$IFS"
    IFS=','
    for mac in $WIFI_BLACKLIST; do
        mac=$(echo "$mac" | tr -d ' ')
        uci add_list wireless.default_radio0.maclist="$mac"
        uci add_list wireless.default_radio1.maclist="$mac"
    done
    IFS="$OLD_IFS"
fi

uci commit wireless
rm -f "$CONFIG_FILE"
exit 0
SCRIPT_END

    chmod +x package/base-files/files/etc/uci-defaults/zzz-wifi-custom

    [ -n "$WIFI_SSID" ] && echo "  WiFi SSID: $WIFI_SSID"
    [ -n "$WIFI_PASSWORD" ] && echo "  WiFi 密码: [已设置]"
    [ -n "$WIFI_BLACKLIST" ] && echo "  WiFi MAC 黑名单: $WIFI_BLACKLIST"
    echo "WiFi 个性化配置完成"
else
    echo "未设置 WiFi 个性化配置，保持 OpenWrt 默认（SSID=OpenWrt，无密码，无黑名单）"
fi

#切换内核版本到5.10
# sed -i '/KERNEL_PATCHVER/cKERNEL_PATCHVER:=5.10' target/linux/ramips/Makefile

#复制内核5.10版本CPU超频补丁


# echo "开始修复 Rust Makefile 以解决 CI 环境下的 llvm.download-ci-llvm 问题"
# RUST_MAKEFILE_PATH="feeds/packages/lang/rust/Makefile"

# if [ -f "$RUST_MAKEFILE_PATH" ]; then
#   echo "找到 Rust Makefile: $RUST_MAKEFILE_PATH"
#   # 检查 Makefile 中是否已经包含了正确的设置
#   if grep -q "echo '.*download-ci-llvm = \"if-unchanged\".*'" "$RUST_MAKEFILE_PATH"; then
#     echo "Rust Makefile 似乎已经包含了正确的 'download-ci-llvm = \"if-unchanged\"' 设置。"
#   else
#     # 尝试定位并修改生成 download-ci-llvm = true 的行
#     # 模式1: echo 'download-ci-llvm = true' >> $(RUSTC_SRC_DIR)/config.toml
#     # 注意: \\\$(RUSTC_SRC_DIR) 用于匹配 Makefile 中的字面量 $(RUSTC_SRC_DIR)
#     #       \"if-unchanged\" 会在 Makefile 的 echo '' 中生成 "if-unchanged"
#     if grep -q "echo 'download-ci-llvm = true' >> \\\$(RUSTC_SRC_DIR)/config.toml" "$RUST_MAKEFILE_PATH"; then
#       echo "找到模式1: echo 'download-ci-llvm = true' ..."
#       sed -i "s|echo 'download-ci-llvm = true' >> \\\$(RUSTC_SRC_DIR)/config.toml|echo 'download-ci-llvm = \"if-unchanged\"' >> \\\$(RUSTC_SRC_DIR)/config.toml|g" "$RUST_MAKEFILE_PATH"
#       echo "已将模式1中的 'true' 修改为 '\"if-unchanged\"'"
#     # 模式2: echo "download-ci-llvm = true" >> $(RUSTC_SRC_DIR)/config.toml
#     #       \\\"if-unchanged\\\" 会在 Makefile 的 echo "" 中生成 \"if-unchanged\" (即 "if-unchanged")
#     elif grep -q "echo \"download-ci-llvm = true\" >> \\\$(RUSTC_SRC_DIR)/config.toml" "$RUST_MAKEFILE_PATH"; then
#       echo "找到模式2: echo \"download-ci-llvm = true\" ..."
#       sed -i "s|echo \"download-ci-llvm = true\" >> \\\$(RUSTC_SRC_DIR)/config.toml|echo \"download-ci-llvm = \\\"if-unchanged\\\"\" >> \\\$(RUSTC_SRC_DIR)/config.toml|g" "$RUST_MAKEFILE_PATH"
#       echo "已将模式2中的 'true' 修改为 '\\\"if-unchanged\\\"'"
#     else
#       echo "警告: 未能在 $RUST_MAKEFILE_PATH 中找到预期的 'download-ci-llvm = true' 配置行。"
#       echo "请手动检查该文件，确保 Rust 构建配置正确。"
#     fi

#     # 验证修改
#     echo "修改后的相关行："
#     grep "download-ci-llvm" "$RUST_MAKEFILE_PATH" || echo "(未找到包含 download-ci-llvm 的行)"
#   fi
# else
#   echo "警告: 未找到 Rust Makefile ($RUST_MAKEFILE_PATH)。无法应用修复。"
# fi
# echo "Rust Makefile 修复尝试完成。"

# ========================================
# 集成自动更新插件
# ========================================
echo "集成自动更新插件..."

# 复制 luci-app-autoupdate 到 package 目录
if [ -d "$GITHUB_WORKSPACE/package/luci-app-autoupdate" ]; then
    cp -r "$GITHUB_WORKSPACE/package/luci-app-autoupdate" package/
    echo "已复制 luci-app-autoupdate"
fi

# 从环境变量读取配置并注入
AUTOPDATE_GITHUB_REPO="${AUTOPDATE_GITHUB_REPO:-Fatty911/AutoBuild_OpenWrt_for_XiaoMi_R4}"
AUTOPDATE_UPDATE_BASE_URL="${AUTOPDATE_UPDATE_BASE_URL:-}"
AUTOPDATE_PROXY_PORT="${AUTOPDATE_PROXY_PORT:-1080}"
AUTOPDATE_CHECK_INTERVAL="${AUTOPDATE_CHECK_INTERVAL:-daily}"
AUTOPDATE_AUTO_INSTALL="${AUTOPDATE_AUTO_INSTALL:-0}"
AUTOPDATE_RELEASE_TAG_PREFIX="${AUTOPDATE_RELEASE_TAG_PREFIX:-OpenWRT.org_Kernel_}"
ENABLE_XRAY="${ENABLE_XRAY:-0}"

case "$AUTOPDATE_GITHUB_REPO" in
  */*) ;;
  *) echo "AUTOPDATE_GITHUB_REPO 必须是 owner/repo"; exit 1 ;;
esac
if [ -n "$AUTOPDATE_UPDATE_BASE_URL" ]; then
  case "$AUTOPDATE_UPDATE_BASE_URL" in
    http://*|https://*) ;;
    *) echo "AUTOPDATE_UPDATE_BASE_URL 必须是 HTTP(S) URL"; exit 1 ;;
  esac
  if printf '%s' "$AUTOPDATE_UPDATE_BASE_URL" | grep -q '[[:space:]]'; then
    echo "AUTOPDATE_UPDATE_BASE_URL 不能包含空白字符"
    exit 1
  fi
fi
case "$AUTOPDATE_PROXY_PORT" in ''|*[!0-9]*|0) echo "AUTOPDATE_PROXY_PORT 无效"; exit 1 ;; esac
[ "$AUTOPDATE_PROXY_PORT" -le 65535 ] || { echo "AUTOPDATE_PROXY_PORT 必须是 1-65535"; exit 1; }
case "$AUTOPDATE_CHECK_INTERVAL" in 6hours|daily|weekly) ;; *) echo "AUTOPDATE_CHECK_INTERVAL 必须是 6hours、daily 或 weekly"; exit 1 ;; esac
case "$AUTOPDATE_AUTO_INSTALL" in 0|1) ;; *) echo "AUTOPDATE_AUTO_INSTALL 必须是 0 或 1"; exit 1 ;; esac
case "$ENABLE_XRAY" in 0|1) ;; *) echo "ENABLE_XRAY 必须是 0 或 1"; exit 1 ;; esac

sed -i \
  -e '/^CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_NONE_V2RAY=/d' \
  -e '/^CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Xray=/d' \
  -e '/^CONFIG_PACKAGE_xray-core=/d' \
  .config
if [ "$ENABLE_XRAY" = "1" ]; then
  {
    echo "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_NONE_V2RAY=n"
    echo "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Xray=y"
    echo "CONFIG_PACKAGE_xray-core=y"
  } >> .config
else
  {
    echo "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_NONE_V2RAY=y"
    echo "CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Xray=n"
    echo "CONFIG_PACKAGE_xray-core=n"
  } >> .config
fi

echo "自动更新配置:"
echo "  GitHub仓库: $AUTOPDATE_GITHUB_REPO"
echo "  更新服务: ${AUTOPDATE_UPDATE_BASE_URL:-GitHub Release API}"
echo "  代理端口: $AUTOPDATE_PROXY_PORT"
echo "  自动刷写: $AUTOPDATE_AUTO_INSTALL"
echo "  检查间隔: $AUTOPDATE_CHECK_INTERVAL"
echo "  Xray: $ENABLE_XRAY"

# 创建默认配置
mkdir -p files/etc/config
cat > files/etc/config/autoupdate << EOF
config autoupdate 'config'
    option enabled '1'
    option github_repo '$AUTOPDATE_GITHUB_REPO'
    option update_base_url '$AUTOPDATE_UPDATE_BASE_URL'
    option github_token ''
    option proxy_service 'auto'
    option proxy_port '$AUTOPDATE_PROXY_PORT'
    option check_interval '$AUTOPDATE_CHECK_INTERVAL'
    option release_tag_prefix '$AUTOPDATE_RELEASE_TAG_PREFIX'
    option device_pattern 'mi-router-4'
    option last_seen_version ''
    option last_check '0'
    option auto_install '$AUTOPDATE_AUTO_INSTALL'
EOF

mkdir -p package/luci-app-autoupdate/root/etc/crontabs
cat > package/luci-app-autoupdate/root/etc/crontabs/root << 'EOF'
# Hourly scheduler; autoupdate.sh enforces the LuCI interval setting.
17 * * * * /usr/bin/autoupdate.sh scheduled >> /var/log/autoupdate.log 2>&1
EOF

echo "自动更新插件配置完成"

echo "修复 DTS nvmem-layout 兼容性..."
if [ -f "$GITHUB_WORKSPACE/custom_scripts/fix_dts_nvmem_layout.py" ]; then
  python3 "$GITHUB_WORKSPACE/custom_scripts/fix_dts_nvmem_layout.py" .
else
  echo "fix_dts_nvmem_layout.py 不存在，跳过 DTS 修复"
fi
