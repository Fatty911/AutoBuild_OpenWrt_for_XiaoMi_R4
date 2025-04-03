#!/bin/bash

# compile_with_retry.sh
# Assumes execution from the OpenWrt source root directory.
# Usage: bash compile_with_retry.sh <make_command> <log_file> [max_retry] [error_pattern]

# --- Configuration ---
BATMAN_ADV_COMMIT="5437d2c91fd9f15e06fbea46677abb529ed3547c" # Known good commit for batman-adv/routing feed

# --- Parameter Parsing ---
MAKE_COMMAND="$1"           # e.g., "make -j1 V=s" or "make package/compile V=s"
LOG_FILE="$2"               # e.g., "compile.log" or "packages.log"
MAX_RETRY="${3:-8}"         # Default max retries: 8
ERROR_PATTERN="${4:-error:|failed|undefined reference|invalid|File exists|missing separator}" # Extended error patterns

# --- Argument Check ---
if [ -z "$MAKE_COMMAND" ] || [ -z "$LOG_FILE" ]; then
    echo "错误：缺少必要参数。用法: $0 <make_command> <log_file> [max_retry] [error_pattern]"
    exit 1
fi

# --- Fix Functions ---

### Fix trojan-plus boost::asio::buffer_cast error
fix_trojan_plus_boost_error() {
    echo "修复 trojan-plus 中的 boost::asio::buffer_cast 错误..."
    local trojan_src_dir service_cpp found_path=""
    trojan_src_dir=$(find build_dir -type d -path '*/trojan-plus-*/src/core' -print -quit)
    if [ -n "$trojan_src_dir" ]; then
        service_cpp="$trojan_src_dir/service.cpp"
        if [ -f "$service_cpp" ]; then
            found_path="$service_cpp"
            echo "找到 trojan-plus 源码: $found_path"
        else
            echo "在找到的目录 $trojan_src_dir 中未找到 service.cpp"
        fi
    fi
    if [ -z "$found_path" ]; then
        echo "未能在 build_dir 中动态找到 trojan-plus 源码路径，尝试基于日志猜测路径..."
        local target_build_dir=$(grep -o '/home/runner/work/[^/]*/[^/]*/openwrt/build_dir/target-[^/]*/trojan-plus-[^/]*' "$LOG_FILE" | head -n 1)
        if [ -n "$target_build_dir" ] && [ -d "$target_build_dir" ]; then
            service_cpp="$target_build_dir/src/core/service.cpp"
            if [ -f "$service_cpp" ]; then
                found_path="$service_cpp"
                echo "根据日志猜测找到 trojan-plus 源码: $found_path"
            fi
        fi
    fi
    if [ -z "$found_path" ]; then
        echo "无法定位 trojan-plus 的 service.cpp 文件，跳过修复。"
        return 1
    fi
    echo "尝试修复 $found_path ..."
    cp "$found_path" "$found_path.bak"
    sed -i "s|boost::asio::buffer_cast<char\*>(\(udp_read_buf.prepare([^)]*)\))|static_cast<char*>(\1.data())|g" "$found_path"
    if grep -q 'static_cast<char\*>' "$found_path"; then
        echo "已成功修改 $found_path"
        rm "$found_path.bak"
        return 0
    else
        echo "尝试修改 $found_path 失败，恢复备份文件。"
        mv "$found_path.bak" "$found_path"
        return 1
    fi
}

### Fix po2lmo command not found
fix_po2lmo() {
    echo "检测到 po2lmo 命令未找到，尝试编译 luci-base..."
    make package/feeds/luci/luci-base/compile V=s || {
        echo "编译 luci-base 失败"
        return 1
    }
    echo "编译 luci-base 完成，将重试主命令。"
    return 0
}

### Extract error block from log
extract_error_block() {
    local log_file="$1"
    echo "--- 最近 300 行日志 (${log_file}) ---"
    tail -300 "$log_file"
    echo "--- 日志结束 ---"
}

### Fix PKG_VERSION and PKG_RELEASE formats
fix_pkg_version() {
    echo "修复 PKG_VERSION 和 PKG_RELEASE 格式..."
    local changed_count=0
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -path "./build_dir/*" -prune -o -path "./staging_dir/*" -prune -o -print | while IFS= read -r makefile; do
        if ! grep -qE '^(include \.\./\.\./(package|buildinfo)\.mk|include \$\(INCLUDE_DIR\)/package\.mk)' "$makefile"; then
            continue
        fi
        local current_version release new_version new_Release suffix modified_in_loop=0
        current_version=$(sed -n 's/^PKG_VERSION:=\(.*\)/\1/p' "$makefile")
        release=$(sed -n 's/^PKG_RELEASE:=\(.*\)/\1/p' "$makefile")
        if [[ "$current_version" =~ ^([0-9]+(\.[0-9]+)*)-([a-zA-Z0-9_.-]+)$ ]] && \
           ( [ -z "$release" ] || ! [[ "$release" =~ ^[0-9]+$ ]] ); then
            new_version="${BASH_REMATCH[1]}"
            suffix="${BASH_REMATCH[3]}"
            new_release=$(echo "$suffix" | tr -cd '0-9' | grep -o '[0-9]\+' || echo "1")
            if [ "$current_version" != "$new_version" ] || [ "$release" != "$new_release" ]; then
                 echo "修改 $makefile: PKG_VERSION: $current_version -> $new_version, PKG_RELEASE: $release -> $new_release"
                 cp "$makefile" "$makefile.tmp"
                 sed -e "s/^PKG_VERSION:=.*/PKG_VERSION:=$new_version/" "$makefile.tmp" > "$makefile.tmp2"
                 if grep -q "^PKG_RELEASE:=" "$makefile.tmp2"; then
                     sed -e "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile.tmp2" > "$makefile"
                 else
                     awk -v ver="$new_version" -v rel="$new_release" '
                        /^PKG_VERSION:=/ { print "PKG_VERSION:=" ver; print "PKG_RELEASE:=" rel; next }
                        { print }
                     ' "$makefile.tmp2" > "$makefile"
                 fi
                 rm "$makefile.tmp" "$makefile.tmp2"
                 release=$new_release
                 modified_in_loop=1
                 changed_count=$((changed_count + 1))
            fi
        fi
        if [ "$modified_in_loop" -eq 0 ] && [ -n "$release" ] && ! [[ "$release" =~ ^[0-9]+$ ]]; then
            new_release=$(echo "$release" | tr -cd '0-9' | grep -o '[0-9]\+' || echo "1")
            if [ "$release" != "$new_release" ]; then
                echo "修正 $makefile: PKG_RELEASE: $release -> $new_release"
                sed -i.bak "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile"
                changed_count=$((changed_count + 1))
            fi
        elif [ -z "$release" ] && grep -q "^PKG_VERSION:=" "$makefile" && ! grep -q "^PKG_RELEASE:=" "$makefile"; then
             echo "添加 $makefile: PKG_RELEASE:=1"
             sed -i.bak "/^PKG_VERSION:=.*/a PKG_RELEASE:=1" "$makefile"
             changed_count=$((changed_count + 1))
        fi
    done
    if [ "$changed_count" -gt 0 ]; then return 0; else return 1; fi
}


