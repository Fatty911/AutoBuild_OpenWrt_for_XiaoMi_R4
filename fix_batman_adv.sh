#!/bin/bash

# fix_batman_adv.sh
# 专门用于修复 batman-adv 相关编译错误的脚本
# 用法: bash fix_batman_adv.sh <make_command> <log_file> [max_retry]

# --- 配置 ---
BATMAN_ADV_COMMIT="5437d2c91fd9f15e06fbea46677abb529ed3547c" # 已知兼容的 batman-adv/routing feed commit
FEED_ROUTING_NAME="routing" # feeds.conf[.default] 中的 routing feed 名称
FEED_ROUTING_URL="https://github.com/coolsnowwolf/routing.git" # routing feed 的 URL

# --- 参数解析 ---
MAKE_COMMAND="$1"           # 例如 "make -j1 package/feeds/routing/batman-adv/compile V=s"
LOG_FILE="$2"               # 例如 "batman-adv.log"
MAX_RETRY="${3:-5}"         # 默认最大重试次数: 5

# --- 参数检查 ---
if [ -z "$MAKE_COMMAND" ] || [ -z "$LOG_FILE" ]; then
    echo "错误：缺少必要参数。用法: $0 <make_command> <log_file> [max_retry]"
    exit 1
fi

# 确保日志文件存在
touch "$LOG_FILE"

# --- 辅助函数: 提取错误块 ---
extract_error_block() {
    local log_file="$1"
    echo "--- 最近 300 行日志 (${log_file}) ---"
    tail -n 300 "$log_file" 2>/dev/null || echo "日志文件为空或不存在"
    echo "--- 日志结束 ---"
}

# --- 检查函数: 检查当前目录是否为 OpenWrt 根目录 ---
check_openwrt_root() {
    # 检查常见的 OpenWrt 目录和文件
    if [ ! -d "package" ] || [ ! -d "target" ] || [ ! -f "Makefile" ] || [ ! -d "scripts" ]; then
        echo "当前目录不是 OpenWrt 根目录，尝试查找..."
        
        # 尝试查找 OpenWrt 根目录
        local openwrt_dir=""
        for dir in . .. ../.. ../../.. ../../../..; do
            if [ -d "$dir/package" ] && [ -d "$dir/target" ] && [ -f "$dir/Makefile" ] && [ -d "$dir/scripts" ]; then
                openwrt_dir="$dir"
                break
            fi
        done
        
        if [ -n "$openwrt_dir" ]; then
            echo "找到 OpenWrt 根目录: $openwrt_dir"
            cd "$openwrt_dir"
            return 0
        else
            echo "错误: 无法找到 OpenWrt 根目录。"
            return 1
        fi
    fi
    
    return 0
}

# --- 检查函数: 检查 batman-adv 包是否存在 ---
check_batman_adv_exists() {
    echo "检查 batman-adv 包是否存在..."
    
    # 检查 feeds 目录
    if [ ! -d "feeds/$FEED_ROUTING_NAME" ]; then
        echo "feeds/$FEED_ROUTING_NAME 目录不存在，尝试更新 feeds..."
        return 1
    fi
    
    # 检查 batman-adv 包目录
    if [ ! -d "feeds/$FEED_ROUTING_NAME/batman-adv" ]; then
        echo "feeds/$FEED_ROUTING_NAME/batman-adv 目录不存在，尝试更新 feeds..."
        return 1
    fi
    
    # 检查 package/feeds 目录
    if [ ! -d "package/feeds/$FEED_ROUTING_NAME" ]; then
        echo "package/feeds/$FEED_ROUTING_NAME 目录不存在，尝试安装 feeds..."
        return 1
    fi
    
    # 检查 package/feeds/routing/batman-adv 目录
    if [ ! -d "package/feeds/$FEED_ROUTING_NAME/batman-adv" ]; then
        echo "package/feeds/$FEED_ROUTING_NAME/batman-adv 目录不存在，尝试安装 feeds..."
        return 1
    fi
    
    echo "batman-adv 包存在。"
    return 0
}

