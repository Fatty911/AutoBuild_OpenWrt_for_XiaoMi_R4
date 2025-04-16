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

def find_trojan_build_dir():
    """动态查找 trojan-plus 的构建目录"""
    try:
        build_dirs = subprocess.check_output(
            ["find", "build_dir", "-type", "d", "-name", "trojan-plus-*", "-print", "-quit"],
            text=True,
            stderr=subprocess.DEVNULL
        ).strip()
        if build_dirs:
            return build_dirs
    except subprocess.CalledProcessError:
        pass
    return None

def fix_gsl_include_error(log_file, attempt_count=0):
    print("检测到 'at' is not a member of 'std' 错误，尝试修复...")
    
    trojan_build_dir = find_trojan_build_dir()
    if not trojan_build_dir:
        print("无法找到 trojan-plus 的构建目录")
        return False
    
    config_cpp_path = os.path.join(trojan_build_dir, "src/core/config.cpp")
    
    if not os.path.exists(config_cpp_path):
        print(f"无法找到 config.cpp 文件: {config_cpp_path}")
        return False
    
    backup_path = f"{config_cpp_path}.bak"
    shutil.copy2(config_cpp_path, backup_path)
    print(f"已备份 {config_cpp_path} 到 {backup_path}")
    
    with open(config_cpp_path, 'r') as f:
        content = f.read()
    
    lines = content.splitlines()
    if len(lines) >= 647:
        print("修改前第647行附近的内容：")
        for i in range(max(0, 646), min(len(lines), 650)):
            print(f"行 {i+1}: {lines[i].strip()}")
    
    original_content = content
    content = re.sub(r'std::at\s*\(\s*mdString\s*,\s*([^)]+)\)', r'mdString[\1]', content)
    if content != original_content:
        print("已将 config.cpp 中的 std::at 替换为直接索引")
    else:
        print("替换逻辑未触发，可能正则表达式未匹配到代码")
    
    with open(config_cpp_path, 'w') as f:
        f.write(content)
    print(f"已更新 {config_cpp_path}")
    
    with open(config_cpp_path, 'r') as f:
        lines = f.read().splitlines()
    if len(lines) >= 647:
        print("修改后第647行附近的内容：")
        for i in range(max(0, 646), min(len(lines), 650)):
            print(f"行 {i+1}: {lines[i].strip()}")
    
    if attempt_count < 2:
        print("清理 trojan-plus 构建目录...")
        subprocess.run(["make", "package/feeds/small8/trojan-plus/clean", "V=s"], shell=True)
        
        build_dir = os.path.dirname(trojan_build_dir)
        trojan_build_path = os.path.join(build_dir, "trojan-plus-10.0.3")
        if os.path.exists(trojan_build_path):
            shutil.rmtree(trojan_build_path)
            print(f"已删除构建目录 {trojan_build_path} 以强制重新提取源代码")
    
    return True

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
    makefile_path = "package/feeds/small8/trojan-plus/Makefile"
    with open(makefile_path, 'r') as f:
        content = f.read()
    version_match = re.search(r'PKG_VERSION:=([\d.]+)', content)
    if version_match:
        return version_match.group(1)
    else:
        raise ValueError("无法从 Makefile 中提取 PKG_VERSION")