### Fix duplicate dependencies
fix_depends() {
    echo "修复依赖重复..."
    local flag_file=".fix_depends_changed"
    rm -f "$flag_file"
    
    find . -type f \( -name "Makefile" -o -name "*.mk" \) \
        \( -path "./build_dir/*" -o -path "./staging_dir/*" \) -prune -o \
        -exec sh -c '
            makefile="$1"
            flag_file_path="$2"
            
            # Skip non-Makefile files
            if ! head -n 20 "$makefile" 2>/dev/null | grep -qE "^\s*include.*\/(package|buildinfo)\.mk"; then
                exit 0
            fi

            awk '\''
            BEGIN { FS = "[[:space:]]+"; OFS = " "; change_made = 0 }
            /^[[:space:]]*(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=/ {
                original_line = $0
                prefix = $1
                line = $0
                sub(/^[[:space:]]*(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=/, "", line)
                
                delete seen_bare
                delete seen_versioned_pkg
                delete result_deps
                idx = 0
                n = split(line, deps, " ")
                
                for (i=1; i<=n; i++) {
                    dep = deps[i]
                    if (dep == "" || dep ~ /^\s*$/ || dep ~ /\$\(.*\)/ ) {
                        result_deps[idx++] = dep
                        continue
                    }
                    
                    # Remove leading +
                    bare_dep = dep
                    sub(/^\+/, "", bare_dep)
                    
                    # Extract package name
                    pkg_name = bare_dep
                    if (match(pkg_name, />=|<=|==/)) {
                        pkg_name = substr(pkg_name, 1, RSTART - 1)
                    }
                    
                    is_versioned = (bare_dep ~ />=|<=|==/)
                    
                    if (is_versioned) {
                        if (!(pkg_name in seen_versioned_pkg)) {
                            result_deps[idx++] = dep
                            seen_versioned_pkg[pkg_name] = 1
                            if (pkg_name in seen_bare) {
                                # Remove existing bare dependency
                                for (k=0; k<idx-1; ++k) {
                                    if (result_deps[k] == pkg_name || result_deps[k] == "+" pkg_name) {
                                        for (l=k; l<idx-1; ++l) {
                                            result_deps[l] = result_deps[l+1]
                                        }
                                        idx--
                                        result_deps[idx] = ""
                                        break
                                    }
                                }
                            }
                            delete seen_bare[pkg_name]
                        }
                    } else {
                        if (!(pkg_name in seen_bare) && !(pkg_name in seen_versioned_pkg)) {
                            result_deps[idx++] = dep
                            seen_bare[pkg_name] = 1
                        }
                    }
                }
                
                # Build new deps string
                new_deps_str = ""
                for (j=0; j<idx; ++j) {
                    if (result_deps[j] != "") {
                        new_deps_str = new_deps_str " " result_deps[j]
                    }
                }
                sub(/^ /, "", new_deps_str)
                
                # Generate new line
                new_line = prefix " " new_deps_str
                gsub(/[[:space:]]+$/, "", new_line)
                
                # Compare with original
                original_line_trimmed = original_line
                gsub(/[[:space:]]+$/, "", original_line_trimmed)
                
                if (new_line != original_line_trimmed) {
                    print new_line
                    change_made = 1
                } else {
                    print original_line
                }
                next
            }
            { print }
            END { exit !change_made }
            '\'' "$makefile" > "$makefile.tmp"
            
            # Check awk exit status
            if [ $? -eq 0 ] && [ -s "$makefile.tmp" ] && ! cmp -s "$makefile" "$makefile.tmp"; then
                echo "修改 $makefile: 修复依赖重复"
                mv "$makefile.tmp" "$makefile"
                touch "$flag_file_path"
            else
                rm -f "$makefile.tmp"
            fi
        ' _ {} "$flag_file" \;
    
    if [ -f .fix_depends_changed ]; then
        rm -f .fix_depends_changed
        return 0
    else
        return 1
    fi
}

### Fix dependency format
fix_dependency_format() {
    echo "尝试修复 Makefile 中的依赖格式..."
    local flag_file=".fix_depformat_changed"
    rm -f "$flag_file"
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -path "./build_dir/*" -prune -o -path "./staging_dir/*" -prune -o -exec sh -c '
        makefile="$1"
        flag_file_path="$2"
        if ! head -n 20 "$makefile" | grep -qE "^\s*include.*\/(package|buildinfo)\.mk"; then
             exit 0
        fi
        cp "$makefile" "$makefile.bak"
        awk '\''BEGIN { FS="[[:space:]]+"; OFS=" "; changed_file=0 }
         /^(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=/ {
            original_line = $0
            line_changed = 0
            delete seen
            prefix = $1
            current_deps = ""
            for (i=2; i<=NF; i++) {
                if ($i != "") {
                     current_deps = current_deps $i " "
                }
            }
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", current_deps);
            split(current_deps, deps, " ")
            new_deps_str = ""
            for (i in deps) {
                dep = deps[i]
                if (dep == "") continue
                original_dep = dep
                gsub(/(>=|<=|==)([0-9]+\.[0-9]+(\.[0-9]+)?)-[0-9]+$/, "\\1\\2", dep)
                gsub(/^\+[[:space:]]+/, "+", dep)
                if (!seen[dep]++) {
                    new_deps_str = new_deps_str " " dep
                }
                 if (original_dep != dep) { line_changed=1 }
            }
            sub(/^[[:space:]]+/, "", new_deps_str)
            new_line = prefix (new_deps_str == "" ? "" : " " new_deps_str)
            gsub(/[[:space:]]+$/, "", new_line)
            original_line_trimmed = original_line
            gsub(/[[:space:]]+$/, "", original_line_trimmed)
            if (new_line != original_line_trimmed) {
                 $0 = new_line
                 line_changed=1
                 changed_file=1
            }
        }
        { print }
        END { exit !changed_file }
        '\'' "$makefile" > "$makefile.tmp"
        awk_status=$?
        if [ $awk_status -eq 0 ]; then
           if [ -s "$makefile.tmp" ] && ! cmp -s "$makefile" "$makefile.tmp"; then
                echo "修改 $makefile: 调整依赖格式"
                mv "$makefile.tmp" "$makefile"
                rm "$makefile.bak"
                touch "$flag_file_path"
           else
                rm "$makefile.tmp"
                mv "$makefile.bak" "$makefile"
           fi
        elif [ $awk_status -eq 1 ]; then
             rm "$makefile.tmp"
             mv "$makefile.bak" "$makefile"
        else
             echo "警告: awk 处理 $makefile 时出错 (退出码: $awk_status)，已从备份恢复。"
             rm "$makefile.tmp"
             mv "$makefile.bak" "$makefile"
        fi
    ' _ {} "$flag_file" \;
    if [ -f "$flag_file" ]; then
        rm -f "$flag_file"
        return 0
    else
        return 1
    fi
}

### Fix mkdir conflicts
fix_mkdir_conflict() {
    local log_file="$1"
    echo "检测到 'mkdir: cannot create directory ... File exists' 错误，尝试修复..."
    local FAILED_PATH PKG_ERROR_LINE PKG_PATH PKG_NAME
    FAILED_PATH=$(grep "mkdir: cannot create directory" "$log_file" | grep "File exists" | sed -e "s/.*mkdir: cannot create directory '\([^']*\)'.*/\1/" | tail -n 1)
    if [ -z "$FAILED_PATH" ]; then
        echo "无法从日志中提取冲突的路径。"
        return 1
    fi
    echo "冲突路径: $FAILED_PATH"
    if [ -e "$FAILED_PATH" ]; then
        echo "正在清理已存在的冲突路径: $FAILED_PATH"
        rm -rf "$FAILED_PATH"
        if [ -e "$FAILED_PATH" ]; then
             echo "警告：无法删除冲突路径 $FAILED_PATH"
             return 1
        fi
    else
        echo "警告：冲突路径 $FAILED_PATH 已不存在。"
    fi
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 50 "mkdir: cannot create directory '$FAILED_PATH'" | grep -m 1 -Eo '(ERROR: (package|feeds)/[^ ]+ failed to build\.|make\[[0-9]+\]: \*\*\* \[(.*/)\.built\] Error)')
    PKG_PATH=""
    if [[ -n "$PKG_ERROR_LINE" ]]; then
        if [[ "$PKG_ERROR_LINE" == ERROR:* ]]; then
            PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build\./\1/')
        else
             PKG_DIR=$(echo "$PKG_ERROR_LINE" | sed -n 's|make\[[0-9]\+\]: \*\*\* \[\(.*\)/\.built\] Error.*|\1|p')
             if [[ "$PKG_DIR" == *build_dir/* ]]; then
                  PKG_NAME_GUESS=$(basename "$PKG_DIR" | sed 's/-[0-9].*//')
                  PKG_PATH=$(find package feeds -name "$PKG_NAME_GUESS" -type d -print -quit)
             fi
        fi
    fi
    if [[ -n "$PKG_PATH" ]] && ( [[ "$PKG_PATH" == package/* ]] || [[ "$PKG_PATH" == feeds/* ]] ) && [ -d "$PKG_PATH" ]; then
        PKG_NAME=$(basename "$PKG_PATH")
        echo "推测是包 '$PKG_NAME' ($PKG_PATH) 导致了错误。"
        echo "尝试清理包 $PKG_NAME..."
        make "$PKG_PATH/clean" DIRCLEAN=1 V=s || {
            echo "清理包 $PKG_NAME 失败，但已删除冲突路径，将继续尝试主编译命令。"
        }
        echo "已清理包 $PKG_NAME，将重试主编译命令。"
    else
        echo "无法从日志中明确推断出导致错误的包或路径无效。仅删除了冲突路径。"
    fi
    return 0
}

### Fix symbolic link conflicts
fix_symbolic_link_conflict() {
    local log_file="$1"
    echo "检测到 'ln: failed to create symbolic link ... File exists' 错误，尝试修复..."
    local FAILED_LINK PKG_ERROR_LINE PKG_PATH PKG_NAME
    FAILED_LINK=$(grep "ln: failed to create symbolic link" "$log_file" | grep "File exists" | sed -e "s/.*failed to create symbolic link '\([^']*\)'.*/\1/" | tail -n 1)
    if [ -z "$FAILED_LINK" ]; then
        echo "无法从日志中提取冲突的符号链接路径。"
        return 1
    fi
ucer    echo "冲突链接: $FAILED_LINK"
    if [ -e "$FAILED_LINK" ]; then
        echo "正在清理已存在的冲突文件/链接: $FAILED_LINK"
        rm -rf "$FAILED_LINK"
        if [ -e "$FAILED_LINK" ]; then
             echo "警告：无法删除冲突链接/文件 $FAILED_LINK"
             return 1
        fi
    else
         echo "警告：冲突链接 $FAILED_LINK 已不存在。"
    fi
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 50 "failed to create symbolic link '$FAILED_LINK'" | grep -m 1 -Eo '(ERROR: (package|feeds)/[^ ]+ failed to build\.|make\[[0-9]+\]: \*\*\* \[(.*/)\.built\] Error)')
    PKG_PATH=""
    if [[ -n "$PKG_ERROR_LINE" ]]; then
        if [[ "$PKG_ERROR_LINE" == ERROR:* ]]; then
             PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build\./\1/')
        else
             PKG_DIR=$(echo "$PKG_ERROR_LINE" | sed -n 's|make\[[0-9]\+\]: \*\*\* \[\(.*\)/\.built\] Error.*|\1|p')
             if [[ "$PKG_DIR" == *build_dir/* ]]; then
                  PKG_NAME_GUESS=$(basename "$PKG_DIR" | sed 's/-[0-9].*//')
                  PKG_PATH=$(find package feeds -name "$PKG_NAME_GUESS" -type d -print -quit)
             fi
        fi
    fi
    if [[ -n "$PKG_PATH" ]] && ( [[ "$PKG_PATH" == package/* ]] || [[ "$PKG_PATH" == feeds/* ]] ) && [ -d "$PKG_PATH" ]; then
        PKG_NAME=$(basename "$PKG_PATH")
        echo "推测是包 '$PKG_NAME' ($PKG_PATH) 导致了错误。"
        echo "尝试清理包 $PKG_NAME..."
        make "$PKG_PATH/clean" DIRCLEAN=1 V=s || {
             echo "清理包 $PKG_NAME 失败，但已删除冲突链接，将继续尝试主编译命令。"
        }
        echo "已清理包 $PKG_NAME，将重试主编译命令。"
    else
        echo "无法从日志中明确推断出导致错误的包或路径无效。仅删除了冲突链接。"
    fi
    return 0
}

### Fix Makefile "missing separator" error
### Fix Makefile "missing separator" error
fix_makefile_separator() {
    local log_file="$1"
    echo "检测到 'missing separator' 错误，尝试修复..."
    local MAKEFILE_PATH MAKE_DIR PKG_PATH MAKE_DIR_REL MAKEFILE_PATH_REL LINE_NUM

    # 从日志中提取Makefile路径和行号
    MAKEFILE_PATH=$(grep "missing separator.*Stop." "$log_file" | head -n 1 | cut -d':' -f1)
    LINE_NUM=$(grep "missing separator.*Stop." "$log_file" | head -n 1 | cut -d':' -f2)

    # 提取编译所在的目录
    MAKE_DIR=$(grep -B 1 "missing separator.*Stop." "$log_file" | grep "Leaving directory" | sed -e "s/.*Leaving directory '\([^']*\)'/\1/")

    # 处理MAKE_DIR路径
    if [ -n "$MAKE_DIR" ]; then
        if [[ "$MAKE_DIR" == /* ]]; then
            MAKE_DIR_REL=$(echo "$MAKE_DIR" | sed 's|^/home/runner/work/[^/]*/[^/]*/openwrt/||' | sed 's|^/github/workspace/openwrt/||' | sed 's|^/mnt/openwrt/||')
        else
            MAKE_DIR_REL="$MAKE_DIR"
        fi
        if [ -d "$MAKE_DIR_REL" ]; then
            PKG_PATH="$MAKE_DIR_REL"
        fi
    fi

    # 如果PKG_PATH未确定，尝试从MAKEFILE_PATH获取
    if [ -z "$PKG_PATH" ] && [ -n "$MAKEFILE_PATH" ]; then
        if [[ "$MAKEFILE_PATH" == /* ]]; then
            MAKEFILE_PATH_REL=$(echo "$MAKEFILE_PATH" | sed 's|^/home/runner/work/[^/]*/[^/]*/openwrt/||' | sed 's|^/github/workspace/openwrt/||' | sed 's|^/mnt/openwrt/||')
        else
            MAKEFILE_PATH_REL="$MAKEFILE_PATH"
        fi
        if [ -f "$MAKEFILE_PATH_REL" ]; then
            PKG_PATH=$(dirname "$MAKEFILE_PATH_REL")
        fi
    fi

    # 检查PKG_PATH是否有效
    if [ -z "$PKG_PATH" ] || [ ! -d "$PKG_PATH" ]; then
        echo "无法将错误定位到有效的相对包路径。"
        return 1
    fi

    # 检查并修复Makefile中的语法错误
    if [ -n "$MAKEFILE_PATH_REL" ] && [ -f "$MAKEFILE_PATH_REL" ] && [ -n "$LINE_NUM" ]; then
        echo "检查文件: $MAKEFILE_PATH_REL，第 $LINE_NUM 行..."
        # 备份原始Makefile
        cp "$MAKEFILE_PATH_REL" "$MAKEFILE_PATH_REL.bak"
        # 检查指定行是否以空格开头，并替换为空格+TAB
        sed -n "${LINE_NUM}p" "$MAKEFILE_PATH_REL" | grep -q "^[[:space:]]\+[^[:space:]]" && {
            echo "检测到第 $LINE_NUM 行使用空格缩进，替换为 TAB..."
            sed -i "${LINE_NUM}s/^[[:space:]]*/\t/" "$MAKEFILE_PATH_REL"
        }
        # 检查修复是否成功
        if ! grep -q "^[[:space:]]\+[^[:space:]]" "$MAKEFILE_PATH_REL" > /dev/null 2>&1; then
            echo "已修复 $MAKEFILE_PATH_REL 的缩进问题，将重试编译。"
            return 0
        else
            echo "修复 $MAKEFILE_PATH_REL 失败，恢复备份文件并尝试清理目录..."
            mv "$MAKEFILE_PATH_REL.bak" "$MAKEFILE_PATH_REL"
        fi
    fi

    # 如果修复失败，尝试清理目录
    echo "尝试清理目录: $PKG_PATH ..."
    make "$PKG_PATH/clean" V=s || {
        echo "清理 $PKG_PATH 失败，但这可能不是致命错误，将继续重试主命令。"
        return 0
    }
    echo "已清理 $PKG_PATH，将重试主命令。"
    return 0
}

### Fix batman-adv 'struct br_ip' dst error
fix_batman_br_ip_dst() {
    local log_file="$1"
    echo "尝试修复 batman-adv 的 'struct br_ip has no member named dst' 错误..."

    # Extract the multicast.c file path from the log
    local multicast_file
    multicast_file=$(grep -oE 'build_dir/target-[^/]+/linux-[^/]+/batman-adv-[^/]+/net/batman-adv/multicast\.c' "$log_file" | head -n 1)
    if [ -z "$multicast_file" ] || [ ! -f "$multicast_file" ]; then
        echo "无法从日志中定位 multicast.c 文件，尝试动态查找..."
        multicast_file=$(find build_dir -type f -path "*/batman-adv-*/net/batman-adv/multicast.c" -print -quit)
        if [ -z "$multicast_file" ] || [ ! -f "$multicast_file" ]; then
            echo "动态查找 multicast.c 文件失败。"
            return 1
        fi
        echo "动态找到路径: $multicast_file"
    fi

    echo "正在修补 $multicast_file ..."
    cp "$multicast_file" "$multicast_file.bak"
    # Replace br_ip_entry->addr.dst.ip6 with br_ip_entry->u.ip6 since newer kernels use a union
    sed -i 's/br_ip_entry->addr\.dst\.ip6/br_ip_entry->u.ip6/g' "$multicast_file"
    if grep -q 'br_ip_entry->u.ip6' "$multicast_file"; then
        echo "已成功修补 $multicast_file，将重试编译。"
        rm "$multicast_file.bak"
        return 0
    else
        echo "修补 $multicast_file 失败，恢复备份文件。"
        mv "$multicast_file.bak" "$multicast_file"
        return 1
    fi
}

### Fix batman-adv tasklet_setup symbol conflict
fix_batman_patch_tasklet() {
    local log_file="$1"
    echo "尝试修复 batman-adv 的 tasklet_setup 符号冲突..."
    local backports_header_path
    backports_header_path=$(grep -oE 'build_dir/target-[^/]+/linux-[^/]+/backports-[^/]+/backport-include/linux/interrupt\.h' "$log_file" | head -n 1)
    if [ -z "$backports_header_path" ] || [ ! -f "$backports_header_path" ]; then
        echo "无法从日志中定位 backports interrupt.h 文件路径，尝试动态查找..."
        backports_header_path=$(find build_dir -type f -path "*/backports-*/backport-include/linux/interrupt.h" -print -quit)
        if [ -z "$backports_header_path" ] || [ ! -f "$backports_header_path" ]; then
            echo "动态查找 backports interrupt.h 文件失败。"
            return 1
        fi
        echo "动态找到路径: $backports_header_path"
    fi
    echo "正在修补 $backports_header_path ..."
    sed -i.bak '/tasklet_setup/d' "$backports_header_path"
    if ! grep -q 'tasklet_setup' "$backports_header_path"; then
        echo "已从 $backports_header_path 移除 tasklet_setup。"
        return 0
    else
        echo "警告: 尝试从 $backports_header_path 移除 tasklet_setup 失败。"
        return 1
    fi
}

### Switch batman-adv package to specified commit
fix_batman_switch_package() {
    local target_commit="$1"
    echo "尝试切换 batman-adv 包源码至 commit $target_commit ..."
    if [ ! -d "feeds/routing/batman-adv" ]; then
        echo "错误: 目录 feeds/routing/batman-adv 不存在，无法切换包。请先确保 feeds 已更新。"
        return 1
    fi
    (
        cd feeds/routing/batman-adv || return 1
        echo "当前目录: $(pwd)"
        echo "运行: git fetch origin"
        git fetch origin || echo "警告: git fetch 失败，继续尝试 checkout..."
        echo "运行: git checkout $target_commit"
        if git checkout "$target_commit"; then
            echo "成功 checkout commit $target_commit"
        else
            echo "错误: 无法 checkout commit $target_commit"
            return 1
        fi
    ) || return 1
    echo "更新 feed 索引并安装 batman-adv..."
    ./scripts/feeds update -i batman-adv || { echo "错误: feeds update -i batman-adv 失败"; return 1; }
    ./scripts/feeds install -p routing batman-adv || { echo "错误: feeds install -p routing batman-adv 失败"; return 1; }
    echo "切换 batman-adv 包完成。"
    return 0
}

### Switch entire routing feed to specified commit
fix_batman_switch_feed() {
    local target_commit="$1"
    echo "尝试切换整个 routing feed 至 commit $target_commit ..."
    echo "删除旧的 feeds/routing ..."
    rm -rf feeds/routing
    echo "克隆 coolsnowwolf/routing ..."
    if ! git clone https://github.com/coolsnowwolf/routing.git feeds/routing; then
        echo "错误: 克隆 feeds/routing 失败。"
        return 1
    fi
    (
        cd feeds/routing || return 1
        echo "切换到 commit $target_commit ..."
        if ! git checkout "$target_commit"; then
            echo "错误: 无法 checkout commit $target_commit"
            return 1
        fi
        echo "成功 checkout commit $target_commit"
    ) || return 1
    echo "更新 routing feed 索引并安装 batman-adv..."
    ./scripts/feeds update -i routing || { echo "错误: feeds update -i routing 失败"; return 1; }
    ./scripts/feeds install -p routing batman-adv || { echo "错误: feeds install -p routing batman-adv 失败"; return 1; }
    echo "切换 routing feed 完成。"
    return 0
}

# --- Main Compilation Loop ---
retry_count=0
last_fix_applied=""
fix_applied_this_iteration=0
# Flags for batman-adv specific fixes
batman_br_ip_patched=0
batman_tasklet_patched=0
batman_package_switched=0
batman_feed_switched=0

while [ $retry_count -lt "$MAX_RETRY" ]; do
    echo "--------------------------------------------------"
    echo "尝试编译: $MAKE_COMMAND (第 $((retry_count + 1)) / $MAX_RETRY 次)..."
    echo "--------------------------------------------------"

    eval "$MAKE_COMMAND" > "$LOG_FILE" 2>&1
    COMPILE_STATUS=$?

    if [ $COMPILE_STATUS -eq 0 ]; then
        echo "编译成功！"
        exit 0
    fi

    echo "编译失败 (退出码: $COMPILE_STATUS)，检查错误..."
    extract_error_block "$LOG_FILE"
    fix_applied_this_iteration=0

    # --- Error Detection and Fix Logic (Order Matters) ---

    # 1. Batman-adv 'struct br_ip' dst error
    if grep -q "struct br_ip.*has no member named .dst" "$LOG_FILE" && grep -q "batman-adv.*multicast\.c" "$LOG_FILE"; then
        echo "检测到 batman-adv 的 'struct br_ip has no member named dst' 错误..."
        if [ "$batman_br_ip_patched" -eq 0 ]; then
            last_fix_applied="fix_batman_br_ip_dst"
            fix_batman_br_ip_dst "$LOG_FILE"
            if [ $? -eq 0 ]; then
                fix_applied_this_iteration=1
                batman_br_ip_patched=1
            else
                echo "修补 batman-adv br_ip dst 失败，尝试切换 commit..."
                if [ "$batman_package_switched" -eq 0 ]; then
                    fix_batman_switch_package "$BATMAN_ADV_COMMIT"
                    if [ $? -eq 0 ]; then
                        fix_applied_this_iteration=1
                        batman_package_switched=1
                    else
                        echo "切换 batman-adv 包失败，尝试切换整个 feed..."
                        if [ "$batman_feed_switched" -eq 0 ]; then
                            fix_batman_switch_feed "$BATMAN_ADV_COMMIT"
                            if [ $? -eq 0 ]; then
                                fix_applied_this_iteration=1
                                batman_feed_switched=1
                            else
                                echo "切换 routing feed 失败，无法修复 batman-adv。"
                                exit 1
                            fi
                        else
                            echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                            exit 1
                        fi
                    fi
                else
                    echo "已尝试切换 batman-adv 包，但错误仍然存在，尝试切换整个 feed..."
                    if [ "$batman_feed_switched" -eq 0 ]; then
                        fix_batman_switch_feed "$BATMAN_ADV_COMMIT"
                        if [ $? -eq 0 ]; then
                            fix_applied_this_iteration=1
                            batman_feed_switched=1
                        else
                            echo "切换 routing feed 失败，无法修复 batman-adv。"
                            exit 1
                        fi
                    else
                        echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                        exit 1
                    fi
                fi
            fi
        else
            echo "上次已尝试修补 br_ip dst 错误，但问题仍存在，尝试切换 commit..."
            if [ "$batman_package_switched" -eq 0 ]; then
                fix_batman_switch_package "$BATMAN_ADV_COMMIT"
                if [ $? -eq 0 ]; then
                    fix_applied_this_iteration=1
                    batman_package_switched=1
                else
                    echo "切换 batman-adv 包失败，尝试切换整个 feed..."
                    if [ "$batman_feed_switched" -eq 0 ]; then
                        fix_batman_switch_feed "$BATMAN_ADV_COMMIT"
                        if [ $? -eq 0 ]; then
                            fix_applied_this_iteration=1
                            batman_feed_switched=1
                        else
                            echo "切换 routing feed 失败，无法修复 batman-adv。"
                            exit 1
                        fi
                    else
                        echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                        exit 1
                    fi
                fi
            else
                echo "已尝试切换 batman-adv 包，但错误仍然存在，尝试切换整个 feed..."
                if [ "$batman_feed_switched" -eq 0 ]; then
                    fix_batman_switch_feed "$BATMAN_ADV_COMMIT"
                    if [ $? -eq 0 ]; then
                        fix_applied_this_iteration=1
                        batman_feed_switched=1
                    else
                        echo "切换 routing feed 失败，无法修复 batman-adv。"
                        exit 1
                    fi
                else
                    echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                    exit 1
                fi
            fi
        fi

    # 2. Batman-adv tasklet_setup error
    elif grep -q 'undefined reference to .*tasklet_setup' "$LOG_FILE" && grep -q -B 10 -A 10 'Entering directory.*batman-adv' "$LOG_FILE"; then
        echo "检测到 batman-adv 的 'tasklet_setup' 符号错误..."
        if [ "$batman_tasklet_patched" -eq 0 ]; then
            last_fix_applied="fix_batman_tasklet"
            fix_batman_patch_tasklet "$LOG_FILE"
            if [ $? -eq 0 ]; then
                fix_applied_this_iteration=1
                batman_tasklet_patched=1
            else
                echo "修复 batman-adv tasklet 失败，尝试切换 commit..."
                if [ "$batman_package_switched" -eq 0 ]; then
                    fix_batman_switch_package "$BATMAN_ADV_COMMIT"
                    if [ $? -eq 0 ]; then
                        fix_applied_this_iteration=1
                        batman_package_switched=1
                    else
                        echo "切换 batman-adv 包失败，尝试切换整个 feed..."
                        if [ "$batman_feed_switched" -eq 0 ]; then
                            fix_batman_switch_feed "$BATMAN_ADV_COMMIT"
                            if [ $? -eq 0 ]; then
                                fix_applied_this_iteration=1
                                batman_feed_switched=1
                            else
                                echo "切换 routing feed 失败，无法修复 batman-adv。"
                                exit 1
                            fi
                        else
                            echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                            exit 1
                        fi
                    fi
                else
                    echo "已尝试切换 batman-adv 包，但错误仍然存在，尝试切换整个 feed..."
                    if [ "$batman_feed_switched" -eq 0 ]; then
                        fix_batman_switch_feed "$BATMAN_ADV_COMMIT"
                        if [ $? -eq 0 ]; then
                            fix_applied_this_iteration=1
                            batman_feed_switched=1
                        else
                            echo "切换 routing feed 失败，无法修复 batman-adv。"
                            exit 1
                        fi
                    else
                        echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                        exit 1
                    fi
                fi
            fi
        else
            echo "上次已尝试修复 tasklet_setup，但错误依旧，尝试切换 commit..."
            if [ "$batman_package_switched" -eq 0 ]; then
                fix_batman_switch_package "$BATMAN_ADV_COMMIT"
                if [ $? -eq 0 ]; then
                    fix_applied_this_iteration=1
                    batman_package_switched=1
                else
                    echo "切换 batman-adv 包失败，尝试切换整个 feed..."
                    if [ "$batman_feed_switched" -eq 0 ]; then
                        fix_batman_switch_feed "$BATMAN_ADV_COMMIT"
                        if [ $? -eq 0 ]; then
                            fix_applied_this_iteration=1
                            batman_feed_switched=1
                        else
                            echo "切换 routing feed 失败，无法修复 batman-adv。"
                            exit 1
                        fi
                    else
                        echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                        exit 1
                    fi
                fi
            else
                echo "已尝试切换 batman-adv 包，但错误仍然存在，尝试切换整个 feed..."
                if [ "$batman_feed_switched" -eq 0 ]; then
                    fix_batman_switch_feed "$BATMAN_ADV_COMMIT"
                    if [ $? -eq 0 ]; then
                        fix_applied_this_iteration=1
                        batman_feed_switched=1
                    else
                        echo "切换 routing feed 失败，无法修复 batman-adv。"
                        exit 1
                    fi
                else
                    echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                    exit 1
                fi
            fi
        fi

    # 3. Trojan-plus buffer_cast error
    elif grep -q 'trojan-plus.*service.cpp.*buffer_cast.*boost::asio' "$LOG_FILE"; then
        echo "检测到 'trojan-plus boost::asio::buffer_cast' 错误..."
        if [ "$last_fix_applied" = "fix_trojan_plus" ]; then
            echo "上次已尝试修复 trojan-plus，但错误依旧，停止重试。"
            cat "$LOG_FILE"
            exit 1
        fi
        last_fix_applied="fix_trojan_plus"
        fix_trojan_plus_boost_error
        if [ $? -eq 0 ]; then
            fix_applied_this_iteration=1
        else
            echo "修复 trojan-plus 失败，停止重试。"
            cat "$LOG_FILE"
            exit 1
        fi

    # 4. po2lmo error
    elif grep -q "po2lmo: command not found" "$LOG_FILE"; then
        echo "检测到 'po2lmo' 错误..."
        if [ "$last_fix_applied" = "fix_po2lmo" ]; then
            echo "上次已尝试修复 po2lmo，但错误依旧，停止重试。"
            exit 1
        fi
        last_fix_applied="fix_po2lmo"
        fix_po2lmo
        if [ $? -eq 0 ]; then
            fix_applied_this_iteration=1
        else
            echo "修复 po2lmo 失败，停止重试。"
            exit 1
        fi

    # 5. Makefile separator error
    # 在 "--- Main Compilation Loop ---" 中修改 "missing separator" 的处理部分
    elif grep -q "missing separator.*Stop." "$LOG_FILE"; then
        echo "检测到 'missing separator' 错误..."
        last_fix_applied="fix_makefile_separator"
        fix_makefile_separator "$LOG_FILE"
        if [ $? -eq 0 ]; then
            fix_applied_this_iteration=1
        else
            echo "自动修复 Makefile 失败，尝试手动检查或更新源码..."
            # 可选：添加更新 OpenWrt 源码的逻辑
            # git pull || echo "更新源码失败，继续重试。"
            # 如果无法修复，可以继续重试而不是退出
            fix_applied_this_iteration=1
        fi

    # 6. Package metadata errors
    elif grep -E -q "package version is invalid|dependency format is invalid|duplicate dependency detected" "$LOG_FILE"; then
        echo "检测到包版本或依赖格式/重复错误..."
        if [ "$last_fix_applied" = "fix_metadata" ]; then
            echo "上次已尝试修复元数据，但错误依旧，停止重试。"
            exit 1
        fi
        last_fix_applied="fix_metadata"
        changed=0
        fix_pkg_version && changed=1
        fix_dependency_format && changed=1
        fix_depends && changed=1
        if [ $changed -eq 1 ]; then
            echo "应用了包元数据修复，将重试。"
            fix_applied_this_iteration=1
        else
            echo "检测到元数据错误，但修复函数未报告任何更改。"
        fi

    # 7. Filesystem conflicts
    elif grep -q "mkdir: cannot create directory.*File exists" "$LOG_FILE"; then
        echo "检测到 'mkdir File exists' 错误..."
        if [ "$last_fix_applied" = "fix_mkdir" ]; then
            echo "上次已尝试修复 mkdir 冲突，但错误依旧，停止重试。"
            exit 1
        fi
        last_fix_applied="fix_mkdir"
        fix_mkdir_conflict "$LOG_FILE"
        if [ $? -eq 0 ]; then
            fix_applied_this_iteration=1
        else
            echo "修复 mkdir 冲突失败，可能无法继续。"
            exit 1
        fi
    elif grep -q "ln: failed to create symbolic link.*File exists" "$LOG_FILE"; then
        echo "检测到 'ln File exists' 错误..."
        if [ "$last_fix_applied" = "fix_symlink" ]; then
            echo "上次已尝试修复符号链接冲突，但错误依旧，停止重试。"
            exit 1
        fi
        last Posted: 1 year ago
last_fix_applied="fix_symlink"
        fix_symbolic_link_conflict "$LOG_FILE"
        if [ $? -eq 0 ]; then
            fix_applied_this_iteration=1
        else
            echo "修复符号链接冲突失败，可能无法继续。"
            exit 1
        fi

    # 8. Batman-adv Last Resort: Commit Switching
    elif grep -q -i 'batman-adv' "$LOG_FILE" && [ $retry_count -ge $((MAX_RETRY / 2)) ]; then
        echo "检测到持续的 batman-adv 相关错误，尝试切换 commit..."
        if [ "$batman_package_switched" -eq 0 ]; then
            echo "尝试切换 batman-adv 包..."
            last_fix_applied="fix_batman_switch_pkg"
            fix_batman_switch_package "$BATMAN_ADV_COMMIT"
            if [ $? -eq 0 ]; then
                fix_applied_this_iteration=1
                batman_package_switched=1
            else
                echo "切换 batman-adv 包失败，下次将尝试切换整个 feed。"
                batman_package_switched=1
            fi
        elif [ "$batman_feed_switched" -eq 0 ]; then
            echo "切换包后仍失败，尝试切换整个 routing feed..."
            last_fix_applied="fix_batman_switch_feed"
            fix_batman_switch_feed "$BATMAN_ADV_COMMIT"
            if [ $? -eq 0 ]; then
                fix_applied_this_iteration=1
                batman_feed_switched=1
            else
                echo "切换 routing feed 失败，无法修复 batman-adv。"
                exit 1
            fi
        else
            echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
            exit 1
        fi

    # 9. Generic error pattern check
    elif grep -E -q "$ERROR_PATTERN" "$LOG_FILE"; then
        echo "检测到通用错误模式 ($ERROR_PATTERN)，尝试通用修复..."
        if [ "$last_fix_applied" = "fix_generic" ]; then
            echo "上次已尝试通用修复，但错误依旧，停止重试。"
            exit 1
        fi
        last_fix_applied="fix_generic"
        changed=0
        fix_pkg_version && changed=1
        fix_dependency_format && changed=1
        fix_depends && changed=1
        if [ $changed -eq 1 ]; then
            echo "应用了通用修复，将重试。"
            fix_applied_this_iteration=1
        else
            echo "检测到通用错误，但通用修复未应用更改。"
            exit 1
        fi
    else
        echo "未检测到已知或通用的错误模式。编译失败。"
        echo "请检查完整日志: $LOG_FILE"
        exit 1
    fi

    # --- Loop Control ---
    if [ $fix_applied_this_iteration -eq 0 ] && [ $COMPILE_STATUS -ne 0 ]; then
        echo "警告：检测到错误，但此轮未应用有效修复。检查日志并停止重试。"
        if [[ "$last_fix_applied" != fix_batman_switch* ]]; then
            echo "停止重试，因为未应用修复。"
            exit 1
        fi
    fi

    retry_count=$((retry_count + 1))
    sleep 3
done

# --- Final Failure ---
echo "--------------------------------------------------"
echo "达到最大重试次数 ($MAX_RETRY)，编译最终失败。"
echo "--------------------------------------------------"
extract_error_block "$LOG_FILE"
echo "请检查完整日志: $LOG_FILE"
exit 1
