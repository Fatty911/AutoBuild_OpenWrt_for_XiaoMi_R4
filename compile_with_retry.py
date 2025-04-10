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


def fix_makefile_separator(log_file):
    """修复 Makefile "missing separator" 错误"""
    print("检测到 'missing separator' 错误，尝试修复...")
    fix_attempted = 0
    
    # 从日志中提取错误行信息
    with open(log_file, 'r', errors='replace') as f:
        log_content = f.read()
    
    error_line_match = re.search(r'^([^:]+):([0-9]+): \*\*\* missing separator', log_content, re.MULTILINE)
    if not error_line_match:
        print("警告: 无法提取文件名和行号。")
        return False
    
    makefile_name_from_err = error_line_match.group(1)
    line_num = int(error_line_match.group(2))
    print(f"从错误行提取: 文件名部分='{makefile_name_from_err}', 行号='{line_num}'")
    
    # 查找最近的 "Entering directory" 以确定上下文目录
    error_line_info = error_line_match.group(0)
    context_dir = None
    
    # 反向搜索日志查找目录上下文
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
    
    # 获取相对路径
    makefile_path_rel = get_relative_path(full_makefile_path)
    if not makefile_path_rel and os.path.isfile(full_makefile_path):
        makefile_path_rel = full_makefile_path
        print(f"使用推测路径: {makefile_path_rel}")
    
    print(f"确定出错的 Makefile: {makefile_path_rel}, 行号: {line_num}")
    
    # 检查并修复文件（包括子文件）
    if os.path.isfile(makefile_path_rel) and line_num and str(line_num).isdigit():
        with open(makefile_path_rel, 'r', errors='replace') as f:
            makefile_lines = f.readlines()
        
        if line_num <= len(makefile_lines):
            line_content = makefile_lines[line_num-1].rstrip('\n')
            print(f"第 {line_num} 行内容: '{line_content}'")
            
            # 检查是否为 include 语句
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
                        
                        # 验证修复
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
            
            # 检查当前行是否需要修复缩进
            if re.match(r'^[ ]+', line_content) and not re.match(r'^\t', line_content):
                print(f"检测到第 {line_num} 行使用空格缩进，替换为 TAB...")
                shutil.copy2(makefile_path_rel, f"{makefile_path_rel}.bak")
                
                makefile_lines[line_num-1] = re.sub(r'^[ ]+', '\t', makefile_lines[line_num-1])
                with open(makefile_path_rel, 'w') as f:
                    f.writelines(makefile_lines)
                
                # 验证修复
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
    
    # 清理相关目录
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
    
    # 特殊处理 package/libs/toolchain
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


