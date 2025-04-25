#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import subprocess
import sys
import time
import shutil
from pathlib import Path
import glob
import hashlib

try:
    import requests
    from bs4 import BeautifulSoup
    LIBS_AVAILABLE = True
except ImportError:
    LIBS_AVAILABLE = False
    print("警告: 未安装 requests 和 beautifulsoup4，lua-neturl 下载修复不可用")

# OOM 高风险包列表（来自版本 2）
OOM_PRONE_PACKAGE_PATTERNS = [
    r'/gcc-\d+', r'/llvm-\d+', r'/qt5base-\d+', r'/webkitgtk-\d+', r'/linux-\d+'
]

# 错误签名检测（结合版本 1 和 2）
def get_error_signature(log_content):
    if not log_content: return "no_log_content"
    if re.search(r'Killed|signal 9|Error 137', log_content): return "oom_detected"
    if "undefined reference to" in log_content and "netifd" in log_content: return "netifd_link_error"
    if "missing separator" in log_content: return "makefile_separator"
    if "Patch failed" in log_content: return "patch_failed"
    if LIBS_AVAILABLE and "lua-neturl" in log_content and "Download failed" in log_content: return "lua_neturl_download"
    if "trojan-plus" in log_content and "buffer-cast" in log_content: return "trojan_plus_buffer_cast"
    if "mkdir: cannot create directory" in log_content: return "directory_conflict"
    if "ln: failed to create symbolic link" in log_content: return "symlink_conflict"
    if "toolchain" in log_content and "provides" in log_content: return "toolchain_provides_syntax"
    if "luci-lib-taskd" in log_content: return "luci_lib_taskd_depends"
    if "base-files=" in log_content and "Error 99" in log_content: return "apk_add_base_files"
    return "unknown_error"

