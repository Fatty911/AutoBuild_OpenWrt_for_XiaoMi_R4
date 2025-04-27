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

# OOM 高风险包列表
OOM_PRONE_PACKAGE_PATTERNS = [
    r'/gcc-\d+', r'/llvm-\d+', r'/qt5base-\d+', r'/webkitgtk-\d+', r'/linux-\d+'
]

# --- Global variable to store log content for fix functions ---
# While not ideal OOP, it simplifies passing log data to many fix functions.
log_content_global = ""
# --- Global flag for pre-computation steps ---
needs_base_files_precompute = False


def get_relative_path(path):
    """获取相对路径，优先相对于当前工作目录"""
    current_pwd = os.getcwd()
    try:
        # Ensure path is absolute first
        abs_path = Path(path).resolve()
        # Check if it's within the current working directory
        if abs_path.is_relative_to(current_pwd):
            return str(abs_path.relative_to(current_pwd))
        else:
            # Return absolute path if outside CWD
            return str(abs_path)
    except (ValueError, OSError, Exception): # Handle various errors like non-existence or cross-drive issues
        # Fallback to the original path string if resolution/relpath fails
        return str(path)

# --- Error Signature Detection ---
def get_error_signature(log_content):
    """Detects a specific error signature from the build log."""
    if not log_content: return "no_log_content"

    # --- High Priority Errors ---
    # APK Version Format Error (Error 99 from mkpkg)
    apk_version_error_match = re.search(
        r"ERROR: info field 'version' has invalid value: package version is invalid.*?make\[\d+\]: \*\*\* .*? ([^ ]+\.apk)\] Error 99",
        log_content, re.DOTALL
    )
    if apk_version_error_match:
        apk_filename = os.path.basename(apk_version_error_match.group(1))
        pkg_name_match = re.match(r'^([a-zA-Z0-9._-]+?)(?:=[\d.-]+)?(?:_\d+)?\.apk$', apk_filename) # Improved regex for name
        pkg_name = pkg_name_match.group(1) if pkg_name_match else "unknown_pkg_from_apk"
        # Try to get package name from "Leaving directory" as fallback
        leaving_dir_match = re.search(r"make\[\d+\]: Leaving directory .*?/([^/']+)'", log_content)
        if leaving_dir_match and pkg_name == "unknown_pkg_from_apk":
             pkg_name = leaving_dir_match.group(1)
        return f"apk_invalid_version_format:{pkg_name}"

    # APK Add Invalid Dependency Format (Error 99 from apk add) - often base-files
    apk_add_invalid_format_match = re.search(
        r"ERROR: ('([^=]+)=' is not a valid world dependency).*?make\[\d+\]: \*\*\* .*?package/install.* Error 99",
        log_content, re.DOTALL
    )
    if apk_add_invalid_format_match:
        invalid_package = apk_add_invalid_format_match.group(2)
        if "base-files=" in apk_add_invalid_format_match.group(1):
             return "apk_add_base_files" # Specific signature for base-files issue
        else:
             return f"apk_add_invalid_dep_format:{invalid_package}"

    # Out Of Memory (OOM)
    if re.search(r'Killed|signal 9|Error 137', log_content): return "oom_detected"

    # Filesystem Conflicts
    if "mkdir: cannot create directory" in log_content and "File exists" in log_content: return "directory_conflict"
    if "ln: failed to create symbolic link" in log_content and "File exists" in log_content: return "symlink_conflict" # <-- Your specific error

    # Patching Failures
    if ("Patch failed" in log_content or "Only garbage was found" in log_content or "unexpected end of file in patch" in log_content or "can't find file to patch" in log_content):
         patch_match = re.search(r'Applying (.+\.patch)', log_content)
         patch = os.path.basename(patch_match.group(1)) if patch_match else "unknown_patch"
         pkg_match = re.search(r"make\[\d+\]: Entering directory .*?/([^/']+)", log_content)
         if not pkg_match:
             pkg_match = re.search(r"ERROR: package/(?:feeds/[^/]+/|pkgs/|libs/|utils/|network/)?([^/]+) failed to build", log_content)
         pkg_name = pkg_match.group(1) if pkg_match else "unknown_pkg"
         return f"patch_failed:{pkg_name}:{patch}"

    # Makefile Syntax Errors
    if "missing separator" in log_content and ("Stop." in log_content or "***" in log_content):
         makefile_match = re.search(r'^([^:]+):\d+: \*\*\* missing separator', log_content, re.MULTILINE)
         makefile = makefile_match.group(1) if makefile_match else "unknown_makefile"
         return f"makefile_separator:{makefile}"

    # Toolchain Provides Syntax Error (trailing space)
    if "toolchain" in log_content and 'provides' in log_content and 'syntax error' in log_content and '--info "provides:' in log_content:
        return "toolchain_provides_syntax"

    # APK Wrapper Syntax Error
    if "Syntax error:" in log_content and "bin/apk" in log_content and "staging_dir/host/bin/apk" in log_content:
         return "apk_wrapper_syntax"

    # --- Specific Package/Linker Errors ---
    # Netifd linking error (missing libnl-tiny)
    if "undefined reference to" in log_content and re.search(r'netifd|toolchain.*netifd', log_content) and 'nl_' in log_content:
        ref_match = re.search(r"undefined reference to `([^']+)'", log_content)
        ref = ref_match.group(1) if ref_match else "unknown_symbol"
        return f"netifd_link_error:{ref}"

    # Lua-neturl download failure
    if LIBS_AVAILABLE and 'lua-neturl' in log_content and ('Download failed' in log_content or 'Hash mismatch' in log_content or 'No more mirrors to try' in log_content):
        return "lua_neturl_download"

    # Trojan-plus specific build error
    if 'trojan-plus' in log_content and ('buffer-cast' in log_content or 'std::span' in log_content): # Broaden trigger slightly
        return "trojan_plus_build_error"

    # Luci-lib-taskd specific dependency issue (often manifests as Error 1 or Error 99)
    if ('luci-lib-taskd' in log_content or 'taskd' in log_content) and ('Error 1' in log_content or 'Error 99' in log_content) and ('apk' in log_content or 'depends' in log_content):
        return "luci_lib_taskd_depends"

    # --- Lower Priority / More General Errors ---
    # Makefile Dependency Warning (missing package)
    dep_warning_match = re.search(r"WARNING: Makefile '([^']+)' has a dependency on '([^']*)', which does not exist", log_content)
    if dep_warning_match:
        makefile_path_str = dep_warning_match.group(1)
        bad_dep = dep_warning_match.group(2)
        # Filter out common noisy/ignorable warnings
        if bad_dep and bad_dep.lower() not in ['perl_tests', ''] and not bad_dep.startswith(('p,', '(virtual)', '$', 'gst1-mod-')) and '=>' not in bad_dep:
             try:
                pkg_name = Path(makefile_path_str).parent.name
             except Exception:
                pkg_name = "unknown_pkg"
             return f"makefile_dep_missing:{pkg_name}:{bad_dep}" # Return this only if no higher priority error found

    # Generic Build Fail (if specific package failed message exists)
    generic_fail_match = re.search(r"ERROR: package/(?:feeds/[^/]+/|pkgs/|libs/|utils/|network/)?([^/]+) failed to build", log_content)
    if generic_fail_match:
        return f"generic_build_fail:{generic_fail_match.group(1)}"

    # Generic Error (lowest priority catch-all)
    generic_error_match = re.search(r'(error:|failed|fatal error:|collect2: error: ld returned 1 exit status)', log_content, re.IGNORECASE)
    if generic_error_match:
        error_keyword = generic_error_match.group(1).lower().split(':')[0].replace(' ', '_')
        context_line = ""
        for line in reversed(log_content.splitlines()):
             if generic_error_match.group(1).lower() in line.lower():
                 context_line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line).strip() # Remove ANSI codes
                 context_line = re.sub(r'[^a-zA-Z0-9\s\._\-\+=:/]', '', context_line)[:80] # Keep relevant chars, allow path separators
                 break
        return f"generic_error:{error_keyword}:{context_line}"

    return "unknown_error"