def fix_trojan_plus_boost_error():
    """修复 trojan-plus 中的 boost::asio::buffer_cast 错误"""
    print("修复 trojan-plus 中的 boost::asio::buffer_cast 错误...")
    found_path = ""
    trojan_pkg_dir = ""
    
    # 查找 trojan-plus 源码目录
    try:
        build_dirs = subprocess.check_output(
            ["find", "build_dir", "-type", "d", "-path", "*/trojan-plus-*/src/core", "-print", "-quit"],
            text=True
        ).strip()
        
        if build_dirs:
            trojan_src_dir = build_dirs.split("\n")[0]
            service_cpp = os.path.join(trojan_src_dir, "service.cpp")
            if os.path.isfile(service_cpp):
                found_path = service_cpp
                # 尝试确定包目录
                match = re.search(r'build_dir/[^/]*/([^/]*)/src/core', trojan_src_dir)
                if match:
                    trojan_pkg_dir = match.group(1)
                print(f"找到 trojan-plus 源码: {found_path} (包构建目录推测: {trojan_pkg_dir})")
            else:
                print(f"在找到的目录 {trojan_src_dir} 中未找到 service.cpp")
    except subprocess.SubprocessError:
        print("在 build_dir 中搜索 trojan-plus 源码时出错")
    
    # 如果未找到，尝试从日志猜测
    if not found_path:
        print("未能在 build_dir 中动态找到 trojan-plus 源码路径，尝试基于日志猜测路径...")
        try:
            with open(args.log_file, 'r', errors='replace') as f:
                log_content = f.read()
            
            target_build_dir_match = re.search(r'(/[^ ]+)?build_dir/target-[^/]+/trojan-plus-[^/]+', log_content)
            if target_build_dir_match:
                target_build_dir = target_build_dir_match.group(0)
                if os.path.isdir(target_build_dir):
                    service_cpp = os.path.join(target_build_dir, "src/core/service.cpp")
                    if os.path.isfile(service_cpp):
                        found_path = service_cpp
                        trojan_pkg_dir = os.path.basename(target_build_dir)
                        print(f"根据日志猜测找到 trojan-plus 源码: {found_path} (包构建目录推测: {trojan_pkg_dir})")
        except:
            pass
    
    if not found_path:
        print("无法定位 trojan-plus 的 service.cpp 文件，跳过修复。")
        return False
    
    print(f"尝试修复 {found_path} ...")
    
    # 备份原文件
    shutil.copy2(found_path, f"{found_path}.bak")
    
    # 读取文件内容
    with open(found_path, 'r', errors='replace') as f:
        content = f.read()
    
    # 应用修复
    modified_content = re.sub(
        r'boost::asio::buffer_cast<char\*>\((udp_read_buf\.prepare\([^)]*\))\)',
        r'static_cast<char*>(\1.data())',
        content
    )
    
    # 写入修改后的内容
    with open(found_path, 'w') as f:
        f.write(modified_content)
    
    # 验证修复
    with open(found_path, 'r') as f:
        if 'static_cast<char*>' in f.read():
            print(f"已成功修改 {found_path}")
            os.remove(f"{found_path}.bak")
            
            # 尝试找到包源目录并清理
            pkg_src_path = ""
            if trojan_pkg_dir:
                try:
                    pkg_name = re.sub(r'-[0-9].*', '', trojan_pkg_dir)
                    pkg_src_paths = subprocess.check_output(
                        ["find", "package", "feeds", "-name", pkg_name, "-type", "d", "-print", "-quit"],
                        text=True
                    ).strip()
                    
                    if pkg_src_paths:
                        pkg_src_path = pkg_src_paths.split("\n")[0]
                except:
                    pass
            
            if pkg_src_path and os.path.isdir(pkg_src_path):
                print(f"尝试清理包 {pkg_src_path} 以应用更改...")
                try:
                    subprocess.run(["make", f"{pkg_src_path}/clean", "DIRCLEAN=1", "V=s"], check=False)
                except:
                    print(f"警告: 清理包 {pkg_src_path} 失败。")
            else:
                print("警告: 未找到 trojan-plus 的源包目录，无法执行清理。可能需要手动清理。")
            
            return True
        else:
            print(f"尝试修改 {found_path} 失败，恢复备份文件。")
            shutil.move(f"{found_path}.bak", found_path)
            return False


