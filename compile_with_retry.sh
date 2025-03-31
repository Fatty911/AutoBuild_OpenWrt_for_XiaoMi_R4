#!/bin/bash

# compile_with_retry.sh
# 用法: bash compile_with_retry.sh <make_command> <log_file> <max_retry> <error_pattern>

# 参数解析
MAKE_COMMAND="$1"           # 编译命令，例如 "make -j1 V=s" 或 "make package/compile V=s"
LOG_FILE="$2"               # 日志文件路径，例如 "compile.log" 或 "packages.log"
MAX_RETRY="${3:-6}"         # 最大重试次数，默认6
ERROR_PATTERN="${4:-error:|failed|undefined reference}"  # 错误模式，默认值

# 检查必要参数
if [ -z "$MAKE_COMMAND" ] || [ -z "$LOG_FILE" ]; then
    echo "错误：缺少必要参数。用法: $0 <make_command> <log_file> [max_retry] [error_pattern]"
    exit 1
fi

# 修复 po2lmo 命令未找到
fix_po2lmo() {
    echo "检测到 po2lmo 命令未找到，尝试编译 luci-base..."
    make package/feeds/luci/luci-base/compile V=s || {
        echo "编译 luci-base 失败"
        extract_error_block "$LOG_FILE"
        exit 1
    }
}

# 日志截取函数
extract_error_block() {
    local log_file="$1"
    tail -200 "$log_file"
}

# 修复 PKG_VERSION 和 PKG_RELEASE 格式
fix_pkg_version() {
    echo "修复 PKG_VERSION 和 PKG_RELEASE 格式..."
    find . -type f \( -name "Makefile" -o -name "*.mk" \) | while read -r makefile; do
        # 提取当前 PKG_VERSION 和 PKG_RELEASE
        version=$(sed -n 's/^PKG_VERSION:=\(.*\)/\1/p' "$makefile")
        release=$(sed -n 's/^PKG_RELEASE:=\(.*\)/\1/p' "$makefile")

        # 处理 PKG_VERSION 中包含后缀的情况（如 1.2.3-rc1）
        if [[ "$version" =~ ^([0-9]+\.[0-9]+\.[0-9]+)-(.+)$ ]] && [ -z "$release" ]; then
            new_version="${BASH_REMATCH[1]}"
            new_release="${BASH_REMATCH[2]}"
            # 如果后缀是数字，直接用作 PKG_RELEASE，否则设为 1
            if ! [[ "$new_release" =~ ^[0-9]+$ ]]; then
                new_release="1"
            fi
            sed -i.bak -e "s/^PKG_VERSION:=.*/PKG_VERSION:=$new_version/" \
                       -e "/^PKG_VERSION/a PKG_RELEASE:=$new_release" "$makefile"
            echo "修改 $makefile: PKG_VERSION=$new_version, PKG_RELEASE=$new_release"
        fi

        # 确保 PKG_RELEASE 是纯数字
        if [ -n "$release" ] && ! [[ "$release" =~ ^[0-9]+$ ]]; then
            new_release=$(echo "$release" | tr -cd '0-9' | grep -o '[0-9]\+' || echo "1")
            sed -i.bak "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$new_release/" "$makefile"
            echo "设置 $makefile 中的 PKG_RELEASE 为 $new_release"
        fi
    done
}