def fix_trojan_plus_boost_error():
    """直接修改 trojan-plus 源代码以修复 buffer_cast 错误"""
    try:
        version = get_trojan_plus_version()
        source_files = [
            f"build_dir/target-mipsel_24kc_musl/trojan-plus-{version}/src/core/service.cpp",
            f"build_dir/target-mipsel_24kc_musl/trojan-plus-{version}/src/core/utils.cpp"
        ]
        fix_applied = False

        for source_path in source_files:
            if not os.path.exists(source_path):
                print(f"[错误] 找不到源码文件: {source_path}")
                continue

            with open(source_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            # 修复已损坏的代码：移除错误插入的 (.data())
            content = content.replace("config.get_udp_recv_buf(.data())", "config.get_udp_recv_buf()")
            content = content.replace("append_buf.data(.data())", "append_buf.data()")
            content = content.replace("target.prepare(n.data())", "target.prepare(n)")
            content = content.replace("target.prepare(char_length.data())", "target.prepare(char_length)")
            content = content.replace("target.data(.data())", "target.data()")

            # 替换 boost::asio::buffer_cast 为 static_cast 并添加 .data()
            pattern = r'(boost::asio::buffer_cast|static_cast)\s*<\s*([^>]+)\s*>\s*\(\s*([^)]+)\s*\)'
            def replace_buffer_cast(match):
                type_str = match.group(2).strip()
                expr = match.group(3).strip()
                # 如果已经有 static_cast<void*> 嵌套，去掉多余层级
                if expr.startswith("static_cast<void*>(") and expr.endswith(")"):
                    expr = expr[len("static_cast<void*>("):-1]
                return f"static_cast<{type_str}>({expr}.data())"
            new_content = re.sub(pattern, replace_buffer_cast, content)

            if new_content != content:
                backup_path = source_path + ".bak"
                shutil.copy2(source_path, backup_path)
                print(f"[备份] 已备份原始文件到: {backup_path}")
                
                with open(source_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"[完成] 已替换 {source_path} 中的 buffer_cast 为 static_cast")
                fix_applied = True
            else:
                print(f"[信息] 未找到需要替换的 buffer_cast 行在 {source_path}")

        # 如果替换成功，尝试清理缓存以确保编译从新文件开始
        if fix_applied:
            os.system("make package/feeds/small8/trojan-plus/clean V=s")
            print("[清理] 已清理 trojan-plus 缓存，确保从新文件开始编译")
            
        return fix_applied

    except Exception as e:
        print(f"[异常] 修复 trojan-plus 出错: {e}")
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
    parser.add_argument('max_retry', nargs='?', type=int, default=8, help='最大重试次数 (默认: 8)')
    parser.add_argument('error_pattern', nargs='?', 
                        default='cc1: some warnings being treated as errors|error:|failed|undefined reference|invalid|File exists|missing separator|cannot find dependency|No rule to make target',
                        help='错误模式正则表达式')
    
    global args
    args = parser.parse_args()
    
    if not args.make_command or not args.log_file:
        print("错误：缺少必要参数。")
        parser.print_help()
        return 1
    
    print("--------------------------------------------------")
    print(f"尝试编译: {args.make_command} (第 1 / {args.max_retry} 次)...")
    print("--------------------------------------------------")
    
    retry_count = 1
    last_fix_applied = ""
    metadata_fixed = 0
    consecutive_fix_failures = 0
    gsl_fix_attempts = 0
    trojan_fix_needed = False
    
    while retry_count <= args.max_retry:
        if retry_count > 1:
            print("--------------------------------------------------")
            print(f"尝试编译: {args.make_command} (第 {retry_count} / {args.max_retry} 次)...")
            print("--------------------------------------------------")
        
        fix_applied_this_iteration = 0
        log_tmp = f"{args.log_file}.tmp"
        
        # 如果需要修复 trojan-plus，则先运行 prepare 阶段并修改源代码
        if trojan_fix_needed:
            print("应用 trojan-plus buffer_cast 修复...")
            subprocess.run(["make", "package/feeds/small8/trojan-plus/prepare", "V=s"], shell=True)
            if fix_trojan_plus_boost_error():
                fix_applied_this_iteration = 1
                trojan_fix_needed = False
                print("源代码修改成功，继续编译...")
            else:
                print("源代码修改失败，跳过此次编译尝试。")
                retry_count += 1
                time.sleep(2)
                continue
        
        # 运行编译命令
        with open(log_tmp, 'w') as f:
            process = subprocess.Popen(
                args.make_command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for line in process.stdout:
                sys.stdout.write(line)
                f.write(line)
                f.flush()
            compile_status = process.wait()
        
        with open(log_tmp, 'r', errors='replace') as f:
            log_content = f.read()
            has_error = re.search(args.error_pattern, log_content, re.MULTILINE) is not None
        
        if compile_status == 0 and not has_error:
            print("--------------------------------------------------")
            print("编译成功！")
            print("--------------------------------------------------")
            with open(args.log_file, 'a') as main_log:
                with open(log_tmp, 'r', errors='replace') as tmp_log:
                    main_log.write(tmp_log.read())
            os.remove(log_tmp)
            return 0
        else:
            print(f"编译失败 (退出码: {compile_status} 或在日志中检测到错误)......")
            if "error: 'at' is not a member of 'std'" in log_content:
                print("检测到 'at' is not a member of 'std' 错误，调用修复函数...")
                if fix_gsl_include_error(args.log_file, retry_count):
                    print("修复完成，准备下一次编译尝试...")
                    fix_applied_this_iteration = 1
                else:
                    print("修复失败，请检查日志和文件路径")
            elif 'trojan-plus' in log_content and 'buffer_cast' in log_content:
                print("检测到 trojan-plus buffer_cast 错误，将在下次重试中直接修改源代码...")
                trojan_fix_needed = True
                fix_applied_this_iteration = 1
                last_fix_applied = "fix_trojan_plus_boost_error"
            elif "'gsl' has not been declared" in log_content or "gsl/gsl: No such file or directory" in log_content:
                if gsl_fix_attempts < 2:
                    if fix_gsl_include_error(args.log_file, gsl_fix_attempts):
                        fix_applied_this_iteration = 1
                        gsl_fix_attempts += 1
                        print(f"已应用 GSL 修复（第 {gsl_fix_attempts} 次），将重试编译...")
                    else:
                        print("GSL 修复失败，停止重试。")
                        break
                else:
                    print("GSL 修复已尝试 2 次仍未成功，停止重试。")
                    break
            elif 'lua-neturl' in log_content and 'No more mirrors to try - giving up' in log_content:
                print("检测到 lua-neturl 下载错误...")
                if last_fix_applied == "fix_lua_neturl":
                    print("上次已尝试修复 lua-neturl 下载错误，但问题未解决，停止重试。")
                    with open(args.log_file, 'a') as main_log:
                        with open(log_tmp, 'r', errors='replace') as tmp_log:
                            main_log.write(tmp_log.read())
                    os.remove(log_tmp)
                    return 1
                last_fix_applied = "fix_lua_neturl"
                if fix_lua_neturl_download(log_tmp):
                    fix_applied_this_iteration = 1
            elif "invalid" in log_content and "lua-neturl" in log_content:
                print("检测到 lua-neturl 版本号格式错误...")
                if last_fix_applied == "fix_lua_neturl":
                    print("上次已尝试修复 lua-neturl 版本号，但问题未解决，停止重试。")
                    with open(args.log_file, 'a') as main_log:
                        with open(log_tmp, 'r', errors='replace') as tmp_log:
                            main_log.write(tmp_log.read())
                    os.remove(log_tmp)
                    return 1
                last_fix_applied = "fix_lua_neturl"
                if fix_lua_neturl_download(log_tmp):
                    fix_applied_this_iteration = 1
            elif "missing separator" in log_content and "Stop." in log_content:
                if fix_makefile_separator(log_tmp):
                    fix_applied_this_iteration = 1
            elif "Patch failed" in log_content:
                print("检测到补丁应用失败...")
                if last_fix_applied == "fix_patch_application":
                    print("上次已尝试修复补丁应用失败，但问题未解决，停止重试。")
                    with open(args.log_file, 'a') as main_log:
                        with open(log_tmp, 'r', errors='replace') as tmp_log:
                            main_log.write(tmp_log.read())
                    os.remove(log_tmp)
                    return 1
                last_fix_applied = "fix_patch_application"
                if fix_patch_application(log_tmp):
                    fix_applied_this_iteration = 1
            elif ("Collected errors:" in log_content or "ERROR: " in log_content) and metadata_fixed == 0:
                print("检测到可能的元数据错误...")
                last_fix_applied = "fix_metadata"
                if fix_metadata_errors():
                    fix_applied_this_iteration = 1
                    metadata_fixed = 1
            elif has_error:
                matched_pattern = re.search(args.error_pattern, log_content, re.MULTILINE)
                print(f"检测到通用错误模式: {matched_pattern.group(0) if matched_pattern else '未知'}")
                if last_fix_applied == "fix_generic_retry":
                    consecutive_fix_failures += 1
                else:
                    consecutive_fix_failures = 1
                last_fix_applied = "fix_generic_retry"
                print("未找到特定修复程序，将重试编译一次。")
        
        if fix_applied_this_iteration == 0 and compile_status != 0:
            print(f"警告：检测到错误，但此轮未应用有效修复。上次尝试: {last_fix_applied or '无'}")
            if consecutive_fix_failures >= 2:
                print(f"连续 {consecutive_fix_failures} 次尝试 {last_fix_applied} 修复失败，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            elif retry_count >= args.max_retry - 1:
                print("停止重试，因为未应用有效修复或已达重试上限。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
        
        os.remove(log_tmp)
        retry_count += 1
        print("等待 2 秒后重试...")
        time.sleep(2)
    
    print("--------------------------------------------------")
    print(f"达到最大重试次数 ({args.max_retry})，编译最终失败。")
    print("--------------------------------------------------")
    extract_error_block(args.log_file)
    print(f"请检查完整日志: {args.log_file}")
    return 1

if __name__ == "__main__":
    sys.exit(main())
