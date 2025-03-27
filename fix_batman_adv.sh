#!/bin/bash

# 脚本目录和工作目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
OPENWRT_DIR="$SCRIPT_DIR/openwrt"

# 最大重试次数
MAX_RETRY=6

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

# 修复 PKG_VERSION 格式
fix_pkg_version() {
  echo "修复 PKG_VERSION 格式..."
  find . -type f \( -name "Makefile" -o -name "*.mk" \) | while read -r makefile; do
    if grep -q "PKG_VERSION:=.*\..*\..*-[0-9]\+" "$makefile" && ! grep -q "PKG_RELEASE:=" "$makefile"; then
      echo "在 $makefile 中找到目标"
      sed -i.bak -E 's/PKG_VERSION:=([0-9]+\.[0-9]+\.[0-9]+)-([0-9]+)/PKG_VERSION:=\1\nPKG_RELEASE:=\2/' "$makefile"
      echo "修改后的 $makefile:"
      grep -E "PKG_VERSION|PKG_RELEASE" "$makefile"
    fi
  done
}

# 修复依赖项重复
fix_dependency_duplicates() {
  echo "修复依赖项重复..."
  find . -type f \( -name "Makefile" -o -name "*.mk" \) -exec sh -c '
    makefile="$1"
    awk '\''BEGIN { FS = "[[:space:]]+" }
    /^[[:space:]]*(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS):=/ {
        split($0, deps, " ")
        seen_versioned = ""
        seen_bare = ""
        result = $1
        for (i = 2; i <= length(deps); i++) {
            dep = deps[i]
            pos = index(dep, ">=")
            if (pos > 0) {
                bare = substr(dep, 2, pos-2)
            } else {
                bare = substr(dep, 2)
            }
            if (match(dep, />=/)) {
                if (seen_versioned !~ bare) {
                    result = result " " dep
                    seen_versioned = seen_versioned " " bare
                    gsub(" *" bare " *", " ", seen_bare)
                }
            } else {
                if (seen_versioned !~ bare && seen_bare !~ bare) {
                    result = result " " dep
                    seen_bare = seen_bare " " bare
                }
            }
        }
        print result
        next
    }
    { print }
    '\'' "$makefile" > "$makefile.tmp"
    if [ -s "$makefile.tmp" ] && ! cmp -s "$makefile" "$makefile.tmp"; then
      echo "修改后的 $makefile:"
      grep -E "(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS):=" "$makefile.tmp"
      mv "$makefile.tmp" "$makefile"
    else
      rm -f "$makefile.tmp"
    fi
  ' _ {} \;
}

# 第一阶段：仅切换batman-adv组件到指定commit
switch_batman_adv_commit() {
  echo "尝试仅切换batman-adv组件到指定commit..."
  if [ -d "feeds/routing/batman-adv" ]; then
    cd feeds/routing/batman-adv
    git fetch origin
    git checkout 5437d2c91fd9f15e06fbea46677abb529ed3547c
    cd ../../..
    ./scripts/feeds update -i batman-adv
    ./scripts/feeds install -p routing batman-adv
  else
    echo "batman-adv组件目录不存在，尝试完整切换"
    switch_routing_commit
  fi
}

# 第二阶段：切换整个routing仓库
switch_routing_commit() {
  echo "切换整个routing仓库到指定commit..."
  rm -rf feeds/routing
  git clone https://github.com/coolsnowwolf/routing.git feeds/routing
  cd feeds/routing
  git checkout 5437d2c91fd9f15e06fbea46677abb529ed3547c
  cd ../..
  ./scripts/feeds update -i routing
  ./scripts/feeds install -p routing batman-adv
}

# 主逻辑：循环重试
cd "$OPENWRT_DIR"
retry_count=0
while [ $retry_count -lt $MAX_RETRY ]; do
  if compile_batman; then
    echo "编译 batman-adv 成功"
    break
  else
    retry_count=$((retry_count + 1))
    echo "尝试第 $retry_count 次修复..."
    LOG_TAIL=$(tac batman-adv.log | awk '/Entering directory/{count++} count==3{exit}1' | tac)
    [ -z "$LOG_TAIL" ] && LOG_TAIL=$(tail -n 100 batman-adv.log)
    echo "错误日志摘要："
    echo "$LOG_TAIL"

    # 检查并修复符号冲突
    if grep -q "tasklet_setup" batman-adv.log; then
      patch_backports
    fi

    # 检查并修复 PKG_VERSION 格式错误
    if grep -q "PKG_VERSION" batman-adv.log; then
      fix_pkg_version
    fi

    # 检查并修复依赖项重复错误
    if grep -q "DEPENDS" batman-adv.log; then
      fix_dependency_duplicates
    fi

    # 确保配置正确
    ensure_config

    # 如果达到最大重试次数，切换到指定 commit
    if [ $retry_count -eq $MAX_RETRY ]; then
      # 先尝试仅切换组件
      switch_batman_adv_commit
      if compile_batman; then
        echo "切换batman-adv组件后编译成功"
      else
        # 组件切换失败则切换整个仓库
        switch_routing_commit
        if compile_batman; then
          echo "切换整个routing仓库后编译成功"
        else
          echo "所有尝试均失败，退出"
          exit 1
        fi
      fi
    fi
  fi
done
