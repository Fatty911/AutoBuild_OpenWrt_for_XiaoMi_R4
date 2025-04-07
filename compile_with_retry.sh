#!/bin/bash

# compile_with_retry.sh
# Assumes execution from the OpenWrt source root directory.
# Usage: bash compile_with_retry.sh <make_command> <log_file> [max_retry] [error_pattern]

# --- Configuration ---
BATMAN_ADV_COMMIT="5437d2c91fd9f15e06fbea46677abb529ed3547c" # Known good commit for batman-adv/routing feed
FEED_ROUTING_NAME="routing" # Name of the routing feed in feeds.conf[.default]
FEED_ROUTING_URL_PATTERN="github.com/coolsnowwolf/routing.git" # Part of the URL to identify the correct line

# --- Parameter Parsing ---
MAKE_COMMAND="$1"           # e.g., "make -j1 V=s" or "make package/compile V=s"
LOG_FILE="$2"               # e.g., "compile.log" or "packages.log"
MAX_RETRY="${3:-8}"         # Default max retries: 8
# Add new error patterns - ORDER MATTERS somewhat in the loop below
ERROR_PATTERN="${4:-cc1: some warnings being treated as errors|error:|failed|undefined reference|invalid|File exists|missing separator|cannot find dependency|No rule to make target}"

# --- Argument Check ---
if [ -z "$MAKE_COMMAND" ] || [ -z "$LOG_FILE" ]; then
    echo "错误：缺少必要参数。用法: $0 <make_command> <log_file> [max_retry] [error_pattern]"
    exit 1
fi

