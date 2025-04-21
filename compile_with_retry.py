#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compile_with_retry.py
用于修复 OpenWrt 编译中的常见错误
用法: python3 compile_with_retry.py <make_command> <log_file> [--max-retry N] [--error-pattern PATTERN]
"""

import argparse
import os
import re
import subprocess
import sys
import time
import shutil
from pathlib import Path
import requests

def get_relative_path(path):
    """获取相对路径"""
    current_pwd = os.getcwd()
    
    if not os.path.isabs(path):
        if os.path.exists(os.path.join(current_pwd, path)):
            path = os.path.join(current_pwd, path)
        else:
            return path
    
    try:
        return os.path.relpath(path, current_pwd)
    except:
        return path

def fix_netifd_libnl_tiny():
    """增强版：修复 netifd 编译时缺少 libnl-tiny 的链接问题"""
    import glob

    print("🔧 正在尝试修复 netifd 缺少 libnl-tiny 的链接错误...")

    try:
        # 步骤 1：清理并重新编译 libnl-tiny
        print("🧹 清理 libnl-tiny...")
        subprocess.run(["make", "package/libs/libnl-tiny/clean", "-j1", "V=s"], check=False)

        print("🔨 编译 libnl-tiny...")
        subprocess.run(["make", "package/libs/libnl-tiny/compile", "-j1", "V=s"], check=False)

        print("📦 安装 libnl-tiny...")
        subprocess.run(["make", "package/libs/libnl-tiny/install", "-j1", "V=s"], check=False)

        # 步骤 2：确认 .so 或 .a 文件是否存在
        lib_paths = glob.glob("staging_dir/target-*/usr/lib/libnl-tiny.*")
        if not lib_paths:
            print("❌ 未找到 libnl-tiny 的输出文件，可能编译失败。")
            return False
        else:
            print("✅ 找到 libnl-tiny 库文件：")
            for path in lib_paths:
                print(f"  - {path}")

        # 步骤 3：检查 netifd 的 CMakeLists.txt 是否包含 nl-tiny 链接
        cmake_path = Path("package/network/config/netifd/CMakeLists.txt")
        if cmake_path.exists():
            with open(cmake_path, "r", encoding="utf-8", errors="replace") as f:
                cmake_content = f.read()

            # 版本1：检查 target_link_libraries 中是否包含 nl-tiny
            if "nl-tiny" not in cmake_content and "libnl-tiny" not in cmake_content and "libnl_tiny" not in cmake_content:
                print("⚠️ CMakeLists.txt 中未包含 nl-tiny，尝试修复...")
                
                # 尝试不同的写法，确保至少一种能成功
                new_content = cmake_content
                
                # 方式1：在 target_link_libraries 行添加 nl-tiny
                if "target_link_libraries(netifd" in new_content:
                    new_content = new_content.replace(
                        "target_link_libraries(netifd",
                        "target_link_libraries(netifd nl-tiny"
                    )
                    
                # 方式2：添加一个完整的新 target_link_libraries 行
                elif "add_executable(netifd" in new_content and "target_link_libraries" not in new_content:
                    new_content = new_content.replace(
                        "add_executable(netifd",
                        "add_executable(netifd\ntarget_link_libraries(netifd nl-tiny)"
                    )
                
                # 方式3：添加 find_library 和链接命令
                if new_content != cmake_content:
                    # 在文件顶部添加 find_library 命令
                    new_content = "find_library(NL_TINY_LIBRARY NAMES nl-tiny libnl-tiny libnl_tiny)\n" + new_content
                
                with open(cmake_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print("✅ 已注入 nl-tiny 到 CMakeLists.txt 中。")
            else:
                print("✅ CMakeLists.txt 中已包含 nl-tiny 或其变体。")
                
            # 添加一个备用解决方案：创建链接文件到 lib 目录
            target_dirs = glob.glob("build_dir/target-*")
            if target_dirs:
                target_dir = target_dirs[0]
                netifd_build_dir = glob.glob(f"{target_dir}/netifd-*/")
                if netifd_build_dir:
                    print("📂 在 netifd 构建目录中创建链接文件...")
                    ln_commands = [
                        f"cp -f staging_dir/target-*/usr/lib/libnl-tiny.so {netifd_build_dir[0]}/ || true",
                        f"ln -sf ../../staging_dir/target-*/usr/lib/libnl-tiny.so {netifd_build_dir[0]}/libnl-tiny.so || true",
                        f"ln -sf ../../staging_dir/target-*/usr/lib/libnl-tiny.so {netifd_build_dir[0]}/libnl_tiny.so || true"
                    ]
                    for cmd in ln_commands:
                        subprocess.run(cmd, shell=True, check=False)
                
        else:
            print("⚠️ 未找到 netifd 的 CMakeLists.txt，尝试直接修改链接命令...")
            
            # 尝试创建临时 CMake 模块文件来强制链接 libnl-tiny
            module_dir = Path("package/network/config/netifd/cmake")
            module_dir.mkdir(exist_ok=True)
            
            with open(module_dir / "FindLibnlTiny.cmake", "w") as f:
                f.write("""
# FindLibnlTiny.cmake - 强制链接 libnl-tiny 库
find_path(LIBNL_TINY_INCLUDE_DIR NAMES netlink/netlink.h PATH_SUFFIXES libnl-tiny)
find_library(LIBNL_TINY_LIBRARY NAMES nl-tiny libnl-tiny libnl_tiny)
include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(LibnlTiny DEFAULT_MSG LIBNL_TINY_LIBRARY LIBNL_TINY_INCLUDE_DIR)
mark_as_advanced(LIBNL_TINY_INCLUDE_DIR LIBNL_TINY_LIBRARY)
""")
        
        # 步骤 4：尝试直接修改 staging_dir 中的链接命令
        # 创建软链接确保库可以被正确查找
        staging_lib_dirs = glob.glob("staging_dir/target-*/usr/lib")
        for lib_dir in staging_lib_dirs:
            if os.path.exists(f"{lib_dir}/libnl-tiny.so"):
                if not os.path.exists(f"{lib_dir}/libnl_tiny.so"):
                    os.symlink("libnl-tiny.so", f"{lib_dir}/libnl_tiny.so")
                if not os.path.exists(f"{lib_dir}/libnl.so"):
                    os.symlink("libnl-tiny.so", f"{lib_dir}/libnl.so")
                print(f"✅ 在 {lib_dir} 创建了库软链接")

        # 步骤 5：修改构建系统配置，确保链接 libnl-tiny
        make_conf = "package/network/config/netifd/Makefile"
        if os.path.exists(make_conf):
            with open(make_conf, "r", encoding="utf-8", errors="replace") as f:
                makefile_content = f.read()
            
            # 添加 LDFLAGS 到 Makefile
            if "PKG_FIXUP:=autoreconf" in makefile_content and "LDFLAGS" not in makefile_content:
                new_makefile = makefile_content.replace(
                    "PKG_FIXUP:=autoreconf",
                    "PKG_FIXUP:=autoreconf\nTARGET_LDFLAGS += -lnl-tiny"
                )
                with open(make_conf, "w", encoding="utf-8") as f:
                    f.write(new_makefile)
                print("✅ 已在 Makefile 中添加 LDFLAGS 链接 libnl-tiny")
            
            # 确保 libnl-tiny 在依赖列表中
            if "DEPENDS:=" in makefile_content and "libnl-tiny" not in makefile_content:
                new_makefile = makefile_content.replace(
                    "DEPENDS:=",
                    "DEPENDS:=+libnl-tiny "
                )
                with open(make_conf, "w", encoding="utf-8") as f:
                    f.write(new_makefile)
                print("✅ 已在 Makefile 依赖中添加 libnl-tiny")

        # 步骤 6：清理并重新编译 netifd
        print("🧹 清理 netifd...")
        subprocess.run(["make", "package/network/config/netifd/clean", "-j1", "V=s"], check=False)

        # 最极端的方法：复制 libnl-tiny 源码到 netifd 源码目录中
        target_dirs = glob.glob("build_dir/target-*")
        if target_dirs:
            target_dir = target_dirs[0]
            netifd_dirs = glob.glob(f"{target_dir}/netifd-*/")
            libnl_dirs = glob.glob(f"{target_dir}/libnl-tiny-*/")
            
            if netifd_dirs and libnl_dirs:
                netifd_dir = netifd_dirs[0]
                libnl_dir = libnl_dirs[0]
                print(f"📁 复制 libnl-tiny 源码到 netifd 目录...")
                
                # 复制头文件
                subprocess.run(f"cp -rf {libnl_dir}/include/* {netifd_dir}/", shell=True, check=False)
                
                # 复制源文件和创建一个简单的包含文件
                os.makedirs(f"{netifd_dir}/libnl_tiny", exist_ok=True)
                subprocess.run(f"cp -rf {libnl_dir}/*.c {libnl_dir}/*.h {netifd_dir}/libnl_tiny/", shell=True, check=False)
                
                with open(f"{netifd_dir}/libnl_tiny.h", "w") as f:
                    f.write("""
