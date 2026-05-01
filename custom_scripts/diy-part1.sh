#!/bin/bash
#
# Copyright (c) 2019-2020 P3TERX <https://p3terx.com>
#
# This is free software, licensed under the MIT License.
# See /LICENSE for more information.
#
# https://github.com/P3TERX/Actions-OpenWrt
# File name: diy-part1.sh
# Description: OpenWrt DIY script part 1 (Before Update feeds)
#

# Uncomment a feed source
#sed -i 's/^#\(.*helloworld\)/\1/' feeds.conf.default

# Add a feed source
echo 'src-git helloworld https://github.com/fw876/helloworld' >>feeds.conf.default

# === 自动防止 APK version invalid 错误（永久修复）===
echo "=== diy-part1: 强制修复 base-files 版本 ==="
mkdir -p package/base-files
if [ -f "package/base-files/Makefile" ]; then
  if grep -q "PKG_RELEASE:=$(COMMITCOUNT)" package/base-files/Makefile; then
    sed -i 's/PKG_RELEASE:=$(COMMITCOUNT)/PKG_RELEASE:=1/' package/base-files/Makefile
    echo "已修复 package/base-files/Makefile 中的 PKG_RELEASE"
  else
    echo 'PKG_RELEASE:=1' >> package/base-files/Makefile
    echo "已追加 PKG_RELEASE:=1 到 base-files/Makefile"
  fi
else
  echo "警告：未找到 package/base-files/Makefile，可能需要 feeds update 后修复"
fi
echo "✅ base-files 版本永久修复完成 (PKG_RELEASE:=1)"
#echo 'src-git passwall2 https://github.com/xiaorouji/openwrt-passwall2' >>feeds.conf.default
#echo 'src-git OpenClash https://github.com/vernesong/OpenClash' >>feeds.conf.default
#echo 'src-git small8 https://github.com/kenzok8/small-package' >>feeds.conf.default
#echo 'src-git kenzo https://github.com/kenzok8/openwrt-packages' >>feeds.conf.default
#echo "src-git qttools https://github.com/openwrt/packages.git;master" >> feeds.conf.default
#echo "src-git lucihttp https://github.com/openwrt/packages.git" >> feeds.conf.default

