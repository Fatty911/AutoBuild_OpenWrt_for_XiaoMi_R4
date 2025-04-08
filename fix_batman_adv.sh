#!/bin/bash

# fix_batman_adv.sh
# 专门用于修复 batman-adv 相关编译错误的脚本
# 用法: bash fix_batman_adv.sh <make_command> <log_file> [max_retry]

# --- 配置 ---
BATMAN_ADV_COMMIT="5437d2c91fd9f15e06fbea46677abb529ed3547c" # 已知兼容的 batman-adv/routing feed commit
FEED_ROUTING_NAME="routing" # feeds.conf[.default] 中的 routing feed 名称

# --- 参数解析 ---
MAKE_COMMAND="$1"           # 例如 "make -j1 package/feeds/routing/batman-adv/compile V=s"
LOG_FILE="$2"               # 例如 "batman-adv.log"
MAX_RETRY="${3:-5}"         # 默认最大重试次数: 5

# --- 参数检查 ---
if [ -z "$MAKE_COMMAND" ] || [ -z "$LOG_FILE" ]; then
    echo "错误：缺少必要参数。用法: $0 <make_command> <log_file> [max_retry]"
    exit 1
fi

# --- 辅助函数: 提取错误块 ---
extract_error_block() {
    local log_file="$1"
    echo "--- 最近 300 行日志 (${log_file}) ---"
    tail -n 300 "$log_file"
    echo "--- 日志结束 ---"
}

# --- 修复函数: 修补 batman-adv 的 multicast.c 文件 ---
fix_batman_multicast_struct() {
    local log_file="$1"
    echo "尝试修补 batman-adv 'struct br_ip' 错误..." >&2
    echo "日志文件: $log_file" >&2

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
        make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: 清理 batman-adv 失败。" >&2
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
        sed -i "s|^src-git $feed_name .*|src-git $feed_name https://github.com/coolsnowwolf/routing.git;${target_commit}|" "$feed_conf_file"
    else
        echo "src-git $feed_name https://github.com/coolsnowwolf/routing.git;${target_commit}" >> "$feed_conf_file"
    fi

    if grep -q "src-git $feed_name https://github.com/coolsnowwolf/routing.git;${target_commit}" "$feed_conf_file"; then
        echo "成功更新 $feed_conf_file 中的 $feed_name feed 配置。"
        ./scripts/feeds update "$feed_name" || echo "警告: feeds update $feed_name 失败"
        ./scripts/feeds install -a -p "$feed_name" || echo "警告: feeds install -a -p $feed_name 失败"
        make "package/feeds/$feed_name/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: 清理 batman-adv 失败。"
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
                 make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: 清理 batman-adv 失败。"
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
    local log_file="$1"
    echo "尝试修补 batman-adv 的 tasklet_setup 错误..."
    
    # 查找 backports 目录
    local backports_dir=$(find feeds -path "*/batman-adv/compat-sources/backports" -type d -print -quit)
    if [ -z "$backports_dir" ]; then
        echo "无法找到 batman-adv 的 backports 目录。"
        return 1
    fi
    
    # 查找 compat.h 文件
    local compat_file="$backports_dir/include/linux/compat-2.6.h"
    if [ ! -f "$compat_file" ]; then
        compat_file="$backports_dir/include/linux/compat.h"
        if [ ! -f "$compat_file" ]; then
            echo "无法找到 backports 的 compat.h 文件。"
            return 1
        fi
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
        make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: 清理 batman-adv 失败。"
        return 0
    else
        echo "$compat_file 中已存在 tasklet_setup 定义。"
        rm -f "$compat_file.bak"
        return 0
    fi
}

# --- 主循环 ---
echo "--------------------------------------------------"
echo "开始修复 batman-adv 编译问题..."
echo "--------------------------------------------------"

# 初始化状态标志
batman_multicast_patched=0
batman_werror_disabled=0
batman_feed_switched=0
batman_tasklet_patched=0
retry_count=0
last_fix_applied=""

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
        rm "$LOG_FILE.tmp"
        exit 0
    else
        echo "编译失败 (退出码: $COMPILE_STATUS)，检查错误..."
        extract_error_block "$LOG_FILE.tmp"
    fi

    # 错误检测和修复逻辑
    fix_applied=0

    # 检查 struct br_ip 错误
    if grep -q "struct br_ip.*has no member named.*dst" "$LOG_FILE.tmp" || \
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
            if fix_batman_patch_tasklet "$LOG_FILE.tmp"; then
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
        # 如果所有修复都已尝试，则退出
        if [ $batman_multicast_patched -eq 1 ] && [ $batman_werror_disabled -eq 1 ] && 
           [ $batman_feed_switched -eq 1 ] && [ $batman_tasklet_patched -eq 1 ]; then
            echo "所有已知修复方法都已尝试，但问题仍然存在。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE"
            rm "$LOG_FILE.tmp"
            exit 1
        fi
    fi

    # 如果没有应用任何修复但已尝试所有修复方法，则退出
    if [ $fix_applied -eq 0 ] && [ $batman_multicast_patched -eq 1 ] && 
       [ $batman_werror_disabled -eq 1 ] && [ $batman_feed_switched -eq 1 ] && 
       [ $batman_tasklet_patched -eq 1 ]; then
        echo "所有修复方法都已尝试，但无法解决问题。"
        cat "$LOG_FILE.tmp" >> "$LOG_FILE"
        rm "$LOG_FILE.tmp"
        exit 1
    fi

    # 清理临时日志
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
