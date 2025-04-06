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
# Added 'br_multicast_has_router_adjacent' and 'struct br_ip.*has no member' specifically
ERROR_PATTERN="${4:-br_multicast_has_router_adjacent|struct br_ip.*has no member|cc1: some warnings being treated as errors|error:|failed|undefined reference|invalid|File exists|missing separator|cannot find dependency|No rule to make target}"

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

# --- NEW Function: Patch batman-adv multicast.c issues ---
fix_batman_multicast_struct() {
    local log_file="$1"
    echo "尝试修补 batman-adv 的 'struct br_ip' 和 'br_multicast_has_router_adjacent' 错误..."
    local patch_applied=0
    local cleanup_needed=0

    # 尝试从日志中提取 multicast.c 文件路径
    local multicast_file
    multicast_file=$(grep -oE 'build_dir/target-[^/]+/linux-[^/]+/(linux-[^/]+|batman-adv-[^/]+)/net/batman-adv/multicast\.c' "$log_file" | head -n 1)
    if [ -z "$multicast_file" ] || [ ! -f "$multicast_file" ]; then
        echo "无法从日志中定位 multicast.c 文件，尝试动态查找..."
        multicast_file=$(find build_dir -type f \( -path "*/batman-adv-*/net/batman-adv/multicast.c" -o -path "*/linux-*/net/batman-adv/multicast.c" \) -print -quit)
        if [ -z "$multicast_file" ] || [ ! -f "$multicast_file" ]; then
            echo "动态查找 multicast.c 文件失败。"
            return 1 # Cannot patch if file not found
        fi
        echo "动态找到路径: $multicast_file"
    fi

    echo "正在修补 $multicast_file ..."
    # Create backup only if file exists
    [ -f "$multicast_file" ] && cp "$multicast_file" "$multicast_file.bak"

    # Apply patches using sed
    # 1. Replace 'dst' member access with 'u' member access for struct br_ip
    sed -i 's/src->dst\.ip4/src->u.ip4/g' "$multicast_file"
    sed -i 's/src->dst\.ip6/src->u.ip6/g' "$multicast_file"
    sed -i 's/br_ip_entry->addr\.dst\.ip4/br_ip_entry->u.ip4/g' "$multicast_file"
    sed -i 's/br_ip_entry->addr\.dst\.ip6/br_ip_entry->u.ip6/g' "$multicast_file"
    # Fix the IPV6_ADDR_MC_SCOPE call as well
    sed -i 's/IPV6_ADDR_MC_SCOPE(&br_ip_entry->addr\.dst\.ip6)/IPV6_ADDR_MC_SCOPE(&br_ip_entry->u.ip6)/g' "$multicast_file"

    # 2. Replace incompatible function name
    sed -i 's/br_multicast_has_router_adjacent/br_multicast_has_querier_adjacent/g' "$multicast_file"

    # Check if patches were applied successfully (at least partially)
    if ! grep -q 'br_ip_entry->addr\.dst\.ip[46]' "$multicast_file" && \
       ! grep -q 'src->dst\.ip[46]' "$multicast_file" && \
       ! grep -q 'IPV6_ADDR_MC_SCOPE(&br_ip_entry->addr\.dst\.ip6)' "$multicast_file" && \
       ! grep -q 'br_multicast_has_router_adjacent' "$multicast_file" ; then
        echo "成功修补 $multicast_file (struct br_ip.dst -> u, router -> querier)"
        patch_applied=1
        cleanup_needed=1
    elif ! grep -q 'br_multicast_has_router_adjacent' "$multicast_file"; then
         echo "成功修补 $multicast_file (router -> querier), 但可能仍有 struct br_ip 问题。"
         patch_applied=1 # Mark as partially applied
         cleanup_needed=1
    elif ! grep -q 'br_ip_entry->addr\.dst\.ip[46]' "$multicast_file"; then
        echo "成功修补 $multicast_file (struct br_ip.dst -> u), 但可能仍有函数问题。"
        patch_applied=1 # Mark as partially applied
        cleanup_needed=1
    else
        echo "修补 $multicast_file 失败，检查 sed 命令或文件内容。"
        patch_applied=0
    fi

    if [ $patch_applied -eq 1 ]; then
        # Clean the build directory for batman-adv to force recompilation with patch
        local build_dir_path
        # Try to find the specific batman-adv build dir related to the file
        build_dir_path=$(echo "$multicast_file" | sed -n 's|\(build_dir/target-[^/]\+/[^/]\+/batman-adv-[^/]\+\)/.*|\1|p')
         # Fallback to finding any batman-adv build dir if specific one not matched
        if [ -z "$build_dir_path" ]; then
             build_dir_path=$(find build_dir -type d -name "batman-adv-*" -print -quit)
        fi

        if [ -n "$build_dir_path" ] && [ -d "$build_dir_path" ]; then
            echo "正在清理构建目录: $build_dir_path"
            rm -rf "$build_dir_path" || echo "警告: 删除构建目录 $build_dir_path 失败。"
            # Also try cleaning via make target
            make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: make clean for batman-adv 失败。"
        else
             echo "警告: 无法找到 batman-adv 的 build_dir 进行清理。"
             # Try cleaning via make target anyway
             make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: make clean for batman-adv 失败。"
        fi
        # Remove backup on success
        rm -f "$multicast_file.bak"
        return 0 # Success
    else
        # Restore backup if patching failed
        echo "恢复备份文件 $multicast_file.bak"
        [ -f "$multicast_file.bak" ] && mv "$multicast_file.bak" "$multicast_file"
        return 1 # Failure
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
    local current_url=$(echo "$current_line" | awk '{print $3}' | cut -d';' -f1) # Extract URL before potential ;commit
    local new_line="$feed_conf_line_prefix$current_url;$target_commit" # Ensure ;commit format

    if [ -z "$current_line" ]; then
        echo "警告: 未能在 $feed_conf_file 中找到 '$feed_conf_line_pattern' 定义。"
        echo "尝试添加该行..."
        echo "$new_line" >> "$feed_conf_file"
        current_line=$(grep "^$feed_conf_line_pattern" "$feed_conf_file" | head -n 1) # Re-check
        if [ -z "$current_line" ]; then
             echo "错误: 添加 $feed_name 定义到 $feed_conf_file 失败。"
             return 1
        fi
        echo "已添加 $feed_name 定义。"
    fi

    # Ensure the URL part is present before appending commit hash
    if [ -z "$current_url" ]; then
        echo "错误: 无法从 '$current_line' 中提取 URL。请检查 $feed_conf_file。"
        return 1
    fi

    # Check if already correct
    if grep -q "^$(echo "$new_line" | sed 's/[^^]/[&]/g; s/\^/\\^/g')$" "$feed_conf_file"; then
        echo "$feed_name feed 已在 $feed_conf_file 中指向 commit $target_commit。"
        echo "运行 feeds update/install 以确保一致性..."
        ./scripts/feeds update "$feed_name" || { echo "错误: feeds update $feed_name 失败"; return 1; }
        ./scripts/feeds install -a -p "$feed_name" || { echo "错误: feeds install -a -p $feed_name 失败"; return 1; }
        # Clean build dir after potential update/install
        echo "清理旧的 batman-adv 构建目录（以防万一）..."
        find build_dir -type d -name "batman-adv-*" -prune -exec rm -rf {} + || echo "警告: 清理 batman-adv 构建目录失败或未找到。"
        make "package/feeds/$feed_name/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: 清理旧 batman-adv 包源文件失败。"
        return 0
    fi

    # Modify the line using sed (handle cases with or without existing commit)
    echo "在 $feed_conf_file 中找到 $feed_name feed 定义，正在修改 commit..."
    cp "$feed_conf_file" "$feed_conf_file.bak"
    # Use a pattern that matches the line start and URL, replacing the rest
    sed -i "s|^src-git $feed_name $current_url[^ ]*|$new_line|" "$feed_conf_file"

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
    local fixed=0

    echo "尝试在 batman-adv Makefile 中禁用 -Werror..."
    # First, try finding the Makefile dynamically in case feed structure changes
    local found_makefile
    found_makefile=$(find package feeds -path "*/$FEED_ROUTING_NAME/batman-adv/Makefile" -print -quit)
    if [ -n "$found_makefile" ] && [ -f "$found_makefile" ]; then
         batman_makefile="$found_makefile"
         echo "找到 Makefile: $batman_makefile"
    elif [ ! -f "$batman_makefile" ]; {
         echo "错误: 未找到 $batman_makefile 或动态查找失败。"
         return 1
    }


    if [ -f "$batman_makefile" ]; then
        # Check if the specific filter-out line already exists
        if ! grep -q 'TARGET_CFLAGS:=$(filter-out -Werror,$(TARGET_CFLAGS))' "$batman_makefile"; then
            echo "正在修改 $batman_makefile..."
            cp "$batman_makefile" "$batman_makefile.bak" # Backup before modification

            # Use awk to insert the line after common include directives
            awk '
            /include \.\.\/\.\.\/package.mk|include \$\(INCLUDE_DIR\)\/package\.mk|include \$\(TOPDIR\)\/rules\.mk/ {
              print $0 # Print the include line itself
              # Check if the next few lines already contain our fix to avoid duplication
              getline line1; if (line1 ~ /filter-out -Werror/) { print line1; next } else { print ""; print "# Disable -Werror for this package"; print "TARGET_CFLAGS:=$(filter-out -Werror,$(TARGET_CFLAGS))"; print ""; print line1; next }
              getline line2; if (line2 ~ /filter-out -Werror/) { print line2; next } else { print line2 }
              # If the include line was the last line, awk might exit, so handle END block? No, simple insertion should work.
              inserted=1 # Flag that we tried inserting
              next # Skip default printing for the include line
            }
            { print $0 } # Print other lines
            END {
                 # If no include was found (unlikely for package makefiles), maybe add at the end? Risky.
                 # Let's rely on finding an include line.
            }
            ' "$batman_makefile" > "$batman_makefile.tmp"

            if [ $? -eq 0 ] && [ -s "$batman_makefile.tmp" ]; then
                # Verify the change was actually made and is correct
                if grep -q 'TARGET_CFLAGS:=$(filter-out -Werror,$(TARGET_CFLAGS))' "$batman_makefile.tmp" && ! cmp -s "$batman_makefile" "$batman_makefile.tmp"; then
                    mv "$batman_makefile.tmp" "$batman_makefile"
                    echo "已在 $batman_makefile 中添加 CFLAGS 过滤。"
                    # Clean the package to ensure new flags are used
                    make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: 清理 batman-adv 失败。"
                    rm -f "$batman_makefile.bak" # Remove backup on success
                    fixed=1
                 else
                    echo "错误: 使用 awk 修改 $batman_makefile 失败或无更改。"
                    rm -f "$batman_makefile.tmp"
                    mv "$batman_makefile.bak" "$batman_makefile" # Restore backup
                    fixed=0
                 fi
            else
                 echo "错误: awk 命令失败或产生空输出。"
                 rm -f "$batman_makefile.tmp"
                 if [ -f "$batman_makefile.bak" ]; then mv "$batman_makefile.bak" "$batman_makefile"; fi # Restore backup
                 fixed=0
            fi
        else
            echo "$batman_makefile 中似乎已禁用 -Werror。"
            fixed=1 # Consider it fixed if already present
        fi
    else
        echo "错误: 未找到 $batman_makefile。"
         fixed=0
    fi

    [ $fixed -eq 1 ] && return 0 || return 1
}