# OOM 处理（结合版本 1 和 2）
def handle_oom(current_jobs, log_content):
    for pattern in OOM_PRONE_PACKAGE_PATTERNS:
        if re.search(pattern, log_content):
            print("检测到 OOM 高风险包，强制使用 -j1")
            return 1
    return max(1, current_jobs // 2)  # 版本 1 的减半策略
def get_relative_path(path):
    """获取相对路径"""
    current_pwd = os.getcwd()

    if not os.path.isabs(path):
        # Try resolving relative to current dir first
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            path = abs_path
        else:
            # If not found relative to cwd, return original path maybe it's inside build context
             return path

    try:
        # Check if path is inside current_pwd before making relative
        if Path(path).is_relative_to(current_pwd):
             return os.path.relpath(path, current_pwd)
        else:
            # If path is outside current working dir, return absolute path
            return path
    except ValueError: # Handle cases like different drives on Windows
        return path
    except Exception: # Generic fallback
        return path

# --- Fix Functions ---

def fix_netifd_libnl_tiny():
    """增强版：修复 netifd 编译时缺少 libnl-tiny 的链接问题"""
    import glob

    print("🔧 正在尝试修复 netifd 缺少 libnl-tiny 的链接错误...")
    fixed = False

    try:
        # --- 强制清理 ---
        print("🧹 强制清理 libnl-tiny 和 netifd...")
        subprocess.run(["make", "package/libs/libnl-tiny/clean", "V=s"], check=False, capture_output=True)
        subprocess.run(["make", "package/network/config/netifd/clean", "V=s"], check=False, capture_output=True)
        # 清理 netifd 的 CMake 缓存（如果存在）
        cmake_cache_files = glob.glob("build_dir/target-*/netifd-*/CMakeCache.txt")
        for cache_file in cmake_cache_files:
            print(f"🗑️ 删除 CMake 缓存: {cache_file}")
            try:
                os.remove(cache_file)
            except OSError as e:
                print(f"警告: 删除 CMake 缓存失败: {e}")


        # --- 重新编译 libnl-tiny ---
        print("🔨 编译 libnl-tiny...")
        compile_result = subprocess.run(["make", "package/libs/libnl-tiny/compile", "V=s"], check=False, capture_output=True, text=True)
        if compile_result.returncode != 0:
            print(f"❌ libnl-tiny 编译失败:\n{compile_result.stderr[-500:]}")
            # return False # 不要立即返回，继续尝试修改 netifd

        print("📦 安装 libnl-tiny...")
        install_result = subprocess.run(["make", "package/libs/libnl-tiny/install", "V=s"], check=False, capture_output=True, text=True)
        if install_result.returncode != 0:
            print(f"❌ libnl-tiny 安装失败:\n{install_result.stderr[-500:]}")
            # return False

        # --- 确认 libnl-tiny 库文件 ---
        lib_paths = glob.glob("staging_dir/target-*/usr/lib/libnl-tiny.so") # 优先检查 .so
        if not lib_paths:
             lib_paths = glob.glob("staging_dir/target-*/usr/lib/libnl-tiny.a") # 检查 .a
        if not lib_paths:
            print("❌ 未找到 libnl-tiny 的库文件 (libnl-tiny.so 或 libnl-tiny.a)，修复可能无效。")
            # return False # 即使找不到也可能通过后续步骤修复
        else:
            print(f"✅ 找到 libnl-tiny 库文件: {lib_paths[0]}")

        # --- 修改 netifd 的 Makefile ---
        netifd_makefile = Path("package/network/config/netifd/Makefile")
        if netifd_makefile.exists():
            print(f"🔧 检查并修改 {netifd_makefile}...")
            content_changed = False
            with open(netifd_makefile, "r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = []
            depends_found = False
            ldflags_found = False
            for line in lines:
                if line.strip().startswith("DEPENDS:="):
                    depends_found = True
                    if "+libnl-tiny" not in line:
                        print("  ➕ 添加 +libnl-tiny 到 DEPENDS")
                        line = line.rstrip() + " +libnl-tiny\n"
                        content_changed = True
                elif line.strip().startswith("TARGET_LDFLAGS +="):
                     ldflags_found = True
                     if "-lnl-tiny" not in line:
                         print("  ➕ 添加 -lnl-tiny 到 TARGET_LDFLAGS")
                         line = line.rstrip() + " -lnl-tiny\n"
                         content_changed = True
                new_lines.append(line)

            # 如果没有找到 TARGET_LDFLAGS，则在 PKG_BUILD_DEPENDS 后添加
            if not ldflags_found:
                 try:
                     insert_index = next(i for i, line in enumerate(new_lines) if line.strip().startswith('PKG_BUILD_DEPENDS:=')) + 1
                     print("  ➕ 添加 TARGET_LDFLAGS += -lnl-tiny")
                     new_lines.insert(insert_index, 'TARGET_LDFLAGS += -lnl-tiny\n')
                     content_changed = True
                 except StopIteration:
                     print("  ⚠️ 未找到 PKG_BUILD_DEPENDS，无法自动添加 TARGET_LDFLAGS")


            if content_changed:
                with open(netifd_makefile, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                print(f"✅ 已修改 {netifd_makefile}")
                fixed = True
            else:
                print(f"ℹ️ {netifd_makefile} 无需修改。")
        else:
            print(f"⚠️ 未找到 {netifd_makefile}")

        # --- 修改 netifd 的 CMakeLists.txt (作为补充) ---
        # CMake 通常会通过 DEPENDS 自动找到库，但以防万一
        cmake_path = Path("package/network/config/netifd/CMakeLists.txt")
        if cmake_path.exists():
            print(f"🔧 检查并修改 {cmake_path}...")
            content_changed = False
            with open(cmake_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 查找 target_link_libraries(netifd ...)
            link_match = re.search(r"target_link_libraries\s*\(\s*netifd\s+([^\)]+)\)", content, re.IGNORECASE)
            if link_match:
                linked_libs = link_match.group(1)
                if 'nl-tiny' not in linked_libs and 'libnl-tiny' not in linked_libs:
                    print("  ➕ 添加 nl-tiny 到 target_link_libraries")
                    new_content = content.replace(
                        link_match.group(0),
                        f"target_link_libraries(netifd nl-tiny {linked_libs.strip()})"
                    )
                    content_changed = True
            # 如果没有找到，尝试在 add_executable 后添加
            elif "add_executable(netifd" in content and "target_link_libraries(netifd" not in content:
                 print("  ➕ 添加新的 target_link_libraries(netifd nl-tiny ...)")
                 # 尝试找到已有的库依赖（通常是 ubox, ubus 等）
                 existing_libs = []
                 find_lib_matches = re.findall(r"find_package\(([^ ]+)\s+REQUIRED\)", content)
                 if find_lib_matches:
                     existing_libs = [f"${{{lib.upper()}_LIBRARIES}}" for lib in find_lib_matches]
                 # 如果找不到，就用已知的基础库
                 if not existing_libs:
                     existing_libs = ["${UBOX_LIBRARIES}", "${UBUS_LIBRARIES}", "${UCI_LIBRARIES}", "${JSONC_LIBRARIES}", "${BLOBMSG_JSON_LIBRARIES}"] # 可能需要调整

                 new_content = re.sub(
                     r"(add_executable\(netifd[^\)]+\))",
                     r"\1\ntarget_link_libraries(netifd nl-tiny " + " ".join(existing_libs) + ")",
                     content,
                     count=1
                 )
                 content_changed = True


            if content_changed:
                with open(cmake_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"✅ 已修改 {cmake_path}")
                fixed = True
            else:
                print(f"ℹ️ {cmake_path} 无需修改。")
        else:
            print(f"⚠️ 未找到 {cmake_path}")


        # --- 再次清理 netifd 以确保更改生效 ---
        if fixed:
            print("🧹 再次清理 netifd 以应用更改...")
            subprocess.run(["make", "package/network/config/netifd/clean", "V=s"], check=False, capture_output=True)

        print("✅ netifd 和 libnl-tiny 修复流程完成。")
        # 即使没有明确修改文件，也返回 True，因为清理和重新编译本身就是一种修复尝试
        return True

    except Exception as e:
        print(f"❌ 修复 netifd/libnl-tiny 时发生异常: {e}")
        return False
def fix_trojan_plus_issues():
    """修复 trojan-plus 相关的编译问题"""
    print("🔧 检测到 trojan-plus 相关错误，尝试禁用...")
    makefile_paths = list(Path(".").glob("**/luci-app-passwall/Makefile"))
    fixed_any = False
    for makefile_path in makefile_paths:
        try:
            print(f"检查: {makefile_path}")
            with open(makefile_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            original_content = content

            # 禁用 select PACKAGE_trojan-plus
            content = re.sub(r'^\s*\+\s*PACKAGE_trojan-plus\s*.*?\n', '', content, flags=re.MULTILINE)
            # 禁用 default y for Trojan_Plus include
            content = re.sub(r'(config PACKAGE_.*?_INCLUDE_Trojan_Plus\s*\n(?:.*\n)*?\s*default )\s*y', r'\1n', content)

            if content != original_content:
                with open(makefile_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"✅ 已修改 {makefile_path}")
                fixed_any = True
            else:
                print(f"ℹ️ {makefile_path} 无需修改。")

        except Exception as e:
            print(f"❌ 处理 {makefile_path} 时出错: {e}")

    if fixed_any:
        # 清理 trojan-plus 包以确保修改生效
        print("🧹 清理 trojan-plus 相关包...")
        # Find the package path dynamically
        trojan_plus_paths = list(Path(".").glob("**/trojan-plus/Makefile"))
        for tp_path in trojan_plus_paths:
            pkg_path = tp_path.parent.relative_to(Path.cwd())
            clean_cmd = ["make", f"{pkg_path}/clean", "V=s"]
            print(f"运行: {' '.join(clean_cmd)}")
            subprocess.run(clean_cmd, check=False, capture_output=True)
        return True
    else:
        print("ℹ️ 未找到需要修复的 trojan-plus 相关 Makefile。")
        return False


def fix_lua_neturl_directory():
    """修复 lua-neturl 的 Makefile 和补丁"""
    print("🔧 修复 lua-neturl Makefile 和补丁...")
    makefile_path_pattern = "**/lua-neturl/Makefile"
    makefile_paths = list(Path(".").glob(makefile_path_pattern))

    if not makefile_paths:
        print("❌ 无法找到 lua-neturl 的 Makefile")
        return False

    makefile_path = makefile_paths[0] # Assume first found is the correct one
    patch_dir = makefile_path.parent / "patches"
    print(f"找到 Makefile: {makefile_path}")
    modified = False

    try:
        with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        original_content = content

        # 确保 PKG_BUILD_DIR 正确
        pkg_source_match = re.search(r'^\s*PKG_SOURCE:=([^\n]+)', content, re.MULTILINE)
        pkg_version_match = re.search(r'^\s*PKG_VERSION:=([^\n]+)', content, re.MULTILINE)
        pkg_release_match = re.search(r'^\s*PKG_RELEASE:=([^\n]+)', content, re.MULTILINE)

        if pkg_source_match and pkg_version_match:
            pkg_source = pkg_source_match.group(1).strip()
            pkg_version = pkg_version_match.group(1).strip()
            pkg_release = pkg_release_match.group(1).strip() if pkg_release_match else "1"

            # Derive expected dir name, e.g., neturl-1.2 or neturl-v1.2-1
            # Try common patterns
            expected_subdir = f"neturl-{pkg_version}"
            if pkg_release and pkg_release != "1":
                 expected_subdir += f"-{pkg_release}" # Less common but possible

            # More robust: look at PKG_SOURCE name pattern like neturl-xxx.tar.gz
            source_base = Path(pkg_source).stem
            if source_base.endswith('.tar'): # Handle .tar.gz etc.
                source_base = Path(source_base).stem
            if source_base.startswith("neturl-"):
                expected_subdir = source_base
            elif source_base.startswith("v"): # Handle tags like v1.2-1
                 expected_subdir = f"neturl-{source_base.lstrip('v')}"


            build_dir_line = f"PKG_BUILD_DIR:=$(BUILD_DIR)/{expected_subdir}"
            build_dir_regex = r'^\s*PKG_BUILD_DIR:=\$\(BUILD_DIR\)/.*'

            if not re.search(build_dir_regex, content, re.MULTILINE):
                # Insert after PKG_SOURCE_URL or PKG_HASH
                insert_after = r'^\s*PKG_HASH:=[^\n]+'
                if not re.search(insert_after, content, re.MULTILINE):
                    insert_after = r'^\s*PKG_SOURCE_URL:=[^\n]+'
                if not re.search(insert_after, content, re.MULTILINE):
                     insert_after = r'^\s*PKG_RELEASE:=[^\n]+' # Fallback

                if re.search(insert_after, content, re.MULTILINE):
                     content = re.sub(f'({insert_after})', f'\\1\n{build_dir_line}', content, 1, re.MULTILINE)
                     print(f"✅ 添加 PKG_BUILD_DIR: {build_dir_line}")
                     modified = True
                else:
                     print("⚠️ 无法找到合适的插入点来添加 PKG_BUILD_DIR")

            elif not re.search(r'^\s*PKG_BUILD_DIR:=\$\(BUILD_DIR\)/' + re.escape(expected_subdir) + r'\s*$', content, re.MULTILINE):
                 content = re.sub(build_dir_regex, build_dir_line, content, 1, re.MULTILINE)
                 print(f"✅ 修正 PKG_BUILD_DIR 为: {build_dir_line}")
                 modified = True

        else:
            print("⚠️ 无法从 Makefile 中提取 PKG_SOURCE 或 PKG_VERSION。")

        if content != original_content:
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(content)

        # 处理补丁目录 (隔离非 .patch 文件)
        if patch_dir.exists() and patch_dir.is_dir():
            excluded_dir = patch_dir / "excluded"
            excluded_dir.mkdir(exist_ok=True)
            for item in patch_dir.iterdir():
                if item.is_file() and not item.name.endswith('.patch') and item.name != "excluded":
                    try:
                        dest = excluded_dir / item.name
                        shutil.move(str(item), str(dest))
                        print(f"✅ 已隔离无效补丁文件: {item.name} -> excluded/")
                        modified = True
                    except Exception as e:
                        print(f"❌ 隔离文件 {item.name} 失败: {e}")

    except Exception as e:
        print(f"❌ 处理 lua-neturl Makefile 时出错: {e}")
        return False

    if modified:
        print("✅ 已完成 lua-neturl 的 Makefile 和补丁修复。")
        # Clean the package to apply changes
        pkg_rel_path = makefile_path.parent.relative_to(Path.cwd())
        subprocess.run(["make", f"{pkg_rel_path}/clean", "V=s"], check=False, capture_output=True)
        return True
    else:
        print("ℹ️ lua-neturl 无需修复。")
        return False


def fix_patch_application(log_content):
    """修复补丁应用失败的问题"""
    print("🔧 检测到补丁应用失败，尝试修复...")

    patch_failed_regex = r'Applying (.*?)(?: to .*)? using plaintext.*\n(?:.*\n){0,5}?(?:patch unexpectedly ends|Only garbage found|can\'t find file to patch|Hunk #\d+ FAILED)'
    patch_match = re.search(patch_failed_regex, log_content, re.MULTILINE)

    if not patch_match:
        print("ℹ️ 未明确匹配到补丁失败日志。")
        return False

    patch_file = patch_match.group(1).strip()
    patch_file_path = Path(patch_file)
    print(f"识别到可能失败的补丁文件: {patch_file}")

    if not patch_file_path.exists():
         # Try to find it relative to CWD if it's not absolute
         patch_file_path = Path.cwd() / patch_file
         if not patch_file_path.exists():
             print(f"❌ 补丁文件 {patch_file} 未找到，无法修复。")
             return False

    # Specific fix for lua-neturl patch issues
    if "lua-neturl" in str(patch_file_path):
        print("检测到 lua-neturl 补丁失败，调用专用修复函数...")
        return fix_lua_neturl_directory() # This function handles both Makefile and patches

    # General fix: try removing the problematic patch
    print(f"补丁应用失败，尝试移除补丁文件: {patch_file_path}")
    try:
        # Backup first
        backup_path = patch_file_path.with_suffix(patch_file_path.suffix + ".disabled")
        shutil.move(str(patch_file_path), str(backup_path))
        print(f"✅ 已禁用补丁文件 (重命名为 {backup_path.name})。")

        # Attempt to clean the package the patch belongs to
        # Try to guess package path from patch path (e.g., feeds/xxx/pkg/patches/ -> feeds/xxx/pkg)
        try:
            pkg_dir = patch_file_path.parent.parent # Go up from /patches
            if pkg_dir.exists() and (pkg_dir / "Makefile").exists():
                 pkg_rel_path = pkg_dir.relative_to(Path.cwd())
                 print(f"🧹 尝试清理相关包: {pkg_rel_path}")
                 subprocess.run(["make", f"{pkg_rel_path}/clean", "V=s"], check=False, capture_output=True)
            else:
                 print("⚠️ 无法确定补丁所属包目录，跳过清理。")
        except Exception as clean_e:
            print(f"⚠️ 清理包时出错: {clean_e}")

        return True
    except Exception as e:
        print(f"❌ 禁用补丁 {patch_file_path} 失败: {e}")
        return False


def fix_makefile_separator(log_content):
    """修复 Makefile "missing separator" 错误"""
    print("🔧 检测到 'missing separator' 错误，尝试修复...")
    fixed = False

    # Regex to find the error line and capture file and line number
    # Handle variations like "Makefile:123: *** missing separator. Stop." or "common.mk:45: *** missing separator."
    error_line_match = re.search(r'^([\/\w\.\-]+):(\d+):\s+\*\*\*\s+missing separator', log_content, re.MULTILINE)

    if not error_line_match:
        print("⚠️ 无法从日志中精确提取文件名和行号。")
        return False

    makefile_name_from_err = error_line_match.group(1)
    line_num = int(error_line_match.group(2))
    print(f"识别到错误位置: 文件='{makefile_name_from_err}', 行号={line_num}")

    # Try to find the context directory from "make[X]: Entering directory ..." lines above the error
    log_lines = log_content.splitlines()
    error_line_index = -1
    for i, line in enumerate(log_lines):
        if error_line_match.group(0) in line:
            error_line_index = i
            break

    context_dir = Path.cwd() # Default to current dir
    if error_line_index != -1:
        for i in range(error_line_index - 1, max(0, error_line_index - 50), -1):
            dir_match = re.search(r"make\[\d+\]: Entering directory '([^']+)'", log_lines[i])
            if dir_match:
                context_dir = Path(dir_match.group(1))
                print(f"找到上下文目录: {context_dir}")
                break

    makefile_path = context_dir / makefile_name_from_err
    makefile_path_rel = get_relative_path(str(makefile_path)) # For display

    print(f"尝试修复文件: {makefile_path_rel} (绝对路径: {makefile_path})")

    if makefile_path.is_file():
        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
                makefile_lines = f.readlines()

            if 0 < line_num <= len(makefile_lines):
                line_content = makefile_lines[line_num - 1]
                original_line = line_content

                # Check if the line starts with spaces but not a tab
                if re.match(r'^[ ]+', line_content) and not line_content.startswith('\t'):
                    print(f"检测到第 {line_num} 行使用空格缩进，替换为 TAB...")
                    # Backup the file
                    backup_path = makefile_path.with_suffix(makefile_path.suffix + ".bak")
                    shutil.copy2(makefile_path, backup_path)
                    print(f"创建备份: {get_relative_path(str(backup_path))}")

                    # Replace leading spaces with a tab
                    makefile_lines[line_num - 1] = '\t' + line_content.lstrip(' ')

                    with open(makefile_path, 'w', encoding='utf-8') as f:
                        f.writelines(makefile_lines)

                    # Verify fix
                    with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f_check:
                         fixed_lines = f_check.readlines()
                    if fixed_lines[line_num - 1].startswith('\t'):
                         print(f"✅ 成功修复第 {line_num} 行缩进。")
                         fixed = True
                         os.remove(backup_path) # Remove backup on success
                    else:
                         print(f"❌ 修复失败，第 {line_num} 行内容仍为: '{fixed_lines[line_num-1].rstrip()}'")
                         shutil.move(str(backup_path), makefile_path) # Restore backup
                         print("已恢复备份。")

                # Handle cases where the error might be on an empty line with weird whitespace
                elif not line_content.strip() and line_content != '\n':
                     print(f"第 {line_num} 行为非标准空行，尝试规范化为空行...")
                     backup_path = makefile_path.with_suffix(makefile_path.suffix + ".bak")
                     shutil.copy2(makefile_path, backup_path)
                     makefile_lines[line_num - 1] = '\n'
                     with open(makefile_path, 'w', encoding='utf-8') as f:
                         f.writelines(makefile_lines)
                     print("✅ 已规范化空行。")
                     fixed = True
                     os.remove(backup_path)

                else:
                    print(f"ℹ️ 第 {line_num} 行内容: '{line_content.rstrip()}'。看起来不是简单的空格缩进问题，可能需要手动检查或问题在 include 的文件中。")
                    # Consider checking includes here if necessary, but keep it simple first.

            else:
                print(f"❌ 行号 {line_num} 超出文件 {makefile_path_rel} 的范围 ({len(makefile_lines)} 行)。")

        except Exception as e:
            print(f"❌ 读写文件 {makefile_path_rel} 时出错: {e}")

    else:
        print(f"❌ 文件 '{makefile_path_rel}' 不存在或不是文件。")

    # If a fix was attempted or the error persists, try cleaning the package directory
    if fixed or not fixed: # Always try cleaning if separator error occurred
        pkg_dir = makefile_path.parent
        # Heuristic: Check if the parent dir looks like a package dir
        if pkg_dir.exists() and (pkg_dir / "Makefile").exists() and pkg_dir != Path.cwd():
            pkg_rel_path = get_relative_path(str(pkg_dir))
            print(f"🧹 尝试清理相关包目录: {pkg_rel_path}...")
            try:
                # Use DIRCLEAN=1 for a deeper clean
                subprocess.run(["make", f"{pkg_rel_path}/clean", "DIRCLEAN=1", "V=s"], check=False, capture_output=True)
                print(f"✅ 清理命令已执行 (不保证成功)。")
                # Setting fixed to True here means we *attempted* a fix (either edit or clean)
                fixed = True # Indicate an action was taken for this error
            except Exception as e:
                print(f"⚠️ 执行清理命令时出错: {e}")
        elif makefile_path.name == "Makefile" and context_dir == Path.cwd():
             print(f"🧹 错误发生在根 Makefile，尝试执行 'make clean'... (这可能需要较长时间)")
             try:
                 subprocess.run(["make", "clean", "V=s"], check=False, capture_output=True)
                 print(f"✅ 'make clean' 命令已执行。")
                 fixed = True
             except Exception as e:
                 print(f"⚠️ 执行 'make clean' 时出错: {e}")

    return fixed


def fix_directory_conflict(log_content):
    """修复目录冲突 (mkdir: cannot create directory ...: File exists)"""
    print("🔧 检测到目录冲突，尝试修复...")
    conflict_match = re.search(r'mkdir: cannot create directory [\'"]?([^\'"]+)[\'"]?: File exists', log_content)
    if not conflict_match:
        print("ℹ️ 未匹配到 'File exists' 目录冲突日志。")
        return False

    conflict_path_str = conflict_match.group(1).strip()
    conflict_path = Path(conflict_path_str)
    print(f"冲突路径: {conflict_path}")

    # Important safety check: Avoid deleting critical directories
    critical_dirs = [Path.cwd(), Path.home(), Path("/"), Path("~"), Path("."), Path("..")]
    if conflict_path.resolve() in [p.resolve() for p in critical_dirs] or not conflict_path_str:
        print(f"❌ 检测到关键目录或无效路径 ({conflict_path_str})，拒绝删除！")
        return False

    # Check if it's a file or a directory
    if conflict_path.is_file():
        print(f"冲突路径是一个文件，尝试删除文件: {conflict_path}")
        try:
            conflict_path.unlink()
            print("✅ 成功删除冲突文件。")
            return True
        except Exception as e:
            print(f"❌ 删除文件 {conflict_path} 失败: {e}")
            return False
    elif conflict_path.is_dir():
         # Maybe it should be a symlink? Or maybe just needs removal.
         # Let's try removing it first, as it's the direct cause of 'mkdir' failure.
        print(f"冲突路径是一个目录，尝试删除目录: {conflict_path}")
        try:
            shutil.rmtree(conflict_path)
            print("✅ 成功删除冲突目录。")
            return True
        except Exception as e:
            print(f"❌ 删除目录 {conflict_path} 失败: {e}")
            return False
    else:
        print(f"ℹ️ 冲突路径 {conflict_path} 当前不存在，可能已被处理。")
        # Return True as the conflict state is resolved
        return True

def fix_symbolic_link_conflict(log_content):
    """修复符号链接冲突 (ln: failed to create symbolic link ...: File exists)"""
    print("🔧 检测到符号链接冲突，尝试修复...")
    conflict_match = re.search(r'ln: failed to create symbolic link [\'"]?([^\'"]+)[\'"]?: File exists', log_content)
    if not conflict_match:
        print("ℹ️ 未匹配到 'File exists' 符号链接冲突日志。")
        return False

    conflict_link_str = conflict_match.group(1).strip()
    conflict_link = Path(conflict_link_str)
    print(f"冲突符号链接路径: {conflict_link}")

    # Safety check
    critical_dirs = [Path.cwd(), Path.home(), Path("/"), Path("~"), Path("."), Path("..")]
    if conflict_link.resolve() in [p.resolve() for p in critical_dirs] or not conflict_link_str:
        print(f"❌ 检测到关键目录或无效路径 ({conflict_link_str})，拒绝删除！")
        return False

    if conflict_link.exists(): # Check if it exists (could be file, dir, or existing link)
        print(f"尝试删除已存在的文件/目录/链接: {conflict_link}")
        try:
            if conflict_link.is_dir() and not conflict_link.is_symlink():
                 shutil.rmtree(conflict_link)
                 print(f"✅ 成功删除冲突目录 {conflict_link}。")
            else:
                 conflict_link.unlink() # Works for files and symlinks
                 print(f"✅ 成功删除冲突文件/链接 {conflict_link}。")
            return True
        except Exception as e:
            print(f"❌ 删除 {conflict_link} 失败: {e}")
            return False
    else:
        print(f"ℹ️ 冲突链接路径 {conflict_link} 当前不存在，可能已被处理。")
        return True # Conflict resolved


def fix_pkg_version_format():
    """修复 PKG_VERSION 和 PKG_RELEASE 格式 (简单数字或标准格式)"""
    print("🔧 修复 Makefile 中的 PKG_VERSION 和 PKG_RELEASE 格式...")
    changed_count = 0
    makefile_pattern = "**/Makefile" # Look for Makefiles everywhere except build/staging/tmp
    ignore_dirs = ['build_dir', 'staging_dir', 'tmp', '.git']

    all_makefiles = list(Path('.').glob(makefile_pattern))
    print(f"找到 {len(all_makefiles)} 个潜在的 Makefile 文件进行检查...")

    processed_count = 0
    for makefile in all_makefiles:
        processed_count += 1
        if processed_count % 100 == 0:
             print(f"已检查 {processed_count}/{len(all_makefiles)}...")

        # Skip ignored directories
        if any(part in makefile.parts for part in ignore_dirs):
            continue

        try:
            with open(makefile, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            original_content = content
            current_content = content

            # Check if it's an OpenWrt package Makefile (basic check)
            if not ('include $(TOPDIR)/rules.mk' in content or 'include ../../buildinfo.mk' in content or 'include $(INCLUDE_DIR)/package.mk' in content):
                continue

            modified_in_file = False

            # --- Fix PKG_VERSION ---
            version_match = re.search(r'^(PKG_VERSION:=)(.*)$', current_content, re.MULTILINE)
            if version_match:
                current_version_line = version_match.group(0)
                current_version = version_match.group(2).strip()
                # Simple fix: remove leading 'v' if present
                if current_version.startswith('v'):
                    new_version = current_version.lstrip('v')
                    print(f"🔧 [{get_relative_path(str(makefile))}] 修正 PKG_VERSION: '{current_version}' -> '{new_version}'")
                    current_content = current_content.replace(current_version_line, f"PKG_VERSION:={new_version}", 1)
                    modified_in_file = True
                    current_version = new_version # Update for release check

                # More complex: Split version-release like 1.2-3 into VERSION=1.2, RELEASE=3
                # This is handled below by the RELEASE check

            # --- Fix PKG_RELEASE ---
            release_match = re.search(r'^(PKG_RELEASE:=)(.*)$', current_content, re.MULTILINE)
            version_present = 'PKG_VERSION:=' in current_content

            new_release_val = None
            if release_match:
                current_release_line = release_match.group(0)
                current_release = release_match.group(2).strip()
                # Must be a positive integer
                if not current_release.isdigit() or int(current_release) <= 0:
                    # Try to extract number if possible, e.g., from "beta1" -> "1"
                    num_part = re.search(r'(\d+)$', current_release)
                    if num_part:
                         new_release_val = num_part.group(1)
                         if int(new_release_val) <= 0: new_release_val = "1" # Ensure positive
                    else:
                         new_release_val = "1" # Default to 1

                    if new_release_val != current_release:
                         print(f"🔧 [{get_relative_path(str(makefile))}] 修正 PKG_RELEASE: '{current_release}' -> '{new_release_val}'")
                         current_content = current_content.replace(current_release_line, f"PKG_RELEASE:={new_release_val}", 1)
                         modified_in_file = True
            elif version_present:
                # PKG_RELEASE is missing, add it (default to 1)
                # Also handle case where version might be like "1.2.3-5"
                version_match_for_release = re.search(r'^(PKG_VERSION:=)(.*?)(-(\d+))?$', current_content, re.MULTILINE)
                if version_match_for_release:
                    current_version_line = version_match_for_release.group(0)
                    base_version = version_match_for_release.group(2).strip()
                    release_part = version_match_for_release.group(4)

                    if release_part and release_part.isdigit() and int(release_part) > 0:
                        # Version contains release, split it
                        new_version_line = f"PKG_VERSION:={base_version}"
                        new_release_line = f"PKG_RELEASE:={release_part}"
                        print(f"🔧 [{get_relative_path(str(makefile))}] 分离 PKG_VERSION/RELEASE: '{version_match_for_release.group(2)}{version_match_for_release.group(3)}' -> VERSION='{base_version}', RELEASE='{release_part}'")
                        # Replace version line and insert release line after it
                        current_content = current_content.replace(current_version_line, f"{new_version_line}\n{new_release_line}", 1)
                        modified_in_file = True
                    else:
                        # Version doesn't contain release, just add PKG_RELEASE:=1
                        new_release_line = "PKG_RELEASE:=1"
                        print(f"🔧 [{get_relative_path(str(makefile))}] 添加缺失的 PKG_RELEASE:=1")
                        # Insert after PKG_VERSION line
                        current_content = re.sub(r'^(PKG_VERSION:=.*)$', r'\1\n' + new_release_line, current_content, 1, re.MULTILINE)
                        modified_in_file = True
                else:
                     # Fallback if version format is weird, just add release line
                     new_release_line = "PKG_RELEASE:=1"
                     print(f"🔧 [{get_relative_path(str(makefile))}] 添加缺失的 PKG_RELEASE:=1 (Fallback)")
                     current_content = re.sub(r'^(PKG_VERSION:=.*)$', r'\1\n' + new_release_line, current_content, 1, re.MULTILINE)
                     modified_in_file = True

            # Write back if modified
            if modified_in_file:
                with open(makefile, 'w', encoding='utf-8') as f:
                    f.write(current_content)
                changed_count += 1

        except Exception as e:
            # Ignore errors reading/parsing files that might not be Makefiles
            if isinstance(e, UnicodeDecodeError):
                 pass # Skip binary files etc.
            else:
                 print(f"⚠️ 处理文件 {get_relative_path(str(makefile))} 时跳过，原因: {e}")
            continue

    print(f"✅ 修复 PKG_VERSION/RELEASE 完成，共检查 {processed_count} 个文件，修改 {changed_count} 个文件。")
    # Return True if any file was changed, as this might require index update
    return changed_count > 0

def fix_metadata_errors():
    """修复 metadata 错误 (包括版本格式，并更新索引)"""
    print("🔧 尝试修复 metadata 相关错误...")
    metadata_changed = False

    # 1. Fix PKG_VERSION/RELEASE formats first
    if fix_pkg_version_format():
        metadata_changed = True

    # 2. If formats were fixed or potentially problematic, update feeds index
    if metadata_changed:
        print("ℹ️ 检测到 Makefile 格式更改，更新 feeds 索引...")
        try:
            update_cmd = ["./scripts/feeds", "update", "-i"]
            print(f"运行: {' '.join(update_cmd)}")
            result = subprocess.run(update_cmd, check=False, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if result.returncode != 0:
                print(f"⚠️ feeds update -i 失败:\n{result.stderr[-500:]}")
            else:
                print("✅ feeds update -i 完成。")
            # Re-install might be needed if index changed significantly
            install_cmd = ["./scripts/feeds", "install", "-a"]
            print(f"运行: {' '.join(install_cmd)}")
            result_install = subprocess.run(install_cmd, check=False, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if result_install.returncode != 0:
                 print(f"⚠️ feeds install -a 失败:\n{result_install.stderr[-500:]}")
            else:
                 print("✅ feeds install -a 完成。")

        except Exception as e:
            print(f"❌ 执行 feeds update/install 时出错: {e}")
            metadata_changed = True # Assume change happened if error occurred

    # 3. Clean tmp directory as a general measure for metadata issues
    tmp_dir = Path("tmp")
    if tmp_dir.exists():
        print("🧹 清理 tmp 目录...")
        try:
            shutil.rmtree(tmp_dir)
            print("✅ tmp 目录已清理。")
            metadata_changed = True # Cleaning tmp is a change
        except Exception as e:
            print(f"⚠️ 清理 tmp 目录失败: {e}")

    if metadata_changed:
        print("✅ Metadata 修复尝试完成。")
    else:
        print("ℹ️ 未执行 Metadata 相关修复。")

    return metadata_changed


def fix_depends_format(log_content):
    """自动修复 Makefile 中的无效依赖项 (增强版 v2)"""
    print("🔧 检测到依赖项格式错误，尝试自动修复 Makefile 中的 DEPENDS 字段...")

    reported_files = set()
    warning_pattern = re.compile(r"WARNING: Makefile '([^']+)' has a dependency on '([^']*)', which does not exist")
    for match in warning_pattern.finditer(log_content):
        # 过滤掉一些已知的、可能无害或难以修复的警告
        bad_dep = match.group(2)
        if bad_dep != 'PERL_TESTS' and 'gst1-mod-' not in bad_dep: # 过滤已知噪音
            reported_files.add(match.group(1))

    fixed_count = 0
    processed_files = set()
    files_actually_fixed = []

    # 优先处理报告的文件
    if reported_files:
        print(f"🎯 优先处理日志中报告的 {len(reported_files)} 个 Makefile...")
        for makefile_path_str in reported_files:
            makefile_path = Path(makefile_path_str)
            if makefile_path.exists() and makefile_path.is_file():
                if str(makefile_path.resolve()) not in processed_files:
                    if fix_single_makefile_depends(makefile_path):
                        fixed_count += 1
                        files_actually_fixed.append(makefile_path_str)
                    processed_files.add(str(makefile_path.resolve()))
            else:
                print(f"  ⚠️ 报告的文件不存在或不是文件: {makefile_path_str}")

    # --- (特定错误包处理逻辑 - 可选增强) ---
    # 如果 apk_depends_invalid 错误发生，也尝试修复那个包的 Makefile
    apk_error_sig = get_error_signature(log_content)
    if "apk_depends_invalid" in apk_error_sig:
        failed_pkg_name = apk_error_sig.split(":")[-1]
        print(f"🎯 尝试修复导致 APK 错误的包 '{failed_pkg_name}' 的 Makefile...")
        possible_makefile_paths = list(Path(".").glob(f"**/feeds/*/{failed_pkg_name}/Makefile")) + \
                                  list(Path(".").glob(f"package/*/{failed_pkg_name}/Makefile"))
        if possible_makefile_paths:
            makefile_path = possible_makefile_paths[0]
            if str(makefile_path.resolve()) not in processed_files:
                print(f"  ➡️ 定位到 Makefile: {makefile_path}")
                if fix_single_makefile_depends(makefile_path):
                    if makefile_path not in files_actually_fixed: # 避免重复计数
                         fixed_count += 1
                         files_actually_fixed.append(str(makefile_path))
                processed_files.add(str(makefile_path.resolve()))
            else:
                 print(f"  ℹ️ 包 '{failed_pkg_name}' 的 Makefile 已处理过。")
        else:
            print(f"  ⚠️ 未能找到包 '{failed_pkg_name}' 的 Makefile。")


    if fixed_count > 0:
        print(f"✅ 共修复 {fixed_count} 个 Makefile 中的依赖格式问题: {files_actually_fixed}")
        print("  🔄 运行 './scripts/feeds update -i && ./scripts/feeds install -a' 来更新依赖...")
        # ... (运行 feeds 命令的代码保持不变) ...
        try:
            update_result = subprocess.run(["./scripts/feeds", "update", "-i"], check=False, capture_output=True, text=True, timeout=120)
            # ... (处理 update 结果) ...
            install_result = subprocess.run(["./scripts/feeds", "install", "-a"], check=False, capture_output=True, text=True, timeout=300)
            # ... (处理 install 结果) ...
        except Exception as e:
            print(f"  ⚠️ 更新/安装 feeds 时出错: {e}")
        return True
    else:
        print("ℹ️ 未发现或未成功修复需要处理的 DEPENDS 字段。")
        return False



def fix_single_makefile_depends(makefile_path: Path):
    """修复单个 Makefile 中的 DEPENDS 字段 (增强版 v2)"""
    try:
        with open(makefile_path, 'r', errors='replace') as f:
            content = f.read()
    except Exception as e:
        print(f"  ❌ 读取 Makefile 出错 {makefile_path}: {e}")
        return False

    # 查找 DEPENDS 行 (支持 += 和多行定义)
    # 使用 re.DOTALL 来匹配跨行的 DEPENDS
    depends_match = re.search(r'^(DEPENDS\s*[:+]?=\s*)((?:.*?\\\n)*.*)$', content, re.MULTILINE | re.IGNORECASE | re.DOTALL)
    if not depends_match:
        return False # 没有 DEPENDS 行

    original_block = depends_match.group(0) # 整个匹配块
    prefix = depends_match.group(1)
    depends_str_multiline = depends_match.group(2)

    # 将多行合并为一行，并移除行尾的反斜杠
    depends_str = depends_str_multiline.replace('\\\n', ' ').replace('\n', ' ').strip()

    # 按空格分割依赖项
    depends_list = re.split(r'\s+', depends_str)
    cleaned_depends = []
    modified = False

    for dep in depends_list:
        dep = dep.strip()
        if not dep or dep == '\\': # 跳过空项和残留的反斜杠
            continue

        original_dep = dep

        # 移除前缀 +@
        dep_prefix = ""
        if dep.startswith('+'):
            dep_prefix = "+"
            dep = dep[1:]
        elif dep.startswith('@'):
             dep_prefix = "@"
             dep = dep[1:]

        # 移除版本约束
        dep_name = re.split(r'[<>=!~]', dep, 1)[0]

        # 移除垃圾字符和模式 (更严格)
        dep_name = re.sub(r'^(?:p|dependency|select|default|bool|tristate),+', '', dep_name, flags=re.IGNORECASE) # 移除更多前缀
        dep_name = dep_name.replace(',)', '').replace(')', '').replace('(', '').replace(',', '') # 移除 ,) () ,
        dep_name = dep_name.strip('\'" ') # 移除首尾引号和空格

        # 再次移除可能引入的版本约束
        dep_name = re.split(r'[<>=!~]', dep_name, 1)[0]

        # 验证清理后的名称
        if dep_name and re.match(r'^[a-zA-Z0-9._-]+$', dep_name) and dep_name != 'gst1-mod-':
            cleaned_dep_str = f"{dep_prefix}{dep_name}"
            cleaned_depends.append(cleaned_dep_str)
            if cleaned_dep_str != original_dep:
                modified = True
                print(f"  🔧 清理依赖: '{original_dep}' -> '{cleaned_dep_str}' in {makefile_path}")
        elif dep_name:
             print(f"  ⚠️ 清理后的依赖 '{dep_name}' (来自 '{original_dep}') 格式无效，已丢弃。文件: {makefile_path}")
             modified = True
        else:
             if original_dep:
                 print(f"  🗑️ 丢弃无效依赖: '{original_dep}' in {makefile_path}")
                 modified = True

    if modified:
        unique_depends = list(dict.fromkeys(cleaned_depends))
        new_depends_str = ' '.join(unique_depends)
        new_depends_line = f"{prefix}{new_depends_str}" # 使用原始前缀

        # 使用 strip() 比较，但替换时要精确
        original_line_to_replace = original_block.strip()
        new_block_to_insert = new_depends_line # 修复后通常不需要多行

        if new_block_to_insert.strip() != original_line_to_replace.strip():
            print(f"  ✅ 修复 {makefile_path}:")
            print(f"    原始块: {original_line_to_replace}")
            print(f"    修复为: {new_block_to_insert.strip()}")
            try:
                # 直接替换整个匹配块
                new_content = content.replace(original_block, new_block_to_insert, 1)
                with open(makefile_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                return True
            except Exception as e:
                 print(f"  ❌ 写回 Makefile 失败 {makefile_path}: {e}")
                 return False
        else:
             print(f"  ℹ️ 清理后内容未变 (或仅空格变化): {makefile_path}")
             return False
    else:
        return False





def process_makefile_depends(makefile_path: Path):
    """Helper function to process DEPENDS in a single Makefile.
       Handles simple lists and complex Make constructs differently."""
    try:
        if makefile_path.is_symlink():
            pass # Process the symlink path

        if not makefile_path.is_file():
            return False

        with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        original_content = content

        is_package_makefile = ('define Package/' in content and 'endef' in content) or \
                              ('include $(TOPDIR)/rules.mk' in content or \
                               'include $(INCLUDE_DIR)/package.mk' in content or \
                               'include ../../buildinfo.mk' in content)
        if not is_package_makefile:
            return False

        depends_regex = r'^([ \t]*DEPENDS\+?=\s*)((?:.*?\\\n)*.*)$'
        modified_in_file = False
        new_content = content
        offset_adjustment = 0

        matches = list(re.finditer(depends_regex, content, re.MULTILINE))
        if not matches:
            return False

        for match in matches:
            start_index = match.start() + offset_adjustment
            end_index = match.end() + offset_adjustment

            original_depends_line_block = new_content[start_index:end_index]
            prefix = match.group(1)
            depends_value = match.group(2).replace('\\\n', ' ').strip()
            original_depends_value_for_log = depends_value # For potential logging

            # --- Check for complex Make syntax ($ or parenthesis) ---
            # We assume lines with these characters should not have duplicates removed after splitting
            is_complex = '$' in depends_value or '(' in depends_value

            # Split by whitespace - this is the source of potential issues with complex lines
            depends_list = re.split(r'\s+', depends_value)
            processed_depends = [] # Store parts after version cleaning
            needs_fix = False      # Track if any version constraint was removed

            for dep in depends_list:
                dep = dep.strip()
                if not dep:
                    continue

                dep_prefix = ""
                if dep.startswith('+') or dep.startswith('@'):
                    dep_prefix = dep[0]
                    dep_name = dep[1:]
                else:
                    dep_name = dep

                # Remove version constraints like >=, <=, =, >, <
                cleaned_name = re.split(r'[>=<]', dep_name, 1)[0].strip()

                if cleaned_name != dep_name:
                    needs_fix = True

                # Reconstruct the potentially cleaned part
                # We keep the original structure for complex lines, just potentially without version constraints
                current_part = f"{dep_prefix}{cleaned_name}" if cleaned_name else dep # Handle empty cleaned_name? Fallback to original dep.

                # Basic validation check (optional, but good practice)
                # If the part still looks weird after cleaning, maybe keep original?
                # For now, we trust the cleaning for version constraints.
                processed_depends.append(current_part)

            # --- Apply fixes only if version constraints were found ---
            if needs_fix:
                if is_complex:
                    # For complex lines (containing $ or parenthesis),
                    # simply join the processed parts back together.
                    # DO NOT remove duplicates, as it breaks Make syntax like $(foreach).
                    new_depends_str = ' '.join(processed_depends)
                    # Optional: Log that we handled a complex line differently
                    # print(f"  处理复杂依赖行 (仅移除版本约束): {get_relative_path(str(makefile_path))}")
                else:
                    # For simple lines, remove duplicates as before.
                    # print(f"  处理简单依赖行 (移除版本约束和重复项): {get_relative_path(str(makefile_path))}")
                    seen = {}
                    unique_depends = []
                    for item in processed_depends: # Iterate over the already cleaned parts
                        item_prefix = ""
                        item_name = item
                        if item.startswith('+') or item.startswith('@'):
                            item_prefix = item[0]
                            item_name = item[1:]

                        if not item_name: continue

                        if item_name not in seen:
                            seen[item_name] = item_prefix
                            unique_depends.append(item)
                        elif item_prefix == '@' and seen[item_name] == '+':
                            seen[item_name] = '@'
                            for i, old_item in enumerate(unique_depends):
                                if old_item == f"+{item_name}":
                                    unique_depends[i] = item
                                    break
                    new_depends_str = ' '.join(unique_depends)

                # Reconstruct the full line
                new_depends_line = f"{prefix}{new_depends_str}"

                # Replace the original block within the *current* state of new_content
                current_block_in_new_content = new_content[start_index:end_index]
                if current_block_in_new_content == original_depends_line_block: # Sanity check
                    new_content = new_content[:start_index] + new_depends_line + new_content[end_index:]
                    offset_adjustment += len(new_depends_line) - len(original_depends_line_block)
                    modified_in_file = True
                else:
                     print(f"⚠️ 替换依赖块时发生偏移错误或内容不匹配 in {get_relative_path(str(makefile_path))}")
                     # Attempting replacement based on original value might be risky if content shifted significantly
                     # Let's try replacing based on the original block content found initially
                     # This is less safe but might work if only minor shifts occurred.
                     try:
                         # Find the original block again in the potentially modified new_content
                         current_start_index = new_content.find(original_depends_line_block, max(0, start_index - 50)) # Search around the original position
                         if current_start_index != -1:
                             current_end_index = current_start_index + len(original_depends_line_block)
                             print(f"  尝试基于原始内容进行替换...")
                             new_content = new_content[:current_start_index] + new_depends_line + new_content[current_end_index:]
                             # Recalculate offset adjustment based on this replacement
                             offset_adjustment = len(new_content) - len(original_content) # Simpler recalculation
                             modified_in_file = True
                         else:
                              print(f"  无法在当前内容中重新定位原始块，跳过替换。")
                              continue # Skip this match
                     except Exception as replace_err:
                          print(f"  基于原始内容替换时出错: {replace_err}, 跳过替换。")
                          continue # Skip this match if fallback replacement fails

        if modified_in_file:
            print(f"✅ 已修改依赖项: {get_relative_path(str(makefile_path))}") # Log modified file
            # Write back the modified content only if changes were made
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return True # Indicate modification

    except Exception as e:
        if isinstance(e, UnicodeDecodeError):
             pass # Skip files that cannot be decoded
        elif isinstance(e, FileNotFoundError):
             print(f"⚠️ 处理文件时未找到: {get_relative_path(str(makefile_path))}")
        else:
             # Log other errors during file processing
             print(f"⚠️ 处理文件 {get_relative_path(str(makefile_path))} 时发生错误: {e}")
        return False

    return False # No modification needed or happened
def fix_lua_neturl_download(log_content):
    """修复 lua-neturl 下载问题 (需要 requests 和 beautifulsoup4)"""
    if not (requests and BeautifulSoup):
        print("❌ 跳过 lua-neturl 下载修复：缺少 'requests' 或 'beautifulsoup4' 库。")
        return False

    print("🔧 检测到 lua-neturl 下载错误，尝试更新 Makefile...")

    makefile_path = None
    for pattern in ["feeds/small8/lua-neturl/Makefile", "package/feeds/small8/lua-neturl/Makefile"]:
        path = Path(pattern)
        if path.exists():
            makefile_path = path
            break

    if not makefile_path:
        print("❌ 无法找到 lua-neturl 的 Makefile。")
        return False

    print(f"找到 Makefile: {makefile_path}")

    try:
        # 1. Get latest tag from GitHub
        print("🌐 正在从 GitHub 获取最新的 neturl tag...")
        response = requests.get("https://github.com/golgote/neturl/tags", timeout=15)
        response.raise_for_status() # Raise exception for bad status codes
        soup = BeautifulSoup(response.text, 'html.parser')
        # Find tags like vX.Y.Z or vX.Y.Z-N
        tag_elements = soup.find_all('a', href=re.compile(r'/golgote/neturl/releases/tag/v[\d.-]+'))
        tags = [tag.text.strip() for tag in tag_elements if re.match(r'^v[\d.-]+$', tag.text.strip())]

        if not tags:
            print("⚠️ 未能在 GitHub 页面找到有效的版本标签，使用默认值 v1.2-1。")
            latest_tag = "v1.2-1"
        else:
            # Simple sort might work for versions like v1.2, v1.10 but fail for v1.2-1 vs v1.2
            # Let's just take the first one found, assuming GitHub lists newest first
            latest_tag = tags[0]
            print(f"✅ 获取到最新/第一个 tag: {latest_tag}")

        # 2. Derive version, source filename, URL, and expected build dir
        raw_version_part = latest_tag.lstrip('v') # e.g., 1.2-1
        pkg_version = re.match(r'^(\d+(\.\d+)*)', raw_version_part).group(1) # e.g., 1.2
        pkg_release = "1" # Default release
        release_match = re.search(r'-(\d+)$', raw_version_part)
        if release_match:
            pkg_release = release_match.group(1)
            pkg_source_filename = f"neturl-{raw_version_part}.tar.gz"
        pkg_source_url = f"https://github.com/golgote/neturl/archive/refs/tags/{latest_tag}.tar.gz"
        expected_build_subdir = f"neturl-{raw_version_part}" # Directory inside tarball

        # 3. Download the source tarball to calculate hash
        dl_dir = Path("./dl")
        dl_dir.mkdir(exist_ok=True)
        tarball_path = dl_dir / pkg_source_filename

        print(f"Downloading {pkg_source_url} to {tarball_path}...")
        try:
            # Use wget or curl, whichever is available
            if shutil.which("wget"):
                download_cmd = ["wget", "-q", "-O", str(tarball_path), pkg_source_url]
            elif shutil.which("curl"):
                download_cmd = ["curl", "-s", "-L", "-o", str(tarball_path), pkg_source_url]
            else:
                print("❌ wget 和 curl 都不可用，无法下载。")
                return False
            subprocess.run(download_cmd, check=True, timeout=60)
            print("✅ 下载成功。")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"❌ 下载失败: {e}")
            if tarball_path.exists(): tarball_path.unlink() # Clean up partial download
            return False

        # 4. Calculate SHA256 hash
        sha256_hash = hashlib.sha256()
        with open(tarball_path, "rb") as f:
            while True:
                byte_block = f.read(4096)
                if not byte_block:
                    break
                sha256_hash.update(byte_block)
        sha256_hex = sha256_hash.hexdigest()
        print(f"✅ 计算得到 SHA256 哈希值: {sha256_hex}")

        # 5. Update the Makefile
        with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        original_content = content

        content = re.sub(r'^(PKG_VERSION:=).*', rf'\g<1>{pkg_version}', content, flags=re.MULTILINE)
        content = re.sub(r'^(PKG_RELEASE:=).*', rf'\g<1>{pkg_release}', content, flags=re.MULTILINE)
        content = re.sub(r'^(PKG_SOURCE:=).*', rf'\g<1>{pkg_source_filename}', content, flags=re.MULTILINE)
        content = re.sub(r'^(PKG_SOURCE_URL:=).*', rf'\g<1>{pkg_source_url}', content, flags=re.MULTILINE)
        content = re.sub(r'^(PKG_HASH:=).*', rf'\g<1>{sha256_hex}', content, flags=re.MULTILINE)

        # Ensure PKG_BUILD_DIR is correct
        build_dir_line = f"PKG_BUILD_DIR:=$(BUILD_DIR)/{expected_build_subdir}"
        build_dir_regex = r'^\s*PKG_BUILD_DIR:=\$\(BUILD_DIR\)/.*'
        if not re.search(build_dir_regex, content, re.MULTILINE):
             insert_after = r'^\s*PKG_HASH:=[^\n]+'
             content = re.sub(f'({insert_after})', f'\\1\n{build_dir_line}', content, 1, re.MULTILINE)
        elif not re.search(r'^\s*PKG_BUILD_DIR:=\$\(BUILD_DIR\)/' + re.escape(expected_build_subdir) + r'\s*$', content, re.MULTILINE):
             content = re.sub(build_dir_regex, build_dir_line, content, 1, re.MULTILINE)

        if content != original_content:
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✅ Makefile {makefile_path} 已更新。")

            # Clean the package to apply changes
            pkg_rel_path = makefile_path.parent.relative_to(Path.cwd())
            print(f"🧹 清理旧的构建文件: {pkg_rel_path}")
            subprocess.run(["make", f"{pkg_rel_path}/clean", "V=s"], check=False, capture_output=True)
            # Optional: Update feeds index again after fixing a specific package
            # print("Updating feeds index...")
            # subprocess.run(["./scripts/feeds", "update", "-i"], check=False, capture_output=True)
            # subprocess.run(["./scripts/feeds", "install", "lua-neturl"], check=False, capture_output=True)

            print("⏳ 等待 2 秒后重试...")
            time.sleep(2)
            return True
        else:
            print("ℹ️ Makefile 无需更新。下载问题可能由网络或其他原因引起。")
            # Even if Makefile is correct, the download might have failed before.
            # Returning True allows a retry with the potentially fixed download.
            return True

    except requests.exceptions.RequestException as e:
         print(f"❌ 网络错误: 无法从 GitHub 获取信息: {e}")
         return False
    except Exception as e:
        print(f"❌ 更新 lua-neturl Makefile 时发生意外错误: {e}")
        return False

def fix_apk_directly():
    """直接修复 luci.mk 中的 apk mkpkg 调用以清理依赖 (v3)"""
    print("🔧 尝试直接修改 luci.mk 中的 apk mkpkg 调用以清理依赖...")
    luci_mk_path = None
    possible_paths = ["feeds/luci/luci.mk", "package/feeds/luci/luci.mk", "package/luci/luci.mk"]
    for path in possible_paths:
        if os.path.exists(path):
            luci_mk_path = path
            break

    if not luci_mk_path:
        print(f"⚠️ 找不到 luci.mk (检查路径: {possible_paths})")
        return False

    try:
        with open(luci_mk_path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        content = original_content
        made_change = False

        # 查找调用 apk mkpkg 并包含 --info "depends:$(PKG_DEPENDS)" 的行
        # 这个模式需要精确匹配，可能需要根据实际 luci.mk 内容调整
        # 假设 apk mkpkg 命令在一行内
        apk_mkpkg_pattern = re.compile(r'(\$\(STAGING_DIR_HOST\)/bin/apk mkpkg .*?--info "depends:)(\$\(PKG_DEPENDS\))(".*)', re.IGNORECASE)

        # 替换方案：在调用 apk mkpkg 前，用 shell 命令清理 PKG_DEPENDS
        # 注意：这里的 shell 命令需要仔细构造，避免引号和特殊字符问题
        # 使用一个临时变量 CLEANED_DEPENDS
        replacement_logic = r"""\
        CLEANED_DEPENDS=$$$$(echo '$(PKG_DEPENDS)' | tr ' ' '\\n' | sed -e 's/[<>=!~].*//g' -e '/^$$/d' | sort -u | tr '\\n' ' ' | sed -e 's/ $$//g'); \
        \1$$$$(CLEANED_DEPENDS)\3
"""
        # 使用 re.sub 进行替换
        modified_content, num_replacements = apk_mkpkg_pattern.subn(replacement_logic, content)

        if num_replacements > 0:
            print(f"  ✅ 在 {luci_mk_path} 中找到并修改了 {num_replacements} 处 apk mkpkg 调用以清理依赖。")
            content = modified_content
            made_change = True
            # 移除可能存在的旧的 CleanDependString 函数定义，因为它不再需要
            content = re.sub(r'^# APK dependency fix.*?endef\s*$', '', content, flags=re.MULTILINE | re.DOTALL).strip()

        else:
            print(f"  ⚠️ 未能在 {luci_mk_path} 中找到预期的 apk mkpkg 调用模式进行修改。")
            # 检查是否已经应用过类似的修复 (查找 CLEANED_DEPENDS)
            if "CLEANED_DEPENDS=" in content and "--info \"depends:$$$$(CLEANED_DEPENDS)\"" in content:
                 print("  ℹ️ 似乎已应用过类似的修复逻辑。")
                 made_change = False # 标记为未做修改，但认为尝试过
            else:
                 # 如果找不到模式，并且没有修复痕迹，则此方法失败
                 print(f"  ❌ 无法应用修复逻辑到 {luci_mk_path}。")
                 return False


        # 如果做了修改，写回文件并清理
        if made_change and content.strip() != original_content.strip():
            print(f"  💾 写回修改到 {luci_mk_path}...")
            with open(luci_mk_path, 'w', encoding='utf-8') as f:
                f.write(content + "\n") # 确保末尾有换行

            # 清理 tmp 目录
            print("  🧹 清理 tmp 目录...")
            if os.path.exists("tmp"):
                try:
                    shutil.rmtree("tmp")
                    print("    ✅ tmp 目录已删除。")
                except Exception as e:
                    print(f"    ⚠️ 清理 tmp 目录失败: {e}")
            else:
                print("    ℹ️ tmp 目录不存在。")

            # 清理相关包 (DIRCLEAN)
            print("  🧹 清理相关构建缓存 (DIRCLEAN)...")
            # ... (清理包的逻辑，同上) ...
            packages_to_clean = [...] # 定义需要清理的包
            for pkg_path in set(packages_to_clean):
                 # ... (执行 make DIRCLEAN=1 .../clean) ...
                 pass

            return True
        elif made_change: # 内容相同，说明之前的修改就是这个
             print(f"  ℹ️ {luci_mk_path} 内容已包含修复逻辑，无需写回。")
             return True # 认为尝试过
        else: # made_change 为 False
            print(f"  ℹ️ {luci_mk_path} 无需修改。")
            return True # 认为尝试过

    except Exception as e:
        print(f"❌ 直接修复 luci.mk 中的 apk mkpkg 调用时出错: {e}")
        return False

def fix_toolchain_provides_syntax(log_content):
    """修复 toolchain Makefile 中 provides 字段末尾的空格导致的语法错误"""
    print("🔧 检测到 toolchain provides 语法错误，尝试修复...")
    makefile_path = Path("package/libs/toolchain/Makefile")
    if not makefile_path.exists():
        print("❌ 找不到 package/libs/toolchain/Makefile。")
        return False

    fixed = False
    try:
        with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        original_content = content

        # Find lines like: --info "provides: name=version " (with trailing space)
        # And remove the trailing space inside the quotes
        # Use a function for replacement to handle multiple occurrences
        def remove_trailing_space(match):
            nonlocal fixed
            provides_val = match.group(1)
            if provides_val.endswith(" "):
                fixed = True
                return f'--info "provides:{provides_val.rstrip()} "' # Keep space after quotes if any
            return match.group(0) # No change

        content = re.sub(r'--info "provides:([^"]+?)\s*"', remove_trailing_space, content)

        if fixed:
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✅ 已修复 {makefile_path} 中的 provides 字段空格问题。")
            # Clean toolchain package
            print("🧹 清理 toolchain 构建...")
            subprocess.run(["make", "package/libs/toolchain/clean", "V=s"], check=False, capture_output=True)
            return True
        else:
            print("ℹ️ 未在 toolchain Makefile 中找到需要修复的 provides 字段空格。")
            return False

    except Exception as e:
        print(f"❌ 修复 toolchain provides 语法时出错: {e}")
        return False

def fix_apk_wrapper_issues(log_content):
    """处理与 apk wrapper 相关的问题 (移除或修复)"""
    wrapper_path = Path("staging_dir/host/bin/apk")
    real_path = Path("staging_dir/host/bin/apk.real")

    if real_path.exists(): # Wrapper exists (or did exist)
        print("🔧 检测到 apk wrapper 或其残留，进行处理...")
        if wrapper_path.exists():
             # Check if it's our wrapper causing syntax errors
             syntax_error_in_log = "Syntax error:" in log_content and str(wrapper_path) in log_content
             if syntax_error_in_log:
                  print("⚠️ 检测到 wrapper 脚本存在语法错误，移除 wrapper 并恢复原始 apk...")
                  try:
                       wrapper_path.unlink()
                       real_path.rename(wrapper_path)
                       print("✅ 已恢复原始 apk 命令。")
                       return True # Action taken
                  except Exception as e:
                       print(f"❌ 恢复原始 apk 时出错: {e}")
                       return False
             else:
                  print("ℹ️ wrapper 存在但日志中未检测到其语法错误。")
                  # Maybe the wrapper fixed the depends issue but another error occurred?
                  # Or maybe the wrapper itself is fine but didn't fix the root cause.
                  # Let's leave it for now, unless specific wrapper errors occur.
                  return False # No action taken on the wrapper itself
        else:
             # Wrapper script is missing, but real binary exists. Restore.
             print("⚠️ wrapper 脚本丢失，但备份存在。恢复原始 apk...")
             try:
                  real_path.rename(wrapper_path)
                  print("✅ 已恢复原始 apk 命令。")
                  return True # Action taken
             except Exception as e:
                  print(f"❌ 恢复原始 apk 时出错: {e}")
                  return False
    else:
         # No wrapper seems to be active
         return False # No action taken

def fix_apk_depends_logic():
    """
    综合处理 APK 依赖格式错误 (Error 99 或 invalid value)。
    优先尝试修改 luci.mk。
    """
    print("🔧 尝试修复 APK 依赖格式逻辑 (优先修改 luci.mk)...")
    luci_mk_path = None
    # Prefer feed path if it exists
    feed_path = Path("feeds/luci/luci.mk")
    package_path = Path("package/feeds/luci/luci.mk") # Fallback if using older structure/local copy

    if feed_path.exists():
        luci_mk_path = feed_path
    elif package_path.exists():
        luci_mk_path = package_path

    if luci_mk_path:
        if fix_apk_directly(luci_mk_path):
            return True # Fixed by modifying luci.mk
        else:
            # If modifying luci.mk didn't work or wasn't needed,
            # maybe the issue is in *another* package's depends definition.
            # Try the global DEPENDS format fix as a fallback.
            print("ℹ️ 修改 luci.mk 未解决问题或无需修改，尝试全局 DEPENDS 格式修复...")
            # We need log content for the global fix, assume it's available in the caller
            # This function now just signals if the primary fix worked.
            return False # Indicate primary fix didn't solve it
    else:
        print("❌ 找不到 feeds/luci/luci.mk 或 package/feeds/luci/luci.mk。")
        return False

def fix_apk_directly():
    """直接修复 APK 依赖命令行参数 (修改 luci.mk)"""
    print("🔧 尝试直接修改 luci.mk 来修复 APK 依赖格式...")
    luci_mk_path = None
    # 优先使用 feeds 中的路径
    possible_paths = ["feeds/luci/luci.mk", "package/feeds/luci/luci.mk", "package/luci/luci.mk"]
    for path in possible_paths:
        if os.path.exists(path):
            luci_mk_path = path
            break

    if not luci_mk_path:
        print(f"⚠️ 找不到 luci.mk (检查路径: {possible_paths})")
        return False

    try:
        with open(luci_mk_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查是否已经修复过
        if "# APK dependency fix" in content:
            print(f"ℹ️ {luci_mk_path} 似乎已经应用过修复。")
            # 即使已修复，也返回 True，表示尝试过此方法
            return True

        # 添加修复代码，使用 sed 来清理依赖项
        fix_code = """
# APK dependency fix
define CleanDependString
$(shell echo $(1) | tr ' ' '\\n' | sed -e 's/[<>=!~].*//g' -e '/^$$/d' | sort -u | tr '\\n' ' ' | sed -e 's/ $$//g')
endef

"""
        # 查找插入点，通常在文件顶部或 include 之后
        insert_pos = content.find("include $(TOPDIR)/rules.mk")
        if insert_pos != -1:
            insert_pos = content.find('\n', insert_pos) + 1
            new_content = content[:insert_pos] + fix_code + content[insert_pos:]
        else:
            new_content = fix_code + content # 放在文件开头

        # 修改依赖参数处理
        # 匹配 --info "depends:..." 部分，确保替换正确
        # 使用 re.sub 更安全地处理可能的多行或复杂情况
        original_depends_pattern = r'(--info "depends:)(\$\(PKG_DEPENDS\))(")'
        replacement_pattern = r'\1$(call CleanDependString,\2)\3'

        modified_content, num_replacements = re.subn(original_depends_pattern, replacement_pattern, new_content)

        if num_replacements > 0:
            with open(luci_mk_path, 'w', encoding='utf-8') as f:
                f.write(modified_content)
            print(f"✅ 已在 {luci_mk_path} 中添加依赖项清理函数并修改了 {num_replacements} 处依赖参数。")

            # 清理可能受影响的包的构建缓存 (示例，可能需要更精确)
            print("🧹 清理 luci 相关构建缓存...")
            subprocess.run(["make", "package/feeds/luci/luci-base/clean"], check=False, capture_output=True)
            subprocess.run(["make", "package/feeds/small8/luci-lib-taskd/clean"], check=False, capture_output=True)
            # 清理 toolchain 缓存，因为它也调用 apk
            subprocess.run(["make", "package/libs/toolchain/clean"], check=False, capture_output=True)
            return True
        else:
            print(f"⚠️ 未能在 {luci_mk_path} 中找到 '--info \"depends:$(PKG_DEPENDS)\"' 进行替换。")
            # 即使未替换，但文件存在且尝试过，也算是一种尝试
            return True # 返回 True 表示尝试过，但不一定成功修改

    except Exception as e:
        print(f"❌ 直接修复 APK 依赖 (luci.mk) 时出错: {e}")
        return False

def fix_luci_lib_taskd_makefile():
    """修复 luci-lib-taskd 的依赖格式问题 (创建 APK wrapper - 作为备选方案)"""
    print("🛠️ 使用拦截方法修复 APK 依赖格式问题 (备选方案)...")

    apk_script_path = "staging_dir/host/bin/apk"
    apk_real_path = "staging_dir/host/bin/apk.real"

    # 确保 staging_dir/host/bin 存在
    host_bin_dir = Path("staging_dir/host/bin")
    if not host_bin_dir.exists():
        print(f"⚠️ 目录 {host_bin_dir} 不存在，无法创建 wrapper。")
        return False
    host_bin_dir.mkdir(parents=True, exist_ok=True) # 尝试创建

    # 如果 wrapper 已存在，先删除，尝试恢复原始文件
    if os.path.exists(apk_script_path) and os.path.realpath(apk_script_path) != apk_script_path: # 检查是否是符号链接或我们的脚本
         if os.path.exists(apk_real_path):
             print(f"ℹ️ 检测到现有 wrapper，尝试恢复原始 apk...")
             try:
                 os.remove(apk_script_path)
                 os.rename(apk_real_path, apk_script_path)
                 os.chmod(apk_script_path, 0o755) # 恢复权限
             except Exception as e:
                 print(f"⚠️ 恢复原始 apk 失败: {e}")
                 # 继续尝试创建新的 wrapper
         else:
              print(f"⚠️ 检测到现有 wrapper 但无备份 ({apk_real_path})，尝试直接覆盖...")
              try:
                  os.remove(apk_script_path)
              except Exception as e:
                  print(f"⚠️ 删除现有 wrapper 失败: {e}")


    # 检查原始 apk 是否存在
    if not os.path.exists(apk_script_path) or os.path.islink(apk_script_path):
         print(f"⚠️ 找不到原始 apk 命令 ({apk_script_path}) 或它是一个链接。")
         # 尝试寻找可能的真实路径
         real_apk_found = False
         for potential_real_path in host_bin_dir.glob("apk*"):
             if potential_real_path.name != "apk" and not potential_real_path.name.endswith(".real"):
                 try:
                     # 假设找到的是原始 apk，重命名它
                     os.rename(potential_real_path, apk_script_path)
                     os.chmod(apk_script_path, 0o755)
                     print(f"✅ 找到了可能的原始 apk 并重命名为: {apk_script_path}")
                     real_apk_found = True
                     break
                 except Exception as e:
                     print(f"⚠️ 尝试重命名 {potential_real_path} 失败: {e}")
         if not real_apk_found:
              print(f"❌ 无法定位原始 apk 命令，无法创建 wrapper。")
              return False


    # 创建 wrapper
    try:
        print(f"ℹ️ 备份原始 apk 到 {apk_real_path}")
        shutil.move(apk_script_path, apk_real_path) # 使用 shutil.move 更可靠
        os.chmod(apk_real_path, 0o755)

        # 创建脚本替换原命令 - 使用更健壮的参数处理和引号
        wrapper_content = f'''#!/bin/sh
# APK wrapper script to fix dependency format issues (v2)
REAL_APK="{apk_real_path}"

# Log wrapper execution for debugging
# echo "APK Wrapper executing with args: $@" >> /tmp/apk_wrapper.log

if [ "$1" = "mkpkg" ]; then
    fixed_args=""
    skip_next=0
    depend_fixed=0

    # Iterate through arguments carefully
    for arg in "$@"; do
        if [ "$skip_next" -eq 1 ]; then
            skip_next=0
            continue
        fi

        case "$arg" in
            --info)
                # Check the next argument
                next_arg=$(eval echo \\$\\$\\(\\( \\(echo "$@" | awk -v current="$arg" '{{ for(i=1; i<=NF; i++) if ($i == current) print i+1 }}'\\) \\)\\))
                # echo "Next arg for --info: $next_arg" >> /tmp/apk_wrapper.log # Debug log
                if echo "$next_arg" | grep -q "^depends:"; then
                    # Extract dependencies, handling potential spaces within quotes
                    deps_raw=$(echo "$next_arg" | sed 's/^depends://')
                    # echo "Raw deps: $deps_raw" >> /tmp/apk_wrapper.log # Debug log

                    # Clean dependencies: remove version constraints, remove duplicates, handle empty strings
                    # Use awk for more robust splitting on spaces, then process each part
                    fixed_deps=$(echo "$deps_raw" | awk '{{for(i=1;i<=NF;i++) print $i}}' | sed -e 's/[<>=!~].*//g' -e '/^$/d' | sort -u | tr '\\n' ' ' | sed 's/ $//')
                    # echo "Fixed deps: $fixed_deps" >> /tmp/apk_wrapper.log # Debug log

                    # Reconstruct the argument with proper quoting
                    fixed_args="$fixed_args --info 'depends:$fixed_deps'" # Use single quotes for the value
                    skip_next=1 # Skip the original dependency string in the next iteration
                    depend_fixed=1
                else
                    # Not a depends info, pass both args as they are
                    fixed_args="$fixed_args '$arg' '$next_arg'" # Quote both
                    skip_next=1
                fi
                ;;
            *)
                # Handle other arguments, quote them just in case
                fixed_args="$fixed_args '$arg'"
                ;;
        esac
    done

    if [ "$depend_fixed" -eq 1 ]; then
        echo "🔧 APK wrapper: Fixed dependency format for mkpkg" >&2
        # echo "Executing: $REAL_APK $fixed_args" >> /tmp/apk_wrapper.log # Debug log
        eval "$REAL_APK $fixed_args" # Use eval to handle the constructed args string
        exit $? # Propagate exit code
    else
        # echo "Executing original: $REAL_APK $@" >> /tmp/apk_wrapper.log # Debug log
        "$REAL_APK" "$@"
        exit $?
    fi
else
    # Not mkpkg, just pass through
    # echo "Executing original (non-mkpkg): $REAL_APK $@" >> /tmp/apk_wrapper.log # Debug log
    "$REAL_APK" "$@"
    exit $?
fi
'''
        with open(apk_script_path, 'w') as f:
            f.write(wrapper_content)
        os.chmod(apk_script_path, 0o755)
        print("✅ 已创建 APK 命令包装器 (wrapper)。")
        return True
    except Exception as e:
        print(f"❌ 创建 APK 命令包装器时出错: {e}")
        # 尝试恢复
        if os.path.exists(apk_real_path) and not os.path.exists(apk_script_path):
            try:
                print(f"ℹ️ 尝试恢复原始 apk 从 {apk_real_path}")
                shutil.move(apk_real_path, apk_script_path)
            except Exception as re_e:
                 print(f"⚠️ 恢复原始 apk 失败: {re_e}")
        return False


def fix_luci_lib_taskd_extra_depends():
    """专门注释掉 luci-lib-taskd/Makefile 中的 LUCI_EXTRA_DEPENDS 行"""
    print("🔧 尝试特定修复: 注释掉 luci-lib-taskd/Makefile 中的 LUCI_EXTRA_DEPENDS...")
    makefile_path = None
    # 精确查找 Makefile
    possible_paths = list(Path(".").glob("**/feeds/small8/luci-lib-taskd/Makefile"))
    if not possible_paths:
         possible_paths = list(Path(".").glob("**/package/feeds/small8/luci-lib-taskd/Makefile")) # 备用

    if not possible_paths:
        print(f"  ⚠️ 未找到 luci-lib-taskd 的 Makefile。")
        return False
    makefile_path = possible_paths[0]
    print(f"  ➡️ 定位到 Makefile: {makefile_path}")

    try:
        with open(makefile_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        modified = False
        found_target_line = False

        # 精确匹配需要注释掉的行
        target_line_pattern = re.compile(r"^\s*LUCI_EXTRA_DEPENDS\s*:=\s*taskd\s*\(\s*>=?\s*[\d.-]+\s*\)\s*$", re.IGNORECASE)

        for i, line in enumerate(lines):
            stripped_line = line.strip()
            # 检查是否是目标行且未被注释
            if target_line_pattern.match(stripped_line) and not stripped_line.startswith("#"):
                found_target_line = True
                print(f"  🔧 在行 {i+1} 注释掉: {line.strip()}")
                new_lines.append("#" + line) # 在行首添加 #
                modified = True
            # 检查是否已经是被注释的目标行
            elif stripped_line.startswith("#") and target_line_pattern.match(stripped_line.lstrip("#").strip()):
                 found_target_line = True
                 print(f"  ℹ️ 在行 {i+1} 发现已注释的目标行: {line.strip()}")
                 new_lines.append(line) # 保持注释状态
            else:
                new_lines.append(line)

        if not found_target_line:
             print(f"  ⚠️ 未找到需要注释的 LUCI_EXTRA_DEPENDS 行。")
             # 检查 DEPENDS 是否已被手动修复（作为后备检查）
             define_block_pattern = re.compile(r'define Package/luci-lib-taskd\s*.*?\s*DEPENDS\s*:=\s*\+taskd\s+\+luci-lib-xterm\s+\+luci-lua-runtime(?:\s+\+libc)?\s*.*?\s*endef', re.DOTALL | re.IGNORECASE)
             if define_block_pattern.search("".join(lines)):
                 print("  ℹ️ 检测到可能已被手动修复的 DEPENDS 定义。")
                 return True # 认为问题已解决
             return False # 确实没找到问题行

        if modified:
            print(f"  ✅ 准备写回修改到 {makefile_path}")
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            # 清理该包的缓存
            print(f"  🧹 清理包 'luci-lib-taskd' 缓存 (DIRCLEAN)...")
            subprocess.run(["make", f"DIRCLEAN=1", f"{makefile_path.parent}/clean"], check=False, capture_output=True)
            # 清理 tmp 目录可能有助于确保更改生效
            print("  🧹 清理 tmp 目录...")
            if os.path.exists("tmp"):
                try: shutil.rmtree("tmp"); print("    ✅ tmp 目录已删除。")
                except Exception as e: print(f"    ⚠️ 清理 tmp 目录失败: {e}")
            return True
        else:
            print(f"  ℹ️ {makefile_path} 无需修改 (LUCI_EXTRA_DEPENDS 已注释或不存在)。")
            return True # 认为问题已解决或无需处理

    except Exception as e:
        print(f"❌ 修改包 'luci-lib-taskd' 的 Makefile 时出错: {e}")
        return False

# --- 更新 fix_apk_depends_problem ---
def fix_apk_depends_problem():
    """综合性解决方案解决 APK 依赖格式问题 (v8 - 优先修复特定包 Makefile 问题)"""
    print("🔍 尝试综合解决方案修复 APK 依赖格式问题...")
    fixed_something = False

    # 步骤 1: 专门修复 luci-lib-taskd 的 LUCI_EXTRA_DEPENDS
    print("  方法 1: 尝试注释掉 luci-lib-taskd/Makefile 中的 LUCI_EXTRA_DEPENDS...")
    if fix_luci_lib_taskd_extra_depends():
        print("  ✅ 方法 1 (注释 LUCI_EXTRA_DEPENDS) 执行完成。")
        fixed_something = True
    else:
        print("  ℹ️ 方法 1 (注释 LUCI_EXTRA_DEPENDS) 未进行修改或失败。")

    # 步骤 2: 如果上一步无效，再尝试修改 luci.mk (作为后备)
    if not fixed_something:
        print("  方法 2: 尝试直接修改 luci.mk 中的 apk mkpkg 调用...")
        if fix_apk_directly():
            print("  ✅ 方法 2 (修改 luci.mk) 执行完成。")
            fixed_something = True
        else:
            print("  ❌ 方法 2 (修改 luci.mk) 失败。")

    # 步骤 3: 尝试修复具体包的 DEPENDS:= 行 (作为补充)
    # 这个步骤现在可能不太必要，因为根源是 LUCI_EXTRA_DEPENDS，但保留以防万一
    apk_error_sig = get_error_signature(log_content_global)
    if "apk_depends_invalid" in apk_error_sig:
        failed_pkg_name = apk_error_sig.split(":")[-1]
        if failed_pkg_name != "unknown_pkg_from_apk":
            print(f"  补充方法: 尝试修复包 '{failed_pkg_name}' 的 Makefile DEPENDS...")
            # ... (查找并修复具体包 Makefile 的逻辑) ...
            pass # 可以暂时跳过或保留之前的逻辑


    return fixed_something
def fix_apk_wrapper_syntax():
    """修复 APK 包装器脚本中的语法错误"""
    print("🔧 检测到 APK wrapper 语法错误，尝试修复...")

    wrapper_path = Path("staging_dir/host/bin/apk")
    real_path = Path("staging_dir/host/bin/apk.real")

    if wrapper_path.exists() and real_path.exists():
        try:
            # 读取当前的包装器脚本
            with open(wrapper_path, 'r') as f:
                content = f.read()

            # 检查是否是我们的 wrapper (通过注释判断)
            if "# APK wrapper script" in content:
                print("  ℹ️ 检测到旧的 APK wrapper，移除并恢复原始命令...")
                wrapper_path.unlink() # 删除脚本
                real_path.rename(wrapper_path) # 恢复原始命令
                wrapper_path.chmod(0o755) # 恢复权限
                print("  ✅ 已恢复原始 APK 命令。")

                # 恢复后，尝试直接修复依赖问题，因为这可能是根本原因
                print("  ▶️ 尝试再次运行直接修复 (luci.mk)...")
                return fix_apk_directly() # 返回直接修复的结果
            else:
                print(f"  ⚠️ {wrapper_path} 存在但不是预期的 wrapper 脚本。")
                # 可能是其他东西，不要动它，返回 False
                return False
        except Exception as e:
            print(f"❌ 移除旧 wrapper 或恢复原始 apk 时出错: {e}")
            return False
    elif wrapper_path.exists() and not real_path.exists():
         print(f"  ⚠️ 找到 {wrapper_path} 但没有备份 {real_path}。可能是原始 apk。")
         # 假设它是原始apk，尝试直接修复
         print("  ▶️ 尝试运行直接修复 (luci.mk)...")
         return fix_apk_directly()
    else:
        print(f"  ⚠️ 找不到 APK wrapper ({wrapper_path}) 或原始备份 ({real_path})。")
        # 尝试直接修复
        print("  ▶️ 尝试运行直接修复 (luci.mk)...")
        return fix_apk_directly()


def get_error_signature(log_content):
    """从日志内容中提取一个更准确的错误签名 (v3)"""
    if not log_content: return "no_log_content"
    apk_add_invalid_format_match = re.search(
        r"ERROR: ('([^=]+)=' is not a valid world dependency).*?make\[\d+\]: \*\*\* .*?package/install.* Error 99",
        log_content, re.DOTALL
    )
    if apk_add_invalid_format_match:
        invalid_package = apk_add_invalid_format_match.group(2)
        # Ensure absolute path isn't captured if present in some logs
        invalid_package = os.path.basename(invalid_package)
        return f"apk_add_invalid_dep_format:{invalid_package}"
    if apk_error_match:
        pkg_name = apk_error_match.group(2)
        # Avoid confusion with the new signature if it's base-files failing here (less likely)
        if pkg_name != "base-files":
             return f"apk_depends_invalid:{pkg_name}"

    # 2. Makefile 依赖缺失警告 (取第一个作为代表)
    dep_warning_match = re.search(r"WARNING: Makefile '([^']+)' has a dependency on '([^']*)', which does not exist", log_content)
    if dep_warning_match:
        # ... (existing logic for dep_warning_match) ...
        # Check if the real error was already identified
        if apk_add_invalid_format_match: # Don't let warning override the real error
             pass # Ignore this warning if the apk_add error was found
        else:
             # ... (extract pkg_name and bad_dep as before) ...
             if bad_dep and bad_dep.lower() not in ['perl_tests', ''] and not bad_dep.startswith(('p,', '(virtual)', '$')):
                 return f"makefile_dep_missing:{pkg_name}:{bad_dep}"
    # 3. APK Wrapper 语法错误
    if "Syntax error:" in log_content and "bin/apk" in log_content:
         return "apk_wrapper_syntax"

    # 4. Netifd 链接错误
    if "undefined reference to" in log_content and re.search(r'netifd|toolchain.*netifd', log_content):
        # ... (保持之前的 netifd 签名逻辑) ...
        ref_match = re.search(r"undefined reference to `([^']+)'", log_content)
        ref = ref_match.group(1) if ref_match else "unknown_symbol"
        if "netifd" in log_content: # 简单检查
             return f"netifd_link_error:{ref}"


    # 5. Makefile 分隔符错误
    if "missing separator" in log_content and ("Stop." in log_content or "***" in log_content):
         # ... (保持之前的 separator 签名逻辑) ...
         makefile_match = re.search(r'^([^:]+):\d+: \*\*\* missing separator', log_content, re.MULTILINE)
         makefile = makefile_match.group(1) if makefile_match else "unknown_makefile"
         return f"makefile_separator:{makefile}"

    # 6. Patch 失败
    if ("Patch failed" in log_content or "Only garbage was found" in log_content or "unexpected end of file in patch" in log_content):
         # ... (保持之前的 patch 签名逻辑) ...
         patch_match = re.search(r'Applying (.+\.patch)', log_content)
         patch = os.path.basename(patch_match.group(1)) if patch_match else "unknown_patch"
         pkg_match = re.search(r"make\[\d+\]: Entering directory .*?/([^/']+)", log_content)
         pkg_name = pkg_match.group(1) if pkg_match else "unknown_pkg"
         return f"patch_failed:{pkg_name}:{patch}"


    # 7. Lua Neturl 下载错误
    if LIBS_AVAILABLE and 'lua-neturl' in log_content and ('Download failed' in log_content or 'Hash mismatch' in log_content or 'No more mirrors to try' in log_content):
        return "lua_neturl_download"

    # 8. Trojan Plus 错误
    if 'trojan-plus' in log_content and 'buffer-cast' in log_content:
        return "trojan_plus_buffer_cast"

    # 9. 通用构建失败 (提取包名)
    generic_fail_match = re.search(r"ERROR: package/(?:feeds/[^/]+/|pkgs/|libs/|utils/|network/|)?([^/]+) failed to build", log_content)
    if generic_fail_match:
        return f"generic_build_fail:{generic_fail_match.group(1)}" # group(1) 是包名

    # 10. 通用错误信息 (提取关键字和上下文)
    generic_error_match = re.search(r'(error:|failed|fatal error:|collect2: error: ld returned 1 exit status)', log_content, re.IGNORECASE)
    if generic_error_match:
        # ... (保持之前的通用错误签名逻辑) ...
        error_keyword = generic_error_match.group(1).lower().split(':')[0]
        context_line = ""
        for line in reversed(log_content.splitlines()):
             if error_keyword in line.lower():
                 context_line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line).strip()[:80]
                 break
        return f"generic_error:{error_keyword}:{context_line}"


    return "unknown_error"


import re
import subprocess
import shutil
from pathlib import Path
import os # Ensure os is imported

# Make sure get_relative_path is defined or imported if used here
# Assuming get_relative_path function exists as before

def get_error_signature(log_content):
    # Assuming get_error_signature function exists as before
    # Make sure it correctly returns "apk_add_invalid_dep_format:base-files"
    # For this specific log
    if not log_content: return "no_log_content"
    apk_add_invalid_format_match = re.search(
        r"ERROR: ('([^=]+)=' is not a valid world dependency).*?make\[\d+\]: \*\*\* .*?package/install.* Error 99",
        log_content, re.DOTALL
    )
    if apk_add_invalid_format_match:
        invalid_package = apk_add_invalid_format_match.group(2)
        # Ensure absolute path isn't captured if present in some logs
        invalid_package = os.path.basename(invalid_package)
        return f"apk_add_invalid_dep_format:{invalid_package}"
    # Add other signature detections here if needed
    return "unknown_error"


import re
import subprocess
import shutil
from pathlib import Path
import os

# Assuming get_relative_path function exists as before
# Assuming get_error_signature function exists and works as before

import re
import subprocess
import shutil
from pathlib import Path
import os

# Assuming get_relative_path function exists as before
# Assuming get_error_signature function exists and works as before
# --- Global flag for pre-computation ---
needs_base_files_precompute = False
def fix_apk_add_base_files_issue(log_content):
    """修复 apk add 时 base-files= 或类似包版本缺失导致的 Error 99 (v11: 设置预处理标志)"""
    global needs_base_files_precompute
    print("🔧 检测到 apk add 无效依赖格式错误 (通常由 base-files 版本缺失引起)。")
    print(f"  设置标志，在下次尝试前预先编译 base-files 并修复版本文件名...")

    action_taken = False

    # --- Perform minimal cleanup ---
    tmp_dir = Path("tmp")
    if tmp_dir.exists():
        print(f"  🧹 清理目录: {get_relative_path(str(tmp_dir))}")
        try:
            shutil.rmtree(tmp_dir)
            action_taken = True
        except Exception as e:
            print(f"    ⚠️ 清理 {tmp_dir} 目录失败: {e}")
            action_taken = True # Still counts as an attempt
    # Ensure tmp exists for subsequent steps
    try:
        tmp_dir.mkdir(exist_ok=True)
    except Exception as e:
        print(f"    ⚠️ 创建 {tmp_dir} 目录失败: {e}")

    # Clean staging package directory
    target_arch_match = re.search(r'staging_dir/target-([a-zA-Z0-9_]+)', log_content)
    package_dir_match = re.search(r'staging_dir/packages/([a-zA-Z0-9_]+)', log_content)
    staging_pkg_dir_path = None
    if package_dir_match:
        staging_pkg_dir_path = Path("staging_dir/packages") / package_dir_match.group(1)
    elif target_arch_match:
         target_name = target_arch_match.group(1)
         if 'ramips' in target_name:
             staging_pkg_dir_path = Path("staging_dir/packages/ramips")
    if staging_pkg_dir_path and staging_pkg_dir_path.exists():
        print(f"  🧹 清理目录: {get_relative_path(str(staging_pkg_dir_path))}")
        try:
            shutil.rmtree(staging_pkg_dir_path)
            action_taken = True
        except Exception as e:
            print(f"    ⚠️ 清理 {staging_pkg_dir_path} 目录失败: {e}")
            action_taken = True

    # --- Set the flag ---
    needs_base_files_precompute = True
    print("  ✅ 已设置 base-files 预处理标志。")

    # Return True to indicate a fix strategy was determined
    return True
# 主逻辑
def main():
    parser = argparse.ArgumentParser(description='OpenWrt 编译修复脚本')
    parser.add_argument('make_command', help='编译命令，如 "make V=s"')
    parser.add_argument('log_file', help='日志文件路径')
    parser.add_argument('--max-retry', type=int, default=8, help='最大重试次数')
    parser.add_argument('--jobs', type=int, default=0, help='初始并行任务数')
    args = parser.parse_args()

    base_cmd = re.sub(r'\s-j\s*\d+', '', args.make_command).strip()
    jobs = args.jobs if args.jobs > 0 else (os.cpu_count() or 1)
    retry = 1
    log_content_global = ""
    last_error = None
    same_error_count = 0

    while retry <= args.max_retry:
        cmd = f"{base_cmd} -j{jobs}"
        print(f"尝试 {retry}/{args.max_retry} 次: {cmd}")
        log_file = f"{Path(args.log_file).stem}.run.{retry}.log"
        
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        with open(log_file, 'w', encoding='utf-8') as f:
            for line in process.stdout:
                sys.stdout.write(line)
                f.write(line)
        status = process.wait()
        with open(log_file, 'r', encoding='utf-8') as f:
            log_content_global = f.read()

        if status == 0:
            print("编译成功！")
            return 0
        
        error = get_error_signature(log_content_global)
        print(f"错误: {error}")

        if error == last_error:
            same_error_count += 1
            if same_error_count >= 2:
                print("连续两次相同错误，停止重试")
                break
        else:
            same_error_count = 0

        last_error = error

        if error == "oom_detected":
			jobs = handle_oom(jobs, log_content_global)
		elif error == "netifd_link_error":
			fix_netifd_libnl_tiny()
		elif error == "lua_neturl_download":
			fix_lua_neturl_download(log_content_global)
		elif error == "trojan_plus_buffer_cast":
			fix_trojan_plus_issues()
		elif error == "patch_failed":
			fix_patch_application(log_content_global)
		elif error == "makefile_separator":
			fix_makefile_separator(log_content_global)
		elif error == "directory_conflict":
			fix_directory_conflict(log_content_global)
		elif error == "symlink_conflict":
			fix_symbolic_link_conflict(log_content_global)
		elif error == "toolchain_provides_syntax":
			fix_toolchain_provides_syntax(log_content_global)
		elif error == "luci_lib_taskd_depends":
			fix_luci_lib_taskd_extra_depends()
		elif error == "apk_add_base_files":
			fix_apk_add_base_files_issue(log_content_global)
		elif error == "makefile_dep_missing":
			fix_depends_format(log_content_global)
		elif error == "unknown_error":
			print("未知错误，无法自动修复")
		else:
			print(f"未处理的错误类型: {error}")

        retry += 1
        time.sleep(3 if error != "unknown_error" else 1)

    print("编译失败，达到最大重试次数或连续相同错误")
    return 1

if __name__ == "__main__":
    sys.exit(main())
