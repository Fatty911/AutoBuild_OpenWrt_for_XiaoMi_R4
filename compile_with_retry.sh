#!/bin/bash

# compile_with_retry.sh
# 用于修复 OpenWrt 编译中的常见错误
# 用法: bash compile_with_retry.sh <make_command> <log_file> [max_retry] [error_pattern]

# --- 参数解析 ---
MAKE_COMMAND="$1"           # 例如 "make -j1 V=s" 或 "make package/feeds/luci/luci-base/compile V=s"
LOG_FILE="$2"               # 例如 "compile.log" 或 "packages.log"
MAX_RETRY="${3:-8}"         # 默认最大重试次数: 8
ERROR_PATTERN="${4:-cc1: some warnings being treated as errors|error:|failed|undefined reference|invalid|File exists|missing separator|cannot find dependency|No rule to make target}"

# --- 参数检查 ---
if [ -z "$MAKE_COMMAND" ] || [ -z "$LOG_FILE" ]; then
    echo "错误：缺少必要参数。用法: $0 <make_command> <log_file> [max_retry] [error_pattern]"
    exit 1
fi

# --- 辅助函数: 获取相对路径 ---
get_relative_path() {
    local path="$1"
    local current_pwd
    current_pwd=$(pwd)

    if [[ "$path" != /* ]]; then
        if [ -e "$current_pwd/$path" ]; then
            path="$current_pwd/$path"
        else
            echo "$path"
            return
        fi
    fi
    realpath --relative-to="$current_pwd" "$path" 2>/dev/null || echo "$path"
}

# --- 修复函数: Makefile "missing separator" 错误 ---
fix_makefile_separator() {
    local log_file="$1"
    echo "检测到 'missing separator' 错误，尝试修复..."
    local error_line_info makefile_name_from_err line_num context_dir full_makefile_path makefile_path_rel fix_attempted=0 line_content tab pkg_dir subfile

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
    context_dir=$(tac "$log_file" | grep -A 50 -m 1 "$error_line_info" | grep -m 1 -E "^make$$[0-9]+$$: Entering directory '([^']+)'" | sed -n "s/.*Entering directory '$[^']*$'/\1/p")
    if [ -n "$context_dir" ]; then
        echo "找到上下文目录: $context_dir"
        full_makefile_path="$context_dir/$makefile_name_from_err"
    else
        if grep -q "package/libs/toolchain" "$log_file"; then
            full_makefile_path="package/libs/toolchain/Makefile"
            echo "推测为工具链包的 Makefile: $full_makefile_path"
        elif [ -f "$makefile_name_from_err" ]; then
            full_makefile_path="$makefile_name_from_err"
            echo "使用当前目录中的文件: $full_makefile_path"
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

    # 检查并修复文件（包括子文件）
    if [ -f "$makefile_path_rel" ] && [ -n "$line_num" ] && [[ "$line_num" =~ ^[0-9]+$ ]]; then
        line_content=$(sed -n "${line_num}p" "$makefile_path_rel")
        echo "第 $line_num 行内容: '$line_content'"

        # 检查是否为 include 语句
        if [[ "$line_content" =~ ^[[:space:]]*include[[:space:]]+(.+) ]]; then
            subfile=$(echo "$line_content" | sed 's/^[[:space:]]*include[[:space:]]\+//')
            subfile=$(realpath --relative-to="$(dirname "$makefile_path_rel")" "$(dirname "$makefile_path_rel")/$subfile" 2>/dev/null || echo "$subfile")
            echo "检测到 include 子文件: $subfile"

            if [ -f "$subfile" ]; then
                echo "检查子文件 $subfile 是否存在 'missing separator' 问题..."
                # 检查子文件每一行
                while IFS= read -r sub_line; do
                    if [[ "$sub_line" =~ ^[[:space:]]+ ]] && ! [[ "$sub_line" =~ ^\t ]] && ! [[ "$sub_line" =~ ^[[:space:]]*[#] ]] && [ -n "$sub_line" ]; then
                        echo "子文件 $subfile 中检测到空格缩进，替换为 TAB..."
                        cp "$subfile" "$subfile.bak"
                        printf -v tab '\t'
                        sed -i "s/^[[:space:]]\+/$tab/" "$subfile"
                        if [ $? -eq 0 ] && grep -q "^\t" "$subfile"; then
                            echo "成功修复子文件 $subfile 的缩进。"
                            rm -f "$subfile.bak"
                            fix_attempted=1
                        else
                            echo "修复子文件失败，恢复备份。"
                            mv "$subfile.bak" "$subfile"
                        fi
                    fi
                done < "$subfile"
            else
                echo "警告: 子文件 $subfile 不存在，跳过检查。"
            fi
        fi

        # 检查当前行是否需要修复缩进
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
        elif [ -z "$line_content" ] || [[ "$line_content" =~ ^[[:space:]]*$ ]]; then
            echo "第 $line_num 行为空行，可能有隐藏字符，尝试规范化..."
            cp "$makefile_path_rel" "$makefile_path_rel.bak"
            sed -i "${line_num}s/^[[:space:]]*$//" "$makefile_path_rel"
            if [ $? -eq 0 ]; then
                echo "已规范化空行。"
                rm -f "$makefile_path_rel.bak"
                fix_attempted=1
            else
                echo "规范化失败，恢复备份。"
                mv "$makefile_path_rel.bak" "$makefile_path_rel"
            fi
        else
            echo "第 $line_num 行无需修复或问题不在缩进（可能是子文件问题）。"
            echo "请检查 $makefile_path_rel 第 $line_num 行内容: '$line_content'"
        fi
    else
        echo "文件 '$makefile_path_rel' 不存在或行号无效。"
    fi

    # 清理相关目录
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
    if [[ "$makefile_path_rel" =~ package/libs/toolchain ]]; then
        echo "检测到工具链包错误，强制清理 package/libs/toolchain..."
        make "package/libs/toolchain/clean" DIRCLEAN=1 V=s || echo "警告: 清理工具链失败。"
        fix_attempted=1
        if [ $fix_attempted -eq 1 ] && grep -q "missing separator" "$log_file"; then
            echo "修复尝试后问题仍未解决，请手动检查 $makefile_path_rel 第 $line_num 行及其子文件。"
            return 1
        fi
    fi

    [ $fix_attempted -eq 1 ] && return 0 || return 1
}

# --- 修复函数: trojan-plus boost::asio::buffer_cast 错误 ---
fix_trojan_plus_boost_error() {
    echo "修复 trojan-plus 中的 boost::asio::buffer_cast 错误..."
    local trojan_src_dir service_cpp found_path="" trojan_pkg_dir=""
    trojan_src_dir=$(find build_dir -type d -path '*/trojan-plus-*/src/core' -print -quit)
    if [ -n "$trojan_src_dir" ]; then
        service_cpp="$trojan_src_dir/service.cpp"
        if [ -f "$service_cpp" ]; then
            found_path="$service_cpp"
            # Try to determine package dir from build_dir path
            trojan_pkg_dir=$(echo "$trojan_src_dir" | sed -n 's|build_dir/[^/]*/$[^/]*$/src/core|\1|p')
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

# --- 修复函数: 目录冲突 ---
fix_directory_conflict() {
    local log_file="$1"
    echo "检测到目录冲突，尝试修复..."
    
    # 提取冲突的目录路径
    local conflict_dir=$(grep -m 1 "mkdir: cannot create directory.*File exists" "$log_file" | sed -n 's/.*mkdir: cannot create directory \([^:]*\).*/\1/p')
    if [ -z "$conflict_dir" ]; then
        echo "无法从日志中提取冲突目录路径。"
        return 1
    fi
    
    echo "冲突目录: $conflict_dir"
    if [ -d "$conflict_dir" ]; then
        echo "尝试删除冲突目录: $conflict_dir"
        rm -rf "$conflict_dir" || {
            echo "删除目录 $conflict_dir 失败。"
            return 1
        }
        echo "成功删除冲突目录。"
        return 0
    else
        echo "冲突目录 $conflict_dir 不存在，可能已被其他进程处理。"
        return 0
    fi
}

# --- 修复函数: 符号链接冲突 ---
fix_symbolic_link_conflict() {
    local log_file="$1"
    echo "检测到符号链接冲突，尝试修复..."
    
    # 提取冲突的符号链接路径
    local conflict_link=$(grep -m 1 "ln: failed to create symbolic link.*File exists" "$log_file" | sed -n 's/.*ln: failed to create symbolic link \([^:]*\).*/\1/p')
    if [ -z "$conflict_link" ]; then
        echo "无法从日志中提取冲突符号链接路径。"
        return 1
    fi
    
    echo "冲突符号链接: $conflict_link"
    if [ -L "$conflict_link" ] || [ -e "$conflict_link" ]; then
        echo "尝试删除冲突符号链接: $conflict_link"
        rm -f "$conflict_link" || {
            echo "删除符号链接 $conflict_link 失败。"
            return 1
        }
        echo "成功删除冲突符号链接。"
        return 0
    else
        echo "冲突符号链接 $conflict_link 不存在，可能已被其他进程处理。"
        return 0
    fi
}

# --- 辅助函数: 提取错误块 ---
extract_error_block() {
    local log_file="$1"
    echo "--- 最近 300 行日志 (${log_file}) ---"
    tail -n 300 "$log_file"
    echo "--- 日志结束 ---"
}

# --- 修复函数: PKG_VERSION 和 PKG_RELEASE 格式 ---
fix_pkg_version() {
    echo "修复 PKG_VERSION 和 PKG_RELEASE 格式..."
    local changed_count=0
    # 直接使用 find 而不使用中间变量，提高健壮性
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -path "./build_dir/*" -prune -o -path "./staging_dir/*" -prune -o -path "./tmp/*" -prune -o -print0 | while IFS= read -r -d $'\0' makefile; do
        # 跳过不包含标准包定义的 Makefile
        if ! head -n 30 "$makefile" 2>/dev/null | grep -qE '^\s*(include \.\./\.\./(package|buildinfo)\.mk|include \$\(INCLUDE_DIR\)/package\.mk|include \$\(TOPDIR\)/rules\.mk)'; then
            continue
        fi

        local current_version release new_version new_release suffix modified_in_loop=0 makefile_changed=0 original_content
        original_content=$(cat "$makefile") # 一次性读取内容
        current_version=$(echo "$original_content" | sed -n 's/^PKG_VERSION:=\(.*\)/\1/p')
        release=$(echo "$original_content" | sed -n 's/^PKG_RELEASE:=\(.*\)/\1/p')

        # 情况1: 版本字符串包含连字符后缀 (例如 1.2.3-beta1)
        if [[ "$current_version" =~ ^([0-9]+(\.[0-9]+)*)-([a-zA-Z0-9_.-]+)$ ]]; then
            new_version="${BASH_REMATCH[1]}"
            suffix="${BASH_REMATCH[3]}"
            # 尝试从后缀中提取数字，默认为1。注意处理类似 2023-11-01 的版本
            new_release=$(echo "$suffix" | tr -cd '0-9' | grep -o '[0-9]*$' || echo "1") # 获取尾部数字，或1
             if [ -z "$new_release" ] || ! [[ "$new_release" =~ ^[0-9]+$ ]]; then new_release=1; fi # 确保是数字

            if [ "$current_version" != "$new_version" ] || [ "$release" != "$new_release" ]; then
                echo "修改 $makefile: PKG_VERSION: '$current_version' -> '$new_version', PKG_RELEASE: '$release' -> '$new_release'"
                # 使用 awk 进行更安全的替换/添加
                 awk -v ver="$new_version" -v rel="$new_release" '
                    BEGIN { release_found=0; version_printed=0 }
                    /^PKG_VERSION:=/ { print "PKG_VERSION:=" ver; version_printed=1; next }
                    /^PKG_RELEASE:=/ { print "PKG_RELEASE:=" rel; release_found=1; next }
                    { print }
                    END { if(version_printed && !release_found) print "PKG_RELEASE:=" rel }
                 ' "$makefile" > "$makefile.tmp" && mv "$makefile.tmp" "$makefile"

                release=$new_release # 更新 release 变量用于下一次检查
                modified_in_loop=1
                makefile_changed=1
            fi
        fi

        # 情况2: PKG_RELEASE 存在但不是简单数字 (且未在情况1中修复)
        if [ "$modified_in_loop" -eq 0 ] && [ -n "$release" ] && ! [[ "$release" =~ ^[0-9]+$ ]]; then
            new_release=$(echo "$release" | tr -cd '0-9' | grep -o '[0-9]*$' || echo "1") # 获取尾部数字，或1
            if [ -z "$new_release" ] || ! [[ "$new_release" =~ ^[0-9]+$ ]]; then new_release=1; fi # 确保是数字
            if [ "$release" != "$new_release" ]; then
                echo "修正 $makefile: PKG_RELEASE: '$release' -> '$new_release'"
                sed -i.bak "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile" && rm "$makefile.bak"
                makefile_changed=1
            fi
        # 情况3: PKG_RELEASE 完全缺失但 PKG_VERSION 存在 (且未被情况1处理)
        elif [ "$modified_in_loop" -eq 0 ] && [ -z "$release" ] && echo "$original_content" | grep -q "^PKG_VERSION:=" && ! echo "$original_content" | grep -q "^PKG_RELEASE:="; then
             echo "添加 $makefile: PKG_RELEASE:=1"
             # 使用 awk 在 PKG_VERSION 后安全添加
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
    return 0
}

# --- 修复函数: 修复 metadata 错误 ---
fix_metadata_errors() {
    echo "尝试修复 metadata 错误..."
    
    # 1. 修复 PKG_VERSION/PKG_RELEASE 格式
    fix_pkg_version
    
    # 2. 更新 feeds 索引
    echo "更新 feeds 索引..."
    ./scripts/feeds update -i || echo "警告: feeds update -i 失败"
    
    # 3. 清理 tmp 目录
    echo "清理 tmp 目录..."
    rm -rf tmp/
    
    return 0
}

# --- 主循环 ---
echo "--------------------------------------------------"
echo "尝试编译: $MAKE_COMMAND (第 1 / $MAX_RETRY 次)..."
echo "--------------------------------------------------"

retry_count=1
last_fix_applied=""
metadata_fixed=0

while [ $retry_count -le $MAX_RETRY ]; do
    if [ $retry_count -gt 1 ]; then
        echo "--------------------------------------------------"
        echo "尝试编译: $MAKE_COMMAND (第 $retry_count / $MAX_RETRY 次)..."
        echo "--------------------------------------------------"
    fi
    
    fix_applied_this_iteration=0
    
    # 执行编译命令，将输出同时写入临时日志文件
    echo "执行: $MAKE_COMMAND"
    $MAKE_COMMAND 2>&1 | tee "$LOG_FILE.tmp"
    COMPILE_STATUS=${PIPESTATUS[0]}
    
    # 检查编译是否成功
    if [ $COMPILE_STATUS -eq 0 ] && ! grep -E -q "$ERROR_PATTERN" "$LOG_FILE.tmp"; then
        echo "--------------------------------------------------"
        echo "编译成功！"
        echo "--------------------------------------------------"
        cat "$LOG_FILE.tmp" >> "$LOG_FILE" # 追加成功日志
        rm "$LOG_FILE.tmp"
        exit 0
    else
        echo "编译失败 (退出码: $COMPILE_STATUS 或在日志中检测到错误)，检查错误..."
        extract_error_block "$LOG_FILE.tmp"
    fi

    # --- 错误检测和修复逻辑 (顺序很重要!) ---
    
    # 1. 特定错误检测和修复
    # Trojan-plus buffer_cast 错误
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
    
    # Makefile 缺少分隔符错误
    elif grep -q "missing separator.*Stop." "$LOG_FILE.tmp"; then
        echo "检测到 Makefile 'missing separator' 错误..."
        if [ "$last_fix_applied" = "fix_makefile_separator" ]; then
            echo "上次已尝试修复 Makefile 分隔符，但错误依旧，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_makefile_separator"
        if fix_makefile_separator "$LOG_FILE.tmp"; then
            fix_applied_this_iteration=1
        else
            echo "修复 Makefile 分隔符失败，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
    
    # 目录冲突
    elif grep -q "mkdir: cannot create directory.*File exists" "$LOG_FILE.tmp"; then
        echo "检测到目录冲突错误..."
        if [ "$last_fix_applied" = "fix_directory_conflict" ]; then
            echo "上次已尝试修复目录冲突，但错误依旧，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_directory_conflict"
        if fix_directory_conflict "$LOG_FILE.tmp"; then
            fix_applied_this_iteration=1
        else
            echo "修复目录冲突失败，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
    
    # 符号链接冲突
    elif grep -q "ln: failed to create symbolic link.*File exists" "$LOG_FILE.tmp"; then
        echo "检测到符号链接冲突错误..."
        if [ "$last_fix_applied" = "fix_symbolic_link_conflict" ]; then
            echo "上次已尝试修复符号链接冲突，但错误依旧，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
        last_fix_applied="fix_symbolic_link_conflict"
        if fix_symbolic_link_conflict "$LOG_FILE.tmp"; then
            fix_applied_this_iteration=1
        else
            echo "修复符号链接冲突失败，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
    
    # 2. 元数据错误 (通常在其他修复失败后尝试)
    elif (grep -q "Collected errors:" "$LOG_FILE.tmp" || grep -q "ERROR: " "$LOG_FILE.tmp") && [ $metadata_fixed -eq 0 ]; then
        echo "检测到可能的元数据错误..."
        last_fix_applied="fix_metadata"
        if fix_metadata_errors; then
            fix_applied_this_iteration=1
            metadata_fixed=1
        else
            echo "未应用元数据修复，停止重试。"
            cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
            exit 1
        fi
    
    # 3. 通用错误模式检查 (最后尝试)
    elif grep -E -q "$ERROR_PATTERN" "$LOG_FILE.tmp"; then
        local matched_pattern
        matched_pattern=$(grep -E -m 1 "$ERROR_PATTERN" "$LOG_FILE.tmp")
        echo "检测到通用错误模式 ($ERROR_PATTERN): $matched_pattern"
        # 避免在通用错误上立即循环，如果没有应用修复
        if [ "$last_fix_applied" = "fix_generic" ] && [ $fix_applied_this_iteration -eq 0 ]; then
             echo "上次已尝试通用修复但无效果，错误依旧，停止重试。"
             cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
             exit 1
        fi

        # 通用修复: 再次尝试元数据修复? 或者只是重试? 让我们只重试一次。
        echo "未找到特定修复程序，将重试编译一次。"
        last_fix_applied="fix_generic_retry"
        # 本次迭代没有应用修复，依赖循环计数器
    else
        # 如果没有匹配已知错误模式，但编译失败
        echo "未检测到已知或通用的错误模式，但编译失败 (退出码: $COMPILE_STATUS)。"
        echo "请检查完整日志: $LOG_FILE"
        cat "$LOG_FILE.tmp" >> "$LOG_FILE" # 追加最终失败的日志段
        rm "$LOG_FILE.tmp"
        exit 1
    fi

    # --- 循环控制 ---
    if [ $fix_applied_this_iteration -eq 0 ] && [ $COMPILE_STATUS -ne 0 ]; then
        echo "警告：检测到错误，但此轮未应用有效修复。上次尝试: ${last_fix_applied:-无}"
        # 即使没有应用修复也允许一次简单重试，可能是暂时性问题
        if [ "$last_fix_applied" = "fix_generic_retry" ] || [ $retry_count -ge $((MAX_RETRY - 1)) ]; then
             echo "停止重试，因为未应用有效修复或已达重试上限。"
             cat "$LOG_FILE.tmp" >> "$LOG_FILE" && rm "$LOG_FILE.tmp"
             exit 1
        else
             echo "将再重试一次，检查是否有其他可修复的错误出现。"
             last_fix_applied="fix_generic_retry" # 标记我们正在进行简单重试
        fi
    fi

    # 清理此次迭代的临时日志
    rm "$LOG_FILE.tmp"

    retry_count=$((retry_count + 1))
    echo "等待 3 秒后重试..."
    sleep 3
done

# --- 最终失败 ---
echo "--------------------------------------------------"
echo "达到最大重试次数 ($MAX_RETRY)，编译最终失败。"
echo "--------------------------------------------------"
# 显示完整日志文件的最后 300 行
extract_error_block "$LOG_FILE"
echo "请检查完整日志: $LOG_FILE"
exit 1