# --- 修复函数: 更新和安装 feeds ---
fix_update_feeds() {
    echo "更新和安装 feeds..."
    
    # 检查 feeds.conf 文件
    local feed_conf_file="feeds.conf.default"
    if [ -f "feeds.conf" ]; then
        feed_conf_file="feeds.conf"
    fi
    
    # 如果 feeds.conf.default 不存在，尝试创建
    if [ ! -f "$feed_conf_file" ]; then
        echo "未找到 $feed_conf_file，尝试创建..."
        if [ -f "feeds.conf.default.bak" ]; then
            cp "feeds.conf.default.bak" "$feed_conf_file"
        elif [ -f "feeds.conf.bak" ]; then
            cp "feeds.conf.bak" "$feed_conf_file"
        else
            # 创建一个基本的 feeds.conf 文件
            echo "创建基本的 $feed_conf_file 文件..."
            cat > "$feed_conf_file" << EOF
src-git packages https://github.com/coolsnowwolf/packages
src-git luci https://github.com/coolsnowwolf/luci
src-git $FEED_ROUTING_NAME $FEED_ROUTING_URL
EOF
        fi
    fi
    
    # 检查 routing feed 是否在 feeds.conf 中
    if ! grep -q "^src-git $FEED_ROUTING_NAME" "$feed_conf_file"; then
        echo "在 $feed_conf_file 中添加 $FEED_ROUTING_NAME feed..."
        echo "src-git $FEED_ROUTING_NAME $FEED_ROUTING_URL" >> "$feed_conf_file"
    fi
    
    # 检查 scripts/feeds 是否存在
    if [ ! -f "scripts/feeds" ]; then
        echo "错误: scripts/feeds 不存在，可能不是 OpenWrt 根目录。"
        return 1
    fi
    
    # 更新 feeds
    echo "执行 ./scripts/feeds update -a"
    ./scripts/feeds update -a || {
        echo "更新 feeds 失败，尝试单独更新 $FEED_ROUTING_NAME..."
        ./scripts/feeds update "$FEED_ROUTING_NAME" || {
            echo "更新 $FEED_ROUTING_NAME feed 失败。"
            return 1
        }
    }
    
    # 安装 feeds
    echo "执行 ./scripts/feeds install -a"
    ./scripts/feeds install -a || {
        echo "安装 feeds 失败，尝试单独安装 $FEED_ROUTING_NAME..."
        ./scripts/feeds install -a -p "$FEED_ROUTING_NAME" || {
            echo "安装 $FEED_ROUTING_NAME feed 失败。"
            return 1
        }
    }
    
    # 特别安装 batman-adv
    echo "特别安装 batman-adv..."
    ./scripts/feeds install -p "$FEED_ROUTING_NAME" batman-adv || {
        echo "安装 batman-adv 失败。"
        return 1
    }
    
    # 检查安装结果
    if [ -d "package/feeds/$FEED_ROUTING_NAME/batman-adv" ]; then
        echo "batman-adv 安装成功。"
        return 0
    else
        echo "batman-adv 安装失败，目录不存在。"
        return 1
    fi
}