# --- Fix Functions (Keep others as they were) ---

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
    # Use a temporary file for sed to avoid potential issues with direct -i on some systems/links
    cp "$found_path" "$found_path.tmp"
    if sed "s|boost::asio::buffer_cast<char\*>(\(udp_read_buf.prepare([^)]*)\))|static_cast<char*>(\1.data())|g" "$found_path.tmp" > "$found_path" && \
       grep -q 'static_cast<char\*>' "$found_path"; then
            echo "已成功修改 $found_path"
            rm "$found_path.tmp"

            # Attempt to find the package source directory for cleaning
            local pkg_src_path=""
            if [ -n "$trojan_pkg_dir" ]; then
                 # Try finding based on package name part
                 pkg_name_base=$(echo "$trojan_pkg_dir" | sed 's/-[0-9].*//')
                 pkg_src_path=$(find package feeds -maxdepth 3 -name "$pkg_name_base" -type d -print -quit)
                 if [ -z "$pkg_src_path" ]; then # Fallback to exact name match if base fails
                     pkg_src_path=$(find package feeds -maxdepth 3 -name "$trojan_pkg_dir" -type d -print -quit)
                 fi
            fi

            if [ -n "$pkg_src_path" ] && [ -d "$pkg_src_path" ]; then
                echo "尝试清理包 $pkg_src_path 以应用更改..."
                make "$pkg_src_path/clean" DIRCLEAN=1 V=s || echo "警告: 清理包 $pkg_src_path 失败。"
            else
                echo "警告: 未找到 trojan-plus 的源包目录 ($pkg_name_base or $trojan_pkg_dir)，无法执行清理。可能需要手动清理。"
            fi
            return 0
    else
         echo "尝试修改 $found_path 失败，恢复原始文件。"
         # If sed failed, $found_path might be empty or corrupted, restore from .tmp
         mv "$found_path.tmp" "$found_path"
         return 1
    fi
}

### Fix po2lmo command not found
fix_po2lmo() {
    echo "检测到 po2lmo 命令未找到，尝试编译 luci-base..."
    # Try to find luci-base path robustly
    local luci_base_path
    luci_base_path=$(find package feeds -path '*/luci-base' -type d -print -quit)
    if [ -z "$luci_base_path" ]; then
        echo "错误: 无法找到 luci-base 包目录。"
        return 1
    fi
    echo "编译 $luci_base_path..."
    make "$luci_base_path/compile" V=s || {
        echo "编译 luci-base 失败"
        # Attempt clean and retry once
        echo "尝试清理并重新编译 luci-base..."
        make "$luci_base_path/clean" DIRCLEAN=1 V=s || echo "警告: 清理 luci-base 失败。"
        make "$luci_base_path/compile" V=s || {
            echo "再次编译 luci-base 仍然失败。"
            return 1
        }
    }
    echo "编译 luci-base 完成，将重试主命令。"
    return 0
}

### Extract error block from log
extract_error_block() {
    local log_file="$1"
    echo "--- 最近 300 行日志 (${log_file}) ---"
    tail -n 300 "$log_file"
    echo "--- 日志结束 ---"
}

### Fix PKG_VERSION and PKG_RELEASE formats
fix_pkg_version() {
    echo "修复 PKG_VERSION 和 PKG_RELEASE 格式..."
    local changed_count=0 flag_file=".fix_pkgver_changed"
    rm -f "$flag_file"
    # Use find directly without intermediate variable for robustness
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -path "./build_dir/*" -prune -o -path "./staging_dir/*" -prune -o -path "./tmp/*" -prune -o -print0 | while IFS= read -r -d $'\0' makefile; do
        # Skip Makefiles that don't include standard package definitions more reliably
        if ! head -n 50 "$makefile" 2>/dev/null | grep -qE '^\s*(include \.\./\.\./(package|buildinfo)\.mk|include \$\(INCLUDE_DIR\)/package\.mk|include \$\(TOPDIR\)/rules\.mk)'; then
            continue
        fi

        local current_version release new_version new_release suffix modified_in_loop=0 makefile_changed=0
        # Use awk for parsing and modification for better safety
        awk -v file="$makefile" -v flag="$flag_file" '
        function apply_change(new_content, filename, flagfile) {
             # Compare original and new content (ignoring whitespace differences for robustness?)
             # Simple comparison first
             if (new_content != original_content) {
                 print "修改 " filename ": PKG_VERSION/RELEASE 调整" > "/dev/stderr"
                 print new_content > filename # Overwrite original file
                 if (system("echo > " flagfile) != 0) { # Touch the flag file
                      print "警告: 无法创建 flag 文件 " flagfile > "/dev/stderr"
                 }
                 return 1 # Indicate change made
             }
             return 0 # Indicate no change needed
        }
        BEGIN {
            FS="="; OFS="=";
            pkg_version=""; pkg_release=""; release_line_nr=0; version_line_nr=0;
            original_content = ""; # Store original file content
            changed = 0; # Flag for changes within awk
        }
        { original_content = original_content $0 ORS } # Build original content
        # Store version/release and line numbers
        /^PKG_VERSION:=/ { pkg_version=substr($0, index($0, "=")+2); version_line_nr = NR }
        /^PKG_RELEASE:=/ { pkg_release=substr($0, index($0, "=")+2); release_line_nr = NR }

        END {
            new_version = pkg_version;
            new_release = pkg_release;
            needs_update = 0;

            # Case 1: Version string contains a hyphenated suffix (e.g., 1.2.3-beta1)
            if (pkg_version != "" && match(pkg_version, /^([0-9]+(\.[0-9]+)*)-([a-zA-Z0-9_.-]+)$/, m)) {
                new_version_candidate = m[1];
                suffix = m[3];
                # Try to extract number from suffix, default to 1.
                new_release_candidate = suffix;
                gsub(/[^0-9]/, "", new_release_candidate); # Remove non-digits
                sub(/.*[^0-9]/, "", new_release_candidate); # Keep only trailing digits
                if (new_release_candidate == "" || !match(new_release_candidate, /^[0-9]+$/)) {
                    new_release_candidate = "1";
                }

                if (new_version != new_version_candidate) {
                     new_version = new_version_candidate;
                     needs_update = 1;
                }
                 # Only update release if it was derived from version AND differs from original release or original release was empty
                if ((pkg_release == "") || (pkg_release != new_release_candidate)) {
                     new_release = new_release_candidate;
                     needs_update = 1;
                 }
            }

            # Case 2: PKG_RELEASE exists but is not a simple number (and wasn't just fixed by Case 1)
             if (!needs_update && pkg_release != "" && !match(pkg_release, /^[0-9]+$/)) {
                 new_release_candidate = pkg_release;
                 gsub(/[^0-9]/, "", new_release_candidate); # Remove non-digits
                 sub(/.*[^0-9]/, "", new_release_candidate); # Keep only trailing digits
                 if (new_release_candidate == "" || !match(new_release_candidate, /^[0-9]+$/)) {
                     new_release_candidate = "1";
                 }
                 if (pkg_release != new_release_candidate) {
                     new_release = new_release_candidate;
                     needs_update = 1;
                 }
             }

            # Case 3: PKG_RELEASE is missing entirely and PKG_VERSION exists (and wasn't handled by Case 1 adding it)
            if (pkg_version != "" && pkg_release == "" && new_release == "") {
                 new_release = "1";
                 needs_update = 1;
             }

             # If changes are needed, reconstruct the file content
            if (needs_update) {
                 FS="\n"; OFS="\n"; # Switch field separators for line processing
                 split(original_content, lines, ORS); # Split original content into lines
                 new_content = "";
                 release_set = 0;

                 for (i=1; i <= length(lines); ++i) {
                     line = lines[i];
                     if (line == "") continue; # Skip empty lines if any at end

                     if (i == version_line_nr) {
                         new_content = new_content "PKG_VERSION:=" new_version ORS;
                         # If PKG_RELEASE was originally missing, add it after PKG_VERSION
                         if (release_line_nr == 0 && new_release != "") {
                              new_content = new_content "PKG_RELEASE:=" new_release ORS;
                              release_set = 1;
                         }
                     } else if (i == release_line_nr) {
                         new_content = new_content "PKG_RELEASE:=" new_release ORS;
                         release_set = 1;
                     } else {
                         new_content = new_content line ORS;
                     }
                 }
                 # If PKG_RELEASE was missing and not added after PKG_VERSION (e.g., VERSION was last line)
                 # This logic is tricky, maybe simple sed is better for *adding* the line if missing.
                 # Let's stick to modifying existing lines or lines derived from version for now.
                 # Re-running the awk script to only *modify* might be safer.

                 # Re-evaluate changes needed based *only* on modifications now
                 final_new_version = new_version; final_new_release = new_release; needs_final_update = 0;
                 if (pkg_version != final_new_version) needs_final_update = 1;
                 if (pkg_release != final_new_release && final_new_release != "") needs_final_update = 1;

                 if (needs_final_update) {
                      # Apply changes using awk for substitution or sed for simplicity if awk gets complex
                      # Using sed might be simpler here for targeted replacement/addition
                      system("cp \047" file "\047 \047" file ".bak\047"); # Backup
                      if (pkg_version != final_new_version) {
                           system("sed -i \047" version_line_nr "s/^PKG_VERSION:=.*/PKG_VERSION:=" final_new_version "/\047 \047" file "\047");
                           changed = 1;
                      }
                      if (pkg_release != final_new_release && final_new_release != "") {
                           if (release_line_nr > 0) { # Modify existing line
                                system("sed -i \047" release_line_nr "s/^PKG_RELEASE:=.*/PKG_RELEASE:=" final_new_release "/\047 \047" file "\047");
                                changed = 1;
                           } else if (version_line_nr > 0) { # Add after version line
                                system("sed -i \047" version_line_nr " a PKG_RELEASE:=" final_new_release "\047 \047" file "\047");
                                changed = 1;
                           }
                      }
                      if (changed) {
                           print "修改 " file ": PKG_VERSION/RELEASE 格式调整" > "/dev/stderr";
                           system("touch \047" flag "\047");
                           system("rm -f \047" file ".bak\047"); # Remove backup on success
                      } else {
                           system("mv \047" file ".bak\047 \047" file "\047"); # Restore backup if no change made by sed
                      }
                 }
            }
        }
        ' "$makefile" # Process the file with awk
        # Awk exit status not reliable for checking changes here, rely on flag file
    done
    echo "修复 PKG_VERSION/RELEASE 完成检查。"
    if [ -f "$flag_file" ]; then
        changed_count=$(find . -name "$flag_file" -print | wc -l) # Count how many times flag was touched (approx)
        rm -f "$flag_file"
        echo "至少在一个文件中应用了 PKG_VERSION/RELEASE 修复。"
        return 0 # Changes were likely made
    else
        return 1 # No changes reported by awk/sed
    fi
}