def fix_directory_conflict(log_file):
    """修复目录冲突"""
    print("检测到目录冲突，尝试修复...")
    
    # 提取冲突的目录路径
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
    
    # 提取冲突的符号链接路径
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
    
    # 查找所有 Makefile 和 .mk 文件
    for makefile in Path('.').glob('**/*'):
        # 跳过 build_dir, staging_dir, tmp 目录
        if any(part in str(makefile.parent) for part in ['build_dir', 'staging_dir', 'tmp']):
            continue
        
        # 只处理 Makefile 和 .mk 文件
        if makefile.name != 'Makefile' and not makefile.name.endswith('.mk'):
            continue
        
        # 跳过不包含标准包定义的 Makefile
        try:
            with open(makefile, 'r', errors='replace') as f:
                header = ''.join(f.readline() for _ in range(30))
                if not re.search(r'^\s*(include \.\./\.\./(package|buildinfo)\.mk|include \$\(INCLUDE_DIR\)/package\.mk|include \$\(TOPDIR\)/rules\.mk)', header, re.MULTILINE):
                    continue
                
                # 重置文件指针并读取全部内容
                f.seek(0)
                original_content = f.read()
        except:
            continue
        
        # 提取 PKG_VERSION 和 PKG_RELEASE
        current_version_match = re.search(r'^PKG_VERSION:=(.*)$', original_content, re.MULTILINE)
        release_match = re.search(r'^PKG_RELEASE:=(.*)$', original_content, re.MULTILINE)
        
        current_version = current_version_match.group(1) if current_version_match else ""
        release = release_match.group(1) if release_match else ""
        
        modified_in_loop = 0
        makefile_changed = 0
        
        # 情况1: 版本字符串包含连字符后缀 (例如 1.2.3-beta1)
        version_suffix_match = re.match(r'^([0-9]+(\.[0-9]+)*)-([a-zA-Z0-9_.-]+)$', current_version)
        if version_suffix_match:
            new_version = version_suffix_match.group(1)
            suffix = version_suffix_match.group(3)
            
            # 尝试从后缀中提取数字，默认为1
            suffix_num_match = re.search(r'[0-9]*$', re.sub(r'[^0-9]', '', suffix))
            new_release = suffix_num_match.group(0) if suffix_num_match and suffix_num_match.group(0) else "1"
            
            if not new_release.isdigit():
                new_release = "1"
            
            if current_version != new_version or release != new_release:
                print(f"修改 {makefile}: PKG_VERSION: '{current_version}' -> '{new_version}', PKG_RELEASE: '{release}' -> '{new_release}'")
                
                # 准备新内容
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
                
                # 如果 PKG_RELEASE 不存在但 PKG_VERSION 存在，添加 PKG_RELEASE
                if version_printed and not release_found:
                    # 找到 PKG_VERSION 行的索引
                    version_idx = next(i for i, line in enumerate(new_content) if line.startswith('PKG_VERSION:='))
                    # 在 PKG_VERSION 后插入 PKG_RELEASE
                    new_content.insert(version_idx + 1, f"PKG_RELEASE:={new_release}")
                
                # 写入新内容
                with open(makefile, 'w') as f:
                    f.write('\n'.join(new_content))
                
                release = new_release  # 更新 release 变量用于下一次检查
                modified_in_loop = 1
                makefile_changed = 1
        
        # 情况2: PKG_RELEASE 存在但不是简单数字 (且未在情况1中修复)
        if modified_in_loop == 0 and release and not release.isdigit():
            suffix_num_match = re.search(r'[0-9]*$', re.sub(r'[^0-9]', '', release))
            new_release = suffix_num_match.group(0) if suffix_num_match and suffix_num_match.group(0) else "1"
            
            if not new_release.isdigit():
                new_release = "1"
            
            if release != new_release:
                print(f"修正 {makefile}: PKG_RELEASE: '{release}' -> '{new_release}'")
                
                # 替换 PKG_RELEASE 行
                new_content = re.sub(
                    r'^PKG_RELEASE:=.*$',
                    f'PKG_RELEASE:={new_release}',
                    original_content,
                    flags=re.MULTILINE
                )
                
                with open(makefile, 'w') as f:
                    f.write(new_content)
                
                makefile_changed = 1
        
        # 情况3: PKG_RELEASE 完全缺失但 PKG_VERSION 存在 (且未被情况1处理)
        elif (modified_in_loop == 0 and not release and 
              re.search(r'^PKG_VERSION:=', original_content, re.MULTILINE) and 
              not re.search(r'^PKG_RELEASE:=', original_content, re.MULTILINE)):
            
            print(f"添加 {makefile}: PKG_RELEASE:=1")
            
            # 在 PKG_VERSION 后添加 PKG_RELEASE
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
    
    # 1. 修复 PKG_VERSION/PKG_RELEASE 格式
    fix_pkg_version()
    
    # 2. 更新 feeds 索引
    print("更新 feeds 索引...")
    try:
        subprocess.run(["./scripts/feeds", "update", "-i"], check=False)
    except:
        print("警告: feeds update -i 失败")
    
    # 3. 清理 tmp 目录
    print("清理 tmp 目录...")
    if os.path.isdir("tmp"):
        try:
            shutil.rmtree("tmp")
        except:
            print("警告: 清理 tmp 目录失败")
    
    return True