# --- 修复函数: 修补 batman-adv 的 multicast.c 文件 ---
fix_batman_multicast_struct() {
    local log_file="$1"
    echo "尝试修补 batman-adv 'struct br_ip' 错误..." >&2
    
    # 定位源目录中的 multicast.c
    local pkg_dir=$(find feeds -type d -name "batman-adv" -print -quit)
    if [ -z "$pkg_dir" ]; then
        echo "无法找到 batman-adv 包目录。" >&2
        return 1
    fi
    local multicast_file="$pkg_dir/net/batman-adv/multicast.c"
    if [ ! -f "$multicast_file" ]; then
        echo "在 $pkg_dir 中未找到 multicast.c 文件。" >&2
        return 1
    fi

    echo "正在修补 $multicast_file..." >&2
    cp "$multicast_file" "$multicast_file.bak"

    # 替换所有 'dst.ip4' 和 'dst.ip6' 为 'u.ip4' 和 'u.ip6'
    sed -i 's/dst\.ip4/u.ip4/g' "$multicast_file"
    sed -i 's/dst\.ip6/u.ip6/g' "$multicast_file"
    # 替换 br_multicast_has_router_adjacent
    sed -i 's/br_multicast_has_router_adjacent/br_multicast_has_querier_adjacent/g' "$multicast_file"

    # 检查修补是否成功
    if ! grep -q 'dst\.ip[4|6]' "$multicast_file" && \
       ! grep -q 'br_multicast_has_router_adjacent' "$multicast_file"; then
        echo "成功修补 $multicast_file" >&2
        # 触摸 Makefile 以触发重新编译
        local pkg_makefile="$pkg_dir/Makefile"
        if [ -f "$pkg_makefile" ]; then
            touch "$pkg_makefile"
            echo "已触摸 $pkg_makefile 以强制重建。" >&2
        fi
        # 清理构建目录以确保使用修补后的文件
        make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" V=s || echo "警告: 清理 batman-adv 失败。" >&2
        rm -f "$multicast_file.bak"
        return 0
    else
        echo "修补 $multicast_file 失败，正在恢复备份。" >&2
        echo "剩余的 'dst' 模式:" >&2
        grep 'dst\.ip[4|6]' "$multicast_file" >&2 || echo "无匹配，但检查逻辑失败。" >&2
        [ -f "$multicast_file.bak" ] && mv "$multicast_file.bak" "$multicast_file"
        return 1
    fi
}

# --- 修复函数: 切换到兼容的 batman-adv feed commit ---
fix_batman_switch_feed() {
    local target_commit="$1"
    local feed_name="$FEED_ROUTING_NAME"
    local feed_conf_file="feeds.conf.default"

    if [ -f "feeds.conf" ]; then
        feed_conf_file="feeds.conf"
        echo "使用 feeds.conf 文件。"
    fi

    echo "尝试切换 $feed_name feed 至 commit $target_commit..."
    if grep -q "^src-git $feed_name" "$feed_conf_file"; then
        sed -i "s|^src-git $feed_name .*|src-git $feed_name $FEED_ROUTING_URL;$target_commit|" "$feed_conf_file"
    else
        echo "src-git $feed_name $FEED_ROUTING_URL;$target_commit" >> "$feed_conf_file"
    fi

    if grep -q "src-git $feed_name $FEED_ROUTING_URL;$target_commit" "$feed_conf_file"; then
        echo "成功更新 $feed_conf_file 中的 $feed_name feed 配置。"
        ./scripts/feeds update "$feed_name" || echo "警告: feeds update $feed_name 失败"
        ./scripts/feeds install -a -p "$feed_name" || echo "警告: feeds install -a -p $feed_name 失败"
        ./scripts/feeds install -p "$feed_name" batman-adv || echo "警告: 安装 batman-adv 失败"
        make "package/feeds/$feed_name/batman-adv/clean" V=s || echo "警告: 清理 batman-adv 失败。"
        return 0
    else
        echo "更新 $feed_conf_file 失败。"
        return 1
    fi
}