# --- Helper Function: Get Relative Path (Revised) ---
get_relative_path() {
    local path="$1"
    local current_pwd
    current_pwd=$(pwd) # Get PWD inside the function

    # Ensure path is absolute for realpath
    if [[ "$path" != /* ]]; then
        # Try making it absolute based on PWD
        if [ -e "$current_pwd/$path" ]; then
            path="$current_pwd/$path"
        else
            echo "$path" # Return as-is if can't resolve
            return
        fi
    fi
    realpath --relative-to="$current_pwd" "$path" 2>/dev/null || echo "$path"
}
fix_batman_multicast_struct() {
    local log_file="$1"
    echo "尝试修补 batman-adv 'struct br_ip' 错误..." >&2
    echo "日志文件: $log_file" >&2

    local multicast_file
    multicast_file=$(grep -oE 'build_dir/target-[^/]+/linux-[^/]+/(linux-[^/]+|batman-adv-[^/]+)/net/batman-adv/multicast\.c' "$log_file" | head -n 1)
    if [ -z "$multicast_file" ] || [ ! -f "$multicast_file" ]; then
        echo "无法从日志定位 multicast.c，尝试动态查找..." >&2
        multicast_file=$(find build_dir -type f -path "*/batman-adv-*/net/batman-adv/multicast.c" -o -path "*/linux-*/net/batman-adv/multicast.c" -print -quit)
        if [ -z "$multicast_file" ] || [ ! -f "$multicast_file" ]; then
            echo "动态查找 multicast.c 失败。" >&2
            return 1
        fi
        echo "动态找到 multicast.c: $multicast_file" >&2
    else
        echo "从日志找到 multicast.c: $multicast_file" >&2
    fi

    echo "正在修补 $multicast_file..." >&2
    cp "$multicast_file" "$multicast_file.bak"

    sed -i 's/src->dst\.ip4/src->u.ip4/g' "$multicast_file"
    sed -i 's/src->dst\.ip6/src->u.ip6/g' "$multicast_file"
    sed -i 's/br_ip_entry->addr\.dst\.ip4/br_ip_entry->addr.u.ip4/g' "$multicast_file"
    sed -i 's/br_ip_entry->addr\.dst\.ip6/br_ip_entry->addr.u.ip6/g' "$multicast_file"
    sed -i 's/IPV6_ADDR_MC_SCOPE(&br_ip_entry->addr\.dst\.ip6)/IPV6_ADDR_MC_SCOPE(&br_ip_entry->addr.u.ip6)/g' "$multicast_file"
    sed -i 's/br_multicast_has_router_adjacent/br_multicast_has_querier_adjacent/g' "$multicast_file"

    echo "检查修补结果..." >&2
    if ! grep -q 'dst\.ip[4|6]' "$multicast_file" && \
       ! grep -q 'br_multicast_has_router_adjacent' "$multicast_file"; then
        echo "成功修补 $multicast_file" >&2
        echo "清理 batman-adv 包以强制重新编译..." >&2
        make "package/feeds/routing/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: 清理 batman-adv 失败。" >&2
        local pkg_makefile
        pkg_makefile=$(find package feeds -path '*/batman-adv/Makefile' -print -quit)
        if [ -n "$pkg_makefile" ]; then
            touch "$pkg_makefile"
            echo "已触摸 $pkg_makefile 以强制重建。" >&2
        fi
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




fix_routing_feed_config() {
    local target_commit="$1"  # 指定兼容的 commit
    local feed_conf_file="feeds.conf.default"

    if [ -f "feeds.conf" ]; then
        feed_conf_file="feeds.conf"
        echo "使用 feeds.conf 文件。"
    fi

    echo "尝试修复 $feed_conf_file 中的 routing feed 配置..."

    # 检查并更新 routing feed
    if grep -q "^src-git routing" "$feed_conf_file"; then
        echo "routing feed 已存在，正在更新 commit..."
        sed -i "s|^src-git routing .*|src-git routing https://github.com/coolsnowwolf/routing.git;${target_commit}|" "$feed_conf_file"
    else
        echo "routing feed 不存在，正在添加..."
        echo "src-git routing https://github.com/coolsnowwolf/routing.git;${target_commit}" >> "$feed_conf_file"
    fi

    # 验证更改并更新 feeds
    if grep -q "src-git routing https://github.com/coolsnowwolf/routing.git;${target_commit}" "$feed_conf_file"; then
        echo "成功更新 $feed_conf_file 中的 routing feed 配置。"
        ./scripts/feeds update routing || echo "警告: feeds update routing 失败"
        ./scripts/feeds install -a -p routing || echo "警告: feeds install -a -p routing 失败"
        return 0
    else
        echo "更新 $feed_conf_file 失败。"
        return 1
    fi
}
# --- Function: Switch to a compatible batman-adv feed commit ---
fix_batman_switch_feed() {
    local target_commit="$1"
    local feed_name="$FEED_ROUTING_NAME"
    local feed_conf_file="feeds.conf.default"
    local feed_conf_line_pattern="src-git $feed_name .*$FEED_ROUTING_URL_PATTERN"
    local feed_conf_line_prefix="src-git $feed_name "

    echo "尝试切换 $feed_name feed 至 commit $target_commit 通过修改 feeds 配置文件..."

    # Determine which feeds file to use
    if [ -f "feeds.conf" ]; then
        feed_conf_file="feeds.conf"
        echo "使用 feeds.conf 文件。"
    elif [ -f "feeds.conf.default" ]; then
        feed_conf_file="feeds.conf.default"
        echo "使用 feeds.conf.default 文件。"
    else
        echo "错误: 未找到 feeds.conf 或 feeds.conf.default 文件。"
        return 1
    fi

    # Check if the line exists and already has the correct commit
    local current_line=$(grep "^$feed_conf_line_pattern" "$feed_conf_file" | head -n 1)
    local current_url=$(echo "$current_line" | awk '{print $3}' | cut -d';' -f1)
    local new_line="$feed_conf_line_prefix$current_url;$target_commit"

    if [ -z "$current_line" ]; then
        echo "错误: 未能在 $feed_conf_file 中找到 '$feed_conf_line_pattern' 定义。"
        echo "请手动检查你的 feeds 配置文件。"
        return 1
    fi

    if grep -q "^$(echo "$new_line" | sed 's/[^^]/[&]/g; s/\^/\\^/g')$" "$feed_conf_file"; then
        echo "$feed_name feed 已在 $feed_conf_file 中指向 commit $target_commit。"
        echo "运行 feeds update/install 以确保一致性..."
        ./scripts/feeds update "$feed_name" || { echo "错误: feeds update $feed_name 失败"; return 1; }
        ./scripts/feeds install -a -p "$feed_name" || { echo "错误: feeds install -a -p $feed_name 失败"; return 1; }
        return 0
    fi

    # Modify the line using sed
    echo "在 $feed_conf_file 中找到 $feed_name feed 定义，正在修改 commit..."
    cp "$feed_conf_file" "$feed_conf_file.bak"
    sed -i "s|^$feed_conf_line_pattern.*|$new_line|" "$feed_conf_file"

    # Verify change
    if grep -q "^$(echo "$new_line" | sed 's/[^^]/[&]/g; s/\^/\\^/g')$" "$feed_conf_file"; then
        echo "已将 $feed_conf_file 中的 $feed_name 更新为 commit $target_commit"
        rm "$feed_conf_file.bak"
    else
        echo "错误: 使用 sed 修改 $feed_conf_file 失败或未生效。"
        mv "$feed_conf_file.bak" "$feed_conf_file"
        return 1
    fi

    echo "运行 feeds update 和 install 以应用更改..."
    ./scripts/feeds update "$feed_name" || { echo "错误: feeds update $feed_name 失败"; return 1; }
    ./scripts/feeds install -a -p "$feed_name" || { echo "错误: feeds install -a -p $feed_name 失败"; return 1; }

    echo "切换 $feed_name feed 至 commit $target_commit 完成。"

    # Clean the potentially problematic package build dir after switching source
    echo "清理旧的 batman-adv 构建目录..."
    local build_dirs_found
    build_dirs_found=$(find build_dir -type d -name "batman-adv-*" -prune 2>/dev/null)
    if [ -n "$build_dirs_found" ]; then
        echo "找到以下 batman-adv 构建目录，将进行清理:"
        echo "$build_dirs_found"
        echo "$build_dirs_found" | xargs rm -rf
        if [ $? -eq 0 ]; then
            echo "构建目录清理完成。"
        else
            echo "警告: 清理 batman-adv 构建目录时可能出错。"
        fi
    else
        echo "未找到 batman-adv 构建目录，可能无需清理或查找失败。"
    fi

    # Also clean the source package directory
    make "package/feeds/$feed_name/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: 清理旧 batman-adv 包源文件失败。"
    return 0
}

# --- Function: Disable -Werror in batman-adv Makefile ---
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
                 # Clean the package to ensure new flags are used
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


# --- Fix Functions ---

### Fix trojan-plus boost::asio::buffer_cast error (Revised: Add Clean)
fix_trojan_plus_boost_error() {
    echo "修复 trojan-plus 中的 boost::asio::buffer_cast 错误..."
    local trojan_src_dir service_cpp found_path="" trojan_pkg_dir=""
    trojan_src_dir=$(find build_dir -type d -path '*/trojan-plus-*/src/core' -print -quit)
    if [ -n "$trojan_src_dir" ]; then
        service_cpp="$trojan_src_dir/service.cpp"
        if [ -f "$service_cpp" ]; then
            found_path="$service_cpp"
            # Try to determine package dir from build_dir path
            trojan_pkg_dir=$(echo "$trojan_src_dir" | sed -n 's|build_dir/[^/]*/\([^/]*\)/src/core|\1|p')
            echo "找到 trojan-plus 源码: $found_path (包构建目录推测: $trojan_pkg_dir)"
        else
            echo "在找到的目录 $trojan_src_dir 中未找到 service.cpp"
        fi
    fi
    if [ -z "$found_path" ]; then
        echo "未能在 build_dir 中动态找到 trojan-plus 源码路径，尝试基于日志猜测路径..."
        local target_build_dir=$(grep -oE '(/[^ ]+)?build_dir/target-[^/]+/trojan-plus-[^/]+' "$LOG_FILE" | head -n 1)
        if [ -n "$target_build_dir" ] && [ -d "$target_build_dir" ]; then
            service_cpp="$target_build_dir/src/core/service.cpp"
            if [ -f "$service_cpp" ]; then
                found_path="$service_cpp"
                trojan_pkg_dir=$(basename "$target_build_dir") # Get package dir name
                echo "根据日志猜测找到 trojan-plus 源码: $found_path (包构建目录推测: $trojan_pkg_dir)"
            fi
        fi
    fi
    if [ -z "$found_path" ]; then
        echo "无法定位 trojan-plus 的 service.cpp 文件，跳过修复。"
        return 1
    fi
    echo "尝试修复 $found_path ..."
    if sed -i.bak "s|boost::asio::buffer_cast<char\*>(\(udp_read_buf.prepare([^)]*)\))|static_cast<char*>(\1.data())|g" "$found_path"; then
        if grep -q 'static_cast<char\*>' "$found_path"; then
            echo "已成功修改 $found_path"
            rm "$found_path.bak"

            # Attempt to find the package source directory for cleaning
            local pkg_src_path=""
            if [ -n "$trojan_pkg_dir" ]; then
                 pkg_src_path=$(find package feeds -name "$(echo "$trojan_pkg_dir" | sed 's/-[0-9].*//')" -type d -print -quit)
            fi

            if [ -n "$pkg_src_path" ] && [ -d "$pkg_src_path" ]; then
                echo "尝试清理包 $pkg_src_path 以应用更改..."
                make "$pkg_src_path/clean" DIRCLEAN=1 V=s || echo "警告: 清理包 $pkg_src_path 失败。"
            else
                echo "警告: 未找到 trojan-plus 的源包目录，无法执行清理。可能需要手动清理。"
            fi
            return 0
        else
            echo "尝试修改 $found_path 失败 (sed 命令成功但未找到预期更改)，恢复备份文件。"
            mv "$found_path.bak" "$found_path"
            return 1
        fi
    else
         echo "尝试修改 $found_path 失败 (sed 命令失败)，恢复备份文件。"
         [ -f "$found_path.bak" ] && mv "$found_path.bak" "$found_path"
         return 1
    fi
}

### Fix po2lmo command not found
# (Keep existing)
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
# (Keep existing)
extract_error_block() {
    local log_file="$1"
    echo "--- 最近 300 行日志 (${log_file}) ---"
    tail -n 300 "$log_file"
    echo "--- 日志结束 ---"
}

### Fix PKG_VERSION and PKG_RELEASE formats
# (Keep existing, but check awk script logic carefully)
fix_pkg_version() {
    echo "修复 PKG_VERSION 和 PKG_RELEASE 格式..."
    local changed_count=0
    # Use find directly without intermediate variable for robustness
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -path "./build_dir/*" -prune -o -path "./staging_dir/*" -prune -o -path "./tmp/*" -prune -o -print0 | while IFS= read -r -d $'\0' makefile; do
        # Skip Makefiles that don't include standard package definitions more reliably
        if ! head -n 30 "$makefile" 2>/dev/null | grep -qE '^\s*(include \.\./\.\./(package|buildinfo)\.mk|include \$\(INCLUDE_DIR\)/package\.mk|include \$\(TOPDIR\)/rules\.mk)'; then
            continue
        fi

        local current_version release new_version new_release suffix modified_in_loop=0 makefile_changed=0 original_content
        original_content=$(cat "$makefile") # Read content once
        current_version=$(echo "$original_content" | sed -n 's/^PKG_VERSION:=\(.*\)/\1/p')
        release=$(echo "$original_content" | sed -n 's/^PKG_RELEASE:=\(.*\)/\1/p')

        # Case 1: Version string contains a hyphenated suffix (e.g., 1.2.3-beta1)
        if [[ "$current_version" =~ ^([0-9]+(\.[0-9]+)*)-([a-zA-Z0-9_.-]+)$ ]]; then
            new_version="${BASH_REMATCH[1]}"
            suffix="${BASH_REMATCH[3]}"
            # Try to extract number from suffix, default to 1. Be careful with versions like 2023-11-01
            new_release=$(echo "$suffix" | tr -cd '0-9' | grep -o '[0-9]*$' || echo "1") # Get trailing numbers, or 1
             if [ -z "$new_release" ] || ! [[ "$new_release" =~ ^[0-9]+$ ]]; then new_release=1; fi # Ensure it's a number

            if [ "$current_version" != "$new_version" ] || [ "$release" != "$new_release" ]; then
                echo "修改 $makefile: PKG_VERSION: '$current_version' -> '$new_version', PKG_RELEASE: '$release' -> '$new_release'"
                # Use awk for safer replacement/addition
                 awk -v ver="$new_version" -v rel="$new_release" '
                    BEGIN { release_found=0; version_printed=0 }
                    /^PKG_VERSION:=/ { print "PKG_VERSION:=" ver; version_printed=1; next }
                    /^PKG_RELEASE:=/ { print "PKG_RELEASE:=" rel; release_found=1; next }
                    { print }
                    END { if(version_printed && !release_found) print "PKG_RELEASE:=" rel }
                 ' "$makefile" > "$makefile.tmp" && mv "$makefile.tmp" "$makefile"

                release=$new_release # Update release variable for next check
                modified_in_loop=1
                makefile_changed=1
            fi
        fi

        # Case 2: PKG_RELEASE exists but is not a simple number (and wasn't just fixed in Case 1)
        if [ "$modified_in_loop" -eq 0 ] && [ -n "$release" ] && ! [[ "$release" =~ ^[0-9]+$ ]]; then
            new_release=$(echo "$release" | tr -cd '0-9' | grep -o '[0-9]*$' || echo "1") # Get trailing numbers, or 1
            if [ -z "$new_release" ] || ! [[ "$new_release" =~ ^[0-9]+$ ]]; then new_release=1; fi # Ensure it's a number
            if [ "$release" != "$new_release" ]; then
                echo "修正 $makefile: PKG_RELEASE: '$release' -> '$new_release'"
                sed -i.bak "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile" && rm "$makefile.bak"
                makefile_changed=1
            fi
        # Case 3: PKG_RELEASE is missing entirely and PKG_VERSION exists (and wasn't handled by Case 1 adding it)
        elif [ "$modified_in_loop" -eq 0 ] && [ -z "$release" ] && echo "$original_content" | grep -q "^PKG_VERSION:=" && ! echo "$original_content" | grep -q "^PKG_RELEASE:="; then
             echo "添加 $makefile: PKG_RELEASE:=1"
             # Use awk for safer addition after PKG_VERSION
             awk '
                /^PKG_VERSION:=/ { print; print "PKG_RELEASE:=1"; next }
                { print }
             ' "$makefile" > "$makefile.tmp" && mv "$makefile.tmp" "$makefile"
             makefile_changed=1
        fi

        if [ "$makefile_changed" -eq 1 ]; then
             changed_count=$((changed_count + 1))
        fi
    done
    echo "修复 PKG_VERSION/RELEASE 完成，共检查/修改 $changed_count 个文件。"
    if [ "$changed_count" -gt 0 ]; then return 0; else return 1; fi
}

### Fix duplicate dependencies
# (Keep existing, seems robust)
fix_depends() {
    echo "修复依赖重复..."
    local flag_file=".fix_depends_changed"
    rm -f "$flag_file"
    local changed_count=0

    find . -type f \( -name "Makefile" -o -name "*.mk" \) \
        \( -path "./build_dir/*" -o -path "./staging_dir/*" -o -path "./tmp/*" \) -prune -o \
        -exec sh -c '
            makefile="$1"
            flag_file_path="$2"

            # Skip non-Makefile files more reliably
            if ! head -n 30 "$makefile" 2>/dev/null | grep -qE "^\s*include.*\/(package|buildinfo|kernel|rules)\.mk"; then
                exit 0
            fi

            awk '\''
            BEGIN { FS = "[[:space:]]+"; OFS = " "; change_made = 0 }
            /^[[:space:]]*(DEPENDS|EXTRA_DEPENDS|PKG_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=/ {
                original_line = $0
                prefix = $1
                line = $0
                # Extract the dependencies part, handling potential comments at end of line
                sub(/^[[:space:]]*(DEPENDS|EXTRA_DEPENDS|PKG_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=[[:space:]]*/, "", line)
                dep_part = line
                comment_part = ""
                if (index(line, "#") > 0) {
                    comment_part = substr(line, index(line, "#"))
                    dep_part = substr(line, 1, index(line, "#") - 1)
                }
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", dep_part) # Trim whitespace

                delete seen_bare
                delete seen_versioned_pkg
                delete result_deps
                idx = 0
                # Use standard field splitting on the dependency part
                n = split(dep_part, deps, /[[:space:]]+/)

                for (i=1; i<=n; i++) {
                    dep = deps[i]
                    if (dep == "" || dep ~ /^\s*$/ || dep ~ /^\$\(.*\)/ ) { # Keep variables untouched
                        result_deps[idx++] = dep
                        continue
                    }

                    # Remove leading +
                    has_plus = (substr(dep, 1, 1) == "+")
                    bare_dep = dep
                    sub(/^\+/, "", bare_dep)

                    # Extract package name (handle version constraints)
                    pkg_name = bare_dep
                    if (match(pkg_name, />=|<=|==/)) {
                        pkg_name = substr(pkg_name, 1, RSTART - 1)
                    }

                    is_versioned = (bare_dep ~ />=|<=|==/)

                    if (is_versioned) {
                        # If we see a versioned dep, keep it and mark it seen.
                        # Also, mark the bare package name as covered by a versioned dep.
                        if (!(pkg_name in seen_versioned_pkg)) {
                            result_deps[idx++] = dep # Keep original (with + if present)
                            seen_versioned_pkg[pkg_name] = 1
                            # If a bare version was previously added, remove it
                            if (pkg_name in seen_bare) {
                                for (k=0; k<idx-1; ++k) {
                                    tmp_bare_k = result_deps[k]
                                    sub(/^\+/, "", tmp_bare_k)
                                    if (tmp_bare_k == pkg_name && !(result_deps[k] ~ />=|<=|==/)) {
                                        # Shift elements left to remove the bare entry
                                        for (l=k; l<idx-1; ++l) {
                                            result_deps[l] = result_deps[l+1]
                                        }
                                        idx--
                                        result_deps[idx] = "" # Clear the last (now duplicated) element
                                        break
                                    }
                                }
                            }
                            delete seen_bare[pkg_name] # Ensure bare is not added later
                        }
                    } else { # Bare dependency
                        # Add bare dependency only if neither bare nor versioned version has been seen
                        if (!(pkg_name in seen_bare) && !(pkg_name in seen_versioned_pkg)) {
                            result_deps[idx++] = dep # Keep original (with + if present)
                            seen_bare[pkg_name] = 1
                        }
                    }
                }

                # Build new deps string
                new_deps_str = ""
                for (j=0; j<idx; ++j) {
                    if (result_deps[j] != "") {
                         # Add space only if string is not empty and current dep is not empty
                        if (new_deps_str != "" && result_deps[j] != "") new_deps_str = new_deps_str " "
                        new_deps_str = new_deps_str result_deps[j]
                    }
                }

                # Reconstruct the full line, preserving original prefix and any trailing comments
                new_line = prefix " " new_deps_str
                if (comment_part != "") {
                    new_line = new_line " " comment_part
                }
                gsub(/[[:space:]]+$/, "", new_line) # Trim trailing whitespace

                # Compare with original (trimmed)
                original_line_trimmed = original_line
                gsub(/[[:space:]]+$/, "", original_line_trimmed)

                if (new_line != original_line_trimmed) {
                    print new_line
                    change_made = 1
                } else {
                    print original_line # Print original if no change
                }
                next # Move to next line in the file
            }
            { print } # Print lines that do not match the DEPENDS pattern
            END { exit !change_made } # Exit with 0 if changes were made, 1 otherwise
            '\'' "$makefile" > "$makefile.tmp"

            awk_status=$?
            if [ $awk_status -eq 0 ]; then
                 if [ -s "$makefile.tmp" ] && ! cmp -s "$makefile" "$makefile.tmp"; then
                     echo "修改 $makefile: 修复依赖重复"
                     mv "$makefile.tmp" "$makefile"
                     touch "$flag_file_path"
                     # Increment counter - tricky within sh -c, use flag file instead
                 else
                      rm -f "$makefile.tmp" # No change or empty output
                 fi
            elif [ $awk_status -eq 1 ]; then
                 rm -f "$makefile.tmp"
            else
                 echo "警告: 处理 $makefile 时 awk 脚本出错 (退出码: $awk_status)" >&2
                 rm -f "$makefile.tmp"
            fi

        ' _ {} "$flag_file" \;

    echo "修复重复依赖完成。"
    if [ -f "$flag_file" ]; then
        rm -f "$flag_file"
        return 0 # Changes were made
    else
        return 1 # No changes made
    fi
}


### Fix dependency format (Using Temp Awk File)
# (Keep existing, seems okay)
fix_dependency_format() {
    echo "尝试修复 Makefile 中的依赖格式 (使用临时文件)..."
    local flag_file=".fix_depformat_changed"
    local awk_script_file
    awk_script_file=$(mktemp /tmp/fix_dep_format_awk.XXXXXX)
    if [ -z "$awk_script_file" ]; then
        echo "错误: 无法创建临时 awk 脚本文件" >&2
        return 1
    fi
    # Ensure cleanup even if the script exits unexpectedly
    trap 'rm -f "$awk_script_file"' EXIT HUP INT QUIT TERM

    # Define the awk script content and write it to the temp file
    cat > "$awk_script_file" << 'EOF'
BEGIN { FS="[[:space:]]+"; OFS=" "; changed_file=0 }
/^[[:space:]]*(DEPENDS|EXTRA_DEPENDS|PKG_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=/ {
    original_line = $0
    line_changed = 0
    delete seen
    prefix = $1
    current_deps = ""
    # Rebuild dependency string, handling potential comments
    line = $0
    sub(/^[[:space:]]*(DEPENDS|EXTRA_DEPENDS|PKG_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS)\+?=[[:space:]]*/, "", line)
    dep_part = line
    comment_part = ""
    if (index(line, "#") > 0) {
        dep_part = substr(line, 1, index(line, "#") - 1)
        comment_part = substr(line, index(line, "#"))
    }
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", dep_part); # Trim whitespace from dep part

    if (dep_part != "") {
        split(dep_part, deps, /[[:space:]]+/) # Split deps by space
        new_deps_str = ""
        for (i=1; i<=length(deps); i++) {
            dep = deps[i]
            if (dep == "") continue
            original_dep = dep
            # Remove pkg-release suffix like -1, -10 from version constraints
            gsub(/(>=|<=|==)([0-9]+\.[0-9]+(\.[0-9]+)?(-[a-zA-Z0-9_.]+)?)-[0-9]+$/, "\\1\\2", dep)

            # Check if modification happened
            if (original_dep != dep) {
                line_changed = 1
            }

            # Add to new string if not already seen (basic duplicate check within the line)
            # This duplicate check might conflict with fix_depends, but harmless if run after fix_depends
            if (!seen[dep]++) {
                 if (new_deps_str != "") new_deps_str = new_deps_str " "
                new_deps_str = new_deps_str dep
            }
        }

        new_line = prefix (new_deps_str == "" ? "" : " " new_deps_str)
        if (comment_part != "") {
            new_line = new_line " " comment_part
        }
        gsub(/[[:space:]]+$/, "", new_line) # Trim trailing space

        original_line_trimmed = original_line
        gsub(/[[:space:]]+$/, "", original_line_trimmed)

        if (new_line != original_line_trimmed) {
             $0 = new_line # Replace the current line with the modified one
             changed_file=1
        }
    }
}
{ print } # Print the (potentially modified) line or original line
END { exit !changed_file } # Exit 0 if changes were made
EOF

    # Check if the temp file was created successfully
    if [ ! -s "$awk_script_file" ]; then
         echo "错误: 未能成功写入临时 awk 脚本文件 $awk_script_file" >&2
         rm -f "$awk_script_file"
         trap - EXIT HUP INT QUIT TERM # Clear trap
         return 1
    fi

    # Now use find with the awk script file
    rm -f "$flag_file"
    local changed_count=0
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -path "./build_dir/*" -prune -o -path "./staging_dir/*" -prune -o -path "./tmp/*" -prune -o -exec sh -c '
        makefile="$1"
        flag_file_path="$2"
        awk_script_path="$3" # Pass the temp script path to sh -c

        # Skip non-Makefile files more reliably
        if ! head -n 30 "$makefile" 2>/dev/null | grep -qE "^\s*include.*\/(package|buildinfo|kernel|rules)\.mk"; then
             exit 0
        fi
        cp "$makefile" "$makefile.bak" # Backup before processing

        # Execute awk using the script file
        awk -f "$awk_script_path" "$makefile" > "$makefile.tmp"
        awk_status=$?

        if [ $awk_status -eq 0 ]; then # Changes were made by awk
           if [ -s "$makefile.tmp" ] && ! cmp -s "$makefile" "$makefile.tmp"; then
                echo "修改 $makefile: 调整依赖格式"
                mv "$makefile.tmp" "$makefile"
                rm "$makefile.bak" # Remove backup on successful change
                touch "$flag_file_path"
           else
                # Awk reported changes (exit 0), but files are same or tmp is empty? Unexpected.
                # echo "警告: awk声称修改了 $makefile 但文件未变或为空。" >&2
                rm "$makefile.tmp"
                rm "$makefile.bak" # No change needed, remove backup
           fi
        elif [ $awk_status -eq 1 ]; then # Awk reported no changes needed
             rm "$makefile.tmp"
             rm "$makefile.bak" # Remove backup
        else # Awk script itself had an error
             echo "警告: awk 处理 $makefile 时出错 (退出码: $awk_status)，已从备份恢复。" >&2
             rm "$makefile.tmp"
             # Keep the backup file if awk failed catastrophically
             mv "$makefile.bak" "$makefile"
        fi
    ' _ {} "$flag_file" "$awk_script_file" \; # Pass flag_file and awk_script_file as arguments

    local find_status=$? # Capture find's exit status (optional)

    # Clean up the temporary file
    rm -f "$awk_script_file"
    trap - EXIT HUP INT QUIT TERM # Clear the trap
    echo "修复依赖格式完成。"

    if [ -f "$flag_file" ]; then
        rm -f "$flag_file"
        return 0
    else
        if [ $find_status -ne 0 ]; then
             echo "警告: find 命令在 fix_dependency_format 中可能遇到了错误。" >&2
        fi
        return 1
    fi
}


### Fix mkdir conflicts
# (Keep existing, logic seems okay)
fix_mkdir_conflict() {
    local log_file="$1"
    echo "检测到 'mkdir: cannot create directory ... File exists' 错误，尝试修复..."
    local FAILED_PATH PKG_ERROR_LINE PKG_PATH PKG_NAME PKG_DIR_REL PKG_BUILD_DIR_PART

    # Extract the conflicting path
    FAILED_PATH=$(grep "mkdir: cannot create directory" "$log_file" | grep "File exists" | sed -e "s/.*mkdir: cannot create directory '\([^']*\)'.*/\1/" | tail -n 1)
    if [ -z "$FAILED_PATH" ]; then
        echo "无法从日志中提取冲突的路径。"
        return 1
    fi
    echo "冲突路径: $FAILED_PATH"

    # Clean the conflicting path if it exists
    if [ -e "$FAILED_PATH" ]; then
        echo "正在清理已存在的冲突路径: $FAILED_PATH"
        rm -rf "$FAILED_PATH"
        if [ -e "$FAILED_PATH" ]; then
             echo "警告：无法删除冲突路径 $FAILED_PATH"
             # This might be serious, return failure? Or let retry happen? Let's warn and continue.
             # return 1
        else
            echo "已成功删除冲突路径。"
        fi
    else
        echo "警告：冲突路径 $FAILED_PATH 已不存在。"
    fi

    # Try to identify the package causing the error more reliably
    # Look further back in the log, as the error message might appear after the package context
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 100 "mkdir: cannot create directory '$FAILED_PATH'" | grep -m 1 -Eo '(ERROR: (package|feeds)/[^ ]+ failed to build\.|make\[[0-9]+\]: Entering directory.*(package|feeds)/[^ ]+|make\[[0-9]+\]: \*\*\* \[(.*)/\.built\] Error)')
    PKG_PATH=""
    PKG_DIR_REL=""
    PKG_BUILD_DIR_PART="" # Initialize

    if [[ -n "$PKG_ERROR_LINE" ]]; then
        echo "找到相关错误/上下文行: $PKG_ERROR_LINE"
        if [[ "$PKG_ERROR_LINE" == ERROR:* ]]; then
            PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build\./\1/')
            if [[ -d "$PKG_PATH" ]]; then
                 PKG_DIR_REL="$PKG_PATH"
                 echo "从 'ERROR:' 行推断出包目录: $PKG_DIR_REL"
            else
                 echo "警告: 从 'ERROR:' 行提取的路径 '$PKG_PATH' 不是一个有效目录。"
                 PKG_PATH=""
            fi
        elif [[ "$PKG_ERROR_LINE" == *'Entering directory'* ]]; then
             PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed -n "s|.*Entering directory .*/\(package/[^ ']*/[^ /']*\).*|\1|p; s|.*Entering directory .*/\(feeds/[^ ']*/[^ /']*\).*|\1|p" | head -n 1)
             # Attempt to convert absolute path if pattern failed
             if [ -z "$PKG_PATH" ]; then
                 ABS_PATH=$(echo "$PKG_ERROR_LINE" | sed -n "s|.*Entering directory '\([^']*\)'.*|\1|p")
                 if [ -n "$ABS_PATH" ]; then
                     PKG_DIR_REL_TMP=$(get_relative_path "$ABS_PATH")
                     if [[ -n "$PKG_DIR_REL_TMP" ]] && [[ "$PKG_DIR_REL_TMP" == package/* || "$PKG_DIR_REL_TMP" == feeds/* ]]; then
                         PKG_DIR_REL="$PKG_DIR_REL_TMP"
                         PKG_PATH="$PKG_DIR_REL"
                         echo "从 'Entering directory' 行推断出包目录 (相对路径): $PKG_DIR_REL"
                     fi
                 fi
             elif [[ -d "$PKG_PATH" ]]; then
                  PKG_DIR_REL="$PKG_PATH"
                  echo "从 'Entering directory' 行推断出包目录: $PKG_DIR_REL"
             else
                  echo "警告: 从 'Entering directory' 行提取的路径 '$PKG_PATH' 不是有效目录。"
                  PKG_PATH=""
             fi

        elif [[ "$PKG_ERROR_LINE" == *'/.built]* Error'* ]]; then
             PKG_BUILD_DIR_PART=$(echo "$PKG_ERROR_LINE" | sed -n 's|make\[[0-9]\+\]: \*\*\* \[\(.*\)/\.built\] Error.*|\1|p')
             if [[ "$PKG_BUILD_DIR_PART" == *build_dir/* ]]; then
                  PKG_NAME_GUESS=$(basename "$PKG_BUILD_DIR_PART" | sed -e 's/-[0-9].*//' -e 's/_.*//')
                  PKG_PATH_FOUND=$(find package feeds -name "$PKG_NAME_GUESS" -type d -print -quit)
                  if [[ -n "$PKG_PATH_FOUND" ]] && ( [[ "$PKG_PATH_FOUND" == ./package/* ]] || [[ "$PKG_PATH_FOUND" == ./feeds/* ]] ); then
                       PKG_DIR_REL="${PKG_PATH_FOUND#./}"
                       PKG_PATH="$PKG_DIR_REL"
                       echo "从 .built 错误推断出包目录: $PKG_DIR_REL"
                  else
                       echo "警告: 无法从 .built 错误 '$PKG_BUILD_DIR_PART' 关联到 package/ 或 feeds/ 中的目录。"
                  fi
             fi
        fi
    fi

    # If we identified a package directory, clean it
    if [[ -n "$PKG_DIR_REL" ]] && [ -d "$PKG_DIR_REL" ]; then
        PKG_NAME=$(basename "$PKG_DIR_REL")
        echo "推测是包 '$PKG_NAME' ($PKG_DIR_REL) 导致了错误。"
        echo "尝试清理包 $PKG_NAME..."
        make "$PKG_DIR_REL/clean" DIRCLEAN=1 V=s || {
            echo "清理包 $PKG_NAME 失败，但已删除冲突路径，将继续尝试主编译命令。"
        }
        echo "已清理包 $PKG_NAME，将重试主命令。"
    else
        echo "无法从日志中明确推断出导致错误的包或推断的路径无效。仅删除了冲突路径。"
        # Also try cleaning the specific build dir if identified
        if [[ -n "$PKG_BUILD_DIR_PART" ]] && [ -d "$PKG_BUILD_DIR_PART" ]; then
             echo "尝试清理具体的 build_dir: $PKG_BUILD_DIR_PART"
             rm -rf "$PKG_BUILD_DIR_PART" || echo "警告: 删除 $PKG_BUILD_DIR_PART 失败"
        fi
    fi
    return 0 # Return success because the conflicting path was removed, allowing a retry
}

### Fix symbolic link conflicts
# (Keep existing, logic seems okay)
fix_symbolic_link_conflict() {
    local log_file="$1"
    echo "检测到 'ln: failed to create symbolic link ... File exists' 错误，尝试修复..."
    local FAILED_LINK PKG_ERROR_LINE PKG_PATH PKG_NAME PKG_DIR_REL PKG_BUILD_DIR_PART

    # Extract the conflicting link path
    FAILED_LINK=$(grep "ln: failed to create symbolic link" "$log_file" | grep "File exists" | sed -e "s/.*failed to create symbolic link '\([^']*\)'.*/\1/" | tail -n 1)
    if [ -z "$FAILED_LINK" ]; then
        echo "无法从日志中提取冲突的符号链接路径。"
        return 1
    fi
    echo "冲突链接: $FAILED_LINK"

    # Clean the conflicting link/file if it exists
    if [ -e "$FAILED_LINK" ]; then # Use -e to check for files or links
        echo "正在清理已存在的冲突文件/链接: $FAILED_LINK"
        rm -rf "$FAILED_LINK"
        if [ -e "$FAILED_LINK" ]; then
             echo "警告：无法删除冲突链接/文件 $FAILED_LINK"
             # return 1
        else
             echo "已成功删除冲突链接/文件。"
        fi
    else
         echo "警告：冲突链接 $FAILED_LINK 已不存在。"
    fi

    # Try to identify the package causing the error (similar logic as fix_mkdir_conflict)
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 100 "failed to create symbolic link '$FAILED_LINK'" | grep -m 1 -Eo '(ERROR: (package|feeds)/[^ ]+ failed to build\.|make\[[0-9]+\]: Entering directory.*(package|feeds)/[^ ]+|make\[[0-9]+\]: \*\*\* \[(.*)/\.built\] Error)')
    PKG_PATH=""
    PKG_DIR_REL=""
    PKG_BUILD_DIR_PART="" # Initialize

    if [[ -n "$PKG_ERROR_LINE" ]]; then
         echo "找到相关错误/上下文行: $PKG_ERROR_LINE"
         # (Same logic as fix_mkdir_conflict to find PKG_DIR_REL / PKG_BUILD_DIR_PART)
        if [[ "$PKG_ERROR_LINE" == ERROR:* ]]; then
            PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build\./\1/')
            if [[ -d "$PKG_PATH" ]]; then PKG_DIR_REL="$PKG_PATH"; echo "从 'ERROR:' 行推断: $PKG_DIR_REL"; else PKG_PATH=""; fi
        elif [[ "$PKG_ERROR_LINE" == *'Entering directory'* ]]; then
             PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed -n "s|.*Entering directory .*/\(package/[^ ']*/[^ /']*\).*|\1|p; s|.*Entering directory .*/\(feeds/[^ ']*/[^ /']*\).*|\1|p" | head -n 1)
             if [ -z "$PKG_PATH" ]; then
                 ABS_PATH=$(echo "$PKG_ERROR_LINE" | sed -n "s|.*Entering directory '\([^']*\)'.*|\1|p")
                 if [ -n "$ABS_PATH" ]; then
                     PKG_DIR_REL_TMP=$(get_relative_path "$ABS_PATH")
                     if [[ -n "$PKG_DIR_REL_TMP" ]] && [[ "$PKG_DIR_REL_TMP" == package/* || "$PKG_DIR_REL_TMP" == feeds/* ]]; then
                         PKG_DIR_REL="$PKG_DIR_REL_TMP"; PKG_PATH="$PKG_DIR_REL"; echo "从 'Entering directory' (相对路径)推断: $PKG_DIR_REL";
                     fi; fi
             elif [[ -d "$PKG_PATH" ]]; then PKG_DIR_REL="$PKG_PATH"; echo "从 'Entering directory' 推断: $PKG_DIR_REL";
             else PKG_PATH=""; fi
        elif [[ "$PKG_ERROR_LINE" == *'/.built]* Error'* ]]; then
             PKG_BUILD_DIR_PART=$(echo "$PKG_ERROR_LINE" | sed -n 's|make\[[0-9]\+\]: \*\*\* \[\(.*\)/\.built\] Error.*|\1|p')
             if [[ "$PKG_BUILD_DIR_PART" == *build_dir/* ]]; then
                  PKG_NAME_GUESS=$(basename "$PKG_BUILD_DIR_PART" | sed -e 's/-[0-9].*//' -e 's/_.*//')
                  PKG_PATH_FOUND=$(find package feeds -name "$PKG_NAME_GUESS" -type d -print -quit)
                  if [[ -n "$PKG_PATH_FOUND" ]] && ( [[ "$PKG_PATH_FOUND" == ./package/* ]] || [[ "$PKG_PATH_FOUND" == ./feeds/* ]] ); then
                       PKG_DIR_REL="${PKG_PATH_FOUND#./}"; PKG_PATH="$PKG_DIR_REL"; echo "从 .built 错误推断: $PKG_DIR_REL";
                  fi; fi
        fi
    fi

    # If we identified a package directory, clean it
    if [[ -n "$PKG_DIR_REL" ]] && [ -d "$PKG_DIR_REL" ]; then
        PKG_NAME=$(basename "$PKG_DIR_REL")
        echo "推测是包 '$PKG_NAME' ($PKG_DIR_REL) 导致了错误。"
        echo "尝试清理包 $PKG_NAME..."
        make "$PKG_DIR_REL/clean" DIRCLEAN=1 V=s || {
             echo "清理包 $PKG_NAME 失败，但已删除冲突链接，将继续尝试主编译命令。"
        }
        echo "已清理包 $PKG_NAME，将重试主命令。"
    else
        echo "无法从日志中明确推断出导致错误的包或路径无效。仅删除了冲突链接。"
         if [[ -n "$PKG_BUILD_DIR_PART" ]] && [ -d "$PKG_BUILD_DIR_PART" ]; then
             echo "尝试清理具体的 build_dir: $PKG_BUILD_DIR_PART"
             rm -rf "$PKG_BUILD_DIR_PART" || echo "警告: 删除 $PKG_BUILD_DIR_PART 失败"
        fi
    fi
    return 0 # Return success because the conflicting item was removed
}


### Fix Makefile "missing separator" error (Revised Path Handling)
### Fix Makefile "missing separator" error (Revised Path Handling v2)
fix_makefile_separator() {
    local log_file="$1"
    echo "检测到 'missing separator' 错误，尝试修复..."
    local error_line_info makefile_name_from_err line_num context_dir full_makefile_path makefile_path_rel fix_attempted=0 line_content tab pkg_dir

    # 从日志中提取错误行信息
    error_line_info=$(grep -m 1 'missing separator.*Stop.' "$log_file" | grep -E '^(.+):([0-9]+): \*\*\* missing separator')
    if [[ "$error_line_info" =~ ^([^:]+):([0-9]+): ]]; then
        makefile_name_from_err="${BASH_REMATCH[1]}"
        line_num="${BASH_REMATCH[2]}"
        echo "从错误行提取: 文件名部分='$makefile_name_from_err', 行号='$line_num'"
    else
        echo "警告: 无法提取文件名和行号。"
        return 1
    fi

    # 查找最近的 "Entering directory" 以确定上下文目录
    context_dir=$(tac "$log_file" | grep -A 50 -m 1 "$error_line_info" | grep -m 1 -E "^make\[[0-9]+\]: Entering directory '([^']+)'" | sed -n "s/.*Entering directory '\([^']*\)'/\1/p")
    if [ -n "$context_dir" ]; then
        echo "找到上下文目录: $context_dir"
        full_makefile_path="$context_dir/$makefile_name_from_err"
    elif [ -f "$makefile_name_from_err" ]; then
        full_makefile_path="$makefile_name_from_err"
        echo "使用当前目录中的文件: $full_makefile_path"
    else
        # 特殊处理 package/libs/toolchain
        if grep -q "package/libs/toolchain" "$log_file"; then
            full_makefile_path="package/libs/toolchain/Makefile"
            echo "推测为工具链包的 Makefile: $full_makefile_path"
        else
            echo "错误: 无法定位 Makefile 文件。"
            return 1
        fi
    fi

    # 获取相对路径
    makefile_path_rel=$(get_relative_path "$full_makefile_path")
    if [ $? -ne 0 ] || [ -z "$makefile_path_rel" ] && [ -f "$full_makefile_path" ]; then
        makefile_path_rel="$full_makefile_path"
        echo "使用推测路径: $makefile_path_rel"
    fi

    echo "确定出错的 Makefile: $makefile_path_rel, 行号: $line_num"

    # 尝试修复缩进
    if [ -f "$makefile_path_rel" ] && [ -n "$line_num" ] && [[ "$line_num" =~ ^[0-9]+$ ]]; then
        line_content=$(sed -n "${line_num}p" "$makefile_path_rel")
        if [[ "$line_content" =~ ^[[:space:]]+ ]] && ! [[ "$line_content" =~ ^\t ]]; then
            echo "检测到第 $line_num 行使用空格缩进，替换为 TAB..."
            cp "$makefile_path_rel" "$makefile_path_rel.bak"
            printf -v tab '\t'
            sed -i "${line_num}s/^[[:space:]]\+/$tab/" "$makefile_path_rel"
            if [ $? -eq 0 ] && sed -n "${line_num}p" "$makefile_path_rel" | grep -q "^\t"; then
                echo "成功修复缩进。"
                rm -f "$makefile_path_rel.bak"
                fix_attempted=1
            else
                echo "修复失败，恢复备份。"
                mv "$makefile_path_rel.bak" "$makefile_path_rel"
            fi
        else
            echo "第 $line_num 行无需修复（已是 TAB、注释或空行）。"
        fi
    else
        echo "文件 '$makefile_path_rel' 不存在或行号无效。"
    fi

    # 无论是否修复成功，都尝试清理相关目录
    pkg_dir=$(dirname "$makefile_path_rel")
    if [ -d "$pkg_dir" ] && [[ "$pkg_dir" =~ ^(package|feeds|tools|toolchain)/ || "$pkg_dir" == "." ]]; then
        if [ "$pkg_dir" == "." ]; then
            echo "错误发生在根目录 Makefile，尝试清理整个构建环境..."
            make clean V=s || echo "警告: 清理根目录失败。"
        else
            echo "尝试清理目录: $pkg_dir..."
            make "$pkg_dir/clean" DIRCLEAN=1 V=s || echo "警告: 清理 $pkg_dir 失败。"
        fi
        fix_attempted=1
    else
        echo "目录 '$pkg_dir' 无效或非标准目录，跳过清理。"
    fi

    # 特殊处理 package/libs/toolchain
    if [[ "$makefile_path_rel" =~ package/libs/toolchain ]] && [ $fix_attempted -eq 0 ]; then
        echo "检测到工具链包错误，强制清理 package/libs/toolchain..."
        make "package/libs/toolchain/clean" DIRCLEAN=1 V=s || echo "警告: 清理工具链失败。"
        fix_attempted=1
    fi

    [ $fix_attempted -eq 1 ] && return 0 || return 1
}

### Fix batman-adv functions
# (Keep existing batman functions: fix_batman_br_ip_dst, fix_batman_disable_werror, fix_batman_patch_tasklet, fix_batman_switch_feed)
# ... (batman functions omitted for brevity, assume they are correct as before) ...
### Fix batman-adv 'struct br_ip' dst error (REVISED for IPV6_ADDR_MC_SCOPE)
fix_batman_br_ip_dst() {
    local log_file="$1"
    echo "尝试修复 batman-adv 的 'struct br_ip has no member named dst' 错误..."

    local multicast_file patch_applied=0
    # 从日志中提取 multicast.c 文件路径
    multicast_file=$(grep -oE 'build_dir/target-[^/]+/linux-[^/]+/(linux-[^/]+|batman-adv-[^/]+)/net/batman-adv/multicast\.c' "$log_file" | head -n 1)
    if [ -z "$multicast_file" ] || [ ! -f "$multicast_file" ]; then
        echo "无法从日志中定位 multicast.c 文件，尝试动态查找..."
        multicast_file=$(find build_dir -type f \( -path "*/batman-adv-*/net/batman-adv/multicast.c" -o -path "*/linux-*/net/batman-adv/multicast.c" \) -print -quit)
        if [ -z "$multicast_file" ] || [ ! -f "$multicast_file" ]; then
            echo "动态查找 multicast.c 文件失败。"
            return 1
        fi
        echo "动态找到路径: $multicast_file"
    fi

    echo "正在修补 $multicast_file ..."
    cp "$multicast_file" "$multicast_file.bak"

    # 替换所有 addr.dst.ip4 和 addr.dst.ip6 为 u.ip4 和 u.ip6
    sed -i 's/br_ip_entry->addr\.dst\.ip4/br_ip_entry->u.ip4/g' "$multicast_file"
    sed -i 's/br_ip_entry->addr\.dst\.ip6/br_ip_entry->u.ip6/g' "$multicast_file"
    # 处理 IPV6_ADDR_MC_SCOPE 的调用
    sed -i 's/IPV6_ADDR_MC_SCOPE\(&br_ip_entry->addr\.dst\.ip6\)/IPV6_ADDR_MC_SCOPE\(&br_ip_entry->u.ip6\)/g' "$multicast_file"

    # 检查修补是否成功
    if ! grep -q 'br_ip_entry->addr\.dst\.ip[4|6]' "$multicast_file" && \
       ! grep -q 'IPV6_ADDR_MC_SCOPE(&br_ip_entry->addr.dst.ip6)' "$multicast_file"; then
        echo "成功修补 $multicast_file，所有 'addr.dst' 引用已替换为 'u'。"
        patch_applied=1
    else
        echo "警告: $multicast_file 中仍存在 'addr.dst' 模式，修补可能不完整。"
    fi

    if [ $patch_applied -eq 1 ]; then
        echo "修补完成。清理 batman-adv 构建目录..."
        local build_dir_path
        build_dir_path=$(echo "$multicast_file" | sed -n 's|\(.*/build_dir/[^/]\+/[^/]\+/[^/]\+\)/.*|\1|p')
        if [ -n "$build_dir_path" ] && [ -d "$build_dir_path" ]; then
            echo "正在清理构建目录: $build_dir_path"
            rm -rf "$build_dir_path" || echo "警告: 删除构建目录 $build_dir_path 失败。"
            # 触摸 Makefile 以确保重新构建
            local pkg_makefile
            pkg_makefile=$(find package feeds -path '*/batman-adv/Makefile' -print -quit)
            [ -n "$pkg_makefile" ] && touch "$pkg_makefile"
        else
            echo "警告: 无法确定构建目录，尝试清理包源..."
            local pkg_dir_rel
            pkg_dir_rel=$(find package feeds -name "batman-adv" -type d -path "*/batman-adv" -print -quit)
            if [ -n "$pkg_dir_rel" ] && [ -d "$pkg_dir_rel" ]; then
                echo "尝试清理包源 $pkg_dir_rel..."
                make "$pkg_dir_rel/clean" DIRCLEAN=1 V=s || echo "警告: 清理 $pkg_dir_rel 失败。"
            else
                echo "警告: 无法确定 batman-adv 包目录，跳过清理。"
            fi
        fi
        rm -f "$multicast_file.bak"
        return 0
    else
        echo "修补 $multicast_file 失败，恢复备份文件。"
        [ -f "$multicast_file.bak" ] && mv "$multicast_file.bak" "$multicast_file"
        return 1
    fi
}


fix_batman_patch_tasklet() {
    local log_file="$1"
    echo "尝试修复 batman-adv 的 tasklet_setup 符号冲突..."
    local backports_header_path
    backports_header_path=$(grep -oE 'build_dir/target-[^/]+/linux-[^/]+/(backports|compat)-[^/]+/backport-include/linux/interrupt\.h' "$log_file" | head -n 1)
    if [ -z "$backports_header_path" ] || [ ! -f "$backports_header_path" ]; then
        echo "无法从日志中定位 backports/compat interrupt.h 文件路径，尝试动态查找..."
        backports_header_path=$(find build_dir -type f \( -path "*/backports-*/backport-include/linux/interrupt.h" -o -path "*/compat-*/backport-include/linux/interrupt.h" \) -print -quit)
        if [ -z "$backports_header_path" ] || [ ! -f "$backports_header_path" ]; then
            echo "动态查找 backports/compat interrupt.h 文件失败。"
            return 1
        fi
        echo "动态找到路径: $backports_header_path"
    fi
    echo "正在修补 $backports_header_path ..."
    if grep -q 'tasklet_setup' "$backports_header_path"; then
        cp "$backports_header_path" "$backports_header_path.bak" # Backup before patching
        sed -i.bak '/tasklet_setup/d' "$backports_header_path"
        if ! grep -q 'tasklet_setup' "$backports_header_path"; then
            echo "已从 $backports_header_path 移除 tasklet_setup 定义。"
            rm -f "$backports_header_path.bak" # Remove backup on success
             # Clean batman-adv after patching
             echo "清理 batman-adv 构建目录..."
             local pkg_dir_rel=""
             pkg_dir_rel=$(find package feeds -name "batman-adv" -type d -path "*/batman-adv" -print -quit)
             if [[ -n "$pkg_dir_rel" ]] && [ -d "$pkg_dir_rel" ]; then
                 make "$pkg_dir_rel/clean" DIRCLEAN=1 V=s || echo "警告: 清理 $pkg_dir_rel 失败。"
             else
                 echo "警告: 无法确定 batman-adv 包目录，跳过清理。"
             fi
            return 0
        else
            echo "警告: 尝试从 $backports_header_path 移除 tasklet_setup 失败，恢复备份。"
            if [ -f "$backports_header_path.bak" ]; then mv "$backports_header_path.bak" "$backports_header_path"; fi
            return 1
        fi
    else
         echo "$backports_header_path 中未找到 tasklet_setup 定义，无需修补。"
         return 0 # Return success as no action was needed
    fi
}


### Fix missing dependency during packaging stage
# (Keep existing, logic seems appropriate for this error type)
fix_missing_dependency() {
    local log_file="$1"
    local missing_dep_pattern='(cannot find dependency|Cannot satisfy.+dependencies for|Unmet dependencies) ([^ ]+)( for|:|\.)'
    local missing_pkg install_pkg_name pkg_path fix_attempted=0

    echo "检测到安装/打包阶段缺少依赖项错误..."

    # Extract the first missing package name (try different patterns)
    missing_pkg=$(grep -E -o "$missing_dep_pattern" "$log_file" | sed -n -r "s/$missing_dep_pattern/\2/p" | head -n 1)

    if [ -z "$missing_pkg" ]; then
        echo "无法从日志中提取缺少的依赖项名称。"
        # Try another common pattern from opkg
        missing_pkg=$(grep -o 'satisfy_dependencies_for: Cannot satisfy the following dependencies for [^:]*:[[:space:]]*\* *([^ ]*) *$' "$log_file" | sed 's/.*\* *//' | head -n 1)
         if [ -z "$missing_pkg" ]; then
             echo "再次尝试提取失败。"
             return 1 # Cannot proceed without package name
         fi
    fi
    # Clean potential garbage around the name
    missing_pkg=$(echo "$missing_pkg" | sed 's/[()*,;:]//g')
    echo "检测到缺少的依赖项: $missing_pkg"

    # Strategy 1: Force feeds update/install (Essential for this type of error)
    echo "尝试强制更新和安装所有 feeds 包..."
    ./scripts/feeds update -a || echo "警告: feeds update -a 失败"
    ./scripts/feeds install -a || {
        echo "警告: feeds install -a 失败。这可能是导致依赖问题的原因。"
        # Consider exiting if install -a fails? Maybe not, let compile attempt continue.
    }
    # Check if the specific package can be installed now
    install_pkg_name=$(./scripts/feeds list | grep -w "$missing_pkg$" | cut -d' ' -f1) # Get full package name if possible
    if [ -n "$install_pkg_name" ]; then
        echo "尝试显式安装 specific package $install_pkg_name..."
        ./scripts/feeds install "$install_pkg_name" || echo "警告: 安装 $install_pkg_name 失败"
    else
         echo "警告: 在 feeds list 中找不到包 '$missing_pkg'"
    fi
    fix_attempted=1 # Mark fix as attempted

    # Strategy 2: Try to compile the specific package
    echo "尝试查找并编译包 '$missing_pkg'..."
    pkg_path=$(./scripts/feeds find "$missing_pkg" | grep -E "(package|feeds)/.*/$missing_pkg$" | head -n 1)

    if [ -n "$pkg_path" ] && [ -d "$pkg_path" ]; then
        echo "找到包目录: $pkg_path"
        echo "尝试编译: make $pkg_path/compile V=s"
        make "$pkg_path/compile" V=s || {
            echo "编译 $pkg_path 失败。"
            # Attempt clean and recompile once
            echo "尝试清理并重新编译: $pkg_path..."
            make "$pkg_path/clean" V=s DIRCLEAN=1 || echo "清理 $pkg_path 失败"
            make "$pkg_path/compile" V=s || echo "再次编译 $pkg_path 仍然失败。"
        }
        fix_attempted=1
    else
        echo "无法在 package/ 或 feeds/ 中找到 '$missing_pkg' 的目录。可能需要手动检查。"
        # Special check for kernel modules
        if [[ "$missing_pkg" == kmod-* ]]; then
             kmod_name=${missing_pkg#kmod-}
             # Guess kernel module path (this varies!)
             kmod_path=$(find package/kernel package/network libs drivers -name "$kmod_name" -type d -print -quit)
             if [ -n "$kmod_path" ] && [ -d "$kmod_path" ]; then
                  echo "找到可能的内核模块目录: $kmod_path"
                  echo "尝试编译: make $kmod_path/compile V=s"
                   make "$kmod_path/compile" V=s || echo "编译 $kmod_path 失败."
                   fix_attempted=1
             else
                  echo "无法找到内核模块 '$kmod_name' 的源目录。"
             fi
        fi
    fi

    # Strategy 3: Re-run make index
    echo "运行 make package/index ..."
    make package/index V=s || echo "警告: make package/index 失败"
    fix_attempted=1

    # Final Advice
    echo "--------------------------------------------------"
    echo "重要提示: 依赖项 '$missing_pkg' 缺失的最常见原因是它没有在配置中启用或 feeds 未正确安装。"
    echo "如果此重试仍然失败，请运行 'make menuconfig' 并确保选中了 '$missing_pkg' 及其所有依赖项，然后尝试 'make download && make V=s'。"
    echo "--------------------------------------------------"

    # Return success as fixes were attempted, let the main loop retry
    # Return failure only if we couldn't even extract the package name
    if [ $fix_attempted -eq 1 ]; then return 0; else return 1; fi
}

# --- Main Compilation Loop ---
retry_count=0
last_fix_applied=""
fix_applied_this_iteration=0
# Flags for batman-adv specific fixes
batman_br_ip_patched=0
batman_tasklet_patched=0
batman_feed_switched=0
# Flag to indicate a metadata fix ran (PKV_VERSION, DEPENDS, FORMAT)
metadata_fix_ran_last_iter=0
batman_werror_disabled=0


while [ $retry_count -lt "$MAX_RETRY" ]; do
    echo "--------------------------------------------------"
    echo "尝试编译: $MAKE_COMMAND (第 $((retry_count + 1)) / $MAX_RETRY 次)..."
    echo "--------------------------------------------------"

    # Reset iteration flag
    fix_applied_this_iteration=0

    # Before compiling, if metadata was fixed last time, run 'make package/index'
    if [ $metadata_fix_ran_last_iter -eq 1 ]; then
        echo "元数据已在上一次迭代中修复，正在运行 'make package/index'..."
        make package/index V=s || echo "警告: make package/index 失败，继续编译..."
        metadata_fix_ran_last_iter=0 # Reset flag
    fi


    # Run the command and capture status/log
    echo "执行: $MAKE_COMMAND"
    eval "$MAKE_COMMAND" > "$LOG_FILE.tmp" 2>&1
    COMPILE_STATUS=$?
    # 过滤掉 WARNING: Makefile ... 的行
    grep -v "WARNING: Makefile '.*' has a dependency on '.*', which does not exist" "$LOG_FILE.tmp" >> "$LOG_FILE"
    cat "$LOG_FILE.tmp" # 显示未过滤的当前输出

    # 检查编译是否成功
    if [ $COMPILE_STATUS -eq 0 ] && \
       ! grep -q -E "^(make\[[0-9]+\]|make): \*\*\* .* Error [0-9]+$" "$LOG_FILE.tmp" && \
       ! grep -q -E "Collected errors:" "$LOG_FILE.tmp" && \
       ! grep -q -E "ERROR: package.* failed to build" "$LOG_FILE.tmp"; then
        echo "编译成功！"
        rm "$LOG_FILE.tmp"
        exit 0
    fi

    echo "编译失败 (退出码: $COMPILE_STATUS 或在日志中检测到错误)，检查错误..."
    extract_error_block "$LOG_FILE.tmp" # Show relevant part of current log

    # --- Error Detection and Fix Logic (Order Matters!) ---
    # Use $LOG_FILE.tmp for checking errors from the *current* attempt

    # 0. VERY SPECIFIC ERRORS FIRST
    # Trojan-plus buffer_cast error
    if grep -q 'trojan-plus.*service.cpp.*buffer_cast.*boost::asio' "$LOG_FILE.tmp"; then
        echo "检测到 'trojan-plus boost::asio::buffer_cast' 错误..."
        if [ "$last_fix_applied" = "fix_trojan_plus" ]; then
            echo "上次已尝试修复 trojan-plus，但错误依旧，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_trojan_plus"
        if fix_trojan_plus_boost_error; then
            fix_applied_this_iteration=1
        else
            echo "修复 trojan-plus 失败，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
        # Batman-adv generic compile error
    elif grep -q "batman-adv.*multicast\.c.*error:" "$LOG_FILE.tmp"; then
        echo "检测到 batman-adv 编译错误..."
        if [ "$batman_multicast_patched" -eq 0 ]; then
            echo "尝试修补 multicast.c..."
            if fix_batman_multicast_struct "$LOG_FILE.tmp"; then
                fix_applied_this_iteration=1
                batman_multicast_patched=1
                echo "修补成功，将重试编译..."
            else
                echo "修补 multicast.c 失败，将尝试修复 routing feed..."
                batman_multicast_patched=1
            fi
        elif [ "$batman_feed_fixed" -eq 0 ]; then
            echo "尝试修复 routing feed 配置到 commit $BATMAN_ADV_COMMIT..."
            if fix_routing_feed_config "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
                batman_feed_fixed=1
                echo "Feed 配置已修复，将重试编译..."
            else
                echo "修复 routing feed 配置失败。"
                batman_feed_fixed=1
            fi
        else
            echo "已尝试修补 multicast.c 和修复 routing feed，但 batman-adv 错误仍存在，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
    # Batman-adv 'struct br_ip' dst error with -Werror
    elif grep -q "struct br_ip.*has no member named" "$LOG_FILE.tmp" && grep -q "cc1: some warnings being treated as errors" "$LOG_FILE.tmp" && grep -q -E "batman-adv.*multicast\.c" "$LOG_FILE.tmp"; then
        echo "检测到 batman-adv 'struct br_ip' 错误且 -Werror 生效..."
        if [ "$batman_br_ip_patched" -eq 0 ]; then
            echo "尝试修补 multicast.c..."
            last_fix_applied="fix_batman_br_ip_dst_werror"
            if fix_batman_br_ip_dst "$LOG_FILE.tmp"; then
                fix_applied_this_iteration=1
                batman_br_ip_patched=1
            else
                echo "修补 multicast.c 失败。"
                batman_br_ip_patched=1
            fi
        elif [ "$batman_werror_disabled" -eq 0 ]; then
            echo "尝试禁用 -Werror..."
            last_fix_applied="fix_batman_disable_werror"
            if fix_batman_disable_werror; then
                fix_applied_this_iteration=1
                batman_werror_disabled=1
            else
                echo "禁用 -Werror 失败。"
            fi
        elif [ "$batman_feed_switched" -eq 0 ]; then
            echo "尝试切换 routing feed..."
            last_fix_applied="fix_batman_switch_feed_werror"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
                batman_feed_switched=1
            else
                echo "切换 routing feed 失败。"
                batman_feed_switched=1
            fi
        else
            echo "已尝试修补、禁用 -Werror 和切换 feed，但错误仍存在，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi

    # Batman-adv 'struct br_ip' dst error (WITHOUT -Werror)
    elif grep -q "struct br_ip.*has no member named" "$LOG_FILE.tmp" && grep -q -E "(batman-adv|net/batman-adv).*multicast\.c" "$LOG_FILE.tmp"; then
        echo "Detected batman-adv struct br_ip 'dst' error (no -Werror)..."
        if [ "$batman_br_ip_patched" -eq 0 ]; then
            last_fix_applied="fix_batman_multicast_struct"
            if fix_batman_multicast_struct "$LOG_FILE.tmp"; then
                fix_applied_this_iteration=1
                batman_br_ip_patched=1
                echo "Patch applied successfully, retrying compilation..."
            else
                echo "Failed to patch multicast.c, attempting to switch feed next..."
                batman_br_ip_patched=1
            fi
        elif [ "$batman_feed_switched" -eq 0 ]; then
            echo "Switching routing feed to a known compatible commit..."
            last_fix_applied="fix_batman_switch_feed"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
                batman_feed_switched=1
                echo "Feed switched to commit $BATMAN_ADV_COMMIT, retrying compilation..."
            else
                echo "Failed to switch routing feed."
                batman_feed_switched=1
            fi
        else
            echo "All attempts to fix batman-adv (patching and feed switch) failed. Aborting."
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi



    # Batman-adv tasklet_setup error
    elif grep -q 'undefined reference to .*tasklet_setup' "$LOG_FILE.tmp" && grep -q -B 10 -A 10 -E 'Entering directory.*(batman-adv|backports|compat)' "$LOG_FILE.tmp"; then
        echo "检测到 batman-adv 的 'tasklet_setup' 符号错误..."
        # Order: Switch Feed -> Patch backports
        if [ "$batman_feed_switched" -eq 0 ]; then
             echo "尝试切换整个 routing feed..."
             last_fix_applied="fix_batman_switch_feed_tasklet"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1; batman_feed_switched=1
            else
                echo "切换 routing feed 失败。下次将尝试修补 backports。"
                batman_feed_switched=1 # Mark as tried
            fi
        elif [ "$batman_tasklet_patched" -eq 0 ]; then
            last_fix_applied="fix_batman_tasklet"
            if fix_batman_patch_tasklet "$LOG_FILE.tmp"; then
                fix_applied_this_iteration=1; batman_tasklet_patched=1
            else
                echo "修复 batman-adv backports tasklet 失败，放弃。"
                cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
                exit 1
            fi
        else # All attempts failed
             echo "已尝试切换 feed 和修补 backports，但 tasklet 错误仍然存在，放弃。"
             cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
             exit 1
         fi
     
    # po2lmo error
    elif grep -q "po2lmo: command not found" "$LOG_FILE.tmp"; then
        echo "检测到 'po2lmo' 错误..."
        if [ "$last_fix_applied" = "fix_po2lmo" ]; then
            echo "上次已尝试修复 po2lmo，但错误依旧，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_po2lmo"
        if fix_po2lmo; then
            fix_applied_this_iteration=1
        else
            echo "修复 po2lmo 失败，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi

    # 1. FILESYSTEM/MAKEFILE STRUCTURE ERRORS
    # Makefile separator error
    elif grep -q "missing separator.*Stop." "$LOG_FILE.tmp"; then
        echo "检测到 'missing separator' 错误..."
        # Don't stop if it failed once, try again, maybe context changes
        # if [ "$last_fix_applied" = "fix_makefile_separator" ]; then
        #      echo "上次已尝试修复 makefile separator，但错误依旧，停止重试。"
        #      cat "$LOG_FILE.tmp" >> "$LOG_FILE"; rm "$LOG_FILE.tmp"; exit 1
        # fi
        last_fix_applied="fix_makefile_separator"
        if fix_makefile_separator "$LOG_FILE.tmp"; then # Pass current log segment
            fix_applied_this_iteration=1
            echo "Makefile separator 修复尝试完成，将重试编译。"
        else
            echo "无法定位或清理导致 'missing separator' 错误的 Makefile，此轮修复失败。"
            # Don't exit immediately, maybe another error will be fixed next round
        fi

    # Filesystem conflicts (mkdir, ln)
    elif grep -q "mkdir: cannot create directory.*File exists" "$LOG_FILE.tmp"; then
        echo "检测到 'mkdir File exists' 错误..."
        # Allow multiple attempts as different conflicts might occur
        last_fix_applied="fix_mkdir"
        if fix_mkdir_conflict "$LOG_FILE.tmp"; then
            fix_applied_this_iteration=1
        else
            echo "修复 mkdir 冲突失败，可能无法继续。"
            # Allow retry loop to continue, maybe cleaning helped partially
        fi
    elif grep -q "ln: failed to create symbolic link.*File exists" "$LOG_FILE.tmp"; then
        echo "检测到 'ln File exists' 错误..."
        # Allow multiple attempts
        last_fix_applied="fix_symlink"
        if fix_symbolic_link_conflict "$LOG_FILE.tmp"; then
            fix_applied_this_iteration=1
        else
            echo "修复符号链接冲突失败，可能无法继续。"
            # Allow retry loop to continue
        fi

    # 2. DEPENDENCY & METADATA ERRORS
    # Missing dependency during packaging/install stage (High Priority for this type)
    elif grep -q -E '(cannot find dependency|Cannot satisfy.+dependencies for|Unmet dependencies)' "$LOG_FILE.tmp" && grep -q -E 'pkg_hash_check_unresolved|opkg_install_cmd|satisfy_dependencies_for' "$LOG_FILE.tmp"; then
        echo "检测到打包/安装阶段缺少依赖项错误..."
        if [ "$last_fix_applied" = "fix_missing_dependency" ]; then
            echo "上次已尝试修复缺失的依赖项，但错误依旧。请检查 .config。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_missing_dependency"
        if fix_missing_dependency "$LOG_FILE.tmp"; then
            fix_applied_this_iteration=1
        else
            echo "修复缺失依赖项的尝试失败。请检查 .config。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi

    # Package metadata errors (Version, Dependency Format, Duplicates) - Lower priority now
    elif grep -E -q "package version is invalid|dependency format is invalid|duplicate dependency detected|has a dependency on .* which does not exist" "$LOG_FILE.tmp"; then
        echo "检测到包元数据错误 (版本/依赖格式/重复/缺失)..."
        if [ "$last_fix_applied" = "fix_metadata" ] && [ $metadata_fix_ran_last_iter -eq 0 ]; then # Avoid immediate loop if no changes were made last time
            echo "上次已尝试修复元数据但无更改或错误依旧，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_metadata"
        changed_version=0
        changed_format=0
        changed_depends=0
        metadata_fix_ran_last_iter=0 # Reset flag for this iteration

        echo "运行 PKG_VERSION/RELEASE 修复..."
        fix_pkg_version && changed_version=1 && echo "PKG_VERSION/RELEASE 修复应用了更改。"
        echo "运行依赖格式修复..."
        fix_dependency_format && changed_format=1 && echo "依赖格式修复应用了更改。"
        echo "运行重复依赖修复..."
        fix_depends && changed_depends=1 && echo "重复依赖修复应用了更改。"

        if [ $changed_version -eq 1 ] || [ $changed_format -eq 1 ] || [ $changed_depends -eq 1 ]; then
            echo "应用了包元数据修复，将运行 'make package/index' 后重试。"
            fix_applied_this_iteration=1
            metadata_fix_ran_last_iter=1 # Set flag to run 'make package/index' next iter
        else
            echo "检测到元数据错误，但修复函数未报告任何更改。"
            if grep -q "dependency on .* which does not exist" "$LOG_FILE.tmp"; then
                echo "警告: 检测到 'dependency ... which does not exist'。这通常需要手动检查 .config 或 feeds 是否正确/完整。"
                echo "将继续重试，但可能失败。"
                fix_applied_this_iteration=1 # Allow retry loop, maybe another error appears
            else
                echo "未应用元数据修复，停止重试。"
                cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
                exit 1
            fi
        fi

    # 3. GENERIC ERRORS / FALLBACKS
    # Batman-adv Last Resort: Feed Switching
    elif grep -q -i 'batman-adv' "$LOG_FILE.tmp" && [ $retry_count -ge 3 ]; then # Try later
        echo "检测到持续的 batman-adv 相关错误，尝试切换 feed (如果尚未进行)..."
        if [ "$batman_feed_switched" -eq 0 ]; then
            echo "尝试切换整个 routing feed 到已知良好 commit..."
            last_fix_applied="fix_batman_switch_feed_fallback"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
                batman_feed_switched=1
            else
                echo "切换 routing feed 失败，无法修复 batman-adv。"
                cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
                exit 1
            fi
        else
            echo "已尝试切换 batman-adv feed，但错误仍然存在，放弃。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi

    # Generic error pattern check (Last resort before giving up)
    elif grep -E -q "$ERROR_PATTERN" "$LOG_FILE.tmp"; then
        local matched_pattern
        matched_pattern=$(grep -E -m 1 "$ERROR_PATTERN" "$LOG_FILE.tmp")
        echo "检测到通用错误模式 ($ERROR_PATTERN): $matched_pattern"
        # Avoid immediate loop on generic error if no fix applied
        if [ "$last_fix_applied" = "fix_generic" ] && [ $fix_applied_this_iteration -eq 0 ]; then
             echo "上次已尝试通用修复但无效果，错误依旧，停止重试。"
             cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
             exit 1
        fi

        # Generic fix: try metadata fixes again? Or just retry? Let's just retry once.
        echo "未找到特定修复程序，将重试编译一次。"
        last_fix_applied="fix_generic_retry"
        # No fix applied this iteration, rely on loop counter
    else
        # If no known error pattern matched, but compile failed
        echo "未检测到已知或通用的错误模式，但编译失败 (退出码: $COMPILE_STATUS)。"
        echo "请检查完整日志: $LOG_FILE"
        cat "$LOG_FILE.tmp" >> "$LOG_FILE" # Append the final failed log segment
        rm "$LOG_FILE.tmp"
        exit 1
    fi

    # --- Loop Control ---
    if [ $fix_applied_this_iteration -eq 0 ] && [ $COMPILE_STATUS -ne 0 ]; then
        echo "警告：检测到错误，但此轮未应用有效修复。上次尝试: ${last_fix_applied:-无}"
        # Allow one simple retry even if no fix was applied, maybe it was transient
        if [ "$last_fix_applied" = "fix_generic_retry" ] || [ $retry_count -ge $((MAX_RETRY - 1)) ]; then
             echo "停止重试，因为未应用有效修复或已达重试上限。"
             cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
             exit 1
        else
             echo "将再重试一次，检查是否有其他可修复的错误出现。"
             last_fix_applied="fix_generic_retry" # Mark that we are doing a simple retry
        fi
    fi

    # Clean up temp log for this iteration
    rm "$LOG_FILE.tmp"

    retry_count=$((retry_count + 1))
    echo "等待 3 秒后重试..."
    sleep 3
done

# --- Final Failure ---
echo "--------------------------------------------------"
echo "达到最大重试次数 ($MAX_RETRY)，编译最终失败。"
echo "--------------------------------------------------"
# Show last 300 lines of the *full* log file
extract_error_block "$LOG_FILE"
echo "请检查完整日志: $LOG_FILE"
exit 1