# --- OOM Handling ---
def handle_oom(current_jobs, log_content):
    """Adjusts job count on OOM error."""
    for pattern in OOM_PRONE_PACKAGE_PATTERNS:
        if re.search(pattern, log_content):
            print("检测到 OOM 高风险包，强制使用 -j1")
            return 1
    new_jobs = max(1, current_jobs // 2)
    print(f"检测到 OOM，减少并行任务数: {current_jobs} -> {new_jobs}")
    return new_jobs



def fix_symbolic_link_conflict(log_content):
    """修复符号链接冲突 (ln: failed to create symbolic link ...: File exists)"""
    print("🔧 检测到符号链接冲突，尝试修复...")
    conflict_match = re.search(r'ln: failed to create symbolic link [\'"]?([^\'"]+)[\'"]?: File exists', log_content)
    if not conflict_match:
        print("ℹ️ 未匹配到 'File exists' 符号链接冲突日志。")
        return False

    conflict_link_str = conflict_match.group(1).strip()
    conflict_link = Path(conflict_link_str)
    conflict_link_rel = get_relative_path(conflict_link_str) # For logging
    print(f"冲突符号链接路径: {conflict_link_rel}")

    # Safety check
    critical_dirs = [Path.cwd(), Path.home(), Path("/"), Path("~"), Path("."), Path("..")]
    try:
        resolved_path = conflict_link.resolve()
        if resolved_path in [p.resolve() for p in critical_dirs if p.exists()] or not conflict_link_str:
            print(f"❌ 检测到关键目录或无效路径 ({conflict_link_rel})，拒绝删除！")
            return False
    except Exception: # Handle cases where resolve might fail (e.g., broken link)
        pass

    if conflict_link.exists() or conflict_link.is_symlink(): # Check existence or if it's a broken symlink
        print(f"尝试删除已存在的文件/目录/链接: {conflict_link_rel}")
        try:
            if conflict_link.is_dir() and not conflict_link.is_symlink():
                 shutil.rmtree(conflict_link)
                 print(f"✅ 成功删除冲突目录 {conflict_link_rel}。")
            else:
                 conflict_link.unlink() # Works for files and symlinks (including broken ones)
                 print(f"✅ 成功删除冲突文件/链接 {conflict_link_rel}。")
            return True
        except Exception as e:
            print(f"❌ 删除 {conflict_link_rel} 失败: {e}")
            return False
    else:
        print(f"ℹ️ 冲突链接路径 {conflict_link_rel} 当前不存在，可能已被处理。")
        return True # Conflict resolved

# --- Placeholder for other fix functions ---
# Add all your other fix functions here...
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
            print(f"🗑️ 删除 CMake 缓存: {get_relative_path(cache_file)}")
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
            print(f"✅ 找到 libnl-tiny 库文件: {get_relative_path(lib_paths[0])}")

        # --- 修改 netifd 的 Makefile ---
        netifd_makefile = Path("package/network/config/netifd/Makefile")
        if netifd_makefile.exists():
            print(f"🔧 检查并修改 {get_relative_path(str(netifd_makefile))}...")
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
                print(f"✅ 已修改 {get_relative_path(str(netifd_makefile))}")
                fixed = True
            else:
                print(f"ℹ️ {get_relative_path(str(netifd_makefile))} 无需修改。")
        else:
            print(f"⚠️ 未找到 {get_relative_path(str(netifd_makefile))}")

        # --- 修改 netifd 的 CMakeLists.txt (作为补充) ---
        # CMake 通常会通过 DEPENDS 自动找到库，但以防万一
        cmake_path = Path("package/network/config/netifd/CMakeLists.txt")
        if cmake_path.exists():
            print(f"🔧 检查并修改 {get_relative_path(str(cmake_path))}...")
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
                print(f"✅ 已修改 {get_relative_path(str(cmake_path))}")
                fixed = True
            else:
                print(f"ℹ️ {get_relative_path(str(cmake_path))} 无需修改。")
        else:
            print(f"⚠️ 未找到 {get_relative_path(str(cmake_path))}")


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
            print(f"检查: {get_relative_path(str(makefile_path))}")
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
                print(f"✅ 已修改 {get_relative_path(str(makefile_path))}")
                fixed_any = True
            else:
                print(f"ℹ️ {get_relative_path(str(makefile_path))} 无需修改。")

        except Exception as e:
            print(f"❌ 处理 {get_relative_path(str(makefile_path))} 时出错: {e}")

    if fixed_any:
        # 清理 trojan-plus 包以确保修改生效
        print("🧹 清理 trojan-plus 相关包...")
        # Find the package path dynamically
        trojan_plus_paths = list(Path(".").glob("**/trojan-plus/Makefile"))
        for tp_path in trojan_plus_paths:
            try:
                pkg_path = tp_path.parent.relative_to(Path.cwd())
                clean_cmd = ["make", f"{pkg_path}/clean", "V=s"]
                print(f"运行: {' '.join(clean_cmd)}")
                subprocess.run(clean_cmd, check=False, capture_output=True)
            except ValueError:
                print(f"⚠️ 无法获取 {tp_path.parent} 的相对路径进行清理。")
            except Exception as e:
                print(f"⚠️ 执行清理命令时出错: {e}")
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
    print(f"找到 Makefile: {get_relative_path(str(makefile_path))}")
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
            expected_subdir = f"neturl-{pkg_version}"
            if pkg_release and pkg_release != "1":
                 # Check if version already contains release-like suffix
                 if not pkg_version.endswith(f"-{pkg_release}"):
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
        try:
            pkg_rel_path = makefile_path.parent.relative_to(Path.cwd())
            subprocess.run(["make", f"{pkg_rel_path}/clean", "V=s"], check=False, capture_output=True)
        except ValueError:
            print(f"⚠️ 无法获取 {makefile_path.parent} 的相对路径进行清理。")
        except Exception as e:
            print(f"⚠️ 执行清理命令时出错: {e}")
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

    patch_file_str = patch_match.group(1).strip()
    patch_file_path = Path(patch_file_str)
    patch_file_rel = get_relative_path(patch_file_str) # For logging
    print(f"识别到可能失败的补丁文件: {patch_file_rel}")

    if not patch_file_path.exists():
         # Try to find it relative to CWD if it's not absolute
         patch_file_path_abs = Path.cwd() / patch_file_str
         if patch_file_path_abs.exists():
             patch_file_path = patch_file_path_abs
             patch_file_rel = get_relative_path(str(patch_file_path_abs)) # Update relative path
         else:
             print(f"❌ 补丁文件 {patch_file_rel} 未找到，无法修复。")
             return False

    # Specific fix for lua-neturl patch issues
    if "lua-neturl" in str(patch_file_path):
        print("检测到 lua-neturl 补丁失败，调用专用修复函数...")
        return fix_lua_neturl_directory() # This function handles both Makefile and patches

    # General fix: try removing the problematic patch
    print(f"补丁应用失败，尝试移除补丁文件: {patch_file_rel}")
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
                 pkg_rel_path = get_relative_path(str(pkg_dir))
                 print(f"🧹 尝试清理相关包: {pkg_rel_path}")
                 subprocess.run(["make", f"{pkg_rel_path}/clean", "V=s"], check=False, capture_output=True)
            else:
                 print("⚠️ 无法确定补丁所属包目录，跳过清理。")
        except Exception as clean_e:
            print(f"⚠️ 清理包时出错: {clean_e}")

        return True
    except Exception as e:
        print(f"❌ 禁用补丁 {patch_file_rel} 失败: {e}")
        return False


def fix_makefile_separator(log_content):
    """修复 Makefile "missing separator" 错误"""
    print("🔧 检测到 'missing separator' 错误，尝试修复...")
    fixed = False

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
                # Resolve potential relative paths from log
                potential_dir = Path(dir_match.group(1))
                if potential_dir.is_dir():
                    context_dir = potential_dir.resolve() # Use resolved absolute path
                    print(f"找到上下文目录: {get_relative_path(str(context_dir))}")
                    break
                else: # If log path is not absolute, try relative to CWD
                    potential_dir = Path.cwd() / dir_match.group(1)
                    if potential_dir.is_dir():
                        context_dir = potential_dir.resolve()
                        print(f"找到上下文目录 (相对解析): {get_relative_path(str(context_dir))}")
                        break

    # Construct absolute path to the makefile
    makefile_path = (context_dir / makefile_name_from_err).resolve()
    makefile_path_rel = get_relative_path(str(makefile_path)) # For display

    print(f"尝试修复文件: {makefile_path_rel}")

    if makefile_path.is_file():
        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
                makefile_lines = f.readlines()

            if 0 < line_num <= len(makefile_lines):
                line_content = makefile_lines[line_num - 1]

                if re.match(r'^[ ]+', line_content) and not line_content.startswith('\t'):
                    print(f"检测到第 {line_num} 行使用空格缩进，替换为 TAB...")
                    backup_path = makefile_path.with_suffix(makefile_path.suffix + ".bak")
                    try:
                        shutil.copy2(makefile_path, backup_path)
                        print(f"创建备份: {get_relative_path(str(backup_path))}")
                    except Exception as backup_e:
                        print(f"⚠️ 创建备份失败: {backup_e}")
                        backup_path = None # Indicate backup failed

                    makefile_lines[line_num - 1] = '\t' + line_content.lstrip(' ')
                    with open(makefile_path, 'w', encoding='utf-8') as f:
                        f.writelines(makefile_lines)

                    # Verify fix
                    with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f_check:
                         fixed_lines = f_check.readlines()
                    if fixed_lines[line_num - 1].startswith('\t'):
                         print(f"✅ 成功修复第 {line_num} 行缩进。")
                         fixed = True
                         if backup_path and backup_path.exists(): os.remove(backup_path) # Remove backup on success
                    else:
                         print(f"❌ 修复失败，第 {line_num} 行内容仍为: '{fixed_lines[line_num-1].rstrip()}'")
                         if backup_path and backup_path.exists():
                             shutil.move(str(backup_path), makefile_path) # Restore backup
                             print("已恢复备份。")

                elif not line_content.strip() and line_content != '\n':
                     print(f"第 {line_num} 行为非标准空行，尝试规范化为空行...")
                     backup_path = makefile_path.with_suffix(makefile_path.suffix + ".bak")
                     try:
                         shutil.copy2(makefile_path, backup_path)
                     except Exception: backup_path = None

                     makefile_lines[line_num - 1] = '\n'
                     with open(makefile_path, 'w', encoding='utf-8') as f:
                         f.writelines(makefile_lines)
                     print("✅ 已规范化空行。")
                     fixed = True
                     if backup_path and backup_path.exists(): os.remove(backup_path)

                else:
                    print(f"ℹ️ 第 {line_num} 行内容: '{line_content.rstrip()}'。看起来不是简单的空格缩进问题，可能需要手动检查或问题在 include 的文件中。")

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
            try:
                pkg_rel_path = get_relative_path(str(pkg_dir))
                print(f"🧹 尝试清理相关包目录: {pkg_rel_path}...")
                # Use DIRCLEAN=1 for a deeper clean
                subprocess.run(["make", f"{pkg_rel_path}/clean", "DIRCLEAN=1", "V=s"], check=False, capture_output=True)
                print(f"✅ 清理命令已执行。")
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
    conflict_path_rel = get_relative_path(conflict_path_str) # For logging
    print(f"冲突路径: {conflict_path_rel}")

    # Important safety check: Avoid deleting critical directories
    critical_dirs = [Path.cwd(), Path.home(), Path("/"), Path("~"), Path("."), Path("..")]
    try:
        resolved_path = conflict_path.resolve()
        if resolved_path in [p.resolve() for p in critical_dirs if p.exists()] or not conflict_path_str:
            print(f"❌ 检测到关键目录或无效路径 ({conflict_path_rel})，拒绝删除！")
            return False
    except Exception: # Handle cases where resolve might fail
        pass

    # Check if it's a file or a directory
    if conflict_path.is_file():
        print(f"冲突路径是一个文件，尝试删除文件: {conflict_path_rel}")
        try:
            conflict_path.unlink()
            print("✅ 成功删除冲突文件。")
            return True
        except Exception as e:
            print(f"❌ 删除文件 {conflict_path_rel} 失败: {e}")
            return False
    elif conflict_path.is_dir():
        print(f"冲突路径是一个目录，尝试删除目录: {conflict_path_rel}")
        try:
            shutil.rmtree(conflict_path)
            print("✅ 成功删除冲突目录。")
            return True
        except Exception as e:
            print(f"❌ 删除目录 {conflict_path_rel} 失败: {e}")
            return False
    else:
        print(f"ℹ️ 冲突路径 {conflict_path_rel} 当前不存在，可能已被处理。")
        return True # Conflict resolved


def fix_pkg_version_format():
    """修复 PKG_VERSION 和 PKG_RELEASE 格式 (简单数字或标准格式)"""
    print("🔧 修复 Makefile 中的 PKG_VERSION 和 PKG_RELEASE 格式...")
    changed_count = 0
    makefile_pattern = "**/Makefile" # Look for Makefiles everywhere except build/staging/tmp
    ignore_dirs = ['build_dir', 'staging_dir', 'tmp', '.git', 'dl']

    all_makefiles = []
    for p in Path('.').rglob('Makefile'): # Use rglob for recursive search
        # Check if the path is within an ignored directory
        if not any(ignored in p.parts for ignored in ignore_dirs):
            all_makefiles.append(p)

    print(f"找到 {len(all_makefiles)} 个潜在的 Makefile 文件进行检查...")

    processed_count = 0
    for makefile in all_makefiles:
        processed_count += 1
        if processed_count % 200 == 0: # Adjust reporting frequency if needed
             print(f"已检查 {processed_count}/{len(all_makefiles)}...")

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
                        print(f"🔧 [{get_relative_path(str(makefile))}] 分离 PKG_VERSION/RELEASE: '{version_match_for_release.group(2)}{version_match_for_release.group(3) or ''}' -> VERSION='{base_version}', RELEASE='{release_part}'")
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
            result = subprocess.run(update_cmd, check=False, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
            if result.returncode != 0:
                print(f"⚠️ feeds update -i 失败:\n{result.stderr[-500:]}")
            else:
                print("✅ feeds update -i 完成。")
            # Re-install might be needed if index changed significantly
            install_cmd = ["./scripts/feeds", "install", "-a"]
            print(f"运行: {' '.join(install_cmd)}")
            result_install = subprocess.run(install_cmd, check=False, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
            if result_install.returncode != 0:
                 print(f"⚠️ feeds install -a 失败:\n{result_install.stderr[-500:]}")
            else:
                 print("✅ feeds install -a 完成。")

        except subprocess.TimeoutExpired:
            print("❌ 执行 feeds update/install 时超时。")
            metadata_changed = True # Assume change happened if timeout occurred
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
    # Regex to capture warnings like: WARNING: Makefile 'path/to/Makefile' has a dependency on 'bad-dep>=1.0', which does not exist
    warning_pattern = re.compile(r"WARNING: Makefile '([^']+)' has a dependency on '([^']*)', which does not exist")
    for match in warning_pattern.finditer(log_content):
        # 过滤掉一些已知的、可能无害或难以修复的警告
        bad_dep = match.group(2).strip()
        makefile_path_str = match.group(1)
        # Filter more aggressively: skip if bad_dep is empty, contains '$', '(', ')', '=>', or known noisy patterns
        if bad_dep and '$' not in bad_dep and '(' not in bad_dep and ')' not in bad_dep and '=>' not in bad_dep \
           and bad_dep.lower() not in ['perl_tests'] and not bad_dep.startswith('gst1-mod-'):
            reported_files.add(makefile_path_str)

    fixed_count = 0
    processed_files = set()
    files_actually_fixed = []

    # 优先处理报告的文件
    if reported_files:
        print(f"🎯 优先处理日志中报告的 {len(reported_files)} 个 Makefile...")
        for makefile_path_str in reported_files:
            makefile_path = Path(makefile_path_str)
            if makefile_path.exists() and makefile_path.is_file():
                resolved_path_str = str(makefile_path.resolve())
                if resolved_path_str not in processed_files:
                    if fix_single_makefile_depends(makefile_path):
                        fixed_count += 1
                        files_actually_fixed.append(get_relative_path(makefile_path_str))
                    processed_files.add(resolved_path_str)
            else:
                print(f"  ⚠️ 报告的文件不存在或不是文件: {get_relative_path(makefile_path_str)}")

    # --- (特定错误包处理逻辑 - 可选增强) ---
    # 如果 apk_depends_invalid 错误发生，也尝试修复那个包的 Makefile
    apk_error_sig = get_error_signature(log_content) # Use local log_content here
    if "apk_add_invalid_dep_format" in apk_error_sig: # Check specific error type
        failed_pkg_name = apk_error_sig.split(":")[-1]
        print(f"🎯 尝试修复导致 APK 错误的包 '{failed_pkg_name}' 的 Makefile...")
        # Search more broadly for the Makefile
        possible_makefile_paths = list(Path(".").glob(f"**/{failed_pkg_name}/Makefile"))
        found_makefile = None
        for mf_path in possible_makefile_paths:
            # Basic check to avoid build_dir etc.
            if not any(ignored in mf_path.parts for ignored in ['build_dir', 'staging_dir', 'tmp', 'dl']):
                found_makefile = mf_path
                break

        if found_makefile:
            resolved_path_str = str(found_makefile.resolve())
            if resolved_path_str not in processed_files:
                print(f"  ➡️ 定位到 Makefile: {get_relative_path(str(found_makefile))}")
                if fix_single_makefile_depends(found_makefile):
                    if get_relative_path(str(found_makefile)) not in files_actually_fixed: # 避免重复计数
                         fixed_count += 1
                         files_actually_fixed.append(get_relative_path(str(found_makefile)))
                processed_files.add(resolved_path_str)
            else:
                 print(f"  ℹ️ 包 '{failed_pkg_name}' 的 Makefile 已处理过。")
        else:
            print(f"  ⚠️ 未能找到包 '{failed_pkg_name}' 的 Makefile。")


    if fixed_count > 0:
        print(f"✅ 共修复 {fixed_count} 个 Makefile 中的依赖格式问题: {files_actually_fixed}")
        print("  🔄 运行 './scripts/feeds update -i && ./scripts/feeds install -a' 来更新依赖...")
        try:
            update_result = subprocess.run(["./scripts/feeds", "update", "-i"], check=False, capture_output=True, text=True, timeout=180)
            if update_result.returncode != 0: print(f"  ⚠️ feeds update -i 失败:\n{update_result.stderr[-500:]}")
            else: print("    ✅ feeds update -i 完成。")

            install_result = subprocess.run(["./scripts/feeds", "install", "-a"], check=False, capture_output=True, text=True, timeout=300)
            if install_result.returncode != 0: print(f"  ⚠️ feeds install -a 失败:\n{install_result.stderr[-500:]}")
            else: print("    ✅ feeds install -a 完成。")
        except subprocess.TimeoutExpired:
             print("  ❌ 更新/安装 feeds 时超时。")
        except Exception as e:
            print(f"  ⚠️ 更新/安装 feeds 时出错: {e}")
        return True
    else:
        print("ℹ️ 未发现或未成功修复需要处理的 DEPENDS 字段。")
        return False

def fix_single_makefile_depends(makefile_path: Path):
    """修复单个 Makefile 中的 DEPENDS 字段 (增强版 v3 - 更精确替换)"""
    try:
        with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        print(f"  ❌ 读取 Makefile 出错 {get_relative_path(str(makefile_path))}: {e}")
        return False

    original_content = content
    new_content = content
    modified = False
    offset_adjustment = 0 # Track changes in length for subsequent replacements

    # Find DEPENDS lines (supports += and multi-line with \)
    depends_regex = r'^([ \t]*DEPENDS\s*[:+]?=\s*)((?:.*?\\\n)*.*)$'
    matches = list(re.finditer(depends_regex, content, re.MULTILINE | re.IGNORECASE))

    if not matches:
        return False # No DEPENDS found

    for match in matches:
        start_index = match.start() + offset_adjustment
        end_index = match.end() + offset_adjustment

        original_block = new_content[start_index:end_index] # Get current block from potentially modified content
        prefix = match.group(1)
        depends_str_multiline = match.group(2)

        # Combine multi-line into single line, remove trailing backslashes
        depends_str = depends_str_multiline.replace('\\\n', ' ').replace('\n', ' ').strip()

        # Check for complex Make syntax early
        is_complex = '$' in depends_str or '(' in depends_str

        # Split dependencies by whitespace
        depends_list = re.split(r'\s+', depends_str)
        cleaned_depends = []
        item_modified = False

        for dep in depends_list:
            dep = dep.strip()
            if not dep or dep == '\\': continue

            original_dep = dep
            cleaned_dep = dep # Start with original

            # Remove version constraints only if NOT complex Make syntax
            if not is_complex:
                # Remove prefixes like +@
                dep_prefix = ""
                if dep.startswith('+') or dep.startswith('@'):
                    dep_prefix = dep[0]
                    dep_name = dep[1:]
                else:
                    dep_name = dep

                # Remove version constraints like >=, <=, =, >, <
                dep_name_cleaned = re.split(r'[<>=!~]', dep_name, 1)[0].strip()

                # Basic validation: ensure it looks like a package name
                if dep_name_cleaned and re.match(r'^[a-zA-Z0-9._-]+$', dep_name_cleaned):
                    cleaned_dep = f"{dep_prefix}{dep_name_cleaned}"
                elif dep_name_cleaned: # Looks invalid after cleaning
                    print(f"  ⚠️ 清理后的依赖 '{dep_name_cleaned}' (来自 '{original_dep}') 格式无效，已丢弃。文件: {get_relative_path(str(makefile_path))}")
                    cleaned_dep = None # Mark for removal
                # else: keep original dep if cleaning results in empty string

            if cleaned_dep is not None: # Add if not marked for removal
                cleaned_depends.append(cleaned_dep)

            if cleaned_dep != original_dep:
                item_modified = True
                print(f"  🔧 清理依赖: '{original_dep}' -> '{cleaned_dep or '(丢弃)'}' in {get_relative_path(str(makefile_path))}")

        if item_modified:
            modified = True # Mark the whole file as modified if any item changed

            # Remove duplicates only for simple lists
            if not is_complex:
                unique_depends = list(dict.fromkeys(cleaned_depends)) # Simple de-duplication
                new_depends_str = ' '.join(unique_depends)
            else:
                new_depends_str = ' '.join(cleaned_depends) # Keep order and duplicates for complex lines

            # Reconstruct the line/block
            # Handle potential multi-line original block - reconstruct as single line for simplicity
            new_depends_line = f"{prefix}{new_depends_str}"

            # Perform replacement in the current state of new_content
            current_block_in_new_content = new_content[start_index:end_index]

            # Check if the block we found is still the same as the original match content
            # This helps avoid incorrect replacement if previous iterations shifted content
            if current_block_in_new_content == original_block:
                new_content = new_content[:start_index] + new_depends_line + new_content[end_index:]
                offset_adjustment += len(new_depends_line) - len(original_block)
            else:
                # Fallback: Try to find the original block text again if content shifted
                # This is less reliable but might work for minor shifts.
                try:
                    current_start_index = new_content.index(original_block, max(0, start_index - 50)) # Search near original position
                    current_end_index = current_start_index + len(original_block)
                    print(f"  ⚠️ 内容偏移，尝试基于原始内容在 {current_start_index} 处替换...")
                    new_content = new_content[:current_start_index] + new_depends_line + new_content[current_end_index:]
                    # Recalculate total offset adjustment from the beginning
                    offset_adjustment = len(new_content) - len(original_content)
                except ValueError:
                    print(f"  ❌ 无法在当前内容中重新定位原始块，跳过此 DEPENDS 行的替换。文件: {get_relative_path(str(makefile_path))}")
                    modified = False # Revert modified status for this block if replacement failed
                    continue # Skip to next match

    if modified:
        try:
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"  ✅ 已写回修改到: {get_relative_path(str(makefile_path))}")
            return True
        except Exception as e:
             print(f"  ❌ 写回 Makefile 失败 {get_relative_path(str(makefile_path))}: {e}")
             return False
    else:
        return False # No modification needed or happened

def process_makefile_depends(makefile_path: Path):
    """Helper function to process DEPENDS in a single Makefile.
       Handles simple lists and complex Make constructs differently."""
    try:
        if makefile_path.is_symlink():
            # If it's a symlink, try resolving it, but process the link path if resolution fails
            try:
                real_path = makefile_path.resolve(strict=True)
                if not real_path.is_file(): return False
                makefile_path = real_path
            except Exception:
                # Process the symlink path itself if resolve fails (might be broken link)
                if not makefile_path.exists(): return False # Skip if link target doesn't exist

        if not makefile_path.is_file():
            return False

        with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        original_content = content

        # Basic check if it looks like an OpenWrt Makefile
        is_package_makefile = ('define Package/' in content and 'endef' in content) or \
                              ('include $(TOPDIR)/rules.mk' in content or \
                               'include $(INCLUDE_DIR)/package.mk' in content or \
                               'include ../../buildinfo.mk' in content)
        if not is_package_makefile:
            return False

        depends_regex = r'^([ \t]*DEPENDS\s*[:+]?=\s*)((?:.*?\\\n)*.*)$' # Added :? for depends:=
        modified_in_file = False
        new_content = content
        offset_adjustment = 0

        matches = list(re.finditer(depends_regex, content, re.MULTILINE | re.IGNORECASE))
        if not matches:
            return False

        for match in matches:
            start_index = match.start() + offset_adjustment
            end_index = match.end() + offset_adjustment

            original_depends_line_block = new_content[start_index:end_index]
            prefix = match.group(1) # Includes DEPENDS+= or DEPENDS:= etc.
            depends_value = match.group(2).replace('\\\n', ' ').strip()

            # --- Check for complex Make syntax ($ or parenthesis) ---
            is_complex = '$' in depends_value or '(' in depends_value

            # Split by whitespace
            depends_list = re.split(r'\s+', depends_value)
            processed_depends = []
            needs_fix = False

            for dep in depends_list:
                dep = dep.strip()
                if not dep: continue

                original_dep_for_log = dep # Store original for logging comparison
                current_part = dep        # Start with the original part

                # Only clean version constraints if it's NOT complex Make syntax
                if not is_complex:
                    dep_prefix = ""
                    if dep.startswith('+') or dep.startswith('@'):
                        dep_prefix = dep[0]
                        dep_name = dep[1:]
                    else:
                        dep_name = dep

                    # Remove version constraints like >=, <=, =, >, <, ~
                    cleaned_name = re.split(r'[>=<~]', dep_name, 1)[0].strip()

                    # Basic validation: ensure it looks like a package name after cleaning
                    if cleaned_name and re.match(r'^[a-zA-Z0-9._-]+$', cleaned_name):
                        current_part = f"{dep_prefix}{cleaned_name}"
                    elif cleaned_name: # Looks invalid after cleaning
                        print(f"  ⚠️ 清理后的依赖 '{cleaned_name}' (来自 '{original_dep_for_log}') 格式无效，已丢弃。文件: {get_relative_path(str(makefile_path))}")
                        current_part = None # Mark for removal
                    # else: keep original dep if cleaning results in empty string or no change needed

                if current_part is not None: # Add if not marked for removal
                    processed_depends.append(current_part)

                if current_part != original_dep_for_log:
                    needs_fix = True
                    # Log the change clearly
                    # print(f"  🔧 清理依赖项部分: '{original_dep_for_log}' -> '{current_part or '(丢弃)'}' in {get_relative_path(str(makefile_path))}")


            # --- Apply fixes only if version constraints were found/removed ---
            if needs_fix:
                if is_complex:
                    # For complex lines, simply join the processed parts back. DO NOT remove duplicates.
                    new_depends_str = ' '.join(processed_depends)
                    # print(f"  处理复杂依赖行 (仅移除版本约束): {get_relative_path(str(makefile_path))}")
                else:
                    # For simple lines, remove duplicates after cleaning.
                    # print(f"  处理简单依赖行 (移除版本约束和重复项): {get_relative_path(str(makefile_path))}")
                    # Use dict for ordered unique items
                    seen = {}
                    unique_depends = []
                    for item in processed_depends:
                        item_prefix = ""
                        item_name = item
                        if item.startswith('+') or item.startswith('@'):
                            item_prefix = item[0]
                            item_name = item[1:]

                        if not item_name: continue

                        # Handle + vs @ preference for duplicates
                        if item_name not in seen:
                            seen[item_name] = item_prefix
                            unique_depends.append(item)
                        elif item_prefix == '@' and seen[item_name] == '+':
                            # Upgrade existing '+' to '@'
                            seen[item_name] = '@'
                            # Find and replace in unique_depends list
                            for i, old_item in enumerate(unique_depends):
                                if old_item == f"+{item_name}":
                                    unique_depends[i] = item
                                    break
                        # else: if current is '+' and seen is '@', do nothing (keep '@')
                        # else: if prefixes are same, do nothing (already unique)

                    new_depends_str = ' '.join(unique_depends)

                # Reconstruct the full line/block (usually single line after fix)
                new_depends_line = f"{prefix}{new_depends_str}"

                # Replace the original block within the *current* state of new_content
                current_block_in_new_content = new_content[start_index:end_index]

                if current_block_in_new_content == original_depends_line_block: # Sanity check
                    new_content = new_content[:start_index] + new_depends_line + new_content[end_index:]
                    offset_adjustment += len(new_depends_line) - len(original_depends_line_block)
                    modified_in_file = True
                else:
                     # Fallback: Try to find the original block text again if content shifted
                     try:
                         current_start_index = new_content.index(original_depends_line_block, max(0, start_index - 100)) # Search wider range
                         current_end_index = current_start_index + len(original_depends_line_block)
                         print(f"  ⚠️ 内容偏移，尝试基于原始内容在 {current_start_index} 处替换...")
                         new_content = new_content[:current_start_index] + new_depends_line + new_content[current_end_index:]
                         offset_adjustment = len(new_content) - len(original_content) # Recalculate total offset
                         modified_in_file = True
                     except ValueError:
                          print(f"  ❌ 无法在当前内容中重新定位原始块，跳过此 DEPENDS 行的替换。文件: {get_relative_path(str(makefile_path))}")
                          # Do not set modified_in_file to True if replacement failed
                          continue # Skip to next match

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
    # Search more broadly
    makefile_paths = list(Path(".").glob("**/lua-neturl/Makefile"))
    if not makefile_paths:
        print("❌ 无法找到 lua-neturl 的 Makefile。")
        return False
    # Prioritize paths not in build_dir etc.
    valid_paths = [p for p in makefile_paths if not any(ignored in p.parts for ignored in ['build_dir', 'staging_dir', 'tmp', 'dl'])]
    if not valid_paths:
        print("❌ 找到的 lua-neturl Makefile 都在忽略目录中。")
        return False
    makefile_path = valid_paths[0] # Take the first valid one

    print(f"找到 Makefile: {get_relative_path(str(makefile_path))}")

    try:
        # 1. Get latest tag from GitHub
        print("🌐 正在从 GitHub 获取最新的 neturl tag...")
        response = requests.get("https://github.com/golgote/neturl/tags", timeout=20)
        response.raise_for_status() # Raise exception for bad status codes
        soup = BeautifulSoup(response.text, 'html.parser')
        tag_elements = soup.find_all('a', href=re.compile(r'/golgote/neturl/releases/tag/v[\d.-]+'))
        tags = [tag.text.strip() for tag in tag_elements if re.match(r'^v[\d.-]+$', tag.text.strip())]

        if not tags:
            print("⚠️ 未能在 GitHub 页面找到有效的版本标签，无法自动更新。")
            return False # Cannot proceed without a valid tag
        else:
            # Simple sort might work, but taking the first is often sufficient if newest is first
            latest_tag = tags[0]
            print(f"✅ 获取到最新/第一个 tag: {latest_tag}")

        # 2. Derive version, source filename, URL, and expected build dir
        raw_version_part = latest_tag.lstrip('v') # e.g., 1.2-1
        pkg_version_match = re.match(r'^(\d+(\.\d+)*)', raw_version_part)
        if not pkg_version_match:
             print(f"❌ 无法从 tag '{latest_tag}' 解析基础版本号。")
             return False
        pkg_version = pkg_version_match.group(1) # e.g., 1.2

        pkg_release = "1" # Default release
        release_match = re.search(r'-(\d+)$', raw_version_part)
        if release_match:
            pkg_release = release_match.group(1)

        pkg_source_filename = f"neturl-{raw_version_part}.tar.gz" # Use the raw version part for filename
        pkg_source_url = f"https://github.com/golgote/neturl/archive/refs/tags/{latest_tag}.tar.gz"
        expected_build_subdir = f"neturl-{raw_version_part}" # Directory inside tarball

        # 3. Download the source tarball to calculate hash
        dl_dir = Path("./dl")
        dl_dir.mkdir(exist_ok=True)
        tarball_path = dl_dir / pkg_source_filename

        print(f"下载 {pkg_source_url} 到 {get_relative_path(str(tarball_path))}...")
        try:
            # Use wget or curl, whichever is available
            if shutil.which("wget"):
                download_cmd = ["wget", "-q", "-O", str(tarball_path), pkg_source_url]
            elif shutil.which("curl"):
                download_cmd = ["curl", "-s", "-L", "-o", str(tarball_path), pkg_source_url]
            else:
                print("❌ wget 和 curl 都不可用，无法下载。")
                return False
            subprocess.run(download_cmd, check=True, timeout=90)
            print("✅ 下载成功。")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"❌ 下载失败: {e}")
            if tarball_path.exists():
                try: tarball_path.unlink() # Clean up partial download
                except OSError: pass
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
        modified_content = content

        # Use functions for safer replacement
        def replace_line(pattern, replacement, text):
            return re.sub(pattern, replacement, text, count=1, flags=re.MULTILINE)

        modified_content = replace_line(r'^(PKG_VERSION:=).*', rf'\g<1>{pkg_version}', modified_content)
        modified_content = replace_line(r'^(PKG_RELEASE:=).*', rf'\g<1>{pkg_release}', modified_content)
        modified_content = replace_line(r'^(PKG_SOURCE:=).*', rf'\g<1>{pkg_source_filename}', modified_content)
        modified_content = replace_line(r'^(PKG_SOURCE_URL:=).*', rf'\g<1>{pkg_source_url}', modified_content)
        modified_content = replace_line(r'^(PKG_HASH:=).*', rf'\g<1>{sha256_hex}', modified_content)

        # Ensure PKG_BUILD_DIR is correct
        build_dir_line = f"PKG_BUILD_DIR:=$(BUILD_DIR)/{expected_build_subdir}"
        build_dir_regex = r'^\s*PKG_BUILD_DIR:=\$\(BUILD_DIR\)/.*'
        if not re.search(build_dir_regex, modified_content, re.MULTILINE):
             insert_after = r'^\s*PKG_HASH:=[^\n]+' # Insert after PKG_HASH
             modified_content = re.sub(f'({insert_after})', f'\\1\n{build_dir_line}', modified_content, 1, re.MULTILINE)
        elif not re.search(r'^\s*PKG_BUILD_DIR:=\$\(BUILD_DIR\)/' + re.escape(expected_build_subdir) + r'\s*$', modified_content, re.MULTILINE):
             modified_content = re.sub(build_dir_regex, build_dir_line, modified_content, 1, re.MULTILINE)

        if modified_content != original_content:
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(modified_content)
            print(f"✅ Makefile {get_relative_path(str(makefile_path))} 已更新。")

            # Clean the package to apply changes
            try:
                pkg_rel_path = makefile_path.parent.relative_to(Path.cwd())
                print(f"🧹 清理旧的构建文件: {pkg_rel_path}")
                subprocess.run(["make", f"{pkg_rel_path}/clean", "V=s"], check=False, capture_output=True)
            except ValueError:
                 print(f"⚠️ 无法获取 {makefile_path.parent} 的相对路径进行清理。")
            except Exception as e:
                 print(f"⚠️ 执行清理命令时出错: {e}")

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

def fix_apk_directly(makefile_to_fix=None):
    """直接修复 APK 依赖命令行参数 (修改 luci.mk 或指定 Makefile)"""
    target_mk_path_str = ""
    if makefile_to_fix and Path(makefile_to_fix).exists():
        target_mk_path = Path(makefile_to_fix)
        target_mk_path_str = get_relative_path(str(target_mk_path))
        print(f"🔧 尝试直接修改指定的 Makefile '{target_mk_path_str}' 来修复 APK 依赖格式...")
    else:
        print("🔧 尝试直接修改 luci.mk 来修复 APK 依赖格式...")
        luci_mk_path = None
        # 优先使用 feeds 中的路径
        possible_paths = ["feeds/luci/luci.mk", "package/feeds/luci/luci.mk", "package/luci/luci.mk"]
        for path in possible_paths:
            if os.path.exists(path):
                luci_mk_path = Path(path)
                break
        if not luci_mk_path:
            print(f"⚠️ 找不到 luci.mk (检查路径: {possible_paths})")
            return False
        target_mk_path = luci_mk_path
        target_mk_path_str = get_relative_path(str(target_mk_path))


    try:
        with open(target_mk_path, 'r', encoding='utf-8') as f:
            content = f.read()
        original_content = content

        # 检查是否已经修复过 (查找 CleanDependString 定义)
        if "define CleanDependString" in content:
            print(f"ℹ️ {target_mk_path_str} 似乎已经应用过修复。")
            return True # 认为尝试过此方法

        # 添加修复代码，使用 sed 来清理依赖项
        fix_code = """

# APK dependency fix v2: Define function to clean dependencies
define CleanDependString
$(strip $(shell echo '$(1)' | tr ' ' '\\n' | sed -e 's/[<>=!~].*//g' -e '/^$$/d' | sort -u | tr '\\n' ' '))
endef

"""
        # 查找插入点，通常在文件顶部或 include 之后
        insert_pos = content.find("include $(TOPDIR)/rules.mk")
        if insert_pos != -1:
            insert_pos = content.find('\n', insert_pos) + 1
            new_content = content[:insert_pos] + fix_code + content[insert_pos:]
        else:
            # Fallback: Insert at the beginning if include is not found
            new_content = fix_code + content

        # 修改依赖参数处理
        # Match --info "depends:..." part, handle potential variations
        # Use a raw string for the pattern
        original_depends_pattern = r'(--info "depends:)(\$\(PKG_DEPENDS\))(")'
        # Alternative pattern if PKG_DEPENDS is not directly used (less common)
        alternative_depends_pattern = r'(--info "depends:)([^"]+)(")'

        modified_content = new_content
        num_replacements = 0

        # Try replacing the primary pattern first
        modified_content, count1 = re.subn(original_depends_pattern, r'\1$(call CleanDependString,\2)\3', modified_content)
        num_replacements += count1

        # If primary pattern wasn't found, try the alternative (more risky)
        if count1 == 0:
            modified_content, count2 = re.subn(alternative_depends_pattern, r'\1$(call CleanDependString,\2)\3', modified_content)
            num_replacements += count2
            if count2 > 0:
                 print(f"  ⚠️ 使用了备用模式替换依赖项，请检查 {target_mk_path_str} 的正确性。")


        if num_replacements > 0:
            print(f"✅ 已在 {target_mk_path_str} 中添加依赖项清理函数并修改了 {num_replacements} 处依赖参数。")
            with open(target_mk_path, 'w', encoding='utf-8') as f:
                f.write(modified_content)

            # Clean tmp directory
            tmp_dir = Path("tmp")
            if tmp_dir.exists():
                print("🧹 清理 tmp 目录...")
                try: shutil.rmtree(tmp_dir)
                except Exception as e: print(f"⚠️ 清理 tmp 目录失败: {e}")

            # Clean potentially affected packages (heuristic)
            print("🧹 清理可能受影响的包 (luci-base, toolchain)...")
            subprocess.run(["make", "package/feeds/luci/luci-base/clean", "V=s"], check=False, capture_output=True)
            subprocess.run(["make", "package/libs/toolchain/clean", "V=s"], check=False, capture_output=True)
            # If a specific makefile was targeted, clean that package too
            if makefile_to_fix:
                 try:
                     pkg_rel_path = target_mk_path.parent.relative_to(Path.cwd())
                     print(f"🧹 清理目标包: {pkg_rel_path}")
                     subprocess.run(["make", f"{pkg_rel_path}/clean", "V=s"], check=False, capture_output=True)
                 except ValueError: pass # Ignore if path is outside CWD
                 except Exception as e: print(f"⚠️ 清理目标包时出错: {e}")

            return True
        else:
            print(f"⚠️ 未能在 {target_mk_path_str} 中找到 '--info \"depends:$(PKG_DEPENDS)\"' 或类似模式进行替换。")
            return False # Return False if no modification was made

    except Exception as e:
        print(f"❌ 直接修复 APK 依赖 ({target_mk_path_str}) 时出错: {e}")
        return False

def fix_toolchain_provides_syntax(log_content):
    """修复 toolchain Makefile 中 provides 字段末尾的空格导致的语法错误"""
    print("🔧 检测到 toolchain provides 语法错误，尝试修复...")
    makefile_path = Path("package/libs/toolchain/Makefile")
    if not makefile_path.exists():
        # Try alternative common location
        makefile_path = Path("toolchain/Makefile")
        if not makefile_path.exists():
            print("❌ 找不到 toolchain Makefile (已检查 package/libs/toolchain/ 和 toolchain/)。")
            return False

    print(f"找到 toolchain Makefile: {get_relative_path(str(makefile_path))}")
    fixed = False
    try:
        with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        original_content = content

        # Find lines like: --info "provides: name=version " (with trailing space)
        # And remove the trailing space inside the quotes
        # Use a function for replacement to handle multiple occurrences safely
        modified_lines = []
        changed_in_file = False
        for line in content.splitlines():
            original_line = line
            # More specific pattern to avoid accidental replacements
            line = re.sub(r'(--info "provides:)([^"]+?)(\s+)(")', lambda m: f"{m.group(1)}{m.group(2).rstrip()}{m.group(4)}", line)
            if line != original_line:
                changed_in_file = True
            modified_lines.append(line)

        if changed_in_file:
            fixed = True
            new_content = "\n".join(modified_lines)
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"✅ 已修复 {get_relative_path(str(makefile_path))} 中的 provides 字段空格问题。")
            # Clean toolchain package
            print("🧹 清理 toolchain 构建...")
            # Determine make target path based on found Makefile location
            if makefile_path.parts[0] == 'toolchain':
                 clean_target = "toolchain/clean"
            else:
                 clean_target = "package/libs/toolchain/clean"
            subprocess.run(["make", clean_target, "V=s"], check=False, capture_output=True)
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
                       wrapper_path.chmod(0o755) # Restore permissions
                       print("✅ 已恢复原始 apk 命令。")
                       return True # Action taken
                  except Exception as e:
                       print(f"❌ 恢复原始 apk 时出错: {e}")
                       # Try deleting the wrapper anyway if rename failed
                       try: wrapper_path.unlink()
                       except OSError: pass
                       return False
             else:
                  print("ℹ️ wrapper 存在但日志中未检测到其语法错误。可能不需要处理。")
                  return False # No action taken on the wrapper itself
        else:
             # Wrapper script is missing, but real binary exists. Restore.
             print("⚠️ wrapper 脚本丢失，但备份存在。恢复原始 apk...")
             try:
                  real_path.rename(wrapper_path)
                  wrapper_path.chmod(0o755)
                  print("✅ 已恢复原始 apk 命令。")
                  return True # Action taken
             except Exception as e:
                  print(f"❌ 恢复原始 apk 时出错: {e}")
                  return False
    else:
         # No wrapper seems to be active
         # Check if the current apk is a script (might be an old broken wrapper without .real)
         if wrapper_path.is_file() and not wrapper_path.is_symlink():
             try:
                 with open(wrapper_path, 'r') as f:
                     first_line = f.readline()
                 if first_line.startswith("#!"): # It's a script!
                      print(f"⚠️ {wrapper_path} 是一个脚本但没有 .real 备份。可能是损坏的 wrapper。尝试删除...")
                      try:
                           wrapper_path.unlink()
                           print(f"✅ 已删除可能是 wrapper 的脚本: {get_relative_path(str(wrapper_path))}")
                           print("   下一步编译可能会因缺少 apk 而失败，但清除了潜在问题。")
                           return True # Action taken (deletion)
                      except Exception as e:
                           print(f"❌ 删除脚本 {get_relative_path(str(wrapper_path))} 失败: {e}")
                           return False
             except Exception:
                 pass # Ignore errors reading the file

         # If it's not a script or doesn't exist, no wrapper issue detected
         return False # No action taken