# --- 修复函数: 在 batman-adv Makefile 中禁用 -Werror ---
fix_batman_disable_werror() {
    local batman_makefile="package/feeds/$FEED_ROUTING_NAME/batman-adv/Makefile"

    echo "尝试在 batman-adv Makefile 中禁用 -Werror..."
    if [ -f "$batman_makefile" ]; then
        if ! grep -qE 'filter-out -Werror|\$\(filter-out -Werror' "$batman_makefile"; then
            echo "正在修改 $batman_makefile..."
            awk '
            /include \.\.\/\.\.\/package.mk|include \$\(TOPDIR\)\/rules\.mk/ {
              print ""
              print "# Disable -Werror for this package"
              print "TARGET_CFLAGS:=$(filter-out -Werror,$(TARGET_CFLAGS))"
              print ""
            }
            { print }
            ' "$batman_makefile" > "$batman_makefile.tmp"

            if [ $? -eq 0 ] && [ -s "$batman_makefile.tmp" ] && ! cmp -s "$batman_makefile" "$batman_makefile.tmp" ; then
                 mv "$batman_makefile.tmp" "$batman_makefile"
                 echo "已在 $batman_makefile 中添加 CFLAGS 过滤。"
                 make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" V=s || echo "警告: 清理 batman-adv 失败。"
                 return 0
            else
                 echo "错误: 使用 awk 修改 $batman_makefile 失败或无更改。"
                 rm -f "$batman_makefile.tmp"
                 return 1
            fi
        else
            echo "$batman_makefile 中似乎已禁用 -Werror。"
            return 0
        fi
    else
        echo "未找到 $batman_makefile。"
        return 1
    fi
}

# --- 修复函数: 修复 batman-adv 的 tasklet_setup 错误 ---
fix_batman_patch_tasklet() {
    echo "尝试修补 batman-adv 的 tasklet_setup 错误..."
    
    # 查找 backports 目录
    local backports_dir=$(find feeds -path "*/batman-adv/compat-sources/backports" -type d -print -quit)
    if [ -z "$backports_dir" ]; then
        echo "无法找到 batman-adv 的 backports 目录。"
        return 1
    fi
    
    echo "找到 backports 目录: $backports_dir"
    
    # 查找 compat.h 文件
    local compat_file="$backports_dir/include/linux/compat-2.6.h"
    if [ ! -f "$compat_file" ]; then
        echo "未找到 compat-2.6.h 文件。"
        return 1
    fi
    
    echo "正在修补 $compat_file..."
    cp "$compat_file" "$compat_file.bak"
    
    # 添加 tasklet_setup 兼容定义
    if ! grep -q "tasklet_setup" "$compat_file"; then
        echo "
/* Backport tasklet_setup for older kernels */
#if LINUX_VERSION_CODE < KERNEL_VERSION(5,9,0)
static inline void tasklet_setup(struct tasklet_struct *t,
                                void (*callback)(struct tasklet_struct *))
{
    void (*tasklet_func)(unsigned long data);
    
    tasklet_func = (void (*)(unsigned long))callback;
    tasklet_init(t, tasklet_func, (unsigned long)t);
}
#endif
" >> "$compat_file"
        
        echo "已添加 tasklet_setup 兼容定义。"
        
        # 清理构建目录
        make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" V=s || echo "警告: 清理 batman-adv 失败。"
        return 0
    else
        echo "$compat_file 中已存在 tasklet_setup 定义。"
        rm -f "$compat_file.bak"
        return 0
    fi
}

# --- 修复函数: 修改编译命令 ---
fix_compile_command() {
    local original_command="$1"
    
    # 检查命令是否包含 package/feeds/routing/batman-adv/compile
    if [[ "$original_command" == *"package/feeds/routing/batman-adv/compile"* ]]; then
        # 尝试使用 package/feeds/routing/batman-adv 而不是 package/feeds/routing/batman-adv/compile
        local new_command="${original_command/package\/feeds\/routing\/batman-adv\/compile/package\/feeds\/routing\/batman-adv}"
        echo "修改编译命令: $original_command -> $new_command"
        return 0
    else
        echo "编译命令无需修改。"
        return 1
    fi
}

# --- 修复函数: 尝试直接安装 batman-adv 包 ---
fix_install_batman_directly() {
    echo "尝试直接安装 batman-adv 包..."
    
    # 检查是否有 batman-adv 包可用
    if ! make menuconfig -j1 | grep -q "batman-adv"; then
        echo "在 menuconfig 中未找到 batman-adv 包。"
        return 1
    fi
    
    # 尝试直接编译 batman-adv
    echo "尝试直接编译 batman-adv..."
    make package/batman-adv/compile V=s || {
        echo "直接编译 batman-adv 失败。"
        return 1
    }
    
    echo "batman-adv 直接编译成功。"
    return 0
}

