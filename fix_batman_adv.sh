#!/bin/bash

# 脚本目录和工作目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
OPENWRT_DIR="$SCRIPT_DIR/openwrt"

# 编译 batman-adv 的函数
compile_batman() {
  cd "$OPENWRT_DIR"
  make -j1 V=s package/feeds/routing/batman-adv/compile > batman-adv.log 2>&1
}

# 修复 tasklet_setup 符号冲突
patch_backports() {
  echo "尝试修复 tasklet_setup 符号冲突..."
  sed -i '/tasklet_setup/d' build_dir/target-mipsel_24kc_musl/linux-ramips_mt7621/backports-6.1.24/backport-include/linux/interrupt.h
}

# 确保 batman-adv 依赖配置
ensure_config() {
  echo "确保 batman-adv 依赖配置..."
  echo "CONFIG_BATMAN_ADV=y" >> .config
  echo "CONFIG_BATMAN_ADV_BATMAN_V=y" >> .config
  echo "CONFIG_BATMAN_ADV_BLA=y" >> .config
  echo "CONFIG_BATMAN_ADV_DAT=y" >> .config
  echo "CONFIG_BATMAN_ADV_NC=y" >> .config
  echo "CONFIG_BATMAN_ADV_MCAST=y" >> .config
  echo "CONFIG_BATMAN_ADV_DEBUG=y" >> .config
  make defconfig
}

# 切换到指定 commit
switch_to_commit() {
  echo "所有修复尝试失败，切换到指定的 batman-adv commit..."
  rm -rf feeds/routing/batman-adv
  git clone https://github.com/coolsnowwolf/routing.git feeds/routing
  cd feeds/routing
  git checkout 5437d2c91fd9f15e06fbea46677abb529ed3547c
  cd ../..
  ./scripts/feeds update -i
  ./scripts/feeds install -p routing batman-adv
}

# 主逻辑
cd "$OPENWRT_DIR"
if ! compile_batman; then
  echo "初次编译 batman-adv 失败，查看错误日志："
  LOG_TAIL=$(tac batman-adv.log | awk '/Entering directory/{count++} count==3{exit}1' | tac)
  [ -z "$LOG_TAIL" ] && LOG_TAIL=$(tail -n 100 batman-adv.log)
  echo "$LOG_TAIL"
  # 尝试修复符号冲突
  patch_backports
  if ! compile_batman; then
    echo "修复符号冲突失败，再次尝试编译失败，检查配置..."
    ensure_config
    if ! compile_batman; then
      echo "配置修复后仍失败，切换到指定 commit..."
      switch_to_commit
      if ! compile_batman; then
        echo "所有尝试均失败，退出"
        exit 1
      else
        echo "切换 commit 后编译成功"
      fi
    else
      echo "配置修复后编译成功"
    fi
  else
    echo "修复符号冲突后编译成功"
  fi
else
  echo "初次编译 batman-adv 成功"
fi