def fix_apk_depends_problem():
    """
    综合处理 APK 依赖格式错误 (Error 99 或 invalid value)。
    优先尝试修复特定包 Makefile 问题 (如 luci-lib-taskd)，然后尝试修改 luci.mk。
    """
    print("🔍 尝试综合解决方案修复 APK 依赖格式问题...")
    fixed_something = False

    # 步骤 1: 专门修复 luci-lib-taskd 的 LUCI_EXTRA_DEPENDS (High priority if applicable)
    print("  方法 1: 尝试注释掉 luci-lib-taskd/Makefile 中的 LUCI_EXTRA_DEPENDS...")
    if fix_luci_lib_taskd_extra_depends():
        print("  ✅ 方法 1 (注释 LUCI_EXTRA_DEPENDS) 执行完成。")
        fixed_something = True
    else:
        print("  ℹ️ 方法 1 (注释 LUCI_EXTRA_DEPENDS) 未进行修改或失败。")

    # 步骤 2: 如果上一步无效或不适用，再尝试修改 luci.mk (作为通用修复)
    if not fixed_something:
        print("  方法 2: 尝试直接修改 luci.mk 中的 apk mkpkg 调用...")
        if fix_apk_directly(): # Pass no specific file, targets luci.mk
            print("  ✅ 方法 2 (修改 luci.mk) 执行完成。")
            fixed_something = True
        else:
            print("  ℹ️ 方法 2 (修改 luci.mk) 未进行修改或失败。")

    # 步骤 3: (可选) 尝试修复具体导致错误的包的 DEPENDS:= 行
    # This might be redundant if luci.mk fix works globally, but can target specific issues.
    if not fixed_something:
        apk_error_sig = get_error_signature(log_content_global) # Use global log content
        if "apk_add_invalid_dep_format" in apk_error_sig:
            failed_pkg_name = apk_error_sig.split(":")[-1]
            if failed_pkg_name != "unknown_pkg_from_apk":
                print(f"  方法 3: 尝试修复包 '{failed_pkg_name}' 的 Makefile DEPENDS...")
                possible_makefile_paths = list(Path(".").glob(f"**/{failed_pkg_name}/Makefile"))
                found_makefile = None
                for mf_path in possible_makefile_paths:
                    if not any(ignored in mf_path.parts for ignored in ['build_dir', 'staging_dir', 'tmp', 'dl']):
                        found_makefile = mf_path
                        break
                if found_makefile:
                     if fix_single_makefile_depends(found_makefile):
                          print(f"  ✅ 方法 3 (修复 {failed_pkg_name} DEPENDS) 执行完成。")
                          fixed_something = True
                     else:
                          print(f"  ℹ️ 方法 3 (修复 {failed_pkg_name} DEPENDS) 未进行修改或失败。")
                else:
                     print(f"  ⚠️ 方法 3: 未找到包 '{failed_pkg_name}' 的 Makefile。")

    return fixed_something

