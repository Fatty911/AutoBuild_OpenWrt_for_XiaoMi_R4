#!/bin/bash

# compile_with_retry.sh
# 用法: bash compile_with_retry.sh <make_command> <log_file> <max_retry> <error_pattern>

# 参数解析
MAKE_COMMAND="$1"           # 编译命令，例如 "make -j1 V=s" 或 "make package/compile V=s"
LOG_FILE="$2"               # 日志文件路径，例如 "compile.log" 或 "packages.log"
MAX_RETRY="${3:-8}"         # 最大重试次数，默认8
ERROR_PATTERN="${4:-error:|failed|undefined reference|invalid|File exists}"  # 扩展错误模式以包含新模式

# 检查必要参数
if [ -z "$MAKE_COMMAND" ] || [ -z "$LOG_FILE" ]; then
    echo "错误：缺少必要参数。用法: $0 <make_command> <log_file> [max_retry] [error_pattern]"
    exit 1
fi

# --- 修复函数 ---

# 修复 trojan-plus 源码中的 boost::asio::buffer_cast 错误
fix_trojan_plus_boost_error() {
    # 注意：硬编码路径可能在不同环境下失效
    local trojan_src_dir="/home/runner/work/AutoBuild_OpenWrt_for_XiaoMi_R4/AutoBuild_OpenWrt_for_XiaoMi_R4/openwrt/build_dir/target-mipsel_24kc_musl/trojan-plus-10.0.3"
    local service_cpp="$trojan_src_dir/src/core/service.cpp"

    if [ -f "$service_cpp" ]; then
        echo "修复 $service_cpp 中的 boost::asio::buffer_cast 错误..."
        # 使用更安全的 sed 替换，避免部分匹配问题
        sed -i.bak -e 's/boost::asio::buffer_cast<char\*>(\(.*\))/static_cast<char*>(\1)/g' \
                   -e 's/udp_read_buf.prepare(config.get_udp_recv_buf()))/udp_read_buf.prepare(config.get_udp_recv_buf()).data())/g' \
                   "$service_cpp"
        if grep -q 'static_cast<char*>' "$service_cpp"; then
             echo "已修改 $service_cpp"
        else
             echo "尝试修改 $service_cpp 失败，请检查 sed 命令。"
             return 1
        fi
    else
        echo "未找到 $service_cpp (路径可能需要调整)"
        # 尝试动态查找 build_dir 下的 trojan-plus 源码路径
        local dynamic_trojan_dir
        dynamic_trojan_dir=$(find build_dir -type d -name "trojan-plus-*" -print -quit)
        if [ -n "$dynamic_trojan_dir" ] && [ -f "$dynamic_trojan_dir/src/core/service.cpp" ]; then
            echo "找到动态路径: $dynamic_trojan_dir/src/core/service.cpp，将尝试修复..."
            service_cpp="$dynamic_trojan_dir/src/core/service.cpp"
            sed -i.bak -e 's/boost::asio::buffer_cast<char\*>(\(.*\))/static_cast<char*>(\1)/g' \
                       -e 's/udp_read_buf.prepare(config.get_udp_recv_buf()))/udp_read_buf.prepare(config.get_udp_recv_buf()).data())/g' \
                       "$service_cpp"
             if grep -q 'static_cast<char*>' "$service_cpp"; then
                  echo "已修改 $service_cpp"
             else
                  echo "尝试修改动态路径 $service_cpp 失败，请检查 sed 命令。"
                  return 1
             fi
        else
            echo "也未能在 build_dir 中动态找到 trojan-plus 源码，跳过修复。"
            return 1
        fi
    fi
    return 0
}

# 修复 po2lmo 命令未找到
fix_po2lmo() {
    echo "检测到 po2lmo 命令未找到，尝试编译 luci-base..."
    # 确保在 OpenWrt 顶层目录执行 make
    (cd "$(dirname "$0")" && make package/feeds/luci/luci-base/compile V=s) || {
        echo "编译 luci-base 失败"
        # 不立即退出，让主循环决定是否重试或失败
        return 1
    }
    echo "编译 luci-base 完成，将重试主命令。"
    return 0
}

# 日志截取函数
extract_error_block() {
    local log_file="$1"
    # 显示更多行数以便分析上下文
    echo "--- 最近 300 行日志 (${log_file}) ---"
    tail -300 "$log_file"
    echo "--- 日志结束 ---"
}