# 修复依赖重复
fix_depends() {
    echo "Fixing dependency duplicates..."
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
                if (dep ~ /\$\(/) { result = result " " dep; continue }
                pos = index(dep, ">=")
                if (pos > 0) { bare = substr(dep, 2, pos-2) } else { bare = substr(dep, 2) }
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
            echo "Modified $makefile:"
            grep -E "(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS):=" "$makefile.tmp"
            mv "$makefile.tmp" "$makefile"
        else
            rm -f "$makefile.tmp"
        fi
    ' _ {} \;
}

# 修复依赖格式
fix_dependency_format() {
    echo "处理依赖格式错误..."
    find . -type f \( -name "Makefile" -o -name "*.mk" \) -exec sh -c '
        makefile="$1"
        awk -i inplace '\''BEGIN { FS="[[:space:]]+"; OFS=" " }
        /^(DEPENDS|EXTRA_DEPENDS|LUCI_DEPENDS|LUCI_EXTRA_DEPENDS):=/ {
            delete seen
            split($0, parts, "=")
            split(parts[2], deps, " ")
            new_deps = ""
            for (i in deps) {
                dep = deps[i]
                gsub(/(>=|<=|>)(\d+\.\d+\.\d+)-\d+/, "\\1\\2", dep)
                if (!seen[dep]++) { new_deps = new_deps " " dep }
            }
            $0 = parts[1] "=" new_deps
        }
        { print }
        '\'' "$makefile"
    ' _ {} \;
}

# 修复目录冲突
fix_mkdir_conflict() {
    local log_file="$1"
    echo "检测到构建目录冲突错误，尝试修复..."
    FAILED_DIR=$(grep -oP "mkdir: cannot create directory '\K[^']+" "$log_file" | tail -n1)
    if [ -n "$FAILED_DIR" ]; then
        echo "正在清理冲突目录: $FAILED_DIR"
        rm -rf "$FAILED_DIR"
        PKG_PATH=$(echo "$FAILED_DIR" | grep -oE 'package/feeds/[^/]+/[^/]+')
        if [ -n "$PKG_PATH" ]; then
            PKG_NAME=$(basename "$PKG_PATH")
            echo "重新编译包: $PKG_NAME"
            make -j1 "$PKG_PATH/compile" V=s || return 1
        else
            echo "无法推断包名，尝试重新编译所有包"
            eval "$MAKE_COMMAND" || return 1
        fi
    else
        echo "无法提取失败路径，尝试重新编译所有包"
        eval "$MAKE_COMMAND" || return 1
    fi
}

# 修复符号链接冲突
fix_symbolic_link_conflict() {
    local log_file="$1"
    echo "检测到符号链接冲突错误，尝试修复..."
    # 提取失败的符号链接路径
    FAILED_LINK=$(grep -oP "ln: failed to create symbolic link '\K[^']+" "$log_file" | tail -n1)
    if [ -n "$FAILED_LINK" ]; then
        echo "正在清理冲突的符号链接: $FAILED_LINK"
        rm -f "$FAILED_LINK"
        # 提取包名并重新编译
        PKG_PATH=$(echo "$FAILED_LINK" | grep -oE 'package/feeds/[^/]+/[^/]+')
        if [ -n "$PKG_PATH" ]; then
            PKG_NAME=$(basename "$PKG_PATH")
            echo "重新编译包: $PKG_NAME"
            make -j1 "$PKG_PATH/compile" V=s || return 1
        else
            echo "无法推断包名，尝试重新编译所有包"
            eval "$MAKE_COMMAND" || return 1
        fi
    else
        echo "无法提取失败的符号链接路径，尝试重新编译所有包"
        eval "$MAKE_COMMAND" || return 1
    fi
}

# 主编译循环
# 主编译循环
retry_count=0
while [ $retry_count -lt "$MAX_RETRY" ]; do
    echo "尝试编译: $MAKE_COMMAND (第 $((retry_count + 1)) 次)..."
    eval "$MAKE_COMMAND" > "$LOG_FILE" 2>&1 && {
        echo "编译成功！"
        exit 0
    }

    echo "编译失败，检查错误..."
    echo "最近 200 行日志如下："
    extract_error_block "$LOG_FILE"

    if grep -q "package version is invalid" "$LOG_FILE" || grep -q "PKG_VERSION" "$LOG_FILE"; then
        fix_pkg_version
    elif grep -q "po2lmo: command not found" "$LOG_FILE"; then
        fix_po2lmo
    elif grep -q "DEPENDS" "$LOG_FILE"; then
        fix_depends
    elif grep -q "dependency format is invalid" "$LOG_FILE"; then
        fix_dependency_format
        fix_pkg_version
        fix_depends
    elif grep -q "mkdir: cannot create directory.*File exists" "$LOG_FILE"; then
        fix_mkdir_conflict "$LOG_FILE" || {
            extract_error_block "$LOG_FILE"
            exit 1
        }
    elif grep -q "ln: failed to create symbolic link.*File exists" "$LOG_FILE"; then
        fix_symbolic_link_conflict "$LOG_FILE" || {
            extract_error_block "$LOG_FILE"
            exit 1
        }
    else
        echo "未识别的错误，请检查完整日志: $LOG_FILE"
        exit 1
    fi

    retry_count=$((retry_count + 1))
done

echo "达到最大重试次数 ($MAX_RETRY)，编译失败。"
extract_error_block "$LOG_FILE"
exit 1
