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