def main():
    parser = argparse.ArgumentParser(description='OpenWrt 编译修复脚本')
    parser.add_argument('make_command', help='编译命令，例如 "make -j1 V=s"')
    parser.add_argument('log_file', help='日志文件路径，例如 "compile.log"')
    parser.add_argument('--max-retry', type=int, default=8, help='最大重试次数 (默认: 8)')
    parser.add_argument('--error-pattern', default='cc1: some warnings being treated as errors|error:|failed|undefined reference|invalid|File exists|missing separator|cannot find dependency|No rule to make target',
                        help='错误模式正则表达式')
    
    global args
    args = parser.parse_args()
    
    # 参数检查
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
    
    while retry_count <= args.max_retry:
        if retry_count > 1:
            print("--------------------------------------------------")
            print(f"尝试编译: {args.make_command} (第 {retry_count} / {args.max_retry} 次)...")
            print("--------------------------------------------------")
        
        fix_applied_this_iteration = 0
        
        # 执行编译命令，将输出同时写入临时日志文件
        print(f"执行: {args.make_command}")
        log_tmp = f"{args.log_file}.tmp"
        
        with open(log_tmp, 'w') as f:
            process = subprocess.Popen(
                args.make_command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # 实时输出并写入日志
            for line in process.stdout:
                sys.stdout.write(line)
                f.write(line)
                f.flush()
            
            compile_status = process.wait()
        
        # 检查编译是否成功
        with open(log_tmp, 'r', errors='replace') as f:
            log_content = f.read()
            has_error = re.search(args.error_pattern, log_content, re.MULTILINE) is not None
        
        if compile_status == 0 and not has_error:
            print("--------------------------------------------------")
            print("编译成功！")
            print("--------------------------------------------------")
            
            # 追加成功日志
            with open(args.log_file, 'a') as main_log:
                with open(log_tmp, 'r', errors='replace') as tmp_log:
                    main_log.write(tmp_log.read())
            
            os.remove(log_tmp)
            return 0
        else:
            print(f"编译失败 (退出码: {compile_status} 或在日志中检测到错误)，检查错误...")
            extract_error_block(log_tmp)
        
        # --- 错误检测和修复逻辑 (顺序很重要!) ---
        
        # 1. 特定错误检测和修复
        # Trojan-plus buffer_cast 错误
        if 'trojan-plus' in log_content and 'service.cpp' in log_content and 'buffer_cast' in log_content and 'boost::asio' in log_content:
            print("检测到 'trojan-plus boost::asio::buffer_cast' 错误...")
            if last_fix_applied == "fix_trojan_plus":
                print("上次已尝试修复 trojan-plus，但错误依旧，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            
            last_fix_applied = "fix_trojan_plus"
            if fix_trojan_plus_boost_error():
                fix_applied_this_iteration = 1
            else:
                print("修复 trojan-plus 失败，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
        
        # Makefile 缺少分隔符错误
        elif "missing separator" in log_content and "Stop." in log_content:
            print("检测到 Makefile 'missing separator' 错误...")
            if last_fix_applied == "fix_makefile_separator":
                print("上次已尝试修复 Makefile 分隔符，但错误依旧，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            
            last_fix_applied = "fix_makefile_separator"
            if fix_makefile_separator(log_tmp):
                fix_applied_this_iteration = 1
            else:
                print("修复 Makefile 分隔符失败，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
        
        # 目录冲突
        elif "mkdir: cannot create directory" in log_content and "File exists" in log_content:
            print("检测到目录冲突错误...")
            if last_fix_applied == "fix_directory_conflict":
                print("上次已尝试修复目录冲突，但错误依旧，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            
            last_fix_applied = "fix_directory_conflict"
            if fix_directory_conflict(log_tmp):
                fix_applied_this_iteration = 1
            else:
                print("修复目录冲突失败，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
        
        # 符号链接冲突
        elif "ln: failed to create symbolic link" in log_content and "File exists" in log_content:
            print("检测到符号链接冲突错误...")
            if last_fix_applied == "fix_symbolic_link_conflict":
                print("上次已尝试修复符号链接冲突，但错误依旧，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            
            last_fix_applied = "fix_symbolic_link_conflict"
            if fix_symbolic_link_conflict(log_tmp):
                fix_applied_this_iteration = 1
            else:
                print("修复符号链接冲突失败，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
        
        # 2. 元数据错误 (通常在其他修复失败后尝试)
        elif ("Collected errors:" in log_content or "ERROR: " in log_content) and metadata_fixed == 0:
            print("检测到可能的元数据错误...")
            last_fix_applied = "fix_metadata"
            if fix_metadata_errors():
                fix_applied_this_iteration = 1
                metadata_fixed = 1
            else:
                print("未应用元数据修复，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
        
        # 3. 通用错误模式检查 (最后尝试)
        elif has_error:
            matched_pattern = re.search(args.error_pattern, log_content, re.MULTILINE)
            if matched_pattern:
                print(f"检测到通用错误模式: {matched_pattern.group(0)}")
            else:
                print(f"检测到通用错误模式，但无法提取具体错误。")
            
            # 避免在通用错误上立即循环，如果没有应用修复
            if last_fix_applied == "fix_generic" and fix_applied_this_iteration == 0:
                print("上次已尝试通用修复但无效果，错误依旧，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            
            # 通用修复: 再次尝试元数据修复? 或者只是重试? 让我们只重试一次。
            print("未找到特定修复程序，将重试编译一次。")
            last_fix_applied = "fix_generic_retry"
            # 本次迭代没有应用修复，依赖循环计数器
        else:
            # 如果没有匹配已知错误模式，但编译失败
            print(f"未检测到已知或通用的错误模式，但编译失败 (退出码: {compile_status})。")
            print(f"请检查完整日志: {args.log_file}")
            with open(args.log_file, 'a') as main_log:
                with open(log_tmp, 'r', errors='replace') as tmp_log:
                    main_log.write(tmp_log.read())
            os.remove(log_tmp)
            return 1
        
        # --- 循环控制 ---
        if fix_applied_this_iteration == 0 and compile_status != 0:
            print(f"警告：检测到错误，但此轮未应用有效修复。上次尝试: {last_fix_applied or '无'}")
            # 即使没有应用修复也允许一次简单重试，可能是暂时性问题
            if last_fix_applied == "fix_generic_retry" or retry_count >= (args.max_retry - 1):
                print("停止重试，因为未应用有效修复或已达重试上限。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            else:
                print("将再重试一次，检查是否有其他可修复的错误出现。")
                last_fix_applied = "fix_generic_retry"  # 标记我们正在进行简单重试
        
        # 清理此次迭代的临时日志
        os.remove(log_tmp)
        
        retry_count += 1
        print("等待 3 秒后重试...")
        time.sleep(3)
    
    # --- 最终失败 ---
    print("--------------------------------------------------")
    print(f"达到最大重试次数 ({args.max_retry})，编译最终失败。")
    print("--------------------------------------------------")
    # 显示完整日志文件的最后 300 行
    extract_error_block(args.log_file)
    print(f"请检查完整日志: {args.log_file}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
