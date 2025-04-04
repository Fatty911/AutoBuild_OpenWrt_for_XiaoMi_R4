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

# --- Helper Function: Get Relative Path ---
# Converts absolute paths from common CI environments to relative paths
get_relative_path() {
    local path="$1"
    local workdir_pattern="/home/runner/work/[^/]*/[^/]*/openwrt/"
    local github_pattern="/github/workspace/openwrt/"
    local mnt_pattern="/mnt/openwrt/" # Add other potential base paths if needed

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
        echo "警告: 未知的基础路径，返回原始绝对路径: $path" >&2
        echo "$path"
    fi
}


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
    # Use different delimiters for sed to avoid conflict with path slashes
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
        # Skip Makefiles that don't include the standard package definitions
        if ! head -n 20 "$makefile" 2>/dev/null | grep -qE '^\s*(include \.\./\.\./(package|buildinfo)\.mk|include \$\(INCLUDE_DIR\)/package\.mk)'; then
            continue
        fi

        local current_version release new_version new_release suffix modified_in_loop=0 makefile_changed=0
        current_version=$(sed -n 's/^PKG_VERSION:=\(.*\)/\1/p' "$makefile")
        release=$(sed -n 's/^PKG_RELEASE:=\(.*\)/\1/p' "$makefile")

        # Case 1: Version string contains a hyphenated suffix (e.g., 1.2.3-beta1)
        if [[ "$current_version" =~ ^([0-9]+(\.[0-9]+)*)-([a-zA-Z0-9_.-]+)$ ]]; then
            new_version="${BASH_REMATCH[1]}"
            suffix="${BASH_REMATCH[3]}"
            # Try to extract numbers from suffix for release, default to 1
            new_release=$(echo "$suffix" | tr -cd '0-9' | grep -o '[0-9]\+' || echo "1")

            # Only modify if version or release actually changes
            if [ "$current_version" != "$new_version" ] || [ "$release" != "$new_release" ]; then
                 echo "修改 $makefile: PKG_VERSION: '$current_version' -> '$new_version', PKG_RELEASE: '$release' -> '$new_release'"
                 cp "$makefile" "$makefile.tmp" # Backup before modification
                 sed -e "s/^PKG_VERSION:=.*/PKG_VERSION:=$new_version/" "$makefile.tmp" > "$makefile.tmp2"
                 # Check if PKG_RELEASE exists and update it, otherwise add it after PKG_VERSION
                 if grep -q "^PKG_RELEASE:=" "$makefile.tmp2"; then
                     sed -e "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile.tmp2" > "$makefile"
                 else
                     # Add PKG_RELEASE after PKG_VERSION
                     awk -v ver="$new_version" -v rel="$new_release" '
                        /^PKG_VERSION:=/ { print "PKG_VERSION:=" ver; print "PKG_RELEASE:=" rel; next }
                        { print }
                     ' "$makefile.tmp2" > "$makefile"
                 fi
                 rm "$makefile.tmp" "$makefile.tmp2" # Clean up temp files
                 release=$new_release # Update release variable for subsequent checks
                 modified_in_loop=1
                 makefile_changed=1
            fi
        fi

        # Case 2: PKG_RELEASE exists but is not a simple number
        if [ "$modified_in_loop" -eq 0 ] && [ -n "$release" ] && ! [[ "$release" =~ ^[0-9]+$ ]]; then
            # Try to extract numbers from the existing release, default to 1
            new_release=$(echo "$release" | tr -cd '0-9' | grep -o '[0-9]\+' || echo "1")
            if [ "$release" != "$new_release" ]; then
                echo "修正 $makefile: PKG_RELEASE: '$release' -> '$new_release'"
                sed -i.bak "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile" && rm "$makefile.bak" # Apply change and remove backup on success
                makefile_changed=1
            fi
        # Case 3: PKG_RELEASE is missing entirely
        elif [ -z "$release" ] && grep -q "^PKG_VERSION:=" "$makefile" && ! grep -q "^PKG_RELEASE:=" "$makefile"; then
             echo "添加 $makefile: PKG_RELEASE:=1"
             sed -i.bak "/^PKG_VERSION:=.*/a PKG_RELEASE:=1" "$makefile" && rm "$makefile.bak" # Add PKG_RELEASE=1 after PKG_VERSION and remove backup on success
             makefile_changed=1
        fi

        if [ "$makefile_changed" -eq 1 ]; then
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

            # Skip non-Makefile files more reliably
            if ! head -n 30 "$makefile" 2>/dev/null | grep -qE "^\s*include.*\/(package|buildinfo|kernel)\.mk"; then
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
                if (index(line, "#") > 0) {
                    dep_part = substr(line, 1, index(line, "#") - 1)
                }

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
                if (index(line, "#") > 0) {
                    new_line = new_line " " substr(line, index(line, "#"))
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

            # Check awk exit status and if files differ
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
                 # AWK exited with 1, meaning no changes were needed according to the script
                 rm -f "$makefile.tmp"
            else
                 # AWK exited with > 1, indicating an error within AWK
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


### Fix dependency format
fix_dependency_format() {
    echo "尝试修复 Makefile 中的依赖格式..."
    local flag_file=".fix_depformat_changed"
    rm -f "$flag_file"
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -path "./build_dir/*" -prune -o -path "./staging_dir/*" -prune -o -exec sh -c '
        makefile="$1"
        flag_file_path="$2"
        # Skip non-Makefile files more reliably
        if ! head -n 30 "$makefile" 2>/dev/null | grep -qE "^\s*include.*\/(package|buildinfo|kernel)\.mk"; then
             exit 0
        fi
        cp "$makefile" "$makefile.bak"
        awk '\''BEGIN { FS="[[:space:]]+"; OFS=" "; changed_file=0 }
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
                    # Remove spaces after + sign, e.g. "+ lib C" -> "+libC" (though spaces usually separate deps)
                    # This might be too aggressive, let's focus on the version suffix for now.
                    # gsub(/^\+[[:space:]]+/, "+", dep) # Be careful with this

                    # Check if modification happened
                    if (original_dep != dep) { line_changed=1 }

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
        '\'' "$makefile" > "$makefile.tmp"
        awk_status=$?

        if [ $awk_status -eq 0 ]; then # Changes were made by awk
           if [ -s "$makefile.tmp" ] && ! cmp -s "$makefile" "$makefile.tmp"; then
                echo "修改 $makefile: 调整依赖格式"
                mv "$makefile.tmp" "$makefile"
                rm "$makefile.bak"
                touch "$flag_file_path"
           else
                # Awk reported changes (exit 0), but files are same or tmp is empty? Unexpected.
                echo "警告: awk声称修改了 $makefile 但文件未变或为空。" >&2
                rm "$makefile.tmp"
                mv "$makefile.bak" "$makefile" # Restore original
           fi
        elif [ $awk_status -eq 1 ]; then # Awk reported no changes needed
             rm "$makefile.tmp"
             mv "$makefile.bak" "$makefile" # Restore original (no .bak needed)
        else # Awk script itself had an error
             echo "警告: awk 处理 $makefile 时出错 (退出码: $awk_status)，已从备份恢复。" >&2
             rm "$makefile.tmp"
             mv "$makefile.bak" "$makefile" # Restore original
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
    local FAILED_PATH PKG_ERROR_LINE PKG_PATH PKG_NAME PKG_DIR

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
             # Don't necessarily exit, maybe cleaning the package will help
             # return 1
        fi
    else
        echo "警告：冲突路径 $FAILED_PATH 已不存在。"
    fi

    # Try to identify the package causing the error more reliably
    # Look for "make[N]: *** [path/to/.built] Error X" or "ERROR: package/... failed to build" lines near the mkdir error
    PKG_ERROR_LINE=$(tac "$log_file" | grep -m 1 -B 50 "mkdir: cannot create directory '$FAILED_PATH'" | grep -m 1 -Eo '(ERROR: (package|feeds)/[^ ]+ failed to build\.|make\[[0-9]+\]: \*\*\* \[(.*)/\.built\] Error)')
    PKG_PATH=""
    PKG_DIR_REL=""

    if [[ -n "$PKG_ERROR_LINE" ]]; then
        if [[ "$PKG_ERROR_LINE" == ERROR:* ]]; then
            # Format: ERROR: package/feeds/name/pkgname failed to build.
            PKG_PATH=$(echo "$PKG_ERROR_LINE" | sed 's/ERROR: \(.*\) failed to build\./\1/')
            # Ensure it's a valid relative path structure
            if [[ "$PKG_PATH" == package/* ]] || [[ "$PKG_PATH" == feeds/* ]]; then
                 if [ -d "$PKG_PATH" ]; then
                      PKG_DIR_REL="$PKG_PATH"
                 else
                      echo "警告: 从 'ERROR:' 行提取的路径 '$PKG_PATH' 不是一个有效目录。"
                      PKG_PATH="" # Invalidate if dir doesn't exist
                 fi
            else
                 PKG_PATH="" # Invalidate if structure is wrong
            fi
        else
            # Format: make[3]: *** [build_dir/.../pkg-1.0/.built] Error 1
             PKG_BUILD_DIR_PART=$(echo "$PKG_ERROR_LINE" | sed -n 's|make\[[0-9]\+\]: \*\*\* \[\(.*\)/\.built\] Error.*|\1|p')
             if [[ "$PKG_BUILD_DIR_PART" == *build_dir/* ]]; then
                  # Extract the likely package source directory relative path
                  # This relies on finding the corresponding source dir in package/ or feeds/
                  PKG_NAME_GUESS=$(basename "$PKG_BUILD_DIR_PART" | sed -e 's/-[0-9].*//' -e 's/_.*//') # Basic guess of package name
                  # Search for the guessed package directory
                  PKG_PATH_FOUND=$(find package feeds -name "$PKG_NAME_GUESS" -type d -print -quit)
                  if [[ -n "$PKG_PATH_FOUND" ]] && ( [[ "$PKG_PATH_FOUND" == ./package/* ]] || [[ "$PKG_PATH_FOUND" == ./feeds/* ]] ); then
                       PKG_DIR_REL="${PKG_PATH_FOUND#./}" # Make relative path clean
                       PKG_PATH="$PKG_DIR_REL" # Use this found path
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
        # Use DIRCLEAN=1 for a more thorough clean
        make "$PKG_DIR_REL/clean" DIRCLEAN=1 V=s || {
            echo "清理包 $PKG_NAME 失败，但已删除冲突路径，将继续尝试主编译命令。"
        }
        echo "已清理包 $PKG_NAME，将重试主编译命令。"
    else
        echo "无法从日志中明确推断出导致错误的包或推断的路径无效。仅删除了冲突路径。"
        # Optionally, could try cleaning the specific build_dir if PKG_BUILD_DIR_PART was found
        if [[ -n "$PKG_BUILD_DIR_PART" ]] && [ -d "$PKG_BUILD_DIR_PART" ]; then
             echo "尝试清理具体的 build_dir: $PKG_BUILD_DIR_PART"
             rm -rf "$PKG_BUILD_DIR_PART"
        fi
    fi
    # Return success because we attempted a fix (deleting the file/dir)
    return 0
}

### Fix symbolic link conflicts
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
             # Consider not exiting immediately
             # return 1
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
    # Return success as a fix was attempted
    return 0
}

### Fix Makefile "missing separator" error (REVISED)
fix_makefile_separator() {
    local log_file="$1"
    echo "检测到 'missing separator' 错误，尝试修复..."
    local error_block make_dir make_dir_rel makefile_info makefile_name line_num makefile_path_rel pkg_dir_rel fix_attempted=0

    # Extract the block around the error more reliably
    error_block=$(grep -B 2 -A 1 "missing separator.*Stop." "$log_file")

    # Extract the directory where make was running
    make_dir=$(echo "$error_block" | grep "Leaving directory" | sed -e "s/.*Leaving directory '\([^']*\)'/\1/")
    if [ -z "$make_dir" ]; then
         make_dir=$(echo "$error_block" | grep "make\[[0-9]*\]: Leaving directory" | sed -e "s/.*Leaving directory '\([^']*\)'/\1/")
    fi

    if [ -z "$make_dir" ]; then
        echo "错误: 无法从日志中提取 'Leaving directory' 信息。"
        return 1 # Cannot proceed without directory context
    fi
    echo "错误发生在目录: $make_dir"
    pkg_dir_rel=$(get_relative_path "$make_dir")
     if [ -z "$pkg_dir_rel" ] || [[ "$pkg_dir_rel" == /* ]]; then
         echo "错误: 无法将目录 '$make_dir' 转换为有效的相对路径。"
         return 1
     fi
     echo "相对包路径: $pkg_dir_rel"

    # Extract Makefile name and line number from the error line itself
    makefile_info=$(echo "$error_block" | grep "missing separator.*Stop." | head -n 1)
    makefile_name=$(echo "$makefile_info" | cut -d':' -f1)
    line_num=$(echo "$makefile_info" | cut -d':' -f2)

    if ! [[ "$line_num" =~ ^[0-9]+$ ]]; then
        echo "错误: 无法从错误行提取有效的行号: '$makefile_info'"
        line_num="" # Invalidate line number
    fi

    # Construct the full relative path to the Makefile
    # Handle cases where makefile_name might already contain part of the path
    if [[ "$makefile_name" == */* ]]; then
        # If makefile_name looks like 'subdir/Makefile', assume it's relative to pkg_dir_rel
        makefile_path_rel="$pkg_dir_rel/$makefile_name"
    else
        # Assume it's directly inside pkg_dir_rel
        makefile_path_rel="$pkg_dir_rel/$makefile_name"
    fi

    # Canonicalize the path (remove ../, ./)
    makefile_path_rel=$(realpath -m --relative-to=. "$makefile_path_rel")

    echo "推测错误的 Makefile: $makefile_path_rel, 行号: ${line_num:-未知}"

    # Attempt to fix the indentation with sed if we have a valid path and line number
    if [ -f "$makefile_path_rel" ] && [ -n "$line_num" ]; then
        echo "检查文件: $makefile_path_rel，第 $line_num 行..."
        # Check if the line actually starts with spaces (and not already a tab)
        line_content=$(sed -n "${line_num}p" "$makefile_path_rel")
        if [[ "$line_content" =~ ^[[:space:]]+ ]] && ! [[ "$line_content" =~ ^\t ]]; then
            echo "检测到第 $line_num 行可能使用空格缩进，尝试替换为 TAB..."
            cp "$makefile_path_rel" "$makefile_path_rel.bak"
            # Replace all leading whitespace with a single tab
            sed -i.sedfix "${line_num}s/^[[:space:]]\+/\t/" "$makefile_path_rel"
            # Verify the change (simple check: does the line now start with a tab?)
            new_line_content=$(sed -n "${line_num}p" "$makefile_path_rel")
            if [[ "$new_line_content" =~ ^\t ]]; then
                 echo "已尝试用 TAB 修复 $makefile_path_rel 第 $line_num 行的缩进。"
                 rm "$makefile_path_rel.bak" # Remove original backup
                 rm "$makefile_path_rel.sedfix" # Remove sed's backup
                 fix_attempted=1
                 return 0 # Success, retry compile
            else
                 echo "警告: 尝试用 sed 修复 $makefile_path_rel 失败，恢复备份文件。"
                 mv "$makefile_path_rel.bak" "$makefile_path_rel" # Restore backup
                 rm -f "$makefile_path_rel.sedfix"
            fi
        else
            echo "第 $line_num 行似乎没有前导空格或已经是 TAB 缩进，跳过 sed 修复。"
        fi
    else
         echo "Makefile 路径 '$makefile_path_rel' 无效或行号未知，无法尝试 sed 修复。"
    fi

    # If sed fix wasn't attempted or failed, fall back to cleaning the package directory
    if [ "$fix_attempted" -eq 0 ]; then
        if [ -d "$pkg_dir_rel" ]; then
            echo "尝试清理包目录: $pkg_dir_rel ..."
            make "$pkg_dir_rel/clean" V=s || {
                echo "警告: 清理 $pkg_dir_rel 失败，但这可能不是致命错误，将继续重试主命令。"
            }
            echo "已清理 $pkg_dir_rel，将重试主命令。"
            fix_attempted=1
            return 0 # Indicate fix attempt was made
        else
            echo "错误: 推断的包目录 '$pkg_dir_rel' 不存在，无法清理。"
            return 1 # Cannot clean, likely won't recover
        fi
    fi

    # Should not reach here if fix was attempted, but return 1 just in case
    return 1
}


### Fix batman-adv 'struct br_ip' dst error
fix_batman_br_ip_dst() {
    local log_file="$1"
    echo "尝试修复 batman-adv 的 'struct br_ip has no member named dst' 错误..."

    # Extract the multicast.c file path from the log
    local multicast_file
    # Make grep pattern more robust for different kernel/target variations
    multicast_file=$(grep -oE 'build_dir/target-[^/]+/linux-[^/]+/(linux-[^/]+|batman-adv-[^/]+)/net/batman-adv/multicast\.c' "$log_file" | head -n 1)

    if [ -z "$multicast_file" ] || [ ! -f "$multicast_file" ]; then
        echo "无法从日志中定位 multicast.c 文件，尝试动态查找..."
        # Broaden find command
        multicast_file=$(find build_dir -type f \( -path "*/batman-adv-*/net/batman-adv/multicast.c" -o -path "*/linux-*/net/batman-adv/multicast.c" \) -print -quit)
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
    # Also check for ipv4 variant if needed (less common issue, but possible)
    sed -i 's/br_ip_entry->addr\.dst\.ip4/br_ip_entry->u.ip4/g' "$multicast_file"

    # Check if *either* replacement was successful (or maybe already correct)
    if grep -q 'br_ip_entry->u\.ip6' "$multicast_file" || grep -q 'br_ip_entry->u\.ip4' "$multicast_file"; then
        # Check if the *problematic* pattern still exists
        if ! grep -q 'br_ip_entry->addr\.dst\.ip6' "$multicast_file" && ! grep -q 'br_ip_entry->addr\.dst\.ip4' "$multicast_file" ; then
            echo "已成功修补 $multicast_file，将重试编译。"
            rm "$multicast_file.bak"
            return 0
        else
             echo "警告: $multicast_file 中仍然存在 addr.dst 模式，修补可能不完整。"
             # Still return 0 to allow retry, maybe another fix is needed
             rm "$multicast_file.bak" # Assume patch did something useful
             return 0
        fi
    else
        echo "修补 $multicast_file 失败，未找到 'u.ip6' 或 'u.ip4'，恢复备份文件。"
        mv "$multicast_file.bak" "$multicast_file"
        return 1
    fi
}

### Fix batman-adv tasklet_setup symbol conflict
fix_batman_patch_tasklet() {
    local log_file="$1"
    echo "尝试修复 batman-adv 的 tasklet_setup 符号冲突..."
    local backports_header_path
    # Make grep pattern more robust
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
    # Check if tasklet_setup is actually defined there before removing
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

### Switch batman-adv package to specified commit
fix_batman_switch_package() {
    local target_commit="$1"
    local pkg_dir="feeds/routing/batman-adv"
    echo "尝试切换 $pkg_dir 包源码至 commit $target_commit ..."

    if [ ! -d "$pkg_dir" ]; then
        echo "错误: 目录 $pkg_dir 不存在。请确保 feeds 已更新且包含 routing feed。"
        # Try updating the specific feed first
        echo "尝试更新 routing feed..."
        ./scripts/feeds update routing || echo "警告: 更新 routing feed 失败。"
        ./scripts/feeds install batman-adv || echo "警告: 安装 batman-adv 失败。"
        if [ ! -d "$pkg_dir" ]; then
            echo "错误: 目录 $pkg_dir 仍然不存在，无法切换包。"
            return 1
        fi
        echo "$pkg_dir 现在存在了，继续切换。"
    fi

    if [ ! -d "$pkg_dir/.git" ]; then
        echo "错误: $pkg_dir 不是一个 git 仓库。可能需要先卸载并重新安装 feed/包。"
        echo "尝试卸载并重新安装 batman-adv..."
        ./scripts/feeds uninstall batman-adv > /dev/null 2>&1
        ./scripts/feeds install batman-adv || { echo "错误: 重新安装 batman-adv 失败。"; return 1; }
         if [ ! -d "$pkg_dir/.git" ]; then
             echo "错误: $pkg_dir 仍然不是 git 仓库，无法切换。"
             return 1
         fi
    fi

    (
        cd "$pkg_dir" || return 1
        echo "当前目录: $(pwd)"
        local current_commit
        current_commit=$(git rev-parse HEAD 2>/dev/null)
        if [[ "$current_commit" == "$target_commit"* ]]; then
            echo "已经是目标 commit $target_commit，无需切换。"
            return 0
        fi

        echo "保存当前状态..."
        git stash push -m "compile_with_retry_stash" > /dev/null 2>&1 || echo "警告: git stash 失败，可能存在未提交的更改。"

        echo "运行: git fetch origin --tags --force" # Force fetch tags too
        git fetch origin --tags --force || { echo "警告: git fetch 失败，继续尝试 checkout..."; }

        echo "运行: git checkout $target_commit"
        if git checkout "$target_commit"; then
            echo "成功 checkout commit $target_commit"
            # Clean up potentially conflicting build artifacts from previous version
            make -C ../../../ "$pkg_dir/clean" V=s DIRCLEAN=1 || echo "警告: 清理旧 batman-adv 构建文件失败。"
            return 0 # Success
        else
            echo "错误: 无法 checkout commit $target_commit"
            echo "恢复之前的状态..."
            git checkout "$current_commit" || git checkout - # Try to go back
            git stash pop > /dev/null 2>&1 || echo "警告: git stash pop 失败。"
            return 1 # Failure
        fi
    )
    local switch_status=$?
    if [ $switch_status -eq 0 ]; then
         echo "切换 $pkg_dir 完成。不需要单独更新/安装索引，因为包本身已修改。"
        # echo "更新 feed 索引并安装 batman-adv..." # Usually not needed after checkout
        # ./scripts/feeds update -i batman-adv || { echo "错误: feeds update -i batman-adv 失败"; return 1; }
        # ./scripts/feeds install -a -p routing || { echo "错误: feeds install -a -p routing 失败"; return 1; } # Install all from routing
    fi
    return $switch_status

}

### Switch entire routing feed to specified commit (More drastic)
fix_batman_switch_feed() {
    local target_commit="$1"
    local feed_name="routing"
    local feed_dir="feeds/$feed_name"
    local feed_repo_url="https://github.com/coolsnowwolf/routing.git" # Or adjust if using a different source

    echo "尝试切换整个 $feed_name feed 至 commit $target_commit ..."

    # Check if feed exists and is a git repo
    if [ -d "$feed_dir" ]; then
        if [ -d "$feed_dir/.git" ]; then
             (
                 cd "$feed_dir" || return 1
                 local current_commit
                 current_commit=$(git rev-parse HEAD 2>/dev/null)
                 local remote_url
                 remote_url=$(git config --get remote.origin.url)

                 # Check if it's already the correct repo and commit
                 if [[ "$remote_url" == "$feed_repo_url" ]] && [[ "$current_commit" == "$target_commit"* ]]; then
                     echo "$feed_name feed 已经是来自 $feed_repo_url 的 commit $target_commit，无需切换。"
                     # Ensure batman-adv is installed from this feed
                     ./scripts/feeds install -a -p "$feed_name" > /dev/null 2>&1 || echo "警告: 安装来自 $feed_name 的包失败。"
                     return 0
                 fi
                 echo "$feed_name feed 存在，但不是目标 commit 或 repo。将重新克隆。"
             )
        else
            echo "$feed_dir 存在但不是 git 仓库。将删除并重新克隆。"
        fi
         echo "删除旧的 $feed_dir ..."
         rm -rf "$feed_dir"
    fi

    # Update feeds.conf.default if needed (optional, depends on setup)
    # sed -i "/src-git $feed_name /d" feeds.conf.default
    # echo "src-git $feed_name $feed_repo_url;$target_commit" >> feeds.conf.default

    echo "克隆 $feed_repo_url 到 $feed_dir ..."
    if ! git clone --depth 1 --branch "$target_commit" "$feed_repo_url" "$feed_dir"; then
        echo "警告: 使用 branch 克隆 commit $target_commit 失败，尝试完整克隆后 checkout..."
        if ! git clone "$feed_repo_url" "$feed_dir"; then
            echo "错误: 克隆 $feed_repo_url 失败。"
            return 1
        fi
        (
            cd "$feed_dir" || return 1
            echo "切换到 commit $target_commit ..."
            if ! git checkout "$target_commit"; then
                echo "错误: 无法 checkout commit $target_commit"
                return 1
            fi
        ) || return 1
    fi
    echo "成功获取 commit $target_commit 的 $feed_name feed。"

    echo "更新 $feed_name feed 索引并安装其所有包..."
    # Use -a to install all packages from the feed
    ./scripts/feeds update "$feed_name" || { echo "错误: feeds update $feed_name 失败"; return 1; }
    ./scripts/feeds install -a -p "$feed_name" || { echo "错误: feeds install -a -p $feed_name 失败"; return 1; }

    echo "切换 $feed_name feed 完成。"
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
        echo "元数据或依赖项已在上一次迭代中修复，正在强制更新 feeds..."
        ./scripts/feeds update -a || echo "警告: feeds 更新失败，继续编译..."
        ./scripts/feeds install -a || echo "警告: feeds 安装失败，继续编译..."
        metadata_fix_applied_last_iter=0 # Reset flag
    fi


    eval "$MAKE_COMMAND" > "$LOG_FILE" 2>&1
    COMPILE_STATUS=$?

    if [ $COMPILE_STATUS -eq 0 ]; then
        echo "编译成功！"
        exit 0
    fi

    echo "编译失败 (退出码: $COMPILE_STATUS)，检查错误..."
    extract_error_block "$LOG_FILE"

    # --- Error Detection and Fix Logic (Order Matters) ---

    # 1. Batman-adv 'struct br_ip' dst error (or similar struct member errors)
    # Broaden the pattern slightly
    if grep -q "struct br_ip.*has no member named" "$LOG_FILE" && grep -q -E "(batman-adv|net/batman-adv).*multicast\.c" "$LOG_FILE"; then
        echo "检测到 batman-adv struct member 错误 (可能是 br_ip->dst)..."
        # Prioritize patching if not done yet
        if [ "$batman_br_ip_patched" -eq 0 ]; then
            last_fix_applied="fix_batman_br_ip_dst"
            if fix_batman_br_ip_dst "$LOG_FILE"; then
                fix_applied_this_iteration=1
                batman_br_ip_patched=1 # Mark as patched
            else
                echo "修补 batman-adv br_ip dst 失败。将尝试切换 commit。"
                # Fall through to commit switching logic
            fi
        fi
         # If patching didn't work or was already done, try switching commit/feed
        if [ $fix_applied_this_iteration -eq 0 ]; then
             if [ "$batman_package_switched" -eq 0 ]; then
                echo "尝试切换 batman-adv 包..."
                last_fix_applied="fix_batman_switch_pkg"
                if fix_batman_switch_package "$BATMAN_ADV_COMMIT"; then
                    fix_applied_this_iteration=1
                    batman_package_switched=1
                else
                    echo "切换 batman-adv 包失败，下次将尝试切换整个 feed。"
                    # Mark as tried even if failed, to proceed to feed switch next time
                    batman_package_switched=1
                fi
             elif [ "$batman_feed_switched" -eq 0 ]; then
                 echo "切换包后仍失败或跳过，尝试切换整个 routing feed..."
                 last_fix_applied="fix_batman_switch_feed"
                 if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                     fix_applied_this_iteration=1
                     batman_feed_switched=1
                 else
                     echo "切换 routing feed 失败，无法自动修复 batman-adv。"
                     exit 1 # Give up if feed switch fails
                 fi
             else
                echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                exit 1
             fi
        fi

    # 2. Batman-adv tasklet_setup error
    elif grep -q 'undefined reference to .*tasklet_setup' "$LOG_FILE" && grep -q -B 10 -A 10 -E 'Entering directory.*(batman-adv|backports|compat)' "$LOG_FILE"; then
        echo "检测到 batman-adv 的 'tasklet_setup' 符号错误..."
        # Prioritize patching
        if [ "$batman_tasklet_patched" -eq 0 ]; then
            last_fix_applied="fix_batman_tasklet"
            if fix_batman_patch_tasklet "$LOG_FILE"; then
                fix_applied_this_iteration=1
                batman_tasklet_patched=1
            else
                echo "修复 batman-adv tasklet 失败。将尝试切换 commit。"
                # Fall through
            fi
        fi
        # If patching failed or already done, switch commit/feed
        if [ $fix_applied_this_iteration -eq 0 ]; then
            if [ "$batman_package_switched" -eq 0 ]; then
                echo "尝试切换 batman-adv 包..."
                last_fix_applied="fix_batman_switch_pkg"
                if fix_batman_switch_package "$BATMAN_ADV_COMMIT"; then
                    fix_applied_this_iteration=1
                    batman_package_switched=1
                else
                    echo "切换 batman-adv 包失败，下次将尝试切换整个 feed。"
                    batman_package_switched=1 # Mark as tried
                fi
            elif [ "$batman_feed_switched" -eq 0 ]; then
                 echo "切换包后仍失败或跳过，尝试切换整个 routing feed..."
                 last_fix_applied="fix_batman_switch_feed"
                 if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                     fix_applied_this_iteration=1
                     batman_feed_switched=1
                 else
                     echo "切换 routing feed 失败，无法自动修复 batman-adv。"
                     exit 1
                 fi
            else
                echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
                exit 1
            fi
        fi

    # 3. Trojan-plus buffer_cast error
    elif grep -q 'trojan-plus.*service.cpp.*buffer_cast.*boost::asio' "$LOG_FILE"; then
        echo "检测到 'trojan-plus boost::asio::buffer_cast' 错误..."
        if [ "$last_fix_applied" = "fix_trojan_plus" ]; then
            echo "上次已尝试修复 trojan-plus，但错误依旧，停止重试。"
            cat "$LOG_FILE" # Show log before exiting
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

    # 4. po2lmo error
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

    # 5. Makefile separator error (using revised function)
    elif grep -q "missing separator.*Stop." "$LOG_FILE"; then
        echo "检测到 'missing separator' 错误..."
        # Avoid loop if the same fix failed last time
        if [ "$last_fix_applied" = "fix_makefile_separator" ]; then
             echo "上次已尝试修复 makefile separator，但错误依旧，可能是无法自动修复的语法错误或清理无效。停止重试。"
             cat "$LOG_FILE"
             exit 1
        fi
        last_fix_applied="fix_makefile_separator"
        if fix_makefile_separator "$LOG_FILE"; then
            # fix_makefile_separator returns 0 if it attempted *any* fix (sed or clean)
            fix_applied_this_iteration=1
            echo "Makefile separator 修复尝试完成，将重试编译。"
        else
            # fix_makefile_separator returns 1 if it couldn't even determine path/dir to fix/clean
            echo "无法定位或清理导致 'missing separator' 错误的 Makefile，停止重试。"
             cat "$LOG_FILE"
            exit 1
        fi

    # 6. Package metadata errors (Version, Dependency Format, Duplicates)
    # Consolidate these checks
    elif grep -E -q "package version is invalid|dependency format is invalid|duplicate dependency detected|has a dependency on .* which does not exist" "$LOG_FILE"; then
        echo "检测到包元数据错误 (版本/依赖格式/重复/缺失)..."
        # Avoid immediate re-run if the last fix was also metadata
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
            echo "检测到元数据错误，但修复函数未报告任何更改。可能是未知格式或无法修复的依赖问题。"
            # Don't exit immediately, maybe another error type will be caught later or retrying helps
            # Check for the specific "does not exist" warning, as it might need manual intervention
            if grep -q "dependency on .* which does not exist" "$LOG_FILE"; then
                echo "警告: 检测到 'dependency ... which does not exist'。这通常需要手动检查 .config 或 feeds 是否正确/完整。"
                echo "将继续重试，但可能失败。"
                # Still mark as fix applied to allow retry loop to continue for other potential issues
                fix_applied_this_iteration=1
            else
                echo "未应用元数据修复，停止重试。"
                cat "$LOG_FILE"
                exit 1
            fi
        fi

    # 7. Filesystem conflicts (mkdir, ln) - Placed after metadata fixes
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

    # 8. Batman-adv Last Resort: Commit Switching (if other batman fixes failed and error persists)
    # Trigger this later in the retry cycle if batman errors are still showing up
    elif grep -q -i 'batman-adv' "$LOG_FILE" && [ $retry_count -ge 2 ]; then # Start trying commit switch earlier if needed
        echo "检测到持续的 batman-adv 相关错误，尝试切换 commit/feed (如果尚未进行)..."
        if [ "$batman_package_switched" -eq 0 ]; then
            echo "尝试切换 batman-adv 包..."
            last_fix_applied="fix_batman_switch_pkg"
            if fix_batman_switch_package "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
                batman_package_switched=1
            else
                echo "切换 batman-adv 包失败，下次将尝试切换整个 feed。"
                batman_package_switched=1 # Mark as tried
            fi
        elif [ "$batman_feed_switched" -eq 0 ]; then
            echo "切换包后仍失败或跳过，尝试切换整个 routing feed..."
            last_fix_applied="fix_batman_switch_feed"
            if fix_batman_switch_feed "$BATMAN_ADV_COMMIT"; then
                fix_applied_this_iteration=1
                batman_feed_switched=1
            else
                echo "切换 routing feed 失败，无法修复 batman-adv。"
                cat "$LOG_FILE"
                exit 1
            fi
        else
            echo "已尝试切换 batman-adv 包和 feed，但错误仍然存在，放弃。"
            cat "$LOG_FILE"
            exit 1
        fi

    # 9. Generic error pattern check (as a fallback)
    elif grep -E -q "$ERROR_PATTERN" "$LOG_FILE"; then
        local matched_pattern
        matched_pattern=$(grep -E -m 1 "$ERROR_PATTERN" "$LOG_FILE")
        echo "检测到通用错误模式 ($ERROR_PATTERN): $matched_pattern"
        # Avoid loop if generic fix applied last time and failed
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
            echo "应用了通用修复，将重试。"
            fix_applied_this_iteration=1
            metadata_fix_applied_last_iter=1 # Force feed update next time
        else
            echo "检测到通用错误，但通用修复 (元数据检查) 未应用更改。"
            # Decide whether to exit or retry one more time without a fix
             if [ $retry_count -lt $((MAX_RETRY - 1)) ]; then
                 echo "将再重试一次编译，即使没有应用修复。"
                 # Don't set fix_applied_this_iteration=1 here if nothing changed
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
        exit 1
    fi

    # --- Loop Control ---
    if [ $fix_applied_this_iteration -eq 0 ] && [ $COMPILE_STATUS -ne 0 ]; then
        # Allow loop to continue if the last applied fix was generic and didn't change anything (see logic in #9)
        if [ "$last_fix_applied" != "fix_generic" ] || [ $changed -eq 1 ]; then
             echo "警告：检测到错误，但此轮未应用有效修复或修复无效果。上次修复: ${last_fix_applied:-无}"
             # Give it one last chance if a batman switch was just attempted
             if [[ "$last_fix_applied" != fix_batman_switch* ]] || [ $retry_count -ge $((MAX_RETRY - 1)) ]; then
                 echo "停止重试，因为未应用有效修复。"
                 cat "$LOG_FILE"
                 exit 1
            else
                 echo "上次尝试了 batman commit/feed 切换，再重试一次。"
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
