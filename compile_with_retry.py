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

import traceback # Add this import at the top if not already present

def patch_trojan_cmake_skip_gsl_clone():
    """
    Patches trojan-plus CMakeLists.txt to skip GSL git clone
    if the directory seems to exist (populated by 'prepare').
    """
    print("尝试修补 trojan-plus CMakeLists.txt 以跳过 GSL 克隆...")
    try:
        version = get_trojan_plus_version()
        trojan_build_dir = find_trojan_plus_build_dir(version)
    except (FileNotFoundError, ValueError, IOError) as e:
        print(f"无法获取 trojan-plus 版本或构建目录: {e}")
        return False
    except Exception as e:
        print(f"查找 trojan-plus 目录时发生未知错误: {e}")
        return False

    if not trojan_build_dir:
        print("无法找到 trojan-plus 的构建目录，无法修补 CMakeLists.txt")
        return False

    cmake_lists_path = os.path.join(trojan_build_dir, "CMakeLists.txt")
    # Check for a file that indicates GSL is already present from 'prepare'
    gsl_check_file = os.path.join(trojan_build_dir, "external/GSL/include/gsl/gsl")

    if not os.path.exists(cmake_lists_path):
        print(f"错误: CMakeLists.txt 未找到于 {cmake_lists_path}")
        print("请确保 'prepare' 步骤已成功运行。")
        return False

    # Check if GSL seems present *before* patching
    if not os.path.exists(gsl_check_file):
         print(f"警告: GSL 检查文件 '{gsl_check_file}' 不存在。")
         print("这可能意味着 'prepare' 未能成功获取 GSL，或者路径错误。")
         print("仍然尝试修补 CMakeLists.txt，以防万一。")
         # Continue, maybe the check path is slightly wrong but clone needs skipping

    backup_path = f"{cmake_lists_path}.bak.gslfix.{int(time.time())}"
    modified = False
    lines = [] # Initialize lines

    try:
        print(f"正在读取: {cmake_lists_path}")
        with open(cmake_lists_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        new_lines = []
        # --- Find the GSL clone/fetch logic ---
        # Option 1: Look for execute_process git clone
        git_clone_pattern = re.compile(r'execute_process\s*\(.*COMMAND\s+\${GIT_EXECUTABLE}\s+clone\s+.*Microsoft/GSL', re.IGNORECASE)
        # Option 2: Look for FetchContent
        fetch_content_pattern = re.compile(r'FetchContent_Declare\s*\(\s*GSL', re.IGNORECASE) # Assuming name is GSL
        populate_content_pattern = re.compile(r'FetchContent_MakeAvailable\s*\(\s*GSL', re.IGNORECASE)
        # Option 3: Look for ExternalProject_Add
        external_project_pattern = re.compile(r'ExternalProject_Add\s*\(\s*GSL', re.IGNORECASE) # Assuming name is GSL

        block_start = -1
        block_end = -1
        patch_type = None

        for i, line in enumerate(lines):
            if git_clone_pattern.search(line):
                # Simplest case: assume the execute_process is the block
                block_start = i
                block_end = i # Assume single line for now
                patch_type = "execute_process"
                print(f"在第 {i+1} 行找到 execute_process GSL clone")
                break
            elif fetch_content_pattern.search(line):
                 # FetchContent usually involves Declare and MakeAvailable/Populate
                 block_start = i
                 patch_type = "FetchContent"
                 # Find the corresponding MakeAvailable/Populate
                 for j in range(i + 1, len(lines)):
                      if populate_content_pattern.search(lines[j]):
                           block_end = j
                           break
                 if block_end == -1: block_end = i # Fallback if MakeAvailable not found nearby
                 print(f"在第 {i+1} 行找到 FetchContent_Declare(GSL)")
                 if block_end != i: print(f"  (对应 MakeAvailable 在第 {block_end+1} 行)")
                 break
            elif external_project_pattern.search(line):
                 # ExternalProject_Add can be multi-line
                 block_start = i
                 patch_type = "ExternalProject"
                 # Find the closing parenthesis ')' for the command
                 paren_level = 0
                 for j in range(i, len(lines)):
                      paren_level += lines[j].count('(')
                      paren_level -= lines[j].count(')')
                      if paren_level <= 0 and lines[j].strip().endswith(')'): # Heuristic end
                           block_end = j
                           break
                 if block_end == -1: block_end = i # Fallback
                 print(f"在第 {i+1} 行找到 ExternalProject_Add(GSL)")
                 if block_end != i: print(f"  (块结束于第 {block_end+1} 行)")
                 break

        if block_start != -1 and block_end != -1:
            # Check if already guarded (simple check)
            already_guarded = False
            if block_start > 0:
                 prev_line = lines[block_start-1].strip()
                 # Check for common guard patterns
                 if prev_line.startswith('if') and ('EXISTS' in prev_line or 'DEFINED' in prev_line) and ('GSL' in prev_line or 'external/GSL' in prev_line):
                      already_guarded = True
                      print("检测到可能已存在的 GSL 检查，跳过修补。")

            if not already_guarded:
                print(f"将在第 {block_start + 1} 行前插入 GSL 存在性检查...")
                # Use CMAKE_CURRENT_SOURCE_DIR which points to the source dir being processed by CMake
                # Check for the include file which should exist after prepare
                check_condition = 'if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/external/GSL/include/gsl/gsl")'

                # Create backup before modifying lines list
                shutil.copy2(cmake_lists_path, backup_path)
                print(f"已备份 {cmake_lists_path} 到 {backup_path}")

                # Insert the 'if' before the block starts
                lines.insert(block_start, f"{check_condition}\n")
                # Insert the 'endif' after the block ends (adjust index due to 'if' insertion)
                lines.insert(block_end + 2, "endif()\n") # +1 for block end, +1 for inserted 'if'

                modified = True
                print(f"已插入 GSL 存在性检查围绕行 {block_start+1} 到 {block_end+2} (原始行号)。") # +1 for 1-based index, +1 for inserted 'if'

        else:
            print("警告: 未能在 CMakeLists.txt 中找到 GSL 克隆/获取逻辑。无法应用补丁。")
            return False # Can't patch if we don't find the target

        if modified:
            print(f"正在写回修改后的 CMakeLists.txt: {cmake_lists_path}")
            with open(cmake_lists_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            # Clean CMake cache *again* after modifying CMakeLists.txt
            print("再次清理 CMake 缓存以确保补丁生效...")
            cmake_cache_file = os.path.join(trojan_build_dir, "CMakeCache.txt")
            cmake_files_dir = os.path.join(trojan_build_dir, "CMakeFiles")
            if os.path.exists(cmake_cache_file):
                try: os.remove(cmake_cache_file); print(f"已删除: {cmake_cache_file}")
                except OSError as e: print(f"警告: 删除失败 {cmake_cache_file}: {e}")
            if os.path.isdir(cmake_files_dir):
                try: shutil.rmtree(cmake_files_dir); print(f"已删除: {cmake_files_dir}")
                except OSError as e: print(f"警告: 删除失败 {cmake_files_dir}: {e}")
            return True
        else:
            # No modification needed or possible
            return False # Return False if no modification was made

    except Exception as e:
        print(f"修补 CMakeLists.txt 时发生错误: {e}")
        traceback.print_exc()
        # Attempt to restore backup if modification started
        if modified and os.path.exists(backup_path) and lines: # Check if lines were read
            try:
                print(f"尝试从备份 {backup_path} 恢复 CMakeLists.txt...")
                shutil.move(backup_path, cmake_lists_path)
                print(f"已恢复 CMakeLists.txt。")
            except Exception as restore_e:
                print(f"警告：恢复备份失败: {restore_e}")
        return False

def fix_gsl_std_at_error(log_file_content, attempt_count=0):
    """修复 trojan-plus 中 'at' is not a member of 'std' 错误"""
    print("检测到 'at' is not a member of 'std' 错误，尝试修复...")

    try:
        version = get_trojan_plus_version()
        trojan_build_dir = find_trojan_plus_build_dir(version)
    except (FileNotFoundError, ValueError, IOError) as e:
        print(f"无法获取 trojan-plus 版本或构建目录: {e}")
        return False
    except Exception as e:
        print(f"查找 trojan-plus 目录时发生未知错误: {e}")
        return False


    if not trojan_build_dir:
        print("无法找到 trojan-plus 的构建目录")
        return False

    config_cpp_path = os.path.join(trojan_build_dir, "src/core/config.cpp")

    if not os.path.exists(config_cpp_path):
        print(f"无法找到 config.cpp 文件: {config_cpp_path}")
        # Try running prepare step first if file is missing
        print("尝试运行 prepare 步骤以确保源文件存在...")
        prepare_cmd = ["make", "package/feeds/small8/trojan-plus/prepare", "V=s"]
        print(f"运行: {' '.join(prepare_cmd)}")
        result = subprocess.run(prepare_cmd, shell=False, capture_output=True, text=True)
        print(f"Prepare stdout:\n{result.stdout}")
        print(f"Prepare stderr:\n{result.stderr}")
        if result.returncode != 0 or not os.path.exists(config_cpp_path):
             print(f"运行 prepare 失败或 config.cpp 仍然不存在: {config_cpp_path}")
             return False
        else:
             print("Prepare 成功，重新检查 config.cpp")
             # Re-check existence after prepare
             if not os.path.exists(config_cpp_path):
                  print(f"Prepare 后 config.cpp 仍然不存在: {config_cpp_path}")
                  return False


    backup_path = f"{config_cpp_path}.bak.{int(time.time())}" # Add timestamp to backup
    try:
        shutil.copy2(config_cpp_path, backup_path)
        print(f"已备份 {config_cpp_path} 到 {backup_path}")
    except Exception as e:
        print(f"备份文件失败: {e}")
        return False

    try:
        with open(config_cpp_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        print(f"读取 config.cpp 失败: {e}")
        return False

    # --- Debugging: Print lines around the typical error location ---
    lines = content.splitlines()
    error_line_num = 647 # Approximate line number from original script
    print(f"--- 内容预览 {config_cpp_path} (行 {max(1, error_line_num-2)} - {min(len(lines), error_line_num+2)}) ---")
    for i in range(max(0, error_line_num - 3), min(len(lines), error_line_num + 2)):
         print(f"行 {i+1}: {lines[i].strip()}")
    print("--- 预览结束 ---")
    # --- End Debugging ---


    original_content = content
    # Regex: Match 'std::at', optional whitespace, '(', optional whitespace,
    # 'mdString', optional whitespace, ',', optional whitespace,
    # capture the index expression until the closing ')'.
    # Make the index capture non-greedy (.*?)
    content = re.sub(r'std::at\s*\(\s*mdString\s*,\s*(.*?)\s*\)', r'mdString[\1]', content)

    if content != original_content:
        print("已将 config.cpp 中的 std::at(mdString, index) 替换为 mdString[index]")
        try:
            with open(config_cpp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"已更新 {config_cpp_path}")

            # --- Debugging: Print lines after modification ---
            with open(config_cpp_path, 'r', encoding='utf-8', errors='replace') as f:
                 lines_after = f.read().splitlines()
            print(f"--- 修改后内容预览 {config_cpp_path} (行 {max(1, error_line_num-2)} - {min(len(lines_after), error_line_num+2)}) ---")
            for i in range(max(0, error_line_num - 3), min(len(lines_after), error_line_num + 2)):
                 print(f"行 {i+1}: {lines_after[i].strip()}")
            print("--- 预览结束 ---")
            # --- End Debugging ---

        except Exception as e:
            print(f"写入更新后的 config.cpp 失败: {e}")
            # Attempt to restore backup
            try:
                shutil.move(backup_path, config_cpp_path)
                print(f"已从备份 {backup_path} 恢复。")
            except Exception as restore_e:
                print(f"警告：恢复备份失败: {restore_e}")
            return False
    else:
        print("替换逻辑未触发，可能 std::at(mdString, ...) 模式未匹配到。")
        # If no replacement happened, no need to clean/rebuild unless forced
        return False # Indicate no fix was applied by *this* function this time

    # If modification was successful, clean the package to force rebuild
    # Only clean if a change was actually made
    print("清理 trojan-plus 以确保修改生效...")
    # --- Find correct make target path (similar logic as in fix_gsl_not_found) ---
    make_target_path_for_clean = None
    package_base = "trojan-plus"
    feed_name = "small8" # Adjust if needed
    package_dir_path_for_clean = f"package/feeds/{feed_name}/{package_base}" # Assuming feed_name and package_base are available or defined
    alt_package_dir_path_for_clean = f"package/network/services/{package_base}"
    if os.path.isdir(package_dir_path_for_clean):
         make_target_path_for_clean = package_dir_path_for_clean
    elif os.path.isdir(alt_package_dir_path_for_clean):
         make_target_path_for_clean = alt_package_dir_path_for_clean
    else:
         # Add fallback logic if needed
         print("警告: 无法确定清理命令的 make 目标路径，将尝试默认路径。")
         make_target_path_for_clean = f"package/feeds/{feed_name}/{package_base}" # Default guess

    if make_target_path_for_clean:
        clean_cmd = ["make", f"{make_target_path_for_clean}/clean", "V=s"]
        print(f"运行: {' '.join(clean_cmd)}")
        result = subprocess.run(clean_cmd, shell=False, capture_output=True, text=True)
        print(f"Clean stdout:\n{result.stdout[-500:]}")
        print(f"Clean stderr:\n{result.stderr}")
        if result.returncode != 0:
             print("警告: 清理 trojan-plus 可能失败，但仍继续尝试编译。")
    else:
        print("错误: 无法执行清理，因为未找到 make 目标路径。")

    return True

# Ensure patch_trojan_cmake_skip_gsl_clone is defined above this function

def fix_gsl_not_found(log_file_content):
    """修复 trojan-plus 编译时找不到 gsl/gsl 的问题 (更积极的修复 + CMake 补丁)"""
    print("检测到 'gsl/gsl: No such file or directory' 错误，尝试更积极的修复...")
    print("步骤: 1. 清理包 2. 运行 Prepare 3. 修补 CMakeLists 4. 清理 CMake 缓存")

    package_base = "trojan-plus"
    feed_name = "small8" # Adjust if needed
    make_target_path = None
    package_dir_path = f"package/feeds/{feed_name}/{package_base}"
    alt_package_dir_path = f"package/network/services/{package_base}"

    # --- Determine Make Target Path ---
    if os.path.isdir(package_dir_path):
         make_target_path = package_dir_path
         print(f"使用 make 目标路径: {make_target_path}")
    elif os.path.isdir(alt_package_dir_path):
         make_target_path = alt_package_dir_path
         print(f"使用备用 make 目标路径: {make_target_path}")
    else:
         makefile_found_in_feeds = os.path.exists(f"feeds/{feed_name}/{package_base}/Makefile")
         makefile_found_in_package = os.path.exists(f"package/feeds/{feed_name}/{package_base}/Makefile")
         if makefile_found_in_package:
              make_target_path = f"package/feeds/{feed_name}/{package_base}"
              print(f"根据 package/下的 Makefile 推断 make 目标路径: {make_target_path}")
         elif makefile_found_in_feeds:
              make_target_path = f"package/feeds/{feed_name}/{package_base}"
              print(f"根据 feeds/下的 Makefile 推断 make 目标路径（标准方式）: {make_target_path}")
         else:
              print(f"错误: 无法确定 '{package_base}' 的正确 make 目标路径。")
              return False

    # --- Step 1: Clean the package ---
    clean_cmd = ["make", f"{make_target_path}/clean", "V=s"]
    print(f"运行清理命令: {' '.join(clean_cmd)}")
    try:
        result_clean = subprocess.run(clean_cmd, shell=False, check=False, capture_output=True, text=True, timeout=60)
        print(f"Clean stdout (last 500 chars):\n{result_clean.stdout[-500:]}")
        print(f"Clean stderr:\n{result_clean.stderr}")
        if result_clean.returncode != 0:
            print(f"信息: 清理命令返回码 {result_clean.returncode}。")
    except subprocess.TimeoutExpired:
         print(f"警告: 清理命令超时。")
    except Exception as e:
        print(f"运行清理命令时发生错误: {e}")

    # --- Step 2: Run Prepare ---
    prepare_cmd = ["make", f"{make_target_path}/prepare", "V=s"]
    print(f"运行 Prepare 命令: {' '.join(prepare_cmd)}")
    try:
        result_prepare = subprocess.run(prepare_cmd, shell=False, check=True, capture_output=True, text=True, timeout=180)
        print("Prepare 命令成功完成。")
    except subprocess.CalledProcessError as e:
        print(f"错误: Prepare 命令 ('{' '.join(prepare_cmd)}') 失败 (返回码 {e.returncode})。")
        print(f"Stderr:\n{e.stderr}")
        print(f"Stdout:\n{e.stdout}")
        return False
    except subprocess.TimeoutExpired:
         print(f"错误: Prepare 命令 ('{' '.join(prepare_cmd)}') 超时。")
         return False
    except Exception as e:
        print(f"运行 Prepare 命令 ('{' '.join(prepare_cmd)}') 时发生未知错误: {e}")
        return False

    # --- Step 3: Patch CMakeLists.txt ---
    patch_successful = patch_trojan_cmake_skip_gsl_clone()
    if not patch_successful:
         print("警告: 修补 CMakeLists.txt 失败或未执行。编译可能仍会因 GSL 克隆失败。")
         # We still cleaned and prepared, so let's return True and hope for the best
         # The cache clean step below might still be useful

    # --- Step 4: Clean CMake Cache ---
    # Clean cache regardless of patch success, as prepare might have changed things
    # The patch function also cleans cache if it modifies the file.
    # Running it again here ensures it's cleaned even if patching wasn't needed/successful.
    print("清理 CMake 缓存...")
    try:
        version = get_trojan_plus_version()
        trojan_build_dir = find_trojan_plus_build_dir(version)
        if trojan_build_dir:
            cmake_cache_file = os.path.join(trojan_build_dir, "CMakeCache.txt")
            cmake_files_dir = os.path.join(trojan_build_dir, "CMakeFiles")
            if os.path.exists(cmake_cache_file):
                try: os.remove(cmake_cache_file); print(f"已删除: {cmake_cache_file}")
                except OSError as e: print(f"警告: 删除失败 {cmake_cache_file}: {e}")
            if os.path.isdir(cmake_files_dir):
                try: shutil.rmtree(cmake_files_dir); print(f"已删除: {cmake_files_dir}")
                except OSError as e: print(f"警告: 删除失败 {cmake_files_dir}: {e}")
        else:
             print("警告: 无法找到构建目录，无法清理 CMake 缓存。")
    except Exception as e:
        print(f"清理 CMake 缓存时发生错误: {e}")

    print("GSL 未找到问题的修复尝试完成。")
    return True # Indicate fix was attempted

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
    
    if "trojan-plus" in patch_file:
        print("检测到 trojan-plus 补丁失败，已在主逻辑中处理，直接返回。")
        return True
    elif "lua-neturl" in patch_file:
        print("检测到 lua-neturl 补丁失败，调用专用修复函数...")
        return fix_lua_neturl_directory()
    else:
        print("非 trojan-plus 或 lua-neturl 的补丁失败，跳过修复。")
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


def get_trojan_plus_version():
    """从 Makefile 获取 trojan-plus 版本"""
    # 尝试在多个可能的位置查找 Makefile
    possible_paths = [
        "feeds/small8/trojan-plus/Makefile",
        "package/feeds/small8/trojan-plus/Makefile"
    ]
    makefile_path = None
    for p in possible_paths:
        if os.path.exists(p):
            makefile_path = p
            break
    
    if not makefile_path:
         # 如果在 feeds 中找不到，尝试在 package/network/services 中查找 (虽然不太可能)
        alt_path = "package/network/services/trojan-plus/Makefile"
        if os.path.exists(alt_path):
            makefile_path = alt_path
        else:
             raise FileNotFoundError("无法在常见位置找到 trojan-plus 的 Makefile")

    print(f"找到 trojan-plus Makefile: {makefile_path}")
    with open(makefile_path, 'r') as f:
        content = f.read()
    version_match = re.search(r'PKG_VERSION\s*:=\s*([\d.]+)', content)
    if version_match:
        return version_match.group(1)
    else:
        raise ValueError(f"无法从 {makefile_path} 中提取 PKG_VERSION")

def find_trojan_plus_build_dir(version):
    """根据版本号动态查找 trojan-plus 的构建目录"""
    base_build_dir = "build_dir"
    pattern = f"*/trojan-plus-{version}" # 匹配 target-*/trojan-plus-VERSION

    try:
        # 使用 find 命令查找匹配的目录
        find_command = ["find", base_build_dir, "-type", "d", "-path", pattern, "-print", "-quit"]
        result = subprocess.run(find_command, capture_output=True, text=True, check=False)

        if result.returncode == 0 and result.stdout.strip():
            found_path = result.stdout.strip()
            print(f"动态找到 trojan-plus 构建目录: {found_path}")
            return found_path
        else:
            print(f"警告: 无法通过 find 命令找到模式 '{pattern}' 的目录。尝试备用方法。")
            # 备用方法：遍历 build_dir 下的 target-* 目录
            for target_dir in os.listdir(base_build_dir):
                if target_dir.startswith("target-"):
                    potential_path = os.path.join(base_build_dir, target_dir, f"trojan-plus-{version}")
                    if os.path.isdir(potential_path):
                        print(f"通过备用方法找到 trojan-plus 构建目录: {potential_path}")
                        return potential_path
            print(f"错误: 无法在 {base_build_dir} 下找到 trojan-plus-{version} 的构建目录。")
            return None

    except Exception as e:
        print(f"查找 trojan-plus 构建目录时出错: {e}")
        return None


def fix_trojan_plus_boost_error():
    """直接修改 trojan-plus 源代码以修复 buffer_cast 错误"""
    try:
        version = get_trojan_plus_version()
        print(f"获取到的 trojan-plus 版本: {version}")

        build_dir = find_trojan_plus_build_dir(version)
        if not build_dir:
            print("[错误] 无法确定 trojan-plus 的构建目录。")
            return False

        # 现在构建源文件路径
        source_files = [
            os.path.join(build_dir, "src/core/service.cpp"),
            os.path.join(build_dir, "src/core/utils.cpp")
        ]
        fix_applied = False

        for source_path in source_files:
            if not os.path.exists(source_path):
                print(f"[信息] 源码文件不存在，跳过: {source_path}")
                continue

            print(f"检查并修复文件: {source_path}")
            try:
                with open(source_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except Exception as e:
                print(f"[错误] 读取文件失败 {source_path}: {e}")
                continue

            original_content = content

            # 核心修复逻辑：替换 boost::asio::buffer_cast<TYPE>(EXPR) 为 static_cast<TYPE>((EXPR).data())
            # 正则表达式解释:
            # boost::asio::buffer_cast  - 匹配字面量
            # \s*<\s*                   - 匹配 '<' 前后的空格
            # ([^>]+)                   - 捕获组 1: 尖括号内的类型 (e.g., "char*", "const void*")
            # \s*>\s*                   - 匹配 '>' 前后的空格
            # \(                        - 匹配左括号 '('
            # \s*                       - 匹配括号内的前导空格
            # (                         - 开始捕获组 2: 括号内的表达式
            #   (?:                     - 非捕获组，用于处理嵌套括号
            #     [^()]+                - 匹配非括号字符
            #     |                     - 或
            #     \( (? R) \)           - 递归匹配平衡的括号对 (需要 regex 模块支持，Python re 不支持)
            #                           - 简化：使用非贪婪匹配 .*? 来捕获，直到最后一个 ')'
            #   )                       - 结束捕获组 2
            # .*?                       - 非贪婪匹配，捕获括号内的表达式内容
            # )                         - 结束捕获组 2 (简化版)
            # \s*                       - 匹配括号内的尾随空格
            # \)                        - 匹配右括号 ')'
            # 使用更健壮的括号匹配（虽然Python re不支持完全递归，但这能处理简单嵌套）
            # 我们需要匹配从第一个 '(' 到与之对应的最后一个 ')'
            # 尝试手动查找匹配的括号来确定表达式范围
            
            new_content_lines = []
            modified_in_file = False
            lines = content.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                match = re.search(r'boost::asio::buffer_cast\s*<([^>]+)>\s*\(', line)
                if match:
                    start_index = match.end() # '(' 之后的位置
                    type_str = match.group(1).strip()
                    
                    # 查找匹配的 ')'
                    paren_level = 1
                    expr_start_line = i
                    expr_start_col = start_index
                    expr_end_line = -1
                    expr_end_col = -1
                    
                    current_line_idx = i
                    current_col_idx = start_index
                    
                    found_end = False
                    while current_line_idx < len(lines):
                        current_line_content = lines[current_line_idx]
                        while current_col_idx < len(current_line_content):
                            char = current_line_content[current_col_idx]
                            if char == '(':
                                paren_level += 1
                            elif char == ')':
                                paren_level -= 1
                                if paren_level == 0:
                                    expr_end_line = current_line_idx
                                    expr_end_col = current_col_idx # ')' 的索引
                                    found_end = True
                                    break
                            current_col_idx += 1
                        
                        if found_end:
                            break
                        
                        # 移动到下一行
                        current_line_idx += 1
                        current_col_idx = 0 # 从下一行开头开始

                    if found_end:
                        # 提取表达式 EXPR
                        if expr_start_line == expr_end_line:
                            expr = lines[expr_start_line][expr_start_col:expr_end_col].strip()
                            # 构建替换后的行
                            prefix = line[:match.start()] # buffer_cast 之前的部分
                            suffix = line[expr_end_col + 1:] # 匹配的 ')' 之后的部分
                            replacement = f"static_cast<{type_str}>(({expr}).data())"
                            new_line = prefix + replacement + suffix
                            new_content_lines.append(new_line)
                            print(f"  - Line {i+1}: Replaced buffer_cast")
                            print(f"    Original segment: {match.group(0)}{expr})")
                            print(f"    New segment: {replacement}")
                            modified_in_file = True
                        else:
                            # 跨行匹配，处理比较复杂，暂时跳过并警告
                            print(f"  - Line {i+1}: WARNING - buffer_cast expression spans multiple lines. Skipping automated fix for this instance.")
                            new_content_lines.append(line) # 保留原始行
                    else:
                         # 找不到匹配的括号，可能格式有问题
                         print(f"  - Line {i+1}: WARNING - Could not find matching parenthesis for buffer_cast. Skipping.")
                         new_content_lines.append(line) # 保留原始行
                else:
                    new_content_lines.append(line) # 没有匹配，保留原始行
                i += 1
            
            new_content = "\n".join(new_content_lines)

            # --- 清理可能由 *先前* 错误脚本造成的 .data(.data()) ---
            # 这个清理应该在主要替换逻辑 *之后* 进行
            cleanup_count = new_content.count(".data(.data())")
            if cleanup_count > 0:
                print(f"  - Cleaning up {cleanup_count} instance(s) of '.data(.data())'")
                new_content = new_content.replace(".data(.data())", ".data()")
                modified_in_file = True
            # --- 清理结束 ---

            if modified_in_file:
                backup_path = source_path + ".bak"
                try:
                    shutil.copy2(source_path, backup_path)
                    print(f"[备份] 已备份原始文件到: {backup_path}")
                except Exception as e:
                    print(f"[警告] 备份文件失败 {source_path}: {e}")

                try:
                    with open(source_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"[完成] 已修改文件: {source_path}")
                    fix_applied = True
                except Exception as e:
                    print(f"[错误] 写入文件失败 {source_path}: {e}")
                    # 尝试恢复备份
                    if os.path.exists(backup_path):
                        try:
                            shutil.move(backup_path, source_path)
                            print(f"[恢复] 已从备份恢复文件: {source_path}")
                        except Exception as re:
                            print(f"[严重错误] 恢复备份失败 {backup_path}: {re}")
            else:
                print(f"[信息] 文件无需修改: {source_path}")

        return fix_applied

    except FileNotFoundError as e:
        print(f"[错误] {e}")
        return False
    except ValueError as e:
        print(f"[错误] {e}")
        return False
    except Exception as e:
        print(f"[异常] 修复 trojan-plus 出错: {e}")
        import traceback
        traceback.print_exc()
        return False

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

def extract_error_block(log_file):
    """提取错误块"""
    print(f"--- 最近 300 行日志 ({log_file}) ---")
    try:
        with open(log_file, 'r', errors='replace') as f:
            lines = f.readlines()
            for line in lines[-300:]:
                print(line.rstrip())
    except Exception as e:
        print(f"读取日志文件时出错: {e}")
    print("--- 日志结束 ---")

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

def main():
    parser = argparse.ArgumentParser(description='OpenWrt 编译修复脚本')
    parser.add_argument('make_command', help='编译命令，例如 "make -j1 V=s"')
    parser.add_argument('log_file', help='日志文件路径，例如 "compile.log"')
    # Make max_retry and error_pattern truly optional with defaults
    parser.add_argument('--max-retry', type=int, default=8, help='最大重试次数 (默认: 8)')
    parser.add_argument('--error-pattern',
                        default=r'error:|failed|undefined reference|invalid|File exists|missing separator|cannot find dependency|No rule to make target|fatal error:|collect2: error: ld returned 1 exit status', # Added fatal error and ld error
                        help='通用错误模式正则表达式')

    # Parse known args, allowing others potentially
    args, unknown = parser.parse_known_args()

    # --- Argument Validation ---
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
    # --- End Validation ---


    print("--------------------------------------------------")
    print(f"编译命令: {args.make_command}")
    print(f"日志文件: {args.log_file}")
    print(f"最大重试: {args.max_retry}")
    print(f"错误模式: {args.error_pattern}")
    print("--------------------------------------------------")

    retry_count = 1
    last_fix_applied = ""
    metadata_fixed = False # Use boolean
    consecutive_fix_failures = 0
    gsl_std_at_fix_attempts = 0 # Renamed counter
    trojan_boost_fix_needed = False # Renamed flag

    # --- Ensure log directory exists ---
    log_dir = os.path.dirname(args.log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
            print(f"创建日志目录: {log_dir}")
        except OSError as e:
            print(f"错误: 无法创建日志目录 {log_dir}: {e}")
            return 1
    # --- End log dir check ---


    while retry_count <= args.max_retry:
        print("==================================================")
        print(f"尝试编译: 第 {retry_count} / {args.max_retry} 次...")
        print(f"命令: {args.make_command}")
        print("==================================================")

        fix_applied_this_iteration = False # Use boolean
        # Use a temporary file for the output of the *current* run
        current_log_file = f"{args.log_file}.current_run.{retry_count}.log"

        # --- Pre-compilation Fixes (like trojan boost fix) ---
        if trojan_boost_fix_needed:
            print("检测到需要应用 trojan-plus buffer_cast 修复...")
            # Ensure prepare is run before modifying source
            package_path = "package/feeds/small8/trojan-plus" # Adjust if needed
            alt_package_path = "feeds/small8/trojan-plus"
            if not os.path.isdir(package_path) and os.path.isdir(alt_package_path):
                package_path = alt_package_path

            prepare_cmd = ["make", f"{package_path}/prepare", "V=s"]
            print(f"运行 prepare: {' '.join(prepare_cmd)}")
            prep_result = subprocess.run(prepare_cmd, shell=False, capture_output=True, text=True)
            print(f"Prepare stdout (last 500 chars):\n{prep_result.stdout[-500:]}")
            print(f"Prepare stderr:\n{prep_result.stderr}")

            if prep_result.returncode == 0:
                print("Prepare 成功，尝试应用 buffer_cast 修复...")
                if fix_trojan_plus_boost_error():
                    print("trojan-plus buffer_cast 源代码修改成功。")
                    fix_applied_this_iteration = True
                    trojan_boost_fix_needed = False # Reset flag after successful application
                    # Clean after successful source mod to ensure rebuild
                    clean_cmd = ["make", f"{package_path}/clean", "V=s"]
                    print(f"运行 clean: {' '.join(clean_cmd)}")
                    subprocess.run(clean_cmd, shell=False)
                else:
                    print("trojan-plus buffer_cast 源代码修改失败，跳过此次编译尝试。")
                    # Don't increment retry_count here, let the main loop handle it after compile fails again
                    # Or decide to abort if the fix itself fails critically
                    # For now, let it try compiling anyway, maybe the prepare fixed something else
                    trojan_boost_fix_needed = False # Avoid infinite loop if fix keeps failing
            else:
                print("错误: trojan-plus prepare 失败，无法应用 buffer_cast 修复。跳过修复。")
                trojan_boost_fix_needed = False # Avoid infinite loop

        # --- Run the actual compile command ---
        print(f"执行编译命令，输出到临时日志: {current_log_file}")
        compile_status = -1 # Default status
        log_content = ""    # Content of the current run
        try:
            with open(current_log_file, 'w', encoding='utf-8', errors='replace') as f:
                # Use Popen for real-time output streaming
                process = subprocess.Popen(
                    args.make_command,
                    shell=True, # Be cautious with shell=True if command is complex
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, # Redirect stderr to stdout
                    text=True,
                    bufsize=1, # Line buffered
                    encoding='utf-8',
                    errors='replace'
                )
                # Read and print/write line by line
                for line in process.stdout:
                    sys.stdout.write(line) # Show output in real-time
                    f.write(line)
                    log_content += line # Accumulate current run's log content
                compile_status = process.wait() # Get the final exit code
        except Exception as e:
             print(f"\n!!! 执行编译命令时发生异常: {e} !!!")
             compile_status = 999 # Indicate script-level failure
             log_content += f"\n!!! Script Error during Popen: {e} !!!\n"
        finally:
             # Append the current log to the main log file *after* analysis
             try:
                 with open(args.log_file, 'a', encoding='utf-8', errors='replace') as main_log:
                     main_log.write(f"\n--- Attempt {retry_count} Log Start ---\n")
                     main_log.write(log_content)
                     main_log.write(f"--- Attempt {retry_count} Log End (Exit Code: {compile_status}) ---\n")
             except Exception as log_e:
                 print(f"警告: 写入主日志文件 {args.log_file} 失败: {log_e}")
             # Optionally remove the temporary current log file
             # if os.path.exists(current_log_file):
             #     os.remove(current_log_file)


        # --- Analyze the result of the *current* run ---
        # Check exit code first
        if compile_status == 0:
            # Double-check log content for errors even if exit code is 0
            has_error_in_log = re.search(args.error_pattern, log_content, re.IGNORECASE | re.MULTILINE) is not None
            if not has_error_in_log:
                print("--------------------------------------------------")
                print("编译成功！")
                print("--------------------------------------------------")
                # Clean up temporary log if needed (optional)
                # if os.path.exists(current_log_file): os.remove(current_log_file)
                return 0 # Success
            else:
                 print(f"警告: 编译退出码为 0，但在日志中检测到错误模式。继续检查...")
                 # Fall through to error handling

        # --- If exit code != 0 or errors found in log ---
        print(f"编译失败 (退出码: {compile_status}) 或在日志中检测到错误。开始分析错误...")
        fix_applied_this_iteration = False # Reset for this analysis phase

        # --- Specific Error Checks (prioritize based on likelihood/impact) ---

        # 1. GSL Not Found Error (NEW)
        if "fatal error: gsl/gsl: No such file or directory" in log_content:
            print("检测到 GSL 头文件未找到错误。")
            if last_fix_applied == "fix_gsl_not_found":
                 print("上次已尝试修复 GSL 未找到问题，但仍失败。停止重试。")
                 consecutive_fix_failures += 1 # Increment here
                 # return 1 # Exit immediately
            else:
                if fix_gsl_not_found(log_content):
                    print("已尝试运行 prepare 修复 GSL 未找到问题。")
                    fix_applied_this_iteration = True
                    last_fix_applied = "fix_gsl_not_found"
                    consecutive_fix_failures = 0 # Reset counter on successful fix attempt
                else:
                    print("尝试修复 GSL 未找到问题失败。")
                    last_fix_applied = "fix_gsl_not_found" # Record the attempt
                    consecutive_fix_failures += 1

        # 2. Trojan Boost buffer_cast Error
        elif 'trojan-plus' in log_content and 'buffer_cast' in log_content and 'is not a member of' in log_content:
             # Check if we already tried the fix in the pre-compilation step
             if last_fix_applied != "fix_trojan_plus_boost_error_prepare": # Use a distinct name if needed
                 print("检测到 trojan-plus buffer_cast 编译错误。")
                 print("将在下次重试前尝试 prepare 和源代码修复...")
                 trojan_boost_fix_needed = True
                 # Mark that we *identified* the need, the fix happens *before* next loop
                 fix_applied_this_iteration = True # Consider identification as progress
                 last_fix_applied = "fix_trojan_plus_boost_error_prepare"
                 consecutive_fix_failures = 0
             else:
                  print("上次已尝试修复 buffer_cast，但编译仍失败。可能是修复无效或有其他问题。")
                  consecutive_fix_failures += 1

        # 3. GSL std::at Error
        elif "error: 'at' is not a member of 'std'" in log_content and 'trojan-plus' in log_content and 'config.cpp' in log_content:
            print("检测到 GSL std::at 编译错误。")
            if gsl_std_at_fix_attempts >= 2:
                 print("已尝试修复 std::at 错误 2 次，不再尝试。")
                 # return 1 # Exit
            elif last_fix_applied == "fix_gsl_std_at_error":
                 print("上次已尝试修复 std::at 错误，但仍失败。")
                 consecutive_fix_failures += 1
                 gsl_std_at_fix_attempts += 1 # Increment attempts even if consecutive
            else:
                if fix_gsl_std_at_error(log_content, gsl_std_at_fix_attempts):
                    print("已尝试修改源代码修复 std::at 错误。")
                    fix_applied_this_iteration = True
                    last_fix_applied = "fix_gsl_std_at_error"
                    consecutive_fix_failures = 0
                    gsl_std_at_fix_attempts += 1
                else:
                    print("尝试修复 std::at 错误失败。")
                    last_fix_applied = "fix_gsl_std_at_error"
                    consecutive_fix_failures += 1
                    gsl_std_at_fix_attempts += 1 # Increment even on failure

        # 4. Lua Neturl Download Error
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
                 if fix_lua_neturl_download(log_content): # Pass current log
                     print("已尝试更新 lua-neturl Makefile 并重新下载。")
                     fix_applied_this_iteration = True
                     last_fix_applied = "fix_lua_neturl_download"
                     consecutive_fix_failures = 0
                 else:
                     print("尝试修复 lua-neturl 下载失败。")
                     last_fix_applied = "fix_lua_neturl_download"
                     consecutive_fix_failures += 1

        # 5. Makefile Separator Error
        elif "missing separator" in log_content and ("Stop." in log_content or "***" in log_content):
             print("检测到 Makefile 'missing separator' 错误...")
             # This fix needs the *current* log content to find the file/line
             if last_fix_applied == "fix_makefile_separator":
                  print("上次已尝试修复 missing separator，但仍失败。")
                  consecutive_fix_failures += 1
             else:
                  # Create a temporary file with *only* current content for the fix function
                  temp_current_log = f"{args.log_file}.current_separator_check.log"
                  try:
                       with open(temp_current_log, 'w') as tmp_f:
                            tmp_f.write(log_content)
                       if fix_makefile_separator(temp_current_log): # Pass temp file path
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


        # 6. Patch Application Error
        elif ("Patch failed" in log_content or "Only garbage was found" in log_content or "unexpected end of file in patch" in log_content):
             print("检测到补丁应用失败...")
             if last_fix_applied == "fix_patch_application":
                 print("上次已尝试修复补丁应用失败，但仍失败。")
                 consecutive_fix_failures += 1
             else:
                 # Similar to separator, use current log content
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

        # 7. Metadata Errors (Check only once)
        elif not metadata_fixed and ("Collected errors:" in log_content or "Cannot satisfy dependencies" in log_content or "check_data_file_clashes" in log_content):
             print("检测到可能的元数据、依赖或文件冲突错误...")
             if fix_metadata_errors(): # This function cleans tmp, updates feeds etc.
                 print("已尝试修复元数据/依赖问题。")
                 fix_applied_this_iteration = True
                 last_fix_applied = "fix_metadata_errors"
                 metadata_fixed = True # Mark as fixed for this run
                 consecutive_fix_failures = 0
             else:
                 print("尝试修复元数据/依赖问题失败。")
                 last_fix_applied = "fix_metadata_errors"
                 consecutive_fix_failures += 1

        # 8. Generic Error Pattern Match (Fallback)
        elif re.search(args.error_pattern, log_content, re.IGNORECASE | re.MULTILINE):
            matched_pattern = re.search(args.error_pattern, log_content, re.IGNORECASE | re.MULTILINE)
            print(f"检测到通用错误模式: '{matched_pattern.group(0).strip() if matched_pattern else '未知错误'}'")
            if last_fix_applied == "fix_generic_retry":
                print("上次已进行通用重试，但仍失败。")
                consecutive_fix_failures += 1
            else:
                print("未找到特定修复程序，将进行一次通用重试。")
                # No specific fix applied here, just letting it retry
                fix_applied_this_iteration = False # Not really a fix
                last_fix_applied = "fix_generic_retry"
                consecutive_fix_failures = 1 # Start counting consecutive generic retries

        # --- Post-analysis checks ---
        if not fix_applied_this_iteration and compile_status != 0:
            print(f"警告：检测到错误，但此轮未应用特定修复。上次尝试: {last_fix_applied or '无'}")
            # If the last attempt was a generic retry and it failed again, increment failure count
            if last_fix_applied == "fix_generic_retry":
                 # Already incremented above
                 pass
            elif last_fix_applied: # If a specific fix was tried last time but didn't apply *this* time
                 consecutive_fix_failures += 1


            if consecutive_fix_failures >= 2:
                print(f"连续 {consecutive_fix_failures} 次尝试 '{last_fix_applied}' 后编译仍失败，停止重试。")
                extract_error_block(args.log_file) # Show recent history from main log
                return 1
            # elif retry_count >= args.max_retry: # Check moved to loop condition
            #     print("已达最大重试次数，停止。")
            #     extract_error_block(args.log_file)
            #     return 1
            else:
                 print("将继续重试...")


        # --- Prepare for next iteration ---
        retry_count += 1
        if retry_count <= args.max_retry:
             wait_time = 2
             print(f"等待 {wait_time} 秒后重试...")
             time.sleep(wait_time)
        # Clean up the temporary log for the current run
        if os.path.exists(current_log_file):
            try:
                os.remove(current_log_file)
            except OSError as e:
                print(f"警告: 删除临时日志 {current_log_file} 失败: {e}")


    # --- Loop finished ---
    print("--------------------------------------------------")
    print(f"达到最大重试次数 ({args.max_retry}) 或连续修复失败，编译最终失败。")
    print("--------------------------------------------------")
    extract_error_block(args.log_file) # Extract from the main accumulated log
    print(f"请检查完整日志: {args.log_file}")
    return 1 # Indicate failure

if __name__ == "__main__":
    # Optional: Add setup for virtual environment or dependency checks here if needed
    sys.exit(main())
