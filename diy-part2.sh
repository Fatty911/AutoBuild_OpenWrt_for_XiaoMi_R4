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

#切换内核版本到5.10
# sed -i '/KERNEL_PATCHVER/cKERNEL_PATCHVER:=5.10' target/linux/ramips/Makefile

#复制内核5.10版本CPU超频补丁
#wget -O target/linux/ramips/patches-5.10/322-mt7621-fix-cpu-clk-add-clkdev.patch https://github.com/Fatty911/AutoBuild_OpenWRT_for_Mi_R4/blob/main/mt7621_overclocking-322-mt7621-fix-cpu-clk-add-clkdev.patch 

RUST_MAKEFILE="feeds/packages/lang/rust/Makefile"
if [ -f "$RUST_MAKEFILE" ]; then
  echo "Patching Rust Makefile for CI LLVM download fix..."
  # Escape characters for sed: \ for [, ], $ and " inside the string to be added.
  # The pattern matches the line that writes "[llvm]" to config.toml
  # The appended line adds the 'download-ci-llvm' setting.
  # Note: \\\$(RUSTC_SRC_DIR) is used to ensure $(RUSTC_SRC_DIR) is literally passed to sed,
  # and not interpreted by the shell running diy-part2.sh.
  sed -i "/echo '\\\[llvm\\\]' >> \\\$(RUSTC_SRC_DIR)\/config.toml/a \    echo 'download-ci-llvm = \"if-unchanged\"' >> \\\$(RUSTC_SRC_DIR)\/config.toml" "$RUST_MAKEFILE"
  echo "Rust Makefile patched."
else
  echo "Warning: Rust Makefile ($RUST_MAKEFILE) not found. Skipping patch."
fi