def fix_luci_lib_taskd_extra_depends():
    """专门注释掉 luci-lib-taskd/Makefile 中的 LUCI_EXTRA_DEPENDS 行"""
    print("🔧 尝试特定修复: 注释掉 luci-lib-taskd/Makefile 中的 LUCI_EXTRA_DEPENDS...")
    makefile_path = None
    # 精确查找 Makefile
    possible_paths = list(Path(".").glob("**/luci-lib-taskd/Makefile"))
    if not possible_paths:
        print(f"  ⚠️ 未找到 luci-lib-taskd 的 Makefile。")
        return False

    # Filter out paths in ignored directories
    valid_paths = [p for p in possible_paths if not any(ignored in p.parts for ignored in ['build_dir', 'staging_dir', 'tmp', 'dl'])]
    if not valid_paths:
        print(f"  ⚠️ 找到的 luci-lib-taskd Makefile 都在忽略目录中。")
        return False
    makefile_path = valid_paths[0] # Take the first valid one
    makefile_path_rel = get_relative_path(str(makefile_path))
    print(f"  ➡️ 定位到 Makefile: {makefile_path_rel}")

    try:
        with open(makefile_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        modified = False
        found_target_line = False

        # 精确匹配需要注释掉的行 (allow variations in spacing and version)
        target_line_pattern = re.compile(r"^\s*LUCI_EXTRA_DEPENDS\s*[:+]?=\s*\+?taskd\s*(?:\(.*\))?\s*$", re.IGNORECASE)

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
             # Check DEPENDS as a fallback indicator of manual fix
             define_block_pattern = re.compile(r'define Package/luci-lib-taskd\s*.*?\s*DEPENDS\s*:=\s*.*?\+taskd\s+', re.DOTALL | re.IGNORECASE)
             if define_block_pattern.search("".join(lines)):
                 print("  ℹ️ 检测到 DEPENDS 可能已被手动修复。")
                 return True # Assume problem is addressed
             return False # Truly not found

        if modified:
            print(f"  ✅ 准备写回修改到 {makefile_path_rel}")
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            # 清理该包的缓存
            try:
                pkg_rel_path = makefile_path.parent.relative_to(Path.cwd())
                print(f"  🧹 清理包 '{pkg_rel_path}' 缓存 (DIRCLEAN)...")
                subprocess.run(["make", f"DIRCLEAN=1", f"{pkg_rel_path}/clean", "V=s"], check=False, capture_output=True)
            except ValueError:
                 print(f"  ⚠️ 无法获取 {makefile_path.parent} 的相对路径进行清理。")
            except Exception as e:
                 print(f"  ⚠️ 执行清理命令时出错: {e}")

            # Clean tmp directory as well
            tmp_dir = Path("tmp")
            if tmp_dir.exists():
                print("  🧹 清理 tmp 目录...")
                try: shutil.rmtree(tmp_dir); print("    ✅ tmp 目录已删除。")
                except Exception as e: print(f"    ⚠️ 清理 tmp 目录失败: {e}")
            return True
        else:
            print(f"  ℹ️ {makefile_path_rel} 无需修改 (LUCI_EXTRA_DEPENDS 已注释或不存在)。")
            return True # Assume problem is addressed or not applicable

    except Exception as e:
        print(f"❌ 修改包 'luci-lib-taskd' 的 Makefile 时出错: {e}")
        return False

def fix_apk_wrapper_syntax():
    """修复 APK 包装器脚本中的语法错误"""
    print("🔧 检测到 APK wrapper 语法错误，尝试修复...")

    wrapper_path = Path("staging_dir/host/bin/apk")
    real_path = Path("staging_dir/host/bin/apk.real")
    wrapper_path_rel = get_relative_path(str(wrapper_path))
    real_path_rel = get_relative_path(str(real_path))

    if wrapper_path.exists() and real_path.exists():
        try:
            # 读取当前的包装器脚本
            with open(wrapper_path, 'r') as f:
                content = f.read()

            # 检查是否是我们的 wrapper (通过注释或特征判断)
            if "# APK wrapper script" in content or 'REAL_APK=' in content:
                print(f"  ℹ️ 检测到旧的/错误的 APK wrapper ({wrapper_path_rel})，移除并恢复原始命令...")
                wrapper_path.unlink() # 删除脚本
                real_path.rename(wrapper_path) # 恢复原始命令
                wrapper_path.chmod(0o755) # 恢复权限
                print(f"  ✅ 已恢复原始 APK 命令 ({wrapper_path_rel})。")

                # 恢复后，尝试直接修复依赖问题，因为这可能是根本原因
                print("  ▶️ 尝试再次运行直接修复 (luci.mk)...")
                return fix_apk_directly() # 返回直接修复的结果
            else:
                print(f"  ⚠️ {wrapper_path_rel} 存在但不是预期的 wrapper 脚本。")
                # 可能是其他东西，不要动它，返回 False
                return False
        except Exception as e:
            print(f"❌ 移除旧 wrapper 或恢复原始 apk 时出错: {e}")
            return False
    elif wrapper_path.exists() and not real_path.exists():
         print(f"  ⚠️ 找到 {wrapper_path_rel} 但没有备份 {real_path_rel}。可能是原始 apk 或损坏的 wrapper。")
         # 尝试检查它是否是脚本
         is_script = False
         try:
             with open(wrapper_path, 'r') as f:
                 first_line = f.readline()
             if first_line.startswith("#!"): is_script = True
         except Exception: pass

         if is_script:
             print(f"  ⚠️ {wrapper_path_rel} 是一个脚本，可能是损坏的 wrapper。尝试删除...")
             try:
                 wrapper_path.unlink()
                 print(f"  ✅ 已删除脚本: {wrapper_path_rel}")
                 return True # Action taken
             except Exception as e:
                 print(f"  ❌ 删除脚本失败: {e}")
                 return False
         else:
             # Assume it's the original apk, try direct fix
             print("  ▶️ 假设是原始 APK，尝试运行直接修复 (luci.mk)...")
             return fix_apk_directly()
    else:
        print(f"  ⚠️ 找不到 APK wrapper ({wrapper_path_rel}) 或原始备份 ({real_path_rel})。")
        # 尝试直接修复
        print("  ▶️ 尝试运行直接修复 (luci.mk)...")
        return fix_apk_directly()

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

    # Clean staging package directory (more specific target)
    staging_pkg_dir_path = None
    # Try to find the specific target staging dir mentioned in logs if possible
    target_staging_match = re.search(r'staging_dir/target-([a-zA-Z0-9_.-]+)', log_content)
    if target_staging_match:
        target_name = target_staging_match.group(1)
        # Construct path like staging_dir/target-mipsel_24kc_musl/pkginfo
        pkginfo_dir = Path("staging_dir") / f"target-{target_name}" / "pkginfo"
        if pkginfo_dir.exists():
             # Clean the pkginfo dir as it contains dependency info
             staging_pkg_dir_path = pkginfo_dir # Target this dir for cleaning
        else:
             # Fallback to cleaning the packages dir for the arch
             arch_match = re.search(r'mipsel|aarch64|x86_64|arm', target_name) # Basic arch detection
             if arch_match:
                  arch = arch_match.group(0)
                  # Heuristic: try common package dir names
                  for pkg_dir_name in [arch, f"{arch}_core", f"{arch}_generic", "all"]:
                       potential_path = Path("staging_dir/packages") / pkg_dir_name
                       if potential_path.exists():
                           staging_pkg_dir_path = potential_path
                           break
    # Fallback if no specific dir found
    if not staging_pkg_dir_path:
         staging_pkg_dir_path = Path("staging_dir/packages") # Clean the whole packages dir as last resort

    if staging_pkg_dir_path and staging_pkg_dir_path.exists():
        print(f"  🧹 清理目录: {get_relative_path(str(staging_pkg_dir_path))}")
        try:
            # Be careful cleaning staging_dir/packages directly, maybe just clean specific arch?
            # For now, let's stick to cleaning the determined path
            if staging_pkg_dir_path.name == "packages" and staging_pkg_dir_path.parent.name == "staging_dir":
                print("    ⚠️ 警告: 将清理整个 staging_dir/packages 目录。")
            shutil.rmtree(staging_pkg_dir_path)
            action_taken = True
        except Exception as e:
            print(f"    ⚠️ 清理 {get_relative_path(str(staging_pkg_dir_path))} 目录失败: {e}")
            action_taken = True

    # --- Set the flag ---
    needs_base_files_precompute = True
    print("  ✅ 已设置 base-files 预处理标志。")

    # Return True to indicate a fix strategy was determined
    return True
# --- Main Logic ---
def main():
    parser = argparse.ArgumentParser(description='OpenWrt 编译修复脚本')
    parser.add_argument('make_command', help='原始编译命令，例如 "make V=s"')
    parser.add_argument('log_file', help='主日志文件基础名 (不含 .run.N.log)')
    parser.add_argument('--max-retry', type=int, default=8, help='最大重试次数')
    parser.add_argument('--jobs', type=int, default=0, help='初始并行任务数 (0 表示自动检测)')
    args = parser.parse_args()

    # Extract base command without -j flag
    base_cmd = re.sub(r'\s-j\s*\d+', '', args.make_command).strip()
    # Determine initial jobs
    jobs = args.jobs if args.jobs > 0 else (os.cpu_count() or 1)
    print(f"初始并行任务数: {jobs}")

    retry = 1
    last_error_signature = None
    same_error_count = 0
    global log_content_global # Allow modification
    global needs_base_files_precompute # Allow modification

    while retry <= args.max_retry:
        # --- Pre-computation Step (if flagged) ---
        if needs_base_files_precompute:
            print(f"\n🚀 [尝试 {retry-1} 后] 执行预处理步骤：编译 base-files...")
            precompute_cmd = f"{base_cmd} package/base-files/compile V=s -j1" # Compile base-files specifically
            print(f"运行: {precompute_cmd}")
            pre_log_file = f"{args.log_file}.pre.{retry}.log"
            pre_status = -1
            try:
                with open(pre_log_file, 'w', encoding='utf-8', errors='replace') as plog:
                    process = subprocess.run(precompute_cmd, shell=True, stdout=plog, stderr=subprocess.STDOUT, timeout=300) # Add timeout
                    pre_status = process.returncode
            except subprocess.TimeoutExpired:
                 print(f"❌ base-files 预编译超时 (日志: {pre_log_file})")
            except Exception as e:
                 print(f"❌ base-files 预编译时发生错误: {e} (日志: {pre_log_file})")


            if pre_status == 0:
                print("✅ base-files 预编译成功。")
                # Find and rename the apk file if necessary
                try:
                    # Find staging package dir more reliably
                    staging_pkg_dir = None
                    for p in Path("staging_dir/packages").iterdir():
                        if p.is_dir(): # Assume the first directory found is the target arch
                            staging_pkg_dir = p
                            break
                    if staging_pkg_dir:
                        base_files_apks = list(staging_pkg_dir.glob("base-files_*.apk"))
                        for apk_path in base_files_apks:
                            if "=" not in apk_path.name:
                                # Extract version like 2023-01-01-abcdef12 or just a number
                                version_match = re.search(r'_([\d.-]+(?:_[a-f0-9]+)?(?:-r\d+)?)_', apk_path.name)
                                if version_match:
                                    version = version_match.group(1)
                                    new_name = f"base-files={version}.apk"
                                    new_path = apk_path.with_name(new_name)
                                    print(f"  🏷️ 重命名 base-files APK: {apk_path.name} -> {new_path.name}")
                                    try:
                                        apk_path.rename(new_path)
                                    except OSError as rename_e:
                                         print(f"    ⚠️ 重命名失败: {rename_e}")
                                else:
                                     print(f"  ⚠️ 无法从 {apk_path.name} 提取版本以重命名。")
                    else:
                        print("  ⚠️ 未找到 staging_dir/packages/<arch> 目录来检查 base-files APK。")
                except Exception as e:
                    print(f"  ⚠️ 重命名 base-files APK 时出错: {e}")
            elif pre_status != -1: # If not timeout/exception
                print(f"❌ base-files 预编译失败，返回码: {pre_status} (日志: {pre_log_file})，继续尝试主编译...")
            needs_base_files_precompute = False # Reset flag regardless of outcome

        # --- Main Compile Step ---
        current_run_log = f"{args.log_file}.run.{retry}.log"
        cmd = f"{base_cmd} -j{jobs}"
        print(f"\n--- 尝试 {retry}/{args.max_retry} ---")
        print(f"运行命令: {cmd}")
        print(f"日志文件: {current_run_log}")

        status = -1 # Default status
        try:
            # Use Popen to stream output and write to log simultaneously
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', bufsize=1) # Line buffered

            with open(current_run_log, 'w', encoding='utf-8', errors='replace') as f:
                for line in iter(process.stdout.readline, ''):
                    sys.stdout.write(line)
                    f.write(line)
            status = process.wait() # Get final return code

        except Exception as e:
            print(f"\n❌ 执行编译命令时发生异常: {e}")
            # Write exception to log if possible
            try:
                with open(current_run_log, 'a', encoding='utf-8', errors='replace') as f:
                    f.write(f"\n\n*** SCRIPT ERROR DURING EXECUTION ***\n{e}\n")
            except Exception: pass
            status = 1 # Assume failure

        # --- Process Results ---
        if status == 0:
            print("\n✅ 编译成功！")
            return 0

        print(f"\n❌ 编译失败 (返回码: {status})")

        # Read log content for error analysis
        try:
            with open(current_run_log, 'r', encoding='utf-8', errors='replace') as f:
                log_content_global = f.read()
        except FileNotFoundError:
             print(f"❌ 无法读取日志文件: {current_run_log}")
             log_content_global = "" # Reset log content
             current_error_signature = "no_log_content_error"
        except Exception as e:
             print(f"❌ 读取日志文件时发生错误: {e}")
             log_content_global = ""
             current_error_signature = "log_read_error"
        else:
             current_error_signature = get_error_signature(log_content_global)

        print(f"检测到的错误签名: {current_error_signature}")

        # --- Consecutive Error Check ---
        if current_error_signature == last_error_signature and current_error_signature not in ["no_log_content", "unknown_error", "log_read_error"]:
            same_error_count += 1
            print(f"连续相同错误次数: {same_error_count + 1}")
            # Define thresholds for stopping
            # More tolerant for dependency/metadata issues which might need multiple steps
            if current_error_signature.startswith(("apk_", "makefile_dep_", "metadata_")):
                consecutive_threshold = 3
            else:
                consecutive_threshold = 2

            if same_error_count >= consecutive_threshold:
                print(f"错误 '{current_error_signature}' 连续出现 {same_error_count + 1} 次，达到阈值 {consecutive_threshold+1}，停止重试。")
                break # Exit the while loop
        else:
            same_error_count = 0 # Reset counter if error changes

        last_error_signature = current_error_signature

        # --- Attempt Fixes ---
        fix_attempted = False
        if current_error_signature == "oom_detected":
            new_jobs = handle_oom(jobs, log_content_global)
            if new_jobs != jobs:
                jobs = new_jobs
                fix_attempted = True
        elif current_error_signature.startswith("netifd_link_error"):
            fix_attempted = fix_netifd_libnl_tiny()
        elif current_error_signature == "lua_neturl_download":
            fix_attempted = fix_lua_neturl_download(log_content_global)
        elif current_error_signature.startswith("apk_invalid_version_format:"):
            fix_attempted = fix_metadata_errors() # This handles version format issues
        elif current_error_signature == "trojan_plus_build_error": # Renamed signature
            fix_attempted = fix_trojan_plus_issues()
        elif current_error_signature.startswith("patch_failed"):
            fix_attempted = fix_patch_application(log_content_global)
        elif current_error_signature.startswith("makefile_separator"):
            fix_attempted = fix_makefile_separator(log_content_global)
        elif current_error_signature == "directory_conflict":
            fix_attempted = fix_directory_conflict(log_content_global)
        elif current_error_signature == "symlink_conflict": # Your specific error
            fix_attempted = fix_symbolic_link_conflict(log_content_global)
        elif current_error_signature == "toolchain_provides_syntax":
            fix_attempted = fix_toolchain_provides_syntax(log_content_global)
        elif current_error_signature == "luci_lib_taskd_depends":
             fix_attempted = fix_apk_depends_problem() # Use the consolidated function
        elif current_error_signature == "apk_add_base_files":
            fix_attempted = fix_apk_add_base_files_issue(log_content_global) # Sets flag for next loop
        elif current_error_signature.startswith("makefile_dep_missing"):
            fix_attempted = fix_depends_format(log_content_global)
        elif current_error_signature.startswith("apk_add_invalid_dep_format"):
             fix_attempted = fix_apk_depends_problem() # Use the consolidated function
        elif current_error_signature == "apk_wrapper_syntax":
             fix_attempted = fix_apk_wrapper_syntax()
        elif current_error_signature == "unknown_error":
            print("未知错误，无法自动修复。")
            # Optional: Reduce jobs as a last resort?
            # if jobs > 1:
            #     jobs = max(1, jobs // 2)
            #     print(f"尝试减少 jobs 到 {jobs} 作为后备措施")
            #     fix_attempted = True
        elif current_error_signature in ["no_log_content", "no_log_content_error", "log_read_error"]:
             print("无法读取日志或无内容，无法分析错误。")
        else:
             print(f"未处理的错误类型: {current_error_signature}，无自动修复程序。")

        # --- Prepare for next retry ---
        retry += 1
        if fix_attempted or needs_base_files_precompute:
            print("已尝试修复或将执行预处理，等待 5 秒...")
            time.sleep(5)
        else:
            print("未尝试修复，等待 2 秒...")
            time.sleep(2)


    # --- End of Loop ---
    print(f"\n--- 编译最终失败 ---")
    print(f"已达到最大重试次数 ({args.max_retry}) 或因连续相同错误停止。")
    print(f"最后一次运行日志: {current_run_log}")
    print(f"最后检测到的错误: {last_error_signature}")
    return 1