### Fix duplicate dependencies
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
            # Increase head lines to catch includes further down if needed
            if ! head -n 50 "$makefile" 2>/dev/null | grep -qE "^\s*include.*\/(package|buildinfo|kernel|rules)\.mk"; then
                exit 0
            fi

            # Backup before processing
            cp "$makefile" "$makefile.bak"

            awk '\''
            BEGIN { FS = "[[:space:]]+"; OFS = " "; change_made = 0 }
            # Match DEPENDS lines, including multiline definitions ending with \
            # This simple awk script handles single lines well. Multiline needs more complex state.
            # Let'\''s assume single line for now, as it covers most cases.
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
                gsub(/^[[:space:]]+|[[:space:]]+$|\\$/, "", dep_part) # Trim whitespace and trailing backslash

                delete seen_bare
                delete seen_versioned_pkg
                delete result_deps
                idx = 0
                # Use standard field splitting on the dependency part
                n = split(dep_part, deps, /[[:space:]]+/)

                for (i=1; i<=n; i++) {
                    dep = deps[i]
                    if (dep == "" || dep ~ /^\s*$/ || dep ~ /^\$\(.*\)/ ) { # Keep variables untouched, skip empty
                        if (dep != "") result_deps[idx++] = dep
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
                                     if (k in result_deps) { # Check index exists before accessing
                                         tmp_bare_k = result_deps[k]
                                         sub(/^\+/, "", tmp_bare_k)
                                         if (tmp_bare_k == pkg_name && !(result_deps[k] ~ />=|<=|==/)) {
                                             # Shift elements left to remove the bare entry
                                             for (l=k; l<idx-1; ++l) {
                                                 result_deps[l] = result_deps[l+1]
                                             }
                                             idx--
                                             delete result_deps[idx] # Clear the last (now duplicated) element index
                                             break
                                         }
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
                     if (j in result_deps && result_deps[j] != "") { # Check index and value
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
                 # Add backslash if original line had one (simple multiline handling attempt)
                if (original_line ~ /\\\s*$/) {
                    new_line = new_line " \\"
                }
                gsub(/[[:space:]]+\\$/, " \\", new_line) # Ensure space before trailing \
                gsub(/[[:space:]]+$/, "", new_line) # Trim trailing whitespace unless it's the one before \

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
            if [ $awk_status -eq 0 ]; then # AWK exited 0 (changes made)
                 # Double check if files actually differ before moving
                 if [ -s "$makefile.tmp" ] && ! cmp -s "$makefile" "$makefile.tmp"; then
                     echo "修改 $makefile: 修复依赖重复"
                     mv "$makefile.tmp" "$makefile"
                     rm "$makefile.bak" # Remove backup on success
                     touch "$flag_file_path"
                     # Increment counter - tricky within sh -c, use flag file instead
                 else
                      # Awk said changes made, but files are identical? Keep original.
                      rm -f "$makefile.tmp"
                      rm -f "$makefile.bak" # No change needed, remove backup
                 fi
            elif [ $awk_status -eq 1 ]; then # AWK exited 1 (no changes made)
                 rm -f "$makefile.tmp"
                 rm -f "$makefile.bak" # Remove backup
            else # AWK had an error
                 echo "警告: 处理 $makefile 时 awk 脚本出错 (退出码: $awk_status)" >&2
                 rm -f "$makefile.tmp"
                 mv "$makefile.bak" "$makefile" # Restore backup on error
            fi

        ' _ {} "$flag_file_path" \; # Need to pass the flag file path correctly

    echo "修复重复依赖完成。"
    if [ -f "$flag_file" ]; then
        rm -f "$flag_file"
        return 0 # Changes were made
    else
        return 1 # No changes made
    fi
}

### Fix dependency format (Using Temp Awk File)
fix_dependency_format() {
    echo "尝试修复 Makefile 中的依赖格式 (移除版本号中的 pkg-release)..."
    local flag_file=".fix_depformat_changed"
    local awk_script_file
    awk_script_file=$(mktemp /tmp/fix_dep_format_awk.XXXXXX)
    if [ -z "$awk_script_file" ] || [ ! -f "$awk_script_file" ]; then
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
    gsub(/^[[:space:]]+|[[:space:]]+$|\\$/, "", dep_part); # Trim whitespace and trailing backslash

    if (dep_part != "") {
        split(dep_part, deps, /[[:space:]]+/) # Split deps by space
        new_deps_str = ""
        for (i=1; i<=length(deps); i++) {
            dep = deps[i]
            if (dep == "" || dep ~ /^\$\(.*\)/) { # Keep variables, skip empty
                 if (dep != "") {
                     if (new_deps_str != "") new_deps_str = new_deps_str " "
                     new_deps_str = new_deps_str dep
                 }
                continue
            }
            original_dep = dep
            # Remove pkg-release suffix like -1, -10 from version constraints (e.g., pkg>=1.2.3-1 -> pkg>=1.2.3)
            # Regex needs refinement to handle version formats like 1.2.3-beta-1
            # Let's target simple numeric suffixes first: >=X.Y.Z-N
            gsub(/(>=|<=|==)([0-9]+(\.[0-9]+)*(-[a-zA-Z0-9_.]*)?)-[0-9]+$/, "\\1\\2", dep)

            # Check if modification happened
            if (original_dep != dep) {
                line_changed = 1
            }

            # Add to new string (no duplicate check here, let fix_depends handle that)
            if (new_deps_str != "") new_deps_str = new_deps_str " "
            new_deps_str = new_deps_str dep
        }

        # Reconstruct line
        new_line = prefix (new_deps_str == "" ? "" : " " new_deps_str)
        if (comment_part != "") {
            new_line = new_line " " comment_part
        }
        # Add backslash if original line had one
        if (original_line ~ /\\\s*$/) {
             new_line = new_line " \\"
        }
        gsub(/[[:space:]]+\\$/, " \\", new_line) # Ensure space before trailing \
        gsub(/[[:space:]]+$/, "", new_line) # Trim trailing whitespace unless it's the one before \

        # Compare with original (trimmed)
        original_line_trimmed = original_line
        gsub(/[[:space:]]+$/, "", original_line_trimmed)


        if (line_changed && new_line != original_line_trimmed) {
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
        if ! head -n 50 "$makefile" 2>/dev/null | grep -qE "^\s*include.*\/(package|buildinfo|kernel|rules)\.mk"; then
             exit 0
        fi
        cp "$makefile" "$makefile.bak" # Backup before processing

        # Execute awk using the script file
        awk -f "$awk_script_path" "$makefile" > "$makefile.tmp"
        awk_status=$?

        if [ $awk_status -eq 0 ]; then # Changes were made by awk (exit 0)
           # Verify files actually differ before moving
           if [ -s "$makefile.tmp" ] && ! cmp -s "$makefile" "$makefile.tmp"; then
                echo "修改 $makefile: 调整依赖格式 (移除版本后缀)"
                mv "$makefile.tmp" "$makefile"
                rm "$makefile.bak" # Remove backup on successful change
                touch "$flag_file_path"
           else
                # Awk reported changes (exit 0), but files are same or tmp is empty? Unexpected.
                # echo "警告: awk声称修改了 $makefile 但文件未变或为空。" >&2
                rm "$makefile.tmp"
                rm "$makefile.bak" # No change needed, remove backup
           fi
        elif [ $awk_status -eq 1 ]; then # Awk reported no changes needed (exit 1)
             rm "$makefile.tmp"
             rm "$makefile.bak" # Remove backup
        else # Awk script itself had an error
             echo "警告: awk 处理 $makefile 时出错 (退出码: $awk_status)，已从备份恢复。" >&2
             rm -f "$makefile.tmp" # Remove potentially corrupt tmp file
             # Keep the backup file if awk failed catastrophically? Or restore? Restore.
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
fix_mkdir_conflict() {
    local log_file="$1"
    echo "检测到 'mkdir: cannot create directory ... File exists' 错误，尝试修复..."
    local FAILED_PATH PKG_ERROR_LINE PKG_PATH PKG_NAME PKG_DIR_REL PKG_BUILD_DIR_PART cleanup_done=0

    # Extract the conflicting path
    FAILED_PATH=$(grep "mkdir: cannot create directory" "$log_file" | grep "File exists" | sed -e "s/.*mkdir: cannot create directory '\([^']*\)'.*/\1/" | tail -n 1)
    if [ -z "$FAILED_PATH" ]; then
        echo "无法从日志中提取冲突的路径。"
        return 1
    fi
     # Try to make path relative for cleaner logs/potential use later
    FAILED_PATH_REL=$(get_relative_path "$FAILED_PATH")
    echo "冲突路径: $FAILED_PATH_REL (Absolute: $FAILED_PATH)"


    # Clean the conflicting path if it exists
    if [ -e "$FAILED_PATH" ]; then # Check absolute path for existence
        echo "正在清理已存在的冲突路径: $FAILED_PATH_REL"
        rm -rf "$FAILED_PATH"
        if [ -e "$FAILED_PATH" ]; then
             echo "警告：无法删除冲突路径 $FAILED_PATH_REL"
             # This might be serious, return failure? Or let retry happen? Let's warn and continue.
             # return 1
        else
            echo "已成功删除冲突路径。"
            cleanup_done=1
        fi
    else
        echo "冲突路径 $FAILED_PATH_REL 已不存在，无需删除。"
         cleanup_done=1 # Consider it 'done' as the conflict state is resolved
    fi

    # Try to identify the package causing the error more reliably
    # Look further back in the log, as the error message might appear after the package context
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 150 "mkdir: cannot create directory '$FAILED_PATH'" | grep -m 1 -Eo '(ERROR: (package|feeds)/[^ ]+ failed to build\.|make\[[0-9]+\]: Entering directory.*(package|feeds)/[^ ]+|make\[[0-9]+\]: \*\*\* \[(.*)/\.built\] Error)')
    PKG_PATH=""
    PKG_DIR_REL=""
    PKG_BUILD_DIR_PART="" # Initialize

    if [[ -n "$PKG_ERROR_LINE" ]]; then
        echo "找到相关错误/上下文行: $PKG_ERROR_LINE"
        if [[ "$PKG_ERROR_LINE" == ERROR:* ]]; then
            PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build\./\1/')
             # Ensure it looks like a package path
            if [[ "$PKG_PATH" == package/* || "$PKG_PATH" == feeds/* ]] && [ -d "$PKG_PATH" ]; then
                 PKG_DIR_REL="$PKG_PATH"
                 echo "从 'ERROR:' 行推断出包目录: $PKG_DIR_REL"
            else
                 echo "警告: 从 'ERROR:' 行提取的路径 '$PKG_PATH' 不是一个有效的包目录。"
                 PKG_PATH=""
            fi
        elif [[ "$PKG_ERROR_LINE" == *'Entering directory'* ]]; then
             # Try extracting relative path first
             PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed -n "s|.*Entering directory .*/\(package/[^ ']*/[^ /']*\).*|\1|p; s|.*Entering directory .*/\(feeds/[^ ']*/[^ /']*\).*|\1|p" | head -n 1)
             # Attempt to convert absolute path if relative pattern failed
             if [ -z "$PKG_PATH" ]; then
                 ABS_PATH=$(echo "$PKG_ERROR_LINE" | sed -n "s|.*Entering directory '\([^']*\)'.*|\1|p")
                 if [ -n "$ABS_PATH" ]; then
                     PKG_DIR_REL_TMP=$(get_relative_path "$ABS_PATH")
                     if [[ -n "$PKG_DIR_REL_TMP" ]] && [[ "$PKG_DIR_REL_TMP" == package/* || "$PKG_DIR_REL_TMP" == feeds/* ]] && [ -d "$PKG_DIR_REL_TMP" ]; then
                         PKG_DIR_REL="$PKG_DIR_REL_TMP"
                         PKG_PATH="$PKG_DIR_REL" # Use relative path consistently
                         echo "从 'Entering directory' 行推断出包目录 (相对路径): $PKG_DIR_REL"
                     fi
                 fi
             elif [[ "$PKG_PATH" == package/* || "$PKG_PATH" == feeds/* ]] && [ -d "$PKG_PATH" ]; then
                  PKG_DIR_REL="$PKG_PATH"
                  echo "从 'Entering directory' 行推断出包目录: $PKG_DIR_REL"
             else
                  echo "警告: 从 'Entering directory' 行提取的路径 '$PKG_PATH' 不是有效的包目录。"
                  PKG_PATH=""
                  PKG_DIR_REL=""
             fi

        elif [[ "$PKG_ERROR_LINE" == *'/.built]* Error'* ]]; then
             PKG_BUILD_DIR_PART=$(echo "$PKG_ERROR_LINE" | sed -n 's|make\[[0-9]\+\]: \*\*\* \[\(.*\)/\.built\] Error.*|\1|p')
             if [[ "$PKG_BUILD_DIR_PART" == *build_dir/* ]]; then
                  # Try to guess package name from build dir
                  PKG_NAME_GUESS=$(basename "$PKG_BUILD_DIR_PART" | sed -e 's/-[0-9].*//' -e 's/_.*//')
                  # Find the corresponding package/feed source directory
                  PKG_PATH_FOUND=$(find package feeds -maxdepth 3 -name "$PKG_NAME_GUESS" -type d -print -quit)
                  if [[ -n "$PKG_PATH_FOUND" ]] && ( [[ "$PKG_PATH_FOUND" == ./package/* ]] || [[ "$PKG_PATH_FOUND" == ./feeds/* ]] ) && [ -d "$PKG_PATH_FOUND" ]; then
                       PKG_DIR_REL="${PKG_PATH_FOUND#./}" # Make relative
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
            echo "警告: 清理包 $PKG_NAME 失败，但已删除冲突路径，将继续尝试主编译命令。"
        }
        echo "已清理包 $PKG_NAME，将重试主命令。"
        cleanup_done=1 # Mark that associated package was cleaned
    else
        echo "无法从日志中明确推断出导致错误的包或推断的路径无效。仅删除了冲突路径。"
        # Also try cleaning the specific build dir if identified from .built error
        if [[ -n "$PKG_BUILD_DIR_PART" ]] && [ -d "$PKG_BUILD_DIR_PART" ]; then
             echo "尝试清理具体的 build_dir: $PKG_BUILD_DIR_PART"
             rm -rf "$PKG_BUILD_DIR_PART" || echo "警告: 删除 $PKG_BUILD_DIR_PART 失败"
             cleanup_done=1 # Mark that build dir was cleaned
        fi
    fi

    # Return success if the conflicting path was removed or the associated package/build dir was cleaned
    [ $cleanup_done -eq 1 ] && return 0 || return 1
}

### Fix symbolic link conflicts
fix_symbolic_link_conflict() {
    local log_file="$1"
    echo "检测到 'ln: failed to create symbolic link ... File exists' 错误，尝试修复..."
    local FAILED_LINK FAILED_LINK_REL PKG_ERROR_LINE PKG_PATH PKG_NAME PKG_DIR_REL PKG_BUILD_DIR_PART cleanup_done=0

    # Extract the conflicting link path
    FAILED_LINK=$(grep "ln: failed to create symbolic link" "$log_file" | grep "File exists" | sed -e "s/.*failed to create symbolic link '\([^']*\)'.*/\1/" | tail -n 1)
    if [ -z "$FAILED_LINK" ]; then
        echo "无法从日志中提取冲突的符号链接路径。"
        return 1
    fi
    FAILED_LINK_REL=$(get_relative_path "$FAILED_LINK")
    echo "冲突链接: $FAILED_LINK_REL (Absolute: $FAILED_LINK)"

    # Clean the conflicting link/file if it exists
    if [ -e "$FAILED_LINK" ]; then # Use -e to check for files or links (absolute path)
        echo "正在清理已存在的冲突文件/链接: $FAILED_LINK_REL"
        rm -rf "$FAILED_LINK"
        if [ -e "$FAILED_LINK" ]; then
             echo "警告：无法删除冲突链接/文件 $FAILED_LINK_REL"
             # return 1
        else
             echo "已成功删除冲突链接/文件。"
             cleanup_done=1
        fi
    else
         echo "冲突链接 $FAILED_LINK_REL 已不存在，无需删除。"
         cleanup_done=1 # Conflict state resolved
    fi

    # Try to identify the package causing the error (similar logic as fix_mkdir_conflict)
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 150 "failed to create symbolic link '$FAILED_LINK'" | grep -m 1 -Eo '(ERROR: (package|feeds)/[^ ]+ failed to build\.|make\[[0-9]+\]: Entering directory.*(package|feeds)/[^ ]+|make\[[0-9]+\]: \*\*\* \[(.*)/\.built\] Error)')
    PKG_PATH=""
    PKG_DIR_REL=""
    PKG_BUILD_DIR_PART="" # Initialize

     if [[ -n "$PKG_ERROR_LINE" ]]; then
         echo "找到相关错误/上下文行: $PKG_ERROR_LINE"
         # (Same logic as fix_mkdir_conflict to find PKG_DIR_REL / PKG_BUILD_DIR_PART)
        if [[ "$PKG_ERROR_LINE" == ERROR:* ]]; then
            PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build\./\1/')
            if [[ "$PKG_PATH" == package/* || "$PKG_PATH" == feeds/* ]] && [ -d "$PKG_PATH" ]; then
                 PKG_DIR_REL="$PKG_PATH"; echo "从 'ERROR:' 行推断: $PKG_DIR_REL";
            else PKG_PATH=""; fi
        elif [[ "$PKG_ERROR_LINE" == *'Entering directory'* ]]; then
             PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed -n "s|.*Entering directory .*/\(package/[^ ']*/[^ /']*\).*|\1|p; s|.*Entering directory .*/\(feeds/[^ ']*/[^ /']*\).*|\1|p" | head -n 1)
             if [ -z "$PKG_PATH" ]; then
                 ABS_PATH=$(echo "$PKG_ERROR_LINE" | sed -n "s|.*Entering directory '\([^']*\)'.*|\1|p")
                 if [ -n "$ABS_PATH" ]; then
                     PKG_DIR_REL_TMP=$(get_relative_path "$ABS_PATH")
                     if [[ -n "$PKG_DIR_REL_TMP" ]] && [[ "$PKG_DIR_REL_TMP" == package/* || "$PKG_DIR_REL_TMP" == feeds/* ]] && [ -d "$PKG_DIR_REL_TMP" ]; then
                         PKG_DIR_REL="$PKG_DIR_REL_TMP"; PKG_PATH="$PKG_DIR_REL"; echo "从 'Entering directory' (相对路径)推断: $PKG_DIR_REL";
                     fi; fi
             elif [[ "$PKG_PATH" == package/* || "$PKG_PATH" == feeds/* ]] && [ -d "$PKG_PATH" ]; then PKG_DIR_REL="$PKG_PATH"; echo "从 'Entering directory' 推断: $PKG_DIR_REL";
             else PKG_PATH=""; PKG_DIR_REL=""; fi
        elif [[ "$PKG_ERROR_LINE" == *'/.built]* Error'* ]]; then
             PKG_BUILD_DIR_PART=$(echo "$PKG_ERROR_LINE" | sed -n 's|make\[[0-9]\+\]: \*\*\* \[\(.*\)/\.built\] Error.*|\1|p')
             if [[ "$PKG_BUILD_DIR_PART" == *build_dir/* ]]; then
                  PKG_NAME_GUESS=$(basename "$PKG_BUILD_DIR_PART" | sed -e 's/-[0-9].*//' -e 's/_.*//')
                  PKG_PATH_FOUND=$(find package feeds -maxdepth 3 -name "$PKG_NAME_GUESS" -type d -print -quit)
                  if [[ -n "$PKG_PATH_FOUND" ]] && ( [[ "$PKG_PATH_FOUND" == ./package/* ]] || [[ "$PKG_PATH_FOUND" == ./feeds/* ]] ) && [ -d "$PKG_PATH_FOUND" ]; then
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
             echo "警告: 清理包 $PKG_NAME 失败，但已删除冲突链接，将继续尝试主编译命令。"
        }
        echo "已清理包 $PKG_NAME，将重试主命令。"
        cleanup_done=1
    else
        echo "无法从日志中明确推断出导致错误的包或路径无效。仅删除了冲突链接。"
         if [[ -n "$PKG_BUILD_DIR_PART" ]] && [ -d "$PKG_BUILD_DIR_PART" ]; then
             echo "尝试清理具体的 build_dir: $PKG_BUILD_DIR_PART"
             rm -rf "$PKG_BUILD_DIR_PART" || echo "警告: 删除 $PKG_BUILD_DIR_PART 失败"
             cleanup_done=1
        fi
    fi

    # Return success if the conflicting item was removed or associated package/build dir cleaned
    [ $cleanup_done -eq 1 ] && return 0 || return 1
}


### Fix Makefile "missing separator" error
fix_makefile_separator() {
    local log_file="$1"
    echo "检测到 'missing separator' 错误，尝试修复..."
    local error_line_info makefile_name_from_err line_num context_dir full_makefile_path makefile_path_rel fix_attempted=0 line_content tab pkg_dir

    # 从日志中提取错误行信息 (make[N]: *** [Makefile:LINE] Error X or similar is less reliable)
    # Try finding the specific error message format: <file>:<line>: *** missing separator. Stop.
    error_line_info=$(grep -m 1 ': \*\*\* missing separator.*Stop\.' "$log_file")

    if [[ "$error_line_info" =~ ^([^:]+):([0-9]+):[[:space:]]+\*\*\*[[:space:]]+missing[[:space:]]+separator ]]; then
        makefile_name_from_err="${BASH_REMATCH[1]}"
        line_num="${BASH_REMATCH[2]}"
        echo "从错误行提取: 文件名部分='$makefile_name_from_err', 行号='$line_num'"
    else
        echo "警告: 无法从日志准确提取文件名和行号。将尝试基于上下文查找。"
        makefile_name_from_err=""
        line_num=""
        # Try finding the 'Stop.' message and look nearby for file context
        local stop_line=$(grep -m 1 'missing separator.*Stop.' "$log_file")
        local make_context=$(tac "$log_file" | grep -A 10 -m 1 "$stop_line" | grep -m 1 -E 'make\[[0-9]+\]: Leaving directory|make\[[0-9]+\]: Entering directory')
        if [[ "$make_context" == *Leaving* ]]; then
             makefile_name_from_err="Makefile" # Common case when leaving dir
        fi
         # Cannot reliably get line number this way
    fi


    # 查找最近的 "Entering directory" 以确定上下文目录
    context_dir=$(tac "$log_file" | grep -A 50 -m 1 -E 'missing separator|Stop\.' | grep -m 1 -E "^make\[[0-9]+\]: Entering directory '([^']+)'" | sed -n "s/.*Entering directory '\([^']*\)'/\1/p")

    full_makefile_path=""
    if [ -n "$context_dir" ]; then
        echo "找到上下文目录: $context_dir"
        # If we extracted a filename, use it relative to context dir
        if [ -n "$makefile_name_from_err" ]; then
             # Handle if extracted name is already absolute or relative to root
             if [[ "$makefile_name_from_err" == /* ]] || [[ "$makefile_name_from_err" == package/* ]] || [[ "$makefile_name_from_err" == feeds/* ]] || [[ "$makefile_name_from_err" == tools/* ]] || [[ "$makefile_name_from_err" == toolchain/* ]]; then
                  full_makefile_path="$makefile_name_from_err"
             elif [ -f "$context_dir/$makefile_name_from_err" ]; then
                 full_makefile_path="$context_dir/$makefile_name_from_err"
             # Sometimes the error just says 'Makefile'
             elif [ "$makefile_name_from_err" == "Makefile" ] && [ -f "$context_dir/Makefile" ]; then
                  full_makefile_path="$context_dir/Makefile"
             fi
        # If no filename extracted, assume 'Makefile' in context dir
        elif [ -f "$context_dir/Makefile" ]; then
            full_makefile_path="$context_dir/Makefile"
            makefile_name_from_err="Makefile" # Assume standard name
        fi
    # If no context dir, but we have a filename, check if it exists relative to PWD
    elif [ -n "$makefile_name_from_err" ] && [ -f "$makefile_name_from_err" ]; then
        full_makefile_path="$makefile_name_from_err"
        echo "使用当前目录中的文件: $full_makefile_path"
    fi

    # Special fallback for toolchain if nothing else found
    if [ -z "$full_makefile_path" ] && grep -q "package/libs/toolchain" "$log_file"; then
        full_makefile_path="package/libs/toolchain/Makefile"
        echo "推测为工具链包的 Makefile: $full_makefile_path"
        makefile_name_from_err="Makefile"
        line_num="" # Cannot trust line number if guessed file
    fi

    if [ -z "$full_makefile_path" ]; then
         echo "错误: 无法定位 Makefile 文件。"
         return 1
    fi

    # Get relative path for cleaner output and potential use in make clean
    makefile_path_rel=$(get_relative_path "$full_makefile_path")
    if [ $? -ne 0 ] || [ -z "$makefile_path_rel" ] && [ -f "$full_makefile_path" ]; then
        makefile_path_rel="$full_makefile_path" # Use absolute if relative fails but file exists
    fi

    echo "确定出错的 Makefile (推测): $makefile_path_rel, 行号 (可能): $line_num"

    # Attempt to fix indentation *only if* we have a valid line number
    if [ -f "$makefile_path_rel" ] && [ -n "$line_num" ] && [[ "$line_num" =~ ^[0-9]+$ ]] && [ "$line_num" -gt 0 ]; then
        line_content=$(sed -n "${line_num}p" "$makefile_path_rel")
        # Check if line starts with space(s) but not a tab
        if [[ "$line_content" =~ ^[[:space:]]+ ]] && ! [[ "$line_content" =~ ^\t ]]; then
            echo "检测到第 $line_num 行 '${line_content:0:50}...' 可能使用空格缩进，尝试替换为 TAB..."
            cp "$makefile_path_rel" "$makefile_path_rel.bak"
            # Use printf to ensure a literal tab is inserted
            printf -v tab '\t'
            # Replace leading whitespace with a single tab
            sed -i "${line_num}s/^[[:space:]]\+/$tab/" "$makefile_path_rel"
            # Verify the change
            if [ $? -eq 0 ] && sed -n "${line_num}p" "$makefile_path_rel" | grep -q "^\t"; then
                echo "成功修复缩进。"
                rm -f "$makefile_path_rel.bak"
                fix_attempted=1
            else
                echo "修复缩进失败或验证失败，恢复备份。"
                mv "$makefile_path_rel.bak" "$makefile_path_rel"
                # Don't set fix_attempted=1 if it failed
            fi
        else
            echo "第 $line_num 行无需修复缩进（非空格开头、已是 TAB、空行或注释）。"
            # Consider this case 'handled' even if no change, proceed to cleanup
            # fix_attempted=1 # No, only set if change was made or cleanup is done
        fi
    else
        echo "文件 '$makefile_path_rel' 不存在或行号 '$line_num' 无效/未知，跳过缩进修复。"
    fi

    # Always try cleaning the directory containing the Makefile, as the error might be due to stale state
    pkg_dir=$(dirname "$makefile_path_rel")
    # Check if pkg_dir is likely a build system directory
    if [ -d "$pkg_dir" ] && ( [[ "$pkg_dir" =~ ^(package|feeds|tools|toolchain)/ ]] || [[ "$pkg_dir" == "." ]] ); then
        if [ "$pkg_dir" == "." ]; then
            echo "错误发生在根目录 Makefile，尝试清理整个构建环境 (make clean)..."
            # Be cautious with make clean in CI, might take long
            make clean V=s || echo "警告: 'make clean' 失败。"
        else
            # Try cleaning the specific directory
            echo "尝试清理目录: $pkg_dir..."
            make "$pkg_dir/clean" DIRCLEAN=1 V=s || echo "警告: 清理 $pkg_dir 失败。"
        fi
        fix_attempted=1 # Mark fix attempted due to cleanup
    else
        echo "目录 '$pkg_dir' 无效或非标准目录，跳过清理。"
    fi

    # Explicitly handle toolchain dir if involved
    if [[ "$makefile_path_rel" =~ package/libs/toolchain ]] && [ $fix_attempted -eq 0 ]; then
        echo "检测到工具链包错误，强制清理 package/libs/toolchain..."
        make "package/libs/toolchain/clean" DIRCLEAN=1 V=s || echo "警告: 清理工具链失败。"
        fix_attempted=1
    fi

    [ $fix_attempted -eq 1 ] && return 0 || return 1 # Return success if *any* action (patch or clean) was taken
}


### Fix batman-adv backports/tasklet_setup error
fix_batman_patch_tasklet() {
    local log_file="$1"
    echo "尝试修复 batman-adv 的 tasklet_setup 符号冲突..."
    local backports_header_path fixed=0
    # Find the header file path (can be in backports-* or compat-*)
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

    echo "检查 $backports_header_path ..."
    # Check if the problematic definition exists
    if grep -q -E '^\s*#define\s+tasklet_setup' "$backports_header_path"; then
        echo "找到 tasklet_setup 定义，尝试注释掉..."
        cp "$backports_header_path" "$backports_header_path.bak" # Backup before patching
        # Comment out the #define line instead of deleting, safer for review
        sed -i.bak '/^\s*#define\s+tasklet_setup/s/^/\/* /; /^\s*#define\s+tasklet_setup/s/$/ *\//' "$backports_header_path"

        # Verify it's commented out
        if grep -q '/\*.*#define\s+tasklet_setup.* \*/' "$backports_header_path" && \
           ! grep -q -E '^\s*#define\s+tasklet_setup' "$backports_header_path"; then
            echo "已从 $backports_header_path 注释掉 tasklet_setup 定义。"
            rm -f "$backports_header_path.bak" # Remove intermediate backup
            fixed=1

            # Clean batman-adv package after patching header
            echo "清理 batman-adv 包以应用头文件更改..."
            local pkg_dir_rel=""
            pkg_dir_rel=$(find package feeds -name "batman-adv" -type d -path "*/batman-adv" -print -quit)
            if [[ -n "$pkg_dir_rel" ]] && [ -d "$pkg_dir_rel" ]; then
                 make "$pkg_dir_rel/clean" DIRCLEAN=1 V=s || echo "警告: 清理 $pkg_dir_rel 失败。"
            else
                 echo "警告: 无法确定 batman-adv 包目录，跳过 make clean。"
                 # Also clean build dir as fallback
                 local build_dir_path
                 build_dir_path=$(find build_dir -type d -name "batman-adv-*" -print -quit)
                 if [ -n "$build_dir_path" ]; then
                      echo "清理构建目录 $build_dir_path"
                      rm -rf "$build_dir_path"
                 fi
            fi
        else
            echo "警告: 尝试从 $backports_header_path 注释掉 tasklet_setup 失败，恢复备份。"
            if [ -f "$backports_header_path.bak" ]; then mv "$backports_header_path.bak" "$backports_header_path"; fi
             # Clean intermediate .bak file from sed -i.bak if it exists
             rm -f "${backports_header_path}.bak"
            fixed=0
        fi
    else
         echo "$backports_header_path 中未找到 tasklet_setup 定义，无需修补。"
         fixed=1 # Return success as no action was needed, the conflict source isn't there
    fi

    [ $fixed -eq 1 ] && return 0 || return 1
}


### Fix missing dependency during packaging stage
fix_missing_dependency() {
    local log_file="$1"
    # More specific patterns to avoid false positives from compile errors
    local missing_dep_pattern='(Cannot satisfy the following dependencies for|Package [^ ]+ is missing dependency|requires package|Unmet dependencies.*for|cannot find dependency) ([^ )*,;]+)'
    local satisfy_pattern='satisfy_dependencies_for: Cannot satisfy the following dependencies for [^:]*:[[:space:]]*\* *([^ ]+) *(.*)$'
    local missing_pkg install_pkg_name pkg_path fix_attempted=0 found_pkg_name=""

    echo "检测到安装/打包阶段缺少依赖项错误..."

    # Try the 'satisfy_dependencies_for' pattern first, often more precise
    if grep -q 'satisfy_dependencies_for: Cannot satisfy' "$log_file"; then
        missing_pkg=$(grep -m 1 -E "$satisfy_pattern" "$log_file" | sed -r "s/$satisfy_pattern/\1/")
        if [ -n "$missing_pkg" ]; then
            found_pkg_name="$missing_pkg"
            echo "从 'satisfy_dependencies_for' 提取到依赖项: $found_pkg_name"
        fi
    fi

    # If first pattern failed, try the broader set
    if [ -z "$found_pkg_name" ]; then
        missing_pkg=$(grep -E -o "$missing_dep_pattern" "$log_file" | sed -n -r "s/$missing_dep_pattern/\2/p" | head -n 1)
         # Clean potential garbage around the name, like leading '*' or trailing chars
         missing_pkg=$(echo "$missing_pkg" | sed -e 's/^[[:space:]*]*//' -e 's/[():*,;[:space:]].*$//' -e 's/^kmod-//' -e 's/^lib//') # Also strip kmod-/lib prefix for broader search later
         if [ -n "$missing_pkg" ]; then
              found_pkg_name="$missing_pkg"
              echo "从通用模式提取到依赖项 (可能简化): $found_pkg_name"
         fi
    fi


    if [ -z "$found_pkg_name" ]; then
        echo "无法从日志中提取缺少的依赖项名称。"
        return 1 # Cannot proceed without package name
    fi

    # Strategy 1: Force feeds update/install (Often helps resolve inconsistencies)
    echo "尝试强制更新和安装所有 feeds 包..."
    # Use '-f' force for install? Maybe too aggressive. Try normal first.
    ./scripts/feeds update -a || echo "警告: feeds update -a 失败"
    ./scripts/feeds install -a || {
        echo "警告: feeds install -a 失败。这可能是导致依赖问题的原因。"
        # Don't exit yet, maybe compiling the specific package helps
    }
    # Check if the specific package can be installed now
    # Use the *original* extracted name (if available and different) for install/find
    local search_name="$found_pkg_name" # Use the potentially simplified name for find/compile
    local install_name_exact # Store the exact name if found for install
    install_name_exact=$(./scripts/feeds list | grep -E "(^|\s)${found_pkg_name}( |\$)" | cut -d' ' -f1 | head -n 1) # Try finding exact match in list

    if [ -n "$install_name_exact" ]; then
        echo "尝试显式安装 specific package $install_name_exact..."
        ./scripts/feeds install "$install_name_exact" || echo "警告: 安装 $install_name_exact 失败"
        search_name="$install_name_exact" # Use exact name if found
    else
         echo "警告: 在 feeds list 中找不到精确包 '$found_pkg_name' 或 '$search_name'"
    fi
    fix_attempted=1 # Mark fix as attempted

    # Strategy 2: Try to compile the specific package (use search_name)
    echo "尝试查找并编译包 '$search_name'..."
    # Find script can be slow, limit depth?
    # Use ./scripts/feeds find first, then broader find if needed
    pkg_path=$(./scripts/feeds find "$search_name" | grep -E "(package|feeds)/.*/${search_name}$" | head -n 1)
    if [ -z "$pkg_path" ]; then
         echo "feeds find 未找到 '$search_name'，尝试全局 find..."
         pkg_path=$(find package feeds -maxdepth 4 -name "$search_name" -type d -print -quit)
    fi


    if [ -n "$pkg_path" ] && [ -d "$pkg_path" ] && [ -f "$pkg_path/Makefile" ]; then
        echo "找到包目录: $pkg_path"
        echo "尝试编译: make $pkg_path/compile V=s"
        # Compile with higher verbosity maybe? V=sc ? Use V=s for now.
        if ! make "$pkg_path/compile" V=s; then
            echo "编译 $pkg_path 失败。"
            # Attempt clean and recompile once
            echo "尝试清理并重新编译: $pkg_path..."
            make "$pkg_path/clean" V=s DIRCLEAN=1 || echo "警告: 清理 $pkg_path 失败"
            if ! make "$pkg_path/compile" V=s; then
                 echo "再次编译 $pkg_path 仍然失败。"
            fi
        else
             echo "编译 $pkg_path 成功。"
        fi
        fix_attempted=1
    else
        echo "无法在 package/ 或 feeds/ 中找到 '$search_name' 的有效目录或 Makefile。可能需要手动检查。"
        # Special check for kernel modules based on original name if it started with kmod-
        if [[ "$missing_pkg" == kmod-* ]]; then
             kmod_name=${missing_pkg#kmod-}
             # Kernel modules are tricky to locate, often part of kernel itself or specific drivers
             # Trying to compile the kernel might help? Or find the specific driver package?
             echo "依赖项看起来像内核模块 ($missing_pkg)。尝试编译内核树可能有助于解决..."
             # Avoid recompiling full kernel if possible, but maybe necessary
             # make target/linux/compile V=s ? Too broad.
             # Just log the warning for now.
             echo "警告: 内核模块依赖项可能需要 'make menuconfig' 中选择相关驱动/选项，或 'make target/linux/compile'。"
        elif [[ "$missing_pkg" == lib* ]]; then
              echo "依赖项看起来像库 ($missing_pkg)。确保它在 .config 中被选中或由其他包引入。"
        fi
    fi

    # Strategy 3: Re-run make index (Crucial after feeds install/compile)
    echo "运行 make package/index ..."
    make package/index V=s || echo "警告: make package/index 失败"
    fix_attempted=1

    # Final Advice
    echo "--------------------------------------------------"
    echo "重要提示: 依赖项 '$found_pkg_name' 缺失的最常见原因是它没有在配置中启用，或者 feeds/包索引未正确更新。"
    echo "如果此重试仍然失败，请:"
    echo "1. 运行 'make menuconfig' 并确保选中了 '$found_pkg_name' (或提供它的包) 及其所有依赖项。"
    echo "2. 确保 feeds 已更新并安装 ('./scripts/feeds update -a && ./scripts/feeds install -a')."
    echo "3. 尝试 'make download' 下载所有源码。"
    echo "4. 再次尝试编译 'make V=s'."
    echo "--------------------------------------------------"

    # Return success as fixes were attempted, let the main loop retry
    # Return failure only if we couldn't even extract the package name initially
    return 0 # Always return 0 here to allow retry loop to continue
}

# --- Main Compilation Loop ---
retry_count=0
last_fix_applied=""
fix_applied_this_iteration=0
# Flags for batman-adv specific fixes, reset each time compile fails
batman_multicast_patched_this_run=0 # Track patching within one failure cycle
batman_feed_switched_this_run=0    # Track feed switch within one failure cycle
batman_werror_disabled_this_run=0  # Track werror disable within one failure cycle
batman_tasklet_patched_this_run=0  # Track tasklet patch within one failure cycle

# Flag to indicate a metadata fix ran (PKV_VERSION, DEPENDS, FORMAT)
metadata_fix_ran_last_iter=0


while [ $retry_count -lt "$MAX_RETRY" ]; do
    echo "--------------------------------------------------"
    echo "尝试编译: $MAKE_COMMAND (第 $((retry_count + 1)) / $MAX_RETRY 次)..."
    echo "--------------------------------------------------"

    # Reset iteration flag and specific fix flags for this attempt
    fix_applied_this_iteration=0
    # Keep track of cumulative attempts across retries if needed, but resetting per failure seems more logical
    # batman_multicast_patched_this_run=0
    # batman_feed_switched_this_run=0
    # batman_werror_disabled_this_run=0
    # batman_tasklet_patched_this_run=0

    # Before compiling, if metadata was fixed last time, run 'make package/index'
    if [ $metadata_fix_ran_last_iter -eq 1 ]; then
        echo "元数据已在上一次迭代中修复，正在运行 'make package/index'..."
        make package/index V=s || echo "警告: make package/index 失败，继续编译..."
        metadata_fix_ran_last_iter=0 # Reset flag
    fi


    # Run the command and capture status/log
    # Truncate temp log file for current attempt's output
    echo "执行: $MAKE_COMMAND (日志追加到 $LOG_FILE, 本次输出到 $LOG_FILE.tmp)"
    # eval "$MAKE_COMMAND" > "$LOG_FILE.tmp" 2>&1 # Overwrite temp file
    # Capture output and append to main log simultaneously, tee to temp file for analysis
    # Ensure stderr is also captured
    { eval "$MAKE_COMMAND"; } > >(tee "$LOG_FILE.tmp") 2> >(tee -a "$LOG_FILE.tmp" >&2) | tee -a "$LOG_FILE"
    COMPILE_STATUS=${PIPESTATUS[0]} # Get status of the eval command

    # Append the filtered temp log content to the main log (optional, tee already does it)
    # grep -v "WARNING: Makefile '.*' has a dependency on '.*', which does not exist" "$LOG_FILE.tmp" >> "$LOG_FILE"
    # cat "$LOG_FILE.tmp" # Show unfiltered current output (tee already did)

    # Check compile status using exit code AND grep for common failure patterns
    # Use the temp log for error detection from the *just finished* command
    if [ $COMPILE_STATUS -eq 0 ] && \
       ! grep -q -E "^(make\[[0-9]+\]|make): \*\*\* .* Error [0-9]+(|\(ignored\))$" "$LOG_FILE.tmp" && \
       ! grep -q -E "(ERROR: package|configure: error:|error: |Cannot find|No rule to make target|failed to build)" "$LOG_FILE.tmp"; then
        echo "编译成功！"
        rm -f "$LOG_FILE.tmp"
        exit 0
    fi

    echo "编译失败 (退出码: $COMPILE_STATUS 或在日志中检测到错误)，检查错误..."
    extract_error_block "$LOG_FILE.tmp" # Show relevant part of current log

    # --- Error Detection and Fix Logic (Order Matters!) ---
    # Use $LOG_FILE.tmp for checking errors from the *current* attempt

    # 0. VERY SPECIFIC ERRORS FIRST
    # Batman-adv multicast.c struct/function errors (as reported by user)
    # Combine checks for struct error OR function error OR -Werror related to multicast.c
    if grep -q -E 'batman-adv.*multicast\.c' "$LOG_FILE.tmp" && \
       ( grep -q 'struct br_ip.*has no member named' "$LOG_FILE.tmp" || \
         grep -q 'br_multicast_has_router_adjacent' "$LOG_FILE.tmp" || \
         grep -q 'cc1: some warnings being treated as errors' "$LOG_FILE.tmp" ); then
        echo "检测到 batman-adv multicast.c 编译错误 (struct/function/Werror)..."
        # Try fixes in order: Patch -> Disable Werror -> Switch Feed
        if [ "$batman_multicast_patched_this_run" -eq 0 ]; then
            echo "尝试 1: 修补 multicast.c..."
            last_fix_applied="fix_batman_multicast_struct"
            if fix_batman_multicast_struct "$LOG_FILE.tmp"; then
                fix_applied_this_iteration=1
            else
                echo "修补 multicast.c 失败。"
            fi
            batman_multicast_patched_this_run=1 # Mark as attempted this run
        elif [ "$batman_werror_disabled_this_run" -eq 0 ] && grep -q 'cc1: some warnings being treated as errors' "$LOG_FILE.tmp"; then
            echo "尝试 2: 禁用 batman-adv 的 -Werror (因为检测到警告被视为错误)..."
            last_fix_applied="fix_batman_disable_werror"
            if fix_batman_disable_werror; then
                fix_applied_this_iteration=1
            else
                echo "禁用 -Werror 失败。"
            fi
             batman_werror_disabled_this_run=1 # Mark as attempted this run
        elif [ "$batman_feed_switched_this_run" -eq 0 ]; then
            echo "尝试 3: 切换 routing feed 到已知良好 commit..."
            last_fix_applied="fix_batman_switch_feed_multicast"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
            else
                echo "切换 routing feed 失败。"
            fi
            batman_feed_switched_this_run=1 # Mark as attempted this run
        else
            echo "已尝试所有 batman-adv multicast.c 相关修复 (修补, Werror, 切换Feed)，但错误仍存在，停止重试。"
            # rm -f "$LOG_FILE.tmp" # Keep tmp log for inspection
            exit 1
        fi

     # Batman-adv tasklet_setup error
    elif grep -q 'undefined reference to .*tasklet_setup' "$LOG_FILE.tmp" && grep -q -E 'batman-adv|backports|compat' "$LOG_FILE.tmp"; then
        echo "检测到 batman-adv 的 'tasklet_setup' 符号错误..."
        # Order: Switch Feed -> Patch backports
        if [ "$batman_feed_switched_this_run" -eq 0 ]; then
             echo "尝试 1: 切换整个 routing feed..."
             last_fix_applied="fix_batman_switch_feed_tasklet"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
            else
                echo "切换 routing feed 失败。"
            fi
            batman_feed_switched_this_run=1 # Mark as tried
        elif [ "$batman_tasklet_patched_this_run" -eq 0 ]; then
             echo "尝试 2: 修补 backports/compat 头文件..."
             last_fix_applied="fix_batman_tasklet"
             if fix_batman_patch_tasklet "$LOG_FILE.tmp"; then
                 fix_applied_this_iteration=1
             else
                 echo "修复 batman-adv backports tasklet 失败。"
             fi
             batman_tasklet_patched_this_run=1 # Mark as tried
        else # All attempts failed
             echo "已尝试切换 feed 和修补 backports，但 tasklet 错误仍然存在，放弃。"
             # rm -f "$LOG_FILE.tmp"
             exit 1
         fi

    # Trojan-plus buffer_cast error
    elif grep -q 'trojan-plus.*service.cpp.*buffer_cast.*boost::asio' "$LOG_FILE.tmp"; then
        echo "检测到 'trojan-plus boost::asio::buffer_cast' 错误..."
        if [ "$last_fix_applied" = "fix_trojan_plus" ]; then # Check if *last* fix was this one
            echo "上次已尝试修复 trojan-plus，但错误依旧，停止重试。"
            # rm -f "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_trojan_plus"
        if fix_trojan_plus_boost_error; then
            fix_applied_this_iteration=1
        else
            echo "修复 trojan-plus 失败，停止重试。"
            # rm -f "$LOG_FILE.tmp"
            exit 1
        fi

    # po2lmo error
    elif grep -q "po2lmo: command not found" "$LOG_FILE.tmp"; then
        echo "检测到 'po2lmo' 错误..."
        if [ "$last_fix_applied" = "fix_po2lmo" ]; then
            echo "上次已尝试修复 po2lmo，但错误依旧，停止重试。"
            # rm -f "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_po2lmo"
        if fix_po2lmo; then
            fix_applied_this_iteration=1
        else
            echo "修复 po2lmo 失败，停止重试。"
            # rm -f "$LOG_FILE.tmp"
            exit 1
        fi

    # 1. FILESYSTEM/MAKEFILE STRUCTURE ERRORS
    # Makefile separator error
    elif grep -q "missing separator.*Stop." "$LOG_FILE.tmp"; then
        echo "检测到 'missing separator' 错误..."
        # Allow multiple attempts as different files might have the error
        # if [ "$last_fix_applied" = "fix_makefile_separator" ]; then
        #      echo "上次已尝试修复 makefile separator，但错误依旧，停止重试。"
        #      # rm -f "$LOG_FILE.tmp"; exit 1
        # fi
        last_fix_applied="fix_makefile_separator"
        if fix_makefile_separator "$LOG_FILE.tmp"; then # Pass current log segment
            fix_applied_this_iteration=1
            echo "Makefile separator 修复尝试完成，将重试编译。"
        else
            echo "无法定位或清理导致 'missing separator' 错误的 Makefile，此轮修复失败。"
            # Don't exit immediately, allow retry loop, maybe another fix works
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
    # Check for opkg install/satisfy messages or pkg_hash unresolved errors
    elif grep -q -E '(Cannot satisfy.+dependencies for|pkg_hash_check_unresolved|opkg_install_cmd.+Cannot find package)' "$LOG_FILE.tmp"; then
        echo "检测到打包/安装阶段缺少依赖项错误..."
        # Allow multiple attempts as different dependencies might be missing
        # if [ "$last_fix_applied" = "fix_missing_dependency" ]; then
        #     echo "上次已尝试修复缺失的依赖项，但错误依旧。请检查 .config。"
        #     # rm -f "$LOG_FILE.tmp"; exit 1
        # fi
        last_fix_applied="fix_missing_dependency"
        if fix_missing_dependency "$LOG_FILE.tmp"; then
            fix_applied_this_iteration=1
        else
            echo "尝试修复缺失依赖项失败（无法提取包名），停止重试。"
            # rm -f "$LOG_FILE.tmp"
            exit 1
        fi

    # Package metadata errors (Version, Dependency Format, Duplicates)
    # Check for specific makefile warnings/errors related to metadata
    elif grep -q -E "Makefile.*(package version is invalid|dependency format is invalid|duplicate dependency detected|has a dependency on .* which does not exist)" "$LOG_FILE.tmp"; then
        echo "检测到包元数据错误 (版本/依赖格式/重复/缺失)..."
        # Avoid immediate loop if no changes were made last time by metadata fixes
        if [ "$last_fix_applied" = "fix_metadata" ] && [ $metadata_fix_ran_last_iter -eq 0 ]; then
            echo "上次已尝试修复元数据但无更改或错误依旧，停止重试。"
            # rm -f "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_metadata"
        changed_version=0
        changed_format=0
        changed_depends=0
        metadata_fix_ran_last_iter=0 # Reset flag for this iteration

        echo "运行 PKG_VERSION/RELEASE 修复..."
        if fix_pkg_version; then changed_version=1; echo "PKG_VERSION/RELEASE 修复应用了更改。"; fi
        echo "运行依赖格式修复 (移除版本后缀)..."
        if fix_dependency_format; then changed_format=1; echo "依赖格式修复应用了更改。"; fi
        echo "运行重复依赖修复..."
        if fix_depends; then changed_depends=1; echo "重复依赖修复应用了更改。"; fi

        if [ $changed_version -eq 1 ] || [ $changed_format -eq 1 ] || [ $changed_depends -eq 1 ]; then
            echo "应用了包元数据修复，将运行 'make package/index' 后重试。"
            fix_applied_this_iteration=1
            metadata_fix_ran_last_iter=1 # Set flag to run 'make package/index' next iter
        else
            echo "检测到元数据错误，但修复函数未报告任何更改。"
            if grep -q "dependency on .* which does not exist" "$LOG_FILE.tmp"; then
                echo "警告: 检测到 'dependency ... which does not exist'。这通常需要手动检查 .config 或 feeds 是否正确/完整。"
                echo "将继续重试，但可能失败。"
                # Don't set fix_applied_this_iteration, let loop logic handle retry limit
            else
                 echo "未应用元数据修复，将尝试通用重试。"
                 # Don't exit immediately, maybe it's a transient issue fixed by retry
                 # last_fix_applied="fix_generic_retry" # Mark for retry logic below
            fi
        fi

    # 3. GENERIC ERRORS / FALLBACKS (Check using the provided ERROR_PATTERN)
    elif grep -E -q "$ERROR_PATTERN" "$LOG_FILE.tmp"; then
        local matched_pattern
        matched_pattern=$(grep -E -m 1 "$ERROR_PATTERN" "$LOG_FILE.tmp")
        echo "检测到通用错误模式 ($ERROR_PATTERN): ${matched_pattern:0:100}..." # Show beginning of match
        # Avoid immediate loop on generic error if no fix applied last time
        if [ "$last_fix_applied" = "fix_generic_retry" ] && [ $fix_applied_this_iteration -eq 0 ]; then
             echo "上次已尝试通用重试但无效果，错误依旧 ($matched_pattern)，停止重试。"
             # rm -f "$LOG_FILE.tmp"
             exit 1
        fi

        # Generic fix: just retry without applying a specific fix function
        echo "未找到特定修复程序，将重试编译 (通用错误)。"
        last_fix_applied="fix_generic_retry"
        # No fix applied this iteration, rely on loop counter and check below
    else
        # If no known error pattern matched, but compile failed
        echo "未检测到已知或通用的错误模式，但编译失败 (退出码: $COMPILE_STATUS)。"
        echo "请检查完整日志: $LOG_FILE"
        # rm -f "$LOG_FILE.tmp" # Keep tmp log for inspection
        exit 1
    fi

    # --- Loop Control ---
    # Reset batman-adv specific flags only if the main command succeeded but errors were grep'd (unlikely based on current checks)
    # or if we are about to retry. Let's reset them before the next iteration starts.
    if [ $fix_applied_this_iteration -eq 1 ]; then
         echo "已应用修复 ($last_fix_applied)，将重试。"
         # Reset batman flags specific to THIS failure instance before next retry
         batman_multicast_patched_this_run=0
         batman_feed_switched_this_run=0
         batman_werror_disabled_this_run=0
         batman_tasklet_patched_this_run=0
    elif [ $COMPILE_STATUS -ne 0 ]; then # Compile failed, but no fix was applied in this iteration
        echo "警告：检测到错误，但此轮未应用有效修复。上次尝试: ${last_fix_applied:-无}"
        # Allow one simple retry even if no fix was applied, maybe it was transient
        if [[ "$last_fix_applied" == fix_generic_retry ]] || [[ "$last_fix_applied" == fix_metadata && $metadata_fix_ran_last_iter -eq 0 ]] || [ $retry_count -ge $((MAX_RETRY - 1)) ]; then
             echo "停止重试，因为未应用有效修复或已达重试上限。"
             # rm -f "$LOG_FILE.tmp"
             exit 1
        else
             echo "将再重试一次，检查是否有其他可修复的错误出现。"
             last_fix_applied="fix_generic_retry" # Mark that we are doing a simple retry
             # Reset batman flags before next retry
             batman_multicast_patched_this_run=0
             batman_feed_switched_this_run=0
             batman_werror_disabled_this_run=0
             batman_tasklet_patched_this_run=0
        fi
    fi

    # Clean up temp log for this iteration AFTER analysis
    rm -f "$LOG_FILE.tmp"

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