# --- 主循环 ---
echo "--------------------------------------------------"
echo "开始修复 batman-adv 编译问题..."
echo "--------------------------------------------------"

# 检查并切换到 OpenWrt 根目录
if ! check_openwrt_root; then
    echo "错误: 无法找到 OpenWrt 根目录，脚本将退出。"
    exit 1
fi

# 初始化状态标志
batman_exists_checked=0
feeds_updated=0
batman_multicast_patched=0
batman_werror_disabled=0
batman_feed_switched=0
batman_tasklet_patched=0
command_fixed=0
direct_install_tried=0
retry_count=0

# 主循环
while [ $retry_count -lt $MAX_RETRY ]; do
    echo "--------------------------------------------------"
    echo "尝试编译: $MAKE_COMMAND (第 $((retry_count + 1)) / $MAX_RETRY 次)..."
    echo "--------------------------------------------------"

    # 运行编译命令并捕获输出到临时日志文件
    $MAKE_COMMAND > "$LOG_FILE.tmp" 2>&1
    COMPILE_STATUS=$?

    # 检查编译是否成功
    if [ $COMPILE_STATUS -eq 0 ] && ! grep -q -E "error:|failed|undefined reference" "$LOG_FILE.tmp"; then
        echo "编译成功！"
        cat "$LOG_FILE.tmp" >> "$LOG_FILE" # 追加成功日志
        rm -f "$LOG_FILE.tmp"
        exit 0
    else
        echo "编译失败 (退出码: $COMPILE_STATUS)，检查错误..."
        extract_error_block "$LOG_FILE.tmp"
    fi

    # 错误检测和修复逻辑
    fix_applied=0

    # 检查 "No rule to make target" 错误
    if grep -q "No rule to make target 'package/feeds/routing/batman-adv/compile'" "$LOG_FILE.tmp"; then
        echo "检测到 'No rule to make target' 错误..."
        
        # 首先检查 batman-adv 包是否存在
        if [ $batman_exists_checked -eq 0 ]; then
            batman_exists_checked=1
            if ! check_batman_adv_exists; then
                echo "batman-adv 包不存在，尝试更新和安装 feeds..."
                if fix_update_feeds; then
                    fix_applied=1
                    feeds_updated=1
                    echo "feeds 更新和安装成功，将重试编译..."
                else
                    echo "feeds 更新和安装失败。"
                fi
            fi
        fi
        
        # 如果包存在但命令有问题，尝试修改命令
        if [ $command_fixed -eq 0 ] && [ $feeds_updated -eq 1 ]; then
            command_fixed=1
            NEW_COMMAND="$MAKE_COMMAND"
            if fix_compile_command "$MAKE_COMMAND"; then
                NEW_COMMAND="${MAKE_COMMAND/package\/feeds\/routing\/batman-adv\/compile/package\/feeds\/routing\/batman-adv}"
                echo "修改编译命令: $MAKE_COMMAND -> $NEW_COMMAND"
                MAKE_COMMAND="$NEW_COMMAND"
                fix_applied=1
            fi
        fi
        
        # 尝试直接安装 batman-adv
        if [ $direct_install_tried -eq 0 ] && [ $fix_applied -eq 0 ]; then
            direct_install_tried=1
            if fix_install_batman_directly; then
                fix_applied=1
                echo "直接安装 batman-adv 成功，将重试编译..."
            else
                echo "直接安装 batman-adv 失败。"
            fi
        fi
    # 检查 struct br_ip 错误
    elif grep -q "struct br_ip.*has no member named.*dst" "$LOG_FILE.tmp" || \
         grep -q "dst\.ip[4|6]" "$LOG_FILE.tmp" && grep -q "batman-adv.*multicast\.c" "$LOG_FILE.tmp"; then
        echo "检测到 batman-adv struct br_ip 'dst' 错误..."
        if [ $batman_multicast_patched -eq 0 ]; then
            if fix_batman_multicast_struct "$LOG_FILE.tmp"; then
                fix_applied=1
                batman_multicast_patched=1
                echo "修补成功，将重试编译..."
            else
                batman_multicast_patched=1
                echo "修补 multicast.c 失败，将尝试其他修复方法..."
            fi
        fi
    # 检查 -Werror 错误
    elif grep -q "cc1: some warnings being treated as errors" "$LOG_FILE.tmp" && grep -q "batman-adv" "$LOG_FILE.tmp"; then
        echo "检测到 batman-adv -Werror 错误..."
        if [ $batman_werror_disabled -eq 0 ]; then
            if fix_batman_disable_werror; then
                fix_applied=1
                batman_werror_disabled=1
                echo "已禁用 -Werror，将重试编译..."
            else
                batman_werror_disabled=1
                echo "禁用 -Werror 失败，将尝试其他修复方法..."
            fi
        fi
    # 检查 tasklet_setup 错误
    elif grep -q 'undefined reference to .*tasklet_setup' "$LOG_FILE.tmp" && grep -q -B 10 -A 10 -E 'batman-adv|backports|compat' "$LOG_FILE.tmp"; then
        echo "检测到 batman-adv 的 'tasklet_setup' 符号错误..."
        if [ $batman_tasklet_patched -eq 0 ]; then
            if fix_batman_patch_tasklet; then
                fix_applied=1
                batman_tasklet_patched=1
                echo "已添加 tasklet_setup 兼容定义，将重试编译..."
            else
                batman_tasklet_patched=1
                echo "修补 tasklet_setup 失败，将尝试其他修复方法..."
            fi
        fi
    # 通用 batman-adv 错误，尝试切换 feed
    elif grep -q -E "batman-adv.*error:|batman-adv.*failed" "$LOG_FILE.tmp" && [ $batman_feed_switched -eq 0 ]; then
        echo "检测到通用 batman-adv 错误，尝试切换 feed..."
        if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
            fix_applied=1
            batman_feed_switched=1
            echo "已切换 feed 到 commit $BATMAN_ADV_COMMIT，将重试编译..."
        else
            batman_feed_switched=1
            echo "切换 feed 失败。"
        fi
    else
        echo "未检测到已知的 batman-adv 错误模式，但编译失败。"
        
        # 如果是第一次运行且没有应用任何修复，尝试更新 feeds
        if [ $retry_count -eq 0 ] && [ $feeds_updated -eq 0 ]; then
            echo "尝试更新和安装 feeds..."
            if fix_update_feeds; then
                fix_applied=1
                feeds_updated=1
                echo "feeds 更新和安装成功，将重试编译..."
            fi
        fi
    fi

    # 如果没有应用任何修复但已尝试所有修复方法，则退出
    if [ $fix_applied -eq 0 ] && [ $feeds_updated -eq 1 ] && [ $batman_multicast_patched -eq 1 ] && 
       [ $batman_werror_disabled -eq 1 ] && [ $batman_feed_switched -eq 1 ] && 
       [ $batman_tasklet_patched -eq 1 ] && [ $command_fixed -eq 1 ] && [ $direct_install_tried -eq 1 ]; then
        echo "所有修复方法都已尝试，但无法解决问题。"
        cat "$LOG_FILE.tmp" >> "$LOG_FILE"
        rm -f "$LOG_FILE.tmp"
        exit 1
    fi

    # 清理临时日志
    cat "$LOG_FILE.tmp" >> "$LOG_FILE"  # 追加到主日志文件
    rm -f "$LOG_FILE.tmp"
    
    retry_count=$((retry_count + 1))
    echo "等待 3 秒后重试..."
    sleep 3
done

# 达到最大重试次数
echo "--------------------------------------------------"
echo "达到最大重试次数 ($MAX_RETRY)，编译最终失败。"
echo "--------------------------------------------------"
extract_error_block "$LOG_FILE"
echo "请检查完整日志: $LOG_FILE"
exit 1