# 修复 PKG_VERSION 和 PKG_RELEASE 格式 (保持不变)
fix_pkg_version() {
    echo "修复 PKG_VERSION 和 PKG_RELEASE 格式..."
    local changed=0
    find . -type f \( -name "Makefile" -o -name "*.mk" \) | while IFS= read -r makefile; do
        # 提取当前 PKG_VERSION 和 PKG_RELEASE
        local current_version release new_version new_release modified_in_loop=0
        current_version=$(sed -n 's/^PKG_VERSION:=\(.*\)/\1/p' "$makefile")
        release=$(sed -n 's/^PKG_RELEASE:=\(.*\)/\1/p' "$makefile")

        # 处理 PKG_VERSION 中包含后缀的情况（如 1.2.3-rc1 或 1.2.3-1）
        # 仅当 PKG_RELEASE 为空或非数字时处理
        if [[ "$current_version" =~ ^([0-9]+(\.[0-9]+)*)-([a-zA-Z0-9_.-]+)$ ]] && \
           ( [ -z "$release" ] || ! [[ "$release" =~ ^[0-9]+$ ]] ); then
            new_version="${BASH_REMATCH[1]}"
            suffix="${BASH_REMATCH[3]}"
            # 尝试将后缀转换为纯数字，如果不行则用 1
            new_release=$(echo "$suffix" | tr -cd '0-9' | grep -o '[0-9]\+' || echo "1")

            # 只有当版本或发布号实际改变时才修改文件
            if [ "$current_version" != "$new_version" ] || [ "$release" != "$new_release" ]; then
                 echo "修改 $makefile: PKG_VERSION: $current_version -> $new_version, PKG_RELEASE: $release -> $new_release"
                 # 使用临时文件进行修改，避免管道问题
                 cp "$makefile" "$makefile.tmp"
                 sed -e "s/^PKG_VERSION:=.*/PKG_VERSION:=$new_version/" "$makefile.tmp" > "$makefile.tmp2"
                 # 如果原来没有 PKG_RELEASE 行，则添加；否则修改
                 if grep -q "^PKG_RELEASE:=" "$makefile.tmp2"; then
                     sed -e "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile.tmp2" > "$makefile"
                 else
                     sed -e "/^PKG_VERSION:=/a PKG_RELEASE:=$new_release" "$makefile.tmp2" > "$makefile"
                 fi
                 rm "$makefile.tmp" "$makefile.tmp2"
                 # 标记已修改，避免下面的 PKG_RELEASE 检查再次修改
                 release=$new_release
                 modified_in_loop=1
                 changed=1
            fi
        fi

        # 确保 PKG_RELEASE 是纯数字 (如果上面没有修改过)
        if [ "$modified_in_loop" -eq 0 ] && [ -n "$release" ] && ! [[ "$release" =~ ^[0-9]+$ ]]; then
            new_release=$(echo "$release" | tr -cd '0-9' | grep -o '[0-9]\+' || echo "1")
            if [ "$release" != "$new_release" ]; then
                echo "修正 $makefile: PKG_RELEASE: $release -> $new_release"
                sed -i.bak "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile"
                changed=1
            fi
        # 如果 PKG_RELEASE 为空，尝试添加 PKG_RELEASE:=1
        elif [ -z "$release" ] && grep -q "^PKG_VERSION:=" "$makefile" && ! grep -q "^PKG_RELEASE:=" "$makefile"; then
             echo "添加 $makefile: PKG_RELEASE:=1"
             sed -i.bak "/^PKG_VERSION:=/a PKG_RELEASE:=1" "$makefile"
             changed=1
        fi
    done
    # 返回是否有修改
    return $changed
}


