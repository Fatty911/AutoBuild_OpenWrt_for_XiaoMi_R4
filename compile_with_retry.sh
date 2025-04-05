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
# Add new error patterns
ERROR_PATTERN="${4:-error:|failed|undefined reference|invalid|File exists|missing separator|cannot find dependency|No rule to make target|warnings being treated as errors}"

# --- Argument Check ---
if [ -z "$MAKE_COMMAND" ] || [ -z "$LOG_FILE" ]; then
    echo "错误：缺少必要参数。用法: $0 <make_command> <log_file> [max_retry] [error_pattern]"
    exit 1
fi

# --- Helper Function: Get Relative Path ---
# (Keep the existing get_relative_path function)
get_relative_path() {
    local path="$1"
    local workdir_pattern="/home/runner/work/[^/]*/[^/]*/openwrt/"
    local github_pattern="/github/workspace/openwrt/"
    local mnt_pattern="/mnt/openwrt/" # Add other potential base paths if needed

    # Try to construct relative path from PWD if it's an absolute path within PWD
    local current_pwd=$(pwd)
    if [[ "$path" == "$current_pwd/"* ]]; then
        echo "${path#$current_pwd/}"
        return 0
    fi

    # Original patterns
    if [[ "$path" == "$workdir_pattern"* ]]; then
        echo "${path#$workdir_pattern}"
    elif [[ "$path" == "$github_pattern"* ]]; then
        echo "${path#$github_pattern}"
    elif [[ "$path" == "$mnt_pattern"* ]]; then
        echo "${path#$mnt_pattern}"
    elif [[ "$path" != /* ]]; then
        # Already relative or a simple filename
        echo "$path"
    else
        # Absolute path from an unknown root, return as is but log warning
        echo "警告: 未知的基础路径或在当前工作目录之外，返回原始绝对路径: $path" >&2
        echo "$path"
    fi
}


# --- Fix Functions ---

### Fix trojan-plus boost::asio::buffer_cast error
# (Keep the existing fix_trojan_plus_boost_error function)
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
        # Improve grep pattern for flexibility
        local target_build_dir=$(grep -oE '(/[^ ]+)?/build_dir/target-[^/]+/trojan-plus-[^/]+' "$LOG_FILE" | head -n 1)
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
    # Use alternative sed delimiters
    if sed -i.bak "s|boost::asio::buffer_cast<char\*>(\(udp_read_buf.prepare([^)]*)\))|static_cast<char*>(\1.data())|g" "$found_path"; then
        if grep -q 'static_cast<char\*>' "$found_path"; then
            echo "已成功修改 $found_path"
            rm "$found_path.bak"
            return 0
        else
            echo "尝试修改 $found_path 失败 (sed 命令成功但未找到预期更改)，恢复备份文件。"
            mv "$found_path.bak" "$found_path"
            return 1
        fi
    else
         echo "尝试修改 $found_path 失败 (sed 命令失败)，恢复备份文件。"
         # Check if backup exists before moving
         [ -f "$found_path.bak" ] && mv "$found_path.bak" "$found_path"
         return 1
    fi
}

### Fix po2lmo command not found
# (Keep the existing fix_po2lmo function)
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
# (Keep the existing extract_error_block function)
extract_error_block() {
    local log_file="$1"
    echo "--- 最近 300 行日志 (${log_file}) ---"
    tail -n 300 "$log_file"
    echo "--- 日志结束 ---"
}

### Fix PKG_VERSION and PKG_RELEASE formats
# (Keep the existing fix_pkg_version function)
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
            new_release=$(echo "$suffix" | tr -cd '0-9' | grep -o '[0-9]\+' || echo "1")

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

                release=$new_release
                modified_in_loop=1
                makefile_changed=1
            fi
        fi

        # Case 2: PKG_RELEASE exists but is not a simple number
        if [ "$modified_in_loop" -eq 0 ] && [ -n "$release" ] && ! [[ "$release" =~ ^[0-9]+$ ]]; then
            new_release=$(echo "$release" | tr -cd '0-9' | grep -o '[0-9]\+' || echo "1")
            if [ "$release" != "$new_release" ]; then
                echo "修正 $makefile: PKG_RELEASE: '$release' -> '$new_release'"
                sed -i.bak "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile" && rm "$makefile.bak"
                makefile_changed=1
            fi
        # Case 3: PKG_RELEASE is missing entirely and PKG_VERSION exists
        elif [ -z "$release" ] && echo "$original_content" | grep -q "^PKG_VERSION:=" && ! echo "$original_content" | grep -q "^PKG_RELEASE:="; then
             echo "添加 $makefile: PKG_RELEASE:=1"
             sed -i.bak "/^PKG_VERSION:=.*/a PKG_RELEASE:=1" "$makefile" && rm "$makefile.bak"
             makefile_changed=1
        fi

        if [ "$makefile_changed" -eq 1 ]; then
             changed_count=$((changed_count + 1))
        fi
    done
    if [ "$changed_count" -gt 0 ]; then return 0; else return 1; fi
}


### Fix duplicate dependencies
# (Keep the existing fix_depends function, seems robust)
fix_depends() {
    echo "修复依赖重复..."
    local flag_file=".fix_depends_changed"
    rm -f "$flag_file"

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

    if [ -f "$flag_file" ]; then
        rm -f "$flag_file"
        return 0
    else
        return 1
    fi
}


### Fix dependency format (Using Temp Awk File)
# (Keep the existing fix_dependency_format function)
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
            # Remove spaces after + sign: This logic might be flawed or unnecessary.
            # Standard format is '+package', spaces separate dependencies. Removing spaces after + might merge things.
            # Let's disable this: gsub(/^\+[[:space:]]+/, "+", dep)

            # Check if modification happened
            if (original_dep != dep) {
                line_changed = 1
            }

            # Add to new string if not already seen (basic duplicate check within the line)
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
                echo "警告: awk声称修改了 $makefile 但文件未变或为空。" >&2
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
             # Consider restoring: mv "$makefile.bak" "$makefile"
        fi
    ' _ {} "$flag_file" "$awk_script_file" \; # Pass flag_file and awk_script_file as arguments

    local find_status=$? # Capture find's exit status (optional)

    # Clean up the temporary file
    rm -f "$awk_script_file"
    trap - EXIT HUP INT QUIT TERM # Clear the trap

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
# (Keep the existing fix_mkdir_conflict function)
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
        fi
    else
        echo "警告：冲突路径 $FAILED_PATH 已不存在。"
    fi

    # Try to identify the package causing the error more reliably
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 50 "mkdir: cannot create directory '$FAILED_PATH'" | grep -m 1 -Eo '(ERROR: (package|feeds)/[^ ]+ failed to build\.|make\[[0-9]+\]: \*\*\* \[(.*)/\.built\] Error)')
    PKG_PATH=""
    PKG_DIR_REL=""

    if [[ -n "$PKG_ERROR_LINE" ]]; then
        if [[ "$PKG_ERROR_LINE" == ERROR:* ]]; then
            PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build\./\1/')
            if [[ ("$PKG_PATH" == package/* || "$PKG_PATH" == feeds/*) && -d "$PKG_PATH" ]]; then
                 PKG_DIR_REL="$PKG_PATH"
            else
                 echo "警告: 从 'ERROR:' 行提取的路径 '$PKG_PATH' 不是一个有效目录。"
                 PKG_PATH=""
            fi
        else
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
        echo "已清理包 $PKG_NAME，将重试主编译命令。"
    else
        echo "无法从日志中明确推断出导致错误的包或推断的路径无效。仅删除了冲突路径。"
        if [[ -n "$PKG_BUILD_DIR_PART" ]] && [ -d "$PKG_BUILD_DIR_PART" ]; then
             echo "尝试清理具体的 build_dir: $PKG_BUILD_DIR_PART"
             rm -rf "$PKG_BUILD_DIR_PART"
        fi
    fi
    return 0
}

### Fix symbolic link conflicts
# (Keep the existing fix_symbolic_link_conflict function)
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
        fi
    else
         echo "警告：冲突链接 $FAILED_LINK 已不存在。"
    fi

    # Try to identify the package causing the error (similar logic as fix_mkdir_conflict)
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 50 "failed to create symbolic link '$FAILED_LINK'" | grep -m 1 -Eo '(ERROR: (package|feeds)/[^ ]+ failed to build\.|make\[[0-9]+\]: \*\*\* \[(.*)/\.built\] Error)')
    PKG_PATH=""
    PKG_DIR_REL=""

    if [[ -n "$PKG_ERROR_LINE" ]]; then
        if [[ "$PKG_ERROR_LINE" == ERROR:* ]]; then
            PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build\./\1/')
            if [[ ("$PKG_PATH" == package/* || "$PKG_PATH" == feeds/*) && -d "$PKG_PATH" ]]; then
                PKG_DIR_REL="$PKG_PATH"
            else
                echo "警告: 从 'ERROR:' 行提取的路径 '$PKG_PATH' 不是一个有效目录。"
                PKG_PATH=""
            fi
        else
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
             echo "清理包 $PKG_NAME 失败，但已删除冲突链接，将继续尝试主编译命令。"
        }
        echo "已清理包 $PKG_NAME，将重试主命令。"
    else
        echo "无法从日志中明确推断出导致错误的包或路径无效。仅删除了冲突链接。"
         if [[ -n "$PKG_BUILD_DIR_PART" ]] && [ -d "$PKG_BUILD_DIR_PART" ]; then
             echo "尝试清理具体的 build_dir: $PKG_BUILD_DIR_PART"
             rm -rf "$PKG_BUILD_DIR_PART"
        fi
    fi
    return 0
}


### Fix Makefile "missing separator" error (Revised)
# (Keep the existing fix_makefile_separator function)
fix_makefile_separator() {
    local log_file="$1"
    echo "检测到 'missing separator' 错误，尝试修复..."
    local error_block make_dir make_dir_rel makefile_info makefile_name line_num makefile_path_rel pkg_dir_rel fix_attempted=0

    # Extract the block around the error more reliably
    # Look for the line number directly in the error message
    makefile_info=$(grep -m 1 'missing separator' "$log_file")
    if [[ "$makefile_info" =~ ^([^:]+):([0-9]+): ]]; then
        makefile_name="${BASH_REMATCH[1]}"
        line_num="${BASH_REMATCH[2]}"
    else
         echo "警告: 无法从 'missing separator' 行直接提取文件名和行号。"
         makefile_name=""
         line_num=""
    fi

    # Extract the directory where make was running
    # Try "make[N]: Leaving directory..." first
    make_dir=$(grep -m 1 "make\[[0-9]*\]: Leaving directory" "$log_file" | sed -e "s/.*Leaving directory '\([^']*\)'/\1/")
    # Fallback to "make: Leaving directory..."
     if [ -z "$make_dir" ]; then
         make_dir=$(grep -m 1 "make: Leaving directory" "$log_file" | sed -e "s/.*Leaving directory '\([^']*\)'/\1/")
     fi
     # Fallback: Use the directory from the error message if available and make_dir failed
     if [ -z "$make_dir" ] && [ -n "$makefile_name" ]; then
         make_dir=$(dirname "$makefile_name")
     fi

    if [ -z "$make_dir" ]; then
        echo "错误: 无法从日志中提取 'Leaving directory' 或相关目录信息。"
        return 1 # Cannot proceed without directory context
    fi
    echo "错误上下文目录: $make_dir"
    pkg_dir_rel=$(get_relative_path "$make_dir")
     if [ -z "$pkg_dir_rel" ] || [[ "$pkg_dir_rel" == /* && ! -d "$pkg_dir_rel" ]]; then # Check if absolute path actually exists if conversion failed
         echo "错误: 无法将目录 '$make_dir' 转换为有效的相对路径或找到对应的绝对路径。"
         # Try cleaning based on makefile_name if possible
         if [[ -n "$makefile_name" ]]; then
             makefile_path_rel=$(get_relative_path "$makefile_name")
             pkg_dir_rel=$(dirname "$makefile_path_rel")
             echo "尝试基于 Makefile 路径推断清理目录: $pkg_dir_rel"
             if [[ -z "$pkg_dir_rel" ]] || [[ "$pkg_dir_rel" == "." ]] || [[ "$pkg_dir_rel" == /* ]]; then
                 echo "基于 Makefile 路径推断目录失败。"
                 return 1
             fi
         else
             return 1
         fi
     fi
     echo "相对包/目录路径: $pkg_dir_rel"

    # If file/line not extracted earlier, try again from the error block
    if [ -z "$line_num" ]; then
        error_block=$(grep -B 2 -A 1 "missing separator.*Stop." "$log_file")
        makefile_info=$(echo "$error_block" | grep "missing separator.*Stop." | head -n 1)
        makefile_name=$(echo "$makefile_info" | cut -d':' -f1)
        line_num=$(echo "$makefile_info" | cut -d':' -f2)
        if ! [[ "$line_num" =~ ^[0-9]+$ ]]; then
            line_num="" # Invalidate line number
        fi
    fi

    # Construct the full relative path to the Makefile
    # Handle cases where makefile_name might already contain part of the path relative to CWD or be absolute
    makefile_path_rel=$(get_relative_path "$makefile_name")
    if [[ "$makefile_path_rel" != /* ]] && [ ! -f "$makefile_path_rel" ] && [ -f "$pkg_dir_rel/$makefile_name" ]; then
         # If relative path doesn't exist, try combining with pkg_dir_rel
         makefile_path_rel="$pkg_dir_rel/$makefile_name"
    fi

    # Canonicalize the path (remove ../, ./) relative to current directory
    if [ -n "$makefile_path_rel" ]; then
         makefile_path_rel_canon=$(realpath -m --relative-to=. "$makefile_path_rel" 2>/dev/null)
         if [ $? -eq 0 ] && [ -f "$makefile_path_rel_canon" ]; then
              makefile_path_rel="$makefile_path_rel_canon"
         elif [ ! -f "$makefile_path_rel" ]; then
              # If canonical fails and original doesn't exist, maybe it's inside the build dir?
              # This is harder to guess reliably. Let's stick with the best guess.
              echo "警告: 无法验证推测的 Makefile 路径 '$makefile_path_rel'"
         fi
    else
         makefile_path_rel="" # Clear if initial name was empty
    fi


    echo "推测错误的 Makefile: ${makefile_path_rel:-未知}, 行号: ${line_num:-未知}"

    # Attempt to fix the indentation with sed if we have a valid path and line number
    if [ -n "$makefile_path_rel" ] && [ -f "$makefile_path_rel" ] && [ -n "$line_num" ]; then
        echo "检查文件: $makefile_path_rel，第 $line_num 行..."
        line_content=$(sed -n "${line_num}p" "$makefile_path_rel")
        # Check if the line actually starts with spaces (and not already a tab or empty/comment)
        if [[ "$line_content" =~ ^[[:space:]]+ ]] && ! [[ "$line_content" =~ ^\t ]] && ! [[ "$line_content" =~ ^[[:space:]]*# ]] && [[ -n "$line_content" ]]; then
            echo "检测到第 $line_num 行可能使用空格缩进，尝试替换为 TAB..."
            cp "$makefile_path_rel" "$makefile_path_rel.bak"
            # Replace all leading whitespace with a single tab more safely
            sed -i.sedfix "${line_num}s/^[[:space:]]\+/	/" "$makefile_path_rel" # Use literal tab
            # Verify the change
            new_line_content=$(sed -n "${line_num}p" "$makefile_path_rel")
            if [[ "$new_line_content" =~ ^\t ]]; then
                 echo "已尝试用 TAB 修复 $makefile_path_rel 第 $line_num 行的缩进。"
                 rm "$makefile_path_rel.bak" "$makefile_path_rel.sedfix" # Clean up backups
                 fix_attempted=1
                 return 0 # Success, retry compile
            else
                 echo "警告: 尝试用 sed 修复 $makefile_path_rel 失败，恢复备份文件。"
                 mv "$makefile_path_rel.bak" "$makefile_path_rel" # Restore backup
                 rm -f "$makefile_path_rel.sedfix"
            fi
        else
            echo "第 $line_num 行似乎没有前导空格、已经是 TAB 缩进、是注释或为空，跳过 sed 修复。"
        fi
    else
         echo "Makefile 路径 '$makefile_path_rel' 无效或行号未知，无法尝试 sed 修复。"
    fi

    # If sed fix wasn't attempted or failed, fall back to cleaning the package directory
    if [ "$fix_attempted" -eq 0 ]; then
        # Use the most likely relative directory path identified earlier
        local dir_to_clean="$pkg_dir_rel"
        if [ -d "$dir_to_clean" ] && [[ "$dir_to_clean" != "." ]] && [[ "$dir_to_clean" != ".." ]] ; then
            echo "尝试清理目录: $dir_to_clean ..."
            # Use make clean if it looks like a package dir, otherwise just rm build dir? This is tricky.
            # Let's assume 'make clean' is appropriate if it contains a Makefile.
            if [ -f "$dir_to_clean/Makefile" ]; then
                make "$dir_to_clean/clean" V=s || {
                    echo "警告: 清理 $dir_to_clean 失败，但这可能不是致命错误，将继续重试主命令。"
                }
                echo "已清理 $dir_to_clean，将重试主命令。"
                fix_attempted=1
                return 0 # Indicate fix attempt was made
            else
                 echo "目录 $dir_to_clean 不含 Makefile，不执行 'make clean'。如果这是 build_dir，可能需要手动清理。"
                 # Maybe try cleaning the specific build dir if it was identified?
                 PKG_BUILD_DIR_PART=$(echo "$makefile_info" | sed -n 's|make\[[0-9]\+\]: \*\*\* \[\(.*\)/\.built\] Error.*|\1|p') # Example pattern
                 if [ -n "$PKG_BUILD_DIR_PART" ] && [ -d "$PKG_BUILD_DIR_PART" ]; then
                     echo "尝试清理 build_dir: $PKG_BUILD_DIR_PART"
                     rm -rf "$PKG_BUILD_DIR_PART"
                     return 0
                 else
                     return 1 # Cannot clean
                 fi

            fi
        else
            echo "错误: 推断的清理目录 '$dir_to_clean' 无效或不存在，无法清理。"
            return 1 # Cannot clean, likely won't recover
        fi
    fi

    # Should not reach here if fix was attempted, but return 1 just in case
    return 1
}


### Fix batman-adv 'struct br_ip' dst error
# (Keep the existing fix_batman_br_ip_dst function)
### Fix batman-adv 'struct br_ip' dst error (REVISED for IPV6_ADDR_MC_SCOPE)
fix_batman_br_ip_dst() {
    local log_file="$1"
    echo "尝试修复 batman-adv 的 'struct br_ip has no member named dst' (特别针对 IPV6_ADDR_MC_SCOPE)..."

    local multicast_file patch_applied=0
    # Find the multicast.c file (keep existing find logic)
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

    # --- Specific Patch for IPV6_ADDR_MC_SCOPE ---
    # Use sed with extended regex (-E) and capture groups to replace the argument
    # Match: IPV6_ADDR_MC_SCOPE(&br_ip_entry->addr.dst.ip6)
    # Replace with: IPV6_ADDR_MC_SCOPE(&br_ip_entry->u.ip6)
    # Using | as delimiter to avoid escaping /
    sed -i -E 's|IPV6_ADDR_MC_SCOPE\(&br_ip_entry->addr\.dst\.ip6\)|IPV6_ADDR_MC_SCOPE\(&br_ip_entry->u.ip6\)|g' "$multicast_file"
    if grep -q 'IPV6_ADDR_MC_SCOPE(&br_ip_entry->u.ip6)' "$multicast_file"; then
        echo "成功修补 $multicast_file 中 IPV6_ADDR_MC_SCOPE 的调用。"
        patch_applied=1
    else
        echo "警告: 未能在 $multicast_file 中应用 IPV6_ADDR_MC_SCOPE 的补丁。"
    fi

    # --- General Patch (as fallback or additional fix if needed) ---
    # Replace other instances if they exist
    sed -i 's/br_ip_entry->addr\.dst\.ip6/br_ip_entry->u.ip6/g' "$multicast_file"
    sed -i 's/br_ip_entry->addr\.dst\.ip4/br_ip_entry->u.ip4/g' "$multicast_file"
    # Check if the *problematic* pattern is gone (more reliable check)
    if ! grep -q 'br_ip_entry->addr\.dst\.ip6' "$multicast_file" && ! grep -q 'br_ip_entry->addr\.dst\.ip4' "$multicast_file" ; then
        echo "常规 br_ip_entry->addr.dst.* 替换已应用或无需应用。"
        # If the specific patch didn't apply, but the general one did, still count as success
        if [ $patch_applied -eq 0 ]; then patch_applied=1; fi
    else
         echo "警告: $multicast_file 中仍然存在 addr.dst 模式，修补可能不完整。"
    fi


    if [ $patch_applied -eq 1 ]; then
        echo "修补完成，将重试编译。"
        rm "$multicast_file.bak"
        return 0
    else
        echo "修补 $multicast_file 失败，恢复备份文件。"
        mv "$multicast_file.bak" "$multicast_file"
        return 1
    fi
}

### Disable -Werror specifically for batman-adv package
fix_batman_disable_werror() {
    local batman_makefile="package/feeds/$FEED_ROUTING_NAME/batman-adv/Makefile"
    local kmod_makefile="package/kernel/batman-adv/Makefile" # Check if kmod is separate

    echo "尝试在 batman-adv Makefile 中禁用 -Werror..."
    local modified=0

    # Modify userspace package Makefile
    if [ -f "$batman_makefile" ]; then
        # Check if already disabled
        if ! grep -q "filter.*Werror" "$batman_makefile"; then
            echo "正在修改 $batman_makefile..."
            # Add a line to filter out -Werror from CFLAGS before including package.mk
            # Using awk for safer insertion before a specific line
            awk '
            /include \.\.\/\.\.\/package.mk/ {
              print ""
              print "# Disable -Werror for this package"
              print "TARGET_CFLAGS:=$(filter-out -Werror,$(TARGET_CFLAGS))"
              print ""
            }
            { print }
            ' "$batman_makefile" > "$batman_makefile.tmp"

            if [ $? -eq 0 ] && [ -s "$batman_makefile.tmp" ]; then
                 mv "$batman_makefile.tmp" "$batman_makefile"
                 echo "已在 $batman_makefile 中添加 TARGET_CFLAGS 过滤。"
                 modified=1
            else
                 echo "错误: 使用 awk 修改 $batman_makefile 失败。"
                 rm -f "$batman_makefile.tmp"
            fi
        else
            echo "$batman_makefile 中似乎已禁用 -Werror。"
            modified=1 # Assume it's okay
        fi
    else
        echo "未找到 $batman_makefile。"
    fi

    # Modify kernel module Makefile (if it exists separately)
    if [ -f "$kmod_makefile" ]; then
         if ! grep -q "filter.*Werror" "$kmod_makefile"; then
            echo "正在修改 $kmod_makefile..."
            # Kernel modules might use different includes, target $(KERNEL_MAKE)
            # A safer approach might be to add it near CFLAGS definition if it exists
             # Let's try adding to EXTRA_CFLAGS common in kernel modules
             if grep -q 'EXTRA_CFLAGS +=' "$kmod_makefile"; then
                 sed -i.bak '/EXTRA_CFLAGS +=/a EXTRA_CFLAGS:=$(filter-out -Werror,$(EXTRA_CFLAGS))' "$kmod_makefile" && rm "$kmod_makefile.bak"
                 echo "已在 $kmod_makefile 中尝试添加 EXTRA_CFLAGS 过滤。"
                 modified=1
             else
                 # Add the line near the top as a fallback
                 sed -i.bak '1 a \\n# Disable -Werror for this package\nEXTRA_CFLAGS:=$(filter-out -Werror,$(EXTRA_CFLAGS))\n' "$kmod_makefile" && rm "$kmod_makefile.bak"
                 echo "已在 $kmod_makefile 顶部尝试添加 EXTRA_CFLAGS 过滤。"
                 modified=1
             fi
         else
             echo "$kmod_makefile 中似乎已禁用 -Werror。"
             modified=1
         fi
    else
         echo "未找到单独的 kmod-batman-adv Makefile ($kmod_makefile)。"
         # If the main Makefile handles both, the first modification might be enough
    fi


    if [ $modified -eq 1 ]; then
        # Clean the package to ensure new flags are used
        echo "清理 batman-adv 以应用新的编译标志..."
        make "package/feeds/$FEED_ROUTING_NAME/batman-adv/clean" DIRCLEAN=1 V=s || echo "警告: 清理 batman-adv 失败。"
        [ -f "$kmod_makefile" ] && make "$kmod_makefile/clean" DIRCLEAN=1 V=s || echo "警告: 清理 kmod-batman-adv 失败。"
        return 0
    else
        echo "无法修改任何 Makefile 来禁用 -Werror。"
        return 1
    fi
}
### Fix batman-adv tasklet_setup symbol conflict
# (Keep the existing fix_batman_patch_tasklet function)
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
        sed -i.bak '/tasklet_setup/d' "$backports_header_path"
        if ! grep -q 'tasklet_setup' "$backports_header_path"; then
            echo "已从 $backports_header_path 移除 tasklet_setup 定义。"
            rm "$backports_header_path.bak"
            return 0
        else
            echo "警告: 尝试从 $backports_header_path 移除 tasklet_setup 失败，恢复备份。"
            mv "$backports_header_path.bak" "$backports_header_path"
            return 1
        fi
    else
         echo "$backports_header_path 中未找到 tasklet_setup 定义，无需修补。"
         return 0 # Return success as no action was needed
    fi
}

### Switch batman-adv package to specified commit (DEPRECATED for feeds)
fix_batman_switch_package() {
    echo "警告: fix_batman_switch_package 对 feeds 中的包通常无效，因为它们不是 git 仓库。"
    echo "       请使用 fix_batman_switch_feed 代替。"
    return 1 # Mark as failed immediately
}

### Switch entire routing feed to specified commit (Revised)
fix_batman_switch_feed() {
    local target_commit="$1"
    local feed_name="$FEED_ROUTING_NAME"
    local feed_conf_file="feeds.conf.default"
    local feed_conf_line_pattern="src-git $feed_name .*$FEED_ROUTING_URL_PATTERN"

    echo "尝试切换 $feed_name feed 至 commit $target_commit 通过修改 $feed_conf_file ..."

    if [ ! -f "$feed_conf_file" ]; then
         # Try feeds.conf if default doesn't exist
         if [ -f "feeds.conf" ]; then
             feed_conf_file="feeds.conf"
             echo "使用 feeds.conf 文件。"
         else
             echo "错误: 未找到 $feed_conf_file 或 feeds.conf 文件。"
             return 1
         fi
    fi

    # Check if the line exists and already has the correct commit
    if grep -q "^$feed_conf_line_pattern;$target_commit" "$feed_conf_file"; then
        echo "$feed_name feed 已在 $feed_conf_file 中指向 commit $target_commit。"
        # Still run update/install to ensure consistency
        echo "运行 feeds update/install 以确保一致性..."
        ./scripts/feeds update "$feed_name" || { echo "错误: feeds update $feed_name 失败"; return 1; }
        # Install all packages from the feed to be safe
        ./scripts/feeds install -a -p "$feed_name" || { echo "错误: feeds install -a -p $feed_name 失败"; return 1; }
        return 0
    fi

    # Find the line and modify it (or add if not present - less likely for default feeds)
    if grep -q "^$feed_conf_line_pattern" "$feed_conf_file"; then
        echo "在 $feed_conf_file 中找到 $feed_name feed 定义，正在修改 commit..."
        # Use sed to replace the line, adding the commit hash
        # Use a temporary file for safety
        sed -e "s|^$feed_conf_line_pattern.*|src-git $feed_name $(grep "^$feed_conf_line_pattern" "$feed_conf_file" | head -n 1 | cut -d' ' -f3 | cut -d';' -f1);$target_commit|" "$feed_conf_file" > "$feed_conf_file.tmp"
        if [ $? -eq 0 ] && [ -s "$feed_conf_file.tmp" ]; then
             mv "$feed_conf_file.tmp" "$feed_conf_file"
             echo "已将 $feed_conf_file 中的 $feed_name 更新为 commit $target_commit"
        else
             echo "错误: 使用 sed 修改 $feed_conf_file 失败。"
             rm -f "$feed_conf_file.tmp"
             return 1
        fi
    else
        echo "错误: 未能在 $feed_conf_file 中找到 '$feed_conf_line_pattern' 定义。"
        echo "请手动检查你的 feeds 配置文件。"
        return 1
    fi

    echo "运行 feeds update 和 install 以应用更改..."
    ./scripts/feeds update "$feed_name" || { echo "错误: feeds update $feed_name 失败"; return 1; }
    ./scripts/feeds install -a -p "$feed_name" || { echo "错误: feeds install -a -p $feed_name 失败"; return 1; }

    echo "切换 $feed_name feed 至 commit $target_commit 完成。"
    # Clean the potentially problematic package build dir after switching source
    echo "清理旧的 batman-adv 构建目录..."
    make package/feeds/$feed_name/batman-adv/clean DIRCLEAN=1 V=s || echo "警告: 清理旧 batman-adv 构建文件失败。"
    # Also clean the kernel module part if it exists
    if [ -d "package/kernel/batman-adv" ]; then
        make package/kernel/batman-adv/clean DIRCLEAN=1 V=s || echo "警告: 清理旧 kmod-batman-adv 构建文件失败。"
    fi

    return 0
}


### Fix missing dependency during packaging stage
fix_missing_dependency() {
    local log_file="$1"
    local missing_dep_pattern='(cannot find dependency|Cannot satisfy.+dependencies for) ([^ ]+)( for|:)'
    local missing_pkg install_pkg_name pkg_path fix_attempted=0

    echo "检测到安装/打包阶段缺少依赖项错误..."

    # Extract the first missing package name
    missing_pkg=$(grep -E "$missing_dep_pattern" "$log_file" | sed -n -r "s/$missing_dep_pattern/\2/p" | head -n 1)

    if [ -z "$missing_pkg" ]; then
        echo "无法从日志中提取缺少的依赖项名称。"
        return 1 # Cannot proceed without package name
    fi
    echo "检测到缺少的依赖项: $missing_pkg"

    # Strategy 1: Force feeds update/install
    echo "尝试强制更新和安装所有 feeds 包..."
    ./scripts/feeds update -a || echo "警告: feeds update -a 失败"
    ./scripts/feeds install -a || echo "警告: feeds install -a 失败"
    # Check if the specific package can be installed now
    install_pkg_name=$(./scripts/feeds list | grep -w "$missing_pkg$" | cut -d' ' -f1) # Get full package name if possible
    if [ -n "$install_pkg_name" ]; then
        echo "尝试安装 specific package $install_pkg_name..."
        ./scripts/feeds install "$install_pkg_name" || echo "警告: 安装 $install_pkg_name 失败"
    else
         echo "警告: 在 feeds list 中找不到包 '$missing_pkg'"
    fi
    fix_attempted=1 # Mark fix as attempted even if install fails

    # Strategy 2: Try to compile the specific package
    echo "尝试查找并编译包 '$missing_pkg'..."
    # Find the package directory (might be in package/ or feeds/)
    pkg_path=$(find package feeds -name "$missing_pkg" -type d -path "*/$missing_pkg" -print -quit)
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
             kmod_path=$(find package/kernel package/network -name "$kmod_name" -type d -print -quit)
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

    # Strategy 3: Run metadata fixes again
    echo "尝试再次运行元数据修复..."
    fix_pkg_version || echo "PKG_VERSION 修复未执行或无更改。"
    fix_dependency_format || echo "依赖格式修复未执行或无更改。"
    fix_depends || echo "重复依赖修复未执行或无更改。"
    fix_attempted=1

    # Final Advice
    echo "--------------------------------------------------"
    echo "重要提示: 依赖项 '$missing_pkg' 缺失的最常见原因是它没有在配置中启用。"
    echo "如果此重试仍然失败，请运行 'make menuconfig' 并确保选中了 '$missing_pkg' 及其所有依赖项。"
    echo "--------------------------------------------------"

    return 0 # Return success as fixes were attempted, let the main loop retry
}

# --- Main Compilation Loop ---
retry_count=0
last_fix_applied=""
fix_applied_this_iteration=0
# Flags for batman-adv specific fixes
batman_br_ip_patched=0
batman_tasklet_patched=0
batman_feed_switched=0 # Use only feed switch flag now
# Flag to track if metadata fix was applied in the *last* iteration
metadata_fix_applied_last_iter=0

while [ $retry_count -lt "$MAX_RETRY" ]; do
    echo "--------------------------------------------------"
    echo "尝试编译: $MAKE_COMMAND (第 $((retry_count + 1)) / $MAX_RETRY 次)..."
    echo "--------------------------------------------------"

    # Reset iteration flag
    fix_applied_this_iteration=0

    # Before compiling, if metadata was fixed last time, force feed update/install
    if [ $metadata_fix_applied_last_iter -eq 1 ]; then
        echo "元数据或依赖项已在上一次迭代中修复，正在强制更新/安装 feeds..."
        ./scripts/feeds update -a || echo "警告: feeds 更新失败，继续编译..."
        ./scripts/feeds install -a || echo "警告: feeds 安装失败，继续编译..."
        metadata_fix_applied_last_iter=0 # Reset flag
    fi


    # Run the command, redirect stderr to stdout, and tee to log file and stdout
    # This allows seeing output in real-time and capturing it
    eval "$MAKE_COMMAND" 2>&1 | tee "$LOG_FILE"
    # Get exit status from PIPESTATUS (bash specific)
    # COMPILE_STATUS=${PIPESTATUS[0]}
    # A more portable way (though less direct): Check the log file for Make failure markers
    # Check for common make error patterns AND the exit code of the eval command itself
    # eval might exit 0 if the pipe succeeds, even if make failed. Need to check log.
    eval "$MAKE_COMMAND" > "$LOG_FILE" 2>&1
    COMPILE_STATUS=$? # Get the exit status of the eval command itself

    if [ $COMPILE_STATUS -eq 0 ] && ! grep -q -E "^make\[[0-9]+\]: \*\*\* .* Error [0-9]+|^make: \*\*\* .* Error [0-9]+" "$LOG_FILE"; then
        # Double check log for errors even if exit status is 0 (can happen with complex builds)
        if ! grep -q 'Collected errors:' "$LOG_FILE" && ! grep -q 'ERROR: package.* failed to build' "$LOG_FILE" ; then
             echo "编译成功！"
             exit 0
        else
             echo "警告: 命令退出码为 0，但在日志中检测到错误标记，继续检查..."
             COMPILE_STATUS=1 # Force error checking
        fi
    fi


    echo "编译失败 (退出码: $COMPILE_STATUS 或在日志中检测到错误)，检查错误..."
    extract_error_block "$LOG_FILE"

    # --- Error Detection and Fix Logic (Order Matters) ---

    # 1. Batman-adv C compile error due to -Werror
    if grep -q "cc1: some warnings being treated as errors" "$LOG_FILE" && grep -q -E "struct br_ip.*has no member named|batman-adv.*(multicast\.c|multicast\.o)" "$LOG_FILE"; then
        echo "检测到 batman-adv struct 错误和 -Werror 同时存在..."

        # Step 1: Try the specific patch first
        if [ "$batman_br_ip_patched" -eq 0 ]; then
            echo "尝试修补 multicast.c..."
            last_fix_applied="fix_batman_br_ip_dst_werror"
            if fix_batman_br_ip_dst "$LOG_FILE"; then
                fix_applied_this_iteration=1
                batman_br_ip_patched=1 # Mark as patched
            else
                echo "修补 multicast.c 失败。将尝试切换 feed。"
                 batman_br_ip_patched=1 # Mark patch as attempted even if failed
            fi
        fi

        # Step 2: If patch failed or error persists, try switching feed
        if [ $fix_applied_this_iteration -eq 0 ] && [ "$batman_feed_switched" -eq 0 ]; then
            echo "尝试切换整个 routing feed 到已知良好 commit..."
            last_fix_applied="fix_batman_switch_feed_werror"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
                batman_feed_switched=1 # Mark feed as switched
            else
                echo "切换 routing feed 失败。下次将尝试禁用 Werror。"
                batman_feed_switched=1 # Mark as attempted even if failed
            fi
        fi

        # Step 3: If feed switch failed or error persists, try disabling Werror locally
         if [ $fix_applied_this_iteration -eq 0 ]; then
              echo "修补和切换 Feed 后错误仍然存在，尝试在包 Makefile 中禁用 -Werror..."
              last_fix_applied="fix_batman_disable_werror"
              if fix_batman_disable_werror; then
                  fix_applied_this_iteration=1
              else
                  echo "无法在 Makefile 中禁用 -Werror。放弃修复 batman-adv。"
                  cat "$LOG_FILE"
                  exit 1
              fi
         fi

    # 2. Batman-adv 'struct br_ip' dst error (WITHOUT -Werror message, less likely now)
    elif grep -q "struct br_ip.*has no member named" "$LOG_FILE" && grep -q -E "(batman-adv|net/batman-adv).*multicast\.c" "$LOG_FILE"; then
        echo "检测到 batman-adv struct member 错误 (无 -Werror)..."
        # Try patch first
        if [ "$batman_br_ip_patched" -eq 0 ]; then
            last_fix_applied="fix_batman_br_ip_dst_no_werror"
            if fix_batman_br_ip_dst "$LOG_FILE"; then
                fix_applied_this_iteration=1
                batman_br_ip_patched=1
            else
                echo "修补 multicast.c 失败。将尝试切换 feed。"
                 batman_br_ip_patched=1
            fi
        fi
         # Then try switching feed
        if [ $fix_applied_this_iteration -eq 0 ] && [ "$batman_feed_switched" -eq 0 ]; then
             echo "尝试切换整个 routing feed..."
             last_fix_applied="fix_batman_switch_feed_br_ip"
             if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                 fix_applied_this_iteration=1
                 batman_feed_switched=1
             else
                 echo "切换 routing feed 失败。"
                 batman_feed_switched=1
             fi
        fi
         # Give up if both failed
         if [ $fix_applied_this_iteration -eq 0 ]; then
              echo "已尝试修补和切换 feed，但 struct 错误仍然存在，放弃。"
              cat "$LOG_FILE"
              exit 1
         fi

    # 3. Batman-adv tasklet_setup error (Keep existing logic, but prioritize feed switch)
    elif grep -q 'undefined reference to .*tasklet_setup' "$LOG_FILE" && grep -q -B 10 -A 10 -E 'Entering directory.*(batman-adv|backports|compat)' "$LOG_FILE"; then
        echo "检测到 batman-adv 的 'tasklet_setup' 符号错误..."
        # Try feed switch first for this error now
        if [ "$batman_feed_switched" -eq 0 ]; then
             echo "尝试切换整个 routing feed..."
             last_fix_applied="fix_batman_switch_feed_tasklet"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
                batman_feed_switched=1
            else
                echo "切换 routing feed 失败。将尝试修补 backports。"
                batman_feed_switched=1 # Mark as tried
            fi
        fi
        # If feed switch failed or already done, try patching backports
        if [ $fix_applied_this_iteration -eq 0 ] && [ "$batman_tasklet_patched" -eq 0 ]; then
            last_fix_applied="fix_batman_tasklet"
            if fix_batman_patch_tasklet "$LOG_FILE"; then
                fix_applied_this_iteration=1
                batman_tasklet_patched=1
            else
                echo "修复 batman-adv backports tasklet 失败，放弃。"
                cat "$LOG_FILE"
                exit 1
            fi
        fi
         # Give up if both failed
         if [ $fix_applied_this_iteration -eq 0 ]; then
              echo "已尝试切换 feed 和修补 backports，但 tasklet 错误仍然存在，放弃。"
              cat "$LOG_FILE"
              exit 1
         fi

    # 4. Trojan-plus buffer_cast error
    elif grep -q 'trojan-plus.*service.cpp.*buffer_cast.*boost::asio' "$LOG_FILE"; then
        echo "检测到 'trojan-plus boost::asio::buffer_cast' 错误..."
        if [ "$last_fix_applied" = "fix_trojan_plus" ]; then
            echo "上次已尝试修复 trojan-plus，但错误依旧，停止重试。"
            cat "$LOG_FILE"
            exit 1
        fi
        last_fix_applied="fix_trojan_plus"
        if fix_trojan_plus_boost_error; then
            fix_applied_this_iteration=1
        else
            echo "修复 trojan-plus 失败，停止重试。"
            cat "$LOG_FILE"
            exit 1
        fi

    # 5. po2lmo error
    elif grep -q "po2lmo: command not found" "$LOG_FILE"; then
        echo "检测到 'po2lmo' 错误..."
        if [ "$last_fix_applied" = "fix_po2lmo" ]; then
            echo "上次已尝试修复 po2lmo，但错误依旧，停止重试。"
             cat "$LOG_FILE"
            exit 1
        fi
        last_fix_applied="fix_po2lmo"
        if fix_po2lmo; then
            fix_applied_this_iteration=1
        else
            echo "修复 po2lmo 失败，停止重试。"
             cat "$LOG_FILE"
            exit 1
        fi

    # 6. Makefile separator error
    elif grep -q "missing separator.*Stop." "$LOG_FILE"; then
        echo "检测到 'missing separator' 错误..."
        if [ "$last_fix_applied" = "fix_makefile_separator" ]; then
             echo "上次已尝试修复 makefile separator，但错误依旧，停止重试。"
             cat "$LOG_FILE"
             exit 1
        fi
        last_fix_applied="fix_makefile_separator"
        if fix_makefile_separator "$LOG_FILE"; then
            fix_applied_this_iteration=1
            echo "Makefile separator 修复尝试完成，将重试编译。"
        else
            echo "无法定位或清理导致 'missing separator' 错误的 Makefile，停止重试。"
             cat "$LOG_FILE"
            exit 1
        fi

    # 7. Package metadata errors (Version, Dependency Format, Duplicates)
    elif grep -E -q "package version is invalid|dependency format is invalid|duplicate dependency detected|has a dependency on .* which does not exist" "$LOG_FILE"; then
        echo "检测到包元数据错误 (版本/依赖格式/重复/缺失)..."
        if [ "$last_fix_applied" = "fix_metadata" ]; then
            echo "上次已尝试修复元数据，但错误依旧，停止重试。"
             cat "$LOG_FILE"
            exit 1
        fi
        last_fix_applied="fix_metadata"
        changed=0
        # Run all metadata fixes
        fix_pkg_version && changed=1 && echo "PKG_VERSION/RELEASE 修复应用了更改。"
        fix_dependency_format && changed=1 && echo "依赖格式修复应用了更改。"
        fix_depends && changed=1 && echo "重复依赖修复应用了更改。"

        if [ $changed -eq 1 ]; then
            echo "应用了包元数据修复，将重试。"
            fix_applied_this_iteration=1
            metadata_fix_applied_last_iter=1 # Set flag to force feed update next iter
        else
            echo "检测到元数据错误，但修复函数未报告任何更改。"
            if grep -q "dependency on .* which does not exist" "$LOG_FILE"; then
                echo "警告: 检测到 'dependency ... which does not exist'。这通常需要手动检查 .config 或 feeds 是否正确/完整。"
                echo "将继续重试，但可能失败。"
                fix_applied_this_iteration=1 # Allow retry loop
            else
                echo "未应用元数据修复，停止重试。"
                cat "$LOG_FILE"
                exit 1
            fi
        fi

    # 8. Filesystem conflicts (mkdir, ln)
    elif grep -q "mkdir: cannot create directory.*File exists" "$LOG_FILE"; then
        echo "检测到 'mkdir File exists' 错误..."
        if [ "$last_fix_applied" = "fix_mkdir" ]; then
            echo "上次已尝试修复 mkdir 冲突，但错误依旧，停止重试。"
             cat "$LOG_FILE"
            exit 1
        fi
        last_fix_applied="fix_mkdir"
        if fix_mkdir_conflict "$LOG_FILE"; then
            fix_applied_this_iteration=1
        else
            echo "修复 mkdir 冲突失败，可能无法继续。"
             cat "$LOG_FILE"
            exit 1
        fi
    elif grep -q "ln: failed to create symbolic link.*File exists" "$LOG_FILE"; then
        echo "检测到 'ln File exists' 错误..."
        if [ "$last_fix_applied" = "fix_symlink" ]; then
            echo "上次已尝试修复符号链接冲突，但错误依旧，停止重试。"
             cat "$LOG_FILE"
            exit 1
        fi
        last_fix_applied="fix_symlink"
        if fix_symbolic_link_conflict "$LOG_FILE"; then
            fix_applied_this_iteration=1
        else
            echo "修复符号链接冲突失败，可能无法继续。"
             cat "$LOG_FILE"
            exit 1
        fi

    # 9. Missing dependency during packaging/install stage (NEW)
    elif grep -q -E '(cannot find dependency|Cannot satisfy.+dependencies for)' "$LOG_FILE" && grep -q 'pkg_hash_check_unresolved\|opkg_install_cmd\|satisfy_dependencies_for' "$LOG_FILE"; then
        echo "检测到打包/安装阶段缺少依赖项错误..."
        if [ "$last_fix_applied" = "fix_missing_dependency" ]; then
            echo "上次已尝试修复缺失的依赖项，但错误依旧。请检查 .config。"
             cat "$LOG_FILE"
             exit 1
        fi
        last_fix_applied="fix_missing_dependency"
        if fix_missing_dependency "$LOG_FILE"; then
            fix_applied_this_iteration=1
            metadata_fix_applied_last_iter=1 # Force feed update next time as well
        else
            echo "修复缺失依赖项的尝试失败。请检查 .config。"
             cat "$LOG_FILE"
            exit 1
        fi

    # 10. Batman-adv Last Resort: Feed Switching (if other batman fixes failed and error persists)
    # Reduced priority now that specific errors are handled first
    elif grep -q -i 'batman-adv' "$LOG_FILE" && [ $retry_count -ge 3 ]; then # Try later
        echo "检测到持续的 batman-adv 相关错误，尝试切换 feed (如果尚未进行)..."
        if [ "$batman_feed_switched" -eq 0 ]; then
            echo "尝试切换整个 routing feed 到已知良好 commit..."
            last_fix_applied="fix_batman_switch_feed_fallback"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
                batman_feed_switched=1
            else
                echo "切换 routing feed 失败，无法修复 batman-adv。"
                cat "$LOG_FILE"
                exit 1
            fi
        else
            echo "已尝试切换 batman-adv feed，但错误仍然存在，放弃。"
            cat "$LOG_FILE"
            exit 1
        fi

    # 11. Generic error pattern check (as a fallback)
    elif grep -E -q "$ERROR_PATTERN" "$LOG_FILE"; then
        local matched_pattern
        matched_pattern=$(grep -E -m 1 "$ERROR_PATTERN" "$LOG_FILE")
        echo "检测到通用错误模式 ($ERROR_PATTERN): $matched_pattern"
        if [ "$last_fix_applied" = "fix_generic" ]; then
            echo "上次已尝试通用修复 (元数据检查)，但错误依旧，停止重试。"
            cat "$LOG_FILE"
            exit 1
        fi
        echo "尝试通用修复 (运行元数据检查)..."
        last_fix_applied="fix_generic"
        changed=0
        # Run metadata fixes as the generic fallback
        fix_pkg_version && changed=1 && echo "PKG_VERSION/RELEASE 修复应用了更改。"
        fix_dependency_format && changed=1 && echo "依赖格式修复应用了更改。"
        fix_depends && changed=1 && echo "重复依赖修复应用了更改。"

        if [ $changed -eq 1 ]; then
            echo "应用了通用修复 (元数据)，将重试。"
            fix_applied_this_iteration=1
            metadata_fix_applied_last_iter=1 # Force feed update next time
        else
            echo "检测到通用错误，但通用修复 (元数据检查) 未应用更改。"
             if [ $retry_count -lt $((MAX_RETRY - 1)) ]; then
                 echo "将再重试一次编译，即使没有应用修复。"
             else
                 echo "通用错误无法通过元数据检查修复，且已接近重试次数上限，停止。"
                 cat "$LOG_FILE"
                 exit 1
             fi
        fi
    else
        # If no specific or generic error pattern matched, but compile failed
        echo "未检测到已知或通用的错误模式，但编译失败 (退出码: $COMPILE_STATUS)。"
        echo "请检查完整日志: $LOG_FILE"
        cat "$LOG_FILE" # Show log before exiting
        exit 1
    fi

    # --- Loop Control ---
    if [ $fix_applied_this_iteration -eq 0 ] && [ $COMPILE_STATUS -ne 0 ]; then
        # Allow loop to continue if a suggestion was made (e.g., manual Werror fix)
         if [[ "$last_fix_applied" != *"_manual_suggest"* ]] && [[ "$last_fix_applied" != "fix_generic" && $changed -eq 0 ]]; then
             echo "警告：检测到错误，但此轮未应用有效修复或修复无效果。上次尝试: ${last_fix_applied:-无}"
             if [ $retry_count -ge $((MAX_RETRY - 1)) ]; then
                 echo "停止重试，因为未应用有效修复且已达重试上限。"
                 cat "$LOG_FILE"
                 exit 1
            else
                 echo "再重试一次，检查是否有其他可修复的错误出现。"
             fi
        fi
    fi

    retry_count=$((retry_count + 1))
    echo "等待 3 秒后重试..."
    sleep 3
done

# --- Final Failure ---
echo "--------------------------------------------------"
echo "达到最大重试次数 ($MAX_RETRY)，编译最终失败。"
echo "--------------------------------------------------"
extract_error_block "$LOG_FILE"
echo "请检查完整日志: $LOG_FILE"
exit 1
