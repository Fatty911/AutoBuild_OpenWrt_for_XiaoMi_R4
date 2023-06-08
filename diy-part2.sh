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

# Modify default IP
sed -i 's/192.168.1.1/192.168.88.1/g' package/base-files/files/bin/config_generate

#复制内核5.10版本CPU超频补丁
wget https://github.com/Fatty911/AutoBuild_OpenWRT_for_Mi_R4/blob/main/mt7621_overclocking-322-mt7621-fix-cpu-clk-add-clkdev.patch target/linux/ramips/patches-5.10/