# 修复依赖重复 (保持不变)
fix_depends() {
    echo "修复依赖重复..."
    local changed=0
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -exec sh -c '
        makefile="$1"
        awk '\''BEGIN { FS = "[[:space:]]+" }
        /^[[:space:]]*(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=/ {
            line = $0
            sub(/^[[:space:]]*(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=/, "", line) # Get dependencies string
            split(line, deps, " ") # Split into array

            delete seen_bare # Reset seen arrays for each line
            delete seen_versioned_pkg
            delete result_deps # Array to hold unique dependencies
            idx = 0

            for (i in deps) {
                dep = deps[i]
                if (dep == "" || dep ~ /^\s*$/ || dep ~ /\$\(.*\)/ ) { # Skip empty, whitespace-only, or variable deps
                    result_deps[idx++] = dep
                    continue
                }

                # Remove leading '+' if present
                bare_dep = dep
                sub(/^\+/, "", bare_dep)

                # Extract base package name (handle +pkg, pkg>=1.0, +pkg>=1.0)
                pkg_name = bare_dep
                if (match(pkg_name, />=|<=|==/)) {
                    pkg_name = substr(pkg_name, 1, RSTART - 1)
                }

                # Check for duplicates
                is_versioned = (bare_dep ~ />=|<=|==/)
                if (is_versioned) {
                    if (!(pkg_name in seen_versioned_pkg)) { # Add if no versioned variant seen
                        result_deps[idx++] = dep
                        seen_versioned_pkg[pkg_name] = 1
                        delete seen_bare[pkg_name] # Remove bare if versioned is added
                    }
                } else {
                    if (!(pkg_name in seen_bare) && !(pkg_name in seen_versioned_pkg)) { # Add if no bare or versioned seen
                        result_deps[idx++] = dep
                        seen_bare[pkg_name] = 1
                    }
                }
            }

            # Reconstruct the line
            prefix = $1
            new_deps_str = ""
            for (j=0; j<idx; ++j) {
                if (result_deps[j] != "") {
                     new_deps_str = new_deps_str " " result_deps[j]
                }
            }
            sub(/^ /, "", new_deps_str) # Remove leading space
            print prefix new_deps_str
            next
        }
        { print }
        '\'' "$makefile" > "$makefile.tmp"

        if [ -s "$makefile.tmp" ] && ! cmp -s "$makefile" "$makefile.tmp"; then
            echo "修改 $makefile: 修复依赖重复"
            # grep -E "(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=" "$makefile.tmp" # Optionally show changes
            mv "$makefile.tmp" "$makefile"
            changed=1 # Mark as changed
        else
            rm -f "$makefile.tmp"
        fi
    ' _ {} \;
    return $changed # Return whether changes were made
}


# 修复依赖格式 (适用于 Makefile 中的 DEPENDS+= 行)
fix_dependency_format() {
    echo "尝试修复 Makefile 中的依赖格式..."
    local changed=0
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -exec sh -c '
        makefile="$1"
        # Use awk for processing, create backup first
        cp "$makefile" "$makefile.bak"
        awk -i inplace '\''
        BEGIN { FS="[[:space:]]+"; OFS=" "; changed_file=0 }
        /^(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=/ {
            original_line = $0
            line_changed = 0
            delete seen
            prefix = $1 # e.g., DEPENDS+=
            current_deps = ""
            # Rebuild the dependency string from fields $2 onwards
            for (i=2; i<=NF; i++) {
                current_deps = current_deps $i " "
            }
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", current_deps); # Trim spaces

            split(current_deps, deps, " ")
            new_deps_str = ""
            for (i in deps) {
                dep = deps[i]
                if (dep == "") continue # Skip empty entries

                # Example fix: Remove extra release part like >=1.2.3-1 -> >=1.2.3
                # This is speculative, adjust based on actual invalid formats observed
                original_dep = dep
                gsub(/(>=|<=|==)([0-9]+\.[0-9]+(\.[0-9]+)?)-[0-9]+$/, "\\1\\2", dep)

                if (!seen[dep]++) { # Add if not seen
                    new_deps_str = new_deps_str " " dep
                }
                 if (original_dep != dep) { line_changed=1 }
            }
            sub(/^[[:space:]]+/, "", new_deps_str) # Remove leading space

            new_line = prefix new_deps_str
            if (new_line != original_line) {
                 $0 = new_line
                 line_changed=1
                 changed_file=1
            }
        }
        { print }
        END { exit !changed_file } # Exit with 0 if changed, 1 otherwise
        '\'' "$makefile"

        # Check awk exit status to see if file was changed
        if [ $? -eq 0 ]; then
            echo "修改 $makefile: 调整依赖格式"
            rm "$makefile.bak" # Remove backup if successful change
            changed=1 # Mark script-level change
        else
            mv "$makefile.bak" "$makefile" # Restore backup if no change or error
        fi
    ' _ {} \;
    return $changed # Return whether changes were made
}


# 修复目录冲突 (mkdir: ... File exists)
fix_mkdir_conflict() {
    local log_file="$1"
    echo "检测到 'mkdir: cannot create directory ... File exists' 错误，尝试修复..."

    # 提取失败的目录路径
    # 使用 grep + tail 来获取最后一个匹配项
    FAILED_DIR=$(grep "mkdir: cannot create directory" "$log_file" | grep "File exists" | sed -e "s/.*mkdir: cannot create directory '\([^']*\)'.*/\1/" | tail -n 1)

    if [ -z "$FAILED_DIR" ]; then
        echo "无法从日志中提取冲突的目录路径。"
        return 1 # Indicate failure to fix
    fi

    echo "冲突目录: $FAILED_DIR"

    # 尝试清理冲突的目录
    if [ -d "$FAILED_DIR" ]; then
        echo "正在清理已存在的冲突目录: $FAILED_DIR"
        rm -rf "$FAILED_DIR"
        # 检查是否删除成功
        if [ -e "$FAILED_DIR" ]; then
             echo "警告：无法删除冲突目录 $FAILED_DIR"
             return 1 # Indicate failure to fix
        fi
    else
        echo "警告：冲突目录 $FAILED_DIR 已不存在或不是一个目录。"
        # 即使目录不在，也可能是一个文件冲突，尝试删除
        rm -f "$FAILED_DIR"
    fi

    # 尝试找出导致错误的包并清理其构建目录
    # 在错误日志附近查找 "ERROR: package/... failed to build."
    # 使用 tac 反转日志，查找错误消息上方的第一个 package 失败信息
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 50 "mkdir: cannot create directory '$FAILED_DIR'" | grep -m 1 -oE 'ERROR: (package/[^ ]+) failed to build.')

    if [[ -n "$PKG_ERROR_LINE" ]]; then
        PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build./\1/')
        PKG_NAME=$(basename "$PKG_PATH")
        echo "推测是包 '$PKG_NAME' ($PKG_PATH) 导致了错误。"
        echo "尝试清理包 $PKG_NAME..."
        # 使用 DIRCLEAN=1 清理构建目录可能更有效
        (cd "$(dirname "$0")" && make "DIRCLEAN=1" "$PKG_PATH/clean" V=s) || {
            echo "清理包 $PKG_NAME 失败，但已删除冲突目录，将继续尝试主编译命令。"
            # 不认为这是致命错误，继续重试
        }
        echo "已清理包 $PKG_NAME，将重试主编译命令。"
    else
        echo "无法从日志中明确推断出导致错误的包。仅删除了冲突目录。"
    fi

    return 0 # Indicate fix was attempted (directory removed)
}

# 修复符号链接冲突 (保持不变，但可以改进类似 fix_mkdir_conflict 的包清理逻辑)
fix_symbolic_link_conflict() {
    local log_file="$1"
    echo "检测到 'ln: failed to create symbolic link ... File exists' 错误，尝试修复..."

    FAILED_LINK=$(grep "ln: failed to create symbolic link" "$log_file" | grep "File exists" | sed -e "s/.*failed to create symbolic link '\([^']*\)'.*/\1/" | tail -n 1)

    if [ -z "$FAILED_LINK" ]; then
        echo "无法从日志中提取冲突的符号链接路径。"
        return 1
    fi

    echo "冲突链接: $FAILED_LINK"

    if [ -e "$FAILED_LINK" ]; then
        echo "正在清理已存在的冲突文件/链接: $FAILED_LINK"
        rm -rf "$FAILED_LINK" # Use rm -rf as it could be a directory link target
        if [ -e "$FAILED_LINK" ]; then
             echo "警告：无法删除冲突链接/文件 $FAILED_LINK"
             return 1
        fi
    else
         echo "警告：冲突链接 $FAILED_LINK 已不存在。"
    fi

    # 同样尝试找到包并清理 (可选增强)
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 50 "failed to create symbolic link '$FAILED_LINK'" | grep -m 1 -oE 'ERROR: (package/[^ ]+) failed to build.')
    if [[ -n "$PKG_ERROR_LINE" ]]; then
        PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build./\1/')
        PKG_NAME=$(basename "$PKG_PATH")
        echo "推测是包 '$PKG_NAME' ($PKG_PATH) 导致了错误。"
        echo "尝试清理包 $PKG_NAME..."
        (cd "$(dirname "$0")" && make "DIRCLEAN=1" "$PKG_PATH/clean" V=s) || {
             echo "清理包 $PKG_NAME 失败，但已删除冲突链接，将继续尝试主编译命令。"
        }
        echo "已清理包 $PKG_NAME，将重试主编译命令。"
    else
        echo "无法从日志中明确推断出导致错误的包。仅删除了冲突链接。"
    fi

    return 0
}

# --- 主编译循环 ---
retry_count=0
last_fix_applied=""
fix_applied_this_iteration=0

while [ $retry_count -lt "$MAX_RETRY" ]; do
    echo "--------------------------------------------------"
    echo "尝试编译: $MAKE_COMMAND (第 $((retry_count + 1)) / $MAX_RETRY 次)..."
    echo "--------------------------------------------------"

    # 清理之前的日志或使用追加模式 >>
    # 使用覆盖模式 > 更简单，每次重试都有干净的日志
    eval "$MAKE_COMMAND" > "$LOG_FILE" 2>&1
    COMPILE_STATUS=$?

    if [ $COMPILE_STATUS -eq 0 ]; then
        echo "编译成功！"
        exit 0
    fi

    echo "编译失败 (退出码: $COMPILE_STATUS)，检查错误..."
    extract_error_block "$LOG_FILE"
    fix_applied_this_iteration=0 # Reset flag for this iteration

    # --- 错误检测与修复逻辑 ---
    # 检查顺序很重要，将更具体的错误放在前面

    if grep -q "po2lmo: command not found" "$LOG_FILE"; then
        echo "检测到 'po2lmo' 错误..."
        last_fix_applied="fix_po2lmo"
        fix_po2lmo || { echo "修复 po2lmo 失败，停止重试。"; exit 1; }
        fix_applied_this_iteration=1
    elif grep -q "trojan-plus.*buffer_cast" "$LOG_FILE"; then
        echo "检测到 'trojan-plus boost::asio::buffer_cast' 错误..."
        last_fix_applied="fix_trojan_plus"
        fix_trojan_plus_boost_error || { echo "修复 trojan-plus 失败，停止重试。"; cat "$LOG_FILE"; exit 1; }
        fix_applied_this_iteration=1
    # 合并 PKG_VERSION 和依赖格式错误的处理
    elif grep -E -q "package version is invalid|dependency format is invalid" "$LOG_FILE"; then
        echo "检测到包版本或依赖格式错误..."
        # 应用所有相关的修复
        local changed=0
        fix_pkg_version && changed=1
        fix_dependency_format && changed=1 # 修复 Makefile 依赖格式
        fix_depends && changed=1 # 修复重复依赖

        if [ $changed -eq 1 ]; then
             echo "应用了包元数据修复，将重试。"
             last_fix_applied="fix_metadata"
             fix_applied_this_iteration=1
        else
             echo "检测到元数据错误，但修复函数未报告任何更改。可能需要手动检查。"
             # 决定是继续重试还是退出
             # exit 1 # 或者注释掉以允许重试
        fi
    elif grep -q "mkdir: cannot create directory.*File exists" "$LOG_FILE"; then
        echo "检测到 'mkdir File exists' 错误..."
        last_fix_applied="fix_mkdir"
        fix_mkdir_conflict "$LOG_FILE" || { echo "修复 mkdir 冲突失败，可能无法继续。"; exit 1; }
        fix_applied_this_iteration=1
    elif grep -q "ln: failed to create symbolic link.*File exists" "$LOG_FILE"; then
        echo "检测到 'ln File exists' 错误..."
        last_fix_applied="fix_symlink"
        fix_symbolic_link_conflict "$LOG_FILE" || { echo "修复符号链接冲突失败，可能无法继续。"; exit 1; }
        fix_applied_this_iteration=1
    # 保留一个通用的错误模式检查，以防上面都未匹配
    elif grep -E -q "$ERROR_PATTERN" "$LOG_FILE"; then
         echo "检测到通用错误模式，但无特定修复程序。尝试应用通用修复（PKG_VERSION, 依赖）..."
         local changed=0
         fix_pkg_version && changed=1
         fix_dependency_format && changed=1
         fix_depends && changed=1
         if [ $changed -eq 1 ]; then
             echo "应用了通用修复，将重试。"
             last_fix_applied="fix_generic"
             fix_applied_this_iteration=1
         else
             echo "检测到通用错误，但通用修复未应用更改。可能是未处理的错误。"
             echo "请检查完整日志: $LOG_FILE"
             exit 1 # 退出，因为不知道如何修复
         fi
    else
        echo "未检测到已知或通用的错误模式。编译失败。"
        echo "请检查完整日志: $LOG_FILE"
        exit 1
    fi

    # 如果本次迭代没有应用任何修复，可能是修复逻辑未能解决根本问题或出现新问题
    # 可以选择在这里增加一次重试，或者直接判定失败
    # if [ $fix_applied_this_iteration -eq 0 ]; then
    #    echo "警告：检测到错误，但没有应用有效的修复动作。可能是修复逻辑无效或出现未知错误。"
        # exit 1 # 强制退出
    # fi

    retry_count=$((retry_count + 1))
    # 添加短暂延迟，有时文件系统操作需要一点时间同步
    sleep 2
done

echo "--------------------------------------------------"
echo "达到最大重试次数 ($MAX_RETRY)，编译最终失败。"
echo "--------------------------------------------------"
extract_error_block "$LOG_FILE"
echo "请检查完整日志: $LOG_FILE"
exit 1