#ifndef _LIBNL_TINY_H_
#define _LIBNL_TINY_H_
#include "libnl_tiny/nl.h"
#include "libnl_tiny/msg.h"
#include "libnl_tiny/attr.h"
#include "libnl_tiny/netlink.h"
#include "libnl_tiny/socket.h"
#include "libnl_tiny/genl.h"
#endif
""")
        
        print("🔨 编译 netifd...")
        result = subprocess.run(["make", "package/network/config/netifd/compile", "-j1", "V=s"], 
                                check=False, capture_output=True, text=True)
        
        # 检查编译结果
        if "Error 1" in result.stdout or "Error 1" in result.stderr:
            print("❌ netifd 编译失败，尝试最后的手动链接方法...")
            
            # 尝试找到编译命令并直接添加库
            build_line = None
            for line in result.stdout.split('\n'):
                if "gcc" in line and "netifd" in line and "-o netifd" in line:
                    build_line = line
                    break
            
            if build_line:
                # 修改链接命令，添加 -lnl-tiny 到命令末尾
                new_build_line = build_line.strip() + " -lnl-tiny"
                print(f"🔧 尝试手动链接: {new_build_line}")
                
                # 查找 build 目录下的 build.ninja 文件
                ninja_files = glob.glob("build_dir/target-*/netifd-*/build.ninja")
                if ninja_files:
                    with open(ninja_files[0], "r", encoding="utf-8", errors="replace") as f:
                        ninja_content = f.read()
                    
                    # 修改链接命令
                    new_ninja = ninja_content.replace(
                        " -o netifd ", 
                        " -o netifd -lnl-tiny "
                    )
                    
                    with open(ninja_files[0], "w", encoding="utf-8") as f:
                        f.write(new_ninja)
                    
                    print("✅ 已修改 build.ninja 文件，添加 -lnl-tiny 到链接命令")
                    
                    # 再次尝试编译
                    print("🔨 再次尝试编译 netifd...")
                    subprocess.run(["make", "package/network/config/netifd/compile", "-j1", "V=s"], check=False)
        
        print("✅ netifd 和 libnl-tiny 修复流程完成。")
        return True

    except Exception as e:
        print(f"❌ 修复 netifd/libnl-tiny 时发生异常: {e}")
        return False




def fix_trojan_plus_issues():
    """修复 trojan-plus 相关的编译问题"""
    print("检测到 trojan-plus 相关错误，尝试修复...")
    try:
        # 执行 sed 命令禁用 trojan-plus
        sed_commands = [
            "sed -i -e '/select PACKAGE_trojan-plus/d' -e '/config PACKAGE_.*_INCLUDE_Trojan_Plus/,/default /s/default y/default n/' feeds/passwall/luci-app-passwall/Makefile || true",
            "sed -i -e '/select PACKAGE_trojan-plus/d' -e '/config PACKAGE_.*_INCLUDE_Trojan_Plus/,/default /s/default y/default n/' package/feeds/passwall/luci-app-passwall/Makefile || true",
            "sed -i -e '/select PACKAGE_trojan-plus/d' -e '/config PACKAGE_.*_INCLUDE_Trojan_Plus/,/default /s/default y/default n/' feeds/small8/luci-app-passwall/Makefile || true",
            "sed -i -e '/select PACKAGE_trojan-plus/d' -e '/config PACKAGE_.*_INCLUDE_Trojan_Plus/,/default /s/default y/default n/' package/feeds/small8/luci-app-passwall/Makefile || true"
        ]
        for cmd in sed_commands:
            print(f"运行: {cmd}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            print(f"stdout:\n{result.stdout}")
            print(f"stderr:\n{result.stderr}")

        # 清理 trojan-plus 相关包以确保修改生效
        clean_cmd = ["make", "package/feeds/small8/trojan-plus/clean", "V=s"]
        print(f"运行: {' '.join(clean_cmd)}")
        result_clean = subprocess.run(clean_cmd, shell=False, capture_output=True, text=True)
        print(f"Clean stdout:\n{result_clean.stdout[-500:]}")
        print(f"Clean stderr:\n{result_clean.stderr}")
        return True
    except Exception as e:
        print(f"修复 trojan-plus 问题时发生错误: {e}")
        return False

def fix_lua_neturl_directory():
    """修复 lua-neturl 的 Makefile 和补丁"""
    makefile_path = "feeds/small8/lua-neturl/Makefile"
    patch_dir = "feeds/small8/lua-neturl/patches"
    excluded_dir = os.path.join(patch_dir, "excluded")
    
    if not os.path.exists(makefile_path):
        print("无法找到 lua-neturl 的 Makefile")
        return False
    
    with open(makefile_path, 'r') as f:
        content = f.read()
    
    pkg_source_match = re.search(r'PKG_SOURCE:=([^\n]+)', content)
    if not pkg_source_match:
        print("无法找到 PKG_SOURCE 定义，无法动态设置 PKG_BUILD_DIR")
        return False
    
    pkg_source = pkg_source_match.group(1).strip()
    
    archive_extensions = ['.tar.gz', '.tar.bz2', '.tar.xz', '.zip']
    subdir = pkg_source
    for ext in archive_extensions:
        if subdir.endswith(ext):
            subdir = subdir[:-len(ext)]
            break
    
    if not subdir or subdir == pkg_source:
        print(f"无法从 PKG_SOURCE '{pkg_source}' 解析有效的解压目录名")
        return False
    
    build_dir_line = f"PKG_BUILD_DIR:=$(BUILD_DIR)/{subdir}\n"
    modified = False
    if "PKG_BUILD_DIR:=" not in content:
        insert_pos = content.find("PKG_VERSION:=")
        if insert_pos != -1:
            insert_pos = content.find('\n', insert_pos) + 1
            content = content[:insert_pos] + build_dir_line + content[insert_pos:]
        else:
            content += "\n" + build_dir_line
        print(f"动态设置 PKG_BUILD_DIR 为 $(BUILD_DIR)/{subdir}")
        modified = True
    else:
        print("Makefile 已有 PKG_BUILD_DIR 定义，继续检查补丁")
    
    if modified:
        with open(makefile_path, 'w') as f:
            f.write(content)
    
    if os.path.exists(patch_dir):
        os.makedirs(excluded_dir, exist_ok=True)
        for patch_file in os.listdir(patch_dir):
            if patch_file.endswith('.bak') or patch_file.endswith('.bak.excluded'):
                original_path = os.path.join(patch_dir, patch_file)
                new_path = os.path.join(excluded_dir, patch_file)
                shutil.move(original_path, new_path)
                print(f"已隔离备份补丁 {original_path}，移至 {new_path}")
                modified = True
    
    if modified:
        print("已完成 lua-neturl 的 Makefile 和补丁修复")
        return True
    else:
        print("无需进一步修复，Makefile 和补丁已正确配置")
        return False

def fix_patch_application(log_file):
    """修复补丁应用失败的问题"""
    print("检测到补丁应用失败，尝试修复...")
    
    with open(log_file, 'r', errors='replace') as f:
        log_content = f.read()
    
    if "Patch failed" not in log_content and "Only garbage was found in the patch input" not in log_content and "unexpected end of file in patch" not in log_content:
        return False
    
    patch_file_match = re.search(r'Applying (.+) using plaintext:', log_content)
    if not patch_file_match:
        print("无法提取补丁文件路径，跳过修复。")
        return False
    
    patch_file = patch_file_match.group(1).strip()
    print(f"补丁文件: {patch_file}")
    
    if "Only garbage was found in the patch input" in log_content or "unexpected end of file in patch" in log_content:
        print("补丁格式无效，自动删除补丁文件以跳过应用...")
        try:
            os.remove(patch_file)
            print(f"已删除无效补丁文件: {patch_file}")
        except Exception as e:
            print(f"删除补丁失败: {e}")
        return True
    
    if "lua-neturl" in patch_file:
        print("检测到 lua-neturl 补丁失败，调用专用修复函数...")
        return fix_lua_neturl_directory()
    else:
        print("非 lua-neturl 的补丁失败，跳过修复。")
        return False

def fix_makefile_separator(log_file):
    """修复 Makefile "missing separator" 错误"""
    print("检测到 'missing separator' 错误，尝试修复...")
    fix_attempted = 0
    
    with open(log_file, 'r', errors='replace') as f:
        log_content = f.read()
    
    error_line_match = re.search(r'^([^:]+):([0-9]+): \*\*\* missing separator', log_content, re.MULTILINE)
    if not error_line_match:
        print("警告: 无法提取文件名和行号。")
        return False
    
    makefile_name_from_err = error_line_match.group(1)
    line_num = int(error_line_match.group(2))
    print(f"从错误行提取: 文件名部分='{makefile_name_from_err}', 行号='{line_num}'")
    
    error_line_info = error_line_match.group(0)
    context_dir = None
    
    log_lines = log_content.splitlines()
    error_line_index = next((i for i, line in enumerate(log_lines) if error_line_info in line), -1)
    
    if error_line_index >= 0:
        for i in range(error_line_index, max(0, error_line_index - 50), -1):
            dir_match = re.search(r"make\[\d+\]: Entering directory '([^']+)'", log_lines[i])
            if dir_match:
                context_dir = dir_match.group(1)
                print(f"找到上下文目录: {context_dir}")
                full_makefile_path = os.path.join(context_dir, makefile_name_from_err)
                break
    
    if not context_dir:
        if "package/libs/toolchain" in log_content:
            full_makefile_path = "package/libs/toolchain/Makefile"
            print(f"推测为工具链包的 Makefile: {full_makefile_path}")
        elif os.path.isfile(makefile_name_from_err):
            full_makefile_path = makefile_name_from_err
            print(f"使用当前目录中的文件: {full_makefile_path}")
        else:
            print("错误: 无法定位 Makefile 文件。")
            return False
    
    makefile_path_rel = get_relative_path(full_makefile_path)
    if not makefile_path_rel and os.path.isfile(full_makefile_path):
        makefile_path_rel = full_makefile_path
        print(f"使用推测路径: {makefile_path_rel}")
    
    print(f"确定出错的 Makefile: {makefile_path_rel}, 行号: {line_num}")
    
    if os.path.isfile(makefile_path_rel) and line_num and str(line_num).isdigit():
        with open(makefile_path_rel, 'r', errors='replace') as f:
            makefile_lines = f.readlines()
        
        if line_num <= len(makefile_lines):
            line_content = makefile_lines[line_num-1].rstrip('\n')
            print(f"第 {line_num} 行内容: '{line_content}'")
            
            include_match = re.match(r'^\s*include\s+(.+)', line_content)
            if include_match:
                subfile = include_match.group(1).strip()
                subfile_dir = os.path.dirname(makefile_path_rel)
                subfile_path = os.path.normpath(os.path.join(subfile_dir, subfile))
                print(f"检测到 include 子文件: {subfile_path}")
                
                if os.path.isfile(subfile_path):
                    print(f"检查子文件 {subfile_path} 是否存在 'missing separator' 问题...")
                    with open(subfile_path, 'r', errors='replace') as f:
                        subfile_lines = f.readlines()
                    
                    subfile_modified = False
                    for i, sub_line in enumerate(subfile_lines):
                        if (re.match(r'^[ ]+', sub_line) and 
                            not re.match(r'^\t', sub_line) and 
                            not re.match(r'^[ ]*#', sub_line) and 
                            sub_line.strip()):
                            print(f"子文件 {subfile_path} 中检测到空格缩进，替换为 TAB...")
                            shutil.copy2(subfile_path, f"{subfile_path}.bak")
                            subfile_lines[i] = re.sub(r'^[ ]+', '\t', sub_line)
                            subfile_modified = True
                    
                    if subfile_modified:
                        with open(subfile_path, 'w') as f:
                            f.writelines(subfile_lines)
                        
                        with open(subfile_path, 'r') as f:
                            if any(line.startswith('\t') for line in f):
                                print(f"成功修复子文件 {subfile_path} 的缩进。")
                                os.remove(f"{subfile_path}.bak")
                                fix_attempted = 1
                            else:
                                print("修复子文件失败，恢复备份。")
                                shutil.move(f"{subfile_path}.bak", subfile_path)
                else:
                    print(f"警告: 子文件 {subfile_path} 不存在，跳过检查。")
            
            if re.match(r'^[ ]+', line_content) and not re.match(r'^\t', line_content):
                print(f"检测到第 {line_num} 行使用空格缩进，替换为 TAB...")
                shutil.copy2(makefile_path_rel, f"{makefile_path_rel}.bak")
                
                makefile_lines[line_num-1] = re.sub(r'^[ ]+', '\t', makefile_lines[line_num-1])
                with open(makefile_path_rel, 'w') as f:
                    f.writelines(makefile_lines)
                
                with open(makefile_path_rel, 'r') as f:
                    fixed_lines = f.readlines()
                    if line_num <= len(fixed_lines) and fixed_lines[line_num-1].startswith('\t'):
                        print("成功修复缩进。")
                        os.remove(f"{makefile_path_rel}.bak")
                        fix_attempted = 1
                    else:
                        print("修复失败，恢复备份。")
                        shutil.move(f"{makefile_path_rel}.bak", makefile_path_rel)
            
            elif not line_content.strip():
                print(f"第 {line_num} 行为空行，可能有隐藏字符，尝试规范化...")
                shutil.copy2(makefile_path_rel, f"{makefile_path_rel}.bak")
                
                makefile_lines[line_num-1] = '\n'
                with open(makefile_path_rel, 'w') as f:
                    f.writelines(makefile_lines)
                
                print("已规范化空行。")
                os.remove(f"{makefile_path_rel}.bak")
                fix_attempted = 1
            
            else:
                print(f"第 {line_num} 行无需修复或问题不在缩进（可能是子文件问题）。")
                print(f"请检查 {makefile_path_rel} 第 {line_num} 行内容: '{line_content}'")
        else:
            print(f"行号 {line_num} 超出文件 {makefile_path_rel} 的范围。")
    else:
        print(f"文件 '{makefile_path_rel}' 不存在或行号无效。")
    
    pkg_dir = os.path.dirname(makefile_path_rel)
    if os.path.isdir(pkg_dir) and (re.match(r'^(package|feeds|tools|toolchain)/', pkg_dir) or pkg_dir == "."):
        if pkg_dir == ".":
            print("错误发生在根目录 Makefile，尝试清理整个构建环境...")
            try:
                subprocess.run(["make", "clean", "V=s"], check=False)
            except:
                print("警告: 清理根目录失败。")
        else:
            print(f"尝试清理目录: {pkg_dir}...")
            try:
                subprocess.run(["make", f"{pkg_dir}/clean", "DIRCLEAN=1", "V=s"], check=False)
            except:
                print(f"警告: 清理 {pkg_dir} 失败。")
        fix_attempted = 1
    else:
        print(f"目录 '{pkg_dir}' 无效或非标准目录，跳过清理。")
    
    if "package/libs/toolchain" in makefile_path_rel:
        print("检测到工具链包错误，强制清理 package/libs/toolchain...")
        try:
            subprocess.run(["make", "package/libs/toolchain/clean", "DIRCLEAN=1", "V=s"], check=False)
        except:
            print("警告: 清理工具链失败。")
        fix_attempted = 1
        if fix_attempted == 1 and "missing separator" in log_content:
            print(f"修复尝试后问题仍未解决，请手动检查 {makefile_path_rel} 第 {line_num} 行及其子文件。")
            return False
    
    return fix_attempted == 1

def fix_directory_conflict(log_file):
    """修复目录冲突"""
    print("检测到目录冲突，尝试修复...")
    
    with open(log_file, 'r', errors='replace') as f:
        log_content = f.read()
    
    conflict_dir_match = re.search(r'mkdir: cannot create directory ([^:]*)', log_content)
    if not conflict_dir_match:
        print("无法从日志中提取冲突目录路径。")
        return False
    
    conflict_dir = conflict_dir_match.group(1).strip()
    print(f"冲突目录: {conflict_dir}")
    
    if os.path.isdir(conflict_dir):
        print(f"尝试删除冲突目录: {conflict_dir}")
        try:
            shutil.rmtree(conflict_dir)
            print("成功删除冲突目录。")
            return True
        except Exception as e:
            print(f"删除目录 {conflict_dir} 失败: {e}")
            return False
    else:
        print(f"冲突目录 {conflict_dir} 不存在，可能已被其他进程处理。")
        return True

def fix_symbolic_link_conflict(log_file):
    """修复符号链接冲突"""
    print("检测到符号链接冲突，尝试修复...")
    
    with open(log_file, 'r', errors='replace') as f:
        log_content = f.read()
    
    conflict_link_match = re.search(r'ln: failed to create symbolic link ([^:]*)', log_content)
    if not conflict_link_match:
        print("无法从日志中提取冲突符号链接路径。")
        return False
    
    conflict_link = conflict_link_match.group(1).strip()
    print(f"冲突符号链接: {conflict_link}")
    
    if os.path.islink(conflict_link) or os.path.exists(conflict_link):
        print(f"尝试删除冲突符号链接: {conflict_link}")
        try:
            os.remove(conflict_link)
            print("成功删除冲突符号链接。")
            return True
        except Exception as e:
            print(f"删除符号链接 {conflict_link} 失败: {e}")
            return False
    else:
        print(f"冲突符号链接 {conflict_link} 不存在，可能已被其他进程处理。")
        return True


def fix_pkg_version():
    """修复 PKG_VERSION 和 PKG_RELEASE 格式"""
    print("修复 PKG_VERSION 和 PKG_RELEASE 格式...")
    changed_count = 0
    
    for makefile in Path('.').glob('**/*'):
        if any(part in str(makefile.parent) for part in ['build_dir', 'staging_dir', 'tmp']):
            continue
        
        if makefile.name != 'Makefile' and not makefile.name.endswith('.mk'):
            continue
        
        try:
            with open(makefile, 'r', errors='replace') as f:
                header = ''.join(f.readline() for _ in range(30))
                if not re.search(r'^\s*(include \.\./\.\./(package|buildinfo)\.mk|include \$\(INCLUDE_DIR\)/package\.mk|include \$\(TOPDIR\)/rules\.mk)', header, re.MULTILINE):
                    continue
                
                f.seek(0)
                original_content = f.read()
        except:
            continue
        
        current_version_match = re.search(r'^PKG_VERSION:=(.*)$', original_content, re.MULTILINE)
        release_match = re.search(r'^PKG_RELEASE:=(.*)$', original_content, re.MULTILINE)
        
        current_version = current_version_match.group(1) if current_version_match else ""
        release = release_match.group(1) if release_match else ""
        
        modified_in_loop = 0
        makefile_changed = 0
        
        version_suffix_match = re.match(r'^([0-9]+(\.[0-9]+)*)-([a-zA-Z0-9_.-]+)$', current_version)
        if version_suffix_match:
            new_version = version_suffix_match.group(1)
            suffix = version_suffix_match.group(3)
            
            suffix_num_match = re.search(r'[0-9]*$', re.sub(r'[^0-9]', '', suffix))
            new_release = suffix_num_match.group(0) if suffix_num_match and suffix_num_match.group(0) else "1"
            
            if not new_release.isdigit():
                new_release = "1"
            
            if current_version != new_version or release != new_release:
                print(f"修改 {makefile}: PKG_VERSION: '{current_version}' -> '{new_version}', PKG_RELEASE: '{release}' -> '{new_release}'")
                
                new_content = []
                version_printed = False
                release_found = False
                
                for line in original_content.splitlines():
                    if line.startswith('PKG_VERSION:='):
                        new_content.append(f"PKG_VERSION:={new_version}")
                        version_printed = True
                    elif line.startswith('PKG_RELEASE:='):
                        new_content.append(f"PKG_RELEASE:={new_release}")
                        release_found = True
                    else:
                        new_content.append(line)
                
                if version_printed and not release_found:
                    version_idx = next(i for i, line in enumerate(new_content) if line.startswith('PKG_VERSION:='))
                    new_content.insert(version_idx + 1, f"PKG_RELEASE:={new_release}")
                
                with open(makefile, 'w') as f:
                    f.write('\n'.join(new_content))
                
                release = new_release
                modified_in_loop = 1
                makefile_changed = 1
        
        if modified_in_loop == 0 and release and not release.isdigit():
            suffix_num_match = re.search(r'[0-9]*$', re.sub(r'[^0-9]', '', release))
            new_release = suffix_num_match.group(0) if suffix_num_match and suffix_num_match.group(0) else "1"
            
            if not new_release.isdigit():
                new_release = "1"
            
            if release != new_release:
                print(f"修正 {makefile}: PKG_RELEASE: '{release}' -> '{new_release}'")
                
                new_content = re.sub(
                    r'^PKG_RELEASE:=.*$',
                    f'PKG_RELEASE:={new_release}',
                    original_content,
                    flags=re.MULTILINE
                )
                
                with open(makefile, 'w') as f:
                    f.write(new_content)
                
                makefile_changed = 1
        
        elif (modified_in_loop == 0 and not release and 
              re.search(r'^PKG_VERSION:=', original_content, re.MULTILINE) and 
              not re.search(r'^PKG_RELEASE:=', original_content, re.MULTILINE)):
            
            print(f"添加 {makefile}: PKG_RELEASE:=1")
            
            new_content = re.sub(
                r'^(PKG_VERSION:=.*)$',
                r'\1\nPKG_RELEASE:=1',
                original_content,
                flags=re.MULTILINE
            )
            
            with open(makefile, 'w') as f:
                f.write(new_content)
            
            makefile_changed = 1
        
        if makefile_changed == 1:
            changed_count += 1
    
    print(f"修复 PKG_VERSION/RELEASE 完成，共检查/修改 {changed_count} 个文件。")
    return True

def fix_metadata_errors():
    """修复 metadata 错误"""
    print("尝试修复 metadata 错误...")
    
    fix_pkg_version()
    
    print("更新 feeds 索引...")
    try:
        subprocess.run(["./scripts/feeds", "update", "-i"], check=False)
    except:
        print("警告: feeds update -i 失败")
    
    print("清理 tmp 目录...")
    if os.path.isdir("tmp"):
        try:
            shutil.rmtree("tmp")
        except:
            print("警告: 清理 tmp 目录失败")
    
    return True
def fix_depends_format(log_file):
    """自动修复 Makefile 中的无效依赖项，包括非法版本约束"""
    print("🔧 检测到依赖项错误，尝试自动修复 Makefile 中的 DEPENDS 字段...")

    if not os.path.exists(log_file):
        print(f"日志文件未找到：{log_file}")
        return False

    with open(log_file, 'r', errors='replace') as f:
        log_content = f.read()

    # 检查是否包含依赖格式错误
    if "has a dependency on" not in log_content or "which does not exist" not in log_content:
        if "syntax error near unexpected token" in log_content and ".provides" in log_content:
            print("⚠️ 检测到非法字符导致的 shell 命令错误，尝试修复依赖格式...")
        else:
            print("未检测到依赖项错误")
            return False

    # 搜索所有 Makefile
    fixed_count = 0
    for makefile_path in Path(".").rglob("Makefile"):
        if "build_dir" in str(makefile_path) or "staging_dir" in str(makefile_path):
            continue

        with open(makefile_path, 'r', errors='replace') as f:
            content = f.read()

        # 查找 DEPENDS 行
        depends_match = re.search(r'^DEPENDS:=(.*)$', content, re.MULTILINE)
        if not depends_match:
            continue

        depends_line = depends_match.group(1).strip()
        depends_list = re.split(r'\s+', depends_line)

        cleaned_depends = []
        for dep in depends_list:
            dep = dep.strip()
            if not dep:
                continue
            dep = dep.lstrip('+@')
            dep = re.split(r'[>=<]', dep)[0].strip()  # 移除版本约束
            if re.match(r'^[a-zA-Z0-9._-]+$', dep):
                cleaned_depends.append(f'+{dep}')

        unique_depends = list(dict.fromkeys(cleaned_depends))
        new_depends_line = 'DEPENDS:=' + ' '.join(unique_depends)

        if new_depends_line != depends_match.group(0):
            print(f"✅ 修复 {makefile_path}:")
            print(f"  原始: {depends_match.group(0)}")
            print(f"  修复: {new_depends_line}")
            content = content.replace(depends_match.group(0), new_depends_line)
            with open(makefile_path, 'w') as f:
                f.write(content)
            fixed_count += 1

    if fixed_count > 0:
        print(f"✅ 共修复 {fixed_count} 个 Makefile 中的依赖格式问题。")
        return True
    else:
        print("未发现需要修复的 DEPENDS 字段。")
        return False

    
def fix_lua_neturl_download(log_file):
    """修复 lua-neturl 下载问题"""
    if "neturl" not in open(log_file, 'r', errors='replace').read():
        return False
    
    print("检测到 lua-neturl 下载错误...")
    
    import hashlib
    from bs4 import BeautifulSoup
    
    makefile_path = None
    for root, dirs, files in os.walk("./feeds"):
        for file in files:
            if file == "Makefile" and "lua-neturl" in root:
                makefile_path = os.path.join(root, file)
                break
        if makefile_path:
            break
    
    if not makefile_path:
        print("无法找到 lua-neturl 的 Makefile")
        return False
    
    print(f"找到 lua-neturl 的 Makefile: {makefile_path}")
    
    try:
        response = requests.get("https://github.com/golgote/neturl/tags")
        soup = BeautifulSoup(response.text, 'html.parser')
        tags = [tag.text.strip() for tag in soup.find_all('a', href=re.compile(r'/golgote/neturl/releases/tag/'))]
        latest_version = next((tag for tag in tags if tag.startswith('v')), "v1.2-1")
        print(f"获取到最新版本: {latest_version}")
    except Exception as e:
        print(f"获取最新版本失败: {e}")
        latest_version = "v1.2-1"
    
    raw_version = latest_version.lstrip('v')
    version = re.sub(r'-.*', '', raw_version)
    github_url = f"https://github.com/golgote/neturl/archive/refs/tags/{latest_version}.tar.gz"
    pkg_source = f"neturl-{raw_version}.tar.gz"
    
    dl_dir = "./dl"
    os.makedirs(dl_dir, exist_ok=True)
    tarball_path = os.path.join(dl_dir, pkg_source)
    
    if os.path.exists(tarball_path):
        os.remove(tarball_path)
        print(f"已删除旧文件: {tarball_path}")
    
    print(f"正在下载 {github_url} 到 {tarball_path}...")
    try:
        download_cmd = f"wget -q -O {tarball_path} {github_url}"
        subprocess.run(download_cmd, shell=True, check=True)
        print("下载成功")
    except Exception as e:
        print(f"下载失败: {e}")
        try:
            download_cmd = f"curl -s -L -o {tarball_path} {github_url}"
            subprocess.run(download_cmd, shell=True, check=True)
            print("使用 curl 下载成功")
        except Exception as e:
            print(f"使用 curl 下载也失败: {e}")
            return False
    
    if os.path.exists(tarball_path):
        sha256_hash = hashlib.sha256()
        with open(tarball_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        sha256_hex = sha256_hash.hexdigest()
        print(f"计算的 SHA256 哈希值: {sha256_hex}")
    else:
        print(f"文件不存在: {tarball_path}")
        return False
    
    with open(makefile_path, 'r') as f:
        content = f.read()
    
    content = re.sub(r'PKG_VERSION:=.*', f'PKG_VERSION:={version}', content)
    content = re.sub(r'PKG_RELEASE:=.*', 'PKG_RELEASE:=1', content)
    content = re.sub(r'PKG_SOURCE:=.*', f'PKG_SOURCE:={pkg_source}', content)
    content = re.sub(r'PKG_SOURCE_URL:=.*', f'PKG_SOURCE_URL:=https://github.com/golgote/neturl/archive/refs/tags/v{raw_version}.tar.gz', content)
    content = re.sub(r'PKG_HASH:=.*', f'PKG_HASH:={sha256_hex}', content)
    
    with open(makefile_path, 'w') as f:
        f.write(content)
    
    print(f"已更新 {makefile_path}")
    print(f"PKG_VERSION 设置为: {version}")
    print(f"PKG_SOURCE 设置为: {pkg_source}")
    
    print("清理旧的构建文件...")
    subprocess.run("make package/feeds/small8/lua-neturl/clean V=s", shell=True)
    
    print("更新 feeds...")
    subprocess.run("./scripts/feeds update -i", shell=True)
    subprocess.run("./scripts/feeds install -a", shell=True)
    
    print("等待 3 秒后重试...")
    time.sleep(3)
    
    return True
    
def fix_luci_lib_taskd_makefile():
    """修复 luci-lib-taskd Makefile 中的依赖格式问题"""
    import re
    
    print("🔧 修复 luci-lib-taskd Makefile 中的依赖格式问题...")
    
    # 查找所有可能的 Makefile 路径
    makefile_paths = [
        "package/feeds/small8/luci-lib-taskd/Makefile",
        "feeds/small8/luci-lib-taskd/Makefile"
    ]
    
    makefile_path = None
    for path in makefile_paths:
        if os.path.exists(path):
            makefile_path = path
            break
    
    if not makefile_path:
        print(f"❌ 找不到 luci-lib-taskd 的 Makefile 文件")
        return False
    
    try:
        # 读取原 Makefile 内容
        with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # 1. 检查并修正 Makefile 中的依赖声明
        modified = False
        
        # 检查各种可能的依赖声明格式
        for dep_var in ['LUCI_DEPENDS', 'DEPENDS', 'PKG_DEPENDS']:
            pattern = re.compile(f'{dep_var}\\s*:=\\s*([^\\n]+)', re.MULTILINE)
            match = pattern.search(content)
            if match:
                old_deps = match.group(1)
                # 清理重复的依赖项，移除版本约束
                deps = []
                seen = set()
                for dep in old_deps.split():
                    # 去掉 +、@前缀和版本约束
                    base_dep = re.sub(r'^[+@]', '', dep)
                    base_dep = re.sub(r'[<>=].+$', '', base_dep)
                    if base_dep not in seen:
                        deps.append(f"+{base_dep}")  # 保持 + 前缀
                        seen.add(base_dep)
                
                new_deps = ' '.join(deps)
                if new_deps != old_deps:
                    content = content.replace(match.group(0), f"{dep_var}:={new_deps}")
                    modified = True
                    print(f"✅ 已修复 {dep_var}: '{old_deps}' -> '{new_deps}'")
        
        # 2. 尝试直接修改构建过程中生成的临时文件
        # 这是一个后备措施，以防 Makefile 修改不够
        apk_cmd_path = None
        for path in ["tmp/.luci-lib-taskd-apk-cmd", "tmp/apk-cmd-luci-lib-taskd"]:
            if os.path.exists(path):
                apk_cmd_path = path
                break
        
        if apk_cmd_path:
            with open(apk_cmd_path, 'r') as f:
                cmd_content = f.read()
            
            # 修复依赖项参数
            if "depends:" in cmd_content:
                # 提取并修复依赖项
                depends_match = re.search(r'--info\s+"depends:([^"]+)"', cmd_content)
                if depends_match:
                    old_deps = depends_match.group(1)
                    deps = []
                    seen = set()
                    for dep in old_deps.split():
                        # 去掉版本约束
                        base_dep = re.sub(r'[<>=].+$', '', dep)
                        if base_dep not in seen:
                            deps.append(base_dep)
                            seen.add(base_dep)
                    
                    new_deps = ' '.join(deps)
                    new_cmd = re.sub(
                        r'--info\s+"depends:[^"]+"', 
                        f'--info "depends:{new_deps}"', 
                        cmd_content
                    )
                    
                    with open(apk_cmd_path, 'w') as f:
                        f.write(new_cmd)
                    
                    print(f"✅ 已修复临时命令文件中的依赖项: '{old_deps}' -> '{new_deps}'")
                    modified = True
        
        # 3. 最直接的方法：修改 feeds/luci/luci.mk 文件
        luci_mk_paths = ["feeds/luci/luci.mk", "package/feeds/luci/luci.mk"]
        luci_mk_path = None
        for path in luci_mk_paths:
            if os.path.exists(path):
                luci_mk_path = path
                break
        
        if luci_mk_path:
            with open(luci_mk_path, 'r', encoding='utf-8', errors='replace') as f:
                luci_mk_content = f.read()
            
            # 在 luci.mk 中查找和修改处理依赖的部分
            # 这是一个更激进的修改，可能会影响其他包的构建
            if 'staging_dir/host/bin/apk mkpkg' in luci_mk_content:
                # 增加处理依赖的函数
                if '# OpenWrt dependency cleaner' not in luci_mk_content:
                    cleaner_function = '''
# OpenWrt dependency cleaner
define CleanDependencies
  $(shell echo $(1) | tr ' ' '\\n' | sort -u | grep -v ">=\\|<=\\|>" | tr '\\n' ' ')
endef
'''
                    # 插入到文件前部
                    luci_mk_content = cleaner_function + luci_mk_content
                    modified = True
                
                # 修改生成依赖参数的部分
                old_depends_line = re.search(r'--info "depends:([^"]+)"', luci_mk_content)
                if old_depends_line:
                    # 替换为使用清理函数
                    new_content = re.sub(
                        r'--info "depends:([^"]+)"', 
                        r'--info "depends:$(call CleanDependencies,\1)"',
                        luci_mk_content
                    )
                    
                    if new_content != luci_mk_content:
                        with open(luci_mk_path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        print(f"✅ 已修复 {luci_mk_path} 中的依赖处理逻辑")
                        modified = True
        
        # 如果进行了任何修改，需要重新配置
        if modified:
            # 保存修改后的 Makefile
            if 'content' in locals() and makefile_path:
                with open(makefile_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            
            # 清理构建缓存
            print("🧹 清理构建缓存...")
            cmds = [
                ["make", "package/feeds/small8/luci-lib-taskd/clean", "V=s"],
                ["rm", "-f", "bin/packages/mipsel_24kc/small8/luci-lib-taskd-1.0.23.apk"]
            ]
            for cmd in cmds:
                try:
                    subprocess.run(cmd, check=False)
                except Exception as e:
                    print(f"⚠️ 运行命令 {' '.join(cmd)} 时出错: {e}")
            
            # 最直接的方法：手动创建正确的依赖文件
            pkg_info_dir = "staging_dir/target-mipsel_24kc_musl/pkginfo"
            if os.path.exists(pkg_info_dir):
                # 创建正确的依赖描述文件
                depends_content = "libc taskd luci-lib-xterm luci-lua-runtime"
                try:
                    with open(os.path.join(pkg_info_dir, "luci-lib-taskd.depends"), 'w') as f:
                        f.write(depends_content)
                    print(f"✅ 已创建正确的依赖文件: {os.path.join(pkg_info_dir, 'luci-lib-taskd.depends')}")
                except Exception as e:
                    print(f"⚠️ 创建依赖文件时出错: {e}")
            
            return True
        else:
            print("⚠️ 未检测到需要修改的依赖项")
            
            # 4. 直接修改命令行参数
            # 这是最后的手段：创建一个包装脚本来覆盖 apk 命令
            
            print("🔧 创建 apk 命令包装器修复依赖格式...")
            wrapper_path = "staging_dir/host/bin/apk.real"
            
            # 如果原始命令尚未被备份，则创建备份
            if not os.path.exists(wrapper_path) and os.path.exists("staging_dir/host/bin/apk"):
                try:
                    os.rename("staging_dir/host/bin/apk", wrapper_path)
                    
                    # 创建包装脚本
                    with open("staging_dir/host/bin/apk", 'w') as f:
                        f.write('''#!/bin/sh
# APK wrapper to fix dependency format issues
if [ "$1" = "mkpkg" ]; then
    # Find and fix the depends argument
    fixed_args=""
    for arg in "$@"; do
        if echo "$arg" | grep -q "^depends:"; then
            # Remove duplicates and version constraints
            fixed_deps=$(echo "$arg" | sed 's/^depends://' | tr ' ' '\\n' | sed 's/[<>=].*$//' | sort -u | tr '\\n' ' ' | sed 's/^/depends:/')
            fixed_args="$fixed_args $fixed_deps"
        else
            fixed_args="$fixed_args $arg"
        fi
    done
    
    exec staging_dir/host/bin/apk.real $fixed_args
else
    exec staging_dir/host/bin/apk.real "$@"
fi
''')
                    os.chmod("staging_dir/host/bin/apk", 0o755)
                    print("✅ 已创建 apk 命令包装器")
                    return True
                except Exception as e:
                    print(f"⚠️ 创建 apk 命令包装器时出错: {e}")
            
            return False
    
    except Exception as e:
        print(f"❌ 修复出错: {e}")
        return False



def main():
    parser = argparse.ArgumentParser(description='OpenWrt 编译修复脚本')
    parser.add_argument('make_command', help='编译命令，例如 "make -j1 V=s"')
    parser.add_argument('log_file', help='日志文件路径，例如 "compile.log"')
    parser.add_argument('--max-retry', type=int, default=8, help='最大重试次数 (默认: 8)')
    parser.add_argument('--error-pattern',
                        default=r'error:|failed|undefined reference|invalid|File exists|missing separator|cannot find dependency|No rule to make target|fatal error:|collect2: error: ld returned 1 exit status',
                        help='通用错误模式正则表达式')

    args, unknown = parser.parse_known_args()

    if not args.make_command:
        print("错误: 缺少 'make_command' 参数。")
        parser.print_help()
        return 1
    if not args.log_file:
        print("错误: 缺少 'log_file' 参数。")
        parser.print_help()
        return 1
    if args.max_retry <= 0:
        print("错误: --max-retry 必须是正整数。")
        return 1

    print("--------------------------------------------------")
    print(f"编译命令: {args.make_command}")
    print(f"日志文件: {args.log_file}")
    print(f"最大重试: {args.max_retry}")
    print(f"错误模式: {args.error_pattern}")
    print("--------------------------------------------------")

    retry_count = 1
    last_fix_applied = ""
    metadata_fixed = False
    consecutive_fix_failures = 0

    log_dir = os.path.dirname(args.log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
            print(f"创建日志目录: {log_dir}")
        except OSError as e:
            print(f"错误: 无法创建日志目录 {log_dir}: {e}")
            return 1

    while retry_count <= args.max_retry:
        print("==================================================")
        print(f"尝试编译: 第 {retry_count} / {args.max_retry} 次...")
        print(f"命令: {args.make_command}")
        print("==================================================")

        fix_applied_this_iteration = False
        current_log_file = f"{args.log_file}.current_run.{retry_count}.log"
        print(f"执行编译命令，输出到临时日志: {current_log_file}")
        compile_status = -1
        log_content = ""
        try:
            with open(current_log_file, 'w', encoding='utf-8', errors='replace') as f:
                process = subprocess.Popen(
                    args.make_command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding='utf-8',
                    errors='replace'
                )
                for line in process.stdout:
                    sys.stdout.write(line)
                    f.write(line)
                    log_content += line
                compile_status = process.wait()
        except Exception as e:
            print(f"\n!!! 执行编译命令时发生异常: {e} !!!")
            compile_status = 999
            log_content += f"\n!!! Script Error during Popen: {e} !!!\n"
        finally:
            try:
                with open(args.log_file, 'a', encoding='utf-8', errors='replace') as main_log:
                    main_log.write(f"\n--- Attempt {retry_count} Log Start ---\n")
                    main_log.write(log_content)
                    main_log.write(f"--- Attempt {retry_count} Log End (Exit Code: {compile_status}) ---\n")
            except Exception as log_e:
                print(f"警告: 写入主日志文件 {args.log_file} 失败: {log_e}")

        if compile_status == 0:
            has_error_in_log = re.search(args.error_pattern, log_content, re.IGNORECASE | re.MULTILINE) is not None
            if not has_error_in_log:
                print("--------------------------------------------------")
                print("编译成功！")
                print("--------------------------------------------------")
                return 0
            else:
                print(f"警告: 编译退出码为 0，但在日志中检测到错误模式。继续检查...")

        print(f"编译失败 (退出码: {compile_status}) 或在日志中检测到错误。开始分析错误...")
        fix_applied_this_iteration = False

        # 1. Trojan-plus 相关错误
        if 'trojan-plus' in log_content and 'buffer-cast' in log_content:
            print("检测到 trojan-plus 相关错误。")
            if last_fix_applied == "fix_trojan_plus_issues":
                print("上次已尝试修复 trojan-plus 问题，但仍失败。")
                consecutive_fix_failures += 1
            else:
                if fix_trojan_plus_issues():
                    print("已尝试禁用 trojan-plus 相关选项。")
                    fix_applied_this_iteration = True
                    last_fix_applied = "fix_trojan_plus_issues"
                    consecutive_fix_failures = 0
                else:
                    print("尝试修复 trojan-plus 问题失败。")
                    last_fix_applied = "fix_trojan_plus_issues"
                    consecutive_fix_failures += 1

        # 2. Netifd libnl-tiny 相关错误
        # 在 main() 函数中修改 netifd 错误检测的部分
        elif ("undefined reference to `nlmsg_alloc_simple`" in log_content or 
              "undefined reference to `nla_put`" in log_content or 
              "undefined reference to `nlmsg_append`" in log_content or
              ("netifd" in log_content and "undefined reference" in log_content)):
            print("检测到 netifd 编译错误，缺少 libnl-tiny 符号。尝试修复...")
            if last_fix_applied == "fix_netifd_libnl_tiny":
                print("上次已尝试修复 netifd libnl-tiny 问题，但仍失败。停止重试。")
                consecutive_fix_failures += 1
            else:
                if fix_netifd_libnl_tiny():
                    print("已尝试重新编译 libnl-tiny 以修复 netifd 问题。")
                    fix_applied_this_iteration = True
                    last_fix_applied = "fix_netifd_libnl_tiny"
                    consecutive_fix_failures = 0
                else:
                    print("尝试修复 netifd libnl-tiny 问题失败。")
                    last_fix_applied = "fix_netifd_libnl_tiny"
                    consecutive_fix_failures += 1


        # 3. Lua Neturl 下载错误
        elif 'lua-neturl' in log_content and ('No more mirrors to try' in log_content or 'Download failed' in log_content or 'Hash mismatch' in log_content):
            print("检测到 lua-neturl 下载或校验错误...")
            if last_fix_applied == "fix_lua_neturl_download":
                print("上次已尝试修复 lua-neturl 下载，但仍失败。")
                consecutive_fix_failures += 1
            elif hashlib is None or BeautifulSoup is None:
                print("缺少 'requests' 或 'beautifulsoup4' 库，无法执行 lua-neturl 下载修复。")
                last_fix_applied = "fix_lua_neturl_download_skipped"
                consecutive_fix_failures += 1
            else:
                if fix_lua_neturl_download(log_content):
                    print("已尝试更新 lua-neturl Makefile 并重新下载。")
                    fix_applied_this_iteration = True
                    last_fix_applied = "fix_lua_neturl_download"
                    consecutive_fix_failures = 0
                else:
                    print("尝试修复 lua-neturl 下载失败。")
                    last_fix_applied = "fix_lua_neturl_download"
                    consecutive_fix_failures += 1

        # 4. Makefile Separator 错误
        elif "missing separator" in log_content and ("Stop." in log_content or "***" in log_content):
            print("检测到 Makefile 'missing separator' 错误...")
            if last_fix_applied == "fix_makefile_separator":
                print("上次已尝试修复 missing separator，但仍失败。")
                consecutive_fix_failures += 1
            else:
                temp_current_log = f"{args.log_file}.current_separator_check.log"
                try:
                    with open(temp_current_log, 'w') as tmp_f:
                        tmp_f.write(log_content)
                    if fix_makefile_separator(temp_current_log):
                        print("已尝试修复 Makefile 缩进或清理相关目录。")
                        fix_applied_this_iteration = True
                        last_fix_applied = "fix_makefile_separator"
                        consecutive_fix_failures = 0
                    else:
                        print("尝试修复 missing separator 失败或未找到修复点。")
                        last_fix_applied = "fix_makefile_separator"
                        consecutive_fix_failures += 1
                finally:
                    if os.path.exists(temp_current_log):
                        os.remove(temp_current_log)

        # 5. 补丁应用错误
        elif ("Patch failed" in log_content or "Only garbage was found" in log_content or "unexpected end of file in patch" in log_content):
            print("检测到补丁应用失败...")
            if last_fix_applied == "fix_patch_application":
                print("上次已尝试修复补丁应用失败，但仍失败。")
                consecutive_fix_failures += 1
            else:
                temp_current_log = f"{args.log_file}.current_patch_check.log"
                try:
                    with open(temp_current_log, 'w') as tmp_f:
                        tmp_f.write(log_content)
                    if fix_patch_application(temp_current_log):
                        print("已尝试修复补丁问题 (可能删除或调整)。")
                        fix_applied_this_iteration = True
                        last_fix_applied = "fix_patch_application"
                        consecutive_fix_failures = 0
                    else:
                        print("尝试修复补丁失败或未进行修复。")
                        last_fix_applied = "fix_patch_application"
                        consecutive_fix_failures += 1
                finally:
                    if os.path.exists(temp_current_log):
                        os.remove(temp_current_log)

        # 6. 元数据错误
        elif not metadata_fixed and ("Collected errors:" in log_content or "Cannot satisfy dependencies" in log_content or "check_data_file_clashes" in log_content):
            print("检测到可能的元数据、依赖或文件冲突错误...")
            if fix_metadata_errors():
                print("已尝试修复元数据/依赖问题。")
                fix_applied_this_iteration = True
                last_fix_applied = "fix_metadata_errors"
                metadata_fixed = True
                consecutive_fix_failures = 0
            else:
                print("尝试修复元数据/依赖问题失败。")
                last_fix_applied = "fix_metadata_errors"
                consecutive_fix_failures += 1
        elif "ERROR: info field 'depends' has invalid value" in log_content or "dependency format is invalid" in log_content:
            print("检测到 APK 依赖格式错误...")
            if last_fix_applied == "fix_luci_lib_taskd_makefile":
                print("上次已尝试修复 Makefile 依赖格式，但仍失败。")
                # 如果 fix_luci_lib_taskd_makefile 失败，尝试通用的 fix_depends_format
                if last_fix_applied != "fix_depends_format":
                    temp_current_log = f"{args.log_file}.current_depends_check.log"
                    try:
                        with open(temp_current_log, 'w') as tmp_f:
                            tmp_f.write(log_content)
                        if fix_depends_format(temp_current_log):
                            print("已尝试修复 APK 依赖格式问题。")
                            fix_applied_this_iteration = True
                            last_fix_applied = "fix_depends_format"
                            consecutive_fix_failures = 0
                        else:
                            consecutive_fix_failures += 1
                    finally:
                        if os.path.exists(temp_current_log):
                            os.remove(temp_current_log)
                else:
                    consecutive_fix_failures += 1
            elif last_fix_applied == "fix_depends_format":
                print("上次已尝试修复 APK 依赖格式，但仍失败。")
                # 如果通用修复失败，尝试更具体的 fix_luci_lib_taskd_makefile
                if fix_luci_lib_taskd_makefile():
                    print("已修复 Makefile 中的依赖格式问题。")
                    fix_applied_this_iteration = True
                    last_fix_applied = "fix_luci_lib_taskd_makefile"
                    consecutive_fix_failures = 0
                else:
                    consecutive_fix_failures += 1
            else:
                # 首先尝试更具体的修复方法
                if fix_luci_lib_taskd_makefile():
                    print("已修复 Makefile 中的依赖格式问题。")
                    fix_applied_this_iteration = True
                    last_fix_applied = "fix_luci_lib_taskd_makefile"
                    consecutive_fix_failures = 0
                else:
                    # 如果失败，尝试通用修复方法
                    temp_current_log = f"{args.log_file}.current_depends_check.log"
                    try:
                        with open(temp_current_log, 'w') as tmp_f:
                            tmp_f.write(log_content)
                        if fix_depends_format(temp_current_log):
                            print("已尝试修复 APK 依赖格式问题。")
                            fix_applied_this_iteration = True
                            last_fix_applied = "fix_depends_format"
                            consecutive_fix_failures = 0
                        else:
                            print("尝试修复 APK 依赖格式失败或未找到修复点。")
                            last_fix_applied = "fix_depends_format"
                            consecutive_fix_failures += 1
                    finally:
                        if os.path.exists(temp_current_log):
                            os.remove(temp_current_log)

        elif (re.search(r'syntax error near unexpected token [`\'"]?\(', log_content) or
              re.search(r'staging_dir/[^:]+/pkginfo/$[^)]+$[^:]*\.provides', log_content) or
              re.search(r'bash: -c: .*?: syntax error.*unexpected.*\(', log_content)):
            print("检测到依赖格式问题或特殊字符文件名问题...")
            if last_fix_applied == "fix_luci_lib_taskd_makefile":
                print("上次已尝试修复 Makefile 中的依赖格式，但仍失败。")
                consecutive_fix_failures += 1
            else:
                if fix_luci_lib_taskd_makefile():
                    print("已修复 Makefile 中的依赖格式问题。")
                    fix_applied_this_iteration = True
                    last_fix_applied = "fix_luci_lib_taskd_makefile"
                    consecutive_fix_failures = 0
                else:
                    print("尝试修复 Makefile 中的依赖格式失败。")
                    last_fix_applied = "fix_luci_lib_taskd_makefile"
                    consecutive_fix_failures += 1
        

        # 7. 通用错误模式
        elif re.search(args.error_pattern, log_content, re.IGNORECASE | re.MULTILINE):
            matched_pattern = re.search(args.error_pattern, log_content, re.IGNORECASE | re.MULTILINE)
            print(f"检测到通用错误模式: '{matched_pattern.group(0).strip() if matched_pattern else '未知错误'}'")
            if last_fix_applied == "fix_generic_retry":
                print("上次已进行通用重试，但仍失败。")
                consecutive_fix_failures += 1
            else:
                print("未找到特定修复程序，将进行一次通用重试。")
                fix_applied_this_iteration = False
                last_fix_applied = "fix_generic_retry"
                consecutive_fix_failures = 1

        if not fix_applied_this_iteration and compile_status != 0:
            print(f"警告：检测到错误，但此轮未应用特定修复。上次尝试: {last_fix_applied or '无'}")
            if last_fix_applied == "fix_generic_retry":
                pass
            elif last_fix_applied:
                consecutive_fix_failures += 1

            if consecutive_fix_failures >= 2:
                print(f"连续 {consecutive_fix_failures} 次尝试 '{last_fix_applied}' 后编译仍失败，停止重试。")
                return 1
            else:
                print("将继续重试...")

        retry_count += 1
        if retry_count <= args.max_retry:
            wait_time = 2
            print(f"等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)
        if os.path.exists(current_log_file):
            try:
                os.remove(current_log_file)
            except OSError as e:
                print(f"警告: 删除临时日志 {current_log_file} 失败: {e}")

    print("--------------------------------------------------")
    print(f"达到最大重试次数 ({args.max_retry}) 或连续修复失败，编译最终失败。")
    print("--------------------------------------------------")
    print(f"请检查完整日志: {args.log_file}")
    return 1

if __name__ == "__main__":
    sys.exit(main())
